# bot/handlers/alerts.py
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from bot.database import db
from bot.services.crypto_service import crypto_service
from bot.services.assets import asset_resolver
from bot.handlers.asset_picker import resolve_or_prompt
from bot.utils.helpers import esc, reply_long, price_str

# "btc > 50000", "eth<3000", "sol % 5"
ALERT_PATTERN = re.compile(r'^([^<>%]+?)\s*([<>%])\s*([\d.,]+)$')
ALERT_TYPES = {'>': 'above', '<': 'below', '%': 'change'}
TYPE_LABELS = {'above': 'Üstü', 'below': 'Altı', 'change': 'Değişim'}

USAGE_TEXT = (
    "Kullanım:\n"
    "• <code>/alert btc &gt; 50000</code> — fiyat üstüne çıkınca\n"
    "• <code>/alert eth &lt; 3000</code> — fiyat altına inince\n"
    "• <code>/alert sol % 5</code> — kurulduğu fiyattan %5 değişince\n\n"
    "📋 Alarmlarınız: /alerts"
)


def _alert_menu():
    keyboard = [
        [InlineKeyboardButton("🔼 Fiyat Üstü Alarm", callback_data="alert_above")],
        [InlineKeyboardButton("🔽 Fiyat Altı Alarm", callback_data="alert_below")],
        [InlineKeyboardButton("📈 Değişim Alarmı", callback_data="alert_change")],
        [InlineKeyboardButton("📋 Alarmlarım", callback_data="alert_list")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/alert <coin> <op> <değer> ile alarm kurar; argümansız ise menüyü gösterir"""
    if not context.args:
        await update.message.reply_text(
            "🔔 <b>Fiyat Alarm Sistemi</b>\n\nNe tür bir alarm kurmak istiyorsunuz?",
            reply_markup=_alert_menu(),
            parse_mode=ParseMode.HTML
        )
        return

    match = ALERT_PATTERN.match(" ".join(context.args).strip())
    if not match:
        await update.message.reply_text(f"❌ Alarm anlaşılamadı.\n\n{USAGE_TEXT}", parse_mode=ParseMode.HTML)
        return

    query, op, raw_value = match.groups()
    try:
        value = float(raw_value.replace(',', '.'))
    except ValueError:
        await update.message.reply_text(f"❌ Geçersiz sayı: {esc(raw_value)}")
        return
    if value <= 0:
        await update.message.reply_text("❌ Değer sıfırdan büyük olmalı.")
        return

    alert_type = ALERT_TYPES[op]
    asset = await resolve_or_prompt(update.message, context, query.strip(), 'alert',
                                    {'alert_type': alert_type, 'target': value})
    if asset is None:
        return  # seçim menüsü veya hata mesajı gönderildi

    text = await create_price_alert(update.effective_user.id, asset, alert_type, value)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def create_price_alert(user_id: int, asset, alert_type: str, target: float) -> str:
    """Çözümlenmiş varlık için fiyat alarmı oluşturur. Değişim alarmında `target` yüzde değeridir."""
    try:
        current_price = await asyncio.to_thread(crypto_service.get_price, asset.provider_id)
        if current_price is None:
            return f"❌ {esc(asset.label())} için şu anda fiyat alınamadı. Lütfen biraz sonra tekrar deneyin."

        db.create_alert(
            user_id=user_id,
            coin_symbol=asset.symbol,
            alert_type=alert_type,
            target_price=target,
            current_price=current_price,
            provider_id=asset.provider_id
        )

        target_text = f"%{target:g}" if alert_type == 'change' else price_str(target)
        return (
            f"✅ Alarm kuruldu!\n\n"
            f"Coin: {esc(asset.name)} ({esc(asset.symbol)})\n"
            f"ID: <code>{esc(asset.provider_id)}</code>\n"
            f"Tür: {TYPE_LABELS[alert_type]}\n"
            f"Hedef: {target_text}\n"
            f"Şu anki: {price_str(current_price)}"
        )

    except Exception as e:
        print(f"❌ Alarm oluşturma hatası: {e}")
        return "❌ Alarm oluşturulamadı, lütfen tekrar deneyin."


def _format_alerts(alerts: list) -> str:
    text = "📋 <b>Alarmlarınız</b>\n\n"
    for alert in alerts:
        status = "✅ Aktif" if alert['is_active'] else "☑️ Tetiklendi"
        if alert['alert_type'] == 'change':
            target = f"%{alert['target_price']:g} değişim"
        else:
            target = f"{TYPE_LABELS.get(alert['alert_type'], alert['alert_type'])} {price_str(alert['target_price'])}"
        text += f"• #{alert['id']} {esc(alert['coin_symbol'])} {target} — {status}\n"
    return text


async def alerts_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/alerts - alarmları listele"""
    alerts = db.get_user_alerts(update.effective_user.id)
    if not alerts:
        await update.message.reply_text(f"🔔 Alarmınız bulunmuyor.\n\n{USAGE_TEXT}", parse_mode=ParseMode.HTML)
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Tümünü Sil", callback_data="alert_delete_all")]])
    await reply_long(update.message, _format_alerts(alerts), reply_markup=keyboard)


async def alert_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alarm callback'lerini işler"""
    query = update.callback_query
    await query.answer()

    callback_data = query.data

    if callback_data == "alert_above":
        await query.edit_message_text(
            "🔼 <b>Fiyat Üstü Alarm</b>\n\n"
            "Örnek kullanım:\n"
            "<code>/alert btc &gt; 50000</code>\n\n"
            "BTC 50,000 USD üzerine çıkınca alarm verir.",
            parse_mode=ParseMode.HTML
        )

    elif callback_data == "alert_below":
        await query.edit_message_text(
            "🔽 <b>Fiyat Altı Alarm</b>\n\n"
            "Örnek kullanım:\n"
            "<code>/alert eth &lt; 3000</code>\n\n"
            "ETH 3,000 USD altına inince alarm verir.",
            parse_mode=ParseMode.HTML
        )

    elif callback_data == "alert_change":
        await query.edit_message_text(
            "📈 <b>Değişim Alarmı</b>\n\n"
            "Örnek kullanım:\n"
            "<code>/alert sol % 5</code>\n\n"
            "SOL, alarmın kurulduğu fiyattan %5 yükselir veya düşerse alarm verir.",
            parse_mode=ParseMode.HTML
        )

    elif callback_data == "alert_list":
        await show_user_alerts(query)

    elif callback_data == "alert_delete_all":
        deleted = db.delete_all_alerts(query.from_user.id)
        await query.edit_message_text(f"🗑 {deleted} alarm silindi.")


async def show_user_alerts(query):
    """Kullanıcının alarmlarını gösterir"""
    alerts = db.get_user_alerts(query.from_user.id)

    if not alerts:
        await query.edit_message_text(f"🔔 Alarmınız bulunmuyor.\n\n{USAGE_TEXT}", parse_mode=ParseMode.HTML)
        return

    keyboard = [[InlineKeyboardButton("🗑 Tümünü Sil", callback_data="alert_delete_all")]]
    text = _format_alerts(alerts)
    if len(text) > 4000:
        text = text[:4000].rsplit("\n", 1)[0] + "\n…"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


def _is_triggered(alert: dict, price: float):
    """Alarm tetiklendiyse (True, değişim%) döner"""
    if alert['alert_type'] == 'above':
        return price >= alert['target_price'], None
    if alert['alert_type'] == 'below':
        return price <= alert['target_price'], None
    if alert['alert_type'] == 'change':
        base = alert['current_price']
        if not base:
            return False, None
        change = (price - base) / base * 100
        return abs(change) >= alert['target_price'], change
    return False, None


async def check_alerts_job(context: ContextTypes.DEFAULT_TYPE):
    """Aktif alarmları kontrol eden background job"""
    try:
        active_alerts = db.get_active_alerts()
        if not active_alerts:
            return

        # Eski (sadece sembollü) alarmları kesin varlık ID'sine bağla
        for alert in active_alerts:
            if not alert['provider_id']:
                resolution = await asyncio.to_thread(asset_resolver.resolve, alert['coin_symbol'], alert['user_id'])
                if resolution.ok:
                    alert['provider_id'] = resolution.asset.provider_id
                    db.set_alert_asset(alert['id'], alert['provider_id'])

        # Tüm coinlerin fiyatını tek istekte al
        prices = await asyncio.to_thread(
            crypto_service.get_prices_by_ids, [a['provider_id'] for a in active_alerts if a['provider_id']]
        )

        for alert in active_alerts:
            current_price = prices.get(alert['provider_id']) if alert['provider_id'] else None
            if current_price is None:
                # Fiyat alınamadıysa bu turda atla (yanlış alarm vermemek için)
                continue

            triggered, change = _is_triggered(alert, current_price)
            if triggered:
                await trigger_alert(context, alert, current_price, change)

    except Exception as e:
        print(f"❌ Alarm kontrol hatası: {e}")


async def trigger_alert(context: ContextTypes.DEFAULT_TYPE, alert: dict, current_price: float, change: float = None):
    """Alarm tetiklendiğinde kullanıcıya bildirim gönderir"""
    symbol = esc(alert['coin_symbol'])
    if alert['alert_type'] == 'above':
        message = f"🚨 <b>ALARM!</b> {symbol} {price_str(alert['target_price'])} ÜZERİNDE!\n\n" \
                  f"📈 Şu anki fiyat: {price_str(current_price)}"
    elif alert['alert_type'] == 'below':
        message = f"🚨 <b>ALARM!</b> {symbol} {price_str(alert['target_price'])} ALTINDA!\n\n" \
                  f"📉 Şu anki fiyat: {price_str(current_price)}"
    else:
        message = f"🚨 <b>ALARM!</b> {symbol} %{abs(change):.1f} {'YÜKSELDİ' if change > 0 else 'DÜŞTÜ'}!\n\n" \
                  f"📊 Değişim: %{change:+.1f}\n" \
                  f"💰 Şu anki fiyat: {price_str(current_price)}"

    try:
        await context.bot.send_message(chat_id=alert['user_id'], text=message, parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"❌ Alarm gönderme hatası (user {alert['user_id']}): {e}")

    # Gönderilemese bile (ör. kullanıcı botu engellediyse) tekrar tekrar denememek için pasif yap
    db.deactivate_alert(alert['id'])


def setup_alert_handlers(application):
    """Alarm handler'larını kurar"""
    application.add_handler(CommandHandler("alert", alert_command))
    application.add_handler(CommandHandler("alerts", alerts_list_command))
    application.add_handler(CallbackQueryHandler(alert_callback_handler, pattern="^alert_"))

    # Background job - her 60 saniyede bir alarmları kontrol et
    application.job_queue.run_repeating(check_alerts_job, interval=60, first=10, name="check_alerts")
    print("✅ Alarm handler'ları kuruldu")
