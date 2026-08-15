"""User-facing announcement endpoints extracted from _misc.py."""
import logging
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload

from app.core.auth import require_auth
from app.db.database import get_session
from app.models import Announcement, AnnouncementRead, AnnouncementVote
from app.utils.datetime import KST, _fmt_dt

logger = logging.getLogger("writ.api.announcements")

announcements_router = APIRouter()


def _parse_dt_field(value: str):
    """Parse a datetime-local style string (KST) into a UTC-aware datetime. Empty -> None."""
    if not value or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid datetime format") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(UTC)


def _is_announcement_active(a: Announcement, now_dt=None) -> bool:
    now_dt = now_dt or datetime.now(UTC)
    def _aware(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    starts = _aware(a.starts_at)
    ends = _aware(a.ends_at)
    if starts and starts > now_dt:
        return False
    return not (ends and ends < now_dt)


def _announcement_json(a: Announcement):
    return {
        "id": a.id,
        "title": a.title,
        "content": a.content,
        "starts_at": _fmt_dt(cast(datetime | None, a.starts_at)),
        "ends_at": _fmt_dt(cast(datetime | None, a.ends_at)),
        "poll_data": a.poll_data,
        "created_by": a.created_by.username if a.created_by else "",
        "created_at": _fmt_dt(cast(datetime | None, a.created_at)),
        "updated_at": _fmt_dt(cast(datetime | None, a.updated_at)),
    }


def _get_announcement_read(s, announcement_id: int, user_id: int) -> AnnouncementRead | None:
    return s.query(AnnouncementRead).filter_by(announcement_id=announcement_id, user_id=user_id).first()


def _get_announcement_vote(s, announcement_id: int, user_id: int) -> AnnouncementVote | None:
    return s.query(AnnouncementVote).filter_by(announcement_id=announcement_id, user_id=user_id).first()


def _sync_announcement_vote_counts(s, a: Announcement):
    votes = s.query(AnnouncementVote.option_index, func.count(AnnouncementVote.id).label("cnt")).filter(
        AnnouncementVote.announcement_id == a.id
    ).group_by(AnnouncementVote.option_index).all()
    counts = {v.option_index: v.cnt for v in votes}
    _poll: dict = a.poll_data if isinstance(a.poll_data, dict) else {}
    options = _poll.get("options") or []
    new_options = [{"text": o.get("text", ""), "votes_count": counts.get(i, 0)} for i, o in enumerate(options)]
    new_poll = {**_poll, "options": new_options}
    a.poll_data = new_poll  # type: ignore[assignment]
    s.query(Announcement).filter(Announcement.id == a.id).update({"poll_data": new_poll}, synchronize_session=False)


def _user_announcement_json(s, a: Announcement, user_id: int):
    read = _get_announcement_read(s, int(a.id), user_id)
    vote = _get_announcement_vote(s, int(a.id), user_id)
    return dict(
        _announcement_json(a),
        active=_is_announcement_active(a),
        is_read=bool(read and read.is_read),
        notified=bool(read and read.notified_at),
        my_vote=vote.option_index if vote else None,
    )


@announcements_router.get("/announcements")
def api_list_announcements(request: Request):
    user = require_auth(request)
    with get_session() as s:
        items = s.query(Announcement).options(joinedload(Announcement.created_by)).order_by(desc(Announcement.created_at)).all()
        return {
            "announcements": [
                _user_announcement_json(s, a, user.id)
                for a in items
                if _is_announcement_active(a)
            ]
        }


@announcements_router.get("/announcements/status")
def api_announcements_status(request: Request):
    user = require_auth(request)
    with get_session() as s:
        items = s.query(Announcement).order_by(desc(Announcement.created_at)).all()
        now_dt = datetime.now(UTC)
        active = [a for a in items if _is_announcement_active(a, now_dt)]
        unread_count = 0
        popups = []
        for a in active:
            read = _get_announcement_read(s, a.id, user.id)
            if not (read and read.is_read):
                unread_count += 1
            if read is None or not read.notified_at:
                popups.append({"id": a.id, "title": a.title})
        return {
            "has_active": bool(active),
            "unread_count": unread_count,
            "popups": popups,
        }


@announcements_router.get("/announcements/{announcement_id}")
def api_get_announcement(request: Request, announcement_id: int):
    user = require_auth(request)
    with get_session() as s:
        a = s.query(Announcement).options(joinedload(Announcement.created_by)).get(announcement_id)
        if not a:
            raise HTTPException(status_code=404, detail="Announcement not found")
        return _user_announcement_json(s, a, user.id)


@announcements_router.post("/announcements/{announcement_id}/read")
def api_announcement_read(request: Request, announcement_id: int):
    user = require_auth(request)
    with get_session() as s:
        a = s.query(Announcement).get(announcement_id)
        if not a:
            raise HTTPException(status_code=404, detail="Announcement not found")
        read = _get_announcement_read(s, a.id, user.id)
        if read is None:
            read = AnnouncementRead(announcement_id=a.id, user_id=user.id)
            s.add(read)
        read.is_read = True  # type: ignore[assignment]
        read.read_at = datetime.now(UTC)  # type: ignore[assignment]
        if not read.notified_at:
            read.notified_at = read.read_at
        s.commit()
    return {"ok": True}


@announcements_router.post("/announcements/{announcement_id}/notified")
def api_announcement_notified(request: Request, announcement_id: int):
    user = require_auth(request)
    with get_session() as s:
        a = s.query(Announcement).get(announcement_id)
        if not a:
            raise HTTPException(status_code=404, detail="Announcement not found")
        read = _get_announcement_read(s, a.id, user.id)
        if read is None:
            read = AnnouncementRead(announcement_id=a.id, user_id=user.id)
            s.add(read)
        if not read.notified_at:
            read.notified_at = datetime.now(UTC)  # type: ignore[assignment]
        s.commit()
    return {"ok": True}


@announcements_router.post("/announcements/{announcement_id}/vote")
def api_announcement_vote(request: Request, announcement_id: int, option: int = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        a = s.query(Announcement).get(announcement_id)
        if not a or not a.poll_data:
            raise HTTPException(status_code=404, detail="Announcement or poll not found")
        if not _is_announcement_active(a):
            raise HTTPException(status_code=400, detail="Announcement is not active")
        options = a.poll_data.get("options", [])
        if option < 0 or option >= len(options):
            raise HTTPException(status_code=400, detail="Invalid option")
        existing = _get_announcement_vote(s, int(a.id), user.id)
        if existing:
            existing.option_index = option  # type: ignore[assignment]
        else:
            s.add(AnnouncementVote(announcement_id=a.id, user_id=user.id, option_index=option))
        s.flush()
        _sync_announcement_vote_counts(s, a)
        s.commit()
        s.refresh(a)
        return {"ok": True, "announcement": _user_announcement_json(s, a, user.id)}


@announcements_router.post("/announcements/{announcement_id}/unvote")
def api_announcement_unvote(request: Request, announcement_id: int):
    user = require_auth(request)
    with get_session() as s:
        a = s.query(Announcement).get(announcement_id)
        if not a or not a.poll_data:
            raise HTTPException(status_code=404, detail="Announcement or poll not found")
        existing = _get_announcement_vote(s, a.id, user.id)
        if existing:
            s.delete(existing)
            s.flush()
            _sync_announcement_vote_counts(s, a)
            s.commit()
            s.refresh(a)
        return {"ok": True, "announcement": _user_announcement_json(s, a, user.id)}
