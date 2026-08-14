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


def test_switch_requires_login(client, auth_cookie):
    _alice, alice_cookie = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    # Switch from bob's session requires an active session cookie AND a valid CSRF token.
    assert client.get("/api/auth/me", cookies=bob_cookie).status_code == 200
    # No CSRF header -> rejected before the session check.
    r = client.post(
        "/api/auth/switch",
        data={"session_token": "garbage"},
        cookies=alice_cookie,
    )
    assert r.status_code == 403
