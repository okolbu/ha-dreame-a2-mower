"""Tests for archive/photos.py — mirrors test_lidar.py structure."""
from __future__ import annotations

from pathlib import Path

from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # ffd8 magic + filler


def test_archive_and_latest(tmp_path: Path) -> None:
    arc = PhotoArchive(tmp_path)
    entry = arc.archive(name="1780512275.jpg", unix_ts=1780512275, data=JPEG, is_person=False)
    assert entry is not None
    assert entry.is_person is False
    assert arc.count == 1
    assert arc.latest().name == "1780512275.jpg"


def test_archive_dedup_by_md5(tmp_path: Path) -> None:
    arc = PhotoArchive(tmp_path)
    arc.archive(name="a.jpg", unix_ts=1, data=JPEG, is_person=False)
    assert arc.archive(name="a.jpg", unix_ts=1, data=JPEG, is_person=False) is None
    assert arc.count == 1


def test_latest_person(tmp_path: Path) -> None:
    arc = PhotoArchive(tmp_path)
    arc.archive(name="1.jpg", unix_ts=1, data=JPEG, is_person=False)
    arc.archive(name="2_person.jpg", unix_ts=2, data=JPEG + b"x", is_person=True)
    assert arc.latest_person().name == "2_person.jpg"
    assert arc.latest().name == "2_person.jpg"  # latest overall


def test_archive_enforces_retention(tmp_path: Path) -> None:
    """retention=2 keeps only the 2 newest photos after archiving 3 distinct JPEGs."""
    arc = PhotoArchive(tmp_path, retention=2)
    # Use DISTINCT bytes so md5 dedup doesn't collapse them.
    arc.archive(name="oldest.jpg", unix_ts=1700000000, data=JPEG + b"\x01", is_person=False)
    arc.archive(name="middle.jpg", unix_ts=1700000010, data=JPEG + b"\x02", is_person=False)
    arc.archive(name="newest.jpg", unix_ts=1700000020, data=JPEG + b"\x03", is_person=False)

    photos = arc.list_photos()
    assert len(photos) == 2
    names = {p.name for p in photos}
    assert "oldest.jpg" not in names
    assert "middle.jpg" in names
    assert "newest.jpg" in names
    # Oldest file must also be gone from disk.
    assert not any(arc.root.glob("*oldest*"))


def test_photo_archive_enforces_size_cap(tmp_path: Path) -> None:
    """max_bytes prunes oldest until total on-disk size is at or below the cap."""
    photo = JPEG  # ~104 bytes
    # Cap at ~2.5 photos worth so the 3rd archive evicts the oldest.
    arc = PhotoArchive(tmp_path, max_bytes=len(photo) * 2 + 10)
    arc.archive(name="oldest.jpg", unix_ts=1700000000, data=photo + b"\x01", is_person=False)
    arc.archive(name="middle.jpg", unix_ts=1700000010, data=photo + b"\x02", is_person=False)
    arc.archive(name="newest.jpg", unix_ts=1700000020, data=photo + b"\x03", is_person=False)

    names = {p.name for p in arc.list_photos()}
    assert "oldest.jpg" not in names  # evicted by size cap
    assert names == {"middle.jpg", "newest.jpg"}
    assert not any(arc.root.glob("*oldest*"))


def test_size_cap_zero_means_unlimited(tmp_path: Path) -> None:
    arc = PhotoArchive(tmp_path, max_bytes=0)
    for i in range(5):
        arc.archive(name=f"{i}.jpg", unix_ts=1700000000 + i, data=JPEG + bytes([i]), is_person=False)
    assert arc.count == 5
