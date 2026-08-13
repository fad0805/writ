"""End-to-end regression tests for DM thread privacy (commit 410dda2).

Direct messages are posts with visibility="mention" whose participants are
recorded in mentioned_user_ids. Thread/conversation listings match those JSON
arrays with _json_array_has_user; before the fix the %2% LIKE also matched
12/20/120, so a user could see other people's conversations.
"""
from app.db.database import get_session
from app.models import Post

_counter = [0]


def _dm(session, author, target, content):
    _counter[0] += 1
    n = _counter[0]
    post = Post(
        author_id=author.id,
        content=f"<p>{content}</p>",
        summary="",
        visibility="mention",
        is_dm=True,
        mentioned_user_ids=[target.id],
        number=f"n{n}",
        ap_id=f"http://localhost:3000/@x/{n}",
        is_deleted=False,
    )
    session.add(post)
    session.commit()
    session.refresh(post)
    return post


def _thread_handles(resp):
    return [u["username"] for u in resp["users"]]


def _conversation_ids(resp):
    return [m["id"] for m in resp["messages"]]


def test_conversation_only_shows_participants(client, make_user, auth_cookie):
    alice, alice_cookie = auth_cookie("alice")
    bob = make_user("bob")
    carol = make_user("carol")

    with get_session() as s:
        ab = _dm(s, alice, bob, "hey bob")
        ba = _dm(s, bob, alice, "hi alice")
        ac = _dm(s, alice, carol, "psst carol")

    resp = client.get(f"/api/direct/conversation/{bob.id}", cookies=alice_cookie)
    assert resp.status_code == 200
    # carol's DM (mentioned_user_ids=[carol.id]) must never leak into alice<->bob
    assert _conversation_ids(resp.json()) == [ab.id, ba.id]

    resp = client.get(f"/api/direct/conversation/{carol.id}", cookies=alice_cookie)
    assert _conversation_ids(resp.json()) == [ac.id]


def test_direct_threads_do_not_leak_other_conversations(client, make_user, auth_cookie):
    # alice's id must not pick up bob<->carol via %2% LIKE (12/20/120 family)
    alice, alice_cookie = auth_cookie("alice")
    bob = make_user("bob")
    carol = make_user("carol")

    with get_session() as s:
        _dm(s, bob, carol, "private bob-carol message")

    resp = client.get("/api/notifications/direct-threads", cookies=alice_cookie)
    assert resp.status_code == 200
    assert resp.json()["users"] == []

    # once alice actually DMs bob, exactly one thread (bob) appears
    with get_session() as s:
        _dm(s, alice, bob, "hello bob")
    resp = client.get("/api/notifications/direct-threads", cookies=alice_cookie)
    assert _thread_handles(resp.json()) == ["bob"]


def test_direct_threads_group_both_directions(client, make_user, auth_cookie):
    alice, alice_cookie = auth_cookie("alice")
    bob = make_user("bob")

    with get_session() as s:
        _dm(s, alice, bob, "from alice")
        _dm(s, bob, alice, "from bob")

    resp = client.get("/api/notifications/direct-threads", cookies=alice_cookie)
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert len(users) == 1
    assert users[0]["username"] == "bob"
    # two previews, one from each direction
    assert len(users[0]["latest_previews"]) == 2
    previews = users[0]["latest_previews"]
    assert any(p["is_me"] for p in previews)
    assert any(not p["is_me"] for p in previews)


def test_direct_threads_exclude_unrelated_dms(client, make_user, auth_cookie):
    alice, alice_cookie = auth_cookie("alice")
    bob = make_user("bob")
    dave = make_user("dave")

    with get_session() as s:
        _dm(s, bob, dave, "bob to dave only")

    resp = client.get("/api/notifications/direct-threads", cookies=alice_cookie)
    assert resp.json()["users"] == []
