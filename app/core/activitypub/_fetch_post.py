import contextlib
import datetime
import html
import logging
import re
import time
import traceback
from urllib.parse import urlparse

from app.config.settings import SECRET_KEY
from app.core.activitypub._emoji import _process_emoji_tags
from app.core.activitypub._fetch_actor import _resolve_actor
from app.core.activitypub._fetch_http import _safe_httpx_get
from app.core.activitypub._media import _cache_remote_media
from app.core.activitypub._utils import _get_instance_actor
from app.core.threads import spawn
from app.db.database import get_session
from app.models import Post, Tag, User
from app.serializers import _post_json
from app.utils.content_parser import _sanitize_html, process_post_content
from app.utils.crypto import get_private_key, sign_string
from app.utils.http import WRIT_USER_AGENT, validate_url, validated_get
from app.utils.urls import extract_remote_url

logger = logging.getLogger("writ.activitypub")

_QUOTE_FIELD_KEYS = ("quote", "quoteUrl", "quoteUri", "quote_uri", "_misskey_quote")


def _extract_quote_url(obj, content=""):
    """AP Note 객체에서 인용(quote) 대상 URL을 추출한다.

    FEP-044f(Mastodon) / Misskey / Firefish 호환 필드와 tag 배열, 그리고
    일부 구현이 본문 HTML에만 인용 링크(RE: <a> / quote-inline span)를
    심어 보내는 경우까지 폴백으로 처리한다.
    """
    if not isinstance(obj, dict):
        return ""
    quote_url = ""
    for key in _QUOTE_FIELD_KEYS:
        val = obj.get(key)
        if isinstance(val, str) and val.startswith("http"):
            quote_url = val
            break
    if not quote_url and isinstance(obj.get("tag"), list):
        for _tag in obj["tag"]:
            if not isinstance(_tag, dict):
                continue
            if _tag.get("type") == "Quote":
                quote_url = _tag.get("href") or _tag.get("id") or ""
            elif _tag.get("type") == "Link" and _tag.get("rel") == "https://misskey-hub.net/ns#_misskey_quote":
                quote_url = _tag.get("href") or ""
            if quote_url:
                break
    if not quote_url:
        for content2 in (content, obj.get("content") if isinstance(obj.get("content"), str) else ""):
            if not content2:
                continue
            m = re.search(r'<span[^>]*class="[^"]*quote-inline[^"]*"[^>]*>\s*RE:\s*<a\b[^>]*\bhref="([^"]+)"', content2, re.I)
            if not m:
                m = re.search(r'\bRE:\s*<a\b[^>]*\bhref="([^"]+)"', content2, re.I)
            if not m:
                m = re.search(r'\bRE:\s*(https?://[^\s<>"\']+)', content2, re.I)
            if m:
                quote_url = html.unescape(m.group(1))
                break
    return quote_url if isinstance(quote_url, str) else ""


def _strip_quote_link(content, quote_url):
    """본문 content에서 인용 링크(RE: <a> / quote-inline span / 순수 URL)를 제거한다."""
    if not content or not quote_url:
        return content
    esc = re.escape(quote_url)
    content = re.sub(
        r'<span[^>]*class="[^"]*quote-inline[^"]*"[^>]*>\s*RE:\s*<a\b[^>]*\bhref="[^"]*"[^>]*>.*?</a>\s*</span>',
        '', content, flags=re.I | re.S
    )
    content = re.sub(
        r'\bRE:\s*<a\b[^>]*\bhref="' + esc + r'"[^>]*>.*?</a>',
        '', content, flags=re.I | re.S
    )
    content = re.sub(
        r'<a\b[^>]*\bhref="' + esc + r'"[^>]*>.*?</a>',
        '', content, flags=re.I | re.S
    )
    content = content.replace(quote_url, "")
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()


