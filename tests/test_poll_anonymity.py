from datetime import UTC, datetime, timedelta

from app.core import push
from app.core.activitypub import _inbound_create
from app.core.auth import hash_password
from app.db.database import get_session
from app.models import Notification, Post, User, Vote
from app.routes.api.interactions import notify as notify_mod


def _make_remote_user(username: str) -> User:
    with get_session() as s:
        user = User(
            username=username,
            display_name="Remote",
            email=f"{username}@remote.example",
            password_hash=hash_password("test-password"),
            private_key="",
            public_key="",
            is_remote=True,
            remote_url=f"https://remote.example/users/{username}",
            inbox_url=f"https://remote.example/users/{username}/inbox",
        )
        s.add(user)
        s.commit()
        s.refresh(user)
        return user


def test_vote_push_notification_is_dropped(monkeypatch):
    class _FailExecutor:
        def submit(self, *args, **kwargs):
            raise AssertionError("vote push must not be queued")

    monkeypatch.setattr(push, "_push_executor", _FailExecutor())
    push.send_push_to_user(1, "vote", "remoteuser")


def test_remote_poll_vote_does_not_notify_poll_author(make_user, make_post, monkeypatch):
    author = make_user("pollauthor")
    post = make_post(
        author,
        content="",
        poll_data={
            "options": [{"text": "A", "votes_count": 0}, {"text": "B", "votes_count": 0}],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )
    voter = _make_remote_user("pollvoter")

    calls = []
    monkeypatch.setattr(_inbound_create, "_resolve_actor", lambda *a, **k: voter)
    monkeypatch.setattr(_inbound_create, "send_push_to_user", lambda *a, **k: calls.append("push"))
    monkeypatch.setattr(_inbound_create, "broadcast_notif_sound", lambda *a, **k: calls.append("sound"))
    monkeypatch.setattr(_inbound_create, "broadcast_refresh_notifs", lambda *a, **k: calls.append("refresh"))
    monkeypatch.setattr(_inbound_create, "broadcast_post", lambda *a, **k: None)
    monkeypatch.setattr(_inbound_create, "_broadcast_emoji_list", lambda *a, **k: [])

    status, message = _inbound_create._handle_create(
        {
            "type": "Create",
            "actor": voter.actor_uri(),
            "object": {
                "id": "https://remote.example/votes/1",
                "type": "Note",
                "name": "A",
                "attributedTo": voter.actor_uri(),
                "inReplyTo": post.ap_id,
                "to": [author.actor_uri()],
            },
        }
    )

    assert (status, message) == (200, "voted")
    assert calls == []

    with get_session() as s:
        vote = s.query(Vote).filter_by(post_id=post.id, user_id=voter.id).one()
        assert vote.option_index == 0
        assert s.query(Notification).filter_by(
            user_id=author.id, notification_type="vote"
        ).count() == 0
        updated = s.query(Post).get(post.id)
        assert updated.poll_data["options"][0]["votes_count"] == 1


def test_notification_api_hides_legacy_vote_notifications(auth_cookie, make_user, make_post, client):
    author, cookie = auth_cookie("pollauthor2")
    voter = make_user("pollvoter2")
    post = make_post(
        author,
        content="",
        poll_data={"options": [{"text": "A", "votes_count": 1}], "expires_at": None},
    )
    with get_session() as s:
        s.add(Notification(
            user_id=author.id,
            from_user_id=voter.id,
            notification_type="vote",
            post_id=post.id,
        ))
        s.commit()

    notify_mod._unread_cache.clear()
    r = client.get("/api/notifications", cookies=cookie)
    assert r.status_code == 200
    assert r.json()["notifications"] == []

    r = client.get("/api/notifications?filter_type=vote", cookies=cookie)
    assert r.status_code == 200
    assert r.json()["notifications"] == []

    r = client.get("/api/notifications/unread-count", cookies=cookie)
    assert r.status_code == 200
    assert r.json()["count"] == 0
