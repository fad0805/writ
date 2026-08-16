from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.permissions import require_permission
from app.db.database import get_session
from app.models import Post, User
from app.utils.log import log_admin_action

router = APIRouter()


@router.post("/admin/users/{user_id}/delete")
def admin_delete_user(request: Request, user_id: int):
    admin = require_permission(request, "users.admin")
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="자기 자신을 삭제할 수 없습니다")

    with get_session() as session:
        target = session.query(User).filter_by(id=user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        if target.is_admin:
            raise HTTPException(status_code=400, detail="관리자 계정은 삭제할 수 없습니다")
        session.delete(target)
        session.commit()

    ip = request.client.host if request.client else ""
    log_admin_action(admin.id, admin.username, "delete_user", target_type="user", target_id=user_id, target_username=target.username, ip_address=ip)

    return JSONResponse({"ok": True})


@router.post("/admin/posts/{post_id}/delete")
def admin_delete_post(request: Request, post_id: int):
    admin = require_permission(request, "content.manage")

    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.is_deleted = True
        session.commit()

    ip = request.client.host if request.client else ""
    log_admin_action(admin.id, admin.username, "delete_post", target_type="post", target_id=post_id, target_username=f"@{post.author.username}", ip_address=ip)

    return JSONResponse({"ok": True})
