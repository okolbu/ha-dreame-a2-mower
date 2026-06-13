"""Tests for PhotoArchive category + detection + per-category retention (Phase D Task 3)."""
from pathlib import Path

from custom_components.dreame_a2_mower.archive.photos import PhotoArchive, ArchivedPhoto


def test_archived_photo_category_detection_roundtrip():
    p = ArchivedPhoto(
        filename="f", name="n", unix_ts=1, size_bytes=2, md5="m",
        is_person=False, category="patrol", detections=[{"cls": "person", "conf": 0.8}],
    )
    d = p.to_dict()
    assert d["category"] == "patrol" and d["detections"][0]["cls"] == "person"
    r = ArchivedPhoto.from_dict(d)
    assert r.category == "patrol" and r.detections[0]["cls"] == "person"


def test_from_dict_legacy_defaults():
    # legacy entry (pre-Phase-D) has no category/detections; under the
    # 7-category scheme is_person migrates to "ai_human" and the absent
    # detection becomes an empty list.
    person = ArchivedPhoto.from_dict(
        {"filename": "f", "name": "n", "unix_ts": 1, "size_bytes": 2, "md5": "m", "is_person": True}
    )
    assert person.category == "ai_human" and person.detections == []
    obst = ArchivedPhoto.from_dict(
        {"filename": "g", "name": "n2", "unix_ts": 1, "size_bytes": 2, "md5": "m2", "is_person": False}
    )
    assert obst.category == "obstacle"


def test_per_category_retention(tmp_path: Path):
    arch = PhotoArchive(tmp_path)
    arch.set_per_category_retention(2)
    for i in range(4):
        arch.archive(
            data=b"\xff\xd8\xff\xd9" + bytes([i]),
            name=f"ob{i}",
            unix_ts=i,
            is_person=False,
            category="obstacle",
        )
    for i in range(3):
        arch.archive(
            data=b"\xff\xd8\xff\xd9" + bytes([100 + i]),
            name=f"pa{i}",
            unix_ts=100 + i,
            is_person=False,
            category="patrol",
        )
    assert arch.count_by_category("obstacle") == 2
    assert arch.count_by_category("patrol") == 2
    # newest kept (highest unix_ts)
    obstacles = [p for p in arch._index if p.category == "obstacle"]
    assert {p.unix_ts for p in obstacles} == {2, 3}
