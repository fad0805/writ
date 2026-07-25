import re
from urllib.parse import quote, unquote, urlparse

import nh3
from bs4 import BeautifulSoup, NavigableString

from app.models import Post
from app.config import BASE_URL


def process_post_content(sanitized_content: str, post: dict | Post | None) -> str:
    if not sanitized_content:
        return ""

    # 1. 로컬 포스트인지 리모트 포스트인지 판별
    # post가 Post 모델이거나 dict 타입 내부에 ap_id가 존재하면 리모트로 간주
    is_remote = False
    if isinstance(post, dict):
        # dict일 경우 id나 attributedTo가 있으면 리모트
        if post.get("id") or post.get("attributedTo"):
            is_remote = True
    elif post and hasattr(post, "is_remote"):
        is_remote = post.is_remote
    elif post and hasattr(post, "ap_id") and post.ap_id:
        # 모델에 ap_id가 있다면 리모트일 확률이 높음
        is_remote = True

    # 2. 판별된 타입에 따라 함수 호출
    if is_remote:
        # 리모트 포스트는 dict 타입으로 변환하거나 그대로 전달
        post_data = post if isinstance(post, dict) else {"object": post}
        return process_remote_post(sanitized_content, post_data)
    else:
        return process_local_post(sanitized_content)


def extract_mentions(post_content: str, post: dict | Post | None) -> list[str]:
    # 1. 리모트/로컬 판별 (기존 로직 재사용)
    is_remote = False
    if isinstance(post, dict):
        is_remote = bool(post.get("id") or post.get("attributedTo"))
    elif post and hasattr(post, "is_remote"):
        is_remote = post.is_remote
    # 2. 판별된 타입에 따라 빠른 경로 선택
    if is_remote:
        return extract_mentions_from_remote(post if isinstance(post, dict) else {"object": post})
    else:
        return extract_mentions_from_local(post_content)


def _sanitize_html(html: str) -> str:
    """Strip dangerous HTML tags/attributes, keep only safe ones."""
    if not html:
        return ""
    # ActivityPub(마스토돈, 미스키 등)에서 흔히 사용하는 안전한 태그 목록
    allowed_tags = {
        "a", "p", "del", "br", "span", "b", "i", "strong", "em", 
        "ul", "ol", "li", "blockquote", "code", "pre", "del"
    }
    # 각 태그별로 허용할 속성 (XSS 방지를 위해 href는 https/http만 허용)
    allowed_attributes = {
        "a": {"href", "target", "class"},
        "span": {"class", "lang"},
    }
    # 스크립트, 스타일, 온클릭 이벤트 등을 전부 날려버리고 안전한 HTML만 반환
    clean_html = nh3.clean(
        html,
        tags=allowed_tags,
        attributes=allowed_attributes,
        link_rel="noopener noreferrer" # 링크 추가 시 보안 속성 강제
    )
    return clean_html


def _finalize_html(soup):
    for br in list(soup.find_all("br")):
        br.replace_with("\n")
    for tag in list(soup.find_all(["p", "div"])):
        tag.insert_before("\n")
        tag.insert_after("\n")

def _serialize_html(soup):
    def _to_html(node):
        if isinstance(node, NavigableString):
            return node.output_ready()
        if node.name == "a":
            attrs_list = []
            for k, v in node.attrs.items():
                val = " ".join(v) if isinstance(v, list) else v
                if k == "href" and "/explore?q=" in val:
                    try:
                        _, query = val.split("/explore?q=", 1)
                        val = f"/explore?q={quote(unquote(query))}"
                    except Exception: pass
                attrs_list.append(f'{k}="{val}"')
            attrs_str = f" {' '.join(attrs_list)}" if attrs_list else ""
            children_str = "".join(_to_html(c) for c in list(node.children))
            return f"<a{attrs_str}>{children_str}</a>"
        if node.name in ("blockquote", "strong", "em", "b", "i", "code", "pre", "del", "span"):
            children_str = "".join(_to_html(c) for c in list(node.children))
            return f"<{node.name}>{children_str}</{node.name}>"
        if node.name in ("ul", "ol"):
            children_str = "".join(_to_html(c) for c in list(node.children))
            return f"<{node.name}>{children_str}</{node.name}>"
        if node.name == "li":
            children_str = "".join(_to_html(c) for c in list(node.children))
            return f"<li>{children_str}</li>\n"
        return "".join(_to_html(c) for c in list(node.children))

    result = "".join(_to_html(c) for c in list(soup.contents))
    return re.sub(r'\n{3,}', '\n\n', result).strip()


