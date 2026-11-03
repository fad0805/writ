"""Account archive generation.

Builds a single, self-contained ZIP with:

- ``profile.json`` — profile information (never credentials/private keys)
- ``posts.json`` — authored posts and live boosts
- ``novels.json`` — authored series, episodes, and notices
- ``media/...`` — profile images, series covers, episode images/audio, post media
- ``manifest.json`` — media index and archive metadata
- ``README.txt`` — short explanation of the contents

The heavy work is intentionally kept in this module so both the synchronous
compatibility endpoint and the background job use exactly the same output.
"""
from __future__ import annotations

import json
import logging
import os
import re
import zipfile
from datetime import UTC, timedelta
from typing import BinaryIO
from urllib.parse import urlparse

from sqlalchemy import func

from app.config.settings import ARCHIVE_DIR, ARCHIVE_RETENTION_DAYS
from app.db.database import get_session
from app.models import ArchiveJob, Episode, Notification, Novel, Post, SeriesNotice, User
from app.utils.datetime import _fmt_dt, now
from app.utils.media_urls import rewrite_src_urls
from app.utils.storage import get_storage

logger = logging.getLogger("writ.archive")


def _posts_for_export(s, user_id: int):
    """Return (post, boost_pointer) pairs for a user's authored posts and boosts.

    A boost row is only a pointer. For backups we want the boosted original's
    content, but only while that original still exists and is not deleted.
    """
    rows = s.query(Post).filter_by(author_id=user_id, is_deleted=False).order_by(Post.created_at).all()
    result = []
    seen_ids = set()
    for row in rows:
        target = row
        pointer = None
        if row.boost_of_id:
            target = s.query(Post).filter_by(id=row.boost_of_id, is_deleted=False).first()
            if not target:
                continue
            pointer = row
        if target.id in seen_ids:
            continue
        seen_ids.add(target.id)
        result.append((target, pointer))
    return result


class _MediaCollector:
    """Fetch local media into the ZIP and rewrite URLs to archive-relative paths."""

    def __init__(self, zf: zipfile.ZipFile):
        self.zf = zf
        self.storage = get_storage()
        self.seen: dict[str, str] = {}
        self.items: list[dict] = []
        self.missing: list[dict] = []
        self._counter = 0

    def add(self, url: str, category: str = "misc") -> str | None:
        if not url or not isinstance(url, str):
            return None
        if url in self.seen:
            return self.seen[url]

        key = self.storage.key_from_url(url)
        if not key:
            self.missing.append({"url": url, "category": category, "reason": "not_local"})
            return None
        key = key.lstrip("/")
        if not key or ".." in key.split("/"):
            self.missing.append({"url": url, "category": category, "reason": "invalid_key"})
            return None

        try:
            data = self.storage.get(key)
        except Exception as exc:
            logger.warning("archive: failed to read media %s: %s", url, exc)
            self.missing.append({"url": url, "category": category, "reason": "unavailable"})
            return None

        self._counter += 1
        safe_category = re.sub(r"[^A-Za-z0-9_-]", "_", category) or "misc"
        base = os.path.basename(urlparse(url).path) or f"file_{self._counter}"
        base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:120]
        if not os.path.splitext(base)[1]:
            base += ".bin"
        archive_path = f"media/{safe_category}/{self._counter:04d}_{base}"

        self.zf.writestr(archive_path, data)
        self.seen[url] = archive_path
        self.items.append({
            "archive_path": archive_path,
            "original_url": url,
            "category": category,
            "size": len(data),
        })
        return archive_path


def _archive_attachments(attachments, collector: _MediaCollector):
    result = []
    for item in attachments or []:
        if isinstance(item, str):
            archive_path = collector.add(item, "posts")
            result.append({"url": archive_path or item, "original_url": item, "type": "image", "alt": ""})
            continue
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        url = entry.get("url") or ""
        archive_path = collector.add(url, "posts")
        if archive_path:
            entry["original_url"] = url
            entry["url"] = archive_path
        result.append(entry)
    return result


