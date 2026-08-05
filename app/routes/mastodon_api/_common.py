"""Shared helpers and serializers for the Mastodon-compatible API package."""
import html
import logging
import re
from datetime import timezone

from fastapi import HTTPException, Request
from sqlalchemy import func as sqlfunc, or_
from sqlalchemy.orm import Session as SASession

from app.models import User, Post, Follow, Like, Boost, MastodonAccessToken, UserMute, UserBlock, now
from app.config.settings import BASE_URL
from app.utils.emoji import _load_emojis


class MastodonAPIError(HTTPException):
    pass


logger = logging.getLogger("writ.mastodon_api")


VISIBILITY_MAP = {
    "public": "public",
    "home": "unlisted",
    "followers": "private",
    "mention": "direct",
    "dm": "direct",
}
VISIBILITY_MAP_REVERSE = {v: k for k, v in VISIBILITY_MAP.items()}
VISIBILITY_MAP_REVERSE["unlisted"] = "home"
# Mastodon의 "direct"는 WRIT의 DM 가시성 "mention"으로 저장해야 한다.
# dict comprehension에서 "dm"이 "mention"을 덮어써 버리므로 여기서 명시적으로 복원한다.
VISIBILITY_MAP_REVERSE["direct"] = "mention"


STAR_REACTION = "★"


def _is_favourite_reaction(reaction):
    """Mastodon 'favourite' maps to writ's default ★ like, not custom reactions."""
    return not reaction or reaction == STAR_REACTION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_bearer_user(request: Request, db: SASession) -> User | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    mat = db.query(MastodonAccessToken).filter_by(access_token=token).first()
    if not mat or mat.user_id is None:
        return None
    return db.query(User).filter_by(id=mat.user_id, is_remote=False).first()


def _require_bearer(request: Request, db: SASession) -> User:
    user = _get_bearer_user(request, db)
    if not user:
        raise MastodonAPIError(status_code=401, detail="The access token is invalid")
    if user.is_suspended:
        raise MastodonAPIError(status_code=403, detail="Account suspended")
    if user.is_frozen:
        raise MastodonAPIError(status_code=403, detail="Account frozen")
    return user


def _maybe_bearer(request: Request, db: SASession) -> User | None:
    return _get_bearer_user(request, db)


def _query_id_list(request: Request) -> list[str]:
    """Parse `id` / `id[]` query params (Mastodon apps send `id[]=1&id[]=2`)."""
    result = []
    for key in ("id", "id[]"):
        for v in request.query_params.getlist(key):
            if v:
                result.append(v)
    return result


def _query_param_list(request: Request, name: str) -> list[str]:
    """Parse `name` / `name[]` query params (Mastodon apps use the `[]` suffix)."""
    result = []
    for key in (name, f"{name}[]"):
        for v in request.query_params.getlist(key):
            if v:
                result.append(v)
    return result


def _visibility_to_mastodon(vis: str) -> str:
    return VISIBILITY_MAP.get(vis, "public")


def _visibility_from_mastodon(vis: str) -> str:
    return VISIBILITY_MAP_REVERSE.get(vis, "public")


