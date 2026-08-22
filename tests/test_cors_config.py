"""CORS 설정 보안 회귀 테스트.

와일드카드("*") 폴백 시 credentials가 비활성화되어야 한다.
Starlette CORSMiddleware는 allow_origins=["*"] + allow_credentials=True 조합에서
요청 Origin을 그대로 반영해 되돌려주므로, 임의 사이트가 쿠키 포함 요청을 보낼 수 있다.
"""

import importlib

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

import app.config.settings as settings


@pytest.fixture(autouse=True)
def _restore_settings():
    """설정 모듈을 reload한 뒤 원래 환경으로 복구한다."""
    yield
    importlib.reload(settings)


def _reload_settings(monkeypatch, **env):
    for key in ("CORS_ORIGINS", "BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(settings)


def test_wildcard_fallback_disables_credentials(monkeypatch):
    s = _reload_settings(monkeypatch)
    assert "*" in s.CORS_ORIGINS
    assert s.CORS_ALLOW_CREDENTIALS is False


def test_explicit_base_url_keeps_credentials(monkeypatch):
    s = _reload_settings(monkeypatch, BASE_URL="https://writ.example")
    assert s.CORS_ORIGINS == ["https://writ.example"]
    assert s.CORS_ALLOW_CREDENTIALS is True


def test_explicit_cors_origins_keep_credentials(monkeypatch):
    s = _reload_settings(monkeypatch, CORS_ORIGINS="https://a.example, https://b.example")
    assert s.CORS_ORIGINS == ["https://a.example", "https://b.example"]
    assert s.CORS_ALLOW_CREDENTIALS is True


def _preflight(cors_origins, allow_credentials, origin):
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    with TestClient(app) as c:
        return c.options(
            "/api/anything",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )


def test_wildcard_preflight_does_not_echo_origin_or_credentials():
    r = _preflight(["*"], False, "https://evil.example")
    assert r.headers.get("access-control-allow-origin") == "*"
    assert "access-control-allow-credentials" not in r.headers


def test_explicit_preflight_rejects_unknown_origin():
    r = _preflight(["https://good.example"], True, "https://evil.example")
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers
