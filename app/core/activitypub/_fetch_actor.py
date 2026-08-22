"""Remote actor fetch helpers.

_resolve_actor와 기타 결의 헬퍼는 _actor_resolver.py로 분리했다
(_fetch_post와의 순환 import 제거). 이 모듈의 공개 _resolve_actor는 pinned
동기화까지 포함한 랩퍼이며, 원본(순수) 결의는 _actor_resolver._resolve_actor로
유지된다. _fetch_post는 pinned가 불필요한 순수 버전을 직접 import한다.
"""

import logging

from app.core.activitypub._actor_resolver import (  # noqa: F401
    _extract_custom_fields,
    _fetch_remote_count,
    _fetch_remote_featured,
)
from app.core.activitypub._actor_resolver import _resolve_actor as _resolve_actor_core
from app.core.activitypub._fetch_post import _fetch_remote_post
from app.core.activitypub._utils import _get_instance_actor
from app.db.database import get_session
from app.models import Post, User

logger = logging.getLogger("writ.activitypub")


def _sync_remote_pinned_posts(user_id: int, pinned_ap_ids: list, sign_as: User | None = None):
    """Resolve remote featured (pinned) AP IDs to local Post IDs and store on the user.

    Empty pinned_ap_ids clears existing pins (the remote user unpinned everything).
    """
    with get_session() as session:
        user = session.query(User).get(user_id)
        if not user or not user.is_remote:
            return
        signer = sign_as or _get_instance_actor(session)
        new_pinned = []
        for ap_id in pinned_ap_ids:
            post = session.query(Post).filter_by(ap_id=ap_id).first()
            if post and not post.is_deleted:
                new_pinned.append(post.id)
                continue
            if signer:
                try:
                    fetched = _fetch_remote_post(ap_id, signer, session)
                    if fetched:
                        new_pinned.append(fetched.id)
                except Exception as e:
                    logger.warning("[PINNED] failed to fetch %s: %s", ap_id, e)
        user.pinned_posts = new_pinned
        session.commit()


def resolve_actor_with_pins(actor_url: str, force_refresh: bool = False, sign_as: User | None = None, lightweight: bool = False, timeout: int = 10) -> User | None:
    """_resolve_actor + 원격 pinned 동기화 랩퍼.

    lightweight=False로 결의된 경우 반환된 User에 부여된 pending_pinned_ap_ids 를
    _sync_remote_pinned_posts로 처리한다. _resolve_actor(순수)와 달리 pinned 까지
    동기화하므로, 기존 _resolve_actor 호출자 중 pinned를 원하는 곳이 사용한다.
    """
    user = _resolve_actor_core(
        actor_url, force_refresh=force_refresh, sign_as=sign_as,
        lightweight=lightweight, timeout=timeout,
    )
    pending = getattr(user, "pending_pinned_ap_ids", None)
    if user and pending is not None:
        user.pending_pinned_ap_ids = None
        _sync_remote_pinned_posts(user.id, pending, sign_as)
    return user


# 공개 _resolve_actor: 기존 동작(기본 lightweight=False 시 pinned 동기화) 보존을
# 위해 랩퍼를 사용한다.
_resolve_actor = resolve_actor_with_pins
