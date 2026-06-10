"""Tests for OSS quota + per-type photo count + latest-video sensors (Phase D, Task 6).

Quota sensors (oss_storage_used / oss_storage_total / oss_storage_pct) are
MowerState-sourced (DreameA2SensorEntityDescription, live in SENSORS).

Count sensors (photos_obstacle / photos_patrol / photos_person / videos) and
latest_video are coordinator-sourced (DreameA2DiagnosticSensorEntityDescription,
live in DIAGNOSTIC_SENSORS).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.dreame_a2_mower import sensor_device
from custom_components.dreame_a2_mower.mower.state import MowerState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find(key: str):
    """Search both SENSORS and DIAGNOSTIC_SENSORS for a descriptor by key."""
    for lst_name in ("SENSORS", "DIAGNOSTIC_SENSORS"):
        lst = getattr(sensor_device, lst_name, ())
        for d in lst:
            if getattr(d, "key", None) == key:
                return d
    raise KeyError(f"No sensor descriptor with key={key!r}")


# ---------------------------------------------------------------------------
# Quota sensors — value_fn takes MowerState
# ---------------------------------------------------------------------------

def test_quota_used_mb():
    s = MowerState(oss_storage_used=104857600)  # 100 MiB exactly
    result = _find("oss_storage_used").value_fn(s)
    assert result == 100


def test_quota_total_mb():
    s = MowerState(oss_storage_total=209715200)  # 200 MiB exactly
    result = _find("oss_storage_total").value_fn(s)
    assert result == 200


def test_quota_pct():
    s = MowerState(oss_storage_used=104857600, oss_storage_total=209715200)
    result = _find("oss_storage_pct").value_fn(s)
    assert result == 50


def test_quota_sensors_read_state():
    """Bundled assertion matching the Task 6 spec."""
    s = MowerState(oss_storage_used=104857600, oss_storage_total=209715200)
    assert _find("oss_storage_used").value_fn(s) == 100
    assert _find("oss_storage_total").value_fn(s) == 200
    assert _find("oss_storage_pct").value_fn(s) == 50


def test_quota_pct_none_when_no_total():
    s = MowerState(oss_storage_used=None, oss_storage_total=None)
    assert _find("oss_storage_pct").value_fn(s) is None


def test_quota_used_none_when_none():
    s = MowerState(oss_storage_used=None)
    assert _find("oss_storage_used").value_fn(s) is None


def test_quota_total_none_when_none():
    s = MowerState(oss_storage_total=None)
    assert _find("oss_storage_total").value_fn(s) is None


def test_quota_pct_none_when_total_zero():
    """Divide-by-zero guard: total=0 → None."""
    s = MowerState(oss_storage_used=1024, oss_storage_total=0)
    assert _find("oss_storage_pct").value_fn(s) is None


# ---------------------------------------------------------------------------
# Count sensors — value_fn takes coordinator
# ---------------------------------------------------------------------------

def _make_coord(*, obstacle=3, patrol=1, person=2, videos=4):
    return SimpleNamespace(
        _photo_archive=SimpleNamespace(
            count_by_category=lambda c: {"obstacle": obstacle, "patrol": patrol, "person": person}[c]
        ),
        _video_archive=SimpleNamespace(count=videos),
    )


def test_count_sensors_read_archive():
    """Bundled assertion matching the Task 6 spec."""
    coord = _make_coord()
    assert _find("photos_obstacle").value_fn(coord) == 3
    assert _find("photos_patrol").value_fn(coord) == 1
    assert _find("photos_person").value_fn(coord) == 2
    assert _find("videos").value_fn(coord) == 4


def test_photos_obstacle_count():
    coord = _make_coord(obstacle=7)
    assert _find("photos_obstacle").value_fn(coord) == 7


def test_photos_patrol_count():
    coord = _make_coord(patrol=5)
    assert _find("photos_patrol").value_fn(coord) == 5


def test_photos_person_count():
    coord = _make_coord(person=9)
    assert _find("photos_person").value_fn(coord) == 9


def test_videos_count():
    coord = _make_coord(videos=12)
    assert _find("videos").value_fn(coord) == 12


# ---------------------------------------------------------------------------
# latest_video sensor — value_fn takes coordinator
# ---------------------------------------------------------------------------

def test_latest_video_returns_duration():
    from types import SimpleNamespace
    vid = SimpleNamespace(duration=42, mp4_filename="clip_001.mp4")
    coord = SimpleNamespace(
        _video_archive=SimpleNamespace(latest=lambda: vid),
    )
    assert _find("latest_video").value_fn(coord) == 42


def test_latest_video_returns_none_when_empty():
    coord = SimpleNamespace(
        _video_archive=SimpleNamespace(latest=lambda: None),
    )
    assert _find("latest_video").value_fn(coord) is None


def test_latest_video_extra_attrs_include_path():
    """latest_video sensor must expose the mp4 path in extra_state_attributes_fn."""
    from pathlib import Path
    vid = SimpleNamespace(duration=42, mp4_filename="clip_001.mp4")
    coord = SimpleNamespace(
        _video_archive=SimpleNamespace(
            latest=lambda: vid,
            root=Path("/config/dreame_a2_mower/videos"),
        ),
    )
    desc = _find("latest_video")
    fn = desc.extra_state_attributes_fn
    assert fn is not None, "latest_video must have extra_state_attributes_fn"
    attrs = fn(coord)
    assert attrs is not None
    assert "mp4_path" in attrs
    assert attrs["mp4_path"] == "/config/dreame_a2_mower/videos/clip_001.mp4"


def test_latest_video_extra_attrs_none_when_empty():
    """extra_state_attributes_fn returns empty/None when no video exists."""
    from pathlib import Path
    coord = SimpleNamespace(
        _video_archive=SimpleNamespace(
            latest=lambda: None,
            root=Path("/config/dreame_a2_mower/videos"),
        ),
    )
    desc = _find("latest_video")
    fn = desc.extra_state_attributes_fn
    assert fn is not None, "latest_video must have extra_state_attributes_fn"
    attrs = fn(coord)
    # Either None or empty dict is acceptable when no video
    assert not attrs
