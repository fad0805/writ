"""Account migration (이전) endpoints extracted from _settings.py."""
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Request, Form, HTTPException

from app.models import User, Novel, Follow, Notification
from app.config.settings import BASE_URL, DOMAIN
from app.core.activitypub import broadcast_to_followers, _fetch_actor_json_signed
from app.db.database import get_session
from app.db.mention_resolver import _resolve_remote_user
from app.core.auth import require_auth
from app.utils.log import log_admin_action

logger = logging.getLogger("writ.api.migration")

migration_router = APIRouter()


@migration_router.post("/settings/migrate")
def api_migrate_account(request: Request, target_username: str = Form(...), series_ids: str = Form("[]")):
    user = require_auth(request)
    if user.is_frozen:
        raise HTTPException(status_code=400, detail="이미 동결된 계정입니다.")
    if getattr(user, 'moved_to', ''):
        raise HTTPException(status_code=400, detail="이미 이전된 계정입니다.")
    target_username = target_username.strip().lstrip("@")
    if not target_username:
        raise HTTPException(status_code=400, detail="대상 계정을 입력하세요.")

    local_name = None
    if "@" not in target_username:
        local_name = target_username
    else:
        _name, _domain = target_username.rsplit("@", 1)
        if _domain.strip().lower().rstrip("/") == DOMAIN.lower():
            local_name = _name

    if local_name is None:
        return _migrate_out_to_remote(request, user, target_username)

    with get_session() as s:
        target = s.query(User).filter_by(username=local_name, is_remote=False).first()
        if not target:
            raise HTTPException(status_code=404, detail="대상 계정을 찾을 수 없습니다.")
        if target.id == user.id:
            raise HTTPException(status_code=400, detail="자기 자신에게 이전할 수 없습니다.")
        if target.is_frozen:
            raise HTTPException(status_code=400, detail="대상 계정이 동결되어 있습니다.")
        if getattr(target, 'is_deactivated', False) or getattr(target, 'moved_to', ''):
            raise HTTPException(status_code=400, detail="대상 계정이 이미 이전된 계정입니다.")

        try:
            sids = json.loads(series_ids)
            if not isinstance(sids, list):
                sids = []
        except (json.JSONDecodeError, TypeError):
            sids = []

        meta = json.dumps({
            "type": "migrate_request",
            "from_user_id": user.id,
            "from_username": user.username,
            "from_display": user.display_name or user.username,
            "series_ids": sids,
        })
        s.add(Notification(
            user_id=target.id, from_user_id=user.id,
            notification_type="moderation",
            metadata_json=meta,
        ))
        s.commit()

    return {"ok": True, "message": f"{target_username}님에게 이전 요청을 보냈습니다. 상대방이 수락하면 이전이 완료됩니다."}


def _migrate_out_to_remote(request: Request, user, target_handle: str):
    """Move the local account out to a remote account (ActivityPub Move).

    Verifies the remote account lists this account in `alsoKnownAs`, then
    sends a Move activity to the local account's remote followers and freezes
    the local account.
    """
    remote = _resolve_remote_user(target_handle)
    if not remote:
        raise HTTPException(status_code=404, detail="대상 계정을 찾을 수 없습니다.")
    new_actor_url = remote.remote_url or ""

    actor_data = _fetch_actor_json_signed(new_actor_url, user)
    known_as = actor_data.get("alsoKnownAs", []) if isinstance(actor_data, dict) else []
    if not isinstance(known_as, list):
        known_as = []
    own_url = user.actor_uri().rstrip("/").lower()
    if not any((str(k) or "").rstrip("/").lower() == own_url for k in known_as):
        raise HTTPException(
            status_code=400,
            detail="새 계정에 현재 계정이 별칭(alsoKnownAs)으로 등록되어 있지 않습니다. "
                   "새 계정(마스토돈 등)에서 먼저 이 계정을 별칭으로 추가한 후 다시 시도하세요.",
        )

    activity = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{BASE_URL}/activities/move/{uuid4().hex}",
        "type": "Move",
        "actor": user.actor_uri(),
        "object": user.actor_uri(),
        "target": new_actor_url,
        "to": [f"{BASE_URL}/users/{user.username}/followers"],
    }
    try:
        broadcast_to_followers(user, activity)
    except Exception:
        logger.exception("Move: failed to broadcast Move to followers")

    with get_session() as s:
        db = s.query(User).filter_by(id=user.id).first()
        followers = s.query(Follow).filter_by(following_id=db.id, accepted=True).all()
        moved_local = 0
        for f in followers:
            existing = s.query(Follow).filter_by(follower_id=f.follower_id, following_id=remote.id).first()
            if not existing:
                f.following_id = remote.id
                moved_local += 1
        db.is_deactivated = True
        db.is_frozen = False
        db.is_suspended = False
        db.moved_to = new_actor_url
        db.session_token = ""
        db.aliases = []
        s.commit()

    log_admin_action(
        user.id, user.username, "account_migrated_remote",
        target_username=remote.username if remote.username else target_handle,
        ip_address=request.client.host if request.client else "",
    )
    logger.info("Move: local %s moved out to %s (%d local followers repointed)", user.username, new_actor_url, moved_local)
    return {"ok": True, "message": "계정 이전(Move)이 팔로워에게 전송되었습니다."}


@migration_router.post("/settings/migrate/approve")
def api_approve_migrate(request: Request, notification_id: int = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        n = s.query(Notification).filter_by(id=notification_id, user_id=user.id).first()
        if not n or n.notification_type != "moderation":
            raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")
        meta = {}
        try:
            meta = json.loads(n.metadata_json or "{}")
        except json.JSONDecodeError:
            pass
        if meta.get("type") != "migrate_request":
            raise HTTPException(status_code=400, detail="잘못된 요청입니다.")

        from_user_id = meta.get("from_user_id")
        from_user = s.query(User).get(from_user_id)
        if not from_user:
            raise HTTPException(status_code=404, detail="요청한 계정을 찾을 수 없습니다.")
        if getattr(from_user, 'is_deactivated', False):
            raise HTTPException(status_code=400, detail="이미 이전된 계정입니다.")

        series_ids = meta.get("series_ids", [])
        if series_ids:
            novels = s.query(Novel).filter(Novel.id.in_(series_ids), Novel.author_id == from_user_id).all()
            for nv in novels:
                nv.author_id = user.id

        if from_user:
            from_user.is_deactivated = True
            from_user.is_frozen = False
            from_user.is_suspended = False
            from_user.session_token = ""
            from_user.moved_to = f"{BASE_URL}/@{user.username}"
            from_user.aliases = []

        s.delete(n)
        s.commit()

        log_admin_action(user.id, user.username, "account_migrated", target_type="user", target_id=from_user.id if from_user else 0, target_username=from_user.username if from_user else "", ip_address=request.client.host if request.client else "")

    return {"ok": True, "message": "계정 이전이 완료되었습니다."}


@migration_router.post("/settings/migrate/reject")
def api_reject_migrate(request: Request, notification_id: int = Form(...)):
    user = require_auth(request)
    with get_session() as s:
        n = s.query(Notification).filter_by(id=notification_id, user_id=user.id).first()
        if n:
            s.delete(n)
            s.commit()
    return {"ok": True}
