import re
import datetime

from urllib.parse import urlparse

from sqlalchemy import func

from app.models import Like, Boost, Bookmark, User, Vote, Post, Follow
from app.utils.datetime import _fmt_dt
from app.utils.emoji import _load_emojis


# 좋아요/부스트/답글 카운트와 리액션 집계를 세션(요청) 단위로 배치 조회하는 캐시.
# lazy="selectin" 컬렉션(p.likes/p.boosts/p.replies)을 통째로 로드하지 않고,
# 세션 identity map에 로드된 Post 전체에 대해 한 번에 집계한다.
_COUNTS_CACHE_KEY = "_writ_post_counts_cache"
_REACTIONS_CACHE_KEY = "_writ_post_reactions_cache"
_DEFAULT_REACT = "★"


def _session_post_ids(session):
    try:
        return {p.id for p in session.identity_map.values()
                if isinstance(p, Post) and p.id is not None}
    except Exception:
        return set()


def _load_counts_batch(session, ids):
    counts = {}
    if not ids:
        return counts
    for pid, cnt in session.query(Like.post_id, func.count(Like.id)).filter(
        Like.post_id.in_(ids)
    ).group_by(Like.post_id).all():
        counts.setdefault(pid, {})["likes"] = cnt
    for pid, cnt in session.query(Boost.post_id, func.count(Boost.id)).filter(
        Boost.post_id.in_(ids)
    ).group_by(Boost.post_id).all():
        counts.setdefault(pid, {})["boosts"] = cnt
    # replies_count 프로퍼티와 동일 조건: in_reply_to_id 기준 + 삭제 제외
    for pid, cnt in session.query(Post.in_reply_to_id, func.count(Post.id)).filter(
        Post.in_reply_to_id.in_(ids), Post.is_deleted == False
    ).group_by(Post.in_reply_to_id).all():
        counts.setdefault(pid, {})["replies"] = cnt
    return counts


def _post_counts(session, pid):
    cache = session.info.setdefault(_COUNTS_CACHE_KEY, {})
    if pid in cache:
        return cache[pid]
    missing = _session_post_ids(session) | {pid}
    missing = {i for i in missing if i not in cache}
    if missing:
        cache.update({i: {} for i in missing})
        cache.update(_load_counts_batch(session, missing))
    return cache.get(pid) or {}


def _load_reactions_batch(session, ids):
    reactions = {}
    if not ids:
        return reactions
    for pid, react, cnt in session.query(
        Like.post_id, func.coalesce(Like.reaction, _DEFAULT_REACT), func.count(Like.id)
    ).filter(Like.post_id.in_(ids)).group_by(Like.post_id, Like.reaction).order_by(
        Like.post_id, func.min(Like.id)
    ).all():
        reactions.setdefault(pid, {})[react] = cnt
    return reactions


def _post_reactions(session, pid):
    cache = session.info.setdefault(_REACTIONS_CACHE_KEY, {})
    if pid in cache:
        return cache[pid]
    missing = _session_post_ids(session) | {pid}
    missing = {i for i in missing if i not in cache}
    if missing:
        cache.update({i: {} for i in missing})
        cache.update(_load_reactions_batch(session, missing))
    return cache.get(pid) or {}


