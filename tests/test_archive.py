"""Server-side account archive: profile, series, media, job notification."""

import io
import json
import re
import zipfile
from datetime import timedelta

from app.core.archive import run_archive_job, write_archive
from app.db.database import get_session
from app.models import Episode, Notification, Novel, Post, SeriesNotice, User
from app.utils.storage import get_storage


def test_archive_contains_profile_series_and_media(client, auth_cookie, make_post):
    user, _cookie = auth_cookie("alice")
    storage = get_storage()
    keys = {
        "avatar": "test_archive/avatar.webp",
        "header": "test_archive/header.webp",
        "post": "test_archive/post.webp",
        "inline_post": "test_archive/inline_post.webp",
        "cover": "test_archive/cover.webp",
        "episode": "test_archive/episode.webp",
        "inline_episode": "test_archive/inline_episode.webp",
        "inline_notice": "test_archive/inline_notice.webp",
        "audio": "test_archive/audio.mp3",
    }
    payloads = {
        "avatar": b"avatar-bytes",
        "header": b"header-bytes",
        "post": b"post-photo-bytes",
        "inline_post": b"inline-post-bytes",
        "cover": b"cover-bytes",
        "episode": b"episode-image-bytes",
        "inline_episode": b"inline-episode-bytes",
        "inline_notice": b"inline-notice-bytes",
        "audio": b"audio-bytes",
    }
    urls = {name: storage.save(key, payloads[name]) for name, key in keys.items()}
    post = make_post(user, content=f'<p>with photo</p><img src="{urls["inline_post"]}">')

    try:
        with get_session() as s:
            db_user = s.query(User).get(user.id)
            db_user.summary = "작가 소개"
            db_user.profile_image = urls["avatar"]
            db_user.header_image = urls["header"]
            db_post = s.query(Post).get(post.id)
            db_post.media_attachments = [{"url": urls["post"], "type": "image", "alt": "photo"}]
            novel = Novel(author_id=user.id, title="연재", description="desc", cover_image=urls["cover"])
            s.add(novel)
            s.flush()
            s.add(Episode(
                novel_id=novel.id,
                episode_number=1,
                title="1화",
                content=f'<p>episode</p><img src="{urls["inline_episode"]}">',
                image_urls=[urls["episode"]],
                audio_url=urls["audio"],
            ))
            s.add(SeriesNotice(
                novel_id=novel.id,
                title="공지",
                content=f'<p>notice</p><img src="{urls["inline_notice"]}">',
            ))
            s.commit()

        buf = io.BytesIO()
        write_archive(user.id, buf)
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            names = set(z.namelist())
            profile = json.loads(z.read("profile.json"))
            posts = json.loads(z.read("posts.json"))
            novels = json.loads(z.read("novels.json"))

            assert "manifest.json" not in names
            assert profile["username"] == "alice"
            assert profile["summary"] == "작가 소개"
            assert profile["profile_image_archive"] in names
            assert profile["header_image_archive"] in names
            assert z.read(profile["profile_image_archive"]) == payloads["avatar"]
            assert "password_hash" not in profile
            assert "private_key" not in profile

            post_entry = next(p for p in posts if p["id"] == post.id)
            attachment = post_entry["media_attachments"][0]
            assert attachment["url"] in names
            assert attachment["original_url"] == urls["post"]
            assert z.read(attachment["url"]) == payloads["post"]
            assert urls["inline_post"] not in post_entry["content"]
            inline_post_path = re.search(r'src="(media/[^"]+)"', post_entry["content"]).group(1)
            assert inline_post_path in names
            assert z.read(inline_post_path) == payloads["inline_post"]

            novel_entry = novels[0]
            assert novel_entry["cover_image_archive"] in names
            episode_entry = novel_entry["episodes"][0]
            assert episode_entry["image_urls"][0] in names
            assert episode_entry["audio_url"] in names
            assert z.read(episode_entry["audio_url"]) == payloads["audio"]
            assert urls["inline_episode"] not in episode_entry["content"]
            inline_episode_path = re.search(r'src="(media/[^"]+)"', episode_entry["content"]).group(1)
            assert inline_episode_path in names
            assert z.read(inline_episode_path) == payloads["inline_episode"]
            notice_content = novel_entry["notices"][0]["content"]
            assert urls["inline_notice"] not in notice_content
            inline_notice_path = re.search(r'src="(media/[^"]+)"', notice_content).group(1)
            assert inline_notice_path in names
            assert z.read(inline_notice_path) == payloads["inline_notice"]

            assert len([name for name in names if name.startswith("media/")]) == 9
            assert len(novels) == 1
    finally:
        for key in keys.values():
            storage.delete(key)


