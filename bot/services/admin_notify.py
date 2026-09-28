# bot/services/admin_notify.py
"""Admin'lere operasyon bildirimleri (açılış, beklenmedik hata).

Bildirimler kullanıcı mesaj içeriği, token veya anahtar içermez; ayrıntılar sadece
sunucu logundadır. Gönderim hataları yutulur: bildirim sistemi botu asla düşürmez.
"""
import logging
import time
from typing import Callable, Iterable

from telegram.constants import ParseMode

from bot.utils.helpers import esc

logger = logging.getLogger(__name__)

ERROR_REPEAT_WINDOW = 30 * 60   # aynı (tür, yer) için en fazla 30 dakikada bir
HOURLY_ERROR_LIMIT = 10         # toplamda saatte en fazla 10 hata bildirimi


class AdminNotifier:
    def __init__(self, bot, admin_ids: Iterable[int], clock: Callable[[], float] = time.time):
        self._bot = bot
        self._admin_ids = list(admin_ids)
        self._clock = clock
        self._last_error_at = {}
        self._recent_errors = []

    @property
    def enabled(self) -> bool:
        return bool(self._admin_ids)

    async def _broadcast(self, text: str) -> bool:
        delivered = False
        for chat_id in self._admin_ids:
            try:
                await self._bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML,
                                             disable_web_page_preview=True)
                delivered = True
            except Exception:
                logger.exception("admin bildirimi gönderilemedi (chat_id=%s)", chat_id)
        return delivered

    async def notify_startup(self, version: str, unclean_previous: bool) -> bool:
        if not self.enabled:
            return False
        text = f"✅ Bot başladı: sürüm <code>{esc(version)}</code>"
        if unclean_previous:
            text += "\n⚠️ Önceki çalışma düzgün kapanmadı (çökme veya sunucu yeniden başlaması)."
        return await self._broadcast(text)

    async def notify_error(self, error_type: str, where: str) -> bool:
        if not self.enabled:
            return False
        now = self._clock()
        key = (error_type, where)
        last = self._last_error_at.get(key)
        if last is not None and now - last < ERROR_REPEAT_WINDOW:
            return False
        self._recent_errors = [t for t in self._recent_errors if now - t < 3600]
        if len(self._recent_errors) >= HOURLY_ERROR_LIMIT:
            return False
        self._last_error_at[key] = now
        self._recent_errors.append(now)
        text = (f"❗ Hata: <code>{esc(error_type)}</code> ({esc(where)})\n"
                f"Ayrıntılar sunucu logunda: <code>journalctl -u messifebot</code>")
        return await self._broadcast(text)
