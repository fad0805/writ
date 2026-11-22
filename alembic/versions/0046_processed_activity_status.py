"""add status to processed activities

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("processed_activities") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default="done",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("processed_activities") as batch_op:
        batch_op.drop_column("status")