def process_remote_post(sanitized_content: str, post: dict) -> str:
    # 1. 메타데이터 추출
    obj_data = post.get("object", post) if isinstance(post.get("object"), dict) else post
    raw_tags = obj_data.get("tag", []) or []
    mentioned_user_ids = []
    for t in raw_tags:
        if isinstance(t, dict) and t.get("type") == "Mention" and t.get("name"):
            mentioned_user_ids.append(t.get("name").strip())

    soup = BeautifulSoup(sanitized_content, "html.parser")

    # 2. 기존 <a> 태그 리모델링
    for a_tag in soup.find_all("a"):
        text = a_tag.get_text().strip()
        raw_href = a_tag.get("href", "").strip()
        raw_username = text.lstrip('@').lower()
        href_lower = raw_href.lower()

        # 멘션 매칭
        is_mention_matched = False
        matched_uid = None
        for uid in mentioned_user_ids:
            uid_lower = uid.lower()
            pure_username = uid_lower.lstrip('@').split('@')[0]
            if (raw_username == pure_username or uid_lower == text.lower() or 
                pure_username in href_lower or uid_lower in href_lower):
                is_mention_matched = True
                matched_uid = uid
                break

        if is_mention_matched and matched_uid:
            # name 필드에 도메인이 없을 경우 href URL에서 추출
            # (Mastodon 등 같은 인스턴스 사용자 Mention 시 name이 @user 형태로 옴)
            if '@' not in matched_uid.lstrip('@') and raw_href.startswith('http'):
                _rm_match = re.match(r'https?://([^/]+)/(?:@|users/)([A-Za-z0-9_.-]+)', raw_href, re.IGNORECASE)
                if _rm_match:
                    _domain = _rm_match.group(1).lower()
                    _uname = _rm_match.group(2)
                    if _domain != urlparse(BASE_URL).hostname:
                        matched_uid = f"@{_uname}@{_domain}"
            # BASE_URL 도메인이 포함된 matched_uid는 로컬 형식으로 변환
            _hostname = urlparse(BASE_URL).hostname
            _mparts = matched_uid.lstrip('@').split('@', 1)
            if len(_mparts) == 2 and _mparts[1] == _hostname:
                matched_uid = f"@{_mparts[0]}"
            a_tag.clear()
            a_tag.string = matched_uid
            a_tag["href"] = f"/{matched_uid}"
            a_tag["class"] = "u-url mention"
            a_tag.attrs.pop("target", None)
            continue

        # 예외 방어 (Fallback)
        if text.startswith('@') and raw_href.startswith('http'):
            remote_url_match = re.match(r'https?://([^/]+)/(?:@|users/)([A-Za-z0-9_.-]+)', raw_href, re.IGNORECASE)
            if remote_url_match:
                domain = remote_url_match.group(1).lower()
                username = remote_url_match.group(2)
                if domain == urlparse(BASE_URL).hostname:
                    a_tag.string = f"@{username}"
                    a_tag["href"] = f"/@{username}"
                else:
                    a_tag.string = f"@{username}@{domain}"
                    a_tag["href"] = f"/@{username}@{domain}"
                a_tag["class"] = "u-url mention"
                a_tag.attrs.pop("target", None)
                continue

        # 해시태그 처리
        if text.startswith('#'):
            tag_name_match = re.search(r'#([^\s#@<]+)', text)
            if tag_name_match:
                tag_name = tag_name_match.group(1)
                a_tag.clear()
                a_tag.string = f"#{tag_name}"
                a_tag["href"] = f"/explore?q={quote(f'#{tag_name}')}"
                a_tag["class"] = "hashtag"
                a_tag.attrs.pop("target", None)
                continue

        # 일반 URL
        if text and re.match(r'^https?://', text):
            display = re.sub(r'^https?://', '', text)
            if len(display) > 40:
                display = display[:37] + "..."
            a_tag.clear()
            a_tag.string = display

    # 줄바꿈 및 직렬화 과정(기존 로직 동일)
    _finalize_html(soup)
    return _serialize_html(soup)


