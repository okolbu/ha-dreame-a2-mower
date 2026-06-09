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


def is_person_photo(name: str) -> bool:
    return name.lower().endswith("_person.jpg")


def main(name: str) -> None:
    cloud = connect()
    uid, did = str(cloud._uid), str(cloud._did)
    # LIVE-VERIFIED 2026-06-09: get_interim_file_url (cloud getDownloadUrl)
    # prepends `oss/media/000000/oss/` itself, so the object_name is the BARE
    # form <uid>/<did>/ali_dreame/<name>. get_file_url is the wrong signer
    # (479D path + [1:] strip). This matches protocol/photo_keys.build_photo_object_key.
    obj = f"{uid}/{did}/ali_dreame/{name}"
    print(f"[{_ts()}] uid={uid} did={did} name={name} (person={is_person_photo(name)})")
    print(f"[{_ts()}] object_name = {obj!r}")
    try:
        url = cloud.get_interim_file_url(obj)
    except Exception as ex:  # noqa: BLE001
        print(f"[{_ts()}] get_interim_file_url raised: {ex!r}")
        return
    keypath = str(url).split("?", 1)[0] if url else url
    print(f"[{_ts()}] signed key → {keypath!r}")
    if url:
        body = cloud.get_file(url)
        ok = bool(body) and body[:2] == b"\xff\xd8"
        print(f"[{_ts()}] downloaded {len(body or b'')} bytes, jpeg={ok}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    main(sys.argv[1])
