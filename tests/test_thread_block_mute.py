"""스레드(포스트 상세)에서 차단/뮤트 상대의 답글·부모 숨김 검증."""

from app.core.relationship import block_user, mute_user
from app.db.database import get_session


def _thread(client, post_id, cookie):
    return client.get(f"/api/posts/{post_id}", cookies=cookie)


def test_blocked_author_reply_hidden_from_thread(client, auth_cookie, make_post):
    """내가 차단한 유저의 답글은 스레드 replies에서 숨겨져야 한다."""
    me, me_cookie = auth_cookie("alice")
    blocker_target, _c = auth_cookie("bob")
    root = make_post(me, content="<p>root</p>")
    reply = make_post(blocker_target, content="<p>blocked reply</p>", parent=root)

    with get_session() as s:
        block_user(s, me, blocker_target)

    r = _thread(client, root.id, me_cookie)
    assert r.status_code == 200
    reply_ids = [p["id"] for p in r.json()["replies"]]
    assert reply.id not in reply_ids


def test_blocked_author_ancestor_hidden_from_thread(client, auth_cookie, make_post):
    """나를 차단한 유저의 부모 글은 스레드 ancestors에서 숨겨져야 한다."""
    me, me_cookie = auth_cookie("alice")
    blocker, _c = auth_cookie("bob")
    parent = make_post(blocker, content="<p>parent by blocker</p>")
    child = make_post(me, content="<p>my reply</p>", parent=parent)

    # 반대로: parent 작성자가 나(me)를 차단한 상황
    with get_session() as s:
        block_user(s, blocker, me)

    r = _thread(client, child.id, me_cookie)
    assert r.status_code == 200
    anc_ids = [p["id"] for p in r.json()["ancestors"]]
    assert parent.id not in anc_ids


def test_muted_author_reply_hidden_from_thread(client, auth_cookie, make_post):
    """내가 뮤트한 유저의 답글은 스레드 replies에서 숨겨져야 한다."""
    me, me_cookie = auth_cookie("alice")
    muted, _c = auth_cookie("carol")
    root = make_post(me, content="<p>root</p>")
    reply = make_post(muted, content="<p>muted reply</p>", parent=root)

    with get_session() as s:
        mute_user(s, me, muted)

    r = _thread(client, root.id, me_cookie)
    assert r.status_code == 200
    reply_ids = [p["id"] for p in r.json()["replies"]]
    assert reply.id not in reply_ids


def test_own_reply_visible_even_when_self_blocked(client, auth_cookie, make_post):
    """내가 차단 대상인 상대 스레드에서도, 내 답글은 항상 보여야 한다."""
    me, me_cookie = auth_cookie("alice")
    root_author, _c = auth_cookie("bob")
    root = make_post(root_author, content="<p>root</p>")
    my_reply = make_post(me, content="<p>my own reply</p>", parent=root)

    # root 작성자(bob)가 나(alice)를 차단
    with get_session() as s:
        block_user(s, root_author, me)

    r = _thread(client, root.id, me_cookie)
    assert r.status_code == 200
    reply_ids = [p["id"] for p in r.json()["replies"]]
    assert my_reply.id in reply_ids


def test_unrelated_reply_visible(client, auth_cookie, make_post):
    """차단/뮤트 없으면 답글은 정상 노출되어야 한다."""
    me, me_cookie = auth_cookie("alice")
    other, _c = auth_cookie("carol")
    root = make_post(me, content="<p>root</p>")
    reply = make_post(other, content="<p>normal reply</p>", parent=root)

    r = _thread(client, root.id, me_cookie)
    assert r.status_code == 200
    reply_ids = [p["id"] for p in r.json()["replies"]]
    assert reply.id in reply_ids
