# bot/services/intents.py
"""Kural tabanlı niyet (intent) sınıflandırması.

Her niyet, ağırlıklı anahtar ifadelerden oluşan tek bir tabloda tanımlıdır (INTENT_RULES).
Eşleştirme aksan katlanmış (fold) kelimeler üzerinde yapılır; tek kelimelik anahtarlar
Türkçe ekleri yakalamak için kelime başı (önek) olarak eşleşir: 'portfoy' -> 'portföyümü'.

Sınıflandırıcı ağ/IO yapmaz. Coin çözümleme gibi işlemler ConversationEngine'dedir;
burada sadece metinden "coin olabilecek" kısım (asset_query) çıkarılır.
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from bot.services.text_normalizer import tokenize, fold_tokens, parse_number, _FOLD_TABLE


class Intent(str, Enum):
    GREETING = "GREETING"
    FAREWELL = "FAREWELL"
    SMALL_TALK = "SMALL_TALK"
    THANKS = "THANKS"
    HELP = "HELP"
    BOT_CAPABILITIES = "BOT_CAPABILITIES"
    CRYPTO_PRICE = "CRYPTO_PRICE"
    CRYPTO_CHANGE = "CRYPTO_CHANGE"
    CRYPTO_CONVERT = "CRYPTO_CONVERT"
    CRYPTO_INFO = "CRYPTO_INFO"
    MARKET_STATUS = "MARKET_STATUS"
    PORTFOLIO_QUERY = "PORTFOLIO_QUERY"
    PORTFOLIO_MODIFY = "PORTFOLIO_MODIFY"
    ALERT_QUERY = "ALERT_QUERY"
    ALERT_CREATE = "ALERT_CREATE"
    NEWS_QUERY = "NEWS_QUERY"
    REPORT_QUERY = "REPORT_QUERY"
    USER_ID_QUERY = "USER_ID_QUERY"
    FUN_INTERACTION = "FUN_INTERACTION"
    UNKNOWN = "UNKNOWN"


CRYPTO_INTENTS = {Intent.CRYPTO_PRICE, Intent.CRYPTO_CHANGE, Intent.CRYPTO_CONVERT, Intent.CRYPTO_INFO}


@dataclass(frozen=True)
class Rule:
    intent: Intent
    phrase: str          # fold edilmiş ifade, ör. "ne kadar"
    weight: float = 1.0
    tag: str = ""        # yanıt varyantı için alt tür (ör. 'morning', 'joke')


def _rules(intent: Intent, weight: float, phrases: str, tag: str = "") -> list:
    return [Rule(intent, p.strip(), weight, tag) for p in phrases.split("|") if p.strip()]


INTENT_RULES = (
    _rules(Intent.GREETING, 2, "selam|merhaba|hey|hi|hello|hola|selamun aleykum|hosgeldin")
    + _rules(Intent.GREETING, 2, "gunaydin", "morning")
    + _rules(Intent.GREETING, 2, "iyi gunler", "day")
    + _rules(Intent.GREETING, 2, "iyi aksamlar", "evening")
    + _rules(Intent.SMALL_TALK, 2.5, "nasilsin|iyi misin|naber|ne haber|napiyorsun|ne yapiyorsun"
                                      "|ne var ne yok|nasil gidiyor|keyifler nasil|keyfin nasil", "how_are_you")
    + _rules(Intent.SMALL_TALK, 2, "iyiyim|ben de iyiyim|fena degil|idare eder|super|harika", "fine")
    + _rules(Intent.SMALL_TALK, 3, "adin ne|ismin ne|sen kimsin|kimsin|who are you|bot musun", "identity")
    + _rules(Intent.SMALL_TALK, 2, "harikasin|mukemmelsin|supersin|akillisin|zekisin|cok iyisin", "compliment")
    + _rules(Intent.SMALL_TALK, 2, "seni seviyorum|seviyorum|asigim", "love")
    + _rules(Intent.THANKS, 3, "tesekkur|sagol|eyvallah|thanks|thank you|mersi|eline saglik|cok sagol")
    + _rules(Intent.FAREWELL, 3, "gorusuruz|hosca kal|bye|goodbye|bay bay|gorusmek uzere|kendine iyi bak"
                                 "|allaha emanet|allah a emanet")
    + _rules(Intent.FAREWELL, 3, "iyi geceler", "night")
    + _rules(Intent.BOT_CAPABILITIES, 4, "ne yapabil|neler yapabil|ne ise yar|ozellik|yetenek|yardimci olabil"
                                         "|neler bil|nasil kullan")
    + _rules(Intent.HELP, 4, "yardim|komutlar|komut listesi|help")
    + _rules(Intent.USER_ID_QUERY, 5, "id|idm|idim|id numara|telegram id|kullanici id")
    + _rules(Intent.PORTFOLIO_QUERY, 4, "portfoy|portfolio|coinlerim|varliklarim|hangi coin|sahip oldugum"
                                        "|toplam param|param ne kadar|toplam deger|elimdeki|hangi kripto")
    + _rules(Intent.PORTFOLIO_MODIFY, 3, "portfoyumu sil|portfoyu sil|hepsini sil|hepsini kaldir|portfoyu temizle"
                                         "|portfoyumu temizle|portfoyumu sifirla")
    + _rules(Intent.ALERT_QUERY, 4, "alarm|uyari|bildirim")
    + _rules(Intent.ALERT_CREATE, 3, "gecerse|gecince|asarsa|asinca|ustune cikarsa|uzerine cikarsa|yukselirse"
                                     "|duserse|dusunce|altina inerse|altina duserse|inerse|haber ver|bana bildir"
                                     "|alarm kur|haberim olsun")
    + _rules(Intent.NEWS_QUERY, 4, "haberler|haberleri|son haber|gundem|news|haber var mi|kripto haber"
                                   "|ekonomi haber|borsa haber|neler oluyor")
    + _rules(Intent.MARKET_STATUS, 3, "piyasa|piyasalar|borsa|bist|doviz|altin|dolar kac|euro kac|dolar ne kadar"
                                      "|euro ne kadar|emtia|petrol|market")
    + _rules(Intent.REPORT_QUERY, 4, "rapor")
    + _rules(Intent.CRYPTO_PRICE, 2, "kac|ne kadar|fiyat|kac dolar|ne durumda|degeri|price|kactan|kac para"
                                     "|kac usd|ne alemde")
    + _rules(Intent.CRYPTO_CHANGE, 3, "yukseldi|yukselis|dustu|dusus|artti|azaldi|degisim|24 saat|saatlik"
                                      "|ne yapti|bugun nasil|gunluk|performans")
    + _rules(Intent.CRYPTO_INFO, 3.5, "neden|niye|nicin|nedir|ne demek|hakkinda|bilgi ver")
    + _rules(Intent.CRYPTO_CONVERT, 4, "tane|adet|alsam|alirsam|kac eder|ne eder|eder mi|olsa")
    + _rules(Intent.FUN_INTERACTION, 4, "saka|fikra|espri|guldur|komik bir", "joke")
    + _rules(Intent.FUN_INTERACTION, 4, "zar at|zar atar", "dice")
    + _rules(Intent.FUN_INTERACTION, 4, "yazi tura", "coin")
)

# Coin adı olamayacak kelimeler (fold edilmiş). Kalanlar asset_query olur.
STOPWORDS = set("""
ne kadar kac fiyat fiyati fiyatlari durumda durum nasil simdi su an anda bugun peki ya bu mi mu mı mü
bana ben benim bi bir lutfen acaba usd dolar dolarla dolara olmus oldu yukseldi dustu artti azaldi degisim
degisimi saat saatte saatlik saatteki 24 son gunluk tane adet alsam alirsam eder ederim ederdi olur
gecerse gecince asarsa asinca ustune uzerine cikarsa yukselirse duserse dusunce altina inerse haber ver
bildir deger degeri degerinde ile ve the how much price is what yapti neden niye nicin artti coin kripto
para ki de da hey bot bakar misin soyle soyler goster gosterir musun icin var yok olsa kactan alemde
nedir demek hakkinda bilgi yukseliste dususte performans gidiyor olsun haberim kur alarm hatirlat
yap yapar mısın misin acaba sence senin sen o simdiki anlik guncel ne durumda mi nasildir usdt dolarda
biraz tl lira try hangi anlat anlatir anlatirmisin kurdum kurdugum olunca olursa gelince gelirse
""".split())

MARKET_WORDS = {"dolar", "euro", "altin", "borsa", "bist", "doviz", "petrol", "emtia", "piyasa", "piyasalar"}

# "Peki X?", "Ya X?" gibi takip soruları
FOLLOW_UP_MARKERS = {"peki", "ya", "bide", "birde", "bir de", "o zaman", "ayrica"}

ABOVE_WORDS = ("gecerse", "gecince", "asarsa", "asinca", "ustune", "uzerine", "yukselirse", "cikarsa")
BELOW_WORDS = ("duserse", "dusunce", "altina", "inerse")


@dataclass
class Classification:
    intent: Intent
    score: float = 0.0
    tag: str = ""
    asset_query: Optional[str] = None   # coin olabilecek kısım (orijinal yazımla)
    amount: Optional[float] = None      # "20 tane" -> 20
    target: Optional[float] = None      # alarm hedef fiyatı
    direction: Optional[str] = None     # 'above' | 'below'
    is_follow_up: bool = False
    scores: dict = field(default_factory=dict)


def _phrase_match(phrase_tokens: list, tokens: list):
    """İfade mesajda ardışık geçiyorsa eşleşen kelime indekslerini, yoksa None döndürür.
    Tek kelimelik ifadeler (4+ harf) önek olarak eşleşir; çok kelimelilerde sadece son kelime önektir."""
    n = len(phrase_tokens)
    if n == 1:
        p = phrase_tokens[0]
        if len(p) <= 3 or p.isdigit():
            hits = [i for i, t in enumerate(tokens) if t == p]
        else:
            hits = [i for i, t in enumerate(tokens) if t.startswith(p)]
        return hits or None
    for i in range(len(tokens) - n + 1):
        window = tokens[i:i + n]
        if window[:-1] == phrase_tokens[:-1] and window[-1].startswith(phrase_tokens[-1]):
            return list(range(i, i + n))
    return None


_PARSED_RULES = [(rule, rule.phrase.split()) for rule in INTENT_RULES]


def _numbers(tokens: list) -> list:
    """Sayı değerleri; '100 bin' -> 100000"""
    values = []
    for i, tok in enumerate(tokens):
        value = parse_number(tok)
        if value is None:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if nxt == "bin":
            value *= 1_000
        elif nxt in ("milyon", "mn"):
            value *= 1_000_000
        values.append(value)
    return values


def _asset_query(original_tokens: list, folded: list, matched_indexes: set) -> Optional[str]:
    kept = []
    for i, (orig, f) in enumerate(zip(original_tokens, folded)):
        if f in STOPWORDS or i in matched_indexes or f in FOLLOW_UP_MARKERS:
            continue
        if parse_number(f) is not None or f in ("bin", "milyon"):
            continue
        if any(f.startswith(p) for p in ("saat", "gun", "dolar", "fiyat", "degis", "haber")):
            continue
        kept.append(orig)
    if not kept or len(kept) > 3:
        return None
    return " ".join(kept)


def classify(text: str) -> Classification:
    original = tokenize(text)
    folded = [t.translate(_FOLD_TABLE) for t in original]
    if not folded:
        return Classification(Intent.UNKNOWN)

    scores, tags, matched_indexes = {}, {}, set()
    for rule, phrase_tokens in _PARSED_RULES:
        hits = _phrase_match(phrase_tokens, folded)
        if hits is not None:
            scores[rule.intent] = scores.get(rule.intent, 0) + rule.weight
            if rule.tag and rule.intent not in tags:
                tags[rule.intent] = rule.tag
            matched_indexes.update(hits)

    numbers = _numbers(original)
    asset_query = _asset_query(original, folded, matched_indexes)
    is_follow_up = folded[0] in FOLLOW_UP_MARKERS

    # "ne haber" bir selamlaşma; NEWS değil. "haber ver" alarm kurma ifadesi.
    if Intent.ALERT_CREATE in scores and not numbers:
        scores[Intent.ALERT_QUERY] = scores.get(Intent.ALERT_QUERY, 0) + scores.pop(Intent.ALERT_CREATE) / 2
    if Intent.ALERT_CREATE in scores:
        scores.pop(Intent.NEWS_QUERY, None)

    # Kripto niyetleri coin olmadan zayıftır; coin varsa güçlenir
    if asset_query and asset_query.translate(_FOLD_TABLE) not in MARKET_WORDS:
        for intent in CRYPTO_INTENTS:
            if intent in scores:
                scores[intent] += 1.5
        # "<coin> ne durumda" gibi ifadeler selamlaşmaya kaymasın
        if Intent.CRYPTO_CHANGE in scores and Intent.SMALL_TALK in scores:
            scores.pop(Intent.SMALL_TALK)
    elif asset_query is None and Intent.CRYPTO_PRICE in scores and Intent.MARKET_STATUS in scores:
        scores.pop(Intent.CRYPTO_PRICE)

    # "20 tane alsam" -> dönüşüm; sayı yoksa dönüşüm değildir
    if Intent.CRYPTO_CONVERT in scores and not numbers:
        scores.pop(Intent.CRYPTO_CONVERT)
    if Intent.CRYPTO_CONVERT in scores:
        scores.pop(Intent.CRYPTO_PRICE, None)
    # Portföy silme niyeti, sorgudan önce gelir
    if Intent.PORTFOLIO_MODIFY in scores:
        scores.pop(Intent.PORTFOLIO_QUERY, None)
    # Alarm kurma, fiyat sorusundan önce gelir
    if Intent.ALERT_CREATE in scores:
        for intent in CRYPTO_INTENTS:
            scores.pop(intent, None)
        scores.pop(Intent.ALERT_QUERY, None)

    if not scores:
        return Classification(Intent.UNKNOWN, asset_query=asset_query, amount=numbers[0] if numbers else None,
                              is_follow_up=is_follow_up)

    best = max(scores, key=lambda i: (scores[i], -list(Intent).index(i)))
    result = Classification(best, scores[best], tags.get(best, ""), asset_query, is_follow_up=is_follow_up,
                            scores={k.value: v for k, v in scores.items()})

    if best == Intent.CRYPTO_CONVERT and numbers:
        result.amount = numbers[0]
    if best == Intent.ALERT_CREATE:
        result.target = numbers[-1] if numbers else None
        joined = " ".join(folded)
        if any(w in joined for w in BELOW_WORDS):
            result.direction = "below"
        elif any(w in joined for w in ABOVE_WORDS):
            result.direction = "above"
    if best == Intent.PORTFOLIO_QUERY and Intent.CRYPTO_CHANGE in scores:
        result.tag = "change"
    if best == Intent.NEWS_QUERY:
        joined = " ".join(folded)
        if any(w in joined for w in ("kripto", "coin", "bitcoin", "btc", "ethereum")):
            result.tag = "crypto"
        elif "ekonomi" in joined:
            result.tag = "economy"
        else:
            result.tag = "markets"
    return result
