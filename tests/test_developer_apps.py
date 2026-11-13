"""개발자 설정 API — OAuth 앱 등록과 개인 액세스 토큰 테스트."""

import secrets

from app.db.database import get_session
from app.models import MastodonAccessToken, MastodonApp


def _create_app(client, cookies, **overrides):
    payload = {
        "client_name": "테스트 앱",
        "website": "https://client.example",
        "redirect_uris": ["https://client.example/callback", "urn:ietf:wg:oauth:2.0:oob"],
        "scopes": ["read", "write"],
    }
    payload.update(overrides)
    return client.post("/api/developer/apps", json=payload, cookies=cookies)


def _create_token(client, cookies, app_id):
    return client.post(f"/api/developer/apps/{app_id}/token", cookies=cookies)


def test_developer_apps_require_login(client):
    r = client.get("/api/developer/apps")
    assert r.status_code == 401


def test_ownerless_app_is_not_visible_or_manageable(client, auth_cookie):
    # 공개 POST /api/v1/apps 로 만들어진 기존 앱은 소유자가 없으므로
    # 개발자 설정의 "내 애플리케이션" 목록에 노출되지 않는다.
    with get_session() as s:
        app = MastodonApp(
            client_name="기존 API 앱",
            client_id=secrets.token_urlsafe(24),
            client_secret=secrets.token_urlsafe(24),
            redirect_uris="urn:ietf:wg:oauth:2.0:oob",
            scopes="read",
        )
        s.add(app)
        s.commit()
        s.refresh(app)
        app_id = app.id

    _user, user_cookies = auth_cookie("bob")
    r = client.get("/api/developer/apps", cookies=user_cookies)
    assert r.status_code == 200
    assert r.json()["apps"] == []

    _admin, admin_cookies = auth_cookie("alice", role="admin")
    r = client.get("/api/developer/apps", cookies=admin_cookies)
    assert r.status_code == 200
    assert all(a["id"] != app_id for a in r.json()["apps"])

    r = client.post(f"/api/developer/apps/{app_id}/token", cookies=admin_cookies)
    assert r.status_code == 404

    r = client.delete(f"/api/developer/apps/{app_id}", cookies=admin_cookies)
    assert r.status_code == 404


def test_create_and_list_developer_app(client, auth_cookie):
    user, cookies = auth_cookie("alice")

    r = _create_app(client, cookies)
    assert r.status_code == 200
    app = r.json()["app"]
    assert app["name"] == "테스트 앱"
    assert app["website"] == "https://client.example"
    assert app["redirect_uris"] == [
        "https://client.example/callback",
        "urn:ietf:wg:oauth:2.0:oob",
    ]
    assert app["scopes"] == ["read", "write"]
    assert app["client_id"]
    assert app["client_secret"]
    assert app["tokens"] == []

    with get_session() as s:
        saved = s.query(MastodonApp).filter_by(id=app["id"]).one()
        assert saved.user_id == user.id

    r = client.get("/api/developer/apps", cookies=cookies)
    assert r.status_code == 200
    assert [a["id"] for a in r.json()["apps"]] == [app["id"]]


def test_apps_are_private_to_owner(client, auth_cookie):
    _alice, alice_cookies = auth_cookie("alice")
    _bob, bob_cookies = auth_cookie("bob")

    r = _create_app(client, alice_cookies)
    app_id = r.json()["app"]["id"]

    r = client.get("/api/developer/apps", cookies=bob_cookies)
    assert r.status_code == 200
    assert r.json()["apps"] == []

    r = client.delete(f"/api/developer/apps/{app_id}", cookies=bob_cookies)
    assert r.status_code == 404

    r = client.post(f"/api/developer/apps/{app_id}/token", cookies=bob_cookies)
    assert r.status_code == 404


def test_create_app_rejects_invalid_input(client, auth_cookie):
    _user, cookies = auth_cookie("alice")

    assert _create_app(client, cookies, client_name="").status_code == 400
    assert _create_app(client, cookies, redirect_uris=[]).status_code == 400
    assert _create_app(client, cookies, redirect_uris=["callback"]).status_code == 400
    assert _create_app(client, cookies, scopes=["not-a-scope"]).status_code == 400
    assert _create_app(client, cookies, scopes=[]).status_code == 400
    assert _create_app(client, cookies, website="not-a-url").status_code == 400


def test_non_staff_cannot_request_admin_scopes(client, auth_cookie):
    _user, cookies = auth_cookie("alice")
    r = _create_app(client, cookies, scopes=["admin:read"])
    assert r.status_code == 403


def test_staff_can_request_admin_scopes(client, auth_cookie):
    _user, cookies = auth_cookie("alice", role="admin")
    r = _create_app(client, cookies, scopes=["admin:read"])
    assert r.status_code == 200
    assert r.json()["app"]["scopes"] == ["admin:read"]


def test_access_token_works_and_scope_is_enforced(client, auth_cookie):
    _user, cookies = auth_cookie("alice")
    app_id = _create_app(client, cookies, scopes=["read"]).json()["app"]["id"]

    r = _create_token(client, cookies, app_id)
    assert r.status_code == 200
    token = r.json()["token"]
    assert token["scopes"] == ["read"]

    headers = {"Authorization": f"Bearer {token['access_token']}"}
    r = client.get("/api/v1/accounts/verify_credentials", headers=headers)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"

    # read 토큰으로는 게시물을 작성할 수 없다.
    r = client.post("/api/v1/statuses", headers=headers, json={"status": "hello"})
    assert r.status_code == 403
    assert "scope" in r.json()["detail"]

    # 앱 목록에도 발급한 토큰이 표시된다.
    r = client.get("/api/developer/apps", cookies=cookies)
    app = next(a for a in r.json()["apps"] if a["id"] == app_id)
    assert [t["id"] for t in app["tokens"]] == [token["id"]]


def test_write_token_can_create_status(client, auth_cookie):
    _user, cookies = auth_cookie("alice")
    app_id = _create_app(client, cookies, scopes=["write"]).json()["app"]["id"]
    token = _create_token(client, cookies, app_id).json()["token"]

    headers = {"Authorization": f"Bearer {token['access_token']}"}
    r = client.post("/api/v1/statuses", headers=headers, json={"status": "hello"})
    assert r.status_code == 200
    assert "hello" in r.json()["content"]


def test_revoke_token(client, auth_cookie):
    _user, cookies = auth_cookie("alice")
    app_id = _create_app(client, cookies, scopes=["read"]).json()["app"]["id"]
    token = _create_token(client, cookies, app_id).json()["token"]
    headers = {"Authorization": f"Bearer {token['access_token']}"}

    r = client.delete(f"/api/developer/tokens/{token['id']}", cookies=cookies)
    assert r.status_code == 200

    r = client.get("/api/v1/accounts/verify_credentials", headers=headers)
    assert r.status_code == 401

    with get_session() as s:
        assert s.query(MastodonAccessToken).filter_by(id=token["id"]).first() is None


def test_delete_app_revokes_its_tokens(client, auth_cookie):
    _user, cookies = auth_cookie("alice")
    app_id = _create_app(client, cookies, scopes=["read"]).json()["app"]["id"]
    token = _create_token(client, cookies, app_id).json()["token"]
    headers = {"Authorization": f"Bearer {token['access_token']}"}

    r = client.delete(f"/api/developer/apps/{app_id}", cookies=cookies)
    assert r.status_code == 200

    r = client.get("/api/v1/accounts/verify_credentials", headers=headers)
    assert r.status_code == 401

    with get_session() as s:
        assert s.query(MastodonAccessToken).filter_by(app_id=app_id).count() == 0
