"""Mastodon poll endpoints for the v1 API."""
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from sqlalchemy import func

from fastapi import Depends
from app.db.database import get_db
from app.models import Post, Vote
from app.routes.mastodon_api._common import (
    MastodonAPIError,
    _require_bearer,
    _maybe_bearer,
    _status_json,
)
from app.core.visibility import _can_view

router = APIRouter()

@router.post("/v1/polls/{poll_id}/votes")
async def vote_poll(poll_id: str, request: Request, db: "SASession" = Depends(get_db)):
    from sqlalchemy.orm import Session as SASession

    user = _require_bearer(request, db)
    try:
        pid = int(poll_id)
    except ValueError:
        raise MastodonAPIError(status_code=404, detail="Record not found")

    return await _vote_poll_common(pid, request, db, user)


@router.post("/v1/statuses/{status_id}/poll/votes")
async def vote_status_poll(status_id: str, request: Request, db=Depends(get_db)):
    user = _require_bearer(request, db)
    try:
        pid = int(status_id)
    except ValueError:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    return await _vote_poll_common(pid, request, db, user)


@router.post("/v1/statuses/{status_id}/vote")
async def vote_status_old(status_id: str, request: Request, db=Depends(get_db)):
    user = _require_bearer(request, db)
    try:
        pid = int(status_id)
    except ValueError:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    return await _vote_poll_common(pid, request, db, user)

async def _extract_choices(request: Request) -> list[int]:
    import json

    ct = request.headers.get("content-type", "")
    choices = []
    try:
        if "json" in ct:
            try:
                body = await request.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                for k in ("choices", "choice", "option"):
                    if k in body and isinstance(body[k], list):
                        choices = [int(x) for x in body[k]]
                        break
                    if k in body and isinstance(body[k], (int, str)):
                        try:
                            choices = [int(body[k])]
                        except Exception:
                            pass
                        break
        if not choices:
            try:
                form = await request.form()
                for k in ("choices", "choice", "option", "poll[options]", "choices[]"):
                    if k in form:
                        v = form.getlist(k) if hasattr(form, "getlist") else [form[k]]
                        if v and isinstance(v[0], str) and v[0].isdigit():
                            choices = [int(v[0])]
                            break
            except Exception:
                pass
    except Exception:
        pass
    return choices


async def _vote_poll_common(pid: int, request: Request, db, user):
    post = db.query(Post).filter_by(id=pid, is_deleted=False).first()
    if not post or not post.poll_data:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    if not _can_view(post, user, db):
        raise MastodonAPIError(status_code=404, detail="Record not found")

    options = post.poll_data.get("options", [])
    choices = await _extract_choices(request)
    if not choices:
        try:
            import json

            body = request.scope.get("body")
            if body:
                data = json.loads(body) if isinstance(body, bytes) else json.loads(body)
                if isinstance(data, dict) and "choices" in data:
                    choices = [int(c) for c in data["choices"]]
        except Exception:
            pass

    if not choices:
        try:
            form = request._json  # no, not available; skip
        except Exception:
            pass

    # For single choice polls, take first
    choice_idx = choices[0] if choices else None
    if choice_idx is None:
        raise MastodonAPIError(status_code=400, detail="Invalid choice")

    if choice_idx < 0 or choice_idx >= len(options):
        raise MastodonAPIError(status_code=400, detail="Invalid choice")

    expires_at = post.poll_data.get("expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp < datetime.now(UTC):
                raise MastodonAPIError(status_code=400, detail="Poll has expired")
        except Exception:
            pass

    existing = db.query(Vote).filter_by(user_id=user.id, post_id=pid).first()
    if existing:
        if existing.option_index != choice_idx:
            existing.option_index = choice_idx
    else:
        db.add(Vote(user_id=user.id, post_id=pid, option_index=choice_idx, expires_at=expires_at))

    db.flush()
    votes = db.query(Vote.option_index, func.count(Vote.id).label("cnt")).filter(Vote.post_id == pid).group_by(Vote.option_index).all()
    counts = {v.option_index: v.cnt for v in votes}
    for i, opt in enumerate(options):
        opt["votes_count"] = counts.get(i, 0)
    db.query(Post).filter(Post.id == pid).update({"poll_data": {**post.poll_data, "options": options}}, synchronize_session=False)
    db.commit()
    db.refresh(post)

    viewer = user
    res = _status_json(post, db, viewer=viewer)
    if not res:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    poll = res.get("poll")
    if poll is None:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    return poll


@router.get("/v1/polls/{poll_id}")
def get_poll(poll_id: str, request: Request, db=Depends(get_db)):
    user = _maybe_bearer(request, db)
    try:
        pid = int(poll_id)
    except ValueError:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    post = db.query(Post).filter_by(id=pid, is_deleted=False).first()
    if not post or not post.poll_data:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    if not _can_view(post, user, db):
        raise MastodonAPIError(status_code=404, detail="Record not found")
    res = _status_json(post, db, viewer=user)
    if not res:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    poll = res.get("poll")
    if poll is None:
        raise MastodonAPIError(status_code=404, detail="Record not found")
    return poll
