"""add reaction_domain to likes

원격 커스텀 이모지 리액션을 shortcode만으로 집계하면 서버별 이미지가 섞이므로,
이모지 출처 도메인을 저장해 배지를 분리한다.

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-26
"""

import os as _os
import sys as _sys
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe, drop_column_safe

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    add_column_safe(
        "likes",
        sa.Column(
            "reaction_domain",
            sa.String(128),
            nullable=False,
            server_default="",
        ),
    )
    # 기존 원격 리액션도 작성자 handle에서 도메인을 복원해 배지를 분리한다.
    conn = op.get_bind()
    if "users" in sa.inspect(conn).get_table_names():
        users = dict(conn.execute(sa.text("SELECT id, username FROM users")).all())
        for user_id, username in users.items():
            if not isinstance(username, str) or "@" not in username:
                continue
            domain = username.rsplit("@", 1)[-1].lower()
            conn.execute(
                sa.text(
                    "UPDATE likes SET reaction_domain = :domain "
                    "WHERE user_id = :user_id AND reaction LIKE ':%:' "
                    "AND (reaction_domain IS NULL OR reaction_domain = '')"
                ),
                {"domain": domain, "user_id": user_id},
            )


def downgrade() -> None:
    drop_column_safe("likes", "reaction_domain")
