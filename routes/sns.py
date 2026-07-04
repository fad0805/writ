import re, os, urllib.request
from uuid import uuid4
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import desc, or_, and_
from sqlalchemy.orm import selectinload

from models import User, Post, Follow, Like, Boost, Notification, Novel, get_session
from routes.auth import require_auth, get_current_user
from activitypub import broadcast_to_followers, _post_to_inbox
from config import BASE_URL, DOMAIN, MAX_POST_LENGTH

AVATAR_DIR = "static/uploads/avatars"

def _save_avatar(image_url, user_id):
    if not image_url:
        return ""
    os.makedirs(AVATAR_DIR, exist_ok=True)
    ext = image_url.rsplit(".", 1)[-1].lower() if "." in image_url else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"
    filename = f"u{user_id}_{uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(AVATAR_DIR, filename)
    try:
        urllib.request.urlretrieve(image_url, filepath)
        return f"/{filepath}"
    except Exception:
        return ""

def _avatar_html(user, size=40, cls=""):
    if user.profile_image:
        return f'<img src="{user.profile_image}" alt="" class="{cls}">'
    initial = (user.display_name or user.username)[0].upper()
    bg = f"hsl({hash(user.username) % 360}, 55%, 50%)"
    fs = size // 2
    r = size // 5
    return f'<div class="{cls}" style="width:{size}px;height:{size}px;min-width:{size}px;border-radius:{r}px;background:{bg};display:inline-flex;align-items:center;justify-content:center;color:#fff;font-weight:bold;font-size:{fs}px">{initial}</div>'

router = APIRouter()

ICONS = {
    "home": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9.5L12 3l9 6.5V20a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1V9.5z"/></svg>',
    "home_solid": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="none"><path d="M12 3L2 9.5V20a1 1 0 001 1h6v-6h6v6h6a1 1 0 001-1V9.5L12 3z"/></svg>',
    "bell": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>',
    "bell_solid": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="none"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>',
    "book": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>',
    "book_solid": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="none"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>',
    "books": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="18" rx="1"/><rect x="12" y="5" width="3" height="16" rx="1"/><rect x="17" y="2" width="5" height="19" rx="1"/></svg>',
    "books_solid": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="none"><rect x="3" y="3" width="7" height="18" rx="1"/><rect x="12" y="5" width="3" height="16" rx="1"/><rect x="17" y="2" width="5" height="19" rx="1"/></svg>',
    "user": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    "user_solid": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="none"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    "settings": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.32 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>',
    "moon": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>',
    "globe": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>',
    "buildings": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="2" width="16" height="20" rx="2" ry="2"/><line x1="9" y1="6" x2="9" y2="10"/><line x1="15" y1="6" x2="15" y2="10"/></svg>',
    "users": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>',
    "lock": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>',
    "mail": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>',
    "star": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
    "star_filled": '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
    "reply": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>',
    "refresh": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>',
    "check": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    "edit": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
    "eye": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
    "tag": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>',
    "bar_chart": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    "document": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
    "trash": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
}

def _icon(name):
    return ICONS.get(name, "")

VISIBILITY_LABELS = {
    "public": "공개",
    "home": "홈",
    "followers": "팔로워",
    "mention": "멘션",
}

VISIBILITY_ICONS = {
    "public": "globe",
    "home": "home",
    "followers": "lock",
    "mention": "mail",
}

def parse_mentions(content):
    mentioned = set(re.findall(r'@(\w+)', content))
    if not mentioned:
        return []
    with get_session() as session:
        users = session.query(User).filter(User.username.in_(mentioned)).all()
        return [u.id for u in users]

def can_view_post(post, viewer, session):
    if post.is_deleted:
        return False
    if post.author_id == viewer.id:
        return True
    v = post.visibility or "public"
    if v == "public":
        return True
    if v == "home":
        return True
    if v == "followers":
        return session.query(Follow).filter_by(
            follower_id=viewer.id, following_id=post.author_id, accepted=True
        ).first() is not None
    if v == "mention":
        if post.mentioned_user_ids and viewer.id in post.mentioned_user_ids:
            return True
        # Also check content for @mention of the viewer
        if viewer.username and f"@{viewer.username}" in (post.content or ""):
            return True
        return False
    return True


TIMELINE_LABELS = {
    "federated": "연합",
    "local": "로컬",
    "social": "소셜",
    "home": "홈",
}

TIMELINE_ICONS = {
    "federated": "globe",
    "local": "buildings",
    "social": "users",
    "home": "home",
}

TIMELINE_DESCRIPTIONS = {
    "federated": "내 서버와 연합된 모든 서버의 공개 게시글",
    "local": "내 서버의 공개 게시글만",
    "social": "팔로잉 + 로컬 공개 게시글",
    "home": "팔로잉 게시글만",
}


def _get_timeline_posts(user, timeline_type, session):
    if timeline_type == "home":
        following_ids = [f.following_id for f in session.query(Follow).filter_by(
            follower_id=user.id, accepted=True
        ).all()]
        following_ids.append(user.id)
        posts = session.query(Post).filter(
            Post.author_id.in_(following_ids),
            Post.is_deleted == False,
        ).order_by(desc(Post.created_at)).limit(50).all()
        posts = [p for p in posts if can_view_post(p, user, session)]

    elif timeline_type == "social":
        following_ids = [f.following_id for f in session.query(Follow).filter_by(
            follower_id=user.id, accepted=True
        ).all()]
        following_ids.append(user.id)
        local_ids = [u.id for u in session.query(User).filter_by(is_remote=False).all()]
        posts = session.query(Post).filter(
            or_(
                Post.author_id.in_(following_ids),
                and_(Post.author_id.in_(local_ids), Post.visibility == "public"),
            ),
            Post.is_deleted == False,
        ).order_by(desc(Post.created_at)).limit(50).all()
        posts = [p for p in posts if can_view_post(p, user, session)]

    elif timeline_type == "local":
        local_ids = [u.id for u in session.query(User).filter_by(is_remote=False).all()]
        posts = session.query(Post).filter(
            Post.author_id.in_(local_ids),
            Post.visibility == "public",
            Post.is_deleted == False,
        ).order_by(desc(Post.created_at)).limit(50).all()

    else:  # federated
        posts = session.query(Post).filter(
            Post.visibility == "public",
            Post.is_deleted == False,
        ).order_by(desc(Post.created_at)).limit(50).all()

    feed = []
    for p in posts:
        liked = session.query(Like).filter_by(user_id=user.id, post_id=p.id).first() is not None
        boosted = session.query(Boost).filter_by(user_id=user.id, post_id=p.id).first() is not None
        feed.append((p, liked, boosted))
    return feed


