"""Series (novel), episode, draft, and notice endpoints extracted from _core.py."""
import os
import json
import io
import secrets
import logging
from uuid import uuid4
from datetime import datetime
from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from PIL import Image
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models import User, Novel, Episode, EpisodeDraft, SeriesFollow, SeriesNotice, Post, Tag, Notification, EpisodeView
from app.serializers import _user_json
from app.config.settings import BASE_URL
from app.core.activitypub import broadcast_to_followers, _post_to_inbox
from app.utils.to_ap_serializer import to_ap_note
from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_notif_sound
from app.db.database import get_session
from app.routes.auth import require_auth, require_active_auth, get_current_user
from app.utils.datetime import _fmt_dt
from app.utils.log import log_admin_action
from app.utils.storage import get_storage

from app.routes.api._core import _validate_upload, MAX_AUDIO_SIZE

logger = logging.getLogger("writ.api.series")

series_router = APIRouter()


@series_router.post("/pin/series/{novel_id}")
def api_pin_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel or novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Series not found")
        pinned = list(user.pinned_series or [])
        if novel_id in pinned:
            return {"ok": True}
        if len(pinned) >= 3:
            raise HTTPException(status_code=400, detail="최대 3개까지 고정할 수 있습니다.")
        pinned.append(novel_id)
        s.query(User).filter_by(id=user.id).update({"pinned_series": pinned})
        s.commit()
    return {"ok": True}


@series_router.post("/unpin/series/{novel_id}")
def api_unpin_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        pinned = list(user.pinned_series or [])
        if novel_id in pinned:
            pinned.remove(novel_id)
            s.query(User).filter_by(id=user.id).update({"pinned_series": pinned})
            s.commit()
    return {"ok": True}


def _apply_latest_activity_order(q, s):
    latest_ep = s.query(
        Episode.novel_id, func.max(Episode.created_at).label("max_ep")
    ).group_by(Episode.novel_id).subquery()
    latest_nt = s.query(
        SeriesNotice.novel_id, func.max(SeriesNotice.created_at).label("max_nt")
    ).group_by(SeriesNotice.novel_id).subquery()
    q = q.outerjoin(latest_ep, Novel.id == latest_ep.c.novel_id)
    q = q.outerjoin(latest_nt, Novel.id == latest_nt.c.novel_id)
    q = q.order_by(desc(func.coalesce(latest_ep.c.max_ep, latest_nt.c.max_nt)).nullslast())
    return q


@series_router.get("/series")
def api_novels(request: Request, limit: int = Query(12), offset: int = Query(0)):
    with get_session() as s:
        q = _apply_latest_activity_order(s.query(Novel).filter_by(is_published=True, visibility="public"), s)
        raw = q.offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        novels = [_novel_json(n, s) for n in raw[:limit]]
        return {"novels": novels, "has_more": has_more}


