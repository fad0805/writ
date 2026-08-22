"Users listing/detail/stats admin endpoints."

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import String

from app.core.permissions import require_permission
from app.db.database import get_session
from app.models import Follow, Novel, Post, User
from app.serializers import _user_json

router = APIRouter()


@router.get("/admin/stats")
def api_admin_stats(request: Request):
    user = require_permission(request, "users.manage")
    with get_session() as s:
        users = s.query(User).filter_by(is_remote=False).count()
        posts = s.query(Post).filter_by(is_deleted=False).count()
        series = s.query(Novel).count()
        return {"users": users, "posts": posts, "series": series}


@router.get("/admin/users")
def api_admin_users(request: Request, location: str = Query("local"), status: str = Query("all"),
                     role: str = Query("all"), sort: str = Query("newest"),
                     q: str = Query(""), username_q: str = Query(""), name_q: str = Query(""),
                     email_q: str = Query(""), ip_q: str = Query(""), domain_q: str = Query("")):
    user = require_permission(request, "users.manage")
    with get_session() as s:
        qb = s.query(User)
        if location == "local":
            qb = qb.filter_by(is_remote=False)
        elif location == "remote":
            qb = qb.filter_by(is_remote=True)
        if status == "active":
            qb = qb.filter(User.is_suspended == False, User.is_remote == False)
        elif status == "suspended":
            qb = qb.filter(User.is_suspended == True)
        elif status == "pending":
            qb = qb.filter(User.email_verified == False, User.is_remote == False)
        elif status == "inactive":
            # no recent activity > 30 days (local only)
            cutoff = datetime.now(UTC) - timedelta(days=30)
            qb = qb.filter(User.is_remote == False, User.created_at < cutoff)
        if role == "admin":
            qb = qb.filter(User.role.in_(["admin", "owner"]))
        elif role == "moderator":
            qb = qb.filter(User.role == "moderator")
        elif role == "owner":
            qb = qb.filter(User.role == "owner")
        elif role == "user":
            qb = qb.filter(User.role == "user")
        if q:
            pattern = f"%{q}%"
            qb = qb.filter(
                User.username.ilike(pattern) |
                User.display_name.ilike(pattern) |
                User.email.ilike(pattern) |
                User.recent_ips.cast(String).ilike(pattern)
            )
        if username_q:
            qb = qb.filter(User.username.ilike(f"%{username_q}%"))
        if name_q:
            qb = qb.filter(User.display_name.ilike(f"%{name_q}%"))
        if email_q:
            qb = qb.filter(User.email.ilike(f"%{email_q}%"))
        if ip_q:
            qb = qb.filter(User.recent_ips.cast(String).ilike(f"%{ip_q}%"))
        if domain_q:
            qb = qb.filter(User.username.ilike(f"%@{domain_q}%") | User.email.ilike(f"%@{domain_q}%"))
        qb = qb.order_by(User.updated_at.desc()) if sort == "active" else qb.order_by(User.created_at.desc())
        users = qb.limit(50).all()
        result = []
        for u in users:
            post_count = s.query(Post).filter_by(author_id=u.id, is_deleted=False).count()
            follower_count = s.query(Follow).filter_by(following_id=u.id, accepted=True).count()
            recent_post = s.query(Post).filter_by(author_id=u.id).order_by(Post.created_at.desc()).first()
            last_active = str(recent_post.created_at) if recent_post and recent_post.created_at else str(u.created_at) if u.created_at else ""
            email_domain = u.email.split("@")[-1] if "@" in (u.email or "") else ""
            result.append({
                **_user_json(u),
                "created_at": str(u.created_at) if u.created_at else "",
                "post_count": post_count,
                "follower_count": follower_count,
                "last_active": last_active,
                "email_domain": email_domain,
                "recent_ips": (u.recent_ips or [])[:3],
                "is_suspended": getattr(u, 'is_suspended', False),
                "is_frozen": getattr(u, 'is_frozen', False),
                "is_limited": getattr(u, 'is_limited', False),
                "is_deceased": getattr(u, 'is_deceased', False),
            })
        return {"users": result}


@router.get("/admin/users/{user_id}")
def api_admin_user_detail(request: Request, user_id: int):
    user = require_permission(request, "users.manage")
    with get_session() as s:
        u = s.query(User).get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        post_count = s.query(Post).filter_by(author_id=u.id, is_deleted=False).count()
        follower_count = s.query(Follow).filter_by(following_id=u.id, accepted=True).count()
        following_count = s.query(Follow).filter_by(follower_id=u.id, accepted=True).count()
        recent_post = s.query(Post).filter_by(author_id=u.id).order_by(Post.created_at.desc()).first()
        last_active = str(recent_post.created_at) if recent_post and recent_post.created_at else str(u.created_at) if u.created_at else ""
        novels = s.query(Novel).filter_by(author_id=u.id).count()
        email_domain = u.email.split("@")[-1] if "@" in (u.email or "") else ""
        return {
            **_user_json(u),
            "created_at": str(u.created_at) if u.created_at else "",
            "post_count": post_count,
            "follower_count": follower_count,
            "following_count": following_count,
            "novels_count": novels,
            "last_active": last_active,
            "email_domain": email_domain,
            "recent_ips": (u.recent_ips or [])[:10],
            "is_limited": getattr(u, 'is_limited', False),
            "is_frozen": getattr(u, 'is_frozen', False),
            "is_deceased": getattr(u, 'is_deceased', False),
            "is_suspended": getattr(u, 'is_suspended', False),
            "is_sensitive": getattr(u, 'is_sensitive', False),
            "moderation_note": getattr(u, 'moderation_note', '') or '',
            "email_verified": getattr(u, 'email_verified', False),
            "summary": u.summary or "",
        }
