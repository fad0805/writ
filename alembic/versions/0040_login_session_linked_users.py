"""add linked_user_ids to login_sessions

계정 전환을 클라이언트 저장 토큰 대신 서버 측 linked set으로 검증하기 위한 컬럼.

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0040'
down_revision: str | None = '0039'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "login_sessions" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("login_sessions")]
    if "linked_user_ids" not in columns:
        op.add_column("login_sessions", sa.Column("linked_user_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "login_sessions" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("login_sessions")]
    if "linked_user_ids" in columns:
        op.drop_column("login_sessions", "linked_user_ids")
