"""Miscellaneous endpoints — emoji, link-preview, server-info, PWA, log, push, sessions extracted from _core.py."""
import os
import re
import base64
import json
import io
import logging
import httpx
import html
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_public_key, Encoding, PublicFormat
from fastapi import APIRouter, Request, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse, Response, FileResponse
from PIL import Image
from sqlalchemy import desc, or_
from sqlalchemy.orm import joinedload

from app.models import User, CustomEmoji, ServerSetting, PushSubscription, LoginSession, Announcement, AnnouncementRead
from app.config.settings import BASE_URL, S3_ENABLED, SESSION_EXPIRE_DAYS
from app.core.push import _get_vapid_key
from app.db.database import get_session
from app.routes.auth import require_auth, require_active_auth, get_session_key_from_cookie
from app.utils.datetime import _fmt_dt, KST
from app.utils.emoji import EMOJI_DIR, _refresh_emoji_cache_forcibly, _emoji_url
from app.utils.log import log_admin_action
from app.utils.storage import LocalStorage, get_storage

logger = logging.getLogger("writ.api.misc")

misc_router = APIRouter()


# ── Emoji API ──

@misc_router.get("/emojis")
def api_list_emojis(limit: int = Query(30), offset: int = Query(0), q: str = Query(""), category: str = Query("")):
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


@misc_router.post("/emojis")
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

    ct_to_ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
    ext = ct_to_ext.get(image.content_type, "png")
    file_name = f"{uuid4().hex}.{ext}"
    local_dir = os.path.join(EMOJI_DIR, "local")
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


@misc_router.patch("/emojis/{emoji_id}")
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


@misc_router.post("/emojis/{emoji_id}/copy")
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
            _dst_local = os.path.join(EMOJI_DIR, "local", _new_fname)
            os.makedirs(os.path.dirname(_dst_local), exist_ok=True)
            with open(_dst_local, "wb") as f:
                f.write(_data)
            try:
                _storage.save(f"emojis/local/{_new_fname}", _data, f"image/{_ext}")
            except Exception:
                pass

        copy = CustomEmoji(keyword=new_kw, file_name=_new_fname, category="기본", aliases=src.aliases or [])
        s.add(copy)
        s.commit()
        _refresh_emoji_cache_forcibly(s)
        return {"ok": True, "emoji": {"id": copy.id, "keyword": copy.keyword, "file_name": copy.file_name, "category": copy.category, "aliases": copy.aliases or [], "url": _emoji_url(copy.file_name, "", copy.category or ""), "source_url": copy.source_url or "", "domain": copy.domain or ""}}


@misc_router.delete("/emojis/{emoji_id}")
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
        file_path = os.path.join(EMOJI_DIR, _del_sub, emoji.file_name)
        if os.path.isfile(file_path):
            os.remove(file_path)
        s.delete(emoji)
        s.commit()
        _refresh_emoji_cache_forcibly(s)
    return {"ok": True}


# ── Link Preview ──

@misc_router.post("/link-preview")
def api_link_preview(url: str = Form(...)):
    parsed = urlparse(url)
    domain = parsed.netloc
    result = {"url": url, "title": domain, "description": "", "image": ""}
    try:
        resp = httpx.get(url, headers={"User-Agent": "WRIT/1.0"}, timeout=10, follow_redirects=True)
        if resp.status_code == 200:
            html_text = resp.text
            def _og(n):
                m = re.search(f'<meta[^>]+property="og:{n}"[^>]+content="([^"]*)"', html_text, re.I)
                if not m:
                    m = re.search(f'<meta[^>]+content="([^"]*)"[^>]+property="og:{n}"', html_text, re.I)
                return m.group(1) if m else ""
            og_title = _og("title") or re.search(r'<title>([^<]*)</title>', html_text, re.I)
            result["title"] = html.unescape((_og("title") or (og_title.group(1) if og_title else domain)))[:200]
            result["description"] = html.unescape(_og("description") or "")[:400]
            result["image"] = _og("image") or ""
            if result["image"] and result["image"].startswith("/"):
                result["image"] = f"{parsed.scheme}://{parsed.netloc}{result['image']}"
    except Exception:
        pass
    return result


# ── Server Info ──

def _resolve_admin_users(s, admin_ids_str: str):
    if not admin_ids_str:
        admin_ids_str = "owner"
    handles = [h.strip().lstrip("@") for h in admin_ids_str.split(",") if h.strip()]
    if not handles:
        return []
    return s.query(User).filter(User.username.in_(handles)).all()