def _profile_json(user: User, collector: _MediaCollector) -> dict:
    profile = {
        "username": user.username,
        "display_name": user.display_name or "",
        "summary": user.summary or "",
        "email": user.email or "",
        "email_verified": bool(user.email_verified),
        "actor_url": user.actor_uri(),
        "profile_url": user.profile_url or "",
        "created_at": _fmt_dt(user.created_at),
        "updated_at": _fmt_dt(user.updated_at),
        "role": user.role,
        "is_admin": bool(user.is_admin),
        "is_locked": bool(user.is_locked),
        "is_bot": bool(user.is_bot),
        "is_sensitive": bool(user.is_sensitive),
        "follow_list_visibility": user.follow_list_visibility or "public",
        "default_visibility": user.default_visibility or "public",
        "episode_default_visibility": user.episode_default_visibility or "public",
        "show_badge": bool(user.show_badge),
        "enable_reactions": bool(user.enable_reactions),
        "post_lifetime": user.post_lifetime or 0,
        "post_lifetime_exceptions": user.post_lifetime_exceptions or [],
        "custom_fields": user.custom_fields or [],
        "profile_hashtags": user.profile_hashtags or [],
        "pinned_posts": user.pinned_posts or [],
        "pinned_series": user.pinned_series or [],
        "aliases": user.aliases or [],
        "moved_to": user.moved_to or "",
        "profile_image": user.profile_image or "",
        "header_image": user.header_image or "",
    }
    profile["profile_image_archive"] = collector.add(user.profile_image, "profile") or ""
    profile["header_image_archive"] = collector.add(user.header_image, "profile") or ""
    return profile


def _novels_json(s, user_id: int, collector: _MediaCollector) -> list[dict]:
    novels = s.query(Novel).filter_by(author_id=user_id).order_by(Novel.created_at).all()
    result = []
    for novel in novels:
        episodes = s.query(Episode).filter_by(novel_id=novel.id).order_by(Episode.episode_number).all()
        notices = s.query(SeriesNotice).filter_by(novel_id=novel.id).order_by(SeriesNotice.created_at).all()
        episodes_data = []
        for episode in episodes:
            original_images = episode.image_urls or []
            archived_images = [collector.add(image_url, "series") or image_url for image_url in original_images]
            audio_archive = collector.add(episode.audio_url, "series") or ""
            episodes_data.append({
                "uuid": episode.uuid,
                "episode_number": episode.episode_number,
                "title": episode.title,
                "content": rewrite_src_urls(
                    episode.content,
                    lambda url: collector.add(url, "series"),
                ),
                "summary": episode.summary or "",
                "comment": episode.comment or "",
                "is_published": episode.is_published,
                "view_mode": episode.view_mode,
                "comic_view_mode": episode.comic_view_mode,
                "reading_direction": episode.reading_direction,
                "page_mode": episode.page_mode,
                "views": episode.views or 0,
                "image_urls": archived_images,
                "image_urls_original": original_images,
                "audio_url": audio_archive or episode.audio_url or "",
                "audio_url_original": episode.audio_url or "",
                "created_at": _fmt_dt(episode.created_at),
                "updated_at": _fmt_dt(episode.updated_at),
            })
        result.append({
            "uuid": novel.uuid,
            "number": novel.number or "",
            "title": novel.title,
            "description": novel.description or "",
            "tags": novel.tags or "",
            "status": novel.status,
            "visibility": novel.visibility,
            "is_published": novel.is_published,
            "is_sensitive": novel.is_sensitive,
            "cover_image": novel.cover_image or "",
            "cover_image_archive": collector.add(novel.cover_image, "series") or "",
            "created_at": _fmt_dt(novel.created_at),
            "updated_at": _fmt_dt(novel.updated_at),
            "episodes": episodes_data,
            "notices": [
                {
                    "uuid": notice.uuid,
                    "title": notice.title,
                    "content": rewrite_src_urls(
                        notice.content,
                        lambda url: collector.add(url, "series"),
                    ),
                    "is_pinned": notice.is_pinned,
                    "created_at": _fmt_dt(notice.created_at),
                    "updated_at": _fmt_dt(notice.updated_at),
                }
                for notice in notices
            ],
        })
    return result


def _posts_json(s, user_id: int, collector: _MediaCollector) -> list[dict]:
    result = []
    for post, pointer in _posts_for_export(s, user_id):
        is_boost = pointer is not None
        result.append({
            "id": post.id,
            "uuid": post.uuid,
            "number": post.number or "",
            "type": "boost" if is_boost else "post",
            "boosted": is_boost,
            "boosted_at": _fmt_dt(pointer.created_at) if is_boost else None,
            "boost_of_author": post.author.username if is_boost else "",
            "boost_of_url": (post.ap_id or post.remote_url or "") if is_boost else "",
            "content": rewrite_src_urls(
                post.content,
                lambda url: collector.add(url, "posts"),
            ),
            "summary": post.summary or "",
            "visibility": post.visibility,
            "created_at": _fmt_dt(post.created_at),
            "edited_at": _fmt_dt(post.edited_at),
            "media_attachments": _archive_attachments(post.media_attachments, collector),
            "poll_data": post.poll_data,
            "is_sensitive": post.is_sensitive,
        })
    return result


