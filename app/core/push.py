import os
import json
import logging
import re

import base64
from concurrent.futures import ThreadPoolExecutor
from py_vapid import Vapid
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pywebpush import webpush, WebPushException

from app.config.settings import DOMAIN
from app.models import ServerSetting, PushSubscription, Post
from app.db.database import get_session

logger = logging.getLogger("writ.push")

# 푸시 발송 전용 바운드 실행기 — 수신자 수만큼 무제한 스레드를 만들지 않는다.
# 발송은 외부 VAPID 엔드포인트 I/O라 느릴 수 있으므로 워커 수를 제한해 폭주를 막는다.
_push_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="push")

# Web Push / VAPID
def _sanitize_pem(val: str) -> str:
    if not val:
        return val
    val = val.strip()
    val = val.replace("\\n", "\n").replace("\\r", "")
    return val

VAPID_PRIVATE_KEY = _sanitize_pem(os.environ.get("VAPID_PRIVATE_KEY", ""))
VAPID_PUBLIC_KEY = _sanitize_pem(os.environ.get("VAPID_PUBLIC_KEY", ""))
VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL", f"admin@{DOMAIN}")
NOTIF_LABELS = {
    "follow": ("새 팔로워", "회원님을 팔로우하기 시작했습니다"),
    "follow_request": ("팔로우 요청", "회원님에게 팔로우를 요청했습니다"),
    "like": ("좋아요", "회원님의 포스트에 좋아요를 남겼습니다"),
    "boost": ("부스트", "회원님의 포스트를 부스트했습니다"),
    "reply": ("답글", "회원님의 포스트에 답글을 남겼습니다"),
    "mention": ("멘션", "회원님을 멘션했습니다"),
    "post": ("새 포스트", "팔로우하는 사용자가 새 포스트를 작성했습니다"),
    "new_episode": ("새 에피소드", "팔로우하는 시리즈에 새 에피소드가 등록되었습니다"),
    "moderation": ("알림", "관리자에게서 알림이 있습니다"),
    "poll_ended": ("투표 종료", "참여한 �표가 종료되었습니다"),
    "vote": ("투표", "회원님의 투표에 참여했습니다"),
}


def _get_vapid_key():
    # 1. Try DB first (authoritative source)
    try:
        with get_session() as s:
            ss = ServerSetting.get(s)
            db_priv = _sanitize_pem(getattr(ss, 'vapid_private_key', '') or '')
            db_pub = _sanitize_pem(getattr(ss, 'vapid_public_key', '') or '')
            if db_priv and db_pub and _is_valid_pem_private_key(db_priv):
                return {"privateKey": db_priv, "publicKey": db_pub}
            if (db_priv or db_pub) and not _is_valid_pem_private_key(db_priv):
                logger.error(f"[PUSH] DB VAPID key invalid (len={len(db_priv)}), clearing and regenerating")
                try:
                    ss.vapid_private_key = ''
                    ss.vapid_public_key = ''
                    s.commit()
                    logger.error("[PUSH] Cleared invalid VAPID key from DB")
                except Exception as ce:
                    logger.error(f"[PUSH] Failed to clear DB key: {ce}", exc_info=True)
    except Exception:
        pass

    # 2. Try env vars
    priv, pub = get_vapid_keys()
    if priv and pub:
        return {"privateKey": priv, "publicKey": pub}

    # 3. Auto-generate and persist to DB
    try:
        _key = ec.generate_private_key(ec.SECP256R1())
        _priv_pem = _key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        _raw_pub = _key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        _pub_b64 = base64.urlsafe_b64encode(_raw_pub).rstrip(b"=").decode()

        with get_session() as s:
            ss = ServerSetting.get(s)
            ss.vapid_private_key = _priv_pem
            ss.vapid_public_key = _pub_b64
            s.commit()

        # Update env for the rest of this process
        os.environ["VAPID_PRIVATE_KEY"] = _priv_pem
        os.environ["VAPID_PUBLIC_KEY"] = _pub_b64

        logger.error("[PUSH] Auto-generated new VAPID keys and saved to DB")
        return {"privateKey": _priv_pem, "publicKey": _pub_b64}
    except Exception as e:
        logger.error(f"[PUSH] Failed to auto-generate VAPID keys: {e}", exc_info=True)

    return None


