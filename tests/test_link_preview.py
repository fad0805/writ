"""링크 미리보기(/api/link-preview) 테스트.

YouTube watch 페이지는 1.3MB라 OG 스캔의 1MB 상한(_meta.api_link_preview의
max_size)에 걸려 제목/썸네일을 못 얻는다. oEmbed fast path가 이걸 우회하는지
회귀를 막는다.
"""

import json

import pytest

import app.routes.api._meta as meta_mod
from app.routes.api._meta import _youtube_video_url

OEMBED = {
    "title": "Rick Astley - Never Gonna Give You Up (Official Video)",
    "author_name": "Rick Astley",
    "type": "video",
    "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
}


class _Resp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


def _oauthed(make_user, monkeypatch, fetch):
    """로그인 세션 + 네트워크를 가로챈 쿠키."""
    user = make_user("alice")
    from app.core.auth import create_session

    monkeypatch.setattr(meta_mod, "validated_get", fetch)
    return {"session": create_session(user.id)}


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&t=30s",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=42",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
    ],
)
def test_youtube_video_url_normalizes(url):
    assert _youtube_video_url(url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/channel/UC123",
        "https://www.youtube.com.evil.test/watch?v=dQw4w9WgXcQ",
        "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
        "https://example.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_youtube_video_url_rejects(url):
    assert _youtube_video_url(url) == ""


def test_youtube_preview_uses_oembed(client, make_user, monkeypatch):
    """oEmbed로 제목·채널명·썸네일을 받고, watch 페이지 HTML은 받지 않는다."""
    calls = []

    def _fetch(url, **kw):
        calls.append(url)
        return _Resp(json.dumps(OEMBED))

    cookies = _oauthed(make_user, monkeypatch, _fetch)
    r = client.post("/api/link-preview", data={"url": "https://youtu.be/dQw4w9WgXcQ"}, cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == OEMBED["title"]
    assert body["site_name"] == "Rick Astley"
    assert body["kind"] == "video"
    assert body["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    # 16:9 썸네일 (oEmbed의 4:3 hqdefault가 아님)
    assert body["image"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg"
    assert all("youtube.com/oembed" in c for c in calls)


def test_youtube_preview_falls_back_to_domain_on_oembed_failure(client, make_user, monkeypatch):
    """oEmbed가 실패하면 기존처럼 도메인 제목을 돌려준다 (500 아님)."""
    cookies = _oauthed(make_user, monkeypatch, lambda url, **kw: None)
    r = client.post(
        "/api/link-preview", data={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}, cookies=cookies
    )
    assert r.status_code == 200
    assert r.json()["title"] == "www.youtube.com"


def test_youtube_preview_falls_back_on_malformed_oembed(client, make_user, monkeypatch):
    cookies = _oauthed(make_user, monkeypatch, lambda url, **kw: _Resp("<html>rate limited</html>"))
    r = client.post(
        "/api/link-preview", data={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}, cookies=cookies
    )
    assert r.status_code == 200
    assert r.json()["title"] == "www.youtube.com"


def test_non_youtube_still_uses_og_tags(client, make_user, monkeypatch):
    """YouTube가 아닌 링크의 기존 OG 파싱 경로는 그대로 동작한다."""
    page = (
        '<html><head><meta property="og:title" content="뉴스 제목">'
        '<meta property="og:description" content="요약 문장">'
        '<meta property="og:image" content="https://news.example.com/x.png">'
        "</head></html>"
    )
    calls = []

    def _fetch(url, **kw):
        calls.append(url)
        return _Resp(page)

    cookies = _oauthed(make_user, monkeypatch, _fetch)
    r = client.post("/api/link-preview", data={"url": "https://news.example.com/x"}, cookies=cookies)
    body = r.json()
    assert body["title"] == "뉴스 제목"
    assert body["description"] == "요약 문장"
    assert body["image"] == "https://news.example.com/x.png"
    assert body.get("kind") is None
    assert calls == ["https://news.example.com/x"]


def test_requires_auth(client):
    r = client.post("/api/link-preview", data={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert r.status_code in (401, 403)
