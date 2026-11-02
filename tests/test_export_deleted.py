"""Account export must not include deleted posts, but should include live boosts."""

import csv
import io
import json
import zipfile

from app.db.database import get_session
from app.models import Post


def _add_boost_pointer(author_id: int, original_id: int) -> int:
    with get_session() as s:
        pointer = Post(
            author_id=author_id,
            content="",
            visibility="public",
            boost_of_id=original_id,
            ap_id=f"https://remote.example/boost/{original_id}",
        )
        s.add(pointer)
        s.commit()
        return pointer.id


def _mark_deleted(post_id: int) -> None:
    with get_session() as s:
        post = s.query(Post).get(post_id)
        post.is_deleted = True
        s.commit()


def test_archive_includes_boosted_original_and_excludes_deleted(client, auth_cookie, make_user, make_post):
    alice, cookie = auth_cookie("alice")
    bob = make_user("bob")
    keep = make_post(alice, content="<p>keep</p>")
    gone = make_post(alice, content="<p>gone</p>")
    boosted = make_post(bob, content="<p>boosted original</p>")
    deleted_original = make_post(bob, content="<p>deleted original</p>")
    boost_id = _add_boost_pointer(alice.id, boosted.id)
    deleted_boost_id = _add_boost_pointer(alice.id, deleted_original.id)

    assert client.post(f"/api/posts/{gone.id}/delete", cookies=cookie).status_code == 200
    _mark_deleted(deleted_original.id)

    r = client.get("/api/settings/export-archive", cookies=cookie)
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    posts = json.loads(z.read("posts.json"))
    ids = {p["id"] for p in posts}
    assert keep.id in ids
    assert boosted.id in ids
    assert gone.id not in ids
    assert deleted_original.id not in ids
    assert boost_id not in ids
    assert deleted_boost_id not in ids

    boosted_entry = next(p for p in posts if p["id"] == boosted.id)
    assert "boosted original" in boosted_entry["content"]
    assert boosted_entry["type"] == "boost"
    assert boosted_entry["boosted"] is True
    assert boosted_entry["boost_of_author"] == bob.username
    keep_entry = next(p for p in posts if p["id"] == keep.id)
    assert keep_entry["type"] == "post"
    assert keep_entry["boosted"] is False


def test_posts_csv_includes_boosted_original_and_excludes_deleted(client, auth_cookie, make_user, make_post):
    alice, cookie = auth_cookie("alice")
    bob = make_user("bob")
    make_post(alice, content="<p>keep</p>")
    gone = make_post(alice, content="<p>gone</p>")
    boosted = make_post(bob, content="<p>boosted original</p>")
    deleted_original = make_post(bob, content="<p>deleted original</p>")
    _add_boost_pointer(alice.id, boosted.id)
    _add_boost_pointer(alice.id, deleted_original.id)

    client.post(f"/api/posts/{gone.id}/delete", cookies=cookie)
    _mark_deleted(deleted_original.id)

    r = client.get("/api/settings/export/posts", cookies=cookie)
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 2  # keep + boosted original
    assert any(row["type"] == "post" and "keep" in row["content"] for row in rows)
    boost_row = next(row for row in rows if row["type"] == "boost")
    assert "boosted original" in boost_row["content"]
    assert boost_row["boost_of_author"] == bob.username
    assert boost_row["boosted_at"]
    assert all("gone" not in row["content"] for row in rows)
    assert all("deleted original" not in row["content"] for row in rows)


def test_bookmarks_csv_and_count_exclude_deleted_posts(client, auth_cookie, make_post):
    alice, cookie = auth_cookie("alice")
    keep = make_post(alice, content="<p>keep</p>")
    gone = make_post(alice, content="<p>gone</p>")
    assert client.post(f"/api/posts/{keep.id}/bookmark", cookies=cookie).status_code == 200
    assert client.post(f"/api/posts/{gone.id}/bookmark", cookies=cookie).status_code == 200
    client.post(f"/api/posts/{gone.id}/delete", cookies=cookie)

    r = client.get("/api/settings/export/bookmarks", cookies=cookie)
    assert r.status_code == 200
    assert f"/@x/{keep.id}" in r.text
    assert f"/@x/{gone.id}" not in r.text

    counts = client.get("/api/settings/export-counts", cookies=cookie).json()
    bookmark_count = next(item["count"] for item in counts["items"] if item["key"] == "bookmarks")
    assert bookmark_count == 1
