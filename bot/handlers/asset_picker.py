# bot/handlers/asset_picker.py
"""Kripto varlık çözümleme için ortak Telegram yardımcıları.

Belirsiz bir girdi (ör. aynı sembolü taşıyan birden fazla coin) olduğunda kullanıcıya
seçenekler gösterilir; seçim "pick:<token>:<index>" callback'i ile assets.py'de işlenir.
"""
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from bot.services.assets import asset_resolver
from bot.utils.helpers import esc

MAX_PENDING_PICKS = 20


def format_asset_line(i: int, asset) -> str:
    rank = f" · Sıra #{asset.market_cap_rank}" if asset.market_cap_rank else " · sıralama yok"
    return (f"{i}. <b>{esc(asset.name)}</b> ({esc(asset.symbol)})\n"
            f"   ID: <code>{esc(asset.provider_id)}</code>{rank}\n")


def not_found_text(query: str, suggestions: list) -> str:
    text = f"❌ \"{esc(query)}\" adında bir kripto varlık bulunamadı."
    if suggestions:
        text += "\n\n🔎 Benzer sonuçlar:\n"
        for asset in suggestions[:5]:
            text += f"• {esc(asset.name)} ({esc(asset.symbol)}) — <code>{esc(asset.provider_id)}</code>\n"
        text += "\nTam ID ile tekrar deneyebilirsiniz, ör. yukarıdaki ID'lerden biri."
    return text


def store_pick(context, query: str, candidates: list, action: str, payload: dict = None) -> str:
    """Seçim bekleyen işlemi user_data'da sakla, kısa bir token döndür"""
    picks = context.user_data.setdefault('asset_picks', {})
    seq = context.user_data.get('asset_pick_seq', 0) + 1
    context.user_data['asset_pick_seq'] = seq
    token = str(seq)
    picks[token] = {'query': query, 'candidates': candidates, 'action': action, 'payload': payload or {}}
    for old in sorted(picks, key=int)[:-MAX_PENDING_PICKS]:
        picks.pop(old, None)
    return token


def picker_markup(token: str, candidates: list) -> InlineKeyboardMarkup:
    buttons = []
    for i, asset in enumerate(candidates):
        label = f"{i + 1}. {asset.name} ({asset.symbol})"
        if len(label) > 40:
            label = label[:39] + "…"
        buttons.append([InlineKeyboardButton(f"✅ Seç: {label}", callback_data=f"pick:{token}:{i}")])
    buttons.append([InlineKeyboardButton("✖️ İptal", callback_data=f"pick:{token}:x")])
    return InlineKeyboardMarkup(buttons)


async def send_picker(message, context, query: str, candidates: list, action: str, payload: dict = None,
                      header: str = None):
    """Adayları seçim butonlarıyla gönder"""
    token = store_pick(context, query, candidates, action, payload)
    text = header or (f"⚠️ \"{esc(query)}\" birden fazla varlıkla eşleşiyor. "
                      f"Lütfen doğru olanı seçin:\n\n")
    for i, asset in enumerate(candidates, 1):
        text += format_asset_line(i, asset)
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=picker_markup(token, candidates))


async def resolve_or_prompt(message, context, query: str, action: str, payload: dict = None):
    """Girdiyi varlığa çöz. Belirsizse seçim menüsü, bulunamazsa hata mesajı gönderir ve None döner."""
    user_id = message.from_user.id if message.from_user else 0
    resolution = await asyncio.to_thread(asset_resolver.resolve, query, user_id)

    if resolution.ok:
        return resolution.asset
    if resolution.status == 'ambiguous':
        await send_picker(message, context, query, resolution.candidates, action, payload)
    elif resolution.status == 'not_found':
        await message.reply_text(not_found_text(query, resolution.suggestions), parse_mode=ParseMode.HTML)
    else:
        await message.reply_text("⚠️ Kripto veri sağlayıcısına şu anda ulaşılamıyor. Lütfen biraz sonra tekrar deneyin.")
    return None
