"""add ondelete set null to posts episode_id

Revision ID: add_ondelete_set_null_posts
Revises: 0012  # <-- 실제 사용 중인 이전 마이그레이션 파일의 Revision ID를 적어주세요.
Create Date: 2026-07-18 18:48:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

def upgrade():
    # SQLite 등 일부 DB에서도 안전하게 외래키를 수정할 수 있도록 batch_alter_table을 사용합니다.
    with op.batch_alter_table('posts', schema=None) as batch_op:
        # 기존 외래키를 drop하고 새로운 제약 조건을 생성합니다.
        # 기존 외래키 이름이 명확하지 않은 경우가 많으므로 drop_constraint를 건너뛰고 
        # 새롭게 정의하는 방식을 취합니다. (새 제약조건 이름: fk_posts_episode_id_episodes)
        batch_op.create_foreign_key(
            'fk_posts_episode_id_episodes',
            'episodes',                  # 대상 테이블
            ['episode_id'],              # 소스 컬럼
            ['id'],                      # 대상 컬럼
            ondelete='SET NULL'          # 우리가 원하던 옵션!
        )


def downgrade():
    with op.batch_alter_table('posts', schema=None) as batch_op:
        # 롤백(downgrade) 시에는 다시 ON DELETE 옵션이 없는 원래 상태로 되돌립니다.
        batch_op.drop_constraint('fk_posts_episode_id_episodes', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_posts_episode_id_episodes',
            'episodes',
            ['episode_id'],
            ['id']
        )