def _retry_fetch_reply(post_id: int, in_reply_to_ap_id: str, attempt: int = 0):
    """Background: fetch remote parent and link to local post. Max 5 attempts with increasing delay."""
    MAX_ATTEMPTS = 5
    def _worker():
        try:
            with get_session() as s:
                post = s.query(Post).get(post_id)
                if not post or post.in_reply_to_id:
                    return
                existing_parent = s.query(Post).filter_by(ap_id=in_reply_to_ap_id).first()
                if existing_parent:
                    post.in_reply_to_id = existing_parent.id
                    s.commit()
                    return
                signer = s.query(User).filter_by(id=post.author_id).first() or _get_instance_actor(s)
                parent = _fetch_remote_post(in_reply_to_ap_id, signer, s)
                if parent:
                    post.in_reply_to_id = parent.id
                    s.commit()
                elif attempt + 1 < MAX_ATTEMPTS:
                    delay = min(30 * (2 ** attempt), 600)
                    time.sleep(delay)
                    _retry_fetch_reply(post_id, in_reply_to_ap_id, attempt + 1)
                else:
                    logger.warning("[RETRY-REPLY] gave up post_id=%s ap_id=%s after %d attempts", post_id, in_reply_to_ap_id, MAX_ATTEMPTS)
        except Exception as e:
            logger.error("[RETRY-REPLY] failed post_id=%s err=%s", post_id, e, exc_info=True)
    spawn(_worker)


def _extract_og_title(html: str) -> str:
    match = re.search(r"<title>([^<]*)</title>", html, re.I)
    return match.group(1) if match else ""


