"""Mastodon OAuth scope definitions and helpers.

The scope list follows Mastodon's application registration UI.  A top-level
scope (``read``, ``write``, ``admin:read``, ``admin:write``) implies all of its
granular children, so the helpers below normalize stored scopes and check
whether a token may perform an operation.
"""

from __future__ import annotations

import re

# Top-level scope -> granular children shown in Mastodon's app creation form.
SCOPE_GROUPS: dict[str, tuple[str, ...]] = {
    "read": (
        "read:accounts",
        "read:blocks",
        "read:bookmarks",
        "read:collections",
        "read:favourites",
        "read:filters",
        "read:follows",
        "read:lists",
        "read:mutes",
        "read:notifications",
        "read:search",
        "read:statuses",
    ),
    "write": (
        "write:accounts",
        "write:blocks",
        "write:bookmarks",
        "write:collections",
        "write:conversations",
        "write:favourites",
        "write:filters",
        "write:follows",
        "write:lists",
        "write:media",
        "write:mutes",
        "write:notifications",
        "write:reports",
        "write:statuses",
    ),
    "admin:read": (
        "admin:read:accounts",
        "admin:read:canonical_email_blocks",
        "admin:read:domain_allows",
        "admin:read:domain_blocks",
        "admin:read:email_domain_blocks",
        "admin:read:ip_blocks",
        "admin:read:reports",
    ),
    "admin:write": (
        "admin:write:accounts",
        "admin:write:canonical_email_blocks",
        "admin:write:domain_allows",
        "admin:write:domain_blocks",
        "admin:write:email_domain_blocks",
        "admin:write:ip_blocks",
        "admin:write:reports",
    ),
}

# Scopes that do not have granular children in the registration UI.
STANDALONE_SCOPES: tuple[str, ...] = ("profile", "follow", "push")

ALL_SCOPES: frozenset[str] = frozenset(
    {scope for scope, children in SCOPE_GROUPS.items() for scope in (scope, *children)}
    | set(STANDALONE_SCOPES)
)

_PARENT_SCOPES = tuple(SCOPE_GROUPS)


