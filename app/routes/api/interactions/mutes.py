"""Interaction endpoints — follow, DM, notification, mute/block, like, boost, bookmark, vote, react, pin."""
import json
import logging

from fastapi import APIRouter, Request, Form, HTTPException

from app.models import User, Follow, UserMute, UserBlock, SeriesMute, KeywordMute
from app.core.relationship import mute_user, unmute_user, block_user, unblock_user
from app.db.database import get_session
from app.routes.auth import require_auth, require_active_auth
from app.utils.datetime import _fmt_dt

logger = logging.getLogger("writ.api.mutes")

mutes_router = APIRouter()


# ── User mute/block ──
@mutes_router.get("/mutes/users")
def api_list_user_mutes(request: Request):
    user = require_auth(request)
    with get_session() as s:
        mutes = s.query(UserMute).filter_by(user_id=user.id).order_by(UserMute.created_at.desc()).all()
        return {"mutes": [{"id": m.id, "target_user_id": m.target_user_id, "username": m.target_user.username, "display_name": m.target_user.display_name, "avatar": m.target_user.profile_image or "", "duration": m.duration, "hide_notifications": m.hide_notifications, "created_at": _fmt_dt(m.created_at)} for m in mutes]}


@mutes_router.post("/mutes/users/{target_user_id}")
def api_mute_user(request: Request, target_user_id: int, duration: int = Form(0), hide_notifications: bool = Form(False)):
    user = require_active_auth(request)
    if user.id == target_user_id:
        raise HTTPException(status_code=400, detail="Cannot mute yourself")
    with get_session() as s:
        target = s.query(User).get(target_user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        mute_user(s, user, target, duration=duration, hide_notifications=hide_notifications)
    return {"ok": True}


@mutes_router.delete("/mutes/users/{target_user_id}")
def api_unmute_user(request: Request, target_user_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        target = s.query(User).get(target_user_id)
        if target:
            unmute_user(s, user, target)
    return {"ok": True}


@mutes_router.get("/blocks/users")
def api_list_user_blocks(request: Request):
    user = require_auth(request)
    with get_session() as s:
        blocks = s.query(UserBlock).filter_by(user_id=user.id).order_by(UserBlock.created_at.desc()).all()
        return {"blocks": [{"id": b.id, "target_user_id": b.target_user_id, "username": b.target_user.username, "display_name": b.target_user.display_name, "avatar": b.target_user.profile_image or "", "created_at": _fmt_dt(b.created_at)} for b in blocks]}


@mutes_router.post("/blocks/users/{target_user_id}")
def api_block_user(request: Request, target_user_id: int):
    user = require_active_auth(request)
    if user.id == target_user_id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")
    with get_session() as s:
        target = s.query(User).get(target_user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        block_user(s, user, target)
    return {"ok": True}


@mutes_router.delete("/blocks/users/{target_user_id}")
def api_unblock_user(request: Request, target_user_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        target = s.query(User).get(target_user_id)
        if target:
            unblock_user(s, user, target)
    return {"ok": True}


# ── Series mute ──
@mutes_router.get("/mutes/series")
def api_list_series_mutes(request: Request):
    user = require_auth(request)
    with get_session() as s:
        mutes = s.query(SeriesMute).filter_by(user_id=user.id).order_by(SeriesMute.created_at.desc()).all()
        return {"mutes": [{"id": m.id, "novel_id": m.novel_id, "title": m.novel.title, "cover_image": m.novel.cover_image or "", "created_at": _fmt_dt(m.created_at)} for m in mutes]}


@mutes_router.post("/mutes/series/{novel_id}")
def api_mute_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(SeriesMute).filter_by(user_id=user.id, novel_id=novel_id).first()
        if existing:
            return {"ok": True}
        s.add(SeriesMute(user_id=user.id, novel_id=novel_id))
        s.commit()
    return {"ok": True}


@mutes_router.delete("/mutes/series/{novel_id}")
def api_unmute_series(request: Request, novel_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(SeriesMute).filter_by(user_id=user.id, novel_id=novel_id).delete()
        s.commit()
    return {"ok": True}


# ── Keyword mute ──
@mutes_router.get("/mutes/keywords")
def api_list_keyword_mutes(request: Request):
    user = require_auth(request)
    with get_session() as s:
        mutes = s.query(KeywordMute).filter_by(user_id=user.id).order_by(KeywordMute.created_at.desc()).all()
        return {"mutes": [{"id": m.id, "keyword": m.keyword, "name": m.name or "", "mode": m.mode, "is_regex": m.is_regex, "created_at": _fmt_dt(m.created_at)} for m in mutes]}


@mutes_router.post("/mutes/keywords")
def api_add_keyword_mute(request: Request, keyword: str = Form(...), mode: str = Form("or"), is_regex: bool = Form(False), name: str = Form("")):
    user = require_active_auth(request)
    kw = keyword.strip()
    if not kw:
        raise HTTPException(status_code=400, detail="Keyword cannot be empty")
    if mode not in ("and", "or"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    if is_regex:
        kw = json.dumps([kw])
    else:
        keywords = [k.strip() for k in kw.split("\n") if k.strip()]
        kw = json.dumps(keywords)
    with get_session() as s:
        existing = s.query(KeywordMute).filter_by(user_id=user.id, keyword=kw, mode=mode, is_regex=is_regex).first()
        if existing:
            return {"ok": True}
        s.add(KeywordMute(user_id=user.id, keyword=kw, name=name, mode=mode, is_regex=is_regex))
        s.commit()
    return {"ok": True}


@mutes_router.delete("/mutes/keywords/{mute_id}")
def api_remove_keyword_mute(request: Request, mute_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(KeywordMute).filter_by(id=mute_id, user_id=user.id).delete()
