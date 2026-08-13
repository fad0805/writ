"""PWA helpers and manifest/icon/favicon endpoints extracted from _misc.py."""
import os
import io
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, FileResponse
from PIL import Image

from app.utils.image import guard_image
guard_image()

from app.models import ServerSetting
from app.config.settings import BASE_URL
from app.db.database import get_session
from app.utils.http import validated_get
from app.utils.storage import LocalStorage, get_storage

logger = logging.getLogger("writ.api.pwa")

pwa_router = APIRouter()


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
        resp = validated_get(url, timeout=10, max_size=5*1024*1024)
        if resp is not None:
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

@pwa_router.get("/pwa/manifest")
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


@pwa_router.api_route("/pwa/favicon", methods=["GET", "HEAD"])
def api_pwa_favicon(request: Request):
    storage = get_storage()
    try:
        if storage.exists("pwa/favicon.png"):
            data = storage.get("pwa/favicon.png")
            if data:
                logger.info("[favicon] serving custom favicon (%d bytes)", len(data))
                if request.method == "HEAD":
                    return Response(headers={"Cache-Control": "no-cache, max-age=0", "Vary": "Accept-Encoding"})
                return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-cache, max-age=0", "Vary": "Accept-Encoding"})
    except Exception as e:
        logger.warning("[favicon] failed to load custom favicon: %s", e)
    for path in [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "static", "favicon.ico"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "web", "public", "favicon.ico"),
    ]:
        if os.path.exists(path):
            if request.method == "HEAD":
                return Response(headers={"Cache-Control": "no-cache, max-age=0"})
            return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache, max-age=0"})
    return JSONResponse({"error": "Not found"}, status_code=404)


@pwa_router.get("/pwa/icon/{size}")
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
