"""스레드(포스트 상세)에서 차단/뮤트 상대의 답글·부모 숨김 검증."""

import json
from unittest.mock import patch

import pytest

from app.core.broadcast import broadcast_post
from app.core.relationship import block_user, mute_user
from app.core.timeline_stream import _streams
from app.db.database import get_session
from app.models import Post


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
    """나를 차단한 상대의 루트 글은 404로 숨겨지지만, 내 답글은 상세 주소로 항상 보여야 한다."""
    me, me_cookie = auth_cookie("alice")
    root_author, _c = auth_cookie("bob")
    root = make_post(root_author, content="<p>root</p>")
    my_reply = make_post(me, content="<p>my own reply</p>", parent=root)

    # root 작성자(bob)가 나(alice)를 차단
    with get_session() as s:
        block_user(s, root_author, me)

    # 차단한 상대의 루트 글 상세는 숨김
    r_root = _thread(client, root.id, me_cookie)
    assert r_root.status_code == 404

    # 내 답글은 상세 주소로 접근 가능하며, 차단 상대의 부모는 ancestors에서 숨김
    r = _thread(client, my_reply.id, me_cookie)
    assert r.status_code == 200
    assert r.json()["id"] == my_reply.id
    anc_ids = [p["id"] for p in r.json()["ancestors"]]
    assert root.id not in anc_ids


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


def _set_quote(session, quote_post, qp):
    quote_post.quote_of_id = qp.id
    quote_post.quote_of_ap_id = qp.ap_id or ""
    session.commit()
    session.refresh(quote_post)


