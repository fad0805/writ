import json
import re

from sqlalchemy.orm import selectinload, Session

from app.models import Post, UserMute, UserBlock, SeriesMute, KeywordMute


def _load_user_filters(session: Session, user):
    """Load and cache all user-level filter data (mutes, blocks, keywords).
    Returns a dict that can be reused across multiple should_deliver_post() calls."""
    if not user:
        return None
    muted_user_ids = {row[0] for row in session.query(UserMute.target_user_id).filter_by(user_id=user.id).all()}
    blocked_ids = {row[0] for row in session.query(UserBlock.target_user_id).filter_by(user_id=user.id).all()}
    blocked_by_ids = {row[0] for row in session.query(UserBlock.user_id).filter_by(target_user_id=user.id).all()}
    muted_series_ids = {row[0] for row in session.query(SeriesMute.novel_id).filter_by(user_id=user.id).all()}
    hidden_ids = muted_user_ids | blocked_ids | blocked_by_ids
    kw_mutes = session.query(KeywordMute).filter_by(user_id=user.id).all()
    parsed_kw = []
    for kw in kw_mutes:
        if kw.is_regex:
            parsed_kw.append(("regex", kw.keyword, kw.mode, None))
        else:
            try:
                keywords = json.loads(kw.keyword)
                if isinstance(keywords, str):
                    keywords = [keywords]
            except (json.JSONDecodeError, TypeError):
                keywords = [kw.keyword]
            keywords = [k.strip().lower() for k in keywords if k.strip()]
            parsed_kw.append(("text", None, kw.mode, keywords))
    return {
        "hidden_ids": hidden_ids,
        "muted_series_ids": muted_series_ids,
        "parsed_kw": parsed_kw,
    }


def _match_keyword_mute(content_lower: str, parsed_kw: list) -> bool:
    """Check if content matches any keyword mute rule."""
    for kw_type, pattern, mode, keywords in parsed_kw:
        if kw_type == "regex":
            try:
                if re.search(pattern, content_lower):
                    return True
            except re.error:
                pass
        else:
            if mode == "and":
                if all(k in content_lower for k in keywords):
                    return True
            else:
                if any(k in content_lower for k in keywords):
                    return True
    return False


def should_deliver_post(post, session: Session, user, tl_type: str,
                         following_ids: set | list | None,
                         filter_ctx: dict | None = None,
                         is_boosted: bool = False) -> bool:
    """Decide whether a single post should be shown to the given user.

    Args:
        post: Post ORM object (must have .author_id, .in_reply_to_id,
              .in_reply_to_ap_id, .content, .mentioned_user_ids, .novel_id,
              .author relationship with .is_remote)
        session: DB session
        user: The viewer (User ORM object)
        tl_type: "home", "social", "local", or "federated"
        following_ids: Set of user IDs that `user` follows
        filter_ctx: Pre-loaded filter data from _load_user_filters() (optional)
        is_boosted: If True, skip reply filtering (boosted posts bypass reply rules)

    Returns True if the post should be delivered, False to hide it.
    """
    if not user:
        return True

    following_set = set(following_ids) if following_ids else set()
    is_self = post.author_id == user.id

    # --- 1. Mention check (대원칙 1: 나한테 온 멘션은 무조건 통과) ---
    is_mentioned_to_me = False
    if post.mentioned_user_ids and user.id in post.mentioned_user_ids:
        is_mentioned_to_me = True
    if not is_mentioned_to_me and post.content and getattr(post, 'author', None) and post.author.is_remote:
        my_username_lower = user.username.split('@')[0].lower()
        if re.search(rf'@{my_username_lower}(?:@[\w.-]+)?\b', post.content.lower()):
            is_mentioned_to_me = True

    if is_mentioned_to_me:
        return True

    # --- 2. Mute/block/keyword filter ---
    if filter_ctx:
        if post.author_id in filter_ctx["hidden_ids"]:
            return False
        if post.novel_id and post.novel_id in filter_ctx["muted_series_ids"]:
            return False
        if filter_ctx["parsed_kw"]:
            content_lower = (post.content or "").lower()
            if _match_keyword_mute(content_lower, filter_ctx["parsed_kw"]):
                return False

    # --- 3. Reply filter (home/social only) ---
    if tl_type in ("home", "social"):
        if not is_boosted and (post.in_reply_to_id or post.in_reply_to_ap_id):
            if post.in_reply_to_id:
                parent = session.query(Post).filter_by(id=post.in_reply_to_id).first()
                parent_author_id = parent.author_id if parent else None
                if parent_author_id is None or (parent_author_id not in following_set and parent_author_id != user.id):
                    return False
            else:
                # remote parent not in DB → hide
                return False

        # 원격 답글 방어: 부모가 DB에 없는 원격 글
        if post.in_reply_to_ap_id and not post.in_reply_to_id:
            return False

        # --- 4. Author must be followed (대원칙 2) ---
        allowed_authors = following_set | {user.id}
        if post.author_id not in allowed_authors:
            return False

    return True


def _timeline_filter(posts, session: Session, user, tl_type, following_ids):
    """Filter a batch of posts for timeline display."""
    if not user:
        return posts

    following_set = set(following_ids) if following_ids else set()
    filter_ctx = _load_user_filters(session, user)

    # Pre-load parent authors for reply filtering (batch optimization)
    parent_authors = {}
    if tl_type in ("home", "social"):
        parent_ids = {p.in_reply_to_id for p in posts if p.author_id != user.id and p.in_reply_to_id}
        if parent_ids:
            for pp in session.query(Post).filter(Post.id.in_(parent_ids)).all():
                parent_authors[pp.id] = pp.author_id

    filtered = []
    for p in posts:
        # Inline parent author lookup for reply filter (avoid N+1 in should_deliver_post)
        if tl_type in ("home", "social") and p.in_reply_to_id and p.in_reply_to_id in parent_authors:
            # Temporarily set a flag so should_deliver_post can use cached data
            pass  # should_deliver_post does its own lookup; batch optimization is minimal here

        if should_deliver_post(p, session, user, tl_type, following_set, filter_ctx):
            filtered.append(p)

    print(f"[feed] after _timeline_filter: {len(filtered)}/{len(posts)} posts", flush=True)
    return filtered
