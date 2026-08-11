import ipaddress
import logging
import os
import socket
import time
from urllib.parse import urlparse, urljoin

import httpx

from app.config.settings import BASE_URL, DOMAIN
from app.core.federation import federation_allowed

logger = logging.getLogger("writ.http")

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


# 호스트별 DNS 검사 결과 TTL 캐시 — validate_url은 리다이렉트/요청마다 호출되어
# 매번 동기 getaddrinfo를 수행하므로, 같은 호스트는 60초간 재사용한다.
# value = (만료시각, private 여부)
_DNS_RESULT_CACHE: dict[str, tuple[float, bool]] = {}
_DNS_CACHE_TTL = 60.0
_DNS_CACHE_MAX = 4096


def _dns_resolves_private(host: str) -> bool:
    """Return True if any resolved address of `host` is in a private subnet."""
    now = time.time()
    cached = _DNS_RESULT_CACHE.get(host)
    if cached is not None and cached[0] > now:
        return cached[1]
    is_private = False
    try:
        addrs = socket.getaddrinfo(host, 80, family=socket.AF_UNSPEC)
        for addr in addrs:
            ip = ipaddress.ip_address(addr[4][0])
            for net in _PRIVATE_SUBNETS:
                if ip in net:
                    is_private = True
                    break
            if is_private:
                break
    except (socket.gaierror, OSError, ValueError):
        pass
    if len(_DNS_RESULT_CACHE) >= _DNS_CACHE_MAX:
        _DNS_RESULT_CACHE.clear()
    _DNS_RESULT_CACHE[host] = (now + _DNS_CACHE_TTL, is_private)
    return is_private


def validate_url(url: str) -> bool:
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
    if _dns_resolves_private(host):
        return False
    try:
        ip = ipaddress.ip_address(host)
        for net in _PRIVATE_SUBNETS:
            if ip in net:
                return False
    except ValueError:
        pass
    return True


def safe_fetch(url, timeout=10, max_size=5*1024*1024, headers=None):
    """HTTP GET with redirect validation and size limit."""
    if not validate_url(url):
        return None
    domain = urlparse(url).hostname or ""
    if not federation_allowed(domain):
        logger.info("Federation blocked for domain: %s", domain)
        return None
    client = httpx.Client(follow_redirects=True, timeout=timeout)
    original_send = client.send
    def _validated_send(request, **kwargs):
        if validate_url(str(request.url)):
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


def validated_get(url: str, headers: dict = None, timeout: int = 15, max_redirects: int = 5):
    """HTTP GET with SSRF-safe redirect validation."""
    if not validate_url(url):
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
            if not validate_url(url):
                logger.warning("SSRF blocked redirect to %s", url)
                return None
            resp = client.get(url, headers=headers or {})
        return resp
    except Exception:
        return None
    finally:
        client.close()