def send_push_to_user(user_id: int, notification_type: str, from_username: str = "", post_id: int = None, metadata: dict = None):
    """Send web push notification to all subscriptions of a user. Runs in background thread."""
    _push_executor.submit(_send_push_sync, user_id, notification_type, from_username, post_id, metadata)


def _send_push_sync(user_id: int, notification_type: str, from_username: str, post_id: int, metadata: dict):
    try:

        vapid_key = _get_vapid_key()
        if not vapid_key:
            return

        with get_session() as s:
            subs = s.query(PushSubscription).filter_by(user_id=user_id).all()
            if not subs:
                return

            title, body = NOTIF_LABELS.get(notification_type, ("알림", "새 알림이 있습니다"))
            if notification_type == "mention":
                if from_username:
                    body = f"@{from_username}"
                if post_id:
                    try:
                        _p = s.query(Post).get(post_id)
                        if _p:
                            _summary = (_p.summary or "").strip()
                            if _summary:
                                body += f": {_summary[:80]}"
                            elif _p.content:
                                _preview = re.sub(r'<[^>]+>', ' ', _p.content).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                                _preview = re.sub(r'\s+', ' ', _preview).strip()[:80]
                                if _preview:
                                    body += f": {_preview}"
                    except Exception:
                        pass
            else:
                if from_username:
                    body = f"@{from_username} — {body}"
                if post_id and notification_type == "reply":
                    try:
                        _p = s.query(Post).get(post_id)
                        if _p and _p.content:
                            _preview = re.sub(r'<[^>]+>', ' ', _p.content).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                            _preview = re.sub(r'\s+', ' ', _preview).strip()[:80]
                            if _preview:
                                body += f"\n{_preview}"
                    except Exception:
                        pass

            url = "/notifications"
            if notification_type in ("reply", "mention", "post") and post_id:
                url = f"/post/{post_id}"
            elif notification_type == "follow" and from_username:
                url = f"/@{from_username}"
            elif notification_type == "new_episode" and metadata:
                novel_id = metadata.get("novel_id")
                if novel_id:
                    url = f"/series/{novel_id}"

            payload = json.dumps({
                "title": f"WRIT — {title}",
                "body": body,
                "url": url,
                "icon": "/icons/icon-192.png",
            })


            raw_pem = vapid_key["privateKey"]
            if isinstance(raw_pem, str):
                raw_pem = raw_pem.strip().replace("\\n", "\n").replace("\\r", "")

            try:
                _priv_key_obj = load_pem_private_key(raw_pem.encode("utf-8"), password=None)
                _vapid_obj = Vapid()
                _vapid_obj.private_key = _priv_key_obj
            except Exception as _kerr:
                logger.error(f"[PUSH] Failed to load VAPID key object: {_kerr}", exc_info=True)
                return

            logger.error(f"[PUSH] VAPID key loaded OK type={type(_vapid_obj.private_key).__name__}")

            for sub in subs:
                try:
                    logger.error(f"[PUSH] sending to sub {sub.id}")
                    webpush(
                        subscription_info={
                            "endpoint": sub.endpoint,
                            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                        },
                        data=payload,
                        vapid_private_key=_vapid_obj,
                        vapid_claims={"sub": f"mailto:{VAPID_CLAIM_EMAIL}"},
                    )
                    logger.error(f"[PUSH] OK sub {sub.id}")
                except (ValueError, TypeError) as _ke:
                    logger.error(f"[PUSH] key error sub {sub.id}: {_ke}", exc_info=True)
                except WebPushException as ex:
                    status_code = getattr(ex, "response", None)
                    if status_code is not None and hasattr(status_code, "status_code"):
                        status_code = status_code.status_code
                    logger.error(f"[PUSH] WebPushException sub {sub.id} status={status_code}: {ex}", exc_info=True)
                    if status_code in (404, 410, 401, 403):
                        logger.error(f"[PUSH] Removing stale subscription {sub.id} (status={status_code}, VAPID key changed)", exc_info=True)
                        s.delete(sub)
                    else:
                        logger.error(f"[PUSH] WebPushException sub {sub.id} (not 404/410/401/403): {ex}", exc_info=True)
                except Exception as ex:
                    logger.error(f"[PUSH] error sub {sub.id}: {ex}", exc_info=True)

            s.commit()
    except Exception as ex:
        logger.error(f"[PUSH] send_push_to_user error: {ex}", exc_info=True)


