"""Post, timeline, and interaction endpoints extracted from _core.py."""
import os
import re
import json
import logging
import threading
import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import selectinload

from app.models import User, Post, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, Report, ServerRule
from app.utils.to_ap_serializer import to_ap_note
from app.serializers import _post_json, _user_json
from app.config.settings import BASE_URL, MAX_POST_LENGTH
from app.core.activitypub import _fetch_remote_post, broadcast_to_followers, _build_reactions, _resolve_actor, _send_delete_post, _send_flag, _get_instance_actor
from app.core.eventbus import broadcast
from app.core.push import send_push_to_user
from app.core.broadcast import broadcast_post, _broadcast_timeline
from app.core.timeline_stream import broadcast_refresh_notifs, broadcast_notif_sound, broadcast_delete
from app.db.database import get_session
from app.db.mention_resolver import resolve_handles_to_ids
from app.routes.auth import require_auth, require_active_auth, get_current_user
from app.utils.content_parser import process_post_content, extract_mentions
from app.utils.post import _get_descendant_ids, _sync_post_tags
from app.utils.storage import get_storage

from app.routes.api._core import _ap_fetch, _fetch_and_save_ap_object, _check_fetch_domain_allowed
from app.core.interactions import _can_view
from app.routes.api._series import _novel_json, _episode_json
from app.core.feed import _broadcast_federation

logger = logging.getLogger("writ.api.posts")

posts_router = APIRouter()



# ── Helpers ──

def _validate_media_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("https", ""):
        return False
    if parsed.scheme == "javascript" or parsed.scheme == "data":
        return False
    path = parsed.path.lower()
    allowed_ext = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm"}
    ext = os.path.splitext(path)[1]
    return ext in allowed_ext


def _normalize_remote_post_url(url: str) -> str:
    """Web URL(/@user/id) → AP URL(/users/user/statuses/id) 형태로 정규화."""
    m = re.match(r'^(https?://[^/]+)/@(\w+(?:@\S+)?)/([\w-]+)(\?.*)?$', url)
    if m:
        return f"{m.group(1)}/users/{m.group(2)}/statuses/{m.group(3)}"
    if url.endswith("/activity"):
        return url[:-len("/activity")]
    return url





