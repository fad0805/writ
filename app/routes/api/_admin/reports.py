"Moderation report admin endpoints."

import logging

from fastapi import APIRouter, HTTPException, Request

from app.core.activitypub import _send_flag
from app.core.permissions import require_permission
from app.db.database import get_session
from app.models import Episode, Novel, Post, Report, ServerRule, User
from app.utils.datetime import _fmt_dt
from app.utils.log import log_admin_action

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/admin/reports")
def api_admin_list_reports(request: Request, status: str = "pending", target_type: str = "", offset: int = 0, limit: int = 50):
    user = require_permission(request, "reports.manage")
    with get_session() as s:
        q = s.query(Report)
        if status in ("pending", "resolved", "dismissed"):
            q = q.filter(Report.status == status)
        if target_type in ("post", "novel", "episode"):
            q = q.filter(Report.target_type == target_type)
        total = q.count()
        reports = q.order_by(Report.created_at.desc()).offset(offset).limit(limit).all()
        results = []
        for r in reports:
            item = {
                "id": r.id,
                "reporter": {"id": r.reporter.id, "username": r.reporter.username, "display_name": r.reporter.display_name},
                "target_type": r.target_type,
                "target_id": r.target_id,
                "reason": r.reason,
                "rule_ids": r.rule_ids if r.rule_ids else [],
                "status": r.status,
                "created_at": _fmt_dt(r.created_at),
            }
            if r.rule_ids:
                rules = s.query(ServerRule).filter(ServerRule.id.in_(r.rule_ids)).all()
                item["rules"] = [{"id": rule.id, "title": rule.title} for rule in rules]
            if r.target_type == "post":
                post = s.query(Post).filter_by(id=r.target_id).first()
                if post:
                    item["target"] = {
                        "id": post.id,
                        "content": post.content[:200] if post.content else "",
                        "author": {"id": post.author.id, "username": post.author.username, "display_name": post.author.display_name},
                        "is_deleted": post.is_deleted,
                    }
            elif r.target_type == "novel":
                novel = s.query(Novel).filter_by(id=r.target_id).first()
                if novel:
                    item["target"] = {
                        "id": novel.id,
                        "title": novel.title,
                        "author": {"id": novel.author.id, "username": novel.author.username, "display_name": novel.author.display_name},
                    }
            elif r.target_type == "episode":
                ep = s.query(Episode).filter_by(id=r.target_id).first()
                if ep:
                    item["target"] = {
                        "id": ep.id,
                        "title": ep.title,
                        "novel_id": ep.novel_id,
                        "novel_title": ep.novel.title if ep.novel else "",
                        "author": {"id": ep.novel.author.id, "username": ep.novel.author.username, "display_name": ep.novel.author.display_name} if ep.novel else None,
                    }
            if r.resolved_by_id:
                resolver = s.query(User).filter_by(id=r.resolved_by_id).first()
                if resolver:
                    item["resolved_by"] = {"id": resolver.id, "username": resolver.username}
            results.append(item)
        return {"reports": results, "total": total}


@router.get("/admin/reports/{report_id}")
def api_admin_get_report(request: Request, report_id: int):
    user = require_permission(request, "reports.manage")
    with get_session() as s:
        r = s.query(Report).get(report_id)
        if not r:
            raise HTTPException(status_code=404, detail="Report not found")
        item = {
            "id": r.id,
            "reporter": {"id": r.reporter.id, "username": r.reporter.username, "display_name": r.reporter.display_name},
            "target_type": r.target_type,
            "target_id": r.target_id,
            "reason": r.reason,
            "rule_ids": r.rule_ids if r.rule_ids else [],
            "status": r.status,
            "created_at": _fmt_dt(r.created_at),
        }
        if r.rule_ids:
            rules = s.query(ServerRule).filter(ServerRule.id.in_(r.rule_ids)).all()
            item["rules"] = [{"id": rule.id, "title": rule.title, "description": rule.description} for rule in rules]
        if r.target_type == "post":
            post = s.query(Post).filter_by(id=r.target_id).first()
            if post:
                item["target"] = {
                    "id": post.id,
                    "content": post.content,
                    "summary": post.summary or "",
                    "author": {"id": post.author.id, "username": post.author.username, "display_name": post.author.display_name, "is_remote": post.author.is_remote},
                    "is_deleted": post.is_deleted,
                    "author_id": post.author_id,
                }
        elif r.target_type == "novel":
            novel = s.query(Novel).filter_by(id=r.target_id).first()
            if novel:
                item["target"] = {
                    "id": novel.id,
                    "title": novel.title,
                    "description": novel.description,
                    "author": {"id": novel.author.id, "username": novel.author.username, "display_name": novel.author.display_name, "is_remote": novel.author.is_remote},
                    "author_id": novel.author_id,
                }
        elif r.target_type == "episode":
            ep = s.query(Episode).filter_by(id=r.target_id).first()
            if ep and ep.novel:
                item["target"] = {
                    "id": ep.id,
                    "title": ep.title,
                    "content": ep.content[:500],
                    "novel_id": ep.novel_id,
                    "novel_title": ep.novel.title,
                    "author": {"id": ep.novel.author.id, "username": ep.novel.author.username, "display_name": ep.novel.author.display_name, "is_remote": ep.novel.author.is_remote},
                    "author_id": ep.novel.author_id,
                }
        if r.resolved_by_id:
            resolver = s.query(User).filter_by(id=r.resolved_by_id).first()
            if resolver:
                item["resolved_by"] = {"id": resolver.id, "username": resolver.username}
        return item


@router.post("/admin/reports/{report_id}/resolve")
def api_admin_resolve_report(request: Request, report_id: int):
    user = require_permission(request, "reports.manage")
    with get_session() as s:
        report = s.query(Report).get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        report.status = "resolved"
        report.resolved_by_id = user.id
        s.commit()
        r_type, r_id = report.target_type, report.target_id
    log_admin_action(user.id, user.username, "resolve_report", target_type="report", target_id=report_id, details=f"target:{r_type}:{r_id}", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/reports/{report_id}/dismiss")
def api_admin_dismiss_report(request: Request, report_id: int):
    user = require_permission(request, "reports.manage")
    with get_session() as s:
        report = s.query(Report).get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        report.status = "dismissed"
        report.resolved_by_id = user.id
        s.commit()
        r_type, r_id = report.target_type, report.target_id
    log_admin_action(user.id, user.username, "dismiss_report", target_type="report", target_id=report_id, details=f"target:{r_type}:{r_id}", ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/reports/{report_id}/forward")
def api_admin_forward_report(request: Request, report_id: int):
    user = require_permission(request, "reports.manage")
    with get_session() as s:
        report = s.query(Report).get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        target_obj = None
        if report.target_type == "post":
            target_obj = s.query(Post).get(report.target_id)
        if not target_obj or not hasattr(target_obj, 'author') or not target_obj.author or not target_obj.author.is_remote:
            raise HTTPException(status_code=400, detail="Target not remote")
        reporter = s.query(User).get(report.reporter_id)
        if not reporter:
            raise HTTPException(status_code=400, detail="Reporter not found")
        try:
            _send_flag(reporter, report.target_type, target_obj, report.reason[:200], report.rule_ids or [])
        except Exception as e:
            logger.error("Failed to forward report %s: %s", report_id, e)
            raise HTTPException(status_code=500, detail="Failed to forward report") from e
    return {"ok": True}