def write_archive(user_id: int, dest: str | BinaryIO) -> None:
    """Write the complete account archive to ``dest`` (path or binary file)."""
    generated_at = _fmt_dt(now())
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        collector = _MediaCollector(zf)
        with get_session() as s:
            user = s.query(User).filter_by(id=user_id).first()
            if not user:
                raise ValueError("User not found")
            profile = _profile_json(user, collector)
            posts = _posts_json(s, user_id, collector)
            novels = _novels_json(s, user_id, collector)

        manifest = {
            "format": "writ-archive",
            "version": 2,
            "generated_at": generated_at,
            "username": profile["username"],
            "counts": {
                "posts": len(posts),
                "novels": len(novels),
                "episodes": sum(len(n["episodes"]) for n in novels),
                "media": len(collector.items),
            },
            "media": collector.items,
            "missing_media": collector.missing,
        }

        zf.writestr("profile.json", json.dumps(profile, ensure_ascii=False, indent=2))
        zf.writestr("posts.json", json.dumps(posts, ensure_ascii=False, indent=2))
        zf.writestr("novels.json", json.dumps(novels, ensure_ascii=False, indent=2))
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("README.txt", (
            "WRIT 계정 아카이브\n"
            "==================\n\n"
            f"생성 시각: {generated_at}\n"
            f"계정: @{profile['username']}\n\n"
            "profile.json  - 프로필 정보 (비밀번호/개인키는 포함되지 않습니다)\n"
            "posts.json    - 게시물 및 부스트\n"
            "novels.json   - 시리즈, 에피소드, 공지\n"
            "media/        - 프로필 사진, 시리즈 표지, 에피소드/게시물 미디어\n"
            "manifest.json - 파일 목록과 원본 URL\n"
        ))


def _archive_file_path(job_uuid: str) -> str:
    return os.path.join(ARCHIVE_DIR, f"{job_uuid}.zip")


def _create_archive_notification(user_id: int, job: ArchiveJob) -> None:
    status = job.status
    message = "아카이브가 준비되었습니다." if status == "completed" else "아카이브 생성에 실패했습니다."
    metadata = {
        "type": "archive",
        "status": status,
        "job_id": job.uuid,
        "message": message,
        "size_bytes": job.size_bytes or 0,
    }
    with get_session() as s:
        s.add(Notification(
            user_id=user_id,
            from_user_id=user_id,
            notification_type="archive",
            metadata_json=json.dumps(metadata, ensure_ascii=False),
        ))
        s.commit()


def run_archive_job(job_id: int) -> None:
    """Background worker: generate a ZIP and notify the owner when done."""
    with get_session() as s:
        job = s.query(ArchiveJob).filter_by(id=job_id).first()
        if not job or job.status != "pending":
            return
        job.status = "processing"
        s.commit()
        user_id = job.user_id
        job_uuid = job.uuid

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    final_path = _archive_file_path(job_uuid)
    temp_path = f"{final_path}.tmp"
    try:
        write_archive(user_id, temp_path)
        os.replace(temp_path, final_path)
        size = os.path.getsize(final_path)
        with get_session() as s:
            job = s.query(ArchiveJob).filter_by(id=job_id).first()
            if not job:
                return
            job.status = "completed"
            job.file_path = final_path
            job.size_bytes = size
            job.error = ""
            job.completed_at = now()
            s.commit()
            completed_job = job
        # Notification failures must not flip an already-completed archive to failed.
        try:
            _create_archive_notification(user_id, completed_job)
            _notify_archive_ready(user_id, completed_job)
        except Exception:
            logger.warning("archive: completion notification failed", exc_info=True)
    except Exception as exc:
        logger.exception("archive job %s failed", job_id)
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        with get_session() as s:
            job = s.query(ArchiveJob).filter_by(id=job_id).first()
            if job:
                job.status = "failed"
                job.error = str(exc)[:500]
                job.completed_at = now()
                s.commit()
                failed_job = job
            else:
                failed_job = None
        if failed_job is not None:
            try:
                _create_archive_notification(user_id, failed_job)
                _notify_archive_ready(user_id, failed_job)
            except Exception:
                logger.warning("archive: failure notification failed", exc_info=True)


