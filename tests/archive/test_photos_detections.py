from custom_components.dreame_a2_mower.archive.photos import ArchivedPhoto, PhotoArchive


def test_archive_stores_detections_list(tmp_path):
    a = PhotoArchive(tmp_path)
    dets = [{"cls": "person", "conf": 0.7, "x": 1, "y": 2, "w": 3, "h": 4}]
    rec = a.archive(name="1_person.jpg", unix_ts=10, data=b"\xff\xd8\xff\xd9",
                    is_person=True, category="ai_human", detections=dets)
    assert rec is not None
    assert rec.detections == dets
    assert rec.category == "ai_human"


def test_from_dict_migrates_legacy_single_detection():
    # Old index rows had `detection` (singular) + coarse category.
    legacy = {"filename": "f.jpg", "name": "1_person.jpg", "unix_ts": 1,
              "size_bytes": 1, "md5": "m", "is_person": True,
              "category": "person", "detection": {"cls": "person", "conf": 0.7}}
    p = ArchivedPhoto.from_dict(legacy)
    assert p.detections == [{"cls": "person", "conf": 0.7}]
    assert p.category == "ai_human"  # 'person' migrated to 'ai_human'


def test_from_dict_legacy_no_detection():
    legacy = {"filename": "f.jpg", "name": "1.jpg", "unix_ts": 1, "size_bytes": 1,
              "md5": "m", "is_person": False, "category": "obstacle"}
    p = ArchivedPhoto.from_dict(legacy)
    assert p.detections == []
    assert p.category == "obstacle"
