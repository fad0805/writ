import re
import copy
import sys
import time
import datetime
import json
import logging
import uuid
import threading
from urllib.parse import urlparse

import httpx
import html
from sqlalchemy import func

from app.core.eventbus import broadcast
from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_notif_sound, broadcast_refresh_notifs, broadcast_refresh_notifs, broadcast_post, broadcast_reaction_update, broadcast_delete
from app.config.settings import BASE_URL, SECRET_KEY
from app.db.database import get_session
from app.models import User, Post, Follow, Like, Boost, Vote, Notification, Report, CustomEmoji, MutedServer, UserBlock, Tag
from app.utils.emoji import _refresh_emoji_cache_forcibly, _load_emojis
from app.utils.crypto import generate_keypair
from app.utils.content_parser import _sanitize_html, process_post_content
from app.core.activitypub._utils import (
    _validate_url, _safe_fetch, _validated_get, _federation_allowed,
    _html_to_newlines, _parse_username_from_url, _get_instance_actor, WRIT_USER_AGENT,
)
from app.core.activitypub._media import _cache_remote_media
from app.core.activitypub._emoji import _process_emoji_tags, _background_import_emoji
from app.core.activitypub._fetch import _fetch_remote_post, _resolve_actor, _retry_fetch_reply
from app.core.activitypub._outbound import _post_to_inbox, _send_accept, broadcast_to_followers

logger = logging.getLogger("writ.activitypub")


def handle_inbox(activity: dict) -> tuple[int, str]:
    atype = activity.get("type")
    actor = activity.get("actor")

    if isinstance(actor, list):
        actor = actor[0]

    actor_domain = urlparse(actor).hostname or "" if actor and isinstance(actor, str) else ""
    print(f"[INBOX] atype={atype} actor_domain={actor_domain}", flush=True)

    # Check federation rules for the actor's domain
    if actor and isinstance(actor, str):
        actor_domain = urlparse(actor).hostname or ""
        if not _federation_allowed(actor_domain):
            logger.info("Rejected inbox activity from blocked domain: %s", actor_domain)
            return (403, "Domain not allowed")

    if atype == "Follow":
        return _handle_follow(activity)
    elif atype == "Accept":
        return _handle_accept(activity)
    elif atype == "Reject":
        return _handle_reject(activity)
    elif atype == "Create":
        return _handle_create(activity)
    elif atype == "Like":
        return _handle_like(activity)
    elif atype == "Announce":
        return _handle_announce(activity)
    elif atype == "Undo":
        return _handle_undo(activity)
    elif atype == "Update":
        return _handle_update(activity)
    elif atype == "Delete":
        return _handle_delete(activity)
    elif atype == "Flag":
        return _handle_flag(activity)
    elif atype == "Move":
        return _handle_move(activity)
    elif atype == "Vote":
        return _handle_vote(activity)
    elif atype == "EmojiReact":
        return _handle_like(activity)
    elif atype == "Block":
        return _handle_block(activity)
    else:
        return (202, f"Accepted {atype}")


def _handle_follow(activity: dict) -> tuple[int, str]:
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    raw_object = activity.get("object", "")
    object_url = raw_object if isinstance(raw_object, str) else raw_object.get("id", "")
    activity_id = activity.get("id", "")

    local_username = _parse_username_from_url(object_url)

    # Resolve follower BEFORE opening session to avoid nested transactions
    with get_session() as s:
        target = s.query(User).filter_by(username=local_username, is_remote=False).first()
    if not target:
        return (404, "Target user not found")

    target_id = target.id
    follower = _resolve_actor(actor_url, sign_as=target)
    if not follower:
        return (404, "Follower not found")

    with get_session() as session:
        target = session.query(User).get(target_id)
        follower = session.merge(follower)
        follower_id = follower.id
        accepted = not target.is_locked
        existing = session.query(Follow).filter_by(
            follower_id=follower.id, following_id=target.id
        ).first()
        if not existing:
            follow = Follow(follower_id=follower.id, following_id=target.id, accepted=accepted, activity_id=activity_id)
            session.add(follow)
            notification = Notification(
                user_id=target.id,
                from_user_id=follower.id,
                notification_type="follow_request" if not accepted else "follow",
            )
            session.add(notification)
            session.commit()
            send_push_to_user(target.id, "follow" if accepted else "follow_request", follower.username)
            broadcast_notif_sound(target.id)

        # Send Accept only if auto-approved (not locked) — inside session so follower is still bound
        if accepted:
            _send_accept(actor_url, activity_id, target, follower=follower)

    return (200, "Followed")


def _handle_reject(activity: dict) -> tuple[int, str]:
    rejecter_url = activity.get("actor", "")
    if isinstance(rejecter_url, list):
        rejecter_url = rejecter_url[0]

    obj = activity.get("object", {})
    follower_url = obj.get("actor", "") if isinstance(obj, dict) else ""

    with get_session() as session:
        remote_user = session.query(User).filter_by(remote_url=rejecter_url).first()
        if not remote_user:
            return (200, "OK")

        local_user = None
        if follower_url:
            local_username = _parse_username_from_url(follower_url)
            if local_username:
                local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()

        query_filter = {
            "following_id": remote_user.id,
            "accepted": False
        }
        if local_user:
            query_filter["follower_id"] = local_user.id

        follow_rel = session.query(Follow).filter_by(**query_filter).first()
        
        if not follow_rel:
            return (200, "No pending follow request found")

        local_user = session.query(User).get(follow_rel.follower_id)
        local_user_id = local_user.id
        session.query(Notification).filter_by(
            from_user_id=remote_user.id, user_id=local_user.id,
            notification_type="follow_request",
        ).delete()
        session.delete(follow_rel)
        session.commit()

    broadcast_refresh_notifs(local_user_id)
    return (200, "Rejected follow removed")

