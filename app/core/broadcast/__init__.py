"""Timeline broadcast orchestration.

Public API (importable from app.core.broadcast):
- broadcast_post: main entry point that delivers a post to connected timeline streams.
- _broadcast_timeline: thread-safe wrapper used by post routes.
"""
from app.core.broadcast.delivery import _broadcast_timeline, broadcast_post

__all__ = ["_broadcast_timeline", "broadcast_post"]
