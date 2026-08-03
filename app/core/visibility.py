"""Post visibility / permission checks shared across the app."""

from sqlalchemy.orm import Session

from app.models import User, Post, Follow


def _can_view(post: Post, viewer: User | None, session: Session) -> bool:
    if post.is_deleted:
        return False
    if viewer and post.author_id == viewer.id:
        return True
    v = post.visibility or "public"
    if v in ("public", "home"):
        return True
    if not viewer:
        return False
    if v == "followers":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return session.query(Follow).filter_by(
            follower_id=viewer.id, following_id=post.author_id, accepted=True
        ).first() is not None
    if v == "mention":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return False
    return True
