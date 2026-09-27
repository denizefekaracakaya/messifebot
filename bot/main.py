# bot/main.py
import logging
import os
import sys
from datetime import datetime

# `python bot/main.py` ile çalıştırıldığında da `bot` paketini bulabilmek için
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows konsolunda emoji içeren print'lerin çökmemesi için
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from telegram.ext import Application, ContextTypes
from bot.config import require_bot_token
from bot.handlers import setup_handlers

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Yakalanmamış hataları logla"""
    logger.error("Güncelleme işlenirken hata oluştu", exc_info=context.error)

def main():
    print("🤖 Bot başlatılıyor...")

    try:
        # Application oluştur
        application = Application.builder().token(require_bot_token()).build()
        application.bot_data['started_at'] = datetime.now()

        setup_handlers(application)
        application.add_error_handler(error_handler)

        print("✅ Handler'lar kuruldu")
        print("🚀 Polling başlatılıyor...")

        application.run_polling()

    except Exception as e:
        print(f"❌ Hata: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
