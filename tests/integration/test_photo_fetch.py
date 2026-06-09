"""TDD tests for fetch_photos_from_summary (module-level helper in _lidar_oss).

Tests are HA-free and run against the pure helper directly.
"""
from custom_components.dreame_a2_mower.coordinator._lidar_oss import fetch_photos_from_summary


class _FakeCloud:
    _uid = "BM169439"
    _did = "-112293549"

    def get_interim_file_url(self, key):
        return f"https://signed/{key}"

    def get_file(self, url):
        # Return unique bytes per URL so md5 dedup doesn't suppress second photo.
        # Use full URL so the differing filename at the end makes distinct md5s.
        return b"\xff\xd8\xff" + url.encode()


def test_fetch_photos_from_summary(tmp_path):
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive
    arc = PhotoArchive(tmp_path)
    raw = {"photo_list": ["1780512275.jpg", "1780512300_person.jpg"]}
    n = fetch_photos_from_summary(
        _FakeCloud(), arc, raw, sign=lambda c, k: c.get_interim_file_url(k),
    )
    assert n == 2
    assert arc.count == 2
    assert arc.latest_person().name == "1780512300_person.jpg"


def test_fetch_photos_empty_list(tmp_path):
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive
    arc = PhotoArchive(tmp_path)
    n = fetch_photos_from_summary(
        _FakeCloud(), arc, {}, sign=lambda c, k: c.get_interim_file_url(k),
    )
    assert n == 0
