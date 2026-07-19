import json
import logging
import threading

from app.config import VAPID_CLAIM_EMAIL, get_vapid_keys

logger = logging.getLogger("writ.push")

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
    from app.config import _sanitize_pem
    # 1. Try DB first (authoritative source)
    try:
        from app.models import ServerSetting, get_session
        with get_session() as s:
            ss = ServerSetting.get(s)
            db_priv = _sanitize_pem(getattr(ss, 'vapid_private_key', '') or '')
            db_pub = _sanitize_pem(getattr(ss, 'vapid_public_key', '') or '')
            if db_priv and db_pub:
                return {"privateKey": db_priv, "publicKey": db_pub}
    except Exception:
        pass

    # 2. Try env vars
    priv, pub = get_vapid_keys()
    if priv and pub:
        return {"privateKey": priv, "publicKey": pub}

    # 3. Auto-generate and persist to DB
    try:
        import base64
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        from app.models import ServerSetting, get_session

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
        import os
        os.environ["VAPID_PRIVATE_KEY"] = _priv_pem
        os.environ["VAPID_PUBLIC_KEY"] = _pub_b64

        logger.info("Auto-generated new VAPID keys and saved to DB")
        return {"privateKey": _priv_pem, "publicKey": _pub_b64}
    except Exception as e:
        logger.warning("Failed to auto-generate VAPID keys: %s", e)

    return None


def send_push_to_user(user_id: int, notification_type: str, from_username: str = "", post_id: int = None, metadata: dict = None):
    """Send web push notification to all subscriptions of a user. Runs in background thread."""
    t = threading.Thread(target=_send_push_sync, args=(user_id, notification_type, from_username, post_id, metadata), daemon=True)
    t.start()


def _send_push_sync(user_id: int, notification_type: str, from_username: str, post_id: int, metadata: dict):
    try:
        from app.models import PushSubscription, get_session

        vapid_key = _get_vapid_key()
        if not vapid_key:
            return

        with get_session() as s:
            subs = s.query(PushSubscription).filter_by(user_id=user_id).all()
            if not subs:
                return

            title, body = NOTIF_LABELS.get(notification_type, ("알림", "새 알림이 있습니다"))
            if from_username:
                body = f"@{from_username} — {body}"
            if post_id and notification_type in ("reply", "mention"):
                try:
                    from app.models import Post as _Po
                    _p = s.query(_Po).get(post_id)
                    if _p and _p.content:
                        _preview = _p.content.replace("<br>", " ").replace("\n", " ").strip()[:80]
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

            from pywebpush import webpush, WebPushException
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            # Pre-load VAPID key once
            _vapid_obj = None
            try:
                _priv_pem = vapid_key["privateKey"]
                if isinstance(_priv_pem, str):
                    _priv_pem = _priv_pem.encode()
                _ec_key = load_pem_private_key(_priv_pem, password=None)
                from py_vapid import Vapid as _Vapid
                _vapid_obj = _Vapid()
                _vapid_obj.private_key = _ec_key
                print(f"[PUSH] VAPID key loaded OK type={type(_ec_key).__name__}", flush=True)
            except Exception as _kerr:
                print(f"[PUSH] VAPID key load FAILED: {_kerr}", flush=True)

            for sub in subs:
                try:
                    print(f"[PUSH] sending to sub {sub.id}", flush=True)
                    webpush(
                        subscription_info={
                            "endpoint": sub.endpoint,
                            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                        },
                        data=payload,
                        vapid_private_key=_vapid_obj or vapid_key["privateKey"],
                        vapid_claims={"sub": f"mailto:{VAPID_CLAIM_EMAIL}"},
                    )
                    print(f"[PUSH] OK sub {sub.id}", flush=True)
                except (ValueError, TypeError) as _ke:
                    print(f"[PUSH] key error sub {sub.id}: {_ke}", flush=True)
                    logger.warning("Push key error for sub %s: %s (key may have changed after restart)", sub.id, _ke)
                except WebPushException as ex:
                    status_code = getattr(ex, "response", None)
                    if status_code is not None and hasattr(status_code, "status_code"):
                        status_code = status_code.status_code
                    print(f"[PUSH] WebPushException sub {sub.id} status={status_code}: {ex}", flush=True)
                    if status_code in (404, 410):
                        logger.info("Removing expired push subscription %s for user %s", sub.id, user_id)
                        s.delete(sub)
                    else:
                        logger.warning("Push send failed for sub %s: %s", sub.id, ex)
                except Exception as ex:
                    print(f"[PUSH] error sub {sub.id}: {ex}", flush=True)
                    logger.warning("Push send error for sub %s: %s", sub.id, ex)

            s.commit()
    except Exception as ex:
        logger.warning("send_push_to_user error: %s", ex)
