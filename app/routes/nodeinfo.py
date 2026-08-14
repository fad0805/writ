import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config.settings import BASE_URL
from app.db.database import get_session
from app.models import Post, ServerSetting, User

router = APIRouter()


@router.get("/nodeinfo/2.0")
def nodeinfo():
    with get_session() as session:
        now = datetime.datetime.now(datetime.UTC)
        user_count = session.query(User).filter_by(is_remote=False).count()
        active_month = session.query(User).filter(
            User.is_remote == False,
            User.id.in_(session.query(Post.author_id).filter(Post.created_at > (now - datetime.timedelta(days=30))))
        ).count()
        active_halfyear = session.query(User).filter(
            User.is_remote == False,
            User.id.in_(session.query(Post.author_id).filter(Post.created_at > (now - datetime.timedelta(days=180))))
        ).count()
        local_post_count = session.query(Post).filter(Post.author.has(is_remote=False)).count()
        settings = ServerSetting.get(session)
        server_name = settings.server_name or "WRIT"
        server_desc = getattr(settings, 'server_description', '') or ''
        open_reg = not (getattr(settings, 'require_invite', False) or False)

    return JSONResponse({
        "version": "2.0",
        "software": {
            "name": "writ",
            "version": "1.0.0",
            "repository": "https://github.com/fad0805/writ",
        },
        "protocols": ["activitypub"],
        "services": {"inbound": [], "outbound": []},
        "openRegistrations": open_reg,
        "usage": {
            "users": {"total": user_count, "activeHalfyear": active_halfyear, "activeMonth": active_month},
            "localPosts": local_post_count,
        },
        "metadata": {
            "nodeName": server_name,
            "nodeDescription": server_desc,
        },
    })


@router.get("/.well-known/nodeinfo")
def well_known_nodeinfo():
    return JSONResponse({
        "links": [
            {
                "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                "href": f"{BASE_URL}/nodeinfo/2.0",
            }
        ]
    })
