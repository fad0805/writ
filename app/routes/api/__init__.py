"""API package — core + posts + interactions + admin endpoints assembled into one router.

Import ``router`` from here:
    from app.routes.api import router, _cleanup_avatars
"""

from app.routes.api._core import (
    router,
    _cleanup_avatars,
    _broadcast_update_actor,
)

from app.routes.api._misc import (
    _read_storage_file,
    _save_pwa_icons,
    _save_favicon,
    _delete_favicon,
    _delete_pwa_icons,
)

from app.routes.api._series import (
    series_router,
    _novel_json,
    _episode_json,
    _apply_latest_activity_order,
)

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

from app.core.timeline_stream import _broadcast_timeline

from app.routes.api.interactions import (
    interactions_router,
    _json_array_has_user,
)

from app.routes.api._admin import admin_router

from app.routes.api._settings import settings_router

from app.routes.api._users import users_router

from app.routes.api._auth import auth_router

from app.routes.api._misc import misc_router

router.include_router(auth_router)
router.include_router(misc_router)
router.include_router(feed_router)
router.include_router(posts_router)
router.include_router(interactions_router)
router.include_router(series_router)
router.include_router(settings_router)
router.include_router(users_router)
router.include_router(admin_router)

__all__ = ["router"]
