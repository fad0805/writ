"""원격 유저 프로필(아바타) 갱신 지연 회귀 테스트.

DB에 이미 있는 원격 유저는 예전에는 무조건 캐시 반환이라 HTTP를 전혀 치지
않았다. 아바타 변경은 refresh_remote_profiles 워커(24시간 게이트 + 시간당 50건)
까지 발견되지 않아 인기가 적은 계정은 사흘 넘게 낡은 프로필을 보여줬다.
이제 TTL이 지난 행은 요청을 막지 않고 백그라운드로 재검증한다.
"""
import datetime
import threading

import pytest
from sqlalchemy import text

from app.config.settings import BASE_URL
from app.core.activitypub import _actor_resolver as ar
from app.db.database import get_session
from app.models import User

ACTOR_URL = "https://remote.example/users/carol"
OLD_AVATAR = "/uploads/avatars/remote/old.png"


def _make_remote(make_user, username="carol", **kw):
    """로컬 유저를 만든 뒤 원격 유저로 바꿔 치환한다 (NOT NULL 컬럼을 피하려고)."""
    u = make_user(username)
    with get_session() as s:
        row = s.query(User).filter_by(id=u.id).first()
        row.is_remote = True
        row.remote_url = kw.pop("remote_url", ACTOR_URL)
        row.profile_image = OLD_AVATAR
        for k, v in kw.items():
            setattr(row, k, v)
        s.commit()
        return row.id


def _backdate(uid, delta):
    """updated_at을 과거로 민다.

    Query.update()는 컬럼의 onupdate를 함께 적용해 지금 시각으로 덮어쓰므로
    파이썬 사이드 기본값(now)을 우회하는 raw SQL로 직접 써야 한다.
    """
    stamp = (datetime.datetime.now(datetime.UTC) - delta).replace(tzinfo=None)
    with get_session() as s:
        s.execute(text("UPDATE users SET updated_at = :t WHERE id = :i"), {"t": stamp, "i": uid})
        s.commit()


def _load(uid):
    with get_session() as s:
        return s.query(User).filter_by(id=uid).first()


@pytest.fixture(autouse=True)
def _clear_revalidating():
    ar._revalidating.clear()
    yield
    ar._revalidating.clear()


def _capture_spawn(monkeypatch):
    spawned = []
    monkeypatch.setattr(ar, "_spawn_revalidation", lambda url, sign_as=None: spawned.append(url))
    return spawned


def test_fresh_row_does_not_spawn_revalidation(make_user, monkeypatch):
    """TTL 안 지났으면 백그라운드 재검증조차 예약하지 않는다."""
    uid = _make_remote(make_user)
    spawned = _capture_spawn(monkeypatch)

    with get_session():
        u = ar._resolve_actor(ACTOR_URL)
        assert u is not None and u.id == uid
    assert spawned == []


def test_stale_row_returns_cache_immediately_but_spawns_refresh(make_user, monkeypatch):
    """핵심: 낡은 행이어도 요청은 DB 값을 즉시 반환하고, 갱신은 백그라운드로 나간다.

    원격 서버가 10초씩 타임아웃 걸려도 사용자 요청이 그걸 기다리면 안 된다.
    """
    uid = _make_remote(make_user)
    _backdate(uid, datetime.timedelta(hours=25))
    spawned = _capture_spawn(monkeypatch)

    with get_session():
        u = ar._resolve_actor(ACTOR_URL)
        # 캐시가 즉시 반환된다 (네트워크 호출 없이)
        assert u.id == uid
        assert u.profile_image == OLD_AVATAR
    assert spawned == [ACTOR_URL]


def test_lightweight_never_spawns_revalidation(make_user, monkeypatch):
    """lightweight 경로는 아바타를 다시 받지 못하므로 재검증해도 소용없다."""
    uid = _make_remote(make_user)
    _backdate(uid, datetime.timedelta(hours=25))
    spawned = _capture_spawn(monkeypatch)

    ar._resolve_actor(ACTOR_URL, lightweight=True)
    assert spawned == []


