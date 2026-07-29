"""User profile, search, and media endpoints extracted from _core.py."""
import os
import json
import io
import re
import threading
import logging
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from PIL import Image, ImageOps
from sqlalchemy import desc, or_, and_, func, select, text
from sqlalchemy.orm import selectinload

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, Tag, CustomEmoji, Report, ServerRule, ServerSetting, UserMute, UserBlock
from app.serializers import _user_json
from app.config.settings import BASE_URL
from app.core.activitypub import _resolve_actor
from app.db.database import get_session
from app.routes.auth import require_auth, require_active_auth, get_current_user
from app.utils.datetime import _fmt_dt
from app.utils.storage import get_storage

from app.routes.api._core import _validate_upload, _can_view, _post_json, _cleanup_avatars, _broadcast_update_actor, MAX_AVATAR_SIZE
from app.routes.api._series import _novel_json, _apply_latest_activity_order

logger = logging.getLogger("writ.api.users")

users_router = APIRouter()


@users_router.get("/search/users")
def api_users_autocomplete(request: Request, q: str = Query("")):
    user = get_current_user(request)
    query = q.strip().lstrip("@")
    if not query:
        return {"users": []}
    with get_session() as s:
        pattern = f"{query}%"
        matches = s.query(User).filter(
            User.username.ilike(pattern),
        ).limit(5).all()
        if not matches:
            return {"users": []}
        following_ids = {f.following_id for f in s.query(Follow).filter_by(
            follower_id=user.id, accepted=True
        ).all()} if user else set()
        mentioned_ids = set()
        if user:
            recent_posts = s.query(Post.mentioned_user_ids).filter(
                Post.author_id == user.id,
                Post.mentioned_user_ids != None,
            ).order_by(desc(Post.created_at)).limit(50).all()
            for row in recent_posts:
                mids = row[0]
                if isinstance(mids, list):
                    for mid in mids:
                        if isinstance(mid, int):
                            mentioned_ids.add(mid)
        match_ids = {m.id for m in matches}
        follows_mentioned = sorted(
            [m for m in matches if m.id in following_ids and m.id in mentioned_ids],
            key=lambda m: (m.display_name or m.username).lower()
        )
        follows_only = sorted(
            [m for m in matches if m.id in following_ids and m.id not in mentioned_ids],
            key=lambda m: (m.display_name or m.username).lower()
        )
        mentioned_only = sorted(
            [m for m in matches if m.id not in following_ids and m.id in mentioned_ids],
            key=lambda m: (m.display_name or m.username).lower()
        )
        others = sorted(
            [m for m in matches if m.id not in following_ids and m.id not in mentioned_ids],
            key=lambda m: (m.display_name or m.username).lower()
        )
        ordered = follows_mentioned + follows_only + mentioned_only + others
        return {"users": [_user_json(u) for u in ordered]}


