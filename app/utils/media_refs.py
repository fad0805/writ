"""Reference tracking for locally stored media files.

Post/episode HTML can embed uploaded media directly, so attachments alone are
not enough when deciding whether a file is still in use. These helpers are
shared by the orphan-media cleanup worker and by delete endpoints that want to
reclaim files immediately.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from app.models import (
    Episode,
    EpisodeDraft,
    Novel,
    Post,
    PostEdit,
    RemoteMedia,
    SeriesNotice,
    User,
)
from app.utils.media_urls import iter_content_media_urls
from app.utils.storage import get_storage, media_key_candidates, resolve_media_key

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.utils.storage import StorageBackend

logger = logging.getLogger("writ.media_refs")


def collect_referenced_media_keys(s: Session, storage: StorageBackend) -> set[str]:
    """Return storage keys still referenced by live content.

    Deleted posts are deliberately excluded: their content and attachments must
    not keep files alive after deletion. Edit history of a live post is kept,
    because the UI can still show previous versions.
    """
    urls: set[str] = set()

    for (attachments,) in (
        s.query(Post.media_attachments)
        .filter(Post.media_attachments.isnot(None), Post.is_deleted.is_(False))
        .all()
    ):
        for item in attachments or []:
            if isinstance(item, dict) and item.get("url"):
                urls.add(item["url"])
            elif isinstance(item, str) and item:
                urls.add(item)

    for (local_url,) in s.query(RemoteMedia.local_url).all():
        if local_url:
            urls.add(local_url)

    for (images,) in s.query(Episode.image_urls).filter(Episode.image_urls.isnot(None)).all():
        for url in images or []:
            if isinstance(url, str) and url:
                urls.add(url)

    for (audio_url,) in s.query(Episode.audio_url).filter(Episode.audio_url != "").all():
        if audio_url:
            urls.add(audio_url)

    for (cover_image,) in s.query(Novel.cover_image).filter(Novel.cover_image != "").all():
        if cover_image:
            urls.add(cover_image)

    for (profile_image,) in s.query(User.profile_image).filter(User.profile_image != "").all():
        if profile_image:
            urls.add(profile_image)
    for (header_image,) in s.query(User.header_image).filter(User.header_image != "").all():
        if header_image:
            urls.add(header_image)

    content_sources = (
        s.query(Post.content).filter(Post.is_deleted.is_(False)).all(),
        s.query(PostEdit.content).join(Post, PostEdit.post_id == Post.id).filter(Post.is_deleted.is_(False)).all(),
        s.query(Episode.content).filter(Episode.content.isnot(None)).all(),
        s.query(SeriesNotice.content).filter(SeriesNotice.content.isnot(None)).all(),
        s.query(EpisodeDraft.content).filter(EpisodeDraft.content.isnot(None)).all(),
    )
    for rows in content_sources:
        for (content,) in rows:
            urls.update(iter_content_media_urls(content))

    keys: set[str] = set()
    for url in urls:
        keys.update(media_key_candidates(storage, url))
    return keys


def post_media_urls(post: Post, s: Session | None = None) -> set[str]:
    """Collect every local-media URL associated with a post.

    Passing a session also includes older edit-history content, so deleting a
    post does not leave media from previous versions behind.
    """
    urls: set[str] = set(iter_content_media_urls(post.content))
    for item in post.media_attachments or []:
        if isinstance(item, dict) and item.get("url"):
            urls.add(item["url"])
        elif isinstance(item, str) and item:
            urls.add(item)
    if s is not None and post.id is not None:
        for (content,) in s.query(PostEdit.content).filter(PostEdit.post_id == post.id).all():
            urls.update(iter_content_media_urls(content))
    return urls


def episode_media_urls(episode: Episode) -> set[str]:
    """Collect local-media URLs belonging to a series episode."""
    urls: set[str] = set(iter_content_media_urls(episode.content))
    for url in episode.image_urls or []:
        if isinstance(url, str) and url:
            urls.add(url)
    if episode.audio_url:
        urls.add(episode.audio_url)
    return urls


def content_media_urls(content: str | None) -> set[str]:
    """Collect local-media URLs embedded in a piece of HTML/text."""
    return set(iter_content_media_urls(content))


def delete_media_urls_if_unreferenced(
    s: Session,
    urls: Iterable[str],
    storage: StorageBackend | None = None,
) -> int:
    """Delete files for ``urls`` that no live content references anymore.

    A file can be shared by several posts/episodes, so each candidate is checked
    against the current reference set before it is removed. Remote/external URLs
    are ignored because they are not stored by this server.
    """
    storage = storage or get_storage()
    protected = collect_referenced_media_keys(s, storage)

    keys: set[str] = set()
    for url in urls:
        if not url:
            continue
        key = resolve_media_key(storage, url)
        if key and key not in protected:
            keys.add(key)

    deleted = 0
    for key in keys:
        try:
            if storage.delete(key):
                deleted += 1
        except Exception:
            logger.warning("Failed to delete unreferenced media %s", key, exc_info=True)
    return deleted
