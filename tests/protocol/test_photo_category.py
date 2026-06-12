from custom_components.dreame_a2_mower.protocol.photo_category import (
    categorize, primary_detection, HUMAN_CLASSES, ANIMAL_CLASSES,
)


def _com(o=None, dets=None):
    return {"o": o, "detections": dets or [], "s": None, "sub": None}


def test_video_by_type():
    assert categorize(name="x.jpg", record={"type": "thumb"}, com=None) == "video"


def test_video_by_videopath():
    assert categorize(name="x.jpg", record={"videoPath": "a.mp4"}, com=_com()) == "video"


def test_ai_human_from_detection():
    com = _com(o=101, dets=[{"cls": "person", "conf": 0.7}])
    assert categorize(name="1_person.jpg", record={"type": "jpg"}, com=com) == "ai_human"


def test_ai_human_during_patrol_still_ai():
    # detection takes priority over o=107 patrol activity
    com = _com(o=107, dets=[{"cls": "person", "conf": 0.8}])
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=com) == "ai_human"


def test_ai_animal_known_class():
    com = _com(o=100, dets=[{"cls": "hedgehog", "conf": 0.95}])
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=com) == "ai_animal"


def test_ai_object_unknown_class_falls_through():
    com = _com(o=100, dets=[{"cls": "wheelbarrow", "conf": 0.6}])
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=com) == "ai_object"


def test_patrol_o107_empty_detections():
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=_com(o=107)) == "patrol"


def test_obstacle_mow_mode_empty_detections():
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=_com(o=100)) == "obstacle"


def test_manual_no_com():
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=None) == "manual"


def test_person_filename_fallback_when_no_detection():
    assert categorize(name="1_person.jpg", record={"type": "jpg"}, com=_com(o=101)) == "ai_human"


def test_primary_detection_is_highest_conf():
    dets = [{"cls": "a", "conf": 0.4}, {"cls": "b", "conf": 0.9}]
    assert primary_detection(dets)["cls"] == "b"


def test_vocab_membership():
    assert "person" in HUMAN_CLASSES
    assert "hedgehog" in ANIMAL_CLASSES
