import html, re
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import desc, or_, and_
from sqlalchemy.orm import selectinload

from models import User, Post, Follow, Like, Boost, Notification, Novel, get_session
from routes.auth import require_auth, get_current_user
from activitypub import broadcast_to_followers, _post_to_inbox
from config import BASE_URL, MAX_POST_LENGTH

from routes.ui_components import _icon, _avatar_html, _save_avatar, ICONS

router = APIRouter()

AVATAR_DIR = "static/uploads/avatars"
# Removed local _save_avatar and _avatar_html definitions as they are now in ui_components.py
# If sns.py needs them, it should use the imported ones.
# Actually I need to make sure I don't break existing calls.

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
        posts = session.query(Post).options(
            selectinload(Post.parent).selectinload(Post.author)
        ).filter(
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
        posts = session.query(Post).options(
            selectinload(Post.parent).selectinload(Post.author)
        ).filter(
            or_(
                Post.author_id.in_(following_ids),
                and_(Post.author_id.in_(local_ids), Post.visibility == "public"),
            ),
            Post.is_deleted == False,
        ).order_by(desc(Post.created_at)).limit(50).all()
        posts = [p for p in posts if can_view_post(p, user, session)]

    elif timeline_type == "local":
        local_ids = [u.id for u in session.query(User).filter_by(is_remote=False).all()]
        posts = session.query(Post).options(
            selectinload(Post.parent).selectinload(Post.author)
        ).filter(
            Post.author_id.in_(local_ids),
            Post.visibility == "public",
            Post.is_deleted == False,
        ).order_by(desc(Post.created_at)).limit(50).all()

    else:  # federated
        posts = session.query(Post).options(
            selectinload(Post.parent).selectinload(Post.author)
        ).filter(
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

    referer = request.headers.get("referer", "/")
    redirect_url = "/timeline/home" if referer.endswith(f"/post/{post_id}") else referer
    return RedirectResponse(url=redirect_url, status_code=303)


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

        parent_post = None
        if post.in_reply_to_id:
            parent_post = session.query(Post).filter_by(
                id=post.in_reply_to_id, is_deleted=False
            ).first()
            if parent_post and not can_view_post(parent_post, user, session):
                parent_post = None

        ancestors = []
        ancestor_cursor = post
        seen_parent_ids = set()
        while ancestor_cursor.in_reply_to_id and ancestor_cursor.in_reply_to_id not in seen_parent_ids:
            seen_parent_ids.add(ancestor_cursor.in_reply_to_id)
            candidate = session.query(Post).filter_by(
                id=ancestor_cursor.in_reply_to_id, is_deleted=False
            ).first()
            if not candidate or not can_view_post(candidate, user, session):
                break
            ancestors.append(candidate)
            ancestor_cursor = candidate
        ancestors.reverse()

        thread_candidates = session.query(Post).options(
            selectinload(Post.author),
            selectinload(Post.parent).selectinload(Post.author),
        ).filter_by(is_deleted=False).order_by(Post.created_at).all()
        thread_candidates = [p for p in thread_candidates if can_view_post(p, user, session)]
        children_by_parent = {}
        for candidate in thread_candidates:
            children_by_parent.setdefault(candidate.in_reply_to_id, []).append(candidate)
        descendant_posts = []
        visited_thread_ids = set()
        def collect_descendants(current, depth=0):
            if current.id in visited_thread_ids:
                return
            visited_thread_ids.add(current.id)
            for child in children_by_parent.get(current.id, []):
                descendant_posts.append((child, depth))
                collect_descendants(child, depth + 1)
        collect_descendants(post, 0)

        replies = session.query(Post).filter_by(
            in_reply_to_id=post.id, is_deleted=False
        ).all()
        # Filter replies by visibility
        replies = [r for r in replies if can_view_post(r, user, session)]
        replies.sort(key=lambda x: x.created_at)

        liked = session.query(Like).filter_by(user_id=user.id, post_id=post.id).first() is not None
        boosted = session.query(Boost).filter_by(user_id=user.id, post_id=post.id).first() is not None

    return HTMLResponse(render_post_detail(user, post, replies, liked, boosted, parent_post, ancestors, descendant_posts))


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

        # Collect unique thread participants
        thread_usernames = set()
        curr = parent
        while curr:
            if curr.author_id != user.id:
                thread_usernames.add(curr.author.username)
            curr = curr.parent

        final_content = content.strip()
        # Add mentions if not already present
        for username in thread_usernames:
            mention = f"@{username}"
            if mention not in final_content:
                final_content = f"{mention} {final_content}"
        
        final_content = final_content.strip()
        
        if len(final_content) > MAX_POST_LENGTH:
            raise HTTPException(status_code=400, detail=f"Content exceeds {MAX_POST_LENGTH} characters")

        from models import Post as PostModel
        reply = PostModel(
            author_id=user.id,
            content=final_content,
            visibility=visibility,
            mentioned_user_ids=parse_mentions(final_content),
            in_reply_to_id=parent.id,
            in_reply_to_ap_id=parent.ap_id,
        )
        session.add(reply)
        session.flush()
        reply.ap_id = f"{BASE_URL}/posts/{reply.id}"
        
        # Create notifications for mentioned local users
        mentioned_ids = parse_mentions(final_content)
        for uid in mentioned_ids:
            if uid != user.id:
                n = Notification(
                    user_id=uid,
                    from_user_id=user.id,
                    notification_type="mention",
                    post_id=reply.id,
                )
                session.add(n)
        
        if parent.author_id != user.id:
            # Check if this parent notification is already handled by mention logic
            is_already_mentioned = parent.author_id in mentioned_ids
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

    return RedirectResponse(url=request.headers.get("referer", f"/post/{post_id}"), status_code=303)


@router.get("/users/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = require_auth(request)
    return HTMLResponse(render_user_settings(user))


@router.post("/users/settings")
def update_settings(request: Request, image_url: str = Form(""),
                    display_name: str = Form(""), summary: str = Form("")):
    user = require_auth(request)
    with get_session() as session:
        db_user = session.query(User).filter_by(id=user.id).first()
        if db_user:
            local_path = _save_avatar(image_url, db_user.id) if image_url and image_url != db_user.profile_image else ""
            db_user.profile_image = local_path or image_url
            db_user.display_name = display_name
            db_user.summary = summary
            session.commit()
    return RedirectResponse(url="/users/settings?saved=1", status_code=303)


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
                "parent": {
                    "id": p.parent.id,
                    "author_name": p.parent.author.display_name or p.parent.author.username,
                    "username": p.parent.author.username,
                    "content": p.parent.content,
                } if p.parent else None,
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

        novel_query = session.query(Novel).filter(Novel.author_id == profile_user.id)
        if profile_user.id == user.id:
            novels = novel_query.order_by(desc(Novel.updated_at)).all()
        else:
            novels = novel_query.filter(
                Novel.is_published == True,
                Novel.visibility.in_(("public", "unlisted")),
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
    notifs = []
    if not user:
        return RedirectResponse(url="/login")

    with get_session() as session:
        q = session.query(Notification).filter_by(user_id=user.id)
        if type == "mention":
            q = q.filter(Notification.notification_type.in_(["mention", "reply"]), Notification.post.has(Post.visibility != "mention"))
        elif type == "direct":
            q = q.filter(Notification.notification_type.in_(["mention", "reply"]), Notification.post.has(Post.visibility == "mention"))
        elif type:
            q = q.filter(Notification.notification_type == type)
        
        # Add a print or log here to debug
        # print(f"DEBUG: Type={type}, Query={q}")
        
        notifs_raw = q.options(
            selectinload(Notification.from_user),
            selectinload(Notification.post).selectinload(Post.author)
        ).order_by(desc(Notification.created_at)).limit(50).all()
        # Build dicts while session is open
        for n in notifs_raw:
            a = n.from_user
            notifs.append({
                "id": n.id,
                "notification_type": n.notification_type,
                "from_user_username": a.username,
                "from_user_display_name": a.display_name,
                "from_user_avatar_html": _avatar_html(a, 24, "sidebar-avatar"),
                "post_id": n.post_id,
                "post": {
                    "id": n.post.id,
                    "content": n.post.content,
                    "summary": n.post.summary,
                    "author": {
                        "id": n.post.author.id,
                        "username": n.post.author.username,
                        "display_name": n.post.author.display_name,
                        "profile_image": n.post.author.profile_image,
                    },
                    "created_at": n.post.created_at,
                    "likes_count": n.post.likes_count,
                    "boosts_count": n.post.boosts_count,
                    "replies_count": n.post.replies_count,
                    "visibility": n.post.visibility,
                    "liked": session.query(Like).filter_by(user_id=user.id, post_id=n.post.id).first() is not None,
                    "boosted": session.query(Boost).filter_by(user_id=user.id, post_id=n.post.id).first() is not None,
                } if n.post else None,
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
    return f'<details class="cw-box"><summary onclick="event.stopPropagation()">⚠️ {summary}</summary><div class="post-content">{linked}</div></details>'

def _reply_context_html(post, parent=None):
    parent = parent or (post.get("parent") if isinstance(post, dict) else getattr(post, "parent", None))
    if not parent:
        return ""
    parent_id = parent["id"] if isinstance(parent, dict) else parent.id
    author = parent["author_name"] if isinstance(parent, dict) else (parent.author.display_name or parent.author.username)
    username = parent["username"] if isinstance(parent, dict) else parent.author.username
    content = parent["content"] if isinstance(parent, dict) else parent.content
    summary = (content or "").replace("\n", " ")[:90]
    if len(content or "") > 90:
        summary += "..."
    return f'''<a href="/post/{parent_id}" class="reply-context" onclick="event.stopPropagation()">
      <span class="reply-context-label">답글 대상</span>
      <strong>{author}</strong><span>@{username}</span>
      <p>{summary}</p>
    </a>'''

def _vis_badge(p):
    vis = p["visibility"] if isinstance(p, dict) else p.visibility
    icon = VISIBILITY_ICONS.get(vis, "")
    return f'<span class="vis-badge vis-{vis}">{_icon(icon)}</span>'

def _vis_badge_from_data(vis):
    icon = VISIBILITY_ICONS.get(vis, "")
    return f'<span class="vis-badge vis-{vis}">{_icon(icon)}</span>'

def _timeline_tabs(current_tl):
    tabs = ""
    for tl_key in ("home", "social", "local", "federated"):
        active = ' class="active"' if tl_key == current_tl else ""
        label = TIMELINE_LABELS[tl_key]
        icon = _icon(TIMELINE_ICONS[tl_key])
        tabs += f'<a href="/timeline/{tl_key}"{active}>{icon} {label}</a>\n'
    return tabs


def _sidebar(user, active_nav=None, notifications=None):
    nav_items = [
        ("timeline", "/timeline/home", f'{_icon("home_solid")} 타임라인', ""),
        ("notifications", "/notifications", f'{_icon("bell_solid")} 알림' + 
         ('<span class="notif-dot"></span>' if notifications else ""), ""),
        ("divider1", None, None, None),
        ("explore", "/explore", f'{_icon("search")} 탐색', ""),
        ("divider2", None, None, None),
        ("my_novels", "/novels/my", f'{_icon("book_solid")} 내 소설', ""),
        ("all_novels", "/novels", f'{_icon("books_solid")} 모든 소설', ""),
        ("divider3", None, None, None),
        ("profile", f"/users/{user.username}", f'{_icon("user_solid")} 내 프로필', ""),
        ("divider4", None, None, None),
        ("settings", "/users/settings", f'{_icon("settings")} 설정 관리', ""),
    ]
    links = ""
    for key, href, label, suffix in nav_items:
        if key.startswith("divider"):
            links += '      <li class="nav-divider"></li>\n'
            continue
        cls = ' class="active"' if key == active_nav else ""
        label_html = label
        if suffix:
            label_html = f'<span style="display:flex; align-items:center; width:100%">{label}{suffix}</span>'
        links += f'      <li><a href="{href}"{cls}>{label_html}</a></li>\n'
    if getattr(user, 'is_admin', False):
        links += f'      <li><a href="/admin">{_icon("settings")} 관리</a></li>\n'

    return f"""  <nav class="sidebar">
    <div class="sidebar-header"><h2><a href="/timeline/home" class="sidebar-home-link">{_icon("books")} SNS+Novel</a></h2></div>
    <form action="/search" method="get" class="sidebar-search">
      <input type="text" name="q" placeholder="검색..." class="sidebar-search-input">
    </form>
      <a href="/users/{user.username}" class="user-info-link">
        <div class="user-info">
          {_avatar_html(user, 40, "sidebar-avatar")}
          <div class="user-info-text-mini">
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


def _post_card(p, liked=False, boosted=False, user=None):
    if not p: return ""
    # p is a dict now in notifications, let's handle both objects and dicts
    if isinstance(p, dict):
        p_id = p["id"]
        p_content = p["content"]
        p_summary = p["summary"]
        p_author = p["author"]
        p_created_at = p["created_at"]
        p_likes_count = p["likes_count"]
        p_boosts_count = p["boosts_count"]
        p_replies_count = p["replies_count"]
        p_visibility = p["visibility"]
        p_reply_context = "" # No easy context for dicts
    else:
        p_id = p.id
        p_content = p.content
        p_summary = p.summary
        p_author = p.author
        p_created_at = p.created_at
        p_likes_count = p.likes_count
        p_boosts_count = p.boosts_count
        p_replies_count = p.replies_count
        p_visibility = p.visibility
        p_reply_context = _reply_context_html(p)

    if isinstance(p_author, dict):
        author_id = p_author.get("id")
        display_name = p_author.get("display_name")
        username = p_author.get("username")
        profile_image = p_author.get("profile_image")
    else:
        author_id = p_author.id
        display_name = p_author.display_name
        username = p_author.username
        profile_image = p_author.profile_image

    reply_preview = html.escape((p_content or "").replace("\n", " ")[:180], quote=True)
    reply_author = html.escape(display_name or username, quote=True)
    
    # p_created_at = p.created_at # Not used here, removing for brevity
    # Actions
    actions = f"""  <div class="post-actions" onclick="event.stopPropagation()">
    <button type="button" class="action-btn" onclick="openReplyModal({p_id}, this.dataset.author, this.dataset.content)" data-author="{reply_author}" data-content="{reply_preview}">{_icon("reply")} {p_replies_count}</button>
    <form method="post" action="/post/{p_id}/{"unlike" if liked else "like"}" class="inline-form">
      <button type="submit" class="action-btn {"liked" if liked else ""}">{_icon("star_filled") if liked else _icon("star")} {p_likes_count}</button>
    </form>
    <form method="post" action="/post/{p_id}/{"unboost" if boosted else "boost"}" class="inline-form">
      <button type="submit" class="action-btn {"boosted" if boosted else ""}">{_icon("refresh")} {p_boosts_count}</button>
    </form>
    <div style="flex:1"></div>
"""

    if user and author_id == user.id:
        actions += f"""
    <a href="javascript:void(0)" class="action-btn" onclick="openEditModal({p_id}, '{p_content.replace(chr(10), '\\n')}', '{p_summary}')">{_icon("edit")}</a>
    <form method="post" action="/post/{p_id}/delete" class="inline-form">
      <button type="submit" class="action-btn" style="color:var(--danger)" onclick="return confirm('삭제하시겠습니까?') && event.stopPropagation()">{_icon("trash")}</button>
    </form>"""
    actions += "\n  </div>"
    
    return f"""<div class="post-card" onclick="location.href='/post/{p_id}'">
  <div class="post-header">
    {_avatar_html(p_author, 28, "post-author-avatar")}
    <a href="/post/{p_id}" class="post-author">{display_name or username}</a>
    <span class="post-username">@{username}</span>
    <span class="post-time">{_vis_badge_from_data(p_visibility)} {p_created_at.strftime("%Y-%m-%d %H:%M")}</span>
  </div>
  {p_reply_context}
  {_cw(p_content, p_summary)}
{actions}
</div>"""

def render_timeline(user, feed, notifications, timeline_type="federated"):
    items = "".join(_post_card(p, liked=liked, boosted=boosted, user=user) for p, liked, boosted in feed)

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

<div class="reply-modal-backdrop" id="reply-modal" onclick="closeReplyModal()">
<div class="reply-modal" onclick="event.stopPropagation()">
<button type="button" class="reply-modal-close" onclick="closeReplyModal()">×</button>
<h3>답글 작성</h3>
<div class="reply-modal-original">
  <strong id="reply-modal-author"></strong>
  <p id="reply-modal-content"></p>
</div>
<form method="post" id="reply-modal-form">
  <textarea name="content" rows="4" placeholder="답글을 입력하세요..." required maxlength="{MAX_POST_LENGTH}" onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter')this.form.requestSubmit()"></textarea>
  <div class="reply-form-footer">
    <div class="visibility-selector">
      <label><input type="radio" name="visibility" value="public" checked>{_icon("globe")} 공개</label>
      <label><input type="radio" name="visibility" value="home">{_icon("home")} 홈</label>
      <label><input type="radio" name="visibility" value="followers">{_icon("lock")} 팔로워</label>
      <label><input type="radio" name="visibility" value="mention">{_icon("mail")} 멘션</label>
    </div>
    <button type="submit" class="btn btn-primary">답글</button>
  </div>
</form>
</div>
</div>

<div class="reply-modal-backdrop" id="edit-modal" onclick="closeEditModal()">
<div class="reply-modal" onclick="event.stopPropagation()">
<button type="button" class="reply-modal-close" onclick="closeEditModal()">×</button>
<h3>글 수정</h3>
<div class="reply-modal-original">
  <strong>수정 전 원문</strong>
  <p id="edit-modal-original-content"></p>
</div>
<form method="post" id="edit-modal-form">
  <textarea name="content" rows="4" placeholder="내용을 수정하세요..." required maxlength="{{MAX_POST_LENGTH}}"></textarea>
  <input type="text" name="summary" placeholder="CW (선택사항)" class="cw-input" style="margin-top:10px">
  <div class="reply-form-footer" style="margin-top:15px">
    <div></div>
    <button type="submit" class="btn btn-primary">수정</button>
  </div>
</form>
</div>
</div>
<script>
function openReplyModal(postId, author, content) {{
var modal = document.getElementById('reply-modal');
var form = document.getElementById('reply-modal-form');
form.action = '/post/' + postId + '/reply';
document.getElementById('reply-modal-author').textContent = author;
document.getElementById('reply-modal-content').textContent = content;
form.querySelector('textarea').value = '';
modal.classList.add('active');
setTimeout(function() {{ form.querySelector('textarea').focus(); }}, 0);
}}
function closeReplyModal() {{
document.getElementById('reply-modal').classList.remove('active');
}}
function openEditModal(postId, content, summary) {{
var modal = document.getElementById('edit-modal');
var form = document.getElementById('edit-modal-form');
form.action = '/post/' + postId + '/edit';
form.querySelector('textarea').value = content;
form.querySelector('input[name="summary"]').value = summary;
document.getElementById('edit-modal-original-content').textContent = content;
modal.classList.add('active');
setTimeout(function() {{ form.querySelector('textarea').focus(); }}, 0);
}}
function closeEditModal() {{
document.getElementById('edit-modal').classList.remove('active');
}}
document.addEventListener('keydown', function(e) {{
if (e.key === 'Escape') {{
closeReplyModal();
closeEditModal();
if (document.activeElement.tagName === 'TEXTAREA' || document.activeElement.tagName === 'INPUT') {{
  document.activeElement.blur();
}}
}}
}});
</script>
<script src="/static/theme.js"></script></body>
</html>"""


def render_post_detail(user, post, replies, liked, boosted, parent_post=None, ancestors=None, descendant_posts=None):
    reply_preview = html.escape((post.content or "").replace("\n", " ")[:180], quote=True)
    reply_author = html.escape(post.author.display_name or post.author.username, quote=True)
    ancestors = ancestors or []
    descendant_posts = descendant_posts or []

    ancestor_items = "".join(
        f'<div class="thread-post ancestor" style="--thread-depth:{min(depth, 6)}" onclick="location.href=\'/post/{t.id}\'">'
        f'  <div class="post-header">'
        f'    {_avatar_html(t.author, 24, "post-author-avatar")}'
        f'    <a href="/post/{t.id}" class="post-author">{t.author.display_name or t.author.username}</a>'
        f'    <span class="post-username">@{t.author.username}</span>'
        f'    <span class="post-time">{_vis_badge(t)} {t.created_at.strftime("%Y-%m-%d %H:%M")}</span>'
        f'  </div>'
        f'  {_cw(t.content, t.summary)}'
        f'</div>'
        for depth, t in enumerate(ancestors)
    )

    reply_items = "".join(
        f'<div class="post-card reply" onclick="location.href=\'/post/{r.id}\'">'
        f'  <div class="post-header">'
        f'    {_avatar_html(r.author, 28, "post-author-avatar")}'
        f'    <a href="/post/{r.id}" class="post-author">{r.author.display_name or r.author.username}</a>'
        f'    <span class="post-username">@{r.author.username}</span>'
        f'    <span class="post-time">{_vis_badge(r)} {r.created_at.strftime("%Y-%m-%d %H:%M")}</span>'
        f'  </div>'
        f'  {_reply_context_html(r, post)}'
        f'  {_cw(r.content, r.summary)}'
        f'</div>'
        for r in replies
    )

    descendant_items = "".join(
        f'<div class="thread-post descendant" style="--thread-depth:{min(depth, 6)}" onclick="location.href=\'/post/{t.id}\'">'
        f'  <div class="post-header">'
        f'    {_avatar_html(t.author, 24, "post-author-avatar")}'
        f'    <a href="/post/{t.id}" class="post-author">{t.author.display_name or t.author.username}</a>'
        f'    <span class="post-username">@{t.author.username}</span>'
        f'    <span class="post-time">{_vis_badge(t)} {t.created_at.strftime("%Y-%m-%d %H:%M")}</span>'
        f'  </div>'
        f'  {_reply_context_html(t) if depth else ""}'
        f'  {_cw(t.content, t.summary)}'
        f'</div>'
        for t, depth in descendant_posts
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
    {f'<div class="thread-list thread-list-above">{ancestor_items}</div>' if ancestors else ''}
    <div class="post-card post-detail">
      <div class="post-header">
        {_avatar_html(post.author, 28, "post-author-avatar")}
        <a href="/post/{post.id}" class="post-author">{post.author.display_name or post.author.username}</a>
        <span class="post-username">@{post.author.username}</span>
        <span class="post-time">{_vis_badge(post)} {post.created_at.strftime("%Y-%m-%d %H:%M")}</span>
      </div>
      {_cw(post.content, post.summary)}
      <div class="post-actions">
        <button type="button" class="action-btn" onclick="openReplyModal({post.id}, this.dataset.author, this.dataset.content)" data-author="{{reply_author}}" data-content="{{reply_preview}}">{_icon("reply")} {post.replies_count}</button>
        <form method="post" action="/post/{post.id}/{{"unlike" if liked else "like"}}" class="inline-form">
          <button type="submit" class="action-btn {{"liked" if liked else ""}}">{_icon("star_filled") if liked else _icon("star")} {post.likes_count}</button>
        </form>
        <form method="post" action="/post/{post.id}/{{"unboost" if boosted else "boost"}}" class="inline-form">
          <button type="submit" class="action-btn {{"boosted" if boosted else ""}}">{_icon("refresh")} {post.boosts_count}</button>
        </form>
        {f'<a href="javascript:void(0)" class="action-btn" onclick="openEditModal({post.id}, \'{post.content.replace(chr(10), "\\n")}\', \'{post.summary or ""}\')">{_icon("edit")}</a>' if post.author_id == user.id else ""}
        {f'<form method="post" action="/post/{post.id}/delete" class="inline-form"><button type="submit" class="action-btn" onclick="return confirm(\'삭제하시겠습니까?\')">{_icon("trash")}</button></form>' if post.author_id == user.id else ""}
      </div>
    </div>

    <div class="thread-list thread-list-below">
      {descendant_items if descendant_items else ""}
    </div>

  </main>
  {_right_sidebar(user)}
</div>
<div class="reply-modal-backdrop" id="reply-modal" onclick="closeReplyModal()">
  <div class="reply-modal" onclick="event.stopPropagation()">
    <button type="button" class="reply-modal-close" onclick="closeReplyModal()">×</button>
    <h3>답글 작성</h3>
    <div class="reply-modal-original">
      <strong id="reply-modal-author"></strong>
      <p id="reply-modal-content"></p>
    </div>
    <form method="post" id="reply-modal-form">
      <textarea name="content" rows="4" placeholder="답글을 입력하세요..." required maxlength="{{MAX_POST_LENGTH}}" onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter')this.form.requestSubmit()"></textarea>
      <div class="reply-form-footer">
        <div class="visibility-selector">
          <label><input type="radio" name="visibility" value="public" checked>{{_icon("globe")}} 공개</label>
          <label><input type="radio" name="visibility" value="home">{{_icon("home")}} 홈</label>
          <label><input type="radio" name="visibility" value="followers">{{_icon("lock")}} 팔로워</label>
          <label><input type="radio" name="visibility" value="mention">{{_icon("mail")}} 멘션</label>
        </div>
        <button type="submit" class="btn btn-primary">답글</button>
      </div>
    </form>
  </div>
</div>

<div class="reply-modal-backdrop" id="edit-modal" onclick="closeEditModal()">
  <div class="reply-modal" onclick="event.stopPropagation()">
    <button type="button" class="reply-modal-close" onclick="closeEditModal()">×</button>
    <h3>글 수정</h3>
    <div class="reply-modal-original">
      <strong>수정 전 원문</strong>
      <p id="edit-modal-original-content"></p>
    </div>
    <form method="post" id="edit-modal-form">
      <textarea name="content" rows="4" placeholder="내용을 수정하세요..." required maxlength="{{MAX_POST_LENGTH}}"></textarea>
      <input type="text" name="summary" placeholder="CW (선택사항)" class="cw-input" style="margin-top:10px">
      <div class="reply-form-footer" style="margin-top:15px">
        <div></div>
        <button type="submit" class="btn btn-primary">수정</button>
      </div>
    </form>
  </div>
</div>
<script>
function openReplyModal(postId, author, content) {{
  var modal = document.getElementById('reply-modal');
  var form = document.getElementById('reply-modal-form');
  form.action = '/post/' + postId + '/reply';
  document.getElementById('reply-modal-author').textContent = author;
  document.getElementById('reply-modal-content').textContent = content;
  form.querySelector('textarea').value = '';
  modal.classList.add('active');
  setTimeout(function() {{ form.querySelector('textarea').focus(); }}, 0);
}}
function closeReplyModal() {{
  document.getElementById('reply-modal').classList.remove('active');
}}
function openEditModal(postId, content, summary) {{
  var modal = document.getElementById('edit-modal');
  var form = document.getElementById('edit-modal-form');
  form.action = '/post/' + postId + '/edit';
  form.querySelector('textarea').value = content;
  form.querySelector('input[name="summary"]').value = summary;
  document.getElementById('edit-modal-original-content').textContent = content;
  modal.classList.add('active');
  setTimeout(function() {{ form.querySelector('textarea').focus(); }}, 0);
}}
function closeEditModal() {{
  document.getElementById('edit-modal').classList.remove('active');
}}
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') {{
    closeReplyModal();
    closeEditModal();
    if (document.activeElement.tagName === 'TEXTAREA' || document.activeElement.tagName === 'INPUT') {{
      document.activeElement.blur();
    }}
  }}
}});
</script>
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


def render_user_settings(user):
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>설정 관리 - SNS+소설 블로그</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="layout">
{_sidebar(user, active_nav="settings")}
  <main class="main-content">
    <div class="page-header">
      <h2>{_icon("settings")} 설정 관리</h2>
    </div>
    <form method="post" action="/users/settings" class="novel-form">
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
        <button type="submit" class="btn btn-primary">설정 저장</button>
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
        f'  <div class="post-header">'
        f'    {_avatar_html(profile_user, 28, "post-author-avatar")}'
        f'    <span class="post-author">{profile_user.display_name or profile_user.username}</span>'
        f'    <span class="post-time">{_vis_badge(p)} {p["created_at"].strftime("%Y-%m-%d %H:%M")}</span>'
        f'  </div>'
        f'  {_reply_context_html(p)}'
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
        f'  <p class="novel-tags" style="margin-top:4px;font-size:0.85em;color:var(--accent);display:flex;align-items:center;gap:4px">{_icon("tag")}{n.tags or ""}</p>'
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
    items = "".join(_post_card(p, liked=liked, boosted=boosted, user=user) for p, liked, boosted in feed)

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
    # Restore missing icons in sns.py if needed (though they should be imported from ui_components)
    # The ICONS dictionary imported from ui_components should already contain "mention" and "direct"
    
    notif_icons = {
        "follow": "user_solid",
        "like": "star_filled",
        "boost": "refresh",
        "reply": "mention",
        "mention": "mention",
        "post": "bell_solid",
    }

    items = "".join(
        f'<div class="notif-card">'
        f'  <div class="notif-icon">{_icon(notif_icons.get(n["notification_type"], "bell"))}</div>'
        f'  <div class="notif-body">'
        f'    {n["from_user_avatar_html"]}'
        f'    <a href="/users/{n["from_user_username"]}"><strong>{n["from_user_display_name"] or n["from_user_username"]}</strong></a>'
        f'    {"님"}'
        f'    {"이 회원님을 팔로우했습니다" if n["notification_type"] == "follow" else ""}'
        f'    {"이 회원님의 글을 즐겨찾기했습니다" if n["notification_type"] == "like" else ""}'
        f'    {"이 회원님의 글을 부스트했습니다" if n["notification_type"] == "boost" else ""}'
        f'    {"이 회원님을 언급했습니다" if n["notification_type"] in ["reply", "mention"] else ""}'
        f'    {"이 새 글을 작성했습니다" if n["notification_type"] == "post" else ""}'
        f'    <span class="notif-time">{n["created_at"].strftime("%m-%d %H:%M") if n["created_at"] else ""}</span>'
        f'    {_post_card(n["post"], liked=n["post"].get("liked", False), boosted=n["post"].get("boosted", False), user=user) if n.get("post") else ""}'
        f'  </div>'
        f'</div>'
        for n in notifs
    )

    notif_filters = [
        ("", "전체", _icon("bell")),
        ("mention", "멘션", _icon("mention")),
        ("like", "즐겨찾기", _icon("star_filled")),
        ("boost", "재게시", _icon("refresh")),
        ("direct", "다이렉트", _icon("direct")),
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
  </main>
  {_right_sidebar(user)}
</div>
<div class="reply-modal-backdrop" id="reply-modal" onclick="closeReplyModal()">
  <div class="reply-modal" onclick="event.stopPropagation()">
    <button type="button" class="reply-modal-close" onclick="closeReplyModal()">×</button>
    <h3>답글 작성</h3>
    <div class="reply-modal-original">
      <strong id="reply-modal-author"></strong>
      <p id="reply-modal-content"></p>
    </div>
    <form method="post" id="reply-modal-form">
      <textarea name="content" rows="4" placeholder="답글을 입력하세요..." required maxlength="{MAX_POST_LENGTH}" onkeydown="if((event.ctrlKey||event.metaKey)&&event.key==='Enter')this.form.requestSubmit()"></textarea>
      <div class="reply-form-footer">
        <div class="visibility-selector">
          <label><input type="radio" name="visibility" value="public" checked>{_icon("globe")} 공개</label>
          <label><input type="radio" name="visibility" value="home">{_icon("home")} 홈</label>
          <label><input type="radio" name="visibility" value="followers">{_icon("lock")} 팔로워</label>
          <label><input type="radio" name="visibility" value="mention">{_icon("mail")} 멘션</label>
        </div>
        <button type="submit" class="btn btn-primary">답글</button>
      </div>
    </form>
  </div>
</div>

<div class="reply-modal-backdrop" id="edit-modal" onclick="closeEditModal()">
  <div class="reply-modal" onclick="event.stopPropagation()">
    <button type="button" class="reply-modal-close" onclick="closeEditModal()">×</button>
    <h3>글 수정</h3>
    <div class="reply-modal-original">
      <strong>수정 전 원문</strong>
      <p id="edit-modal-original-content"></p>
    </div>
    <form method="post" id="edit-modal-form">
      <textarea name="content" rows="4" placeholder="내용을 수정하세요..." required maxlength="{{MAX_POST_LENGTH}}"></textarea>
      <input type="text" name="summary" placeholder="CW (선택사항)" class="cw-input" style="margin-top:10px">
      <div class="reply-form-footer" style="margin-top:15px">
        <div></div>
        <button type="submit" class="btn btn-primary">수정</button>
      </div>
    </form>
  </div>
</div>
<script>
function openReplyModal(postId, author, content) {{
  var modal = document.getElementById('reply-modal');
  var form = document.getElementById('reply-modal-form');
  form.action = '/post/' + postId + '/reply';
  document.getElementById('reply-modal-author').textContent = author;
  document.getElementById('reply-modal-content').textContent = content;
  form.querySelector('textarea').value = '';
  modal.classList.add('active');
  setTimeout(function() {{ form.querySelector('textarea').focus(); }}, 0);
}}
function closeReplyModal() {{
  document.getElementById('reply-modal').classList.remove('active');
}}
function openEditModal(postId, content, summary) {{
  var modal = document.getElementById('edit-modal');
  var form = document.getElementById('edit-modal-form');
  form.action = '/post/' + postId + '/edit';
  form.querySelector('textarea').value = content;
  form.querySelector('input[name="summary"]').value = summary;
  document.getElementById('edit-modal-original-content').textContent = content;
  modal.classList.add('active');
  setTimeout(function() {{ form.querySelector('textarea').focus(); }}, 0);
}}
function closeEditModal() {{
  document.getElementById('edit-modal').classList.remove('active');
}}
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') {{
    closeReplyModal();
    closeEditModal();
    if (document.activeElement.tagName === 'TEXTAREA' || document.activeElement.tagName === 'INPUT') {{
      document.activeElement.blur();
    }}
  }}
}});
</script>
<script src="/static/theme.js"></script></body>
</html>"""
