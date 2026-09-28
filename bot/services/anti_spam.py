# bot/services/anti_spam.py
"""Sohbet yanıtları için basit spam koruması (bellekte).

- Aynı kullanıcının aynı (normalize) mesajı kısa sürede tekrar gelirse yanıt verilmez.
- Kullanıcı başına pencere içinde en fazla N yanıt.
- Grup sohbetlerinde sohbet başına pencere içinde en fazla M yanıt.
Komutlar ve portföy/alarm işlemleri bu korumadan etkilenmez; sadece serbest sohbet yanıtları.
"""
import threading
import time
from collections import deque

DUPLICATE_WINDOW = 30      # saniye
USER_WINDOW = 30
USER_MAX_REPLIES = 6
GROUP_WINDOW = 60
GROUP_MAX_REPLIES = 10
MAX_TRACKED = 10000


class AntiSpam:
    def __init__(self, now=time.time):
        self._now = now
        self._lock = threading.Lock()
        self._last_text = {}   # (chat_id, user_id) -> (normalize metin, zaman)
        self._user_hits = {}   # user_id -> deque[zaman]
        self._chat_hits = {}   # chat_id -> deque[zaman]

    @staticmethod
    def _within(hits: deque, now: float, window: float) -> deque:
        while hits and now - hits[0] > window:
            hits.popleft()
        return hits

    def allow(self, chat_id: int, user_id: int, normalized_text: str, is_group: bool) -> tuple:
        """(izin, sebep) döndürür. İzin verilirse yanıt sayacı artırılır."""
        now = self._now()
        with self._lock:
            if len(self._last_text) > MAX_TRACKED:
                self._last_text.clear()
                self._user_hits.clear()
                self._chat_hits.clear()

            key = (chat_id, user_id)
            last = self._last_text.get(key)
            self._last_text[key] = (normalized_text, now)
            if last and last[0] == normalized_text and now - last[1] < DUPLICATE_WINDOW:
                return False, "duplicate"

            user_hits = self._within(self._user_hits.setdefault(user_id, deque()), now, USER_WINDOW)
            if len(user_hits) >= USER_MAX_REPLIES:
                return False, "user_rate"

            if is_group:
                chat_hits = self._within(self._chat_hits.setdefault(chat_id, deque()), now, GROUP_WINDOW)
                if len(chat_hits) >= GROUP_MAX_REPLIES:
                    return False, "group_rate"
                chat_hits.append(now)

            user_hits.append(now)
            return True, ""