def _ap_datetime(dt) -> str:
    if dt is None:
        return now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _account_json(user: User, db: SASession, viewer: User | None = None,
                  _counts: tuple | None = None) -> dict:
    hide_collections = (getattr(user, 'follow_list_visibility', 'public') or 'public') == 'private'
    viewer_is_owner = viewer is not None and viewer.id == user.id

    if _counts is not None:
        follower_count, following_count, statuses_count = _counts
    else:
        follower_count = db.query(sqlfunc.count(Follow.id)).filter(
            Follow.following_id == user.id, Follow.accepted == True
        ).scalar() or 0
        following_count = db.query(sqlfunc.count(Follow.id)).filter(
            Follow.follower_id == user.id, Follow.accepted == True
        ).scalar() or 0
        statuses_count = db.query(sqlfunc.count(Post.id)).filter(
            Post.author_id == user.id, Post.is_deleted == False
        ).scalar() or 0

    if hide_collections and not viewer_is_owner:
        follower_count = 0
        following_count = 0

    acct = user.display_handle or user.username
    if acct.count('@') > 1:
        parts = acct.split('@')
        acct = f"{parts[0]}@{parts[1]}"

    # Mastodon API 규격: username은 로컬 부분만, acct에 전체 핸들
    if user.is_remote:
        username = user.username.split("@")[0] if "@" in user.username else user.username
    else:
        username = user.username

    display_name = user.display_name or ""
    note_html = f"<p>{user.summary}</p>" if user.summary else "<p></p>"
    source_note = user.summary or ""

    all_emojis = _load_emojis(db)
    shortcode_re = re.compile(r':(\w+):')
    used = set(shortcode_re.findall(display_name)) | set(shortcode_re.findall(source_note))
    used_lower = {u.lower() for u in used}
    emojis_in_account = [e for e in all_emojis if e["keyword"].lower() in used_lower]

    def _emoji_to_img(m):
        kw = m.group(1)
        emoji = next((e for e in emojis_in_account if e["keyword"].lower() == kw.lower()), None)
        if emoji and emoji.get("url"):
            safe_url = emoji["url"].replace('"', "%22")
            return f'<img src="{safe_url}" alt=":{kw}:" title=":{kw}:" class="custom-emoji" style="display:inline-block;width:1.2em;height:1.2em;vertical-align:-0.2em;">'
        return m.group(0)
    note_html = shortcode_re.sub(_emoji_to_img, note_html)

    account = {
        "id": str(user.id),
        "username": username,
        "acct": acct,
        "display_name": display_name,
        "locked": bool(user.is_locked),
        "bot": bool(user.is_bot),
        "discoverable": True,
        "indexable": False,
        "group": False,
        "roles": [],
        "noindex": False,
        "hide_collections": hide_collections,
        "suspended": bool(user.is_suspended),
        "limited": bool(user.is_limited),
        "created_at": _ap_datetime(user.created_at),
        "note": note_html,
        "url": user.profile_url or (user.remote_url if user.is_remote else f"{BASE_URL}/@{username}"),
        "avatar": user.profile_image or f"{BASE_URL}/default-avatar.png",
        "avatar_static": user.profile_image or f"{BASE_URL}/default-avatar.png",
        "header": user.header_image or f"{BASE_URL}/default-header.png",
        "header_static": user.header_image or f"{BASE_URL}/default-header.png",
        "followers_count": follower_count,
        "following_count": following_count,
        "statuses_count": statuses_count,
        "last_status_at": _ap_datetime(user.updated_at) if user.updated_at else None,
        "emojis": [
            {"shortcode": e["keyword"], "url": e["url"], "static_url": e["url"], "visible_in_picker": True, "category": e.get("category", "")}
            for e in emojis_in_account
        ],
        "fields": [],
        "source": {
            "note": source_note,
            "privacy": _visibility_to_mastodon(user.default_visibility),
            "sensitive": bool(user.is_sensitive),
            "language": "ko",
            "fields": [],
            "follow_requests_count": 0,
        },
    }

    custom_fields = getattr(user, "custom_fields", None) or []
    for cf in custom_fields:
        name = cf.get("name") or cf.get("label", "")
        value = cf.get("value", "")
        if name:
            account["fields"].append({
                "name": name,
                "value": value,
                "verified_at": None,
            })
    account["source"]["fields"] = account["fields"]

    if viewer:
        account["relationship"] = _relationship_json(viewer, user, db)

    return account


def _build_account_counts_map(user_ids: set, db: SASession) -> dict:
    """Precompute (followers, following, statuses) counts for a set of user ids in 3 queries."""
    user_ids = list(user_ids)
    if not user_ids:
        return {}
    fw = dict(db.query(Follow.following_id, sqlfunc.count(Follow.id)).filter(
        Follow.following_id.in_(user_ids), Follow.accepted == True
    ).group_by(Follow.following_id).all())
    fg = dict(db.query(Follow.follower_id, sqlfunc.count(Follow.id)).filter(
        Follow.follower_id.in_(user_ids), Follow.accepted == True
    ).group_by(Follow.follower_id).all())
    st = dict(db.query(Post.author_id, sqlfunc.count(Post.id)).filter(
        Post.author_id.in_(user_ids), Post.is_deleted == False
    ).group_by(Post.author_id).all())
    return {uid: (fw.get(uid, 0), fg.get(uid, 0), st.get(uid, 0)) for uid in user_ids}


