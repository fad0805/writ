import httpx
from uuid import uuid4
from app.utils.storage import get_storage


def _save_avatar(image_url, user_id):
    if not image_url:
        return ""
    try:
        resp = httpx.get(image_url, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        from PIL import Image, ImageOps
        import io
        img = Image.open(io.BytesIO(resp.content))
        img = ImageOps.exif_transpose(img)
        sz = min(img.size)
        img = img.crop(((img.width - sz) // 2, (img.height - sz) // 2, (img.width + sz) // 2, (img.height + sz) // 2))
        img = img.resize((400, 400), Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=100)
        storage = get_storage()
        key = f"avatars/local/u{user_id}_{uuid4().hex[:8]}.webp"
        return storage.save(key, out.getvalue(), "image/webp")
    except Exception:
        return ""