def _is_valid_pem_private_key(pem: str) -> bool:
    """Check that a PEM string is a real private key by actually parsing it."""
    if not pem:
        return False
    if not pem.startswith("-----BEGIN ") or not pem.rstrip().endswith("-----"):
        return False
    try:
        load_pem_private_key(pem.encode("utf-8"), password=None)
        return True
    except Exception:
        return False


def get_vapid_keys():
    """VAPID 키를 즉시 조회 (lifespan에서 env 업데이트 후 재조회 가능)."""
    priv = _sanitize_pem(os.environ.get("VAPID_PRIVATE_KEY", ""))
    pub = _sanitize_pem(os.environ.get("VAPID_PUBLIC_KEY", ""))
    return priv, pub

def init_vapid_keys():
    """Initialize VAPID keys: try DB first, then auto-generate.

    Must be called after models are fully loaded (e.g. from lifespan)
    to avoid circular imports.
    """
    global VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY

    if VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY:
        return

    try:
        with get_session() as _s:
            _ss = ServerSetting.get(_s)
            _db_priv = getattr(_ss, 'vapid_private_key', '') or ''
            _db_pub = getattr(_ss, 'vapid_public_key', '') or ''
            _db_priv_san = _sanitize_pem(_db_priv)
            if _db_priv_san and _db_pub and _is_valid_pem_private_key(_db_priv_san):
                VAPID_PRIVATE_KEY = _db_priv_san
                VAPID_PUBLIC_KEY = _sanitize_pem(_db_pub)
                os.environ["VAPID_PRIVATE_KEY"] = VAPID_PRIVATE_KEY
                os.environ["VAPID_PUBLIC_KEY"] = VAPID_PUBLIC_KEY
                if VAPID_PRIVATE_KEY != _db_priv or VAPID_PUBLIC_KEY != _db_pub:
                    try:
                        _ss.vapid_private_key = VAPID_PRIVATE_KEY
                        _ss.vapid_public_key = VAPID_PUBLIC_KEY
                        _s.commit()
                    except Exception:
                        pass
                return
            elif _db_priv_san and _db_pub:
                logger.warning("VAPID DB key invalid (len=%s), regenerating...", len(_db_priv_san))
                try:
                    _ss.vapid_private_key = ''
                    _ss.vapid_public_key = ''
                    _s.commit()
                    logger.warning("VAPID cleared invalid key from DB")
                except Exception as _e:
                    logger.error("VAPID failed to clear DB key: %s", _e)
    except Exception as _e:
        logger.error("VAPID DB read error: %s", _e)

    if VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY:
        return

    try:
        _private_key = ec.generate_private_key(ec.SECP256R1())
        _public_key = _private_key.public_key()

        if not VAPID_PRIVATE_KEY:
            VAPID_PRIVATE_KEY = _private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode()

        if not VAPID_PUBLIC_KEY:
            _raw_pub = _public_key.public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
            VAPID_PUBLIC_KEY = base64.urlsafe_b64encode(_raw_pub).rstrip(b"=").decode()

        os.environ["VAPID_PRIVATE_KEY"] = VAPID_PRIVATE_KEY
        os.environ["VAPID_PUBLIC_KEY"] = VAPID_PUBLIC_KEY

        try:
            with get_session() as _s:
                _ss = ServerSetting.get(_s)
                _ss.vapid_private_key = VAPID_PRIVATE_KEY
                _ss.vapid_public_key = VAPID_PUBLIC_KEY
                _s.commit()
                logger.warning("VAPID auto-generated and saved new key (priv len=%s)", len(VAPID_PRIVATE_KEY))
                try:
                    _deleted = _s.query(PushSubscription).delete()
                    _s.commit()
                    if _deleted:
                        logger.warning("VAPID cleared %s stale push subscriptions (users must re-subscribe)", _deleted)
                except Exception as _e:
                    logger.error("VAPID failed to clear push subscriptions: %s", _e)
        except Exception as _e:
            logger.error("VAPID failed to save auto-generated key to DB: %s", _e)
    except Exception as _e:
        logger.error("VAPID auto-generate error: %s", _e)

