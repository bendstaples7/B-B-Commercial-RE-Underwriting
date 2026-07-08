"""Tests for queue order ID cache."""
import time

from app.services.queue_order_cache import QueueOrderCache


def test_cache_hit_within_ttl():
    cache = QueueOrderCache(ttl_sec=60)
    key = ('admin', 'todays-action', 'lead_score', 'desc', '')
    cache.set(key, [1, 2, 3], 3)
    assert cache.get(key) == ([1, 2, 3], 3)


def test_cache_miss_after_ttl():
    cache = QueueOrderCache(ttl_sec=0.01)
    key = ('admin', 'todays-action', 'lead_score', 'desc', '')
    cache.set(key, [10, 20], 2)
    time.sleep(0.02)
    assert cache.get(key) is None
