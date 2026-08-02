"""Add announcements and announcement_reads tables

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0032'
down_revision: Union[str, None] = '0031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(36), nullable=False, unique=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "announcement_reads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("announcement_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_announcement_reads_announcement_user",
        "announcement_reads",
        ["announcement_id", "user_id"],
        unique=True,
    )
    op.create_index("ix_announcement_reads_announcement_id", "announcement_reads", ["announcement_id"])
    op.create_index("ix_announcement_reads_user_id", "announcement_reads", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_announcement_reads_user_id", table_name="announcement_reads")
    op.drop_index("ix_announcement_reads_announcement_id", table_name="announcement_reads")
    op.drop_index("ix_announcement_reads_announcement_user", table_name="announcement_reads")
    op.drop_table("announcement_reads")
    op.drop_table("announcements")
