from app.models import User, get_session
from urllib.parse import urlparse as _urlparse

def resolve_handles_to_ids(handles: list[str]) -> list[int]:
    """핸들 리스트를 받아 DB에서 일치하는 User.id 리스트를 반환합니다."""
    if not handles:
        return []

    user_ids = []
    with get_session() as s:
        for handle in handles:
            # 핸들에서 @ 제거
            clean_handle = handle.lstrip('@')
            # 리모트 유저 (handle에 @가 포함된 경우)
            if '@' in clean_handle:
                local_part, domain = clean_handle.split('@', 1)
                # 1. 직접 매칭 시도
                u = s.query(User).filter(
                    User.username == local_part,
                    User.is_remote == True
                ).first()
                if u and u.remote_url:
                    parsed = _urlparse(u.remote_url)
                    if parsed.hostname and parsed.hostname.lower() == domain.lower():
                        user_ids.append(u.id)
                        continue
                # 2. 후보군 매칭 (username@domain 형태 고려)
                candidates = s.query(User).filter(
                    User.username.like(f"{local_part}@%"),
                    User.is_remote == True
                ).all()
                for _c in candidates:
                    if _c.remote_url:
                        _p = _urlparse(_c.remote_url)
                        if _p.hostname and _p.hostname.lower() == domain.lower():
                            user_ids.append(_c.id)
                            break
            # 로컬 유저
            else:
                u = s.query(User).filter(
                    User.username == clean_handle,
                    User.is_remote == False
                ).first()
                if u:
                    user_ids.append(u.id)
    # 중복 제거 후 반환
    return list(set(user_ids))

