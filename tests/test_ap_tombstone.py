"""삭제된 포스트의 AP 응답 검증 — 전문 노출 금지, Tombstone 반환."""


def _ap_get(client, url):
    return client.get(url, headers={"Accept": "application/activity+json"})


def test_deleted_post_by_number_returns_tombstone(client, auth_cookie, make_post):
    user, cookie = auth_cookie("alice")
    post = make_post(user, content="<p>secret body</p>", is_deleted=True)

    r = _ap_get(client, f"/@alice/{post.number}")
    assert r.status_code == 410
    body = r.json()
    assert body["type"] == "Tombstone"
    assert "secret body" not in r.text
    assert "content" not in body


def test_live_post_by_number_still_serves_note(client, auth_cookie, make_post):
    user, _cookie = auth_cookie("bob")
    post = make_post(user, content="<p>alive</p>")

    r = _ap_get(client, f"/@bob/{post.number}")
    assert r.status_code == 200
    assert r.json()["type"] in ("Note", "Article", "Page")


def test_deleted_post_by_id_returns_tombstone(client, auth_cookie, make_post):
    user, _cookie = auth_cookie("carol")
    post = make_post(user, content="<p>gone soon</p>", is_deleted=True)

    r = _ap_get(client, f"/posts/{post.id}")
    assert r.status_code == 410
    assert r.json()["type"] == "Tombstone"
    assert "gone soon" not in r.text


def test_missing_post_by_id_is_404(client):
    assert _ap_get(client, "/posts/999999").status_code == 404


def test_by_number_api_deleted_post_tombstone(client, auth_cookie, make_post):
    from app.routes.api._resolve import resolve_router  # noqa: F401 라우트 등록 확인용

    user, _cookie = auth_cookie("dave")
    post = make_post(user, content="<p>resolve leak?</p>", is_deleted=True)

    r = _ap_get(client, f"/api/by-number/dave/{post.number}")
    assert r.status_code == 410
    assert r.json()["type"] == "Tombstone"
    assert "resolve leak?" not in r.text