def _notify_archive_ready(user_id: int, job: ArchiveJob) -> None:
    """Best-effort SSE + Web Push after the notification row is committed."""
    try:
        from app.core.push import send_push_to_user
        from app.core.timeline_stream import broadcast_refresh_notifs

        broadcast_refresh_notifs(user_id)
        send_push_to_user(user_id, "archive", metadata={
            "status": job.status,
            "job_id": job.uuid,
        })
    except Exception:
        logger.warning("archive: notification broadcast failed", exc_info=True)


def recover_interrupted_archive_jobs() -> int:
    """Mark jobs left pending/processing by a restart as failed.

    Without this a restart during generation would leave the user's only active
    job stuck forever, blocking new archive requests.
    """
    with get_session() as s:
        jobs = s.query(ArchiveJob).filter(ArchiveJob.status.in_(["pending", "processing"])).all()
        for job in jobs:
            job.status = "failed"
            job.error = "서버 재시작으로 아카이브 생성이 중단되었습니다."
            job.completed_at = now()
        s.commit()
    if jobs:
        logger.warning("Marked %d interrupted archive jobs as failed", len(jobs))
    return len(jobs)


def archive_job_json(job: ArchiveJob | None) -> dict | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "uuid": job.uuid,
        "status": job.status,
        "size_bytes": job.size_bytes or 0,
        "error": job.error or "",
        "created_at": _fmt_dt(job.created_at),
        "completed_at": _fmt_dt(job.completed_at),
        "download_url": f"/api/settings/archive-download/{job.uuid}" if job.status == "completed" else "",
    }


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def archive_next_available_at(user_id: int):
    """Return when the user may generate their next archive, or None.

    One archive per retention window (7 days by default): a successfully
    generated backup keeps the cooldown active until it is removed.
    """
    with get_session() as s:
        latest = s.query(ArchiveJob).filter(
            ArchiveJob.user_id == user_id,
            ArchiveJob.status == "completed",
        ).order_by(
            func.coalesce(ArchiveJob.completed_at, ArchiveJob.created_at).desc(),
        ).first()
        if not latest:
            return None
        finished = _aware(latest.completed_at or latest.created_at)
        if not finished:
            return None
        next_at = finished + timedelta(days=ARCHIVE_RETENTION_DAYS)
        return next_at if next_at > now() else None


def _cleanup_where(*conditions) -> int:
    cutoff = now() - timedelta(days=ARCHIVE_RETENTION_DAYS)
    with get_session() as s:
        stale = s.query(ArchiveJob).filter(
            ArchiveJob.status.in_(["completed", "failed"]),
            # 보관 기간은 생성 완료 시점부터 센다 (실패 작업은 완료 시각도 기록됨).
            func.coalesce(ArchiveJob.completed_at, ArchiveJob.created_at) < cutoff,
            *conditions,
        ).all()
        for job in stale:
            if job.file_path:
                try:
                    if os.path.isfile(job.file_path):
                        os.remove(job.file_path)
                except OSError:
                    logger.warning("archive: failed to remove %s", job.file_path, exc_info=True)
            s.delete(job)
        s.commit()
    return len(stale)


def cleanup_user_archives(user_id: int) -> None:
    """Remove this user's completed/failed jobs and files past retention."""
    _cleanup_where(ArchiveJob.user_id == user_id)


def delete_user_archives(user_id: int) -> None:
    """Remove every archive file and row for an account being deleted."""
    with get_session() as s:
        jobs = s.query(ArchiveJob).filter_by(user_id=user_id).all()
        for job in jobs:
            if job.file_path:
                try:
                    if os.path.isfile(job.file_path):
                        os.remove(job.file_path)
                except OSError:
                    logger.warning("archive: failed to remove %s", job.file_path, exc_info=True)
        s.query(ArchiveJob).filter_by(user_id=user_id).delete(synchronize_session=False)
        s.commit()


def cleanup_expired_archives() -> int:
    """Delete every archive past retention. Returns the number removed.

    Called from the daily media-cleanup worker so files disappear even if the
    owner never visits the download page again.
    """
    removed = _cleanup_where()
    if removed:
        logger.info("Cleaned %d expired account archives", removed)
    return removed
