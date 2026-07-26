from app.routes.api.interactions._common import *

logger = logging.getLogger("writ.api.follow")

follow_router = APIRouter()



@follow_router.post("/users/{username}/follow")
def api_follow(request: Request, username: str):
    user = require_active_auth(request)
    if "@" in username and not username.startswith("@"):
        remote_username = username
        with get_session() as s:
            target = s.query(User).filter_by(username=remote_username).first()
            if not target:
                parts = remote_username.split("@")
                if len(parts) == 2:
                    actor_url = f"https://{parts[1]}/@{parts[0]}"
                    target = _resolve_actor(actor_url)
            if not target or not target.is_remote:
                raise HTTPException(status_code=404, detail="Remote user not found")
            existing = s.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
            if not existing:
                remote_obj = target.actor_uri()
                follow_activity = {
                    "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"],
                    "id": f"{BASE_URL}/activities/follow/{uuid4()}",
                    "type": "Follow",
                    "actor": user.actor_uri(),
                    "object": remote_obj,
                    "to": [remote_obj],
                }
                s.add(Follow(follower_id=user.id, following_id=target.id, accepted=False, activity_id=follow_activity["id"]))
                s.commit()
                inbox = target.inbox_url
                if inbox:
                    _post_to_inbox(inbox, follow_activity, user)
        return {"ok": True}

    with get_session() as s:
        target = s.query(User).filter_by(username=username, is_remote=False).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        if target.id == user.id:
            raise HTTPException(status_code=400, detail="Cannot follow yourself")
        existing = s.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
        if not existing:
            accepted = not target.is_locked
            s.add(Follow(follower_id=user.id, following_id=target.id, accepted=accepted))
            existing_notif = s.query(Notification).filter_by(
                from_user_id=user.id, user_id=target.id
            ).filter(Notification.notification_type.in_(["follow", "follow_request"])).first()
            if not existing_notif:
                s.add(Notification(user_id=target.id, from_user_id=user.id, notification_type="follow_request" if not accepted else "follow"))
            s.commit()
            broadcast_refresh_notifs(target.id)
            send_push_to_user(target.id, "follow" if accepted else "follow_request", user.username)
            broadcast_notif_sound(target.id)
    return {"ok": True}


@follow_router.post("/users/{username}/approve-follow")
def api_approve_follow(request: Request, username: str):
    user = require_active_auth(request)
    with get_session() as s:
        target = s.query(Follow).filter_by(
            following_id=user.id
        ).join(User, Follow.follower_id == User.id).filter(User.username == username).first()
        if not target:
            raise HTTPException(status_code=404, detail="Follow request not found")
        follower = s.query(User).get(target.follower_id)
        follower_is_remote = follower and follower.is_remote
        target.accepted = True
        s.query(Notification).filter_by(
            from_user_id=target.follower_id, user_id=user.id, notification_type="follow_request"
        ).update({"notification_type": "follow"})
        s.commit()
        if follower_is_remote and follower:
            try:
                follow_activity_id = target.activity_id or f"{follower.actor_uri()}#follows/{user.id}"
                inbox = follower.inbox_url or (follower.actor_uri().rstrip("/") + "/inbox")
                _send_accept(inbox, follow_activity_id, user, follower=follower)
            except Exception as e:
                logger.error("Failed to send Accept: %s", e, exc_info=True)
    return {"ok": True}

@follow_router.post("/users/{username}/remove-follower")
def api_remove_follower(request: Request, username: str):
    user = require_active_auth(request)
    with get_session() as s:
        follower = s.query(User).filter_by(username=username).first()
        if not follower:
            raise HTTPException(status_code=404, detail="User not found")
        follow = s.query(Follow).filter_by(
            follower_id=follower.id, following_id=user.id
        ).first()
        if not follow:
            raise HTTPException(status_code=404, detail="Not following you")
        s.query(Notification).filter(
            Notification.from_user_id == follower.id,
            Notification.user_id == user.id,
            Notification.notification_type.in_(["follow", "follow_request"])
        ).delete(synchronize_session=False)
        s.delete(follow)
        s.commit()
        try:
            broadcast_refresh_notifs(user.id)
        except Exception:
            pass
    return {"ok": True}

