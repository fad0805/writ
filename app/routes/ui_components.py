import httpx
from uuid import uuid4
from app.utils.storage import get_storage


def _save_avatar(image_url, user_id):
    if not image_url:
        return ""
    ext = image_url.rsplit(".", 1)[-1].lower() if "." in image_url else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"
    filename = f"u{user_id}_{uuid4().hex[:8]}.{ext}"
    key = f"avatars/local/{filename}"
    try:
        resp = httpx.get(image_url, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        storage = get_storage()
        ct = f"image/{ext}"
        return storage.save(key, resp.content, ct)
    except Exception:
        return ""
