# bot/utils/helpers.py
import html
import math
from telegram.constants import ParseMode

TELEGRAM_MAX_LEN = 4096


def esc(value) -> str:
    """Dinamik metni Telegram HTML modu için güvenli hale getir"""
    return html.escape(str(value), quote=False)


def tr_upper(text: str) -> str:
    """Türkçe büyük harf dönüşümü (i -> İ, ı -> I)"""
    return text.replace('i', 'İ').replace('ı', 'I').upper()


def tr_lower(text: str) -> str:
    """Türkçe küçük harf dönüşümü (İ -> i, I -> ı)"""
    return text.replace('İ', 'i').replace('I', 'ı').lower()


def fold_tr(text: str) -> str:
    """Karşılaştırma için İ/I/ı/i farkını yok sayan büyük harf hali"""
    return text.upper().replace('İ', 'I').replace('İ', 'I')


def split_message(text: str, limit: int = TELEGRAM_MAX_LEN) -> list:
    """Uzun metni satır sınırlarından Telegram limitine göre böl"""
    if len(text) <= limit:
        return [text]

    chunks, current = [], ""
    for line in text.split("\n"):
        # Tek satır bile limiti aşıyorsa zorla böl
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]

        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


async def reply_long(message, text: str, parse_mode=ParseMode.HTML, **kwargs):
    """Uzun metni birden fazla mesaj olarak gönder"""
    for chunk in split_message(text):
        await message.reply_text(chunk, parse_mode=parse_mode, disable_web_page_preview=True, **kwargs)


async def edit_long(message, text: str, parse_mode=ParseMode.HTML):
    """İlk parçayı mevcut mesaja yaz, kalanları yeni mesaj olarak gönder"""
    chunks = split_message(text)
    await message.edit_text(chunks[0], parse_mode=parse_mode, disable_web_page_preview=True)
    for chunk in chunks[1:]:
        await message.chat.send_message(chunk, parse_mode=parse_mode, disable_web_page_preview=True)


def usd(value: float) -> str:
    """Negatif değerleri '$-5.00' yerine '-$5.00' olarak formatla"""
    return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"


def price_str(value: float) -> str:
    """Fiyatı büyüklüğüne göre formatla: $84,166.00 / $0.09191 / $0.0003209"""
    if value is None:
        return "-"
    if abs(value) >= 1 or value == 0:
        return f"${value:,.2f}"
    decimals = min(12, 3 - math.floor(math.log10(abs(value))))  # ~4 anlamlı basamak
    return f"${value:.{decimals}f}".rstrip('0').rstrip('.')


def format_quote(name: str, unit: str, quote) -> str:
    """Piyasa satırı, ör. '• USD/TRY: 48.96 ₺ 📈 +0.02%' (HTML güvenli)"""
    if not quote or quote.get('price') is None:
        return f"• {esc(name)}: veri alınamadı\n"
    price = quote['price']
    line = f"• {esc(name)}: {unit}{price:,.2f}" if unit == '$' else f"• {esc(name)}: {price:,.2f}{(' ' + unit) if unit else ''}"
    change = quote.get('change_pct')
    if change is not None:
        arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        line += f" {arrow} {change:+.2f}%"
    return line + "\n"
