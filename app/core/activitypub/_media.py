import io
import os
import uuid
import datetime
import logging
from urllib.parse import urlparse

from PIL import Image, ImageOps, ImageSequence

from app.utils.image import guard_image
guard_image()

from app.db.database import get_session
from app.models import RemoteMedia
from app.utils.storage import get_storage
from app.utils.http import validate_url, safe_fetch, validated_get, WRIT_USER_AGENT

logger = logging.getLogger("writ.activitypub")

_REMOTE_MEDIA_MAX_SIZE = 10 * 1024 * 1024
_REMOTE_MEDIA_EXPIRY_DAYS = 30


def _cache_remote_media(remote_url: str) -> str:
    if not validate_url(remote_url):
        return remote_url

    with get_session() as s:
        existing = s.query(RemoteMedia).filter_by(remote_url=remote_url).first()
        if existing and existing.expires_at and existing.expires_at > datetime.datetime.now(datetime.timezone.utc):
            return existing.local_url

    try:
        resp = safe_fetch(remote_url, max_size=_REMOTE_MEDIA_MAX_SIZE)
        if not resp:
            return remote_url
        data = resp.content
        clean_url = remote_url.split("?")[0].split("#")[0]
        orig_ext = clean_url.rsplit(".", 1)[-1].lower() if "." in clean_url else "bin"
        ext = orig_ext
        is_image = orig_ext in ("jpg", "jpeg", "png", "gif", "webp")

        if is_image and len(data) < _REMOTE_MEDIA_MAX_SIZE:
            is_apng = (orig_ext == "png" and b"acTL" in data)
            is_custom_emoji = "custom_emojis" in remote_url

            if is_apng or is_custom_emoji:
                logger.info("Preserving original animated/emoji media without processing: %s", remote_url)
            else:
                try:
                    img = Image.open(io.BytesIO(data))
                    img = ImageOps.exif_transpose(img)
                    is_animated = getattr(img, "is_animated", False) or (img.format == "GIF")
                    max_dim = 2048
                    out = io.BytesIO()

                    if is_animated:
                        frames = []
                        durations = []
                        for frame in ImageSequence.Iterator(img):
                            frames.append(frame.convert("RGBA"))
                            durations.append(frame.info.get("duration", 100))

                        if any(f.width > max_dim or f.height > max_dim for f in frames):
                            ratio = min(max_dim / max(f.width for f in frames), max_dim / max(f.height for f in frames))
                            frames = [f.resize((int(f.width * ratio), int(f.height * ratio)), Image.LANCZOS) for f in frames]
                        frames[0].save(out, format="WEBP", save_all=True, append_images=frames[1:], duration=durations, loop=0, quality=85)
                        data = out.getvalue()
                        ext = "webp"
                    else:
                        if img.width > max_dim or img.height > max_dim:
                            ratio = min(max_dim / img.width, max_dim / img.height)
                            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
                        save_format = "PNG" if orig_ext == "png" else "WEBP"
                        img.save(out, format=save_format, quality=85)
                        data = out.getvalue()
                        ext = save_format.lower()

                except Exception as img_err:
                    logger.error("Image processing failed, fallback to original bytes: %s", img_err, exc_info=True)
                    data = resp.content
                    ext = orig_ext

        name = f"remote_{uuid.uuid4().hex[:12]}.{ext}"
        key = f"media/remote/{name}"
        storage = get_storage()
        ct = f"image/{ext}" if is_image else "application/octet-stream"
        local_url = storage.save(key, data, ct)
        expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=_REMOTE_MEDIA_EXPIRY_DAYS)
        with get_session() as s:
            existing2 = s.query(RemoteMedia).filter_by(remote_url=remote_url).first()
            if existing2:
                return existing2.local_url
            s.add(RemoteMedia(remote_url=remote_url, local_url=local_url, size=len(data), expires_at=expires))
            s.commit()
        return local_url
    except Exception as e:
        logger.error("Failed to cache remote media %s: %s", remote_url, e, exc_info=True)
    return remote_url


