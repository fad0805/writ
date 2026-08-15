import json
import logging

from sqlalchemy.orm import Session

from app.models import Post

logger = logging.getLogger(__name__)


def _sanitize_post_payload(
        post_json: dict
    ) -> tuple[str, list, int | None, dict | None]:

    # content가 dict 타입으로 잘못 유입되었는지 방어 코드 추가
    if isinstance(post_json.get("content"), dict):
        # dict 형태라면 특정 언어 코드를 가져오거나 문자열로 강제 치환
        content_dict = post_json["content"]
        post_json["content"] = content_dict.get("html") or content_dict.get("text") or str(content_dict)

    if not post_json.get("author") and post_json.get("type") != "update":
        raise ValueError("Post JSON must have an 'author' field unless it's an 'update' type.")

    mentioned_ids = post_json.get("mentioned_user_ids") or []
    # Extract parent author ID from reply_context
    parent_author_id = None
    reply_ctx = post_json.get("reply_context")
    if reply_ctx and isinstance(reply_ctx, dict):
        parent_author = reply_ctx.get("author")
        if parent_author:
            parent_author_id = parent_author.get("id")

    return json.dumps(post_json, default=str), mentioned_ids, parent_author_id, reply_ctx


def _resolve_parent_author(
        post_json: dict,
        post_id: int | None,
        reply_ctx: dict | None,
        session: Session) -> int | None:
    """Resolve the parent author ID from the post JSON or DB."""

    parent_author_id = None
    _is_reply = bool(post_json.get("in_reply_to_id") or post_json.get("in_reply_to_ap_id") or reply_ctx)

    if not post_id:
        return None

    if not _is_reply:
        try:
            _db_post = session.query(Post).filter_by(id=post_id).first()
            if _db_post and _db_post.in_reply_to_id:
                _is_reply = True
                _parent = session.query(Post).filter_by(id=_db_post.in_reply_to_id).first()
                if _parent:
                    parent_author_id = int(_parent.author_id)
        except Exception:
            logger.warning(f"Failed to resolve parent author for post {post_id}", exc_info=True)

    return parent_author_id