def process_local_post(text: str) -> str:
    # 1. 텍스트 정제
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip('\n\r ')
    if not text:
        return ""

    # 2. 코드 블록 보호 (플레이스홀더 사용)
    code_blocks = []
    # 2.1 마크다운 코드 블록 처리
    text = re.sub(r'```(\w*)\r?\n([\s\S]*?)```', _save_code_block, text)
    text = re.sub(r'```([^`\n]+?)```', lambda m: f'<pre><code>{m.group(1)}</code></pre>', text)

    # series: 처리
    text = re.sub(
        r'(?i)\bseries\s*:\s*(https?://[^\s<>"\')\]#]+)',
        lambda m: _make_internal_link(m, 'series'),
        text
    )
    # episode: 처리
    text = re.sub(
        r'(?i)\bepisode\s*:\s*(https?://[^\s<>"\')\]#]+)',
        lambda m: _make_internal_link(m, 'episode'),
        text
    )

    # 3. 생짜 URL 링크화 (코드 블록은 이미 보호됨)
    url_pattern = r'(?<!href=")(?<!src=")(?<!">)(https?://(?!.*/tags/)[^\s<>"\')\]#]+)'
    text = re.sub(url_pattern, r'<a href="\1" class="u-url" target="_blank" rel="noopener noreferrer">\1</a>', text)

    # 4. 나머지 마크다운 문법 변환
    text = re.sub(r'`([^`\n]+?)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = text.replace('\n', '<br>')

    # 5. BeautifulSoup을 이용한 멘션/해시태그 파싱
    soup = BeautifulSoup(text, "html.parser")

    for text_node in list(soup.find_all(string=True)):
        # 이미 링크 안이거나, 코드 블록 내부 보호문자열이면 건너뜀
        if not text_node.parent or text_node.find_parent("a") or text_node.find_parent("code") or text_node.find_parent("pre"):
            continue

        text_str = str(text_node)
        # 멘션/태그 정규식
        new_text = re.sub(r'(?<![A-Za-z0-9_.-="])@([A-Za-z0-9_.-]+)@([A-Za-z0-9_.-]+\.[A-Za-z]{2,})(?![A-Za-z0-9_.-])',
                          r'<a href="/@\1@\2" class="u-url mention">@\1@\2</a>', text_str)
        new_text = re.sub(r'(?<![A-Za-z0-9_.-="/])@([A-Za-z0-9_.-]+)(?!@[A-Za-z0-9_.-]+\.)(?!@)(?![A-Za-z0-9_.-])',
                          r'<a href="/@\1" class="u-url mention">@\1</a>', new_text)
        new_text = re.sub(r'(?<![A-Za-z0-9_.-="])#([A-Za-z0-9가-힣_]+)(?![A-Za-z0-9_.-])',
                          lambda m: f'<a href="/explore?q={quote(f"#{m.group(1)}")}" rel="tag" class="mention hashtag">#{m.group(1)}</a>', new_text)
        if new_text != text_str:
            new_soup = BeautifulSoup(new_text, "html.parser")
            for child in list(new_soup.contents):
                text_node.insert_before(child.extract())
            text_node.extract()

    # 6. 복원: 보호했던 코드 블록 다시 삽입
    final_html = str(soup)
    for i, block in enumerate(code_blocks):
        final_html = final_html.replace(f'\x00codeblock_{i}\x00', block)

    # 7. 최종 마무리
    soup = BeautifulSoup(final_html, "html.parser")
    _finalize_html(soup)
    return _serialize_html(soup)


def extract_mentions_from_remote(post: dict) -> list[dict]:
    """ActivityPub 데이터에서 멘션된 유저의 handle과 href 정보를 추출합니다."""
    obj_data = post.get("object", post) if isinstance(post.get("object"), dict) else post
    raw_tags = obj_data.get("tag", []) or []

    mentions = []
    # 중복 방지를 위한 딕셔너리 키 기반 관리
    seen_handles = set()

    for t in raw_tags:
        if isinstance(t, dict) and t.get("type") == "Mention":
            handle = t.get("name")
            href = t.get("href")
            if handle and href and handle not in seen_handles:
                mentions.append({
                    "handle": handle.strip(),
                    "href": href.strip()
                })
                seen_handles.add(handle)
    return mentions


def extract_mentions_from_local(text: str) -> list[dict]:
    # 1. 풀 핸들: @user@domain (우선순위 높음)
    full_pattern = r'@([A-Za-z0-9_.-]+)@([A-Za-z0-9_.-]+\.[A-Za-z]{2,})'
    # 2. 단축 핸들: @user (도메인 형식이 뒤에 붙지 않는 경우만 매칭)
    # (?!...) : 뒤에 @domain 형태가 오지 않아야 함
    short_pattern = r'(?<![A-Za-z0-9_./])@([A-Za-z0-9_.-]+)(?!@[A-Za-z0-9_.-]+\.[A-Za-z]{2,})'

    mentions = []
    seen_handles = set()

    # 풀 핸들 매칭
    for m in re.finditer(full_pattern, text):
        handle = f"@{m.group(1)}@{m.group(2)}"
        if handle not in seen_handles:
            mentions.append({
                "handle": handle,
                "href": f'https://{m.group(2)}/users/{m.group(1)}'
            })
            seen_handles.add(handle)

    # 단축 핸들 매칭
    for m in re.finditer(short_pattern, text):
        user_part = m.group(1) # @ 제외한 순수 유저명
        handle = f"@{user_part}"
        if handle not in seen_handles:
            mentions.append({
                "handle": f"@{user_part}@{BASE_URL}",
                "href": f'https://{BASE_URL}/users/{user_part}'
            })
            seen_handles.add(handle)
    return mentions


def _save_code_block(m):
    code_blocks.append(f'<pre><code>{m.group(2).rstrip()}</code></pre>')
    return f'\x00codeblock_{len(code_blocks) - 1}\x00'


def _make_internal_link(match, label):
    url = match.group(1)
    parsed = urlparse(url)
    # 만약 우리 도메인 내부 URL이라면 경로(path)만 추출 (예: /series/1/episodes/1)
    # 외부 도메인이라면 원본 URL 그대로 유지
    path = parsed.path if parsed.path else url
    return f'{label}: <a href="{path}" class="u-url {label}-link">{url}</a>'

