"""리액션 배지 키 유틸.

같은 shortcode라도 서버마다 다른 이모지이므로, 원격 커스텀 이모지 리액션은
``:shortcode:@domain`` 형태의 키로 집계해 배지를 분리한다. 로컬/유니코드
리액션은 기존처럼 ``:shortcode:`` / ``★`` 키를 그대로 사용한다.
"""

from sqlalchemy import func

from app.models import Like


def reaction_key(reaction: str | None, domain: str = "") -> str:
    """리액션 문자열과 이모지 출처 도메인을 UI 배지 키로 합친다."""
    value = reaction or "★"
    if domain and value.startswith(":") and value.endswith(":"):
        return f"{value}@{domain.lower()}"
    return value


def parse_reaction_key(key: str) -> tuple[str, str]:
    """배지 키를 (원본 리액션 문자열, 이모지 출처 도메인)으로 나눈다."""
    if "@" in key:
        reaction, domain = key.rsplit("@", 1)
        if domain and reaction.startswith(":") and reaction.endswith(":"):
            return reaction, domain
    return key, ""


def build_reactions_map(session, ids) -> dict[int, dict[str, int]]:
    """여러 글의 리액션을 한 번에 집계해 도메인별 배지 키로 반환한다."""
    result: dict[int, dict[str, int]] = {}
    if not ids:
        return result
    rows = session.query(
        Like.post_id,
        Like.reaction,
        Like.reaction_domain,
        func.count(Like.id),
    ).filter(
        Like.post_id.in_(ids),
    ).group_by(
        Like.post_id, Like.reaction, Like.reaction_domain
    ).order_by(
        Like.post_id, func.min(Like.id)
    ).all()
    for pid, reaction, domain, count in rows:
        result.setdefault(pid, {})[reaction_key(reaction, domain or "")] = count
    return result
