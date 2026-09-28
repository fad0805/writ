"""Server-info, link-preview, and client-log endpoints extracted from _misc.py."""
import contextlib
import html
import json
import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.auth import get_current_user, require_auth
from app.core.permissions import is_staff
from app.db.database import get_session
from app.models import ServerSetting, User
from app.utils.http import validate_url, validated_get
from app.utils.log import log_admin_action

logger = logging.getLogger("writ.api.meta")

meta_router = APIRouter()


# ── Link Preview ──

_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtube-nocookie.com", "www.youtube-nocookie.com",
    "youtu.be", "www.youtu.be",
}
_YOUTUBE_PATH_PREFIXES = ("embed", "live", "shorts", "v")
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _youtube_video_url(url: str) -> str:
    """YouTube/watch·youtu.be·shorts·live·embed URL → canonical watch URL. 없으면 빈 문자열."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        return ""
    parts = [p for p in parsed.path.split("/") if p]
    if host in ("youtu.be", "www.youtu.be"):
        video_id = parts[0] if parts else ""
    elif parts and parts[0] in _YOUTUBE_PATH_PREFIXES:
        video_id = parts[1] if len(parts) > 1 else ""
    else:
        try:
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        except ValueError:
            video_id = ""
    if not _VIDEO_ID_RE.match(video_id):
        return ""
    return f"https://www.youtube.com/watch?v={video_id}"


def _youtube_preview(url: str):
    """oEmbed로 제목·채널명·썸네일을 가져온다.

    watch 페이지는 1.3MB 넘고 OG 스캔의 1MB 상한(_meta.py의 max_size)에 걸려
    제목/썸네일을 못 얻는다. 채널명은 어차피 OG 태그에 없으니 oEmbed를 쓴다.
    """
    video_url = _youtube_video_url(url)
    if not video_url:
        return None
    oembed_url = "https://www.youtube.com/oembed?" + urlencode({"url": video_url, "format": "json"})
    resp = validated_get(oembed_url, timeout=10, max_size=256 * 1024)
    if not resp or resp.status_code != 200:
        return None
    try:
        data = json.loads(resp.text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    title = (data.get("title") or "").strip()
    if not title:
        return None
    video_id = video_url.rsplit("=", 1)[1]
    return {
        "url": video_url,
        "title": title[:200],
        "description": "",
        # oEmbed의 thumbnail_url은 4:3 레터박스(hqdefault)라 16:9로 바꿔 쓴다
        "image": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
        "site_name": (data.get("author_name") or "").strip()[:100],
        "kind": "video",
    }


@meta_router.post("/link-preview")
def api_link_preview(request: Request, url: str = Form(...)):
    require_auth(request)
    parsed = urlparse(url)
    domain = parsed.netloc
    result = {"url": url, "title": domain, "description": "", "image": ""}
    if not validate_url(url):
        return result
    yt = _youtube_preview(url)
    if yt:
        return yt
    try:
        resp = validated_get(url, timeout=10, max_size=1024 * 1024)
        if resp and resp.status_code == 200:
            html_text = resp.text
            def _og(n):
                m = re.search(f'<meta[^>]+property="og:{n}"[^>]+content="([^"]*)"', html_text, re.I)
                if not m:
                    m = re.search(f'<meta[^>]+content="([^"]*)"[^>]+property="og:{n}"', html_text, re.I)
                return m.group(1) if m else ""
            og_title = _og("title") or re.search(r'<title>([^<]*)</title>', html_text, re.I)
            result["title"] = html.unescape(_og("title") or (og_title.group(1) if og_title else domain))[:200]
            result["description"] = html.unescape(_og("description") or "")[:400]
            result["image"] = _og("image") or ""
            if result["image"] and result["image"].startswith("/"):
                result["image"] = f"{parsed.scheme}://{parsed.netloc}{result['image']}"
            if result["image"] and not validate_url(result["image"]):
                result["image"] = ""
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


@meta_router.get("/server-info")
def api_server_info(request: Request):
    user = get_current_user(request)
    is_admin = bool(user and is_staff(user))
    with get_session() as s:
        settings = ServerSetting.get(s)
        admins = _resolve_admin_users(s, settings.admin_ids or "")
        admin_email = settings.admin_email or (admins[0].email if admins else "")
        return {
            "name": settings.server_name or "WRIT",
            "description": getattr(settings, 'server_description', '') or '',
            "admins": [
                {"username": a.username, "email": (admin_email or a.email) if is_admin else ""}
                for a in admins
            ],
            "logo": settings.logo,
            "favicon": settings.favicon,
            "app_icon": settings.app_icon,
            "enable_reactions": settings.enable_reactions is not False,
        }


# ── Client Log ──

@meta_router.post("/log")
async def api_client_log(request: Request):
    try:
        data = await request.json()
        action = data.get("action", "client_event")
        details = data.get("details", "")
        ip = request.client.host if request.client else ""
        user = None
        with contextlib.suppress(HTTPException):
            user = require_auth(request)
        log_admin_action(
            user_id=user.id if user else None,
            username=user.username if user else "anonymous",
            action=action,
            details=details,
            ip_address=ip,
        )
        return {"ok": True}
    except Exception:
        logger.exception("Client log error")
        return JSONResponse({"ok": False, "error": "Failed to save log"}, status_code=400)
