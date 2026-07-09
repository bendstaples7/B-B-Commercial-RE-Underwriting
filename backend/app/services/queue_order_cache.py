"""In-process TTL cache for ordered queue lead IDs (navigation prev/next)."""
from __future__ import annotations

import threading
import time
from typing import Any

# Short TTL: fast queue stepping without stale neighbors for long.
QUEUE_ORDER_CACHE_TTL_SEC = 30


class QueueOrderCache:
    """Thread-safe TTL cache mapping cache keys → (ids, total, expires_at)."""

    def __init__(self, ttl_sec: float = QUEUE_ORDER_CACHE_TTL_SEC) -> None:
        self._ttl_sec = ttl_sec
        self._lock = threading.Lock()
        self._store: dict[tuple[Any, ...], tuple[list[int], int, float]] = {}

    def get(self, key: tuple[Any, ...]) -> tuple[list[int], int] | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ids, total, expires_at = entry
            if expires_at <= now:
                del self._store[key]
                return None
            return ids, total

    def set(self, key: tuple[Any, ...], ids: list[int], total: int) -> None:
        expires_at = time.monotonic() + self._ttl_sec
        with self._lock:
            self._store[key] = (ids, total, expires_at)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Shared cache for all QueueService instances in this process.
queue_order_cache = QueueOrderCache()
