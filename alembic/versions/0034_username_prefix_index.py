"""Add prefix-search index on users.username

멘션/답글 시 리모트 핸들 해석(User.username.like('user@%'))과 작성창 @ 자동완성
(User.username.ilike('prefix%'))이 users 테이블을 전체 스캔하는 것을 막기 위한
접두사 전용 인덱스.

- Postgres: lower(username) text_pattern_ops (쿼리는 lower(username) LIKE 'prefix%')
- SQLite: username COLLATE NOCASE (쿼리는 username LIKE 'prefix%')

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0034'
down_revision: Union[str, None] = '0033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_context().bind
    if bind is not None and bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_users_lower_username "
            "ON users (lower(username) text_pattern_ops)"
        )
    else:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_users_username_nocase "
            "ON users (username COLLATE NOCASE)"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_lower_username")
    op.execute("DROP INDEX IF EXISTS ix_users_username_nocase")