def parse_scopes(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Split a scope string/list into unique, whitespace-free scope names."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.split()
    else:
        parts = []
        for item in raw:
            if isinstance(item, str):
                parts.extend(item.split())
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            result.append(part)
    return result


def normalize_scopes(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Validate scopes and remove granular children implied by a parent scope.

    Raises ``ValueError`` for unknown scope names.
    """
    scopes = parse_scopes(raw)
    unknown = [scope for scope in scopes if scope not in ALL_SCOPES]
    if unknown:
        raise ValueError(f"Unknown scope(s): {', '.join(unknown)}")

    # If a top-level scope is present, its children are redundant.
    for parent, children in SCOPE_GROUPS.items():
        if parent in scopes:
            scopes = [scope for scope in scopes if scope not in children]

    return scopes


def scopes_to_string(scopes: str | list[str] | tuple[str, ...] | None) -> str:
    return " ".join(normalize_scopes(scopes))


def has_admin_scope(scopes: str | list[str] | tuple[str, ...] | None) -> bool:
    """Return whether any admin scope is present."""
    return any(scope.startswith("admin:") for scope in parse_scopes(scopes))


def _parent_of(scope: str) -> str | None:
    if scope.startswith("admin:read:"):
        return "admin:read"
    if scope.startswith("admin:write:"):
        return "admin:write"
    if scope.startswith("read:"):
        return "read"
    if scope.startswith("write:"):
        return "write"
    return None


def scope_allowed(granted: str | list[str] | tuple[str, ...] | None, required: str) -> bool:
    """Return whether ``granted`` scopes allow an operation requiring ``required``."""
    scopes = set(parse_scopes(granted))
    if required in scopes:
        return True

    parent = _parent_of(required)
    if parent and parent in scopes:
        return True

    # ``profile`` is the minimal scope for reading the authenticated account.
    # A normal read token may do that too.
    if required == "profile" and "read" in scopes:
        return True

    # Mastodon's top-level ``follow`` covers relationship mutations.  Granular
    # write scopes can also be used for the corresponding operation.
    if required == "follow" and "write:follows" in scopes:
        return True
    if required == "write:mutes" and ("follow" in scopes or "write" in scopes):
        return True
    return required == "write:blocks" and ("follow" in scopes or "write" in scopes)


def required_scope_for_request(method: str, path: str) -> str | None:
    """Best-effort scope requirement for a Mastodon API route.

    Public endpoints use ``_maybe_bearer`` and never reach this helper.  The
    mapping is deliberately coarse where Mastodon has several equivalent
    granular scopes; a top-level ``read``/``write`` token always works.
    """
    if path.startswith("/api/"):
        path = path[4:]
    method = method.upper()

    if path.startswith(("/v1/push", "/v2/push")):
        return "push"
    if path.startswith(("/v1/admin", "/v2/admin")):
        return "admin:write" if method not in ("GET", "HEAD") else "admin:read"

    if path == "/v1/accounts/verify_credentials":
        return "profile"
    if path.startswith("/v1/accounts"):
        if path.endswith(("/follow", "/unfollow")):
            return "follow"
        if path.endswith(("/mute", "/unmute")):
            return "write:mutes"
        if path.endswith(("/block", "/unblock")):
            return "write:blocks"
        if method in ("GET", "HEAD"):
            if path.endswith(("/followers", "/following", "/relationships")):
                return "read:follows"
            if path.endswith("/statuses"):
                return "read:statuses"
            return "read:accounts"
        return "write:accounts"

    if path.startswith(("/v1/statuses", "/v2/statuses")):
        if re.search(r"/(favourite|unfavourite)$", path):
            return "write:favourites"
        if re.search(r"/(reblog|unreblog)$", path):
            return "write:statuses"
        if re.search(r"/(bookmark|unbookmark)$", path):
            return "write:bookmarks"
        if re.search(r"/(react|unreact)/", path):
            return "write:favourites"
        if re.search(r"/(mute|unmute)$", path):
            return "write:mutes"
        if re.search(r"/(pin|unpin)$", path):
            return "write:statuses"
        if method in ("GET", "HEAD"):
            return "read:statuses"
        return "write:statuses"

    if path.startswith(("/v1/media", "/v2/media")):
        return "write:media"
    if path.startswith("/v1/notifications"):
        return "read:notifications" if method in ("GET", "HEAD") else "write:notifications"
    if path.startswith(("/v1/filters", "/v2/filters")):
        return "read:filters" if method in ("GET", "HEAD") else "write:filters"
    if path.startswith("/v1/bookmarks"):
        return "read:bookmarks"
    if path.startswith("/v1/favourites"):
        return "read:favourites"
    if path.startswith("/v1/blocks"):
        return "read:blocks"
    if path.startswith("/v1/mutes"):
        return "read:mutes"
    if path.startswith("/v1/follow_requests"):
        return "read:follows"
    if path.startswith("/v1/lists"):
        return "read:lists"
    if path.startswith("/v1/conversations"):
        return "read:conversations"
    if path.startswith("/v1/timelines/home"):
        return "read:statuses"
    if path.startswith(("/v1/search", "/v2/search")):
        return "read:search"
    if path.startswith("/v1/polls"):
        return "read:statuses" if method in ("GET", "HEAD") else "write:statuses"
    if path.startswith("/v1/markers"):
        return "read" if method in ("GET", "HEAD") else "write"
    if path.startswith("/v1/preferences"):
        return "read"
    if path.startswith("/v1/followed_tags"):
        return "read:follows"
    if path.startswith("/v1/domain_blocks"):
        return "read:blocks"
    if path.startswith("/v1/endorsements"):
        return "read:accounts"
    if path.startswith("/v1/scheduled_statuses"):
        return "read"
    if path.startswith("/v1/suggestions"):
        return "read"
    if path.startswith("/v1/featured_tags"):
        return "read"

    return "read" if method in ("GET", "HEAD", "OPTIONS") else "write"
