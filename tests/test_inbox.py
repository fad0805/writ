"""Inbox processing tests.

Includes a full HTTP round-trip (signed POST to /users/{username}/inbox) for the
Follow activity, which resolves locally and never touches the network (local
inboxes fail validate_url's SSRF guard, so the Accept delivery early-returns).
"""

import base64
import hashlib
import email.utils
import json


from app.core.activitypub._inbound import handle_inbox, _mark_activity_processed, _is_activity_processed
from app.db.database import get_session
from app.models import Follow
from app.utils.crypto import sign_string


def _signed_post(client, username, user, body, path=None):
    """POST a signed ActivityPub body to a user's inbox."""
    date = email.utils.formatdate(usegmt=True)
    digest = "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode()
    actor_uri = user.actor_uri()
    target_path = path or f"/users/{username}/inbox"
    signed_string = "\n".join([
        f"(request-target): post {target_path}",
        "host: localhost:3000",
        f"date: {date}",
        f"digest: {digest}",
    ])
    sig = sign_string(signed_string, user.private_key)
    signature_header = (
        f'keyId="{actor_uri}#main-key",algorithm="rsa-sha256",'
        f'headers="(request-target) host date digest",signature="{sig}"'
    )
    headers = {
        "Date": date,
        "Host": "localhost:3000",
        "Digest": digest,
        "Signature": signature_header,
        "Content-Type": "application/activity+json",
    }
    return client.post(target_path, content=body, headers=headers)


def test_handle_inbox_unknown_type(make_user):
    alice = make_user("alice")
    status, message = handle_inbox({"type": "ComicRelief", "actor": alice.actor_uri()})
    assert status == 202
    assert "ComicRelief" in message


def test_handle_inbox_missing_actor():
    status, _ = handle_inbox({"type": "Follow"})
    assert status == 400


def test_follow_roundtrip_creates_follow(client, make_user):
    follower = make_user("remote_follower")
    target = make_user("target")
    body = json.dumps({
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{follower.actor_uri()}/follows/1",
        "type": "Follow",
        "actor": follower.actor_uri(),
        "object": target.actor_uri(),
    }).encode()
    r = _signed_post(client, target.username, follower, body)
    assert r.status_code == 200
    assert r.json()["status"] == 200

    with get_session() as s:
        follow = s.query(Follow).filter_by(
            follower_id=follower.id, following_id=target.id
        ).first()
        assert follow is not None
        assert follow.accepted is True


def test_follow_to_unknown_user_returns_404(client, make_user):
    follower = make_user("remote_follower")
    body = json.dumps({
        "id": f"{follower.actor_uri()}/follows/2",
        "type": "Follow",
        "actor": follower.actor_uri(),
        "object": "http://localhost:3000/users/nobody",
    }).encode()
    r = _signed_post(client, "nobody", follower, body)
    assert r.status_code == 404


def test_inbox_rejects_unsigned_request(client, make_user):
    target = make_user("target")
    body = json.dumps({"type": "Follow", "actor": "http://localhost:3000/users/x", "object": target.actor_uri()}).encode()
    r = client.post(f"/users/{target.username}/inbox", content=body, headers={"Content-Type": "application/activity+json"})
    assert r.status_code == 401


def test_activity_dedup(client, make_user):
    follower = make_user("dedup_follower")
    target = make_user("dedup_target")
    body = json.dumps({
        "id": f"{follower.actor_uri()}/follows/99",
        "type": "Follow",
        "actor": follower.actor_uri(),
        "object": target.actor_uri(),
    }).encode()
    assert _signed_post(client, target.username, follower, body).status_code == 200
    # Same activity id processed twice -> second attempt is a no-op (still 200).
    assert _signed_post(client, target.username, follower, body).status_code == 200


def test_mark_and_check_processed():
    activity_id = "http://example.test/activities/abc123"
    assert _is_activity_processed(activity_id) is False
    _mark_activity_processed(activity_id)
    assert _is_activity_processed(activity_id) is True
