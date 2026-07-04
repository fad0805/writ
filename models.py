import datetime
import uuid
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, JSON, Index, event, text
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session

from config import DATABASE_URL, BASE_URL

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
    remote_url = Column(String(512), default="")
    shared_inbox_url = Column(String(512), default="")
    profile_image = Column(String(512), default="")

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
        return {
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
        }


class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True)
    follower_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    following_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    accepted = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=now)

    follower = relationship("User", foreign_keys=[follower_id], lazy="selectin")
    following = relationship("User", foreign_keys=[following_id], lazy="selectin")


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
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
    created_at = Column(DateTime(timezone=True), default=now)

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
        obj = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": self.ap_id,
            "type": "Note",
            "published": self.created_at.isoformat(),
            "attributedTo": self.author.actor_uri(),
            "content": self.content,
            "to": [],
            "cc": [],
            "tag": [],
        }
        if self.visibility == "public":
            obj["to"] = [f"{self.author.followers_uri()}", "https://www.w3.org/ns/activitystreams#Public"]
        elif self.visibility in ("home", "followers"):
            obj["to"] = [f"{self.author.followers_uri()}"]
        elif self.visibility == "mention":
            obj["to"] = [f"{self.author.followers_uri()}"]
        if self.summary:
            obj["summary"] = self.summary
        if self.in_reply_to_ap_id:
            obj["inReplyTo"] = self.in_reply_to_ap_id
        return obj


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


class Novel(Base):
    __tablename__ = "novels"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, default="")
    cover_image = Column(String(512), default="")
    tags = Column(String(512), default="")
    is_completed = Column(Boolean, default=False)
    is_published = Column(Boolean, default=True)
    # Visibility: public(listed), unlisted(profile/url), private(author only)
    visibility = Column(String(16), default="public", nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    author = relationship("User", back_populates="novels", lazy="selectin")
    episodes = relationship("Episode", back_populates="novel", cascade="all, delete-orphan",
                            order_by="Episode.episode_number", lazy="selectin")

    @property
    def episode_count(self):
        return len(self.episodes) if self.episodes is not None else 0

    @property
    def total_views(self):
        if self.episodes is not None:
            return sum(e.views for e in self.episodes)
        return 0


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), default=generate_uuid, unique=True, nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    episode_number = Column(Integer, nullable=False)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(Text, default="")
    views = Column(Integer, default=0)
    is_published = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

    novel = relationship("Novel", back_populates="episodes", lazy="selectin")

    # ActivityPub post ID (when announced)
    announcement_post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    notification_type = Column(String(32), nullable=False)  # follow, like, boost, reply, mention
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)

    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    from_user = relationship("User", foreign_keys=[from_user_id], lazy="selectin")
    post = relationship("Post", lazy="selectin")


def init_db():
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.execute(text("ALTER TABLE users ADD COLUMN profile_image VARCHAR(512) DEFAULT ''"))
            session.commit()
    except Exception:
        pass
    try:
        with Session(engine) as session:
            session.execute(text("ALTER TABLE posts ADD COLUMN is_pinned BOOLEAN DEFAULT 0"))
            session.commit()
    except Exception:
        pass
    try:
        with Session(engine) as session:
            session.execute(text("ALTER TABLE novels ADD COLUMN visibility VARCHAR(16) DEFAULT 'public' NOT NULL"))
            session.commit()
    except Exception:
        pass
    try:
        with Session(engine) as session:
            session.execute(text("UPDATE novels SET visibility = 'private' WHERE is_published = 0"))
            session.commit()
    except Exception:
        pass


def get_session():
    return Session(engine)
