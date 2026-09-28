# bot/handlers/fun.py
import random
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler

DICE_FACES = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zar atma komutu"""
    dice_value = random.randint(1, 6)
    await update.message.reply_text(
        f"{DICE_FACES[dice_value]} Zar attınız: <b>{dice_value}</b>", parse_mode=ParseMode.HTML
    )

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yazı tura atma"""
    result = random.choice(["Yazı", "Tura"])
    emoji = "👑" if result == "Yazı" else "🦅"
    await update.message.reply_text(f"🪙 Para atıldı: {emoji} <b>{result}</b>", parse_mode=ParseMode.HTML)

async def random_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rastgele sayı üret"""
    try:
        if context.args:
            if len(context.args) == 1:
                min_val = 1
                max_val = int(context.args[0])
            else:
                min_val = int(context.args[0])
                max_val = int(context.args[1])
        else:
            min_val, max_val = 1, 100

        if min_val > max_val:
            min_val, max_val = max_val, min_val

        number = random.randint(min_val, max_val)
        await update.message.reply_text(
            f"🎯 Rastgele sayı ({min_val}-{max_val}): <b>{number}</b>", parse_mode=ParseMode.HTML
        )

    except ValueError:
        await update.message.reply_text("❌ Kullanım: /random [min] [max] veya /random [max]")

def setup_fun_handlers(application):
    """Eğlence handler'larını kur"""
    application.add_handler(CommandHandler("dice", dice_command))
    application.add_handler(CommandHandler("coin", coin_command))
    application.add_handler(CommandHandler("random", random_command))
    print("✅ Eğlence handler'ları kuruldu")
