# bot/services/conversation_context.py
"""Kısa süreli, kullanıcı+sohbet bazlı konuşma bağlamı (sadece bellekte).

- Anahtar: (chat_id, user_id) -> bir grubun bağlamı başka gruba/kullanıcıya sızmaz.
- Sadece yararlı özet tutulur: son niyet, son coin, son konu, son yanıt şablonu ve
  son N mesajın NİYETLERİ (mesaj metni saklanmaz).
- Kayıtlar TTL sonunda geçersiz olur; toplam kayıt sayısı sınırlıdır (en eski silinir).
"""
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Optional

CONTEXT_TTL_SECONDS = 10 * 60
MAX_CONTEXTS = 5000
HISTORY_SIZE = 6


@dataclass
class ConversationState:
    last_intent: Optional[str] = None
    last_asset: Optional[object] = None      # asset_resolver.Asset
    last_topic: Optional[str] = None         # 'crypto', 'portfolio', 'alerts', 'news', 'market', 'chat'
    last_response_key: Optional[str] = None  # tekrar eden yanıtı önlemek için
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))  # (rol, niyet)
    updated_at: float = 0.0


class ConversationContextStore:
    def __init__(self, ttl: float = CONTEXT_TTL_SECONDS, max_entries: int = MAX_CONTEXTS, now=time.time):
        self.ttl = ttl
        self.max_entries = max_entries
        self._now = now
        self._items: "OrderedDict[tuple, ConversationState]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, chat_id: int, user_id: int) -> ConversationState:
        """Geçerli bağlamı döndürür; süresi dolmuşsa boş bir bağlam başlatır."""
        key = (chat_id, user_id)
        with self._lock:
            state = self._items.get(key)
            if state is None or self._now() - state.updated_at > self.ttl:
                state = ConversationState(updated_at=self._now())
                self._items[key] = state
            self._items.move_to_end(key)
            self._evict()
            return state

    def touch(self, state: ConversationState):
        state.updated_at = self._now()

    def _evict(self):
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def cleanup(self) -> int:
        """Süresi dolan bağlamları sil (periyodik job'dan çağrılır)"""
        cutoff = self._now() - self.ttl
        with self._lock:
            expired = [k for k, s in self._items.items() if s.updated_at < cutoff]
            for key in expired:
                del self._items[key]
        return len(expired)

    def __len__(self):
        return len(self._items)
