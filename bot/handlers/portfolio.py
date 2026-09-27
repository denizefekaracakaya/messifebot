# bot/handlers/portfolio.py
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ApplicationHandlerStop
)
from bot.database import db
from bot.services.crypto_service import crypto_service
from bot.services.portfolio_service import value_portfolio
from bot.handlers.asset_picker import resolve_or_prompt
from bot.utils.helpers import esc, fold_tr, edit_long, usd, price_str

ADD_FORMAT_HELP = (
    "Doğru format: <code>EKLE VARLIK MİKTAR [ALIŞ_FİYATI]</code>\n"
    "• VARLIK - Sembol, isim veya ID (BTC, Pi Network, pi-network)\n"
    "• MİKTAR - Adet\n"
    "• ALIŞ_FİYATI - USD (yazılmazsa güncel fiyat kullanılır)\n\n"
    "Örnekler: <code>EKLE BTC 0.5 35000</code>, <code>EKLE PI 100</code>, "
    "<code>EKLE Pi Network 100 0.08</code>"
)

# Portföy komutları
async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Portföy menüsü"""
    user = update.effective_user

    keyboard = [
        [InlineKeyboardButton("➕ Varlık Ekle", callback_data="add_asset")],
        [InlineKeyboardButton("📊 Portföyümü Göster", callback_data="show_portfolio")],
        [InlineKeyboardButton("💹 En Popüler Kriptolar", callback_data="market_track")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"💰 <b>PORTFÖY YÖNETİMİ</b>\n\n"
        f"Hoş geldin {esc(user.first_name)}!\n\n"
        f"📊 Portföyünüzü yönetin:\n"
        f"• Kripto paralar ekleyin\n"
        f"• Anlık kar/zarar görün\n"
        f"• Piyasa takibi yapın\n\n"
        f"🗑 Silmek için: <code>/sil ID</code>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def handle_portfolio_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Portföy callback'lerini işle"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    callback_data = query.data

    if callback_data == "add_asset":
        await query.edit_message_text(
            "➕ <b>Varlık Ekleme</b>\n\n"
            "Lütfen şu formatta gönderin:\n"
            "<code>EKLE VARLIK MİKTAR [ALIŞ_FİYATI]</code>\n\n"
            "Örnekler:\n"
            "• <code>EKLE BTC 0.5 35000</code>\n"
            "• <code>EKLE PI 100</code> (güncel fiyattan)\n"
            "• <code>EKLE Pi Network 100 0.08</code>\n\n"
            "🔎 Coin bulmak için: /searchcrypto PI\n"
            "⚠️ Sadece kripto paralar desteklenmektedir.",
            parse_mode=ParseMode.HTML
        )

    elif callback_data == "show_portfolio":
        await query.edit_message_text("⏳ Portföy hesaplanıyor...")
        text = await build_portfolio_text(user.id)
        await edit_long(query.message, text)

    elif callback_data == "market_track":
        await query.edit_message_text("⏳ Kripto verileri getiriliyor...")
        crypto_data = await asyncio.to_thread(crypto_service.get_top_cryptos, 10)
        await edit_long(query.message, crypto_service.format_crypto_message(crypto_data))

def _parse_number(value: str) -> float:
    """'0,5' veya '35.000,50' gibi girişleri de kabul et"""
    value = value.strip()
    if ',' in value and '.' in value:
        value = value.replace('.', '').replace(',', '.')
    else:
        value = value.replace(',', '.')
    return float(value)

def _try_number(value: str):
    try:
        return _parse_number(value)
    except ValueError:
        return None

def parse_add_command(text: str):
    """'EKLE [KRİPTO] <varlık...> <miktar> [alış_fiyatı]' ayrıştırır.

    Varlık birden fazla kelime olabilir ('ekle pi network 100').
    Dönüş: (varlık_sorgusu, miktar, fiyat veya None) ya da hata metni (str).
    """
    # Baştaki @bot mention'ı ve "EKLE" kelimesi hariç, orijinal yazım korunur
    words = [w for w in text.split() if not w.startswith('@')][1:]
    if words and fold_tr(words[0]) == 'KRIPTO':
        words = words[1:]

    numbers = []
    while len(words) > 1 and len(numbers) < 2 and _try_number(words[-1]) is not None:
        numbers.insert(0, _parse_number(words.pop()))

    if not words or not numbers:
        return f"❌ Geçersiz format!\n\n{ADD_FORMAT_HELP}"

    quantity = numbers[0]
    price = numbers[1] if len(numbers) > 1 else None
    if quantity <= 0 or (price is not None and price < 0):
        return "❌ Miktar pozitif, fiyat negatif olmayan bir sayı olmalı!"
    return " ".join(words), quantity, price

async def add_asset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Varlık ekleme mesajını işle"""
    message = update.message
    if message.chat.type != 'private':
        # Grupta sadece bota yazılan EKLE mesajları işlenir; sıradan grup sohbeti yok sayılır
        from bot.handlers.messages import is_addressed_to_bot
        if not is_addressed_to_bot(message, context.bot.username, context.bot.id):
            return
    await _add_asset(update, context)
    # Sohbet handler'ının (group 1) bu mesaja ayrıca yanıt vermesini engelle
    raise ApplicationHandlerStop