def _post_json(p, session, user, tl_type=None,
               _liked_ids=None, _boosted_ids=None, _bookmarked_ids=None,
               _vote_map=None, _my_reaction_map=None, _reactions_map=None,
               _mentioned_users_map=None, _boost_originals=None, _skip_emojis=False,
               _quote_depth=0, _following_ids=None, _counts_map=None):
    if not p:
        return None
    if p.is_deleted:
        return {
            "id": p.id,
            "number": p.number or "",
            "content": "",
            "summary": "",
            "visibility": "public",
            "created_at": _fmt_dt(p.created_at),
            "author": {"id": 0, "username": "deleted", "display_name": "삭제된 사용자", "avatar": "", "header": "", "is_admin": False, "is_remote": False, "summary": "", "is_locked": False, "is_limited": False, "is_frozen": False, "is_deceased": False, "is_deactivated": False, "is_sensitive": False, "role": "user", "show_badge": False, "email_verified": False, "default_visibility": "public", "display_handle": "deleted", "is_bot": False, "pinned_posts": [], "pinned_series": [], "episode_default_visibility": "public", "follow_list_visibility": "public", "custom_fields": [], "profile_hashtags": [], "enable_reactions": True, "aliases": [], "moved_to": ""},
            "likes_count": 0, "boosts_count": 0, "replies_count": 0,
            "liked": False, "boosted": False, "bookmarked": False,
            "is_mine": False, "is_dm": False, "is_sensitive": False,
            "ap_id": p.ap_id or "",
            "url": p.remote_url or p.ap_id or "",
            "reply_context": None, "boosted_by": [],
            "media_attachments": [], "poll_data": None, "my_vote": None,
            "reactions": {}, "my_reaction": None,
            "mentioned_user_ids": [], "mentioned_handles": [],
            "link_preview": None, "is_deleted": True,
            "quote_of_id": None, "quote_of_ap_id": "",
            "boost_of_id": p.boost_of_id,
            "quoted_post": None,
        }

    # If this is a boost pointer post, resolve to the original
    if p.boost_of_id:
        original = (_boost_originals or {}).get(p.boost_of_id) or session.query(Post).filter_by(id=p.boost_of_id).first()
        if original and not original.is_deleted:
            result = _post_json(original, session, user, tl_type,
                                _liked_ids, _boosted_ids, _bookmarked_ids,
                                _vote_map, _my_reaction_map, _reactions_map,
                                _mentioned_users_map, _boost_originals,
                                _skip_emojis=_skip_emojis, _quote_depth=_quote_depth,
                                _following_ids=_following_ids, _counts_map=_counts_map)
            result["id"] = p.id
            existing_boosted_by = result.get("boosted_by") or []
            booster_json = _user_json(p.author)
            if not any(b.get("id") == booster_json["id"] for b in existing_boosted_by if b):
                existing_boosted_by = list(existing_boosted_by) + [booster_json]
            result["boosted_by"] = existing_boosted_by
            result["boost_of_id"] = p.boost_of_id
            if user and _boosted_ids is not None:
                result["i_boosted"] = original.id in _boosted_ids
            if not _skip_emojis:
                result["_emojis"] = _merge_boost_emojis(result.get("_emojis") or [], session, existing_boosted_by)
            return result
        else:
            return {"id": p.id, "is_deleted": True, "boosted_by": [_user_json(p.author)], "boost_of_id": p.boost_of_id}
    if user:
        if _liked_ids is not None:
            liked = p.id in _liked_ids
        else:
            liked = session.query(Like).filter_by(user_id=user.id, post_id=p.id).first() is not None
        if _boosted_ids is not None:
            boosted = p.id in _boosted_ids
        else:
            boosted = session.query(Boost).filter_by(user_id=user.id, post_id=p.id).first() is not None
        if _bookmarked_ids is not None:
            bookmarked = p.id in _bookmarked_ids
        else:
            bookmarked = session.query(Bookmark).filter_by(user_id=user.id, post_id=p.id).first() is not None
    else:
        liked = boosted = bookmarked = False
    my_vote = None
    if user and p.poll_data:
        if _vote_map is not None:
            my_vote = _vote_map.get(p.id)
        else:
            vote = session.query(Vote).filter_by(user_id=user.id, post_id=p.id).first()
            if vote:
                my_vote = vote.option_index
    my_reaction = None
    if user and liked:
        if _my_reaction_map is not None:
            my_reaction = _my_reaction_map.get(p.id)
        else:
            my_reaction = session.query(Like.reaction).filter_by(user_id=user.id, post_id=p.id).scalar()
    if _reactions_map is not None:
        reactions = _reactions_map.get(p.id, {})
    else:
        reactions = _post_reactions(session, p.id)
    if _mentioned_users_map is not None and p.id in _mentioned_users_map:
        mentioned_handles = _mentioned_users_map[p.id]
    elif p.mentioned_user_ids:
        mentioned_handles = []
        for u in session.query(User).filter(User.id.in_(p.mentioned_user_ids or [])).all():
            if u.is_remote and u.remote_url:
                _name = u.username.split("@")[0]
                _domain = urlparse(u.remote_url).hostname or ""
                mentioned_handles.append(f"{_name}@{_domain}")
            else:
                mentioned_handles.append(u.username)
    else:
        # content에서 @handle@domain 패턴 파싱
        mentioned_handles = list(set(
            f"{m.group(1)}@{m.group(2)}" for m in re.finditer(r'@([a-zA-Z0-9_]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', p.content or "")
        ))

    quoted_post = None
    if p.quote_of_id and _quote_depth < 2:
        _qp = session.query(Post).filter_by(id=p.quote_of_id, is_deleted=False).first()
        if _qp:
            from app.core.visibility import _can_view
            if _can_view(_qp, user, session):
                quoted_post = _post_json(
                    _qp, session, user, None,
                    _liked_ids=_liked_ids, _boosted_ids=_boosted_ids,
                    _bookmarked_ids=_bookmarked_ids, _vote_map=_vote_map,
                    _my_reaction_map=_my_reaction_map, _reactions_map=_reactions_map,
                    _mentioned_users_map=_mentioned_users_map,
                    _boost_originals=_boost_originals,
                    _skip_emojis=False,
                    _quote_depth=_quote_depth + 1,
                    _following_ids=_following_ids,
                    _counts_map=_counts_map,
                )

    if _counts_map is not None:
        _c = _counts_map.get(p.id) or {}
        likes_count = _c.get("likes", 0)
        boosts_count = _c.get("boosts", 0)
        replies_count = _c.get("replies", 0)
    else:
        _c = _post_counts(session, p.id)
        likes_count = _c.get("likes", 0)
        boosts_count = _c.get("boosts", 0)
        replies_count = _c.get("replies", 0)

    return {
        "id": p.id,
        "number": p.number or "",
        "content": p.content,
        "summary": p.summary or "",
        "visibility": p.visibility or "public",
        "created_at": _fmt_dt(p.created_at),
        "author": _user_json(p.author),
        "likes_count": likes_count,
        "boosts_count": boosts_count,
        "replies_count": replies_count,
        "liked": liked,
        "boosted": boosted,
        "bookmarked": bookmarked,
        "is_mine": p.author_id == user.id if user else False,
        "is_dm": p.is_dm or False,
        "is_sensitive": getattr(p, 'is_sensitive', False) or False,
        "ap_id": p.ap_id or "",
        "url": p.remote_url or p.ap_id or "",
        "reply_context": _reply_context(p, session, user, tl_type, _following_ids=_following_ids),
        "boosted_by": [],
        "media_attachments": (p.media_attachments or []) if hasattr(p, 'media_attachments') else [],
        "poll_data": p.poll_data,
        "my_vote": my_vote,
        "reactions": reactions,
        "my_reaction": my_reaction,
        "mentioned_user_ids": p.mentioned_user_ids or [],
        "mentioned_handles": mentioned_handles,
        "link_preview": p.link_preview or None,
        "quote_of_id": p.quote_of_id or None,
        "quote_of_ap_id": p.quote_of_ap_id or "",
        "boost_of_id": p.boost_of_id,
        "quoted_post": quoted_post,
        **(({}) if _skip_emojis else {"_emojis": _post_used_emojis(p, session, reactions)}),
    }


