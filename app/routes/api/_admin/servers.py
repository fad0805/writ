"""Remote-server federation admin endpoints (listing, search, mute/block/purge)."""

import re
import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import or_, func

from app.models import (
    User, Post, Follow, Like, Boost, Vote, Bookmark, Notification,
    FederationBlock, MutedServer, AdminLog,
)
from app.core.activitypub import _resolve_actor, _safe_httpx_get
from app.core.auth import require_auth
from app.utils.http import validate_url
from app.utils.log import log_admin_action
from app.utils.storage import get_storage
from app.db.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter()


def _domain_users(s, domain):
    """Return all remote User objects whose remote_url hostname matches domain."""
    candidates = s.query(User).filter(
        User.is_remote == True,
        or_(
            User.remote_url.like(f"https://{domain}/%"),
            User.remote_url.like(f"http://{domain}/%"),
        )
    ).all()
    result = []
    for u in candidates:
        if u.remote_url:
            parsed = urlparse(u.remote_url)
            if parsed.hostname == domain:
                result.append(u)
    return result


@router.get("/admin/remote-servers")
def api_admin_remote_servers(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        remote_users = s.query(User).filter(User.is_remote == True).all()
        domains = set()
        for u in remote_users:
            if u.remote_url:
                domain = urlparse(u.remote_url).hostname
                if domain:
                    domains.add(domain)
        return {"servers": sorted(domains)}


@router.get("/admin/remote-server/{domain:path}")
def api_admin_remote_server(domain: str, request: Request, offset: int = 0, limit: int = 20):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        candidates = s.query(User).filter(
            User.is_remote == True,
            or_(
                User.remote_url.like(f"https://{domain}/%"),
                User.remote_url.like(f"http://{domain}/%"),
            )
        ).all()
        domain_users = []
        for u in candidates:
            if u.remote_url:
                parsed = urlparse(u.remote_url)
                if parsed.hostname == domain:
                    domain_users.append(u)

        total_users = len(domain_users)
        remote_ids = [u.id for u in domain_users]

        local_following = 0
        local_followers = 0
        if remote_ids:
            local_following = s.query(Follow).filter(
                Follow.following_id.in_(remote_ids),
                Follow.accepted == True
            ).count()
            local_followers = s.query(Follow).filter(
                Follow.follower_id.in_(remote_ids),
                Follow.accepted == True
            ).count()

        is_blocked = s.query(FederationBlock).filter_by(domain=domain).first() is not None
        mute_entry = s.query(MutedServer).filter_by(domain=domain).first()
        is_muted = mute_entry is not None and mute_entry.muted
        is_media_muted = mute_entry is not None and mute_entry.media_muted

        try:
            if not validate_url(f"https://{domain}"):
                is_reachable = False
            else:
                resp = httpx.get(f"https://{domain}", timeout=5)
                is_reachable = resp.status_code < 500
        except:
            is_reachable = False

        paged = domain_users[offset:offset + limit + 1]
        has_more = len(paged) > limit
        paged = paged[:limit]

        return {
            "domain": domain,
            "total_users": total_users,
            "local_following": local_following,
            "local_followers": local_followers,
            "is_reachable": is_reachable,
            "is_blocked": is_blocked,
            "is_muted": is_muted,
            "is_media_muted": is_media_muted,
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "profile_image": u.profile_image,
                    "remote_url": u.remote_url,
                }
                for u in paged
            ],
            "has_more": has_more,
            "total_users_count": total_users,
            "server_icon": f"https://{domain}/favicon.ico",
        }


