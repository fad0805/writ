"""File upload validation helpers and constants."""
import os

from fastapi import HTTPException, UploadFile

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogg", ".mov"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg"}
ALLOWED_UPLOAD_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS | ALLOWED_AUDIO_EXTENSIONS
MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_AVATAR_SIZE = 5 * 1024 * 1024
MAX_VIDEO_SIZE = 26214400
MAX_AUDIO_SIZE = 20 * 1024 * 1024
IMAGE_MIME_PREFIXES = ("image/jpeg", "image/png", "image/gif", "image/webp", "image/ico")
VIDEO_MIME_TYPES = {"video/mp4", "video/webm", "video/ogg", "video/quicktime"}
AUDIO_MIME_TYPES = {"audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/aac", "audio/wav", "audio/x-wav", "audio/flac", "audio/ogg", "audio/x-flac"}


def _validate_upload(file: UploadFile, *, allow_video: bool = True, allow_audio: bool = False, max_size: int = MAX_IMAGE_SIZE, label: str = "file"):
    ext = os.path.splitext(file.filename or "file")[1].lower() if file.filename else ""
    is_video = ext in ALLOWED_VIDEO_EXTENSIONS
    is_image = ext in ALLOWED_IMAGE_EXTENSIONS
    is_audio = ext in ALLOWED_AUDIO_EXTENSIONS
    if not is_image and not (is_video and allow_video) and not (is_audio and allow_audio):
        raise HTTPException(status_code=400, detail=f"{label}: 지원하지 않는 파일 형식입니다")
    ct = (file.content_type or "").lower()
    if is_image and not any(ct.startswith(p) for p in IMAGE_MIME_PREFIXES):
        raise HTTPException(status_code=400, detail=f"{label}: 이미지 MIME 타입이 올바르지 않습니다")
    if is_video and ct not in VIDEO_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"{label}: 비디오 MIME 타입이 올바르지 않습니다")
    if is_audio and not any(ct.startswith(p) for p in AUDIO_MIME_TYPES) and ct not in AUDIO_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"{label}: 오디오 MIME 타입이 올바르지 않습니다")
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if is_video and size > MAX_VIDEO_SIZE:
        raise HTTPException(status_code=400, detail=f"{label}: 비디오 파일이 너무 큽니다 (최대 25MB)")
    if is_audio and size > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=400, detail=f"{label}: 오디오 파일이 너무 큽니다 (최대 20MB)")
    if is_image and size > max_size:
        raise HTTPException(status_code=400, detail=f"{label}: 이미지 파일이 너무 큽니다 (최대 {max_size // (1024*1024)}MB)")
    return ext, is_image, is_video, is_audio
