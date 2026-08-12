"""Bounded background task execution.

Per-request `threading.Thread(...).start()` calls spawn an unbounded number of
threads under load. This module provides a single shared, size-bounded
executor plus a `spawn()` helper so background jobs are queued and concurrency
is capped at a small multiple of CPU count (mirroring the pattern used in
`app/core/push.py` and `app/core/activitypub/_inbound.py`).
"""
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_MAX_WORKERS = max(4, min(12, (os.cpu_count() or 2) + 1))

_executor = ThreadPoolExecutor(
    max_workers=_MAX_WORKERS,
    thread_name_prefix="writ-bg",
)


def spawn(fn, *args, **kwargs):
    """Schedule ``fn(*args, **kwargs)`` on the shared background executor.

    Never blocks: jobs that exceed the pool's capacity are queued. Returns the
    ``Future`` (or ``None`` if the executor is shutting down).
    """
    try:
        return _executor.submit(fn, *args, **kwargs)
    except RuntimeError:
        # Executor already shut down (app teardown) — fall back to a daemon
        # thread so pending work still has a chance to run.
        threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()
        return None