def _build_status_maps(posts: list, db: SASession, viewer: User | None = None) -> dict:
    """Precompute all per-post / per-author counts and lookups for a status list (~7 queries total)."""
    maps = {
        "_replies_map": {}, "_reblogs_map": {}, "_favs_map": {},
        "_reactions_map": {}, "_my_reactions_map": {},
        "_users_map": {}, "_username_map": {}, "_author_counts": {},
    }
    post_ids = [p.id for p in posts]
    if not post_ids:
        return maps

    author_ids = {p.author_id for p in posts}
    mention_ids = set()
    for p in posts:
        mention_ids.update(p.mentioned_user_ids or [])

    maps["_replies_map"] = dict(db.query(Post.in_reply_to_id, sqlfunc.count(Post.id)).filter(
        Post.in_reply_to_id.in_(post_ids), Post.is_deleted == False
    ).group_by(Post.in_reply_to_id).all())
    maps["_reblogs_map"] = dict(db.query(Boost.post_id, sqlfunc.count(Boost.id)).filter(
        Boost.post_id.in_(post_ids)
    ).group_by(Boost.post_id).all())
    maps["_favs_map"] = dict(db.query(Like.post_id, sqlfunc.count(Like.id)).filter(
        Like.post_id.in_(post_ids),
        or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
    ).group_by(Like.post_id).all())

    rows = db.query(Like.post_id, sqlfunc.coalesce(Like.reaction, "★"), sqlfunc.count(Like.id), sqlfunc.min(Like.id)).filter(
        Like.post_id.in_(post_ids)
    ).group_by(Like.post_id, Like.reaction).all()
    for pid, react, cnt, min_id in rows:
        maps["_reactions_map"].setdefault(pid, []).append((react, cnt, min_id))

    if viewer:
        my_rows = db.query(Like.post_id, sqlfunc.coalesce(Like.reaction, "★")).filter(
            Like.post_id.in_(post_ids), Like.user_id == viewer.id
        ).order_by(Like.id.asc()).all()
        for pid, react in my_rows:
            maps["_my_reactions_map"].setdefault(pid, react)

    user_ids = set(author_ids) | set(mention_ids)
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        maps["_users_map"] = {u.id: u for u in users}
        maps["_username_map"] = {u.username: u for u in users}
    maps["_author_counts"] = _build_account_counts_map(author_ids, db)
    return maps


def _relationship_json(user: User, target: User, db: SASession) -> dict:
    relationship = db.query(Follow).filter_by(
        follower_id=user.id, following_id=target.id
    ).first()
    return {
        "id": str(target.id),
        "following": bool(relationship),
        "showing_reblogs": True,
        "notifying": bool(relationship and relationship.notify_on_post),
        "followed_by": bool(db.query(Follow).filter_by(follower_id=target.id, following_id=user.id).first()),
        "blocking": bool(db.query(UserBlock).filter_by(user_id=user.id, target_user_id=target.id).first()),
        "blocked_by": bool(db.query(UserBlock).filter_by(user_id=target.id, target_user_id=user.id).first()),
        "muting": bool(db.query(UserMute).filter_by(user_id=user.id, target_user_id=target.id).first()),
        "muting_notifications": bool(db.query(UserMute).filter_by(user_id=user.id, target_user_id=target.id, hide_notifications=True).first()),
        "requested": False,
        "domain_blocking": False,
        "endorsed": False,
        "note": "",
    }