@users_router.get("/users/{username}")
def api_get_profile(request: Request, username: str, offset: int = 0, limit: int = 10):
    user = get_current_user(request)
    if "@" in username:
        parts = username.split("@")
        if len(parts) == 2:
            remote_user, remote_domain = parts
            actor_url = f"https://{remote_domain}/@{remote_user}"
            try:
                threading.Thread(target=_resolve_actor, args=(actor_url,), daemon=True).start()
            except Exception:
                pass
    with get_session() as s:
        profile = s.query(User).filter_by(username=username).first()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        is_deactivated = getattr(profile, 'is_deactivated', False) or False
        is_viewer_owner = user and profile.id == user.id
        if is_deactivated and not is_viewer_owner:
            return {
                "profile": _user_json(profile),
                "posts": [],
                "novels": [],
                "followers": [],
                "following": [],
                "total_posts": 0,
                "followers_count": 0,
                "following_count": 0,
                "is_following": False,
                "is_follow_pending": False,
                "has_pending_follower": False,
                "is_follower": False,
                "is_mine": False,
                "is_muted": False,
                "is_blocked": False,
                "am_i_blocked": False,
                "has_more": False,
                "offset": offset,
                "pinned_posts_data": [],
                "pinned_series_data": [],
            }
        boosted_ids = [b.post_id for b in s.query(Boost).filter_by(user_id=profile.id).all()]
        boost_subq = select(Boost.created_at).where(
            Boost.user_id == profile.id, Boost.post_id == Post.id
        ).correlate(Post).scalar_subquery()
        posts = s.query(Post).options(
            selectinload(Post.author)
        ).filter(
            or_(
                Post.author_id == profile.id,
                Post.id.in_(boosted_ids),
            ),
            Post.is_deleted == False,
        ).order_by(
            desc(func.coalesce(boost_subq, Post.created_at))
        ).offset(offset).limit(limit + 1).all()
        has_more = len(posts) > limit
        posts = [p for p in posts[:limit] if _can_view(p, user, s)]
        seen_ids = set()
        deduped = []
        pending_boosts = {}
        for p in posts:
            if p.boost_of_id:
                pending_boosts[p.boost_of_id] = p
            elif p.id in seen_ids:
                continue
            else:
                seen_ids.add(p.id)
                deduped.append(p)
        for boost_of_id, bp in pending_boosts.items():
            if bp.author_id == profile.id:
                continue
            inserted = False
            for i, d in enumerate(deduped):
                if d.id == boost_of_id:
                    deduped.insert(i + 1, bp)
                    inserted = True
                    break
            if not inserted:
                deduped.append(bp)
        posts = deduped
        total_posts = s.query(Post).filter(
            or_(
                Post.author_id == profile.id,
                Post.id.in_(boosted_ids),
            ),
            Post.is_deleted == False,
        ).count()
        followers_count = s.query(Follow).filter_by(following_id=profile.id, accepted=True).count()
        following_count = s.query(Follow).filter_by(follower_id=profile.id, accepted=True).count()
        is_muted = s.query(UserMute).filter_by(user_id=user.id, target_user_id=profile.id).first() is not None if user else False
        is_blocked = s.query(UserBlock).filter_by(user_id=user.id, target_user_id=profile.id).first() is not None if user else False
        am_i_blocked = s.query(UserBlock).filter_by(user_id=profile.id, target_user_id=user.id).first() is not None if user else False
        is_following = s.query(Follow).filter_by(
            follower_id=user.id, following_id=profile.id, accepted=True
        ).first() is not None if user else False
        is_follow_pending = s.query(Follow).filter_by(
            follower_id=user.id, following_id=profile.id, accepted=False
        ).first() is not None if user else False
        notify_on_post = False
        if is_following and user:
            follow_rel = s.query(Follow).filter_by(
                follower_id=user.id, following_id=profile.id, accepted=True
            ).first()
            if follow_rel:
                notify_on_post = follow_rel.notify_on_post
        has_pending_follower = s.query(Follow).filter_by(
            follower_id=profile.id, following_id=user.id, accepted=False
        ).first() is not None if user else False
        is_follower = s.query(Follow).filter_by(
            follower_id=profile.id, following_id=user.id, accepted=True
        ).first() is not None if user else False
        novels_q = s.query(Novel).filter_by(author_id=profile.id)
        if not user or profile.id != user.id:
            novels_q = novels_q.filter(Novel.visibility != "private")
        novels = _apply_latest_activity_order(novels_q, s).all()
        show_follows = user and (profile.id == user.id or profile.follow_list_visibility != "private")
        followers = s.query(Follow).filter_by(following_id=profile.id, accepted=True).order_by(desc(Follow.created_at)).limit(20).all() if show_follows else []
        following = s.query(Follow).filter_by(follower_id=profile.id, accepted=True).order_by(desc(Follow.created_at)).limit(20).all() if show_follows else []
        _all_post_ids = {p.id for p in posts}
        for _p in posts:
            if _p.boost_of_id:
                _all_post_ids.add(_p.boost_of_id)
        _all_post_ids = list(_all_post_ids | set(profile.pinned_posts or []))
        if user and _all_post_ids:
            _liked_ids = {l.post_id for l in s.query(Like).filter(Like.user_id == user.id, Like.post_id.in_(_all_post_ids)).all()}
            _boosted_ids = {b.post_id for b in s.query(Boost).filter(Boost.user_id == user.id, Boost.post_id.in_(_all_post_ids)).all()}
            _bookmarked_ids = {bm.post_id for bm in s.query(Bookmark).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(_all_post_ids)).all()}
            _vote_map = {}
            for v in s.query(Vote).filter(Vote.user_id == user.id, Vote.post_id.in_(_all_post_ids)).all():
                _vote_map[v.post_id] = v.option_index
            _my_reaction_map = {}
            for l in s.query(Like).filter(Like.user_id == user.id, Like.post_id.in_(_all_post_ids), Like.reaction.isnot(None)).all():
                _my_reaction_map[l.post_id] = l.reaction
            _reactions_map = {}
            for pid, react, cnt in s.query(Like.post_id, func.coalesce(Like.reaction, "★"), func.count(Like.id)).filter(Like.post_id.in_(_all_post_ids)).group_by(Like.post_id, Like.reaction).order_by(Like.post_id, func.min(Like.id)).all():
                if pid not in _reactions_map:
                    _reactions_map[pid] = {}
                _reactions_map[pid][react] = cnt
            _booster_map = {}
            _three_hours_ago = datetime.now(timezone.utc) - timedelta(seconds=10800)
            _boost_rows = s.query(Boost).filter(
                Boost.post_id.in_(_all_post_ids),
                Boost.user_id == profile.id,
                Boost.created_at > _three_hours_ago,
            ).order_by(desc(Boost.created_at)).all()
            _booster_user_ids = {b.user_id for b in _boost_rows}
            _booster_users = {u.id: u for u in s.query(User).filter(User.id.in_(_booster_user_ids)).all()} if _booster_user_ids else {}
            for b in _boost_rows:
                if b.post_id not in _booster_map:
                    _booster_map[b.post_id] = _booster_users.get(b.user_id)
            all_mentioned_ids = set()
            _posts_for_mentions = s.query(Post).filter(Post.id.in_(_all_post_ids)).all()
            for pp in _posts_for_mentions:
                if pp.mentioned_user_ids:
                    all_mentioned_ids.update(pp.mentioned_user_ids)
            _mentioned_users_map = {}
            if all_mentioned_ids:
                _mu = {}
                for _um in s.query(User).filter(User.id.in_(all_mentioned_ids)).all():
                    if _um.is_remote and _um.remote_url:
                        _name = _um.username.split("@")[0]
                        _domain = urlparse(_um.remote_url).hostname or ""
                        _mu[_um.id] = f"{_name}@{_domain}"
                    else:
                        _mu[_um.id] = _um.username
                for pp in _posts_for_mentions:
                    if pp.mentioned_user_ids:
                        _mentioned_users_map[pp.id] = [_mu.get(mid, "?") for mid in pp.mentioned_user_ids if mid in _mu]
                    else:
                        _mentioned_users_map[pp.id] = []
        else:
            _liked_ids = _boosted_ids = _bookmarked_ids = set()
            _vote_map = _my_reaction_map = _reactions_map = _mentioned_users_map = _booster_map = {}
        _pj_kwargs = dict(_liked_ids=_liked_ids, _boosted_ids=_boosted_ids, _bookmarked_ids=_bookmarked_ids,
                          _vote_map=_vote_map, _my_reaction_map=_my_reaction_map,
                          _reactions_map=_reactions_map, _booster_map=_booster_map,
                          _mentioned_users_map=_mentioned_users_map)
        return {
            "profile": _user_json(profile),
            "posts": [_post_json(p, s, user, **_pj_kwargs) for p in posts],
            "novels": [_novel_json(n, s) for n in novels],
            "followers": [{"user": _user_json(f.follower)} for f in (followers if show_follows else [])],
            "following": [{"user": _user_json(f.following)} for f in (following if show_follows else [])],
            "total_posts": total_posts,
            "followers_count": followers_count if show_follows else 0,
            "following_count": following_count if show_follows else 0,
            "is_following": is_following,
            "is_follow_pending": is_follow_pending,
            "notify_on_post": notify_on_post,
            "has_pending_follower": has_pending_follower,
            "is_follower": is_follower,
            "is_mine": profile.id == user.id if user else False,
            "is_muted": is_muted,
            "is_blocked": is_blocked,
            "am_i_blocked": am_i_blocked,
            "has_more": has_more,
            "offset": offset,
            "pinned_posts_data": [_post_json(p, s, user, **_pj_kwargs) for p in (s.query(Post).filter(Post.id.in_(profile.pinned_posts or []), Post.is_deleted == False).all() if profile.pinned_posts else []) if _can_view(p, user, s)],
            "pinned_series_data": [_novel_json(n, s) for n in (s.query(Novel).filter(Novel.id.in_(profile.pinned_series or [])).all() if profile.pinned_series else [])],
        }


