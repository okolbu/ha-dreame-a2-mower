"""Tests for _LidarOssMixin._refresh_oss_gallery — canonical OSS media sync."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
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