def _status_json(post: Post, db: SASession, viewer: User | None = None,
                 _boosted_ids: set = None, _liked_ids: set = None,
                 _bookmarked_ids: set = None, _replies_map: dict = None,
                 _reblogs_map: dict = None, _favs_map: dict = None,
                 _reactions_map: dict = None, _my_reactions_map: dict = None,
                 _users_map: dict = None, _username_map: dict = None,
                 _author_counts: dict = None) -> dict:
    if post.is_deleted:
        return None

    author = post.author
    if not author or author.is_suspended:
        return None

    content = post.content or ""

    all_emojis = _load_emojis(db)

    content = re.sub(
        r'!\[":(\w+):"\]\(vector://vector/[^)]*\)',
        lambda m: next(
            (f'<img src="{e["url"]}" alt=":{e["keyword"]}:" title=":{e["keyword"]}:" class="custom-emoji" width="16" height="16">'
             for e in all_emojis if e["keyword"] == m.group(1)),
            m.group(0)
        ),
        content
    )

    # Mastodon 포맷으로 멘션 변환
    def _fmt_mention(m):
        tag = m.group(0)
        # 0. 멘션 대상 핸들 추출 (@username 또는 @username@domain)
        _inner = re.search(r'href="[^"]*?/@([^/"]+)', tag)
        _uname = _inner.group(1) if _inner else None
        _mu = None
        if _username_map is not None and _uname:
            _mu = _username_map.get(_uname)
        if _mu is None and _uname:
            _mu = db.query(User).filter_by(username=_uname).first()
        # 1. 원격 유저는 원격 웹 프로필 주소로, 로컬 유저는 BASE_URL 주소로 변환
        if _mu and _mu.is_remote:
            _profile = _mu.profile_url or _mu.remote_url or f"{BASE_URL}/@{_uname}"
            tag = re.sub(r'href="[^"]*"', f'href="{_profile}"', tag, count=1)
        else:
            tag = re.sub(r'href="/@', f'href="{BASE_URL}/@', tag)
        # 2. 멘션 태그 내부 구조 정리
        tag = re.sub(r'>@([^<]+)</a>', r'>@<span>\1</span></a>', tag)
        # 3. 여기서 닫히는 괄호(>) 바로 앞에 rel 속성을 안전하게 추가!
        tag = re.sub(r'(\s*?)>', r' rel="nofollow noopener">', tag, count=1)
        return f'<span class="h-card" translate="no">{tag}</span>'

    # 메인 실행부는 깔끔하게 이거 하나만 호출하면 끝!
    content = re.sub(
        r'<a\b[^>]*?\bclass="[^"]*\bmention\b[^"]*"[^>]*?>',
        _fmt_mention,
        content
    )

    # 인용(quote) 게시글: Mastodon 앱은 quote 필드를 렌더링하지 않으므로
    # 인용 대상 링크를 "RE: <url>" 형식으로 본문에 붙여 클릭 가능하게 만든다.
    _quote_url = ""
    if post.quote_of_id:
        _qp = db.query(Post).filter_by(id=post.quote_of_id).first()
        if _qp and not _qp.is_deleted:
            if _qp.author and _qp.author.is_remote:
                _quote_url = _qp.remote_url or _qp.ap_id or ""
            else:
                _quote_url = _qp.ap_id or f"{BASE_URL}/@{_qp.author.username}/{_qp.id}"
    if not _quote_url:
        _quote_url = post.quote_of_ap_id or ""
    if _quote_url:
        _quote_link = (
            f'<p>RE: <a href="{html.escape(_quote_url, quote=True)}" '
            f'rel="nofollow noopener noreferrer" target="_blank">'
            f'{html.escape(_quote_url)}</a></p>'
        )
        if content.strip().startswith("<"):
            content = content + _quote_link
        else:
            content = f"<p>{content}</p>" + _quote_link

    shortcode_pattern = re.compile(r':(\w+):')
    used_shortcodes = {sc.lower() for sc in shortcode_pattern.findall(content)}
    post_emojis = [e for e in all_emojis if e["keyword"].lower() in used_shortcodes]

    if _replies_map is not None:
        replies_count = _replies_map.get(post.id, 0)
    else:
        replies_count = db.query(sqlfunc.count(Post.id)).filter(
            Post.in_reply_to_id == post.id, Post.is_deleted == False
        ).scalar() or 0
    if _reblogs_map is not None:
        reblogs_count = _reblogs_map.get(post.id, 0)
    else:
        reblogs_count = db.query(sqlfunc.count(Boost.id)).filter(
            Boost.post_id == post.id
        ).scalar() or 0
    if _favs_map is not None:
        favourites_count = _favs_map.get(post.id, 0)
    else:
        favourites_count = db.query(sqlfunc.count(Like.id)).filter(
            Like.post_id == post.id,
            or_(Like.reaction == STAR_REACTION, Like.reaction.is_(None)),
        ).scalar() or 0

    status = {
        "id": str(post.id),
        "created_at": _ap_datetime(post.created_at),
        "in_reply_to_id": str(post.in_reply_to_id) if post.in_reply_to_id else None,
        "in_reply_to_account_id": None,
        "sensitive": bool(post.is_sensitive),
        "spoiler_text": post.summary or "",
        "visibility": _visibility_to_mastodon(post.visibility),
        "language": "ko",
        "uri": post.ap_id or f"{BASE_URL}/posts/{post.id}",
        "url": post.remote_url or post.ap_id or f"{BASE_URL}/@{author.username}/{post.id}" if author.is_remote else f"{BASE_URL}/@{author.username}/{post.id}",
        "replies_count": replies_count,
        "reblogs_count": reblogs_count,
        "favourites_count": favourites_count,
        "favourited": False,
        "reblogged": False,
        "muted": False,
        "bookmarked": False,
        "pinned": bool(post.is_pinned),
        "content": content if content.strip().startswith("<") else f"<p>{content}</p>",
        "reblog": None,
        "application": None,
        "account": _account_json(author, db, viewer,
                                 _counts=(_author_counts or {}).get(author.id) if _author_counts is not None else None),
        "media_attachments": [],
        "mentions": [
            {"id": str(mid), "username": mu.username.split("@")[0], "url": mu.profile_url or (mu.remote_url if mu.is_remote else f"{BASE_URL}/@{mu.username.split('@')[0]}"), "acct": mu.username}
            for mid in (post.mentioned_user_ids or [])
            if (mu := (_users_map.get(mid) if _users_map is not None else db.query(User).filter_by(id=mid).first()))
        ],
        "tags": [],
        "emojis": [
            {"shortcode": e["keyword"], "url": e["url"], "static_url": e["url"], "visible_in_picker": True, "category": e.get("category", "")}
            for e in post_emojis
        ],
        "card": None,
        "poll": None,
        "reactions": [],
    }

    if post.in_reply_to_id and post.parent:
        status["in_reply_to_account_id"] = str(post.parent.author_id)

    if post.media_attachments:
        for m in post.media_attachments:
            if not isinstance(m, dict):
                continue
            status["media_attachments"].append({
                "id": str(m.get("id", "")),
                "type": m.get("type", "image"),
                "url": m.get("url", ""),
                "preview_url": m.get("preview_url", m.get("url", "")),
                "remote_url": None,
                "text_url": m.get("url", ""),
                "meta": {},
                "description": m.get("alt", ""),
                "blurhash": None,
            })

    if post.tag_list:
        for tag in post.tag_list:
            display = tag.display_name or tag.name
            status["tags"].append({
                "name": display,
                "url": f"{BASE_URL}/explore?q=%23{display}",
            })

    if post.poll_data:
        pd = post.poll_data
        options = pd.get("options", [])
        total_votes = sum(o.get("votes_count", 0) for o in options)
        status["poll"] = {
            "id": str(post.id),
            "expires_at": pd.get("expires_at"),
            "expired": False,
            "multiple": pd.get("multiple", False),
            "votes_count": total_votes,
            "voters_count": total_votes,
            "voted": False,
            "own_votes": [],
            "options": [{"title": o.get("text", ""), "votes_count": o.get("votes_count", 0)} for o in options],
        "emojis": [{
            "shortcode": e["keyword"],
            "url": e["url"],
            "static_url": e["url"],
            "visible_in_picker": True,
            "category": e.get("category", ""),
        } for e in post_emojis],
        }

    if viewer:
        if _liked_ids is None:
            _liked_ids = set()
        if _boosted_ids is None:
            _boosted_ids = set()
        if _bookmarked_ids is None:
            _bookmarked_ids = set()
        status["favourited"] = post.id in _liked_ids
        status["reblogged"] = post.id in _boosted_ids
        status["bookmarked"] = post.id in _bookmarked_ids

    if _reactions_map is not None:
        reaction_rows = [(r[0], r[1]) for r in sorted(_reactions_map.get(post.id, []), key=lambda r: r[2])]
    else:
        reaction_rows = db.query(
            sqlfunc.coalesce(Like.reaction, "★"), sqlfunc.count(Like.id)
        ).filter(Like.post_id == post.id).group_by(Like.reaction).order_by(sqlfunc.min(Like.id)).all()
    my_reaction = None
    if viewer:
        if _my_reactions_map is not None:
            my_reaction = _my_reactions_map.get(post.id)
        else:
            my_like = db.query(Like).filter_by(user_id=viewer.id, post_id=post.id).first()
            if my_like:
                my_reaction = my_like.reaction or "★"
    for react, cnt in reaction_rows:
        name = (react or "★").strip(":")
        emoji_url = ""
        emoji_static_url = ""
        if name != "★":
            emoji_row = next((e for e in all_emojis if e["keyword"] == name), None)
            if emoji_row:
                emoji_url = emoji_row["url"]
                emoji_static_url = emoji_row["url"]
                if not any(e["shortcode"] == name for e in status["emojis"]):
                    status["emojis"].append({
                        "shortcode": emoji_row["keyword"],
                        "url": emoji_row["url"],
                        "static_url": emoji_row["url"],
                        "visible_in_picker": True,
                        "category": emoji_row.get("category", ""),
                    })
        status["reactions"].append({
            "name": name,
            "count": cnt,
            "me": name == (my_reaction or "").strip(":"),
            "url": emoji_url,
            "static_url": emoji_static_url,
        })

    return status


def _boost_status_json(boost_post: Post, original: Post, db: SASession,
                       viewer: User | None = None, **kwargs) -> dict:
    inner = _status_json(original, db, viewer, **kwargs)
    if inner is None:
        return None
    outer = _status_json(boost_post, db, viewer, **kwargs)
    if outer is None:
        return None
    outer["reblog"] = inner
    return outer

