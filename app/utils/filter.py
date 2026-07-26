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
                         filter_ctx: dict | None = None,
                         is_boosted: bool = False) -> bool:
    """Decide whether a single post should be shown to the given user.

    Args:
        post: Post ORM object
        session: DB session
        user: The viewer (User ORM object)
        tl_type: "home", "social", "local", or "federated"
        following_ids: Set of user IDs that `user` follows
        filter_ctx: Pre-loaded filter data from _load_user_filters() (optional)
        is_boosted: If True, skip reply filtering

    Returns True if the post should be delivered, False to hide it.
    """
    if not user:
        return True

    following_set = set(following_ids) if following_ids else set()
    is_self = post.author_id == user.id

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

    # --- 3. home/social 전용 필터 ---
    if tl_type in ("home", "social"):
        allowed_authors = following_set | {user.id}

        # 작성자가 팔로우 대상이 아니면 드롭
        # (부스트된 글은 예외 — 단, 팔로워 공개 글은 부스트여도 원작자 팔로우 필수)
        if post.author_id not in allowed_authors:
            if not is_boosted:
                return False
            if post.visibility == "followers":
                return False

        # --- 3. 답글 필터: 캐시 데이터 기반으로 N+1 없이 칼같이 검사 ---
        if not is_boosted and (post.in_reply_to_id or post.in_reply_to_ap_id):
            # 대원칙 A: DB에 연동된 로컬/원격 부모 ID가 아예 없는 '쌩 원격 답글'은 즉시 드롭
            if not post.in_reply_to_id:
                return False

            # 대원션을 위해 콘텍스트에서 캐시된 부모 작성자 ID 매핑 가져오기
            cached_parents = filter_ctx.get("parent_authors", {}) if filter_ctx else {}
            # 캐시에 존재하면 가져오고, 배치 캐시가 누락된 단일 호출 환경이라면 폴백(Fallback)으로 DB 조회
            if post.in_reply_to_id in cached_parents:
                parent_author_id = cached_parents[post.in_reply_to_id]
            else:
                parent = session.query(Post).filter_by(id=post.in_reply_to_id).first()
                parent_author_id = parent.author_id if parent else None

            # 대원칙 B: 부모 글의 작성자를 알 수 없거나, (내가 팔로우하는 사람도 아니고 + 나 자신도 아니라면) 드롭
            # 단, 내 글이면 어떤 부모에게든 보임
            if parent_author_id is None:
                return False
            if post.author_id != user.id and parent_author_id not in following_set and parent_author_id != user.id:
                return False
    return True


def _timeline_filter(posts, session: Session, user, tl_type, following_ids, boosted_ids: set | None = None, boost_originals: dict | None = None):
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
        # 부스트 포인터이고 원본이 팔로워 공개면 원작자 팔로우 여부 확인
        if p.boost_of_id and tl_type in ("home", "social"):
            _orig = (boost_originals or {}).get(p.boost_of_id) or session.query(Post).filter_by(id=p.boost_of_id).first()
            if _orig and _orig.visibility == "followers" and _orig.author_id not in following_set:
                continue
        is_boosted = bool(boosted_ids and p.id in boosted_ids)
        if should_deliver_post(p, session, user, tl_type, following_set, filter_ctx, is_boosted=is_boosted):
            filtered.append(p)

    print(f"[feed] after _timeline_filter: {len(filtered)}/{len(posts)} posts", flush=True)
    return filtered
