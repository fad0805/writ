"""backfill posts.is_pinned from users.pinned_posts

웹 UI 고정 엔드포인트(/api/pin/post/{id})가 User.pinned_posts만 갱신하고
Post.is_pinned를 세우지 않았다. 프로필 렌더는 pinned_posts를 보므로 사용자에게는
고정된 글로 보이는데 자동삭제 워커는 is_pinned=False로 보고 지워버렸다.

핀 엔드포인트와 자동삭제 판정은 이미 고쳤지만, 이미 고정한 기존 데이터의
is_pinned가 비어 있는 상태를 heal한다. (마스토돈 API가 pinned로 노출하는 값도
이 필드를 본다)

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-29
"""
import json
from typing import Any, Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = '0042'
down_revision: Union[str, None] = '0041'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SELECT = text("SELECT id, pinned_posts FROM users")
_UPDATE = text("UPDATE posts SET is_pinned = :flag WHERE id = :pid AND author_id = :uid")


def _pinned_ids(raw: Any) -> set[int]:
    """pinned_posts를 post id 집합으로 바꾼다.

    raw SQL로 읽은 값이라 dialect마다 형태가 다르다.
    PostgreSQL JSON 컬럼은 이미 list, SQLite는 JSON 문자열로 온다.
    """
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return set()
    if not isinstance(raw, list):
        return set()
    ids = set()
    for pid in raw:
        try:
            ids.add(int(pid))
        except (TypeError, ValueError):
            continue
    return ids


def upgrade() -> None:
    bind = op.get_context().bind
    if bind is None:
        return
    for user_id, raw in bind.execute(_SELECT).fetchall():
        for post_id in _pinned_ids(raw):
            # author_id까지 조건에 넣어 남의 글 id가 섞여 있어도 건드리지 않는다.
            bind.execute(_UPDATE, {"flag": True, "pid": post_id, "uid": user_id})


def downgrade() -> None:
    """되돌리지 않는다.

    is_pinned만으로 고정돼 있던 글과 pinned_posts에서 온 글은 이제 구분이 불가해
    되돌리면 함께 풀려 버린다. 마스토돈 API 핀도 is_pinned=True이므로 위험하다.
    """
    pass
