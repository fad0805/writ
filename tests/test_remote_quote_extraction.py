"""Remote quote post (인용) 추출 회귀 테스트.

https://writ.daydream.ink/post/55869 처럼 마스토돈 포크(quote 지원)에서
넘어온 인용 글의 인용 URL이 quote_of_ap_id로 감지되어야 하고, 본문에 남은
RE:/quote-inline 링크가 제거되어 인용 카드로 렌더링될 수 있어야 한다.
"""

from app.core.activitypub._fetch import _extract_quote_url, _strip_quote_link

QUOTED_AP_ID = "https://sharlayan.in/users/nose2k/statuses/117097837889628434"
QUOTED_WEB_URL = "https://sharlayan.in/@nose2k/117097837889628434"

# 마스토돈 4.7.0-0495d+shrn (Sharlayan 포크) Note 객체의 실제 형태
MASTODON_NOTE_QUOTE_FIELD = {
    "id": "https://sharlayan.in/users/nose2k/statuses/117097852410535313",
    "type": "Note",
    "attributedTo": "https://sharlayan.in/users/nose2k",
    "quote": QUOTED_AP_ID,
    "_misskey_quote": QUOTED_AP_ID,
    "quote_uri": QUOTED_AP_ID,
    "content": (
        "<p>당근빵 이제 잎모양 종이도 안 끼워주는구나...</p>"
        f'<span class="quote-inline">RE: <a href="{QUOTED_WEB_URL}">link</a></span>'
    ),
}

# 일부 구현은 구조화된 quote 필드 없이 본문 HTML에만 인용 링크를 심는다
NOTE_QUOTE_ONLY_IN_CONTENT = {
    "id": "https://other.example/users/alice/statuses/1",
    "type": "Note",
    "attributedTo": "https://other.example/users/alice",
    "content": (
        "<p>본문</p>"
        f'<span class="quote-inline">RE: <a href="{QUOTED_WEB_URL}">link</a></span>'
    ),
}

NOTE_MISSKEY_QUOTE_TAG = {
    "id": "https://misskey.example/notes/1",
    "type": "Note",
    "attributedTo": "https://misskey.example/users/bob",
    "tag": [{
        "type": "Link",
        "rel": "https://misskey-hub.net/ns#_misskey_quote",
        "href": QUOTED_AP_ID,
    }],
    "content": "<p>본문</p>",
}

NO_QUOTE_NOTE = {
    "id": "https://other.example/users/carol/statuses/2",
    "type": "Note",
    "attributedTo": "https://other.example/users/carol",
    "content": "<p>그냥 글</p>",
}


def test_extract_quote_from_mastodon_quote_field():
    url = _extract_quote_url(MASTODON_NOTE_QUOTE_FIELD)
    assert url == QUOTED_AP_ID


def test_extract_quote_from_content_inline_link():
    url = _extract_quote_url(NOTE_QUOTE_ONLY_IN_CONTENT)
    assert url == QUOTED_WEB_URL


def test_extract_quote_from_misskey_tag():
    url = _extract_quote_url(NOTE_MISSKEY_QUOTE_TAG)
    assert url == QUOTED_AP_ID


def test_no_quote_returns_empty():
    assert _extract_quote_url(NO_QUOTE_NOTE) == ""


def test_strip_quote_inline_span():
    content = (
        "<p>당근빵 이제 잎모양 종이도 안 끼워주는구나...</p>"
        f'<span class="quote-inline">RE: <a href="{QUOTED_WEB_URL}">link</a></span>'
    )
    stripped = _strip_quote_link(content, QUOTED_WEB_URL)
    assert 'quote-inline' not in stripped
    assert QUOTED_WEB_URL not in stripped
    assert "당근빵" in stripped


def test_strip_plain_re_link():
    content = f'<p>본문<br>RE: <a href="{QUOTED_WEB_URL}">link</a></p>'
    stripped = _strip_quote_link(content, QUOTED_WEB_URL)
    assert QUOTED_WEB_URL not in stripped
    assert "본문" in stripped


def test_strip_plain_url():
    content = f"<p>본문<br>RE: {QUOTED_WEB_URL}</p>"
    stripped = _strip_quote_link(content, QUOTED_WEB_URL)
    assert QUOTED_WEB_URL not in stripped
    assert "본문" in stripped


def test_strip_no_quote_url_unchanged():
    content = "<p>그냥 글</p>"
    assert _strip_quote_link(content, "") == content


def test_extract_quote_normalizes_re_prefix_with_br():
    # 실제 저장본에서 관찰된 형태 (BR 사이에 RE: 링크)
    content = (
        "당근빵 이제 잎모양 종이도 안 끼워주는구나...<br>"
        f'<br><br><span class="quote-inline">RE: <a href="{QUOTED_WEB_URL}">'
        f"{QUOTED_WEB_URL}</a></span>"
    )
    url = _extract_quote_url({}, content)
    assert url == QUOTED_WEB_URL
    stripped = _strip_quote_link(content, url)
    assert QUOTED_WEB_URL not in stripped
    assert "당근빵" in stripped
