"""Admin API endpoints, split by domain under this package.

Routes stay under the /admin/* prefix and are aggregated into `admin_router`.
"""
from fastapi import APIRouter

from app.routes.api._admin.users import router as _users_router
from app.routes.api._admin.content import router as _content_router
from app.routes.api._admin.reports import router as _reports_router
from app.routes.api._admin.rules import router as _rules_router
from app.routes.api._admin.announcements import router as _announcements_router
from app.routes.api._admin.federation import router as _federation_router
from app.routes.api._admin.settings import router as _settings_router

admin_router = APIRouter()
admin_router.include_router(_users_router)
admin_router.include_router(_content_router)
admin_router.include_router(_reports_router)
admin_router.include_router(_rules_router)
admin_router.include_router(_announcements_router)
admin_router.include_router(_federation_router)
admin_router.include_router(_settings_router)

__all__ = ["admin_router"]
