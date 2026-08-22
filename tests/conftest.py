import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "writ-test-secret-key-not-for-production")
os.environ.setdefault("DOMAIN", "localhost:3000")
os.environ.setdefault("BASE_URL", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/opencode/writ_test.db")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import create_session, hash_password
from app.db.database import Base, engine, get_session, init_db
from app.middleware import LogRequestsMiddleware
from app.models import Follow, Post, User
from app.routes.admin import router as admin_router
from app.routes.ap import router as ap_router
from app.routes.api import router as api_router
from app.routes.mastodon_api import oauth_router
from app.routes.mastodon_api import router as mastodon_api_router
from app.routes.nodeinfo import router as nodeinfo_router
from app.routes.streaming import router as streaming_router
from app.utils.crypto import generate_csrf_token, generate_keypair


def _build_app():
    """Test app mirroring app.main.py — all routers in priority order, no static
    mounts, no lifespan workers, and no CSRF middleware (POST tests stay simple;
    CSRF behavior is covered by tests/test_csrf.py which mounts it explicitly).
    """
    app = FastAPI(title="writ-test")
    app.add_middleware(LogRequestsMiddleware)
    app.include_router(ap_router)
    app.include_router(nodeinfo_router)
    app.include_router(streaming_router)
    app.include_router(oauth_router)
    app.include_router(admin_router)
    app.include_router(api_router)
    app.include_router(mastodon_api_router, prefix="/api")
    return app


@pytest.fixture(scope="session")
def client():
    app = _build_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(engine)
    init_db()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _reset_in_memory_limits():
    """Clear in-memory rate-limit state between tests.

    Auth failures (app.routes.api._auth) and the generic rate limiter
    (app.core.rate_limit) are module-level dicts keyed by client IP, so they
    would otherwise accumulate across tests that share a single TestClient IP.
    """
    import app.routes.api._auth as auth_mod
    from app.core.permissions import _ROLE_PERM_CACHE, _ROLE_PERM_CACHE_TIME
    from app.core.rate_limit import _rate_limit_daily, _rate_limit_store
    from app.utils.filter import _filters_cache

    with auth_mod._auth_lock:
        auth_mod._auth_failures.clear()
    _rate_limit_store.clear()
    _rate_limit_daily.clear()
    _ROLE_PERM_CACHE.clear()
    _ROLE_PERM_CACHE_TIME.clear()
    _filters_cache.clear()
    yield
    with auth_mod._auth_lock:
        auth_mod._auth_failures.clear()
    _rate_limit_store.clear()
    _rate_limit_daily.clear()
    _ROLE_PERM_CACHE.clear()
    _ROLE_PERM_CACHE_TIME.clear()
    _filters_cache.clear()


@pytest.fixture
def make_user():
    """Create a local user directly in the DB. Returns the ORM object."""
    counter = [0]

    def _make(username, role="user"):
        counter[0] += 1
        pwd_hash = hash_password("test-password")
        priv, pub = generate_keypair()
        with get_session() as s:
            u = User(
                username=username,
                display_name=username,
                email=f"{username}@test.local",
                password_hash=pwd_hash,
                private_key=priv,
                public_key=pub,
                is_remote=False,
                role=role,
                email_verified=True,
            )
            s.add(u)
            s.commit()
            s.refresh(u)
            return u

    return _make


@pytest.fixture
def auth_cookie(make_user):
    """Create a user and return (user, {'session': signed_cookie})."""

    def _auth(username, role="user"):
        user = make_user(username, role=role)
        token = create_session(user.id)
        return user, {"session": token}

    return _auth


@pytest.fixture
def make_post(make_user):
    """Create a post directly in the DB. Returns the ORM object."""
    counter = [0]

    def _make(
        author,
        content="<p>test post</p>",
        visibility="public",
        mentioned_user_ids=None,
        parent=None,
        is_dm=False,
        poll_data=None,
        summary="",
        is_deleted=False,
    ):
        counter[0] += 1
        n = counter[0]
        with get_session() as s:
            p = Post(
                author_id=author.id,
                content=content,
                summary=summary,
                visibility=visibility,
                mentioned_user_ids=mentioned_user_ids or [],
                number=f"n{n}",
                ap_id=f"http://localhost:3000/@x/{n}",
                is_dm=is_dm,
                poll_data=poll_data,
                is_deleted=is_deleted,
                in_reply_to_id=parent.id if parent else None,
            )
            s.add(p)
            s.commit()
            s.refresh(p)
            return p

    return _make


@pytest.fixture
def make_follow():
    """Create a follow relation directly in the DB."""

    def _make(follower, following, accepted=True):
        with get_session() as s:
            f = Follow(
                follower_id=follower.id,
                following_id=following.id,
                accepted=accepted,
            )
            s.add(f)
            s.commit()
            s.refresh(f)
            return f

    return _make


@pytest.fixture
def csrf_token():
    """Generate a valid CSRF token for a user (used by the CSRF middleware tests)."""

    def _token(user):
        return generate_csrf_token(user.id)

    return _token
