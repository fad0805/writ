"""Episode, draft, and announce-post endpoints extracted from _series.py."""
import json
import logging
import os
import secrets
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import desc, func

from app.config.settings import BASE_URL
from app.core.activitypub import broadcast_to_followers
from app.core.auth import get_current_user, require_active_auth
from app.core.permissions import has_permission
from app.core.push import send_push_to_user
from app.core.threads import spawn
from app.core.timeline_stream import broadcast_notif_sound
from app.db.database import get_session
from app.models import Episode, EpisodeDraft, EpisodeView, Notification, Novel, Post, SeriesFollow
from app.routes.api._episode_serializer import _episode_json
from app.routes.api._novels import _novel_json
from app.utils.content_parser import process_post_content
from app.utils.datetime import _fmt_dt
from app.utils.log import log_admin_action
from app.utils.post import _sync_post_tags
from app.utils.storage import get_storage
from app.utils.to_ap_serializer import to_ap_note
from app.utils.upload import MAX_AUDIO_SIZE, _validate_upload

logger = logging.getLogger("writ.api.episodes")

episodes_router = APIRouter()


def _build_announce_post_content(novel, episode_number, episode_title, episode_id, summary="", announce_comment=""):
    """에피소드 홍보글 본문을 생성한다. // 구분 = <br> 2개, / 구분 = <br> 1개."""
    chunks = []
    if announce_comment:
        chunks.append([announce_comment])
    chunks.append([
        f'「{novel.title}」',
        f'by {novel.author.display_name or novel.author.username}',
    ])
    if novel.tags:
        _tags = ' '.join(f'#{t.strip()}' for t in novel.tags.replace(',', ' ').split() if t.strip())
        if _tags:
            chunks.append([_tags])
    ep_lines = [f'「{episode_number}화: {episode_title}」']
    if summary:
        ep_lines.append(summary)
    ep_lines.append(f'episode : {BASE_URL}/series/{novel.id}/episodes/{episode_id}')
    chunks.append(ep_lines)
    post_content = "\n\n".join("\n".join(c) for c in chunks)
    return process_post_content(post_content, None)


@episodes_router.post("/series/{novel_id}/episodes/new")
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
            post_content = _build_announce_post_content(novel, next_num, title, episode.id, summary, announce_comment)
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
            post.ap_id = f"{BASE_URL}/@{user.username}/{ep_post_number}"  # type: ignore[assignment]
            _sync_post_tags(post, s)
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
                spawn(broadcast_to_followers, user, create_activity)
            except Exception as e:
                logger.warning("Failed to broadcast episode federation: %s", e)
                s.commit()
        else:
            s.commit()

        if is_published:
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


@episodes_router.get("/series/{novel_id}/episodes/{episode_id}")
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
        if not is_mine and not episode.is_published:
            raise HTTPException(status_code=404, detail="Episode not found")
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
        return {
            "episode": ep_json,
            "novel": _novel_json(novel, s),
            "is_mine": is_mine,
            "prev_episode": _episode_json(prev_ep) if prev_ep else None,
            "next_episode": _episode_json(next_ep) if next_ep else None,
        }


@episodes_router.post("/series/{novel_id}/episodes/{episode_id}/edit")
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
            post_content = _build_announce_post_content(episode.novel, episode.episode_number, title, episode_id, summary, announce_comment)
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
            post.ap_id = f"{BASE_URL}/@{user.username}/{ep_post_number}"  # type: ignore[assignment]
            _sync_post_tags(post, s)
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
                spawn(broadcast_to_followers, user, create_activity)
            except Exception as e:
                logger.warning("Failed to broadcast episode edit federation: %s", e)
                s.commit()

        s.commit()
    return {"ok": True}


@episodes_router.post("/series/{novel_id}/episodes/{episode_id}/delete")
def api_delete_episode(request: Request, novel_id: int, episode_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        episode = s.query(Episode).filter_by(id=episode_id, novel_id=novel_id).first()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        if episode.novel.author_id != user.id and not has_permission(user, "content.manage"):
            raise HTTPException(status_code=404, detail="Episode not found")
        if episode.novel.author_id != user.id:
            log_admin_action(user.id, user.username, "delete_episode", target_type="episode", target_id=episode_id, target_username=episode.novel.author.username if episode.novel else "", details=episode.title, ip_address=request.client.host if request.client else "")
        for p in s.query(Post).filter(Post.episode_id == episode_id).all():
            p.episode_id = None
        s.flush()
        s.delete(episode)
        s.commit()
    return {"ok": True}


@episodes_router.get("/series/{novel_id}/drafts")
def api_list_drafts(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id, author_id=user.id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found")
        drafts = s.query(EpisodeDraft).filter_by(user_id=user.id, novel_id=novel_id).order_by(desc(EpisodeDraft.updated_at)).limit(5).all()
        return {"drafts": [{"id": d.id, "title": d.title or "", "summary": d.summary or "", "content": d.content or "", "comment": d.comment or "", "is_published": d.is_published, "announce": d.announce, "announce_comment": d.announce_comment or "", "visibility": d.visibility or "public", "episode_id": d.episode_id, "created_at": _fmt_dt(d.created_at), "updated_at": _fmt_dt(d.updated_at)} for d in drafts]}


@episodes_router.post("/series/{novel_id}/drafts")
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
            draft_id = int(draft.id)
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


@episodes_router.post("/series/{novel_id}/drafts/{draft_id}/delete")
def api_delete_draft(request: Request, novel_id: int, draft_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        draft = s.query(EpisodeDraft).filter_by(id=draft_id, user_id=user.id, novel_id=novel_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        s.delete(draft)
        s.commit()
        return {"ok": True}
