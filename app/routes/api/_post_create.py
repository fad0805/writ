"""Post creation endpoint extracted from _posts.py."""
import os
import json
import secrets
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone, UTC
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Form, HTTPException

from app.models import User, Post, Notification
from app.serializers import _post_json
from app.config.settings import BASE_URL, MAX_POST_LENGTH
from app.core.activitypub import _ap_fetch, _fetch_and_save_ap_object
from app.core.eventbus import broadcast
from app.core.push import send_push_to_user
from app.core.broadcast import _broadcast_timeline
from app.core.timeline_stream import broadcast_refresh_notifs, broadcast_notif_sound
from app.db.database import get_session
from app.db.mention_resolver import resolve_handles_to_ids
from app.core.auth import require_active_auth
from app.utils.content_parser import process_post_content, extract_mentions
from app.utils.post import _sync_post_tags
from app.core.feed import _broadcast_federation

logger = logging.getLogger("writ.api.post_create")

post_create_router = APIRouter()

# 글/답글 작성용 전용 executor. 리모트 inbox 처리(handle_inbox)와 기본 풀을
# 공유하지 않아, 리모트 활동 폭주 시에도 작성 요청이 뒤에서 대기하지 않는다.
# 코어 수에 맞춰 워커를 제한해 GIL 경합/커넥션 소진을 막는다.
_post_create_executor = ThreadPoolExecutor(
    max_workers=max(4, min(8, (os.cpu_count() or 1) + 1)),
    thread_name_prefix="post-create",
)


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


@post_create_router.post("/posts")
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
        _post_create_executor, _do_create_post,
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
    mentioned_ids = resolve_handles_to_ids(mentioned_handles, resolve_remote=False)
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
                    now = datetime.now(UTC)
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

        _post_create_executor.submit(_create_notifications_and_broadcast)

        def _resolve_remote_mentions_and_federate():
            try:
                full_ids = resolve_handles_to_ids(mentioned_handles)
                if full_ids != mentioned_ids:
                    with get_session() as s:
                        s.query(Post).filter_by(id=post.id).update({"mentioned_user_ids": full_ids})
                        s.commit()
            except Exception as e:
                logger.error("Failed to resolve remote mentions: %s", e)
            _broadcast_federation(user_id, post.id, visibility, content)

        _post_create_executor.submit(_resolve_remote_mentions_and_federate)

        try:
            broadcast("new_post", {"post_id": post.id, "author_id": user_id})
        except Exception as e:
            logger.error("Failed to broadcast new_post event: %s", e, exc_info=True)

        pj = _post_json(post, s, _author)
        _post_create_executor.submit(_broadcast_timeline, pj, user_id, visibility)
        return pj
