import secrets
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.auth import verify_password
from app.db.database import get_session
from app.models import MastodonAccessToken, MastodonApp, MastodonAuthorizationCode, User
from app.routes.api._auth import _check_auth_rate_limit, _get_client_ip, _record_auth_failure

router = APIRouter()

# RFC 6749 권고에 따른 인증 코드 유효 기간 (10분)
AUTH_CODE_TTL_SECONDS = 600


def _form_text(form: dict[str, Any], key: str, default: str = "") -> str:
    val = form.get(key)
    return val if isinstance(val, str) else default


def _registered_redirect_uris(app_obj: MastodonApp) -> list[str]:
    uris = [u.strip() for u in (app_obj.redirect_uris or "").split("\n") if u.strip()]
    return uris or ["urn:ietf:wg:oauth:2.0:oob"]


def _authorization_code_expired(created_at) -> bool:
    """created_at이 UTC now 대비 AUTH_CODE_TTL_SECONDS를 넘었는지 확인한다.

    PostgreSQL은 timezone-aware 값을 돌려주지만 SQLite 드라이버는 naive UTC를
    돌려줄 수 있어, naive면 UTC로 간주해 비교한다.
    """
    if not created_at:
        return True
    ca = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - ca).total_seconds() > AUTH_CODE_TTL_SECONDS


def _do_authorize(client_id: str, redirect_uri: str, response_type: str, scope: str, state: str, username: str, password: str, client_ip: str):
    if response_type != "code":
        return JSONResponse({"error": "unsupported_response_type"}, status_code=400)

    if not _check_auth_rate_limit(client_ip):
        return JSONResponse({"error": "rate_limited", "error_description": "Too many attempts. Please try again later."}, status_code=429)

    with get_session() as db:
        app_obj = db.query(MastodonApp).filter_by(client_id=client_id).first()
        if not app_obj:
            return JSONResponse({"error": "Invalid client_id"}, status_code=400)

        if not redirect_uri:
            redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        # 등록되지 않은 redirect_uri로 인증 코드가 발급되는 것을 차단한다 (RFC 6749 §3.1.2)
        if redirect_uri not in _registered_redirect_uris(app_obj):
            return JSONResponse(
                {"error": "invalid_request", "error_description": "Redirect URI is not registered for this client"},
                status_code=400,
            )

        user = db.query(User).filter(
            User.is_remote == False,
            ((User.username == username) | (User.email == username))
        ).first()
        if not user or not user.password_hash:
            _record_auth_failure(client_ip)
            return JSONResponse({"error": "Invalid username or password"}, status_code=401)

        if getattr(user, "is_frozen", False):
            return JSONResponse({"error": "Account frozen"}, status_code=403)
        if getattr(user, "is_suspended", False):
            return JSONResponse({"error": "Account suspended"}, status_code=403)

        salt, hval = user.password_hash.split(":", 1)
        if not verify_password(password, salt, hval):
            _record_auth_failure(client_ip)
            return JSONResponse({"error": "Invalid username or password"}, status_code=401)

        code = secrets.token_urlsafe(32)
        auth_code = MastodonAuthorizationCode(
            code=code,
            app_id=app_obj.id,
            user_id=user.id,
            redirect_uri=redirect_uri,
            scopes=scope,
        )
        db.add(auth_code)
        db.commit()

    if redirect_uri == "urn:ietf:wg:oauth:2.0:oob":
        return JSONResponse({"code": code})

    sep = "&" if "?" in redirect_uri else "?"
    url = f"{redirect_uri}{sep}code={code}"
    if state:
        url += f"&state={state}"
    return JSONResponse({"redirect": url})


@router.post("/api/oauth/authorize")
async def api_oauth_authorize(request: Request):
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)
    return _do_authorize(
        client_id=_form_text(body, "client_id"),
        redirect_uri=_form_text(body, "redirect_uri", "urn:ietf:wg:oauth:2.0:oob"),
        response_type=_form_text(body, "response_type", "code"),
        scope=_form_text(body, "scope", "read write push"),
        state=_form_text(body, "state"),
        username=_form_text(body, "username"),
        password=_form_text(body, "password"),
        client_ip=_get_client_ip(request),
    )


@router.post("/oauth/authorize")
async def oauth_authorize_form(request: Request):
    form = await request.form()
    body = dict(form)
    return _do_authorize(
        client_id=_form_text(body, "client_id"),
        redirect_uri=_form_text(body, "redirect_uri", "urn:ietf:wg:oauth:2.0:oob"),
        response_type=_form_text(body, "response_type", "code"),
        scope=_form_text(body, "scope", "read write push"),
        state=_form_text(body, "state"),
        username=_form_text(body, "username"),
        password=_form_text(body, "password"),
        client_ip=_get_client_ip(request),
    )


@router.post("/oauth/token")
async def oauth_token(request: Request):
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    grant_type = body.get("grant_type", "")
    client_id = body.get("client_id", "")
    client_secret = body.get("client_secret", "")

    with get_session() as db:
        app_obj = db.query(MastodonApp).filter_by(client_id=client_id, client_secret=client_secret).first()
        if not app_obj:
            return JSONResponse({"error": "invalid_client"}, status_code=400)

        if grant_type == "client_credentials":
            token = secrets.token_urlsafe(48)
            mat = MastodonAccessToken(app_id=app_obj.id, user_id=None, access_token=token, scopes="read")
            db.add(mat)
            db.commit()
            return {"access_token": token, "token_type": "bearer", "scope": "read", "created_at": int(time.time())}

        if grant_type == "password":
            client_ip = _get_client_ip(request)
            if not _check_auth_rate_limit(client_ip):
                return JSONResponse({"error": "rate_limited", "error_description": "Too many attempts. Please try again later."}, status_code=429)
            username = body.get("username", "")
            password = body.get("password", "")
            user = db.query(User).filter(
                (User.username == username) | (User.email == username)
            ).first()
            if not user or not user.password_hash:
                _record_auth_failure(client_ip)
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            salt = user.password_hash[:32]
            if not verify_password(password, salt, user.password_hash):
                _record_auth_failure(client_ip)
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            if user.is_suspended:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            scope = body.get("scope", "read write push")
            token = secrets.token_urlsafe(48)
            mat = MastodonAccessToken(app_id=app_obj.id, user_id=user.id, access_token=token, scopes=scope)
            db.add(mat)
            db.commit()
            return {"access_token": token, "token_type": "bearer", "scope": scope, "created_at": int(time.time())}

        if grant_type == "authorization_code":
            code = body.get("code", "")
            auth_code = db.query(MastodonAuthorizationCode).filter_by(
                code=code, used=False, app_id=app_obj.id
            ).first()
            if not auth_code or _authorization_code_expired(auth_code.created_at):
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            # authorize 요청에 redirect_uri가 포함되어 저장되므로, 교환 시 반드시 동일해야 한다 (RFC 6749 §4.1.3)
            requested_redirect = body.get("redirect_uri", "")
            if not requested_redirect or requested_redirect != auth_code.redirect_uri:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            auth_code.used = True
            db.commit()
            # 토큰 스코프는 승인된(auth_code) 스코프로 고정 — 교환 시 확대를 차단한다 (RFC 6749 §4.1.4)
            scope = auth_code.scopes or "read write"
            token = secrets.token_urlsafe(48)
            mat = MastodonAccessToken(app_id=app_obj.id, user_id=auth_code.user_id, access_token=token, scopes=scope)
            db.add(mat)
            db.commit()
            return {"access_token": token, "token_type": "bearer", "scope": scope, "created_at": int(time.time())}

        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