@router.get("/", response_class=HTMLResponse)
def timeline_root(request: Request):
    return RedirectResponse(url="/timeline/home")


@router.get("/timeline/federated", response_class=HTMLResponse)
def timeline_federated(request: Request):
    return _timeline_view(request, "federated")


@router.get("/timeline/local", response_class=HTMLResponse)
def timeline_local(request: Request):
    return _timeline_view(request, "local")


@router.get("/timeline/social", response_class=HTMLResponse)
def timeline_social(request: Request):
    return _timeline_view(request, "social")


@router.get("/timeline/home", response_class=HTMLResponse)
def timeline_home(request: Request):
    return _timeline_view(request, "home")


def _timeline_view(request: Request, timeline_type: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with get_session() as session:
        feed = _get_timeline_posts(user, timeline_type, session)
        notifications = session.query(Notification).filter_by(
            user_id=user.id, is_read=False
        ).order_by(desc(Notification.created_at)).limit(10).all()

    return HTMLResponse(render_timeline(user, feed, notifications, timeline_type))


@router.post("/post")
def create_post(request: Request, content: str = Form(...), summary: str = Form(""), visibility: str = Form("public")):
    user = require_auth(request)
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    total_len = len(content) + len(summary)
    if total_len > MAX_POST_LENGTH:
        raise HTTPException(status_code=400, detail=f"Total length (content+CW) exceeds {MAX_POST_LENGTH} characters (currently {total_len})")

    if visibility not in ("public", "home", "followers", "mention"):
        visibility = "public"

    with get_session() as session:
        mentioned_ids = parse_mentions(content)
        post = Post(
            author_id=user.id,
            content=content,
            summary=summary,
            visibility=visibility,
            mentioned_user_ids=mentioned_ids,
        )
        session.add(post)
        session.flush()
        post.ap_id = f"{BASE_URL}/posts/{post.id}"

        # Create notifications for mentioned local users
        if mentioned_ids:
            for uid in mentioned_ids:
                if uid != user.id:
                    n = Notification(
                        user_id=uid,
                        from_user_id=user.id,
                        notification_type="mention",
                        post_id=post.id,
                    )
                    session.add(n)

        session.commit()

        # Broadcast to ActivityPub followers (unless mention-only)
        create_activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{BASE_URL}/activities/create/{post.id}",
            "type": "Create",
            "actor": user.actor_uri(),
            "object": post.to_ap_note(),
        }
        if visibility == "mention":
            # Send only to mentioned remote users
            if post.mentioned_user_ids:
                mentioned_users = session.query(User).filter(
                    User.id.in_(post.mentioned_user_ids), User.is_remote == True
                ).all()
                for mu in mentioned_users:
                    _post_to_inbox(mu.inbox_uri(), create_activity, user)
        else:
            broadcast_to_followers(user, create_activity)

    return RedirectResponse(url=request.headers.get("referer", "/"), status_code=303)


@router.post("/post/{post_id}/delete")
def delete_post(request: Request, post_id: int):
    user = require_auth(request)
    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id, author_id=user.id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.is_deleted = True
        session.commit()

        # Broadcast delete
        delete_activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"{BASE_URL}/activities/delete/{post.id}",
            "type": "Delete",
            "actor": user.actor_uri(),
            "object": post.ap_id,
        }
        broadcast_to_followers(user, delete_activity)

    return RedirectResponse(url=request.headers.get("referer", "/"), status_code=303)


@router.post("/post/{post_id}/edit")
def edit_post(request: Request, post_id: int, content: str = Form(...), summary: str = Form("")):
    user = require_auth(request)
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id, author_id=user.id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post.content = content
        post.summary = summary
        session.commit()
    return RedirectResponse(url=request.headers.get("referer", "/post/" + str(post_id)), status_code=303)


@router.post("/post/{post_id}/like")
def like_post(request: Request, post_id: int):
    user = require_auth(request)
    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        existing = session.query(Like).filter_by(user_id=user.id, post_id=post.id).first()
        if not existing:
            like = Like(user_id=user.id, post_id=post.id)
            session.add(like)

            if post.author_id != user.id:
                n = Notification(
                    user_id=post.author_id,
                    from_user_id=user.id,
                    notification_type="like",
                    post_id=post.id,
                )
                session.add(n)

                # ActivityPub broadcast
                like_activity = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{BASE_URL}/activities/like/{like.id}",
                    "type": "Like",
                    "actor": user.actor_uri(),
                    "object": post.ap_id,
                }
                if post.author.is_remote:
                    from activitypub import _post_to_inbox
                    _post_to_inbox(post.author.inbox_uri(), like_activity, user)

            session.commit()

    return RedirectResponse(url=request.headers.get("referer", "/"), status_code=303)


