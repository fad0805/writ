import re
from urllib.parse import quote, urlparse

from app.config.settings import BASE_URL
from app.db.database import get_session


def _ap_datetime(dt):
    import datetime
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ap_actor(user) -> dict:
    tags = []
    for ht in (getattr(user, 'profile_hashtags', None) or []):
        tags.append({"type": "Hashtag", "href": f"{BASE_URL}/explore?tag={ht}", "name": f"#{ht}"})
    result = {
        "@context": [
            "https://www.w3.org/ns/activitystreams",
            "https://w3id.org/security/v1",
            {"PropertyValue": "https://schema.org/PropertyValue", "value": "https://schema.org/value"},
        ],
        "id": user.actor_uri(),
        "type": "Person",
        "preferredUsername": user.username,
        "name": user.display_name or user.username,
        "summary": user.summary or "",
        "url": f"{BASE_URL}/@{user.username}",
        "inbox": user.inbox_uri(),
        "outbox": user.outbox_uri(),
        "featured": user.featured_uri(),
        "followers": user.followers_uri(),
        "following": user.following_uri(),
        "publicKey": {
            "id": f"{user.actor_uri()}#main-key",
            "owner": user.actor_uri(),
            "publicKeyPem": user.public_key,
        },
        "published": _ap_datetime(user.created_at),
        "discoverable": True,
        "manuallyApprovesFollowers": bool(user.is_locked),
    }
    if tags:
        result["tag"] = tags
    if user.profile_image:
        result["icon"] = {"type": "Image", "url": user.profile_image}
    if user.header_image:
        result["image"] = {"type": "Image", "url": user.header_image}
    if user.shared_inbox_url:
        result["endpoints"] = {"sharedInbox": user.shared_inbox_url}
    elif not user.is_remote:
        result["endpoints"] = {"sharedInbox": f"{BASE_URL}/inbox"}
    if user.updated_at:
        result["updated"] = user.updated_at.isoformat()
    custom_fields = getattr(user, 'custom_fields', None) or []
    if custom_fields:
        result["attachment"] = [
            {"type": "PropertyValue", "name": cf.get("name") or cf.get("label", ""), "value": cf.get("value", "")}
            for cf in custom_fields if (cf.get("name") or cf.get("label")) and cf.get("value")
        ]
    return result


