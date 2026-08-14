import threading
import time
from collections import defaultdict

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 30
RATE_LIMIT_BURST = 10
RATE_LIMIT_DAILY = 500
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_daily: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()
_SWEEP_THRESHOLD = 10_000


def _sweep_if_large() -> None:
    """Drop keys whose history is entirely expired to bound memory."""
    if len(_rate_limit_store) > _SWEEP_THRESHOLD:
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW
        kept = {k: v for k, v in _rate_limit_store.items() if any(t > window_start for t in v)}
        _rate_limit_store.clear()
        _rate_limit_store.update(kept)
    if len(_rate_limit_daily) > _SWEEP_THRESHOLD:
        now = time.time()
        day_start = now - 86400
        kept = {k: v for k, v in _rate_limit_daily.items() if any(t > day_start for t in v)}
        _rate_limit_daily.clear()
        _rate_limit_daily.update(kept)


def check_rate_limit(key: str) -> bool:
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    with _rate_limit_lock:
        _sweep_if_large()
        timestamps = _rate_limit_store[key]
        pruned = [t for t in timestamps if t > window_start]
        if len(pruned) >= RATE_LIMIT_MAX:
            return False
        _rate_limit_store[key] = [*pruned, now]
        return True


def check_burst_limit(key: str) -> bool:
    now = time.time()
    burst_start = now - 5
    with _rate_limit_lock:
        timestamps = _rate_limit_store[key]
        recent = [t for t in timestamps if t > burst_start]
        return not len(recent) >= RATE_LIMIT_BURST


def check_daily_limit(key: str) -> bool:
    now = time.time()
    day_start = now - 86400
    with _rate_limit_lock:
        timestamps = _rate_limit_daily[key]
        pruned = [t for t in timestamps if t > day_start]
        if len(pruned) >= RATE_LIMIT_DAILY:
            return False
        _rate_limit_daily[key] = [*pruned, now]
        return True
