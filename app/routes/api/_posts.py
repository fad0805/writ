"""Post detail, edit, and delete endpoints extracted from _core.py."""
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import selectinload

from app.models import Post, Like, Boost, Vote, Bookmark, Notification
from app.utils.to_ap_serializer import to_ap_note
from app.serializers import _post_json
from app.config.settings import BASE_URL
from app.core.activitypub import _build_reactions, broadcast_to_followers, _fetch_remote_post, _send_delete_post
from app.core.broadcast import broadcast_post
from app.core.timeline_stream import broadcast_refresh_notifs, broadcast_delete
from app.db.database import get_session
from app.core.auth import require_active_auth, get_current_user
from app.utils.content_parser import process_post_content, extract_mentions
from app.db.mention_resolver import resolve_handles_to_ids
from app.utils.post import _get_descendant_ids, _sync_post_tags
from app.utils.storage import get_storage
from app.core.visibility import _can_view
from app.core.threads import spawn

logger = logging.getLogger("writ.api.posts")

# 리모트 부모 fetch 전용 바운드 실행기 — 요청 스레드풀을 잠식하지 않도록 제한된 스레드에서만
# 느린 리모트 I/O(_fetch_remote_post → _resolve_actor)가 실행되게 한다.
_remote_fetch_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="remote-parent")

posts_router = APIRouter()


def _fetch_remote_parent_json(url, user_id):
    """Fetch a remote parent post off the request thread and serialize it."""
    with get_session() as s:
        signer = s.query(User).filter_by(id=user_id).first()
        remote_parent = _fetch_remote_post(url, signer, s)
        if remote_parent is None:
            return None
        user = s.query(User).filter_by(id=user_id).first()
        return _post_json(remote_parent, s, user)


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
            if post.visibility not in ("public", "unlisted", "home"):
                raise HTTPException(status_code=403, detail="Not authorized")
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
        # 리모트 부모 fetch는 별도 바운드 실행기에서 8초 상한으로만 대기한다.
        # 느린/응답 없는 리모트 서버가 요청 스레드를 최대 수십 초 붙잡지 않게 한다.
        fut = _remote_fetch_executor.submit(_fetch_remote_parent_json, fetch_remote_url, user.id)
        try:
            remote_parent_json = fut.result(timeout=8)
        except TimeoutError:
            logger.warning("Remote parent fetch for %s exceeded 8s, skipping", fetch_remote_url)
            remote_parent_json = None
        except Exception as e:
            logger.error("Failed to fetch or process remote parent: %s", e, exc_info=True)
            remote_parent_json = None
        if remote_parent_json is not None:
            result["ancestors"] = [remote_parent_json]
    return result


def _do_edit_post(s, post, user, content, summary, visibility=None, is_sensitive=None):
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    if post.summary and post.summary.startswith("[관리자 강제] ") and not summary.startswith("[관리자 강제] "):
        raise HTTPException(status_code=403, detail="관리자가 강제한 CW는 수정할 수 없습니다")
    new_content = content.replace('\r\n', '\n').replace('\r', '\n')
    post.content = process_post_content(new_content, post=post)
    # 수정 시 멘션 재추출 — mentioned_user_ids를 새 내용에 맞게 갱신
    # (리모트 멘션은 백그라운드에서 해석한 뒤 Update 활동 발송)
    mentions = extract_mentions(new_content, post=post)
    mentioned_handles = [m["handle"] for m in mentions]
    mentioned_ids = resolve_handles_to_ids(mentioned_handles, resolve_remote=False)
    post.mentioned_user_ids = mentioned_ids
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
        _post_id = post.id

        def _send_update():
            try:
                # 리모트 멘션을 해석해 mentioned_user_ids를 최종 확정한 뒤 Update 발송
                try:
                    full_ids = resolve_handles_to_ids(mentioned_handles)
                    if full_ids != mentioned_ids:
                        with get_session() as s:
                            s.query(Post).filter_by(id=_post_id).update({"mentioned_user_ids": full_ids})
                            s.commit()
                except Exception as e:
                    logger.error("Failed to resolve remote mentions on edit: %s", e, exc_info=True)
                update_activity = None
                with get_session() as s:
                    _p = s.query(Post).filter_by(id=_post_id).first()
                    if not _p:
                        return
                    note_data = to_ap_note(_p)
                    note_data.pop("@context", None)
                    note_data.pop("url", None)
                    note_data["atomUri"] = _p.ap_id
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
                        "id": f"{BASE_URL}/activities/update/{_p.id}",
                        "type": "Update",
                        "actor": user.actor_uri(),
                        "to": note_data.get("to", []),
                        "cc": note_data.get("cc", []),
                        "object": note_data,
                    }
                if update_activity:
                    broadcast_to_followers(user, update_activity)
            except Exception as e:
                logger.error("Update federation failed: %s", e, exc_info=True)

        spawn(_send_update)


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


def _do_delete_post(s, post, user, cascade=True, keep_media=False):
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
        def _background(_pid=post.id, _media=media, _ap_id=ap_id, _remote=is_remote_author, _user=user, _keep=keep_media):
            if _media and not _keep:
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
        spawn(_background)

    return media, ap_id


@posts_router.post("/posts/{post_id}/delete")
def api_delete_post(request: Request, post_id: int, keep_media: bool = Form(False)):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.author_id != user.id and not user.is_admin:
            raise HTTPException(status_code=403, detail="Cannot delete this post")
        _do_delete_post(s, post, user, cascade=True, keep_media=keep_media)
    return {"ok": True}