@misc_router.get("/server-info")
def api_server_info():
    with get_session() as s:
        settings = ServerSetting.get(s)
        admins = _resolve_admin_users(s, settings.admin_ids or "")
        admin_email = settings.admin_email or (admins[0].email if admins else "")
        return {
            "name": settings.server_name or "WRIT",
            "description": getattr(settings, 'server_description', '') or '',
            "admins": [
                {"username": a.username, "email": admin_email or ""}
                for a in admins
            ],
            "logo": settings.logo,
            "favicon": settings.favicon,
            "app_icon": settings.app_icon,
            "enable_reactions": settings.enable_reactions is not False,
        }


# ── PWA Helpers ──

def _read_storage_file(url: str) -> bytes:
    storage = get_storage()
    if isinstance(storage, LocalStorage):
        key = storage._extract_path(url)
        if key and os.path.isfile(key):
            with open(key, "rb") as f:
                return f.read()
    try:
        if not url.startswith("http"):
            url = f"{BASE_URL}{url}"
        resp = httpx.get(url, timeout=10)
        if resp.is_success:
            return resp.content
    except Exception as e:
        logger.warning("Failed to read file via HTTP %s: %s", url, e)
    raise FileNotFoundError(url)


def _save_pwa_icons(source_url: str):
    if not source_url:
        return
    try:
        data = _read_storage_file(source_url)
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGBA")
        storage = get_storage()
        for size in (192, 512):
            resized = img.resize((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            buf.seek(0)
            storage.save(f"pwa/icon-{size}.png", buf.getvalue(), "image/png")
    except Exception as e:
        logger.warning("Failed to save PWA icons: %s", e)


def _save_favicon(source_url: str):
    if not source_url:
        return
    try:
        data = _read_storage_file(source_url)
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGBA")
        resized = img.resize((32, 32), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        buf.seek(0)
        storage = get_storage()
        storage.save("pwa/favicon.png", buf.getvalue(), "image/png")
    except Exception as e:
        logger.warning("Failed to save favicon: %s", e)


def _delete_favicon():
    try:
        get_storage().delete("pwa/favicon.png")
    except Exception:
        pass


def _delete_pwa_icons():
    storage = get_storage()
    for size in (192, 512):
        try:
            storage.delete(f"pwa/icon-{size}.png")
        except Exception:
            pass


# ── PWA Routes ──

@misc_router.get("/pwa/manifest")
def api_pwa_manifest():
    with get_session() as s:
        settings = ServerSetting.get(s)
        name = settings.server_name or "WRIT"
        app_icon = settings.app_icon or ""
    icons = []
    for size in (192, 512):
        if app_icon:
            icons.append({"src": f"/api/pwa/icon/{size}", "sizes": f"{size}x{size}", "type": "image/png"})
        else:
            icons.append({"src": f"/icons/icon-{size}.png", "sizes": f"{size}x{size}", "type": "image/png"})
    return {
        "name": name,
        "short_name": name,
        "description": "작가를 위한 소셜 네트워크",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#689f38",
        "theme_color": "#689f38",
        "orientation": "portrait",
        "categories": ["social", "books", "writing"],
        "icons": icons,
    }


@misc_router.api_route("/pwa/favicon", methods=["GET", "HEAD"])
def api_pwa_favicon(request: Request):
    storage = get_storage()
    try:
        data = storage.get("pwa/favicon.png")
        if data:
            logger.info("[favicon] serving custom favicon (%d bytes)", len(data))
            if request.method == "HEAD":
                return Response(headers={"Cache-Control": "no-cache, max-age=0", "Vary": "Accept-Encoding"})
            return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-cache, max-age=0", "Vary": "Accept-Encoding"})
    except Exception as e:
        logger.info("[favicon] no custom favicon: %s", e)
    for path in [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "static", "favicon.ico"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "web", "public", "favicon.ico"),
    ]:
        if os.path.exists(path):
            if request.method == "HEAD":
                return Response(headers={"Cache-Control": "no-cache, max-age=0"})
            return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache, max-age=0"})
    return JSONResponse({"error": "Not found"}, status_code=404)


@misc_router.get("/pwa/icon/{size}")
def api_pwa_icon(size: int):
    storage = get_storage()
    try:
        data = storage.get(f"pwa/icon-{size}.png")
        if data:
            return Response(content=data, media_type="image/png")
    except Exception:
        pass
    default_path = os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "icons", f"icon-{size}.png")
    if os.path.exists(default_path):
        return FileResponse(default_path, media_type="image/png")
    return JSONResponse({"error": "Not found"}, status_code=404)


# ── Client Log ──

@misc_router.post("/log")
def api_client_log(request: Request):
    try:
        data = request.json()
        action = data.get("action", "client_event")
        details = data.get("details", "")
        ip = request.client.host if request.client else ""
        user = None
        try:
            user = require_auth(request)
        except HTTPException:
            pass
        log_admin_action(
            user_id=user.id if user else None,
            username=user.username if user else "anonymous",
            action=action,
            details=details,
            ip_address=ip,
        )
        return {"ok": True}
    except Exception as e:
        logger.exception("Client log error")
        return JSONResponse({"ok": False, "error": "Failed to save log"}, status_code=400)


# ── Web Push ──

@misc_router.get("/push/vapid-public-key")
def get_vapid_public_key():
    keys = _get_vapid_key()
    if not keys:
        raise HTTPException(500, "Web Push configuration error")
    key = keys["publicKey"]
    if key.startswith("-----"):
        try:
            pub = load_pem_public_key(key.encode())
            if isinstance(pub, ec.EllipticCurvePublicKey):
                raw = pub.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
                key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        except Exception:
            raise HTTPException(500, "Web Push configuration error")
    return {"publicKey": key}


@misc_router.post("/push/subscribe")
def subscribe_push(request: Request, endpoint: str = Form(...), p256dh: str = Form(...), auth: str = Form(...), device_name: str = Form("")):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(PushSubscription).filter_by(user_id=user.id, endpoint=endpoint).first()
        if existing:
            existing.p256dh = p256dh
            existing.auth = auth
            if device_name:
                existing.device_name = device_name
        else:
            s.add(PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth, device_name=device_name))
        s.commit()
    return {"ok": True}


