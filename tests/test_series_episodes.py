"""Series (novel) and episode CRUD tests."""

from sqlalchemy import event

from app.db.database import engine, get_session
from app.models import Episode, Novel, SeriesFollow
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


def test_series_detail_does_not_select_episode_content(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    novel_id = _create_series(client, alice_cookie).json()["novel_id"]
    client.post(
        f"/api/series/{novel_id}/episodes/new",
        data={
            "title": "Long chapter",
            "content": "<p>" + "x" * 100_000 + "</p>",
            "is_published": "true",
        },
        cookies=alice_cookie,
    )

    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        upper = statement.lstrip().upper()
        if upper.startswith("SELECT") and "FROM EPISODES" in upper:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        r = client.get(f"/api/series/{novel_id}", cookies=alice_cookie)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert r.status_code == 200
    assert statements
    assert all("EPISODES.CONTENT" not in stmt.upper() for stmt in statements)
    assert "content" not in r.json()["episodes"][0]


def test_episode_pagination(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    novel_id = _create_series(client, alice_cookie).json()["novel_id"]
    with get_session() as s:
        s.add_all([
            Episode(
                novel_id=novel_id,
                episode_number=i,
                title=f"Ch {i}",
                content="<p>body</p>",
                is_published=(i != 25),
            )
            for i in range(1, 26)
        ])
        s.commit()

    first = client.get(f"/api/series/{novel_id}?limit=10", cookies=alice_cookie).json()
    assert [e["episode_number"] for e in first["episodes"]] == list(range(1, 11))
    assert first["episodes_total"] == 25
    assert first["episodes_has_more"] is True

    second = client.get(
        f"/api/series/{novel_id}/episodes?limit=10&offset=10", cookies=alice_cookie
    ).json()
    assert [e["episode_number"] for e in second["episodes"]] == list(range(11, 21))
    assert second["total"] == 25
    assert second["has_more"] is True

    last = client.get(
        f"/api/series/{novel_id}/episodes?limit=10&offset=20", cookies=alice_cookie
    ).json()
    assert [e["episode_number"] for e in last["episodes"]] == [21, 22, 23, 24, 25]
    assert last["has_more"] is False

    # 다른 사용자는 미공개 에피소드를 페이지 총개수에서도 제외한다.
    other = client.get(f"/api/series/{novel_id}?limit=10", cookies=bob_cookie).json()
    assert other["episodes_total"] == 24
    assert 25 not in [e["episode_number"] for e in other["episodes"]]
    assert "views" not in other["episodes"][0]


def test_series_list_batches_relations(client, auth_cookie):
    alice, alice_cookie = auth_cookie("alice")
    first_id = _create_series(client, alice_cookie, title="First", tags="fantasy mystery").json()["novel_id"]

    def list_with_query_count():
        count = 0

        def capture(conn, cursor, statement, parameters, context, executemany):
            nonlocal count
            if statement.lstrip().upper().startswith("SELECT"):
                count += 1

        event.listen(engine, "before_cursor_execute", capture)
        try:
            r = client.get("/api/series?limit=100")
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert r.status_code == 200
        return count, r.json()

    one_count, one_data = list_with_query_count()
    assert [n["id"] for n in one_data["novels"]] == [first_id]

    _, bob_cookie = auth_cookie("bob")
    _, carol_cookie = auth_cookie("carol")
    for name, cookie in (("Second", bob_cookie), ("Third", carol_cookie)):
        _create_series(client, cookie, title=name, tags="fantasy mystery")
    with get_session() as s:
        for novel in s.query(Novel).all():
            s.add(SeriesFollow(user_id=alice.id, novel_id=novel.id))
        s.commit()

    many_count, many_data = list_with_query_count()
    assert len(many_data["novels"]) == 3
    # 시리즈 수가 늘어나도 관계 조회 쿼리 수는 증가하지 않는다.
    assert many_count == one_count
    for novel in many_data["novels"]:
        assert novel["author"]["username"] in ("alice", "bob", "carol")
        assert novel["tags"] == "fantasy mystery"
        assert novel["followers_count"] == 1
