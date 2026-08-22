"""HTTP signature verification tests for the ActivityPub inbox path.

Signs requests with a user's real RSA key (mirroring the wire format produced
by app/core/activitypub/_outbound.py) and asserts on accept/reject behavior.
"""

import base64
import email.utils
import hashlib

from starlette.requests import Request

from app.core.activitypub._signature import _validate_inbox_activity, verify_http_signature
from app.utils.crypto import sign_string

SIGNED_HEADERS = "(request-target) date host digest"
INBOX_PATH = "/inbox"


def _make_request(path, headers, body=b""):
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "scheme": "http",
        "server": ("localhost", 3000),
        "client": ("127.0.0.1", 12345),
        "http_version": "1.1",
        "root_path": "",
    }

    async def _receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, _receive)


def _signed_request(user, body, date=None):
    actor_uri = user.actor_uri()
    activity = {
        "type": "Create",
        "actor": actor_uri,
        "id": f"{actor_uri}/activities/1",
        "object": {"id": f"{actor_uri}/posts/1", "type": "Note"},
    }
    date = date or email.utils.formatdate(usegmt=True)
    digest = "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode()
    host = "localhost:3000"
    signed_lines = [
        "(request-target): post /inbox",
        f"date: {date}",
        f"host: {host}",
        f"digest: {digest}",
    ]
    signed_string = "\n".join(signed_lines)
    sig = sign_string(signed_string, user.private_key)
    signature_header = (
        f'keyId="{actor_uri}#main-key",algorithm="rsa-sha256",'
        f'headers="{SIGNED_HEADERS}",signature="{sig}"'
    )
    headers = {
        "Date": date,
        "Host": host,
        "Digest": digest,
        "Signature": signature_header,
    }
    return _make_request(INBOX_PATH, headers, body), activity


def test_missing_signature_header_rejected(make_user):
    make_user("alice")
    body = b"{}"
    req = _make_request(INBOX_PATH, {"Date": email.utils.formatdate(usegmt=True), "Host": "localhost:3000"}, body)
    ok, actor = verify_http_signature(req, body, {"type": "Create"})
    assert ok is False
    assert actor is None


def test_missing_digest_rejected(make_user):
    user = make_user("alice")
    actor_uri = user.actor_uri()
    body = b'{"type":"Create"}'
    date = email.utils.formatdate(usegmt=True)
    # Valid signature over date+host only, but no Digest header for the body.
    signed_string = f"(request-target): post /inbox\ndate: {date}\nhost: localhost:3000"
    sig = sign_string(signed_string, user.private_key)
    signature_header = (
        f'keyId="{actor_uri}#main-key",algorithm="rsa-sha256",'
        f'headers="(request-target) date host",signature="{sig}"'
    )
    headers = {"Date": date, "Host": "localhost:3000", "Signature": signature_header}
    req = _make_request(INBOX_PATH, headers, body)
    ok, _ = verify_http_signature(req, body, {"type": "Create", "actor": actor_uri})
    assert ok is False


def test_valid_signature_accepted(make_user):
    user = make_user("alice")
    body = b'{"type":"Create","actor":"alice"}'
    req, activity = _signed_request(user, body)
    ok, actor = verify_http_signature(req, body, activity)
    assert ok is True
    assert actor is not None
    assert actor.id == user.id


def test_tampered_body_rejected(make_user):
    user = make_user("alice")
    body = b'{"type":"Create"}'
    req, activity = _signed_request(user, body)
    # Re-verify with a *different* body than the one signed.
    ok, _ = verify_http_signature(req, b'{"type":"Create","evil":true}', activity)
    assert ok is False


def test_wrong_key_rejected(make_user):
    attacker = make_user("attacker")
    victim = make_user("victim")
    body = b'{"type":"Create"}'
    # Build the request as if the victim's actor, but sign with attacker's key.
    req, activity = _signed_request(victim, body)
    actor_uri = victim.actor_uri()
    digest = "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode()
    date = email.utils.formatdate(usegmt=True)
    signed_string = "\n".join([
        "(request-target): post /inbox",
        f"date: {date}",
        "host: localhost:3000",
        f"digest: {digest}",
    ])
    sig = sign_string(signed_string, attacker.private_key)
    signature_header = (
        f'keyId="{actor_uri}#main-key",algorithm="rsa-sha256",'
        f'headers="{SIGNED_HEADERS}",signature="{sig}"'
    )
    headers = {"Date": date, "Host": "localhost:3000", "Digest": digest, "Signature": signature_header}
    req = _make_request(INBOX_PATH, headers, body)
    ok, _ = verify_http_signature(req, body, activity)
    assert ok is False


def test_stale_date_rejected(make_user):
    user = make_user("alice")
    body = b'{"type":"Create"}'
    stale = email.utils.formatdate(timeval=email.utils.mktime_tz(email.utils.parsedate_tz("Wed, 01 Jan 2020 00:00:00 GMT")), usegmt=True)
    req, activity = _signed_request(user, body, date=stale)
    ok, _ = verify_http_signature(req, body, activity)
    assert ok is False


