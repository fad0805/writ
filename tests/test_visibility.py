"""Server-side visibility enforcement tests.

The core privacy contract: a post is only visible to users allowed by its
visibility level, regardless of how it is accessed. This is the same class of
bug that previously leaked private/DM posts through streams and listings.
"""


def _get(client, post_id, cookies=None):
    return client.get(f"/api/posts/{post_id}", cookies=cookies)


def test_public_post_visible_to_anonymous(client, make_user, make_post):
    alice = make_user("alice")
    post = make_post(alice, visibility="public")
    r = _get(client, post.id)
    assert r.status_code == 200


def test_followers_post_hidden_from_stranger(client, auth_cookie, make_post):
    alice, _ = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    post = make_post(alice, visibility="followers")
    assert _get(client, post.id, bob_cookie).status_code == 403


def test_followers_post_visible_to_follower(client, auth_cookie, make_post, make_follow):
    alice, _ = auth_cookie("alice")
    bob, bob_cookie = auth_cookie("bob")
    post = make_post(alice, visibility="followers")
    make_follow(bob, alice)
    assert _get(client, post.id, bob_cookie).status_code == 200


def test_followers_post_visible_to_author(client, auth_cookie, make_post):
    alice, alice_cookie = auth_cookie("alice")
    post = make_post(alice, visibility="followers")
    assert _get(client, post.id, alice_cookie).status_code == 200


def test_mention_post_hidden_from_non_mentioned(client, auth_cookie, make_post):
    alice, _ = auth_cookie("alice")
    bob, bob_cookie = auth_cookie("bob")
    _carol, carol_cookie = auth_cookie("carol")
    post = make_post(alice, visibility="mention", mentioned_user_ids=[bob.id])
    assert _get(client, post.id, carol_cookie).status_code == 403
    assert _get(client, post.id, bob_cookie).status_code == 200


def test_followers_post_hidden_from_username_prefix(client, auth_cookie, make_post):
    """@alice2 수신자에게 보낸 글을 @alice가 볼 수 없어야 한다."""
    author, _ = auth_cookie("author")
    alice, alice_cookie = auth_cookie("alice")
    alice2, alice2_cookie = auth_cookie("alice2")
    post = make_post(
        author,
        visibility="followers",
        mentioned_user_ids=[alice2.id],
        content="<p>@alice2 only</p>",
    )
    assert _get(client, post.id, alice_cookie).status_code == 403
    assert _get(client, post.id, alice2_cookie).status_code == 200


def test_mention_post_hidden_from_username_prefix(client, auth_cookie, make_post):
    """본문에 @alice2가 있어도 실제 수신자가 아닌 @alice는 차단한다."""
    author, _ = auth_cookie("author")
    alice, alice_cookie = auth_cookie("alice")
    alice2, alice2_cookie = auth_cookie("alice2")
    post = make_post(
        author,
        visibility="mention",
        mentioned_user_ids=[alice2.id],
        is_dm=True,
        content="<p>@alice2 only</p>",
    )
    assert _get(client, post.id, alice_cookie).status_code == 403
    assert _get(client, post.id, alice2_cookie).status_code == 200


def test_mention_post_hidden_from_anonymous(client, make_user, make_post):
    alice = make_user("alice")
    bob = make_user("bob")
    post = make_post(alice, visibility="mention", mentioned_user_ids=[bob.id])
    assert _get(client, post.id).status_code == 403


def test_dm_post_hidden_from_non_participant(client, auth_cookie, make_post):
    alice, _ = auth_cookie("alice")
    bob, bob_cookie = auth_cookie("bob")
    _carol, carol_cookie = auth_cookie("carol")
    post = make_post(alice, visibility="mention", mentioned_user_ids=[bob.id], is_dm=True)
    assert _get(client, post.id, carol_cookie).status_code == 403
    assert _get(client, post.id, bob_cookie).status_code == 200


def test_deleted_post_not_visible(client, auth_cookie, make_post):
    alice, alice_cookie = auth_cookie("alice")
    post = make_post(alice, visibility="public", is_deleted=True)
    assert _get(client, post.id, alice_cookie).status_code == 404


