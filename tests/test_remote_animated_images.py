import io

import pytest
from PIL import Image

from app.core.activitypub import _media


class _Response:
    def __init__(self, content: bytes, content_type: str):
        self.content = content
        self.status_code = 200
        self.headers = {"Content-Type": content_type}


class _FakeStorage:
    def __init__(self):
        self.saved: dict[str, tuple[bytes, str]] = {}

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.saved[key] = (data, content_type)
        return f"/uploads/{key}"

    def delete(self, url_or_key: str) -> bool:
        return True


def _animated_bytes(fmt: str) -> bytes:
    frames = [Image.new("RGB", (12, 12), color) for color in ((255, 0, 0), (0, 255, 0))]
    out = io.BytesIO()
    frames[0].save(
        out,
        format=fmt,
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return out.getvalue()


def _assert_animated(data: bytes, fmt: str, frames: int = 2):
    with Image.open(io.BytesIO(data)) as img:
        assert img.format == fmt
        assert getattr(img, "n_frames", 1) == frames
        assert getattr(img, "is_animated", False)


def test_cache_remote_media_preserves_animated_webp(monkeypatch):
    original = _animated_bytes("WEBP")
    storage = _FakeStorage()
    monkeypatch.setattr(_media, "safe_fetch", lambda *a, **k: _Response(original, "image/webp"))
    monkeypatch.setattr(_media, "get_storage", lambda: storage)

    url = _media._cache_remote_media("https://remote.example/animated.webp")

    assert url.startswith("/uploads/media/remote/")
    assert url.endswith(".webp")
    key = url.removeprefix("/uploads/")
    saved, content_type = storage.saved[key]
    assert content_type == "image/webp"
    assert saved == original
    _assert_animated(saved, "WEBP")


def test_cache_remote_media_keeps_all_gif_frames(monkeypatch):
    original = _animated_bytes("GIF")
    storage = _FakeStorage()
    monkeypatch.setattr(_media, "safe_fetch", lambda *a, **k: _Response(original, "image/gif"))
    monkeypatch.setattr(_media, "get_storage", lambda: storage)

    url = _media._cache_remote_media("https://remote.example/animated.gif")

    assert url.endswith(".webp")
    saved, _ = storage.saved[url.removeprefix("/uploads/")]
    _assert_animated(saved, "WEBP")


@pytest.mark.parametrize("prefix", ["avatars", "headers"])
def test_save_remote_image_preserves_animated_webp(monkeypatch, prefix):
    original = _animated_bytes("WEBP")
    storage = _FakeStorage()
    monkeypatch.setattr(_media, "validated_get", lambda *a, **k: _Response(original, "image/webp"))
    monkeypatch.setattr(_media, "get_storage", lambda: storage)

    url = _media._save_remote_image("https://remote.example/animated.webp", prefix, "alice")

    assert url.startswith(f"/uploads/{prefix}/remote/")
    assert url.endswith(".webp")
    saved, content_type = storage.saved[url.removeprefix("/uploads/")]
    assert content_type == "image/webp"
    assert saved == original
    _assert_animated(saved, "WEBP")


def test_save_remote_image_static_webp_still_converted(monkeypatch):
    static = io.BytesIO()
    Image.new("RGBA", (20, 12), (0, 0, 255, 128)).save(static, format="WEBP")
    storage = _FakeStorage()
    monkeypatch.setattr(_media, "validated_get", lambda *a, **k: _Response(static.getvalue(), "image/webp"))
    monkeypatch.setattr(_media, "get_storage", lambda: storage)

    url = _media._save_remote_image("https://remote.example/static.webp", "avatars", "alice")

    saved, _ = storage.saved[url.removeprefix("/uploads/")]
    with Image.open(io.BytesIO(saved)) as img:
        assert img.size == (12, 12)  # avatar cropped to square
        assert getattr(img, "n_frames", 1) == 1
