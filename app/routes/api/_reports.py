"""Report and server-rules endpoints extracted from _posts.py."""
import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Form, HTTPException, Request

from app.core.activitypub import _send_flag
from app.core.auth import require_active_auth
from app.core.push import send_push_to_user
from app.core.timeline_stream import broadcast_notif_sound, broadcast_refresh_notifs
from app.db.database import get_session
from app.models import Episode, Notification, Novel, Post, Report, ServerRule, User

logger = logging.getLogger("writ.api.reports")

reports_router = APIRouter()


@reports_router.post("/reports")
def api_create_report(request: Request, target_type: str = Form(...), target_id: int = Form(...), reason: str = Form(...), forward_to_remote: bool = Form(False), rule_ids: str = Form("")):
    user = require_active_auth(request)
    target_type = target_type.strip().lower()
    if target_type not in ("post", "novel", "episode"):
        raise HTTPException(status_code=400, detail="Invalid target_type")
    if forward_to_remote:
        _cutoff = datetime.now(UTC) - timedelta(minutes=1)
        with get_session() as _s:
            _recent = _s.query(Report).filter(
                Report.reporter_id == user.id,
                Report.forward_to_remote == True,
                Report.created_at >= _cutoff,
            ).count()
            if _recent >= 3:
                raise HTTPException(status_code=429, detail="원격 신고는 1분에 3회까지 가능합니다")
    parsed_rule_ids = []
    if rule_ids and rule_ids.strip():
        try:
            parsed = json.loads(rule_ids)
            if isinstance(parsed, list):
                parsed_rule_ids = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    if (not reason or len(reason.strip()) < 10) and not parsed_rule_ids:
        raise HTTPException(status_code=400, detail="Reason must be at least 10 characters")
    with get_session() as s:
        existing = s.query(Report).filter_by(
            reporter_id=user.id, target_type=target_type, target_id=target_id, status="pending"
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Already reported")
        report = Report(reporter_id=user.id, target_type=target_type, target_id=target_id, reason=reason.strip(), forward_to_remote=forward_to_remote, rule_ids=parsed_rule_ids)
        s.add(report)
        s.flush()
        report_id = report.id
        admins = s.query(User).filter(User.role.in_(["admin", "moderator", "owner"])).all()
        target_label = ""
        target_author_name = ""
        target_obj = None
        if target_type == "post":
            target_obj = s.query(Post).filter_by(id=target_id).first()
            if target_obj:
                target_label = (target_obj.content or "")[:120]
                target_author_name = target_obj.author.username
        elif target_type == "novel":
            target_obj = s.query(Novel).filter_by(id=target_id).first()
            if target_obj:
                target_label = target_obj.title[:120]
                target_author_name = target_obj.author.username
        elif target_type == "episode":
            target_obj = s.query(Episode).filter_by(id=target_id).first()
            if target_obj:
                target_label = target_obj.title[:120]
                target_author_name = target_obj.novel.author.username if target_obj.novel else ""
        meta = {
            "type": "report",
            "report_id": report_id,
            "target_type": target_type,
            "target_id": target_id,
            "target_label": target_label,
            "target_author": target_author_name,
            "reason": reason.strip()[:200],
        }
        for admin in admins:
            if admin.id == user.id:
                continue
            s.add(Notification(
                user_id=admin.id, from_user_id=user.id,
                notification_type="moderation",
                metadata_json=json.dumps(meta),
            ))
        s.commit()
        for admin in admins:
            broadcast_refresh_notifs(admin.id)
        for admin in admins:
            if admin.id != user.id:
                send_push_to_user(admin.id, "moderation", user.username)
                broadcast_notif_sound(admin.id)

        if forward_to_remote and target_obj and hasattr(target_obj, 'author') and target_obj.author and target_obj.author.is_remote:
            try:
                _send_flag(user, target_type, target_obj, reason.strip()[:200], parsed_rule_ids)
            except Exception as e:
                logger.error("Failed to send Flag activity: %s", e, exc_info=True)
    return {"ok": True, "report_id": report_id}


@reports_router.get("/rules")
def api_list_rules():
    with get_session() as s:
        rules = s.query(ServerRule).order_by(ServerRule.sort_order).all()
        return [{"id": r.id, "title": r.title, "description": r.description, "sort_order": r.sort_order} for r in rules]
