"""Account alias helpers for ActivityPub account migration (alsoKnownAs / Move).

Aliases are stored as handles (e.g. "user@mastodon.social") by the settings UI.
These helpers turn a handle into the actor URI(s) the remote server uses, so we
can advertise them via `alsoKnownAs` and verify incoming/outgoing Move activities.
"""
import logging
import time

import httpx

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, list[str]]] = {}
_TTL = 24 * 3600


def _webfinger_actor_urls(handle: str, domain: str) -> list[str]:
    try:
        wf = httpx.get(
            f"https://{domain}/.well-known/webfinger?resource=acct:{handle}",
            timeout=5,
        )
        if wf.status_code == 200:
            urls = []
            for link in wf.json().get("links", []):
                if link.get("rel") == "self":
                    href = link.get("href", "")
                    if isinstance(href, str) and href.startswith("http"):
                        urls.append(href)
            return urls
    except Exception as e:
        logger.debug("webfinger failed for %s: %s", handle, e)
    return []


def alias_to_actor_urls(alias: str) -> list[str]:
    """Resolve an account alias (handle or URL) to candidate actor URIs.

    Authoritative URL comes from WebFinger; common path patterns are included
    as fallback. Results are cached for 24h.
    """
    if not alias or not isinstance(alias, str):
        return []
    alias = alias.strip()
    if alias.startswith("http://") or alias.startswith("https://"):
        return [alias]
    clean = alias.lstrip("@")
    if "@" not in clean:
        return []
    name, domain = clean.split("@", 1)
    domain = domain.strip().lower().rstrip("/")
    if not name or not domain:
        return []
    key = clean.lower()
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < _TTL:
        return cached[1]

    urls = [
        f"https://{domain}/users/{name}",
        f"https://{domain}/@{name}",
    ]
    urls += _webfinger_actor_urls(clean, domain)

    seen: list[str] = []
    for u in urls:
        if u and u not in seen:
            seen.append(u)
    _cache[key] = (now, seen)
    return seen


def actor_urls_include(aliases: list[str], actor_url: str) -> bool:
    """Whether any stored alias resolves to the given actor URI.

    Comparison is case-insensitive and ignores a trailing slash.
    """
    if not aliases or not actor_url:
        return False
    target = actor_url.rstrip("/").lower()
    for a in aliases:
        for u in alias_to_actor_urls(a):
            if u.rstrip("/").lower() == target:
                return True
    return False