@users_router.get("/users/{username}/media")
def api_user_media(request: Request, username: str, limit: int = Query(12), offset: int = Query(0)):
    user = get_current_user(request)
    with get_session() as s:
        profile = s.query(User).filter_by(username=username).first()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        rows = s.execute(
            text("SELECT id FROM posts WHERE author_id = :aid AND is_deleted = FALSE AND CAST(media_attachments AS TEXT) NOT IN ('null', '[]') ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
            {"aid": profile.id, "lim": limit + 1, "off": offset}
        ).fetchall()
        post_ids = [r[0] for r in rows]
        has_more = len(post_ids) > limit
        post_ids = post_ids[:limit]
        if not post_ids:
            return {"posts": [], "has_more": False}
        posts = s.query(Post).options(selectinload(Post.author)).filter(Post.id.in_(post_ids)).all()
        posts = sorted(posts, key=lambda p: post_ids.index(p.id))
        if not has_more:
            total = s.execute(
                text("SELECT COUNT(*) FROM posts WHERE author_id = :aid AND is_deleted = FALSE AND CAST(media_attachments AS TEXT) NOT IN ('null', '[]')"),
                {"aid": profile.id}
            ).scalar()
            has_more = total > offset + limit
        return {"posts": [_post_json(p, s, user) for p in posts if _can_view(p, user, s)], "has_more": has_more}


def _save_profile_image(user_id: int, file: UploadFile, prefix: str, max_size: tuple[int, int], storage) -> str:
    _validate_upload(file, allow_video=False, max_size=MAX_AVATAR_SIZE, label="프로필 이미지")
    key = f"{prefix}/local/u{user_id}_{uuid4().hex[:8]}.webp"
    img = Image.open(file.file)
    img = ImageOps.exif_transpose(img)
    img.thumbnail(max_size, Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))

        bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = bg
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=100)
    return storage.save(key, out.getvalue(), "image/webp")


