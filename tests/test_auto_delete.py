"""Auto-delete (user.post_lifetime) worker tests.

`_run_auto_delete_once` is the single-pass unit of work extracted from the
`auto_delete_expired_posts` loop, so tests can drive it directly without
waiting for the 3 AM schedule.
"""

import datetime

import pytest

import app.core.workers as workers_mod
from app.core.workers import _get_cpu_percent, _run_auto_delete_once
from app.db.database import get_session
from app.models import Bookmark, Like, Notification, Post, User


@pytest.fixture(autouse=True)
def _not_busy(monkeypatch):
    """개발기/CI CPU 부하에 따라 자동삭제가 중간에 끊기면 테스트가 흔들린다.
    삭제 로직 자체만 검증하므로 부하 판정은 0으로 고정한다."""
    workers_mod._cpu_cache = None
    monkeypatch.setattr(workers_mod, "_get_cpu_percent", lambda: 0.0)


def test_cpu_probe_is_cached(monkeypatch):
    """/proc/stat 두 읽기 사이에 1초를 자므로, 측정 결과를 TTL 동안 재사용한다.

    (회귀: 캐시가 없으면 자동삭제가 글마다 1초씩 잠들어 1건/초로 느려진다.
    프로덕션(Linux)에서만 /proc/stat이 있어 그 slowdown이 발현됐다)
    """
    workers_mod._cpu_cache = None
    sleeps = []

    class _FakeProc:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def readline(self):
            # parts[0]=cpu, parts[1..3]=user/nice/system, parts[4]=idle
            return "cpu  100 0 100 700  100 0 0 0\n"

    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeProc())
    monkeypatch.setattr(workers_mod.time, "sleep", lambda s: sleeps.append(s))

    for _ in range(5):
        _get_cpu_percent()

    # 5번 호출 → 실제 측정은 1번뿐(두 번째 이후는 캐시 적중)
    assert len(sleeps) == 1, f"CPU 측정이 {len(sleeps)}번 실행됨 (캐시 미작동)"
    assert workers_mod._cpu_cache is not None


def test_cpu_probe_returns_value(monkeypatch):
    workers_mod._cpu_cache = None
    lines = iter([
        "cpu  100 0 100 700  0 0 0 0\n",
        "cpu  150 0 100 750  0 0 0 0\n",
    ])

    class _FakeProc:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def readline(self):
            return next(lines)

    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeProc())
    monkeypatch.setattr(workers_mod.time, "sleep", lambda s: None)
    # idle 700→750 (idle_d=50), total 900→1000 (total_d=100) → 50% idle → 50% used
    assert _get_cpu_percent() == 50.0


def test_cpu_probe_survives_missing_proc_stat(monkeypatch):
    """macOS 등 /proc이 없으면 조용히 0을 돌려주고 캐시한다."""
    workers_mod._cpu_cache = None

    def _boom(*a, **k):
        raise FileNotFoundError("/proc/stat")

    monkeypatch.setattr("builtins.open", _boom)
    assert _get_cpu_percent() == 0.0
    assert workers_mod._cpu_cache is not None


def _age(post, days):
    """Rewrite a post's created_at so it looks `days` old."""
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
    with get_session() as s:
        s.query(Post).filter_by(id=post.id).update({"created_at": cutoff})
        s.commit()
    return post


def _set_lifetime(user, days, exceptions=None):
    with get_session() as s:
        u = s.query(User).get(user.id)
        u.post_lifetime = days
        u.post_lifetime_exceptions = list(exceptions or [])
        s.commit()
    return user


def _post_ids():
    with get_session() as s:
        return {row[0] for row in s.query(Post.id).all()}


def test_deletes_only_expired_posts(client, make_user, make_post):
    alice = make_user("alice")
    _set_lifetime(alice, 7)
    old = _age(make_post(alice), 30)
    recent = _age(make_post(alice), 1)
    assert _run_auto_delete_once() == 1
    ids = _post_ids()
    assert old.id not in ids
    assert recent.id in ids


def test_no_op_when_lifetime_zero(client, make_user, make_post):
    alice = make_user("alice")
    _set_lifetime(alice, 0)
    old = _age(make_post(alice), 30)
    assert _run_auto_delete_once() == 0
    assert old.id in _post_ids()


