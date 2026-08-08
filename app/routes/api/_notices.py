"""Series notice (공지) endpoints extracted from _series.py."""
from fastapi import APIRouter, Request, Form, HTTPException

from app.models import SeriesNotice, Novel
from app.db.database import get_session
from app.core.auth import require_auth
from app.utils.datetime import _fmt_dt

notices_router = APIRouter()


def _notice_json(n):
    return {
        "id": n.id,
        "uuid": n.uuid,
        "novel_id": n.novel_id,
        "title": n.title,
        "content": n.content,
        "is_pinned": n.is_pinned,
        "created_at": _fmt_dt(n.created_at),
        "updated_at": _fmt_dt(n.updated_at),
    }


@notices_router.get("/series/{novel_id}/notices")
def api_list_notices(request: Request, novel_id: int, pinned: int = 0):
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel:
            raise HTTPException(status_code=404, detail="Series not found")
        q = s.query(SeriesNotice).filter_by(novel_id=novel_id)
        if pinned:
            q = q.filter_by(is_pinned=True)
        notices = q.order_by(SeriesNotice.is_pinned.desc(), SeriesNotice.created_at.desc()).all()
        return [_notice_json(n) for n in notices]


@notices_router.get("/series/{novel_id}/notices/{notice_id}")
def api_get_notice(request: Request, novel_id: int, notice_id: int):
    with get_session() as s:
        notice = s.query(SeriesNotice).filter_by(id=notice_id, novel_id=novel_id).first()
        if not notice:
            raise HTTPException(status_code=404, detail="Notice not found")
        return _notice_json(notice)


@notices_router.post("/series/{novel_id}/notices/new")
def api_create_notice(request: Request, novel_id: int, title: str = Form(...), content: str = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        novel = s.query(Novel).filter_by(id=novel_id).first()
        if not novel or novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Series not found")
        notice = SeriesNotice(novel_id=novel_id, title=title, content=content)
        s.add(notice)
        s.commit()
        return _notice_json(notice)


@notices_router.post("/series/{novel_id}/notices/{notice_id}/edit")
def api_edit_notice(request: Request, novel_id: int, notice_id: int, title: str = Form(...), content: str = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        notice = s.query(SeriesNotice).filter_by(id=notice_id, novel_id=novel_id).first()
        if not notice or notice.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Notice not found")
        notice.title = title
        notice.content = content
        s.commit()
        return _notice_json(notice)


@notices_router.post("/series/{novel_id}/notices/{notice_id}/delete")
def api_delete_notice(request: Request, novel_id: int, notice_id: int):
    user = require_auth(request)
    with get_session() as s:
        notice = s.query(SeriesNotice).filter_by(id=notice_id, novel_id=novel_id).first()
        if not notice:
            raise HTTPException(status_code=404, detail="Notice not found")
        if notice.novel.author_id != user.id and user.role not in ("admin", "moderator", "owner"):
            raise HTTPException(status_code=404, detail="Notice not found")
        s.delete(notice)
        s.commit()
    return {"ok": True}


@notices_router.post("/series/{novel_id}/notices/{notice_id}/pin")
def api_toggle_pin_notice(request: Request, novel_id: int, notice_id: int):
    user = require_auth(request)
    with get_session() as s:
        notice = s.query(SeriesNotice).filter_by(id=notice_id, novel_id=novel_id).first()
        if not notice or notice.novel.author_id != user.id:
            raise HTTPException(status_code=404, detail="Notice not found")
        if not notice.is_pinned:
            pinned_count = s.query(SeriesNotice).filter_by(novel_id=novel_id, is_pinned=True).count()
            if pinned_count >= 3:
                raise HTTPException(status_code=400, detail="최대 3개까지 고정할 수 있습니다")
        notice.is_pinned = not notice.is_pinned
        s.commit()
        return _notice_json(notice)
