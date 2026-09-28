"""Sohbet katmanı testleri (ağ çağrısı yapmaz; tüm servisler sahtedir).

Çalıştırma (telegram-bot/ klasöründen):
    .venv\\Scripts\\python -m unittest discover -s tests -v
"""
import asyncio
import html.parser
import os
import random
import sys
import tempfile
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("BOT_DATABASE_PATH", os.path.join(tempfile.mkdtemp(), "conv_test.db"))

from bot.services import responses as R  # noqa: E402
from bot.services.anti_spam import AntiSpam  # noqa: E402
from bot.services.asset_resolver import Asset, Resolution, normalize as asset_normalize  # noqa: E402
from bot.services.conversation_context import ConversationContextStore  # noqa: E402
from bot.services.conversation_engine import ConversationEngine  # noqa: E402
from bot.services.intents import Intent, classify  # noqa: E402
from bot.services.text_normalizer import normalize, fold, parse_number  # noqa: E402

BTC = Asset("bitcoin", "BTC", "Bitcoin", 1)
ETH = Asset("ethereum", "ETH", "Ethereum", 2)
SOL = Asset("solana", "SOL", "Solana", 7)
PI = Asset("pi-network", "PI", "Pi Network", 79)
ABC1 = Asset("abc-one", "ABC", "Alpha Beta Coin", 300)
ABC2 = Asset("abc-two", "ABC", "Another <Blockchain> & Co", 450)
OBSCURE = Asset("ok-token", "OK", "OK Token", 4000)

ALIASES = {"btc": BTC, "bitcoin": BTC, "eth": ETH, "ethereum": ETH, "sol": SOL, "solana": SOL,
           "pi": PI, "pi network": PI, "pi-network": PI, "ok": OBSCURE}
SNAPSHOTS = {
    "bitcoin": {"price": 84166.0, "change_24h": 1.25, "high_24h": 85000.0, "low_24h": 82000.0, "market_cap_rank": 1},
    "ethereum": {"price": 2717.5, "change_24h": -2.4, "high_24h": 2800.0, "low_24h": 2650.0, "market_cap_rank": 2},
    "solana": {"price": 120.7, "change_24h": 0.0, "high_24h": None, "low_24h": None, "market_cap_rank": 7},
    "pi-network": {"price": 0.0919, "change_24h": -0.5, "high_24h": 0.095, "low_24h": 0.09, "market_cap_rank": 79},
}


class FakeActions:
    """ConversationActions ile aynı arayüz. Çağrıları sayar; down=True iken servisler hata verir."""

    def __init__(self):
        self.calls = []
        self.down = False
        self.portfolio = {
            "items": [
                {"id": 1, "symbol": "PI", "name": "Pi Network", "provider_id": "pi-network", "amount": 1600,
                 "buy_price": 0.1, "investment": 160, "current_price": 0.0919, "current_value": 147.04,
                 "profit": -12.96, "profit_pct": -8.1},
                {"id": 2, "symbol": "BTC", "name": "Bitcoin", "provider_id": "bitcoin", "amount": 0.1,
                 "buy_price": 50000, "investment": 5000, "current_price": 84166, "current_value": 8416.6,
                 "profit": 3416.6, "profit_pct": 68.3},
            ],
            "total_investment": 5160, "total_current": 8563.64, "total_profit": 3403.64, "missing_prices": [],
        }
        self.alerts = [{"id": 1, "coin_symbol": "BTC", "alert_type": "above", "target_price": 100000,
                        "is_active": True, "provider_id": "bitcoin"}]

    def _call(self, name):
        self.calls.append(name)
        if self.down:
            raise RuntimeError("HTTP 500 secret-api-key-123 Traceback")

    def resolve_asset(self, query, user_id, offline=False):
        self.calls.append("resolve_offline" if offline else "resolve")
        key = asset_normalize(query)
        if key == "abc":
            return Resolution("ambiguous", query, candidates=[ABC1, ABC2])
        if key in ALIASES:
            return Resolution("resolved", query, asset=ALIASES[key], source="catalog")
        return Resolution("not_found", query)

    def get_snapshot(self, provider_id):
        self._call("snapshot")
        return SNAPSHOTS.get(provider_id, {})

    def get_portfolio(self, user_id):
        self._call("portfolio")
        return self.portfolio

    def get_portfolio_value_before(self, user_id, hours=20):
        self._call("portfolio_before")
        return 8000.0

    def get_alerts(self, user_id):
        self._call("alerts")
        return self.alerts

    def get_news(self, topic):
        self._call("news")
        return [{"title": "Bitcoin <yükseldi> & rekor", "url": "https://x.test/a?b=1&c=2", "source": "Test"}]

    def get_market(self):
        self._call("market")
        return {"bist": [("BIST 100", "", {"price": 12900.0, "change_pct": 0.1})],
                "fx": [("USD/TRY", "₺", {"price": 48.9, "change_pct": 0.02})],
                "commodity": [], "crypto": [("Bitcoin", "$", {"price": 84166.0, "change_pct": 1.2})]}


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


