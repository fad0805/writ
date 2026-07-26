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


logger = logging.getLogger("writ.api.pins")

from app.routes.api.interactions._common import _json_array_has_user

pins_router = APIRouter()



@pins_router.post("/pin/post/{post_id}")
def api_pin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post or post.author_id != user.id:
            raise HTTPException(status_code=404, detail="Post not found")
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            return {"ok": True}
        if len(pinned) >= 5:
            raise HTTPException(status_code=400, detail="최대 5개까지 고정할 수 있습니다.")
        pinned.append(post_id)
        s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
        s.commit()
    return {"ok": True}


@pins_router.post("/unpin/post/{post_id}")
def api_unpin_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        pinned = list(user.pinned_posts or [])
        if post_id in pinned:
            pinned.remove(post_id)
            s.query(User).filter_by(id=user.id).update({"pinned_posts": pinned})
            s.commit()
    return {"ok": True}
