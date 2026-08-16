"""Auto-delete (user.post_lifetime) worker tests.

`_run_auto_delete_once` is the single-pass unit of work extracted from the
`auto_delete_expired_posts` loop, so tests can drive it directly without
waiting for the 3 AM schedule.
"""

import datetime

from app.core.workers import _run_auto_delete_once
from app.db.database import get_session
from app.models import Bookmark, Like, Notification, Post, User


def _age(post, days):
    """Rewrite a post's created_at so it looks `days` old."""
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
    with get_session() as s:
        s.query(Post).filter_by(id=post.id).update({"created_at": cutoff})
        s.commit()
    return post


def _set_lifetime(user, days, exceptions=None):
    with get_session() as s:
        u = s.query(User).get(user.id)
        u.post_lifetime = days
        u.post_lifetime_exceptions = list(exceptions or [])
        s.commit()
    return user


def _post_ids():
    with get_session() as s:
        return {row[0] for row in s.query(Post.id).all()}


def test_deletes_only_expired_posts(client, make_user, make_post):
    alice = make_user("alice")
    _set_lifetime(alice, 7)
    old = _age(make_post(alice), 30)
    recent = _age(make_post(alice), 1)
    assert _run_auto_delete_once() == 1
    ids = _post_ids()
    assert old.id not in ids
    assert recent.id in ids


def test_no_op_when_lifetime_zero(client, make_user, make_post):
    alice = make_user("alice")
    _set_lifetime(alice, 0)
    old = _age(make_post(alice), 30)
    assert _run_auto_delete_once() == 0
    assert old.id in _post_ids()


def test_only_targets_user_with_lifetime(client, make_user, make_post):
    alice = make_user("alice")
    bob = make_user("bob")
    _set_lifetime(alice, 7)
    _set_lifetime(bob, 0)
    old_alice = _age(make_post(alice), 30)
    old_bob = _age(make_post(bob), 30)
    assert _run_auto_delete_once() == 1
    ids = _post_ids()
    assert old_alice.id not in ids
    assert old_bob.id in ids


def test_skips_deleted_posts(client, make_user, make_post):
    alice = make_user("alice")
    _set_lifetime(alice, 7)
    _age(make_post(alice, is_deleted=True), 30)
    assert _run_auto_delete_once() == 0
    assert len(_post_ids()) == 1


def test_flag_exceptions_keep_posts(client, make_user, make_post):
    alice = make_user("alice")
    _set_lifetime(alice, 7, exceptions=["pinned", "dm", "poll", "media"])
    pinned = _age(make_post(alice), 30)
    dm = _age(make_post(alice), 30)
    poll = _age(make_post(alice), 30)
    media = _age(make_post(alice), 30)
    normal = _age(make_post(alice), 30)
    with get_session() as s:
        s.query(Post).filter_by(id=pinned.id).update({"is_pinned": True})
        s.query(Post).filter_by(id=dm.id).update({"is_dm": True})
        s.query(Post).filter_by(id=poll.id).update({"poll_data": {"options": []}})
        s.query(Post).filter_by(id=media.id).update({"media_attachments": [{"url": "http://x", "type": "image"}]})
        s.commit()
    assert _run_auto_delete_once() == 1
    ids = _post_ids()
    assert pinned.id in ids
    assert dm.id in ids
    assert poll.id in ids
    assert media.id in ids
    assert normal.id not in ids


def test_liked_bookmarked_exceptions_keep_posts(client, make_user, make_post):
    alice = make_user("alice")
    _set_lifetime(alice, 7, exceptions=["liked", "bookmarked"])
    liked = _age(make_post(alice), 30)
    bookmarked = _age(make_post(alice), 30)
    with get_session() as s:
        s.add(Like(user_id=alice.id, post_id=liked.id))
        s.add(Bookmark(user_id=alice.id, post_id=bookmarked.id))
        s.commit()
    assert _run_auto_delete_once() == 0
    ids = _post_ids()
    assert liked.id in ids
    assert bookmarked.id in ids


def test_deletes_related_rows(client, make_user, make_post):
    alice = make_user("alice")
    bob = make_user("bob")
    _set_lifetime(alice, 7)
    post = _age(make_post(alice), 30)
    with get_session() as s:
        s.add(Like(user_id=bob.id, post_id=post.id))
        s.add(Bookmark(user_id=bob.id, post_id=post.id))
        s.add(Notification(
            user_id=bob.id,
            from_user_id=alice.id,
            notification_type="like",
            post_id=post.id,
        ))
        s.commit()
    assert _run_auto_delete_once() == 1
    with get_session() as s:
        assert s.query(Like).filter_by(post_id=post.id).first() is None
        assert s.query(Bookmark).filter_by(post_id=post.id).first() is None
        assert s.query(Notification).filter_by(post_id=post.id).first() is None
