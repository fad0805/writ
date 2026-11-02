"""Remote post re-fetch / re-announce edit refresh tests.

Mastodon sends an Update for public/unlisted posts to servers that boosted
them, but a local copy can also miss an edit (boost arrived after the edit,
server was down, non-Mastodon instance, ...). Re-fetching or re-announcing an
already-stored remote post must refresh the mutable fields instead of returning
the stale row forever.
"""

import app.core.activitypub._fetch_post as fetch_post
import app.core.activitypub._inbound_interactions as inbound
from app.db.database import get_session
from app.models import Post, Tag, User

ACTOR_URL = "https://remote.example/users/carol"
POST_URL = "https://remote.example/statuses/123"


def _make_remote_user(make_user, username="carol"):
    user = make_user(username)
    with get_session() as s:
        row = s.query(User).filter_by(id=user.id).first()
        row.is_remote = True
        row.remote_url = ACTOR_URL
        row.username = f"{username}@remote.example"
        s.commit()
    return user


def _make_post(author_id, *, content="<p>old body</p>", visibility="public"):
    with get_session() as s:
        post = Post(
            author_id=author_id,
            content=content,
            summary="",
            visibility=visibility,
            ap_id=POST_URL,
        )
        s.add(post)
        s.commit()
        return post.id


def _remote_note(**overrides):
    note = {
        "id": POST_URL,
        "type": "Note",
        "attributedTo": ACTOR_URL,
        "content": "<p>edited body</p>",
        "summary": "edited CW",
        "sensitive": True,
        "to": [f"{ACTOR_URL}/followers"],
        "cc": [],
        "tag": [{"type": "Hashtag", "name": "#updated"}],
        "attachment": [{
            "type": "Image",
            "mediaType": "image/png",
            "url": "https://remote.example/media/1.png",
        }],
    }
    note.update(overrides)
    return note


class _FakeResponse:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_fetch_remote_post_refreshes_existing_row(make_user, monkeypatch):
    remote = _make_remote_user(make_user)
    post_id = _make_post(remote.id)
    with get_session() as s:
        pointer = Post(
            author_id=remote.id,
            content="",
            visibility="public",
            boost_of_id=post_id,
            ap_id="https://remote.example/boost/1",
        )
        s.add(pointer)
        s.commit()
        pointer_id = pointer.id

    note = _remote_note()
    monkeypatch.setattr(fetch_post, "validated_get", lambda url, **kw: _FakeResponse(note))
    monkeypatch.setattr(fetch_post, "_resolve_actor", lambda url, **kw: remote)
    monkeypatch.setattr(fetch_post, "_cache_remote_media", lambda url: "/uploads/remote/1.png")

    signer = make_user("local_signer")
    with get_session() as s:
        result = fetch_post._fetch_remote_post(POST_URL, signer, s)
        s.commit()
        assert result is not None
        assert result.id == post_id
        assert "edited body" in result.content
        assert result.summary == "edited CW"
        assert result.visibility == "followers"
        assert result.is_sensitive is True
        assert result.media_attachments == [{"url": "/uploads/remote/1.png", "type": "image"}]
        assert [t.name for t in result.tag_list] == ["updated"]

    with get_session() as s:
        # 부스트 포인터는 원글의 공개범위 변경을 따라간다.
        assert s.query(Post).get(pointer_id).visibility == "followers"
        assert s.query(Tag).filter_by(name="updated").first() is not None


def test_fetch_remote_post_can_skip_refresh(make_user, monkeypatch):
    remote = _make_remote_user(make_user)
    post_id = _make_post(remote.id)

    note = _remote_note()
    monkeypatch.setattr(fetch_post, "validated_get", lambda url, **kw: _FakeResponse(note))

    signer = make_user("local_signer")
    with get_session() as s:
        result = fetch_post._fetch_remote_post(POST_URL, signer, s, refresh_existing=False)
        assert result is not None
        assert result.id == post_id
        assert "old body" in result.content


def test_announce_refreshes_existing_post_before_dedup(make_user, monkeypatch):
    """같은 부스트가 다시 들어와도 'Already boosted'로 끝내기 전에 원글을 갱신한다."""
    remote = _make_remote_user(make_user)
    booster = _make_remote_user(make_user, username="booster")
    with get_session() as s:
        booster_row = s.query(User).filter_by(id=booster.id).first()
        booster_row.remote_url = "https://remote.example/users/booster"
        booster_row.username = "booster@remote.example"
        s.commit()

    post_id = _make_post(remote.id)
    with get_session() as s:
        from app.models import Boost

        s.add(Boost(user_id=booster.id, post_id=post_id, ap_id="https://remote.example/boost/1"))
        s.commit()

    calls = []

    def _fake_fetch(url, signer, session, *args, **kwargs):
        calls.append(url)
        post = session.query(Post).filter_by(ap_id=url).first()
        assert post is not None
        post.content = "<p>edited by re-announce</p>"
        session.flush()
        return post

    monkeypatch.setattr(inbound, "_resolve_actor", lambda url, **kw: booster)
    monkeypatch.setattr(inbound, "_get_instance_actor", lambda session: make_user("instance_actor"))
    monkeypatch.setattr(inbound, "_fetch_remote_post", _fake_fetch)

    status, message = inbound._handle_announce({
        "id": "https://remote.example/activities/announce/2",
        "type": "Announce",
        "actor": "https://remote.example/users/booster",
        "object": POST_URL,
    })

    assert status == 200
    assert message == "Already boosted"
    assert calls == [POST_URL]
    with get_session() as s:
        assert "edited by re-announce" in s.query(Post).get(post_id).content
