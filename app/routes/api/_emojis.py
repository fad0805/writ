"""Emoji CRUD endpoints extracted from _misc.py."""
import os
import re
import io
import logging
from uuid import uuid4

from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse
from PIL import Image
from sqlalchemy import desc, or_

from app.models import CustomEmoji
from app.config.settings import S3_ENABLED
from app.db.database import get_session
from app.core.auth import require_auth
from app.utils.emoji import EMOJI_DIR, _refresh_emoji_cache_forcibly, _emoji_url
from app.utils.storage import get_storage

logger = logging.getLogger("writ.api.emojis")

emoji_router = APIRouter()


@emoji_router.get("/emojis")
def api_list_emojis(limit: int = Query(30, le=100), offset: int = Query(0), q: str = Query(""), category: str = Query("")):
    with get_session() as s:
        query = s.query(CustomEmoji)
        if q:
            query = query.filter(
                or_(
                    CustomEmoji.keyword.ilike(f"%{q}%"),
                    CustomEmoji.category.ilike(f"%{q}%"),
                )
            )
        if category != "remote":
            query = query.filter(CustomEmoji.category != "remote")
        elif category == "remote":
            query = query.filter(CustomEmoji.category == "remote")
        total = query.count()
        emojis = query.order_by(desc(CustomEmoji.created_at)).offset(offset).limit(limit).all()
        result = [
            {
                "id": e.id,
                "keyword": e.keyword,
                "file_name": e.file_name,
                "category": e.category or "",
                "aliases": e.aliases or [],
                "url": _emoji_url(e.file_name, e.domain or "", e.category or ""),
                "source_url": e.source_url or "",
                "domain": e.domain or "",
            }
            for e in emojis
        ]
    return JSONResponse({"emojis": result, "total": total, "has_more": offset + limit < total}, headers={"Cache-Control": "no-cache, must-revalidate"})


@emoji_router.post("/emojis")
def api_create_emoji(
    request: Request,
    keyword: str = Form(...),
    category: str = Form(""),
    aliases: str = Form(""),
    image: UploadFile = File(...),
):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not keyword.strip():
        raise HTTPException(status_code=400, detail="Keyword is required")
    keyword = keyword.strip().lower().replace(" ", "_")
    if not re.match(r'^[a-z0-9_]+$', keyword):
        raise HTTPException(status_code=400, detail="Keyword must be lowercase alphanumeric with underscores")

    allowed_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    if image.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {image.content_type}")

    image.file.seek(0, 2)
    _file_size = image.file.tell()
    image.file.seek(0)
    if _file_size > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Emoji image is too large (max 2MB)")

    ct_to_ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
    ext = ct_to_ext.get(image.content_type, "png")
    file_name = f"{uuid4().hex}.{ext}"
    local_dir = os.path.join(EMOJI_DIR, "local")
    if not S3_ENABLED:
        os.makedirs(local_dir, exist_ok=True)
    file_path = os.path.join(local_dir, file_name)
    _emoji_data = None

    try:
        tmp = Image.open(image.file)
        w, h = tmp.size
        tmp.close()
        image.file.seek(0)
        if h > 0 and w / h > 1.5:
            raise HTTPException(status_code=400, detail="Emoji is too wide (max 2x height)")
        if ext == "gif":
            _emoji_data = image.file.read()
            if not S3_ENABLED:
                with open(file_path, "wb") as f:
                    f.write(_emoji_data)
        else:
            file_name = f"{uuid4().hex}.webp"
            file_path = os.path.join(local_dir, file_name)
            img = Image.open(image.file)
            if img.mode == "RGBA" or img.mode == "P":
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
            if img.width > 66 or img.height > 66:
                img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=100)
            _emoji_data = buf.getvalue()
            if not S3_ENABLED:
                with open(file_path, "wb") as f:
                    f.write(_emoji_data)
        if S3_ENABLED and _emoji_data:
            try:
                get_storage().save(f"emojis/local/{file_name}", _emoji_data, f"image/{ext}")
            except Exception:
                pass
    except Exception as e:
        logger.exception("Failed to process emoji image")
        raise HTTPException(status_code=400, detail="Failed to process image")

    alias_list = [a.strip().lower().replace(" ", "_") for a in aliases.split(",") if a.strip()]

    with get_session() as s:
        existing = s.query(CustomEmoji).filter_by(keyword=keyword).first()
        if existing:
            os.remove(file_path)
            raise HTTPException(status_code=400, detail=f"Emoji ':${keyword}:' already exists")
        emoji = CustomEmoji(
            keyword=keyword,
            file_name=file_name,
            category=category or "",
            aliases=alias_list,
        )
        s.add(emoji)
        s.commit()
        _refresh_emoji_cache_forcibly(s)
        return {
            "id": emoji.id,
            "keyword": emoji.keyword,
            "file_name": emoji.file_name,
            "category": emoji.category or "",
            "aliases": emoji.aliases or [],
            "url": _emoji_url(emoji.file_name, emoji.domain or "", emoji.category or ""),
        }


