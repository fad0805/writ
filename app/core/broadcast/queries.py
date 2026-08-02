from sqlalchemy.orm import Session

from app.models import Post, Follow, User


def _load_follower_ids(session: Session, author_id: int) -> set[int]:
    return {f.follower_id for f in session.query(Follow).filter_by(
        following_id=author_id, accepted=True
    ).all()}


def _load_author_is_local(session: Session, author_id: int) -> bool:
    author = session.query(User).get(author_id)
    return author.is_remote == False if author else False


def _load_stream_users(session: Session, streams: dict[int, dict]) -> tuple[set[int], dict[int, User]]:
    home_uids = set()
    all_stream_uids = set()

    for info in streams.values():
        uid = info.get("user_id")
        if uid:
            all_stream_uids.add(uid)
            if info.get("tl_type") in ("home", "social"):
                home_uids.add(uid)

    stream_users = {}
    if all_stream_uids:
        for u in session.query(User).filter(User.id.in_(all_stream_uids)).all():
            stream_users[u.id] = u

    return home_uids, stream_users


def _load_home_follow_map(session: Session, home_uids: set[int]) -> dict[int, set[int]]:
    home_follows = {}
    if home_uids:
        for f in session.query(Follow).filter(
            Follow.follower_id.in_(home_uids),
            Follow.accepted == True
        ).all():
            home_follows.setdefault(f.follower_id, set()).add(f.following_id)
    return home_follows


def _load_post_for_filter(session: Session, post_id: int | None,
                          boost_pointer_id: int | None = None) -> Post | None:
    _db_post = session.query(Post).filter_by(id=post_id).first()
    # Boost pointer: use actual boost pointer Post for author-based filtering (block/mute against booster)
    if boost_pointer_id:
        _bp = session.query(Post).filter_by(id=boost_pointer_id).first()
        if _bp and not _bp.is_deleted:
            _db_post = _bp
    return _db_post
