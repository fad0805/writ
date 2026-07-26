import os
import time
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config.settings import APP_ENV, DOMAIN
from app.config.logging import _request_logger
from app.utils.crypto import CSRF_EXEMPT_PREFIXES, CSRF_EXEMPT_EXACT, CSRF_EXEMPT_METHODS, validate_csrf_token


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in CSRF_EXEMPT_METHODS:
            return await call_next(request)
        path = request.url.path
        for prefix in CSRF_EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)
        if path in CSRF_EXEMPT_EXACT or any(path.startswith(p) for p in CSRF_EXEMPT_EXACT):
            return await call_next(request)
        session_token = request.cookies.get("session", "")
        csrf_token = request.headers.get("X-CSRF-Token", "")
        if APP_ENV == "development":
            pass
        else:
            host_header = request.headers.get("Host", "")
            if host_header in ("api:8000", "localhost:8000") or host_header.startswith("172."):
                host_header = DOMAIN
            origin = request.headers.get("Origin", "")
            referer = request.headers.get("Referer", "")
            if origin:
                try:
                    origin_host = urlparse(origin).netloc
                except Exception:
                    origin_host = ""
                if origin_host and origin_host != host_header:
                    print(f"[CSRF] origin mismatch: origin={origin_host} host={host_header}", flush=True)
                    return JSONResponse({"detail": "CSRF origin mismatch"}, status_code=403)
            elif referer:
                try:
                    referer_host = urlparse(referer).netloc
                except Exception:
                    referer_host = ""
                if referer_host and referer_host != host_header:
                    print(f"[CSRF] referer mismatch: referer={referer_host} host={host_header}", flush=True)
                    return JSONResponse({"detail": "CSRF referer mismatch"}, status_code=403)
        if not validate_csrf_token(csrf_token, session_token):
            return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)
        return await call_next(request)


class LogRequestsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = time.time() - start
        _request_logger.info("%s %s -> %s (%.0fms)", request.method, request.url.path, response.status_code, elapsed * 1000)
        return response
