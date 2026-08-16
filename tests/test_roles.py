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


def test_create_role(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    r = client.post("/api/admin/roles", json={"name": "helper", "label": "도우미", "permissions": ["reports.manage"]}, cookies=cookie)
    assert r.status_code == 200
    assert r.json()["role"]["name"] == "helper"
    assert r.json()["role"]["permissions"] == ["reports.manage"]
    names = {role["name"] for role in client.get("/api/admin/roles", cookies=cookie).json()["roles"]}
    assert "helper" in names


def test_create_role_rejects_duplicate_and_builtin(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    assert client.post("/api/admin/roles", json={"name": "moderator", "label": "중복"}, cookies=cookie).status_code == 400
    client.post("/api/admin/roles", json={"name": "helper", "label": "도우미"}, cookies=cookie)
    assert client.post("/api/admin/roles", json={"name": "helper", "label": "도우미2"}, cookies=cookie).status_code == 400


def test_create_role_rejects_bad_name(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    for bad in ["", "1abc", "has space", "ab!c", "a" * 16]:
        assert client.post("/api/admin/roles", json={"name": bad, "label": "x"}, cookies=cookie).status_code == 400
    assert client.post("/api/admin/roles", json={"name": "ok_role", "label": ""}, cookies=cookie).status_code == 400


def test_create_role_normalizes_lowercase(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    r = client.post("/api/admin/roles", json={"name": "Helper", "label": "도우미"}, cookies=cookie)
    assert r.status_code == 200
    assert r.json()["role"]["name"] == "helper"


def test_delete_role(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    client.post("/api/admin/roles", json={"name": "helper", "label": "도우미"}, cookies=cookie)
    r = client.delete("/api/admin/roles/helper", cookies=cookie)
    assert r.status_code == 200
    names = {role["name"] for role in client.get("/api/admin/roles", cookies=cookie).json()["roles"]}
    assert "helper" not in names


def test_delete_builtin_role_rejected(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    for name in ("owner", "admin", "moderator", "user"):
        assert client.delete(f"/api/admin/roles/{name}", cookies=cookie).status_code == 400


def test_delete_role_in_use_rejected(client, auth_cookie, make_user):
    _, cookie = auth_cookie("boss", role="admin")
    client.post("/api/admin/roles", json={"name": "helper", "label": "도우미"}, cookies=cookie)
    target = make_user("alice")
    r = client.post(f"/api/admin/users/{target.id}/change-role", data={"role": "helper"}, cookies=cookie)
    assert r.status_code == 200
    r = client.delete("/api/admin/roles/helper", cookies=cookie)
    assert r.status_code == 400
    names = {role["name"] for role in client.get("/api/admin/roles", cookies=cookie).json()["roles"]}
    assert "helper" in names


def test_custom_role_assignable_via_change_role(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    client.post("/api/admin/roles", json={"name": "helper", "label": "도우미", "permissions": ["reports.manage"]}, cookies=cookie)
    mod, mod_cookie = auth_cookie("alice")
    r = client.post(f"/api/admin/users/{mod.id}/change-role", data={"role": "helper"}, cookies=cookie)
    assert r.status_code == 200
    assert client.get("/api/admin/reports", cookies=mod_cookie).status_code == 200


def test_me_returns_permissions(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    d = client.get("/api/auth/me", cookies=cookie).json()
    assert "permissions" in d
    assert "reports.manage" in d["permissions"]


def test_me_permissions_follow_custom_role(client, auth_cookie):
    _, cookie = auth_cookie("boss", role="admin")
    client.post("/api/admin/roles", json={"name": "helper", "label": "도우미", "permissions": ["reports.manage"]}, cookies=cookie)
    user, ucookie = auth_cookie("alice")
    client.post(f"/api/admin/users/{user.id}/change-role", data={"role": "helper"}, cookies=cookie)
    d = client.get("/api/auth/me", cookies=ucookie).json()
    assert d["permissions"] == ["reports.manage"]


def test_me_owner_gets_all_permissions(client, auth_cookie):
    _, cookie = auth_cookie("own", role="owner")
    d = client.get("/api/auth/me", cookies=cookie).json()
    assert "users.admin" in d["permissions"]
    assert "federation.mode" in d["permissions"]
    assert "roles.manage" in d["permissions"]
