import datetime
import re
import uuid
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, JSON, Index, event, text, Table
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session

from app.config import DATABASE_URL, BASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)


class Base(DeclarativeBase):
    pass


def generate_uuid():
    return str(uuid.uuid4())


def now():
    return datetime.datetime.now(datetime.timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), default="")
    summary = Column(Text, default="")
    email = Column(String(255), default="")
    email_verified = Column(Boolean, default=False)
    verification_token = Column(String(128), default="")
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

    is_remote = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    role = Column(String(16), default="user")
    remote_url = Column(String(512), default="")
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
    pinned_posts = Column(JSON, default=list)
    pinned_series = Column(JSON, default=list)
    aliases = Column(JSON, default=list)
    moved_to = Column(String(512), default="")

    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)
    session_token = Column(String(64), default="")

    posts = relationship("Post", back_populates="author", foreign_keys="Post.author_id",
                         cascade="all, delete-orphan", lazy="selectin")
    novels = relationship("Novel", back_populates="author", cascade="all, delete-orphan", lazy="selectin")

    def actor_uri(self):
        return f"{BASE_URL}/users/{self.username}"

    def followers_uri(self):
        return f"{BASE_URL}/users/{self.username}/followers"

    def following_uri(self):
        return f"{BASE_URL}/users/{self.username}/following"

    def inbox_uri(self):
        return f"{BASE_URL}/users/{self.username}/inbox"

    def outbox_uri(self):
        return f"{BASE_URL}/users/{self.username}/outbox"

    def to_ap_actor(self):
        tags = []
        for ht in (getattr(self, 'profile_hashtags', None) or []):
            tags.append({"type": "Hashtag", "href": f"{BASE_URL}/explore?tag={ht}", "name": f"#{ht}"})
        result = {
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/security/v1",
            ],
            "id": self.actor_uri(),
            "type": "Person",
            "preferredUsername": self.username,
            "name": self.display_name or self.username,
            "summary": self.summary or "",
            "url": self.actor_uri(),
            "inbox": self.inbox_uri(),
            "outbox": self.outbox_uri(),
            "followers": self.followers_uri(),
            "following": self.following_uri(),
            "publicKey": {
                "id": f"{self.actor_uri()}#main-key",
                "owner": self.actor_uri(),
                "publicKeyPem": self.public_key,
            },
            "published": (self.created_at.isoformat() if self.created_at else ""),
            "discoverable": True,
            "manuallyApprovesFollowers": bool(self.is_locked),
        }
        if tags:
            result["tag"] = tags
        if self.profile_image:
            result["icon"] = {"type": "Image", "url": self.profile_image}
        if self.header_image:
            result["image"] = {"type": "Image", "url": self.header_image}
        if self.shared_inbox_url:
            result["endpoints"] = {"sharedInbox": self.shared_inbox_url}
        custom_fields = getattr(self, 'custom_fields', None) or []
        if custom_fields:
            result["attachment"] = [
                {"type": "PropertyValue", "name": cf.get("name", ""), "value": cf.get("value", "")}
                for cf in custom_fields if cf.get("name") and cf.get("value")
            ]
        return result


class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True)
    follower_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    following_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    accepted = Column(Boolean, default=True)
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
    ap_id = Column(String(512), unique=True)
    in_reply_to_id = Column(Integer, ForeignKey("posts.id"), index=True)
    in_reply_to_ap_id = Column(String(512), default="")

    # Novel post (if this post is a novel episode announcement)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=True)
    episode_id = Column(Integer, ForeignKey("episodes.id"), nullable=True)

    is_deleted = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    is_dm = Column(Boolean, default=False)
    original_visibility = Column(String(16), default="")
    media_attachments = Column(JSON, default=list)
    tag_list = relationship("Tag", secondary=post_tags, lazy="selectin")
    created_at = Column(DateTime(timezone=True), default=now)
    bumped_at = Column(DateTime(timezone=True), nullable=True)

    author = relationship("User", back_populates="posts", foreign_keys=[author_id], lazy="selectin")
    parent = relationship("Post", back_populates="replies", remote_side=[id], lazy="selectin")
    replies = relationship("Post", back_populates="parent", lazy="selectin")
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan", lazy="selectin")
    boosts = relationship("Boost", back_populates="post", cascade="all, delete-orphan", lazy="selectin")
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
            return len(self.replies) if self.replies is not None else 0
        except Exception:
            return 0

    def to_ap_note(self):
        content = self.content

        content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
        content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
        content = content.replace('\n', '<br>')

        tags = []
        if self.mentioned_user_ids:
            with get_session() as s:
                users = s.query(User).filter(User.id.in_(self.mentioned_user_ids)).all()
                for u in users:
                    name = f"@{u.username}"
                    href = u.actor_uri()
                    content = re.sub(
                        re.escape(name) + r'(?![^\s<]*(?:</a>|">))',
                        f'<a href="{href}" class="mention">{name}</a>',
                        content,
                    )
                    tags.append({"type": "Mention", "href": href, "name": name})

        content = re.sub(r'href="/', f'href="{BASE_URL}/', content)

        html_url = f"{BASE_URL}/@{self.author.username}/{self.number}" if self.number else self.ap_id
        obj = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": self.ap_id,
            "url": html_url,
            "type": "Note",
            "published": self.created_at.isoformat() if self.created_at else "",
            "attributedTo": self.author.actor_uri(),
            "content": content,
            "to": [],
            "cc": [],
            "tag": tags,
        }
        followers_uri = self.author.followers_uri()
        public_uri = "https://www.w3.org/ns/activitystreams#Public"
        if self.visibility == "public":
            obj["to"] = [followers_uri, public_uri]
        elif self.visibility == "home":
            obj["to"] = [followers_uri]
            obj["cc"] = [public_uri]
        elif self.visibility == "followers":
            obj["to"] = [followers_uri]
        elif self.visibility == "mention":
            obj["to"] = []
        if self.summary:
            obj["summary"] = self.summary
        if self.in_reply_to_ap_id:
            obj["inReplyTo"] = self.in_reply_to_ap_id
        return obj

    def to_ap_create(self):
        note = self.to_ap_note()
        return {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": self.ap_id + "/activity",
            "type": "Create",
            "actor": self.author.actor_uri(),
            "published": self.created_at.isoformat() if self.created_at else "",
            "to": note.get("to", []),
            "cc": note.get("cc", []),
            "object": note,
        }


class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False, index=True)
    ap_id = Column(String(512), unique=True)
    created_at = Column(DateTime(timezone=True), default=now)

    user = relationship("User", lazy="selectin")
    post = relationship("Post", back_populates="likes", lazy="selectin")


class Boost(Base):
    __tablename__ = "boosts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False, index=True)
    ap_id = Column(String(512), unique=True)
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

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    episode_number = Column(Integer, nullable=False)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(Text, default="")
    comment = Column(Text, default="")
    views = Column(Integer, default=0)
    is_published = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    novel = relationship("Novel", back_populates="episodes", lazy="selectin")

    # ActivityPub post ID (when announced)


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
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)
    metadata_json = Column(Text, default="")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)

    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    from_user = relationship("User", foreign_keys=[from_user_id], lazy="selectin")
    post = relationship("Post", lazy="selectin")


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
    federation_mode = Column(String(16), default="blacklist")  # whitelist or blacklist

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

    id = Column(String(512), primary_key=True)
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


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    return Session(engine)
