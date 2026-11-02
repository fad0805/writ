"""add post edit history

게시글 수정 표시(edited_at)와 상세 페이지의 수정 이력(post_edits)을 저장한다.
post_edits에는 수정 직전 버전만 남기고 현재 버전은 posts 본체를 사용한다.

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-02
"""
import os as _os
import sys as _sys
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import add_column_safe, drop_column_safe, index_exists, table_exists

revision: str = '0043'
down_revision: Union[str, None] = '0042'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    add_column_safe("posts", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    if not table_exists("post_edits"):
        op.create_table(
            "post_edits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("summary", sa.String(length=512), nullable=True),
            sa.Column("visibility", sa.String(length=16), nullable=False),
            sa.Column("is_sensitive", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(op.f("ix_post_edits_post_id"), "post_edits", ["post_id"], unique=False)


def downgrade() -> None:
    if table_exists("post_edits"):
        if index_exists("post_edits", "ix_post_edits_post_id"):
            op.drop_index(op.f("ix_post_edits_post_id"), table_name="post_edits")
        op.drop_table("post_edits")
    drop_column_safe("posts", "edited_at")
