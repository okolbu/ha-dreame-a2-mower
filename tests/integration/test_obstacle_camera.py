"""Tests for DreameA2ObstaclePhotoCamera — latest obstacle_ephemeral photo."""
from __future__ import annotations


def _make_coordinator(archive):
    """Build a minimal coordinator-double for obstacle camera tests.

    Mirrors _make_coordinator in test_photo_camera.py.
    """
    from unittest.mock import MagicMock

    coord = MagicMock()
    coord.sn = "TESTUNIT"
    coord.entry.entry_id = "e1"
    coord._cloud = None
    coord.cloud_state.maps_by_id = {}
    coord.photo_archive = archive
    return coord


def _make_obstacle_camera(coordinator):
    """Construct a DreameA2ObstaclePhotoCamera bypassing Camera.__init__.

    Mirrors _make_album_camera / _make_person_camera in test_photo_camera.py.
    """
    from custom_components.dreame_a2_mower.camera.photos import (
        DreameA2ObstaclePhotoCamera,
    )

    cam = DreameA2ObstaclePhotoCamera.__new__(DreameA2ObstaclePhotoCamera)
    cam.coordinator = coordinator
    cam._attr_unique_id = f"{coordinator.sn}_obstacle_photo"
    cam._attr_device_info = {}
    return cam


def test_obstacle_camera_returns_latest_bytes(tmp_path):
    """Camera returns the JPEG bytes of the single obstacle_ephemeral photo."""
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    arc.archive(
        name="obs1.jpg",
        unix_ts=100,
        data=b"\xff\xd8X" + b"0" * 20,
        is_person=False,
        category="obstacle_ephemeral",
    )

    coord = _make_coordinator(arc)
    cam = _make_obstacle_camera(coord)
    result = cam._latest_bytes()
    assert result is not None
    assert result[:3] == b"\xff\xd8X"


def test_obstacle_camera_returns_latest_when_multiple(tmp_path):
    """Camera returns the bytes of the photo with the highest unix_ts."""
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    arc.archive(
        name="obs1.jpg",
        unix_ts=100,
        data=b"\xff\xd8A" + b"0" * 20,
        is_person=False,
        category="obstacle_ephemeral",
    )
    arc.archive(
        name="obs2.jpg",
        unix_ts=200,
        data=b"\xff\xd8B" + b"0" * 20,
        is_person=False,
        category="obstacle_ephemeral",
    )

    coord = _make_coordinator(arc)
    cam = _make_obstacle_camera(coord)
    result = cam._latest_bytes()
    assert result is not None
    assert result[:3] == b"\xff\xd8B"  # newest (ts=200)


def test_obstacle_camera_returns_none_when_no_obstacle_ephemeral(tmp_path):
    """Camera returns None when the archive has no obstacle_ephemeral photos."""
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    # Archive a non-obstacle_ephemeral photo — camera must ignore it.
    arc.archive(
        name="album.jpg",
        unix_ts=100,
        data=b"\xff\xd8C" + b"0" * 20,
        is_person=False,
        category="obstacle",
    )

    coord = _make_coordinator(arc)
    cam = _make_obstacle_camera(coord)
    assert cam._latest_bytes() is None


def test_obstacle_camera_returns_none_when_archive_empty(tmp_path):
    """Camera returns None when the archive is completely empty."""
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    coord = _make_coordinator(arc)
    cam = _make_obstacle_camera(coord)
    assert cam._latest_bytes() is None


def test_obstacle_camera_available_iff_obstacle_ephemeral_exists(tmp_path):
    """available is True only when at least one obstacle_ephemeral photo exists."""
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    coord = _make_coordinator(arc)
    cam = _make_obstacle_camera(coord)
    assert not cam.available

    arc.archive(
        name="obs.jpg",
        unix_ts=1,
        data=b"\xff\xd8D" + b"0" * 20,
        is_person=False,
        category="obstacle_ephemeral",
    )
    cam2 = _make_obstacle_camera(coord)
    assert cam2.available


def test_obstacle_camera_ignores_non_ephemeral_for_availability(tmp_path):
    """available stays False when only non-obstacle_ephemeral photos exist."""
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    arc.archive(
        name="patrol.jpg",
        unix_ts=1,
        data=b"\xff\xd8E" + b"0" * 20,
        is_person=False,
        category="patrol",
    )

    coord = _make_coordinator(arc)
    cam = _make_obstacle_camera(coord)
    assert not cam.available
