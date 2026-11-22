"""Post visibility / permission checks shared across the app."""

from sqlalchemy.orm import Session

from app.models import Follow, Post, User


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
        return session.query(Follow).filter_by(
            follower_id=viewer.id, following_id=post.author_id, accepted=True
        ).first() is not None
    if v == "mention":
        # 본문의 @username 문자열은 접두어 충돌(@alice vs @alice2)로
        # 권한을 잘못 부여할 수 있으므로 검증된 ID 목록만 사용한다.
        return bool(post.mentioned_user_ids and viewer.id in post.mentioned_user_ids)
    return True
