"""OAuth authorization_code 흐름 보안 회귀 테스트.

- 등록되지 않은 redirect_uri로 인증 코드 발급 차단
- 토큰 교환 시 redirect_uri 필수 일치
- 인증 코드 만료(10분)
- 교환 시 스코프 확대 차단
"""

import secrets
from datetime import UTC, datetime, timedelta

from app.db.database import get_session
from app.models import MastodonAccessToken, MastodonApp, MastodonAuthorizationCode


def _make_app(
    redirect_uris: str = "https://client.example/callback\nurn:ietf:wg:oauth:2.0:oob",
    scopes: str = "read write push",
) -> MastodonApp:
    with get_session() as s:
        app = MastodonApp(
            client_name="test-client",
            client_id=secrets.token_urlsafe(24),
            client_secret=secrets.token_urlsafe(24),
            redirect_uris=redirect_uris,
            scopes=scopes,
        )
        s.add(app)
        s.commit()
        s.refresh(app)
        return app


def _authorize(client, app_obj, username, redirect_uri, password="test-password"):
    return client.post(
        "/api/oauth/authorize",
        json={
            "client_id": app_obj.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "read",
            "username": username,
            "password": password,
        },
    )


def _insert_code(
    app_id,
    user_id,
    redirect_uri="https://client.example/callback",
    age_seconds=0,
    scopes="read",
):
    code = secrets.token_urlsafe(32)
    with get_session() as s:
        s.add(
            MastodonAuthorizationCode(
                code=code,
                app_id=app_id,
                user_id=user_id,
                redirect_uri=redirect_uri,
                scopes=scopes,
                created_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
            )
        )
        s.commit()
    return code


def test_authorize_rejects_unregistered_redirect(client, make_user):
    make_user("alice")
    app_obj = _make_app()
    r = _authorize(client, app_obj, "alice", "https://evil.example/steal")
    assert r.status_code == 400


def test_authorize_rejects_scope_outside_app_scopes(client, make_user):
    make_user("alice")
    app_obj = _make_app()
    # _make_app 의 기본 앱 스코프는 read write push 이므로 follow 는 허용되지 않는다.
    r = client.post(
        "/api/oauth/authorize",
        json={
            "client_id": app_obj.client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "scope": "follow",
            "username": "alice",
            "password": "test-password",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_scope"


def test_authorize_normalizes_top_level_scope(client, make_user):
    make_user("alice")
    app_obj = _make_app()
    r = client.post(
        "/api/oauth/authorize",
        json={
            "client_id": app_obj.client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "scope": "read read:accounts write",
            "username": "alice",
            "password": "test-password",
        },
    )
    assert r.status_code == 200
    code = r.json()["redirect"].split("code=")[1]

    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": app_obj.client_id,
            "client_secret": app_obj.client_secret,
            "redirect_uri": "https://client.example/callback",
        },
    )
    assert r.status_code == 200
    assert r.json()["scope"] == "read write"


def test_authorize_allows_registered_redirect(client, make_user):
    make_user("alice")
    app_obj = _make_app()
    r = _authorize(client, app_obj, "alice", "https://client.example/callback")
    assert r.status_code == 200
    assert "code=" in r.json()["redirect"]


def test_token_exchange_requires_matching_redirect(client, make_user):
    make_user("alice")
    app_obj = _make_app()
    r = _authorize(client, app_obj, "alice", "https://client.example/callback")
    code = r.json()["redirect"].split("code=")[1]

    # redirect_uri 생략 → 거부 (RFC 6749 §4.1.3)
    r = client.post(
        "/oauth/token",
        data={"grant_type": "authorization_code", "code": code, "client_id": app_obj.client_id, "client_secret": app_obj.client_secret},
    )
    assert r.status_code == 400

    # 다른 redirect_uri → 거부
    r = client.post(
        "/oauth/token",
        data={"grant_type": "authorization_code", "code": code, "client_id": app_obj.client_id, "client_secret": app_obj.client_secret, "redirect_uri": "https://evil.example/x"},
    )
    assert r.status_code == 400


