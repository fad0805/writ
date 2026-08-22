import contextlib
import copy
import datetime
import html
import logging
import re
import sys
from urllib.parse import urlparse

from app.config.settings import BASE_URL
from app.core.activitypub._emoji import _process_emoji_tags
from app.core.activitypub._fetch import (
    _extract_og_title,
    _extract_quote_url,
    _fetch_remote_post,
    _resolve_actor,
    _retry_fetch_reply,
)
from app.core.activitypub._inbound_common import _broadcast_emoji_list
from app.core.activitypub._media import _cache_remote_media
from app.core.activitypub._utils import _get_instance_actor
from app.core.broadcast import broadcast_post
from app.core.eventbus import broadcast
from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_notif_sound, broadcast_refresh_notifs
from app.db.database import get_session, username_prefix_like
from app.models import Follow, MutedServer, Notification, Post, Tag, User, Vote
from app.utils.content_parser import _sanitize_html, process_post_content
from app.utils.emoji import _refresh_emoji_cache_forcibly
from app.utils.http import validate_url, validated_get
from app.utils.urls import extract_remote_url

logger = logging.getLogger("writ.activitypub")


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
        remote_url = extract_remote_url(obj, post_id)
        content = process_post_content(_sanitize_html(raw_content), obj)
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
                    for new_opt in list(poll_data.get("options", [])):
                        for old_opt in list(existing.poll_data.get("options", [])):
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
                            now = datetime.datetime.now(datetime.UTC)
                            if exp < now:
                                return (200, "poll ended")
                        except (ValueError, TypeError):
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
                    _voter_ids = {v.user_id for v in session.query(Vote).filter_by(post_id=poll_post.id).all()}
                    _voter_ids.add(poll_post.author_id)
                    for _vid in _voter_ids:
                        broadcast_refresh_notifs(_vid)
                    if poll_post.author_id != actor_id:
                        send_push_to_user(int(poll_post.author_id), "vote", str(actor_username), int(poll_post.id))
                        broadcast_notif_sound(int(poll_post.author_id))
                    broadcast_post({
                        "id": int(poll_post.id),
                        "type": "update",
                        "poll_data": poll_post.poll_data,
                        "_emojis": _broadcast_emoji_list(session),
                    }, int(poll_post.author_id), str(poll_post.visibility or "public"), False)
                    return (200, "voted")

            # Parse mentions ONLY from AP tag array (No regex body parsing)
            mentioned_hrefs = set()
            mentioned_names = set()
            _actor_domain = urlparse(str(actor.remote_url)).hostname if actor.remote_url else ""

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
            logger.debug("[_handle_create MENTION DEBUG] actor=%s to=%s cc=%s", actor_url, to, cc)
            logger.debug("[_handle_create MENTION DEBUG] mentioned_hrefs=%s mentioned_names=%s", mentioned_hrefs, mentioned_names)

            _seen_ids = set()
            if mentioned_hrefs:
                for _href in mentioned_hrefs:
                    _matched = False
                    if BASE_URL in _href:
                        # 로컬 유저 전체 스캔 대신 URL 경로에서 username을 뽑아 인덱스 조회
                        _path = urlparse(_href).path.rstrip("/")
                        _uname = None
                        for _prefix in ("/users/", "/@"):
                            if _path.startswith(_prefix):
                                _uname = _path[len(_prefix):].split("/")[0].split("@")[0]
                                break
                        if _uname:
                            u = session.query(User).filter(
                                User.username == _uname, User.is_remote == False,
                            ).first()
                            if u and u.id not in _seen_ids:
                                mentioned_ids.append(u.id)
                                _seen_ids.add(u.id)
                                logger.debug("[_handle_create MENTION] LOCAL MATCH: href=%s -> uid=%s username=%s", _href, u.id, u.username)
                                _matched = True
                    if not _matched:
                        u = session.query(User).filter(User.remote_url == _href).first()
                        if u and u.id not in _seen_ids:
                            mentioned_ids.append(u.id)
                            _seen_ids.add(u.id)
                            logger.debug("[_handle_create MENTION] REMOTE MATCH: href=%s -> uid=%s username=%s", _href, u.id, u.username)
                        elif not u:
                            logger.debug("[_handle_create MENTION] NO MATCH: href=%s", _href)
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
                                _seen_ids.add(u.id)
                                continue
                        candidates = session.query(User).filter(
                            username_prefix_like(User.username, f"{_lp}@"),
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

            logger.debug("[_handle_create MENTION RESULT] mentioned_ids=%s (from hrefs=%s, names=%s)", mentioned_ids, mentioned_hrefs, mentioned_names)
            actor_domain = urlparse(str(actor.remote_url)).hostname if actor.remote_url else ""
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
                                "is_locked": getattr(_ra, "is_locked", False),
                                "is_limited": getattr(_ra, "is_limited", False),
                                "is_remote": _ra.is_remote, "ap_id": _ra.remote_url or "",
                            },
                            "likes_count": 0, "boosts_count": 0, "replies_count": 0,
                            "liked": False, "boosted": False, "bookmarked": False, "is_mine": False,
                            "is_dm": False, "is_sensitive": getattr(fetched_reply, "is_sensitive", False) or False,
                            "ap_id": fetched_reply.ap_id or "", "media_attachments": fetched_reply.media_attachments or [],
                            "poll_data": fetched_reply.poll_data, "my_vote": None, "reactions": {}, "my_reaction": None,
                            "quote_of_id": fetched_reply.quote_of_id or None, "quote_of_ap_id": fetched_reply.quote_of_ap_id or "",
                            "_emojis": _broadcast_emoji_list(fetch_s),
                        }, fetched_reply.author_id, fetched_reply.visibility or "public", False)
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
                logger.debug("[_handle_create MEDIA] image url=%s sensitive=%s", cached, att_sensitive)
            elif att_type.startswith("video/") or att_as2_type == "Video":
                media_list.append({"url": cached, "type": "video"})
                logger.debug("[_handle_create MEDIA] video url=%s sensitive=%s", cached, att_sensitive)
            elif att_as2_type == "Document" or att_type.startswith("audio/"):
                if att_type.startswith(("image/", "video/")):
                    mtype = "video" if att_type.startswith("video/") else "image"
                else:
                    mtype = "image"
                media_list.append({"url": cached, "type": mtype})
                logger.debug("[_handle_create MEDIA] Document(%s) url=%s type=%s sensitive=%s", att_type, cached, mtype, att_sensitive)

        # Extract quote reference from Note (FEP-044f / Mastodon / Misskey / Firefish compat)
        quote_of_ap_id = ""
        quote_of_id = None
        if isinstance(obj, dict):
            quote_url = _extract_quote_url(obj, content)
            try:
                _q_fields = {k: obj.get(k) for k in ("quote", "quoteUrl", "quoteUri", "quote_uri", "_misskey_quote") if obj.get(k)}
                if quote_url:
                    logger.debug("[_handle_create QUOTE] post_id=%s url=%s fields=%s", post_id, quote_url, _q_fields)
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
                            logger.debug("[_handle_create QUOTE OK] post_id=%s", quote_post.id)
                        else:
                            logger.debug("[_handle_create QUOTE FETCH FAIL] url=%s", quote_url)
                except Exception as e:
                    logger.error("[QUOTE] url=%s %s", quote_url, e, exc_info=True)

        # Fetch link preview for URLs in remote post content (skip if quote post)
        link_preview = None
        if not quote_of_ap_id:
            _url_match_lp = re.search(r'https?://(?!.*/tags/)[^\s<>"\')\]#]+', content or "")
            if _url_match_lp:
                _url_lp = _url_match_lp.group(0)
                try:
                    _resp_lp = None if not validate_url(_url_lp) else validated_get(_url_lp, timeout=5)
                    if _resp_lp and _resp_lp.status_code == 200:
                        _html_lp = _resp_lp.text
                        def _og_lp(n):
                            _m = re.search(f'<meta[^>]+property="og:{n}"[^>]+content="([^"]*)"', _html_lp, re.I)
                            if not _m:
                                _m = re.search(f'<meta[^>]+content="([^"]*)"[^>]+property="og:{n}"', _html_lp, re.I)
                            return _m.group(1) if _m else ""
                        _og_title_lp = _og_lp("title") or _extract_og_title(_html_lp)
                        _og_desc_lp = _og_lp("description")
                        _og_img_lp = _og_lp("image")
                        if _og_img_lp and _og_img_lp.startswith("/"):
                            _p_lp = urlparse(_url_lp)
                            _og_img_lp = f"{_p_lp.scheme}://{_p_lp.netloc}{_og_img_lp}"
                        if _og_img_lp and not validate_url(_og_img_lp):
                            _og_img_lp = ""
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
                remote_url=remote_url,
                in_reply_to_ap_id=in_reply_to,
                in_reply_to_id=reply_to_post_id,
                media_attachments=media_list if media_list else None,
                poll_data=poll_data,
                is_dm=is_incoming_dm,
                is_sensitive=obj.get("sensitive", False) or _att_has_sensitive,
                quote_of_ap_id=quote_of_ap_id,
                quote_of_id=quote_of_id,
            )
            published = obj.get("published", "")
            if published:
                with contextlib.suppress(Exception):
                    post.created_at = datetime.datetime.fromisoformat(published.replace("Z", "+00:00"))  # type: ignore[assignment]
            if quote_of_ap_id and post.content:
                post.content = re.sub(
                    r'^[\s\n]*RE:\s*<a[^>]*>[^<]*</a>\s*[\n\s]*',
                    '', str(post.content), count=1, flags=re.I
                )  # type: ignore[assignment]
                post.content = re.sub(
                    r'^[\s\n]*RE:\s*https?://\S+\s*[\n\s]*',
                    '', str(post.content), count=1, flags=re.I
                )  # type: ignore[assignment]
                post.content = re.sub(
                    r'\s*RE:\s*https?://\S+\s*$',
                    '', str(post.content), count=1, flags=re.I
                )  # type: ignore[assignment]
                post.content = re.sub(
                    r'\s*RE:\s*<a[^>]*>[^<]*</a>\s*$',
                    '', str(post.content), count=1, flags=re.I
                )  # type: ignore[assignment]
            if link_preview:
                post.link_preview = link_preview  # type: ignore[assignment]
            session.add(post)
            session.flush()

            # Background retry if remote parent not found
            if in_reply_to and not reply_to_post_id:
                _retry_fetch_reply(int(post.id), in_reply_to)

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
                send_push_to_user(int(reply_to_post.author_id), "mention", str(actor_username), int(post.id))
                broadcast_notif_sound(int(reply_to_post.author_id))
            for _mu_id in mentioned_ids:
                if _mu_id != actor_id and _mu_id not in _push_notified:
                    _push_notified.add(_mu_id)
                    send_push_to_user(_mu_id, "mention", str(actor_username), int(post.id))
                    broadcast_notif_sound(_mu_id)
            for f in followers:
                if not f.follower.is_remote and f.follower.id != actor_id and f.follower.id not in _push_notified:
                    _push_notified.add(f.follower.id)
                    send_push_to_user(int(f.follower.id), "post", str(actor_username), int(post.id))
                    broadcast_notif_sound(int(f.follower.id))
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
                broadcast_post(post_json, int(actor_id), visibility)
            except Exception as e:
                logger.error("timeline broadcast failed: %s", e, exc_info=True)

        return (200, "Created")
    return (200, "OK")
