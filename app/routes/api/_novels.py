"""Novel (series) endpoints and serializers extracted from _series.py."""
import io
import secrets
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from PIL import Image, ImageOps
from sqlalchemy import desc, func

from app.utils.image import guard_image

guard_image()

from app.core.auth import get_current_user, require_active_auth, require_auth
from app.db.database import get_session
from app.models import Episode, Novel, Post, SeriesFollow, SeriesNotice, Tag, User
from app.serializers import _user_json
from app.utils.datetime import _fmt_dt
from app.utils.storage import get_storage
from app.utils.upload import _validate_upload

novels_router = APIRouter()


def _apply_latest_activity_order(q, s):
    latest_ep = s.query(
        Episode.novel_id, func.max(Episode.created_at).label("max_ep")
    ).group_by(Episode.novel_id).subquery()
    latest_nt = s.query(
        SeriesNotice.novel_id, func.max(SeriesNotice.created_at).label("max_nt")
    ).group_by(SeriesNotice.novel_id).subquery()
    q = q.outerjoin(latest_ep, Novel.id == latest_ep.c.novel_id)
    q = q.outerjoin(latest_nt, Novel.id == latest_nt.c.novel_id)
    return q.order_by(desc(func.coalesce(latest_ep.c.max_ep, latest_nt.c.max_nt)).nullslast())


def _load_novel_meta(s, novels):
    """novel_id -> [episode_count, total_views] 일괄 조회 (episode content 로드 방지)."""
    if not novels:
        return {}
    ids = [n.id for n in novels]
    meta = {nid: [0, 0] for nid in ids}
    for nid, cnt, views in s.query(
        Episode.novel_id, func.count(Episode.id), func.sum(func.coalesce(Episode.views, 0))
    ).filter(Episode.novel_id.in_(ids)).group_by(Episode.novel_id).all():
        meta[nid] = [cnt, views or 0]
    return meta


def _novel_json(n, s=None, _followers_map=None, _episode_meta=None):
    author = None
    if hasattr(n, 'author') and n.author:
        author = _user_json(n.author)
    tag_names = " ".join(t.display_name or t.name for t in (n.tag_list or [])) or (n.tags or "")
    if _episode_meta is not None:
        _ec, _tv = _episode_meta.get(n.id, (0, 0))
        episode_count = _ec or 0
        total_views = _tv or 0
    else:
        episode_count = n.episode_count or 0
        total_views = n.total_views or 0
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
        "episode_count": episode_count,
        "total_views": total_views,
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


@novels_router.post("/pin/series/{novel_id}")
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


@novels_router.post("/unpin/series/{novel_id}")
def api_unpin_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        pinned = list(user.pinned_series or [])
        if novel_id in pinned:
            pinned.remove(novel_id)
            s.query(User).filter_by(id=user.id).update({"pinned_series": pinned})
            s.commit()
    return {"ok": True}


@novels_router.get("/series")
def api_novels(request: Request, limit: int = Query(12, le=100), offset: int = Query(0)):
    with get_session() as s:
        q = _apply_latest_activity_order(s.query(Novel).filter_by(is_published=True, visibility="public"), s)
        raw = q.offset(offset).limit(limit + 1).all()
        has_more = len(raw) > limit
        novels = raw[:limit]
        _episode_meta = _load_novel_meta(s, novels)
        return {"novels": [_novel_json(n, s, _episode_meta=_episode_meta) for n in novels], "has_more": has_more}


@novels_router.get("/series/my")
def api_my_novels(request: Request, limit: int = Query(12, le=100), offset: int = Query(0)):
    user = require_auth(request)
    with get_session() as s:
        q = _apply_latest_activity_order(s.query(Novel).filter_by(author_id=user.id), s)
        total = q.count()
        raw = q.offset(offset).limit(limit).all()
        _episode_meta = _load_novel_meta(s, raw)
        novels = [_novel_json(n, s, _episode_meta=_episode_meta) for n in raw]
        return {"novels": novels, "total": total, "page": offset // limit + 1, "pages": max(1, (total + limit - 1) // limit)}


@novels_router.get("/series/followed")
def api_followed_novels(request: Request, limit: int = Query(12, le=100), offset: int = Query(0)):
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
        _episode_meta = _load_novel_meta(s, raw)
        novels = [_novel_json(n, s, _episode_meta=_episode_meta) for n in raw]
        return {"novels": novels, "total": total, "page": offset // limit + 1, "pages": max(1, (total + limit - 1) // limit)}


@novels_router.post("/series/new")
def api_create_novel(request: Request, title: str = Form(...), description: str = Form(""),
                     tags: str = Form(""), visibility: str = Form("public"), status: str = Form("ongoing"),
                     cover_image: UploadFile = File(None), is_sensitive: bool = Form(False)):
    user = require_active_auth(request)
    is_user_deceased = False
    is_user_deceased = user.get('is_deceased', False) if isinstance(user, dict) else getattr(user, 'is_deceased', False)

    if is_user_deceased:
        raise HTTPException(status_code=403, detail="고인 계정은 시리즈를 생성할 수 없습니다.")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"
    storage = get_storage()
    cover_url = ""
    if cover_image and cover_image.filename:
        ext, _is_image, _is_video, _ = _validate_upload(cover_image, allow_video=False, max_size=5 * 1024 * 1024, label="커버 이미지")
        ct = cover_image.content_type or ""
        if "gif" in ct:
            ext = "gif"
        key = f"series/covers/{uuid4().hex[:16]}.{ext}"
        try:
            img: Image.Image = Image.open(cover_image.file)
        except (Image.DecompressionBombError, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail="커버 이미지 해상도가 너무 큽니다.") from exc
        img = ImageOps.exif_transpose(img) or img
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


@novels_router.get("/series/{novel_id}")
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
        episodes = s.query(Episode).filter_by(novel_id=novel_id)
        is_mine = user.id == novel.author_id if user else False
        if not is_mine:
            episodes = episodes.filter(Episode.is_published == True)
        episodes = episodes.order_by(Episode.episode_number).all()
        author = s.query(User).get(novel.author_id)
        from app.routes.api._episodes import _episode_json  # circular-avoiding lazy import
        episode_list = [_episode_json(e, summary_only=True) for e in episodes]
        novel_json = _novel_json(novel, s)
        if not is_mine:
            for e in episode_list:
                e.pop("views", None)
            novel_json.pop("total_views", None)
        return {
            "novel": novel_json,
            "episodes": episode_list,
            "author": _user_json(author) if author else None,
            "is_mine": user.id == novel.author_id if user else False,
            "is_following": s.query(SeriesFollow).filter_by(user_id=user.id, novel_id=novel.id).count() > 0 if user else False,
        }


@novels_router.post("/series/{novel_id}/follow")
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


@novels_router.post("/series/{novel_id}/unfollow")
def api_unfollow_novel(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(SeriesFollow).filter_by(user_id=user.id, novel_id=novel_id).delete()
        s.commit()
    return {"ok": True}


@novels_router.post("/series/{novel_id}/edit")
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
        ext, _is_image, _is_video, _ = _validate_upload(cover_image, allow_video=False, max_size=5 * 1024 * 1024, label="커버 이미지")
        ct = cover_image.content_type or ""
        if "gif" in ct:
            ext = "gif"
        key = f"series/covers/{uuid4().hex[:16]}.{ext}"
        try:
            img: Image.Image = Image.open(cover_image.file)
        except (Image.DecompressionBombError, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail="커버 이미지 해상도가 너무 큽니다.") from exc
        img = ImageOps.exif_transpose(img) or img
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


@novels_router.post("/series/{novel_id}/delete")
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
