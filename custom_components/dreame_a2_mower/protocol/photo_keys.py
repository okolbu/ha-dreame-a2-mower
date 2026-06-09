"""Build OSS object keys for album (Patrol + AI-obstacle) photos.

[dreame-app-implementation-guide-2026-06-09.md] Photos live in the
dreame-eu.oss-eu-central-1 bucket at
``oss/media/000000/oss/<uid>/<did>/ali_dreame/<name>``, where ``<name>`` is a
``photo_list`` leaf from the session-summary ``.0550.json`` (a bare
``<unix_ts>.jpg`` or a ``<unix_ts>_person.jpg`` person-detection variant).

This module is pure (no HA, no network) and unit-testable in isolation. Whether
``get_interim_file_url`` or ``get_file_url`` signs this key is verified live by
``tools/probes/oss_photo_probe.py`` before the feature uses it.
"""
from __future__ import annotations

_PHOTO_KEY_PREFIX = "oss/media/000000/oss"
_PHOTO_KEY_SUBDIR = "ali_dreame"


def build_photo_object_key(*, uid: str, did: str, name: str) -> str:
    """Return the OSS object key for one photo_list leaf."""
    return f"{_PHOTO_KEY_PREFIX}/{uid}/{did}/{_PHOTO_KEY_SUBDIR}/{name}"


def is_person_photo(name: str) -> bool:
    """True when the leaf is a person/guard-detection variant (`_person.jpg`)."""
    return name.lower().endswith("_person.jpg")
