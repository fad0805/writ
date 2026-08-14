"""CSRF protection middleware tests — mounted explicitly on a dedicated app."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import CSRFProtectionMiddleware
from conftest import _build_app


@pytest.fixture(scope="module")
def csrf_client():
    app = _build_app()
    app.add_middleware(CSRFProtectionMiddleware)
    with TestClient(app) as c:
        yield c


def test_post_without_csrf_token_rejected(csrf_client, auth_cookie):
    _, cookie = auth_cookie("alice")
    r = csrf_client.post("/api/posts", data={"content": "<p>x</p>"}, cookies=cookie)
    assert r.status_code == 403
    assert "CSRF" in r.json()["detail"]


def test_post_with_invalid_csrf_token_rejected(csrf_client, auth_cookie):
    alice, cookie = auth_cookie("alice")
    r = csrf_client.post(
        "/api/posts",
        data={"content": "<p>x</p>"},
        cookies=cookie,
        headers={"X-CSRF-Token": "not-a-valid-token"},
    )
    assert r.status_code == 403


def test_post_with_valid_csrf_token_allowed(csrf_client, auth_cookie, csrf_token):
    alice, cookie = auth_cookie("alice")
    r = csrf_client.post(
        "/api/posts",
        data={"content": "<p>hello csrf</p>"},
        cookies=cookie,
        headers={"X-CSRF-Token": csrf_token(alice)},
    )
    assert r.status_code == 200
    assert r.json()["content"] == "hello csrf"


def test_get_is_exempt(csrf_client, auth_cookie):
    _, cookie = auth_cookie("alice")
    assert csrf_client.get("/api/auth/me", cookies=cookie).status_code == 200


def test_auth_routes_are_exempt(csrf_client, auth_cookie):
    alice, _ = auth_cookie("alice")
    r = csrf_client.post("/api/auth/login", data={"username": alice.username, "password": "test-password"})
    assert r.status_code == 200


def test_csrf_token_requires_valid_session(csrf_client, auth_cookie, csrf_token):
    alice, cookie = auth_cookie("alice")
    r = csrf_client.post(
        "/api/posts",
        data={"content": "<p>x</p>"},
        headers={"X-CSRF-Token": csrf_token(alice)},
    )
    assert r.status_code == 403


def test_expired_csrf_token_rejected(csrf_client, auth_cookie):
    import base64
    import hashlib
    import hmac
    import time

    from app.config.settings import SECRET_KEY

    alice, cookie = auth_cookie("alice")
    expired_payload = f"{alice.id}:{int(time.time()) - 10}"
    sig = hmac.new(SECRET_KEY.encode(), expired_payload.encode(), hashlib.sha256).hexdigest()
    expired_token = base64.urlsafe_b64encode(f"{expired_payload}:{sig}".encode()).decode()
    r = csrf_client.post(
        "/api/posts",
        data={"content": "<p>x</p>"},
        cookies=cookie,
        headers={"X-CSRF-Token": expired_token},
    )
    assert r.status_code == 403