@posts_router.get("/posts/{post_id}")
def api_get_post(request: Request, post_id: int):
    # --- [추가 시작] ActivityPub 전용 inbox 처리 ---
    accept_header = request.headers.get("Accept", "")
    is_activitypub = "application/activity+json" in accept_header or "application/ld+json" in accept_header
    if is_activitypub:
        with get_session() as s:
            post = s.query(Post).filter_by(id=post_id).first()
            if not post:
                raise HTTPException(status_code=404, detail="Not Found")
            note = to_ap_note(post)
            return JSONResponse(content=note, media_type="application/activity+json")
    # --- [추가 끝] ---

    user = get_current_user(request)
    fetch_remote_url = None
    with get_session() as s:
        post = s.query(Post).options(
            selectinload(Post.author),
            selectinload(Post.parent).selectinload(Post.author),
        ).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=403, detail="Cannot view this post")
        result = _post_json(post, s, user)

        limit = min(int(request.query_params.get("reply_limit", 5)), 50)
        offset = int(request.query_params.get("reply_offset", 0))
        anc_limit = min(int(request.query_params.get("ancestor_limit", 5)), 50)
        anc_offset = int(request.query_params.get("ancestor_offset", 0))

        descendant_ids = _get_descendant_ids(s, post_id, max_depth=20) if limit > 0 else []
        result["total_descendants"] = len(descendant_ids)
        result["total_replies"] = result["total_descendants"]

        if descendant_ids:
            descendants = s.query(Post).options(
                selectinload(Post.author),
                selectinload(Post.parent),
            ).filter(Post.id.in_(descendant_ids)).order_by(Post.created_at).offset(offset).limit(limit).all()
        else:
            descendants = []
        reply_id_set = {r.id for r in descendants}
        _reply_liked_ids = _reply_boosted_ids = _reply_bookmarked_ids = set()
        if user and reply_id_set:
            _reply_liked_ids = set(r[0] for r in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(reply_id_set)).all())
            _reply_boosted_ids = set(r[0] for r in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(reply_id_set)).all())
            _reply_bookmarked_ids = set(r[0] for r in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(reply_id_set)).all())
        result["replies"] = [_post_json(r, s, user, _liked_ids=_reply_liked_ids, _boosted_ids=_reply_boosted_ids, _bookmarked_ids=_reply_bookmarked_ids) for r in descendants if _can_view(r, user, s)]
        result["has_more_replies"] = offset + limit < len(descendant_ids)

        ancestors = []
        has_more_ancestors = False
        fetch_remote_url = None
        if anc_limit > 0:
            cur = post.parent
            ancestor_ids = []

            max_depth = 100
            depth = 0
            while cur and depth < max_depth:
                if not cur.is_deleted:
                    ancestor_ids.append(cur.id)
                    depth += 1
                cur = cur.parent

            total_ancestors = len(ancestor_ids)
            has_more_ancestors = anc_offset + anc_limit < total_ancestors
            sliced_ids = ancestor_ids[anc_offset:anc_offset + anc_limit]

            if sliced_ids:
                if user:
                    _anc_liked = {a[0] for a in s.query(Like.post_id).filter(Like.user_id == user.id, Like.post_id.in_(sliced_ids)).all()}
                    _anc_boosted = {a[0] for a in s.query(Boost.post_id).filter(Boost.user_id == user.id, Boost.post_id.in_(sliced_ids)).all()}
                    _anc_bookmarked = {a[0] for a in s.query(Bookmark.post_id).filter(Bookmark.user_id == user.id, Bookmark.post_id.in_(sliced_ids)).all()}
                else:
                    _anc_liked = _anc_boosted = _anc_bookmarked = set()

                sliced_posts = s.query(Post).options(
                    selectinload(Post.author), selectinload(Post.parent),
                ).filter(Post.id.in_(sliced_ids)).all()
                sliced_map = {p.id: p for p in sliced_posts}

                for aid in sliced_ids:
                    p = sliced_map.get(aid)
                    if p and _can_view(p, user, s):
                        ancestors.append(_post_json(p, s, user, _liked_ids=_anc_liked, _boosted_ids=_anc_boosted, _bookmarked_ids=_anc_bookmarked))

            if not ancestors and not sliced_ids and post.in_reply_to_ap_id:
                parent = s.query(Post).filter_by(ap_id=post.in_reply_to_ap_id).first()
                if parent and _can_view(parent, user, s):
                    ancestors = [_post_json(parent, s, user)]
                else:
                    fetch_remote_url = post.in_reply_to_ap_id
        result["ancestors"] = ancestors
        result["has_more_ancestors"] = has_more_ancestors

    if fetch_remote_url:
        try:
            with get_session() as remote_s:
                remote_parent = _fetch_remote_post(fetch_remote_url, user, remote_s)
                # 💡 remote_parent가 정확히 존재하고(None이 아니고) 부모 게시글 객체일 때만 파싱하도록 방어막을 칩니다.
                if remote_parent is not None:
                    result["ancestors"] = [_post_json(remote_parent, remote_s, user)]
                else:
                    logger.warning("Remote parent fetch returned None for URL: %s", fetch_remote_url)
        except Exception as e:
            # 💡 pass로 에러를 완전히 지우지 말고, 개발 중에는 최소한 어떤 에러인지 로그를 남겨줍니다.
            logger.error("Failed to fetch or process remote parent: %s", e, exc_info=True)
    return result


@posts_router.post("/posts")
async def api_create_post(
    request: Request,
    content: str = Form(...),
    summary: str = Form(""),
    visibility: str = Form("public"),
    parent_id: int = Form(None),
    dm_target_id: int = Form(None),
    share_url: str = Form(""),
    media_attachments: str = Form("[]"),
    is_sensitive: bool = Form(False),
    poll_options: str = Form(""),
    poll_expires_in: int = Form(60),
    link_preview: str = Form(""),
):
    user = require_active_auth(request)
    loop = asyncio.get_running_loop()
    pj = await loop.run_in_executor(
        None, _do_create_post,
        user.id, user.is_limited, getattr(user, 'is_sensitive', False),
        content, summary, visibility, parent_id,
        dm_target_id, share_url, media_attachments, is_sensitive,
        poll_options, poll_expires_in, link_preview,
    )
    return pj