@router.get("/admin/federation-search")
def api_admin_federation_search(request: Request, q: str = ""):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    q = q.strip()
    logger.info("federation-search q=%r", q)
    if not q:
        return {"results": []}
    results = []
    # Try @handle@domain pattern
    if q.startswith("@") and "@" in q[1:]:
        parts = q[1:].split("@", 1)
        if len(parts) == 2:
            handle = parts[0].strip()
            domain = parts[1].strip()
            logger.info("federation-search handle=%r domain=%r", handle, domain)
            if not handle or not domain:
                return {"results": []}
            local_username = f"{handle}@{domain}"
            with get_session() as s:
                # Check remote users by exact match on username
                remote_user = s.query(User).filter(
                    User.username == local_username,
                    User.is_remote == True,
                ).first()
                logger.info("federation-search exact=%s id=%s", remote_user is not None, getattr(remote_user, 'id', None))
                if not remote_user:
                    remote_user = s.query(User).filter(
                        func.lower(User.username) == local_username.lower(),
                        User.is_remote == True,
                    ).first()
                    logger.info("federation-search casefold=%s id=%s", remote_user is not None, getattr(remote_user, 'id', None))
                if not remote_user:
                    all_remote = s.query(User).filter(
                        User.is_remote == True,
                        User.remote_url.isnot(None),
                    ).limit(500).all()
                    logger.info("federation-search scanning %d remote users for domain=%s handle=%s", len(all_remote), domain, handle)
                    for u in all_remote:
                        parsed = urlparse(u.remote_url)
                        if parsed.hostname and parsed.hostname.lower() == domain.lower():
                            uname = u.username.split("@")[0]
                            if uname.lower() == handle.lower():
                                remote_user = u
                                logger.info("federation-search found by url match: id=%s username=%s", u.id, u.username)
                                break
                if remote_user:
                    results.append({
                        "source": "remote_cached",
                        "id": remote_user.id,
                        "username": remote_user.username,
                        "display_name": remote_user.display_name,
                        "profile_image": remote_user.profile_image,
                        "remote_url": remote_user.remote_url,
                    })
                else:
                    # Try to resolve via ActivityPub
                    # Try actor URL patterns
                    actor_urls = [
                        f"https://{domain}/users/{handle}",
                        f"https://{domain}/@{handle}",
                        f"https://{domain}/u/{handle}",
                        f"https://{domain}/profile/{handle}",
                    ]
                    resolved = None
                    for url in actor_urls:
                        try:
                            resolved = _resolve_actor(url)
                            if resolved:
                                break
                        except Exception:
                            continue
                    if not resolved:
                        # Try WebFinger discovery
                        wf = _safe_httpx_get(
                            f"https://{domain}/.well-known/webfinger?resource=acct:{handle}@{domain}",
                            timeout=5,
                            max_size=2*1024*1024,
                        )
                        if wf is not None:
                            try:
                                wf_data = wf.json()
                                for link in wf_data.get("links", []):
                                    if link.get("rel") == "self" and link.get("type", "").endswith("activity+json"):
                                        href = link.get("href", "")
                                        if href:
                                            resolved = _resolve_actor(href)
                                            break
                            except (ValueError, TypeError):
                                pass
                    if resolved:
                        results.append({
                            "source": "remote_fetched",
                            "id": resolved.id,
                            "username": resolved.username,
                            "display_name": resolved.display_name,
                            "profile_image": resolved.profile_image,
                            "remote_url": resolved.remote_url,
                        })
    else:
        # Plain text: search local users and remote users by username
        with get_session() as s:
            local = s.query(User).filter(
                func.lower(User.username).contains(q.lower()),
                User.is_remote == False,
        ).limit(5).all()
            for u in local:
                results.append({
                    "source": "local",
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "profile_image": u.profile_image,
                    "remote_url": None,
                })
            # Also search remote users by username
            remote = s.query(User).filter(
                func.lower(User.username).contains(q.lower()),
                User.is_remote == True,
            ).limit(10).all()
            for u in remote:
                results.append({
                    "source": "remote_cached",
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "profile_image": u.profile_image,
                    "remote_url": u.remote_url,
                })
    return {"results": results}