def test_missing_freshness_rejected(make_user):
    """Replay 방어: Date 및 hs2019 created 신선도 기준이 전무하면 거부."""
    user = make_user("bob")
    body = b'{"type":"Create"}'
    actor_uri = user.actor_uri()
    # hs2019 `created` 없이 `headers`에서도 date를 제외해야 하지만, Date 헤더부터 제거한다.
    digest = "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode()
    host = "localhost:3000"
    signed_lines = [
        "(request-target): post /inbox",
        f"host: {host}",
        f"digest: {digest}",
    ]
    signed_string = "\n".join(signed_lines)
    sig = sign_string(signed_string, user.private_key)
    signature_header = (
        f'keyId="{actor_uri}#main-key",algorithm="rsa-sha256",'
        f'headers="(request-target) host digest",signature="{sig}"'
    )
    headers = {
        "Host": host,
        "Digest": digest,
        "Signature": signature_header,
    }
    req = _make_request(INBOX_PATH, headers, body)
    ok, _ = verify_http_signature(req, body, {"type": "Create", "actor": actor_uri})
    assert ok is False


def test_hs2019_created_param_timestamp_accepted(make_user):
    """hs2019 `created` 파라미터가 신선하면 Date 없이도 통과해야 한다."""
    import time as _time
    user = make_user("carol")
    body = b'{"type":"Create"}'
    actor_uri = user.actor_uri()
    created = str(int(_time.time()))
    digest = "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode()
    host = "localhost:3000"
    signed_lines = [
        "(request-target): post /inbox",
        f"host: {host}",
        f"digest: {digest}",
        f"(request-created): {created}",
    ]
    signed_string = "\n".join(signed_lines)
    sig = sign_string(signed_string, user.private_key)
    signature_header = (
        f'keyId="{actor_uri}#main-key",algorithm="rsa-sha256",'
        f'headers="(request-target) host digest (request-created)",'
        f'created="{created}",signature="{sig}"'
    )
    headers = {
        "Host": host,
        "Digest": digest,
        "Signature": signature_header,
    }
    req = _make_request(INBOX_PATH, headers, body)
    ok, _ = verify_http_signature(req, body, {"type": "Create", "actor": actor_uri})
    assert ok is True


def test_stale_created_param_rejected(make_user):
    """hs2019 `created` 파라미터가 오래됐으면 Date 없이는 거부해야 한다."""
    import time as _time
    user = make_user("dave")
    body = b'{"type":"Create"}'
    actor_uri = user.actor_uri()
    created = str(int(_time.time()) - 7200)
    digest = "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode()
    host = "localhost:3000"
    signed_lines = [
        "(request-target): post /inbox",
        f"host: {host}",
        f"digest: {digest}",
        f"(request-created): {created}",
    ]
    signed_string = "\n".join(signed_lines)
    sig = sign_string(signed_string, user.private_key)
    signature_header = (
        f'keyId="{actor_uri}#main-key",algorithm="rsa-sha256",'
        f'headers="(request-target) host digest (request-created)",'
        f'created="{created}",signature="{sig}"'
    )
    headers = {
        "Host": host,
        "Digest": digest,
        "Signature": signature_header,
    }
    req = _make_request(INBOX_PATH, headers, body)
    ok, _ = verify_http_signature(req, body, {"type": "Create", "actor": actor_uri})
    assert ok is False


def test_signature_bind_check_rejects_actor_spoofing(make_user):
    """The signer's keyId must match activity.actor — spoofing must fail."""
    user = make_user("alice")
    body = b'{"type":"Create"}'
    req, activity = _signed_request(user, body)
    # Re-verify with activity.actor pointing at someone else.
    activity["actor"] = "http://localhost:3000/users/carol"
    ok, _ = verify_http_signature(req, body, activity)
    assert ok is False


# --- _validate_inbox_activity unit tests ---

def test_validate_missing_type():
    err = _validate_inbox_activity({"actor": "http://x/u"})
    assert err is not None
    assert err[0] == 400


def test_validate_missing_actor():
    err = _validate_inbox_activity({"type": "Create", "object": {"id": "http://x/p"}})
    assert err is not None
    assert err[0] == 400


def test_validate_missing_object():
    err = _validate_inbox_activity({"type": "Create", "actor": "http://x/u"})
    assert err is not None
    assert err[0] == 400


def test_validate_undo_actor_mismatch():
    err = _validate_inbox_activity({
        "type": "Undo",
        "actor": "http://x/u1",
        "object": {"type": "Like", "actor": "http://x/u2", "id": "http://x/like1"},
    })
    assert err is not None
    assert err[0] == 403


def test_validate_well_formed_returns_none():
    err = _validate_inbox_activity({
        "type": "Create",
        "actor": "http://x/u",
        "object": {"id": "http://x/p", "type": "Note"},
    })
    assert err is None
