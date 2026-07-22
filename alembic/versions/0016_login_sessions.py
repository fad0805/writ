"""add login_sessions table

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-22

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0016'
down_revision: Union[str, None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "login_sessions" not in inspector.get_table_names():
        op.create_table(
            "login_sessions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("session_key", sa.String(64), nullable=False),
            sa.Column("ip_address", sa.String(45), server_default=""),
            sa.Column("user_agent", sa.Text, server_default=""),
            sa.Column("last_active", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_login_session_key", "login_sessions", ["session_key"], unique=True)
        op.create_index("ix_login_session_user", "login_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("login_sessions")
