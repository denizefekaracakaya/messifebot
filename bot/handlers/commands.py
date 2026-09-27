# bot/handlers/commands.py
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler
from bot.database import db
from bot.utils.helpers import esc

COMMANDS_TEXT = """
📈 <b>Haber &amp; Piyasa Komutları:</b>
/news - 📰 Borsa haberleri
/economy - 💼 Ekonomi haberleri
/cryptonews - 🗞 Kripto para haberleri
/crypto - 🪙 En popüler 10 kripto
/market - 📊 Piyasa özeti

💰 <b>Portföy, Alarm &amp; Rapor:</b>
/searchcrypto - 🔎 Kripto ara (ör. <code>/searchcrypto PI</code>)
/price - 💵 Kripto fiyatı (ör. <code>/price Pi Network</code>)
/portfolio - 💼 Portföy yönetimi (<code>EKLE PI 100</code>)
/sil ID - 🗑 Portföyden varlık sil
/alert - 🔔 Fiyat alarmı kur (ör. <code>/alert btc &gt; 50000</code>)
/alerts - 📋 Alarmlarım
/report - 📋 Raporlar ve otomatik rapor ayarları

🎮 <b>Eğlence Komutları:</b>
/dice - 🎲 Zar at
/coin - 🪙 Yazı tura
/random - 🎯 Rastgele sayı

📊 <b>İstatistik:</b>
/stats - 📈 Kişisel istatistikler
/id - 🆔 Telegram ID'ni göster

👑 <b>Admin:</b>
/admin - 👑 Admin paneli (sadece yöneticiler)
"""

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Kullanıcıyı veritabanına ekle
    db.add_user(user.id, user.username, user.first_name, user.last_name)

    welcome_text = f"""
🎉 <b>Hoş geldin {esc(user.first_name)}!</b> 🤖

Ben senin kişisel asistan botunum! Seninle sohbet edebilir, komutlarını işleyebilirim.

💬 <b>Benimle sohbet edebilirsin:</b>
• Merhaba de, selamlaşalım
• Nasılsın diye sor
• Şaka anlatmamı iste
• Kompliman yap 😊
{COMMANDS_TEXT}
Hadi sohbet edelim! Bir şeyler yaz ve beni test et! 🚀
    """

    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = f"""
🤖 <b>YARDIM MENÜSÜ</b>

💬 <b>Sohbet Özellikleri:</b>
Merhaba, nasılsın, şaka, teşekkür vb. (Gruplarda beni etiketle veya mesajıma yanıt ver.)
{COMMANDS_TEXT}
🔧 <b>Yardım:</b>
/help - 🤖 Bu menü
    """

    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcının Telegram ID'sini gösterir (ADMIN_IDS ayarı için)"""
    await update.message.reply_text(
        f"🆔 Telegram ID'n: <code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML
    )

def setup_commands(application):
    """Komut handler'larını kur"""
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("id", id_command))
    print("✅ Komut handler'ları kuruldu")