def test_only_targets_user_with_lifetime(client, make_user, make_post):
    alice = make_user("alice")
    bob = make_user("bob")
    _set_lifetime(alice, 7)
    _set_lifetime(bob, 0)
    old_alice = _age(make_post(alice), 30)
    old_bob = _age(make_post(bob), 30)
    assert _run_auto_delete_once() == 1
    ids = _post_ids()
    assert old_alice.id not in ids
    assert old_bob.id in ids


def test_skips_deleted_posts(client, make_user, make_post):
    alice = make_user("alice")
    _set_lifetime(alice, 7)
    _age(make_post(alice, is_deleted=True), 30)
    assert _run_auto_delete_once() == 0
    assert len(_post_ids()) == 1


def test_flag_exceptions_keep_posts(client, make_user, make_post):
    alice = make_user("alice")
    _set_lifetime(alice, 7, exceptions=["pinned", "dm", "poll", "media"])
    pinned = _age(make_post(alice), 30)
    dm = _age(make_post(alice), 30)
    poll = _age(make_post(alice), 30)
    media = _age(make_post(alice), 30)
    normal = _age(make_post(alice), 30)
    with get_session() as s:
        s.query(Post).filter_by(id=pinned.id).update({"is_pinned": True})
        s.query(Post).filter_by(id=dm.id).update({"is_dm": True})
        s.query(Post).filter_by(id=poll.id).update({"poll_data": {"options": []}})
        s.query(Post).filter_by(id=media.id).update({"media_attachments": [{"url": "http://x", "type": "image"}]})
        s.commit()
    assert _run_auto_delete_once() == 1
    ids = _post_ids()
    assert pinned.id in ids
    assert dm.id in ids
    assert poll.id in ids
    assert media.id in ids
    assert normal.id not in ids


def test_liked_bookmarked_exceptions_keep_posts(client, make_user, make_post):
    alice = make_user("alice")
    _set_lifetime(alice, 7, exceptions=["liked", "bookmarked"])
    liked = _age(make_post(alice), 30)
    bookmarked = _age(make_post(alice), 30)
    with get_session() as s:
        s.add(Like(user_id=alice.id, post_id=liked.id))
        s.add(Bookmark(user_id=alice.id, post_id=bookmarked.id))
        s.commit()
    assert _run_auto_delete_once() == 0
    ids = _post_ids()
    assert liked.id in ids
    assert bookmarked.id in ids


def test_deletes_related_rows(client, make_user, make_post):
    alice = make_user("alice")
    bob = make_user("bob")
    _set_lifetime(alice, 7)
    post = _age(make_post(alice), 30)
    with get_session() as s:
        s.add(Like(user_id=bob.id, post_id=post.id))
        s.add(Bookmark(user_id=bob.id, post_id=post.id))
        s.add(Notification(
            user_id=bob.id,
            from_user_id=alice.id,
            notification_type="like",
            post_id=post.id,
        ))
        s.commit()
    assert _run_auto_delete_once() == 1
    with get_session() as s:
        assert s.query(Like).filter_by(post_id=post.id).first() is None
        assert s.query(Bookmark).filter_by(post_id=post.id).first() is None
        assert s.query(Notification).filter_by(post_id=post.id).first() is None


def test_bookmarked_exception_full_flow(client, auth_cookie, make_post):
    """설정 API 저장 → 워커 실행 경로 검증: 작성자 본인이 북마크한 글만 보호되고,
    다른 유저가 북마크한 글은 삭제된다."""
    alice, alice_cookie = auth_cookie("alice")
    bob, _ = auth_cookie("bob")
    r = client.post("/api/settings/update", data={
        "post_lifetime": "7",
        "post_lifetime_exceptions": '["bookmarked"]',
    }, cookies=alice_cookie)
    assert r.status_code == 200

    own_bookmarked = _age(make_post(alice), 30)
    other_bookmarked = _age(make_post(alice), 30)
    plain = _age(make_post(alice), 30)
    with get_session() as s:
        s.add(Bookmark(user_id=alice.id, post_id=own_bookmarked.id))
        s.add(Bookmark(user_id=bob.id, post_id=other_bookmarked.id))
        s.commit()

    assert _run_auto_delete_once() == 2
    ids = _post_ids()
    assert own_bookmarked.id in ids
    assert other_bookmarked.id not in ids
    assert plain.id not in ids


