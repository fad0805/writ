import re


def parse_username_from_url(url: str) -> str:
    url = url.rstrip("/")
    match = re.search(r'/(?:users/)?@?([\w.\-]+)$', url)
    if match:
        return match.group(1)
    return url.split("/")[-1]


def extract_remote_url(obj: dict, fallback: str = "") -> str:
    """Extract the human-facing web URL from a remote AP object.

    Mastodon: url="https://host/@user/123" vs id=".../users/user/statuses/123"
    Misskey:  url == id (".../notes/xxx")
    kos.moe:  url="https://host/@user/xxx" vs id=".../ap/note/uuid"
    """
    raw = obj.get("url", "")
    if isinstance(raw, str) and raw.startswith("http"):
        return raw
    if isinstance(raw, dict):
        href = raw.get("href", "") or raw.get("url", "")
        if href.startswith("http"):
            return href
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.startswith("http"):
                return item
            if isinstance(item, dict):
                href = item.get("href", "") or item.get("url", "")
                if href.startswith("http"):
                    return href
    return fallback
