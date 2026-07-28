"""add profile_url to users

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-11

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    add_column_safe("users", sa.Column("profile_url", sa.String(512), server_default=""))


def downgrade() -> None:
    op.drop_column("users", "profile_url")
