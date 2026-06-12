"""Tests for the photo-gallery HTTP views (PhotoFileView / VideoThumbView /
VideoFileView): in-index ids serve bytes with the right content-type; unknown /
traversal ids return 404 and never open an arbitrary path."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.photos import PhotoArchive
from custom_components.dreame_a2_mower.archive.videos import VideoArchive
from custom_components.dreame_a2_mower.camera import (
    PhotoFileView,
    VideoFileView,
    VideoThumbView,
)
from custom_components.dreame_a2_mower.const import DOMAIN


def _make_hass(data=None):
    hass = MagicMock()
    hass.data = data or {}

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor
    return hass


def _coord(photo_archive=None, video_archive=None):
    coord = MagicMock()
    coord.photo_archive = photo_archive
    coord.video_archive = video_archive
    return coord


def _request(coord):
    request = MagicMock()
    request.app = {"hass": _make_hass({DOMAIN: {"abc": coord}} if coord else {DOMAIN: {}})}
    return request


# -------------------- view metadata --------------------

def test_view_urls_and_auth():
    assert PhotoFileView.url == "/api/dreame_a2_mower/photo/{name}"
    assert PhotoFileView.requires_auth is True
    assert PhotoFileView.name == "api:dreame_a2_mower:photo"
    assert VideoThumbView.url == "/api/dreame_a2_mower/video_thumb/{vid}"
    assert VideoThumbView.requires_auth is True
    assert VideoFileView.url == "/api/dreame_a2_mower/video/{vid}"
    assert VideoFileView.requires_auth is True


# -------------------- PhotoFileView --------------------

def _photo_archive(tmp_path: Path) -> PhotoArchive:
    arch = PhotoArchive(tmp_path)
    arch.archive(name="1700000000.jpg", unix_ts=1700000000,
                 data=b"\xff\xd8\xff\xd9", is_person=False, category="obstacle")
    return arch


def test_photo_view_serves_known_filename(tmp_path: Path):
    arch = _photo_archive(tmp_path)
    filename = arch.list_photos()[0].filename
    view = PhotoFileView()
    resp = asyncio.run(view.get(_request(_coord(photo_archive=arch)), name=filename))
    assert resp.status == 200
    assert resp.content_type == "image/jpeg"
    assert resp.body == b"\xff\xd8\xff\xd9"
    assert "private" in resp.headers.get("Cache-Control", "")


def test_photo_view_404_for_unknown_name(tmp_path: Path):
    arch = _photo_archive(tmp_path)
    view = PhotoFileView()
    resp = asyncio.run(view.get(_request(_coord(photo_archive=arch)), name="nope.jpg"))
    assert resp.status == 404


def test_photo_view_404_for_traversal(tmp_path: Path):
    arch = _photo_archive(tmp_path)
    view = PhotoFileView()
    resp = asyncio.run(
        view.get(_request(_coord(photo_archive=arch)), name="../../etc/passwd")
    )
    assert resp.status == 404


def test_photo_view_404_when_no_coordinator():
    view = PhotoFileView()
    request = MagicMock()
    request.app = {"hass": _make_hass({DOMAIN: {}})}
    resp = asyncio.run(view.get(request, name="x.jpg"))
    assert resp.status == 404


# -------------------- VideoThumbView / VideoFileView --------------------

def _video_archive(tmp_path: Path) -> VideoArchive:
    arch = VideoArchive(tmp_path)
    arch.archive(video_id="vid1", mp4=b"MP4DATA", thumb=b"\xff\xd8\xff\xd9",
                 unix_ts=1700000001, duration=18)
    return arch


def test_video_thumb_view_serves_known_id(tmp_path: Path):
    arch = _video_archive(tmp_path)
    view = VideoThumbView()
    resp = asyncio.run(view.get(_request(_coord(video_archive=arch)), vid="vid1"))
    assert resp.status == 200
    assert resp.content_type == "image/jpeg"
    assert resp.body == b"\xff\xd8\xff\xd9"


def test_video_thumb_view_404_for_unknown_id(tmp_path: Path):
    arch = _video_archive(tmp_path)
    view = VideoThumbView()
    resp = asyncio.run(view.get(_request(_coord(video_archive=arch)), vid="nope"))
    assert resp.status == 404


def test_video_thumb_view_404_for_traversal(tmp_path: Path):
    arch = _video_archive(tmp_path)
    view = VideoThumbView()
    resp = asyncio.run(
        view.get(_request(_coord(video_archive=arch)), vid="../../etc/passwd")
    )
    assert resp.status == 404


def test_video_file_view_serves_known_id(tmp_path: Path):
    arch = _video_archive(tmp_path)
    view = VideoFileView()
    resp = asyncio.run(view.get(_request(_coord(video_archive=arch)), vid="vid1"))
    assert resp.status == 200
    assert resp.content_type == "video/mp4"
    assert resp.body == b"MP4DATA"


def test_video_file_view_404_for_unknown_id(tmp_path: Path):
    arch = _video_archive(tmp_path)
    view = VideoFileView()
    resp = asyncio.run(view.get(_request(_coord(video_archive=arch)), vid="nope"))
    assert resp.status == 404


def test_video_file_view_404_for_traversal(tmp_path: Path):
    arch = _video_archive(tmp_path)
    view = VideoFileView()
    resp = asyncio.run(
        view.get(_request(_coord(video_archive=arch)), vid="../../secret.mp4")
    )
    assert resp.status == 404
