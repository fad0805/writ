"""Background task execution with bounded concurrency and queue depth.

Per-request `threading.Thread(...).start()` calls spawn an unbounded number of
threads under load. This module provides a single shared executor plus a
`spawn()` helper so concurrency is capped at a small multiple of CPU count
(mirroring the pattern used in `app/core/push.py` and
`app/core/activitypub/_inbound.py`).

Unlike a plain `ThreadPoolExecutor`, the pending queue is also bounded. When
the backlog is full `submit()` raises `BacklogFull` instead of growing memory
without limit. Callers must drop/reject the job explicitly (or fall back to a
request-scoped error), which gives backpressure while running as a single
process. Multi-worker scaling still needs an external queue.
"""
import logging
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_MAX_WORKERS = max(4, min(12, (os.cpu_count() or 2) + 1))
_MAX_QUEUE = 200


class BacklogFull(RuntimeError):
    """Raised when the executor's pending queue cannot accept more work."""


class _BacklogQueue(queue.SimpleQueue):
    """SimpleQueue that rejects work items when the pending count is full.

    `ThreadPoolExecutor` uses `None` sentinels for wakeups/shutdown. Those must
    never be rejected or counted, otherwise interpreter shutdown can deadlock
    when the queue is full. Only real work items consume backlog capacity.
    """

    def __init__(self, maxsize: int):
        super().__init__()
        self._maxsize = maxsize
        self._size = 0
        self._lock = threading.Lock()

    def put(self, item, block=True, timeout=None):
        if item is not None:
            with self._lock:
                if self._size >= self._maxsize:
                    raise BacklogFull("background task backlog is full")
                self._size += 1
        super().put(item)

    def put_nowait(self, item):
        self.put(item)

    def get(self, block=True, timeout=None):
        item = super().get(block, timeout)
        if item is not None:
            with self._lock:
                self._size -= 1
        return item

    def get_nowait(self):
        return self.get(block=False)


class BoundedThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor with a bounded pending queue."""

    def __init__(self, max_workers: int, queue_size: int, **kwargs):
        super().__init__(max_workers=max_workers, **kwargs)
        # No threads are started until the first submit, so replacing the
        # internal queue here is safe.
        self._work_queue = _BacklogQueue(maxsize=queue_size)


_executor = BoundedThreadPoolExecutor(
    max_workers=_MAX_WORKERS,
    queue_size=_MAX_QUEUE,
    thread_name_prefix="writ-bg",
)


def spawn(fn, *args, **kwargs):
    """Schedule ``fn(*args, **kwargs)`` on the shared background executor.

    Never blocks: jobs beyond the worker capacity wait in a bounded queue. If
    that queue is full the job is dropped with a warning. Returns the ``Future``
    (or ``None`` if the job was dropped or the executor is shutting down).
    """
    try:
        return _executor.submit(fn, *args, **kwargs)
    except BacklogFull:
        logger.warning("Background task backlog full, dropping %s", getattr(fn, "__name__", fn))
        return None
    except RuntimeError:
        # Executor already shut down (app teardown) — fall back to a daemon
        # thread so pending work still has a chance to run.
        threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()
        return None
