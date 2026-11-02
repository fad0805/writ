"""Post edit indicator and edit-history tests."""

import app.core.activitypub._inbound_interactions as inbound
from app.db.database import get_session
from app.models import Post, PostEdit, User

ACTOR_URL = "https://remote.example/users/carol"
POST_URL = "https://remote.example/statuses/99"


def test_local_edit_records_history_and_indicator(client, auth_cookie, make_post):
    alice, cookie = auth_cookie("alice")
    post = make_post(alice, content="<p>original body</p>")

    initial = client.get(f"/api/posts/{post.id}", cookies=cookie).json()
    assert initial["is_edited"] is False
    assert initial["edited_at"] is None

    first = client.post(
        f"/api/posts/{post.id}/edit",
        data={"content": "<p>first edit</p>"},
        cookies=cookie,
    )
    assert first.status_code == 200
    assert first.json()["is_edited"] is True
    assert first.json()["edited_at"]

    history = client.get(f"/api/posts/{post.id}/edits", cookies=cookie)
    assert history.status_code == 200
    versions = history.json()["versions"]
    assert len(versions) == 2
    assert versions[0]["is_current"] is True
    assert versions[0]["version"] == 1
    assert "first edit" in versions[0]["content"]
    assert versions[1]["is_current"] is False
    assert versions[1]["version"] == 0
    assert "original body" in versions[1]["content"]

    second = client.post(
        f"/api/posts/{post.id}/edit",
        data={"content": "<p>second edit</p>"},
        cookies=cookie,
    )
    assert second.status_code == 200

    versions = client.get(f"/api/posts/{post.id}/edits", cookies=cookie).json()["versions"]
    assert [v["version"] for v in versions] == [2, 1, 0]
    assert versions[0]["is_current"] is True
    assert "second edit" in versions[0]["content"]
    assert "first edit" in versions[1]["content"]
    assert "original body" in versions[2]["content"]

    with get_session() as s:
        assert s.query(PostEdit).filter_by(post_id=post.id).count() == 2
        assert s.query(Post).get(post.id).edited_at is not None


def test_unchanged_edit_does_not_create_history(client, auth_cookie, make_post):
    alice, cookie = auth_cookie("alice")
    post = make_post(alice, content="same body")

    r = client.post(
        f"/api/posts/{post.id}/edit",
        data={"content": "<p>same body</p>"},
        cookies=cookie,
    )
    assert r.status_code == 200
    assert r.json()["is_edited"] is False
    with get_session() as s:
        assert s.query(PostEdit).filter_by(post_id=post.id).count() == 0


def test_remote_update_records_history(make_user):
    remote = make_user("carol")
    with get_session() as s:
        row = s.query(User).filter_by(id=remote.id).first()
        row.is_remote = True
        row.remote_url = ACTOR_URL
        row.username = "carol@remote.example"
        post = Post(
            author_id=remote.id,
            content="<p>remote original</p>",
            summary="",
            visibility="public",
            ap_id=POST_URL,
        )
        s.add(post)
        s.commit()
        post_id = post.id

    status, message = inbound._handle_update({
        "id": "https://remote.example/activities/update/1",
        "type": "Update",
        "actor": ACTOR_URL,
        "object": {
            "id": POST_URL,
            "type": "Note",
            "attributedTo": ACTOR_URL,
            "content": "<p>remote edited</p>",
            "summary": "edited CW",
            "updated": "2026-11-02T10:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
        },
    })

    assert status == 200
    assert message == "Updated"
    with get_session() as s:
        post = s.query(Post).get(post_id)
        assert "remote edited" in post.content
        assert post.summary == "edited CW"
        assert post.edited_at is not None
        edits = s.query(PostEdit).filter_by(post_id=post_id).all()
        assert len(edits) == 1
        assert "remote original" in edits[0].content
        assert edits[0].summary == ""


def test_edit_history_requires_visibility(client, auth_cookie, make_post):
    alice, alice_cookie = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    post = make_post(alice, content="<p>private original</p>", visibility="followers")
    client.post(
        f"/api/posts/{post.id}/edit",
        data={"content": "<p>private edit</p>"},
        cookies=alice_cookie,
    )

    assert client.get(f"/api/posts/{post.id}/edits", cookies=bob_cookie).status_code == 403
    assert client.get(f"/api/posts/{post.id}/edits", cookies=alice_cookie).status_code == 200
