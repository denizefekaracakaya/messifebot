# bot/services/responses.py
"""Sohbet yanıt metinleri ve bot kişiliği.

Ton: samimi, kısa, yardımsever, Türkçe; az emoji, zorlama şaka yok.
Tüm çıktılar Telegram HTML'idir; dinamik her değer esc() ile kaçırılır.
Basit yanıtlarda kontrollü çeşitlilik: aynı anahtar için bir önceki şablon tekrar seçilmez.
"""
import random
from typing import Optional

from bot.utils.helpers import esc, price_str, usd, format_quote

TEMPLATES = {
    "greeting": ["Selam{name}! 👋", "Merhaba{name}, hoş geldin.", "Hey{name} 👋 Nasılsın?", "Selam{name}, nasıl yardımcı olabilirim?"],
    "greeting.morning": ["Günaydın{name}! ☀️", "Günaydın{name}, güzel bir gün olsun."],
    "greeting.day": ["İyi günler{name}!", "Sana da iyi günler{name}."],
    "greeting.evening": ["İyi akşamlar{name}!", "Sana da iyi akşamlar{name} 🌙"],
    "small_talk.how_are_you": ["İyiyim, teşekkürler! Sen nasılsın?", "Gayet iyi, piyasaları izliyorum 📈 Sen nasılsın?",
                               "İyiyim, sağ ol. Senden ne haber?"],
    "small_talk.fine": ["Sevindim! Bir şeye bakmamı ister misin?", "Güzel 😊 Yardımcı olabileceğim bir şey var mı?"],
    "small_talk.identity": ["Ben MessifeBot 🤖 Kripto fiyatları, portföy, alarm ve haberler konusunda yardımcı olurum.",
                            "Adım MessifeBot. Kripto ve piyasa asistanınım."],
    "small_talk.compliment": ["Teşekkürler, çok naziksin 😊", "Sağ ol! Sen de harikasın."],
    "small_talk.love": ["Ben de seninle sohbet etmeyi seviyorum 🤖", "Çok tatlısın, teşekkürler 😊"],
    "small_talk": ["Buradayım 🙂 Ne konuşalım?", "Dinliyorum, nasıl yardımcı olabilirim?"],
    "thanks": ["Rica ederim{name}!", "Ne demek, her zaman 😊", "Rica ederim, başka bir şey olursa yaz."],
    "farewell": ["Görüşürüz{name}! 👋", "Kendine iyi bak{name}.", "Hoşça kal, yine beklerim."],
    "farewell.night": ["İyi geceler{name} 🌙", "İyi geceler, tatlı rüyalar."],
    "joke": [
        "Neden bilgisayar hasta oldu? Çünkü virüs kaptı! 😄",
        "Neden botlar partiye gitmez? Çünkü hep çalışmak zorundalar 🤖",
        "İki byte restorana gider. Garson: 'Bir şey alır mısınız?' — 'Hayır, biz sadece bit'e bakıyoruz.' 😄",
        "Programcılar neden karanlıkta çalışır? Çünkü ışık bug'ları çeker 💡",
        "HODL'un açılımı ne biliyor musun? 'Hâlâ Orada Duruyor, Lütfen' 😅",
    ],
}

UNKNOWN_TEXT = ("Anladığımdan emin olamadım. Kripto fiyatı, portföy, alarm, haber veya piyasa "
                "hakkında yardımcı olabilirim. Örnek: <i>bitcoin ne kadar</i>, <i>portföyüm ne durumda</i>, "
                "<i>alarmlarım</i>. Tüm komutlar için /help")

CAPABILITIES_TEXT = (
    "Şunlarda yardımcı olabilirim:\n\n"
    "💰 <b>Kripto fiyatları</b> — <i>btc kaç?</i>, <i>pi network ne durumda</i>, <i>eth 24 saatte ne yaptı</i>\n"
    "💼 <b>Portföy</b> — <i>portföyüm ne durumda</i>, eklemek için <code>EKLE BTC 0.1</code>\n"
    "🔔 <b>Fiyat alarmları</b> — <i>alarmlarım</i>, <i>btc 100000'i geçerse haber ver</i>\n"
    "📰 <b>Haberler</b> — <i>son haberler</i>, <i>kripto haberleri</i>\n"
    "📊 <b>Piyasa özeti</b> — <i>piyasalar nasıl</i>, <i>dolar kaç</i>\n"
    "📋 <b>Raporlar</b> — /report\n"
    "🎲 <b>Eğlence</b> — <i>şaka yap</i>, <i>zar at</i>, <i>yazı tura</i>\n\n"
    "Tüm komutlar: /help"
)

