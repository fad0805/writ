import datetime
import re
import uuid
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, JSON, text, Table
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session

from app.config import DATABASE_URL, BASE_URL

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_use_lifo=True,
        pool_recycle=300,
        pool_timeout=15,
        pool_pre_ping=False,
    )


class Base(DeclarativeBase):
    pass


def generate_uuid():
    return str(uuid.uuid4())


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def _ap_datetime(dt):
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
            "featured": self.featured_uri(),
            "followers": self.followers_uri(),
            "following": self.following_uri(),
            "publicKey": {
                "id": f"{self.actor_uri()}#main-key",
                "owner": self.actor_uri(),
                "publicKeyPem": self.public_key,
            },
            "published": _ap_datetime(self.created_at),
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
    tag_list = relationship("Tag", secondary=post_tags, lazy="selectin")
    created_at = Column(DateTime(timezone=True), default=now)
    bumped_at = Column(DateTime(timezone=True), nullable=True)

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

    def to_ap_note(self, plain_content = ''):
        from urllib.parse import urlparse
        content = self.content
        if plain_content:
            content = plain_content

        # extract code blocks with placeholders to protect from later transformations
        code_blocks = []
        def _save_code_block(m):
            code_blocks.append(f'<pre><code>{m.group(2).rstrip()}</code></pre>')
            return f'\x00codeblock_{len(code_blocks) - 1}\x00'
        content = re.sub(r'```(\w*)\r?\n([\s\s]*?)```', _save_code_block, content)
        content = re.sub(r'```([^`\n]+?)```', lambda m: f'<pre><code>{m.group(1)}</code></pre>', content)

        # \s\s -> \s\S 로 수정 (줄바꿈 포함 모든 문자 매칭)
        content = re.sub(r'```(\w*)\r?\n([\s\S]*?)```', _save_code_block, content)
        content = re.sub(r'```([^`\n]+?)```', lambda m: f'<pre><code>{m.group(1)}</code></pre>', content)

        # inline code
        content = re.sub(r'`([^`\n]+?)`', r'<code>\1</code>', content)
        content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
        content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
        content = content.replace('\n', '<br>')

        # restore code blocks
        for i, block in enumerate(code_blocks):
            content = content.replace(f'\x00codeblock_{i}\x00', block)

        # collect :emoji: shortcodes for tag array (content stays as :shortcode:)
        _emoji_pattern = re.compile(r':([a-z0-9_]{2,}):')
        _emoji_keywords = set(_emoji_pattern.findall(content))
        _emoji_map = {}
        if _emoji_keywords:
            def _get_emoji_url(file_name: str, domain: str = "", category: str = "") -> str:
                sub = "remote" if domain or category == "remote" else "local"
                from app.config import s3_enabled
                if s3_enabled:
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
                    "type": "emoji",
                    "id": f"{BASE_URL}/emojis/{keyword}",
                    "name": f":{keyword}:",
                    "icon": {
                        "type": "image",
                        "mediatype": "image/webp",
                        "url": url,
                    },
                })
        # Strip existing mention <a> tags to plain text so the regex below can
        # re-match and rewrite them with correct actor_href + <span class="h-card">
        content = re.sub(
            r'<a\s[^>]*class="[^"]*mention[^"]*"[^>]*>(.*?)</a>',
            r'\1',
            content,
            flags=re.I,
        )
        # Also strip any leftover <span class="h-card"> wrappers from stored content
        content = re.sub(r'<span\s+class="h-card"[^>]*>\s*', '', content, flags=re.I)
        content = re.sub(r'\s*</span>\s*(?=<)', '', content)

        if self.mentioned_user_ids:
            with get_session() as s:
                users = s.query(User).filter(User.id.in_(self.mentioned_user_ids)).all()
                for u in users:
                    web_href = getattr(u, 'profile_url', '') or f"{BASE_URL}/@{u.username}"
                    # actor uri (for mention tag)
                    actor_href = u.actor_uri()
                    # display name: just username (mastodon expects @<span>username</span>)
                    short_username = u.username.split("@")[0] if u.is_remote else u.username
                    # tag name must be @user@domain for remote, @user for local
                    if u.is_remote:
                        tag_name = f"@{u.username}"  # username already has @domain
                        domain_part = u.username.split("@")[1] if "@" in u.username else ""
                    else:
                        domain_part = urlparse(BASE_URL).hostname or ""
                        tag_name = f"@{u.username}@{domain_part}"
                    mention_html = (
                        f'<span class="h-card" translate="no">'
                        f'<a href="{web_href}" class="u-url mention" rel="mention">'
                        f'@<span>{short_username}</span>'
                        + (f'@<span>{domain_part}</span>' if domain_part else '')
                        + f'</a></span>'
                    )
                    short_name = f"@{u.username}"
                    content = re.sub(
                        r'(?<!/)' + re.escape(short_name) + r'(?:@[a-za-z0-9.-]+)?(?![^\s<]*(?:</a>|">))',
                        mention_html,
                        content,
                    )
                    tags.append({"type": "Mention", "href": actor_href, "name": tag_name})

        # wrap remaining @user@domain patterns as mentions + tag array entries
        def _actor_uri_for_handle(handle: str) -> str:
            if "@" in handle:
                name, domain = handle.split("@", 1)
                domain_uri = f"https://{domain}" if domain != urlparse(BASE_URL).hostname else BASE_URL
                return f"{domain_uri}/users/{name}"
            return f"{BASE_URL}/users/{handle}"
        def _web_profile_for_handle(handle: str) -> str:
            if "@" in handle:
                name, domain = handle.split("@", 1)
                domain_url = f"https://{domain}" if domain != urlparse(BASE_URL).hostname else BASE_URL
                return f"{domain_url}/@{name}"
            return f"{BASE_URL}/@{handle}"
        def _wrap_unknown_mention(m):
            handle = m.group(1)
            actor_uri = _actor_uri_for_handle(handle)
            web_url = _web_profile_for_handle(handle)
            _parts = handle.split("@", 1)
            _handle_name = _parts[0]
            _handle_domain = _parts[1] if len(_parts) > 1 else ""
            tags.append({"type": "Mention", "href": actor_uri, "name": f"@{handle}"})
            return (
                f'<span class="h-card" translate="no">'
                f'<a href="{web_url}" class="u-url mention" rel="mention">'
                f'@<span>{_handle_name}</span>'
                + (f'@<span>{_handle_domain}</span>' if _handle_domain else '')
                + f'</a></span>'
            )
        content = re.sub(
            r'(?<!/)(?:^|(?<=\s))@([a-za-z0-9_]+(?:@[a-za-z0-9-]+(?:\.[a-za-z0-9-]+)*)?)(?=\s|$|<|\.|[,:;!?)\'"])',
            _wrap_unknown_mention,
            content,
        )

        content = re.sub(
            r'(^|>|　|\s)(https?://[^\s<>"\')\]]+)(?![^<]*</a>)',
            lambda m: f'{m.group(1)}<a href="{m.group(2)}">{m.group(2)}</a>',
            content,
        )

        from urllib.parse import quote as _urlencode
        content = re.sub(
            r'(^|(?<=\s)|(?<=>))#([^\s<]+)',
            lambda m: f'{m.group(1)}<a href="{BASE_URL}/explore?tag={_urlencode(m.group(2))}" class="mention hashtag" rel="tag">#{m.group(2)}</a>',
            content,
        )

        if self.tag_list:
            for t in self.tag_list:
                tags.append({"type": "Hashtag", "href": f"{BASE_URL}/explore?tag={_urlencode(t.name)}", "name": f"#{t.name}"})

        content = re.sub(r'href="/', f'href="{BASE_URL}/', content)

        _ap_context = [
            "https://www.w3.org/ns/activitystreams",
            "https://w3id.org/security/v1",
            {
                "manuallyapprovesfollowers": "as:manuallyapprovesfollowers",
                "toot": "http://joinmastodon.org/ns#",
                "misskey": "https://misskey-hub.net/ns#",
                "hashtag": "as:hashtag",
                "mention": "as:mention",
                "sensitive": "as:sensitive",
                "emoji": "toot:emoji",
                "quoteurl": "as:quoteurl",
                "quote": {"@id": "https://w3id.org/fep/044f#quote", "@type": "@id"},
                "quoteuri": "http://fedibird.com/ns#quoteuri",
            },
        ]
        obj = {
            "@context": _ap_context,
            "id": f"{BASE_URL}/posts/{self.id}",
            "url": f"{BASE_URL}/posts/{self.id}",
            "type": "Note",
            "published": _ap_datetime(self.created_at),
            "attributedTo": self.author.actor_uri().strip(),
            "content": f"<p>{content}</p>" if not content.strip().startswith("<p>") else content,
            "mediaType": "text/html",
            "to": [],
            "cc": [],
            "tag": tags,
        }
        public_uri = "https://www.w3.org/ns/activitystreams#Public"
        followers_uri = self.author.followers_uri()

        # 멘션 대상자들 URI 미리 구하기
        mentioned_uris = []
        if self.mentioned_user_ids:
            with get_session() as s:
                users = s.query(User).filter(User.id.in_(self.mentioned_user_ids)).all()
                mentioned_uris = [u.actor_uri() for u in users]

        obj['to'] = mentioned_uris

        # 2. 공개 글 권한 강제 보정 (가장 중요)
        if self.visibility == "public":
            # 마스토돈이 가장 좋아하는 조합
            obj["to"].append(public_uri)
            obj["cc"] = [followers_uri]
        elif self.visibility == "home":
            # unlisted: public을 cc에만 넣어야 Mastodon이 " bąd만 공개"로 처리
            # to에 public이 있으면 Mastodon이 "공개"로 해석함
            # But mentioned users must still be in 'to' for Mastodon mention rendering
            obj["to"] = list(mentioned_uris) if mentioned_uris else []
            obj["cc"] = [public_uri, followers_uri]
        elif self.visibility == "followers":
            obj["to"].append(followers_uri)
            obj["cc"] = []
        elif self.visibility == "mention":
            obj["to"] = mentioned_uris if mentioned_uris else [followers_uri]
            obj["cc"] = []
        # 추가로 본인도 to나 cc에 있어야 마스토돈이 잘 처리함 (선택사항)
        if self.author.actor_uri() not in obj["to"]:
            obj["cc"].append(self.author.actor_uri())
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
            if self.in_reply_to_id:
                obj["inReplyTo"] = f"{BASE_URL}/posts/{self.in_reply_to_id}"
            else:
                obj["inReplyTo"] = self.in_reply_to_ap_id
        if self.quote_of_ap_id:
            obj["quoteUrl"] = self.quote_of_ap_id
            obj["quote"] = self.quote_of_ap_id
            obj["quoteUri"] = self.quote_of_ap_id
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
        # 안전장치: to/cc가 비어있으면 안 됨
        to = note.get("to", [])
        cc = note.get("cc", [])
        # 만약 아무것도 없다면(테스트시) 강제로 public 추가
        if not to and not cc:
            public_uri = "https://www.w3.org/ns/activitystreams#Public"
            to = [public_uri]
        return {
            "@context": note.get("@context", "https://www.w3.org/ns/activitystreams"),
            "id": f"{BASE_URL}/activities/create/{self.id}",
            "type": "Create",
            "actor": self.author.actor_uri(),
            "published": _ap_datetime(self.created_at),
            "to": to,
            "cc": cc,
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


def init_db():
    Base.metadata.create_all(engine)
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
        ("remote_followers_count", "INTEGER DEFAULT 0"),
        ("remote_following_count", "INTEGER DEFAULT 0"),
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


_SAFE_TABLE_NAMES = {"users", "posts", "novels", "episodes", "follows", "likes", "boosts",
                      "bookmarks", "notifications", "server_settings", "processed_activities",
                      "custom_emojis", "votes", "reactions", "user_blocks", "user_mutes",
                      "keyword_mutes", "series_mutes", "reports", "report_rules",
                      "federation_blocks", "federation_modes", "allowed_servers", "custom_fields",
                      "episode_comments", "series_notices", "remote_followers"}


def _add_cols(table: str, inspector, cols: list[tuple[str, str]]):
    if table not in _SAFE_TABLE_NAMES:
        raise ValueError(f"Invalid table name: {table}")
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


import contextvars as _cv
_request_session: _cv.ContextVar = _cv.ContextVar("request_session", default=None)


def get_session():
    sess = _request_session.get()
    if sess is not None:
        return sess
    return Session(engine, expire_on_commit=False)
