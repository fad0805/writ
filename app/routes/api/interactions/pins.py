"""Interaction endpoints — follow, DM, notification, mute/block, like, boost, bookmark, vote, react, pin."""
import logging

from fastapi import APIRouter, HTTPException, Request

from app.core.auth import require_active_auth
from app.db.database import get_session
from app.models import Post, User

logger = logging.getLogger("writ.api.pins")

pins_router = APIRouter()


@pins_router.post("/pin/post/{post_id}")
def api_pin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post or post.author_id != user.id:
            raise HTTPException(status_code=404, detail="Post not found")
        if post.visibility == "mention":
            raise HTTPException(status_code=400, detail="멘션 공개 글은 고정할 수 없습니다.")
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            return {"ok": True}
        if len(pinned) >= 5:
            raise HTTPException(status_code=400, detail="최대 5개까지 고정할 수 있습니다.")
        pinned.append(post_id)
        s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
        # Post.is_pinned도 세운다. 프로필 렌더는 User.pinned_posts를 보지만
        # 자동삭제 예외("고정된 게시물")는 Post.is_pinned를 보므로, 둘 중 하나만
        # 갱신하면 고정글이 삭제된다. (마스토돈 API statuses.py와 동일하게 유지)
        post.is_pinned = True  # type: ignore[assignment]
        s.commit()
    return {"ok": True}


@pins_router.post("/unpin/post/{post_id}")
def api_unpin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            pinned.remove(post_id)
            s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
        if post:
            post.is_pinned = False  # type: ignore[assignment]
        s.commit()
    return {"ok": True}