def test_token_exchange_expired_code_rejected(client, make_user):
    user = make_user("alice")
    app_obj = _make_app()
    code = _insert_code(app_obj.id, user.id, age_seconds=601)

    r = client.post(
        "/oauth/token",
        data={"grant_type": "authorization_code", "code": code, "client_id": app_obj.client_id, "client_secret": app_obj.client_secret, "redirect_uri": "https://client.example/callback"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_token_exchange_valid_code_succeeds(client, make_user):
    user = make_user("alice")
    app_obj = _make_app()
    code = _insert_code(app_obj.id, user.id, age_seconds=30)

    r = client.post(
        "/oauth/token",
        data={"grant_type": "authorization_code", "code": code, "client_id": app_obj.client_id, "client_secret": app_obj.client_secret, "redirect_uri": "https://client.example/callback"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    # 인가된(read) 스코프로 고정된다
    assert body["scope"] == "read"


def test_token_exchange_cannot_escalate_scope(client, make_user):
    user = make_user("alice")
    app_obj = _make_app()
    code = _insert_code(app_obj.id, user.id)  # scopes="read" 로 승인됨

    r = client.post(
        "/oauth/token",
        data={"grant_type": "authorization_code", "code": code, "client_id": app_obj.client_id, "client_secret": app_obj.client_secret, "redirect_uri": "https://client.example/callback", "scope": "read write push admin"},
    )
    assert r.status_code == 200
    assert r.json()["scope"] == "read"


def test_public_app_registration_rejects_admin_scopes(client):
    r = client.post(
        "/api/v1/apps",
        json={"client_name": "admin-client", "scopes": "read admin:read"},
    )
    assert r.status_code == 403
    assert "Admin scopes" in r.json()["detail"]


def test_public_app_registration_allows_normal_scopes(client):
    r = client.post(
        "/api/v1/apps",
        json={"client_name": "normal-client", "scopes": "read write push"},
    )
    assert r.status_code == 200
    assert r.json()["scopes"] == ["read", "write", "push"]


def test_authorize_rejects_admin_scopes_for_non_staff(client, make_user):
    make_user("alice")
    app_obj = _make_app(scopes="read admin:read")
    r = client.post(
        "/api/oauth/authorize",
        json={
            "client_id": app_obj.client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "scope": "admin:read",
            "username": "alice",
            "password": "test-password",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_scope"


def test_authorize_allows_admin_scopes_for_staff(client, make_user):
    make_user("alice", role="admin")
    app_obj = _make_app(scopes="read admin:read")
    r = client.post(
        "/api/oauth/authorize",
        json={
            "client_id": app_obj.client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "scope": "admin:read",
            "username": "alice",
            "password": "test-password",
        },
    )
    assert r.status_code == 200


def test_password_grant_rejects_admin_scopes_for_non_staff(client, make_user):
    make_user("alice")
    app_obj = _make_app(scopes="read admin:read")
    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "password",
            "client_id": app_obj.client_id,
            "client_secret": app_obj.client_secret,
            "username": "alice",
            "password": "test-password",
            "scope": "admin:read",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_scope"


def test_token_exchange_rejects_existing_admin_code_for_non_staff(client, make_user):
    user = make_user("alice")
    app_obj = _make_app(scopes="read admin:read")
    code = _insert_code(app_obj.id, user.id, scopes="admin:read")

    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": app_obj.client_id,
            "client_secret": app_obj.client_secret,
            "redirect_uri": "https://client.example/callback",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_scope"


def test_existing_non_staff_admin_token_is_rejected(client, make_user):
    user = make_user("alice")
    app_obj = _make_app(scopes="read admin:read")
    token = secrets.token_urlsafe(48)
    with get_session() as s:
        s.add(
            MastodonAccessToken(
                app_id=app_obj.id,
                user_id=user.id,
                access_token=token,
                scopes="admin:read",
            )
        )
        s.commit()

    r = client.get(
        "/api/v1/accounts/verify_credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert "Admin scopes" in r.json()["detail"]
