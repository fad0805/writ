"""Add mastodon oauth tables

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mastodon_apps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_name", sa.String(256), nullable=False),
        sa.Column("redirect_uris", sa.Text, default="urn:ietf:wg:oauth:2.0:oob"),
        sa.Column("scopes", sa.String(256), default="read write push"),
        sa.Column("website", sa.String(512), default=""),
        sa.Column("client_id", sa.String(128), unique=True, nullable=False),
        sa.Column("client_secret", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_mastodon_apps_client_id", "mastodon_apps", ["client_id"])

    op.create_table(
        "mastodon_access_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("app_id", sa.Integer, sa.ForeignKey("mastodon_apps.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("access_token", sa.String(256), unique=True, nullable=False),
        sa.Column("scopes", sa.String(256), default="read write push"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_mastodon_access_tokens_app_id", "mastodon_access_tokens", ["app_id"])
    op.create_index("ix_mastodon_access_tokens_user_id", "mastodon_access_tokens", ["user_id"])
    op.create_index("ix_mastodon_access_tokens_access_token", "mastodon_access_tokens", ["access_token"])

    op.create_table(
        "mastodon_authorization_codes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(128), unique=True, nullable=False),
        sa.Column("app_id", sa.Integer, sa.ForeignKey("mastodon_apps.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("redirect_uri", sa.Text, default=""),
        sa.Column("scopes", sa.String(256), default="read write push"),
        sa.Column("used", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_mastodon_auth_codes_code", "mastodon_authorization_codes", ["code"])


def downgrade():
    op.drop_index("ix_mastodon_auth_codes_code", table_name="mastodon_authorization_codes")
    op.drop_table("mastodon_authorization_codes")
    op.drop_index("ix_mastodon_access_tokens_access_token", table_name="mastodon_access_tokens")
    op.drop_index("ix_mastodon_access_tokens_user_id", table_name="mastodon_access_tokens")
    op.drop_index("ix_mastodon_access_tokens_app_id", table_name="mastodon_access_tokens")
    op.drop_table("mastodon_access_tokens")
    op.drop_index("ix_mastodon_apps_client_id", table_name="mastodon_apps")
    op.drop_table("mastodon_apps")