def _fetch_remote_post(url: str, signer: User, session, _depth=0):
    """Fetch a remote AP object and save it as a Post. Returns the Post or None."""
    if _depth > 3 or not url:
        return None

    logger.debug("[FETCH-POST] url=%s signer=%s depth=%s", url, signer.actor_uri() if signer else 'None', _depth)

    # Convert web URL /@username/id to AP URL /users/username/statuses/id (Mastodon)
    m = re.match(r'^(https?://[^/]+)/@(\w+(?:@\S+)?)/([a-f0-9]+)(\?.*)?$', url)
    if m:
        base, username, status_id, query = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        url = f"{base}/users/{username}/statuses/{status_id}{query}"
        logger.debug("[FETCH-POST] Mastodon URL converted to: %s", url)

    if url.endswith("/activity"):
        url = url[:-len("/activity")]
        logger.debug("[FETCH-POST] stripped /activity suffix to %s", url)

    parsed = urlparse(url)
    headers = {"Accept": "application/activity+json", "User-Agent": WRIT_USER_AGENT}

    if not signer:
        with contextlib.suppress(Exception):
            signer = _get_instance_actor(session)
    if signer:
        try:
            date_str = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
            path_with_query = parsed.path or "/"
            if parsed.query:
                path_with_query += f"?{parsed.query}"
            signed_string = (
                f"(request-target): get {path_with_query}\n"
                f"host: {parsed.netloc}\n"
                f"date: {date_str}"
            )
            sig = sign_string(signed_string, get_private_key(signer, SECRET_KEY))
            sig_header = (
                f'keyId="{signer.actor_uri()}#main-key",'
                f'headers="(request-target) host date",'
                f'signature="{sig}"'
            )
            headers["Signature"] = sig_header
            headers["Date"] = date_str
            headers["Host"] = parsed.netloc
        except Exception:
            pass

    headers["Accept"] = "application/activity+json"
    data = None
    try:
        resp = validated_get(url, headers=headers, timeout=10)
        logger.debug("[FETCH-POST] first attempt url=%s status=%s", url, resp.status_code if resp else 'None')
        if resp is not None and resp.status_code == 200:
            data = resp.json()
    except Exception as e:
        logger.error("[FETCH-POST] url=%s error=%s", url, e, exc_info=True)

    if data is None:
        logger.debug("[FETCH-POST] FAILED url=%s", url)
        return None

    obj = data.get("object", data) if isinstance(data, dict) else {}
    if not isinstance(obj, dict):
        logger.debug("[FETCH-POST] obj not dict url=%s", url)
        return None
    obj_type = obj.get("type", "")
    if obj_type not in ("Note", "Question"):
        logger.debug("[FETCH-POST] not Note/Question type=%s url=%s", obj_type, url)
        return None

    ap_id = obj.get("id", url)
    remote_url = extract_remote_url(obj, ap_id)
    req_domain = urlparse(url).hostname or ""
    resp_domain = urlparse(ap_id).hostname or ""
    if req_domain and resp_domain and req_domain != resp_domain:
        logger.warning("[FETCH-POST] id domain mismatch: requested %s, response claims %s", req_domain, resp_domain)
        return None
    existing = session.query(Post).filter_by(ap_id=ap_id).first()
    if existing and not existing.is_deleted:
        logger.debug("[FETCH-POST] existing post id=%s ap_id=%s", existing.id, ap_id)
        return existing

    attributed_to = obj.get("attributedTo", "")
    if isinstance(attributed_to, list):
        attributed_to = attributed_to[0] if attributed_to else ""
    if isinstance(attributed_to, dict):
        attributed_to = attributed_to.get("id", "")
    if not attributed_to:
        logger.debug("[FETCH-POST] no attributedTo url=%s", url)
        return None
    att_domain = urlparse(attributed_to).hostname or ""
    if req_domain and att_domain and req_domain != att_domain:
        logger.warning("[FETCH-POST] attributedTo domain mismatch: requested %s, response claims %s", req_domain, att_domain)
        return None

    _resolve_actor(attributed_to, sign_as=signer)
    author = session.query(User).filter_by(remote_url=attributed_to).first()
    if not author:
        logger.debug("[FETCH-POST] author not found attributed_to=%s", attributed_to)
        return None

    raw_content = obj.get("content", "") or ""
    if not raw_content:
        cm = obj.get("contentMap")
        if isinstance(cm, dict) and cm:
            raw_content = next(iter(cm.values()), "")
    if len(raw_content) > 65536:
        raw_content = raw_content[:65536]
    content = process_post_content(_sanitize_html(raw_content), obj)
    summary = obj.get("summary", "")

    to = obj.get("to", [])
    if isinstance(to, str):
        to = [to]
    cc = obj.get("cc", [])
    if isinstance(cc, str):
        cc = [cc]
    all_auds = to + cc
    pub = "https://www.w3.org/ns/activitystreams#Public"
    pub_set = {pub, "as:Public"}

    tags = obj.get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]
    elif not isinstance(tags, list):
        tags = []

    has_mention_tag = False
    mentioned_ids = []
    hashtag_list = []
    for t in tags:
        if not isinstance(t, dict):
            continue
        is_mention_type = t.get("type") == "Mention"
        name_val = t.get("name", "") or ""
        is_double_at = name_val.startswith("@") and name_val.count("@") >= 2
        if is_mention_type or is_double_at:
            has_mention_tag = True
            actor_href = t.get("href", "")
            if not actor_href:
                continue
            try:
                _resolve_actor(actor_href)
                mentioned_user = session.query(User).filter_by(remote_url=actor_href).first()
                if mentioned_user:
                    mentioned_ids.append(mentioned_user.id)
            except Exception as e:
                logger.error("[FETCH-POST] Failed to resolve mentioned actor=%s: %s", actor_href, e, exc_info=True)
        elif t.get('type') == "Hashtag":
            tag_name = (t.get("name", "") or "").lstrip("#").strip().lower()
            if tag_name:
                existing_tag = session.query(Tag).filter_by(name=tag_name).first()
                if existing_tag:
                    hashtag_list.append(existing_tag)
                else:
                    hashtag_list.append(Tag(name=tag_name))
    mentioned_ids = list(set(mentioned_ids))

    if pub_set & set(to):
        vis = "public"
    elif pub_set & set(cc):
        vis = "home"
    elif any(a.endswith("/followers") for a in all_auds):
        vis = "followers"
    elif (not (pub_set & set(all_auds)) and has_mention_tag) or all(a.startswith("http") for a in all_auds if a):
        vis = "mention"
    else:
        vis = "home"

    instance_actor = session.query(User).filter_by(username='actor').first()
    in_reply_to_ap = obj.get("inReplyTo", "")
    if isinstance(in_reply_to_ap, dict):
        in_reply_to_ap = in_reply_to_ap.get("id", "")

    in_reply_to_id = None
    if in_reply_to_ap:
        parent = session.query(Post).filter_by(ap_id=in_reply_to_ap).first()
        if parent:
            in_reply_to_id = parent.id
        else:
            parent = _fetch_remote_post(in_reply_to_ap, instance_actor, session, _depth + 1)
            if parent:
                in_reply_to_id = parent.id

    # 💡 [해결] 원격 오브젝트에서 인용 URL(quoteUrl) 추출 및 연동 처리
    quote_url = obj.get("quoteUrl", "")
    quote_id = None
    if quote_url:
        quoted_post = session.query(Post).filter_by(ap_id=quote_url).first()
        if not quoted_post:
            # 내 DB에 없다면 인용된 원본 게시물도 연합망에서 깊이(depth)를 더해 긁어옵니다.
            quoted_post = _fetch_remote_post(quote_url, signer, session, _depth + 1)
        if quoted_post:
            quote_id = quoted_post.id

    _process_emoji_tags(obj.get("tag", []), session)
    session.flush()

    raw_attachments = obj.get("attachment", [])
    if isinstance(raw_attachments, dict):
        raw_attachments = [raw_attachments]
    elif not isinstance(raw_attachments, list):
        raw_attachments = []
    media_list = []
    _att_has_sensitive = False
    for att in raw_attachments:
        if not isinstance(att, dict):
            continue
        att_type = att.get("mediaType", "")
        att_as2_type = att.get("type", "")
        att_url = ""
        if isinstance(att.get("url"), str):
            att_url = att["url"]
        elif isinstance(att.get("url"), dict):
            att_url = att["url"].get("href", "")
        if not att_url:
            continue
        if att.get("sensitive", False):
            _att_has_sensitive = True
        cached = _cache_remote_media(att_url)
        if att_type.startswith("image/") or att_as2_type == "Image":
            media_list.append({"url": cached, "type": "image"})
        elif att_type.startswith("video/") or att_as2_type == "Video":
            media_list.append({"url": cached, "type": "video"})
        elif att_as2_type == "Document" or att_type.startswith("audio/"):
            if att_type.startswith("image/"):
                mtype = "image"
            elif att_type.startswith("video/"):
                mtype = "video"
            else:
                mtype = "image"  # fallback for missing mediaType
            media_list.append({"url": cached, "type": mtype})

    # 💡 Post 모델 생성 시 quote_id (또는 모델 설계에 맞춘 인용 필드명) 채워넣기
    post = Post(
        author_id=author.id,
        content=content,
        summary=summary,
        visibility=vis,
        ap_id=ap_id,
        remote_url=remote_url,
        in_reply_to_ap_id=in_reply_to_ap,
        in_reply_to_id=in_reply_to_id,
        quote_of_id=quote_id,
        quote_of_ap_id=quote_url,
        mentioned_user_ids=mentioned_ids,
        media_attachments=media_list if media_list else None,
        is_sensitive=obj.get("sensitive", False) or _att_has_sensitive,
        tag_list=hashtag_list,
    )
    published = obj.get("published", "")
    if published:
        with contextlib.suppress(Exception):
            post.created_at = datetime.datetime.fromisoformat(published.replace("Z", "+00:00"))  # type: ignore[assignment]
    session.add(post)
    try:
        session.flush()
    except Exception:
        session.rollback()
        return session.query(Post).filter_by(ap_id=ap_id).first()

    # 💡 만약 인용 글이 제대로 매칭되었다면 하단의 링크 미리보기(외부링크 상자) 연산을 건너뜁니다.
    if post.quote_of_id:
        return post

    # 원격 포스트에 포함된 URL의 링크 미리보기 fetch
    _url_match = re.search(r'https?://(?:(?!/tags/)[^\s<>"\')\]#])+', content or "")
    if _url_match:
        _url = _url_match.group(0)
        try:
            if not validate_url(_url):
                return post
            _resp = validated_get(_url, timeout=5)
            if _resp.status_code == 200:
                _html = _resp.text
                def _og(n):
                    _m = re.search(f'<meta[^>]+property="og:{n}"[^>]+content="([^"]*)"', _html, re.I)
                    if not _m:
                        _m = re.search(f'<meta[^>]+content="([^"]*)"[^>]+property="og:{n}"', _html, re.I)
                    return _m.group(1) if _m else ""
                _og_title = _og("title") or _extract_og_title(_html)
                _og_desc = _og("description")
                _og_img = _og("image")
                if _og_img and _og_img.startswith("/"):
                    _p = urlparse(_url)
                    _og_img = f"{_p.scheme}://{_p.netloc}{_og_img}"
                if _og_img and not validate_url(_og_img):
                    _og_img = ""
                if _og_title:
                    post.link_preview = {"url": _url, "title": html.unescape(_og_title[:200]), "description": html.unescape(_og_desc[:400]) if _og_desc else "", "image": _og_img or ""}  # type: ignore[assignment]
        except Exception:
            pass

    return post


