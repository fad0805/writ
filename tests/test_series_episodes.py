"""Series (novel) and episode CRUD tests."""

from app.db.database import get_session
from app.models import Episode, Novel
from app.utils.storage import get_storage


def _create_series(client, cookie, title="My Novel", **extra):
    data = {
        "title": title,
        "description": "A test novel",
        "tags": "fantasy",
        "visibility": "public",
        "status": "ongoing",
        **extra,
    }
    return client.post("/api/series/new", data=data, cookies=cookie)


def test_create_series(client, auth_cookie):
    _, cookie = auth_cookie("alice")
    r = _create_series(client, cookie)
    assert r.status_code == 200
    with get_session() as s:
        assert s.query(Novel).count() == 1


def test_create_series_requires_title(client, auth_cookie):
    _, cookie = auth_cookie("alice")
    r = _create_series(client, cookie, title="   ")
    assert r.status_code == 400


def test_create_series_requires_auth(client):
    r = _create_series(client, {})
    assert r.status_code == 401


def test_series_listing_shows_published(client, auth_cookie):
    _, cookie = auth_cookie("alice")
    _create_series(client, cookie, title="Published One")
    r = client.get("/api/series")
    assert r.status_code == 200
    titles = [n["title"] for n in r.json()["novels"]]
    assert "Published One" in titles


def test_my_series_lists_own_only(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    _create_series(client, alice_cookie, title="Alice's")
    _create_series(client, bob_cookie, title="Bob's")
    r = client.get("/api/series/my", cookies=alice_cookie)
    titles = [n["title"] for n in r.json()["novels"]]
    assert "Alice's" in titles
    assert "Bob's" not in titles


def test_edit_series_by_author(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    novel_id = _create_series(client, alice_cookie, title="Before").json()["novel_id"]
    r = client.post(f"/api/series/{novel_id}/edit", data={"title": "After"}, cookies=alice_cookie)
    assert r.status_code == 200
    with get_session() as s:
        assert s.query(Novel).get(novel_id).title == "After"


def test_edit_series_others_forbidden(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    novel_id = _create_series(client, alice_cookie).json()["novel_id"]
    assert client.post(f"/api/series/{novel_id}/edit", data={"title": "Hacked"}, cookies=bob_cookie).status_code == 404


def test_delete_series(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    novel_id = _create_series(client, alice_cookie).json()["novel_id"]
    r = client.post(f"/api/series/{novel_id}/delete", cookies=alice_cookie)
    assert r.status_code == 200
    with get_session() as s:
        assert s.query(Novel).get(novel_id) is None


def test_delete_episode_removes_its_media(client, auth_cookie, monkeypatch):
    _alice, cookie = auth_cookie("alice")
    novel_id = _create_series(client, cookie).json()["novel_id"]
    ep_id = client.post(
        f"/api/series/{novel_id}/episodes/new",
        data={"title": "Chapter 1", "content": "<p>body</p>", "is_published": "true"},
        cookies=cookie,
    ).json()["episode_id"]

    import app.routes.api._episodes as episodes_module

    monkeypatch.setattr(episodes_module, "spawn", lambda fn, *args, **kwargs: fn(*args, **kwargs))
    storage = get_storage()
    keys = {
        "inline": "test_episode_delete/inline.webp",
        "image": "test_episode_delete/image.webp",
        "audio": "test_episode_delete/audio.mp3",
    }
    urls = {name: storage.save(key, name.encode()) for name, key in keys.items()}
    try:
        with get_session() as s:
            episode = s.query(Episode).get(ep_id)
            episode.content = f'<p>body</p><img src="{urls["inline"]}">'
            episode.image_urls = [urls["image"]]
            episode.audio_url = urls["audio"]
            s.commit()

        r = client.post(f"/api/series/{novel_id}/episodes/{ep_id}/delete", cookies=cookie)
        assert r.status_code == 200
        assert not storage.exists(keys["inline"])
        assert not storage.exists(keys["image"])
        assert not storage.exists(keys["audio"])
    finally:
        for key in keys.values():
            storage.delete(key)


def test_create_episode(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    novel_id = _create_series(client, alice_cookie).json()["novel_id"]
    r = client.post(
        f"/api/series/{novel_id}/episodes/new",
        data={"title": "Chapter 1", "content": "<p>Once upon a time...</p>", "is_published": "true"},
        cookies=alice_cookie,
    )
    assert r.status_code == 200
    assert r.json()["episode_id"]
    with get_session() as s:
        ep = s.query(Episode).get(r.json()["episode_id"])
        assert ep.episode_number == 1
        assert ep.is_published is True


def test_create_episode_requires_content(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    novel_id = _create_series(client, alice_cookie).json()["novel_id"]
    r = client.post(
        f"/api/series/{novel_id}/episodes/new",
        data={"title": "Empty", "content": "", "is_published": "true"},
        cookies=alice_cookie,
    )
    assert r.status_code == 400


def test_create_episode_requires_own_series(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    novel_id = _create_series(client, alice_cookie).json()["novel_id"]
    r = client.post(
        f"/api/series/{novel_id}/episodes/new",
        data={"title": "Hack", "content": "<p>x</p>", "is_published": "true"},
        cookies=bob_cookie,
    )
    assert r.status_code == 404


def test_get_episode(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    novel_id = _create_series(client, alice_cookie).json()["novel_id"]
    ep_id = client.post(
        f"/api/series/{novel_id}/episodes/new",
        data={"title": "Ch", "content": "<p>body</p>", "is_published": "true"},
        cookies=alice_cookie,
    ).json()["episode_id"]
    r = client.get(f"/api/series/{novel_id}/episodes/{ep_id}", cookies=alice_cookie)
    assert r.status_code == 200
    assert r.json()["episode"]["title"] == "Ch"
