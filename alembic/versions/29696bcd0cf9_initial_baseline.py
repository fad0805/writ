"""Initial baseline

Revision ID: 29696bcd0cf9
Revises: 0006
Create Date: 2026-07-13 08:37:23.349814

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29696bcd0cf9'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table, index):
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return index in [idx["name"] for idx in inspector.get_indexes(table)]


def upgrade() -> None:
    for name, table in [
        ('ix_follows_follower_following', 'follows'),
        ('ix_notif_user_created', 'notifications'),
        ('ix_notif_user_type', 'notifications'),
        ('ix_posts_author_created', 'posts'),
        ('ix_posts_author_deleted_created', 'posts'),
    ]:
        if _index_exists(table, name):
            op.drop_index(name, table_name=table)


def downgrade() -> None:
    op.create_index('ix_posts_author_deleted_created', 'posts', ['author_id', 'is_deleted', 'created_at'], unique=False)
    op.create_index('ix_posts_author_created', 'posts', ['author_id', 'created_at'], unique=False)
    op.create_index('ix_notif_user_type', 'notifications', ['user_id', 'notification_type'], unique=False)
    op.create_index('ix_notif_user_created', 'notifications', ['user_id', 'created_at'], unique=False)
    op.create_index('ix_follows_follower_following', 'follows', ['follower_id', 'following_id'], unique=False)
