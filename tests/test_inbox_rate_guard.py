"""인박스 레이트 가드 키잉 테스트 — 위조 actor로 저장소 오염 차단."""

from fastapi.testclient import TestClient

import app.routes.ap as ap_mod
from app.core import rate_limit


def test_pre_signature_guard_is_ip_keyed_only():
    """서명 전 가드는 IP 키만 건드린다: 위조 actor 문자열은 키를 만들지 않는다."""
    from fastapi import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/inbox",
        "headers": [],
        "client": ("203.0.113.9", 44444),
        "query_string": b"",
        "server": ("testserver", 80),
    }
    request = Request(scope)
    before = set(rate_limit._rate_limit_store) | set(rate_limit._rate_limit_daily)
    ap_mod._inbox_rate_guard_ip(request)
    after = set(rate_limit._rate_limit_store) | set(rate_limit._rate_limit_daily)
    new_keys = after - before
    assert new_keys, "IP 가드는 IP 기반 키를 생성해야 한다"
    assert all(k.startswith(("ip:", "daily:ip:")) for k in new_keys)


def test_actor_guard_only_runs_post_verification():
    """actor 가드는 신원 확인된 actor에만 적용되고 임의 문자열도 검증 후라 안전하다.

    여기서는 함수가 actor 키만 사용함을 확인한다.
    """
    before = set(rate_limit._rate_limit_store) | set(rate_limit._rate_limit_daily)
    ap_mod._inbox_rate_guard_actor("https://remote.example/users/bob")
    after = set(rate_limit._rate_limit_store) | set(rate_limit._rate_limit_daily)
    new_keys = after - before
    assert new_keys
    assert all(k.startswith(("actor:", "daily:actor:")) for k in new_keys)


def test_ip_guard_blocks_flood_from_same_ip(monkeypatch):
    """같은 IP에서 한도 초과 시 서명 검증 이전에 429로 거부된다."""
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_MAX", 3)
    calls = {"verify": 0}

    async def fake_verify(request, body, activity):
        calls["verify"] += 1
        return True, None

    monkeypatch.setattr(ap_mod, "_verify_signature_async", fake_verify)

    from tests.conftest import _build_app

    app = _build_app()
    with TestClient(app) as c:
        payload = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": "https://remote.example/activities/x",
            "type": "Delete",
            "actor": "https://remote.example/users/bob",
        }
        statuses = []
        for i in range(6):
            body = dict(payload)
            body["id"] = f"https://remote.example/activities/x{i}"
            r = c.post("/inbox", json=body)
            statuses.append(r.status_code)
        # 앞부분 일부는 서명 실패(401)로 끝나지만, 한도 초과분은 429여야 하고
        # 서명 검증이 계속 호출되지 않는다(가드가 먼저 차단).
        assert statuses.count(429) >= 1
        assert calls["verify"] < 6
