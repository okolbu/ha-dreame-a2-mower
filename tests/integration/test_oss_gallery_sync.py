"""Tests for _LidarOssMixin._refresh_oss_gallery — canonical OSS media sync."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from custom_components.dreame_a2_mower.archive.photos import PhotoArchive
from custom_components.dreame_a2_mower.archive.videos import VideoArchive
from custom_components.dreame_a2_mower.coordinator import _lidar_oss
from custom_components.dreame_a2_mower.mower.state import MowerState

MIXIN = _lidar_oss._LidarOssMixin


def _coord(photos, videos, quota):
    c = MIXIN()
    c._cloud = SimpleNamespace(
        list_oss_media=MagicMock(side_effect=lambda t, **k: photos if t == "jpg" else videos),
        fetch_oss_quota=MagicMock(return_value=quota),
        get_file=MagicMock(return_value=b"\xff\xd8\xff\xd9"),
        get_interim_file_url=MagicMock(side_effect=lambda k: k),
    )
    c._photo_archive = MagicMock(has=MagicMock(return_value=False), has_name=MagicMock(return_value=False))
    c._video_archive = MagicMock(has=MagicMock(return_value=False))
    c.data = MowerState()
    async def _exec(fn, *a): return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    c.async_set_updated_data = lambda s: setattr(c, "data", s)
    return c


@pytest.mark.asyncio
async def test_gallery_sync_archives_photo_and_video_and_quota():
    photos = [{"id": "p1", "filepath": "https://fake/a_person.jpg", "uploadTime": "2026-06-08 21:07:08", "videoPath": ""}]
    videos = [{"id": "v1", "filepath": "https://fake/t.jpg", "videoPath": "https://fake/v.mp4", "ext": "{\"duration\":18}", "uploadTime": "2026-06-09 18:42:13"}]
    c = _coord(photos, videos, {"total": 209715200, "used": 1000})
    await c._refresh_oss_gallery()
    c._photo_archive.archive.assert_called()
    c._video_archive.archive.assert_called()
    assert c.data.oss_storage_used == 1000 and c.data.oss_storage_total == 209715200


@pytest.mark.asyncio
async def test_gallery_sync_skips_already_archived():
    c = _coord([{"id": "p1", "filepath": "https://fake/a.jpg", "uploadTime": "x", "videoPath": ""}], [], None)
    c._video_archive.has = MagicMock(return_value=True)
    # photo already present — dedup is by OSS leaf name (has_name), not md5 has():
    c._photo_archive.has_name = MagicMock(return_value=True)
    await c._refresh_oss_gallery()
    c._photo_archive.archive.assert_not_called()


def _coord_real_archives(tmp_path, photos, videos, quota):
    """Coordinator with REAL Photo/Video archives so the manifest build can
    read list_photos()/list_videos(), plus a hass.http.async_sign_path stub."""
    c = MIXIN()
    c._cloud = SimpleNamespace(
        list_oss_media=MagicMock(side_effect=lambda t, **k: photos if t == "jpg" else videos),
        fetch_oss_quota=MagicMock(return_value=quota),
        get_file=MagicMock(return_value=b"\xff\xd8\xff\xd9"),
        get_interim_file_url=MagicMock(side_effect=lambda k: k),
    )
    c._photo_archive = PhotoArchive(tmp_path / "photos")
    c._video_archive = VideoArchive(tmp_path / "videos")
    c._photo_gallery = []
    c.data = MowerState()

    async def _exec(fn, *a):
        return fn(*a)

    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    # Stub the media-path signer (real impl calls homeassistant.components.http
    # async_sign_path, which isn't available in the stubbed test env).
    c._sign_media_path = lambda path: path + "?authSig=fake"
    c.async_set_updated_data = lambda s: setattr(c, "data", s)
    return c


@pytest.mark.asyncio
async def test_gallery_manifest_shape_and_sort(tmp_path):
    """Manifest carries a photo + a video item, newest-first, with signed
    /api/dreame_a2_mower/ URLs and the documented per-type keys."""
    photos = [{"id": "p1", "filepath": "https://fake/1700000000_person.jpg",
               "uploadTime": "2026-06-08 21:07:08", "videoPath": ""}]
    videos = [{"id": "v1", "filepath": "https://fake/t.jpg", "videoPath": "https://fake/v.mp4",
               "ext": "{\"duration\":18}", "uploadTime": "2026-06-09 18:42:13"}]
    c = _coord_real_archives(tmp_path, photos, videos, {"total": 100, "used": 1})
    await c._refresh_oss_gallery()

    gal = c._photo_gallery
    assert len(gal) == 2
    # newest-first: the video (2026-06-09) sorts before the photo (2026-06-08).
    assert [it["ts"] for it in gal] == sorted([it["ts"] for it in gal], reverse=True)

    photo = next(it for it in gal if it["type"] == "photo")
    video = next(it for it in gal if it["type"] == "video")

    for it in (photo, video):
        assert it["url"].startswith("/api/dreame_a2_mower/")
        assert it["thumb_url"].startswith("/api/dreame_a2_mower/")
        assert isinstance(it["ts"], int)
        assert it["date"]  # non-empty YYYY-MM-DD HH:MM

    assert photo["category"] == "person"
    assert "detection" in photo
    assert photo["url"] == photo["thumb_url"]
    assert photo["url"].startswith("/api/dreame_a2_mower/photo/")

    assert video["category"] == "video"
    assert video["duration"] == 18
    assert video["url"].startswith("/api/dreame_a2_mower/video/")
    assert video["thumb_url"].startswith("/api/dreame_a2_mower/video_thumb/")


@pytest.mark.asyncio
async def test_gallery_backfill_threads_max_pages(tmp_path):
    """_refresh_oss_gallery(max_pages=7) passes max_pages=7 into list_oss_media."""
    c = _coord_real_archives(tmp_path, [], [], None)
    await c._refresh_oss_gallery(max_pages=7)
    for call in c._cloud.list_oss_media.call_args_list:
        assert call.kwargs.get("max_pages") == 7


@pytest.mark.asyncio
async def test_sync_categorizes_via_categorizer(tmp_path):
    # A person photo (COM person detection) -> ai_human; a no-COM photo -> manual.
    # _coord_real_archives is the existing helper in this file.
    photos = [
        {"id": "p1", "filepath": "https://fake/1_person.jpg", "type": "jpg",
         "uploadTime": "2026-06-08 21:07:08", "videoPath": ""},
    ]
    c = _coord_real_archives(tmp_path, photos, [], {"total": 100, "used": 1})
    # get_file returns a JPEG with a COM person detection — stub photo_meta.
    import custom_components.dreame_a2_mower.coordinator._lidar_oss as L
    orig = L.photo_meta.parse_jpeg_com
    L.photo_meta.parse_jpeg_com = lambda data: {"o": 101, "detections": [{"cls": "person", "conf": 0.7, "x": 1, "y": 2, "w": 3, "h": 4}], "s": None, "sub": None}
    try:
        await c._refresh_oss_gallery()
    finally:
        L.photo_meta.parse_jpeg_com = orig
    cats = [p.category for p in c._photo_archive.list_photos()]
    assert "ai_human" in cats
    assert c._photo_archive.list_photos()[0].detections[0]["cls"] == "person"
