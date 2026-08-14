"""Feed/timeline query orchestration.

Public API (importable from app.core.feed):
- _get_feed: main feed query entry point.
- _broadcast_federation: federation broadcast for new posts.
"""
import logging

from sqlalchemy.orm import selectinload

from app.core.feed.aggregator import _aggregate_boost_groups
from app.core.feed.broadcast import _broadcast_federation
from app.core.feed.criteria import _build_feed_criteria
from app.core.feed.metadata import (
    _EMPTY_POST_METADATA,
    PostMetadata,
    _feed_used_emojis,
    _load_boost_originals,
    _load_post_metadata,
)
from app.core.feed.query import _fetch_filtered_posts, query_feed_posts
from app.models import Post
from app.serializers import _post_json
from app.utils.filter import _load_user_filters

logger = logging.getLogger(__name__)

__all__ = [
    "_EMPTY_POST_METADATA",
    "PostMetadata",
    "_aggregate_boost_groups",
    "_broadcast_federation",
    "_build_feed_criteria",
    "_feed_used_emojis",
    "_fetch_filtered_posts",
    "_get_feed",
    "_load_boost_originals",
    "_load_post_metadata",
    "query_feed_posts",
]


def _get_feed(user, tl_type, session, limit=10, offset=0, cursor=None):
    _base_opts = [selectinload(Post.author), selectinload(Post.parent)]
    user_id = user.id if user else None

    # 1. 권한 및 가시성 조건 계산
    _following_ids, _local_ids, _visible_user_ids, visibility = _build_feed_criteria(user, session, tl_type)

    # 2. 피드 포스트 수집 및 필터링
    filter_ctx = _load_user_filters(session, user) if user else None
    posts = _fetch_filtered_posts(
        session, tl_type, user, limit, offset,
        _visible_user_ids, _local_ids, user_id, visibility,
        _base_opts, _following_ids, filter_ctx,
        cursor=cursor,
    )

    has_more = len(posts) > limit
    posts = posts[:limit]
    # 다음 페이지 커서: 이번 페이지에서 실제로 보여준 마지막 포스트 기준.
    # (limit+1번째 오버플로 포스트가 아니라, 보여준 포스트 뒤부터 이어서 가져오도록)
    next_cursor = None
    if has_more and posts:
        _last = posts[-1]
        next_cursor = f"{_last.created_at.isoformat()}|{_last.id}"

    # 3. 메타데이터 및 부스트 원본 로드
    posts_metadata = _load_post_metadata(session, user, posts)
    _boost_originals = _load_boost_originals(session, posts)
    _timeline_emojis = _feed_used_emojis(session, posts, _boost_originals)

    # 4. JSON 변환
    feed_dicts = [
        _post_json(p, session, user, tl_type,
                   _liked_ids=posts_metadata.get("liked_ids"),
                   _boosted_ids=posts_metadata.get("boosted_ids"),
                   _bookmarked_ids=posts_metadata.get("bookmarked_ids"),
                   _vote_map=posts_metadata.get("vote_map"),
                   _my_reaction_map=posts_metadata.get("my_reaction_map"),
                   _reactions_map=posts_metadata.get("reactions_map"),
                   _mentioned_users_map=posts_metadata.get("mentioned_users_map"),
                   _boost_originals=_boost_originals,
                   _following_ids=_following_ids,
                   _counts_map=posts_metadata.get("counts_map"),
                   _skip_emojis=True)
        for p in posts
    ]

    # 5. 부스트 그룹 병합 및 정렬 후 반환
    feed_dicts = _aggregate_boost_groups(feed_dicts)

    return feed_dicts, has_more, _timeline_emojis, next_cursor
