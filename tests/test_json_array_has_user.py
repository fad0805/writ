"""Regression tests for _json_array_has_user SQLite fallback (DM thread privacy).

The old implementation used ``%{uid}%`` LIKE which matched ``2`` inside ``12``,
``20`` and ``120``, leaking other users' DM threads into a conversation listing.
The boundary-based fallback in _common.py must only match exact JSON array
elements.
"""
from app.db.database import get_session
from app.models import Post
from app.routes.api.interactions._common import _json_array_has_user


def _matching_ids(uid, arrays):
    """Return which arrays contain uid according to the query helper."""
    hits = []
    with get_session() as s:
        s.query(Post).delete()
        s.commit()
        for arr in arrays:
            post = Post(
                author_id=1,
                content="<p>x</p>",
                visibility="mention",
                mentioned_user_ids=arr,
                number=f"n{len(arr)}",
            )
            s.add(post)
        s.commit()
        for post in s.query(Post).all():
            q = s.query(Post).filter(
                Post.id == post.id,
                _json_array_has_user(Post.mentioned_user_ids, uid),
            )
            if q.first() is not None:
                hits.append(post.mentioned_user_ids)
    return hits


def test_uid_matches_when_present_in_any_position():
    assert [2] in _matching_ids(2, [[2], [2, 5], [1, 2, 5], [1, 2]])


def test_uid_does_not_match_similar_larger_numbers():
    # 2 must NOT match 12, 20, 120 or any array containing only those
    arrays = [[12], [20], [120], [1, 20, 120], [12, 20], [120, 12, 20]]
    assert _matching_ids(2, arrays) == []


def test_empty_array_never_matches():
    assert _matching_ids(2, [[]]) == []


def test_boundaries_apply_to_other_digits_too():
    # uid 12 matches [12] and [1, 12, 20], but not [2] or [120]
    assert _matching_ids(12, [[12], [1, 12, 20]]) == [[12], [1, 12, 20]]
    assert _matching_ids(12, [[2], [120], [1, 2]]) == []


def test_uid_one_matches_only_itself():
    assert _matching_ids(1, [[1], [12]]) == [[1]]