def test_settings_update_keeps_fields_that_were_not_sent(client, auth_cookie):
    """/api/settings/update는 기본 설정 페이지와 자동 삭제 페이지가 공유한다.

    각 페이지는 자신의 폼 필드만 보내므로, 안 온 필드를 기본값("public"/False/0)으로
    덮어쓰면 반대쪽 설정이 리셋된다. 요청에 포함된 필드만 갱신되어야 한다.
    (회귀: 자동 삭제 저장 → default_visibility가 public으로 초기화되던 버그)
    """
    alice, alice_cookie = auth_cookie("alice")
    with get_session() as s:
        u = s.query(User).filter_by(id=alice.id).first()
        u.default_visibility = "followers"
        u.episode_default_visibility = "home"
        u.is_locked = True
        u.is_bot = True
        u.follow_list_visibility = "private"
        u.enable_reactions = False
        u.post_lifetime = 0
        s.commit()

    # 자동 삭제 페이지가 보내는 필드만 전송
    r = client.post("/api/settings/update", data={
        "post_lifetime": "7",
        "post_lifetime_exceptions": '["pinned","bookmarked"]',
    }, cookies=alice_cookie)
    assert r.status_code == 200

    with get_session() as s:
        u = s.query(User).filter_by(id=alice.id).first()
        assert u.default_visibility == "followers"          # 리셋되면 안 됨
        assert u.episode_default_visibility == "home"
        assert u.is_locked is True
        assert u.is_bot is True
        assert u.follow_list_visibility == "private"
        assert u.enable_reactions is False
        assert u.post_lifetime == 7
        assert u.post_lifetime_exceptions == ["pinned", "bookmarked"]

    # 반대 방향: 기본 설정 페이지처럼 공개 설정만 전송 → post_lifetime 유지
    r = client.post("/api/settings/update", data={
        "default_visibility": "followers",
        "is_locked": "true",
        "is_bot": "",
        "follow_list_visibility": "private",
        "enable_reactions": "true",
    }, cookies=alice_cookie)
    assert r.status_code == 200

    with get_session() as s:
        u = s.query(User).filter_by(id=alice.id).first()
        assert u.default_visibility == "followers"
        assert u.is_locked is True
        assert u.post_lifetime == 7                    # 리셋되면 안 됨
        assert u.post_lifetime_exceptions == ["pinned", "bookmarked"]


# ── 워커 스케줄 ──
# auto_delete_expired_posts()는 무한 루프라, 주기 대기(interval sleep)에서
# 예외를 던져 한 주기만 돌린 뒤 관찰한다.

class _StopLoop(Exception):
    pass


def _run_one_cycle(monkeypatch, busy, pass_results, max_sleeps=8):
    """워커를 한 주기만 돌리고 (패스별 삭제수, sleep 인자들)을 돌려준다.

    종료 신호는 '주기 대기'지만, 스케줄이 이전 구현(매일 3시)으로 되돌아가면
    그 sleep이 영영 오지 않아 루프가 끝나지 않는다. sleep 횟수 상한도 같이 두어
    그런 회귀는 멈추지 않고 실패하도록 한다."""
    workers_mod._cpu_cache = None
    monkeypatch.setattr(workers_mod, "_server_busy", lambda: busy)

    calls = []
    results = list(pass_results)

    def _fake_pass():
        calls.append(1)
        return results.pop(0) if results else 0

    monkeypatch.setattr(workers_mod, "_run_auto_delete_once", _fake_pass)

    sleeps = []
    interval = workers_mod.AUTO_DELETE_INTERVAL_SECONDS

    def _sleep(seconds):
        sleeps.append(seconds)
        if seconds == interval or len(sleeps) >= max_sleeps:  # 주기 대기 = 주기 종료
            raise _StopLoop

    monkeypatch.setattr(workers_mod.time, "sleep", _sleep)
    with pytest.raises(_StopLoop):
        workers_mod.auto_delete_expired_posts()
    return len(calls), sleeps


def test_auto_delete_interval_default_is_frequent():
    """하루 한 번(3시) 스케줄로 되돌아가지 않도록 기본 주기를 고정한다."""
    from app.config.settings import AUTO_DELETE_INTERVAL_SECONDS

    assert 0 < AUTO_DELETE_INTERVAL_SECONDS <= 3600


