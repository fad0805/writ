import io
import logging
import os
import re
import uuid
from urllib.parse import urlparse

from PIL import Image

from app.utils.image import guard_image

guard_image()

import contextlib

from app.config.settings import S3_ENABLED
from app.db.database import get_session
from app.models import CustomEmoji
from app.utils.emoji import EMOJI_DIR, _refresh_emoji_cache_forcibly
from app.utils.http import WRIT_USER_AGENT, validate_url, validated_get
from app.utils.storage import get_storage

logger = logging.getLogger("writ.activitypub")


def _background_import_emoji(url: str, keyword: str, domain: str):
    """Download and save a remote emoji in the background. GIF/PNG preserved, others converted to WebP."""
    try:
        _resp = validated_get(url, headers={"User-Agent": WRIT_USER_AGENT}, timeout=15)
        if _resp is None or _resp.status_code != 200:
            return
        _ct = _resp.headers.get("content-type", "")
        _ext_from_url = url.rsplit(".", 1)[-1].lower() if "." in url.split("?")[0] else ""
        if "gif" in _ct or _ext_from_url == "gif":
            _ext, _ct_save = "gif", "image/gif"
        elif "png" in _ct or _ext_from_url == "png":
            _ext, _ct_save = "png", "image/png"
        else:
            _img = Image.open(io.BytesIO(_resp.content))
            _img = _img.convert("RGBA") if _img.mode in ("RGBA", "P") else _img.convert("RGB")
            _out = io.BytesIO()
            _img.save(_out, format="WEBP", quality=85)
            _ext, _ct_save = "webp", "image/webp"
            _content = _out.getvalue()
        if _ext in ("gif", "png"):
            _content = _resp.content
        _fname = f"{keyword}.{_ext}"
        get_storage().save(f"emojis/remote/{_fname}", _content, _ct_save)
        with get_session() as _es:
            _existing = _es.query(CustomEmoji).filter_by(keyword=keyword).first()
            if not _existing:
                _es.add(CustomEmoji(keyword=keyword, file_name=_fname, category="remote", domain=domain))
                _es.commit()
                _refresh_emoji_cache_forcibly(_es)
    except Exception as e:
        logger.error("Background emoji import failed %s: %s", keyword, e, exc_info=True)


def _process_emoji_tags(tags: list, session):
    """Parse Emoji tags from an ActivityPub object, download and save custom emojis safely."""
    if not tags or not isinstance(tags, list):
        return
    _storage = get_storage()
    if not S3_ENABLED:
        with contextlib.suppress(Exception):
            os.makedirs(EMOJI_DIR, exist_ok=True)
    for tag in tags:
        if not isinstance(tag, dict) or tag.get("type") != "Emoji":
            continue
        name = tag.get("name", "")
        if not name.startswith(":") or not name.endswith(":"):
            continue
        keyword = name[1:-1].strip().lower().replace(" ", "_")
        if not keyword or not re.match(r'^[a-z0-9_]+$', keyword):
            continue
        icon = tag.get("icon", {})
        if isinstance(icon, list):
            icon = icon[0] if icon else {}
        img_url = ""
        if isinstance(icon, dict):
            img_url = icon.get("url", "") or icon.get("href", "")
        elif isinstance(icon, str):
            img_url = icon
        if not img_url or not img_url.startswith("http"):
            continue

        emoji_id = tag.get("id", "")
        domain = urlparse(emoji_id).netloc if emoji_id else ""

        existing = session.query(CustomEmoji).filter_by(keyword=keyword, domain=domain).first()
        if existing:
            continue

        if not validate_url(img_url):
            continue
        try:
            resp = validated_get(img_url, timeout=15)
            if resp.status_code != 200:
                continue
            ext = "png"
            ct = resp.headers.get("content-type", "")
            if "jpeg" in ct or "jpg" in ct:
                ext = "jpg"
            elif "webp" in ct:
                ext = "webp"
            elif "gif" in ct:
                ext = "gif"
            elif "png" in ct:
                ext = "png"
            else:
                ext = resp.url.path.rsplit(".", 1)[-1].lower() if "." in resp.url.path else "png"
                if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
                    ext = "png"
            if ext == "jpeg":
                ext = "jpg"

            tmp = Image.open(io.BytesIO(resp.content))
            w, h = tmp.size
            tmp.close()
            if h > 0 and w / h > 2.0:
                continue

            remote_dir = os.path.join(EMOJI_DIR, "remote")
            if not S3_ENABLED:
                with contextlib.suppress(Exception):
                    os.makedirs(remote_dir, exist_ok=True)

            if ext in ("gif", "png"):
                file_name = f"{uuid.uuid4().hex}.{ext}"
                file_path = os.path.join(remote_dir, file_name)
                data = resp.content
                content_type = "image/gif" if ext == "gif" else "image/png"
            else:
                file_name = f"{uuid.uuid4().hex}.webp"
                file_path = os.path.join(remote_dir, file_name)
                img = Image.open(io.BytesIO(resp.content))
                img = img.convert("RGBA") if img.mode in ("RGBA", "P") else img.convert("RGB")
                if img.width > 66 or img.height > 66:
                    img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="WEBP", quality=100)
                data = buf.getvalue()
                content_type = "image/webp"

            if not S3_ENABLED:
                try:
                    with open(file_path, "wb") as f:
                        f.write(data)
                except Exception:
                    pass
            with contextlib.suppress(Exception):
                _storage.save(f"emojis/remote/{file_name}", data, content_type)
            emoji = CustomEmoji(
                keyword=keyword,
                file_name=file_name,
                category="remote",
                aliases=[],
                source_url=img_url,
                domain=domain,
            )
            session.add(emoji)
        except Exception as e:
            logger.error("Failed to process remote emoji %s: %s", keyword, e, exc_info=True)
