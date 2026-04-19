"""Tests for the on-disk LiDAR scan archive.

The archive stores the raw ``.pcd`` files exactly as the mower uploaded
them — content-addressed by md5 so repeat downloads of the same OSS key
are no-ops. Mirrors the shape of :mod:`session_archive` but is simpler
because LiDAR scans carry fewer metadata fields.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lidar_archive import ArchivedLidarScan, LidarArchive


@pytest.fixture
def sample_pcd_bytes() -> bytes:
    # Tiny valid PCD — the archive doesn't decode it, just stores it.
    return (
        b"VERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\n"
        b"WIDTH 1\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS 1\nDATA binary\n"
        b"\x00\x00\x80\x3f\x00\x00\x00\x40\x00\x00\x40\x40"
    )


def test_archive_persists_raw_bytes_and_indexes_metadata(tmp_path: Path, sample_pcd_bytes):
    arc = LidarArchive(tmp_path / "lidar")
    ok = arc.archive(
        object_name="ali_dreame/2026/04/19/BM.../device_abc.bin",
        unix_ts=1745050000,
        data=sample_pcd_bytes,
    )
    assert isinstance(ok, ArchivedLidarScan)
    assert arc.count == 1
    assert arc.latest().md5 == hashlib.md5(sample_pcd_bytes).hexdigest()

    # File exists on disk and roundtrips exactly.
    written = (tmp_path / "lidar" / ok.filename).read_bytes()
    assert written == sample_pcd_bytes

    # Index persisted.
    idx = json.loads((tmp_path / "lidar" / "index.json").read_text())
    assert idx["scans"][0]["md5"] == ok.md5


def test_archive_is_idempotent_by_md5(tmp_path: Path, sample_pcd_bytes):
    arc = LidarArchive(tmp_path / "lidar")
    first = arc.archive("k1.bin", 100, sample_pcd_bytes)
    second = arc.archive("k2.bin", 200, sample_pcd_bytes)
    assert first is not None
    assert second is None  # same md5 → skipped
    assert arc.count == 1


def test_two_distinct_scans_coexist(tmp_path: Path, sample_pcd_bytes):
    other = sample_pcd_bytes + b"\x01\x02\x03"  # different bytes → different md5
    arc = LidarArchive(tmp_path / "lidar")
    a = arc.archive("k1.bin", 100, sample_pcd_bytes)
    b = arc.archive("k2.bin", 200, other)
    assert arc.count == 2
    md5s = {s.md5 for s in arc.list_scans()}
    assert a.md5 in md5s and b.md5 in md5s


def test_list_scans_returns_newest_first(tmp_path: Path, sample_pcd_bytes):
    arc = LidarArchive(tmp_path / "lidar")
    arc.archive("k1.bin", 100, sample_pcd_bytes)
    arc.archive("k2.bin", 300, sample_pcd_bytes + b"\x01")
    arc.archive("k3.bin", 200, sample_pcd_bytes + b"\x02")
    tsseq = [s.unix_ts for s in arc.list_scans()]
    assert tsseq == [300, 200, 100]


def test_index_survives_reload(tmp_path: Path, sample_pcd_bytes):
    a1 = LidarArchive(tmp_path / "lidar")
    a1.archive("k.bin", 123, sample_pcd_bytes)

    a2 = LidarArchive(tmp_path / "lidar")
    assert a2.count == 1
    assert a2.latest().unix_ts == 123


def test_archive_records_object_name_and_size(tmp_path: Path, sample_pcd_bytes):
    arc = LidarArchive(tmp_path / "lidar")
    scan = arc.archive("ali_dreame/orig.bin", 555, sample_pcd_bytes)
    assert scan.object_name == "ali_dreame/orig.bin"
    assert scan.size_bytes == len(sample_pcd_bytes)


def test_archive_rejects_empty_payload(tmp_path: Path):
    arc = LidarArchive(tmp_path / "lidar")
    assert arc.archive("empty.bin", 1, b"") is None
    assert arc.count == 0
