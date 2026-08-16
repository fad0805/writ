"""Role & permission management endpoint tests."""

import pytest


@pytest.fixture(autouse=True)
def _seed_roles():
    from app.core.permissions import ensure_default_roles

    ensure_default_roles()
    yield


def test_roles_list_requires_auth(client):
    assert client.get("/api/admin/roles").status_code == 401


def test_roles_list_forbidden_for_regular_user(client, auth_cookie):
    _, cookie = auth_cookie("alice", role="user")
    assert client.get("/api/admin/roles", cookies=cookie).status_code == 403


def test_roles_list_forbidden_for_moderator(client, auth_cookie):
    _, cookie = auth_cookie("mod", role="moderator")
    assert client.get("/api/admin/roles", cookies=cookie).status_code == 403


def test_roles_list_allowed_for_admin(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    r = client.get("/api/admin/roles", cookies=cookie)
    assert r.status_code == 200
    data = r.json()
    assert "catalog" in data and "roles" in data
    names = {role["name"] for role in data["roles"]}
    assert names == {"owner", "admin", "moderator", "user"}
    assert "users.admin" in data["catalog"]
    assert data["catalog"]["users.admin"]["tier"] == "admin"


def test_roles_list_allowed_for_owner(client, auth_cookie):
    _, cookie = auth_cookie("owner", role="owner")
    assert client.get("/api/admin/roles", cookies=cookie).status_code == 200


def test_update_role_rejects_owner_edit(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    r = client.post("/api/admin/roles/owner", json={"permissions": []}, cookies=cookie)
    assert r.status_code == 400


def test_update_role_rejects_unknown_permission(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    r = client.post("/api/admin/roles/moderator", json={"permissions": ["nope.nope"]}, cookies=cookie)
    assert r.status_code == 400


def test_update_role_changes_permissions(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    r = client.post("/api/admin/roles/moderator", json={"permissions": ["reports.manage"]}, cookies=cookie)
    assert r.status_code == 200
    assert r.json()["permissions"] == ["reports.manage"]

    mod, mod_cookie = auth_cookie("mod", role="moderator")
    assert client.get("/api/admin/roles", cookies=mod_cookie).status_code == 403
    assert client.get("/api/admin/reports", cookies=mod_cookie).status_code == 200


def test_stripped_admin_permission_takes_effect(client, auth_cookie):
    _, admin_cookie = auth_cookie("boss", role="admin")
    r = client.post("/api/admin/roles/admin", json={"permissions": []}, cookies=admin_cookie)
    assert r.status_code == 200
    assert client.get("/api/admin/reports", cookies=admin_cookie).status_code == 403


def test_owner_bypasses_permission_checks(client, auth_cookie):
    _, owner_cookie = auth_cookie("owner", role="owner")
    r = client.post("/api/admin/roles/admin", json={"permissions": []}, cookies=owner_cookie)
    assert r.status_code == 200
    assert client.get("/api/admin/reports", cookies=owner_cookie).status_code == 200
    assert client.get("/api/admin/roles", cookies=owner_cookie).status_code == 200
