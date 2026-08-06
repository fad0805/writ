"""Feed DB query and paginated filtering."""
import logging
from typing import List

from sqlalchemy import desc, or_, and_
from sqlalchemy.orm import Session, Load

from app.models import Post
from app.utils.filter import _timeline_filter

logger = logging.getLogger(__name__)

# 필터(뮤트/블록/키워드)가 많이 걸려도 무한 루프에 빠지지 않도록 하는 반복 상한.
# 상한에 도달하면 target보다 적은 글이 반환될 수 있고, 이 경우 has_more가
# 실제보다 작게 잡힐 수 있으나(마지막 페이지로 보임) 병목을 방지하는 것이 우선이다.
MAX_FETCH_ITERATIONS = 20


def query_feed_posts(
        tl_type: str,
        visible_user_ids: set,
        local_ids: set,
        user_id: int,
        visibility: list,
        session: Session,
        base_opts: List[Load],
        fetch_size: int,
        offset: int = 0,
        cursor=None):
    """피드 포스트를 생성일 역순으로 조회한다.

    cursor=(created_at, id)가 주어지면 해당 지점보다 오래된 글을 키셋 방식으로
    조회한다(오프셋 스킵 없이 인덱스를 타고 이동). cursor가 없으면 기존 offset
    방식을 사용한다. 두 방식 모두 생성일 역순, 동일 생성일은 id 역순으로 정렬해
    페이지 간 경계가 결정적이도록 한다.
    """
    def _apply_paging(q):
        q = q.order_by(desc(Post.created_at), desc(Post.id))
        if cursor is not None:
            cursor_ts, cursor_id = cursor
            return q.filter(or_(
                Post.created_at < cursor_ts,
                and_(Post.created_at == cursor_ts, Post.id < cursor_id),
            )).limit(fetch_size)
        return q.offset(offset).limit(fetch_size)

    posts = []
    if tl_type != 'social':
        if visible_user_ids is not None:
            q = session.query(Post).options(*base_opts).filter(
                Post.is_deleted == False,
                Post.visibility.in_(visibility),
                Post.author_id.in_(visible_user_ids),
                or_(
                    Post.parent == None,
                    Post.parent.has(Post.author_id.in_(visible_user_ids))
                ),
            )
            visible_posts = _apply_paging(q).all()
        else:
            q = session.query(Post).options(*base_opts).filter(
                Post.is_deleted == False,
                Post.visibility.in_(visibility),
            )
            visible_posts = _apply_paging(q).all()

        posts = [
            p for p in visible_posts
            if not (
                p.visibility == "mention"
                and p.author_id != user_id
                and user_id not in (p.mentioned_user_ids or [])
            )
        ]
    else:
        local_public_ids = (local_ids or set()) - (visible_user_ids or set())
        q = session.query(Post).options(*base_opts).filter(
            Post.is_deleted == False,
        )
        conditions = []
        if visible_user_ids:
            conditions.append(
                and_(Post.author_id.in_(visible_user_ids), Post.visibility.in_(visibility))
            )
        if local_public_ids:
            conditions.append(
                and_(Post.author_id.in_(local_public_ids), Post.visibility == 'public')
            )
        if not conditions:
            return []

        allowed_ids = visible_user_ids | local_public_ids
        try:
            q = q.filter(or_(*conditions)).filter(
                or_(
                    Post.parent == None,
                    Post.parent.has(Post.author_id.in_(allowed_ids))
                )
            )
            posts = _apply_paging(q).all()
        except Exception as e:
            logging.error(f'No post in social feed: {e}')

        posts = [
            p for p in posts
            if not (
                p.visibility == "mention"
                and p.author_id != user_id
                and user_id not in (p.mentioned_user_ids or [])
            )
        ]

    return posts


def _fetch_filtered_posts(session, tl_type, user, limit, offset,
                          _visible_user_ids, _local_ids, user_id, visibility,
                          _base_opts, _following_ids, filter_ctx, cursor=None):
    """2. 필요한 수량(offset + limit + 1)이 채워질 때까지 반복 조회 및 필터링 수행.

    offset은 필터링 *이후* 결과 기준이다. 원본 DB row에 offset을 적용하면
    _timeline_filter로 걸러진 글만큼 페이지 간 오프셋이 어긋나 중복/누락이 생기므로,
    필터된 결과를 누적한 뒤 offset부터 슬라이스한다.

    배치 진행은 OFFSET 대신 (created_at, id) 키셋 커서를 사용한다. 필터는 여전히
    배치 이후 적용되므로 '필터 후 offset' 보정이 그대로 유지된다.

    cursor=(created_at, id)가 주어지면 해당 지점보다 오래된 글부터 limit+1개만
    채운다(무한 스크롤 후반부에서도 이전 페이지를 다시 스캔하지 않도록 O(1) 유지).
    cursor가 없으면 기존 offset 방식으로 동작한다.
    """
    fetch_size = limit + 20
    filtered = []
    if cursor is None:
        target = offset + limit + 1
        slice_start = offset
    else:
        target = limit + 1
        slice_start = 0
    iterations = 0
    cur = cursor

    while len(filtered) < target and iterations < MAX_FETCH_ITERATIONS:
        iterations += 1
        batch = query_feed_posts(
            tl_type,
            _visible_user_ids, _local_ids, user_id, visibility,
            session, _base_opts, fetch_size, cursor=cur
        )
        if not batch:
            break
        batch_size = len(batch)
        _last_raw = batch[-1]
        cur = (_last_raw.created_at, _last_raw.id)
        if user:
            batch = _timeline_filter(batch, session, user, tl_type, _following_ids, filter_ctx=filter_ctx)
        filtered.extend(batch)
        if batch_size < fetch_size:
            break

    return filtered[slice_start:target]
