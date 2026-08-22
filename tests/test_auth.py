"""Auth flow tests — register, login, rate limit, logout, password reset."""


def _register(client, username, password="secret123", email=None):
    return client.post(
        "/api/auth/register",
        data={
            "username": username,
            "password": password,
            "email": email or f"{username}@test.local",
        },
    )


def test_register_creates_user(client):
    r = _register(client, "newuser")
    assert r.status_code == 200
    assert r.json()["email_sent"] is True


def test_register_rejects_reserved_handle(client):
    assert _register(client, "admin").status_code == 400


def test_register_rejects_invalid_username(client):
    assert _register(client, "ab").status_code == 400  # too short
    assert _register(client, "bad name").status_code == 400
    assert _register(client, "bad-name").status_code == 400  # hyphen not allowed
    assert _register(client, "UPPER").status_code == 200  # lowercased to valid "upper"


def test_register_rejects_short_password(client):
    assert _register(client, "shortpw", password="123").status_code == 400


def test_register_rejects_invalid_email(client):
    assert _register(client, "badmail", email="not-an-email").status_code == 400


def test_register_rejects_duplicate_username(client, make_user):
    make_user("alice")
    assert _register(client, "alice").status_code == 400


def test_register_rejects_duplicate_email(client, make_user):
    make_user("alice")
    assert _register(client, "bob", email="alice@test.local").status_code == 400


def test_login_success_sets_session_cookie(client, make_user):
    make_user("alice")
    r = client.post("/api/auth/login", data={"username": "alice", "password": "test-password"})
    assert r.status_code == 200
    assert r.cookies.get("session")


def test_login_wrong_password(client, make_user):
    make_user("alice")
    r = client.post("/api/auth/login", data={"username": "alice", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_user(client):
    r = client.post("/api/auth/login", data={"username": "ghost", "password": "x"})
    assert r.status_code == 401


def test_login_rate_limits_after_5_failures(client, make_user):
    make_user("alice")
    for _ in range(5):
        client.post("/api/auth/login", data={"username": "alice", "password": "wrong"})
    r = client.post("/api/auth/login", data={"username": "alice", "password": "wrong"})
    assert r.status_code == 429


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_user(client, auth_cookie):
    user, cookie = auth_cookie("alice")
    r = client.get("/api/auth/me", cookies=cookie)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"
    assert r.json()["id"] == user.id


def test_logout_clears_session(client, auth_cookie):
    _, cookie = auth_cookie("bob")
    r = client.post("/api/auth/logout", cookies=cookie)
    assert r.status_code == 200
    assert client.get("/api/auth/me", cookies=cookie).status_code == 401


def test_legacy_user_id_cookie_rejected(client, make_user):
    """DB 세션 행 없이 user_id만 담은 구버전 쿠키는 서명이 유효해도 인증되지 않아야 한다.

    비밀번호 변경 등으로 delete_user_sessions()가 세션 행을 모두 지우면,
    레거시 폴백이 남아 있을 때 해당 쿠키가 무효화를 우회하는 문제가 있었다.
    """
    import time

    from app.core.auth import _sign_session_key

    user = make_user("legacysession")
    legacy_cookie = {"session": _sign_session_key(str(user.id), int(time.time()) + 3600)}
    assert client.get("/api/auth/me", cookies=legacy_cookie).status_code == 401


def test_switch_requires_csrf(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    # No CSRF header -> rejected before anything else.
    r = client.post(
        "/api/auth/switch",
        data={"target_user_id": "999"},
        cookies=alice_cookie,
    )
    assert r.status_code == 403


def test_switch_rejects_unlinked_account(client, auth_cookie):
    from app.utils.crypto import generate_csrf_token

    alice, _alice_cookie = auth_cookie("alice")
    bob, bob_cookie = auth_cookie("bob")
    carol, _carol_cookie = auth_cookie("carol")
    # bob's session has no linked accounts: switching to alice/carol is denied.
    for target in (alice, carol):
        r = client.post(
            "/api/auth/switch",
            data={"target_user_id": str(target.id)},
            cookies=bob_cookie,
            headers={"X-CSRF-Token": generate_csrf_token(bob.id)},
        )
        assert r.status_code == 403


def test_login_while_logged_in_links_accounts_and_enables_switch(client, auth_cookie):
    from app.utils.crypto import generate_csrf_token

    alice, alice_cookie = auth_cookie("alice")
    bob, _bob_cookie = auth_cookie("bob")
    # Add-account flow: while holding alice's session, log in as bob.
    r = client.post(
        "/api/auth/login",
        data={"username": "bob", "password": "test-password"},
        cookies=alice_cookie,
    )
    assert r.status_code == 200
    bob_linked_cookie = dict(r.cookies)
    # Switch back to alice with no stored token — only the cookie + CSRF + user id.
    r = client.post(
        "/api/auth/switch",
        data={"target_user_id": str(alice.id)},
        cookies=bob_linked_cookie,
        headers={"X-CSRF-Token": generate_csrf_token(bob.id)},
    )
    assert r.status_code == 200
    assert r.json()["username"] == "alice"
    me = client.get("/api/auth/me", cookies=dict(r.cookies))
    assert me.status_code == 200
    assert me.json()["id"] == alice.id


def test_switch_response_contains_no_session_token(client, make_user):
    """전환 응답과 로그인 응답은 토큰을 노출하지 않는다(클라이언트 저장 금지)."""
    from app.core.auth import create_session
    from app.utils.crypto import generate_csrf_token

    alice = make_user("alice")
    bob = make_user("bob")
    alice_token = create_session(alice.id)
    r = client.post(
        "/api/auth/login",
        data={"username": "bob", "password": "test-password"},
        cookies={"session": alice_token},
    )
    assert "session_token" not in r.json()
    bob_linked_cookie = dict(r.cookies)
    r = client.post(
        "/api/auth/switch",
        data={"target_user_id": str(alice.id)},
        cookies=bob_linked_cookie,
        headers={"X-CSRF-Token": generate_csrf_token(bob.id)},
    )
    assert r.status_code == 200
    assert "session_token" not in r.json()


def test_old_session_token_body_is_not_accepted(client, auth_cookie):
    """구 프로토콜(session_token 폼 필드)은 더 이상 스위치로 이어지지 않는다."""
    from app.utils.crypto import generate_csrf_token

    alice, alice_cookie = auth_cookie("alice")
    # 유효한 세션+CSRF여도 구 필드만으로는 target_user_id가 없어 422로 거부된다.
    r = client.post(
        "/api/auth/switch",
        data={"session_token": "garbage"},
        cookies=alice_cookie,
        headers={"X-CSRF-Token": generate_csrf_token(alice.id)},
    )
    assert r.status_code == 422