PRICE_UNAVAILABLE = "Şu anda fiyat verisine ulaşamıyorum. Biraz sonra tekrar deneyebilirsin."
SERVICE_UNAVAILABLE = "Şu anda bu bilgiye ulaşamıyorum. Biraz sonra tekrar deneyebilirsin."
NEED_ASSET = "Hangi coini soruyorsun? Örneğin: <i>bitcoin ne kadar</i> veya <i>pi network kaç</i>"
DESTRUCTIVE_TEXT = ("Portföyünü sohbet üzerinden silmiyorum; yanlışlıkla veri kaybı olmasın. 🙂\n"
                    "Bir varlığı silmek için /portfolio ile ID'sini görüp <code>/sil ID</code> yazabilirsin.")
REPORT_TEXT = ("📋 Günlük/haftalık portföy raporlarını /report ile görebilir, otomatik gönderimi "
               "oradaki ⚙️ Rapor Ayarları'ndan açabilirsin.")


class ResponseBank:
    def __init__(self, rng: Optional[random.Random] = None):
        self._rng = rng or random.Random()

    def pick(self, key: str, state=None, name: str = "") -> str:
        """Şablon seç; aynı anahtar için bir önceki şablonu tekrar seçme"""
        options = TEMPLATES.get(key) or TEMPLATES.get(key.split(".")[0]) or TEMPLATES["small_talk"]
        last = getattr(state, "last_response_key", None) if state is not None else None
        indexes = list(range(len(options)))
        if last and last.startswith(key + "#") and len(options) > 1:
            previous = int(last.split("#")[1])
            indexes = [i for i in indexes if i != previous]
        choice = self._rng.choice(indexes)
        if state is not None:
            state.last_response_key = f"{key}#{choice}"
        name_part = f" {esc(name)}" if name else ""
        return options[choice].replace("{name}", name_part)


# --- Kripto -----------------------------------------------------------------

def _asset_title(asset) -> str:
    return f"<b>{esc(asset.name)}</b> ({esc(asset.symbol)})"


def _change_text(change) -> str:
    if change is None:
        return "24 saatlik değişim verisi yok"
    arrow = "📈" if change >= 0.01 else "📉" if change <= -0.01 else "➡️"
    return f"{arrow} 24s: {change:+.2f}%"


def crypto_price(asset, snap: dict) -> str:
    return f"💰 {_asset_title(asset)}: {price_str(snap['price'])}\n{_change_text(snap.get('change_24h'))}"


def crypto_change(asset, snap: dict) -> str:
    change = snap.get("change_24h")
    if change is None:
        return f"{_asset_title(asset)} şu an {price_str(snap['price'])}. 24 saatlik değişim verisi yok."
    verb = "yükseldi" if change >= 0.01 else "düştü" if change <= -0.01 else "neredeyse hiç değişmedi"
    text = f"📊 {_asset_title(asset)} son 24 saatte <b>%{abs(change):.2f}</b> {verb}.\nŞu an: {price_str(snap['price'])}"
    if snap.get("low_24h") is not None and snap.get("high_24h") is not None:
        text += f"\n24s aralık: {price_str(snap['low_24h'])} – {price_str(snap['high_24h'])}"
    return text


def crypto_info(asset, snap: dict) -> str:
    return (crypto_change(asset, snap) +
            "\n\nFiyat hareketlerinin nedenini kesin olarak bilemem; ilgili gelişmeler için /cryptonews'e bakabilirsin.")


def crypto_convert(asset, snap: dict, amount: float) -> str:
    total = amount * snap["price"]
    return (f"🧮 {amount:g} {esc(asset.symbol)} ≈ <b>{usd(total) if total >= 1 else price_str(total)}</b>\n"
            f"(1 {esc(asset.symbol)} = {price_str(snap['price'])})")


def no_market_data(asset) -> str:
    return f"{_asset_title(asset)} için şu anda piyasa verisi bulunmuyor (işlem görmüyor olabilir)."


def asset_not_found(query: str) -> str:
    return (f"\"{esc(query)}\" adında bir coin bulamadım. /searchcrypto {esc(query)} ile arayabilir "
            f"veya tam adını yazabilirsin.")


# --- Portföy / alarm ---------------------------------------------------------

