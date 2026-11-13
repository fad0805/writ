"""add owner to Mastodon OAuth applications

The developer settings page lists only applications created by the current
user, so apps need an owner.  Apps registered through the public
``POST /api/v1/apps`` endpoint remain ownerless (NULL).

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-13
"""
import os as _os
import sys as _sys
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe, drop_column_safe, index_exists

revision: str = '0045'
down_revision: str | None = '0044'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite cannot ALTER an existing table to add a foreign-key constraint,
    # so keep the column itself portable.  The ORM still declares the FK.
    add_column_safe(
        "mastodon_apps",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    if not index_exists("mastodon_apps", "ix_mastodon_apps_user_id"):
        op.create_index(op.f("ix_mastodon_apps_user_id"), "mastodon_apps", ["user_id"], unique=False)


def downgrade() -> None:
    if index_exists("mastodon_apps", "ix_mastodon_apps_user_id"):
        op.drop_index(op.f("ix_mastodon_apps_user_id"), table_name="mastodon_apps")
    drop_column_safe("mastodon_apps", "user_id")
