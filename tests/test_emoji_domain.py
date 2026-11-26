"""같은 shortcode를 쓰는 서버 간 이모지 충돌 회귀 테스트."""

import datetime

from app.db.database import get_session
from app.models import CustomEmoji, Like, User
from app.utils.crypto import generate_keypair
from app.utils.emoji import _refresh_emoji_cache_forcibly


def _remote_user(username: str, domain: str):
    priv, pub = generate_keypair()
    with get_session() as s:
        u = User(
            username=f"{username}@{domain}",
            display_name=f"{username}@{domain}",
            email=f"{username}@{domain}",
            password_hash="remote",
            private_key=priv,
            public_key=pub,
            is_remote=True,
            remote_url=f"https://{domain}/users/{username}",
            inbox_url=f"https://{domain}/users/{username}/inbox",
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        return u


def _emoji(keyword: str, domain: str, file_name: str, created_at: datetime.datetime):
    with get_session() as s:
        e = CustomEmoji(
            keyword=keyword,
            file_name=file_name,
            category="remote",
            domain=domain,
            created_at=created_at,
        )
        s.add(e)
        s.commit()
        return e


def test_timeline_posts_use_authors_domain_emoji(client, auth_cookie, make_post):
    _viewer, cookies = auth_cookie("viewer")
    kitsune = _remote_user("villain", "kitsunesoba.com")
    dream = _remote_user("dreamer", "daydream.ink")
    kw = "ablobcat_frustration"
    # 전역 목록(최신순)에서는 daydream.ink 쪽이 먼저 나오도록 한다.
    _emoji(kw, "kitsunesoba.com", "kitsune.png", datetime.datetime(2026, 1, 1))
    _emoji(kw, "daydream.ink", "daydream.png", datetime.datetime(2026, 2, 1))
    with get_session() as s:
        _refresh_emoji_cache_forcibly(s)
    p_kitsune = make_post(kitsune, content=f":{kw}:")
    p_dream = make_post(dream, content=f":{kw}:")
    with get_session() as s:
        s.add(Like(user_id=kitsune.id, post_id=p_kitsune.id, reaction=f":{kw}:"))
        s.add(Like(user_id=dream.id, post_id=p_dream.id, reaction=f":{kw}:"))
        s.commit()

    res = client.get("/api/timeline/federated?limit=20", cookies=cookies)
    assert res.status_code == 200
    posts = {p["id"]: p for p in res.json()["posts"]}

    def _url(post):
        matches = [e for e in posts[post.id]["_emojis"] if e["keyword"] == kw]
        assert len(matches) == 1
        return matches[0]["url"]

    assert "kitsune.png" in _url(p_kitsune)
    assert "daydream.png" in _url(p_dream)

    def _reaction_url(post):
        assert kw in posts[post.id]["_reaction_emojis"]
        return posts[post.id]["_reaction_emojis"][kw]

    assert "kitsune.png" in _reaction_url(p_kitsune)
    assert "daydream.png" in _reaction_url(p_dream)
