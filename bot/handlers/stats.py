# bot/handlers/stats.py
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler
from bot.database import db
from bot.utils.helpers import esc

MESSAGES_PER_LEVEL = 50

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcı istatistiklerini göster"""
    try:
        user = update.effective_user
        user_data = db.get_user_stats(user.id)
        message_count = user_data['message_count'] or 0

        if message_count > 0:
            level = message_count // MESSAGES_PER_LEVEL + 1
            to_next = MESSAGES_PER_LEVEL - message_count % MESSAGES_PER_LEVEL
            last = user_data['last_message_date']
            last_text = datetime.fromisoformat(last).strftime('%d.%m.%Y %H:%M') if last else "-"

            stats_text = f"""
📊 <b>{esc(user.first_name)} - İstatistikler</b>

👤 İsim: {esc(user.first_name)}
🆔 ID: <code>{user.id}</code>
📨 Toplam Mesaj: {message_count}
⭐ Seviye: {level} (sonraki seviyeye {to_next} mesaj)
🕐 Son Mesaj: {last_text}
            """
        else:
            stats_text = "📊 Henüz yeterli veri yok. Biraz daha sohbet edelim!"

        await update.message.reply_text(stats_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        print(f"❌ Stats komutu hatası: {e}")
        await update.message.reply_text("❌ İstatistikler alınırken bir hata oluştu.")

def setup_stats_handlers(application):
    """İstatistik handler'larını kur"""
    application.add_handler(CommandHandler("stats", stats_command))
    print("✅ İstatistik handler'ları kuruldu")
