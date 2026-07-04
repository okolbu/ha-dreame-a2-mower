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


@pytest.mark.asyncio
async def test_post_session_gallery_refresh_scheduled_and_runs(monkeypatch):
    """_schedule_post_session_gallery_refresh arms a delayed one-shot that
    runs _refresh_oss_gallery (so videos / non-photo_list media appear within
    ~Ns of finalize instead of waiting for the hourly sync)."""
    c = MIXIN()
    c.hass = SimpleNamespace()
    c._refresh_oss_gallery = AsyncMock()

    captured = {}

    def _fake_call_later(hass, delay, action):
        captured["delay"] = delay
        captured["action"] = action
        return lambda: None

    monkeypatch.setattr(_lidar_oss, "async_call_later", _fake_call_later)
    c._schedule_post_session_gallery_refresh()

    assert captured["delay"] == c._POST_SESSION_GALLERY_DELAY_S
    # Firing the scheduled callback triggers exactly one gallery sync.
    await captured["action"](None)
    c._refresh_oss_gallery.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_session_gallery_refresh_registers_unload_canceller(monkeypatch):
    """T3-8 + P2-inherit: the delayed one-shot's canceller goes through the
    self-cleaning registry — a reload/unload inside the delay window cancels it,
    but the entry's unload list gains ONE hook that cancels all outstanding
    timers (bounded growth across repeated finalizes), not one hook per timer."""
    c = MIXIN()
    c.hass = SimpleNamespace()
    c.entry = MagicMock()
    canceller = MagicMock(name="canceller")

    monkeypatch.setattr(
        _lidar_oss, "async_call_later", lambda hass, delay, action: canceller
    )
    c._schedule_post_session_gallery_refresh()

    # One unload hook registered (the cancel-all), and firing it cancels the
    # scheduled one-shot.
    c.entry.async_on_unload.assert_called_once()
    assert canceller in c._managed_cancellers
    cancel_all = c.entry.async_on_unload.call_args.args[0]
    cancel_all()
    canceller.assert_called_once()

    # A second finalize re-uses the same single unload hook.
    c._schedule_post_session_gallery_refresh()
    c.entry.async_on_unload.assert_called_once()


@pytest.mark.asyncio
async def test_post_session_gallery_refresh_noop_without_hass(monkeypatch):
    c = MIXIN()
    c.hass = None
    called = {"n": 0}
    monkeypatch.setattr(
        _lidar_oss, "async_call_later",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    c._schedule_post_session_gallery_refresh()  # must not raise / schedule
    assert called["n"] == 0


def test_session_photos_manifest_matches_photo_list_by_ts():
    """session_photos_manifest links a session's photo_list to archived photos
    by capture timestamp (so the `<ts>_person.jpg` gallery variant still matches
    the bare `<ts>.jpg` photo_list name), and emits signed thumbnails."""
    c = MIXIN()
    P = SimpleNamespace
    photos = [
        # archived under the _person gallery name; photo_list has the bare name
        P(filename="2026-06-16_1780952775_aabbccdd.jpg", name="1780952775_person.jpg",
          unix_ts=1780952775, category="person", detections=[{"cls": "human"}]),
        P(filename="2026-06-16_1780952780_eeff0011.jpg", name="1780952780.jpg",
          unix_ts=1780952780, category="patrol", detections=[]),
        # a photo NOT in this session's photo_list -> excluded
        P(filename="2026-06-16_1780999999_99999999.jpg", name="1780999999.jpg",
          unix_ts=1780999999, category="obstacle", detections=[]),
    ]
    c._photo_archive = SimpleNamespace(list_photos=lambda: photos)
    c._sign_media_path = lambda path: path + "?sig=X"

    items = c.session_photos_manifest({"photo_list": ["1780952775.jpg", "1780952780.jpg"]})

    assert [it["id"] for it in items] == [
        "2026-06-16_1780952775_aabbccdd.jpg",
        "2026-06-16_1780952780_eeff0011.jpg",
    ]  # oldest-first, the unlisted obstacle photo excluded
    assert items[0]["category"] == "person"
    assert items[0]["detections"] == [{"cls": "human"}]
    assert items[0]["thumb_url"] == (
        "/api/dreame_a2_mower/photo/2026-06-16_1780952775_aabbccdd.jpg?sig=X"
    )


def _snapshot_coord(photos):
    c = MIXIN()
    c._photo_archive = SimpleNamespace(list_photos=lambda: photos)
    c._sign_media_path = lambda path: path + "?sig=X"
    return c


def test_link_message_snapshot_photos_matches_ai_human_in_window():
    """A 'View snapshots in the app.' notification links to the ai_human photo
    that lands a few seconds later (timestamp-window match)."""
    P = SimpleNamespace
    photos = [
        P(filename="2026-06-15_1781558884_32e14546.jpg", name="1781558884_person.jpg",
          unix_ts=1781558884, category="ai_human", detections=[{"cls": "human", "conf": 0.8}]),
        P(filename="far_1781550000_aaaa.jpg", name="1781550000.jpg",
          unix_ts=1781550000, category="ai_human", detections=[]),  # ~2.5h before -> out of window
        P(filename="patrol_1781558886_bbbb.jpg", name="1781558886.jpg",
          unix_ts=1781558886, category="patrol", detections=[]),    # in window but patrol -> excluded
    ]
    c = _snapshot_coord(photos)
    msgs = [
        {"id": "m1", "title": "Human entry into the mapped area is detected. Please be alert. View snapshots in the app.",
         "date": "2026-06-15T21:27:59+00:00"},   # unix 1781558879; photo at +5s
        {"id": "m2", "title": "Mowing task complete. View work log in the app.",
         "date": "2026-06-15T21:30:00+00:00"},   # no marker -> untouched
    ]
    c.link_message_snapshot_photos(msgs)

    assert [p["id"] for p in msgs[0]["photos"]] == ["2026-06-15_1781558884_32e14546.jpg"]
    assert msgs[0]["photos"][0]["detections"] == [{"cls": "human", "conf": 0.8}]
    assert msgs[0]["photos"][0]["thumb_url"].startswith("/api/dreame_a2_mower/photo/")
    assert "photos" not in msgs[1]  # non-snapshot message left untouched


def test_link_message_snapshot_photos_no_match_leaves_key_absent():
    c = _snapshot_coord([
        SimpleNamespace(filename="x.jpg", name="x", unix_ts=1, category="ai_human", detections=[]),
    ])
    msgs = [{"id": "m", "title": "Human detected. View snapshots in the app.",
             "date": "2026-06-15T21:27:59+00:00"}]
    c.link_message_snapshot_photos(msgs)
    assert "photos" not in msgs[0]  # no photo in window -> no key


def test_session_photos_manifest_empty_without_photo_list():
    c = MIXIN()
    c._photo_archive = SimpleNamespace(list_photos=lambda: [])
    c._sign_media_path = lambda p: p
    assert c.session_photos_manifest({}) == []
    assert c.session_photos_manifest({"photo_list": []}) == []


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

    assert photo["category"] == "ai_human"  # _person.jpg -> ai_human under the 7-category scheme
    assert "detections" in photo  # full detection list present on photo items
    assert isinstance(photo["detections"], list)
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
