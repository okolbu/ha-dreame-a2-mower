from custom_components.dreame_a2_mower.protocol.photo_keys import (
    build_photo_object_key,
    is_person_photo,
)


def test_build_photo_object_key():
    # [dreame-app-implementation-guide-2026-06-09.md] key layout:
    # oss/media/000000/oss/<uid>/<did>/ali_dreame/<name>
    key = build_photo_object_key(uid="BM169439", did="-112293549", name="1780512275.jpg")
    assert key == "oss/media/000000/oss/BM169439/-112293549/ali_dreame/1780512275.jpg"


def test_build_photo_object_key_person_variant():
    key = build_photo_object_key(uid="BM169439", did="-112293549", name="1780512275_person.jpg")
    assert key.endswith("/ali_dreame/1780512275_person.jpg")


def test_is_person_photo():
    assert is_person_photo("1780512275_person.jpg") is True
    assert is_person_photo("1780512275.jpg") is False