def test_followers_post_does_not_appear_in_stranger_feed(client, auth_cookie, make_post):
    alice, _ = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    make_post(alice, visibility="followers", content="<p>private to followers</p>")
    r = client.get("/api/timeline/federated", cookies=bob_cookie)
    assert r.status_code == 200
    for post in r.json().get("posts", []):
        assert post["content"] != "<p>private to followers</p>"


def _masto_oauth_header():
    import secrets

    from app.db.database import get_session
    from app.models import MastodonAccessToken, MastodonApp

    token = secrets.token_urlsafe(24)
    with get_session() as s:
        app = s.query(MastodonApp).first()
        if not app:
            app = MastodonApp(client_name="test-app", client_id=secrets.token_urlsafe(24), client_secret=secrets.token_urlsafe(24))
            s.add(app)
            s.flush()
        s.add(MastodonAccessToken(access_token=token, app_id=app.id, scopes="read"))
        s.commit()
    return {"Authorization": f"Bearer {token}"}


def _masto_home(client, user):
    from app.db.database import get_session
    from app.models import MastodonAccessToken

    token = _masto_oauth_header()["Authorization"].split(" ")[1]
    with get_session() as s:
        s.query(MastodonAccessToken).filter_by(access_token=token).update({"user_id": user.id})
        s.commit()
    return client.get("/api/v1/timelines/home", headers={"Authorization": f"Bearer {token}"})


def _masto_context(client, user, status_id):
    from app.db.database import get_session
    from app.models import MastodonAccessToken

    token = _masto_oauth_header()["Authorization"].split(" ")[1]
    with get_session() as s:
        s.query(MastodonAccessToken).filter_by(access_token=token).update({"user_id": user.id})
        s.commit()
    return client.get(
        f"/api/v1/statuses/{status_id}/context",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_mastodon_home_timeline_includes_mentioned_dm(client, auth_cookie, make_post):
    alice, _ = auth_cookie("alice")
    bob, _ = auth_cookie("bob")
    # 팔로우 관계 없이도 alice→bob DM이 bob의 홈 타임라인에 보여야 한다
    dm = make_post(alice, visibility="mention", mentioned_user_ids=[bob.id], is_dm=True,
                   content="<p>DM to bob</p>")
    r = _masto_home(client, bob)
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert str(dm.id) in ids
    # direct visibility로 변환되어야 한다
    status = next(s for s in r.json() if s["id"] == str(dm.id))
    assert status["visibility"] == "direct"


def test_mastodon_home_timeline_hides_dm_for_non_participant(client, auth_cookie, make_post):
    alice, _ = auth_cookie("alice")
    bob, _ = auth_cookie("bob")
    carol, _ = auth_cookie("carol")
    dm = make_post(alice, visibility="mention", mentioned_user_ids=[carol.id], is_dm=True,
                   content="<p>DM to carol</p>")
    # bob은 alice가 만든 DM에 참여하지 않았으므로 보이면 안 된다
    r = _masto_home(client, bob)
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert str(dm.id) not in ids


def test_mastodon_context_hides_mention_post_from_username_prefix(client, auth_cookie, make_post):
    """스레드 조회도 @alice에게 @alice2 전용 답글을 노출하면 안 된다."""
    author, _ = auth_cookie("author")
    alice, _ = auth_cookie("alice")
    alice2, _ = auth_cookie("alice2")
    root = make_post(author, visibility="public", content="<p>root</p>")
    reply = make_post(
        author,
        visibility="mention",
        mentioned_user_ids=[alice2.id],
        is_dm=True,
        content="<p>@alice2 private reply</p>",
        parent=root,
    )

    r = _masto_context(client, alice, root.id)
    assert r.status_code == 200
    assert str(reply.id) not in [s["id"] for s in r.json()["descendants"]]

    r = _masto_context(client, alice2, root.id)
    assert r.status_code == 200
    assert str(reply.id) in [s["id"] for s in r.json()["descendants"]]