def test_worker_repeats_passes_until_nothing_left(monkeypatch):
    """0건이 나올 때까지 패스를 반복해 백로그를 비운다."""
    passes, sleeps = _run_one_cycle(monkeypatch, busy=False, pass_results=[3, 2, 0])
    assert passes == 3
    # 패스 사이에만 쿨다운이 있고, 마지막에 주기 대기 1회
    assert sleeps[-1] == workers_mod.AUTO_DELETE_INTERVAL_SECONDS
    assert all(s != workers_mod.AUTO_DELETE_INTERVAL_SECONDS for s in sleeps[:-1])


def test_worker_stops_after_single_pass_when_nothing_expired(monkeypatch):
    """만료된 글이 없으면 패스를 1번만 돌고 다음 주기로 넘어간다."""
    passes, _ = _run_one_cycle(monkeypatch, busy=False, pass_results=[0])
    assert passes == 1


def test_worker_busy_cycle_reschedules_on_interval(monkeypatch):
    """부하로 건너뛰어도 1800초 하드코딩이 아니라 정상 주기로 재예약한다.

    (회귀: 예전엔 busy면 sleep(1800)+continue로 스케줄이 3시에서 밀려났다)
    """
    passes, sleeps = _run_one_cycle(monkeypatch, busy=True, pass_results=[])
    assert passes == 0, "부하 상태에서 삭제 패스를 돌리면 안 됨"
    assert 1800 not in sleeps
    assert sleeps[-1] == workers_mod.AUTO_DELETE_INTERVAL_SECONDS


def test_worker_survives_pass_exception(monkeypatch):
    """패스에서 예외가 나도 워커가 죽지 않고 다음 주기로 넘어간다."""
    workers_mod._cpu_cache = None
    monkeypatch.setattr(workers_mod, "_server_busy", lambda: False)

    def _boom():
        raise RuntimeError("pass failed")

    monkeypatch.setattr(workers_mod, "_run_auto_delete_once", _boom)
    interval = workers_mod.AUTO_DELETE_INTERVAL_SECONDS
    sleeps = []

    def _sleep(seconds):
        sleeps.append(seconds)
        if seconds == interval or len(sleeps) >= 8:
            raise _StopLoop

    monkeypatch.setattr(workers_mod.time, "sleep", _sleep)
    with pytest.raises(_StopLoop):
        workers_mod.auto_delete_expired_posts()
    assert sleeps[-1] == interval


# ── 고정(핀) 예외 ──

def test_web_pin_endpoint_marks_post_pinned(client, auth_cookie, make_post):
    """웹 UI 고정 엔드포인트가 Post.is_pinned를 세워야 자동삭제 예외가 먹는다.

    (회귀: /api/pin/post/{id}가 User.pinned_posts만 갱신하고 is_pinned는 안 세웠다.
    그래서 프로필에는 고정으로 보이는데 자동삭제 워커는 False로 보고 지워버렸다)
    """
    alice, alice_cookie = auth_cookie("alice")
    _set_lifetime(alice, 7, exceptions=["pinned"])
    post = _age(make_post(alice), 30)

    r = client.post(f"/api/pin/post/{post.id}", cookies=alice_cookie)
    assert r.status_code == 200
    with get_session() as s:
        assert s.query(Post).filter_by(id=post.id).first().is_pinned is True

    assert _run_auto_delete_once() == 0
    assert post.id in _post_ids()


def test_web_unpin_endpoint_clears_post_pinned(client, auth_cookie, make_post):
    alice, alice_cookie = auth_cookie("alice")
    post = make_post(alice)
    client.post(f"/api/pin/post/{post.id}", cookies=alice_cookie)
    r = client.post(f"/api/unpin/post/{post.id}", cookies=alice_cookie)
    assert r.status_code == 200
    with get_session() as s:
        assert s.query(Post).filter_by(id=post.id).first().is_pinned is False


def test_pinned_posts_list_protects_post(client, auth_cookie, make_post):
    """is_pinned가 비어 있어도 User.pinned_posts에 있으면 삭제에서 제외한다.

    웹 UI 핀 버그로 is_pinned가 세어지지 않은 기존 데이터도 보호돼야 하므로,
    워커는 두 신호를 모두 본다.
    """
    alice, _alice_cookie = auth_cookie("alice")
    _set_lifetime(alice, 7, exceptions=["pinned"])
    post = _age(make_post(alice), 30)
    with get_session() as s:
        u = s.query(User).filter_by(id=alice.id).first()
        u.pinned_posts = [post.id]
        s.commit()

    assert _run_auto_delete_once() == 0
    assert post.id in _post_ids()
