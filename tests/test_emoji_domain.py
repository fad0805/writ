"""같은 shortcode를 쓰는 서버 간 이모지 충돌 회귀 테스트."""

import datetime

from app.db.database import get_session
from app.models import CustomEmoji, Like, User
from app.utils.crypto import generate_keypair
from app.utils.emoji import _refresh_emoji_cache_forcibly, emoji_keywords_in_text


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


def test_emoji_keywords_in_text_only_extracts_shortcodes():
    assert emoji_keywords_in_text("hi :wave: and :A_B:") == {"wave", "a_b"}
    assert emoji_keywords_in_text("no emoji :not valid:") == set()
    assert emoji_keywords_in_text("") == set()


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
        s.add(Like(user_id=kitsune.id, post_id=p_kitsune.id, reaction=f":{kw}:", reaction_domain="kitsunesoba.com"))
        s.add(Like(user_id=dream.id, post_id=p_dream.id, reaction=f":{kw}:", reaction_domain="daydream.ink"))
        # 같은 글에 두 서버가 같은 shortcode로 리액션한 경우 배지가 분리되어야 한다.
        s.add(Like(user_id=kitsune.id, post_id=p_dream.id, reaction=f":{kw}:", reaction_domain="kitsunesoba.com"))
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

    kitsune_key = f":{kw}:@kitsunesoba.com"
    dream_key = f":{kw}:@daydream.ink"
    assert posts[p_kitsune.id]["reactions"] == {kitsune_key: 1}
    assert posts[p_dream.id]["reactions"] == {dream_key: 1, kitsune_key: 1}
    assert "kitsune.png" in posts[p_kitsune.id]["_reaction_emojis"][kitsune_key]
    assert "kitsune.png" in posts[p_dream.id]["_reaction_emojis"][kitsune_key]
    assert "daydream.png" in posts[p_dream.id]["_reaction_emojis"][dream_key]

    # 도메인별 배지 툴팁도 출처에 맞는 사용자만 보여줘야 한다.
    for _key, domain, expected in (
        (kitsune_key, "kitsunesoba.com", "villain"),
        (dream_key, "daydream.ink", "dreamer"),
    ):
        r = client.get(
            f"/api/posts/{p_dream.id}/reaction-users",
            params={"emoji": f":{kw}:", "domain": domain},
            cookies=cookies,
        )
        assert r.status_code == 200
        users = r.json()["users"]
        assert len(users) == 1
        assert users[0]["username"].startswith(expected)
