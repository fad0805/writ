"""Developer settings API — application registration and personal access tokens.

These endpoints back the Mastodon-style "Development" settings page.  They use
the normal WRIT session cookie (not an OAuth bearer token) and only expose
applications owned by the current user.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session as SASession

from app.core.auth import require_active_auth
from app.core.mastodon_scopes import (
    has_admin_scope,
    normalize_scopes,
    parse_scopes,
    scope_allowed,
    scopes_to_string,
)
from app.core.permissions import is_staff
from app.db.database import get_db
from app.models import MastodonAccessToken, MastodonApp, MastodonAuthorizationCode
from app.utils.datetime import _fmt_dt

developer_router = APIRouter()

_DEFAULT_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
_MAX_REDIRECT_URIS = 20
_MAX_REDIRECT_URI_LENGTH = 1024
_FORBIDDEN_URI_SCHEMES = {"data", "file", "javascript", "vbscript"}


def _text(body: dict, key: str, default: str = "") -> str:
    value = body.get(key)
    return value if isinstance(value, str) else default


def _clean_redirect_uris(raw) -> list[str]:
    values = [str(v) for v in raw] if isinstance(raw, list) else str(raw or "").splitlines()

    uris: list[str] = []
    for value in values:
        uri = value.strip()
        if not uri:
            continue
        if len(uri) > _MAX_REDIRECT_URI_LENGTH:
            raise HTTPException(status_code=400, detail="Redirect URI is too long")
        if any(ch.isspace() for ch in uri):
            raise HTTPException(status_code=400, detail="Redirect URI must not contain whitespace")
        parsed = urlparse(uri)
        if not parsed.scheme:
            raise HTTPException(status_code=400, detail="Redirect URI must include a scheme")
        if parsed.scheme.lower() in _FORBIDDEN_URI_SCHEMES:
            raise HTTPException(status_code=400, detail="Unsupported redirect URI scheme")
        if uri not in uris:
            uris.append(uri)

    if not uris:
        raise HTTPException(status_code=400, detail="At least one redirect URI is required")
    if len(uris) > _MAX_REDIRECT_URIS:
        raise HTTPException(status_code=400, detail="Too many redirect URIs")
    return uris


def _clean_website(raw: str) -> str:
    website = raw.strip()
    if not website:
        return ""
    if len(website) > 512:
        raise HTTPException(status_code=400, detail="Website URL is too long")
    parsed = urlparse(website)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Website must be an http(s) URL")
    return website


def _validate_scopes_for_user(user, scopes: list[str]) -> None:
    if not scopes:
        raise HTTPException(status_code=400, detail="At least one scope is required")
    if has_admin_scope(scopes) and not is_staff(user):
        raise HTTPException(status_code=403, detail="Admin scopes require staff permissions")


def _app_tokens(db: SASession, app: MastodonApp, user_id: int) -> list[MastodonAccessToken]:
    return (
        db.query(MastodonAccessToken)
        .filter_by(app_id=app.id, user_id=user_id)
        .order_by(MastodonAccessToken.id.desc())
        .all()
    )


def _token_json(token: MastodonAccessToken) -> dict:
    return {
        "id": token.id,
        "access_token": token.access_token,
        "scopes": parse_scopes(token.scopes),
        "created_at": _fmt_dt(token.created_at),
    }


def _app_json(db: SASession, app: MastodonApp, user_id: int) -> dict:
    tokens = _app_tokens(db, app, user_id)
    return {
        "id": app.id,
        "name": app.client_name,
        "website": app.website or None,
        "redirect_uri": app.redirect_uris,
        "redirect_uris": [u for u in (app.redirect_uris or "").splitlines() if u.strip()],
        "scopes": parse_scopes(app.scopes),
        "client_id": app.client_id,
        "client_secret": app.client_secret,
        "created_at": _fmt_dt(app.created_at),
        "ownerless": app.user_id is None,
        "tokens": [_token_json(t) for t in tokens],
    }


def _can_manage_app(user, app: MastodonApp) -> bool:
    if app.user_id == user.id:
        return True
    # Apps registered through the public POST /api/v1/apps endpoint have no
    # owner.  Staff members may manage them from the developer settings page.
    return app.user_id is None and is_staff(user)


def _owned_app(db: SASession, user, app_id: int) -> MastodonApp:
    app = db.query(MastodonApp).filter_by(id=app_id).first()
    if not app or not _can_manage_app(user, app):
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@developer_router.get("/developer/apps")
def list_developer_apps(request: Request, db: SASession = Depends(get_db)):
    user = require_active_auth(request)
    query = db.query(MastodonApp)
    if is_staff(user):
        query = query.filter(or_(MastodonApp.user_id == user.id, MastodonApp.user_id.is_(None)))
    else:
        query = query.filter(MastodonApp.user_id == user.id)
    apps = query.order_by(MastodonApp.id.desc()).all()
    return {"apps": [_app_json(db, app, user.id) for app in apps]}


@developer_router.post("/developer/apps")
async def create_developer_app(request: Request, db: SASession = Depends(get_db)):
    user = require_active_auth(request)
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    name = _text(body, "client_name", _text(body, "name")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Application name is required")
    if len(name) > 256:
        raise HTTPException(status_code=400, detail="Application name is too long")

    website = _clean_website(_text(body, "website"))
    redirect_raw = body.get("redirect_uris")
    if redirect_raw is None:
        redirect_raw = body.get("redirect_uri")
    if redirect_raw is None:
        redirect_raw = _DEFAULT_REDIRECT_URI
    redirect_uris = _clean_redirect_uris(redirect_raw)

    scopes_raw = body.get("scopes")
    if scopes_raw is None:
        scopes_raw = "read"
    try:
        scopes = normalize_scopes(scopes_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _validate_scopes_for_user(user, scopes)

    app = MastodonApp(
        user_id=user.id,
        client_name=name,
        redirect_uris="\n".join(redirect_uris),
        scopes=scopes_to_string(scopes),
        website=website,
        client_id=secrets.token_urlsafe(32),
        client_secret=secrets.token_urlsafe(48),
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return {"app": _app_json(db, app, user.id)}


@developer_router.delete("/developer/apps/{app_id}")
def delete_developer_app(app_id: int, request: Request, db: SASession = Depends(get_db)):
    user = require_active_auth(request)
    app = _owned_app(db, user, app_id)

    db.query(MastodonAuthorizationCode).filter_by(app_id=app.id).delete()
    db.query(MastodonAccessToken).filter_by(app_id=app.id).delete()
    db.delete(app)
    db.commit()
    return {"ok": True}


@developer_router.post("/developer/apps/{app_id}/token")
async def create_developer_token(app_id: int, request: Request, db: SASession = Depends(get_db)):
    user = require_active_auth(request)
    app = _owned_app(db, user, app_id)

    body: dict = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
        except ValueError:
            body = {}

    app_scopes = parse_scopes(app.scopes)
    requested = body.get("scopes") if isinstance(body, dict) else None
    try:
        scopes = normalize_scopes(requested) if requested else app_scopes
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not scopes or not all(scope_allowed(app_scopes, scope) for scope in scopes):
        raise HTTPException(status_code=400, detail="Token scopes must be a subset of the application scopes")
    _validate_scopes_for_user(user, scopes)

    token = MastodonAccessToken(
        app_id=app.id,
        user_id=user.id,
        access_token=secrets.token_urlsafe(48),
        scopes=scopes_to_string(scopes),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return {"token": _token_json(token)}


@developer_router.delete("/developer/tokens/{token_id}")
def revoke_developer_token(token_id: int, request: Request, db: SASession = Depends(get_db)):
    user = require_active_auth(request)
    token = (
        db.query(MastodonAccessToken)
        .filter_by(id=token_id, user_id=user.id)
        .first()
    )
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    app = db.query(MastodonApp).filter_by(id=token.app_id).first()
    if not app or not _can_manage_app(user, app):
        raise HTTPException(status_code=404, detail="Token not found")

    db.delete(token)
    db.commit()
    return {"ok": True}
