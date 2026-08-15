"""Mastodon instance endpoints (/api/v1/instance*, /api/v2/instance)."""
from fastapi import APIRouter, Depends
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session as SASession

from app.config.settings import BASE_URL, DOMAIN, MAX_POST_LENGTH, SCHEME
from app.core.push import get_vapid_keys
from app.db.database import get_db
from app.models import Post, ServerRule, ServerSetting, Tag, User, now

router = APIRouter()


def _abs_url(value: str | None) -> str | None:
    """로컬 상대 경로를 절대 URL로 변환. 비어 있으면 None 반환."""
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return f"{SCHEME}:{value}"
    if value.startswith("/"):
        return f"{BASE_URL}{value}"
    return value


def _rules_json(db: SASession) -> list[dict]:
    """DB의 서버 규칙을 Mastodon Rule 형태([{id, text}])로 변환."""
    rules = db.query(ServerRule).order_by(ServerRule.sort_order).all()
    return [
        {
            "id": str(r.id),
            "text": r.title if not r.description else f"{r.title} — {r.description}",
        }
        for r in rules
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/instance
# ---------------------------------------------------------------------------
@router.get("/v1/instance")
def mastodon_instance(db: SASession = Depends(get_db)):
    settings = ServerSetting.get(db)
    user_count = db.query(sqlfunc.count(User.id)).filter(User.is_remote == False).scalar() or 0
    status_count = db.query(sqlfunc.count(Post.id)).filter(Post.is_deleted == False).scalar() or 0
    admin_email = settings.admin_email or ""
    admin_ids = [int(i) for i in (settings.admin_ids or "").split(",") if i.strip().isdigit()]
    if not admin_email and admin_ids:
        admin_user = db.query(User).filter(User.id.in_(admin_ids), User.is_remote == False).first()
        if admin_user:
            admin_email = admin_user.email or ""
    contact_account = None
    contact_user = None
    if admin_ids:
        contact_user = db.query(User).filter(User.id.in_(admin_ids), User.is_remote == False).first()
    if not contact_user:
        contact_user = db.query(User).filter(User.is_remote == False, User.is_admin == True).first()
    if not contact_user:
        contact_user = db.query(User).filter(User.is_remote == False).order_by(User.id.asc()).first()
    if contact_user:
        contact_account = {
            "id": str(contact_user.id),
            "username": contact_user.username,
            "acct": contact_user.username,
            "display_name": contact_user.display_name or contact_user.username,
            "avatar": _abs_url(str(contact_user.profile_image)) or f"{BASE_URL}/default-avatar.png",
            "avatar_static": _abs_url(str(contact_user.profile_image)) or f"{BASE_URL}/default-avatar.png",
            "header": _abs_url(str(contact_user.header_image)) or f"{BASE_URL}/default-header.png",
            "header_static": _abs_url(str(contact_user.header_image)) or f"{BASE_URL}/default-header.png",
            "url": f"{BASE_URL}/@{contact_user.username}",
            "note": contact_user.summary or "",
            "locked": False,
            "bot": False,
            "created_at": (contact_user.created_at or now()).isoformat(),
            "followers_count": 0,
            "following_count": 0,
            "statuses_count": 0,
            "last_status_at": None,
            "emojis": [],
            "fields": [],
        }

    _, vapid_pub = get_vapid_keys()

    desc = settings.server_description or "WRIT — 글쓰기에 집중하는 소셜 네트워크"

    return {
        "uri": DOMAIN,
        "title": settings.server_name or "WRIT",
        "description": desc,
        "short_description": desc,
        "email": admin_email,
        "version": "4.3.0 (compatible; WRIT)",
        "languages": ["ko"],
        "urls": {
            "streaming_api": f"wss://{DOMAIN}/api/v1/streaming",
        },
        "stats": {
            "user_count": user_count,
            "status_count": status_count,
            "domain_count": 0,
        },
        "thumbnail": _abs_url(settings.logo),
        "registrations": True,
        "approval_required": False,
        "invites_enabled": False,
        "contact_account": contact_account,
        "rules": _rules_json(db),
        "configuration": {
            "urls": {
                "accounts": f"{BASE_URL}/authorize_fetch",
            },
            "vapid_key": vapid_pub or "",
            "accounts": {
                "max_featured_tags": 10,
            },
            "statuses": {
                "max_characters": MAX_POST_LENGTH,
                "max_media_attachments": 4,
                "characters_reserved_per_url": 23,
            },
            "media_attachments": {
                "supported_file_types": [
                    "image/jpeg", "image/png", "image/gif", "image/webp",
                    "video/webm", "video/mp4", "video/quicktime",
                    "audio/mpeg", "audio/ogg",
                ],
                "image_size_limit": 10485760,
                "image_matrix_limit": 4096,
                "video_size_limit": 41943040,
                "video_frame_rate_limit": 60,
                "video_matrix_limit": 2304,
            },
            "polls": {
                "max_options": 4,
                "max_characters_per_option": 50,
                "min_expiration": 300,
                "max_expiration": 2629746,
            },
            "reactions": {
                "max_reactions": 10,
            },
        },
    }


# ---------------------------------------------------------------------------
# GET /api/v1/instance/peers (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/instance/peers")
def instance_peers():
    return []


# ---------------------------------------------------------------------------
# GET /api/v1/instance/trends (stub)
# ---------------------------------------------------------------------------
@router.get("/v1/instance/trends")
def instance_trends(db: SASession = Depends(get_db)):
    tags = db.query(Tag).order_by(Tag.id.desc()).limit(10).all()
    return [
        {"name": t.display_name or t.name, "url": f"{BASE_URL}/explore?q=%23{t.display_name or t.name}"}
        for t in tags
    ]


# ---------------------------------------------------------------------------
# GET /api/v1/instance/rules
# ---------------------------------------------------------------------------
@router.get("/v1/instance/rules")
def instance_rules(db: SASession = Depends(get_db)):
    return _rules_json(db)


# ---------------------------------------------------------------------------
# GET /api/v2/instance
# ---------------------------------------------------------------------------
@router.get("/v2/instance")
def v2_instance(db: SASession = Depends(get_db)):
    return mastodon_instance(db)
