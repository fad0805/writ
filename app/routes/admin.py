from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.models import User, Post, get_session
from app.routes.auth import require_auth

router = APIRouter()

def require_admin(request: Request):
    user = require_auth(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


@router.post("/admin/users/{user_id}/delete")
def admin_delete_user(request: Request, user_id: int):
    admin = require_admin(request)
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

    return JSONResponse({"ok": True})


@router.post("/admin/posts/{post_id}/delete")
def admin_delete_post(request: Request, post_id: int):
    require_admin(request)

    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.is_deleted = True
        session.commit()

    return JSONResponse({"ok": True})