@follow_router.get("/follow-requests")
def api_list_follow_requests(request: Request):
    user = require_auth(request)
    with get_session() as s:
        pending = s.query(Follow).filter_by(following_id=user.id, accepted=False).all()
        return {"requests": [{"id": f.id, "user": _user_json(f.follower)} for f in pending]}


@follow_router.post("/users/{username}/reject-follow")
def api_reject_follow(request: Request, username: str):
    user = require_active_auth(request)
    with get_session() as s:
        target = s.query(Follow).filter_by(
            following_id=user.id
        ).join(User, Follow.follower_id == User.id).filter(User.username == username).first()
        if not target:
            raise HTTPException(status_code=404, detail="Follow request not found")
        follower = s.query(User).get(target.follower_id)
        follower_is_remote = follower and follower.is_remote
        s.query(Notification).filter_by(
            from_user_id=target.follower_id, user_id=user.id, notification_type="follow_request"
        ).delete()
        s.delete(target)
        s.commit()
        try:
            broadcast_refresh_notifs(user.id)
        except Exception:
            pass
        if follower_is_remote and follower:
            try:
                follow_activity_id = f"{follower.actor_uri()}#follows/{user.id}"
                inbox = follower.inbox_url or (follower.actor_uri().rstrip("/") + "/inbox")
                _send_reject(inbox, follow_activity_id, user, follower_actor_url=follower.actor_uri())
            except Exception as e:
                logger.error("Failed to send Reject: %s", e, exc_info=True)
    return {"ok": True}

@follow_router.post("/users/{username}/unfollow")
def api_unfollow(request: Request, username: str):
    user = require_active_auth(request)
    with get_session() as s:
        target = s.query(User).filter_by(username=username).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        existing = s.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
        if existing:
            s.delete(existing)
            s.query(Notification).filter(
                Notification.from_user_id == user.id,
                Notification.user_id == target.id,
                Notification.notification_type.in_(["follow", "follow_request"])
            ).delete(synchronize_session=False)
            s.commit()
            try:
                broadcast_refresh_notifs(target.id)
            except Exception:
                pass
            if target.is_remote and target.inbox_url:
                follow_activity_id = f"{user.actor_uri()}#follows/{target.id}"
                undo = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"{user.actor_uri()}#follows/{target.id}/undo",
                    "type": "Undo",
                    "actor": user.actor_uri(),
                    "object": {
                        "id": follow_activity_id,
                        "type": "Follow",
                        "actor": user.actor_uri(),
                        "object": target.actor_uri(),
                    },
                }
                try:
                    _post_to_inbox(target.inbox_url, undo, user)
                except Exception as e:
                    logger.error("Failed to send Undo Follow: %s", e, exc_info=True)
    return {"ok": True}


@follow_router.post("/users/{username}/toggle-notify")
def api_toggle_notify(request: Request, username: str):
    user = require_active_auth(request)
    with get_session() as s:
        target = s.query(User).filter_by(username=username).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        follow = s.query(Follow).filter_by(follower_id=user.id, following_id=target.id).first()
        if not follow:
            raise HTTPException(status_code=404, detail="Not following this user")
        follow.notify_on_post = not follow.notify_on_post
        s.commit()
        return {"ok": True, "notify_on_post": follow.notify_on_post}


@follow_router.get("/users/{username}/followers")
def api_followers(request: Request, username: str):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    with get_session() as s:
        target = s.query(User).filter_by(username=username, is_remote=False).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        follows = s.query(Follow).filter_by(following_id=target.id, accepted=True).order_by(desc(Follow.created_at)).all()
        users = [s.query(User).get(f.follower_id) for f in follows]
    return {"users": [_user_json(u) for u in users if u]}


@follow_router.get("/users/{username}/following")
def api_following(request: Request, username: str):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    with get_session() as s:
        target = s.query(User).filter_by(username=username, is_remote=False).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
