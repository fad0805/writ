import logging
import time
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config.logging import _request_logger
from app.config.settings import APP_ENV
from app.utils.crypto import (
    CSRF_EXEMPT_EXACT,
    CSRF_EXEMPT_METHODS,
    CSRF_EXEMPT_PREFIXES,
    csrf_token_user_id,
    generate_csrf_token,
    validate_csrf_token,
)
from app.utils.http import normalize_host

logger = logging.getLogger("writ.middleware")


def _renew_csrf_cookie(response, uid: int | None):
    if not uid:
        return
    secure = APP_ENV != "development"
    response.set_cookie(key="csrf_token", value=generate_csrf_token(uid), max_age=30*86400, httponly=False, samesite="lax", path="/", secure=secure)


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        for prefix in CSRF_EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)
        if path in CSRF_EXEMPT_EXACT or any(path.startswith(p) for p in CSRF_EXEMPT_EXACT):
            return await call_next(request)
        session_token = request.cookies.get("session", "")
        if request.method in CSRF_EXEMPT_METHODS:
            response = await call_next(request)
            uid = csrf_token_user_id(request.cookies.get("csrf_token", ""))
            if session_token and uid:
                _renew_csrf_cookie(response, uid)
            return response
        csrf_token = request.headers.get("X-CSRF-Token", "")
        if APP_ENV == "development":
            pass
        else:
            host_header = normalize_host(request)
            origin = request.headers.get("Origin", "")
            referer = request.headers.get("Referer", "")
            if origin:
                try:
                    origin_host = urlparse(origin).netloc
                except Exception:
                    origin_host = ""
                if origin_host and origin_host != host_header:
                    logger.warning("CSRF origin mismatch: origin=%s host=%s", origin_host, host_header)
                    return JSONResponse({"detail": "CSRF origin mismatch"}, status_code=403)
            elif referer:
                try:
                    referer_host = urlparse(referer).netloc
                except Exception:
                    referer_host = ""
                if referer_host and referer_host != host_header:
                    logger.warning("CSRF referer mismatch: referer=%s host=%s", referer_host, host_header)
                    return JSONResponse({"detail": "CSRF referer mismatch"}, status_code=403)
        if not validate_csrf_token(csrf_token, session_token):
            return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)
        response = await call_next(request)
        uid = csrf_token_user_id(csrf_token)
        if uid:
            _renew_csrf_cookie(response, uid)
        return response


class LogRequestsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = time.time() - start
        _request_logger.info("%s %s -> %s (%.0fms)", request.method, request.url.path, response.status_code, elapsed * 1000)
        return response
