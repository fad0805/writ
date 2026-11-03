"""Account data export/import endpoints extracted from _settings.py."""
import csv
import io
import json
import os
import re

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import desc

from app.config.settings import BASE_URL
from app.core.archive import (
    _posts_for_export,
    archive_job_json,
    cleanup_user_archives,
    run_archive_job,
    write_archive,
)
from app.core.auth import require_active_auth, require_auth
from app.core.threads import spawn
from app.db.database import get_session
from app.models import ArchiveJob, Bookmark, Follow, KeywordMute, Post, User, UserBlock, UserMute
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
                if post and not post.is_deleted:
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
            w.writerow([
                "id", "type", "content", "created_at",
                "boosted_at", "boost_of_author", "boost_of_url",
            ])
            for post, pointer in _posts_for_export(s, user.id):
                w.writerow([
                    post.id,
                    "boost" if pointer is not None else "post",
                    post.content or "",
                    str(post.created_at),
                    str(pointer.created_at) if pointer is not None else "",
                    post.author.username if pointer is not None else "",
                    (post.ap_id or post.remote_url or "") if pointer is not None else "",
                ])
        else:
            raise HTTPException(status_code=400, detail="Invalid type")
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={export_type}.csv"})


@export_router.get("/settings/export-counts")
def api_export_counts(request: Request):
    user = require_auth(request)
    with get_session() as s:
        follows = s.query(Follow).filter_by(follower_id=user.id, accepted=True).count()
        followers = s.query(Follow).filter_by(following_id=user.id, accepted=True).count()
        mutes = s.query(UserMute).filter_by(user_id=user.id).count()
        blocks = s.query(UserBlock).filter_by(user_id=user.id).count()
        bookmarks = s.query(Bookmark).join(
            Post, Bookmark.post_id == Post.id
        ).filter(
            Bookmark.user_id == user.id, Post.is_deleted == False
        ).count()
        filters = s.query(KeywordMute).filter_by(user_id=user.id).count()
        domains = set()
        for b in s.query(UserBlock).filter_by(user_id=user.id).all():
            target = s.query(User).get(b.target_user_id)
            if target and target.is_remote:
                domain = _domain_from_actor(target)
                if domain:
                    domains.add(domain)
    return {
        "items": [
            {"key": "follows", "name": "팔로우", "count": follows, "format": "CSV"},
            {"key": "followers", "name": "팔로워", "count": followers, "format": ""},
            {"key": "mutes", "name": "뮤트", "count": mutes, "format": "CSV"},
            {"key": "blocks", "name": "차단", "count": blocks, "format": "CSV"},
            {"key": "domain_blocks", "name": "도메인 차단", "count": len(domains), "format": "CSV"},
            {"key": "bookmarks", "name": "북마크", "count": bookmarks, "format": "CSV"},
            {"key": "filters", "name": "필터", "count": filters, "format": "JSON"},
        ]
    }


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
        keyword_mutes = [
            {"keyword": kw.keyword, "name": kw.name or "", "mode": kw.mode, "is_regex": kw.is_regex}
            for kw in s.query(KeywordMute).filter_by(user_id=user.id).all()
        ]
        return {"follows": follows, "mutes": mutes, "blocks": blocks, "bookmarks": bookmarks, "keyword_mutes": keyword_mutes}


@export_router.get("/settings/export-archive")
def api_export_archive(request: Request):
    """Synchronous compatibility download.

    The settings UI requests a server-side job instead; this endpoint stays for
    API clients and returns the exact same archive (profile + posts + series +
    media).
    """
    user = require_auth(request)
    buf = io.BytesIO()
    write_archive(user.id, buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename=writ_archive_{user.username}.zip"})


@export_router.post("/settings/import-data")
def api_import_data(request: Request, data: str = Form(...)):
    user = require_active_auth(request)
    try:
        payload = json.loads(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="잘못된 JSON 형식입니다.") from exc
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
    """Queue a server-side archive build.

    The ZIP is generated in the background and the owner receives an in-app and
    Web Push notification when it is ready. The file can be downloaded for
    ARCHIVE_RETENTION_DAYS (7 days by default), then it is removed automatically.
    """
    user = require_auth(request)
    cleanup_user_archives(user.id)
    with get_session() as s:
        active = s.query(ArchiveJob).filter(
            ArchiveJob.user_id == user.id,
            ArchiveJob.status.in_(["pending", "processing"]),
        ).order_by(desc(ArchiveJob.created_at)).first()
        if active:
            return {"ok": True, "job": archive_job_json(active), "already_running": True}

        job = ArchiveJob(user_id=user.id, status="pending")
        s.add(job)
        s.commit()
        job_id = job.id
        payload = archive_job_json(job)
    spawn(run_archive_job, job_id)
    return {"ok": True, "job": payload}


@export_router.get("/settings/archive-status")
def api_archive_status(request: Request):
    user = require_auth(request)
    cleanup_user_archives(user.id)
    with get_session() as s:
        job = s.query(ArchiveJob).filter_by(user_id=user.id).order_by(
            desc(ArchiveJob.created_at), desc(ArchiveJob.id)
        ).first()
        return {"job": archive_job_json(job)}


@export_router.get("/settings/archive-download/{job_uuid}")
def api_archive_download(request: Request, job_uuid: str):
    user = require_auth(request)
    cleanup_user_archives(user.id)
    with get_session() as s:
        job = s.query(ArchiveJob).filter_by(uuid=job_uuid, user_id=user.id).first()
        if not job:
            raise HTTPException(status_code=404, detail="아카이브를 찾을 수 없습니다.")
        if job.status != "completed" or not job.file_path:
            raise HTTPException(status_code=409, detail="아카이브가 아직 준비되지 않았습니다.")
        path = job.file_path
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="아카이브 파일이 삭제되었습니다.")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"writ_archive_{user.username}.zip",
    )
