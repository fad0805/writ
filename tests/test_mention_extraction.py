"""Unit tests for mention extraction and remote mention name sanitization.

Covers extract_mentions_from_local (full vs short handles, word boundaries) and
the stored-XSS fix that rejects attribute-escape characters in remote Mention
names (commit a1b2c3: _MENTION_NAME_RE guard).
"""
from app.utils.content_parser import (
    _MENTION_NAME_RE,
    extract_mentions_from_local,
    process_remote_post,
)

LOCAL = "localhost:3000"


def test_short_handle_uses_local_domain():
    result = extract_mentions_from_local("hi @alice")
    assert result == [{"handle": f"@alice@{LOCAL}", "href": f"https://{LOCAL}/users/alice"}]


def test_full_handle_keeps_remote_domain():
    result = extract_mentions_from_local("cc @mallory@example.com")
    assert result == [{"handle": "@mallory@example.com", "href": "https://example.com/users/mallory"}]


def test_mixed_full_and_short_handles():
    result = extract_mentions_from_local("Hey @alice, see @mallory@example.com")
    handles = [m["handle"] for m in result]
    assert handles == ["@mallory@example.com", f"@alice@{LOCAL}"]


def test_full_handle_is_not_split_into_short_mentions():
    result = extract_mentions_from_local("talk to @mallory@example.com please")
    assert len(result) == 1
    assert result[0]["handle"] == "@mallory@example.com"


def test_email_address_is_not_a_mention():
    # '@example.com' is preceded by a word char, so it must not match
    assert extract_mentions_from_local("contact foo@example.com") == []


def test_duplicate_handles_are_deduplicated():
    result = extract_mentions_from_local("@alice hi @alice")
    assert len(result) == 1


def test_username_with_dot_dash_underscore():
    result = extract_mentions_from_local("@a.b-c_d")
    assert result == [{"handle": f"@a.b-c_d@{LOCAL}", "href": f"https://{LOCAL}/users/a.b-c_d"}]


def test_mention_name_re_accepts_legit_names():
    assert _MENTION_NAME_RE.match("@user")
    assert _MENTION_NAME_RE.match("user")
    assert _MENTION_NAME_RE.match("@user@example.com")
    assert _MENTION_NAME_RE.match("@user@example.co.uk")


def test_mention_name_re_rejects_attribute_escape_chars():
    # Stored-XSS payloads: quotes, angle brackets, etc. must be rejected
    for bad in (
        '"><script>alert(1)</script>',
        '@user" onmouseover="alert(1)',
        "@user'",
        "<img src=x onerror=alert(1)>",
        "@user;drop table",
    ):
        assert not _MENTION_NAME_RE.match(bad), f"should reject {bad!r}"


def test_mention_name_re_accepts_name_with_trailing_whitespace():
    # the caller strips the name before matching (content_parser._process)
    assert _MENTION_NAME_RE.match("@user\n")


def test_remote_post_drops_malicious_mention_name():
    post = {
        "id": "http://evil.example/activities/1",
        "attributedTo": "http://evil.example/users/bad",
        "object": {
            "type": "Note",
            "content": '<p>hi <a href="http://evil.example/@bad" class="mention">@bad</a></p>',
            "tag": [
                {"type": "Mention", "name": '@bad"><img src=x onerror="alert(1)">', "href": "http://evil.example/@bad"},
            ],
        },
    }
    html = process_remote_post('<p>hi <a href="http://evil.example/@bad">@bad</a></p>', post)
    assert "<img" not in html
    assert "onerror" not in html
    assert "alert(1)" not in html


def test_remote_post_accepts_legit_mention_name():
    post = {
        "id": "http://mastodon.example/activities/1",
        "attributedTo": "http://mastodon.example/users/friend",
        "object": {
            "type": "Note",
            "content": '<p>hello <a href="http://mastodon.example/@friend" class="mention">@friend</a></p>',
            "tag": [{"type": "Mention", "name": "@friend@mastodon.example", "href": "http://mastodon.example/@friend"}],
        },
    }
    html = process_remote_post('<p>hello <a href="http://mastodon.example/@friend">@friend</a></p>', post)
    assert "@friend" in html


def test_remote_span_content_not_turned_into_img():
    # Misskey notes wrap text in <span>; the serializer must keep the text
    # instead of collapsing the node into a bare <img>.
    post = {
        "id": "https://madost.one/notes/apw8df8r11",
        "attributedTo": "https://madost.one/users/805dgm8rlz",
        "tag": [],
    }
    html = process_remote_post("<p><span>오늘 날씨가 좋네요</span></p>", post)
    assert "오늘 날씨가 좋네요" in html
    assert html != "<img>"


def test_remote_img_with_attrs_is_kept():
    post = {
        "id": "https://example.com/notes/1",
        "attributedTo": "https://example.com/users/u",
        "tag": [],
    }
    html = process_remote_post('<p><img src="https://example.com/a.png" alt="a"></p>', post)
    assert '<img src="https://example.com/a.png" alt="a">' in html
