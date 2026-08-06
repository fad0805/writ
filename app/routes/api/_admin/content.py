"Novel/episode/post content admin endpoints (search, sensitivity, CW)."

import re

from fastapi import APIRouter, Request, Form, HTTPException
from sqlalchemy import desc, or_
from sqlalchemy.orm import joinedload, selectinload

from app.models import Novel, Episode, Post
from app.utils.datetime import _fmt_dt
from app.utils.log import log_admin_action
from app.routes.api._novels import _novel_json, _apply_latest_activity_order
from app.db.database import get_session
from app.core.auth import require_auth

router = APIRouter()


@router.get("/admin/content/search")
def api_admin_content_search(request: Request, q: str = "", mode: str = "series"):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not q.strip():
        return {"novels": [], "episodes": []}
    with get_session() as s:
        query = q.strip()
        like = f"%{query}%"
        if mode == "episode":
            episodes = s.query(Episode).options(joinedload(Episode.novel)).filter(
                Episode.title.ilike(like)
            ).order_by(desc(Episode.created_at)).limit(50).all()
            return {"novels": [], "episodes": [{
                "id": ep.id, "title": ep.title, "number": ep.episode_number, "is_published": ep.is_published,
                "created_at": _fmt_dt(ep.created_at), "novel_id": ep.novel_id,
            } for ep in episodes]}
        else:
            novels_q = s.query(Novel).options(selectinload(Novel.author))
            if re.match(r'^\d+$', query):
                novels_q = novels_q.filter(
                    or_(Novel.title.ilike(like), Novel.id == int(query))
                )
            elif re.match(r'^[a-f0-9]{6,16}$', query):
                novels_q = novels_q.filter(
                    or_(Novel.title.ilike(like), Novel.number == query)
                )
            else:
                novels_q = novels_q.filter(Novel.title.ilike(like))
            novels = _apply_latest_activity_order(novels_q, s).limit(50).all()
            novel_ids = [n.id for n in novels]
            episodes = s.query(Episode).filter(
                Episode.novel_id.in_(novel_ids)
            ).order_by(desc(Episode.created_at)).all()
            ep_map: dict[int, list] = {}
            for ep in episodes:
                ep_map.setdefault(ep.novel_id, []).append({
                    "id": ep.id, "title": ep.title, "number": ep.episode_number, "is_published": ep.is_published,
                    "created_at": _fmt_dt(ep.created_at), "novel_id": ep.novel_id,
                })
            result = []
            for n in novels:
                nj = _novel_json(n, s)
                nj["episodes"] = ep_map.get(n.id, [])
                result.append(nj)
            return {"novels": result, "episodes": []}

@router.post("/admin/novels/{novel_id}/toggle-sensitive")
def api_admin_toggle_novel_sensitive(request: Request, novel_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        n = s.query(Novel).get(novel_id)
        if not n: raise HTTPException(status_code=404, detail="Novel not found")
        new_val = not (n.is_sensitive or False)
        s.query(Novel).filter_by(id=novel_id).update(
            {"is_sensitive": new_val}, synchronize_session=False
        )
        s.commit()
    return {"ok": True, "is_sensitive": new_val}


@router.post("/admin/novels/{novel_id}/set-visibility")
def api_admin_set_novel_visibility(request: Request, novel_id: int, visibility: str = Form("public")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if visibility not in ("public", "unlisted", "private"):
        raise HTTPException(status_code=400, detail="Invalid visibility")
    with get_session() as s:
        n = s.query(Novel).get(novel_id)
        if not n: raise HTTPException(status_code=404, detail="Novel not found")
        is_published = visibility != "private"
        s.query(Novel).filter_by(id=novel_id).update(
            {"visibility": visibility, "is_published": is_published},
            synchronize_session=False
        )
        s.commit()
    return {"ok": True, "visibility": visibility}


@router.post("/admin/episodes/{episode_id}/toggle-publish")
def api_admin_toggle_episode_publish(request: Request, episode_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        ep = s.query(Episode).get(episode_id)
        if not ep: raise HTTPException(status_code=404, detail="Episode not found")
        new_val = not ep.is_published
        s.query(Episode).filter_by(id=episode_id).update(
            {"is_published": new_val}, synchronize_session=False
        )
        s.commit()
        log_admin_action(user.id, user.username, "toggle_episode_publish", target_type="episode", target_id=episode_id, target_username=ep.novel.author.username if ep.novel else "", details=f"published={new_val}", ip_address=request.client.host if request.client else "")
    return {"ok": True, "is_published": new_val}

@router.post("/admin/posts/{post_id}/set-cw")
def api_admin_set_post_cw(request: Request, post_id: int, summary: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        tag = "[관리자 강제] "
        if not summary:
            summary = "규칙 위반 게시글"
        if not summary.startswith(tag):
            summary = tag + summary
        post.summary = summary
        s.commit()
        author_username = post.author.username
    log_admin_action(user.id, user.username, "set_post_cw", target_type="post", target_id=post_id, target_username=f"@{author_username}", details=summary, ip_address=request.client.host if request.client else "")
    return {"ok": True, "summary": summary}


@router.post("/admin/posts/{post_id}/remove-cw")
def api_admin_remove_post_cw(request: Request, post_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        post = s.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.summary = ""
        s.commit()
        author_username = post.author.username
    log_admin_action(user.id, user.username, "remove_post_cw", target_type="post", target_id=post_id, target_username=f"@{author_username}", ip_address=request.client.host if request.client else "")
    return {"ok": True}
