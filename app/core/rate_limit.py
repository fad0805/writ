"""인프로세스 슬라이딩 윈도우 레이트 리밋.

한계(문서화): 저장소가 프로세스 로컬 dict이므로 uvicorn/gunicorn 워커를
N개로 띄우면 실효 한도도 N배가 된다(키 분산 + 카운터 비공유). 단일
인스턴스 소규모 배포를 전제로 하며, 수평 확장 시 Redis 등 공유 저장소로
교체해야 정확한 한도가 유지된다. 인터페이스(check_* 함수)는 유지되므로
내부 구현만 바꾸면 된다.

메모리 상한: 키 1만 개 초과 시 만료 키 스윕(_SWEEP_THRESHOLD). 과거에는
위조 가능한 actor 문자열이 키로 쓰여 이 스윕을 강제하는 공격이 가능했지만,
인박스 가드는 서명 검증 전 IP 기준 / 검증 후 actor 기준으로 분리되어
(app/routes/ap.py _inbox_rate_guard_ip/_actor) 위조 키 생성이 차단됐다.
"""

import threading
import time
from collections import defaultdict

RATE_LIMIT_WINDOW = 60
# 인박스로 몰려드는 페더레이션 트래픽은 같은 IP(상대 인스턴스 서버)에서 대량으로
# 들어온다. 아래 제한은 "위조/플러드"만 걸러내는 DoS 가드 수준으로 잡으며, 정상
# 인스턴스의 일상 동기화(백필, like/boost 폭주, 팔로우 폭풍)는 걸리지 않는다.
RATE_LIMIT_MAX = 300
RATE_LIMIT_BURST = 100
RATE_LIMIT_DAILY = 5000
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_daily: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()
_SWEEP_THRESHOLD = 10_000


def _sweep_if_large() -> None:
    """Drop keys whose history is entirely expired to bound memory."""
    if len(_rate_limit_store) > _SWEEP_THRESHOLD:
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW
        kept = {k: v for k, v in _rate_limit_store.items() if any(t > window_start for t in v)}
        _rate_limit_store.clear()
        _rate_limit_store.update(kept)
    if len(_rate_limit_daily) > _SWEEP_THRESHOLD:
        now = time.time()
        day_start = now - 86400
        kept = {k: v for k, v in _rate_limit_daily.items() if any(t > day_start for t in v)}
        _rate_limit_daily.clear()
        _rate_limit_daily.update(kept)


def check_rate_limit(key: str) -> bool:
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    with _rate_limit_lock:
        _sweep_if_large()
        timestamps = _rate_limit_store[key]
        pruned = [t for t in timestamps if t > window_start]
        if len(pruned) >= RATE_LIMIT_MAX:
            return False
        _rate_limit_store[key] = [*pruned, now]
        return True


def check_burst_limit(key: str) -> bool:
    now = time.time()
    burst_start = now - 5
    with _rate_limit_lock:
        timestamps = _rate_limit_store[key]
        recent = [t for t in timestamps if t > burst_start]
        return not len(recent) >= RATE_LIMIT_BURST


def check_daily_limit(key: str) -> bool:
    now = time.time()
    day_start = now - 86400
    with _rate_limit_lock:
        timestamps = _rate_limit_daily[key]
        pruned = [t for t in timestamps if t > day_start]
        if len(pruned) >= RATE_LIMIT_DAILY:
            return False
        _rate_limit_daily[key] = [*pruned, now]
        return True
