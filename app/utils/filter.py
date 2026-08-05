import json
import re

from sqlalchemy.orm import Session

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
                         following_ids: set | list = [],
                         filter_ctx: dict | None = None) -> bool:
    """Decide whether a single post should be shown to the given user.

    Args:
        post: Post ORM object (boost pointer if boosted)
        session: DB session
        user: The viewer (User ORM object)
        tl_type: "home", "social", "local", or "federated"
        following_ids: Set of user IDs that `user` follows
        filter_ctx: Pre-loaded filter data from _load_user_filters() (optional)

    Returns True if the post should be delivered, False to hide it.
    """
    if not user:
        return True

    following_set = set(following_ids) if following_ids else set()
    is_self = post.author_id == user.id
    is_boosted = bool(post.boost_of_id)

    # --- Boost visibility check (boost pointer가 가리키는 원글이 followers-only면 팔로워만 통과) ---
    if post.boost_of_id and tl_type in ("home", "social"):
        if filter_ctx is not None and "boost_originals" in filter_ctx:
            _orig = filter_ctx["boost_originals"].get(post.boost_of_id)
        else:
            _orig = session.query(Post).filter_by(id=post.boost_of_id).first()
        if _orig and _orig.visibility == "followers" and _orig.author_id not in following_set:
            return False

    # --- 1. 블록/뮤트/키워드 (최우선 — 멘션보다 우선) ---
    if filter_ctx:
        if post.author_id in filter_ctx["hidden_ids"]:
            return False
        if post.novel_id and post.novel_id in filter_ctx["muted_series_ids"]:
            return False
        if filter_ctx["parsed_kw"]:
            content_lower = (post.content or "").lower()
            if _match_keyword_mute(content_lower, filter_ctx["parsed_kw"]):
                return False

    # --- 2. 멘션 체크 (대원칙 1: 나한테 온 멘션은 무조건 통과) ---
    # mentioned_user_ids만 사용 (content 정규식은 텍스트 참조까지 잡아서 너무 넓음)
    is_mentioned_to_me = bool(post.mentioned_user_ids and user.id in post.mentioned_user_ids)
    if is_mentioned_to_me:
        return True

    # --- 2.5. 멘션 공개 글: 본인 글 또는 나에게 온 멘션이 아니면 드롭 ---
    if post.visibility == "mention" and not is_self and not is_mentioned_to_me:
        return False

    # --- 3. home/social 전용 필터 ---
    if tl_type == "home":
        allowed_authors = following_set | {user.id}

        # 작성자가 팔로우 대상이 아니면 드롭
        # (부스트된 글은 예외 — 단, 팔로워 공개 글은 부스트여도 원작자 팔로우 필수)
        if post.author_id not in allowed_authors:
            if not is_boosted:
                return False
            if post.visibility == "followers":
                return False

    elif tl_type == "social":
        allowed_authors = following_set | {user.id}
        if post.author_id not in allowed_authors and post.visibility != "public":
            return False

    # --- 3. 답글 필터: home/social 공통, 캐시 데이터 기반으로 N+1 없이 검사 ---
    if tl_type in ("home", "social") and not is_boosted and (post.in_reply_to_id or post.in_reply_to_ap_id):
        # 대원칙 A: DB에 연동된 로컬/원격 부모 ID가 아예 없는 '쌩 원격 답글'은 즉시 드롭
        if not post.in_reply_to_id:
            return False

        # 콘텍스트에서 캐시된 부모 작성자 ID 매핑 가져오기
        cached_parents = filter_ctx.get("parent_authors", {}) if filter_ctx else {}
        if post.in_reply_to_id in cached_parents:
            parent_author_id = cached_parents[post.in_reply_to_id]
        else:
            parent = session.query(Post).filter_by(id=post.in_reply_to_id).first()
            parent_author_id = parent.author_id if parent else None

        # 대원칙 B: 부모 글 작성자를 모르거나, (내가 팔로우하지도 않고 + 나도 아니라면) 드롭
        if parent_author_id is None:
            return False
        if post.author_id != user.id and parent_author_id not in following_set and parent_author_id != user.id:
            return False
    return True


def _timeline_filter(posts, session: Session, user, tl_type, following_ids, filter_ctx: dict | None = None):
    """Filter a batch of posts for timeline display."""
    if not user:
        return posts

    if filter_ctx is None:
        filter_ctx = _load_user_filters(session, user)

    # Pre-load parent authors for reply filtering (batch optimization)
    filter_ctx["parent_authors"] = {}
    if tl_type in ("home", "social"):
        parent_ids = {p.in_reply_to_id for p in posts if p.author_id != user.id and p.in_reply_to_id}
        if parent_ids:
            for pp in session.query(Post).filter(Post.id.in_(parent_ids)).all():
                filter_ctx["parent_authors"][pp.id] = pp.author_id

    # Pre-load boost originals for boost visibility filtering (batch optimization)
    filter_ctx["boost_originals"] = {}
    if tl_type in ("home", "social"):
        boost_ids = {p.boost_of_id for p in posts if p.boost_of_id}
        if boost_ids:
            for _bo in session.query(Post).filter(Post.id.in_(boost_ids)).all():
                filter_ctx["boost_originals"][_bo.id] = _bo

    filtered = []
    for p in posts:
        if should_deliver_post(p, session, user, tl_type, following_ids, filter_ctx):
            filtered.append(p)

    return filtered
