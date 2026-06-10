"""Tests for OSS camera entities: latest-video thumb camera + photo detection attrs.

These tests bypass coordinator __init__ with object.__new__, mirroring
tests/integration/test_cfg_switch_writes.py.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from custom_components.dreame_a2_mower import _camera_photos as cp


def test_latest_video_thumb_camera_returns_thumb_bytes(tmp_path):
    # archive with a latest video whose thumb file exists on disk
    (tmp_path / "9.jpg").write_bytes(b"\xff\xd8THUMB\xff\xd9")
    video = SimpleNamespace(thumb_filename="9.jpg", mp4_filename="9.mp4", duration=18, unix_ts=5)
    varch = SimpleNamespace(root=tmp_path, latest=lambda: video)
    coord = SimpleNamespace(_video_archive=varch, video_archive=varch)
    cam = object.__new__(cp.DreameA2LatestVideoThumbCamera)
    cam.coordinator = coord
    # the video camera reads bytes from <video_archive.root>/<thumb_filename>
    assert cam._latest_bytes() == b"\xff\xd8THUMB\xff\xd9"


def test_latest_video_thumb_camera_no_video_returns_none(tmp_path):
    # archive with no videos
    varch = SimpleNamespace(root=tmp_path, latest=lambda: None)
    coord = SimpleNamespace(_video_archive=varch, video_archive=varch)
    cam = object.__new__(cp.DreameA2LatestVideoThumbCamera)
    cam.coordinator = coord
    assert cam._latest_bytes() is None


def test_latest_video_thumb_camera_available_false_when_empty(tmp_path):
    varch = SimpleNamespace(root=tmp_path, latest=lambda: None)
    coord = SimpleNamespace(_video_archive=varch, video_archive=varch)
    cam = object.__new__(cp.DreameA2LatestVideoThumbCamera)
    cam.coordinator = coord
    assert cam.available is False


def test_latest_video_thumb_camera_available_true_when_video_exists(tmp_path):
    video = SimpleNamespace(thumb_filename="9.jpg", mp4_filename="9.mp4", duration=18, unix_ts=5)
    varch = SimpleNamespace(root=tmp_path, latest=lambda: video)
    coord = SimpleNamespace(_video_archive=varch, video_archive=varch)
    cam = object.__new__(cp.DreameA2LatestVideoThumbCamera)
    cam.coordinator = coord
    assert cam.available is True


def test_album_camera_exposes_detection_attributes():
    photo = SimpleNamespace(
        category="patrol",
        detection={"cls": "person", "conf": 0.81},
        filename="f",
        name="n",
        unix_ts=1,
        is_person=False,
    )
    coord = SimpleNamespace()
    cam = object.__new__(cp.DreameA2AlbumPhotoCamera)
    cam.coordinator = coord
    cam._latest_entry = lambda: photo  # stub the resolver
    attrs = cam.extra_state_attributes
    assert attrs.get("category") == "patrol"
    assert attrs.get("detection_class") == "person"
    assert abs(attrs.get("detection_confidence") - 0.81) < 1e-6


def test_album_camera_no_photo_returns_empty_attrs():
    coord = SimpleNamespace()
    cam = object.__new__(cp.DreameA2AlbumPhotoCamera)
    cam.coordinator = coord
    cam._latest_entry = lambda: None
    assert cam.extra_state_attributes == {}


def test_album_camera_no_detection_skips_detection_keys():
    photo = SimpleNamespace(
        category="obstacle",
        detection=None,
        filename="f",
        name="n",
        unix_ts=1,
        is_person=False,
    )
    coord = SimpleNamespace()
    cam = object.__new__(cp.DreameA2AlbumPhotoCamera)
    cam.coordinator = coord
    cam._latest_entry = lambda: photo
    attrs = cam.extra_state_attributes
    assert attrs.get("category") == "obstacle"
    assert "detection_class" not in attrs
    assert "detection_confidence" not in attrs


def test_person_camera_exposes_detection_attributes():
    photo = SimpleNamespace(
        category="person",
        detection={"cls": "guard", "conf": 0.95},
        filename="f",
        name="n",
        unix_ts=1,
        is_person=True,
    )
    coord = SimpleNamespace()
    cam = object.__new__(cp.DreameA2PersonPhotoCamera)
    cam.coordinator = coord
    cam._latest_entry = lambda: photo
    attrs = cam.extra_state_attributes
    assert attrs.get("category") == "person"
    assert attrs.get("detection_class") == "guard"
    assert abs(attrs.get("detection_confidence") - 0.95) < 1e-6
