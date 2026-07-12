import json
import logging
import threading

from pywebpush import webpush, WebPushException
from app.config import VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_CLAIM_EMAIL

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
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return None
    return {
        "privateKey": VAPID_PRIVATE_KEY,
        "publicKey": VAPID_PUBLIC_KEY,
    }


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

            url = "/notifications"
            if notification_type in ("reply", "mention") and post_id:
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

            for sub in subs:
                try:
                    webpush(
                        subscription_info={
                            "endpoint": sub.endpoint,
                            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                        },
                        data=payload,
                        vapid_private_key=vapid_key["privateKey"],
                        vapid_claims={"sub": f"mailto:{VAPID_CLAIM_EMAIL}"},
                    )
                except WebPushException as ex:
                    status_code = getattr(ex, "response", None)
                    if status_code is not None and hasattr(status_code, "status_code"):
                        status_code = status_code.status_code
                    if status_code in (404, 410):
                        logger.info("Removing expired push subscription %s for user %s", sub.id, user_id)
                        s.delete(sub)
                    else:
                        logger.warning("Push send failed for sub %s: %s", sub.id, ex)
                except Exception as ex:
                    logger.warning("Push send error for sub %s: %s", sub.id, ex)

            s.commit()
    except Exception as ex:
        logger.warning("send_push_to_user error: %s", ex)
