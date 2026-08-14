"""Web Push subscription endpoints extracted from _misc.py."""
import base64
import logging

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key
from fastapi import APIRouter, Form, HTTPException, Request

from app.core.auth import require_active_auth
from app.core.push import _get_vapid_key
from app.db.database import get_session
from app.models import PushSubscription

logger = logging.getLogger("writ.api.push")

push_router = APIRouter()


@push_router.get("/push/vapid-public-key")
def get_vapid_public_key():
    keys = _get_vapid_key()
    if not keys:
        raise HTTPException(500, "Web Push configuration error")
    key = keys["publicKey"]
    if key.startswith("-----"):
        try:
            pub = load_pem_public_key(key.encode())
            if isinstance(pub, ec.EllipticCurvePublicKey):
                raw = pub.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
                key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        except Exception as exc:
            raise HTTPException(500, "Web Push configuration error") from exc
    return {"publicKey": key}


@push_router.post("/push/subscribe")
def subscribe_push(request: Request, endpoint: str = Form(...), p256dh: str = Form(...), auth: str = Form(...), device_name: str = Form("")):
    user = require_active_auth(request)
    with get_session() as s:
        existing = s.query(PushSubscription).filter_by(user_id=user.id, endpoint=endpoint).first()
        if existing:
            existing.p256dh = p256dh
            existing.auth = auth
            if device_name:
                existing.device_name = device_name
        else:
            s.add(PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth, device_name=device_name))
        s.commit()
    return {"ok": True}


@push_router.post("/push/unsubscribe")
def unsubscribe_push(request: Request, endpoint: str = Form(...)):
    user = require_active_auth(request)
    with get_session() as s:
        s.query(PushSubscription).filter_by(user_id=user.id, endpoint=endpoint).delete()
        s.commit()
    return {"ok": True}


@push_router.get("/push/subscriptions")
def push_subscriptions(request: Request):
    user = require_active_auth(request)
    with get_session() as s:
        subs = s.query(PushSubscription).filter_by(user_id=user.id).all()
    return {"subscriptions": [{"id": sub.id, "device_name": sub.device_name, "created_at": sub.created_at.isoformat() if sub.created_at else ""} for sub in subs]}


@push_router.post("/push/subscriptions/{sub_id}/delete")
def delete_push_subscription(request: Request, sub_id: int):
    user = require_active_auth(request)
    with get_session() as s:
        sub = s.query(PushSubscription).filter_by(id=sub_id, user_id=user.id).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscription not found")
        s.delete(sub)
        s.commit()
    return {"ok": True}


@push_router.get("/push/status")
def push_status(request: Request):
    user = require_active_auth(request)
    with get_session() as s:
        count = s.query(PushSubscription).filter_by(user_id=user.id).count()
    return {"subscribed": count > 0}