def _ap_fetch(url, user):
    """Fetch a remote URL with HTTP Signature, return parsed JSON."""
    # Convert web URL /@username/id to AP URL /users/username/statuses/id
    original_url = url
    m = re.match(r'^(https?://[^/]+)/@(\w+(?:@\S+)?)/([\w-]+)(\?.*)?$', url)
    if m:
        base, username, status_id, query = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        url = f"{base}/users/{username}/statuses/{status_id}{query}"

    if not validate_url(url):
        return None

    def _sign_and_fetch(target_url, _depth=0):
        if _depth > 2:
            return None
        date_str = datetime.datetime.now(datetime.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
        parsed = urlparse(target_url)
        path_with_query = parsed.path or "/"
        if parsed.query:
            path_with_query += f"?{parsed.query}"
        signed_string = (
            f"(request-target): get {path_with_query}\n"
            f"host: {parsed.netloc}\n"
            f"date: {date_str}"
        )
        try:
            signature = sign_string(signed_string, get_private_key(user, SECRET_KEY))
        except Exception:
            return None
        signature_header = (
            f'keyId="{user.actor_uri()}#main-key",'
            f'headers="(request-target) host date",'
            f'signature="{signature}"'
        )
        headers = {
            "Accept": "application/activity+json",
            "Signature": signature_header,
            "Date": date_str,
            "Host": parsed.netloc,
        }
        resp = _safe_httpx_get(target_url, headers=headers)
        if not resp or resp.status_code != 200:
            logger.debug("[AP_FETCH] url=%s status=%s", target_url, resp.status_code if resp else 'None resp')
            return None
        ct = resp.headers.get("content-type", "")
        if "json" not in ct and "activity" not in ct:
            html = resp.text[:100000]
            alt_m = re.search(r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/activity\+json["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
            if not alt_m:
                alt_m = re.search(r'<link[^>]+type=["\']application/activity\+json["\'][^>]+rel=["\']alternate["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
            if not alt_m:
                alt_m = re.search(r'href=["\']([^"\']+)["\'][^>]*type=["\']application/activity\+json["\']', html, re.I)
            if alt_m:
                alt_url = alt_m.group(1)
                logger.debug("[AP_FETCH] HTML response, found alternate AP URL: %s", alt_url)
                return _sign_and_fetch(alt_url, _depth + 1)
            logger.debug("[AP_FETCH] HTML response, no alternate link found for %s", target_url)
            return None
        try:
            return resp.json()
        except Exception as e:
            logger.debug("[AP_FETCH] json error url=%s: %s", target_url, e)
            return None

    result = _sign_and_fetch(url)
    # Fallback: try original /@username/id URL if /users/.../statuses/... returned 404
    if not result and original_url != url:
        logger.debug("[AP_FETCH] fallback to original_url=%s", original_url)
        result = _sign_and_fetch(original_url)
    logger.debug("[AP_FETCH] result_is_none=%s original=%s converted=%s", result is None, original_url, url)
    return result


def _fetch_and_save_ap_object(obj, user, _visited=None, _depth=0):
    """Fetch a remote AP object, resolve its author, save to DB, return post.
    Also recursively fetches parent posts (thread ancestors) up to depth 5."""
    if _depth > 5:
        return None
    if _visited is None:
        _visited = set()

    # 1. 스레드 상위 글 역추적 로직 안전하게 실행
    in_reply_to = obj.get("inReplyTo", "")
    if isinstance(in_reply_to, dict):
        in_reply_to = in_reply_to.get("id", "")
    if in_reply_to and in_reply_to not in _visited:
        _visited.add(in_reply_to)
        parent_data = _ap_fetch(in_reply_to, user)
        if parent_data:
            parent_obj = parent_data.get("object", parent_data)
            # 💡 재귀 함수가 안전하게 마칠 수 있도록 단독 실행 확보
            try:
                _fetch_and_save_ap_object(parent_obj, user, _visited, _depth + 1)
            except Exception as e:
                logger.warning("Failed to process parent post %s: %s", in_reply_to, e)

    actor_url = obj.get("id")
    post = None
    # 2. 본문 페치 및 DB 저장 로직 수행
    with get_session() as session:
        try:
            post = _fetch_remote_post(actor_url, user, session, _depth)
            # 💡 페치가 성공했을 때만 확실하게 DB 세션 커밋을 보장
            if post:
                session.commit()
        except Exception as e:
            # 💡 단순 print 대신 에러가 발생한 정확한 라인과 원인을 추적하기 위해 traceback 추가
            logger.error("Failed to fetch remote post from %s: %s", actor_url, e)
            traceback.print_exc()
            return None # 껍데기를 만들지 않도록 에러 시 None 리턴 구조로 방어

        if not post:
            return None
        return _post_json(post, session, user)


def _background_fetch_outbox(url: str, user_id: int, actor_id: int):
    with get_session() as s:
        user = s.query(User).get(user_id)
        actor = s.query(User).get(actor_id)
        if not user or not actor:
            return
        try:
            outbox_url = getattr(actor, "outbox_url", None) or getattr(actor, "endpoints", {}).get("sharedInbox", "")
            if not outbox_url:
                date = datetime.datetime.now(datetime.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
                parsed = urlparse(url)
                created = int(time.time())
                ss = f"(request-target): get {parsed.path}\nhost: {parsed.netloc}\ndate: {date}\n(created): {created}"
                priv = get_private_key(user, SECRET_KEY)
                sig = sign_string(ss, priv)
                sig_header = f'keyId="{user.actor_uri()}#main-key",algorithm="hs2019",created="{created}",headers="(request-target) host date (created)",signature="{sig}"'
                headers = {"Accept": "application/activity+json", "Signature": sig_header, "Date": date, "Host": parsed.netloc}
                r = _safe_httpx_get(url, headers=headers)
                if r:
                    outbox_url = r.json().get("outbox", "")
            if outbox_url:
                parsed2 = urlparse(outbox_url)
                date2 = datetime.datetime.now(datetime.UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
                created2 = int(time.time())
                path2 = parsed2.path or "/"
                if parsed2.query:
                    path2 += f"?{parsed2.query}"
                priv = get_private_key(user, SECRET_KEY)
                ss2 = f"(request-target): get {path2}\nhost: {parsed2.netloc}\ndate: {date2}\n(created): {created2}"
                sig2 = sign_string(ss2, priv)
                sig_header2 = f'keyId="{user.actor_uri()}#main-key",algorithm="hs2019",created="{created2}",headers="(request-target) host date (created)",signature="{sig2}"'
                headers2 = {"Accept": "application/activity+json", "Signature": sig_header2, "Date": date2, "Host": parsed2.netloc}
                resp = _safe_httpx_get(f"{outbox_url}?page=1", headers=headers2)
                if resp:
                    outbox_data = resp.json()
                    for item in outbox_data.get("orderedItems", []):
                        try:
                            obj = item.get("object", item)
                            _fetch_and_save_ap_object(obj, actor)
                        except Exception:
                            pass
        except Exception:
            pass