def _handle_accept(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    if isinstance(obj, dict):
        follower_url = obj.get("actor", "")
    elif isinstance(obj, str):
        try:
            resp = httpx.get(obj, headers={"Accept": "application/activity+json, application/ld+json; profile=\"https://www.w3.org/ns/activitystreams\"", "User-Agent": WRIT_USER_AGENT}, timeout=10)
            if resp.status_code == 200:
                follow_activity = resp.json()
                follower_url = follow_activity.get("actor", "")
        except Exception:
            pass
    else:
        follower_url = ""

    if not follower_url:
        return (200, "OK")

    accepter_url = activity.get("actor", "")
    if isinstance(accepter_url, list):
        accepter_url = accepter_url[0]

    local_username = _parse_username_from_url(follower_url)
    if not local_username:
        return (200, "OK")

    # Resolve actor BEFORE opening session (network I/O + its own session)
    remote_accepter = _resolve_actor(accepter_url)
    if not remote_accepter:
        return (200, "OK")
    remote_accepter_id = remote_accepter.id

    with get_session() as session:
        local_user = session.query(User).filter_by(username=local_username, is_remote=False).first()
        if not local_user:
            return (200, "OK")

        follow_rel = session.query(Follow).filter_by(
            follower_id=local_user.id,
            following_id=remote_accepter_id,
            accepted=False,
        ).first()
        if not follow_rel:
            return (200, "No pending follow request found")
        if follow_rel:
            follow_rel.accepted = True
            session.commit()

    return (200, "Accepted follow")


def _handle_create(activity: dict) -> tuple[int, str]:
    obj = activity.get("object", {})
    obj_type = obj.get("type") if isinstance(obj, dict) else ""
    if obj_type in ("Note", "Question"):
        raw_actor = activity.get("actor")
        if not raw_actor:
            return (400, "Missing actor")
        actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
        # Try with sign_as from the poll author (for vote on our poll)
        in_reply_to_url = obj.get("inReplyTo", "") if isinstance(obj, dict) else ""
        _sign_as = None
        if in_reply_to_url:
            with get_session() as __s:
                _poll = __s.query(Post).filter_by(ap_id=in_reply_to_url).first()
                if _poll:
                    _sign_as = __s.query(User).get(_poll.author_id)
        actor = _resolve_actor(actor_url, sign_as=_sign_as)
        if not actor:
            return (404, "Actor not found")
        actor_id = actor.id
        actor_username = actor.username
        actor_uri = actor.actor_uri()
        actor_remote_url = actor.remote_url or ""

        # Verify attributedTo matches activity actor
        obj_attributed = obj.get("attributedTo", "")
        if isinstance(obj_attributed, list):
            obj_attributed = obj_attributed[0] if obj_attributed else ""
        if isinstance(obj_attributed, dict):
            obj_attributed = obj_attributed.get("id", "")
        if obj_attributed and obj_attributed != actor_url and obj_attributed != actor_uri and obj_attributed != actor_remote_url:
            return (403, "attributedTo does not match actor")

        # Limit content length (65536 chars ~ 64KB)
        raw_content = obj.get("content", "") or ""
        if not raw_content:
            cm = obj.get("contentMap")
            if isinstance(cm, dict) and cm:
                raw_content = next(iter(cm.values()), "")
        if len(raw_content) > 65536:
            raw_content = raw_content[:65536]
        post_id = obj.get("id", "")
        content = _html_to_newlines(process_post_content(_sanitize_html(raw_content), obj))
        summary = obj.get("summary", "")
        in_reply_to = obj.get("inReplyTo", "")

        # Determine visibility from to/cc
        to = obj.get("to", [])
        if isinstance(to, str):
            to = [to]
        cc = obj.get("cc", [])
        if isinstance(cc, str):
            cc = [cc]
        all_audiences = to + cc
        public_uris = {"https://www.w3.org/ns/activitystreams#Public", "as:Public"}

        is_incoming_dm = False
        if public_uris & set(to):
            visibility = "public"
        elif public_uris & set(cc):
            visibility = "home"
        elif any(aud.endswith("/followers") for aud in all_audiences):
            visibility = "followers"
        elif all_audiences and all(aud.startswith("http") for aud in all_audiences if aud):
            visibility = "mention"
            is_incoming_dm = True
        else:
            visibility = "home"

        # Extract poll data from Question type
        poll_data = None
        if obj_type == "Question":
            options = []
            one_of = obj.get("oneOf") or obj.get("anyOf") or []
            if isinstance(one_of, list):
                for opt in one_of:
                    if isinstance(opt, dict) and opt.get("name"):
                        replies = opt.get("replies", {})
                        votes_count = 0
                        if isinstance(replies, dict):
                            votes_count = replies.get("totalItems", 0)
                        options.append({"text": opt["name"], "votes_count": votes_count})
            if options:
                expires_at = obj.get("endTime") or ""
                poll_data = {
                    "options": options,
                    "expires_at": expires_at,
                }

        # ===== PHASE 1: DB READS (short-lived session) =====
        reply_to_post_id = None
        tag_names = []
        mentioned_ids = []
        muted_visibility = False

        with get_session() as session:
            sys.stdout.flush()
            existing = session.query(Post).filter_by(ap_id=post_id).first()
            sys.stdout.flush()
            if existing:
                if existing.poll_data and poll_data:
                    for new_opt in poll_data.get("options", []):
                        for old_opt in existing.poll_data.get("options", []):
                            if old_opt.get("text") == new_opt.get("text"):
                                old_opt["votes_count"] = new_opt.get("votes_count", 0)
                                break
                    existing.poll_data["expires_at"] = poll_data.get("expires_at", existing.poll_data.get("expires_at", ""))
                    session.commit()
                    return (200, "Poll votes updated")
                return (200, "Already exists")

            reply_to_post_local = None
            if in_reply_to:
                reply_to_post_local = session.query(Post).filter_by(ap_id=in_reply_to).first()
                if not reply_to_post_local:
                    alt_url = in_reply_to.replace("https://", "http://") if "https://" in in_reply_to else in_reply_to.replace("http://", "https://")
                    reply_to_post_local = session.query(Post).filter_by(ap_id=alt_url).first()
                if not reply_to_post_local:
                    _posts_match = re.match(r'https?://[^/]+/posts/(\d+)', in_reply_to)
                    if _posts_match:
                        reply_to_post_local = session.query(Post).filter_by(id=int(_posts_match.group(1)), is_deleted=False).first()
                if reply_to_post_local:
                    reply_to_post_id = reply_to_post_local.id

            # mastodon poll votes: create(note) with name + inreplyto + no content
            vote_name = obj.get("name", "") if not raw_content.strip() else ""
            if vote_name and reply_to_post_local and reply_to_post_local.poll_data:
                poll_post = reply_to_post_local
                options = poll_post.poll_data.get("options", [])
                option_idx = -1
                for i, opt in enumerate(options):
                    if opt.get("text", "").strip().lower() == vote_name.strip().lower():
                        option_idx = i
                        break
                if option_idx >= 0:
                    expires_at = poll_post.poll_data.get("expires_at")
                    if expires_at:
                        try:
                            exp = datetime.datetime.fromisoformat(expires_at)
                            now = datetime.datetime.now(datetime.timezone.utc)
                            if exp < now:
                                return (200, "poll ended")
                        except (valueerror, typeerror) as ex:
                            pass
                    existing_vote = session.query(Vote).filter_by(user_id=actor_id, post_id=poll_post.id).first()
                    if existing_vote:
                        if existing_vote.option_index == option_idx:
                            return (200, "already voted")
                        options[existing_vote.option_index]["votes_count"] = max(0, options[existing_vote.option_index].get("votes_count", 0) - 1)
                        existing_vote.option_index = option_idx
                    else:
                        session.add(Vote(user_id=actor_id, post_id=poll_post.id, option_index=option_idx))
                    new_options = copy.deepcopy(options)
                    new_options[option_idx]["votes_count"] = new_options[option_idx].get("votes_count", 0) + 1
                    poll_post.poll_data = {**poll_post.poll_data, "options": new_options}
                    session.commit()
                    _voter_ids = {v.user_id for v in session.query(vote).filter_by(post_id=poll_post.id).all()}
                    _voter_ids.add(poll_post.author_id)
                    for _vid in _voter_ids:
                        broadcast_refresh_notifs(_vid)
                    if poll_post.author_id != actor_id:
                        send_push_to_user(poll_post.author_id, "vote", actor_username, poll_post.id)
                        broadcast_notif_sound(poll_post.author_id)
                    broadcast_post({
                        "id": poll_post.id,
                        "type": "update",
                        "poll_data": poll_post.poll_data,
                        "_emojis": _broadcast_emoji_list(session),
                    }, poll_post.author_id, poll_post.visibility or "public", false)
                    return (200, "voted")

            # Parse mentions ONLY from AP tag array (No regex body parsing)
            mentioned_hrefs = set()
            mentioned_names = set()
            _actor_domain = urlparse(actor.remote_url).hostname if actor.remote_url else ""

            for tag in (obj.get("tag", []) or []):
                if isinstance(tag, dict) and tag.get("type") == "Mention":
                    href = tag.get("href", "")
                    name = tag.get("name", "")
                    if href:
                        mentioned_hrefs.add(href.rstrip("/"))
                    if name and name.startswith("@"):
                        mentioned_names.add(name.lstrip("@"))
                if isinstance(tag, dict) and tag.get("type") == "Hashtag":
                    _tn = (tag.get("name", "") or "").lstrip("#").strip().lower()
                    if _tn:
                        tag_names.append(_tn)

            for _aud in all_audiences:
                _a = _aud.rstrip("/")
                if _a and _a.startswith("http"):
                    mentioned_hrefs.add(_a)
            print(f"[_handle_create MENTION DEBUG] actor={actor_url} to={to} cc={cc}", flush=True)
            print(f"[_handle_create MENTION DEBUG] mentioned_hrefs={mentioned_hrefs} mentioned_names={mentioned_names}", flush=True)

            _seen_ids = set()
            if mentioned_hrefs:
                for _href in mentioned_hrefs:
                    _matched = False
                    if BASE_URL in _href:
                        for _u in session.query(User).filter_by(is_remote=False).all():
                            local_uris = {
                                _u.actor_uri().rstrip("/"),
                                _u.actor_uri().replace("/users/", "/@").rstrip("/")
                            }
                            if _href in local_uris and _u.id not in _seen_ids:
                                mentioned_ids.append(_u.id)
                                _seen_ids.add(_u.id)
                                print(f"[_handle_create MENTION] LOCAL MATCH: href={_href} -> uid={_u.id} username={_u.username}", flush=True)
                                _matched = True
                                break
                    if not _matched:
                        u = session.query(User).filter(User.remote_url == _href).first()
                        if u and u.id not in _seen_ids:
                            mentioned_ids.append(u.id)
                            _seen_ids.add(u.id)
                            print(f"[_handle_create MENTION] REMOTE MATCH: href={_href} -> uid={u.id} username={u.username}", flush=True)
                        elif not u:
                            print(f"[_handle_create MENTION] NO MATCH: href={_href}", flush=True)
            if mentioned_names:
                for _name in mentioned_names:
                    if '@' in _name:
                        _lp, _dom = _name.split('@', 1)
                        u = session.query(User).filter(
                            User.username == _lp, User.is_remote == True,
                        ).first()
                        if u and u.id not in _seen_ids and u.remote_url:
                            _p = urlparse(u.remote_url)
                            if _p.hostname and _p.hostname.lower() == _dom.lower():
                                mentioned_ids.append(u.id)
                                _seen_ids.add(_u.id)
                                continue
                        candidates = session.query(User).filter(
                            User.username.like(f"{_lp}@%"),
                            User.is_remote == True,
                        ).all()
                        for _c in candidates:
                            if _c.id in _seen_ids:
                                continue
                            if _c.remote_url:
                                _p = urlparse(_c.remote_url)
                                if _p.hostname and _p.hostname.lower() == _dom.lower():
                                    mentioned_ids.append(_c.id)
                                    _seen_ids.add(_c.id)
                                    break
                    else:
                        if _actor_domain:
                            u = session.query(User).filter(
                                User.username == _name, User.is_remote == True,
                                User.remote_url.contains(_actor_domain)
                            ).first()
                            if u and u.id not in _seen_ids:
                                mentioned_ids.append(u.id)
                                _seen_ids.add(u.id)

            print(f"[_handle_create MENTION RESULT] mentioned_ids={mentioned_ids} (from hrefs={mentioned_hrefs}, names={mentioned_names})", flush=True)
            actor_domain = urlparse(actor.remote_url).hostname if actor.remote_url else ""
            if actor_domain:
                mute_entry = session.query(MutedServer).filter_by(domain=actor_domain).first()
                if mute_entry and mute_entry.muted and visibility == "public":
                    muted_visibility = True

        if muted_visibility:
            visibility = "home"

        # ===== PHASE 2: NETWORK I/O (no DB session held) =====

        # Fetch remote reply if not found locally
        if in_reply_to and not reply_to_post_id:
            with get_session() as fetch_s:
                _local_signer = fetch_s.query(User).join(Follow, Follow.follower_id == User.id).filter(Follow.following_id == actor_id, User.is_remote == False).first()
                if not _local_signer:
                    _local_signer = _get_instance_actor(fetch_s)
                fetched_reply = _fetch_remote_post(in_reply_to, _local_signer, fetch_s)
                if fetched_reply:
                    fetch_s.commit()
                    reply_to_post_id = fetched_reply.id
                    try:
                        _ra = fetched_reply.author
                        broadcast_post({
                            "id": fetched_reply.id,
                            "number": fetched_reply.number or "",
                            "content": fetched_reply.content,
                            "summary": fetched_reply.summary or "",
                            "visibility": fetched_reply.visibility or "public",
                            "created_at": fetched_reply.created_at.isoformat() if fetched_reply.created_at else "",
                            "author": {
                                "id": _ra.id, "username": _ra.username,
                                "display_name": _ra.display_name or _ra.username,
                                "avatar": _ra.profile_image or "", "header": _ra.header_image or "",
                                "summary": _ra.summary or "", "is_admin": _ra.is_admin,
                                "is_locked": getattr(_ra, "is_locked", false),
                                "is_limited": getattr(_ra, "is_limited", false),
                                "is_remote": _ra.is_remote, "ap_id": _ra.remote_url or "",
                            },
                            "likes_count": 0, "boosts_count": 0, "replies_count": 0,
                            "liked": false, "boosted": false, "bookmarked": false, "is_mine": false,
                            "is_dm": false, "is_sensitive": getattr(fetched_reply, "is_sensitive", false) or false,
                            "ap_id": fetched_reply.ap_id or "", "media_attachments": fetched_reply.media_attachments or [],
                            "poll_data": fetched_reply.poll_data, "my_vote": none, "reactions": {}, "my_reaction": none,
                            "quote_of_id": fetched_reply.quote_of_id or None, "quote_of_ap_id": fetched_reply.quote_of_ap_id or "",
                            "_emojis": _broadcast_emoji_list(fetch_s),
                        }, fetched_reply.author_id, fetched_reply.visibility or "public", false)
                    except Exception:
                        pass

        # Cache media attachments
        raw_attachments = obj.get("attachment", []) if isinstance(obj, dict) else []
        if isinstance(raw_attachments, dict):
            raw_attachments = [raw_attachments]
        elif not isinstance(raw_attachments, list):
            raw_attachments = []
        media_list = []
        _att_has_sensitive = False
        for att in raw_attachments:
            if not isinstance(att, dict):
                continue
            att_type = att.get("mediaType", "")
            att_as2_type = att.get("type", "")
            url = ""
            if isinstance(att.get("url"), str):
                url = att["url"]
            elif isinstance(att.get("url"), dict):
                url = att["url"].get("href", "")
            if not url:
                continue
            att_sensitive = att.get("sensitive", False)
            if att_sensitive:
                _att_has_sensitive = True
            cached = _cache_remote_media(url)
            if att_type.startswith("image/") or att_as2_type == "Image":
                media_list.append({"url": cached, "type": "image"})
                print(f"[_handle_create MEDIA] image url={cached} sensitive={att_sensitive}", flush=True)
            elif att_type.startswith("video/") or att_as2_type == "Video":
                media_list.append({"url": cached, "type": "video"})
                print(f"[_handle_create MEDIA] video url={cached} sensitive={att_sensitive}", flush=True)
            elif att_as2_type == "Document" or att_type.startswith("audio/"):
                if att_type.startswith("image/") or att_type.startswith("video/"):
                    mtype = "video" if att_type.startswith("video/") else "image"
                else:
                    mtype = "image"
                media_list.append({"url": cached, "type": mtype})
                print(f"[_handle_create MEDIA] Document({att_type}) url={cached} type={mtype} sensitive={att_sensitive}", flush=True)

        # Extract quote reference from Note (FEP-044f / Mastodon / Misskey / Firefish compat)
        quote_of_ap_id = ""
        quote_of_id = None
        if isinstance(obj, dict):
            quote_url = (
                obj.get("quote")
                or obj.get("quoteUrl")
                or obj.get("quoteUri")
                or obj.get("_misskey_quote")
                or ""
            )
            if not quote_url and isinstance(obj.get("tag"), list):
                for _tag in obj["tag"]:
                    if not isinstance(_tag, dict):
                        continue
                    if _tag.get("type") == "Quote":
                        quote_url = _tag.get("href") or _tag.get("id") or ""
                    elif _tag.get("type") == "Link" and _tag.get("rel") == "https://misskey-hub.net/ns#_misskey_quote":
                        quote_url = _tag.get("href") or ""
                    if quote_url:
                        break
            try:
                _q_fields = {k: obj.get(k) for k in ("quote", "quoteUrl", "quoteUri", "_misskey_quote") if obj.get(k)}
                if quote_url:
                    print(f"[_handle_create QUOTE] post_id={post_id} url={quote_url} fields={_q_fields}", flush=True)
            except Exception:
                pass
            if quote_url and isinstance(quote_url, str):
                quote_of_ap_id = quote_url
                try:
                    with get_session() as quote_s:
                        quote_post = _fetch_remote_post(quote_url, actor, quote_s)
                        if quote_post:
                            quote_s.commit()
                            quote_of_id = quote_post.id
                            print(f"[_handle_create QUOTE OK] post_id={quote_post.id}", flush=True)
                        else:
                            print(f"[_handle_create QUOTE FETCH FAIL] url={quote_url}", flush=True)
                except Exception as e:
                    logger.error("[QUOTE] url=%s %s", quote_url, e, exc_info=True)

        # Fetch link preview for URLs in remote post content (skip if quote post)
        link_preview = None
        if not quote_of_ap_id:
            _url_match_lp = re.search(r'https?://(?!.*/tags/)[^\s<>"\')\]#]+', content or "")
            if _url_match_lp:
                _url_lp = _url_match_lp.group(0)
                try:
                    _resp_lp = httpx.get(_url_lp, headers={"User-Agent": "WRIT/1.0"}, timeout=5, follow_redirects=True)
                    if _resp_lp.status_code == 200:
                        _html_lp = _resp_lp.text
                        def _og_lp(n):
                            _m = re.search(f'<meta[^>]+property="og:{n}"[^>]+content="([^"]*)"', _html_lp, re.I)
                            if not _m:
                                _m = re.search(f'<meta[^>]+content="([^"]*)"[^>]+property="og:{n}"', _html_lp, re.I)
                            return _m.group(1) if _m else ""
                        _og_title_lp = _og_lp("title") or (re.search(r'<title>([^<]*)</title>', _html_lp, re.I).group(1) if re.search(r'<title>([^<]*)</title>', _html_lp, re.I) else "")
                        _og_desc_lp = _og_lp("description")
                        _og_img_lp = _og_lp("image")
                        if _og_img_lp and _og_img_lp.startswith("/"):
                            _p_lp = urlparse(_url_lp)
                            _og_img_lp = f"{_p_lp.scheme}://{_p_lp.netloc}{_og_img_lp}"
                        if _og_title_lp:
                            link_preview = {"url": _url_lp, "title": html.unescape(_og_title_lp[:200]), "description": html.unescape(_og_desc_lp[:400]) if _og_desc_lp else "", "image": _og_img_lp or ""}
                except Exception:
                    pass

        # ===== PHASE 3: DB WRITES (new session) =====
        with get_session() as session:
            reply_to_post = None
            if reply_to_post_id:
                reply_to_post = session.query(Post).get(reply_to_post_id)

            post = Post(
                author_id=actor_id,
                content=content,
                summary=summary,
                visibility=visibility,
                mentioned_user_ids=mentioned_ids,
                ap_id=post_id,
                in_reply_to_ap_id=in_reply_to,
                in_reply_to_id=reply_to_post_id,
                media_attachments=media_list if media_list else None,
                poll_data=poll_data,
                is_dm=is_incoming_dm,
                is_sensitive=obj.get("sensitive", False) or _att_has_sensitive,
                quote_of_ap_id=quote_of_ap_id,
                quote_of_id=quote_of_id,
            )
            if quote_of_ap_id and post.content:
                post.content = re.sub(
                    r'^[\s\n]*RE:\s*<a[^>]*>[^<]*</a>\s*[\n\s]*',
                    '', post.content, count=1, flags=re.I
                )
                post.content = re.sub(
                    r'^[\s\n]*RE:\s*https?://\S+\s*[\n\s]*',
                    '', post.content, count=1, flags=re.I
                )
            if link_preview:
                post.link_preview = link_preview
            session.add(post)
            session.flush()

            # Background retry if remote parent not found
            if in_reply_to and not reply_to_post_id:
                _retry_fetch_reply(post.id, in_reply_to)

            # Resolve and set hashtag tags
            tag_list = []
            for tag_name in tag_names:
                _existing = session.query(Tag).filter_by(name=tag_name).first()
                if not _existing:
                    _existing = Tag(name=tag_name)
                    session.add(_existing)
                    session.flush()
                tag_list.append(_existing)
            post.tag_list = tag_list

            # Notify local users mentioned or replied to
            _notified = set()
            if reply_to_post and reply_to_post.author_id != actor_id:
                _notified.add(reply_to_post.author_id)
                session.add(Notification(
                    user_id=reply_to_post.author_id,
                    from_user_id=actor_id,
                    notification_type="mention",
                    post_id=post.id,
                ))
            for _mu_id in mentioned_ids:
                if _mu_id != actor_id and _mu_id not in _notified:
                    _notified.add(_mu_id)
                    session.add(Notification(
                        user_id=_mu_id, from_user_id=actor_id,
                        notification_type="mention", post_id=post.id,
                    ))

            followers = session.query(Follow).filter(
                Follow.following_id == actor_id,
                Follow.notify_on_post == True,
            ).all()
            for f in followers:
                if not f.follower.is_remote and f.follower.id != actor_id and f.follower.id not in _notified:
                    _notified.add(f.follower.id)
                    session.add(Notification(
                        user_id=f.follower.id,
                        from_user_id=actor_id,
                        notification_type="post",
                        post_id=post.id,
                    ))

            session.commit()
            # Process emoji tags AFTER commit (separate session for HTTP I/O)
            try:
                with get_session() as emoji_s:
                    _process_emoji_tags(obj.get("tag", []), emoji_s)
                    emoji_s.commit()
                    _refresh_emoji_cache_forcibly(emoji_s)
            except Exception:
                pass
            _push_notified = set()
            if reply_to_post and reply_to_post.author_id != actor_id and reply_to_post.author_id not in _push_notified:
                _push_notified.add(reply_to_post.author_id)
                send_push_to_user(reply_to_post.author_id, "mention", actor_username, post.id)
                broadcast_notif_sound(reply_to_post.author_id)
            for _mu_id in mentioned_ids:
                if _mu_id != actor_id and _mu_id not in _push_notified:
                    _push_notified.add(_mu_id)
                    send_push_to_user(_mu_id, "mention", actor_username, post.id)
                    broadcast_notif_sound(_mu_id)
            for f in followers:
                if not f.follower.is_remote and f.follower.id != actor_id and f.follower.id not in _push_notified:
                    _push_notified.add(f.follower.id)
                    send_push_to_user(f.follower.id, "post", actor_username, post.id)
                    broadcast_notif_sound(f.follower.id)
            broadcast_refresh_notifs()
            try:
                broadcast("new_post", {"post_id": post.id, "author_id": actor_id})
            except Exception as e:
                logger.error("broadcast failed: %s", e, exc_info=True)
            try:
                _broadcast_emojis = _broadcast_emoji_list(session)
                author = post.author
                _reply_ctx = None
                if reply_to_post and not getattr(reply_to_post, 'is_deleted', False):
                    _rp_author = reply_to_post.author
                    _reply_ctx = {
                        "id": reply_to_post.id,
                        "number": reply_to_post.number or "",
                        "content": (reply_to_post.content or "")[:200],
                        "summary": (reply_to_post.summary or ""),
                        "author": {
                            "id": _rp_author.id, "username": _rp_author.username,
                            "display_name": _rp_author.display_name or _rp_author.username,
                            "avatar": _rp_author.profile_image or "",
                            "header": _rp_author.header_image or "",
                            "summary": _rp_author.summary or "", "is_admin": _rp_author.is_admin,
                            "is_locked": getattr(_rp_author, "is_locked", False),
                            "is_limited": getattr(_rp_author, "is_limited", False),
                            "is_remote": _rp_author.is_remote, "ap_id": _rp_author.remote_url or "",
                        },
                        "visibility": reply_to_post.visibility or "public",
                    }
                post_json = {
                    "id": post.id,
                    "number": post.number or "",
                    "content": post.content,
                    "summary": post.summary or "",
                    "visibility": post.visibility or "public",
                    "created_at": post.created_at.isoformat() if post.created_at else "",
                    "author": {
                        "id": author.id,
                        "username": author.username,
                        "display_name": author.display_name or author.username,
                        "avatar": author.profile_image or "",
                        "header": author.header_image or "",
                        "summary": author.summary or "",
                        "is_admin": author.is_admin,
                        "is_locked": getattr(author, 'is_locked', False),
                        "is_limited": getattr(author, 'is_limited', False),
                        "is_remote": author.is_remote,
                        "ap_id": author.remote_url or "",
                    },
                    "likes_count": 0,
                    "boosts_count": 0,
                    "replies_count": 0,
                    "liked": False,
                    "boosted": False,
                    "bookmarked": False,
                    "is_mine": False,
                    "is_dm": is_incoming_dm,
                    "is_sensitive": getattr(post, 'is_sensitive', False) or False,
                    "ap_id": post.ap_id or "",
                    "media_attachments": post.media_attachments or [],
                    "poll_data": post.poll_data,
                    "my_vote": None,
                    "reactions": {},
                    "my_reaction": None,
                    "mentioned_user_ids": mentioned_ids,
                    "reply_context": _reply_ctx,
                    "link_preview": post.link_preview,
                    "quote_of_id": post.quote_of_id or None,
                    "quote_of_ap_id": post.quote_of_ap_id or "",
                    "_emojis": _broadcast_emojis,
                }
                broadcast_post(post_json, actor_id, visibility, is_incoming_dm)
            except Exception as e:
                logger.error("timeline broadcast failed: %s", e, exc_info=True)

        return (200, "Created")
    return (200, "OK")


def _broadcast_emoji_list(session):
    """Return ALL emojis from DB formatted for SSE broadcast payload."""
    return [{"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]} for e in _load_emojis(session)]


def _build_reactions(session, post_id: int) -> dict:
    """Build reactions dict from Like table for a given post."""
    _reactions = {}
    _default_react = "★"
    for _pid, _react, _cnt in session.query(Like.post_id, func.coalesce(Like.reaction, _default_react), func.count(Like.id)).filter(
        Like.post_id == post_id
    ).group_by(Like.post_id, Like.reaction).order_by(Like.post_id, func.min(Like.id)).all():
        if _pid not in _reactions:
            _reactions[_pid] = {}
        _reactions[_pid][_react] = _cnt
    return _reactions


def _handle_like(activity: dict) -> tuple[int, str]:
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    object_url = activity["object"] if isinstance(activity.get("object"), str) else ""
    activity_id = activity.get("id", "")
    reaction = activity.get("_misskey_reaction", activity.get("content", activity.get("reaction", "")))

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
                    import threading as _thr
                    _thr.Thread(target=_background_import_emoji, args=(_import_data["url"], _import_data["kw"], _import_data["domain"]), daemon=True).start()

        existing = session.query(Like).filter_by(user_id=actor_id, post_id=post.id).first()
        if existing:
            if reaction and existing.reaction != reaction:
                existing.reaction = reaction
                _existing_n = session.query(Notification).filter_by(
                    user_id=post.author_id, from_user_id=actor_id, notification_type="like", post_id=post.id
                ).first()
                if _existing_n:
                    _author_reactions = getattr(post.author, 'enable_reactions', True)
                    if _author_reactions:
                        _r = reaction or "★"
                        _existing_n.metadata_json = json.dumps({"reaction": _r})
                    else:
                        _existing_n.metadata_json = ""
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
            _author_reactions = getattr(post.author, 'enable_reactions', True)
            _notif_meta = json.dumps({"reaction": reaction or "★"}) if _author_reactions else ""
            n = Notification(
                user_id=post.author_id,
                from_user_id=actor_id,
                notification_type="like",
                post_id=post.id,
                metadata_json=_notif_meta,
            )
            session.add(n)
            session.commit()
            send_push_to_user(post.author_id, "like", actor_username, post.id)
            broadcast_notif_sound(post.author_id)
            broadcast_refresh_notifs(post.author_id)
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

    actor_id = ''
    try:
        actor = _resolve_actor(actor_url, sign_as=_sign_as)
        if not actor:
            return (404, "Actor not found")
        actor_id = actor.id
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
                if datetime.datetime.fromisoformat(expires_at) < datetime.datetime.now(datetime.timezone.utc):
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
    raw_actor = activity.get("actor")
    if not raw_actor:
        return (400, "Missing actor")
    actor_url = raw_actor if isinstance(raw_actor, str) else raw_actor[0]
    raw_object = activity.get("object")
    object_url = raw_object if isinstance(raw_object, str) else ""
    activity_id = activity.get("id", "")
    print(f"[ANNOUNCE] actor={actor_url} object_type={type(raw_object).__name__} object_url={object_url[:120]}", flush=True)

    if not object_url and isinstance(raw_object, dict):
        object_url = raw_object.get("id", "")
        print(f"[ANNOUNCE] embedded object, extracted id={object_url[:120]}", flush=True)

    if not object_url:
        print("[ANNOUNCE] no object_url, returning early", flush=True)
        return (200, "OK")

    if object_url.endswith("/activity"):
        object_url = object_url[:-len("/activity")]
        print(f"[ANNOUNCE] stripped /activity suffix → {object_url[:120]}", flush=True)

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if post and post.boost_of_id:
            post = session.query(Post).get(post.boost_of_id)
        _sign_as = session.query(User).get(post.author_id) if post else None
        if not _sign_as:
            _sign_as = _get_instance_actor(session)
    print(f"[ANNOUNCE] db_post={'found id='+str(post.id) if post else 'none'} signer={'id='+str(_sign_as.id) if _sign_as else 'none'}", flush=True)
    actor = _resolve_actor(actor_url, sign_as=_sign_as)
    if not actor:
        print("[ANNOUNCE] actor not found, returning 404", flush=True)
        return (404, "Actor not found")

    actor_id = actor.id
    actor_username = actor.username

    with get_session() as session:
        post = session.query(Post).filter_by(ap_id=object_url).first()
        if post and post.boost_of_id:
            post = session.query(Post).get(post.boost_of_id)
        print(f"[ANNOUNCE] session2 post={'found id='+str(post.id) if post else 'none'}", flush=True)
        if not post:
            _local_signer = _get_instance_actor(session)
            try:
                post = _fetch_remote_post(object_url, _local_signer, session)
                if post and post.boost_of_id:
                    post = session.query(Post).get(post.boost_of_id)
                print(f"[ANNOUNCE] fetch_remote_post result={'id='+str(post.id) if post else 'None'}", flush=True)
            except Exception as e:
                logger.warning("Announce: _fetch_remote_post failed for %s: %s", object_url, e)
                print(f"[ANNOUNCE] fetch_remote_post EXCEPTION: {e}", flush=True)
                post = None
            if not post:
                logger.warning("Announce: could not fetch remote post %s", object_url)
                print(f"[ANNOUNCE] could not fetch remote post, returning early", flush=True)
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

        session.commit()

        # 5. 커밋 이후 외부 연동 (푸시 및 스트리밍) 처리
        if not existing_n:
            send_push_to_user(post.author_id, "boost", actor_username, post.id)
            broadcast_notif_sound(post.author_id)

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
                    "enable_reactions": getattr(u, "enable_reactions", True),
                    "aliases": (u.aliases or []) if hasattr(u, 'aliases') else [],
                    "moved_to": getattr(u, "moved_to", "") or "",
                }
            _author_data = _safe_user_json(_a)
            if not _author_data:
                _a = session.query(User).get(post.author_id)
                _author_data = _safe_user_json(_a)
            broadcast_post({
                "id": post.id,
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
                "ap_id": post.ap_id or "", "media_attachments": post.media_attachments or [],
                "poll_data": post.poll_data, "my_vote": None,
                "reactions": reactions_data,
                "my_reaction": None,
                "boosted_by": _safe_user_json(_actor),
                "mentioned_user_ids": [],
                "quote_of_id": post.quote_of_id or None, "quote_of_ap_id": post.quote_of_ap_id or "",
                "_emojis": _broadcast_emoji_list(session),
            }, post.author_id, post.visibility or "public", False)
        except Exception as e:
            logger.error("Failed to broadcast boost from AP: %s", e, exc_info=True)

    print(f"[ANNOUNCE] success post_id={post.id} by actor_id={actor_id}", flush=True)
    return (200, "Announced")

def _handle_block(activity: dict) -> tuple[int, str]:
    actor_url = activity.get("actor", "")
    object_url = activity.get("object", "")
    if isinstance(actor_url, list):
        actor_url = actor_url[0]
    if isinstance(object_url, dict):
        object_url = object_url.get("id", "")

    local_username = _parse_username_from_url(object_url)
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
            deleted_incoming = session.query(Follow).filter_by(follower_id=remote.id, following_id=local_user.id).delete()
            deleted_outgoing = session.query(Follow).filter_by(follower_id=local_user.id, following_id=remote.id).delete()
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
            resp = _validated_get(obj, headers={"Accept": "application/activity+json", "User-Agent": WRIT_USER_AGENT}, timeout=10)
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

        local_username = _parse_username_from_url(object_url)
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

    elif obj_type == "Like":
        actor_url = activity.get("actor", "")
        if isinstance(actor_url, list):
            actor_url = actor_url[0]
        object_url = obj.get("object", "") if isinstance(obj, dict) else ""

        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            if post:
                _sign_as = session.query(User).get(post.author_id)
            else:
                _sign_as = None
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

    elif obj_type == "Announce":
        actor_url = activity.get("actor", "")
        object_url = obj.get("object", "") if isinstance(obj, dict) else ""
        if isinstance(actor_url, list):
            actor_url = actor_url[0]

        with get_session() as session:
            post = session.query(Post).filter_by(ap_id=object_url).first()
            if post:
                _sign_as = session.query(User).get(post.author_id)
            else:
                _sign_as = None
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

    elif obj_type == "Block":
        actor_url = obj.get("actor", activity.get("actor", ""))
        object_url = obj.get("object", "")
        if isinstance(actor_url, list):
            actor_url = actor_url[0]
        if isinstance(object_url, dict):
            object_url = object_url.get("id", "")

        local_username = _parse_username_from_url(object_url)
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
            resp = _validated_get(object_data, headers={"Accept": "application/activity+json", "User-Agent": WRIT_USER_AGENT}, timeout=10)
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
                        print(f"[AP] _handle_update REJECTED: actor {actor_url} does not own post {obj_id}", flush=True)
                        return (403, "Actor does not own this post")
                    # Update content/summary
                    new_content = object_data.get("content", "")
                    if not new_content:
                        cm = object_data.get("contentMap")
                        if isinstance(cm, dict) and cm:
                            new_content = next(iter(cm.values()), "")
                    if new_content:
                        post.content = _html_to_newlines(process_post_content(_sanitize_html(new_content), post))
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
            }, actor_id, post.visibility or "public", False)
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
                print(f"[AP] _handle_delete REJECTED: actor {actor_url} does not own post {object_url} (author={post.author.remote_url})", flush=True)
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


