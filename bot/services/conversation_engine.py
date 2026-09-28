# bot/services/conversation_engine.py
"""Sohbet motoru: mesaj -> niyet -> bağlam -> (salt-okunur) aksiyon -> yanıt nesnesi.

Telegram'dan bağımsızdır: Reply nesnesi döndürür, gönderme/buton işini handler yapar.
Veri değiştiren işlemleri kendisi yapmaz; alarm kurma gibi işlemler için 'confirm'
türünde yanıt döndürür ve işlem kullanıcı onayından sonra handler'da gerçekleşir.

Katmanlar (yedekleme sırası):
    1. Bilinen niyet (intents.classify)
    2. Bağlamsal yorum (takip soruları: "peki ethereum?", "24 saatte?")
    3. Kelime bir coin mi? (sadece yerel katalog, ağ çağrısı yok)
    4. İsteğe bağlı yedek sağlayıcı (ör. ileride bir LLM) — varsayılan: yok
    5. Yetenek/yardım yönlendirmesi
"""
import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from bot.services import responses as R
from bot.services.conversation_context import ConversationContextStore, ConversationState
from bot.services.intents import Intent, Classification, CRYPTO_INTENTS, classify
from bot.utils.helpers import esc

logger = logging.getLogger(__name__)

# Tek kelimelik belirsiz girdilerde ("ok", "sol") bir kelimeyi coin saymak için gereken en kötü sıralama
BARE_ASSET_MAX_RANK = 300

TOPIC_BY_INTENT = {
    **{i: "crypto" for i in CRYPTO_INTENTS},
    Intent.PORTFOLIO_QUERY: "portfolio", Intent.PORTFOLIO_MODIFY: "portfolio",
    Intent.ALERT_QUERY: "alerts", Intent.ALERT_CREATE: "alerts",
    Intent.NEWS_QUERY: "news", Intent.MARKET_STATUS: "market",
}
DICE_FACES = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}


@dataclass
class Reply:
    text: str = ""
    kind: str = "text"                   # 'text' | 'pick' | 'confirm'
    intent: str = ""
    candidates: list = field(default_factory=list)   # kind='pick'
    query: str = ""                                   # kind='pick'
    payload: dict = field(default_factory=dict)       # pick/confirm verisi


# İsteğe bağlı yedek sağlayıcı (ör. LLM): (düz metin, bağlam) -> düz metin veya None.
# Sadece UNKNOWN mesajlarda çağrılır, hiçbir araca/veriye erişimi yoktur, çıktısı escape edilir.
FallbackProvider = Callable[[str, ConversationState], Awaitable[Optional[str]]]