def test_archive_resolves_legacy_media_urls(client, auth_cookie, make_post):
    """Absolute URLs from an old host/CDN or without /uploads must still resolve."""
    user, _cookie = auth_cookie("alice")
    storage = get_storage()
    keys = {
        "attachment": "test_archive/legacy_attachment.webp",
        "inline": "test_archive/legacy_inline.webp",
    }
    payloads = {
        "attachment": b"legacy-attachment",
        "inline": b"legacy-inline",
    }
    for name, key in keys.items():
        storage.save(key, payloads[name])
    old_host = "https://old.example.test"
    attachment_url = f"{old_host}/uploads/{keys['attachment']}"
    inline_url = f"https://cdn.example.test/{keys['inline']}"
    post = make_post(user, content=f'<p>legacy</p><img src="{inline_url}">')
    try:
        with get_session() as s:
            db_post = s.query(Post).get(post.id)
            db_post.media_attachments = [{"url": attachment_url, "type": "image", "alt": ""}]
            s.commit()

        buf = io.BytesIO()
        write_archive(user.id, buf)
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            names = set(z.namelist())
            posts = json.loads(z.read("posts.json"))
            entry = next(p for p in posts if p["id"] == post.id)
            attachment = entry["media_attachments"][0]
            assert attachment["url"] in names
            assert z.read(attachment["url"]) == payloads["attachment"]
            assert inline_url not in entry["content"]
            inline_path = re.search(r'src="(media/[^"]+)"', entry["content"]).group(1)
            assert inline_path in names
            assert z.read(inline_path) == payloads["inline"]

        from app.utils.media_refs import collect_referenced_media_keys
        with get_session() as s:
            used = collect_referenced_media_keys(s, storage)
        assert keys["attachment"] in used
        assert keys["inline"] in used
    finally:
        for key in keys.values():
            storage.delete(key)


def test_orphan_cleanup_protects_legacy_media_urls(client, auth_cookie, make_post):
    from app.utils.media_refs import collect_referenced_media_keys

    user, _cookie = auth_cookie("alice")
    storage = get_storage()
    key = "test_archive/legacy_cleanup.webp"
    storage.save(key, b"legacy")
    try:
        make_post(user, content=f'<img src="https://old.example.test/uploads/{key}">')
        with get_session() as s:
            used = collect_referenced_media_keys(s, storage)
        assert key in used
    finally:
        storage.delete(key)


def test_orphan_cleanup_protects_media_embedded_in_content(client, auth_cookie, make_post):
    from app.utils.media_refs import collect_referenced_media_keys

    user, _cookie = auth_cookie("alice")
    storage = get_storage()
    key = "test_archive/inline_cleanup.webp"
    series_key = "test_archive/series_cleanup.webp"
    url = storage.save(key, b"inline")
    series_url = storage.save(series_key, b"series")
    try:
        make_post(user, content=f'<p>keep inline media</p><img src="{url}">')
        with get_session() as s:
            novel = Novel(author_id=user.id, title="보호 테스트")
            s.add(novel)
            s.flush()
            s.add(Episode(
                novel_id=novel.id,
                episode_number=1,
                title="1화",
                content="<p>comic</p>",
                image_urls=[series_url],
            ))
            s.commit()
        with get_session() as s:
            used = collect_referenced_media_keys(s, storage)
        assert key in used
        assert series_key in used
    finally:
        storage.delete(key)
        storage.delete(series_key)


