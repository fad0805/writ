"""create all tables

Revision ID: 0000
Revises: None
Create Date: 2026-07-28

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0000'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', sa.String(36), unique=True, nullable=False),
        sa.Column('username', sa.String(64), unique=True, nullable=False, index=True),
        sa.Column('display_name', sa.String(128), nullable=True, default=''),
        sa.Column('summary', sa.Text(), nullable=True, default=''),
        sa.Column('email', sa.String(255), unique=True, nullable=True, default=''),
        sa.Column('email_verified', sa.Boolean(), nullable=True, default=False),
        sa.Column('verification_token', sa.String(128), nullable=True, default=''),
        sa.Column('reset_token', sa.String(128), nullable=True, default=''),
        sa.Column('recent_ips', sa.JSON(), nullable=True, default=list),
        sa.Column('is_suspended', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_frozen', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_deactivated', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_sensitive', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_limited', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_deceased', sa.Boolean(), nullable=True, default=False),
        sa.Column('moderation_note', sa.Text(), nullable=True, default=''),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('private_key', sa.Text(), nullable=False),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('inbox_url', sa.String(512), nullable=True),
        sa.Column('outbox_url', sa.String(512), nullable=True),
        sa.Column('followers_url', sa.String(512), nullable=True),
        sa.Column('following_url', sa.String(512), nullable=True),
        sa.Column('remote_followers_count', sa.Integer(), nullable=True, default=0),
        sa.Column('remote_following_count', sa.Integer(), nullable=True, default=0),
        sa.Column('is_remote', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_admin', sa.Boolean(), nullable=True, default=False),
        sa.Column('role', sa.String(16), nullable=True, default='user'),
        sa.Column('remote_url', sa.String(512), nullable=True, default=''),
        sa.Column('profile_url', sa.String(512), nullable=True, default=''),
        sa.Column('shared_inbox_url', sa.String(512), nullable=True, default=''),
        sa.Column('profile_image', sa.String(512), nullable=True, default=''),
        sa.Column('header_image', sa.String(512), nullable=True, default=''),
        sa.Column('default_visibility', sa.String(16), nullable=True, default='public'),
        sa.Column('episode_default_visibility', sa.String(16), nullable=True, default='public'),
        sa.Column('is_locked', sa.Boolean(), nullable=True, default=False),
        sa.Column('show_badge', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_bot', sa.Boolean(), nullable=True, default=False),
        sa.Column('display_handle', sa.String(64), nullable=True, default=''),
        sa.Column('follow_list_visibility', sa.String(16), nullable=True, default='public'),
        sa.Column('custom_fields', sa.JSON(), nullable=True, default=list),
        sa.Column('profile_hashtags', sa.JSON(), nullable=True, default=list),
        sa.Column('enable_reactions', sa.Boolean(), nullable=True, default=True),
        sa.Column('post_lifetime', sa.Integer(), nullable=True, default=0),
        sa.Column('post_lifetime_exceptions', sa.JSON(), nullable=True, default=list),
        sa.Column('pinned_posts', sa.JSON(), nullable=True, default=list),
        sa.Column('pinned_series', sa.JSON(), nullable=True, default=list),
        sa.Column('aliases', sa.JSON(), nullable=True, default=list),
        sa.Column('moved_to', sa.String(512), nullable=True, default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('session_token', sa.String(64), nullable=True, default=''),
    )

    op.create_table('follows',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('follower_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('following_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('accepted', sa.Boolean(), nullable=True, default=True),
        sa.Column('activity_id', sa.String(1024), nullable=True, default=''),
        sa.Column('notify_on_post', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('tags',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(128), unique=True, nullable=False, index=True),
        sa.Column('display_name', sa.String(128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('custom_emojis',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('keyword', sa.String(128), nullable=False, index=True),
        sa.Column('file_name', sa.String(256), nullable=False),
        sa.Column('category', sa.String(64), nullable=True, default=''),
        sa.Column('aliases', sa.JSON(), nullable=True, default=list),
        sa.Column('source_url', sa.String(512), nullable=True, default=''),
        sa.Column('domain', sa.String(128), nullable=True, default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('novels',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', sa.String(36), unique=True, nullable=False),
        sa.Column('number', sa.String(16), nullable=False, default=''),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True, default=''),
        sa.Column('cover_image', sa.String(512), nullable=True, default=''),
        sa.Column('tags', sa.String(512), nullable=True, default=''),
        sa.Column('status', sa.String(16), nullable=True, default='ongoing'),
        sa.Column('is_published', sa.Boolean(), nullable=True, default=True),
        sa.Column('is_sensitive', sa.Boolean(), nullable=True, default=False),
        sa.Column('visibility', sa.String(16), nullable=False, default='public'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('novel_tags',
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id'), primary_key=True),
        sa.Column('tag_id', sa.Integer(), sa.ForeignKey('tags.id'), primary_key=True),
    )

    op.create_table('episodes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', sa.String(36), unique=True, nullable=False),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id'), nullable=False, index=True),
        sa.Column('episode_number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True, default=''),
        sa.Column('comment', sa.Text(), nullable=True, default=''),
        sa.Column('audio_url', sa.String(512), nullable=True, default=''),
        sa.Column('view_mode', sa.String(16), nullable=True, default='text'),
        sa.Column('comic_view_mode', sa.String(16), nullable=True, default='paged'),
        sa.Column('image_urls', sa.JSON(), nullable=True, default=list),
        sa.Column('reading_direction', sa.String(8), nullable=True, default='ltr'),
        sa.Column('views', sa.Integer(), nullable=True, default=0),
        sa.Column('is_published', sa.Boolean(), nullable=True, default=True),
        sa.Column('page_mode', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('episode_drafts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id'), nullable=False, index=True),
        sa.Column('episode_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(256), nullable=True, default=''),
        sa.Column('summary', sa.Text(), nullable=True, default=''),
        sa.Column('content', sa.Text(), nullable=True, default=''),
        sa.Column('comment', sa.Text(), nullable=True, default=''),
        sa.Column('is_published', sa.Boolean(), nullable=True, default=True),
        sa.Column('announce', sa.Boolean(), nullable=True, default=False),
        sa.Column('announce_comment', sa.String(200), nullable=True, default=''),
        sa.Column('visibility', sa.String(20), nullable=True, default='public'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('posts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', sa.String(36), unique=True, nullable=False),
        sa.Column('number', sa.String(16), nullable=False, default=''),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('summary', sa.String(512), nullable=True, default=''),
        sa.Column('visibility', sa.String(16), nullable=False, default='public'),
        sa.Column('mentioned_user_ids', sa.JSON(), nullable=True, default=list),
        sa.Column('ap_id', sa.String(1024), unique=True, nullable=True),
        sa.Column('in_reply_to_id', sa.Integer(), sa.ForeignKey('posts.id'), nullable=True, index=True),
        sa.Column('in_reply_to_ap_id', sa.String(1024), nullable=True, default=''),
        sa.Column('boost_of_id', sa.Integer(), sa.ForeignKey('posts.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('quote_of_id', sa.Integer(), sa.ForeignKey('posts.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('quote_of_ap_id', sa.String(1024), nullable=True, default=''),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id', ondelete='SET NULL'), nullable=True),
        sa.Column('episode_id', sa.Integer(), sa.ForeignKey('episodes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_pinned', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_dm', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_sensitive', sa.Boolean(), nullable=True, default=False),
        sa.Column('original_visibility', sa.String(16), nullable=True, default=''),
        sa.Column('media_attachments', sa.JSON(), nullable=True, default=list),
        sa.Column('poll_data', sa.JSON(), nullable=True),
        sa.Column('link_preview', sa.JSON(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('post_tags',
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('posts.id'), primary_key=True),
        sa.Column('tag_id', sa.Integer(), sa.ForeignKey('tags.id'), primary_key=True),
    )

    op.create_table('votes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('posts.id'), nullable=False, index=True),
        sa.Column('option_index', sa.Integer(), nullable=False),
        sa.Column('ap_id', sa.String(1024), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('likes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('posts.id'), nullable=False, index=True),
        sa.Column('ap_id', sa.String(1024), unique=True, nullable=True),
        sa.Column('reaction', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('boosts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('posts.id'), nullable=False, index=True),
        sa.Column('ap_id', sa.String(1024), unique=True, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('bookmarks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('posts.id'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('notifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('from_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('notification_type', sa.String(32), nullable=False),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('posts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True, default=''),
        sa.Column('is_read', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('push_subscriptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('p256dh', sa.Text(), nullable=False),
        sa.Column('auth', sa.Text(), nullable=False),
        sa.Column('device_name', sa.String(256), nullable=True, default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('login_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('session_key', sa.String(64), unique=True, nullable=False, index=True),
        sa.Column('ip_address', sa.String(45), nullable=True, default=''),
        sa.Column('user_agent', sa.Text(), nullable=True, default=''),
        sa.Column('last_active', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('series_follows',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('series_notices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', sa.String(36), unique=True, nullable=False),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id'), nullable=False, index=True),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('is_pinned', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('profile_notes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('target_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('content', sa.Text(), nullable=True, default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('server_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True, default=''),
        sa.Column('sort_order', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('reporter_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('target_type', sa.String(32), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('rule_ids', sa.JSON(), nullable=True, default=list),
        sa.Column('status', sa.String(16), nullable=False, default='pending'),
        sa.Column('forward_to_remote', sa.Boolean(), nullable=True, default=False),
        sa.Column('resolved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('blocked_domains',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('domain', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('federation_blocks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('domain', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('reason', sa.String(512), nullable=True, default=''),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('allowed_servers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('domain', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('muted_servers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('domain', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('muted', sa.Boolean(), nullable=True, default=True),
        sa.Column('media_muted', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('admin_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('username', sa.String(255), nullable=True, default=''),
        sa.Column('action', sa.String(50), nullable=False, index=True),
        sa.Column('target_type', sa.String(50), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('target_username', sa.String(255), nullable=True, default=''),
        sa.Column('details', sa.Text(), nullable=True, default=''),
        sa.Column('ip_address', sa.String(45), nullable=True, default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('user_mutes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('target_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('duration', sa.Integer(), nullable=True, default=0),
        sa.Column('hide_notifications', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('user_blocks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('target_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('series_mutes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('keyword_mutes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('keyword', sa.String(512), nullable=False),
        sa.Column('name', sa.String(128), nullable=True, default=''),
        sa.Column('mode', sa.String(8), nullable=True, default='or'),
        sa.Column('is_regex', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('episode_views',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('episode_id', sa.Integer(), sa.ForeignKey('episodes.id'), nullable=False),
        sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('server_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('server_name', sa.String(255), nullable=True, default='WRIT'),
        sa.Column('server_description', sa.Text(), nullable=True, default=''),
        sa.Column('logo', sa.String(512), nullable=True, default=''),
        sa.Column('favicon', sa.String(512), nullable=True, default=''),
        sa.Column('app_icon', sa.String(512), nullable=True, default=''),
        sa.Column('admin_ids', sa.String(512), nullable=True, default=''),
        sa.Column('admin_email', sa.String(255), nullable=True, default=''),
        sa.Column('federation_mode', sa.String(16), nullable=True, default='blacklist'),
        sa.Column('enable_reactions', sa.Boolean(), nullable=True, default=True),
        sa.Column('vapid_private_key', sa.Text(), nullable=True, default=''),
        sa.Column('vapid_public_key', sa.Text(), nullable=True, default=''),
    )

    op.create_table('processed_activities',
        sa.Column('id', sa.String(1024), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('remote_media',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('remote_url', sa.String(1024), nullable=False, index=True),
        sa.Column('local_url', sa.String(512), nullable=False),
        sa.Column('size', sa.Integer(), nullable=True, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('pending_deliveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('inbox_url', sa.String(512), nullable=False),
        sa.Column('activity_json', sa.Text(), nullable=False),
        sa.Column('sender_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(16), nullable=True, default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=True, default=0),
        sa.Column('last_error', sa.Text(), nullable=True, default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('mastodon_apps',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('client_name', sa.String(256), nullable=False),
        sa.Column('redirect_uris', sa.Text(), nullable=True, default='urn:ietf:wg:oauth:2.0:oob'),
        sa.Column('scopes', sa.String(256), nullable=True, default='read write push'),
        sa.Column('website', sa.String(512), nullable=True, default=''),
        sa.Column('client_id', sa.String(128), unique=True, nullable=False, index=True),
        sa.Column('client_secret', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('mastodon_access_tokens',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mastodon_apps.id'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('access_token', sa.String(256), unique=True, nullable=False, index=True),
        sa.Column('scopes', sa.String(256), nullable=True, default='read write push'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table('mastodon_authorization_codes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(128), unique=True, nullable=False, index=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mastodon_apps.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('redirect_uri', sa.Text(), nullable=True, default=''),
        sa.Column('scopes', sa.String(256), nullable=True, default='read write push'),
        sa.Column('used', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Composite indexes
    op.create_index('ix_posts_author_created', 'posts', ['author_id', 'created_at'])
    op.create_index('ix_posts_author_deleted_created', 'posts', ['author_id', 'is_deleted', 'created_at'])
    op.create_index('ix_follow_activity_id', 'follows', ['activity_id'])
    op.create_index('ix_notif_user_created', 'notifications', ['user_id', 'created_at'])
    op.create_index('ix_notif_user_type', 'notifications', ['user_id', 'notification_type'])
    op.create_index('ix_notif_user_read', 'notifications', ['user_id', 'is_read'])
    op.create_index('ix_follows_follower_following', 'follows', ['follower_id', 'following_id'])
    op.create_index('ix_follows_follower_accepted', 'follows', ['follower_id', 'following_id', 'accepted'])
    op.create_index('ix_users_is_remote', 'users', ['is_remote'])
    op.create_index('ix_posts_visibility_deleted', 'posts', ['visibility', 'is_deleted'])
    op.create_index('ix_posts_in_reply_to_deleted', 'posts', ['in_reply_to_id', 'is_deleted'])
    op.create_index('ix_likes_user_post', 'likes', ['user_id', 'post_id'])
    op.create_index('ix_boosts_user_post', 'boosts', ['user_id', 'post_id'])
    op.create_index('ix_bookmarks_user_post', 'bookmarks', ['user_id', 'post_id'])
    op.create_index('ix_votes_user_post', 'votes', ['user_id', 'post_id'])


def downgrade() -> None:
    op.drop_table('mastodon_authorization_codes')
    op.drop_table('mastodon_access_tokens')
    op.drop_table('mastodon_apps')
    op.drop_table('pending_deliveries')
    op.drop_table('remote_media')
    op.drop_table('processed_activities')
    op.drop_table('server_settings')
    op.drop_table('episode_views')
    op.drop_table('keyword_mutes')
    op.drop_table('series_mutes')
    op.drop_table('user_blocks')
    op.drop_table('user_mutes')
    op.drop_table('admin_logs')
    op.drop_table('muted_servers')
    op.drop_table('allowed_servers')
    op.drop_table('federation_blocks')
    op.drop_table('blocked_domains')
    op.drop_table('reports')
    op.drop_table('server_rules')
    op.drop_table('profile_notes')
    op.drop_table('series_notices')
    op.drop_table('series_follows')
    op.drop_table('login_sessions')
    op.drop_table('push_subscriptions')
    op.drop_table('notifications')
    op.drop_table('bookmarks')
    op.drop_table('boosts')
    op.drop_table('likes')
    op.drop_table('votes')
    op.drop_table('post_tags')
    op.drop_table('posts')
    op.drop_table('episode_drafts')
    op.drop_table('episodes')
    op.drop_table('novel_tags')
    op.drop_table('novels')
    op.drop_table('custom_emojis')
    op.drop_table('tags')
    op.drop_table('follows')
    op.drop_table('users')
