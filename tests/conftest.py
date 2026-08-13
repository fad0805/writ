import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "writ-test-secret-key-not-for-production")
os.environ.setdefault("DOMAIN", "localhost:3000")
os.environ.setdefault("BASE_URL", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/opencode/writ_test.db")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.database import engine, init_db, Base, get_session
from app.models import User
from app.routes.api import router as api_router
from app.core.auth import create_session, hash_password
from app.utils.crypto import generate_keypair


def _build_app():
    app = FastAPI()
    app.include_router(api_router)
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


@pytest.fixture
def make_user():
    """Create a local user directly in the DB. Returns the ORM object."""
    counter = [0]

    def _make(username):
        counter[0] += 1
        salt, hval = hash_password("test-password")
        priv, pub = generate_keypair()
        with get_session() as s:
            u = User(
                username=username,
                display_name=username,
                email=f"{username}@test.local",
                password_hash=f"{salt}:{hval}",
                private_key=priv,
                public_key=pub,
                is_remote=False,
            )
            s.add(u)
            s.commit()
            s.refresh(u)
            return u

    return _make


@pytest.fixture
def auth_cookie(make_user):
    """Create a user and return (user, {'session': signed_cookie})."""
    def _auth(username):
        user = make_user(username)
        token = create_session(user.id)
        return user, {"session": token}
    return _auth
