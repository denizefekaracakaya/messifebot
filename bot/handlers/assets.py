# bot/handlers/assets.py
"""Kripto varlık arama/seçim komutları: /searchcrypto, /price ve seçim butonları"""
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from bot.services.assets import asset_resolver
from bot.services.crypto_service import crypto_service
from bot.handlers.asset_picker import send_picker, resolve_or_prompt, not_found_text
from bot.handlers.portfolio import finalize_add
from bot.handlers.alerts import create_price_alert
from bot.utils.helpers import esc, price_str

SEARCH_USAGE = "❌ Kullanım: /searchcrypto <sembol veya isim>\n\nÖrnek: /searchcrypto PI"


async def search_crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/searchcrypto PI - varlık ara, sonuçlardan seçim yap"""
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text(SEARCH_USAGE)
        return

    result = await asyncio.to_thread(asset_resolver.search, query)
    if result.status == 'error':
        await update.message.reply_text("⚠️ Kripto veri sağlayıcısına şu anda ulaşılamıyor. Lütfen biraz sonra tekrar deneyin.")
        return
    if result.status == 'not_found':
        await update.message.reply_text(not_found_text(query, []), parse_mode=ParseMode.HTML)
        return

    header = f"🔎 <b>Arama sonuçları:</b> {esc(query)}\n\n"
    await send_picker(update.message, context, query, result.candidates, 'select', header=header)


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/price PI - varlığın güncel fiyatı"""
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("❌ Kullanım: /price <sembol veya isim>\n\nÖrnek: /price Pi Network")
        return

    asset = await resolve_or_prompt(update.message, context, query, 'select')
    if asset:
        await update.message.reply_text(await asset_price_text(asset), parse_mode=ParseMode.HTML)


async def asset_price_text(asset, prefix: str = "") -> str:
    price = await asyncio.to_thread(crypto_service.get_price, asset.provider_id)
    text = prefix
    text += f"🪙 <b>{esc(asset.name)}</b> ({esc(asset.symbol)})\n"
    text += f"🔗 ID: <code>{esc(asset.provider_id)}</code>\n"
    if asset.market_cap_rank:
        text += f"🏅 Piyasa değeri sırası: #{asset.market_cap_rank}\n"
    text += f"💵 Fiyat: {price_str(price)}" if price is not None else "💵 Fiyat: şu anda alınamadı"
    return text


async def pick_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'pick:<token>:<index>' - kullanıcının varlık seçimi"""
    query = update.callback_query
    await query.answer()

    try:
        _, token, choice = query.data.split(":", 2)
    except ValueError:
        return

    pick = context.user_data.get('asset_picks', {}).pop(token, None)
    if pick is None:
        await query.edit_message_text("⌛ Bu seçim menüsünün süresi doldu. Lütfen komutu tekrar gönderin.")
        return
    if choice == 'x':
        await query.edit_message_text("✖️ İptal edildi.")
        return

    try:
        asset = pick['candidates'][int(choice)]
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Geçersiz seçim.")
        return

    user_id = query.from_user.id
    # Seçimi hatırla: aynı sorgu bir dahaki sefere doğrudan bu varlığa çözülür
    await asyncio.to_thread(asset_resolver.remember_selection, pick['query'], asset, user_id)

    action, payload = pick['action'], pick['payload']
    if action == 'add':
        text = await finalize_add(user_id, asset, payload['quantity'], payload['price'])
    elif action == 'alert':
        text = await create_price_alert(user_id, asset, payload['alert_type'], payload['target'])
    elif action == 'chat':
        from bot.handlers.messages import conversation_engine
        text = await conversation_engine.answer_for_asset(
            payload.get('intent', ''), asset, payload.get('amount'),
            chat_id=query.message.chat.id if query.message else user_id, user_id=user_id)
    else:
        text = await asset_price_text(asset, prefix=f"✅ {esc(asset.label())} seçildi.\n\n")

    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


async def refresh_catalog_job(context: ContextTypes.DEFAULT_TYPE):
    """Yerel varlık kataloğunu periyodik olarak sağlayıcıyla senkronize et"""
    try:
        await asyncio.to_thread(asset_resolver.ensure_catalog)
    except Exception as e:
        print(f"❌ Katalog yenileme hatası: {e}")


def setup_asset_handlers(application):
    application.add_handler(CommandHandler("searchcrypto", search_crypto_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CallbackQueryHandler(pick_callback_handler, pattern="^pick:"))
    # Açılışta ve her saat kontrol et; katalog 24 saatten eskiyse yenilenir
    application.job_queue.run_repeating(refresh_catalog_job, interval=3600, first=5, name="asset_catalog")
    print("✅ Varlık arama handler'ları kuruldu")
