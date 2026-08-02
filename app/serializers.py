import re
import datetime

from urllib.parse import urlparse

from app.models import Like, Boost, Bookmark, User, Vote, Post, Follow
from app.utils.datetime import _fmt_dt
from app.utils.emoji import _load_emojis


def _author_reactions_off(author) -> bool:
    """True only when the author explicitly disabled reactions (NULL means enabled)."""
    return getattr(author, 'enable_reactions', True) is False


def _reactions_for_display(reactions, author) -> dict:
    """Merge a post's reaction counts into a single ★ when its author disabled reactions (display only)."""
    if reactions and _author_reactions_off(author):
        return {"★": sum(reactions.values())}
    return reactions


def _post_json(p, session, user, tl_type=None,
               _liked_ids=None, _boosted_ids=None, _bookmarked_ids=None,
               _vote_map=None, _my_reaction_map=None, _reactions_map=None,
               _mentioned_users_map=None, _boost_originals=None, _skip_emojis=False):
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
        }

    # If this is a boost pointer post, resolve to the original
    if p.boost_of_id:
        original = (_boost_originals or {}).get(p.boost_of_id) or session.query(Post).filter_by(id=p.boost_of_id).first()
        if original and not original.is_deleted:
            result = _post_json(original, session, user, tl_type,
                                _liked_ids, _boosted_ids, _bookmarked_ids,
                                _vote_map, _my_reaction_map, _reactions_map,
                                _mentioned_users_map, _boost_originals,
                                _skip_emojis=_skip_emojis)
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
        reactions = {}
        _default_react = "★"
        if p.likes:
            for like in p.likes:
                if like.reaction:
                    reactions[like.reaction] = reactions.get(like.reaction, 0) + 1
                else:
                    reactions[_default_react] = reactions.get(_default_react, 0) + 1
    if _author_reactions_off(p.author):
        if reactions:
            reactions = {"★": sum(reactions.values())}
        if my_reaction:
            my_reaction = "★"
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
    return {
        "id": p.id,
        "number": p.number or "",
        "content": p.content,
        "summary": p.summary or "",
        "visibility": p.visibility or "public",
        "created_at": _fmt_dt(p.created_at),
        "author": _user_json(p.author),
        "likes_count": p.likes_count,
        "boosts_count": p.boosts_count,
        "replies_count": p.replies_count,
        "liked": liked,
        "boosted": boosted,
        "bookmarked": bookmarked,
        "is_mine": p.author_id == user.id if user else False,
        "is_dm": p.is_dm or False,
        "is_sensitive": getattr(p, 'is_sensitive', False) or False,
        "ap_id": p.ap_id or "",
        "url": p.remote_url or p.ap_id or "",
        "reply_context": _reply_context(p, session, user, tl_type),
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
        **(({}) if _skip_emojis else {"_emojis": _post_used_emojis(p, session, reactions)}),
    }


def _post_used_emojis(p, session, reactions=None):
    """Post에 실제로 쓰인 커스텀 이모지만 골라서 반환 (전체 카탈로그 전송 방지)."""
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
    used = []
    seen = set()
    for e in all_emojis:
        kw = e["keyword"]
        if kw in seen:
            continue
        seen.add(kw)
        if f":{kw.lower()}:" in needle:
            used.append({"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]})
    return used


def _merge_boost_emojis(base_emojis, session, boosters):
    """부스트한 사람의 표시 이름에 쓰인 이모지를 추가로 포함시킨다."""
    booster_names = " ".join(
        b.get("display_name") or "" for b in (boosters or []) if b
    ).lower()
    if not booster_names:
        return base_emojis
    result = list(base_emojis)
    existing = {e["keyword"] for e in result}
    for e in _load_emojis(session):
        kw = e["keyword"]
        if kw in existing:
            continue
        if f":{kw.lower()}:" in booster_names:
            result.append({"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]})
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

def _reply_context(p, session=None, user=None, tl_type=None):
    parent = p.parent if hasattr(p, 'parent') else None
    if not parent and p.in_reply_to_ap_id and session:
        try:
            parent = session.query(Post).filter_by(ap_id=p.in_reply_to_ap_id).first()
        except Exception:
            pass
    if not parent or parent.is_deleted:
        return None
    if tl_type == "home" and user and parent.author_id != user.id:
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

