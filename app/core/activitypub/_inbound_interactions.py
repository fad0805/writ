import datetime
import json
import logging
import uuid
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.config.settings import BASE_URL
from app.core.activitypub._emoji import _background_import_emoji, _process_emoji_tags
from app.core.activitypub._fetch import _fetch_remote_post, _resolve_actor
from app.core.activitypub._inbound_common import (
    _broadcast_emoji_list,
    _build_reactions,
    _notify_admins,
    _sanitize_reaction,
)
from app.core.activitypub._utils import _get_instance_actor
from app.core.broadcast import broadcast_post
from app.core.push import send_push_to_user
from app.core.threads import spawn
from app.core.timeline_stream import (
    broadcast_delete,
    broadcast_notif_sound,
    broadcast_reaction_update,
    broadcast_refresh_notifs,
)
from app.db.database import get_session
from app.models import (
    Boost,
    CustomEmoji,
    Follow,
    Like,
    Notification,
    Post,
    ProcessedActivity,
    Report,
    User,
    UserBlock,
    Vote,
)
from app.utils.alias import actor_urls_include
from app.utils.content_parser import _sanitize_html, process_post_content
from app.utils.crypto import generate_keypair
from app.utils.emoji import _refresh_emoji_cache_forcibly
from app.utils.http import WRIT_USER_AGENT, validated_get
from app.utils.urls import parse_username_from_url

logger = logging.getLogger("writ.activitypub")


def _handle_like(activity: dict) -> tuple[int, str]:
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    object_url = activity["object"] if isinstance(activity.get("object"), str) else ""
    activity_id = activity.get("id", "")
    reaction = _sanitize_reaction(activity.get("_misskey_reaction", activity.get("content", activity.get("reaction", ""))))

    if not object_url:
        return (200, "OK")

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        _sign_as = session.query(User).get(post.author_id) if post else None
    actor = _resolve_actor(actor_url, sign_as=_sign_as)
    if not actor:
        return (404, "Actor not found")

    actor_id = actor.id
    actor_username = actor.username

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if not post:
            return (200, "OK")

        # Process remote emoji if present in tag array
        if reaction and reaction.startswith(":") and reaction.endswith(":"):
            _kw = reaction[1:-1]
            _existing_emoji = session.query(CustomEmoji).filter_by(keyword=_kw).first()
            if not _existing_emoji:
                _import_data = {"kw": _kw}
                tags = activity.get("tag", []) or []
                for _tag in tags:
                    if isinstance(_tag, dict) and _tag.get("type") == "Emoji":
                        _icon = _tag.get("icon", {})
                        _import_data["url"] = _icon.get("url", "") if isinstance(_icon, dict) else ""
                        _import_data["domain"] = urlparse(_tag.get("id", "")).netloc if _tag.get("id", "") else ""
                        break
                if _import_data.get("url"):
                    spawn(_background_import_emoji, _import_data["url"], _import_data["kw"], _import_data["domain"])

        existing = session.query(Like).filter_by(user_id=actor_id, post_id=post.id).first()
        if existing:
            if reaction and existing.reaction != reaction:
                existing.reaction = reaction
                _existing_n = session.query(Notification).filter_by(
                    user_id=post.author_id, from_user_id=actor_id, notification_type="like", post_id=post.id
                ).first()
                if _existing_n:
                    _r = reaction or "★"
                    _existing_n.metadata_json = json.dumps({"reaction": _r})
                session.commit()
                _reactions = {}
                for _react, _cnt in session.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post.id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
                    _reactions[_react or "★"] = _cnt
                broadcast_reaction_update(post.id, _reactions)
            return (200, "Already liked")

        like_ap_id = activity_id
        if not like_ap_id:
            like_ap_id = f"{BASE_URL}/likes/{uuid.uuid4()}"

        like = Like(
            user_id=actor_id,
            post_id=post.id,
            ap_id=like_ap_id,
            reaction=reaction if reaction else None,
        )
        session.add(like)

        existing_n = session.query(Notification).filter_by(
            user_id=post.author_id, from_user_id=actor_id, notification_type="like", post_id=post.id
        ).first()
        if not existing_n:
            _notif_meta = json.dumps({"reaction": reaction or "★"})
            n = Notification(
                user_id=post.author_id,
                from_user_id=actor_id,
                notification_type="like",
                post_id=post.id,
                metadata_json=_notif_meta,
            )
            session.add(n)
            session.commit()
            send_push_to_user(int(post.author_id), "like", str(actor_username), int(post.id))
            broadcast_notif_sound(int(post.author_id))
            broadcast_refresh_notifs(int(post.author_id))
            _reactions = {}
            for _react, _cnt in session.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post.id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
                _reactions[_react or "★"] = _cnt
            broadcast_reaction_update(post.id, _reactions)
        else:
            session.commit()
            _reactions = {}
            for _react, _cnt in session.query(Like.reaction, func.count(Like.id)).filter(Like.post_id == post.id).group_by(Like.reaction).order_by(func.min(Like.id)).all():
                _reactions[_react or "★"] = _cnt
            broadcast_reaction_update(post.id, _reactions)

    return (200, "Liked")


