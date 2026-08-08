"""Add reset_token_expires_at to users

비밀번호 재설정 토큰의 만료 시각을 DB에 저장해 1시간 유효 기간을 강제한다.
(revision 0035)

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0035'
down_revision: Union[str, None] = '0034'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_context().bind
    if bind is not None and bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP")
    else:
        cols = bind.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        if "reset_token_expires_at" not in {c[1] for c in cols}:
            op.execute("ALTER TABLE users ADD COLUMN reset_token_expires_at DATETIME")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS reset_token_expires_at")
