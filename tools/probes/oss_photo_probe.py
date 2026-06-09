"""LIVE read-only probe: verify which OSS signing endpoint resolves a photo key.

[dreame-app-implementation-guide-2026-06-09.md] Photos sit at
oss/media/000000/oss/<uid>/<did>/ali_dreame/<name>. The capture used a
pre-signed URL we cannot replay (Expires-limited), so we must sign the key
ourselves. This probe tries get_interim_file_url(key) and get_file_url(key)
against a real photo_list leaf and reports which returns a 200-downloadable URL.

Dev-box only. Pretty-prints inline with timestamps.
Usage:
  /data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/oss_photo_probe.py <photo_name.jpg>
where <photo_name.jpg> is a leaf from a recent session summary's photo_list.
"""
from __future__ import annotations

import sys
from datetime import datetime

# _probe_common injects HA stubs, adds repo root to sys.path, loads
# cloud_client via spec_from_file_location, and exposes connect().
# All probes in this directory use the same bootstrap; see _probe_common.py.
from _probe_common import connect

TOOL_META = {
    "domain": "probes",
    "run_by": "owner",
    "when": "When verifying which OSS signing endpoint resolves a photo key. Read-only.",
    "summary": "Probe get_interim_file_url vs get_file_url for a photo_list OSS key.",
}


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main(name: str) -> None:
    from custom_components.dreame_a2_mower.protocol.photo_keys import (
        build_photo_object_key,
        is_person_photo,
    )

    cloud = connect()
    # _uid and _did are the real private attribute names on DreameA2CloudClient
    # (see cloud_client/__init__.py lines 80, 97 — set in __init__ and used by
    # get_file_url, mqtt_topic, object_name etc.).
    key = build_photo_object_key(uid=str(cloud._uid), did=str(cloud._did), name=name)
    print(f"[{_ts()}] photo key = {key}  (person={is_person_photo(name)})")

    for label, fn in (
        ("get_interim_file_url", cloud.get_interim_file_url),
        ("get_file_url", cloud.get_file_url),
    ):
        try:
            url = fn(key)
        except Exception as ex:  # noqa: BLE001
            print(f"[{_ts()}] {label}: raised {ex!r}")
            continue

        # NOTE — get_file_url caveat: the implementation in _oss.py line 64
        # passes `"filename": object_name[1:]` (strips the first character).
        # Our key has NO leading slash, so [1:] strips the first real character
        # (the leading 'o' of 'oss/media/…'). This is likely wrong and may
        # cause a 'key not found' response. The probe is precisely to observe
        # which endpoint+form works; if get_file_url fails, try passing
        # '/' + key to give [1:] the slash to strip instead.
        print(f"[{_ts()}] {label}: url={str(url)[:120]!r}")
        if url:
            body = cloud.get_file(url)
            ok = bool(body) and body[:2] == b"\xff\xd8"
            print(
                f"[{_ts()}] {label}: downloaded {len(body or b'')} bytes, jpeg={ok}"
            )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    main(sys.argv[1])
