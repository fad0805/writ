"""Role & permission management admin endpoints.

Lists the permission catalog and each role's permission set, and updates a
role's permissions. Only users with the `roles.manage` permission can access
(owner always bypasses); the `owner` role itself cannot be edited. Custom roles
can be created and deleted (as long as no user holds them).
"""

import re

from fastapi import APIRouter, HTTPException, Request

from app.core.permissions import (
    PERMISSION_CATALOG,
    ROLE_DEFAULTS,
    ROLE_LABELS,
    ensure_default_roles,
    invalidate_role_perms,
    require_permission,
)
from app.db.database import get_session
from app.models import Role, User
from app.utils.log import log_admin_action

router = APIRouter()

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,14}$")
_BUILTIN_ROLES = frozenset(ROLE_DEFAULTS.keys())


def _role_json(r: Role):
    return {
        "name": r.name,
        "label": r.label or ROLE_LABELS.get(r.name, r.name),
        "permissions": sorted(set(r.permissions or [])),
    }


def _validate_permissions(perms) -> list[str]:
    if not isinstance(perms, list) or not all(isinstance(p, str) for p in perms):
        raise HTTPException(status_code=400, detail="Invalid permissions")
    valid = set(PERMISSION_CATALOG.keys())
    unknown = [p for p in perms if p not in valid]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown permissions: {', '.join(unknown)}")
    return sorted(set(perms))


@router.get("/admin/roles")
def api_admin_list_roles(request: Request):
    user = require_permission(request, "roles.manage")
    ensure_default_roles()
    with get_session() as s:
        roles = s.query(Role).order_by(Role.id).all()
    return {
        "catalog": {k: {"label": v["label"], "tier": v["tier"]} for k, v in PERMISSION_CATALOG.items()},
        "roles": [_role_json(r) for r in roles],
    }


@router.post("/admin/roles")
async def api_admin_create_role(request: Request):
    user = require_permission(request, "roles.manage")
    ensure_default_roles()
    payload = await request.json()
    name = (payload.get("name") or "").strip().lower()
    label = (payload.get("label") or "").strip()
    perms = _validate_permissions(payload.get("permissions") or [])
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="역할 이름은 영문 소문자/숫자/밑줄로 2~15자여야 합니다.")
    if name in _BUILTIN_ROLES:
        raise HTTPException(status_code=400, detail="이미 존재하는 역할입니다.")
    if not label:
        raise HTTPException(status_code=400, detail="표시 이름은 필수입니다.")
    if len(label) > 30:
        raise HTTPException(status_code=400, detail="표시 이름은 30자 이하여야 합니다.")
    with get_session() as s:
        if s.query(Role).filter_by(name=name).first():
            raise HTTPException(status_code=400, detail="이미 존재하는 역할입니다.")
        r = Role(name=name, label=label, permissions=perms)
        s.add(r)
        s.commit()
    log_admin_action(user.id, user.username, "create_role", target_type="role", target_username=name, details=label, ip_address=request.client.host if request.client else "")
    return {"ok": True, "role": _role_json(r)}


@router.delete("/admin/roles/{role_name}")
def api_admin_delete_role(role_name: str, request: Request):
    user = require_permission(request, "roles.manage")
    if role_name in _BUILTIN_ROLES:
        raise HTTPException(status_code=400, detail="기본 역할은 삭제할 수 없습니다.")
    with get_session() as s:
        r = s.query(Role).filter_by(name=role_name).first()
        if not r:
            raise HTTPException(status_code=404, detail="Role not found")
        in_use = s.query(User).filter(User.role == role_name).count()
        if in_use:
            raise HTTPException(status_code=400, detail=f"해당 역할을 가진 사용자가 {in_use}명 있어 삭제할 수 없습니다.")
        s.delete(r)
        s.commit()
    invalidate_role_perms(role_name)
    log_admin_action(user.id, user.username, "delete_role", target_type="role", target_username=role_name, ip_address=request.client.host if request.client else "")
    return {"ok": True}


@router.post("/admin/roles/{role_name}")
async def api_admin_update_role(role_name: str, request: Request):
    user = require_permission(request, "roles.manage")
    ensure_default_roles()
    if role_name in _BUILTIN_ROLES and role_name == "owner":
        raise HTTPException(status_code=400, detail="owner 역할의 권한은 변경할 수 없습니다.")
    payload = await request.json()
    perms = _validate_permissions(payload.get("permissions") or [])
    with get_session() as s:
        r = s.query(Role).filter_by(name=role_name).first()
        if not r:
            raise HTTPException(status_code=404, detail="Role not found")
        r.permissions = perms
        s.commit()
    invalidate_role_perms(role_name)
    log_admin_action(user.id, user.username, "update_role_permissions", target_type="role", target_username=role_name, details=",".join(perms), ip_address=request.client.host if request.client else "")
    return {"ok": True, "role": role_name, "permissions": perms}


__all__ = ["router"]