def _save_remote_image(image_url: str, prefix: str, local_username: str, old_url: str = "") -> str:
    """Download remote image. Keep GIF/PNG as-is, convert others (like JPG) to WebP."""
    if not validate_url(image_url):
        return ""

    pure_path = urlparse(image_url).path.split('?')[0].split('#')[0]
    ext = pure_path.rsplit(".", 1)[-1].lower() if "." in pure_path else "webp"

    try:
        r = validated_get(image_url, headers={"User-Agent": WRIT_USER_AGENT}, timeout=15)
        if r.status_code != 200 or len(r.content) > 10 * 1024 * 1024:
            return image_url

        data = r.content
        storage = get_storage()
        content_type_header = r.headers.get("Content-Type", "").lower()
        new_url = None

        is_avatar = prefix == "avatars"
        raw_ext = ext
        if ext in ("gif", "png") or "gif" in content_type_header or "png" in content_type_header:
            if is_avatar and ext != "gif" and "gif" not in content_type_header:
                img = Image.open(io.BytesIO(data))
                img = ImageOps.exif_transpose(img)
                sz = min(img.size)
                img = img.crop(((img.width - sz) // 2, (img.height - sz) // 2, (img.width + sz) // 2, (img.height + sz) // 2))
                out = io.BytesIO()
                img.save(out, format="PNG", quality=85)
                filename = f"{uuid.uuid4().hex}.png"
                key = f"{prefix}/remote/{filename}"
                new_url = storage.save(key, out.getvalue(), "image/png")
            else:
                final_ext = "gif" if ("gif" in ext or "gif" in content_type_header) else "png"
                filename = f"{uuid.uuid4().hex}.{final_ext}"
                key = f"{prefix}/remote/{filename}"
                new_url = storage.save(key, data, f"image/{final_ext}")
        else:
            try:
                img = Image.open(io.BytesIO(data))
                img = ImageOps.exif_transpose(img)
                if is_avatar:
                    sz = min(img.size)
                    img = img.crop(((img.width - sz) // 2, (img.height - sz) // 2, (img.width + sz) // 2, (img.height + sz) // 2))
                is_animated = getattr(img, "is_animated", False)
                real_format = (img.format or "").lower()
                if is_animated or real_format in ("gif", "png"):
                    final_ext = real_format if real_format in ("gif", "png", "webp") else "webp"
                    filename = f"{uuid.uuid4().hex}.{final_ext}"
                    key = f"{prefix}/remote/{filename}"
                    new_url = storage.save(key, data, f"image/{final_ext}")
                else:
                    if img.mode in ("RGBA", "P"):
                        bg = Image.new("RGB", img.size, (255, 255, 255))
                        bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                        img = bg
                    out = io.BytesIO()
                    img.save(out, format="WEBP", quality=85)
                    filename = f"{uuid.uuid4().hex}.webp"
                    key = f"{prefix}/remote/{filename}"
                    new_url = storage.save(key, out.getvalue(), "image/webp")

            except Exception as img_err:
                logger.error("Pillow could not process image %s, saving raw data: %s", image_url, img_err, exc_info=True)
                filename = f"{uuid.uuid4().hex}.{ext}"
                key = f"{prefix}/remote/{filename}"
                new_url = storage.save(key, data, content_type_header or f"image/{ext}")

        if new_url and old_url:
            try:
                storage.delete(old_url)
            except Exception:
                pass

        return new_url if new_url else image_url

    except Exception as e:
        logger.error("Failed to save remote %s %s. Error: %s", prefix, image_url, e, exc_info=True)
    return image_url


def _save_remote_avatar(avatar_url: str, local_username: str, old_url: str = "") -> str:
    return _save_remote_image(avatar_url, "avatars", local_username, old_url)
