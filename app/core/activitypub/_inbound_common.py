import html
import json
import logging
import re

from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_notif_sound
from app.models import Notification, User
from app.utils.emoji import _load_emojis
from app.utils.reactions import build_reactions_map

logger = logging.getLogger("writ.activitypub")


def _broadcast_emoji_list(session):
    """Return ALL emojis from DB formatted for SSE broadcast payload."""
    return [{"keyword": e["keyword"], "file_name": e["file_name"], "url": e["url"], "aliases": e["aliases"]} for e in _load_emojis(session)]


def _build_reactions(session, post_id: int) -> dict:
    """Build reactions dict from Like table, separated by emoji domain."""
    return build_reactions_map(session, [post_id]).get(post_id, {})


def _sanitize_reaction(reaction: str) -> str:
    """원격 reaction 문자열을 안전한 형태로 정규화한다.

    일부 서버는 리액션을 HTML 조각(예: <img src=...>, <p>❤️</p>)으로 보내므로,
    HTML 태그/엔티티를 제거하고 이모지 유니코드나 :shortcode: 형태만 남긴다.
    """
    if not reaction:
        return reaction
    r = html.unescape(reaction)
    r = re.sub(r"<[^>]*>", "", r).strip()
    if not r:
        return "★"
    if re.fullmatch(r":[^<>&\"'\s]+:", r) and len(r) <= 50:
        return r
    if len(r) <= 32 and not re.search(r"[<>&\"']", r):
        return r
    return "★"


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