@series_router.get("/series/my")
def api_my_novels(request: Request, limit: int = Query(12), offset: int = Query(0)):
    user = require_auth(request)
    with get_session() as s:
        q = _apply_latest_activity_order(s.query(Novel).filter_by(author_id=user.id), s)
        total = q.count()
        raw = q.offset(offset).limit(limit).all()
        novels = [_novel_json(n, s) for n in raw]
        return {"novels": novels, "total": total, "page": offset // limit + 1, "pages": max(1, (total + limit - 1) // limit)}


@series_router.get("/series/followed")
def api_followed_novels(request: Request, limit: int = Query(12), offset: int = Query(0)):
    user = require_auth(request)
    with get_session() as s:
        follow_ids = [f.novel_id for f in s.query(SeriesFollow).filter_by(user_id=user.id).all()]
        if not follow_ids:
            return {"novels": [], "total": 0, "page": 1, "pages": 1}
        q = _apply_latest_activity_order(
            s.query(Novel).filter(Novel.id.in_(follow_ids), Novel.is_published == True), s
        )
        total = q.count()
        raw = q.offset(offset).limit(limit).all()
        novels = [_novel_json(n, s) for n in raw]
        return {"novels": novels, "total": total, "page": offset // limit + 1, "pages": max(1, (total + limit - 1) // limit)}


def _sync_tags(n, s):
    raw = n.tags or ""
    desired = {}
    for t in raw.replace(",", " ").split():
        if t:
            desired[t.lower()] = t
    current = {t.name: t for t in (n.tag_list or [])}
    for lower_name, display in desired.items():
        if lower_name in current:
            tag = current[lower_name]
            if tag.display_name != display:
                tag.display_name = display
        else:
            tag = s.query(Tag).filter_by(name=lower_name).first()
            if not tag:
                tag = Tag(name=lower_name, display_name=display)
                s.add(tag)
                s.flush()
            else:
                tag.display_name = display
            n.tag_list.append(tag)
    for name in set(current.keys()) - set(desired.keys()):
        tag = current[name]
        n.tag_list.remove(tag)


def _novel_json(n, s=None, _followers_map=None):
    author = None
    if hasattr(n, 'author') and n.author:
        author = _user_json(n.author)
    tag_names = " ".join(t.display_name or t.name for t in (n.tag_list or [])) or (n.tags or "")
    result = {
        "id": n.id,
        "number": n.number or "",
        "title": n.title,
        "description": n.description or "",
        "cover_image": n.cover_image or "",
        "tags": tag_names,
        "status": n.status or "ongoing",
        "is_published": n.is_published,
        "is_sensitive": getattr(n, 'is_sensitive', False) or False,
        "episode_count": n.episode_count or 0,
        "total_views": n.total_views or 0,
        "visibility": n.visibility or "public",
        "created_at": _fmt_dt(n.created_at),
        "updated_at": _fmt_dt(n.updated_at),
        "author": author,
        "author_id": n.author_id,
    }
    if _followers_map is not None:
        result["followers_count"] = _followers_map.get(n.id, 0)
    elif s is not None:
        result["followers_count"] = s.query(SeriesFollow).filter_by(novel_id=n.id).count()
    return result


@series_router.post("/series/new")
def api_create_novel(request: Request, title: str = Form(...), description: str = Form(""),
                     tags: str = Form(""), visibility: str = Form("public"), status: str = Form("ongoing"),
                     cover_image: UploadFile = File(None), is_sensitive: bool = Form(False)):
    user = require_active_auth(request)
    is_user_deceased = False
    if isinstance(user, dict):
        is_user_deceased = user.get('is_deceased', False)
    else:
        is_user_deceased = getattr(user, 'is_deceased', False)

    if is_user_deceased:
        raise HTTPException(status_code=403, detail="고인 계정은 시리즈를 생성할 수 없습니다.")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"
    storage = get_storage()
    cover_url = ""
    if cover_image and cover_image.filename:
        ext, is_image, is_video, _ = _validate_upload(cover_image, allow_video=False, max_size=5 * 1024 * 1024, label="커버 이미지")
        ct = cover_image.content_type or ""
        if "gif" in ct:
            ext = "gif"
        key = f"series/covers/{uuid4().hex[:16]}.{ext}"
        img = Image.open(cover_image.file)
        target_w, target_h = 120, 160
        img_w, img_h = img.size
        ratio = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * ratio)
        new_h = int(img_h * ratio)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        out = io.BytesIO()
        img.save(out, format="WEBP" if ext != "gif" else "GIF", quality=90)
        cover_url = storage.save(key, out.getvalue(), f"image/{ext}")
    with get_session() as s:
        novel_number = secrets.token_hex(4)
        novel_status = status if status in ("ongoing", "hiatus", "discontinued", "completed") else "ongoing"
        novel = Novel(author_id=user.id, title=title, description=description, tags=tags,
                      visibility=visibility, is_published=visibility != "private", status=novel_status,
                      cover_image=cover_url, number=novel_number, is_sensitive=is_sensitive)
        s.add(novel)
        s.flush()
        _sync_tags(novel, s)
        nid = novel.id
        s.commit()
    return {"ok": True, "novel_id": nid}


@series_router.get("/series/{novel_id}")
def api_get_novel(request: Request, novel_id: int):
    user = get_current_user(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if novel.visibility == "private" and (not user or novel.author_id != user.id):
            raise HTTPException(status_code=404, detail="Novel not found")
        if not user and novel.visibility in ("public", "unlisted"):
            pass
        episodes = s.query(Episode).filter_by(novel_id=novel_id).order_by(Episode.episode_number).all()
        author = s.query(User).get(novel.author_id)
        is_mine = user.id == novel.author_id if user else False
        episode_list = [_episode_json(e, summary_only=True) for e in episodes]
        novel_json = _novel_json(novel, s)
        if not is_mine:
            for e in episode_list:
                e.pop("views", None)
            novel_json.pop("total_views", None)
        result = {
            "novel": novel_json,
            "episodes": episode_list,
            "author": _user_json(author) if author else None,
            "is_mine": user.id == novel.author_id if user else False,
            "is_following": s.query(SeriesFollow).filter_by(user_id=user.id, novel_id=novel.id).count() > 0 if user else False,
        }
    return result


@series_router.post("/series/{novel_id}/follow")
def api_follow_novel(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if novel.visibility == "private" and novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Novel not found")
        existing = s.query(SeriesFollow).filter_by(user_id=user.id, novel_id=novel.id).first()
        if not existing:
            sf = SeriesFollow(user_id=user.id, novel_id=novel.id)
            s.add(sf)
            s.commit()
    return {"ok": True}


@series_router.post("/series/{novel_id}/unfollow")
def api_unfollow_novel(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(SeriesFollow).filter_by(user_id=user.id, novel_id=novel_id).delete()
        s.commit()
    return {"ok": True}


@series_router.post("/series/{novel_id}/edit")
def api_edit_novel(request: Request, novel_id: int, title: str = Form(...), description: str = Form(""),
                   tags: str = Form(""), visibility: str = Form("public"), status: str = Form("ongoing"),
                   cover_image: UploadFile = File(None), remove_cover: bool = Form(False),
                   is_sensitive: bool = Form(False)):
    user = require_active_auth(request)
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"
    storage = get_storage()
    cover_url = ""
    if cover_image and cover_image.filename:
        ext, is_image, is_video, _ = _validate_upload(cover_image, allow_video=False, max_size=5 * 1024 * 1024, label="커버 이미지")
        ct = cover_image.content_type or ""
        if "gif" in ct:
            ext = "gif"
        key = f"series/covers/{uuid4().hex[:16]}.{ext}"
        img = Image.open(cover_image.file)
        target_w, target_h = 120, 160
        img_w, img_h = img.size
        ratio = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * ratio)
        new_h = int(img_h * ratio)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        out = io.BytesIO()
        img.save(out, format="WEBP" if ext != "gif" else "GIF", quality=90)
        cover_url = storage.save(key, out.getvalue(), f"image/{ext}")
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        novel.title = title
        novel.description = description
        novel.tags = tags
        novel.visibility = visibility
        novel.status = status if status in ("ongoing", "hiatus", "discontinued", "completed") else "ongoing"
        novel.is_published = visibility != "private"
        novel.is_sensitive = is_sensitive
        if remove_cover:
            old = novel.cover_image
            novel.cover_image = ""
            s.flush()
            if old and old.startswith("/"):
                storage.delete(old)
        if cover_url:
            old = novel.cover_image
            novel.cover_image = cover_url
            s.flush()
            if old and old.startswith("/"):
                storage.delete(old)
        s.flush()
        _sync_tags(novel, s)
        s.commit()
    return {"ok": True}


@series_router.post("/series/{novel_id}/episodes/new")
def api_create_episode(request: Request, novel_id: int, title: str = Form(...), content: str = Form(""),
                       summary: str = Form(""), comment: str = Form(""),
                       announce: bool = Form(False), announce_comment: str = Form(""),
                       is_published: bool = Form(True), page_mode: bool = Form(False),
                       view_mode: str = Form("text"), comic_view_mode: str = Form("paged"),
                       image_urls: str = Form("[]"), reading_direction: str = Form("ltr"),
                       audio: UploadFile = File(None)):
    user = require_active_auth(request)
    if getattr(user, 'is_deceased', False):
        raise HTTPException(status_code=403, detail="고인 계정은 에피소드를 생성할 수 없습니다.")
    if view_mode == "comic":
        try:
            image_list = json.loads(image_urls) if image_urls else []
        except (json.JSONDecodeError, TypeError):
            image_list = []
        if not image_list:
            raise HTTPException(status_code=400, detail="만화 모드에는 이미지가 필요합니다")
    else:
        image_list = []
        if not title.strip() or not content.strip():
            raise HTTPException(status_code=400, detail="Title and content are required")
    audio_url = ""
    if audio and audio.filename:
        _validate_upload(audio, allow_video=False, allow_audio=True, max_size=MAX_AUDIO_SIZE, label="음악 파일")
        aext = os.path.splitext(audio.filename)[1].lower()
        akey = f"episodes/audio/{uuid4().hex[:16]}{aext}"
        storage = get_storage()
        storage.save(akey, audio.file.read())
        audio_url = storage.url(akey)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        max_ep = s.query(Episode).filter_by(novel_id=novel.id).order_by(desc(Episode.episode_number)).first()
        next_num = (max_ep.episode_number + 1) if max_ep else 1
        episode = Episode(novel_id=novel.id, episode_number=next_num, title=title, content=content, summary=summary, comment=comment, audio_url=audio_url, is_published=is_published, page_mode=page_mode, view_mode=view_mode, comic_view_mode=comic_view_mode, image_urls=image_list, reading_direction=reading_direction)
        s.add(episode)
        s.flush()
        if announce:
            parts = []
            if announce_comment:
                parts.append(announce_comment)
            link = f'📖 <a href="/series/{novel.id}/episodes/{episode.id}">[{novel.title}] {next_num}화: {title}</a>'
            parts.append(link)
            if summary:
                parts.append(summary)
            post_content = "\n\n".join(parts)
            ep_post_number = secrets.token_hex(4)
            post = Post(
                author_id=user.id,
                content=post_content,
                visibility="public",
                number=ep_post_number,
                novel_id=novel.id,
                episode_id=episode.id,
                ap_id="",
            )
            s.add(post)
            s.flush()
            post.ap_id = f"{BASE_URL}/@{user.username}/{ep_post_number}"
            s.flush()
            try:
                s.refresh(post)
                create_activity = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{BASE_URL}/activities/create/{post.id}",
                    "type": "Create",
                    "actor": user.actor_uri(),
                    "object": to_ap_note(post),
                }
                s.commit()
                broadcast_to_followers(user, create_activity)
            except Exception as e:
                logger.warning("Failed to broadcast episode federation: %s", e)
                s.commit()
        else:
            s.commit()

        followers = s.query(SeriesFollow).filter_by(novel_id=novel.id).all()
        for sf in followers:
            if sf.user_id != user.id:
                n = Notification(
                    user_id=sf.user_id,
                    from_user_id=user.id,
                    notification_type="new_episode",
                    metadata_json=json.dumps({
                        "novel_id": novel.id,
                        "novel_title": novel.title,
                        "episode_id": episode.id,
                        "episode_number": next_num,
                        "episode_title": title,
                    }, ensure_ascii=False),
                )
                s.add(n)
        if followers:
            s.commit()
            for sf in followers:
                if sf.user_id != user.id:
                    send_push_to_user(sf.user_id, "new_episode", user.username, metadata={"novel_id": novel.id})
                    broadcast_notif_sound(sf.user_id)

        eid = episode.id
    return {"ok": True, "episode_id": eid}


@series_router.get("/series/{novel_id}/episodes/{episode_id}")
def api_get_episode(request: Request, novel_id: int, episode_id: int):
    user = get_current_user(request)
    with get_session() as s:
        episode = s.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        novel = episode.novel
        if novel.visibility == "private" and (not user or novel.author_id != user.id):
            raise HTTPException(status_code=404, detail="Episode not found")
        if not user and novel.visibility in ("public", "unlisted"):
            pass
        is_mine = novel.author_id == user.id if user else False
        prev_ep = s.query(Episode).filter(
            Episode.novel_id == novel_id,
            Episode.episode_number < episode.episode_number,
        )
        if not is_mine:
            prev_ep = prev_ep.filter(Episode.is_published == True)
        prev_ep = prev_ep.order_by(desc(Episode.episode_number)).first()
        next_ep = s.query(Episode).filter(
            Episode.novel_id == novel_id,
            Episode.episode_number > episode.episode_number,
        )
        if not is_mine:
            next_ep = next_ep.filter(Episode.is_published == True)
        next_ep = next_ep.order_by(Episode.episode_number).first()
        if user and not is_mine:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            existing_view = s.query(EpisodeView).filter(
                EpisodeView.user_id == user.id,
                EpisodeView.episode_id == episode.id,
                EpisodeView.viewed_at >= today_start,
            ).first()
            if not existing_view:
                episode.views = (episode.views or 0) + 1
                s.add(EpisodeView(user_id=user.id, episode_id=episode.id))
        s.commit()
        ep_json = _episode_json(episode)
        if not is_mine:
            ep_json.pop("views", None)
        result = {
            "episode": ep_json,
            "novel": _novel_json(novel, s),
            "is_mine": is_mine,
            "prev_episode": _episode_json(prev_ep) if prev_ep else None,
            "next_episode": _episode_json(next_ep) if next_ep else None,
        }
    return result


@series_router.post("/series/{novel_id}/episodes/{episode_id}/edit")
def api_edit_episode(request: Request, novel_id: int, episode_id: int,
                     title: str = Form(...), content: str = Form(""),
                     summary: str = Form(""), comment: str = Form(""),
                     is_published: bool = Form(True), announce: bool = Form(False),
                     visibility: str = Form("public"), announce_comment: str = Form(""),
                     page_mode: bool = Form(False), view_mode: str = Form("text"),
                     comic_view_mode: str = Form("paged"),
                     image_urls: str = Form("[]"), reading_direction: str = Form("ltr"),
                     audio: UploadFile = File(None), remove_audio: bool = Form(False)):
    user = require_active_auth(request)
    audio_url = ""
    if audio and audio.filename:
        _validate_upload(audio, allow_video=False, allow_audio=True, max_size=MAX_AUDIO_SIZE, label="음악 파일")
        aext = os.path.splitext(audio.filename)[1].lower()
        akey = f"episodes/audio/{uuid4().hex[:16]}{aext}"
        storage = get_storage()
        storage.save(akey, audio.file.read())
        audio_url = storage.url(akey)
    with get_session() as s:
        episode = s.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode or episode.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Episode not found")
        episode.title = title
        episode.content = content
        episode.summary = summary
        episode.comment = comment
        episode.is_published = is_published
        episode.page_mode = page_mode
        episode.view_mode = view_mode
        episode.comic_view_mode = comic_view_mode
        try:
            episode.image_urls = json.loads(image_urls) if image_urls else []
        except (json.JSONDecodeError, TypeError):
            episode.image_urls = []
        episode.reading_direction = reading_direction
        if remove_audio:
            old = episode.audio_url
            episode.audio_url = ""
            s.flush()
            if old and old.startswith("/"):
                get_storage().delete(old)
        if audio_url:
            old = episode.audio_url
            episode.audio_url = audio_url
            s.flush()
            if old and old.startswith("/"):
                get_storage().delete(old)

        if announce:
            parts = []
            if announce_comment:
                parts.append(announce_comment)
            link = f'📖 <a href="/series/{novel_id}/episodes/{episode_id}">[{episode.novel.title}] {episode.episode_number}화: {title}</a>'
            parts.append(link)
            if summary:
                parts.append(summary)
            post_content = "\n\n".join(parts)
            ep_post_number = secrets.token_hex(4)
            post = Post(
                author_id=user.id,
                content=post_content,
                visibility=visibility,
                number=ep_post_number,
                novel_id=novel_id,
                episode_id=episode_id,
                ap_id="",
            )
            s.add(post)
            s.flush()
            post.ap_id = f"{BASE_URL}/@{user.username}/{ep_post_number}"
            s.flush()
            try:
                s.refresh(post)
                create_activity = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{BASE_URL}/activities/create/{post.id}",
                    "type": "Create",
                    "actor": user.actor_uri(),
                    "object": to_ap_note(post),
                }
                s.commit()
                broadcast_to_followers(user, create_activity)
            except Exception as e:
                logger.warning("Failed to broadcast episode edit federation: %s", e)
                s.commit()

        s.commit()
    return {"ok": True}


@series_router.post("/series/{novel_id}/episodes/{episode_id}/delete")
def api_delete_episode(request: Request, novel_id: int, episode_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        episode = s.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        if episode.novel.author_id != user.id and user.role not in ("admin", "moderator", "owner"):
            raise HTTPException(status_code=404, detail="Episode not found")
        if episode.novel.author_id != user.id:
            log_admin_action(user.id, user.username, "delete_episode", target_type="episode", target_id=episode_id, target_username=episode.novel.author.username if episode.novel else "", details=episode.title, ip_address=request.client.host if request.client else "")
        for p in s.query(Post).filter(Post.episode_id == episode_id).all():
            p.episode_id = None
        s.flush()
        s.delete(episode)
        s.commit()
    return {"ok": True}


@series_router.post("/series/{novel_id}/delete")
def api_delete_novel(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        s.query(Post).filter(Post.novel_id == novel.id).update({Post.novel_id: None})
        s.query(Episode).filter(Episode.novel_id == novel.id).update({Episode.novel_id: None})
        s.delete(novel)
        s.commit()
    return {"ok": True}


def _episode_json(e, summary_only=False):
    d = {
        "id": e.id,
        "novel_id": e.novel_id,
        "episode_number": e.episode_number,
        "title": e.title,
        "summary": e.summary or "",
        "comment": e.comment or "",
        "audio_url": e.audio_url or "",
        "view_mode": getattr(e, "view_mode", "text"),
        "comic_view_mode": getattr(e, "comic_view_mode", "paged"),
        "image_urls": getattr(e, "image_urls", []) or [],
        "reading_direction": getattr(e, "reading_direction", "ltr"),
        "views": e.views or 0,
        "is_published": e.is_published,
        "page_mode": getattr(e, "page_mode", False),
        "created_at": _fmt_dt(e.created_at),
        "updated_at": _fmt_dt(e.updated_at),
    }
    if not summary_only:
        d["content"] = e.content
    return d


def _notice_json(n):
    return {
        "id": n.id,
        "uuid": n.uuid,
        "novel_id": n.novel_id,
        "title": n.title,
        "content": n.content,
        "is_pinned": n.is_pinned,
        "created_at": _fmt_dt(n.created_at),
        "updated_at": _fmt_dt(n.updated_at),
    }


@series_router.get("/series/{novel_id}/drafts")
def api_list_drafts(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        drafts = s.query(EpisodeDraft).filter_by(user_id=user.id, novel_id=novel_id).order_by(desc(EpisodeDraft.updated_at)).limit(5).all()
        return {"drafts": [{"id": d.id, "title": d.title or "", "summary": d.summary or "", "content": d.content or "", "comment": d.comment or "", "is_published": d.is_published, "announce": d.announce, "announce_comment": d.announce_comment or "", "visibility": d.visibility or "public", "episode_id": d.episode_id, "created_at": _fmt_dt(d.created_at), "updated_at": _fmt_dt(d.updated_at)} for d in drafts]}


@series_router.post("/series/{novel_id}/drafts")
def api_save_draft(request: Request, novel_id: int, title: str = Form(""), summary: str = Form(""), content: str = Form(""), comment: str = Form(""), is_published: bool = Form(True), announce: bool = Form(False), announce_comment: str = Form(""), visibility: str = Form("public"), draft_id: int = Form(0), episode_id: int = Form(0)):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        if draft_id:
            draft = s.query(EpisodeDraft).filter_by(id=draft_id, user_id=user.id, novel_id=novel_id).first()
            if not draft:
                raise HTTPException(status_code=404, detail="Draft not found")
        else:
            count = s.query(EpisodeDraft).filter_by(user_id=user.id, novel_id=novel_id).count()
            if count >= 5:
                oldest = s.query(EpisodeDraft).filter_by(user_id=user.id, novel_id=novel_id).order_by(EpisodeDraft.updated_at.asc()).first()
                if oldest:
                    s.delete(oldest)
                    s.flush()
            draft = EpisodeDraft(user_id=user.id, novel_id=novel_id)
            s.add(draft)
            s.flush()
            draft_id = draft.id
        draft.title = title
        draft.summary = summary
        draft.content = content
        draft.comment = comment
        draft.is_published = is_published
        draft.announce = announce
        draft.announce_comment = announce_comment
        draft.visibility = visibility
        draft.episode_id = episode_id or None
        draft.updated_at = func.now()
        s.commit()
        return {"ok": True, "draft_id": draft_id}


@series_router.post("/series/{novel_id}/drafts/{draft_id}/delete")
def api_delete_draft(request: Request, novel_id: int, draft_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        draft = s.query(EpisodeDraft).filter_by(id=draft_id, user_id=user.id, novel_id=novel_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        s.delete(draft)
        s.commit()
        return {"ok": True}


@series_router.get("/series/{novel_id}/notices")
def api_list_notices(request: Request, novel_id: int):
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Series not found")
        notices = s.query(SeriesNotice).filter_by(novel_id=novel_id).order_by(
            SeriesNotice.is_pinned.desc(), SeriesNotice.created_at.desc()).all()
        return [_notice_json(n) for n in notices]


@series_router.post("/series/{novel_id}/notices/new")
def api_create_notice(request: Request, novel_id: int, title: str = Form(...), content: str = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel or novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Series not found")
        notice = SeriesNotice(novel_id=novel_id, title=title, content=content)
        s.add(notice)
        s.commit()
        return _notice_json(notice)


@series_router.post("/series/{novel_id}/notices/{notice_id}/edit")
def api_edit_notice(request: Request, novel_id: int, notice_id: int, title: str = Form(...), content: str = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        notice = s.query(SeriesNotice).filter_by(id=notice_id, novel_id=novel_id).first()
        if not notice or notice.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Notice not found")
        notice.title = title
        notice.content = content
        s.commit()
        return _notice_json(notice)


@series_router.post("/series/{novel_id}/notices/{notice_id}/delete")
def api_delete_notice(request: Request, novel_id: int, notice_id: int):
    user = require_auth(request)
    with get_session() as s:
        notice = s.query(SeriesNotice).filter_by(id=notice_id, novel_id=novel_id).first()
        if not notice:
            raise HTTPException(status_code=404, detail="Notice not found")
        if notice.novel.author_id != user.id and user.role not in ("admin", "moderator", "owner"):
            raise HTTPException(status_code=404, detail="Notice not found")
        s.delete(notice)
        s.commit()
    return {"ok": True}


@series_router.post("/series/{novel_id}/notices/{notice_id}/pin")
def api_toggle_pin_notice(request: Request, novel_id: int, notice_id: int):
    user = require_auth(request)
    with get_session() as s:
        notice = s.query(SeriesNotice).filter_by(id=notice_id, novel_id=novel_id).first()
        if not notice or notice.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Notice not found")
        if not notice.is_pinned:
            pinned_count = s.query(SeriesNotice).filter_by(novel_id=novel_id, is_pinned=True).count()
            if pinned_count >= 3:
                raise HTTPException(status_code=400, detail="최대 3개까지 고정할 수 있습니다")
        notice.is_pinned = not notice.is_pinned
        s.commit()
        return _notice_json(notice)