@router.post("/admin/remote-server/{domain:path}/block")
def api_admin_remote_server_block(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        existing = s.query(FederationBlock).filter_by(domain=domain).first()
        if not existing:
            s.add(FederationBlock(domain=domain, reason="", created_by_id=user.id))
            s.commit()
    log_admin_action(user.id, user.username, "federation_block", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/remote-server/{domain:path}/unblock")
def api_admin_remote_server_unblock(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        s.query(FederationBlock).filter_by(domain=domain).delete()
        s.commit()
    log_admin_action(user.id, user.username, "federation_unblock", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/remote-server/{domain:path}/mute")
def api_admin_remote_server_mute(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        mute = s.query(MutedServer).filter_by(domain=domain).first()
        if not mute:
            mute = MutedServer(domain=domain, muted=True, media_muted=False, created_by_id=user.id)
            s.add(mute)
        else:
            mute.muted = True
        # Apply limit action to all users from this domain
        for u in _domain_users(s, domain):
            u.is_limited = True
            u.is_sensitive = True
            for p in s.query(Post).filter(Post.author_id == u.id, Post.visibility == "public").all():
                p.original_visibility = p.visibility
                p.visibility = "home"
        s.commit()
    log_admin_action(user.id, user.username, "server_mute", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/remote-server/{domain:path}/unmute")
def api_admin_remote_server_unmute(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        mute = s.query(MutedServer).filter_by(domain=domain).first()
        if mute:
            mute.muted = False
            # Only delete the row if both flags are off
            if not mute.media_muted:
                s.delete(mute)
        # Restore visibility for users from this domain
        for u in _domain_users(s, domain):
            u.is_limited = False
            u.is_sensitive = False
            for p in s.query(Post).filter(Post.author_id == u.id, Post.original_visibility != "").all():
                p.visibility = p.original_visibility
                p.original_visibility = ""
        s.commit()
    log_admin_action(user.id, user.username, "server_unmute", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/remote-server/{domain:path}/media-mute")
def api_admin_remote_server_media_mute(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        mute = s.query(MutedServer).filter_by(domain=domain).first()
        if not mute:
            mute = MutedServer(domain=domain, muted=False, media_muted=True, created_by_id=user.id)
            s.add(mute)
        else:
            mute.media_muted = True
        for u in _domain_users(s, domain):
            u.is_sensitive = True
        s.commit()
    log_admin_action(user.id, user.username, "server_media_mute", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/remote-server/{domain:path}/unmedia-mute")
def api_admin_remote_server_unmedia_mute(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        mute = s.query(MutedServer).filter_by(domain=domain).first()
        if mute:
            mute.media_muted = False
            if not mute.muted:
                s.delete(mute)
        # Only clear is_sensitive if the user is not also muted (which sets is_sensitive)
        for u in _domain_users(s, domain):
            mute_user = s.query(MutedServer).filter_by(domain=domain).first()
            if not mute_user or not mute_user.muted:
                u.is_sensitive = False
        s.commit()
    log_admin_action(user.id, user.username, "server_unmedia_mute", target_type="domain", target_username=domain, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/remote-server/{domain:path}/purge")
def api_admin_remote_server_purge(domain: str, request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    storage = get_storage()
    with get_session() as s:
        users = _domain_users(s, domain)
        user_ids = [u.id for u in users]
        # Delete stored avatar/header files first
        for u in users:
            if u.profile_image:
                storage.delete(u.profile_image)
            if u.header_image:
                storage.delete(u.header_image)
        if user_ids:
            # Delete follows involving these users
            s.query(Follow).filter(
                or_(Follow.follower_id.in_(user_ids), Follow.following_id.in_(user_ids))
            ).delete(synchronize_session=False)
            # Delete notifications
            s.query(Notification).filter(
                or_(Notification.from_user_id.in_(user_ids), Notification.user_id.in_(user_ids))
            ).delete(synchronize_session=False)
            # Delete likes, boosts, bookmarks
            s.query(Like).filter(Like.user_id.in_(user_ids)).delete(synchronize_session=False)
            s.query(Boost).filter(Boost.user_id.in_(user_ids)).delete(synchronize_session=False)
            s.query(Bookmark).filter(Bookmark.user_id.in_(user_ids)).delete(synchronize_session=False)
            s.query(Vote).filter(Vote.user_id.in_(user_ids)).delete(synchronize_session=False)
            # Convert mentions to the purged domain to plain text in local posts
            _esc = re.escape(domain)
            _mention_re = re.compile(
                r'<span class="h-card"[^>]*>'
                r'<a href="[^"]*' + _esc + r'[^"]*" class="u-url mention">'
                r'@<span>([^<]+)</span></a></span>'
            )
            _mention_re2 = re.compile(
                r'<a href="[^"]*' + _esc + r'[^"]*" class="mention">@([^<]+)</a>'
            )
            for _p in s.query(Post).filter(Post.author_id.notin_(user_ids), Post.content.contains(domain)).all():
                _new = _mention_re.sub(r'@\1@' + domain, _p.content)
                _new = _mention_re2.sub(r'@\1@' + domain, _new)
                if _new != _p.content:
                    _p.content = _new
            # Delete posts (FK: in_reply_to_id)
            for p in s.query(Post).filter(Post.author_id.in_(user_ids)).all():
                s.query(Post).filter(Post.in_reply_to_id == p.id).update({"in_reply_to_id": None})
                s.delete(p)
            # Finally delete the users
            s.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        # Delete AdminLog entries for this domain
        s.query(AdminLog).filter(
            AdminLog.target_type == "domain",
            AdminLog.target_username == domain,
        ).delete(synchronize_session=False)
        # Clean up federation blocks, mutes, muted_servers
        s.query(FederationBlock).filter_by(domain=domain).delete()
        s.query(MutedServer).filter_by(domain=domain).delete()
        s.commit()
    return {"ok": True}
