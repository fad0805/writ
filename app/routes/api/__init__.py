"""API package — core + posts + interactions + admin endpoints assembled into one router.

Import ``router`` from here:
    from app.routes.api import router
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api")

from app.routes.api._pwa import (
    _read_storage_file,
    _save_pwa_icons,
    _save_favicon,
    _delete_favicon,
    _delete_pwa_icons,
)

from app.routes.api._novels import (
    novels_router,
    _novel_json,
    _apply_latest_activity_order,
)

from app.routes.api._episodes import (
    episodes_router,
    _episode_json,
)

from app.routes.api._notices import notices_router

from app.routes.api._posts import (
    posts_router,
    _sync_post_tags,
    _do_edit_post,
    _do_delete_post,
)

from app.core.feed import _broadcast_federation

from app.routes.api._feed import (
    feed_router,
)

from app.core.broadcast import _broadcast_timeline

from app.routes.api.interactions import (
    interactions_router,
    _json_array_has_user,
)

from app.routes.api._admin import admin_router

from app.routes.api._settings import settings_router

from app.routes.api._migration import migration_router

from app.routes.api._export import export_router

from app.routes.api._users import users_router

from app.routes.api._auth import auth_router

from app.routes.api._emojis import emoji_router
from app.routes.api._push import push_router
from app.routes.api._sessions import sessions_router
from app.routes.api._announcements import announcements_router
from app.routes.api._pwa import pwa_router
from app.routes.api._meta import meta_router
from app.routes.api._post_create import post_create_router
from app.routes.api._reports import reports_router
from app.routes.api._resolve import resolve_router
from app.routes.api._search import search_router

router.include_router(auth_router)
router.include_router(meta_router)
router.include_router(emoji_router)
router.include_router(pwa_router)
router.include_router(push_router)
router.include_router(sessions_router)
router.include_router(announcements_router)
router.include_router(feed_router)
router.include_router(posts_router)
router.include_router(post_create_router)
router.include_router(reports_router)
router.include_router(resolve_router)
router.include_router(search_router)
router.include_router(interactions_router)
router.include_router(novels_router)
router.include_router(episodes_router)
router.include_router(notices_router)
router.include_router(settings_router)
router.include_router(migration_router)
router.include_router(export_router)
router.include_router(users_router)
router.include_router(admin_router)

__all__ = ["router"]