@router.post("/post/{post_id}/unlike")
def unlike_post(request: Request, post_id: int):
    user = require_auth(request)
    with get_session() as session:
        session.query(Like).filter_by(user_id=user.id, post_id=post_id).delete()

        post = session.query(Post).filter_by(id=post_id).first()
        if post and post.author.is_remote:
            undo = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{BASE_URL}/activities/undo/{post_id}",
                "type": "Undo",
                "actor": user.actor_uri(),
                "object": {
                    "id": f"{BASE_URL}/activities/like/{post_id}",
                    "type": "Like",
                    "actor": user.actor_uri(),
                    "object": post.ap_id,
                },
            }
            from activitypub import _post_to_inbox
            _post_to_inbox(post.author.inbox_uri(), undo, user)

        session.commit()

    return RedirectResponse(url=request.headers.get("referer", "/"), status_code=303)


@router.post("/post/{post_id}/boost")
def boost_post(request: Request, post_id: int):
    user = require_auth(request)
    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        if post.author_id != user.id and post.visibility in ("followers", "mention"):
            raise HTTPException(status_code=403, detail="이 글은 재게시할 수 없습니다")

        existing = session.query(Boost).filter_by(user_id=user.id, post_id=post.id).first()
        if not existing:
            boost = Boost(user_id=user.id, post_id=post.id)
            session.add(boost)

            if post.author_id != user.id:
                n = Notification(
                    user_id=post.author_id,
                    from_user_id=user.id,
                    notification_type="boost",
                    post_id=post.id,
                )
                session.add(n)

                announce = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{BASE_URL}/activities/announce/{boost.id}",
                    "type": "Announce",
                    "actor": user.actor_uri(),
                    "object": post.ap_id,
                }
                if post.author.is_remote:
                    from activitypub import _post_to_inbox
                    _post_to_inbox(post.author.inbox_uri(), announce, user)
                broadcast_to_followers(user, announce)

            session.commit()

    return RedirectResponse(url=request.headers.get("referer", "/"), status_code=303)


@router.post("/post/{post_id}/unboost")
def unboost_post(request: Request, post_id: int):
    user = require_auth(request)
    with get_session() as session:
        session.query(Boost).filter_by(user_id=user.id, post_id=post_id).delete()

        post = session.query(Post).filter_by(id=post_id).first()
        if post and post.author.is_remote:
            undo = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{BASE_URL}/activities/undo/{post_id}",
                "type": "Undo",
                "actor": user.actor_uri(),
                "object": {
                    "id": f"{BASE_URL}/activities/announce/{post_id}",
                    "type": "Announce",
                    "actor": user.actor_uri(),
                    "object": post.ap_id,
                },
            }
            from activitypub import _post_to_inbox
            _post_to_inbox(post.author.inbox_uri(), undo, user)

        session.commit()

    return RedirectResponse(url=request.headers.get("referer", "/"), status_code=303)


