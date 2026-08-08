import datetime
import uuid

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Table, Index
from sqlalchemy.orm import relationship

from app.config.settings import BASE_URL
from app.db.database import Base
from app.utils.datetime import now, get_24hours_later

def generate_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), default="")
    summary = Column(Text, default="")
    email = Column(String(255), unique=True, default="")
    email_verified = Column(Boolean, default=False)
    verification_token = Column(String(128), default="")
    reset_token = Column(String(128), default="")
    reset_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    recent_ips = Column(JSON, default=list)
    is_suspended = Column(Boolean, default=False)
    is_frozen = Column(Boolean, default=False)
    is_deactivated = Column(Boolean, default=False)
    is_sensitive = Column(Boolean, default=False)
    is_limited = Column(Boolean, default=False)
    is_deceased = Column(Boolean, default=False)
    moderation_note = Column(Text, default="")
    password_hash = Column(String(255), nullable=False)

    # ActivityPub
    private_key = Column(Text, nullable=False)
    public_key = Column(Text, nullable=False)
    inbox_url = Column(String(512))
    outbox_url = Column(String(512))
    followers_url = Column(String(512))
    following_url = Column(String(512))
    remote_followers_count = Column(Integer, default=0)
    remote_following_count = Column(Integer, default=0)

    is_remote = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    role = Column(String(16), default="user")
    remote_url = Column(String(512), default="")
    profile_url = Column(String(512), default="")
    shared_inbox_url = Column(String(512), default="")
    profile_image = Column(String(512), default="")
    header_image = Column(String(512), default="")
    default_visibility = Column(String(16), default="public")
    episode_default_visibility = Column(String(16), default="public")
    is_locked = Column(Boolean, default=False)
    show_badge = Column(Boolean, default=False)
    is_bot = Column(Boolean, default=False)
    display_handle = Column(String(64), default="")
    follow_list_visibility = Column(String(16), default="public")
    custom_fields = Column(JSON, default=list)
    profile_hashtags = Column(JSON, default=list)
    enable_reactions = Column(Boolean, default=True)
    post_lifetime = Column(Integer, default=0)
    post_lifetime_exceptions = Column(JSON, default=list)
    pinned_posts = Column(JSON, default=list)
    pinned_series = Column(JSON, default=list)
    aliases = Column(JSON, default=list)
    moved_to = Column(String(512), default="")

    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)
    session_token = Column(String(64), default="")

    posts = relationship("Post", back_populates="author", foreign_keys="Post.author_id",
                         cascade="all, delete-orphan", lazy="noload")
    novels = relationship("Novel", back_populates="author", cascade="all, delete-orphan", lazy="noload")

    def actor_uri(self):
        if self.is_remote and self.remote_url:
            return self.remote_url
        return f"{BASE_URL}/users/{self.username}"

    def followers_uri(self):
        return f"{BASE_URL}/users/{self.username}/followers"

    def following_uri(self):
        return f"{BASE_URL}/users/{self.username}/following"

    def inbox_uri(self):
        return f"{BASE_URL}/users/{self.username}/inbox"

    def outbox_uri(self):
        return f"{BASE_URL}/users/{self.username}/outbox"

    def featured_uri(self):
        return f"{BASE_URL}/users/{self.username}/featured"



class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True)
    follower_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    following_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    accepted = Column(Boolean, default=True)
    activity_id = Column(String(1024), default="")
    notify_on_post = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)

    follower = relationship("User", foreign_keys=[follower_id], lazy="selectin")
    following = relationship("User", foreign_keys=[following_id], lazy="selectin")


class SeriesFollow(Base):
    __tablename__ = "series_follows"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=now)

    user = relationship("User", lazy="selectin")
    novel = relationship("Novel", lazy="selectin")