def _notify_admins(session, reporter, target_type, target_id, reason):
    _admins = session.query(User).filter(User.role.in_(["admin", "moderator", "owner"])).all()
    for _a in _admins:
        if _a.id == reporter.id:
            continue
        session.add(Notification(
            user_id=_a.id, from_user_id=reporter.id,
            notification_type="moderation",
            metadata_json=json.dumps({"type": "report", "target_type": target_type, "target_id": target_id, "target_label": "", "reason": (reason or "")[:200]}),
        ))
    session.flush()
    for _a in _admins:
        if _a.id != reporter.id:
            send_push_to_user(_a.id, "moderation", reporter.username)
            broadcast_notif_sound(_a.id)

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
            _r = _validated_get(actor_url, headers={"Accept": "application/activity+json"}, timeout=10)
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
            if not user:
                if BASE_URL in obj_url:
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
            if old_actor_url not in aliases and local_user.actor_uri() not in aliases:
                return (403, "New account has not aliased the old account")
        else:
            # new_actor is detached; query fresh from session for alias check
            new_actor_in_session = session.query(User).filter_by(id=new_actor_id).first()
            if new_actor_in_session and new_actor_in_session.is_remote:
                aliases = new_actor_in_session.aliases or []
                if old_actor_url not in aliases and local_user.remote_url not in aliases:
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
