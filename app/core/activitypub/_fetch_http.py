import datetime
import logging
import re
import time
from urllib.parse import urlparse

import httpx

from app.config.settings import SECRET_KEY
from app.utils.crypto import get_private_key, sign_string
from app.utils.http import WRIT_USER_AGENT, safe_fetch, validate_url

logger = logging.getLogger("writ.activitypub")


def _fetch_ap_json(url, headers=None, timeout=10, _depth=0):
    """Fetch AP JSON. If server returns HTML, parse for rel=alternate AP link and retry."""
    if _depth > 2:
        return None
    unsigned_headers = {"Accept": "application/activity+json"}
    try:
        resp = safe_fetch(url, timeout=timeout, headers=headers or unsigned_headers)
        if not resp or resp.status_code != 200:
            return None
        ct = resp.headers.get("content-type", "")
        body = resp.text[:200000] if "json" not in ct and "activity" not in ct else ""
        if body:
            alt_m = re.search(r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/activity\+json["\'][^>]+href=["\']([^"\']+)["\']', body, re.I)
            if not alt_m:
                alt_m = re.search(r'<link[^>]+type=["\']application/activity\+json["\'][^>]+rel=["\']alternate["\'][^>]+href=["\']([^"\']+)["\']', body, re.I)
            if not alt_m:
                alt_m = re.search(r'href=["\']([^"\']+)["\'][^>]*type=["\']application/activity\+json["\']', body, re.I)
            if alt_m:
                return _fetch_ap_json(alt_m.group(1), headers=unsigned_headers, timeout=timeout, _depth=_depth + 1)
            return None
        return resp.json()
    except Exception:
        return None


def _fetch_actor_json_signed(actor_url: str, sign_as=None) -> dict | None:
    """Fetch a remote actor document with an HTTP signature.

    Some servers (e.g. Mastodon) return 401 for unsigned actor requests, so we
    sign the request as `sign_as` when available.
    """
    if not actor_url:
        return None
    try:
        parsed = urlparse(actor_url)
        headers = {
            "Accept": "application/activity+json",
            "User-Agent": WRIT_USER_AGENT,
        }
        if sign_as is not None:
            date = datetime.datetime.now(datetime.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
            created = int(time.time())
            ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
            priv = get_private_key(sign_as, SECRET_KEY)
            sig = sign_string(ss, priv)
            headers["Signature"] = (
                f'keyId="{sign_as.actor_uri()}#main-key",algorithm="hs2019",'
                f'created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
            )
            headers["Date"] = date
            headers["Host"] = parsed.netloc
        data = _fetch_ap_json(actor_url, headers=headers)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _safe_httpx_get(url, headers=None, timeout=15, max_size=5*1024*1024):
    """HTTP GET with redirect validation and size limit."""
    if not validate_url(url):
        logger.warning("[SAFE_GET] blocked by validate_url url=%s", url)
        return None
    client = httpx.Client(follow_redirects=True, timeout=timeout)
    # Intercept redirects to validate each target
    original_send = client.send
    def _validated_send(request, **kwargs):
        if validate_url(str(request.url)):
            return original_send(request, **kwargs)
        raise httpx.InvalidURL(f"Blocked redirect to {request.url}")
    client.send = _validated_send
    try:
        resp = client.get(url, headers=headers)
        client.close()
        logger.debug("[SAFE_GET] url=%s status=%s len=%s", url, resp.status_code, len(resp.content))
        if resp.status_code != 200:
            return None
        if len(resp.content) > max_size:
            return None
        return resp
    except Exception:
        client.close()
        return None
