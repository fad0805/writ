import re
import datetime

from sqlalchemy import desc

from app.models import Like, Boost, Bookmark, User, Vote, Post, Follow
from app.utils.datetime import _fmt_dt
from app.utils.emoji import _load_emojis

def _post_json(p, session, user, tl_type=None,
               _liked_ids=None, _boosted_ids=None, _bookmarked_ids=None,
               _vote_map=None, _my_reaction_map=None, _reactions_map=None,
               _booster_map=None, _mentioned_users_map=None, _boost_originals=None, _skip_emojis=False):
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
            "reply_context": None, "boosted_by": None,
            "media_attachments": [], "poll_data": None, "my_vote": None,
            "reactions": {}, "my_reaction": None,
            "mentioned_user_ids": [], "mentioned_handles": [],
            "link_preview": None, "is_deleted": True,
            "quote_of_id": None, "quote_of_ap_id": "",
        }

    # If this is a boost pointer post, resolve to the original
    if p.boost_of_id:
        original = (_boost_originals or {}).get(p.boost_of_id) or session.query(Post).filter_by(id=p.boost_of_id).first()
        if original and not original.is_deleted:
            result = _post_json(original, session, user, tl_type,
                                _liked_ids, _boosted_ids, _bookmarked_ids,
                                _vote_map, _my_reaction_map, _reactions_map,
                                _booster_map, _mentioned_users_map, _boost_originals)
            result["boosted_by"] = _user_json(p.author)
            return result
        else:
            return {"id": p.id, "is_deleted": True, "boosted_by": _user_json(p.author)}
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
    booster = None
    if user and p.author_id != user.id:
        if _booster_map is not None:
            b = _booster_map.get(p.id)
        else:
            latest_boost = session.query(Boost).filter_by(post_id=p.id).order_by(desc(Boost.created_at)).first()
            b = None
            if latest_boost:
                if (datetime.datetime.now(datetime.timezone.utc) - latest_boost.created_at).total_seconds() > 10800:
                    b = session.query(User).get(latest_boost.user_id)
        if b and b.id != p.author_id:
            booster = b
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
    if _mentioned_users_map is not None and p.id in _mentioned_users_map:
        mentioned_handles = _mentioned_users_map[p.id]
    elif p.mentioned_user_ids:
        from urllib.parse import urlparse as _urlparse2
        mentioned_handles = []
        for u in session.query(User).filter(User.id.in_(p.mentioned_user_ids or [])).all():
            if u.is_remote and u.remote_url:
                _name = u.username.split("@")[0]
                _domain = _urlparse2(u.remote_url).hostname or ""
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
        "reply_context": _reply_context(p, session, user, tl_type),
        "boosted_by": _user_json(booster) if booster else None,
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
        **(({}) if _skip_emojis else {"_emojis": [{"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]} for e in _load_emojis(session)]}),
    }


def _user_json(u):
    role = getattr(u, 'role', 'user') or 'user'
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
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
        "enable_reactions": getattr(u, 'enable_reactions', True),
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

