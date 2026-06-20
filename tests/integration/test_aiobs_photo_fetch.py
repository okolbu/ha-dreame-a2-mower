"""Tests for _fetch_pending_obstacle_photos (Task 12).

The coordinator attribute is _photo_archive (not photo_archive).
The fetch path calls self._cloud.get_device_file(fn); no hass present in
stub → executor fallback path calls it directly.
Backend currently returns None for all fetches (signer unverified,
backend down) — the loop must mark records backend_unavailable without
crashing. When the backend recovers, the same code path succeeds.
"""
from __future__ import annotations

import asyncio
import types
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.obstacle_markers_log import (
    ObstacleMarkerLog,
)
from custom_components.dreame_a2_mower.protocol.obstacle_markers import ObstacleMarker

_M = ObstacleMarker(
    id="1781714586.078000_0",
    filename="1781714586.078000_0",
    polygon_m=((-6.6, 4.1),),
    confidence=78,
    obstacle_class=5,
    flag=0,
    detection_epoch=1781714586.078,
)

_M2 = ObstacleMarker(
    id="1781714600.000000_1",
    filename="1781714600.000000_1",
    polygon_m=((-5.0, 3.0),),
    confidence=65,
    obstacle_class=3,
    flag=0,
    detection_epoch=1781714600.0,
)


def _make_coord(tmp_path, *, get_device_file_fn):
    """Minimal stub with _fetch_pending_obstacle_photos wired from the mixin."""
    from custom_components.dreame_a2_mower.coordinator._refreshers import (
        _RefreshersMixin,
    )

    class _Arch:
        def __init__(self):
            self.calls = []

        def archive(self, **kw):
            self.calls.append(kw)
            return types.SimpleNamespace(md5=kw.get("name", ""))

    class _Coord(_RefreshersMixin):
        def __init__(self):
            self._obstacle_marker_log = ObstacleMarkerLog(tmp_path)
            self._obstacle_marker_log.load()
            self._cloud = types.SimpleNamespace(
                get_device_file=get_device_file_fn
            )
            self._photo_archive = _Arch()
            # No hass → executor fallback path
            # (mirrors how _refresh_aiobs uses getattr(self, "hass", None))

    return _Coord()


def test_pending_photo_fetched_and_marked_ready(tmp_path):
    """Successful fetch: archive is called with obstacle_ephemeral + record flips to ready."""
    jpeg = b"\xff\xd8\xff\xe0JFIF"
    log = ObstacleMarkerLog(tmp_path)
    log.load()
    log.note(_M)

    coord = _make_coord(tmp_path, get_device_file_fn=lambda fn, **k: jpeg)
    # replace log with the pre-populated one
    coord._obstacle_marker_log = log

    asyncio.run(coord._fetch_pending_obstacle_photos())

    assert len(coord._photo_archive.calls) == 1
    call = coord._photo_archive.calls[0]
    assert call["category"] == "obstacle_ephemeral"
    assert call["data"] == jpeg
    assert call["is_person"] is False
    assert log.all()[0].image_status == "ready"
    assert log.all()[0].image_md5 is not None


def test_fetch_failure_marks_backend_unavailable(tmp_path):
    """get_device_file returns None → record → backend_unavailable, archive NOT called."""
    log = ObstacleMarkerLog(tmp_path)
    log.load()
    log.note(_M)

    coord = _make_coord(tmp_path, get_device_file_fn=lambda fn, **k: None)
    coord._obstacle_marker_log = log

    asyncio.run(coord._fetch_pending_obstacle_photos())

    assert coord._photo_archive.calls == []
    assert log.all()[0].image_status == "backend_unavailable"


def test_loop_continues_past_one_marker_error(tmp_path):
    """First get_device_file raises; second marker still attempted and loop doesn't crash."""
    log = ObstacleMarkerLog(tmp_path)
    log.load()
    log.note(_M)
    log.note(_M2)

    call_count = [0]
    jpeg = b"\xff\xd8\xff\xe0JFIF"

    def _flaky_fetch(fn, **k):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("simulated backend error")
        return jpeg

    coord = _make_coord(tmp_path, get_device_file_fn=_flaky_fetch)
    coord._obstacle_marker_log = log

    # Must not raise
    asyncio.run(coord._fetch_pending_obstacle_photos())

    assert call_count[0] == 2, "second marker must be attempted"
    # second marker succeeded → archived
    assert len(coord._photo_archive.calls) == 1
    assert coord._photo_archive.calls[0]["category"] == "obstacle_ephemeral"
