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
    """Construct a DreameA2AlbumPhotoCamera bypassing Camera.__init__.

    With CoordinatorEntity added to the base, ``__new__`` skips all
    ``__init__`` calls.  We set ``coordinator`` manually (same value that
    ``CoordinatorEntity.__init__`` would assign) so the entity methods work.
    """
    from custom_components.dreame_a2_mower.camera.photos import (
        DreameA2AlbumPhotoCamera,
    )

    cam = DreameA2AlbumPhotoCamera.__new__(DreameA2AlbumPhotoCamera)
    cam.coordinator = coordinator
    cam._attr_unique_id = f"{coordinator.sn}_album_photo"
    cam._attr_device_info = {}
    return cam


def _make_person_camera(coordinator):
    """Construct a DreameA2PersonPhotoCamera bypassing Camera.__init__.

    Same pattern as ``_make_album_camera``.
    """
    from custom_components.dreame_a2_mower.camera.photos import (
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


def test_available_is_index_only_not_byte_read(tmp_path):
    """``available`` must be True based on the index even when the JPEG file
    has been deleted from disk — proving it does NOT read bytes to decide.

    Protocol:
    1. Archive a photo (writes both the JPEG and index.json).
    2. Delete the JPEG file from disk.
    3. Load a *fresh* PhotoArchive over the same directory (reads index.json
       only — it never touches the JPEG until ``read_bytes`` is called).
    4. ``available`` must be True (index entry exists).
    5. ``_latest_bytes()`` must be None (JPEG is gone → read_bytes returns None).

    This distinguishes index-only availability from byte-read availability.
    """
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

    # Step 1: archive a photo so index.json is written
    arc = PhotoArchive(tmp_path)
    entry = arc.archive(
        name="1.jpg", unix_ts=1, data=b"\xff\xd8A" + b"0" * 20, is_person=False
    )
    assert entry is not None

    # Step 2: delete the JPEG file
    (arc.root / entry.filename).unlink()

    # Step 3: fresh PhotoArchive reads only index.json (no JPEG touch)
    fresh_arc = PhotoArchive(tmp_path)
    coord = _make_coordinator(fresh_arc)
    cam = _make_album_camera(coord)

    # Step 4: available is True — index still has the entry
    assert cam.available is True, (
        "available should be True based on the index entry, not require the JPEG"
    )

    # Step 5: _latest_bytes() is None — JPEG is gone
    assert cam._latest_bytes() is None, (
        "_latest_bytes() should return None when the JPEG file is missing"
    )