@emoji_router.patch("/emojis/{emoji_id}")
def api_update_emoji(request: Request, emoji_id: int, category: str = Form(""), keyword: str = Form(""), aliases: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        emoji = s.query(CustomEmoji).get(emoji_id)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        if keyword:
            keyword_clean = keyword.strip().lower().replace(" ", "_").replace(":", "")
            if keyword_clean != emoji.keyword:
                existing = s.query(CustomEmoji).filter(CustomEmoji.keyword == keyword_clean, CustomEmoji.id != emoji_id).first()
                if existing:
                    raise HTTPException(status_code=400, detail="Keyword already taken")
                emoji.keyword = keyword_clean
        if category:
            emoji.category = category
        emoji.aliases = [a.strip().lower().replace(" ", "_") for a in aliases.split(",") if a.strip()]
        s.commit()
        _refresh_emoji_cache_forcibly(s)
        return {"ok": True, "emoji": {"id": emoji.id, "keyword": emoji.keyword, "file_name": emoji.file_name, "category": emoji.category, "aliases": emoji.aliases or [], "url": _emoji_url(emoji.file_name, emoji.domain or "", emoji.category or ""), "source_url": emoji.source_url or "", "domain": emoji.domain or ""}}


@emoji_router.post("/emojis/{emoji_id}/copy")
def api_copy_emoji(request: Request, emoji_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        src = s.query(CustomEmoji).get(emoji_id)
        if not src:
            raise HTTPException(status_code=404, detail="Emoji not found")
        new_kw = src.keyword
        existing = s.query(CustomEmoji).filter_by(keyword=new_kw, category="기본").first()
        if existing:
            raise HTTPException(status_code=400, detail="Local emoji with this keyword already exists")
        _ext = src.file_name.rsplit(".", 1)[-1] if "." in src.file_name else "webp"
        _new_fname = f"{new_kw}.{_ext}"
        _src_sub = "remote" if src.domain or src.category == "remote" else "local"
        _data = None

        _storage = get_storage()
        try:
            _data = _storage.get(f"emojis/{_src_sub}/{src.file_name}")
        except Exception:
            pass
        if not _data:
            _src_path = os.path.join(EMOJI_DIR, _src_sub, src.file_name)
            if os.path.isfile(_src_path):
                with open(_src_path, "rb") as f:
                    _data = f.read()

        if _data:
            if not S3_ENABLED:
                try:
                    _dst_local = os.path.join(EMOJI_DIR, "local", _new_fname)
                    os.makedirs(os.path.dirname(_dst_local), exist_ok=True)
                    with open(_dst_local, "wb") as f:
                        f.write(_data)
                except Exception:
                    pass
            try:
                _storage.save(f"emojis/local/{_new_fname}", _data, f"image/{_ext}")
            except Exception:
                pass

        copy = CustomEmoji(keyword=new_kw, file_name=_new_fname, category="기본", aliases=src.aliases or [])
        s.add(copy)
        s.commit()
        _refresh_emoji_cache_forcibly(s)
        return {"ok": True, "emoji": {"id": copy.id, "keyword": copy.keyword, "file_name": copy.file_name, "category": copy.category, "aliases": copy.aliases or [], "url": _emoji_url(copy.file_name, "", copy.category or ""), "source_url": copy.source_url or "", "domain": copy.domain or ""}}


@emoji_router.delete("/emojis/{emoji_id}")
def api_delete_emoji(request: Request, emoji_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        emoji = s.query(CustomEmoji).get(emoji_id)
        if not emoji:
            raise HTTPException(status_code=404, detail="Emoji not found")
        _del_sub = "remote" if emoji.domain or emoji.category == "remote" else "local"
        try:
            get_storage().delete(f"emojis/{_del_sub}/{emoji.file_name}")
        except Exception:
            pass
        if not S3_ENABLED:
            file_path = os.path.join(EMOJI_DIR, _del_sub, emoji.file_name)
            if os.path.isfile(file_path):
                os.remove(file_path)
        s.delete(emoji)
        s.commit()
        _refresh_emoji_cache_forcibly(s)
    return {"ok": True}