def test_force_refresh_skips_spawn(make_user, monkeypatch):
    """force_refresh는 이미 동기 갱신 경로이므로 백그라운드 재검증을 예약하지 않는다."""
    uid = _make_remote(make_user)
    _backdate(uid, datetime.timedelta(hours=25))
    spawned = _capture_spawn(monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("HTTP 호출됨")

    monkeypatch.setattr(ar, "_fetch_ap_json", _boom)
    with pytest.raises(AssertionError):
        ar._resolve_actor(ACTOR_URL, force_refresh=True)
    assert spawned == []


def test_spawn_revalidation_dedupes_concurrent_calls(monkeypatch):
    """같은 URL로 요청이 몰려도 백그라운드 스레드는 하나만 뜬다."""
    calls = []
    started = threading.Event()
    release = threading.Event()

    def _fake(url, **kwargs):
        calls.append(url)
        started.set()
        release.wait(5)

    monkeypatch.setattr(ar, "_resolve_actor", _fake)

    ar._spawn_revalidation(ACTOR_URL)
    assert started.wait(2), "백그라운드 스레드가 시작되지 않음"
    ar._spawn_revalidation(ACTOR_URL)
    ar._spawn_revalidation(ACTOR_URL)
    assert calls == [ACTOR_URL]

    release.set()


def test_revalidate_stamps_updated_at_even_on_failure(make_user, monkeypatch):
    """원격 서버가 죽었어도 updated_at을 갱신해 매 요청마다 다시 두드리지 않는다."""
    uid = _make_remote(make_user)
    _backdate(uid, datetime.timedelta(hours=25))

    def _boom(url, **kwargs):
        raise RuntimeError("remote down")

    monkeypatch.setattr(ar, "_resolve_actor", _boom)
    ar._revalidate_actor(ACTOR_URL)

    assert ar._is_stale(_load(uid)) is False


def test_revalidate_success_applies_new_avatar(make_user, monkeypatch):
    """재검증이 성공하면 새 아바타가 DB에 반영된다(갱신 지연의 목적)."""
    uid = _make_remote(make_user)
    _backdate(uid, datetime.timedelta(hours=25))

    def _fake(url, **kwargs):
        with get_session() as s:
            row = s.query(User).filter_by(id=uid).first()
            row.profile_image = "/uploads/avatars/remote/new.png"
            s.commit()

    monkeypatch.setattr(ar, "_resolve_actor", _fake)
    ar._revalidate_actor(ACTOR_URL)

    assert _load(uid).profile_image == "/uploads/avatars/remote/new.png"


def test_is_stale_boundaries(make_user):
    uid = _make_remote(make_user, username="dave")

    # updated_at이 없으면 낡은 것으로 간주
    with get_session() as s:
        row = s.query(User).filter_by(id=uid).first()
        row.updated_at = None
        s.commit()
    assert ar._is_stale(_load(uid)) is True

    _backdate(uid, datetime.timedelta(minutes=1))
    assert ar._is_stale(_load(uid)) is False

    # 정확히 TTL 이상 지나면 참
    _backdate(uid, datetime.timedelta(seconds=ar._ACTOR_REFRESH_TTL_SECONDS + 5))
    assert ar._is_stale(_load(uid)) is True

    # naive datetime(SQLite 저장 형태)도 예외 없이 비교된다
    assert ar._is_stale(_load(uid)) is True


def test_fallback_handle_url_also_refreshes(make_user, monkeypatch):
    """/@handle 형태 주소로 들어와도 재검증이 예약된다."""
    uid = _make_remote(make_user, remote_url="https://remote.example/users/erin")
    _backdate(uid, datetime.timedelta(hours=25))
    spawned = _capture_spawn(monkeypatch)

    with get_session():
        u = ar._resolve_actor("https://remote.example/@erin")
        assert u.id == uid
    assert spawned == ["https://remote.example/@erin"]


def test_local_user_never_spawns_revalidation(make_user, monkeypatch):
    """로컬 유저는 우리 서버가 아바타를 직접 관리하므로 네트워크 재검증이 없다."""
    make_user("localonly")
    spawned = _capture_spawn(monkeypatch)

    with get_session():
        u = ar._resolve_actor(f"{BASE_URL}/@localonly")
        assert u is not None and u.username == "localonly"
    assert spawned == []
