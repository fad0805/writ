import asyncio

import pytest

from app.core import push, threads
from app.core.activitypub import _inbound
from app.core.threads import BacklogFull, BoundedThreadPoolExecutor


class _FullExecutor:
    def submit(self, fn, *args, **kwargs):
        raise BacklogFull("full")


def test_bounded_executor_rejects_when_pending_queue_is_full():
    import threading

    release = threading.Event()
    ex = BoundedThreadPoolExecutor(max_workers=1, queue_size=1, thread_name_prefix="test")

    def block():
        release.wait(2)

    running = ex.submit(block)
    queued = ex.submit(lambda: None)
    with pytest.raises(BacklogFull):
        ex.submit(lambda: None)

    release.set()
    running.result(timeout=2)
    queued.result(timeout=2)
    ex.shutdown(wait=True)


def test_spawn_drops_job_when_backlog_is_full(monkeypatch):
    monkeypatch.setattr(threads, "_executor", _FullExecutor())
    assert threads.spawn(lambda: None) is None


def test_inbox_rejects_activity_when_backlog_is_full(monkeypatch):
    monkeypatch.setattr(_inbound, "_inbox_executor", _FullExecutor())
    status, message = asyncio.run(_inbound._submit_inbox({"type": "Follow"}))
    assert status == 503
    assert message == "Server busy"


def test_push_drops_notification_when_backlog_is_full(monkeypatch):
    monkeypatch.setattr(push, "_push_executor", _FullExecutor())
    push.send_push_to_user(1, "like")
