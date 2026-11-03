"""add server-side archive jobs

게시물/시리즈/프로필/사진을 하나의 ZIP으로 서버에서 생성하고, 완료 시
알림으로 알려주기 위한 작업 상태 테이블.

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-03
"""
import os as _os
import sys as _sys
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from helpers import index_exists, table_exists

revision: str = '0044'
down_revision: str | None = '0043'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if table_exists("archive_jobs"):
        return
    op.create_table(
        "archive_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_archive_jobs_uuid"), "archive_jobs", ["uuid"], unique=True)
    op.create_index(op.f("ix_archive_jobs_user_id"), "archive_jobs", ["user_id"], unique=False)
    op.create_index(op.f("ix_archive_jobs_status"), "archive_jobs", ["status"], unique=False)


def downgrade() -> None:
    if not table_exists("archive_jobs"):
        return
    for name in ("ix_archive_jobs_status", "ix_archive_jobs_user_id", "ix_archive_jobs_uuid"):
        if index_exists("archive_jobs", name):
            op.drop_index(op.f(name), table_name="archive_jobs")
    op.drop_table("archive_jobs")
