"""Account data export/import endpoints extracted from _settings.py."""
import re
import json
import io
import csv
import zipfile

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.models import User, Post, Follow, UserMute, UserBlock, Bookmark, KeywordMute, Novel, Episode, Notification
from app.config.settings import BASE_URL
from app.db.database import get_session
from app.core.auth import require_auth, require_active_auth
from app.routes.api._settings import _domain_from_actor

export_router = APIRouter()


@export_router.get("/settings/export/{export_type}")
def api_export_account(request: Request, export_type: str):
    user = require_auth(request)
    buf = io.StringIO()
    w = csv.writer(buf)
    with get_session() as s:
        if export_type == "follows":
            w.writerow(["Account address", "Show boosts", "Notify on new posts"])
            follows = s.query(Follow).filter_by(follower_id=user.id, accepted=True).all()
            for f in follows:
                target = s.query(User).get(f.following_id)
                if target:
                    handle = target.username
                    w.writerow([handle, "true", "false"])
        elif export_type == "mutes":
            w.writerow(["Account address"])
            mutes = s.query(UserMute).filter_by(user_id=user.id).all()
            for m in mutes:
                target = s.query(User).get(m.target_user_id)
                if target:
                    handle = target.username
                    w.writerow([handle])
        elif export_type == "blocks":
            w.writerow(["Account address"])
            blocks = s.query(UserBlock).filter_by(user_id=user.id).all()
            for b in blocks:
                target = s.query(User).get(b.target_user_id)
                if target:
                    handle = target.username
                    w.writerow([handle])
        elif export_type == "bookmarks":
            w.writerow(["Post URL", "Created at"])
            bookmarks = s.query(Bookmark).filter_by(user_id=user.id).all()
            for bm in bookmarks:
                post = s.query(Post).get(bm.post_id)
                if post:
                    w.writerow([post.ap_id or f"{BASE_URL}/post/{post.id}", str(bm.created_at)])
        elif export_type == "keyword_mutes":
            w.writerow(["Keyword", "Whole word"])
            kw_mutes = s.query(KeywordMute).filter_by(user_id=user.id).all()
            for kw in kw_mutes:
                w.writerow([kw.keyword, "false"])
        elif export_type == "domain_blocks":
            w.writerow(["Domain"])
            blocks = s.query(UserBlock).filter_by(user_id=user.id).all()
            domains = set()
            for b in blocks:
                target = s.query(User).get(b.target_user_id)
                if target and target.is_remote:
                    domain = _domain_from_actor(target)
                    if domain:
                        domains.add(domain)
            for d in sorted(domains):
                w.writerow([d])
        elif export_type == "posts":
            w.writerow(["id", "content", "created_at"])
            posts = s.query(Post).filter_by(author_id=user.id, is_deleted=False).all()
            for p in posts:
                w.writerow([p.id, p.content or "", str(p.created_at)])
        else:
            raise HTTPException(status_code=400, detail="Invalid type")
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={export_type}.csv"})


@export_router.get("/settings/export-data")
def api_export_data(request: Request):
    user = require_auth(request)
    with get_session() as s:
        follows = []
        for f in s.query(Follow).filter_by(follower_id=user.id, accepted=True).all():
            target = s.query(User).get(f.following_id)
            if target:
                follows.append({"handle": target.username, "display_name": target.display_name, "notify_on_post": f.notify_on_post})
        mutes = []
        for m in s.query(UserMute).filter_by(user_id=user.id).all():
            target = s.query(User).get(m.target_user_id)
            if target:
                mutes.append({"handle": target.username, "display_name": target.display_name})
        blocks = []
        for b in s.query(UserBlock).filter_by(user_id=user.id).all():
            target = s.query(User).get(b.target_user_id)
            if target:
                blocks.append({"handle": target.username, "display_name": target.display_name})
        bookmarks = []
        for bm in s.query(Bookmark).filter_by(user_id=user.id).all():
            post = s.query(Post).get(bm.post_id)
            if post and not post.is_deleted:
                bookmarks.append({"url": post.ap_id or f"{BASE_URL}/post/{post.id}", "created_at": str(bm.created_at)})
        keyword_mutes = []
        for kw in s.query(KeywordMute).filter_by(user_id=user.id).all():
            keyword_mutes.append({"keyword": kw.keyword, "name": kw.name or "", "mode": kw.mode, "is_regex": kw.is_regex})
        return {"follows": follows, "mutes": mutes, "blocks": blocks, "bookmarks": bookmarks, "keyword_mutes": keyword_mutes}


