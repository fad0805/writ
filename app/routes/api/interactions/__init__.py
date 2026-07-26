"""Interactions package."""
from fastapi import APIRouter
from app.routes.api.interactions._common import _json_array_has_user
from app.routes.api.interactions.follow import follow_router
from app.routes.api.interactions.notify import notify_router
from app.routes.api.interactions.mutes import mutes_router
from app.routes.api.interactions.engagement import engagement_router
from app.routes.api.interactions.reactions import reactions_router
from app.routes.api.interactions.polls import polls_router
from app.routes.api.interactions.pins import pins_router

interactions_router = APIRouter()
interactions_router.include_router(follow_router)
interactions_router.include_router(notify_router)
interactions_router.include_router(mutes_router)
interactions_router.include_router(engagement_router)
interactions_router.include_router(reactions_router)
interactions_router.include_router(polls_router)
interactions_router.include_router(pins_router)
__all__ = ["interactions_router"]