@router.get("/post/{post_id}", response_class=HTMLResponse)
def view_post(request: Request, post_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with get_session() as session:
        post = session.query(Post).filter_by(id=post_id, is_deleted=False).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        if not can_view_post(post, user, session):
            raise HTTPException(status_code=403, detail="이 글을 볼 수 없습니다")

        replies = session.query(Post).filter_by(
            in_reply_to_id=post.id, is_deleted=False
        ).all()
        # Filter replies by visibility
        replies = [r for r in replies if can_view_post(r, user, session)]
        replies.sort(key=lambda x: x.created_at)

        liked = session.query(Like).filter_by(user_id=user.id, post_id=post.id).first() is not None
        boosted = session.query(Boost).filter_by(user_id=user.id, post_id=post.id).first() is not None

    return HTMLResponse(render_post_detail(user, post, replies, liked, boosted))


@router.post("/post/{post_id}/reply")
def reply_to_post(request: Request, post_id: int, content: str = Form(...), visibility: str = Form("public")):
    user = require_auth(request)
    if not content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    if len(content) > MAX_POST_LENGTH:
        raise HTTPException(status_code=400, detail=f"Content exceeds {MAX_POST_LENGTH} characters")

    if visibility not in ("public", "home", "followers", "mention"):
        visibility = "public"

    with get_session() as session:
        parent = session.query(Post).filter_by(id=post_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Post not found")

        from models import Post as PostModel
        reply = PostModel(
            author_id=user.id,
            content=content,
            visibility=visibility,
            mentioned_user_ids=parse_mentions(content),
            in_reply_to_id=parent.id,
            in_reply_to_ap_id=parent.ap_id,
        )
        session.add(reply)
        session.flush()
        reply.ap_id = f"{BASE_URL}/posts/{reply.id}"
        session.commit()

        if parent.author_id != user.id:
            n = Notification(
                user_id=parent.author_id,
                from_user_id=user.id,
                notification_type="reply",
                post_id=reply.id,
            )
            session.add(n)

            # Send to remote
            if parent.author.is_remote:
                create_activity = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{BASE_URL}/activities/create/{reply.id}",
                    "type": "Create",
                    "actor": user.actor_uri(),
                    "object": reply.to_ap_note(),
                }
                from activitypub import _post_to_inbox
                _post_to_inbox(parent.author.inbox_uri(), create_activity, user)

            session.commit()

    return RedirectResponse(url=f"/post/{post_id}", status_code=303)


@router.get("/users/{username}", response_class=HTMLResponse)
def view_profile(request: Request, username: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with get_session() as session:
        profile_user = session.query(User).filter_by(username=username).first()
        if not profile_user:
            raise HTTPException(status_code=404, detail="User not found")

        q = session.query(Post).filter(
            Post.author_id == profile_user.id,
            Post.is_deleted == False,
        ).order_by(desc(Post.created_at)).limit(50)

        posts_raw = q.all()
        posts_raw = [p for p in posts_raw if can_view_post(p, user, session)]
        # Build dicts with reaction info while session is open
        posts = []
        for p in posts_raw:
            liked = session.query(Like).filter_by(user_id=user.id, post_id=p.id).first() is not None
            boosted = session.query(Boost).filter_by(user_id=user.id, post_id=p.id).first() is not None
            posts.append({
                "id": p.id,
                "content": p.content,
                "summary": p.summary,
                "visibility": p.visibility,
                "created_at": p.created_at,
                "likes_count": p.likes_count,
                "boosts_count": p.boosts_count,
                "replies_count": p.replies_count,
                "liked": liked,
                "boosted": boosted,
            })

        followers_count = session.query(Follow).filter_by(
            following_id=profile_user.id, accepted=True
        ).count()
        following_count = session.query(Follow).filter_by(
            follower_id=profile_user.id, accepted=True
        ).count()

        is_following = session.query(Follow).filter_by(
            follower_id=user.id, following_id=profile_user.id, accepted=True
        ).first() is not None

        novels = session.query(Novel).filter_by(
            author_id=profile_user.id, is_published=True
        ).order_by(desc(Novel.updated_at)).all()

        followers = session.query(Follow).filter_by(
            following_id=profile_user.id, accepted=True
        ).order_by(desc(Follow.created_at)).limit(50).all()

        following = session.query(Follow).filter_by(
            follower_id=profile_user.id, accepted=True
        ).order_by(desc(Follow.created_at)).limit(50).all()

    return HTMLResponse(render_profile(user, profile_user, posts, followers_count,
                                        following_count, is_following, novels,
                                        followers, following))


@router.post("/users/{username}/follow")
def follow_user(request: Request, username: str):
    user = require_auth(request)

    with get_session() as session:
        target = session.query(User).filter_by(username=username).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")

        if target.id == user.id:
            raise HTTPException(status_code=400, detail="Cannot follow yourself")

        existing = session.query(Follow).filter_by(
            follower_id=user.id, following_id=target.id
        ).first()
        if not existing:
            follow = Follow(follower_id=user.id, following_id=target.id, accepted=True)
            session.add(follow)

            n = Notification(
                user_id=target.id,
                from_user_id=user.id,
                notification_type="follow",
            )
            session.add(n)

            if target.is_remote:
                follow_activity = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{BASE_URL}/activities/follow/{follow.id}",
                    "type": "Follow",
                    "actor": user.actor_uri(),
                    "object": target.remote_url,
                }
                from activitypub import _post_to_inbox
                _post_to_inbox(target.inbox_uri(), follow_activity, user)

            session.commit()

    return RedirectResponse(url=f"/users/{username}", status_code=303)


@router.post("/users/{username}/unfollow")
def unfollow_user(request: Request, username: str):
    user = require_auth(request)

    with get_session() as session:
        target = session.query(User).filter_by(username=username).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")

        follow = session.query(Follow).filter_by(
            follower_id=user.id, following_id=target.id
        ).first()
        if follow:
            session.delete(follow)

            if target.is_remote:
                undo = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{BASE_URL}/activities/undo/{follow.id}",
                    "type": "Undo",
                    "actor": user.actor_uri(),
                    "object": {
                        "id": f"{BASE_URL}/activities/follow/{follow.id}",
                        "type": "Follow",
                        "actor": user.actor_uri(),
                        "object": target.remote_url,
                    },
                }
                from activitypub import _post_to_inbox
                _post_to_inbox(target.inbox_uri(), undo, user)

            session.commit()

    return RedirectResponse(url=f"/users/{username}", status_code=303)


@router.get("/users/profile/edit", response_class=HTMLResponse)
def profile_edit_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return HTMLResponse(render_profile_edit(user))


@router.post("/users/profile/update")
def update_profile(request: Request, image_url: str = Form(""),
                   display_name: str = Form(""), summary: str = Form("")):
    user = require_auth(request)
    local_path = _save_avatar(image_url, user.id)
    with get_session() as session:
        db_user = session.query(User).filter_by(id=user.id).first()
        db_user.profile_image = local_path or image_url
        db_user.display_name = display_name
        db_user.summary = summary
        session.commit()
    return RedirectResponse(url="/users/profile/edit", status_code=303)


@router.get("/notifications", response_class=HTMLResponse)
def view_notifications(request: Request, type: str = ""):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with get_session() as session:
        q = session.query(Notification).filter_by(user_id=user.id)
        if type:
            q = q.filter(Notification.notification_type == type)
        notifs_raw = q.options(
            selectinload(Notification.from_user)
        ).order_by(desc(Notification.created_at)).limit(50).all()
        # Build dicts while session is open
        notifs = []
        for n in notifs_raw:
            a = n.from_user
            notifs.append({
                "id": n.id,
                "notification_type": n.notification_type,
                "from_user_username": a.username,
                "from_user_display_name": a.display_name,
                "from_user_avatar_html": _avatar_html(a, 24, "sidebar-avatar"),
                "post_id": n.post_id,
                "is_read": n.is_read,
                "created_at": n.created_at,
            })

        # Mark all as read
        session.query(Notification).filter_by(user_id=user.id, is_read=False).update(
            {"is_read": True}
        )
        session.commit()

    return HTMLResponse(render_notifications(user, notifs, type))


