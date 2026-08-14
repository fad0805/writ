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
    bob, bob_cookie = auth_cookie("bob")
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
    carol, carol_cookie = auth_cookie("carol")
    post = make_post(alice, visibility="mention", mentioned_user_ids=[bob.id])
    assert _get(client, post.id, carol_cookie).status_code == 403
    assert _get(client, post.id, bob_cookie).status_code == 200


def test_mention_post_hidden_from_anonymous(client, make_user, make_post):
    alice = make_user("alice")
    bob = make_user("bob")
    post = make_post(alice, visibility="mention", mentioned_user_ids=[bob.id])
    assert _get(client, post.id).status_code == 403


def test_dm_post_hidden_from_non_participant(client, auth_cookie, make_post):
    alice, _ = auth_cookie("alice")
    bob, bob_cookie = auth_cookie("bob")
    carol, carol_cookie = auth_cookie("carol")
    post = make_post(alice, visibility="mention", mentioned_user_ids=[bob.id], is_dm=True)
    assert _get(client, post.id, carol_cookie).status_code == 403
    assert _get(client, post.id, bob_cookie).status_code == 200


def test_deleted_post_not_visible(client, auth_cookie, make_post):
    alice, alice_cookie = auth_cookie("alice")
    post = make_post(alice, visibility="public", is_deleted=True)
    assert _get(client, post.id, alice_cookie).status_code == 404


def test_followers_post_does_not_appear_in_stranger_feed(client, auth_cookie, make_post):
    alice, _ = auth_cookie("alice")
    bob, bob_cookie = auth_cookie("bob")
    make_post(alice, visibility="followers", content="<p>private to followers</p>")
    r = client.get("/api/timeline/federated", cookies=bob_cookie)
    assert r.status_code == 200
    for post in r.json().get("posts", []):
        assert post["content"] != "<p>private to followers</p>"
