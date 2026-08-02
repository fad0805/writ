import logging

from app.core.broadcast.filter import _should_deliver_fast
from app.core.broadcast.prepare import _sanitize_post_payload, _resolve_parent_author
from app.core.broadcast.queries import (
    _load_follower_ids,
    _load_author_is_local,
    _load_stream_users,
    _load_home_follow_map,
    _load_post_for_filter,
)
from app.core.timeline_stream import _streams, _enqueue
from app.db.database import get_session
from app.utils.filter import should_deliver_post, _load_user_filters

logger = logging.getLogger(__name__)


def broadcast_post(
        post_json: dict,
        post_author_id: int,
        post_visibility: str,
        mentioned_ids = None):

    if post_visibility in ("unlisted",):
        post_visibility = "home"

    if post_visibility not in (
        "public", "home", "followers", "mention") or not _streams:
        return

    try:
        payload, mentioned_ids, parent_author_id, reply_ctx = _sanitize_post_payload(post_json)

        with get_session() as s:
            if parent_author_id is None:
                parent_author_id = _resolve_parent_author(
                    post_json, post_json.get("id"), reply_ctx, s)

            follower_ids = _load_follower_ids(s, post_author_id)
            author_is_local = _load_author_is_local(s, post_author_id)
            home_uids, stream_users = _load_stream_users(s, _streams)
            home_follows = _load_home_follow_map(s, home_uids)
            _db_post = _load_post_for_filter(
                s, post_json.get("id"), post_json.get("_boost_pointer_id"))

            _filter_cache: dict[int, dict | None] = {}

            for _, info in list(_streams.items()):
                uid = info["user_id"]
                tl = info["tl_type"]
                if post_json.get("type") != "update" and not _should_deliver_fast(uid, tl, post_author_id, post_visibility, follower_ids, author_is_local, mentioned_ids):
                    continue

                # Home/social: use unified filter (mention, reply, mute/block, keyword)
                if tl in ("home", "social") and post_visibility != "mention":
                    if uid not in _filter_cache:
                        _filter_cache[uid] = _load_user_filters(s, stream_users.get(uid))
                    viewer = stream_users.get(uid)
                    following_set = home_follows.get(uid, set()) | {uid}
                    if _db_post and not should_deliver_post(_db_post, s, viewer, tl, following_set, _filter_cache[uid]):
                        continue
                _enqueue(info["queue"], payload)

    except Exception as e:
        logger.error(f"BROADCAST_POST ERROR: {e}", exc_info=True)


def _broadcast_timeline(post_json, author_id, visibility):
    try:
        broadcast_post(post_json, author_id, visibility)
    except Exception as e:
        logger.error("Failed to broadcast timeline: %s", e, exc_info=True)