@router.post("/notifications/read-all")
def read_all_notifications(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    with get_session() as session:
        session.query(Notification).filter_by(user_id=user.id, is_read=False).update({"is_read": True})
        session.commit()
    return RedirectResponse(url="/notifications", status_code=303)


@router.get("/mentions", response_class=HTMLResponse)
def view_mentions(request: Request):
    return RedirectResponse(url="/notifications?type=mention")


@router.get("/explore", response_class=HTMLResponse)
def explore(request: Request):
    return RedirectResponse(url="/timeline/local")


# ---- Render helpers ----

def _link_mentions(content):
    import re as _re
    return _re.sub(r'@(\w+)', r'<a href="/users/\1" class="mention-link">@\1</a>', content)

def _cw(content, summary):
    linked = _link_mentions(content)
    if not summary:
        return f'<div class="post-content">{linked}</div>'
    return f'<details class="cw-box"><summary>⚠️ {summary}</summary><div class="post-content">{linked}</div></details>'

def _vis_badge(p):
    vis = p["visibility"] if isinstance(p, dict) else p.visibility
    icon = VISIBILITY_ICONS.get(vis, "")
    return f'<span class="vis-badge vis-{vis}">{_icon(icon)}</span>'

def _timeline_tabs(current_tl):
    tabs = ""
    for tl_key in ("federated", "local", "social", "home"):
        active = ' class="active"' if tl_key == current_tl else ""
        label = TIMELINE_LABELS[tl_key]
        icon = _icon(TIMELINE_ICONS[tl_key])
        tabs += f'<a href="/timeline/{tl_key}"{active}>{icon} {label}</a>\n'
    return tabs


def _sidebar(user, active_nav=None, notifications=None):
    nav_items = [
        ("timeline", "/timeline/home", f'{_icon("home_solid")} 타임라인',
         ' <span class="notif-dot"></span>' if notifications else ""),
        ("notifications", "/notifications", f'{_icon("bell_solid")} 알림', ""),
        ("my_novels", "/novels/my", f'{_icon("book_solid")} 내 소설', ""),
        ("all_novels", "/novels", f'{_icon("books_solid")} 모든 소설', ""),
        ("profile", f"/users/{user.username}", f'{_icon("user_solid")} 내 프로필', ""),
    ]
    links = ""
    for key, href, label, suffix in nav_items:
        cls = ' class="active"' if key == active_nav else ""
        links += f'      <li><a href="{href}"{cls}>{label}{suffix}</a></li>\n'
    if getattr(user, 'is_admin', False):
        links += f'      <li><a href="/admin">{_icon("settings")} 관리</a></li>\n'

    return f"""  <nav class="sidebar">
    <div class="sidebar-header"><h2><a href="/timeline/home" class="sidebar-home-link">{_icon("books")} SNS+Novel</a></h2></div>
      <a href="/users/{user.username}" class="user-info-link">
        <div class="user-info">
          {_avatar_html(user, 40, "sidebar-avatar")}
          <div>
            <strong>{user.display_name or user.username}</strong>
            <span>@{user.username}</span>
          </div>
        </div>
      </a>
    <ul class="nav-links">
{links}    </ul>
    <div style="flex:1"></div>
    <button class="theme-toggle" >{_icon("moon")} 다크모드</button>
    <form method="post" action="/logout" style="margin-top:8px">
      <button type="submit" class="sidebar-btn">로그아웃</button>
    </form>
  </nav>"""

def _right_sidebar_widgets(user):
    with get_session() as session:
        all_novels = session.query(Novel).filter_by(author_id=user.id).order_by(desc(Novel.updated_at)).all()
        novels = all_novels[:3]
        notifs = session.query(Notification).filter_by(
            user_id=user.id, is_read=False
        ).order_by(desc(Notification.created_at)).limit(5).all()

    novel_items = "".join(
        f'<a href="/novels/{n.id}" class="novel-mini-card">'
        f'  <strong>{n.title}</strong>'
        f'  <span>총 {n.episode_count}화</span>'
        f'</a>'
        for n in novels
    )
    extra = len(all_novels) - 3
    more_link = f'<div style="text-align:right;margin-top:4px"><a href="/novels/my" style="font-size:0.85em;color:var(--text-muted)">더보기 +{extra}개</a></div>' if extra > 0 else ""

    notif_items = "".join(
        f'<div class="notif-item">'
        f'  <span class="notif-type">{n.notification_type}</span>'
        f'  <a href="/users/{n.from_user.username}">{n.from_user.display_name or n.from_user.username}</a>'
        f'</div>'
        for n in notifs
    )

    return f"""<div class="widget">
      <h4>{_icon("book")} 내 소설</h4>
      <div class="novel-mini-list">
        {novel_items if novel_items else '<p class="empty-small">연재 중인 소설이 없습니다.</p>'}
      </div>
      {more_link}
      <a href="/novels/new" class="btn btn-primary btn-small" style="width:100%;margin-top:8px">+ 새 소설 시작하기</a>
    </div>
    <div class="widget">
      <h4>{_icon("bell")} 알림</h4>
      <div class="notif-list">
        {notif_items if notif_items else ""}
      </div>
    </div>"""


def _right_sidebar(user):
    return f"""<aside class="right-sidebar">
    {_right_sidebar_widgets(user)}
  </aside>"""


def _post_card(p, liked, boosted, user):
    actions = f"""  <div class="post-actions" onclick="event.stopPropagation()">
    <a href="/post/{p.id}" class="action-btn">{_icon("reply")} {p.replies_count}</a>
    <form method="post" action="/post/{p.id}/{"unlike" if liked else "like"}" class="inline-form">
      <button type="submit" class="action-btn {"liked" if liked else ""}">{_icon("star_filled") if liked else _icon("star")} {p.likes_count}</button>
    </form>
    <form method="post" action="/post/{p.id}/{"unboost" if boosted else "boost"}" class="inline-form">
      <button type="submit" class="action-btn {"boosted" if boosted else ""}">{_icon("refresh")} {p.boosts_count}</button>
    </form>"""
    if p.author_id == user.id:
        actions += f"""
    <a href="/post/{p.id}" class="action-btn">{_icon("edit")}</a>
    <form method="post" action="/post/{p.id}/delete" class="inline-form">
      <button type="submit" class="action-btn" onclick="return confirm('삭제하시겠습니까?') && event.stopPropagation()">{_icon("trash")}</button>
    </form>"""
    actions += "\n  </div>"
    return f"""<div class="post-card" onclick="location.href='/post/{p.id}'">
  <div class="post-header" onclick="event.stopPropagation()">
    <a href="/users/{p.author.username}" class="post-author">{p.author.display_name or p.author.username}</a>
    <span class="post-username">@{p.author.username}</span>
    <span class="post-time">{_vis_badge(p)} {p.created_at.strftime("%Y-%m-%d %H:%M")}</span>
  </div>
  {_cw(p.content, p.summary)}
{actions}
</div>"""

def render_timeline(user, feed, notifications, timeline_type="federated"):
    items = "".join(_post_card(p, liked, boosted, user) for p, liked, boosted in feed)

    timeline_nav = _timeline_tabs(timeline_type)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{TIMELINE_LABELS.get(timeline_type, '타임라인')} - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user, active_nav="timeline", notifications=notifications)}
  <main class="main-content">
    <div class="post-form">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <h3>새 글 작성</h3>
        <div class="char-count" id="post-count-wrap" style="margin-bottom:0;padding-right:1ch"><span id="post-count">0</span>/{MAX_POST_LENGTH}</div>
      </div>
      <form method="post" action="/post">
        <textarea name="content" id="post-content" data-max-length="{MAX_POST_LENGTH}" rows="3" placeholder="무슨 생각을 하고 계신가요?" required oninput="updatePostCount()" onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter')this.form.requestSubmit()"></textarea>
        <input type="text" name="summary" id="post-summary" placeholder="CW (선택사항)" class="cw-input" oninput="updatePostCount()">
        <script src="/static/char-highlight.js"></script>
        <script>function updatePostCount(){{var a=document.getElementById('post-content'),b=document.getElementById('post-summary'),c=document.getElementById('post-count'),e=a.value.length+b.value.length;c.textContent=e;var t=a.closest('.post-form')||a.parentNode;t.classList.toggle('over-limit',e>{MAX_POST_LENGTH});t.classList.toggle('near-limit',e>{MAX_POST_LENGTH-50}&&e<={MAX_POST_LENGTH})}}</script>
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
          <div class="visibility-selector" style="margin-bottom:0">
            <label><input type="radio" name="visibility" value="public" checked>{_icon("globe")} 공개</label>
            <label><input type="radio" name="visibility" value="home">{_icon("home")} 홈</label>
            <label><input type="radio" name="visibility" value="followers">{_icon("lock")} 팔로워</label>
            <label><input type="radio" name="visibility" value="mention">{_icon("mail")} 멘션</label>
          </div>
          <button type="submit" class="btn btn-primary">게시</button>
        </div>
      </form>
    </div>
    <div class="timeline-tabs">{timeline_nav}</div>
    <div class="feed">
      {"<p class='empty-state'>표시할 글이 없습니다.</p>" if not feed else items}
    </div>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_post_detail(user, post, replies, liked, boosted):
    reply_items = "".join(
        f'<div class="post-card reply">'
        f'  <div class="post-header">'
        f'    <a href="/users/{r.author.username}" class="post-author">{r.author.display_name or r.author.username}</a>'
        f'    <span class="post-time">{_vis_badge(r)} {r.created_at.strftime("%Y-%m-%d %H:%M")}</span>'
        f'  </div>'
        f'  {_cw(r.content, r.summary)}'
        f'</div>'
        for r in replies
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>글 보기</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user)}
  <main class="main-content">
    <div class="post-card post-detail">
      <div class="post-header">
        <a href="/users/{post.author.username}" class="post-author">{post.author.display_name or post.author.username}</a>
        <span class="post-username">@{post.author.username}</span>
        <span class="post-time">{_vis_badge(post)} {post.created_at.strftime("%Y-%m-%d %H:%M")}</span>
      </div>
      {_cw(post.content, post.summary)}
      <div class="post-actions">
        <a href="/post/{post.id}" class="action-btn">{_icon("reply")} {post.replies_count}</a>
        <form method="post" action="/post/{post.id}/{"unlike" if liked else "like"}" class="inline-form">
          <button type="submit" class="action-btn {"liked" if liked else ""}">{_icon("star_filled") if liked else _icon("star")} {post.likes_count}</button>
        </form>
        <form method="post" action="/post/{post.id}/{"unboost" if boosted else "boost"}" class="inline-form">
          <button type="submit" class="action-btn {"boosted" if boosted else ""}">{_icon("refresh")} {post.boosts_count}</button>
        </form>
        {f'<a href="#" class="action-btn" onclick="document.getElementById(\'edit-form\').style.display=\'block\';this.style.display=\'none\';return false">{_icon("edit")}</a>' if post.author_id == user.id else ""}
        {f'<form method="post" action="/post/{post.id}/delete" class="inline-form"><button type="submit" class="action-btn" onclick="return confirm(\'삭제하시겠습니까?\')">{_icon("trash")}</button></form>' if post.author_id == user.id else ""}
      </div>
      {f'''
      <div id="edit-form" style="display:none;margin-top:12px">
        <form method="post" action="/post/{post.id}/edit">
          <textarea name="content" rows="3" style="margin-bottom:8px">{post.content}</textarea>
          <input type="text" name="summary" value="{post.summary or ""}" placeholder="CW" class="cw-input">
          <div style="display:flex;gap:8px;justify-content:flex-end">
            <button type="submit" class="btn btn-primary btn-small">저장</button>
            <button type="button" class="btn btn-outline btn-small" onclick="document.getElementById(\'edit-form\').style.display=\'none\';document.querySelector(\'[onclick*=\\\\\'edit-form\\\\\']\').style.display=\'\'">취소</button>
          </div>
        </form>
      </div>
      ''' if post.author_id == user.id else ""}
    </div>

    <div class="reply-form">
      <h4>답글 작성</h4>
      <form method="post" action="/post/{post.id}/reply">
        <textarea name="content" rows="2" placeholder="답글을 입력하세요..." required maxlength="{MAX_POST_LENGTH}"></textarea>
        <div class="visibility-selector">
          <label><input type="radio" name="visibility" value="public" checked>{_icon("globe")} 공개</label>
          <label><input type="radio" name="visibility" value="home">{_icon("home")} 홈</label>
          <label><input type="radio" name="visibility" value="followers">{_icon("lock")} 팔로워</label>
          <label><input type="radio" name="visibility" value="mention">{_icon("mail")} 멘션</label>
        </div>
        <button type="submit" class="btn btn-primary">답글</button>
      </form>
    </div>

    <div class="replies">
      <h4>답글 ({len(replies)})</h4>
      {reply_items if reply_items else "<p class='empty-state'>아직 답글이 없습니다.</p>"}
    </div>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_profile_edit(user):
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>프로필 수정 - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user)}
  <main class="main-content">
    <h2>프로필 수정</h2>
    <form method="post" action="/users/profile/update" class="novel-form">
      <div class="form-group">
        <label>프로필 이미지</label>
        {_avatar_html(user, 80, "profile-avatar")}
      </div>
      <div class="form-group">
        <label for="image_url">이미지 URL</label>
        <input type="text" id="image_url" name="image_url" value="{user.profile_image or ''}" placeholder="https://example.com/avatar.jpg">
      </div>
      <div class="form-group">
        <label for="display_name">표시 이름</label>
        <input type="text" id="display_name" name="display_name" value="{user.display_name or ''}" placeholder="사용자 표시 이름">
      </div>
      <div class="form-group">
        <label for="summary">소개글</label>
        <textarea id="summary" name="summary" rows="3" placeholder="자기소개">{user.summary or ''}</textarea>
      </div>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">저장</button>
        <a href="/users/{user.username}" class="btn btn-outline">취소</a>
      </div>
    </form>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_profile(user, profile_user, posts, followers_count, following_count, is_following, novels, followers, following):
    items = "".join(
        f'<div class="post-card" onclick="location.href=\'/post/{p["id"]}\'">'
        f'  <div class="post-header" onclick="event.stopPropagation()">'
        f'    <span class="post-author">{profile_user.display_name or profile_user.username}</span>'
        f'    <span class="post-time">{_vis_badge(p)} {p["created_at"].strftime("%Y-%m-%d %H:%M")}</span>'
        f'  </div>'
        f'  {_cw(p["content"], p["summary"])}'
        f'  <div class="post-actions" onclick="event.stopPropagation()">'
        f'    <a href="/post/{p["id"]}" class="action-btn">{_icon("reply")} {p["replies_count"]}</a>'
        f'    <form method="post" action="/post/{p["id"]}/{"unlike" if p["liked"] else "like"}" class="inline-form">'
        f'      <button type="submit" class="action-btn {"liked" if p["liked"] else ""}">{_icon("star_filled") if p["liked"] else _icon("star")} {p["likes_count"]}</button>'
        f'    </form>'
        f'    <form method="post" action="/post/{p["id"]}/{"unboost" if p["boosted"] else "boost"}" class="inline-form">'
        f'      <button type="submit" class="action-btn {"boosted" if p["boosted"] else ""}">{_icon("refresh")} {p["boosts_count"]}</button>'
        f'    </form>'
        f'  </div>'
        f'</div>'
        for p in posts
    )

    novels_html = "".join(
        f'<a href="/novels/{n.id}" class="profile-novel" style="display:block;text-decoration:none;color:inherit">'
        f'  <strong class="profile-novel-title">{n.title}</strong>'
        f'  <span class="profile-novel-meta">{n.episode_count}화 · {"완결" if n.is_completed else "연재중"}</span>'
        f'  <p class="profile-novel-desc">{n.description or "설명 없음"}</p>'
        f'</a>'
        for n in novels
    )

    followers_html = "".join(
        f'<a href="/users/{f.follower.username}" class="post-card" style="display:block;text-decoration:none;color:inherit">'
        f'<div class="profile-user-row">'
        f'  {_avatar_html(f.follower, 32, "sidebar-avatar")}'
        f'  <div>'
        f'    <strong style="color:var(--text-white)">{f.follower.display_name or f.follower.username}</strong>'
        f'    <br><span class="text-muted">@{f.follower.username}</span>'
        f'  </div>'
        f'</div>'
        f'</a>'
        for f in followers
    )

    following_html = "".join(
        f'<a href="/users/{f.following.username}" class="post-card" style="display:block;text-decoration:none;color:inherit">'
        f'<div class="profile-user-row">'
        f'  {_avatar_html(f.following, 32, "sidebar-avatar")}'
        f'  <div>'
        f'    <strong style="color:var(--text-white)">{f.following.display_name or f.following.username}</strong>'
        f'    <br><span class="text-muted">@{f.following.username}</span>'
        f'  </div>'
        f'</div>'
        f'</a>'
        for f in following
    )

    tab_js = """<script>
function switchTab(name) {
  document.querySelectorAll('.profile-tab-content').forEach(function(el) { el.style.display = 'none'; });
  document.querySelectorAll('.profile-stat').forEach(function(el) { el.classList.remove('active'); });
  document.getElementById('tab-' + name).style.display = 'block';
  var tab = document.querySelector('.profile-stat[onclick*="' + name + '"]');
  if (tab) tab.classList.add('active');
}
</script>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{profile_user.display_name or profile_user.username} - 프로필</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user)}
  <main class="main-content">
      <div class="profile-info">
        {_avatar_html(profile_user, 80, "profile-avatar")}
        {f'<a href="/users/profile/edit" style="position:absolute;bottom:0;right:0;font-size:0.85em;color:var(--text-muted)">{_icon("edit")} 편집</a>' if profile_user.id == user.id else ""}
        <div class="profile-info-text">
        <h2>{profile_user.display_name or profile_user.username}</h2>
        <p class="profile-username">@{profile_user.username}</p>
        <p class="profile-summary">{profile_user.summary or ""}</p>
        </div>
      </div>
        <div class="profile-stats">
          <span class="profile-stat active" onclick="switchTab('posts')"><strong>{len(posts)}</strong> 게시글</span>
          <span class="profile-stat" onclick="switchTab('novels')"><strong>{len(novels)}</strong> 소설</span>
          <span class="profile-stat" onclick="switchTab('followers')"><strong>{followers_count}</strong> 팔로워</span>
          <span class="profile-stat" onclick="switchTab('following')"><strong>{following_count}</strong> 팔로잉</span>
        </div>

    <div id="tab-posts" class="profile-tab-content">
      {items if items else "<p class='empty-state'>게시글이 없습니다.</p>"}
    </div>

    <div id="tab-novels" class="profile-tab-content" style="display:none">
      <div class="profile-novel-list">
        {novels_html if novels_html else "<p>소설이 없습니다.</p>"}
      </div>
    </div>

    <div id="tab-followers" class="profile-tab-content" style="display:none">
      {followers_html if followers_html else "<p class='empty-state'>팔로워가 없습니다.</p>"}
    </div>

    <div id="tab-following" class="profile-tab-content" style="display:none">
      {following_html if following_html else "<p class='empty-state'>팔로잉이 없습니다.</p>"}
    </div>

    {tab_js}
   </main>
   <aside class="right-sidebar">
{f'''
    <div class="widget">
      <h4>관리</h4>
      <form method="post" action="/users/{profile_user.username}/{"unfollow" if is_following else "follow"}">
        <button type="submit" class="btn btn-{"outline" if is_following else "primary"}">
          {is_following and "언팔로우" or "팔로우"}
        </button>
      </form>
    </div>
    ''' if profile_user.id != user.id else ""}
    {_right_sidebar_widgets(user)}
  </aside>
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_explore(user, feed):
    items = "".join(_post_card(p, liked, boosted, user) for p, liked, boosted in feed)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>탐색 - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user)}
  <main class="main-content">
    <h2>{_icon("globe")} 탐색</h2>
    <p class="subtitle">모든 사용자의 공개 글을 볼 수 있습니다.</p>
    <div class="feed">
      {items if items else "<p class='empty-state'>아직 글이 없습니다.</p>"}
    </div>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_mentions(user, posts):
    items = "".join(
        f'<div class="post-card">'
        f'  <div class="post-header">'
        f'    {p["avatar_html"]}'
        f'    <a href="/users/{p["author_username"]}" class="post-author">{p["author_display_name"] or p["author_username"]}</a>'
        f'    <span class="post-username">@{p["author_username"]}</span>'
        f'    <span class="post-time">{_vis_badge(p)} {p["created_at"].strftime("%Y-%m-%d %H:%M")}</span>'
        f'  </div>'
        f'  {_cw(p["content"], p["summary"])}'
        f'  <div class="post-actions">'
        f'    <a href="/post/{p["id"]}" class="action-btn">{_icon("reply")} {p["replies_count"]}</a>'
        f'  </div>'
        f'</div>'
        for p in posts
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>멘션 - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user, active_nav="mentions")}
  <main class="main-content">
    <h2>{_icon("mail")} 멘션</h2>
    <div class="feed">
      {items if items else "<p class='empty-state'>멘션된 글이 없습니다.</p>"}
    </div>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""


def render_notifications(user, notifs, filter_type=""):
    items = "".join(
        f'<div class="notif-card">'
        f'  <div class="notif-icon">{n["notification_type"]}</div>'
        f'  <div class="notif-body">'
        f'    {n["from_user_avatar_html"]}'
        f'    <a href="/users/{n["from_user_username"]}"><strong>{n["from_user_display_name"] or n["from_user_username"]}</strong></a>'
        f'    {"님이 회원님을 팔로우했습니다" if n["notification_type"] == "follow" else ""}'
        f'    {"님이 회원님의 글을 즐겨찾기했습니다" if n["notification_type"] == "like" else ""}'
        f'    {"님이 회원님의 글을 부스트했습니다" if n["notification_type"] == "boost" else ""}'
        f'    {"님이 회원님의 글에 답글을 달았습니다" if n["notification_type"] == "reply" else ""}'
        f'    {"님이 새 글을 작성했습니다" if n["notification_type"] == "post" else ""}'
        f'    {"님이 회원님을 멘션했습니다" if n["notification_type"] == "mention" else ""}'
        f'    <span class="notif-time">{n["created_at"].strftime("%m-%d %H:%M") if n["created_at"] else ""}</span>'
        f'  </div>'
        f'</div>'
        for n in notifs
    )

    notif_filters = [
        ("", "전체", _icon("bell")),
        ("like", "즐겨찾기", _icon("star_filled")),
        ("boost", "재게시", _icon("refresh")),
        ("follow", "팔로우", _icon("user_solid")),
        ("mention", "멘션", _icon("mail")),
    ]
    filter_tabs = "".join(
        f'<a href="/notifications{"?type=" + k if k else ""}" class="notif-tab{" active" if k == filter_type else ""}">{v}</a>'
        for k, _, v in notif_filters
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>알림 - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user, active_nav="notifications")}
  <main class="main-content">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2 style="margin:0">{_icon("bell")} 알림</h2>
      <form method="post" action="/notifications/read-all" style="display:inline">
        <button type="submit" class="btn btn-small" style="background:var(--accent);color:#fff;border:none">모두 읽음</button>
      </form>
    </div>
    <div class="notif-tabs">{filter_tabs}</div>
    <div class="notif-list">
      {items if items else "<p class='empty-state'>알림이 없습니다.</p>"}
    </div>
    <div class="notif-list">
      {items if items else "<p class='empty-state'>알림이 없습니다.</p>"}
    </div>
  </main>
  {_right_sidebar(user)}
</div>
<script src="/static/theme.js"></script></body>
</html>"""