class ConversationEngine:
    def __init__(self, actions, contexts: Optional[ConversationContextStore] = None,
                 bank: Optional[R.ResponseBank] = None, fallback_provider: Optional[FallbackProvider] = None,
                 run_blocking=asyncio.to_thread, rng: Optional[random.Random] = None):
        self.actions = actions
        self.contexts = contexts if contexts is not None else ConversationContextStore()
        self.bank = bank or R.ResponseBank(rng)
        self.fallback_provider = fallback_provider
        self._run = run_blocking
        self._rng = rng or random.Random()

    # ------------------------------------------------------------------ giriş

    async def handle(self, text: str, *, chat_id: int, user_id: int, user_name: str = "") -> Reply:
        state = self.contexts.get(chat_id, user_id)
        cls = classify(text)
        try:
            reply = await self._dispatch(cls, state, chat_id=chat_id, user_id=user_id, user_name=user_name)
        except Exception:
            logger.exception("conversation failure intent=%s", cls.intent.value)
            reply = Reply(R.SERVICE_UNAVAILABLE, intent=cls.intent.value)
        state.history.append(("user", reply.intent or cls.intent.value))
        self.contexts.touch(state)
        return reply

    async def answer_for_asset(self, intent_value: str, asset, amount: Optional[float], *, chat_id: int,
                               user_id: int) -> str:
        """Kullanıcı belirsiz bir coin için seçim yaptıktan sonra sohbet yanıtı"""
        state = self.contexts.get(chat_id, user_id)
        intent = Intent(intent_value) if intent_value in Intent._value2member_map_ else Intent.CRYPTO_PRICE
        reply = await self._crypto_reply(intent, asset, amount, state)
        self.contexts.touch(state)
        return reply.text

    # ------------------------------------------------------------- yönlendirme

    async def _dispatch(self, cls: Classification, state: ConversationState, *, chat_id: int, user_id: int,
                        user_name: str) -> Reply:
        intent = cls.intent
        context_hit = False

        # Takip sorusu: "peki ethereum?" / "ya sol?" / sadece coin adı
        if intent == Intent.UNKNOWN and cls.asset_query:
            last = Intent(state.last_intent) if state.last_intent in Intent._value2member_map_ else None
            if last in CRYPTO_INTENTS and state.last_topic == "crypto":
                intent = Intent.CRYPTO_PRICE if last == Intent.CRYPTO_CONVERT and cls.amount is None else last
                context_hit = True
            elif await self._looks_like_asset(cls.asset_query, user_id):
                intent = Intent.CRYPTO_PRICE

        # "bitcoin nasıl gidiyor" -> selamlaşma değil, coin durumu
        if intent == Intent.SMALL_TALK and cls.tag == "how_are_you" and cls.asset_query \
                and await self._looks_like_asset(cls.asset_query, user_id):
            intent = Intent.CRYPTO_CHANGE

        # "20 tane alsam?" gibi sayı içeren ama coin içermeyen takip soruları
        if intent == Intent.UNKNOWN and cls.amount is not None and state.last_topic == "crypto" and state.last_asset:
            intent, context_hit = Intent.CRYPTO_CONVERT, True

        logger.info("conversation intent=%s tag=%s context_hit=%s", intent.value, cls.tag, context_hit)

        if intent in CRYPTO_INTENTS:
            return await self._handle_crypto(intent, cls, state, user_id)
        if intent == Intent.ALERT_CREATE:
            return await self._handle_alert_create(cls, state, user_id)

        handler = {
            Intent.GREETING: self._simple, Intent.SMALL_TALK: self._simple, Intent.THANKS: self._simple,
            Intent.FAREWELL: self._simple, Intent.FUN_INTERACTION: self._fun,
        }.get(intent)
        if handler:
            return self._remember(state, intent, handler(intent, cls, state, user_name))

        if intent in (Intent.HELP, Intent.BOT_CAPABILITIES):
            return self._remember(state, intent, Reply(R.CAPABILITIES_TEXT))
        if intent == Intent.USER_ID_QUERY:
            return self._remember(state, intent, Reply(f"🆔 Telegram ID'n: <code>{int(user_id)}</code>"))
        if intent == Intent.REPORT_QUERY:
            return self._remember(state, intent, Reply(R.REPORT_TEXT))
        if intent == Intent.PORTFOLIO_MODIFY:
            return self._remember(state, intent, Reply(R.DESTRUCTIVE_TEXT))
        if intent == Intent.PORTFOLIO_QUERY:
            return self._remember(state, intent, await self._portfolio(cls, user_id))
        if intent == Intent.ALERT_QUERY:
            return self._remember(state, intent, await self._alerts(cls, user_id))
        if intent == Intent.NEWS_QUERY:
            items = await self._safe(self.actions.get_news, cls.tag or "markets")
            return self._remember(state, intent, Reply(R.news_summary(items or [], cls.tag or "markets")))
        if intent == Intent.MARKET_STATUS:
            summary = await self._safe(self.actions.get_market)
            text = R.market_summary(summary) if summary else R.SERVICE_UNAVAILABLE
            return self._remember(state, intent, Reply(text))

        return self._remember(state, Intent.UNKNOWN, await self._unknown(cls, state))

    def _remember(self, state: ConversationState, intent: Intent, reply: Reply) -> Reply:
        reply.intent = reply.intent or intent.value
        state.last_intent = intent.value
        state.last_topic = TOPIC_BY_INTENT.get(intent, "chat")
        return reply

    async def _safe(self, func, *args):
        """Servis çağrısı; hata kullanıcıya sızmaz, sadece loglanır"""
        try:
            return await self._run(func, *args)
        except Exception:
            logger.exception("conversation action failed: %s", getattr(func, "__name__", func))
            return None

    # ----------------------------------------------------------------- sohbet

    def _simple(self, intent: Intent, cls: Classification, state, user_name: str) -> Reply:
        base = {Intent.GREETING: "greeting", Intent.SMALL_TALK: "small_talk", Intent.THANKS: "thanks",
                Intent.FAREWELL: "farewell"}[intent]
        key = f"{base}.{cls.tag}" if cls.tag else base
        # Adı sadece bazen kullan (her mesajda isim tekrarı yapay durur)
        name = user_name if self._rng.random() < 0.5 else ""
        return Reply(self.bank.pick(key, state, name))

    def _fun(self, intent: Intent, cls: Classification, state, user_name: str) -> Reply:
        if cls.tag == "dice":
            value = self._rng.randint(1, 6)
            return Reply(f"{DICE_FACES[value]} Zar: <b>{value}</b>")
        if cls.tag == "coin":
            return Reply(f"🪙 {self._rng.choice(['👑 <b>Yazı</b>', '🦅 <b>Tura</b>'])}")
        return Reply(self.bank.pick("joke", state))

    async def _unknown(self, cls: Classification, state) -> Reply:
        if self.fallback_provider is not None:
            try:
                answer = await asyncio.wait_for(self.fallback_provider(cls.asset_query or "", state), timeout=8)
                if answer:
                    return Reply(esc(answer))
            except Exception:
                logger.exception("fallback provider failed")
        return Reply(R.UNKNOWN_TEXT)

    # ------------------------------------------------------------------ kripto

    async def _looks_like_asset(self, query: str, user_id: int) -> bool:
        """Belirsiz kelimeyi sadece yerel veriyle yokla (ağ çağrısı yok). Popüler coinlerle sınırlı."""
        if len(query.split()) > 2:
            return False
        resolution = await self._safe(self.actions.resolve_asset, query, user_id, True)
        if not resolution or not resolution.ok:
            return False
        rank = resolution.asset.market_cap_rank
        return resolution.source == "alias" or (rank is not None and rank <= BARE_ASSET_MAX_RANK)

    async def _resolve(self, query: str, user_id: int, intent: Intent, amount=None):
        """(asset, None) veya (None, hata/seçim yanıtı)"""
        resolution = await self._safe(self.actions.resolve_asset, query, user_id, False)
        if resolution is None or resolution.status == "error":
            return None, Reply(R.PRICE_UNAVAILABLE)
        if resolution.ok:
            return resolution.asset, None
        if resolution.status == "ambiguous":
            header = (f"⚠️ \"{esc(query)}\" birden fazla coinle eşleşiyor. Hangisini kastettin?\n\n")
            return None, Reply(header, kind="pick", candidates=resolution.candidates, query=query,
                               payload={"intent": intent.value, "amount": amount})
        return None, Reply(R.asset_not_found(query))

    async def _handle_crypto(self, intent: Intent, cls: Classification, state, user_id: int) -> Reply:
        amount = cls.amount
        if cls.asset_query:
            asset, error = await self._resolve(cls.asset_query, user_id, intent, amount)
            if error:
                return self._remember(state, intent, error)
        elif state.last_asset is not None and state.last_topic == "crypto":
            asset = state.last_asset
            logger.info("conversation context hit asset=%s", asset.provider_id)
        else:
            # Hangi coin olduğu belli değil: tahmin etme, sor
            return self._remember(state, intent, Reply(R.NEED_ASSET))
        return await self._crypto_reply(intent, asset, amount, state)

    async def _crypto_reply(self, intent: Intent, asset, amount, state) -> Reply:
        snap = await self._safe(self.actions.get_snapshot, asset.provider_id)
        state.last_asset = asset
        if snap is None:
            return self._remember(state, intent, Reply(R.PRICE_UNAVAILABLE))
        if not snap:
            return self._remember(state, intent, Reply(R.no_market_data(asset)))
        if intent == Intent.CRYPTO_CHANGE:
            text = R.crypto_change(asset, snap)
        elif intent == Intent.CRYPTO_INFO:
            text = R.crypto_info(asset, snap)
        elif intent == Intent.CRYPTO_CONVERT and amount:
            text = R.crypto_convert(asset, snap, amount)
        else:
            intent = Intent.CRYPTO_PRICE
            text = R.crypto_price(asset, snap)
        return self._remember(state, intent, Reply(text))

    # ------------------------------------------------------ portföy / alarm

    async def _portfolio(self, cls: Classification, user_id: int) -> Reply:
        result = await self._safe(self.actions.get_portfolio, user_id)
        if result is None:
            return Reply(R.SERVICE_UNAVAILABLE)
        previous = None
        if cls.tag == "change":
            previous = await self._safe(self.actions.get_portfolio_value_before, user_id, 20)
        return Reply(R.portfolio_summary(result, previous, want_change=cls.tag == "change"))

    async def _alerts(self, cls: Classification, user_id: int) -> Reply:
        alerts = await self._safe(self.actions.get_alerts, user_id)
        if alerts is None:
            return Reply(R.SERVICE_UNAVAILABLE)
        asset = None
        if cls.asset_query:
            resolution = await self._safe(self.actions.resolve_asset, cls.asset_query, user_id, True)
            if resolution is not None and resolution.ok:
                asset = resolution.asset
        return Reply(R.alerts_summary(alerts, asset))

    async def _handle_alert_create(self, cls: Classification, state, user_id: int) -> Reply:
        intent = Intent.ALERT_CREATE
        if cls.target is None or cls.target <= 0:
            return self._remember(state, intent, Reply(
                "Hangi fiyatta haber vereyim? Örnek: <i>btc 100000'i geçerse haber ver</i>"))
        if cls.asset_query:
            asset, error = await self._resolve(cls.asset_query, user_id, Intent.CRYPTO_PRICE)
            if error:
                return self._remember(state, intent, error)
        elif state.last_asset is not None and state.last_topic == "crypto":
            asset = state.last_asset
        else:
            return self._remember(state, intent, Reply(R.NEED_ASSET))

        snap = await self._safe(self.actions.get_snapshot, asset.provider_id)
        current = snap.get("price") if snap else None
        direction = cls.direction
        if direction is None:
            if current is None:
                return self._remember(state, intent, Reply(
                    "Fiyat yükselince mi düşünce mi haber vereyim? Örnek: <i>btc 100000'i geçerse haber ver</i>"))
            direction = "above" if cls.target > current else "below"

        state.last_asset = asset
        text = R.alert_confirmation(asset, direction, cls.target, current)
        return self._remember(state, intent, Reply(text, kind="confirm", payload={
            "action": "create_alert", "asset": asset, "alert_type": direction, "target": cls.target}))