@misc_router.post("/push/unsubscribe")
def unsubscribe_push(request: Request, endpoint: str = Form(...)):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(PushSubscription).filter_by(user_id=user.id, endpoint=endpoint).delete()
        s.commit()
    return {"ok": True}


@misc_router.get("/push/subscriptions")
def push_subscriptions(request: Request):
    user = require_active_auth(request)
    with get_session() as s:
        subs = s.query(PushSubscription).filter_by(user_id=user.id).all()
    return {"subscriptions": [{"id": sub.id, "device_name": sub.device_name, "created_at": sub.created_at.isoformat() if sub.created_at else ""} for sub in subs]}


@misc_router.post("/push/subscriptions/{sub_id}/delete")
def delete_push_subscription(request: Request, sub_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        sub = s.query(PushSubscription).filter_by(id=sub_id, user_id=user.id).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        s.delete(sub)
        s.commit()
    return {"ok": True}


@misc_router.get("/push/status")
def push_status(request: Request):
    user = require_active_auth(request)
    with get_session() as s:
        count = s.query(PushSubscription).filter_by(user_id=user.id).count()
    return {"subscribed": count > 0}


# ── Login session management ──

_UA_BROWSER = {
    "chrome": ("Chrome", re.compile(r"Chrome/(\d+)")),
    "edge": ("Edge", re.compile(r"Edg/(\d+)")),
    "firefox": ("Firefox", re.compile(r"Firefox/(\d+)")),
    "safari": ("Safari", re.compile(r"Version/(\d+).*Safari")),
    "opera": ("Opera", re.compile(r"(?:OPR|Opera)/(\d+)")),
}


def _parse_device_name(ua: str) -> str:
    if not ua:
        return "알 수 없는 기기"
    for key, (name, pattern) in _UA_BROWSER.items():
        m = pattern.search(ua)
        if m:
            return f"{name} {m.group(1)}"
    if "Mobile" in ua or "Android" in ua:
        return "모바일 브라우저"
    return "알 수 없는 브라우저"


@misc_router.get("/sessions")
def list_sessions(request: Request):
    user = require_active_auth(request)
    current_key = get_session_key_from_cookie(request)
    with get_session() as s:
        cutoff = datetime.now(timezone.utc) - timedelta(days=SESSION_EXPIRE_DAYS)
        s.query(LoginSession).filter(LoginSession.user_id == user.id, LoginSession.created_at < cutoff).delete(synchronize_session=False)
        s.commit()
        sessions = s.query(LoginSession).filter_by(user_id=user.id).order_by(LoginSession.last_active.desc()).limit(50).all()
        result = []
        for ls in sessions:
            result.append({
                "id": ls.id,
                "device_name": _parse_device_name(ls.user_agent),
                "ip_address": ls.ip_address,
                "is_current": ls.session_key == current_key,
                "last_active": ls.last_active.isoformat() if ls.last_active else "",
                "created_at": ls.created_at.isoformat() if ls.created_at else "",
            })
    return {"sessions": result}


@misc_router.post("/sessions/{session_id}/delete")
def delete_session(request: Request, session_id: int):
    user = require_active_auth(request)
    current_key = get_session_key_from_cookie(request)
    with get_session() as s:
        ls = s.query(LoginSession).filter_by(id=session_id, user_id=user.id).first()
        if not ls:
            raise HTTPException(status_code=404, detail="Session not found")
        if ls.session_key == current_key:
            raise HTTPException(status_code=400, detail="현재 사용 중인 기기는 해제할 수 없습니다.")
        s.delete(ls)
        s.commit()
    return {"ok": True}


# ── Announcements ──

def _parse_dt_field(value: str):
    """Parse a datetime-local style string (KST) into a UTC-aware datetime. Empty -> None."""
    if not value or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(timezone.utc)


def _is_announcement_active(a: Announcement, now_dt=None) -> bool:
    now_dt = now_dt or datetime.now(timezone.utc)
    def _aware(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    starts = _aware(a.starts_at)
    ends = _aware(a.ends_at)
    if starts and starts > now_dt:
        return False
    if ends and ends < now_dt:
        return False
    return True


def _announcement_json(a: Announcement):
    return {
        "id": a.id,
        "title": a.title,
        "content": a.content,
        "starts_at": _fmt_dt(a.starts_at),
        "ends_at": _fmt_dt(a.ends_at),
        "created_by": a.created_by.username if a.created_by else "",
        "created_at": _fmt_dt(a.created_at),
        "updated_at": _fmt_dt(a.updated_at),
    }


def _get_announcement_read(s, announcement_id: int, user_id: int) -> AnnouncementRead | None:
    return s.query(AnnouncementRead).filter_by(announcement_id=announcement_id, user_id=user_id).first()


def _user_announcement_json(s, a: Announcement, user_id: int):
    read = _get_announcement_read(s, a.id, user_id)
    return dict(
        _announcement_json(a),
        active=_is_announcement_active(a),
        is_read=bool(read and read.is_read),
        notified=bool(read and read.notified_at),
    )


@misc_router.get("/announcements")
def api_list_announcements(request: Request):
    user = require_auth(request)
    with get_session() as s:
        items = s.query(Announcement).options(joinedload(Announcement.created_by)).order_by(desc(Announcement.created_at)).all()
        return {
            "announcements": [
                _user_announcement_json(s, a, user.id)
                for a in items
                if _is_announcement_active(a)
            ]
        }


@misc_router.get("/announcements/status")
def api_announcements_status(request: Request):
    user = require_auth(request)
    with get_session() as s:
        items = s.query(Announcement).order_by(desc(Announcement.created_at)).all()
        now_dt = datetime.now(timezone.utc)
        active = [a for a in items if _is_announcement_active(a, now_dt)]
        unread_count = 0
        popups = []
        for a in active:
            read = _get_announcement_read(s, a.id, user.id)
            if not (read and read.is_read):
                unread_count += 1
            if read is None or not read.notified_at:
                popups.append({"id": a.id, "title": a.title})
        return {
            "has_active": bool(active),
            "unread_count": unread_count,
            "popups": popups,
        }


@misc_router.get("/announcements/{announcement_id}")
def api_get_announcement(request: Request, announcement_id: int):
    user = require_auth(request)
    with get_session() as s:
        a = s.query(Announcement).options(joinedload(Announcement.created_by)).get(announcement_id)
        if not a:
            raise HTTPException(status_code=404, detail="Announcement not found")
        return _user_announcement_json(s, a, user.id)


@misc_router.post("/announcements/{announcement_id}/read")
def api_announcement_read(request: Request, announcement_id: int):
    user = require_auth(request)
    with get_session() as s:
        a = s.query(Announcement).get(announcement_id)
        if not a:
            raise HTTPException(status_code=404, detail="Announcement not found")
        read = _get_announcement_read(s, a.id, user.id)
        if read is None:
            read = AnnouncementRead(announcement_id=a.id, user_id=user.id)
            s.add(read)
        read.is_read = True
        read.read_at = datetime.now(timezone.utc)
        if not read.notified_at:
            read.notified_at = read.read_at
        s.commit()
    return {"ok": True}


@misc_router.post("/announcements/{announcement_id}/notified")
def api_announcement_notified(request: Request, announcement_id: int):
    user = require_auth(request)
    with get_session() as s:
        a = s.query(Announcement).get(announcement_id)
        if not a:
            raise HTTPException(status_code=404, detail="Announcement not found")
        read = _get_announcement_read(s, a.id, user.id)
        if read is None:
            read = AnnouncementRead(announcement_id=a.id, user_id=user.id)
            s.add(read)
        if not read.notified_at:
            read.notified_at = datetime.now(timezone.utc)
        s.commit()
    return {"ok": True}
