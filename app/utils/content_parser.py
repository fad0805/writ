import re
from urllib.parse import quote, unquote

import nh3
from bs4 import BeautifulSoup, NavigableString

from app.models import Post

def _sanitize_html(html: str) -> str:
    """Strip dangerous HTML tags/attributes, keep only safe ones."""
    if not html:
        return ""
    # ActivityPub(마스토돈, 미스키 등)에서 흔히 사용하는 안전한 태그 목록
    allowed_tags = {
        "a", "p", "br", "span", "b", "i", "strong", "em", 
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

def _extract_plain_text(sanitized_content: str, post: dict | Post | None) -> str:
    if not sanitized_content:
        return ""

    # [수정 포인트 1] 무거운 객체 검사 및 데이터 추출은 루프 밖에서 딱 '한 번만' 수행합니다.
    mentioned_user_ids = []
    tag_names = []  # 순수 해시태그 문자열만 담을 리스트

    if post and isinstance(post, dict):
        # 액티비티펍 인박스 웹훅 대응 (내부에 object가 있으면 언패킹)
        obj_data = post.get("object", post) if isinstance(post.get("object"), dict) else post
        raw_tags = obj_data.get("tag", []) or []
        # 딕셔너리 구조에서 필요한 값만 정확히 매핑
        for t in raw_tags:
            if not isinstance(t, dict):
                continue
            t_type = t.get("type")
            t_name = t.get("name", "")
            if t_type == "Mention" and t_name:
                mentioned_user_ids.append(t_name.strip())
            elif t_type == "Hashtag" and t_name:
                tag_names.append(t_name.replace("#", "").strip())
    elif post and hasattr(post, "mentioned_user_ids"):  # SQLAlchemy Post 모델 대응
        mentioned_user_ids = getattr(post, "mentioned_user_ids", []) or []
        raw_tags = getattr(post, "tag_list", []) or []
        tag_names = [str(t) for t in raw_tags if t]

    # 1. 생짜 URL을 a 태그로 변환
    url_pattern = r'(?<!href=")(?<!src=")(?<!">)(https?://(?!.*/tags/)[^\s<>"\')\]#]+)'
    def _repl_raw_url(m):
        url = m.group(1)
        display = re.sub(r'^https?://', '', url)
        if len(display) > 40:
            display = display[:37] + "..."
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{display}</a>'
    sanitized_content = re.sub(url_pattern, _repl_raw_url, sanitized_content)

    soup = BeautifulSoup(sanitized_content, "html.parser")

    # 2. 이미 존재하는 모든 <a> 태그를 찾아서 안전하게 리모델링
    for a_tag in soup.find_all("a"):
        text = a_tag.get_text().strip()
        raw_href = a_tag.get("href", "")
        if isinstance(raw_href, list):
            raw_href = " ".join(raw_href)
        raw_href = raw_href.strip()

        # 멘션 매칭을 위한 방어적 텍스트 정제
        raw_username = text.lstrip('@').lower()
        href_lower = raw_href.lower()

        # 2-0. 언급된 유저 목록(mentioned_user_ids)과 매칭 시도
        is_mention_matched = False
        matched_uid = None

        for uid in mentioned_user_ids:
            uid_lower = uid.lower()
            # 풀 핸들에서 도메인을 떼어낸 순수 username 추출 (ex: @siarte@daydream.ink -> siarte)
            pure_username = uid_lower.lstrip('@').split('@')[0]
            # 조건 1: 태그 안의 텍스트가 풀 핸들과 같거나, 도메인이 없는 유저명과 같을 때
            # 조건 2: 태그의 href 주소에 유저명이 포함되어 있거나 풀 핸들 자체가 매칭될 때
            if (raw_username == pure_username or uid_lower == text.lower() or 
                pure_username in href_lower or uid_lower in href_lower):
                is_mention_matched = True
                matched_uid = uid  # 원래 대소문자가 유지된 풀 핸들 선택
                break

        # 매칭 성공 시 우리 서비스 규격에 맞게 리모델링
        if is_mention_matched and matched_uid:
            a_tag.clear()
            a_tag.string = matched_uid
            a_tag["href"] = f"/{matched_uid}"
            a_tag["class"] = "mention"
            a_tag.attrs.pop("target", None)
            continue

        # [예외 방어] 데이터 바인딩이 누락되었으나 원격 주소 형태인 경우 (Fallback 1)
        if text.startswith('@') and raw_href.startswith('http'):
            remote_url_match = re.match(r'https?://([^/]+)/(?:@|users/)([A-Za-z0-9_.-]+)', raw_href, re.IGNORECASE)
            if remote_url_match:
                domain = remote_url_match.group(1).lower()
                username = remote_url_match.group(2)
                a_tag.clear()
                a_tag.string = f"@{username}@{domain}"
                a_tag["href"] = f"/@{username}@{domain}"
                a_tag["class"] = "mention"
                a_tag.attrs.pop("target", None)
                continue

        # 해시태그 처리
        if text.startswith('#'):
            tag_name_match = re.search(r'#([^\s#@<]+)', text)
            if tag_name_match:
                tag_name = tag_name_match.group(1)
                if not tag_names or tag_name.lower() in [t.lower() for t in tag_names]:
                    a_tag.clear()
                    a_tag.string = f"#{tag_name}"
                    a_tag["href"] = f"/explore?q={quote(f'#{tag_name}')}"
                    a_tag["class"] = "hashtag"
                    a_tag.attrs.pop("target", None)
                    continue

        # 일반 URL인 경우
        if text and re.match(r'^https?://', text):
            display = re.sub(r'^https?://', '', text)
            if len(display) > 40:
                display = display[:37] + "..."
            a_tag.clear()
            a_tag.string = display

    # 3. <a> 태그 밖에 쌩으로 굴러다니는 핸들 & 해시태그 텍스트 처리
    for text_node in list(soup.find_all(string=True)):
        if not text_node.parent:
            continue
        if text_node.find_parent("a"):
            continue

        text_str = str(text_node)
        # 1) 풀 핸들 변환: 뒤에 도메인이 확실히 붙어있는 경우
        new_text = re.sub(
            r'(?<![A-Za-z0-9_.-])@([A-Za-z0-9_.-]+)@([A-Za-z0-9_.-]+\.[A-Za-z]{2,})',
            r'<a href="/@\1@\2" class="mention">@\1@\2</a>',
            text_str
        )
        # 2) 단축 핸들 변환: 'href="/@' 내부에 있거나 이미 변환된 풀 핸들의 일부가 아닌 녀석만 골라냅니다.
        # (?!@[A-Za-z0-9_.-]+\.) 패턴을 넣어 뒤에 도메인이 이어지는 구조를 원천 차단합니다.
        new_text = re.sub(
            r'(?<![A-Za-z0-9_.-])@([A-Za-z0-9_.-]+)(?!@[A-Za-z0-9_.-]+\.)(?!@)',
            r'<a href="/@\1" class="mention">@\1</a>',
            new_text
        )
        if tag_names:
            escaped_tags = [re.escape(t) for t in sorted(tag_names, key=len, reverse=True)]
            tags_pattern = r'(?<![A-Za-z0-9_.-])#(' + '|'.join(escaped_tags) + r')(?![A-Za-z0-9_.-])'
            new_text = re.sub(
                tags_pattern,
                lambda m: f'<a href="/explore?q={quote(f"#{m.group(1)}")}" class="hashtag">#{m.group(1)}</a>',
                new_text
            )
        if new_text != text_str:
            new_soup = BeautifulSoup(new_text, "html.parser")
            for child in list(new_soup.contents):
                text_node.insert_before(child.extract())
            text_node.extract()

    # 줄바꿈 보존 작업
    for br in list(soup.find_all("br")):
        br.replace_with("\n")
    for tag in list(soup.find_all(["p", "div"])):
        tag.insert_before("\n")
        tag.insert_after("\n")

    # 4. 직렬화
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
                    except Exception:
                        pass
                attrs_list.append(f'{k}="{val}"')
            attrs_str = f" {' '.join(attrs_list)}" if attrs_list else ""
            children_str = "".join(_to_html(c) for c in list(node.children))
            return f"<a{attrs_str}>{children_str}</a>"
        return "".join(_to_html(c) for c in list(node.children))

    result = "".join(_to_html(c) for c in list(soup.contents))
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()