def test_archive_request_runs_in_background_and_notifies(client, auth_cookie, make_post, monkeypatch, tmp_path):
    import app.core.archive as archive_module
    import app.routes.api._export as export_module

    monkeypatch.setattr(archive_module, "ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(archive_module, "_notify_archive_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(export_module, "spawn", lambda *args, **kwargs: None)

    user, cookie = auth_cookie("bob")
    make_post(user, content="<p>archive me</p>")

    created = client.post("/api/settings/archive-request", cookies=cookie)
    assert created.status_code == 200
    job = created.json()["job"]
    assert job["status"] == "pending"

    duplicate = client.post("/api/settings/archive-request", cookies=cookie)
    assert duplicate.status_code == 200
    assert duplicate.json()["already_running"] is True

    run_archive_job(job["id"])

    status = client.get("/api/settings/archive-status", cookies=cookie).json()["job"]
    assert status["status"] == "completed"
    assert status["size_bytes"] > 0
    assert status["download_url"].endswith(f"/{job['uuid']}")

    with get_session() as s:
        notif = s.query(Notification).filter_by(user_id=user.id, notification_type="archive").first()
        assert notif is not None
        meta = json.loads(notif.metadata_json)
        assert meta["status"] == "completed"
        assert meta["job_id"] == job["uuid"]

    download = client.get(status["download_url"], cookies=cookie)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(download.content)) as z:
        assert "profile.json" in z.namelist()
        assert "posts.json" in z.namelist()


def test_archive_can_only_be_created_once_per_week(client, auth_cookie, make_post, monkeypatch, tmp_path):
    import app.core.archive as archive_module
    import app.routes.api._export as export_module

    monkeypatch.setattr(archive_module, "ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(archive_module, "_notify_archive_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(export_module, "spawn", lambda *args, **kwargs: None)

    user, cookie = auth_cookie("carol")
    make_post(user, content="<p>weekly archive</p>")
    first = client.post("/api/settings/archive-request", cookies=cookie).json()["job"]
    run_archive_job(first["id"])

    second = client.post("/api/settings/archive-request", cookies=cookie)
    assert second.status_code == 429
    assert "일주일에 한 번" in second.json()["detail"]

    status = client.get("/api/settings/archive-status", cookies=cookie).json()
    assert status["job"]["status"] == "completed"
    assert status["next_available_at"]


def test_expired_archives_are_removed(client, auth_cookie, monkeypatch, tmp_path):
    import app.core.archive as archive_module
    from app.models import ArchiveJob
    from app.utils.datetime import now

    monkeypatch.setattr(archive_module, "ARCHIVE_DIR", str(tmp_path))
    user, _cookie = auth_cookie("alice")
    archive_file = tmp_path / "old.zip"
    archive_file.write_bytes(b"old archive")
    with get_session() as s:
        s.add(ArchiveJob(
            user_id=user.id,
            status="completed",
            file_path=str(archive_file),
            created_at=now() - timedelta(days=8),
        ))
        s.commit()

    removed = archive_module.cleanup_expired_archives()

    assert removed == 1
    assert not archive_file.exists()
    with get_session() as s:
        assert s.query(ArchiveJob).filter_by(user_id=user.id).count() == 0


def test_archive_download_rejects_other_users(client, auth_cookie, monkeypatch, tmp_path):
    import app.core.archive as archive_module
    import app.routes.api._export as export_module

    monkeypatch.setattr(archive_module, "ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(archive_module, "_notify_archive_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(export_module, "spawn", lambda *args, **kwargs: None)

    _alice, alice_cookie = auth_cookie("alice")
    _bob, bob_cookie = auth_cookie("bob")
    job = client.post("/api/settings/archive-request", cookies=alice_cookie).json()["job"]
    run_archive_job(job["id"])

    response = client.get(f"/api/settings/archive-download/{job['uuid']}", cookies=bob_cookie)
    assert response.status_code == 404
