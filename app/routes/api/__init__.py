"""API package — core endpoints + admin endpoints assembled into one router.

Import ``router`` from here:
    from app.routes.api import router, _cleanup_avatars
"""

from app.routes.api._core import (
    router,
    _cleanup_avatars,
    _sync_post_tags,
    _broadcast_update_actor,
    _broadcast_federation,
    _broadcast_timeline,
    _novel_json,
    _apply_latest_activity_order,
    _read_storage_file,
    _save_pwa_icons,
    _save_favicon,
    _delete_favicon,
    _delete_pwa_icons,
)

from app.routes.api._admin import admin_router

# Mount admin routes onto the core router so the rest of the app
# only needs to include one ``router``.
router.include_router(admin_router)

__all__ = ["router"]
