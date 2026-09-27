# bot/handlers/admin.py
import asyncio
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest, RetryAfter
from telegram.ext import ContextTypes, CommandHandler
from bot.config import ADMIN_IDS
from bot.database import db
from bot.utils.helpers import esc

def is_admin(user_id):
    """Kullanıcının admin olup olmadığını kontrol et"""
    return user_id in ADMIN_IDS

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin paneli"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Bu komutu kullanma yetkiniz yok.")
        return

    admin_text = f"""
👑 <b>ADMİN PANELİ</b>

📊 <b>İstatistikler:</b>
/admin_stats - Bot istatistikleri
/admin_users - Son aktif kullanıcılar

📢 <b>Yayın:</b>
/broadcast &lt;mesaj&gt; - Tüm kullanıcılara mesaj gönder

🛠️ <b>Sistem:</b>
/admin_logs - Sistem durumu

💡 Toplam {len(ADMIN_IDS)} admin var.
    """
    await update.message.reply_text(admin_text, parse_mode=ParseMode.HTML)

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot istatistikleri"""
    if not is_admin(update.effective_user.id):
        return

    try:
        s = db.get_bot_summary()
        stats_text = f"""
📊 <b>BOT İSTATİSTİKLERİ</b>

👥 <b>Kullanıcılar:</b>
• Toplam: {s['total_users']}
• Bugün aktif: {s['active_today']}

💬 <b>Mesajlar:</b>
• Toplam: {s['total_messages']}
• Grup sayısı: {s['total_groups']}

💰 <b>Özellikler:</b>
• Portföy kalemleri: {s['portfolio_items']}
• Aktif alarmlar: {s['active_alerts']}

⚙️ <b>Sistem:</b>
• Admin: {len(ADMIN_IDS)}
• Durum: 🟢 Çalışıyor
        """
        await update.message.reply_text(stats_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        print(f"❌ İstatistik hatası: {e}")
        await update.message.reply_text("❌ İstatistikler alınırken hata oluştu.")

async def admin_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Son aktif kullanıcı listesi"""
    if not is_admin(update.effective_user.id):
        return

    try:
        users = db.get_recent_users(10)

        if not users:
            await update.message.reply_text("📭 Henüz kullanıcı yok.")
            return

        users_text = "👥 <b>SON AKTİF 10 KULLANICI</b>\n\n"
        for i, (user_id, first_name, username, msg_count) in enumerate(users, 1):
            username_display = f"@{esc(username)}" if username else "-"
            users_text += f"{i}. {esc(first_name or '-')} (<code>{user_id}</code>)\n"
            users_text += f"   📛 {username_display} | 📨 {msg_count} mesaj\n\n"

        await update.message.reply_text(users_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        print(f"❌ Kullanıcı listesi hatası: {e}")
        await update.message.reply_text("❌ Kullanıcı listesi alınırken hata oluştu.")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tüm kullanıcılara mesaj gönder"""
    if not is_admin(update.effective_user.id):
        return

    # Satır sonlarını korumak için mesajın ham metnini kullan
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text("❌ Kullanım: /broadcast <mesaj>")
        return
    message = parts[1]

    user_ids = db.get_all_user_ids()
    status = await update.message.reply_text(f"📢 {len(user_ids)} kullanıcıya gönderiliyor...")

    # Diğer güncellemeleri bekletmemek için arka planda gönder
    context.application.create_task(_run_broadcast(context, status, user_ids, message))

async def _run_broadcast(context: ContextTypes.DEFAULT_TYPE, status, user_ids: list, message: str):
    sent = failed = 0
    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            sent += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await context.bot.send_message(chat_id=user_id, text=message)
                sent += 1
            except Exception:
                failed += 1
        except (Forbidden, BadRequest):
            # Kullanıcı botu engellemiş veya hiç özel sohbet başlatmamış
            failed += 1
        except Exception as e:
            print(f"❌ Broadcast hatası (user {user_id}): {e}")
            failed += 1
        # Telegram limiti: saniyede ~30 mesaj
        await asyncio.sleep(0.05)

    await status.edit_text(f"📢 Broadcast tamamlandı.\n\n✅ Gönderildi: {sent}\n❌ Başarısız: {failed}")

async def admin_logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sistem durumu"""
    if not is_admin(update.effective_user.id):
        return

    started = context.bot_data.get('started_at')
    uptime = str(datetime.now() - started).split('.')[0] if started else "-"
    jobs = [job.name for job in context.job_queue.jobs()] if context.job_queue else []

    log_text = f"""
📋 <b>SİSTEM DURUMU</b>

🟢 Bot çalışıyor
⏱ Çalışma süresi: {uptime}
🗄 Veritabanı: <code>{esc(db.db_path)}</code>
⏰ Zamanlanmış görevler: {esc(', '.join(jobs) or 'yok')}

💡 Ayrıntılı loglar konsol çıktısındadır.
    """
    await update.message.reply_text(log_text, parse_mode=ParseMode.HTML)

def setup_admin_handlers(application):
    """Admin handler'larını kur"""
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("admin_stats", admin_stats_command))
    application.add_handler(CommandHandler("admin_users", admin_users_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("admin_logs", admin_logs_command))
    if not ADMIN_IDS:
        print("⚠️ ADMIN_IDS tanımlı değil - admin komutları kimse tarafından kullanılamaz (.env: ADMIN_IDS=...)")
    print("✅ Admin handler'ları kuruldu")
