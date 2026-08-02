"""Timeline criteria and visibility calculation."""
from app.models import User, Follow


def _build_feed_criteria(user, session, tl_type):
    """1. 타임라인 종류에 따른 팔로잉, 로컬, 가시성 조건 생성"""
    _following_ids = None
    if user and tl_type in ("home", "social"):
        _following_ids = {
            row[0]
            for row in session.query(Follow.following_id)
            .filter_by(follower_id=user.id, accepted=True)
        }
        _following_ids.add(user.id)

    _local_ids = None
    if tl_type in ("social", "local"):
        _local_ids = {
            row[0]
            for row in session.query(User.id).filter_by(is_remote=False)
        }

    _visible_user_ids = {user.id} if user else set()
    visibility = ['mention', 'followers', 'home', 'public']
    if tl_type == 'home' and _following_ids:
        _visible_user_ids.update(_following_ids)
    elif tl_type == 'social' and _following_ids:
        _visible_user_ids.update(_following_ids)
    elif tl_type == 'local' and _local_ids:
        _visible_user_ids.update(_local_ids)
        visibility = ['public']
    elif tl_type == 'federated':
        _visible_user_ids = None
        visibility = ['public']

    return _following_ids, _local_ids, _visible_user_ids, visibility
