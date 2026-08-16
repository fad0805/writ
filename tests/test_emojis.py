"""Custom emoji list endpoint tests.

The admin emoji tab filters by category: "" = 전체(all), "local", "remote".
Regression: "all" used to exclude remote emojis because an empty category
matched the `!= "remote"` branch.
"""

from app.db.database import get_session
from app.models import CustomEmoji


def _add_emoji(keyword, category="", domain=""):
    with get_session() as s:
        e = CustomEmoji(keyword=keyword, file_name=f"{keyword}.webp", category=category, domain=domain)
        s.add(e)
        s.commit()
        return e.id


def _fetch(client, category):
    r = client.get(f"/api/emojis?limit=100&offset=0&category={category}")
    assert r.status_code == 200
    return [e["keyword"] for e in r.json()["emojis"]]


def test_all_includes_local_and_remote(client):
    _add_emoji("local1", category="기본")
    _add_emoji("remote1", category="remote", domain="remote.example")
    assert set(_fetch(client, "")) == {"local1", "remote1"}


def test_local_excludes_remote(client):
    _add_emoji("local1", category="기본")
    _add_emoji("remote1", category="remote", domain="remote.example")
    assert _fetch(client, "local") == ["local1"]


def test_remote_returns_only_remote(client):
    _add_emoji("local1", category="기본")
    _add_emoji("remote1", category="remote", domain="remote.example")
    assert _fetch(client, "remote") == ["remote1"]
