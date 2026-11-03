"""Post creation/editing/deletion and content sanitization tests."""

from app.db.database import get_session
from app.models import Post, PostEdit
from app.utils.storage import get_storage


def test_create_post_public(client, auth_cookie):
    _, cookie = auth_cookie("alice")
    r = client.post("/api/posts", data={"content": "<p>hello world</p>"}, cookies=cookie)
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "hello world"
    assert data["visibility"] == "public"
    assert data["is_mine"] is True


def test_create_post_empty_content_rejected(client, auth_cookie):
    _, cookie = auth_cookie("alice")
    r = client.post("/api/posts", data={"content": "   "}, cookies=cookie)
    assert r.status_code == 400


def test_create_post_media_only_allowed(client, auth_cookie):
    _, cookie = auth_cookie("alice")
    r = client.post(
        "/api/posts",
        data={"content": "", "media_attachments": '[{"url": "/media/a.webp", "type": "image"}]'},
        cookies=cookie,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == ""
    assert len(data["media_attachments"]) == 1


def test_create_post_sanitizes_html(client, auth_cookie):
    _, cookie = auth_cookie("alice")
    r = client.post(
        "/api/posts",
        data={"content": '<p>hi <script>alert(1)</script><img src=x onerror=alert(2)></p>'},
        cookies=cookie,
    )
    assert r.status_code == 200
    data = r.json()
    assert "<script>" not in data["content"]
    assert "onerror" not in data["content"]
    assert "hi alert(1)" in data["content"]


def test_create_post_requires_auth(client):
    r = client.post("/api/posts", data={"content": "<p>hi</p>"})
    assert r.status_code == 401


def test_create_post_rejects_invalid_media_url(client, auth_cookie):
    _, cookie = auth_cookie("alice")
    r = client.post(
        "/api/posts",
        data={"content": "<p>media</p>", "media_attachments": '["javascript:alert(1)"]'},
        cookies=cookie,
    )
    assert r.status_code == 200
    assert r.json()["media_attachments"] == []


def test_get_post_detail(client, auth_cookie, make_post):
    alice, cookie = auth_cookie("alice")
    post = make_post(alice, content="<p>secret detail</p>")
    r = client.get(f"/api/posts/{post.id}", cookies=cookie)
    assert r.status_code == 200
    assert r.json()["content"] == "<p>secret detail</p>"


def test_edit_post_requires_author(client, auth_cookie, make_post):
    alice, _alice_cookie = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    post = make_post(alice, content="<p>original</p>")
    r = client.post(f"/api/posts/{post.id}/edit", data={"content": "<p>hacked</p>"}, cookies=bob_cookie)
    assert r.status_code == 403


def test_edit_post_by_author(client, auth_cookie, make_post):
    alice, alice_cookie = auth_cookie("alice")
    post = make_post(alice, content="<p>original</p>")
    r = client.post(f"/api/posts/{post.id}/edit", data={"content": "<p>edited</p>"}, cookies=alice_cookie)
    assert r.status_code == 200
    assert r.json()["content"] == "edited"


def test_edit_post_media_only_allowed(client, auth_cookie, make_post):
    alice, cookie = auth_cookie("alice")
    post = make_post(alice, content="")
    with get_session() as s:
        db_post = s.get(Post, post.id)
        db_post.media_attachments = [{"url": "/media/a.webp", "type": "image"}]
        s.commit()
    r = client.post(f"/api/posts/{post.id}/edit", data={"content": ""}, cookies=cookie)
    assert r.status_code == 200
    assert r.json()["content"] == ""


def test_delete_post_marks_deleted(client, auth_cookie, make_post):
    alice, alice_cookie = auth_cookie("alice")
    post = make_post(alice, content="<p>bye</p>")
    r = client.post(f"/api/posts/{post.id}/delete", cookies=alice_cookie)
    assert r.status_code == 200
    assert client.get(f"/api/posts/{post.id}", cookies=alice_cookie).status_code == 404
    with get_session() as s:
        db_post = s.query(Post).get(post.id)
        assert db_post.is_deleted is True


def test_delete_post_removes_its_media_but_keeps_shared_files(client, auth_cookie, make_post, monkeypatch):
    import app.routes.api._posts as posts_module

    monkeypatch.setattr(posts_module, "spawn", lambda fn, *args, **kwargs: fn(*args, **kwargs))
    user, cookie = auth_cookie("alice")
    storage = get_storage()
    keys = {
        "inline": "test_delete/inline.webp",
        "attachment": "test_delete/attachment.webp",
        "edit": "test_delete/edit.webp",
        "shared": "test_delete/shared.webp",
    }
    urls = {name: storage.save(key, name.encode()) for name, key in keys.items()}
    post = make_post(
        user,
        content=f'<p>inline</p><img src="{urls["inline"]}"><img src="{urls["shared"]}">',
    )
    make_post(user, content=f'<p>still here</p><img src="{urls["shared"]}">')
    with get_session() as s:
        db_post = s.query(Post).get(post.id)
        db_post.ap_id = ""
        db_post.media_attachments = [{"url": urls["attachment"], "type": "image"}]
        s.add(PostEdit(
            post_id=post.id,
            content=f'<p>old version</p><img src="{urls["edit"]}">',
            summary="",
            visibility="public",
            is_sensitive=False,
        ))
        s.commit()

    try:
        r = client.post(f"/api/posts/{post.id}/delete", cookies=cookie)
        assert r.status_code == 200
        assert not storage.exists(keys["inline"])
        assert not storage.exists(keys["attachment"])
        assert not storage.exists(keys["edit"])
        assert storage.exists(keys["shared"])
    finally:
        for key in keys.values():
            storage.delete(key)


def test_orphan_cleanup_ignores_media_of_deleted_posts(client, auth_cookie, make_post):
    from app.utils.media_refs import collect_referenced_media_keys

    user, _cookie = auth_cookie("alice")
    storage = get_storage()
    key = "test_delete/deleted_only.webp"
    url = storage.save(key, b"deleted")
    post = make_post(user, content=f'<img src="{url}">')
    try:
        with get_session() as s:
            db_post = s.query(Post).get(post.id)
            db_post.is_deleted = True
            db_post.media_attachments = [{"url": url, "type": "image"}]
            s.commit()
        with get_session() as s:
            used = collect_referenced_media_keys(s, storage)
        assert key not in used
    finally:
        storage.delete(key)


def test_delete_post_others_forbidden(client, auth_cookie, make_post):
    alice, _ = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    post = make_post(alice, content="<p>mine</p>")
    assert client.post(f"/api/posts/{post.id}/delete", cookies=bob_cookie).status_code == 403


def test_reply_to_post(client, auth_cookie, make_post):
    alice, alice_cookie = auth_cookie("alice")
    parent = make_post(alice, content="<p>parent</p>")
    r = client.post("/api/posts", data={"content": "<p>reply</p>", "parent_id": str(parent.id)}, cookies=alice_cookie)
    assert r.status_code == 200
    assert r.json()["reply_context"]["id"] == parent.id
