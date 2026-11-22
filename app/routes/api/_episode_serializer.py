"""Episode JSON serializer.

_episodes와 _novels가 서로 _episode_json/_novel_json을 import하는 순환을
끊기 위해 분리했다. 이 모듈은 라우트에 의존하지 않는다.
"""

from app.models import Episode
from app.utils.datetime import _fmt_dt

# summary_only 응답에 필요한 컬럼만 조회하기 위한 projection.
# content(본문)는 목록에서 쓰지 않으므로 의도적으로 제외한다.
EPISODE_SUMMARY_COLUMNS = (
    Episode.id,
    Episode.novel_id,
    Episode.episode_number,
    Episode.title,
    Episode.summary,
    Episode.comment,
    Episode.audio_url,
    Episode.view_mode,
    Episode.comic_view_mode,
    Episode.image_urls,
    Episode.reading_direction,
    Episode.views,
    Episode.is_published,
    Episode.page_mode,
    Episode.created_at,
    Episode.updated_at,
)


def _episode_json(e, summary_only=False):
    d = {
        "id": e.id,
        "novel_id": e.novel_id,
        "episode_number": e.episode_number,
        "title": e.title,
        "summary": e.summary or "",
        "comment": e.comment or "",
        "audio_url": e.audio_url or "",
        "view_mode": getattr(e, "view_mode", "text"),
        "comic_view_mode": getattr(e, "comic_view_mode", "paged"),
        "image_urls": getattr(e, "image_urls", []) or [],
        "reading_direction": getattr(e, "reading_direction", None) or "ltr",
        "views": e.views or 0,
        "is_published": e.is_published,
        "page_mode": getattr(e, "page_mode", False),
        "created_at": _fmt_dt(e.created_at),
        "updated_at": _fmt_dt(e.updated_at),
    }
    if not summary_only:
        d["content"] = e.content
    return d