def portfolio_summary(result: dict, previous_value=None, want_change: bool = False) -> str:
    items = result["items"]
    if not items:
        return ("Portföyün şu an boş. Eklemek için örneğin <code>EKLE BTC 0.1</code> yazabilirsin "
                "(fiyat yazmazsan güncel fiyat kullanılır).")
    names = sorted({f"{esc(i['name'])} ({esc(i['symbol'])})" for i in items})
    text = f"💼 Portföyünde {len(items)} kalem var: {', '.join(names[:8])}"
    if len(names) > 8:
        text += f" ve {len(names) - 8} diğeri"
    text += "\n"
    if result["total_current"] > 0:
        text += f"💵 Toplam değer: <b>${result['total_current']:,.2f}</b>\n"
        text += f"🎯 Kar/Zarar: {usd(result['total_profit'])}\n"
    else:
        text += f"💰 Toplam yatırım: ${result['total_investment']:,.2f} (güncel fiyatlar alınamadı)\n"
    if want_change:
        if previous_value and previous_value > 0 and result["total_current"] > 0 and not result["missing_prices"]:
            change = (result["total_current"] - previous_value) / previous_value * 100
            text += f"📅 Son kayda göre değişim: %{change:+.2f}\n"
        else:
            text += "📅 Günlük değişim için henüz yeterli geçmiş kayıt yok (/report ile rapor oluşturuldukça birikir).\n"
    if result["missing_prices"]:
        text += f"⚠️ Fiyatı alınamayanlar: {esc(', '.join(result['missing_prices']))}\n"
    text += "Ayrıntılar için /portfolio"
    return text


def alerts_summary(alerts: list, asset=None) -> str:
    active = [a for a in alerts if a["is_active"]]
    if asset is not None:
        active = [a for a in active if a.get("provider_id") == asset.provider_id
                  or (a.get("coin_symbol") or "").upper() == asset.symbol.upper()]
    if not active:
        scope = f" {_asset_title(asset)} için" if asset is not None else ""
        return (f"🔔{scope} aktif alarmın yok. Kurmak için örneğin <code>/alert btc &gt; 100000</code> "
                f"yazabilir ya da <i>btc 100000'i geçerse haber ver</i> diyebilirsin.")
    lines = []
    for a in active[:10]:
        if a["alert_type"] == "change":
            target = f"%{a['target_price']:g} değişim"
        else:
            target = f"{'≥' if a['alert_type'] == 'above' else '≤'} {price_str(a['target_price'])}"
        lines.append(f"• {esc(a['coin_symbol'])} {target}")
    text = f"🔔 {len(active)} aktif alarmın var:\n" + "\n".join(lines)
    if len(active) > 10:
        text += f"\n… ve {len(active) - 10} tane daha"
    return text + "\nTümü için /alerts"


def alert_confirmation(asset, direction: str, target: float, current: Optional[float]) -> str:
    cond = "üzerine çıkarsa" if direction == "above" else "altına düşerse"
    text = f"🔔 Şu alarmı kurayım mı?\n\n{_asset_title(asset)} {price_str(target)} {cond} haber vereceğim."
    if current is not None:
        text += f"\nŞu anki fiyat: {price_str(current)}"
    return text


# --- Haber / piyasa ----------------------------------------------------------

def news_summary(items: list, topic: str) -> str:
    if not items:
        return "Şu anda haberlere ulaşamıyorum. Biraz sonra /news ile tekrar deneyebilirsin."
    title = {"crypto": "🗞 Son kripto haberleri", "economy": "💼 Son ekonomi haberleri"}.get(topic, "📰 Son haberler")
    lines = []
    for item in items[:3]:
        headline = esc(item["title"])
        if item.get("url"):
            headline = f'<a href="{esc(item["url"])}">{headline}</a>'
        lines.append(f"• {headline} <i>({esc(item.get('source', ''))})</i>")
    command = {"crypto": "/cryptonews", "economy": "/economy"}.get(topic, "/news")
    return f"<b>{title}</b>\n" + "\n".join(lines) + f"\n\nDaha fazlası: {command}"


def market_summary(summary: dict) -> str:
    rows = []
    for key in ("bist", "fx", "commodity", "crypto"):
        for name, unit, quote in summary.get(key, [])[:2]:
            rows.append(format_quote(name, unit, quote))
    return "📊 <b>Piyasa özeti</b>\n" + "".join(rows) + "Ayrıntılar: /market"
