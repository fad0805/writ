from app.routes.api.interactions._common import *

logger = logging.getLogger("writ.api.pins")

pins_router = APIRouter()



@pins_router.post("/pin/post/{post_id}")
def api_pin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post or post.author_id != user.id:
            raise HTTPException(status_code=404, detail="Post not found")
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            return {"ok": True}
        if len(pinned) >= 5:
            raise HTTPException(status_code=400, detail="최대 5개까지 고정할 수 있습니다.")
        pinned.append(post_id)
        s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
        s.commit()
    return {"ok": True}


@pins_router.post("/unpin/post/{post_id}")
def api_unpin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            pinned.remove(post_id)
            s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
            s.commit()
    return {"ok": True}
