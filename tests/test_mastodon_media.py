"""Mastodon media upload endpoint tests (/api/v1/media, /api/v2/media).

Mastodon clients (SubwayTooter, Tusky, etc.) upload media to /api/v2/media,
which must exist and must be exempt from CSRF validation just like /api/v1/.
"""

import io
import secrets

import pytest
from conftest import _build_app
from fastapi.testclient import TestClient

from app.db.database import get_session
from app.middleware import CSRFProtectionMiddleware
from app.models import MastodonAccessToken, MastodonApp

_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 100


def _bearer(user):
    token = secrets.token_urlsafe(24)
    with get_session() as s:
        app = s.query(MastodonApp).first()
        if not app:
            app = MastodonApp(client_name="test-app", client_id="test-cid", client_secret="test-secret")
            s.add(app)
            s.flush()
        s.add(MastodonAccessToken(access_token=token, app_id=app.id, user_id=user.id, scopes="read write push"))
        s.commit()
    return f"Bearer {token}"


def _upload(client, path, user, **kw):
    return client.post(
        path,
        headers={"Authorization": _bearer(user)},
        files={"file": ("test.png", io.BytesIO(_PNG), "image/png")},
        **kw,
    )


@pytest.fixture(scope="module")
def csrf_client():
    app = _build_app()
    app.add_middleware(CSRFProtectionMiddleware)
    with TestClient(app) as c:
        yield c


def test_upload_media_v1(client, make_user):
    alice = make_user("alice")
    r = _upload(client, "/api/v1/media", alice)
    assert r.status_code == 200
    assert r.json()["url"].startswith("/uploads/media/")
    assert r.json()["type"] == "image"


def test_upload_media_v2(client, make_user):
    alice = make_user("alice")
    r = _upload(client, "/api/v2/media", alice)
    assert r.status_code == 200
    assert r.json()["url"].startswith("/uploads/media/")
    assert r.json()["type"] == "image"


def test_upload_media_requires_bearer(client, make_user):
    alice = make_user("alice")
    r = client.post("/api/v2/media", files={"file": ("test.png", io.BytesIO(_PNG), "image/png")})
    assert r.status_code == 401


def test_v2_media_is_csrf_exempt(csrf_client, make_user):
    alice = make_user("alice")
    r = _upload(csrf_client, "/api/v2/media", alice)
    assert r.status_code == 200
    assert r.json()["url"].startswith("/uploads/media/")