def _handle_vote(activity: dict) -> tuple[int, str]:
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    obj = activity.get("object", "")
    if not obj:
        return (200, "OK")
    if not isinstance(obj, dict):
        return (400, "Wrong object")
    if obj.get('type') != "Question":
        return (400, "Not vote")

    _sign_as = None
    post = None
    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=obj.get("id")).first()
        _sign_as = session.query(User).get(post.author_id) if post else None
    if not post or not post.poll_data:
        return (200, "OK")

    actor_id: int | str = ''
    try:
        actor = _resolve_actor(actor_url, sign_as=_sign_as)
        if not actor:
            return (404, "Actor not found")
        actor_id = int(actor.id)
    except Exception as e:
        logger.error("Failed to resolve actor %s: %s", actor_url, e, exc_info=True)
        return (404, "Actor not found")

    with get_session() as session:
        # Determine which option was voted for
        option_name = obj.get("name", "") or obj.get("content", "")
        options = post.poll_data.get("options", [])
        option_idx = -1
        if option_name:
            for i, opt in enumerate(options):
                if opt.get("text", "").strip().lower() == option_name.strip().lower():
                    option_idx = i
                    break
        if option_idx < 0 or option_idx >= len(options):
            return (200, "OK")

        # Check if poll expired
        expires_at = post.poll_data.get("expires_at")
        if expires_at:
            try:
                if datetime.datetime.fromisoformat(expires_at) < datetime.datetime.now(datetime.UTC):
                    return (200, "Poll ended")
            except (ValueError, TypeError):
                pass

        # Check for existing vote (change or dedup)
        existing = session.query(Vote).filter_by(user_id=actor_id, post_id=post.id).first()
        if existing:
            if existing.option_index == option_idx:
                return (200, "Already voted")
            options[existing.option_index]["votes_count"] = max(0, options[existing.option_index].get("votes_count", 0) - 1)
            existing.option_index = option_idx
        else:
            session.add(Vote(user_id=actor_id, post_id=post.id, option_index=option_idx))

        options[option_idx]["votes_count"] = options[option_idx].get("votes_count", 0) + 1
        post.poll_data = {**post.poll_data, "options": options}
        session.commit()

    return (200, "Voted")


