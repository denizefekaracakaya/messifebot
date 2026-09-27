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

from telegram import Update
from telegram.ext import Application, ContextTypes

from bot.config import ADMIN_IDS, HEALTHCHECK_URL, VERSION_FILE, require_bot_token
from bot.database import db
from bot.handlers import setup_handlers
from bot.services.admin_notify import AdminNotifier
from bot.services.heartbeat import schedule_heartbeat
from bot.services.lifecycle import mark_clean_shutdown, mark_started, resolve_version

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def describe_error_source(update: object, context) -> str:
    """Hatanın nereden geldiğini kullanıcı içeriği sızdırmadan tarif eder."""
    if isinstance(update, Update):
        if update.callback_query:
            return "buton"
        message = update.effective_message
        if message is not None:
            text = message.text or ""
            if text.startswith("/"):
                return f"komut {text.split()[0].split('@')[0][:32]}"
            return "mesaj"
    job = getattr(context, "job", None)
    if job is not None:
        return f"görev {job.name}"
    return "genel"


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Yakalanmamış hataları logla ve admin'e kısa özet gönder"""
    logger.error("Güncelleme işlenirken hata oluştu", exc_info=context.error)
    notifier = context.application.bot_data.get("notifier")
    if notifier is not None:
        await notifier.notify_error(type(context.error).__name__, describe_error_source(update, context))


async def on_startup(application: Application):
    unclean = mark_started(db)
    version = resolve_version(version_file=VERSION_FILE)
    notifier = AdminNotifier(application.bot, ADMIN_IDS)
    application.bot_data["notifier"] = notifier
    application.bot_data["version"] = version
    logger.info("bot başlıyor sürüm=%s önceki_kapanış_temiz=%s", version, not unclean)
    await notifier.notify_startup(version, unclean)
    if schedule_heartbeat(application.job_queue, HEALTHCHECK_URL):
        logger.info("healthchecks.io sinyali etkin")


async def on_shutdown(application: Application):
    mark_clean_shutdown(db)
    logger.info("bot düzgün kapandı")


def build_application(token: str) -> Application:
    application = (
        Application.builder()
        .token(token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    application.bot_data['started_at'] = datetime.now()
    setup_handlers(application)
    application.add_error_handler(error_handler)
    return application


def main():
    print("🤖 Bot başlatılıyor...")
    try:
        application = build_application(require_bot_token())
        print("✅ Handler'lar kuruldu")
        print("🚀 Polling başlatılıyor...")
        application.run_polling()
    except Exception as e:
        print(f"❌ Hata: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