def test_blocked_author_quote_hidden_with_link(client, auth_cookie, make_post):
    """내가 차단한 유저의 글이 인용되면 quoted_post가 비워지고 링크만 노출된다."""
    me, me_cookie = auth_cookie("alice")
    blocker_target, _c = auth_cookie("bob")
    quoter, _c = auth_cookie("carol")
    quoted = make_post(blocker_target, content="<p>blocked quote target</p>")
    quoting = make_post(quoter, content="<p>quoting post</p>")

    with get_session() as s:
        block_user(s, me, blocker_target)
        _set_quote(s, s.query(Post).filter_by(id=quoting.id).one(), quoted)

    r = client.get(f"/api/posts/{quoting.id}", cookies=me_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["quote_hidden"] is True
    assert body["quoted_post"] is None
    assert body["quote_hidden_url"] == f"/post/{quoted.id}"


def test_muted_author_quote_hidden_with_link(client, auth_cookie, make_post):
    """내가 뮤트한 유저의 글이 인용되어도 본문은 숨겨지고 링크만 노출된다."""
    me, me_cookie = auth_cookie("alice")
    muted_target, _c = auth_cookie("bob")
    quoter, _c = auth_cookie("carol")
    quoted = make_post(muted_target, content="<p>muted quote target</p>")
    quoting = make_post(quoter, content="<p>quoting post</p>")

    with get_session() as s:
        mute_user(s, me, muted_target)
        _set_quote(s, s.query(Post).filter_by(id=quoting.id).one(), quoted)

    r = client.get(f"/api/posts/{quoting.id}", cookies=me_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["quote_hidden"] is True
    assert body["quoted_post"] is None


def test_followed_author_quote_contents_visible(client, auth_cookie, make_post):
    """차단/뮤트 대상이 아닌 인용글은 기존대로 본문이 노출된다."""
    _me, me_cookie = auth_cookie("alice")
    target, _c = auth_cookie("bob")
    quoter, _c = auth_cookie("carol")
    quoted = make_post(target, content="<p>normal quote target</p>")
    quoting = make_post(quoter, content="<p>quoting post</p>")

    with get_session() as s:
        _set_quote(s, s.query(Post).filter_by(id=quoting.id).one(), quoted)

    r = client.get(f"/api/posts/{quoting.id}", cookies=me_cookie)
    assert r.status_code == 200
    body = r.json()
    assert body["quote_hidden"] is False
    assert body["quoted_post"] is not None
    assert body["quoted_post"]["id"] == quoted.id


def test_blocked_author_post_hidden_on_detail_url(client, auth_cookie, make_post):
    """내가 차단한 유저의 글은 상세 주소로 들어가도 404로 숨겨져야 한다."""
    me, me_cookie = auth_cookie("alice")
    blocker_target, _c = auth_cookie("bob")
    post = make_post(blocker_target, content="<p>blocked post</p>")

    with get_session() as s:
        block_user(s, me, blocker_target)

    r = _thread(client, post.id, me_cookie)
    assert r.status_code == 404


def test_blocker_of_me_post_hidden_on_detail_url(client, auth_cookie, make_post):
    """나를 차단한 유저의 글도 상세 주소에서 404로 숨겨져야 한다."""
    me, me_cookie = auth_cookie("alice")
    blocker, _c = auth_cookie("bob")
    post = make_post(blocker, content="<p>blocker post</p>")

    with get_session() as s:
        block_user(s, blocker, me)

    r = _thread(client, post.id, me_cookie)
    assert r.status_code == 404


def test_muted_author_post_visible_on_detail_url(client, auth_cookie, make_post):
    """뮤트한 유저의 글은 상세 주소에서 여전히 볼 수 있어야 한다(뮤트 제외)."""
    me, me_cookie = auth_cookie("alice")
    muted_target, _c = auth_cookie("bob")
    post = make_post(muted_target, content="<p>muted post</p>")

    with get_session() as s:
        mute_user(s, me, muted_target)

    r = _thread(client, post.id, me_cookie)
    assert r.status_code == 200
    assert r.json()["id"] == post.id


def test_own_post_visible_when_blocked_by_author(client, auth_cookie, make_post):
    """내 글은 작성자가 나를 차단했더라도 상세 주소에서 보여야 한다."""
    me, me_cookie = auth_cookie("alice")
    blocker, _c = auth_cookie("bob")
    my_post = make_post(me, content="<p>my post</p>")

    with get_session() as s:
        block_user(s, blocker, me)

    r = _thread(client, my_post.id, me_cookie)
    assert r.status_code == 200
    assert r.json()["id"] == my_post.id


def test_blocked_author_post_hidden_on_by_number(client, auth_cookie, make_post):
    """차단한 유저의 글은 by-number 상세 주소로도 404로 숨겨져야 한다."""
    me, me_cookie = auth_cookie("alice")
    blocker_target, _c = auth_cookie("bob")
    post = make_post(blocker_target, content="<p>blocked post</p>")

    with get_session() as s:
        block_user(s, me, blocker_target)

    r = client.get(f"/api/by-number/{blocker_target.username}/{post.number}", cookies=me_cookie)
    assert r.status_code == 404


def _stream_quote_post_json(quoting, quoted, **overrides):
    payload = {
        "id": quoting.id,
        "number": quoting.number,
        "content": quoting.content,
        "summary": quoting.summary or "",
        "visibility": quoting.visibility,
        "created_at": quoting.created_at.isoformat(),
        "author": {
            "id": quoting.author_id,
            "username": "quoter",
            "display_name": "quoter",
        },
        "quote_of_id": quoted.id,
        "quote_of_ap_id": quoted.ap_id or "",
    }
    payload.update(overrides)
    return payload


def _capture_broadcast_payloads(post_json, author_id, visibility, streams):
    payloads: dict[object, dict] = {}
    saved = dict(_streams)
    _streams.clear()
    _streams.update(streams)
    try:
        with patch(
            "app.core.broadcast.delivery._enqueue",
            side_effect=lambda queue, payload: payloads.__setitem__(queue, json.loads(payload)),
        ):
            broadcast_post(post_json, author_id, visibility)
    finally:
        _streams.clear()
        _streams.update(saved)
    return payloads


@pytest.mark.parametrize("relationship", ["block", "mute"])
def test_streamed_quote_hidden_for_filtered_viewer(
        relationship, auth_cookie, make_post):
    """SSE로 들어온 글의 인용 작성자가 차단/뮤트 대상이면 숨김 플래그를 실어 보낸다."""
    me, _c = auth_cookie("alice")
    filtered, _c = auth_cookie("bob")
    quoter, _c = auth_cookie("carol")
    other, _c = auth_cookie("dave")
    quoted = make_post(filtered, content="<p>filtered quote</p>")
    quoting = make_post(quoter, content="<p>quoting post</p>")

    with get_session() as s:
        if relationship == "block":
            block_user(s, me, filtered)
        else:
            mute_user(s, me, filtered)
        _set_quote(s, s.query(Post).filter_by(id=quoting.id).one(), quoted)

    payloads = _capture_broadcast_payloads(
        _stream_quote_post_json(quoting, quoted),
        quoting.author_id,
        "public",
        {
            "me": {"queue": "me", "user_id": me.id, "tl_type": "local"},
            "other": {"queue": "other", "user_id": other.id, "tl_type": "local"},
        },
    )

    assert payloads["me"]["quote_hidden"] is True
    assert payloads["me"]["quoted_post"] is None
    assert payloads["me"]["quote_hidden_url"] == f"/post/{quoted.id}"
    # 필터 대상이 아닌 시청자에게는 숨김 처리를 하지 않는다.
    assert payloads["other"].get("quote_hidden", False) is False


def test_streamed_quote_unhidden_for_non_filtered_viewer(
        auth_cookie, make_post):
    """작성자 기준으로 숨겨진 페이로드라도 시청자가 차단/뮤트 대상이 아니면 인용을 연다."""
    viewer, _c = auth_cookie("alice")
    quoted_author, _c = auth_cookie("bob")
    quoter, _c = auth_cookie("carol")
    quoted = make_post(quoted_author, content="<p>quote</p>")
    quoting = make_post(quoter, content="<p>quoting post</p>")

    with get_session() as s:
        _set_quote(s, s.query(Post).filter_by(id=quoting.id).one(), quoted)

    payloads = _capture_broadcast_payloads(
        _stream_quote_post_json(
            quoting, quoted,
            quote_hidden=True,
            quote_hidden_url=f"/post/{quoted.id}",
            quoted_post=None,
        ),
        quoting.author_id,
        "public",
        {"viewer": {"queue": "viewer", "user_id": viewer.id, "tl_type": "local"}},
    )

    assert payloads["viewer"]["quote_hidden"] is False
    assert payloads["viewer"]["quote_hidden_url"] == ""