@export_router.get("/settings/export-archive")
def api_export_archive(request: Request):
    user = require_auth(request)
    buf = io.BytesIO()
    with get_session() as s:
        posts = s.query(Post).filter_by(author_id=user.id, is_deleted=False).order_by(Post.created_at).all()
        posts_data = []
        for p in posts:
            posts_data.append({
                "id": p.id, "content": p.content or "", "summary": p.summary or "",
                "visibility": p.visibility, "created_at": str(p.created_at),
                "media_attachments": p.media_attachments or [],
                "poll_data": p.poll_data, "is_sensitive": p.is_sensitive,
            })
        novels = s.query(Novel).filter_by(author_id=user.id).order_by(Novel.created_at).all()
        novels_data = []
        for n in novels:
            eps = s.query(Episode).filter_by(novel_id=n.id).order_by(Episode.episode_number).all()
            episodes_data = []
            for e in eps:
                episodes_data.append({
                    "episode_number": e.episode_number, "title": e.title,
                    "content": e.content, "summary": e.summary or "",
                    "is_published": e.is_published, "created_at": str(e.created_at),
                })
            novels_data.append({
                "title": n.title, "description": n.description or "", "tags": n.tags or "",
                "status": n.status, "visibility": n.visibility,
                "is_sensitive": n.is_sensitive, "created_at": str(n.created_at),
                "episodes": episodes_data,
            })
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("posts.json", json.dumps(posts_data, ensure_ascii=False, indent=2))
        zf.writestr("novels.json", json.dumps(novels_data, ensure_ascii=False, indent=2))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename=writ_archive_{user.username}.zip"})


@export_router.post("/settings/import-data")
def api_import_data(request: Request, data: str = Form(...)):
    user = require_active_auth(request)
    try:
        payload = json.loads(data)
    except Exception:
        raise HTTPException(status_code=400, detail="잘못된 JSON 형식입니다.")
    imported = {"follows": 0, "mutes": 0, "blocks": 0, "bookmarks": 0, "keyword_mutes": 0}
    with get_session() as s:
        for item in payload.get("follows", []):
            handle = item.get("handle", "").strip().lower()
            if not handle:
                continue
            target = s.query(User).filter_by(username=handle, is_remote=False).first()
            if not target or target.id == user.id:
                continue
            exists = s.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
            if not exists:
                s.add(Follow(follower_id=user.id, following_id=target.id, accepted=True))
                imported["follows"] += 1
        for item in payload.get("mutes", []):
            handle = item.get("handle", "").strip().lower()
            if not handle:
                continue
            target = s.query(User).filter_by(username=handle, is_remote=False).first()
            if not target or target.id == user.id:
                continue
            exists = s.query(UserMute).filter_by(user_id=user.id, target_user_id=target.id).first()
            if not exists:
                s.add(UserMute(user_id=user.id, target_user_id=target.id))
                imported["mutes"] += 1
        for item in payload.get("blocks", []):
            handle = item.get("handle", "").strip().lower()
            if not handle:
                continue
            target = s.query(User).filter_by(username=handle, is_remote=False).first()
            if not target or target.id == user.id:
                continue
            exists = s.query(UserBlock).filter_by(user_id=user.id, target_user_id=target.id).first()
            if not exists:
                s.add(UserBlock(user_id=user.id, target_user_id=target.id))
                imported["blocks"] += 1
        for item in payload.get("bookmarks", []):
            url = item.get("url", "")
            if not url:
                continue
            post = s.query(Post).filter(Post.ap_id == url).first()
            if not post:
                m = re.search(r"/post/(\d+)", url)
                if m:
                    post = s.query(Post).filter_by(id=int(m.group(1))).first()
            if not post or post.is_deleted:
                continue
            exists = s.query(Bookmark).filter_by(user_id=user.id, post_id=post.id).first()
            if not exists:
                s.add(Bookmark(user_id=user.id, post_id=post.id))
                imported["bookmarks"] += 1
        for item in payload.get("keyword_mutes", []):
            keyword = item.get("keyword", "").strip()
            if not keyword:
                continue
            exists = s.query(KeywordMute).filter_by(user_id=user.id, keyword=keyword).first()
            if not exists:
                s.add(KeywordMute(user_id=user.id, keyword=keyword, name=item.get("name", ""), mode=item.get("mode", "or"), is_regex=item.get("is_regex", False)))
                imported["keyword_mutes"] += 1
        s.commit()
    return {"ok": True, "imported": imported}


@export_router.post("/settings/archive-request")
def api_archive_request(request: Request):
    user = require_auth(request)
    with get_session() as s:
        admins = s.query(User).filter(User.role.in_(["admin", "moderator", "owner"])).all()
        for admin in admins:
            if admin.id == user.id:
                continue
            s.add(Notification(
                user_id=admin.id, from_user_id=user.id,
                notification_type="moderation",
                metadata_json=json.dumps({"type": "archive_request", "user_id": user.id, "username": user.username}),
            ))
        s.commit()
    return {"ok": True, "message": "아카이브 요청이 접수되었습니다."}
