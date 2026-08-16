"""Role & permission system.

Roles are fixed (owner/admin/moderator/user) but each role's permission set is
configurable. `owner` always bypasses all checks. Permission sets are stored in
the `roles` table and fall back to the built-in defaults (ROLE_DEFAULTS) when no
row exists yet (e.g. fresh test DBs). A short TTL cache avoids a DB query on
every admin request; it is invalidated whenever permissions are updated.
"""

import time

from fastapi import HTTPException, Request

from app.core.auth import require_auth
from app.db.database import get_session
from app.models import Role

# permission key -> {label, tier}
# tier "admin": 관리 (기존 admin/owner 전용)
# tier "moderation": 중재 (기존 admin/moderator/owner 전용)
PERMISSION_CATALOG: dict[str, dict] = {
    # 관리
    "users.admin": {"label": "사용자 역할 변경 · 계정 삭제", "tier": "admin"},
    "settings.manage": {"label": "서버 정보 관리", "tier": "admin"},
    "federation.mode": {"label": "연합 모드 · 서버 차단/제거", "tier": "admin"},
    "roles.manage": {"label": "역할/권한 관리", "tier": "admin"},
    # 중재
    "users.manage": {"label": "사용자 중재 (정지 · 동결 · 비밀번호 초기화 등)", "tier": "moderation"},
    "content.manage": {"label": "콘텐츠 관리", "tier": "moderation"},
    "reports.manage": {"label": "신고 관리", "tier": "moderation"},
    "rules.manage": {"label": "서버 규칙", "tier": "moderation"},
    "announcements.manage": {"label": "공지사항", "tier": "moderation"},
    "emojis.manage": {"label": "커스텀 이모지", "tier": "moderation"},
    "domains.manage": {"label": "도메인 차단", "tier": "moderation"},
    "federation.manage": {"label": "연합 관리", "tier": "moderation"},
    "log.view": {"label": "중재 기록 조회", "tier": "moderation"},
}

ROLE_LABELS: dict[str, str] = {
    "owner": "서버 소유자",
    "admin": "관리자",
    "moderator": "중재자",
    "user": "일반 사용자",
}

_ALL_PERMS = list(PERMISSION_CATALOG.keys())

ROLE_DEFAULTS: dict[str, list[str]] = {
    "owner": list(_ALL_PERMS),
    "admin": list(_ALL_PERMS),
    "moderator": [
        "users.manage", "content.manage", "reports.manage", "rules.manage",
        "announcements.manage", "emojis.manage", "domains.manage",
        "federation.manage", "log.view",
    ],
    "user": [],
}

_ROLE_PERM_CACHE: dict[str, list[str]] = {}
_ROLE_PERM_CACHE_TIME: dict[str, float] = {}
_ROLE_PERM_CACHE_TTL = 60.0


def ensure_default_roles() -> None:
    """Seed the roles table with default permission sets (idempotent)."""
    with get_session() as s:
        for name, perms in ROLE_DEFAULTS.items():
            r = s.query(Role).filter_by(name=name).first()
            if r is None:
                s.add(Role(name=name, label=ROLE_LABELS.get(name, name), permissions=perms))
        s.commit()


def invalidate_role_perms(role_name: str) -> None:
    _ROLE_PERM_CACHE.pop(role_name, None)
    _ROLE_PERM_CACHE_TIME.pop(role_name, None)


def get_role_permissions(role_name: str) -> set:
    now = time.time()
    cached = _ROLE_PERM_CACHE.get(role_name)
    if cached is not None and now - _ROLE_PERM_CACHE_TIME.get(role_name, 0) < _ROLE_PERM_CACHE_TTL:
        return set(cached)
    with get_session() as s:
        r = s.query(Role).filter_by(name=role_name).first()
    if r is not None and r.permissions is not None:
        perms = list(r.permissions)
    else:
        perms = list(ROLE_DEFAULTS.get(role_name, []))
    _ROLE_PERM_CACHE[role_name] = perms
    _ROLE_PERM_CACHE_TIME[role_name] = now
    return set(perms)


def has_permission(user, permission: str) -> bool:
    if getattr(user, "role", "user") == "owner":
        return True
    return permission in get_role_permissions(user.role or "user")


def is_staff(user) -> bool:
    """True if the user has any staff permission (or is the owner)."""
    if getattr(user, "role", "user") == "owner":
        return True
    return bool(get_role_permissions(user.role or "user"))


def require_permission(request: Request, permission: str):
    user = require_auth(request)
    if not has_permission(user, permission):
        raise HTTPException(status_code=403, detail="Forbidden")
    return user