def _post_used_emojis(p, session, reactions=None):
    """Post에 실제로 쓰인 커스텀 이모지만 골라서 반환 (전체 카탈로그 전송 방지).

    같은 키워드라도 서버마다 다른 이미지일 수 있으므로, 작성자 도메인과 일치하는
    이모지를 우선 선택한다. 해당 도메인 이모지가 없으면 로컬 정의(domain=""),
    그것도 없으면 첫 번째 후보로 폴백한다.
    """
    all_emojis = _load_emojis(session)
    if not all_emojis:
        return []
    texts = [p.content or "", p.summary or ""]
    if p.author:
        texts.append(p.author.display_name or "")
    if reactions:
        texts.append(" ".join(reactions.keys()))
    parent = getattr(p, "parent", None)
    if parent is not None and not parent.is_deleted:
        texts.append(parent.content or "")
        texts.append(parent.summary or "")
        if parent.author:
            texts.append(parent.author.display_name or "")
    needle = " ".join(texts).lower()
    if not needle:
        return []

    author_domain = ""
    if p.author and p.author.is_remote:
        uname = (p.author.username or "").lower()
        if "@" in uname:
            author_domain = uname.rsplit("@", 1)[-1]

    candidates_by_kw = {}
    for e in all_emojis:
        kw = e["keyword"]
        if f":{kw.lower()}:" in needle:
            candidates_by_kw.setdefault(kw.lower(), []).append(e)

    def _pick(candidates):
        if author_domain:
            chosen = next((e for e in candidates if (e.get("domain") or "").lower() == author_domain), None)
            if chosen:
                return chosen
        chosen = next((e for e in candidates if not e.get("domain")), None)
        return chosen or candidates[0]

    used = []
    for candidates in candidates_by_kw.values():
        chosen = _pick(candidates)
        used.append({"keyword": chosen["keyword"], "file_name": chosen["file_name"], "url": chosen["url"], "aliases": chosen["aliases"]})
    return used


