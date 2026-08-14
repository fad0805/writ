"""Mastodon OAuth app endpoints (/api/v1/apps*)."""
import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session as SASession

from app.db.database import get_db
from app.models import MastodonAccessToken, MastodonApp
from app.routes.mastodon_api._common import MastodonAPIError

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/v1/apps — Register client application
# ---------------------------------------------------------------------------
@router.post("/v1/apps")
async def create_app(request: Request, db: SASession = Depends(get_db)):
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    client_name = body.get("client_name") or "WRIT Client"
    redirect_uris = body.get("redirect_uris", "urn:ietf:wg:oauth:2.0:oob")
    if isinstance(redirect_uris, list):
        redirect_uris = "\n".join(redirect_uris)
    scopes = body.get("scopes", "read write push")
    website = body.get("website", "")

    client_id = secrets.token_urlsafe(32)
    client_secret = secrets.token_urlsafe(48)

    app = MastodonApp(
        client_name=client_name,
        redirect_uris=redirect_uris,
        scopes=scopes,
        website=website,
        client_id=client_id,
        client_secret=client_secret,
    )
    db.add(app)
    db.commit()
    db.refresh(app)

    return {
        "id": str(app.id),
        "name": app.client_name,
        "website": app.website or None,
        "scopes": app.scopes.split(),
        "redirect_uri": app.redirect_uris,
        "redirect_uris": app.redirect_uris.split("\n"),
        "client_id": app.client_id,
        "client_secret": app.client_secret,
        "client_secret_expires_at": 0,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/apps/verify_credentials
# ---------------------------------------------------------------------------
@router.get("/v1/apps/verify_credentials")
def verify_app_credentials(request: Request, db: SASession = Depends(get_db)):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise MastodonAPIError(status_code=401, detail="The access token is invalid")
    token = auth[7:]
    mat = db.query(MastodonAccessToken).filter_by(access_token=token).first()
    if not mat:
        raise MastodonAPIError(status_code=401, detail="The access token is invalid")
    app = db.query(MastodonApp).filter_by(id=mat.app_id).first()
    if not app:
        raise MastodonAPIError(status_code=401, detail="The access token is invalid")
    return {
        "id": str(app.id),
        "name": app.client_name,
        "website": app.website or None,
        "scopes": app.scopes.split(),
        "redirect_uris": app.redirect_uris.split("\n"),
        "vapid_key": "",
    }
