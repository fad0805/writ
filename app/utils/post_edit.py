"""Helpers for recording post edit history."""

from datetime import UTC, datetime

from app.models import PostEdit


def record_post_edit(
    session,
    post,
    *,
    old_content: str,
    old_summary: str,
    old_visibility: str,
    old_is_sensitive: bool,
    edited_at: datetime | None = None,
):
    """Save the version that was just replaced and mark the post as edited.

    The current version stays on ``Post`` itself; ``PostEdit`` rows are the
    previous versions in oldest-first order. Call this only after the post has
    actually changed and before committing the transaction.
    """
    now = edited_at or datetime.now(UTC)
    previous_at = post.edited_at or post.created_at or now
    session.add(PostEdit(
        post_id=post.id,
        content=old_content or "",
        summary=old_summary or "",
        visibility=old_visibility or "public",
        is_sensitive=bool(old_is_sensitive),
        created_at=previous_at,
    ))
    post.edited_at = now
    return now