def _do_create_post(
    user_id, user_limited, user_sensitive, content, summary, visibility, parent_id,
    dm_target_id, share_url, media_attachments, is_sensitive,
    poll_options, poll_expires_in, link_preview,
):
    quote_of_ap_id = ""
    quote_of_id = None
    pending_quote_url = None
    if share_url:
        with get_session() as _qs:
            local = _qs.query(Post).filter(Post.ap_id == share_url).first()
            if local:
                quote_of_ap_id = local.ap_id
                quote_of_id = local.id
            else:
                pending_quote_url = share_url
    content_html = process_post_content(content, None)
    mentions = extract_mentions(content, None)
    mentioned_handles = [m["handle"] for m in mentions]
    mentioned_ids = resolve_handles_to_ids(mentioned_handles)
    if dm_target_id:
        mentioned_ids.append(dm_target_id)
    mentioned_ids = list(set(mentioned_ids))

    if not content_html.strip() and not poll_options:
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    total_len = len(content) + len(summary)
    if total_len > MAX_POST_LENGTH:
        raise HTTPException(status_code=400, detail=f"Total length exceeds {MAX_POST_LENGTH}")
    if visibility not in ("public", "home", "followers", "mention"):
        visibility = "public"

    if user_limited and visibility == "public":
        visibility = "home"

    if parent_id:
        vis_order = {"public": 0, "home": 1, "followers": 2, "mention": 3}
        with get_session() as _s:
            parent_post = _s.query(Post).filter_by(id=parent_id).first()
            if parent_post:
                parent_vis = parent_post.visibility or "public"
                if vis_order.get(parent_vis, 0) > vis_order.get(visibility, 0):
                    visibility = parent_vis

    with get_session() as s:
        _author = s.query(User).filter_by(id=user_id).first()
        if not _author:
            raise HTTPException(status_code=404, detail="User not found")
        post_number = secrets.token_hex(4)
        author_is_sensitive = user_sensitive
        if parent_id:
            _parent_exists = s.query(Post.id).filter_by(id=parent_id).first()
            if not _parent_exists:
                raise HTTPException(status_code=404, detail="부모 게시글이 삭제되었습니다.")
        post = Post(
            author_id=user_id,
            content=content_html,
            summary=summary,
            visibility=visibility,
            in_reply_to_id=parent_id,
            mentioned_user_ids=mentioned_ids,
            number=post_number,
            ap_id="",
            is_dm=bool(dm_target_id),
            is_sensitive=is_sensitive or author_is_sensitive,
            quote_of_ap_id=quote_of_ap_id,
            quote_of_id=quote_of_id,
        )
        if link_preview:
            try:
                post.link_preview = json.loads(link_preview)
            except (json.JSONDecodeError, TypeError):
                pass
        try:
            media = json.loads(media_attachments)
            if isinstance(media, list):
                cleaned = []
                for m in media[:16]:
                    if isinstance(m, str):
                        if _validate_media_url(m):
                            cleaned.append({"url": m, "type": "image", "alt": ""})
                    elif isinstance(m, dict) and _validate_media_url(m.get("url", "")):
                        cleaned.append({"url": m["url"], "type": m.get("type", "image"), "alt": m.get("alt", "")})
                post.media_attachments = cleaned
        except (json.JSONDecodeError, TypeError):
            pass
        if poll_options:
            try:
                opts = json.loads(poll_options)
                if isinstance(opts, list) and 2 <= len(opts) <= 10 and all(isinstance(o, str) and o.strip() for o in opts):
                    now = datetime.now(timezone.utc)
                    expires_at = (now + timedelta(minutes=poll_expires_in)).isoformat() if poll_expires_in > 0 else None
                    post.poll_data = {
                        "options": [{"text": o.strip(), "votes_count": 0} for o in opts],
                        "expires_at": expires_at,
                    }
            except (json.JSONDecodeError, TypeError):
                pass
        s.add(post)
        s.flush()
        post.ap_id = f"{BASE_URL}/@{_author.username}/{post.number}"
        _sync_post_tags(post, s)
        if parent_id:
            parent = s.query(Post).filter_by(id=parent_id).first()
            if parent:
                post.in_reply_to_ap_id = parent.ap_id or ""
        s.commit()

        def _create_notifications_and_broadcast():
            try:
                if pending_quote_url:
                    try:
                        with get_session() as _qs:
                            _signer = _qs.query(User).get(user_id)
                        if not _signer:
                            return
                        data = _ap_fetch(pending_quote_url, _signer)
                        if data:
                            obj = data.get("object", data)
                            if obj.get("type") in ("Note", "Article"):
                                result = _fetch_and_save_ap_object(obj, _signer)
                                if result:
                                    with get_session() as uqs:
                                        uqs.query(Post).filter_by(id=post.id).update({
                                            "quote_of_ap_id": result.ap_id, "quote_of_id": result.id
                                        })
                                        uqs.commit()
                    except Exception:
                        pass

                with get_session() as ns:
                    mentioned_notified = set()
                    for mu_id in mentioned_ids:
                        if mu_id != user_id:
                            notif = Notification(user_id=mu_id, from_user_id=user_id, notification_type="mention", post_id=post.id)
                            ns.add(notif)
                            mentioned_notified.add(mu_id)
                    if parent_id:
                        parent = ns.query(Post).filter_by(id=parent_id).first()
                        if parent and parent.author_id != user_id and parent.author_id not in mentioned_notified:
                            notif = Notification(user_id=parent.author_id, from_user_id=user_id, notification_type="reply", post_id=post.id)
                            ns.add(notif)
                    ns.commit()

                for mu_id in mentioned_ids:
                    if mu_id != user_id:
                        send_push_to_user(mu_id, "mention", _author.username, post.id)
                        broadcast_notif_sound(mu_id)
                        broadcast_refresh_notifs(mu_id)
                if parent_id:
                    with get_session() as ps:
                        parent = ps.query(Post).filter_by(id=parent_id).first()
                    if parent and parent.author_id != user_id and parent.author_id not in [mid for mid in mentioned_ids if mid != user_id]:
                        send_push_to_user(parent.author_id, "reply", _author.username, post.id)
                        broadcast_notif_sound(parent.author_id)
                        broadcast_refresh_notifs(parent.author_id)
            except Exception as e:
                logger.error("Failed to create notifications: %s", e, exc_info=True)

        threading.Thread(target=_create_notifications_and_broadcast, daemon=True).start()
        threading.Thread(target=_broadcast_federation, args=(user_id, post.id, visibility, content), daemon=True).start()

        try:
            broadcast("new_post", {"post_id": post.id, "author_id": user_id})
        except Exception as e:
            logger.error("Failed to broadcast new_post event: %s", e, exc_info=True)

        pj = _post_json(post, s, _author)
        threading.Thread(target=_broadcast_timeline, args=(pj, user_id, visibility), daemon=True).start()
        return pj


