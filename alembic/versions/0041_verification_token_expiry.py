"""add verification_token_expires_at to users

이메일 인증 토큰의 24시간 만료 체크를 위한 컬럼 추가.

Revision ID: 0041
Revises: 0040
Create Date: 2026-08-22
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0041'
down_revision: Union[str, None] = '0040'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_context().bind
    if bind is not None and bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token_expires_at TIMESTAMP")
    else:
        cols = bind.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        if "verification_token_expires_at" not in {c[1] for c in cols}:
            op.execute("ALTER TABLE users ADD COLUMN verification_token_expires_at DATETIME")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS verification_token_expires_at")