def _handle_announce(activity: dict) -> tuple[int, str]:
    activity_id = activity.get("id", "")
    if activity_id:
        try:
            with get_session() as _pa_s:
                _pa_s.add(ProcessedActivity(id=activity_id))
                _pa_s.commit()
        except IntegrityError:
            # 라우트(inbox)가 이미 processed_activities에 넣고 진입하므로 여기서
            # 중복이라도 실제 부스트 생성은 여전히 필요하다. 조기 반환하면 리모트
            # 부스트가 영영 저장되지 않는다 (아래 Boost 존재 확인으로 중복 방지).
            pass
        except Exception:
            pass

    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    raw_object = activity.get("object")
    object_url = raw_object if isinstance(raw_object, str) else ""
    logger.debug("[ANNOUNCE] actor=%s object_type=%s object_url=%s", actor_url, type(raw_object).__name__, object_url[:120])

    if not object_url and isinstance(raw_object, dict):
        object_url = raw_object.get("id", "")
        logger.debug("[ANNOUNCE] embedded object, extracted id=%s", object_url[:120])

    if not object_url:
        logger.debug("[ANNOUNCE] no object_url, returning early")
        return (200, "OK")

    if object_url.endswith("/activity"):
        object_url = object_url[:-len("/activity")]
        logger.debug("[ANNOUNCE] stripped /activity suffix to %s", object_url[:120])

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if post and post.boost_of_id:
            post = session.query(Post).get(post.boost_of_id)
        _sign_as = session.query(User).get(post.author_id) if post else None
        if not _sign_as:
            _sign_as = _get_instance_actor(session)
    logger.debug("[ANNOUNCE] db_post=%s signer=%s", 'found id=' + str(post.id) if post else 'none', 'id=' + str(_sign_as.id) if _sign_as else 'none')
    actor = _resolve_actor(actor_url, sign_as=_sign_as)
    if not actor:
        logger.debug("[ANNOUNCE] actor not found, returning 404")
        return (404, "Actor not found")

    actor_id = actor.id
    actor_username = actor.username

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if post and post.boost_of_id:
            post = session.query(Post).get(post.boost_of_id)
        logger.debug("[ANNOUNCE] session2 post=%s", 'found id=' + str(post.id) if post else 'none')
        if not post:
            _local_signer = _get_instance_actor(session)
            try:
                post = _fetch_remote_post(object_url, _local_signer, session)
                if post and post.boost_of_id:
                    post = session.query(Post).get(post.boost_of_id)
                logger.debug("[ANNOUNCE] fetch_remote_post result=%s", 'id=' + str(post.id) if post else 'None')
            except Exception as e:
                logger.warning("Announce: _fetch_remote_post failed for %s: %s", object_url, e)
                logger.debug("[ANNOUNCE] fetch_remote_post EXCEPTION: %s", e)
                post = None
            if not post:
                logger.warning("Announce: could not fetch remote post %s", object_url)
                logger.debug("[ANNOUNCE] could not fetch remote post, returning early")
                return (200, "OK")

        existing = session.query(Boost).filter_by(user_id=actor_id, post_id=post.id).first()
        if existing:
            return (200, "Already boosted")

        boost_ap_id = activity_id
        if not boost_ap_id:
            boost_ap_id = f"{BASE_URL}/boosts/{uuid.uuid4()}"

        boost = Boost(
            user_id=actor_id,
            post_id=post.id,
            ap_id=boost_ap_id,
        )
        session.add(boost)
        # Create boost pointer post row
        boost_post = Post(
            author_id=actor_id,
            content="",
            boost_of_id=post.id,
            visibility=post.visibility or "public",
            ap_id=boost_ap_id,
        )
        session.add(boost_post)

        # 1. 안전하게 DB 세션이 활성화되어 있을 때 미리 _actor와 post.author(_a)를 가져옵니다.
        _actor = session.query(User).get(actor_id)
        _a = post.author

        # 2. 통계 개수 조회도 커밋 전에 안전하게 미리 해둡니다.
        likes_cnt = session.query(Like).filter_by(post_id=post.id).count()
        boosts_cnt = session.query(Boost).filter_by(post_id=post.id).count()
        replies_cnt = session.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count()
        reactions_data = _build_reactions(session, post.id)

        existing_n = session.query(Notification).filter_by(
            user_id=post.author_id, from_user_id=actor_id, notification_type="boost", post_id=post.id
        ).first()

        if not existing_n:
            n = Notification(
                user_id=post.author_id,
                from_user_id=actor_id,
                notification_type="boost",
                post_id=post.id,
            )
            session.add(n)

        try:
            session.commit()
        except IntegrityError:
            # 동시에 같은 Announce가 두 경로(공유/유저 인박스)로 들어와
            # 동일 boost_ap_id 삽입이 경합한 경우 → 상대 스레드가 처리했으므로 중단
            session.rollback()
            return (200, "Already boosted")

        # 5. 커밋 이후 외부 연동 (푸시 및 스트리밍) 처리
        if not existing_n:
            send_push_to_user(int(post.author_id), "boost", str(actor_username), int(post.id))
            broadcast_notif_sound(int(post.author_id))

        try:
            def _safe_user_json(u):
                if not u:
                    return None
                role = getattr(u, 'role', 'user') or 'user'
                return {
                    "id": u.id, "username": u.username,
                    "display_name": u.display_name or u.username,
                    "avatar": u.profile_image or "", "header": u.header_image or "",
                    "summary": u.summary or "", "is_admin": u.is_admin,
                    "is_locked": getattr(u, "is_locked", False) or False,
                    "is_limited": getattr(u, "is_limited", False) or False,
                    "is_frozen": getattr(u, "is_frozen", False) or False,
                    "is_deceased": getattr(u, "is_deceased", False) or False,
                    "is_deactivated": getattr(u, "is_deactivated", False) or False,
                    "is_sensitive": getattr(u, "is_sensitive", False) or False,
                    "is_remote": u.is_remote, "role": role,
                    "show_badge": getattr(u, "show_badge", False) or False,
                    "email_verified": getattr(u, "email_verified", False) or False,
                    "default_visibility": getattr(u, "default_visibility", "public") or "public",
                    "display_handle": getattr(u, "display_handle", "") or "",
                    "is_bot": getattr(u, "is_bot", False) or False,
                    "pinned_posts": (u.pinned_posts or []) if hasattr(u, 'pinned_posts') else [],
                    "pinned_series": (u.pinned_series or []) if hasattr(u, 'pinned_series') else [],
                    "episode_default_visibility": getattr(u, "episode_default_visibility", "public") or "public",
                    "follow_list_visibility": getattr(u, "follow_list_visibility", "public") or "public",
                    "custom_fields": (u.custom_fields or []) if hasattr(u, 'custom_fields') else [],
                    "profile_hashtags": (u.profile_hashtags or []) if hasattr(u, 'profile_hashtags') else [],
                    "enable_reactions": getattr(u, "enable_reactions", True) is not False,
                    "aliases": (u.aliases or []) if hasattr(u, 'aliases') else [],
                    "moved_to": getattr(u, "moved_to", "") or "",
                }
            _author_data = _safe_user_json(_a)
            if not _author_data:
                _a = session.query(User).get(post.author_id)
                _author_data = _safe_user_json(_a)
            _broadcast_emojis = _broadcast_emoji_list(session)

            # Broadcast boost pointer to followers of the booster (remote boost)
            try:
                broadcast_post({
                    "id": boost_post.id,
                    "number": post.number or "",
                    "content": post.content,
                    "summary": post.summary or "",
                    "visibility": post.visibility or "public",
                    "created_at": post.created_at.isoformat() if post.created_at else "",
                    "author": _author_data,
                    "likes_count": likes_cnt,
                    "boosts_count": boosts_cnt,
                    "replies_count": replies_cnt,
                    "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                    "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                    "ap_id": post.ap_id or "",
                    "reply_context": None,
                    "boosted_by": [_safe_user_json(_actor)] if _safe_user_json(_actor) else [],
                    "boost_of_id": post.id,
                    "_boost_pointer_id": boost_post.id,
                    "media_attachments": (post.media_attachments or []) if hasattr(post, 'media_attachments') else [],
                    "poll_data": post.poll_data, "my_vote": None,
                    "reactions": reactions_data, "my_reaction": None,
                    "mentioned_user_ids": [],
                    "quote_of_id": post.quote_of_id or None, "quote_of_ap_id": post.quote_of_ap_id or "",
                    "_emojis": _broadcast_emojis,
                }, int(actor_id), str(post.visibility or "public"))
            except Exception as e:
                logger.error("Failed to broadcast remote boost timeline: %s", e, exc_info=True)
        except Exception as e:
            logger.error("Failed to broadcast boost from AP: %s", e, exc_info=True)

    logger.debug("[ANNOUNCE] success post_id=%s by actor_id=%s", post.id, actor_id)
    return (200, "Announced")

