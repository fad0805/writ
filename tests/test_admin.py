"""Admin endpoint role-based access control tests."""

ROLE_BY_USER = {"moderator": "moderator", "admin": "admin", "owner": "owner"}


def test_admin_stats_forbidden_for_regular_user(client, auth_cookie):
    _, cookie = auth_cookie("alice", role="user")
    assert client.get("/api/admin/stats", cookies=cookie).status_code == 403


def test_admin_stats_requires_auth(client):
    assert client.get("/api/admin/stats").status_code == 401


def test_admin_stats_allowed_for_moderator(client, auth_cookie):
    _, cookie = auth_cookie("mod", role="moderator")
    r = client.get("/api/admin/stats", cookies=cookie)
    assert r.status_code == 200
    assert "users" in r.json()


def test_admin_stats_allowed_for_admin(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    assert client.get("/api/admin/stats", cookies=cookie).status_code == 200


def test_admin_stats_allowed_for_owner(client, auth_cookie):
    _, cookie = auth_cookie("owner", role="owner")
    assert client.get("/api/admin/stats", cookies=cookie).status_code == 200


def test_admin_users_listing_forbidden_for_regular_user(client, auth_cookie):
    _, cookie = auth_cookie("alice", role="user")
    assert client.get("/api/admin/users", cookies=cookie).status_code == 403


def test_admin_users_listing_shows_local_users(client, auth_cookie, make_user):
    _, cookie = auth_cookie("admin", role="admin")
    make_user("alice")
    make_user("bob")
    r = client.get("/api/admin/users", cookies=cookie)
    assert r.status_code == 200
    usernames = {u["username"] for u in r.json()["users"]}
    assert "alice" in usernames
    assert "bob" in usernames


def test_admin_user_detail(client, auth_cookie, make_user):
    _, cookie = auth_cookie("admin", role="admin")
    alice = make_user("alice")
    r = client.get(f"/api/admin/users/{alice.id}", cookies=cookie)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_admin_user_detail_not_found(client, auth_cookie):
    _, cookie = auth_cookie("admin", role="admin")
    assert client.get("/api/admin/users/999999", cookies=cookie).status_code == 404
