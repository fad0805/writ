import os, urllib.request
from uuid import uuid4
from config import AVATAR_STORAGE_PATH, AVATAR_URL_PREFIX

AVATAR_DIR = AVATAR_STORAGE_PATH

def _save_avatar(image_url, user_id):
    if not image_url:
        return ""
    os.makedirs(AVATAR_DIR, exist_ok=True)
    ext = image_url.rsplit(".", 1)[-1].lower() if "." in image_url else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"
    filename = f"u{user_id}_{uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(AVATAR_DIR, filename)
    try:
        urllib.request.urlretrieve(image_url, filepath)
        return f"{AVATAR_URL_PREFIX}/{filename}"
    except Exception:
        return ""