@users_router.post("/profile/update")
def api_update_profile(request: Request, display_name: str = Form(""), summary: str = Form(""),
                       image: UploadFile = File(None), header_image: UploadFile = File(None),
                       custom_fields: str = Form("[]"), profile_hashtags: str = Form("[]"),
                       remove_avatar: bool = Form(False), remove_header: bool = Form(False)):
    user = require_active_auth(request)
    storage = get_storage()
    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        db.display_name = display_name
        db.summary = summary
        if remove_avatar:
            old = db.profile_image
            db.profile_image = ""
            s.flush()
            if old:
                storage.delete(old)
        elif image and image.filename:
            new_url = _save_profile_image(user.id, image, "avatars", (400, 400), storage)
            old = db.profile_image
            db.profile_image = new_url
            s.flush()
            if old:
                storage.delete(old)
        if remove_header:
            old = db.header_image
            db.header_image = ""
            s.flush()
            if old:
                storage.delete(old)
        elif header_image and header_image.filename:
            new_url = _save_profile_image(user.id, header_image, "headers", (1500, 500), storage)
            old = db.header_image
            db.header_image = new_url
            s.flush()
            if old:
                storage.delete(old)
        try:
            parsed_fields = json.loads(custom_fields)
            if isinstance(parsed_fields, list):
                db.custom_fields = [
                    {"name": f.get("name") or f.get("label", ""), "value": f.get("value", "")}
                    for f in parsed_fields
                ]
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            parsed_tags = json.loads(profile_hashtags)
            if isinstance(parsed_tags, list):
                db.profile_hashtags = parsed_tags
        except (json.JSONDecodeError, TypeError):
            pass
        s.commit()
    _cleanup_avatars()
    threading.Thread(target=_broadcast_update_actor, args=(user,), daemon=True).start()
    return {"ok": True}
