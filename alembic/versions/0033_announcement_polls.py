"""Add announcement poll (poll_data column + announcement_votes table)

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0033'
down_revision: Union[str, None] = '0032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("announcements", sa.Column("poll_data", sa.JSON(), nullable=True))
    op.create_table(
        "announcement_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("announcement_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("option_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_announcement_votes_announcement_user",
        "announcement_votes",
        ["announcement_id", "user_id"],
        unique=True,
    )
    op.create_index("ix_announcement_votes_announcement_id", "announcement_votes", ["announcement_id"])
    op.create_index("ix_announcement_votes_user_id", "announcement_votes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_announcement_votes_user_id", table_name="announcement_votes")
    op.drop_index("ix_announcement_votes_announcement_id", table_name="announcement_votes")
    op.drop_index("ix_announcement_votes_announcement_user", table_name="announcement_votes")
    op.drop_table("announcement_votes")
    op.drop_column("announcements", "poll_data")
