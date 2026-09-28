# bot/services/text_normalizer.py
"""Sohbet metinleri için merkezi Türkçe normalizasyon.

İki seviye:
- normalize(): Türkçe küçük harf (İ->i, I->ı), noktalama temizliği, uzatılmış harfler,
  kesme işaretli ekler ve yaygın kısaltmalar. Türkçe karakterler korunur.
- fold(): normalize() + aksan katlama (ı/i, ş/s, ğ/g, ç/c, ö/o, ü/u). Anahtar kelime
  eşleştirmesi bu biçimde yapılır; böylece "nasılsın", "nasilsin", "NASILSIN" aynı olur.
"""
import re

_FOLD_TABLE = str.maketrans({
    'ı': 'i', 'ş': 's', 'ğ': 'g', 'ç': 'c', 'ö': 'o', 'ü': 'u', 'â': 'a', 'î': 'i', 'û': 'u',
})

# Yaygın sohbet kısaltmaları / yazım biçimleri (fold edilmiş biçimde)
ABBREVIATIONS = {
    'slm': 'selam',
    'sa': 'selamun aleykum',
    'selamlar': 'selam',
    'mrb': 'merhaba',
    'mrhb': 'merhaba',
    'nbr': 'naber',
    'nbrr': 'naber',
    'napiyosun': 'napiyorsun',
    'naptin': 'napiyorsun',
    'nasilsn': 'nasilsin',
    'tsk': 'tesekkurler',
    'tskler': 'tesekkurler',
    'tsklr': 'tesekkurler',
    'sgl': 'sagol',
    'sagolun': 'sagol',
    'eyv': 'eyvallah',
    'gg': 'gorusuruz',
    'grsrz': 'gorusuruz',
    'gunaydinn': 'gunaydin',
    'bi': 'bir',
    'btc': 'btc',
    'yardm': 'yardim',
    'thx': 'thanks',
    'ty': 'thanks',
    'pls': 'lutfen',
    'lutfn': 'lutfen',
}

_APOSTROPHES = "'’‘`´"
_NUMBER_RE = re.compile(r'^\d+(?:[.,]\d+)*$')


def tr_lower(text: str) -> str:
    """Türkçe'ye uygun küçük harf: 'İ' -> 'i', 'I' -> 'ı' (Python'un lower() 'I'yı 'i' yapar)"""
    return (text or '').replace('İ', 'i').replace('I', 'ı').lower().replace('i̇', 'i')


def fold(text: str) -> str:
    """Aksan katlanmış, karşılaştırmaya hazır biçim"""
    return normalize(text).translate(_FOLD_TABLE)


def _strip_suffix(token: str) -> str:
    """Kesme işaretinden sonraki eki at: "btc'nin" -> "btc", "100000'i" -> "100000" """
    for ch in _APOSTROPHES:
        if ch in token:
            return token.split(ch, 1)[0]
    return token


def _squeeze(token: str) -> str:
    """3+ kez tekrarlanan harfi teke indir: 'selaaaam' -> 'selam' (sayılara dokunmaz)"""
    if token.isdigit():
        return token
    return re.sub(r'([^\d])\1{2,}', r'\1', token)


def tokenize(text: str) -> list:
    """Normalize edilmiş kelime listesi. Sayılar (100000, 0.5, 0,5) tek parça kalır."""
    lowered = tr_lower(text)
    lowered = re.sub(r'@\w+', ' ', lowered)          # @mention'lar
    lowered = re.sub(r'https?://\S+', ' ', lowered)  # linkler
    tokens = []
    for raw in lowered.split():
        raw = _strip_suffix(raw)
        # Sayı değilse noktalamayı boşluğa çevir
        if not _NUMBER_RE.match(raw.strip('.,!?;:')):
            parts = re.split(r'[^\w\-]+', raw)
        else:
            parts = [raw.strip('.,!?;:')]
        for part in parts:
            part = part.strip('-_')
            if not part:
                continue
            part = _squeeze(part)
            expanded = ABBREVIATIONS.get(part.translate(_FOLD_TABLE))
            tokens.extend(expanded.split() if expanded else [part])
    return tokens


def normalize(text: str) -> str:
    return ' '.join(tokenize(text))


def fold_tokens(text: str) -> list:
    return [t.translate(_FOLD_TABLE) for t in tokenize(text)]


def parse_number(token: str):
    """'100000', '100.000', '0,5', '1.5', '100k', '2m' -> float; değilse None"""
    t = token.lower().strip()
    multiplier = 1
    if t.endswith('k') and t[:-1].replace('.', '').replace(',', '').isdigit():
        multiplier, t = 1_000, t[:-1]
    elif t.endswith('m') and t[:-1].replace('.', '').replace(',', '').isdigit():
        multiplier, t = 1_000_000, t[:-1]
    if not t or not _NUMBER_RE.match(t):
        return None
    if ',' in t and '.' in t:
        t = t.replace('.', '').replace(',', '.')
    elif ',' in t:
        # "0,5" ondalık; "100,000" binlik ayraç
        head, _, tail = t.rpartition(',')
        t = t.replace(',', '') if len(tail) == 3 and head.isdigit() and len(head) <= 3 else t.replace(',', '.')
    elif t.count('.') > 1 or (t.count('.') == 1 and len(t.split('.')[1]) == 3 and len(t.split('.')[0]) <= 3
                              and t.split('.')[0] != '0'):
        # "100.000" -> binlik ayraç (Türkçe yazım)
        t = t.replace('.', '')
    try:
        return float(t) * multiplier
    except ValueError:
        return None
