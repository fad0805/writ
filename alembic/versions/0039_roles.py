"""create roles table for role/permission management

역할(owner/admin/moderator/user)별 권한 목록을 저장하는 roles 테이블을
생성한다. 초기 데이터는 앱 시작 시 ensure_default_roles()가 채운다.

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0039'
down_revision: Union[str, None] = '0038'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=16), nullable=False),
        sa.Column('label', sa.String(length=50), nullable=True),
        sa.Column('permissions', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f('ix_roles_name'), 'roles', ['name'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_roles_name'), table_name='roles')
    op.drop_table('roles')
