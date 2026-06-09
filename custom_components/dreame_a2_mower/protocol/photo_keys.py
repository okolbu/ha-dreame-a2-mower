"""Build OSS object names for album (Patrol + AI-obstacle) photos.

[dreame-app-implementation-guide-2026-06-09.md] The full OSS object key in the
dreame-eu.oss-eu-central-1 bucket is
``oss/media/000000/oss/<uid>/<did>/ali_dreame/<name>``, where ``<name>`` is a
``photo_list`` leaf from the session-summary ``.0550.json`` (a bare
``<unix_ts>.jpg`` or a ``<unix_ts>_person.jpg`` person-detection variant).

LIVE-VERIFIED 2026-06-09 (tools/probes/oss_photo_probe.py): the cloud
``getDownloadUrl`` (``cloud_client.get_interim_file_url``) PREPENDS the
``oss/media/000000/oss/`` media prefix to the object_name we pass — passing the
full prefixed key double-prefixes and 404s. So ``build_photo_object_key`` returns
the BARE object_name ``<uid>/<did>/ali_dreame/<name>``, and ``get_interim_file_url``
is the correct signer (NOT ``get_file_url``, which builds a 479D path + strips a
char). Confirmed end-to-end: a real photo downloaded as a 57 KB JPEG.

This module is pure (no HA, no network) and unit-testable in isolation.
"""
from __future__ import annotations

# The media prefix the cloud getDownloadUrl prepends ITSELF (do NOT include it in
# the object_name passed to get_interim_file_url). Kept for documentation of the
# full bucket key layout.
_FULL_KEY_PREFIX = "oss/media/000000/oss"
_PHOTO_KEY_SUBDIR = "ali_dreame"


def build_photo_object_key(*, uid: str, did: str, name: str) -> str:
    """Return the object_name to pass to ``get_interim_file_url`` for one photo.

    This is the BARE form ``<uid>/<did>/ali_dreame/<name>`` — the cloud prepends
    ``oss/media/000000/oss/`` itself (live-verified; see module docstring).
    """
    return f"{uid}/{did}/{_PHOTO_KEY_SUBDIR}/{name}"


def is_person_photo(name: str) -> bool:
    """True when the leaf is a person/guard-detection variant (`_person.jpg`)."""
    return name.lower().endswith("_person.jpg")
