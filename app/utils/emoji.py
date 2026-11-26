import contextlib
import os
import re
import shutil
import time

from sqlalchemy import case

from app.config.settings import S3_ENABLED
from app.models import CustomEmoji
from app.utils.storage import get_storage

# 이모지 파일은 쓰기 가능한 uploads 볼륨에 저장한다.
# (web/public/emojis는 read_only 컨테이너에서 쓸 수 없어 업로드/복사가 500으로 실패함)
EMOJI_DIR = os.path.join("uploads", "emojis")

# 이전 버전은 web/public/emojis에 저장했으므로 기동 시점에 마이그레이션한다.
_LEGACY_EMOJI_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "emojis")


def _migrate_legacy_emoji_files():
    """web/public/emojis에 남아 있는 이모지 파일을 uploads/emojis로 복사한다."""
    if not os.path.isdir(_LEGACY_EMOJI_DIR):
        return
    for sub in ("local", "remote"):
        _src = os.path.join(_LEGACY_EMOJI_DIR, sub)
        if not os.path.isdir(_src):
            continue
        _dst = os.path.join(EMOJI_DIR, sub)
        os.makedirs(_dst, exist_ok=True)
        for name in os.listdir(_src):
            _sp = os.path.join(_src, name)
            _dp = os.path.join(_dst, name)
            if os.path.isfile(_sp) and not os.path.exists(_dp):
                with contextlib.suppress(Exception):
                    shutil.copy2(_sp, _dp)

# Simple in-memory TTL cache for emoji list
_EMOJI_CACHE_TTL = 60  # seconds

_emoji_cache = {"data": None, "ts": 0}
_emoji_storage = None
_EMOJI_TOKEN_RE = re.compile(r":([a-z0-9_]+):")


def _invalidate_emoji_cache():
    """다음 조회 때 DB에서 다시 읽도록만 표시한다.

    원격 이모지가 추가될 때마다 전체 목록을 즉시 재생성하면, 임포트가 몰릴 때
    매번 전체 테이블을 스캔하게 된다. 실제로 목록이 필요한 시점에 한 번만
    재생성하는 편이 훨씬 싸다.
    """
    _emoji_cache["data"] = None
    _emoji_cache["ts"] = 0
    _emoji_cache.pop("index", None)
    _emoji_cache.pop("index_data", None)


def _refresh_emoji_cache_forcibly(session):
    emojis = session.query(CustomEmoji).all()
    # 딕셔너리 형태로 안전하게 직렬화
    serialized = [{
        "id": e.id,
        "keyword": e.keyword,
        "file_name": e.file_name,
        "category": e.category,
        "aliases": list(e.aliases) if e.aliases else [],
        "url": _emoji_url(e.file_name, e.domain or "", e.category or ""),
        "source_url": e.source_url or "",
        "domain": e.domain or ""
    } for e in emojis]
    _emoji_cache["data"] = serialized
    _emoji_cache["ts"] = time.time()


def pick_emoji_for_domain(emojis: list[dict], domain: str = "") -> dict | None:
    """여러 서버에 같은 shortcode가 있을 때 도메인에 맞는 이모지를 고른다.

    우선순위: 요청한 도메인 -> 로컬 정의(domain="") -> 첫 후보.
    """
    if not emojis:
        return None
    if domain:
        chosen = next((e for e in emojis if (e.get("domain") or "").lower() == domain.lower()), None)
        if chosen:
            return chosen
    return next((e for e in emojis if not e.get("domain")), None) or emojis[0]


def _emoji_url(file_name: str, domain: str = "", category: str = "") -> str:
    """Return the correct emoji URL (local or S3)."""
    global _emoji_storage
    sub = "remote" if domain or category == "remote" else "local"
    if S3_ENABLED:
        if _emoji_storage is None:
            _emoji_storage = get_storage()
        try:
            return _emoji_storage.url(f"emojis/{sub}/{file_name}")
        except Exception:
            pass
    return f"/emojis/{sub}/{file_name}"


def _load_emojis(session):
    """Load all emojis from DB, with simple in-memory TTL caching."""
    now = time.time()
    if _emoji_cache["data"] is not None and now - _emoji_cache["ts"] < _EMOJI_CACHE_TTL:
        return _emoji_cache["data"]
    emojis = session.query(CustomEmoji).order_by(
        case(
            (CustomEmoji.category == "remote", 1),
            else_=0
        ),
        CustomEmoji.created_at.desc()
    ).all()
    result = [
        {
            "id": e.id,
            "keyword": e.keyword,
            "file_name": e.file_name,
            "category": e.category or "",
            "aliases": e.aliases or [],
            "url": _emoji_url(e.file_name, e.domain or "", e.category or ""),
            "source_url": e.source_url or "",
            "domain": e.domain or "",
        }
        for e in emojis
    ]
    _emoji_cache["data"] = result
    _emoji_cache["ts"] = now
    _emoji_cache.pop("index", None)
    _emoji_cache.pop("index_data", None)
    return result


def emoji_keywords_in_text(text: str) -> set[str]:
    """텍스트에 등장하는 ``:keyword:`` 형태의 shortcode만 뽑는다."""
    return set(_EMOJI_TOKEN_RE.findall((text or "").lower()))


def _emoji_index(session):
    """keyword -> 후보 이모지 목록 인덱스를 캐시한다."""
    data = _load_emojis(session)
    index = _emoji_cache.get("index")
    if index is not None and _emoji_cache.get("index_data") is data:
        return index
    index = {}
    for e in data:
        index.setdefault(e["keyword"].lower(), []).append(e)
    _emoji_cache["index"] = index
    _emoji_cache["index_data"] = data
    return index

