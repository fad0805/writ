"Server rules admin endpoints."

import json

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy import func

from app.core.auth import require_auth
from app.db.database import get_session
from app.models import ServerRule

router = APIRouter()


@router.get("/admin/rules")
def api_admin_list_rules(request: Request):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        rules = s.query(ServerRule).order_by(ServerRule.sort_order).all()
        return [{"id": r.id, "title": r.title, "description": r.description, "sort_order": r.sort_order} for r in rules]


@router.post("/admin/rules/new")
def api_admin_create_rule(request: Request, title: str = Form(...), description: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        max_order = s.query(func.max(ServerRule.sort_order)).scalar() or 0
        rule = ServerRule(title=title, description=description, sort_order=max_order + 1)
        s.add(rule)
        s.commit()
        return {"id": rule.id, "title": rule.title, "description": rule.description, "sort_order": rule.sort_order}


@router.post("/admin/rules/{rule_id}/edit")
def api_admin_edit_rule(request: Request, rule_id: int, title: str = Form(...), description: str = Form("")):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        rule = s.query(ServerRule).get(rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")
        rule.title = title
        rule.description = description
        s.commit()
        return {"id": rule.id, "title": rule.title, "description": rule.description, "sort_order": rule.sort_order}


@router.post("/admin/rules/{rule_id}/delete")
def api_admin_delete_rule(request: Request, rule_id: int):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_session() as s:
        rule = s.query(ServerRule).get(rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")
        s.delete(rule)
        s.commit()
    return {"ok": True}


@router.post("/admin/rules/reorder")
def api_admin_reorder_rules(request: Request, rule_ids: str = Form(...)):
    user = require_auth(request)
    if user.role not in ("admin", "moderator", "owner"):
        raise HTTPException(status_code=403, detail="Forbidden")
    ids = []
    try:
        ids = json.loads(rule_ids)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid rule_ids") from exc
    with get_session() as s:
        for i, rid in enumerate(ids):
            s.query(ServerRule).filter_by(id=rid).update({"sort_order": i})
        s.commit()
    return {"ok": True}
