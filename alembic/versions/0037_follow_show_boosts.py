"""add show_boosts to follows

팔로우 유지한 채 상대의 부스트만 숨기는 per-follow 설정.
기본값 True (부스트 표시), False면 해당 유저의 부스트만 홈 피드에서 걸러낸다.

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe


revision: str = '0037'
down_revision: Union[str, None] = '0036'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    add_column_safe("follows", sa.Column("show_boosts", sa.Boolean(), default=True))


def downgrade() -> None:
    op.drop_column("follows", "show_boosts")
