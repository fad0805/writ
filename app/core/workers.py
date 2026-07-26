import datetime
import base64
import hashlib
import json
import logging
import time
from urllib.parse import urlparse

from app.config.settings import SECRET_KEY, BASE_URL
from app.core.activitypub import _deliver_sync, _send_delete_post
from app.core.timeline_stream import broadcast_delete, broadcast_refresh_notifs
from app.db.database import get_session, engine
from app.models import User, PendingDelivery, Post, Like, Boost, Bookmark, Vote, Notification
from app.utils.crypto import sign_string, get_private_key
from app.utils.storage import get_storage

logger = logging.getLogger(__name__)


def delivery_worker():
    while True:
        time.sleep(30)
        try:
            with get_session() as s:
                items = s.query(PendingDelivery).filter_by(status="pending").order_by(PendingDelivery.created_at).limit(50).all()
                for item in items:
                    try:
                        sender = s.query(User).get(item.sender_id)
                        if not sender:
                            item.status = "failed"
                            item.last_error = "Sender not found"
                            continue
                        activity = json.loads(item.activity_json)
                        body = json.dumps(activity, ensure_ascii=True, sort_keys=True).encode("utf-8")
                        digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
                        date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
                        parsed = urlparse(item.inbox_url)
                        path = parsed.path or "/"
                        signed_string = f"(request-target): post {path}\nhost: {parsed.netloc}\ndate: {date}\ndigest: SHA-256={digest}"
                        signature = sign_string(signed_string, get_private_key(sender, SECRET_KEY))
                        signature_header = (
                            f'keyId="{sender.actor_uri()}#main-key",'
                            f'algorithm="rsa-sha256",'
                            f'headers="(request-target) host date digest",'
                            f'signature="{signature}"'
                        )
                        headers = {
                            "Content-Type": "application/activity+json",
                            "Signature": signature_header,
                            "Date": date,
                            "Digest": f"SHA-256={digest}",
                            "Host": parsed.netloc,
                        }
                        ok = _deliver_sync(item.inbox_url, body, headers)
                        if ok:
                            s.delete(item)
                        else:
                            item.attempts += 1
                            if item.attempts >= 7:
                                item.status = "failed"
                            item.last_error = "Max retries reached"
                    except Exception as e:
                        item.attempts += 1
                        item.last_error = str(e)
                        if item.attempts >= 7:
                            item.status = "failed"
                s.commit()
        except Exception as e:
            logger.error("Delivery worker error: %s", e, exc_info=True)


def refresh_remote_profiles():
    """Cycle updated_at so oldest-refreshed users get picked eventually (HTTP refresh is manual)."""
    while True:
        time.sleep(600)
        try:
            with get_session() as _s:
                for ru in _s.query(User).filter(User.is_remote == True).order_by(User.updated_at.asc()).limit(5).all():
                    ru.updated_at = datetime.datetime.now(datetime.timezone.utc)
                _s.commit()
        except Exception:
            pass


def auto_delete_expired_posts():
    """Hard-delete expired posts daily at 3 AM server time.
    Checks CPU and DB load before and during execution; aborts if too busy.
    Uses user.post_lifetime (days) + post.created_at to determine expiry."""

    def _next_3am():
        now = datetime.datetime.now()
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return (target - now).total_seconds()

    def _get_cpu_percent():
        try:
            with open("/proc/stat") as f:
                parts = f.readline().split()
            idle1 = int(parts[4])
            total1 = sum(int(x) for x in parts[1:])
            time.sleep(1)
            with open("/proc/stat") as f:
                parts = f.readline().split()
            idle2 = int(parts[4])
            total2 = sum(int(x) for x in parts[1:])
            idle_d = idle2 - idle1
            total_d = total2 - total1
            if total_d == 0:
                return 0
            return (1 - idle_d / total_d) * 100
        except Exception:
            return 0

    def _server_busy():
        if _get_cpu_percent() > 70:
            return True
        try:
            pool = engine.pool
            checkedout = pool.checkedout()
            size = pool.size()
            if size > 0 and checkedout / size > 0.8:
                return True
        except Exception:
            pass
        return False

    time.sleep(min(_next_3am(), 300))
    while True:
        try:
            if _server_busy():
                logger.info("Auto-delete: server busy, skipping")
                time.sleep(1800)
                continue

            with get_session() as s:
                now = datetime.datetime.now(datetime.timezone.utc)
                users_with_lifetime = s.query(User).filter(
                    User.post_lifetime > 0,
                    User.is_remote == False,
                ).all()
                deleted = 0
                _autodel_notif_users = set()
                for u in users_with_lifetime:
                    exc = u.post_lifetime_exceptions or []
                    cutoff = now - datetime.timedelta(days=u.post_lifetime)
                    expired = s.query(Post).filter(
                        Post.author_id == u.id,
                        Post.is_deleted == False,
                        Post.created_at <= cutoff,
                    ).all()
                    for post in expired:
                        if _server_busy():
                            logger.info("Auto-delete: server busy mid-run, stopping at %d", deleted)
                            break
                        try:
                            if "pinned" in exc and post.is_pinned:
                                continue
                            if "dm" in exc and post.is_dm:
                                continue
                            if "liked" in exc:
                                if s.query(Like).filter_by(user_id=u.id, post_id=post.id).first():
                                    continue
                            if "bookmarked" in exc:
                                if s.query(Bookmark).filter_by(user_id=u.id, post_id=post.id).first():
                                    continue
                            if "poll" in exc and post.poll_data:
                                continue
                            if "media" in exc and post.media_attachments:
                                continue
                            for _n in s.query(Notification.user_id).filter(Notification.post_id == post.id).distinct().all():
                                _autodel_notif_users.add(_n[0])
                            s.query(Notification).filter(Notification.post_id == post.id).delete()
                            s.query(Like).filter(Like.post_id == post.id).delete()
                            s.query(Boost).filter(Boost.post_id == post.id).delete()
                            s.query(Bookmark).filter(Bookmark.post_id == post.id).delete()
                            s.query(Vote).filter(Vote.post_id == post.id).delete()

                            media = list(post.media_attachments or [])
                            if media:
                                try:
                                    storage = get_storage()
                                    for m in media:
                                        if isinstance(m, dict) and m.get("url"):
                                            try:
                                                storage.delete(m["url"])
                                            except Exception:
                                                pass
                                except Exception:
                                    pass

                            ap_id = post.ap_id or ""
                            if ap_id and ap_id.startswith("http"):
                                try:
                                    _send_delete_post(post, u)
                                except Exception:
                                    pass

                            s.delete(post)
                            s.flush()

                            try:
                                broadcast_delete(post.id)
                            except Exception:
                                pass
                            deleted += 1
                        except Exception:
                            pass
                    if _server_busy():
                        break
                if deleted:
                    s.commit()
                    logger.info("Auto-deleted %d expired posts", deleted)
                    try:
                        for _uid in _autodel_notif_users:
                            broadcast_refresh_notifs(_uid)
                    except Exception:
                        pass
        except Exception as e:
            logger.error("Auto-delete worker error: %s", e, exc_info=True)
        time.sleep(_next_3am() + 60)
