"""Interaction endpoints — follow, DM, notification, mute/block, like, boost, bookmark, vote, react, pin."""
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request, Form, HTTPException
import threading
from sqlalchemy import func

from app.models import Post, Vote
from app.serializers import _post_json
from app.config.settings import BASE_URL
from app.core.activitypub import _post_to_inbox
from app.db.database import get_session
from app.routes.auth import require_active_auth

from app.routes.api._core import _ap_fetch
from app.core.visibility import _can_view

logger = logging.getLogger("writ.api.polls")

polls_router = APIRouter()


@polls_router.post("/posts/{post_id}/vote")
def api_vote_post(request: Request, post_id: int, option: int = Form(...)):
    user = require_active_auth(request)
    remote_vote_data = None
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        options = post.poll_data.get("options", [])
        if option < 0 or option >= len(options):
            raise HTTPException(status_code=400, detail="Invalid option")
        expires_at = post.poll_data.get("expires_at")
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
                    raise HTTPException(status_code=400, detail="Poll has ended")
            except (ValueError, TypeError):
                pass
        existing = s.query(Vote).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            old_option = existing.option_index
            if old_option == option:
                return {"ok": True}
            existing.option_index = option
        else:
            s.add(
                Vote(
                    user_id=user.id,
                    post_id=post_id,
                    option_index=option,
                    expires_at=post.poll_data.get("expires_at") or None
                )
            )
        s.flush()
        votes = s.query(Vote.option_index, func.count(Vote.id).label("cnt")).filter(Vote.post_id == post_id).group_by(Vote.option_index).all()
        counts = {v.option_index: v.cnt for v in votes}
        for i, opt in enumerate(options):
            opt["votes_count"] = counts.get(i, 0)
        s.query(Post).filter(Post.id == post_id).update({"poll_data": {**post.poll_data, "options": options}}, synchronize_session=False)
        s.flush()
        s.refresh(post)
        post_json = _post_json(post, s, user)
        if post.ap_id and post.author and post.author.is_remote:
            inbox = post.author.shared_inbox_url or post.author.inbox_url
            if inbox:
                remote_vote_data = (post.ap_id, post.author.actor_uri(), inbox, options[option]["text"])
        s.commit()
    if remote_vote_data:
        ap_id, author_uri, inbox, option_text = remote_vote_data

        def _deliver_remote_vote():
            vote_activity = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{BASE_URL}/votes/{uuid4()}/activity",
                "type": "Create",
                "actor": user.actor_uri(),
                "object": {
                    "id": f"{BASE_URL}/votes/{uuid4()}",
                    "type": "Note",
                    "name": option_text,
                    "attributedTo": user.actor_uri(),
                    "to": [author_uri],
                    "inReplyTo": ap_id,
                },
                "to": [author_uri],
            }
            try:
                _post_to_inbox(inbox, vote_activity, user)
            except Exception:
                pass

        threading.Thread(target=_deliver_remote_vote, daemon=True).start()
    return {"ok": True, "post": post_json}


@polls_router.post("/posts/{post_id}/unvote")
def api_unvote_post(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        existing = s.query(Vote).filter_by(user_id=user.id, post_id=post_id).first()
        if existing:
            options = post.poll_data.get("options", [])
            s.delete(existing)
            s.flush()
            votes = s.query(Vote.option_index, func.count(Vote.id).label("cnt")).filter(Vote.post_id == post_id).group_by(Vote.option_index).all()
            counts = {v.option_index: v.cnt for v in votes}
            for i, opt in enumerate(options):
                opt["votes_count"] = counts.get(i, 0)
            s.query(Post).filter(Post.id == post_id).update({"poll_data": {**post.poll_data, "options": options}}, synchronize_session=False)
            s.commit()
            s.expire_all()
    return {"ok": True}


@polls_router.post("/posts/{post_id}/refresh-poll")
def api_refresh_poll(request: Request, post_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post or poll not found")
        if not _can_view(post, user, s):
            raise HTTPException(status_code=404, detail="Post not found")
        if not post.ap_id:
            raise HTTPException(status_code=400, detail="Local poll has nothing to refresh")
    remote_data = _ap_fetch(post.ap_id, user)
    if not remote_data:
        raise HTTPException(status_code=502, detail="Failed to fetch remote poll")
    obj = remote_data.get("object", remote_data) if isinstance(remote_data, dict) else {}
    if not isinstance(obj, dict):
        raise HTTPException(status_code=502, detail="Invalid remote response")

    one_of = obj.get("oneOf") or obj.get("anyOf") or []
    if not isinstance(one_of, list) or not one_of:
        raise HTTPException(status_code=502, detail="Remote object has no poll data")

    new_options = []
    for opt in one_of:
        if isinstance(opt, dict) and opt.get("name"):
            replies = opt.get("replies", {})
            votes_count = 0
            if isinstance(replies, dict):
                votes_count = replies.get("totalItems", 0)
            new_options.append({"text": opt["name"], "votes_count": votes_count})

    if not new_options:
        raise HTTPException(status_code=502, detail="No valid poll options found")

    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post or not post.poll_data:
            raise HTTPException(status_code=404, detail="Post not found")
        old_options = post.poll_data.get("options", [])
        text_to_old = {o.get("text", ""): o for o in old_options}
        for new_opt in new_options:
            old = text_to_old.get(new_opt["text"])
            if old:
                new_opt["votes_count"] = max(new_opt.get("votes_count", 0), old.get("votes_count", 0))

        new_expires = obj.get("endTime") or post.poll_data.get("expires_at", "")
        post.poll_data = {
            "options": new_options,
            "expires_at": new_expires,
        }
        s.commit()
        s.expire_all()

        post = s.query(Post).filter_by(id=post_id).first()
        updated = _post_json(post, s, user)

    return {"ok": True, "post": updated}
