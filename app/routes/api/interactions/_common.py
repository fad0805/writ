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

logger = logging.getLogger("writ.api.interactions")


def _json_array_has_user(column, user_id):
    """JSON 배열 컬럼에 user_id가 정확히 포함되어 있는지 확인"""
    if isinstance(column.type, postgresql.JSONB):
        return column.cast(JSONB).op('@>')(func.json_build_array(user_id).cast(JSONB))
    else:
        # SQLite fallback: cast to text and check containment via LIKE
        return column.cast(String).like(f'%{user_id}%')


def _generate_poll_end_notifications(user_id: int, session):
    now = datetime.now(timezone.utc)
    # 빠른 확인: 사용자의 poll이 없으면 skip
    has_any_poll = session.query(Post.id).filter(
        Post.poll_data.isnot(None), Post.is_deleted == False,
        Post.author_id == user_id,
    ).first() is not None
    has_voted_poll = session.query(Post.id).join(Vote, Vote.post_id == Post.id).filter(
        Vote.user_id == user_id, Post.poll_data.isnot(None), Post.is_deleted == False
    ).first() is not None
    if not has_any_poll and not has_voted_poll:
        return
    candidates = []
    if has_voted_poll:
        voted_posts = (
            session.query(Post)
            .join(Vote, Vote.post_id == Post.id)
            .filter(Vote.user_id == user_id, Post.poll_data.isnot(None), Post.is_deleted == False)
            .limit(50)
            .all()
        )
        candidates.extend(voted_posts)
    if has_any_poll:
        authored_posts = (
            session.query(Post)
            .filter(Post.author_id == user_id, Post.poll_data.isnot(None), Post.is_deleted == False)
            .limit(50)
            .all()
        )
        for p in authored_posts:
            if p not in candidates and len(candidates) < 100:
                candidates.append(p)
    for post in candidates:
        expires_at = post.poll_data.get("expires_at") if post.poll_data else None
        if not expires_at:
            continue
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now:
                continue
        except (ValueError, TypeError):
            continue
        existing = (
            session.query(Notification)
            .filter_by(user_id=user_id, notification_type="poll_ended", post_id=post.id)
            .first()
        )
        if not existing:
            session.add(Notification(
                user_id=user_id,
                from_user_id=post.author_id,
                notification_type="poll_ended",
                post_id=post.id,
                metadata_json=json.dumps({"is_author": post.author_id == user_id}),
            ))
    session.commit()


interactions_router = APIRouter()
