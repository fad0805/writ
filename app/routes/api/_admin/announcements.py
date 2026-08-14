"Announcements admin endpoints."

import json

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy import desc
from sqlalchemy.orm import joinedload

from app.core.auth import require_auth
from app.db.database import get_session
from app.models import Announcement, AnnouncementRead, AnnouncementVote
from app.routes.api._announcements import _announcement_json, _is_announcement_active, _parse_dt_field
from app.utils.log import log_admin_action

router = APIRouter()


@router.get("/admin/announcements")
def api_admin_list_announcements(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        items = s.query(Announcement).options(joinedload(Announcement.created_by)).order_by(desc(Announcement.created_at)).all()
        return [dict(_announcement_json(a), active=_is_announcement_active(a)) for a in items]


def _build_announcement_poll(poll_options: str):
    """Parse poll_options JSON array of strings. Returns poll_data dict or None."""
    if not poll_options or not poll_options.strip():
        return None
    try:
        opts = json.loads(poll_options)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid poll_options") from exc
    if not isinstance(opts, list):
        raise HTTPException(status_code=400, detail="Invalid poll_options")
    texts = [str(o).strip() for o in opts if str(o).strip()]
    if len(texts) < 2:
        return None
    return {"options": [{"text": t, "votes_count": 0} for t in texts]}


@router.post("/admin/announcements/new")
def api_admin_create_announcement(request: Request, title: str = Form(...), content: str = Form(...),
                                  starts_at: str = Form(""), ends_at: str = Form(""), poll_options: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    with get_session() as s:
        a = Announcement(
            title=title.strip(),
            content=content,
            starts_at=_parse_dt_field(starts_at),
            ends_at=_parse_dt_field(ends_at),
            poll_data=_build_announcement_poll(poll_options),
            created_by_id=user.id,
        )
        s.add(a)
        s.commit()
        s.refresh(a)
        result = dict(_announcement_json(a), active=_is_announcement_active(a))
    log_admin_action(user.id, user.username, "create_announcement", target_type="announcement", target_id=a.id, details=a.title, ip_address=request.client.host if request.client else "")
    return result


@router.post("/admin/announcements/{announcement_id}/edit")
def api_admin_edit_announcement(request: Request, announcement_id: int, title: str = Form(...), content: str = Form(...),
                                starts_at: str = Form(""), ends_at: str = Form(""), poll_options: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        a = s.query(Announcement).get(announcement_id)
        if not a:
            raise HTTPException(status_code=404, detail="Announcement not found")
        a.title = title.strip()
        a.content = content
        a.starts_at = _parse_dt_field(starts_at)
        a.ends_at = _parse_dt_field(ends_at)
        new_poll = _build_announcement_poll(poll_options)
        old_options = (a.poll_data or {}).get("options", []) if a.poll_data else []
        if new_poll is None:
            if a.poll_data is not None:
                s.query(AnnouncementVote).filter_by(announcement_id=a.id).delete()
            a.poll_data = None
        elif len(old_options) == len(new_poll["options"]) and [o.get("text") for o in old_options] == [o.get("text") for o in new_poll["options"]]:
            new_poll["options"] = [
                {"text": o.get("text", ""), "votes_count": old.get("votes_count", 0)}
                for o, old in zip(new_poll["options"], old_options, strict=False)
            ]
            a.poll_data = new_poll
        else:
            s.query(AnnouncementVote).filter_by(announcement_id=a.id).delete()
            a.poll_data = new_poll
        s.commit()
        s.refresh(a)
        result = dict(_announcement_json(a), active=_is_announcement_active(a))
    log_admin_action(user.id, user.username, "edit_announcement", target_type="announcement", target_id=a.id, details=a.title, ip_address=request.client.host if request.client else "")
    return result


@router.post("/admin/announcements/{announcement_id}/delete")
def api_admin_delete_announcement(request: Request, announcement_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        a = s.query(Announcement).get(announcement_id)
        if not a:
            raise HTTPException(status_code=404, detail="Announcement not found")
        s.query(AnnouncementRead).filter_by(announcement_id=a.id).delete()
        s.query(AnnouncementVote).filter_by(announcement_id=a.id).delete()
        s.delete(a)
        s.commit()
    log_admin_action(user.id, user.username, "delete_announcement", target_type="announcement", target_id=announcement_id, ip_address=request.client.host if request.client else "")
    return {"ok": True}
