import os
import time

from sqlalchemy import desc

from app.models import CustomEmoji
from app.config.settings import S3_ENABLED

EMOJI_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "emojis")

# Simple in-memory TTL cache for emoji list
_EMOJI_CACHE_TTL = 60  # seconds

_emoji_cache = {"data": None, "ts": 0}
_emoji_storage = None

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


def _emoji_url(file_name: str, domain: str = "", category: str = "") -> str:
    """Return the correct emoji URL (local or S3)."""
    global _emoji_storage
    sub = "remote" if domain or category == "remote" else "local"
    if S3_ENABLED:
        if _emoji_storage is None:
            from app.utils.storage import get_storage
            _emoji_storage = get_storage()
        try:
            return _emoji_storage.url(f"emojis/{sub}/{file_name}")
        except Exception:
            pass
    return f"/emojis/{sub}/{file_name}"


def _load_emojis(session):
    """Load all emojis from DB, with simple in-memory TTL caching."""
    import time as _time
    now = _time.time()
    if _emoji_cache["data"] is not None and now - _emoji_cache["ts"] < _EMOJI_CACHE_TTL:
        return _emoji_cache["data"]
    emojis = session.query(CustomEmoji).order_by(desc(CustomEmoji.created_at)).all()
    from sqlalchemy import case
    emojis = session.query(CustomEmoji).order_by(
        case(
            (CustomEmoji.category == "remote", 1),
            else_=0
        ),
        CustomEmoji.created_at.desc() # 동일 조건 내에서는 최신순 정렬
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
    return result

