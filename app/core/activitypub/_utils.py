import io
import os
import re
import time
import datetime
import ipaddress
import logging
import socket
from urllib.parse import urlparse, urljoin

import httpx

from app.config.settings import BASE_URL, DOMAIN
from app.db.database import get_session
from app.models import ServerSetting, FederationBlock, AllowedServer, User
from app.utils.crypto import generate_keypair, sign_string, encrypt_key, get_private_key

logger = logging.getLogger("writ.activitypub")

WRIT_USER_AGENT = "WRIT/1.0 (+https://daydream.ink)"

_PRIVATE_SUBNETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("2001:db8::/32"),
]


def _federation_allowed(domain: str) -> bool:
    if not domain:
        return False
    if domain.lower().strip() == DOMAIN.lower().strip():
        return True
    with get_session() as s:
        try:
            settings = s.query(ServerSetting).first()
            if not settings:
                return True
            mode = settings.federation_mode or "blacklist"
            domain = domain.lower().strip()
            if mode == "whitelist":
                allowed = s.query(AllowedServer).filter_by(domain=domain).first()
                return allowed is not None
            else:
                blocked = s.query(FederationBlock).filter_by(domain=domain).first()
                return blocked is None
        except Exception:
            return False


def _html_to_newlines(raw_html: str) -> str:
    """Convert HTML line breaks/paragraphs to \\n for consistent storage."""
    new_html = re.sub(r'<br\s*/?>', '\n', raw_html, flags=re.I)
    new_html = re.sub(r'</?p>', '\n', new_html, flags=re.I)
    return new_html.strip('\n')


def _validate_url(url: str) -> bool:
    """Reject URLs pointing to private/internal IPs (SSRF protection)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    _SSRF_ALLOWED = {s.strip() for s in os.environ.get("SSRF_ALLOWED_DOMAINS", "").split(",") if s.strip()}
    own_domain = urlparse(BASE_URL).hostname or DOMAIN
    _SSRF_ALLOWED.add(own_domain)
    if host in _SSRF_ALLOWED:
        return True
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    if host.endswith(".localhost"):
        return False
    try:
        addrs = socket.getaddrinfo(host, 80, family=socket.AF_UNSPEC)
        for addr in addrs:
            ip = ipaddress.ip_address(addr[4][0])
            for net in _PRIVATE_SUBNETS:
                if ip in net:
                    return False
    except (socket.gaierror, OSError, ValueError):
        pass
    try:
        ip = ipaddress.ip_address(host)
        for net in _PRIVATE_SUBNETS:
            if ip in net:
                return False
    except ValueError:
        pass
    return True


def _parse_username_from_url(url: str) -> str:
    url = url.rstrip("/")
    match = re.search(r'/(?:users/)?@?([\w.\-]+)$', url)
    if match:
        return match.group(1)
    return url.split("/")[-1]


def _safe_fetch(url, timeout=10, max_size=5*1024*1024, headers=None):
    """HTTP GET with redirect validation and size limit."""
    if not _validate_url(url):
        return None
    domain = urlparse(url).hostname or ""
    if not _federation_allowed(domain):
        logger.info("Federation blocked for domain: %s", domain)
        return None
    client = httpx.Client(follow_redirects=True, timeout=timeout)
    original_send = client.send
    def _validated_send(request, **kwargs):
        if _validate_url(str(request.url)):
            return original_send(request, **kwargs)
        raise httpx.InvalidURL(f"Blocked redirect to {request.url}")
    client.send = _validated_send
    try:
        resp = client.get(url, headers=headers or {})
        if resp.status_code != 200:
            return None
        if len(resp.content) > max_size:
            return None
        return resp
    except Exception as e:
        return None
    finally:
        client.close()


def _validated_get(url: str, headers: dict = None, timeout: int = 15, max_redirects: int = 5):
    """HTTP GET with SSRF-safe redirect validation."""
    if not _validate_url(url):
        return None
    client = httpx.Client(follow_redirects=False, timeout=timeout)
    try:
        resp = client.get(url, headers=headers or {})
        for _ in range(max_redirects):
            if resp.status_code not in (301, 302, 307, 308):
                return resp
            location = resp.headers.get("location", "")
            if not location:
                return resp
            url = urljoin(url, location)
            if not _validate_url(url):
                logger.warning("SSRF blocked redirect to %s", url)
                return None
            resp = client.get(url, headers=headers or {})
        return resp
    except Exception:
        return None
    finally:
        client.close()


def _get_instance_actor(session) -> User:
    """Get or create the instance actor (system account for server-level requests)."""
    actor = session.query(User).filter_by(username="actor", is_remote=False).first()
    if not actor:
        priv, pub = generate_keypair()
        actor = User(
            username="actor",
            display_name="(instance actor)",
            password_hash="",
            private_key=encrypt_key(priv, SECRET_KEY),
            public_key=pub,
            is_remote=False,
            is_admin=False,
            role="actor",
        )
        session.add(actor)
        session.commit()
    return actor
