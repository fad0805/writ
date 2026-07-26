"""Interaction endpoints — follow, DM, notification, mute/block, like, boost, bookmark, vote, react, pin."""
import json
import re
import time
import logging
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from uuid import uuid4
from fastapi import APIRouter, Request, Form, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import or_, and_, func, String, desc, select
from sqlalchemy.orm import selectinload, Session, joinedload
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from app.models import User, Post, Follow, Like, Boost, Vote, Bookmark, Notification, Novel, Episode, ProfileNote, UserMute, UserBlock, SeriesMute, KeywordMute, PushSubscription, CustomEmoji, ServerSetting
from app.serializers import _user_json, _post_json
from app.config.settings import BASE_URL, MAX_POST_LENGTH
from app.core.activitypub import _send_delete_post, _post_to_inbox, _resolve_actor, _send_accept, _send_reject
from app.core.eventbus import broadcast
from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_refresh_notifs, add_notif_stream, remove_notif_stream, broadcast_notif_sound, broadcast_reaction_update, broadcast_post
from app.db.database import get_session, get_db
from app.db.mention_resolver import resolve_handles_to_ids
from app.routes.auth import require_auth, require_active_auth, get_current_user
from app.utils.datetime import _fmt_dt
from app.utils.emoji import _emoji_url, _load_emojis
from app.utils.filter import _timeline_filter
from app.utils.storage import get_storage

from app.routes.api._core import _can_view, _ap_fetch, _check_fetch_domain_allowed
from app.routes.api._feed import _broadcast_timeline


logger = logging.getLogger("writ.api.mutes")

from app.routes.api.interactions._common import _json_array_has_user

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
        existing = s.query(UserMute).filter_by(user_id=user.id, target_user_id=target_user_id).first()
        if existing:
            existing.duration = duration
            existing.hide_notifications = hide_notifications
            s.commit()
            return {"ok": True}
        s.add(UserMute(user_id=user.id, target_user_id=target_user_id, duration=duration, hide_notifications=hide_notifications))
        s.commit()
    return {"ok": True}


@mutes_router.delete("/mutes/users/{target_user_id}")
def api_unmute_user(request: Request, target_user_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(UserMute).filter_by(user_id=user.id, target_user_id=target_user_id).delete()
        s.commit()
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
    target_remote_url = None
    target_shared_inbox = None
    target_id = None
    with get_session() as s:
        existing = s.query(UserBlock).filter_by(user_id=user.id, target_user_id=target_user_id).first()
        if existing:
            return {"ok": True}
        s.add(UserBlock(user_id=user.id, target_user_id=target_user_id))
        # Remove follows both ways
        s.query(Follow).filter_by(follower_id=user.id, following_id=target_user_id).delete()
        s.query(Follow).filter_by(follower_id=target_user_id, following_id=user.id).delete()
        s.commit()
        target = s.query(User).get(target_user_id)
        if target:
            target_remote_url = target.remote_url
            target_shared_inbox = target.shared_inbox_url or target.inbox_url
            target_id = target.id
    if target_remote_url and target_shared_inbox:
        try:
            block_id = f"{BASE_URL}/users/{user.username}/status/activities/block/{target_id}"
            actor_uri = f"{BASE_URL}/users/{user.username}"
            block_activity = {
                "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
                "type": "Block",
                "id": block_id,
                "actor": actor_uri,
                "to": [target_remote_url],
                "object": target_remote_url,
            }
            _post_to_inbox(target_shared_inbox, block_activity, user)
        except Exception:
            pass
    return {"ok": True}


@mutes_router.delete("/blocks/users/{target_user_id}")
def api_unblock_user(request: Request, target_user_id: int):
    user = require_active_auth(request)
    target_remote_url = None
    target_shared_inbox = None
    target_id = None
    with get_session() as s:
        target = s.query(User).get(target_user_id)
        if target:
            target_remote_url = target.remote_url
            target_shared_inbox = target.shared_inbox_url or target.inbox_url
            target_id = target.id
        s.query(UserBlock).filter_by(user_id=user.id, target_user_id=target_user_id).delete()
        s.commit()
    if target_remote_url:
        try:
            block_id = f"{BASE_URL}/users/{user.username}/status/activities/block/{target_id}"
            actor_uri = f"{BASE_URL}/users/{user.username}"
            undo_activity = {
                "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
                "type": "Undo",
                "id": f"{BASE_URL}/users/{user.username}/status/activities/undo/{target_id}",
                "actor": actor_uri,
                "to": [target_remote_url],
                "object": {
                    "id": block_id,
                    "type": "Block",
                    "actor": actor_uri,
                    "object": target_remote_url,
                },
            }
            _post_to_inbox(target_shared_inbox, undo_activity, user)
        except Exception:
            pass
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