async def _add_asset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parse_add_command(update.message.text)
    if isinstance(parsed, str):
        await update.message.reply_text(parsed, parse_mode=ParseMode.HTML)
        return
    query, quantity, price = parsed

    try:
        asset = await resolve_or_prompt(update.message, context, query, 'add',
                                        {'quantity': quantity, 'price': price})
        if asset is None:
            return  # seçim menüsü veya hata mesajı gönderildi
        text = await finalize_add(update.effective_user.id, asset, quantity, price)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"❌ Varlık ekleme hatası: {e}")
        await update.message.reply_text("❌ Varlık eklenirken bir hata oluştu.")

async def finalize_add(user_id: int, asset, quantity: float, price) -> str:
    """Çözümlenmiş varlığı portföye ekler ve sonuç metnini döndürür"""
    current_price = await asyncio.to_thread(crypto_service.get_price, asset.provider_id)
    if price is None:
        if current_price is None:
            return (f"❌ {esc(asset.label())} için güncel fiyat alınamadı. Lütfen alış fiyatını da yazın, "
                    f"ör. <code>EKLE {esc(asset.provider_id)} {quantity:g} 0.5</code>")
        price = current_price

    item_id = db.add_to_portfolio(user_id, asset.symbol, quantity, price,
                                  provider_id=asset.provider_id, asset_name=asset.name)
    text = (
        f"✅ <b>Varlık Eklendi!</b> (ID: {item_id})\n\n"
        f"🪙 Varlık: {esc(asset.name)} ({esc(asset.symbol)})\n"
        f"🔗 Sağlayıcı ID: <code>{esc(asset.provider_id)}</code>\n"
        f"📦 Miktar: {quantity:g}\n"
        f"💰 Alış Fiyatı: {price_str(price)}\n"
    )
    if current_price is not None:
        text += f"🎯 Güncel Fiyat: {price_str(current_price)}\n"
    else:
        text += "⚠️ Güncel fiyat şu anda alınamadı.\n"
    text += "\nPortföyünüzü görmek için /portfolio yazın."
    return text

async def remove_asset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sil ID - portföyden varlık sil"""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Kullanım: /sil ID\n\nID'leri portföyünüzde görebilirsiniz.")
        return

    if db.remove_from_portfolio(update.effective_user.id, int(context.args[0])):
        await update.message.reply_text("🗑 Varlık portföyden silindi.")
    else:
        await update.message.reply_text("❌ Bu ID ile bir varlık bulunamadı.")

async def build_portfolio_text(user_id: int) -> str:
    """Kullanıcının portföy özetini HTML olarak oluştur"""
    result = await asyncio.to_thread(value_portfolio, user_id)

    if not result['items']:
        return (
            "📭 Portföyünüz boş.\n\n"
            "Varlık eklemek için /portfolio menüsündeki '➕ Varlık Ekle' butonunu kullanın."
        )

    message = "💰 <b>PORTFÖY ÖZETİ</b>\n\n"

    for item in result['items']:
        message += f"<b>{esc(item['name'])}</b> ({esc(item['symbol'])}) · ID: {item['id']}\n"
        message += f"📦 Miktar: {item['amount']:g}\n"
        message += f"💰 Alış: {price_str(item['buy_price'])}\n"

        if item['current_price'] is not None:
            profit = item['profit']
            profit_emoji = "📈" if profit > 0 else "📉" if profit < 0 else "➡️"
            message += f"🎯 Güncel: {price_str(item['current_price'])}\n"
            message += f"{profit_emoji} Kar/Zarar: {usd(profit)} (%{item['profit_pct']:+.1f})\n"
            message += f"💵 Değer: ${item['current_value']:,.2f}\n"
        else:
            message += f"💵 Yatırım: ${item['investment']:,.2f}\n"
            if item['provider_id']:
                message += "ℹ️ Güncel fiyat şu anda alınamadı\n"
            else:
                message += (f"ℹ️ Varlık belirlenemedi. <code>/sil {item['id']}</code> ile silip "
                            f"/searchcrypto ile doğru coini bularak tekrar ekleyin\n")

        message += "─" * 25 + "\n\n"

    total_investment = result['total_investment']
    message += "<b>📊 TOPLAM</b>\n"
    message += f"💰 Yatırım: ${total_investment:,.2f}\n"
    if result['total_current'] > 0:
        message += f"💵 Güncel: ${result['total_current']:,.2f}\n"
        message += f"🎯 Kar/Zarar: {usd(result['total_profit'])}"
        priced_investment = result['total_current'] - result['total_profit']
        if priced_investment > 0:
            message += f" (%{result['total_profit'] / priced_investment * 100:+.1f})"
        message += "\n"
    if result['missing_prices']:
        message += f"⚠️ Fiyatı alınamayanlar toplama dahil değil: {esc(', '.join(result['missing_prices']))}"

    return message

def setup_portfolio_handlers(application):
    """Portföy handler'larını kur"""
    application.add_handler(CommandHandler("portfolio", portfolio_command))
    application.add_handler(CommandHandler("sil", remove_asset_command))
    application.add_handler(CallbackQueryHandler(handle_portfolio_callback, pattern="^(add_asset|show_portfolio|market_track)$"))

    # "EKLE ..." ile başlayan mesajlar (büyük/küçük harf fark etmez)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'(?i)^\s*(@\w+\s+)?ekle\b'),
        add_asset_handler
    ))

    print("✅ Portföy handler'ları kuruldu")
