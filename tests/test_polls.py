"""Poll voting tests."""

from app.db.database import get_session
from app.models import Vote


def _poll_data():
    return {
        "options": [
            {"text": "Option A", "votes_count": 0},
            {"text": "Option B", "votes_count": 0},
        ],
        "expires_at": None,
    }


def test_vote_on_poll(client, auth_cookie, make_post):
    alice, _alice_cookie = auth_cookie("alice")
    bob, bob_cookie = auth_cookie("bob")
    post = make_post(alice, poll_data=_poll_data())
    r = client.post(f"/api/posts/{post.id}/vote", data={"option": "0"}, cookies=bob_cookie)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    with get_session() as s:
        vote = s.query(Vote).filter_by(user_id=bob.id, post_id=post.id).first()
        assert vote is not None
        assert vote.option_index == 0


def test_vote_changes_option(client, auth_cookie, make_post):
    alice, _alice_cookie = auth_cookie("alice")
    bob, bob_cookie = auth_cookie("bob")
    post = make_post(alice, poll_data=_poll_data())
    client.post(f"/api/posts/{post.id}/vote", data={"option": "0"}, cookies=bob_cookie)
    r = client.post(f"/api/posts/{post.id}/vote", data={"option": "1"}, cookies=bob_cookie)
    assert r.status_code == 200
    with get_session() as s:
        vote = s.query(Vote).filter_by(user_id=bob.id, post_id=post.id).first()
        assert vote.option_index == 1


def test_vote_invalid_option(client, auth_cookie, make_post):
    alice, _alice_cookie = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    post = make_post(alice, poll_data=_poll_data())
    r = client.post(f"/api/posts/{post.id}/vote", data={"option": "5"}, cookies=bob_cookie)
    assert r.status_code == 400


def test_vote_on_non_poll_post(client, auth_cookie, make_post):
    alice, _alice_cookie = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    post = make_post(alice, content="<p>no poll here</p>")
    assert client.post(f"/api/posts/{post.id}/vote", data={"option": "0"}, cookies=bob_cookie).status_code == 404


def test_vote_requires_auth(client, make_user, make_post):
    alice = make_user("alice")
    post = make_post(alice, poll_data=_poll_data())
    assert client.post(f"/api/posts/{post.id}/vote", data={"option": "0"}).status_code == 401


def test_unvote(client, auth_cookie, make_post):
    alice, _alice_cookie = auth_cookie("alice")
    bob, bob_cookie = auth_cookie("bob")
    post = make_post(alice, poll_data=_poll_data())
    client.post(f"/api/posts/{post.id}/vote", data={"option": "0"}, cookies=bob_cookie)
    r = client.post(f"/api/posts/{post.id}/unvote", cookies=bob_cookie)
    assert r.status_code == 200
    with get_session() as s:
        assert s.query(Vote).filter_by(user_id=bob.id, post_id=post.id).first() is None