def _merge_boost_emojis(base_emojis, session, boosters):
    """부스트한 사람의 표시 이름에 쓰인 이모지를 추가로 포함시킨다.

    부스트한 사람마다 도메인이 다를 수 있으므로 각자 도메인의 이모지를 우선 선택한다.
    """
    result = list(base_emojis)
    existing = {e["keyword"] for e in result}
    all_emojis = _load_emojis(session)
    by_kw = {}
    for e in all_emojis:
        by_kw.setdefault(e["keyword"], []).append(e)
    for b in (boosters or []):
        bname = (b.get("display_name") or "").lower()
        if not bname:
            continue
        bdomain = ""
        uname = (b.get("username") or "").lower()
        if "@" in uname:
            bdomain = uname.rsplit("@", 1)[-1]
        for kw, candidates in by_kw.items():
            if kw in existing:
                continue
            if f":{kw.lower()}:" not in bname:
                continue
            chosen = next((x for x in candidates if (x.get("domain") or "").lower() == bdomain), None)
            if chosen is None:
                chosen = next((x for x in candidates if not x.get("domain")), None) or candidates[0]
            result.append({"keyword": chosen["keyword"], "file_name": chosen["file_name"], "url": chosen["url"], "aliases": chosen["aliases"]})
            existing.add(kw)
    return result


def _clean_username(username: str) -> str:
    if username.count('@') > 1:
        parts = username.split('@')
        return f"{parts[0]}@{parts[1]}"
    return username


def _user_json(u):
    role = getattr(u, 'role', 'user') or 'user'
    _name = _clean_username(u.username)
    return {
        "id": u.id,
        "username": _name,
        "display_name": u.display_name or _name,
        "avatar": u.profile_image or "",
        "header": u.header_image or "",
        "summary": u.summary or "",
        "is_admin": u.is_admin,
        "is_locked": u.is_locked or False,
        "is_limited": u.is_limited or False,
        "is_frozen": getattr(u, 'is_frozen', False) or False,
        "is_deceased": getattr(u, 'is_deceased', False) or False,
        "is_deactivated": getattr(u, 'is_deactivated', False) or False,
        "is_sensitive": getattr(u, 'is_sensitive', False) or False,
        "is_remote": u.is_remote,
        "role": role,
        "show_badge": getattr(u, 'show_badge', False) or False,
        "email_verified": u.email_verified or False,
        "default_visibility": u.default_visibility or "public",
        "display_handle": getattr(u, 'display_handle', '') or "",
        "is_bot": getattr(u, 'is_bot', False) or False,
        "pinned_posts": (u.pinned_posts or []) if hasattr(u, 'pinned_posts') else [],
        "pinned_series": (u.pinned_series or []) if hasattr(u, 'pinned_series') else [],
        "episode_default_visibility": u.episode_default_visibility or "public",
        "follow_list_visibility": getattr(u, 'follow_list_visibility', 'public') or 'public',
        "custom_fields": [
            {"name": f.get("name") or f.get("label", ""), "label": f.get("name") or f.get("label", ""), "value": f.get("value", "")}
            for f in (u.custom_fields or [])
        ] if hasattr(u, 'custom_fields') else [],
        "profile_hashtags": (u.profile_hashtags or []) if hasattr(u, 'profile_hashtags') else [],
        "enable_reactions": getattr(u, 'enable_reactions', True) is not False,
        "post_lifetime": getattr(u, 'post_lifetime', 0) or 0,
        "post_lifetime_exceptions": getattr(u, 'post_lifetime_exceptions', []) or [],
        "aliases": (u.aliases or []) if hasattr(u, 'aliases') else [],
        "moved_to": getattr(u, 'moved_to', '') or '',
        "remote_followers_count": getattr(u, 'remote_followers_count', 0) or 0,
        "remote_following_count": getattr(u, 'remote_following_count', 0) or 0,
    }

def _reply_context(p, session=None, user=None, tl_type=None, _following_ids=None):
    parent = p.parent if hasattr(p, 'parent') else None
    if not parent and p.in_reply_to_ap_id and session:
        try:
            parent = session.query(Post).filter_by(ap_id=p.in_reply_to_ap_id).first()
        except Exception:
            pass
    if not parent or parent.is_deleted:
        return None
    if tl_type == "home" and user and parent.author_id != user.id:
        if _following_ids is not None:
            if parent.author_id not in _following_ids:
                return None
        else:
            followed = session.query(Follow).filter_by(
                follower_id=user.id, following_id=parent.author_id, accepted=True
            ).first()
            if not followed:
                return None
    if tl_type == "local" and parent.author.is_remote:
        return None
    return {
        "id": parent.id,
        "number": parent.number or "",
        "content": parent.content[:200] if parent.content else "",
        "summary": parent.summary or "",
        "is_sensitive": bool(getattr(parent, 'is_sensitive', False)),
        "author": _user_json(parent.author),
        "visibility": parent.visibility or "public",
    }

