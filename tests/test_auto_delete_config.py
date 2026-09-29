"""AUTO_DELETE_INTERVAL_SECONDS 환경변수 검증 테스트.

주기 워커는 `time.sleep(주기)`로 루프를 도는데, 0/음수가 그대로 통과하면
무한 루프 + DB 상시 조회(그리고 sleep 예외로 죽음)가 되고, 파싱 실패하면
워커 기동 시 ValueError로 죽는다. 값이 잘못돼도 서버는 뜨도록 경계 안으로
되돌리는지 고정한다.
"""

import importlib

import pytest

import app.config.settings as settings


@pytest.fixture(autouse=True)
def _restore_settings():
    yield
    importlib.reload(settings)


def _interval(s):
    """상수처럼 보이는 속성을 그대로 비교하면 ruff SIM300이 걸린다."""
    return s.AUTO_DELETE_INTERVAL_SECONDS


def _reload(monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("AUTO_DELETE_INTERVAL_SECONDS", raising=False)
    else:
        monkeypatch.setenv("AUTO_DELETE_INTERVAL_SECONDS", raw)
    return importlib.reload(settings)


def test_default_when_unset(monkeypatch):
    assert _interval(_reload(monkeypatch, None)) == 3600


def test_empty_falls_back_to_default(monkeypatch):
    assert _interval(_reload(monkeypatch, "")) == 3600
    assert _interval(_reload(monkeypatch, "   ")) == 3600


@pytest.mark.parametrize("raw,expected", [("60", 60), ("300", 300), ("86400", 86400), (" 600 ", 600)])
def test_valid_values_pass_through(monkeypatch, raw, expected):
    s = _reload(monkeypatch, raw)
    assert _interval(s) == expected


@pytest.mark.parametrize("raw", ["0", "-1", "-3600"])
def test_zero_and_negative_clamped_to_minimum(monkeypatch, raw):
    """0은 sleep(0) 무한 루프가 되므로 최소값으로 올려야 한다."""
    assert _interval(_reload(monkeypatch, raw)) == 60


def test_absurdly_large_clamped_to_maximum(monkeypatch):
    """999999999처럼 넣으면 사실상 워커가 영영 안 돌아 조용히 죽는다."""
    assert _interval(_reload(monkeypatch, "999999999")) == 86400


@pytest.mark.parametrize("raw", ["abc", "3600.5", "1h", "3600s", "null"])
def test_non_integer_falls_back_to_default(monkeypatch, raw):
    """파싱 실패가 워커를 죽이지 않고 기본값으로 돌아가야 한다."""
    assert _interval(_reload(monkeypatch, raw)) == 3600


def test_bad_value_is_logged(monkeypatch, caplog):
    with caplog.at_level("WARNING", logger="writ.config"):
        _reload(monkeypatch, "abc")
    assert any("AUTO_DELETE_INTERVAL_SECONDS" in r.message for r in caplog.records)
