"""Shared helpers for the interactions package."""
import logging
import json
from datetime import datetime, timezone
from sqlalchemy import String, func, or_
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from app.models import User, Post, Vote, Notification
from app.utils.datetime import _fmt_dt
logger = logging.getLogger("writ.api.interactions")


def _json_array_has_user(column, user_id):
    """JSON 배열 컬럼에 user_id가 정확히 포함되어 있는지 확인"""
    if isinstance(column.type, postgresql.JSONB):
        return column.cast(JSONB).op('@>')(func.json_build_array(user_id).cast(JSONB))
    # SQLite fallback: '%{uid}%' LIKE는 2가 12/20/120을 매칭해 타인의 DM 스레드를
    # 노출하던 부정확 버그가 있었다. JSON 직렬화는 json.dumps → "[1, 2]" 형태이므로
    # 배열 요소 경계를 명시해 정확히 매칭한다.
    uid = str(user_id)
    return or_(
        column.cast(String).like(f'[{uid}]'),
        column.cast(String).like(f'[{uid},%'),
        column.cast(String).like(f'%, {uid},%'),
        column.cast(String).like(f'%, {uid}]'),
    )


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
