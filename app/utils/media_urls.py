"""Media URLs embedded in post/episode HTML.

Uploaded editor images live in ``/uploads/media/...`` and are referenced from
HTML rather than ``media_attachments``. These helpers keep those references in
sync with the archive builder and the orphan-media cleanup worker.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from html import unescape

# <img src="...">, <video src="...">, <audio src="...">, <source src="...">
_SRC_RE = re.compile(
    r'(?P<prefix><(?:img|video|audio|source)\b[^>]*?\bsrc\s*=\s*["\'])(?P<url>[^"\']+)(?P<suffix>["\'])',
    re.IGNORECASE,
)

# Absolute or root-relative upload URLs. The host, if present, is validated by
# the storage backend before anything is read or protected from cleanup.
_UPLOAD_URL_RE = re.compile(
    r'(?:https?://[^\s"\'<>]+?)?/uploads/[^\s"\'<>()]+',
    re.IGNORECASE,
)


def iter_upload_urls(value: str | None) -> Iterator[str]:
    """Yield raw upload URLs found anywhere in a piece of HTML/text."""
    if not value:
        return
    for match in _UPLOAD_URL_RE.finditer(value):
        url = unescape(match.group(0)).rstrip(".,;:!?")
        if url:
            yield url


def rewrite_src_urls(value: str | None, rewrite: Callable[[str], str | None]) -> str:
    """Rewrite ``src`` attributes, keeping the original when rewrite returns None."""
    if not value:
        return value or ""

    def replace(match: re.Match[str]) -> str:
        original = unescape(match.group("url"))
        updated = rewrite(original)
        return f"{match.group('prefix')}{updated or match.group('url')}{match.group('suffix')}"

    return _SRC_RE.sub(replace, value)