def _handle_block(activity: dict) -> tuple[int, str]:
    actor_url = activity.get("actor", "")
    object_url = activity.get("object", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    if isinstance(object_url, dict):
        object_url = object_url.get("id", "")

    local_username = parse_username_from_url(object_url)
    sign_as = None
    if local_username:
        with get_session() as _s:
            _u = _s.query(User).filter_by(username=local_username, is_remote=False).first()
            if _u:
                sign_as = _u
    remote_user = _resolve_actor(actor_url, sign_as=sign_as)
    if not remote_user:
        return (200, "OK")

    try:
        with get_session() as session:
            # Re-query both users in the SAME session to avoid detached instance issues
            remote = session.query(User).filter_by(remote_url=actor_url).first()
            if not remote:
                p = urlparse(actor_url)
                if "/@" in p.path:
                    alt_url = f"{p.scheme}://{p.netloc}/users/{p.path.split('/@')[-1]}"
                    remote = session.query(User).filter_by(remote_url=alt_url).first()
            if not remote:
                remote = session.query(User).filter_by(id=remote_user.id).first()
            if not remote:
                return (200, "OK")
            local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()
            if not local_user:
                return (200, "OK")
            session.query(Follow).filter_by(follower_id=remote.id, following_id=local_user.id).delete()
            session.query(Follow).filter_by(follower_id=local_user.id, following_id=remote.id).delete()
            existing = session.query(UserBlock).filter_by(user_id=remote.id, target_user_id=local_user.id).first()
            if not existing:
                session.add(UserBlock(user_id=remote.id, target_user_id=local_user.id))
                session.commit()
            return (200, "Blocked")
    except Exception as e:
        logger.error("Error processing Block from %s: %s", actor_url, e, exc_info=True)
        return (200, "OK")


def _handle_undo(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    obj_type = obj.get("type", "") if isinstance(obj, dict) else ""

    if not isinstance(obj, dict) and isinstance(obj, str):
        fetched = None
        try:
            resp = validated_get(obj, headers={"Accept": "application/activity+json", "User-Agent": WRIT_USER_AGENT}, timeout=10)
            if resp is not None and resp.status_code < 300:
                fetched = resp.json()
                obj_type = fetched.get("type", "")
        except Exception:
            pass
        if fetched:
            obj = fetched
        else:
            return (200, "OK")

    if obj_type == "Follow":
        actor_url = obj.get("actor", activity.get("actor", ""))
        object_url = obj.get("object", "")
        if isinstance(actor_url, list):
            actor_url = actor_url[0]

        local_username = parse_username_from_url(object_url)
        follower = _resolve_actor(actor_url)
        if not follower:
            return (200, "OK")
        follower_id = follower.id
        with get_session() as session:
            target = session.query(User).filter_by(username=local_username, is_remote=False).first()
            if not target:
                return (200, "OK")
            session.query(Follow).filter_by(
                follower_id=follower_id, following_id=target.id
            ).delete()
            session.commit()
            broadcast_refresh_notifs(target.id)

        return (200, "Unfollowed")

    if obj_type == "Like":
        actor_url = activity.get("actor", "")
        if isinstance(actor_url, list):
            actor_url = actor_url[0]
        object_url = obj.get("object", "") if isinstance(obj, dict) else ""

        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            _sign_as = session.query(User).get(post.author_id) if post else None
        actor = _resolve_actor(actor_url, sign_as=_sign_as)
        if not actor:
            return (200, "OK")

        actor_id = actor.id
        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            if not post:
                return (200, "OK")
            session.query(Like).filter_by(user_id=actor_id, post_id=post.id).delete()
            session.query(Notification).filter_by(
                user_id=post.author_id, from_user_id=actor_id,
                notification_type="like", post_id=post.id,
            ).delete()
            session.commit()
            broadcast_refresh_notifs(post.author_id)
            try:
                _la = post.author
                broadcast_post({
                    "id": post.id, "type": "update",
                    "number": post.number or "",
                    "content": post.content, "summary": post.summary or "",
                    "visibility": post.visibility or "public",
                    "created_at": post.created_at.isoformat() if post.created_at else "",
                    "author": {
                        "id": _la.id, "username": _la.username,
                        "display_name": _la.display_name or _la.username,
                        "avatar": _la.profile_image or "", "header": _la.header_image or "",
                        "summary": _la.summary or "", "is_admin": _la.is_admin,
                        "is_locked": getattr(_la, "is_locked", False),
                        "is_limited": getattr(_la, "is_limited", False),
                        "is_remote": _la.is_remote, "ap_id": _la.remote_url or "",
                    },
                    "likes_count": session.query(Like).filter_by(post_id=post.id).count(),
                    "boosts_count": session.query(Boost).filter_by(post_id=post.id).count(),
                    "replies_count": session.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count(),
                    "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                    "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                    "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                    "poll_data": post.poll_data, "my_vote": None, "reactions": {}, "my_reaction": None,
                    "_emojis": _broadcast_emoji_list(session),
                }, post.author_id, post.visibility or "public", False)
            except Exception:
                pass

        return (200, "Unliked")

    if obj_type == "Announce":
        actor_url = activity.get("actor", "")
        object_url = obj.get("object", "") if isinstance(obj, dict) else ""
        if isinstance(actor_url, list):
            actor_url = actor_url[0]

        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            _sign_as = session.query(User).get(post.author_id) if post else None
        actor = _resolve_actor(actor_url, sign_as=_sign_as)
        if not actor:
            return (200, "OK")

        actor_id = actor.id
        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            if not post:
                return (200, "OK")
            session.query(Boost).filter_by(user_id=actor_id, post_id=post.id).delete()
            # Delete boost pointer post
            session.query(Post).filter_by(author_id=actor_id, boost_of_id=post.id).delete()
            session.query(Notification).filter_by(
                user_id=post.author_id, from_user_id=actor_id,
                notification_type="boost", post_id=post.id,
            ).delete()
            session.commit()
            broadcast_refresh_notifs(post.author_id)
            try:
                _ba = post.author
                broadcast_post({
                    "id": post.id, "type": "update",
                    "number": post.number or "",
                    "content": post.content, "summary": post.summary or "",
                    "visibility": post.visibility or "public",
                    "created_at": post.created_at.isoformat() if post.created_at else "",
                    "author": {
                        "id": _ba.id, "username": _ba.username,
                        "display_name": _ba.display_name or _ba.username,
                        "avatar": _ba.profile_image or "", "header": _ba.header_image or "",
                        "summary": _ba.summary or "", "is_admin": _ba.is_admin,
                        "is_locked": getattr(_ba, "is_locked", False),
                        "is_limited": getattr(_ba, "is_limited", False),
                        "is_remote": _ba.is_remote, "ap_id": _ba.remote_url or "",
                    },
                    "likes_count": session.query(Like).filter_by(post_id=post.id).count(),
                    "boosts_count": session.query(Boost).filter_by(post_id=post.id).count(),
                    "replies_count": session.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count(),
                    "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                    "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                    "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                    "poll_data": post.poll_data, "my_vote": None, "reactions": {}, "my_reaction": None,
                    "_emojis": _broadcast_emoji_list(session),
                }, post.author_id, post.visibility or "public", False)
            except Exception:
                pass

        return (200, "Unboosted")

    if obj_type == "Block":
        actor_url = obj.get("actor", activity.get("actor", ""))
        object_url = obj.get("object", "")
        if isinstance(actor_url, list):
            actor_url = actor_url[0]
        if isinstance(object_url, dict):
            object_url = object_url.get("id", "")

        local_username = parse_username_from_url(object_url)
        sign_as = None
        if local_username:
            with get_session() as _s:
                _u = _s.query(User).filter_by(username=local_username, is_remote=False).first()
                if _u:
                    sign_as = _u
        remote_user = _resolve_actor(actor_url, sign_as=sign_as)
        if not remote_user:
            return (200, "OK")
        try:
            with get_session() as session:
                remote = session.query(User).filter_by(id=remote_user.id).first()
                if not remote:
                    return (200, "OK")
                local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()
                if not local_user:
                    return (200, "OK")
                session.query(UserBlock).filter_by(user_id=remote.id, target_user_id=local_user.id).delete()
                session.commit()
            return (200, "Unblocked")
        except Exception as e:
            logger.error("Error processing Undo Block from %s: %s", actor_url, e, exc_info=True)
            return (200, "OK")

    return (200, "OK")


def _handle_update(activity: dict) -> tuple[int, str]:
    actor_url = activity.get("actor", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    object_data = activity.get("object", {})
    if isinstance(object_data, str):
        try:
            resp = validated_get(object_data, headers={"Accept": "application/activity+json", "User-Agent": WRIT_USER_AGENT}, timeout=10)
            if resp is not None and resp.status_code < 300:
                object_data = resp.json()
            else:
                return (200, "OK")
        except Exception:
            return (200, "OK")
    if isinstance(object_data, dict):
        obj_type = object_data.get("type", "")
        obj_id = object_data.get("id", "")
        if obj_type in ("Person", "Service"):
            _resolve_actor(obj_id, force_refresh=True)
        elif obj_type in ("Note", "Question"):
            with get_session() as session:
                post = session.query(Post).filter_by(ap_id=obj_id).first()
                if post and not post.is_deleted:
                    if post.author and post.author.remote_url != actor_url:
                        logger.warning("[AP] _handle_update REJECTED: actor %s does not own post %s", actor_url, obj_id)
                        return (403, "Actor does not own this post")
                    # Update content/summary
                    new_content = object_data.get("content", "")
                    if not new_content:
                        cm = object_data.get("contentMap")
                        if isinstance(cm, dict) and cm:
                            new_content = next(iter(cm.values()), "")
                    if new_content:
                        post.content = process_post_content(_sanitize_html(new_content), post)
                    if "summary" in object_data:
                        post.summary = object_data.get("summary", "")
                    # Update poll data
                    if post.poll_data:
                        one_of = object_data.get("oneOf") or object_data.get("anyOf") or []
                        if isinstance(one_of, list):
                            new_options = []
                            for opt in one_of:
                                if isinstance(opt, dict) and opt.get("name"):
                                    replies = opt.get("replies", {})
                                    votes_count = 0
                                    if isinstance(replies, dict):
                                        votes_count = replies.get("totalItems", 0)
                                    new_options.append({"text": opt["name"], "votes_count": votes_count})
                            if new_options:
                                old_options = post.poll_data.get("options", [])
                                text_to_old = {o.get("text", ""): o for o in old_options}
                                for new_opt in new_options:
                                    old = text_to_old.get(new_opt["text"])
                                    if old:
                                        new_opt["votes_count"] = max(new_opt.get("votes_count", 0), old.get("votes_count", 0))
                                post.poll_data = {**post.poll_data, "options": new_options}
                    # Update emoji tags
                    _process_emoji_tags(object_data.get("tag", []), session)
                    session.commit()
                    _refresh_emoji_cache_forcibly(session)
                    try:
                        _ua = post.author
                        broadcast_post({
                            "id": post.id,
                            "number": post.number or "",
                            "content": post.content,
                            "summary": post.summary or "",
                            "visibility": post.visibility or "public",
                            "created_at": post.created_at.isoformat() if post.created_at else "",
                            "author": {
                                "id": _ua.id, "username": _ua.username,
                                "display_name": _ua.display_name or _ua.username,
                                "avatar": _ua.profile_image or "", "header": _ua.header_image or "",
                                "summary": _ua.summary or "", "is_admin": _ua.is_admin,
                                "is_locked": getattr(_ua, "is_locked", False),
                                "is_limited": getattr(_ua, "is_limited", False),
                                "is_remote": _ua.is_remote, "ap_id": _ua.remote_url or "",
                            },
                    "likes_count": session.query(Like).filter_by(post_id=post.id).count(),
                    "boosts_count": session.query(Boost).filter_by(post_id=post.id).count(),
                    "replies_count": session.query(Post).filter_by(in_reply_to_id=post.id, is_deleted=False).count(),
                    "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                    "is_dm": False, "is_sensitive": getattr(post, "is_sensitive", False) or False,
                    "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                    "poll_data": post.poll_data, "my_vote": None,
                    "reactions": _build_reactions(session, post.id),
                    "my_reaction": None,
                            "type": "update",
                            "_emojis": _broadcast_emoji_list(session),
            }, post.author_id, post.visibility or "public", False)
                    except Exception:
                        pass
    return (200, "Updated")

def _handle_delete(activity: dict) -> tuple[int, str]:
    actor_url = activity.get("actor", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    object_url = activity.get("object", "")
    if isinstance(object_url, dict):
        object_url = object_url.get("id", "")

    if not object_url:
        return (200, "OK")

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if post:
            if post.author and post.author.remote_url != actor_url:
                logger.warning("[AP] _handle_delete REJECTED: actor %s does not own post %s (author=%s)", actor_url, object_url, post.author.remote_url)
                return (403, "Actor does not own this post")
            _del_author_id = post.author_id
            post.is_deleted = True
            session.query(Notification).filter_by(post_id=post.id).delete()
            session.commit()
            try:
                broadcast_delete(post.id)
                broadcast_refresh_notifs(_del_author_id)
            except Exception:
                pass

    return (200, "Deleted")


def _handle_flag(activity: dict) -> tuple[int, str]:
    logger.info("=== FLAG called ===")
    actor_url = activity.get("actor")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    logger.info("FLAG actor_url=%s", actor_url)
    if not actor_url:
        return (400, "Missing actor")

    # Try to find or resolve reporter BEFORE opening session (avoids connection hold during network I/O)
    reporter = None
    try:
        with get_session() as _s:
            reporter = _s.query(User).filter_by(remote_url=actor_url).first()
            if not reporter:
                for u in _s.query(User).filter(User.is_remote == False).all():
                    if u.actor_uri() == actor_url:
                        reporter = u
                        break
            if reporter:
                _reporter_id = reporter.id
                _reporter_username = reporter.username
                _reporter_is_remote = reporter.is_remote
    except Exception:
        _reporter_id = None
    logger.info("FLAG reporter found in DB: %s", reporter is not None)

    if not reporter:
        reporter = _resolve_actor(actor_url)
        logger.info("FLAG _resolve_actor: %s", reporter is not None)

    if not reporter:
        try:
            _r = validated_get(actor_url, headers={"Accept": "application/activity+json"}, timeout=10)
            if _r.status_code == 200:
                _d = _r.json()
                _pref = _d.get("preferredUsername", "")
                if _pref:
                    _domain = urlparse(actor_url).netloc
                    _username = f"{_pref}@{_domain}"
                    _pubkey = _d.get("publicKey", {}).get("publicKeyPem", "") if isinstance(_d.get("publicKey"), dict) else ""
                    _privkey = generate_keypair()[0]
                    with get_session() as _s:
                        _existing = _s.query(User).filter_by(remote_url=actor_url).first()
                        if _existing:
                            _existing.public_key = _pubkey or _existing.public_key
                            reporter = _existing
                        else:
                            _by = _s.query(User).filter_by(username=_username).first()
                            if _by:
                                _by.remote_url = actor_url
                                _by.public_key = _pubkey or _by.public_key
                                reporter = _by
                            else:
                                reporter = User(
                                    username=_username, remote_url=actor_url,
                                    public_key=_pubkey, private_key=_privkey,
                                    password_hash="", is_remote=True,
                                    inbox_url=_d.get("inbox", ""),
                                    shared_inbox_url=_d.get("endpoints", {}).get("sharedInbox", "") if isinstance(_d.get("endpoints"), dict) else "",
                                    display_name=_d.get("name", _pref), summary=_d.get("summary", ""),
                                    profile_url=_d.get("url", actor_url),
                                )
                                _s.add(reporter)
                        _s.flush()
                        logger.info("FLAG reporter created via direct fetch: %s", reporter.id)
        except Exception as e:
            logger.error("FLAG direct fetch failed: %s", e, exc_info=True)

    if not reporter:
        return (202, "Accepted (unknown reporter)")

    with get_session() as s:
        objects = activity.get("object", [])
        if isinstance(objects, str):
            objects = [objects]
        logger.info("FLAG objects=%s", objects)
        content = activity.get("content", "")
        for obj_url in objects:
            logger.info("FLAG processing obj: %s", obj_url)
            post = s.query(Post).filter_by(ap_id=obj_url).first()
            if post:
                logger.info("FLAG found post id=%s", post.id)
                report = Report(
                    reporter_id=reporter.id, target_type="post", target_id=post.id,
                    reason=content or "Reported via federation", forward_to_remote=False,
                )
                s.add(report)
                _notify_admins(s, reporter, "post", post.id, content)
                continue
            user = s.query(User).filter(User.remote_url == obj_url).first()
            if not user and BASE_URL in obj_url:
                for _u in s.query(User).filter_by(is_remote=False).all():
                    if _u.actor_uri() == obj_url:
                        user = _u
                        break
            if user and not user.is_remote:
                logger.info("FLAG found local user %s", user.username)
                report = Report(
                    reporter_id=reporter.id, target_type="user", target_id=user.id,
                    reason=content or "Reported via federation", forward_to_remote=False,
                )
                s.add(report)
                _notify_admins(s, reporter, "user", user.id, content)
            else:
                logger.info("FLAG no match for obj: %s", obj_url)
        s.commit()
        broadcast_refresh_notifs()
        logger.info("FLAG done, committed")
    return (200, "Flagged")


def _handle_move(activity: dict) -> tuple[int, str]:
    actor_url = activity.get("actor")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    if not actor_url:
        return (400, "Missing actor")

    old_actor_url = activity.get("object", "")
    if isinstance(old_actor_url, dict):
        old_actor_url = old_actor_url.get("id", "")
    if isinstance(old_actor_url, list):
        old_actor_url = old_actor_url[0] if old_actor_url else ""
    if not old_actor_url:
        return (400, "Missing object")

    new_actor_url = activity.get("target", "")
    if isinstance(new_actor_url, dict):
        new_actor_url = new_actor_url.get("id", "")
    if isinstance(new_actor_url, list):
        new_actor_url = new_actor_url[0] if new_actor_url else ""
    if not new_actor_url:
        return (400, "Missing target")

    # Resolve new actor BEFORE session (network I/O)
    new_actor = _resolve_actor(new_actor_url)
    if not new_actor:
        return (404, "New actor not found")
    new_actor_id = new_actor.id

    with get_session() as session:
        local_user = None
        for u in session.query(User).filter(User.is_remote == False).all():
            if u.actor_uri() == old_actor_url:
                local_user = u
                break
        if not local_user:
            local_user = session.query(User).filter(
                User.remote_url == old_actor_url,
                User.is_remote == True,
            ).first()
        if not local_user:
            return (200, "OK (not a local/known account)")

        # Verify that the new account has the old account in its aliases
        new_actor_local = session.query(User).filter_by(id=new_actor_id, is_remote=False).first()
        if new_actor_local:
            aliases = new_actor_local.aliases or []
            if not actor_urls_include(aliases, old_actor_url) and not actor_urls_include(aliases, local_user.actor_uri()):
                return (403, "New account has not aliased the old account")
        else:
            # new_actor is detached; query fresh from session for alias check
            new_actor_in_session = session.query(User).filter_by(id=new_actor_id).first()
            if new_actor_in_session and new_actor_in_session.is_remote:
                aliases = new_actor_in_session.aliases or []
                if not actor_urls_include(aliases, old_actor_url) and not actor_urls_include(aliases, local_user.remote_url):
                    return (403, "New account has not aliased the old account")

        followers = session.query(Follow).filter_by(following_id=local_user.id, accepted=True).all()
        moved_count = 0
        for f in followers:
            existing = session.query(Follow).filter_by(
                follower_id=f.follower_id, following_id=new_actor_id
            ).first()
            if not existing:
                f.following_id = new_actor_id
                moved_count += 1
        session.commit()

    logger.info("Move: moved %d followers from %s to %s", moved_count, old_actor_url, new_actor_url)
    return (200, f"Moved {moved_count} followers")
