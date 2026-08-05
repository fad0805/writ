"""Mastodon-compatible API endpoints (/api/v1/*).

Enables third-party Mastodon clients (Tusky, Metatext, etc.) to interact with WRIT.
"""
from fastapi import APIRouter

from app.routes.mastodon_api._common import MastodonAPIError
from app.routes.mastodon_api.apps import router as apps_router
from app.routes.mastodon_api.oauth import router as oauth_router
from app.routes.mastodon_api.accounts import router as accounts_router
from app.routes.mastodon_api.timelines import router as timelines_router
from app.routes.mastodon_api.statuses import router as statuses_router
from app.routes.mastodon_api.notifications import router as notifications_router
from app.routes.mastodon_api.search import router as search_router
from app.routes.mastodon_api.instance import router as instance_router
from app.routes.mastodon_api.misc import router as misc_router

router = APIRouter()
router.include_router(apps_router)
router.include_router(accounts_router)
router.include_router(timelines_router)
router.include_router(statuses_router)
router.include_router(notifications_router)
router.include_router(search_router)
router.include_router(instance_router)
router.include_router(misc_router)

# NOTE: oauth_router is intentionally NOT merged into `router` (which is mounted
# with prefix="/api"): standard Mastodon OAuth paths (/oauth/authorize,
# /oauth/token) must stay at the root for client compatibility.
__all__ = ["router", "oauth_router", "MastodonAPIError"]