def _do_edit_post(s, post, user, content, summary, visibility=None, is_sensitive=None):
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    if post.summary and post.summary.startswith("[관리자 강제] ") and not summary.startswith("[관리자 강제] "):
        raise HTTPException(status_code=403, detail="관리자가 강제한 CW는 수정할 수 없습니다")
    new_content = content.replace('\r\n', '\n').replace('\r', '\n')
    post.content = process_post_content(new_content, post=post)
    post.summary = summary
    if visibility is not None:
        post.visibility = visibility
    if is_sensitive is not None:
        post.is_sensitive = is_sensitive
    _sync_post_tags(post, s)
    s.commit()

    try:
        _ua = post.author
        broadcast_post({
            "id": post.id,
            "number": post.number or "",
            "content": post.content,
            "summary": post.summary or "",
            "visibility": post.visibility or "public",
            "created_at": post.created_at.isoformat() if post.created_at else "",
            "author": {
                "id": _ua.id, "username": _ua.username,
                "display_name": _ua.display_name or _ua.username,
                "avatar": _ua.profile_image or "", "header": _ua.header_image or "",
                "summary": _ua.summary or "", "is_admin": _ua.is_admin,
                "is_locked": getattr(_ua, "is_locked", False),
                "is_limited": getattr(_ua, "is_limited", False),
                "is_remote": _ua.is_remote, "ap_id": _ua.remote_url or "",
            },
            "likes_count": s.query(Like).filter_by(post_id=post.id).count(),
            "boosts_count": s.query(Boost).filter_by(post_id=post.id).count(),
            "replies_count": s.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count(),
            "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
            "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
            "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
            "poll_data": post.poll_data, "my_vote": None,
            "reactions": _build_reactions(s, post.id),
            "my_reaction": None,
            "type": "update",
        }, post.author_id, post.visibility or "public", False)
    except Exception:
        pass

    if post.ap_id and not post.author.is_remote:
        try:
            note_data = to_ap_note(post)
            note_data.pop("@context", None)
            note_data.pop("url", None)
            note_data["atomUri"] = post.ap_id
            note_data["updated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            note_data.setdefault("summary", None)
            note_data.setdefault("sensitive", False)
            note_data.setdefault("attachment", [])
            note_data.setdefault("tag", [])
            note_data.setdefault("inReplyTo", None)
            update_activity = {
                "@context": [
                    "https://www.w3.org/ns/activitystreams",
                    "https://w3id.org/security/v1",
                ],
                "id": f"{BASE_URL}/activities/update/{post.id}",
                "type": "Update",
                "actor": user.actor_uri(),
                "to": note_data.get("to", []),
                "cc": note_data.get("cc", []),
                "object": note_data,
            }
            def _send_update():
                try:
                    broadcast_to_followers(user, update_activity)
                except Exception as e:
                    logger.error("Update federation failed: %s", e, exc_info=True)
            threading.Thread(target=_send_update, daemon=True).start()
        except Exception as e:
            logger.error("Update activity build failed: %s", e, exc_info=True)


@posts_router.post("/posts/{post_id}/edit")
def api_edit_post(request: Request, post_id: int, content: str = Form(...), summary: str = Form("")):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id != user.id:
            raise HTTPException(status_code=403, detail="Cannot edit this post")
        _do_edit_post(s, post, user, content, summary)
        return _post_json(post, s, user)


def _do_delete_post(s, post, user, cascade=True):
    media = list(post.media_attachments or [])
    ap_id = post.ap_id or ""
    is_remote_author = bool(post.author.is_remote)
    post.content = ""
    post.media_attachments = []
    post.poll_data = None
    post.link_preview = None
    post.is_deleted = True
    s.query(Notification).filter_by(post_id=post.id).delete()
    broadcast_refresh_notifs(post.author_id)
    s.flush()

    _cascade_authors = set()
    if cascade:
        def _all_deleted(pid):
            return not s.query(Post).filter(
                Post.in_reply_to_id == pid, Post.is_deleted == False
            ).first()

        _pid = post.id
        while True:
            _parent = s.query(Post).filter(Post.in_reply_to_id == _pid).first()
            if not _parent:
                if _pid == post.id:
                    _parent = s.query(Post).get(post.in_reply_to_id) if post.in_reply_to_id else None
                else:
                    _parent = s.query(Post).get(_pid)
            if not _parent or not _parent.is_deleted:
                break
            if not _all_deleted(_parent.id):
                break
            s.query(Like).filter(Like.post_id == _parent.id).delete()
            s.query(Boost).filter(Boost.post_id == _parent.id).delete()
            s.query(Bookmark).filter(Bookmark.post_id == _parent.id).delete()
            s.query(Vote).filter(Vote.post_id == _parent.id).delete()
            s.query(Notification).filter(Notification.post_id == _parent.id).delete()
            _cascade_authors.add(_parent.author_id)
            s.delete(_parent)
            _pid = _parent.in_reply_to_id
    s.commit()

    try:
        broadcast_delete(post.id)
        for _aid in _cascade_authors:
            broadcast_refresh_notifs(_aid)
    except Exception:
        pass

    if media or (ap_id and ap_id.startswith("http") and not is_remote_author):
        def _background(_pid=post.id, _media=media, _ap_id=ap_id, _remote=is_remote_author, _user=user):
            if _media:
                storage = get_storage()
                for m in _media:
                    if isinstance(m, dict) and m.get("url"):
                        try:
                            storage.delete(m["url"])
                        except Exception:
                            pass
            if _ap_id and _ap_id.startswith("http") and not _remote:
                try:
                    with get_session() as _s:
                        p = _s.query(Post).get(_pid)
                        if p:
                            _send_delete_post(p, _user)
                        else:
                            logger.warning("DELETE_FAIL: post %s not found in DB", _pid)
                except Exception as e:
                    logger.error("DELETE_FAIL: %s", e, exc_info=True)
        threading.Thread(target=_background, daemon=True).start()

    return media, ap_id


@posts_router.post("/posts/{post_id}/delete")
def api_delete_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id != user.id and not user.is_admin:
            raise HTTPException(status_code=403, detail="Cannot delete this post")
        _do_delete_post(s, post, user, cascade=True)
    return {"ok": True}


@posts_router.post("/reports")
def api_create_report(request: Request, target_type: str = Form(...), target_id: int = Form(...), reason: str = Form(...), forward_to_remote: bool = Form(False), rule_ids: str = Form("")):
    user = require_active_auth(request)
    target_type = target_type.strip().lower()
    if target_type not in ("post", "novel", "episode"):
        raise HTTPException(status_code=400, detail="Invalid target_type")
    if forward_to_remote:
        _cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
        with get_session() as _s:
            _recent = _s.query(Report).filter(
                Report.reporter_id == user.id,
                Report.forward_to_remote == True,
                Report.created_at >= _cutoff,
            ).count()
            if _recent >= 3:
                raise HTTPException(status_code=429, detail="원격 신고는 1분에 3회까지 가능합니다")
    parsed_rule_ids = []
    if rule_ids and rule_ids.strip():
        try:
            parsed = json.loads(rule_ids)
            if isinstance(parsed, list):
                parsed_rule_ids = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if not reason or len(reason.strip()) < 10:
        if not parsed_rule_ids:
            raise HTTPException(status_code=400, detail="Reason must be at least 10 characters")
    with get_session() as s:
        existing = s.query(Report).filter_by(
            reporter_id=user.id, target_type=target_type, target_id=target_id, status="pending"
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Already reported")
        report = Report(reporter_id=user.id, target_type=target_type, target_id=target_id, reason=reason.strip(), forward_to_remote=forward_to_remote, rule_ids=parsed_rule_ids)
        s.add(report)
        s.flush()
        report_id = report.id
        admins = s.query(User).filter(User.role.in_(["admin", "moderator", "owner"])).all()
        target_label = ""
        target_author_name = ""
        target_obj = None
        if target_type == "post":
            target_obj = s.query(Post).filter_by(id=target_id).first()
            if target_obj:
                target_label = (target_obj.content or "")[:120]
                target_author_name = target_obj.author.username
        elif target_type == "novel":
            target_obj = s.query(Novel).filter_by(id=target_id).first()
            if target_obj:
                target_label = target_obj.title[:120]
                target_author_name = target_obj.author.username
        elif target_type == "episode":
            target_obj = s.query(Episode).filter_by(id=target_id).first()
            if target_obj:
                target_label = target_obj.title[:120]
                target_author_name = target_obj.novel.author.username if target_obj.novel else ""
        meta = {
            "type": "report",
            "report_id": report_id,
            "target_type": target_type,
            "target_id": target_id,
            "target_label": target_label,
            "target_author": target_author_name,
            "reason": reason.strip()[:200],
        }
        for admin in admins:
            if admin.id == user.id:
                continue
            s.add(Notification(
                user_id=admin.id, from_user_id=user.id,
                notification_type="moderation",
                metadata_json=json.dumps(meta),
            ))
        s.commit()
        for admin in admins:
            broadcast_refresh_notifs(admin.id)
        for admin in admins:
            if admin.id != user.id:
                send_push_to_user(admin.id, "moderation", user.username)
                broadcast_notif_sound(admin.id)

        if forward_to_remote and target_obj and hasattr(target_obj, 'author') and target_obj.author and target_obj.author.is_remote:
            try:
                _send_flag(user, target_type, target_obj, reason.strip()[:200], parsed_rule_ids)
            except Exception as e:
                logger.error("Failed to send Flag activity: %s", e, exc_info=True)
    return {"ok": True, "report_id": report_id}


@posts_router.get("/rules")
def api_list_rules():
    with get_session() as s:
        rules = s.query(ServerRule).order_by(ServerRule.sort_order).all()
        return [{"id": r.id, "title": r.title, "description": r.description, "sort_order": r.sort_order} for r in rules]




@posts_router.get("/by-series-number/{username}/{number}")
def api_by_series_number(request: Request, username: str, number: str):
    user = get_current_user(request)
    with get_session() as s:
        author = s.query(User).filter_by(username=username).first()
        if not author:
            raise HTTPException(status_code=404, detail="User not found")
        novel = s.query(Novel).filter_by(author_id=author.id, number=number).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if novel.visibility == "private" and (not user or novel.author_id != user.id):
            raise HTTPException(status_code=404, detail="Novel not found")
        return {"id": novel.id}


@posts_router.post("/fetch-series")
def api_fetch_series(request: Request, url: str = Form(...)):
    with get_session() as s:
        m = re.match(r"(?:https?://[^/]+)?/series/(\d+)$", url)
        if m:
            novel = s.query(Novel).filter_by(id=int(m.group(1))).first()
            if novel and novel.visibility != "private":
                author = s.query(User).get(novel.author_id)
                return {"type": "series", "novel": _novel_json(novel, s), "author": _user_json(author) if author else None}
        m = re.match(r"(?:https?://[^/]+)?/series/by-number/(\w+)/([a-f0-9]+)", url)
        if m:
            author = s.query(User).filter_by(username=m.group(1)).first()
            if author:
                novel = s.query(Novel).filter_by(author_id=author.id, number=m.group(2)).first()
                if novel and novel.visibility != "private":
                    return {"type": "series", "novel": _novel_json(novel, s), "author": _user_json(author)}
        m = re.match(r"(?:https?://[^/]+)?/series/@(\w+)/(\S+)", url)
        if m:
            author = s.query(User).filter_by(username=m.group(1)).first()
            if author:
                novel = s.query(Novel).filter_by(author_id=author.id, number=m.group(2)).first()
                if novel and novel.visibility != "private":
                    return {"type": "series", "novel": _novel_json(novel, s), "author": _user_json(author)}
        raise HTTPException(status_code=404, detail="Series not found")


@posts_router.post("/fetch-episode")
def api_fetch_episode(request: Request, url: str = Form(...)):
    user = get_current_user(request)
    with get_session() as s:
        m = re.match(r"(?:https?://[^/]+)?/series/(\d+)/episodes/(\d+)", url)
        if m:
            novel = s.query(Novel).filter_by(id=int(m.group(1))).first()
            if not novel or novel.visibility == "private":
                raise HTTPException(status_code=404, detail="Episode not found")
            episode = s.query(Episode).filter_by(id=int(m.group(2)), novel_id=novel.id).first()
            if not episode or not episode.is_published:
                raise HTTPException(status_code=404, detail="Episode not found")
            author = s.query(User).get(novel.author_id)
            return {
                "type": "episode",
                "episode": _episode_json(episode),
                "novel": _novel_json(novel, s),
                "author": _user_json(author) if author else None,
            }
        m = re.match(r"(?:https?://[^/]+)?/series/@(\w+)/(\S+?)/episodes/(\d+)", url)
        if m:
            author = s.query(User).filter_by(username=m.group(1)).first()
            if author:
                novel = s.query(Novel).filter_by(author_id=author.id, number=m.group(2)).first()
                if novel and novel.visibility == "private":
                    raise HTTPException(status_code=404, detail="Episode not found")
                if novel:
                    episode = s.query(Episode).filter_by(id=int(m.group(3)), novel_id=novel.id).first()
                    if episode and episode.is_published:
                        return {
                            "type": "episode",
                            "episode": _episode_json(episode),
                            "novel": _novel_json(novel, s),
                            "author": _user_json(author) if author else None,
                        }
        raise HTTPException(status_code=404, detail="Episode not found")


@posts_router.get("/by-number/{username}/{number}")
def api_by_number(request: Request, username: str, number: str):
    accept = request.headers.get("accept", "")
    with get_session() as s:
        author = s.query(User).filter_by(username=username).first()
        post = None
        if author:
            post = s.query(Post).filter_by(author_id=author.id, number=number).first()
        if not post:
            # 로컬에 없으면 원격 AP에서 가져오기 시도
            remote_user = None
            if author:
                remote_user = author
            elif "@" in username:
                parts = username.split("@", 1)
                uname, domain = parts[0], parts[1]
                remote_url = f"https://{domain}/users/{uname}"
                remote_user = _resolve_actor(remote_url, sign_as=_get_instance_actor(s))
            if remote_user and remote_user.remote_url:
                base = remote_user.remote_url.rsplit("/users/", 1)[0] if "/users/" in remote_user.remote_url else ""
                if base:
                    remote_post_url = f"{base}/users/{remote_user.username.split('@')[0]}/statuses/{number}"
                    signer = _get_instance_actor(s)
                    post = _fetch_remote_post(remote_post_url, signer, s)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        # ActivityPub 요청 → AP JSON 반환
        if "application/activity+json" in accept or "application/ld+json" in accept:
            if post.visibility not in ("public", "unlisted", "home"):
                raise HTTPException(status_code=403, detail="Not authorized")
            return JSONResponse(content=to_ap_note(post), media_type="application/activity+json")
        # 일반 요청 → 로그인 없이도 공개 게시글 조회 가능
        user = get_current_user(request)
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        return _post_json(post, s, user)


@posts_router.post("/fetch-post")
def api_fetch_post(request: Request, url: str = Form(...)):
    user = require_auth(request)
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    err = _check_fetch_domain_allowed(url)
    if err:
        raise HTTPException(status_code=403, detail=err)

    # 💡 로컬 DB에 이미 저장된 원격 게시물이라면 네트워크 요청 없이 바로 반환 (빠른 인용 로딩)
    try:
        normalized = _normalize_remote_post_url(url)
        with get_session() as s:
            existing = s.query(Post).options(
                selectinload(Post.author),
            ).filter(Post.ap_id.in_([url, normalized]), Post.is_deleted == False).first()
            if existing and _can_view(existing, user, s):
                return _post_json(existing, s, user)
    except Exception as e:
        logger.error("fetch-post DB check failed: %s", e, exc_info=True)

    data = _ap_fetch(url, user)
    logger.info("fetch-post url=%s data_is_none=%s", url, data is None)
    if not data:
        raise HTTPException(status_code=400, detail="Cannot fetch post")

    logger.info("fetch-post data type=%s keys=%s", data.get("type"), list(data.keys())[:10])
    obj = data.get("object", data)
    obj_type = data.get("type", "")
    if obj_type in ("Create", "Announce"):
        obj = obj.get("object", obj) if isinstance(obj, dict) else obj
        obj_type = obj.get("type", "") if isinstance(obj, dict) else ""
    logger.info("fetch-post obj_type=%s obj_keys=%s", obj_type, list(obj.keys())[:10] if isinstance(obj, dict) else type(obj))
    if obj_type in ("Person", "Application", "Service"):
        with get_session() as _us:
            actor = _resolve_actor(url, sign_as=user)
            if actor:
                return {"type": "user", "redirect": f"/@{actor.username}"}
        raise HTTPException(status_code=400, detail="Cannot resolve actor")
    if obj_type not in ("Note", "Article"):
        raise HTTPException(status_code=400, detail=f"Not a Note/Article (type={obj_type})")

    result = _fetch_and_save_ap_object(obj, user)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to save post")
    return result


__all__ = ["posts_router"]
