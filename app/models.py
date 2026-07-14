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
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=20,
        max_overflow=20,
        pool_pre_ping=False,
        pool_use_lifo=True,
        pool_recycle=3600,
    )


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
    email = Column(String(255), unique=True, default="")
    email_verified = Column(Boolean, default=False)
    verification_token = Column(String(128), default="")
    reset_token = Column(String(128), default="")
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

    def to_ap_actor(self):
        tags = []
        for ht in (getattr(self, 'profile_hashtags', None) or []):
            tags.append({"type": "Hashtag", "href": f"{BASE_URL}/explore?tag={ht}", "name": f"#{ht}"})
        result = {
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/security/v1",
                {"PropertyValue": "https://schema.org/PropertyValue", "value": "https://schema.org/value"},
            ],
            "id": self.actor_uri(),
            "type": "Person",
            "preferredUsername": self.username,
            "name": self.display_name or self.username,
            "summary": self.summary or "",
            "url": f"{BASE_URL}/@{self.username}",
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
        elif not self.is_remote:
            result["endpoints"] = {"sharedInbox": f"{BASE_URL}/inbox"}
        if self.updated_at:
            result["updated"] = self.updated_at.isoformat()
        custom_fields = getattr(self, 'custom_fields', None) or []
        if custom_fields:
            result["attachment"] = [
                {"type": "PropertyValue", "name": cf.get("name") or cf.get("label", ""), "value": cf.get("value", "")}
                for cf in custom_fields if (cf.get("name") or cf.get("label")) and cf.get("value")
            ]
        return result


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
    in_reply_to_id = Column(Integer, ForeignKey("posts.id"), index=True)
    in_reply_to_ap_id = Column(String(1024), default="")

    # Boost pointer: if set, this post is a boost of another post
    boost_of_id = Column(Integer, ForeignKey("posts.id"), nullable=True, index=True)

    # Novel post (if this post is a novel episode announcement)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=True)
    episode_id = Column(Integer, ForeignKey("episodes.id"), nullable=True)

    is_deleted = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    is_dm = Column(Boolean, default=False)
    is_sensitive = Column(Boolean, default=False)
    original_visibility = Column(String(16), default="")
    media_attachments = Column(JSON, default=list)
    poll_data = Column(JSON, nullable=True)
    link_preview = Column(JSON, nullable=True)
    tag_list = relationship("Tag", secondary=post_tags, lazy="selectin")
    created_at = Column(DateTime(timezone=True), default=now)
    bumped_at = Column(DateTime(timezone=True), nullable=True)

    author = relationship("User", back_populates="posts", foreign_keys=[author_id], lazy="selectin")
    parent = relationship("Post", back_populates="replies", remote_side=[id], foreign_keys=[in_reply_to_id], lazy="selectin")
    replies = relationship("Post", back_populates="parent", foreign_keys=[in_reply_to_id], lazy="selectin")
    boost_of = relationship("Post", foreign_keys=[boost_of_id], remote_side=[id], lazy="selectin")
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan", lazy="selectin")
    boosts = relationship("Boost", back_populates="post", cascade="all, delete-orphan", lazy="selectin")
    votes = relationship("Vote", back_populates="post", cascade="all, delete-orphan", lazy="selectin")
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

    def to_ap_note(self):
        from urllib.parse import urlparse
        content = self.content

        content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
        content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
        content = content.replace('\n', '<br>')

        # Collect :emoji: shortcodes for tag array (content stays as :shortcode:)
        _emoji_pattern = re.compile(r':([a-z0-9_]{2,}):')
        _emoji_keywords = set(_emoji_pattern.findall(content))
        _emoji_map = {}
        if _emoji_keywords:
            def _get_emoji_url(file_name: str, domain: str = "", category: str = "") -> str:
                sub = "remote" if domain or category == "remote" else "local"
                from app.config import S3_ENABLED
                if S3_ENABLED:
                    from app.utils.storage import get_storage
                    try:
                        storage = get_storage()
                        return storage.url(f"emojis/{sub}/{file_name}")
                    except Exception:
                        pass
                return f"{BASE_URL}/emojis/{sub}/{file_name}"

            with get_session() as _es:
                for kw in _emoji_keywords:
                    emoji = _es.query(CustomEmoji).filter_by(keyword=kw).first()
                    if emoji:
                        _emoji_map[kw] = (_get_emoji_url(emoji.file_name, emoji.domain or "", emoji.category or ""), emoji.keyword)

        tags = []
        if _emoji_map:
            for keyword, (url, _) in _emoji_map.items():
                tags.append({
                    "type": "Emoji",
                    "id": f"{BASE_URL}/emojis/{keyword}",
                    "name": f":{keyword}:",
                    "icon": {
                        "type": "Image",
                        "mediaType": "image/webp",
                        "url": url,
                    },
                })
        if self.mentioned_user_ids:
            from app.config import DOMAIN
            from urllib.parse import urlparse as _urlparse
            with get_session() as s:
                users = s.query(User).filter(User.id.in_(self.mentioned_user_ids)).all()
                for u in users:
                    web_href = getattr(u, 'profile_url', '') or f"{BASE_URL}/@{u.username}"
                    # Actor URI (for Mention tag)
                    actor_href = u.actor_uri()
                    # Display name: just username (Mastodon expects @<span>username</span>)
                    short_username = u.username.split("@")[0] if u.is_remote else u.username
                    # tag name must be @user@domain for remote, @user for local
                    if u.is_remote:
                        tag_name = f"@{u.username}"  # username already has @domain
                    else:
                        tag_name = f"@{u.username}@{DOMAIN}"
                    mention_html = (
                        f'<span class="h-card" translate="no">'
                        f'<a href="{web_href}" class="u-url mention" rel="mention">'
                        f'@<span>{short_username}</span>'
                        f'</a></span>'
                    )
                    short_name = f"@{u.username}"
                    content = re.sub(
                        r'(?<!/)' + re.escape(short_name) + r'(?:@[a-zA-Z0-9.-]+)?(?![^\s<]*(?:</a>|">))',
                        mention_html,
                        content,
                    )
                    tags.append({"type": "Mention", "href": actor_href, "name": tag_name})

        # Wrap remaining @user@domain patterns as mentions + tag array entries
        def _actor_uri_for_handle(handle: str) -> str:
            if "@" in handle:
                name, domain = handle.split("@", 1)
                domain_uri = f"https://{domain}" if domain != urlparse(BASE_URL).hostname else BASE_URL
                return f"{domain_uri}/users/{name}"
            return f"{BASE_URL}/users/{handle}"
        def _wrap_unknown_mention(m):
            handle = m.group(1)
            actor_uri = _actor_uri_for_handle(handle)
            web_uri = f"{BASE_URL}/@{handle}"
            tags.append({"type": "Mention", "href": actor_uri, "name": f"@{handle}"})
            return (
                f'<span class="h-card" translate="no">'
                f'<a href="{web_uri}" class="u-url mention" rel="mention">'
                f'@<span>{handle.split("@")[0]}</span>'
                f'</a></span>'
            )
        content = re.sub(
            r'(?<!/)(?:^|(?<=\s))@([a-zA-Z0-9_]+(?:@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*)?)(?=\s|$|<|\.|[,:;!?)\'"])',
            _wrap_unknown_mention,
            content,
        )

        content = re.sub(
            r'(^|>|　|\s)(https?://[^\s<>"\')\]]+)(?![^<]*</a>)',
            lambda m: f'{m.group(1)}<a href="{m.group(2)}">{m.group(2)}</a>',
            content,
        )


        if self.tag_list:
            for t in self.tag_list:
                tags.append({"type": "Hashtag", "href": f"{BASE_URL}/explore?tag={t.name}", "name": f"#{t.name}"})

        content = re.sub(r'href="/', f'href="{BASE_URL}/', content)

        _ap_context = [
            "https://www.w3.org/ns/activitystreams",
            "https://w3id.org/security/v1",
            {
                "manuallyApprovesFollowers": "as:manuallyApprovesFollowers",
                "toot": "http://joinmastodon.org/ns#",
                "misskey": "https://misskey-hub.net/ns#",
                "Hashtag": "as:Hashtag",
                "sensitive": "as:sensitive",
                "Emoji": "toot:Emoji",
                "emoji": "toot:emoji",
                "quoteUrl": "as:quoteUrl",
            },
        ]
        obj_id = f"{BASE_URL}/@{self.author.username}/{self.number}" if self.number else self.ap_id
        obj = {
            "@context": _ap_context,
            "id": obj_id,
            "url": obj_id,
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
        if self.mentioned_user_ids:
            with get_session() as _ms:
                _musers = _ms.query(User).filter(User.id.in_(self.mentioned_user_ids)).all()
                for _mu in _musers:
                    _mu_uri = _mu.actor_uri()
                    if _mu_uri not in obj["to"] and _mu_uri not in obj["cc"]:
                        if self.is_dm:
                            obj["to"].append(_mu_uri)
                        else:
                            obj["cc"].append(_mu_uri)
        is_sensitive = self.is_sensitive or getattr(self.author, 'is_sensitive', False) or False
        if self.summary:
            obj["summary"] = self.summary
            obj["sensitive"] = True
        elif is_sensitive:
            obj["sensitive"] = True
        if self.media_attachments:
            from urllib.parse import urlparse
            attachments = []
            for m in (self.media_attachments or [])[:4]:
                if isinstance(m, dict):
                    url = m.get("url", "")
                    mtype = m.get("type", "image")
                    if url:
                        ext = url.rsplit(".", 1)[-1].lower() if "." in url else "png"
                        if mtype == "video" or ext in ("mp4", "webm", "mov"):
                            ap_type = "Video"
                            ct = "video/webm"
                        else:
                            ap_type = "Image"
                            ct = f"image/{ext}"
                        attachments.append({
                            "type": ap_type,
                            "mediaType": ct,
                            "url": url,
                            "name": "",
                        })
            if attachments:
                obj["attachment"] = attachments
        if self.in_reply_to_ap_id:
            obj["inReplyTo"] = self.in_reply_to_ap_id
        if self.poll_data:
            obj["type"] = "Question"
            poll_id = self.ap_id or f"{BASE_URL}/@{self.author.username}/{self.number}"
            obj["oneOf"] = [
                {
                    "type": "Note",
                    "id": f"{poll_id}/options/{i}",
                    "name": o["text"],
                    "replies": {"type": "Collection", "totalItems": o.get("votes_count", 0)},
                }
                for i, o in enumerate(self.poll_data.get("options", []))
            ]
            voters = sum(o.get("votes_count", 0) for o in self.poll_data.get("options", []))
            obj["votersCount"] = voters
            expires_at = self.poll_data.get("expires_at")
            if expires_at:
                obj["endTime"] = expires_at
                try:
                    from datetime import datetime
                    if datetime.fromisoformat(expires_at) < datetime.now(datetime.timezone.utc):
                        obj["closed"] = expires_at
                except Exception:
                    pass
        return obj

    def to_ap_create(self):
        note = self.to_ap_note()
        return {
            "@context": note.get("@context", "https://www.w3.org/ns/activitystreams"),
            "id": f"{BASE_URL}/activities/create/{self.id}",
            "type": "Create",
            "actor": self.author.actor_uri(),
            "published": self.created_at.isoformat() if self.created_at else "",
            "to": note.get("to", []),
            "cc": note.get("cc", []),
            "object": note,
        }


class Vote(Base):
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False, index=True)
    option_index = Column(Integer, nullable=False)
    ap_id = Column(String(1024), unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)

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
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)
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


