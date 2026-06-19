"""LIVE read-only probe: download named OSS photos to disk so they can be viewed.

Signs each key via get_interim_file_url (the LIVE-verified signer) and writes the
bytes to <outdir>/<name>. Dev-box only, read-only.

Usage:
  python tools/probes/oss_fetch_probe.py <outdir> <name1.jpg> [<name2.jpg> ...]
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

from _probe_common import connect

_CREDS = next(
    (p for p in (
        "/Volumes/claude/homeassistant/secrets/server-credentials.txt",
        "/data/claude/homeassistant/secrets/server-credentials.txt",
    ) if os.path.isfile(p)),
    None,
)


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main(outdir: str, names: list[str]) -> None:
    os.makedirs(outdir, exist_ok=True)
    cloud = connect(_CREDS) if _CREDS else connect()
    uid, did = str(cloud._uid), str(cloud._did)
    for name in names:
        obj = f"{uid}/{did}/ali_dreame/{name}"
        try:
            url = cloud.get_interim_file_url(obj)
        except Exception as ex:  # noqa: BLE001
            print(f"[{_ts()}] {name}: get_interim_file_url raised: {ex!r}")
            continue
        if not url:
            print(f"[{_ts()}] {name}: no signed URL returned")
            continue
        body = cloud.get_file(url)
        if not body:
            print(f"[{_ts()}] {name}: download returned empty")
            continue
        is_jpeg = body[:2] == b"\xff\xd8"
        dest = os.path.join(outdir, name)
        with open(dest, "wb") as f:
            f.write(body)
        print(f"[{_ts()}] {name}: wrote {len(body)} bytes jpeg={is_jpeg} -> {dest}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2:])
