"""Mastodon notification endpoints (/api/v1/notifications*)."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session as SASession

from app.db.database import get_db
from app.models import Notification
from app.routes.mastodon_api._common import (
    _account_json,
    _ap_datetime,
    _build_account_counts_map,
    _build_status_maps,
    _query_param_list,
    _require_bearer,
    _status_json,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/v1/notifications
# ---------------------------------------------------------------------------
@router.get("/v1/notifications")
def list_notifications(
    request: Request,
    db: SASession = Depends(get_db),
    max_id: str | None = None,
    since_id: str | None = None,
    min_id: str | None = None,
    limit: int = Query(default=20, le=100),
):
    user = _require_bearer(request, db)

    types = _query_param_list(request, "types")
    exclude_types = _query_param_list(request, "exclude_types")

    q = db.query(Notification).filter(Notification.user_id == user.id)

    type_map = {
        "follow": "follow",
        "follow_request": "follow_request",
        "mention": "mention",
        "reblog": "boost",
        "favourite": "like",
        "poll": "poll",
        "status": "status",
    }
    if types:
        mapped = [type_map.get(t, t) for t in types]
        q = q.filter(Notification.notification_type.in_(mapped))
    elif exclude_types:
        mapped = [type_map.get(t, t) for t in exclude_types]
        q = q.filter(~Notification.notification_type.in_(mapped))

    if max_id:
        q = q.filter(Notification.id < int(max_id))
    if since_id:
        q = q.filter(Notification.id > int(since_id))
    if min_id:
        q = q.filter(Notification.id > int(min_id))

    notifs = q.order_by(Notification.id.desc()).limit(limit).all()

    _NOTIF_TYPE_MAP_RESPONSE = {
        "like": "favourite",
        "reply": "mention",
        "boost": "reblog",
        "follow": "follow",
        "follow_request": "follow_request",
        "poll": "poll",
        "status": "status",
        "mention": "mention",
    }

    notif_posts = [n.post for n in notifs if n.post and not n.post.is_deleted]
    maps = _build_status_maps(notif_posts, db, user)
    from_ids = {n.from_user_id for n in notifs if n.from_user_id}
    from_counts = _build_account_counts_map(from_ids, db)

    result = []
    for n in notifs:
        item = {
            "id": str(n.id),
            "type": _NOTIF_TYPE_MAP_RESPONSE.get(n.notification_type, n.notification_type),
            "created_at": _ap_datetime(n.created_at),
            "account": _account_json(n.from_user, db, viewer=user,
                                     _counts=from_counts.get(n.from_user_id)) if n.from_user else _account_json(user, db),
        }
        if n.post and not n.post.is_deleted:
            item["status"] = _status_json(n.post, db, viewer=user, **maps)
        else:
            item["status"] = None
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# POST /api/v1/notifications/:id/dismiss
# ---------------------------------------------------------------------------
@router.post("/v1/notifications/{notification_id}/dismiss")
def dismiss_notification(notification_id: str, request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    n = db.query(Notification).filter_by(id=int(notification_id), user_id=user.id).first()
    if n:
        n.is_read = True
        db.commit()
    return {}


# ---------------------------------------------------------------------------
# POST /api/v1/notifications/clear
# ---------------------------------------------------------------------------
@router.post("/v1/notifications/clear")
def clear_notifications(request: Request, db: SASession = Depends(get_db)):
    user = _require_bearer(request, db)
    db.query(Notification).filter(Notification.user_id == user.id).update({"is_read": True})
    db.commit()
    return {}


# ---------------------------------------------------------------------------
# GET /api/v1/notifications/types
# ---------------------------------------------------------------------------
@router.get("/v1/notifications/types")
def notification_types():
    return {
        "follow": "follow",
        "follow_request": "follow_request",
        "mention": "mention",
        "reblog": "reblog",
        "favourite": "favourite",
        "poll": "poll",
        "status": "status",
        "move": "move",
        "report": "report",
    }