def init_db():
    Base.metadata.create_all(engine)
    # Alembic migration (logs if fails, non-fatal)
    try:
        from alembic.config import Config
        from alembic import command
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", str(engine.url))
        command.upgrade(cfg, "head")
    except Exception as exc:
        import logging
        logging.getLogger("writ.init").warning("Alembic migration skipped: %s", exc)
    # Direct SQL fallback — add missing columns that Alembic may have skipped
    _add_missing_columns()
    # Create additional composite indexes for performance
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_author_created ON posts(author_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_author_deleted_created ON posts(author_id, is_deleted, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_follow_activity_id ON follows(activity_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notif_user_created ON notifications(user_id, created_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notif_user_type ON notifications(user_id, notification_type)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_notif_user_read ON notifications(user_id, is_read)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_follows_follower_following ON follows(follower_id, following_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_follows_follower_accepted ON follows(follower_id, following_id, accepted)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_is_remote ON users(is_remote)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_bumped ON posts(bumped_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_visibility_deleted ON posts(visibility, is_deleted)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_in_reply_to_deleted ON posts(in_reply_to_id, is_deleted)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_likes_user_post ON likes(user_id, post_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_boosts_user_post ON boosts(user_id, post_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bookmarks_user_post ON bookmarks(user_id, post_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_votes_user_post ON votes(user_id, post_id)"))
            conn.commit()
    except Exception:
        pass


def _add_missing_columns():
    """Add columns that exist in SQLAlchemy models but are missing from DB tables."""
    from sqlalchemy import inspect as sa_inspect
    try:
        inspector = sa_inspect(engine)
    except Exception:
        return
    _add_cols("users", inspector, [
        ("enable_reactions", "BOOLEAN DEFAULT TRUE"),
        ("is_deactivated", "BOOLEAN DEFAULT FALSE"),
        ("is_deceased", "BOOLEAN DEFAULT FALSE"),
        ("is_sensitive", "BOOLEAN DEFAULT FALSE"),
        ("show_badge", "BOOLEAN DEFAULT FALSE"),
        ("is_bot", "BOOLEAN DEFAULT FALSE"),
        ("is_limited", "BOOLEAN DEFAULT FALSE"),
        ("is_locked", "BOOLEAN DEFAULT FALSE"),
        ("display_handle", "VARCHAR(256) DEFAULT ''"),
        ("follow_list_visibility", "VARCHAR(16) DEFAULT 'public'"),
        ("episode_default_visibility", "VARCHAR(16) DEFAULT 'public'"),
        ("session_token", "VARCHAR(256) DEFAULT ''"),
        ("moderation_note", "TEXT DEFAULT ''"),
        ("moved_to", "VARCHAR(512) DEFAULT ''"),
        ("custom_fields", "JSON DEFAULT '[]'"),
        ("profile_hashtags", "JSON DEFAULT '[]'"),
        ("pinned_posts", "JSON DEFAULT '[]'"),
        ("pinned_series", "JSON DEFAULT '[]'"),
        ("aliases", "JSON DEFAULT '[]'"),
    ])
    _add_cols("posts", inspector, [
        ("is_sensitive", "BOOLEAN DEFAULT FALSE"),
        ("original_visibility", "VARCHAR(16) DEFAULT ''"),
        ("media_attachments", "JSON DEFAULT '[]'"),
        ("poll_data", "JSON"),
        ("is_dm", "BOOLEAN DEFAULT FALSE"),
        ("novel_id", "INTEGER"),
        ("episode_id", "INTEGER"),
        ("mentioned_user_ids", "JSON DEFAULT '[]'"),
        ("in_reply_to_ap_id", "VARCHAR(1024) DEFAULT ''"),
        ("bumped_at", "TIMESTAMP"),
    ])
    _add_cols("novels", inspector, [
        ("is_sensitive", "BOOLEAN DEFAULT FALSE"),
    ])
    _add_cols("episodes", inspector, [
        ("summary", "TEXT DEFAULT ''"),
        ("comment", "TEXT DEFAULT ''"),
    ])


def _add_cols(table: str, inspector, cols: list[tuple[str, str]]):
    try:
        existing = {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return
    col_defs = [f"ADD COLUMN {col_name} {col_def}" for col_name, col_def in cols if col_name not in existing]
    if not col_defs:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} {', '.join(col_defs)}"))
            conn.commit()
    except Exception:
        pass


def get_session():
    return Session(engine)