def to_ap_note(post, session=None) -> dict:
    from app.models import User, CustomEmoji
    content = post.content
    tags = []
    mentioned_uris = []

    # 1. 멘션 및 해시태그 구축
    with get_session() as s:
        if post.mentioned_user_ids:
            users = s.query(User).filter(User.id.in_(post.mentioned_user_ids)).all()
            for u in users:
                actor_uri = u.actor_uri()
                mentioned_uris.append(actor_uri)
                tag_name = f"@{u.username}" if u.is_remote else f"@{u.username}@{urlparse(BASE_URL).hostname}"
                tags.append({"type": "Mention", "href": actor_uri, "name": tag_name})
                target_rel = f'href="/@{u.username}"'
                domain = u.username.split('@', 1)[1] if '@' in u.username else urlparse(BASE_URL).netloc
                username = u.username.split('@', 1)[0]
                content = content.replace(target_rel, f'href="https://{domain}/@{username}"')
                if not u.is_remote:
                    content = re.sub(
                        rf'>@{re.escape(username)}</a>',
                        f'>@{username}@{domain}</a>',
                        content)

        if post.tag_list:
            for t in post.tag_list:
                tags.append({"type": "Hashtag", "href": f"{BASE_URL}/explore?q=#{quote(t.display_name)}", "name": f"#{t.display_name}"})

    # 2. 이모지 구축
    _emoji_pattern = re.compile(r':([a-z0-9_]{2,}):')
    _emoji_keywords = set(_emoji_pattern.findall(content))
    if _emoji_keywords:
        with get_session() as _es:
            for kw in _emoji_keywords:
                emoji = _es.query(CustomEmoji).filter_by(keyword=kw).first()
                if emoji:
                    url = emoji.source_url
                    tags.append({
                        "type": "Emoji", "id": f"{BASE_URL}/emojis/{kw}", "name": f":{kw}:",
                        "icon": {"type": "Image", "mediaType": "image/webp", "url": url}
                    })

    # 2-3. 내부 링크를 절대 경로로 변환 (AP 전송 시)
    content = re.sub(
        r'href="(/(?:series|episode)/[^"]*)"',
        lambda m: f'href="{BASE_URL}{m.group(1)}"',
        content
    )
    content = re.sub(
        r'href="[^"]*explore\?q=(?:%23|#)([^&"]+)[^"]*"',
        lambda m: f'href="{BASE_URL}/explore?q=#{m.group(1)}"',
        content
    )
    content = re.sub(
        r'href="(/@\w+)"',
        lambda m: f'href="{BASE_URL}{m.group(1)}"',
        content
    )

    # 3. 객체 생성
    obj = {
        "@context": ["https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1", {
            "manuallyapprovesfollowers": "as:manuallyapprovesfollowers", "toot": "http://joinmastodon.org/ns#",
            "emoji": "toot:emoji", "quote": {"@id": "https://w3id.org/fep/044f#quote", "@type": "@id"}
        }],
        "id": post.ap_id,
        "type": "Question" if post.poll_data else "Note",
        "attributedTo": post.author.actor_uri().strip(),
        "content": f"<p>{content}</p>" if not content.strip().startswith("<p>") else content,
        "mediaType": "text/html",
        "tag": tags,
        "to": [], "cc": []
    }

    # 4. 수신자 및 답글 관계 설정
    to_list = list(set(mentioned_uris))
    cc_list = []
    public_uri = "https://www.w3.org/ns/activitystreams#Public"
    followers_uri = post.author.followers_uri()

    # 답글 처리
    if post.parent:
        ap_id = post.parent.ap_id or f"{BASE_URL}/posts/{post.parent.id}"
        obj["inReplyTo"] = ap_id
        if post.parent.author.actor_uri().strip() not in to_list:
            to_list.append(post.parent.author.actor_uri().strip())
        parent_followers = post.parent.author.followers_uri()
        if parent_followers not in to_list and parent_followers not in cc_list:
            cc_list.append(parent_followers)

    # 공개 범위
    if post.visibility == "mention":
        cc_list.clear()
    elif post.visibility == "followers":
        to_list.append(followers_uri)
    elif post.visibility == "home":
        if followers_uri not in to_list:
            to_list.append(followers_uri)
        if public_uri not in cc_list:
            cc_list.append(public_uri)
    else:
        to_list.append(public_uri)
        cc_list.append(followers_uri)

    # 본인에게 보내는 답글일 경우, to_list에 본인을 포함
    if post.parent and post.parent.author_id == post.author_id:
        if post.author.actor_uri().strip() not in to_list:
            to_list.append(post.author.actor_uri().strip())

    # 5. 미디어, 인용, 설문 처리
    if post.media_attachments:
        obj["attachment"] = [{"type": "Video" if m.get("type")=="video" else "Image",
                             "mediaType": "video/webm" if m.get("type")=="video" else f"image/{m.get('url', '').rsplit('.',1)[-1]}",
                             "url": m.get("url")} for m in post.media_attachments[:4]]
    if post.quote_of_ap_id:
        obj.update({"quoteUrl": post.quote_of_ap_id, "quote": post.quote_of_ap_id, "quoteUri": post.quote_of_ap_id})
    if post.poll_data:
        obj["oneOf"] = [
            {
                "type": "Note",
                "name": o["text"],
                "replies": {
                    "type": "Collection",
                    "totalItems": o.get("votes_count", 0)
                }} for o in post.poll_data.get("options", [])
        ]
        obj["votersCount"] = sum(o.get("votes_count", 0) for o in post.poll_data.get("options", []))
        obj["endTime"] = post.poll_data.get('expires_at')

    # 6. 최종 수신자 정리
    if post.visibility != "mention":
        cc_list.append(post.author.actor_uri().strip())
    obj["to"] = list(set(to_list))
    obj["cc"] = list(set(cc_list) - set(obj["to"]))
    return obj


def to_ap_create(post, session=None) -> dict:
    note = to_ap_note(post, session=session)
    return {
        "@context": note.get("@context"),
        "id": f"{BASE_URL}/activities/create/{post.id}",
        "type": "Create",
        "actor": post.author.actor_uri(),
        "published": note.get("published"),
        "to": note.get("to", []),
        "cc": note.get("cc", []),
        "object": note,
    }
