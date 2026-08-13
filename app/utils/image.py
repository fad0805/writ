"""Shared Pillow hardening: cap decoded image dimensions (decompression bombs)."""
from PIL import Image

# ~25MP 상한: 정상 아바타/커버/미디어(최대 2048px)로 충분하며,
# 작은 파일로 압축된 초고해상도(디컴프레션 폭탄) 이미지의 메모리 폭주를 차단한다.
Image.MAX_IMAGE_PIXELS = 25_000_000


def guard_image() -> None:
    """Ensure the pixel cap is applied. Idempotent — call at module import."""
    if Image.MAX_IMAGE_PIXELS != 25_000_000:
        Image.MAX_IMAGE_PIXELS = 25_000_000