async def run_direct(func, *args):
    return func(*args)


class HTMLChecker(html.parser.HTMLParser):
    ALLOWED = {"b", "i", "a", "code", "pre", "u", "s"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.ALLOWED:
            self.errors.append(f"izin verilmeyen etiket <{tag}>")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.errors.append(f"eşleşmeyen </{tag}>")


def assert_valid_html(testcase, text):
    testcase.assertLessEqual(len(text), 4096)
    checker = HTMLChecker()
    checker.feed(text)
    checker.close()
    testcase.assertEqual(checker.errors, [], text)
    testcase.assertEqual(checker.stack, [], text)


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self.actions = FakeActions()
        self.clock = Clock()
        self.engine = ConversationEngine(self.actions, contexts=ConversationContextStore(now=self.clock),
                                         run_blocking=run_direct, rng=random.Random(1))

    def ask(self, text, user_id=1, chat_id=1, name="Deniz"):
        reply = asyncio.run(self.engine.handle(text, chat_id=chat_id, user_id=user_id, user_name=name))
        assert_valid_html(self, reply.text)
        for forbidden in ("Traceback", "HTTP 500", "secret-api-key"):
            self.assertNotIn(forbidden, reply.text)
        return reply


class NormalizationTests(unittest.TestCase):
    def test_turkish_case_variants_are_equal(self):
        self.assertEqual(fold("Nasılsın?"), fold("NASILSIN"))
        self.assertEqual(fold("nasılsın"), fold("nasilsin"))
        self.assertEqual(normalize("İSTANBUL"), "istanbul")
        self.assertEqual(normalize("IŞIK"), "ışık")

    def test_casual_spelling_and_abbreviations(self):
        self.assertEqual(fold("selaaaam"), "selam")
        self.assertEqual(fold("slm nbr"), "selam naber")
        self.assertEqual(fold("napıyosun"), "napiyorsun")
        self.assertEqual(fold("tşk"), "tesekkurler")

    def test_apostrophe_suffixes_and_numbers(self):
        self.assertEqual(normalize("BTC'nin fiyatı"), "btc fiyatı")
        self.assertEqual(normalize("100000'i geçerse"), "100000 geçerse")
        self.assertEqual(parse_number("100.000"), 100000)
        self.assertEqual(parse_number("0,5"), 0.5)
        self.assertEqual(parse_number("1.5"), 1.5)
        self.assertEqual(parse_number("100k"), 100000)
        self.assertIsNone(parse_number("abc"))


class IntentTests(unittest.TestCase):
    CASES = {
        Intent.GREETING: ["selam", "merhaba", "hey", "günaydın", "Selaaam!"],
        Intent.SMALL_TALK: ["naber", "nasılsın", "Nasılsın?", "NASILSIN", "Nasılsın ya", "napıyosun", "ne haber",
                            "iyi misin"],
        Intent.THANKS: ["teşekkürler", "sağol", "eyvallah", "tşk"],
        Intent.FAREWELL: ["görüşürüz", "iyi geceler", "hoşça kal"],
        Intent.CRYPTO_PRICE: ["btc kaç", "bitcoin ne kadar", "bitcoin kaç dolar", "pi network ne durumda",
                              "btc ne kadar"],
        Intent.CRYPTO_CHANGE: ["btc yükseldi mi", "eth düştü mü", "solana bugün nasıl",
                               "ethereum 24 saatte ne yaptı", "24 saatlik değişim?"],
        Intent.CRYPTO_INFO: ["bitcoin neden yükseldi"],
        Intent.CRYPTO_CONVERT: ["20 tane alsam ne kadar eder?"],
        Intent.PORTFOLIO_QUERY: ["portföyüm ne durumda", "portföyümü göster", "hangi coinlerim var",
                                 "toplam param ne kadar", "toplam değeri ne", "hangi coinlere sahibim"],
        Intent.PORTFOLIO_MODIFY: ["portföyümü sil", "hepsini kaldır"],
        Intent.ALERT_QUERY: ["alarmım var mı", "hangi fiyat alarmlarını kurdum", "btc için alarmım var mı"],
        Intent.ALERT_CREATE: ["btc 100000'i geçerse bana haber ver", "eth 2000'in altına düşerse haber ver"],
        Intent.NEWS_QUERY: ["son haberler", "kripto haberleri"],
        Intent.MARKET_STATUS: ["piyasalar nasıl", "dolar kaç"],
        Intent.REPORT_QUERY: ["raporum"],
        Intent.USER_ID_QUERY: ["id'm ne"],
        Intent.FUN_INTERACTION: ["şaka yap", "zar at", "yazı tura"],
        Intent.UNKNOWN: ["asdasdasdxyz"],
    }

    def test_intents(self):
        for expected, texts in self.CASES.items():
            for text in texts:
                with self.subTest(text=text):
                    self.assertEqual(classify(text).intent, expected)

    def test_capabilities(self):
        for text in ["neler yapabiliyorsun?", "ne işe yarıyorsun?", "hangi özelliklerin var?",
                     "bana yardımcı olabilir misin?", "bana ne yapabildiğini anlatır mısın?"]:
            with self.subTest(text=text):
                self.assertIn(classify(text).intent, (Intent.BOT_CAPABILITIES, Intent.HELP))

    def test_asset_extraction(self):
        self.assertEqual(classify("bitcoin ne kadar").asset_query, "bitcoin")
        self.assertEqual(classify("pi network kaç?").asset_query, "pi network")
        self.assertEqual(classify("BTC'nin fiyatı ne").asset_query, "btc")
        self.assertIsNone(classify("24 saatte?").asset_query)

    def test_alert_details(self):
        c = classify("btc 100000'i geçerse bana haber ver")
        self.assertEqual((c.asset_query, c.target, c.direction), ("btc", 100000, "above"))
        c = classify("eth 2000'in altına düşerse haber ver")
        self.assertEqual((c.asset_query, c.target, c.direction), ("eth", 2000, "below"))


class SmallTalkTests(EngineTestCase):
    def test_simple_messages_make_no_service_calls(self):
        for text in ["selam", "merhaba", "naber", "nasılsın", "günaydın", "teşekkürler", "sağol", "eyvallah",
                     "görüşürüz", "iyi geceler", "şaka yap"]:
            with self.subTest(text=text):
                reply = self.ask(text)
                self.assertTrue(reply.text)
                self.assertEqual(self.actions.calls, [], "basit sohbet servis çağırmamalı")

    def test_morning_greeting_is_appropriate(self):
        self.assertIn("Günaydın", self.ask("günaydın").text)

    def test_consecutive_replies_vary(self):
        first = self.ask("selam", name="")
        second = self.ask("selam", name="")
        self.assertNotEqual(first.text, second.text)

    def test_user_name_is_escaped(self):
        for _ in range(6):
            reply = self.ask("selam", name="<b>Hacker</b> & co")
            self.assertNotIn("<b>Hacker", reply.text)

    def test_capabilities_reply(self):
        reply = self.ask("neler yapabiliyorsun?")
        self.assertEqual(reply.text, R.CAPABILITIES_TEXT)
        self.assertEqual(self.actions.calls, [])

    def test_unknown_is_controlled(self):
        reply = self.ask("asdasdasdxyz")
        self.assertEqual(reply.text, R.UNKNOWN_TEXT)
        self.assertNotIn("snapshot", self.actions.calls)
        self.assertNotIn("resolve", self.actions.calls, "bilinmeyen kelime için ağ araması yapılmamalı")

    def test_user_id(self):
        self.assertIn("<code>42</code>", self.ask("id'm ne", user_id=42).text)


class CryptoTests(EngineTestCase):
    def test_prices(self):
        for text, name in [("btc kaç", "Bitcoin"), ("bitcoin ne kadar", "Bitcoin"), ("Bitcoin kaç dolar?", "Bitcoin"),
                           ("pi network ne durumda", "Pi Network"), ("ETH ne kadar", "Ethereum"),
                           ("Solana fiyatı", "Solana")]:
            with self.subTest(text=text):
                reply = self.ask(text, user_id=hash(text) % 10000)
                self.assertEqual(reply.intent, Intent.CRYPTO_PRICE.value)
                self.assertIn(name, reply.text)
                self.assertIn("$", reply.text)

    def test_24h_change(self):
        reply = self.ask("ethereum 24 saatte ne yaptı")
        self.assertEqual(reply.intent, Intent.CRYPTO_CHANGE.value)
        self.assertIn("Ethereum", reply.text)
        self.assertIn("düştü", reply.text)
        self.assertIn("2.40", reply.text)

    def test_why_question_does_not_invent_reasons(self):
        reply = self.ask("bitcoin neden yükseldi")
        self.assertEqual(reply.intent, Intent.CRYPTO_INFO.value)
        self.assertIn("kesin olarak bilemem", reply.text)

    def test_bare_popular_asset_name(self):
        self.assertEqual(self.ask("ethereum").intent, Intent.CRYPTO_PRICE.value)

    def test_bare_obscure_word_is_not_treated_as_coin(self):
        self.assertEqual(self.ask("ok").text, R.UNKNOWN_TEXT)

    def test_ambiguous_asset_offers_choices(self):
        reply = self.ask("abc kaç")
        self.assertEqual(reply.kind, "pick")
        self.assertEqual([c.provider_id for c in reply.candidates], ["abc-one", "abc-two"])
        self.assertEqual(reply.payload["intent"], Intent.CRYPTO_PRICE.value)

    def test_unknown_asset(self):
        reply = self.ask("<script>coin kaç")
        self.assertIn("bulamadım", reply.text)
        self.assertNotIn("<script>", reply.text)

    def test_api_failure_is_clean(self):
        self.actions.down = True
        reply = self.ask("btc kaç")
        self.assertEqual(reply.text, R.PRICE_UNAVAILABLE)

    def test_pick_callback_answer(self):
        text = asyncio.run(self.engine.answer_for_asset(Intent.CRYPTO_CHANGE.value, ABC2, None, chat_id=1, user_id=1))
        assert_valid_html(self, text)
        self.assertIn("&lt;Blockchain&gt;", text)


class FollowUpTests(EngineTestCase):
    def test_change_follow_up_inherits_asset(self):
        self.ask("btc kaç?")
        reply = self.ask("24 saatte?")
        self.assertEqual(reply.intent, Intent.CRYPTO_CHANGE.value)
        self.assertIn("Bitcoin", reply.text)

    def test_24h_change_question(self):
        self.ask("BTC kaç?")
        reply = self.ask("24 saatlik değişim?")
        self.assertIn("Bitcoin", reply.text)
        self.assertIn("yükseldi", reply.text)

    def test_other_asset_follow_up(self):
        self.ask("Bitcoin ne kadar?")
        reply = self.ask("Peki Ethereum?")
        self.assertEqual(reply.intent, Intent.CRYPTO_PRICE.value)
        self.assertIn("Ethereum", reply.text)

    def test_follow_up_keeps_question_type(self):
        self.ask("btc yükseldi mi")
        reply = self.ask("peki eth?")
        self.assertEqual(reply.intent, Intent.CRYPTO_CHANGE.value)
        self.assertIn("Ethereum", reply.text)

    def test_conversion_follow_up(self):
        self.ask("pi network kaç?")
        reply = self.ask("20 tane alsam ne kadar eder?")
        self.assertEqual(reply.intent, Intent.CRYPTO_CONVERT.value)
        self.assertIn("20 PI", reply.text)
        self.assertIn("$1.84", reply.text)

    def test_no_context_means_ask_not_guess(self):
        reply = self.ask("24 saatte?")
        self.assertEqual(reply.text, R.NEED_ASSET)
        self.assertNotIn("snapshot", self.actions.calls)

    def test_context_is_isolated_per_user_and_chat(self):
        self.ask("btc kaç?", user_id=1, chat_id=1)
        self.assertEqual(self.ask("24 saatte?", user_id=2, chat_id=1).text, R.NEED_ASSET)
        self.assertEqual(self.ask("24 saatte?", user_id=1, chat_id=-100).text, R.NEED_ASSET)
        self.assertIn("Bitcoin", self.ask("24 saatte?", user_id=1, chat_id=1).text)

    def test_context_expires(self):
        self.ask("btc kaç?")
        self.clock.t += 11 * 60
        self.assertEqual(self.ask("24 saatte?").text, R.NEED_ASSET)

    def test_topic_change_clears_crypto_follow_up(self):
        self.ask("btc kaç?")
        self.ask("teşekkürler")
        self.assertEqual(self.ask("24 saatte?").text, R.NEED_ASSET)


class PortfolioAlertNewsTests(EngineTestCase):
    def test_portfolio_queries(self):
        for text in ["portföyüm ne durumda", "hangi coinlerim var", "toplam değeri ne", "portföyümü göster"]:
            with self.subTest(text=text):
                reply = self.ask(text)
                self.assertEqual(reply.intent, Intent.PORTFOLIO_QUERY.value)
                self.assertIn("Pi Network", reply.text)
                self.assertIn("$8,563.64", reply.text)

    def test_portfolio_today_change(self):
        reply = self.ask("portföyüm bugün arttı mı")
        self.assertIn("%+7.05", reply.text)

    def test_empty_portfolio(self):
        self.actions.portfolio = {"items": [], "total_investment": 0, "total_current": 0, "total_profit": 0,
                                  "missing_prices": []}
        self.assertIn("boş", self.ask("portföyüm ne durumda").text)

    def test_destructive_request_is_not_executed(self):
        reply = self.ask("portföyümü sil")
        self.assertEqual(reply.text, R.DESTRUCTIVE_TEXT)
        self.assertEqual(self.actions.calls, [])

    def test_alert_queries(self):
        reply = self.ask("alarmım var mı")
        self.assertIn("1 aktif alarm", reply.text)
        self.assertIn("BTC", reply.text)
        self.assertIn("aktif alarmın yok", self.ask("eth için alarmım var mı").text)

    def test_alert_creation_requires_confirmation(self):
        reply = self.ask("btc 100000'i geçerse bana haber ver")
        self.assertEqual(reply.kind, "confirm")
        self.assertEqual(reply.payload["asset"].provider_id, "bitcoin")
        self.assertEqual((reply.payload["alert_type"], reply.payload["target"]), ("above", 100000))
        self.assertIn("kurayım mı", reply.text)

    def test_alert_direction_inferred_from_price(self):
        reply = self.ask("eth 5000 olunca haber ver")
        self.assertEqual(reply.kind, "confirm")
        self.assertEqual(reply.payload["alert_type"], "above")

    def test_news_and_market(self):
        news = self.ask("son haberler")
        self.assertIn("&lt;yükseldi&gt;", news.text)
        self.assertIn("&amp;c=2", news.text)
        market = self.ask("piyasalar nasıl")
        self.assertIn("USD/TRY", market.text)

    def test_services_down(self):
        self.actions.down = True
        for text in ["portföyüm ne durumda", "alarmım var mı", "son haberler", "piyasalar nasıl"]:
            with self.subTest(text=text):
                reply = self.ask(text)
                self.assertTrue(reply.text)


class AntiSpamTests(unittest.TestCase):
    def test_duplicate_and_rate_limits(self):
        clock = Clock()
        spam = AntiSpam(now=clock)
        self.assertTrue(spam.allow(1, 1, "selam", False)[0])
        self.assertEqual(spam.allow(1, 1, "selam", False), (False, "duplicate"))
        clock.t += 31
        self.assertTrue(spam.allow(1, 1, "selam", False)[0])
        for i in range(5):
            spam.allow(1, 1, f"m{i}", False)
        self.assertEqual(spam.allow(1, 1, "yeni", False), (False, "user_rate"))
        self.assertTrue(spam.allow(1, 2, "yeni", False)[0], "başka kullanıcı etkilenmemeli")

    def test_group_limit(self):
        clock = Clock()
        spam = AntiSpam(now=clock)
        for user in range(10):
            self.assertTrue(spam.allow(-5, user, "x", True)[0])
        self.assertEqual(spam.allow(-5, 99, "x", True), (False, "group_rate"))
        self.assertTrue(spam.allow(-6, 99, "x", True)[0])


# ----------------------------------------------------------- handler / routing

class RoutingTests(unittest.TestCase):
    """Gerçek python-telegram-bot yönlendirmesi ile: hangi handler hangi mesajı alıyor?"""

    @classmethod
    def setUpClass(cls):
        import telegram
        from telegram import Message, Chat, CallbackQuery, User
        from telegram.ext import Application, ExtBot
        from bot.handlers import setup_handlers
        import bot.handlers.messages as messages
        import bot.handlers.portfolio as portfolio
        import bot.handlers.alerts as alerts

        cls.telegram, cls.Message, cls.Chat, cls.User, cls.CallbackQuery = telegram, Message, Chat, User, CallbackQuery
        cls.sent = []
        cls.added = []
        cls.created_alerts = []

        def recorder(kind):
            async def record(self, *args, **kwargs):
                text = kwargs.get("text") or (args[0] if args else "")
                cls.sent.append((kind, text, kwargs.get("reply_markup")))
                return cls.fake_message(1, text)
            return record

        cls._originals = {
            (Message, "reply_text"): Message.reply_text, (Message, "edit_text"): Message.edit_text,
            (CallbackQuery, "edit_message_text"): CallbackQuery.edit_message_text,
            (CallbackQuery, "answer"): CallbackQuery.answer,
        }
        Message.reply_text = recorder("reply")
        Message.edit_text = recorder("edit")
        CallbackQuery.edit_message_text = recorder("cq_edit")

        async def answer(self, *a, **k):
            return True
        CallbackQuery.answer = answer

        cls.app = Application.builder().token("123:TEST").build()
        cls.app.bot._bot_user = User(999, "Bot", True, username="TestBot")
        setup_handlers(cls.app)
        cls.app._initialized = True
        cls.app.bot._initialized = True

        # Sohbet motoruna sahte servisler ver (ağ yok)
        cls.actions = FakeActions()
        messages.conversation_engine.actions = cls.actions
        messages.conversation_engine._run = run_direct
        cls.messages = messages

        async def fake_add(update, context):
            cls.added.append(update.message.text)
        cls._orig_add = portfolio._add_asset
        portfolio._add_asset = fake_add

        async def fake_create(user_id, asset, alert_type, target):
            cls.created_alerts.append((user_id, asset.provider_id, alert_type, target))
            return "✅ Alarm kuruldu!"
        cls._orig_create = alerts.create_price_alert
        alerts.create_price_alert = fake_create
        cls.alerts_module = alerts
        cls.portfolio_module = portfolio
        cls.counter = 1000

    @classmethod
    def tearDownClass(cls):
        for (klass, name), func in cls._originals.items():
            setattr(klass, name, func)
        cls.portfolio_module._add_asset = cls._orig_add
        cls.alerts_module.create_price_alert = cls._orig_create

    @classmethod
    def next_id(cls):
        cls.counter += 1
        return cls.counter

    @classmethod
    def fake_message(cls, chat_id, text, chat_type="private", user=None, reply_to=None, entities=None):
        chat = cls.Chat(chat_id, chat_type, title="Grup" if chat_type != "private" else None)
        msg = cls.Message(cls.next_id(), datetime.now(), chat, from_user=user or cls.User(999, "Bot", True),
                          text=text, reply_to_message=reply_to, entities=entities)
        msg.set_bot(cls.app.bot)
        return msg

    def setUp(self):
        self.sent.clear()
        self.added.clear()
        self.created_alerts.clear()
        self.messages.anti_spam.__init__()  # her test temiz spam sayaçlarıyla başlasın

    def send(self, text, user_id=None, chat_id=None, chat_type="private", reply_to_bot=False, is_bot=False):
        self.sent.clear()
        user_id = user_id or self.next_id()
        chat_id = chat_id or (user_id if chat_type == "private" else -100)
        user = self.User(user_id, "Deniz", is_bot)
        entities = None
        if text.startswith("/"):
            entities = [self.telegram.MessageEntity("bot_command", 0, len(text.split()[0]))]
        reply_to = self.fake_message(chat_id, "önceki", chat_type) if reply_to_bot else None
        msg = self.fake_message(chat_id, text, chat_type, user, reply_to, entities)
        update = self.telegram.Update(self.next_id(), message=msg)
        update.set_bot(self.app.bot)
        asyncio.run(self.app.process_update(update))
        for _, reply_text, _ in self.sent:
            assert_valid_html(self, reply_text)
        return list(self.sent)

    def press(self, data, user_id):
        user = self.User(user_id, "Deniz", False)
        query = self.CallbackQuery(str(self.next_id()), user, "inst", message=self.fake_message(user_id, "menu"),
                                   data=data)
        query.set_bot(self.app.bot)
        update = self.telegram.Update(self.next_id(), callback_query=query)
        update.set_bot(self.app.bot)
        self.sent.clear()
        asyncio.run(self.app.process_update(update))
        return list(self.sent)

    def test_private_chat_replies(self):
        out = self.send("selam")
        self.assertEqual(len(out), 1)

    def test_portfolio_syntax_is_not_stolen_by_chat(self):
        out = self.send("ekle BTC 0.1")
        self.assertEqual(self.added, ["ekle BTC 0.1"])
        self.assertEqual(out, [], "sohbet handler'ı ayrıca yanıt vermemeli")

    def test_commands_are_not_stolen_by_chat(self):
        out = self.send("/help")
        self.assertEqual(len(out), 1)
        self.assertIn("YARDIM MENÜSÜ", out[0][1])

    def test_group_ordinary_message_is_ignored(self):
        self.assertEqual(self.send("selam millet", chat_type="group"), [])
        self.assertEqual(self.send("ekle btc 1", chat_type="group"), [])
        self.assertEqual(self.added, [], "grupta bota yazılmayan EKLE mesajı işlenmemeli")

    def test_group_mention_and_reply(self):
        self.assertEqual(len(self.send("@TestBot selam", chat_type="supergroup")), 1)
        self.assertEqual(len(self.send("nasılsın", chat_type="group", reply_to_bot=True)), 1)
        self.send("@TestBot ekle btc 1", chat_type="group")
        self.assertEqual(self.added, ["@TestBot ekle btc 1"])

    def test_bot_messages_are_ignored(self):
        self.assertEqual(self.send("selam", is_bot=True), [])

    def test_duplicate_messages_are_throttled(self):
        user = self.next_id()
        self.assertEqual(len(self.send("selam", user_id=user)), 1)
        self.sent.clear()
        self.assertEqual(self.send("selam", user_id=user), [])

    def test_crypto_via_handler(self):
        out = self.send("btc kaç")
        self.assertEqual(len(out), 1)
        self.assertIn("Bitcoin", out[0][1])

    def test_ambiguous_asset_shows_picker_and_selection_answers(self):
        user = self.next_id()
        out = self.send("abc kaç", user_id=user)
        buttons = out[0][2].inline_keyboard
        self.assertTrue(buttons[0][0].callback_data.startswith("pick:"))
        answer = self.press(buttons[1][0].callback_data, user)
        self.assertIn("Another", answer[0][1])

    def test_alert_confirmation_flow(self):
        user = self.next_id()
        out = self.send("btc 100000'i geçerse bana haber ver", user_id=user)
        self.assertEqual(self.created_alerts, [], "onaydan önce alarm kurulmamalı")
        ok_button = out[0][2].inline_keyboard[0][0]
        self.press(ok_button.callback_data, user)
        self.assertEqual(self.created_alerts, [(user, "bitcoin", "above", 100000)])
        # Aynı buton ikinci kez çalışmaz
        self.press(ok_button.callback_data, user)
        self.assertEqual(len(self.created_alerts), 1)

    def test_alert_cancel(self):
        user = self.next_id()
        out = self.send("eth 2000'in altına düşerse haber ver", user_id=user)
        self.press(out[0][2].inline_keyboard[0][1].callback_data, user)
        self.assertEqual(self.created_alerts, [])

    def test_other_user_cannot_confirm(self):
        user = self.next_id()
        out = self.send("btc 100000'i geçerse bana haber ver", user_id=user)
        self.press(out[0][2].inline_keyboard[0][0].callback_data, self.next_id())
        self.assertEqual(self.created_alerts, [])


if __name__ == "__main__":
    unittest.main()
