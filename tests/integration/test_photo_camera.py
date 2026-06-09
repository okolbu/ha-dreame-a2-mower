"""Tests for photo camera entities (album + person-detection)."""
from __future__ import annotations


def _make_coordinator(archive):
    """Build a minimal coordinator-double for photo camera tests.

    Mirrors the pattern in test_lidar_camera.py: set the required attrs
    that the entity ctor/helpers read (sn, entry, _cloud, cloud_state).
    """
    from unittest.mock import MagicMock

    coord = MagicMock()
    coord.sn = "TESTUNIT"
    coord.entry.entry_id = "e1"
    coord._cloud = None
    coord.cloud_state.maps_by_id = {}
    coord.photo_archive = archive
    return coord


def _make_album_camera(coordinator):
    """Construct a DreameA2AlbumPhotoCamera bypassing Camera.__init__."""
    from custom_components.dreame_a2_mower._camera_photos import (
        DreameA2AlbumPhotoCamera,
    )

    cam = DreameA2AlbumPhotoCamera.__new__(DreameA2AlbumPhotoCamera)
    cam.coordinator = coordinator
    cam._attr_unique_id = f"{coordinator.sn}_album_photo"
    cam._attr_device_info = {}
    return cam


def _make_person_camera(coordinator):
    """Construct a DreameA2PersonPhotoCamera bypassing Camera.__init__."""
    from custom_components.dreame_a2_mower._camera_photos import (
        DreameA2PersonPhotoCamera,
    )

    cam = DreameA2PersonPhotoCamera.__new__(DreameA2PersonPhotoCamera)
    cam.coordinator = coordinator
    cam._attr_unique_id = f"{coordinator.sn}_person_photo"
    cam._attr_device_info = {}
    return cam


def test_album_camera_returns_latest_bytes(tmp_path):
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    arc.archive(name="1.jpg", unix_ts=1, data=b"\xff\xd8A" + b"0" * 20, is_person=False)
    arc.archive(name="2_person.jpg", unix_ts=2, data=b"\xff\xd8B" + b"0" * 20, is_person=True)

    coord = _make_coordinator(arc)
    cam = _make_album_camera(coord)
    assert cam._latest_bytes()[:3] == b"\xff\xd8B"  # newest overall


def test_person_camera_returns_latest_person_bytes(tmp_path):
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    arc.archive(name="1.jpg", unix_ts=1, data=b"\xff\xd8A" + b"0" * 20, is_person=False)
    arc.archive(name="2_person.jpg", unix_ts=2, data=b"\xff\xd8B" + b"0" * 20, is_person=True)

    coord = _make_coordinator(arc)
    person = _make_person_camera(coord)
    assert person._latest_bytes()[:3] == b"\xff\xd8B"  # newest person


def test_album_camera_returns_none_when_archive_empty(tmp_path):
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    coord = _make_coordinator(arc)
    cam = _make_album_camera(coord)
    assert cam._latest_bytes() is None


def test_person_camera_returns_none_when_no_person_photos(tmp_path):
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    arc.archive(name="1.jpg", unix_ts=1, data=b"\xff\xd8A" + b"0" * 20, is_person=False)

    coord = _make_coordinator(arc)
    cam = _make_person_camera(coord)
    assert cam._latest_bytes() is None


def test_album_camera_available_iff_latest_exists(tmp_path):
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    coord = _make_coordinator(arc)
    cam = _make_album_camera(coord)
    assert not cam.available

    arc.archive(name="1.jpg", unix_ts=1, data=b"\xff\xd8A" + b"0" * 20, is_person=False)
    # New cam to re-check (archive mutated)
    cam2 = _make_album_camera(coord)
    assert cam2.available


def test_person_camera_available_iff_person_photo_exists(tmp_path):
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    coord = _make_coordinator(arc)
    cam = _make_person_camera(coord)
    assert not cam.available

    arc.archive(name="p.jpg", unix_ts=1, data=b"\xff\xd8P" + b"0" * 20, is_person=True)
    cam2 = _make_person_camera(coord)
    assert cam2.available


def test_album_camera_returns_none_when_file_missing(tmp_path):
    """If index says file exists but it's been deleted, return None."""
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    arc = PhotoArchive(tmp_path)
    arc.archive(name="1.jpg", unix_ts=1, data=b"\xff\xd8A" + b"0" * 20, is_person=False)
    # Delete the actual JPEG
    for p in tmp_path.glob("*.jpg"):
        p.unlink()

    coord = _make_coordinator(arc)
    cam = _make_album_camera(coord)
    assert cam._latest_bytes() is None
