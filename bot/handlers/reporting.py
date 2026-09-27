# bot/handlers/reporting.py
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from bot.config import DEFAULT_TIMEZONE
from bot.database import db
from bot.services.portfolio_service import value_portfolio
from bot.handlers.portfolio import build_portfolio_text
from bot.utils.helpers import esc, edit_long, usd

REPORT_TIMES = ["08:00", "09:00", "12:00", "18:00", "21:00"]


def _report_menu():
    keyboard = [
        [InlineKeyboardButton("📊 Günlük Rapor", callback_data="report_daily")],
        [InlineKeyboardButton("📈 Haftalık Rapor", callback_data="report_weekly")],
        [InlineKeyboardButton("💰 Portföy Raporu", callback_data="report_portfolio")],
        [InlineKeyboardButton("⚙️ Rapor Ayarları", callback_data="report_settings")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rapor menüsünü gösterir"""
    await update.message.reply_text(
        "📋 <b>Rapor Menüsü</b>\n\nHangi raporu görmek istiyorsunuz?",
        reply_markup=_report_menu(),
        parse_mode=ParseMode.HTML
    )


def _change_line(label: str, current: float, previous):
    if previous is None or previous <= 0:
        return f"{label} hesaplanamadı (yeterli geçmiş kayıt yok)\n"
    change = (current - previous) / previous * 100
    return f"{label} %{change:+.2f} ({'+' if current >= previous else ''}{usd(current - previous)})\n"


def _allocation_lines(items: list, total_value: float) -> str:
    priced = sorted((i for i in items if i['current_value'] is not None),
                    key=lambda i: i['current_value'], reverse=True)
    text = ""
    for item in priced[:5]:
        pct = item['current_value'] / total_value * 100 if total_value > 0 else 0
        text += f"• {esc(item['symbol'])}: %{pct:.1f}\n"
    if len(priced) > 5:
        text += f"• ... ve {len(priced) - 5} diğer coin\n"
    return text


def _missing_line(result: dict) -> str:
    if not result['missing_prices']:
        return ""
    return f"\n⚠️ Fiyatı alınamayanlar hesaba katılmadı: {esc(', '.join(result['missing_prices']))}\n"


def _value_or_error(user_id: int):
    """Portföyü değerle; rapor oluşturulamıyorsa (None, hata metni) döner"""
    result = value_portfolio(user_id)
    if not result['items']:
        return None, "📭 Portföyünüz boş. Rapor oluşturmak için önce /portfolio ile varlık ekleyin."
    if len(result['missing_prices']) == len(result['items']):
        return None, "⚠️ Şu anda fiyat verisi alınamadı, rapor oluşturulamadı. Lütfen biraz sonra tekrar deneyin."
    return result, None


def _record_history(user_id: int, result: dict):
    """Sadece tüm fiyatlar alındıysa geçmişe kaydet (eksik değer geçmişi bozmasın)"""
    if not result['missing_prices']:
        db.save_portfolio_history(user_id, result['total_current'], result['total_profit'])


def _build_daily_report(user_id: int) -> str:
    """Günlük rapor (bloklayan çağrı)"""
    result, error = _value_or_error(user_id)
    if error:
        return error

    total_value = result['total_current']
    # Eksik fiyat varsa karşılaştırma yanıltıcı olur
    previous = None if result['missing_prices'] else db.get_value_before(user_id, hours=20)
    _record_history(user_id, result)

    text = "📊 <b>Günlük Portföy Raporu</b>\n\n"
    text += f"💰 <b>Toplam Değer:</b> ${total_value:,.2f}\n"
    text += _change_line("📈 <b>24s Değişim:</b>", total_value, previous)
    text += f"🎯 <b>Toplam Kar/Zarar:</b> {usd(result['total_profit'])}\n\n"
    text += "💎 <b>Portföy Dağılımı:</b>\n"
    text += _allocation_lines(result['items'], total_value)
    text += _missing_line(result)
    text += f"\n⏰ <b>Rapor Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    return text


def _build_weekly_report(user_id: int) -> str:
    """Haftalık rapor (bloklayan çağrı)"""
    result, error = _value_or_error(user_id)
    if error:
        return error

    total_value = result['total_current']
    week_ago = None if result['missing_prices'] else db.get_value_before(user_id, hours=24 * 7)
    history = db.get_portfolio_history(user_id, days=7)
    _record_history(user_id, result)

    values = [h['total_value'] for h in history] + [total_value]

    text = "📈 <b>Haftalık Portföy Raporu</b>\n\n"
    text += f"💰 <b>Toplam Değer:</b> ${total_value:,.2f}\n"
    text += _change_line("📅 <b>7 Günlük Değişim:</b>", total_value, week_ago)
    text += f"🔼 <b>Hafta En Yüksek:</b> ${max(values):,.2f}\n"
    text += f"🔽 <b>Hafta En Düşük:</b> ${min(values):,.2f}\n"
    text += f"🎯 <b>Toplam Kar/Zarar:</b> {usd(result['total_profit'])}\n\n"

    priced = [i for i in result['items'] if i['profit_pct'] is not None]
    if priced:
        best = max(priced, key=lambda i: i['profit_pct'])
        worst = min(priced, key=lambda i: i['profit_pct'])
        text += f"🏆 <b>En İyi:</b> {esc(best['symbol'])} (%{best['profit_pct']:+.1f})\n"
        text += f"⚠️ <b>En Kötü:</b> {esc(worst['symbol'])} (%{worst['profit_pct']:+.1f})\n\n"

    text += "💎 <b>Portföy Dağılımı:</b>\n"
    text += _allocation_lines(result['items'], total_value)
    text += _missing_line(result)
    text += f"\nℹ️ Geçmiş, rapor oluşturuldukça kaydedilir ({len(history)} kayıt).\n"
    text += f"⏰ <b>Rapor Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    return text


async def generate_daily_report(user_id: int) -> str:
    try:
        return await asyncio.to_thread(_build_daily_report, user_id)
    except Exception as e:
        print(f"❌ Günlük rapor hatası: {e}")
        return "❌ Rapor oluşturulurken bir hata oluştu."


async def generate_weekly_report(user_id: int) -> str:
    try:
        return await asyncio.to_thread(_build_weekly_report, user_id)
    except Exception as e:
        print(f"❌ Haftalık rapor hatası: {e}")
        return "❌ Rapor oluşturulurken bir hata oluştu."


async def generate_portfolio_report(user_id: int) -> str:
    try:
        return await build_portfolio_text(user_id)
    except Exception as e:
        print(f"❌ Portföy raporu hatası: {e}")
        return "❌ Rapor oluşturulurken bir hata oluştu."


async def report_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rapor callback'lerini işler"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data in ("report_daily", "report_weekly", "report_portfolio"):
        await query.edit_message_text("⏳ Rapor hazırlanıyor...")
        generator = {
            "report_daily": generate_daily_report,
            "report_weekly": generate_weekly_report,
            "report_portfolio": generate_portfolio_report,
        }[data]
        await edit_long(query.message, await generator(user_id))

    elif data == "report_settings":
        await show_report_settings(query)

    elif data == "report_toggle_daily":
        settings = db.get_report_settings(user_id)
        db.update_report_settings(user_id, daily_report=not settings['daily_report'])
        await show_report_settings(query)

    elif data == "report_toggle_weekly":
        settings = db.get_report_settings(user_id)
        db.update_report_settings(user_id, weekly_report=not settings['weekly_report'])
        await show_report_settings(query)

    elif data == "report_set_time":
        keyboard = [[InlineKeyboardButton(t, callback_data=f"report_time_{t}")] for t in REPORT_TIMES]
        keyboard.append([InlineKeyboardButton("🔙 Geri", callback_data="report_settings")])
        await query.edit_message_text(
            "⏰ Raporların gönderileceği saati seçin (Türkiye saati):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("report_time_"):
        new_time = data[len("report_time_"):]
        if new_time in REPORT_TIMES:
            db.update_report_settings(user_id, report_time=new_time)
        await show_report_settings(query)

    elif data == "report_back":
        await query.edit_message_text(
            "📋 <b>Rapor Menüsü</b>\n\nHangi raporu görmek istiyorsunuz?",
            reply_markup=_report_menu(),
            parse_mode=ParseMode.HTML
        )


async def show_report_settings(query):
    """Rapor ayarlarını gösterir"""
    settings = db.get_report_settings(query.from_user.id)

    daily_status = "✅ Açık" if settings.get('daily_report') else "❌ Kapalı"
    weekly_status = "✅ Açık" if settings.get('weekly_report') else "❌ Kapalı"

    keyboard = [
        [InlineKeyboardButton(f"Günlük Rapor: {daily_status}", callback_data="report_toggle_daily")],
        [InlineKeyboardButton(f"Haftalık Rapor: {weekly_status}", callback_data="report_toggle_weekly")],
        [InlineKeyboardButton("⏰ Zaman Ayarla", callback_data="report_set_time")],
        [InlineKeyboardButton("🔙 Geri", callback_data="report_back")]
    ]

    await query.edit_message_text(
        f"⚙️ <b>Rapor Ayarları</b>\n\n"
        f"Günlük Rapor: {daily_status}\n"
        f"Haftalık Rapor: {weekly_status} (Pazartesi)\n"
        f"Rapor Saati: {esc(settings.get('report_time', '09:00'))}\n",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


def _local_now(tz_name: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name or DEFAULT_TIMEZONE))
    except Exception:
        return datetime.now(ZoneInfo(DEFAULT_TIMEZONE))


async def _send_report(context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str):
    try:
        await context.bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"❌ Rapor gönderme hatası (user {user_id}): {e}")


async def scheduled_reports_job(context: ContextTypes.DEFAULT_TYPE):
    """Her dakika çalışır; saati gelen kullanıcılara günlük/haftalık rapor gönderir"""
    sent = context.bot_data.setdefault('reports_sent', set())

    try:
        for user in db.get_users_with_daily_reports():
            now = _local_now(user['timezone'])
            key = ('daily', user['user_id'], now.date())
            if _is_due(now, user['report_time']) and key not in sent:
                sent.add(key)
                await _send_report(context, user['user_id'], await generate_daily_report(user['user_id']))

        for user in db.get_users_with_weekly_reports():
            now = _local_now(user['timezone'])
            key = ('weekly', user['user_id'], now.date())
            if now.weekday() == 0 and _is_due(now, user['report_time']) and key not in sent:
                sent.add(key)
                await _send_report(context, user['user_id'], await generate_weekly_report(user['user_id']))
    except Exception as e:
        print(f"❌ Zamanlanmış rapor hatası: {e}")


def _is_due(now: datetime, report_time: str) -> bool:
    """Rapor saati geldi mi? (job gecikmelerine karşı 5 dakikalık pencere)"""
    try:
        h, m = map(int, report_time.split(':'))
    except (ValueError, AttributeError):
        h, m = 9, 0
    minutes_since = (now.hour * 60 + now.minute) - (h * 60 + m)
    return 0 <= minutes_since < 5


def setup_reporting_handlers(application):
    """Raporlama handler'larını kurar"""
    application.add_handler(CommandHandler("report", report_command))
    application.add_handler(CallbackQueryHandler(report_callback_handler, pattern="^report_"))
    application.job_queue.run_repeating(scheduled_reports_job, interval=60, first=15, name="scheduled_reports")
    print("✅ Rapor handler'ları kuruldu")
