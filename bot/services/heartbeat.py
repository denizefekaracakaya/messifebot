# bot/services/heartbeat.py
"""healthchecks.io için "hayattayım" sinyali.

Sinyal gelmezse healthchecks.io admin'e e-posta atar. Bu, Telegram bildiriminin
gönderilemediği durumları da (sunucu kapalı, ağ yok, bot donmuş) kapsar.
URL gizli bir kimlik içerdiği için loglanmaz.
"""
import asyncio
import logging

import requests

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 300
HTTP_TIMEOUT = 10


async def send_heartbeat(bot, url: str, http_get=requests.get) -> str:
    """Telegram'a ulaşılabiliyorsa URL'ye, ulaşılamıyorsa URL/fail'e istek atar."""
    try:
        await bot.get_me()
        target, status = url, "ok"
    except Exception:
        logger.warning("heartbeat: Telegram'a ulaşılamadı, /fail sinyali gönderiliyor")
        target, status = url.rstrip("/") + "/fail", "fail"
    try:
        await asyncio.to_thread(http_get, target, timeout=HTTP_TIMEOUT)
    except Exception as e:
        logger.warning("heartbeat: sinyal gönderilemedi (%s)", type(e).__name__)
        return "error"
    return status


async def heartbeat_job(context) -> None:
    await send_heartbeat(context.bot, context.job.data)


def schedule_heartbeat(job_queue, url: str, interval: int = HEARTBEAT_INTERVAL) -> bool:
    if not url:
        return False
    job_queue.run_repeating(heartbeat_job, interval=interval, first=30, data=url, name="heartbeat")
    return True