post_tags = Table(
    "post_tags", Base.metadata,
    Column("post_id", Integer, ForeignKey("posts.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
    number = Column(String(16), default="", nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    summary = Column(String(512), default="")

    # Visibility: public, home, followers, mention
    visibility = Column(String(16), default="public", nullable=False)
    mentioned_user_ids = Column(JSON, default=list)

    # ActivityPub IDs
    ap_id = Column(String(1024), unique=True)
    # Human-facing web URL for remote posts (AP object's "url" field)
    remote_url = Column(String(1024), default="")
    in_reply_to_id = Column(Integer, ForeignKey("posts.id"), index=True)
    in_reply_to_ap_id = Column(String(1024), default="")

    # Boost pointer: if set, this post is a boost of another post
    boost_of_id = Column(Integer, ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True)

    # Quote pointer: if set, this post quotes another post
    quote_of_id = Column(Integer, ForeignKey("posts.id", ondelete="SET NULL"), nullable=True, index=True)
    quote_of_ap_id = Column(String(1024), default="")

    # Novel post (if this post is a novel episode announcement)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="SET NULL"), nullable=True)
    episode_id = Column(Integer, ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True)

    is_deleted = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    is_dm = Column(Boolean, default=False)
    is_sensitive = Column(Boolean, default=False)
    original_visibility = Column(String(16), default="")
    media_attachments = Column(JSON, default=list)
    poll_data = Column(JSON, nullable=True)
    link_preview = Column(JSON, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    tag_list = relationship("Tag", secondary=post_tags, lazy="selectin")
    created_at = Column(DateTime(timezone=True), default=now)

    author = relationship("User", back_populates="posts", foreign_keys=[author_id], lazy="selectin")
    parent = relationship("Post", back_populates="replies", remote_side=[id], foreign_keys=[in_reply_to_id], lazy="selectin")
    replies = relationship("Post", back_populates="parent", foreign_keys=[in_reply_to_id], lazy="selectin")
    boost_of = relationship("Post", foreign_keys=[boost_of_id], remote_side=[id], lazy="noload")
    quote_of = relationship("Post", foreign_keys=[quote_of_id], remote_side=[id], lazy="noload")
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan", lazy="selectin")
    boosts = relationship("Boost", back_populates="post", cascade="all, delete-orphan", lazy="selectin")
    votes = relationship("Vote", back_populates="post", cascade="all, delete-orphan", lazy="noload")
    novel = relationship("Novel", foreign_keys=[novel_id], lazy="selectin")
    episode = relationship("Episode", foreign_keys=[episode_id], lazy="selectin")

    @property
    def likes_count(self):
        try:
            return len(self.likes) if self.likes is not None else 0
        except Exception:
            return 0

    @property
    def boosts_count(self):
        try:
            return len(self.boosts) if self.boosts is not None else 0
        except Exception:
            return 0

    @property
    def replies_count(self):
        try:
            return sum(1 for r in self.replies if not r.is_deleted) if self.replies is not None else 0
        except Exception:
            return 0


class Vote(Base):
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False, index=True)
    option_index = Column(Integer, nullable=False)
    ap_id = Column(String(1024), unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)
    expires_at = Column(DateTime(timezone=True), default=get_24hours_later)

    user = relationship("User", lazy="selectin")
    post = relationship("Post", back_populates="votes", lazy="selectin")


class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False, index=True)
    ap_id = Column(String(1024), unique=True)
    reaction = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)

    user = relationship("User", lazy="selectin")
    post = relationship("Post", back_populates="likes", lazy="selectin")


class Boost(Base):
    __tablename__ = "boosts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False, index=True)
    ap_id = Column(String(1024), unique=True)
    created_at = Column(DateTime(timezone=True), default=now)

    user = relationship("User", lazy="selectin")
    post = relationship("Post", back_populates="boosts", lazy="selectin")


novel_tags = Table(
    "novel_tags", Base.metadata,
    Column("novel_id", Integer, ForeignKey("novels.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)


class CustomEmoji(Base):
    __tablename__ = "custom_emojis"

    id = Column(Integer, primary_key=True)
    keyword = Column(String(128), nullable=False, index=True)
    file_name = Column(String(256), nullable=False)
    category = Column(String(64), default="")
    aliases = Column(JSON, default=list)
    source_url = Column(String(512), default="")
    domain = Column(String(128), default="")
    created_at = Column(DateTime(timezone=True), default=now)


class Novel(Base):
    __tablename__ = "novels"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
    number = Column(String(16), default="", nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, default="")
    cover_image = Column(String(512), default="")
    tags = Column(String(512), default="")
    status = Column(String(16), default="ongoing")
    is_published = Column(Boolean, default=True)
    is_sensitive = Column(Boolean, default=False)
    visibility = Column(String(16), default="public", nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    author = relationship("User", back_populates="novels", lazy="selectin")
    episodes = relationship("Episode", back_populates="novel", cascade="all, delete-orphan",
                            order_by="Episode.episode_number", lazy="selectin")
    tag_list = relationship("Tag", secondary=novel_tags, lazy="selectin")
    notices = relationship("SeriesNotice", back_populates="novel", cascade="all, delete-orphan",
                           order_by="SeriesNotice.is_pinned.desc(), SeriesNotice.created_at.desc()", lazy="selectin")

    @property
    def episode_count(self):
        return len(self.episodes) if self.episodes is not None else 0

    @property
    def total_views(self):
        if self.episodes is not None:
            return sum(e.views for e in self.episodes)
        return 0


class SeriesNotice(Base):
    __tablename__ = "series_notices"
    __table_args__ = (
        Index("ix_series_notices_novel_created", "novel_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    is_pinned = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    novel = relationship("Novel", back_populates="notices", lazy="selectin")


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        Index("ix_episodes_novel_created", "novel_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    episode_number = Column(Integer, nullable=False)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(Text, default="")
    comment = Column(Text, default="")
    audio_url = Column(String(512), default="")
    view_mode = Column(String(16), default="text")
    comic_view_mode = Column(String(16), default="paged")
    image_urls = Column(JSON, default=list)
    reading_direction = Column(String(8), default="ltr")
    views = Column(Integer, default=0)
    is_published = Column(Boolean, default=True)
    page_mode = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    novel = relationship("Novel", back_populates="episodes", lazy="selectin")

    # ActivityPub post ID (when announced)


class EpisodeDraft(Base):
    __tablename__ = "episode_drafts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    episode_id = Column(Integer, nullable=True)
    title = Column(String(256), default="")
    summary = Column(Text, default="")
    content = Column(Text, default="")
    comment = Column(Text, default="")
    is_published = Column(Boolean, default=True)
    announce = Column(Boolean, default=False)
    announce_comment = Column(String(200), default="")
    visibility = Column(String(20), default="public")
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=now)

    user = relationship("User", lazy="selectin")
    post = relationship("Post", lazy="selectin")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notification_type = Column(String(32), nullable=False)  # follow, like, boost, reply, mention, moderation
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="SET NULL"), nullable=True)
    metadata_json = Column(Text, default="")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)

    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    from_user = relationship("User", foreign_keys=[from_user_id], lazy="selectin")
    post = relationship("Post", lazy="selectin")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    endpoint = Column(Text, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    device_name = Column(String(256), default="")
    created_at = Column(DateTime(timezone=True), default=now)


class LoginSession(Base):
    __tablename__ = "login_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_key = Column(String(64), unique=True, nullable=False, index=True)
    ip_address = Column(String(45), default="")
    user_agent = Column(Text, default="")
    last_active = Column(DateTime(timezone=True), default=now)
    created_at = Column(DateTime(timezone=True), default=now)


class ProfileNote(Base):
    __tablename__ = "profile_notes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    target = relationship("User", foreign_keys=[target_user_id], lazy="selectin")


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=True)
    ends_at = Column(DateTime(timezone=True), nullable=True)
    poll_data = Column(JSON, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    created_by = relationship("User", lazy="selectin")


class AnnouncementRead(Base):
    __tablename__ = "announcement_reads"
    __table_args__ = (
        Index("ix_announcement_reads_announcement_user", "announcement_id", "user_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    announcement_id = Column(Integer, ForeignKey("announcements.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    is_read = Column(Boolean, default=False)
    notified_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)


class AnnouncementVote(Base):
    __tablename__ = "announcement_votes"
    __table_args__ = (
        Index("ix_announcement_votes_announcement_user", "announcement_id", "user_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    announcement_id = Column(Integer, ForeignKey("announcements.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    option_index = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)


class ServerRule(Base):
    __tablename__ = "server_rules"

    id = Column(Integer, primary_key=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, default="")
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_type = Column(String(32), nullable=False)  # post, novel, episode
    target_id = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    rule_ids = Column(JSON, default=list)
    status = Column(String(16), default="pending", nullable=False)  # pending, resolved, dismissed
    forward_to_remote = Column(Boolean, default=False)
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    reporter = relationship("User", foreign_keys=[reporter_id], lazy="selectin")
    resolver = relationship("User", foreign_keys=[resolved_by_id], lazy="selectin")


class BlockedDomain(Base):
    __tablename__ = "blocked_domains"

    id = Column(Integer, primary_key=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)

    created_by = relationship("User", lazy="selectin")


class FederationBlock(Base):
    __tablename__ = "federation_blocks"

    id = Column(Integer, primary_key=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    reason = Column(String(512), default="")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)

    created_by = relationship("User", lazy="selectin")


class AllowedServer(Base):
    __tablename__ = "allowed_servers"

    id = Column(Integer, primary_key=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)

    created_by = relationship("User", lazy="selectin")


class MutedServer(Base):
    __tablename__ = "muted_servers"

    id = Column(Integer, primary_key=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    muted = Column(Boolean, default=True)
    media_muted = Column(Boolean, default=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)

    created_by = relationship("User", lazy="selectin")


class AdminLog(Base):
    __tablename__ = "admin_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(255), default="")
    action = Column(String(50), nullable=False, index=True)
    target_type = Column(String(50), nullable=True)
    target_id = Column(Integer, nullable=True)
    target_username = Column(String(255), default="")
    details = Column(Text, default="")
    ip_address = Column(String(45), default="")
    created_at = Column(DateTime(timezone=True), default=now)

    user = relationship("User", foreign_keys=[user_id], lazy="selectin")


class UserMute(Base):
    __tablename__ = "user_mutes"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    duration = Column(Integer, default=0)
    hide_notifications = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)
    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    target_user = relationship("User", foreign_keys=[target_user_id], lazy="selectin")


class UserBlock(Base):
    __tablename__ = "user_blocks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    target_user = relationship("User", foreign_keys=[target_user_id], lazy="selectin")


class SeriesMute(Base):
    __tablename__ = "series_mutes"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)


class KeywordMute(Base):
    __tablename__ = "keyword_mutes"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    keyword = Column(String(512), nullable=False)
    name = Column(String(128), default="")
    mode = Column(String(8), default="or")
    is_regex = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)


class EpisodeView(Base):
    __tablename__ = "episode_views"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    episode_id = Column(Integer, ForeignKey("episodes.id"), nullable=False)
    viewed_at = Column(DateTime(timezone=True), default=now)


class ServerSetting(Base):
    __tablename__ = "server_settings"

    id = Column(Integer, primary_key=True)
    server_name = Column(String(255), default="WRIT")
    server_description = Column(Text, default="")
    logo = Column(String(512), default="")
    favicon = Column(String(512), default="")
    app_icon = Column(String(512), default="")
    admin_ids = Column(String(512), default="")
    admin_email = Column(String(255), default="")
    federation_mode = Column(String(16), default="blacklist")
    enable_reactions = Column(Boolean, default=True)
    vapid_private_key = Column(Text, default="")
    vapid_public_key = Column(Text, default="")

    @classmethod
    def get(cls, session):
        s = session.query(cls).first()
        if not s:
            s = cls(server_name="WRIT")
            session.add(s)
            session.commit()
        return s


class ProcessedActivity(Base):
    __tablename__ = "processed_activities"

    id = Column(String(1024), primary_key=True)
    created_at = Column(DateTime(timezone=True), default=now)


class RemoteMedia(Base):
    __tablename__ = "remote_media"

    id = Column(Integer, primary_key=True)
    remote_url = Column(String(1024), nullable=False, index=True)
    local_url = Column(String(512), nullable=False)
    size = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=now)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class PendingDelivery(Base):
    __tablename__ = "pending_deliveries"

    id = Column(Integer, primary_key=True)
    inbox_url = Column(String(512), nullable=False)
    activity_json = Column(Text, nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(16), default="pending")  # pending, failed
    attempts = Column(Integer, default=0)
    last_error = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)


class MastodonApp(Base):
    __tablename__ = "mastodon_apps"

    id = Column(Integer, primary_key=True)
    client_name = Column(String(256), nullable=False)
    redirect_uris = Column(Text, default="urn:ietf:wg:oauth:2.0:oob")
    scopes = Column(String(256), default="read write push")
    website = Column(String(512), default="")
    client_id = Column(String(128), unique=True, nullable=False, index=True)
    client_secret = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)


class MastodonAccessToken(Base):
    __tablename__ = "mastodon_access_tokens"

    id = Column(Integer, primary_key=True)
    app_id = Column(Integer, ForeignKey("mastodon_apps.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    access_token = Column(String(256), unique=True, nullable=False, index=True)
    scopes = Column(String(256), default="read write push")
    created_at = Column(DateTime(timezone=True), default=now)

    app = relationship("MastodonApp", lazy="selectin")
    user = relationship("User", lazy="selectin")


class MastodonAuthorizationCode(Base):
    __tablename__ = "mastodon_authorization_codes"

    id = Column(Integer, primary_key=True)
    code = Column(String(128), unique=True, nullable=False, index=True)
    app_id = Column(Integer, ForeignKey("mastodon_apps.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    redirect_uri = Column(Text, default="")
    scopes = Column(String(256), default="read write push")
    used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)

