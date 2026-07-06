from uuid import uuid4
from utils.storage import get_storage

def _save_avatar(image_url, user_id):
    if not image_url:
        return ""
    import urllib.request
    ext = image_url.rsplit(".", 1)[-1].lower() if "." in image_url else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"
    filename = f"u{user_id}_{uuid4().hex[:8]}.{ext}"
    key = f"avatars/local/{filename}"
    try:
        resp = urllib.request.urlopen(image_url)
        data = resp.read()
        storage = get_storage()
        ct = f"image/{ext}"
        return storage.save(key, data, ct)
    except Exception:
        return ""
