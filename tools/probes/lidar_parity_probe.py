"""LIVE read-only probe: is our 3dmap object the same one the app renders?

[dreame-app-implementation-guide-2026-06-09.md] reports the app fetches a
153,261-point PCD dated 2026/04/20. This lists our OBJ objects, fetches the
newest, decodes the PCD header, and prints name/date/point count so we can tell
whether OBJ-list hands us a stale/sparser object or the dense scan is on a
surface we don't reach.

Usage: /data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/lidar_parity_probe.py
"""
from __future__ import annotations

from datetime import datetime

# _probe_common injects HA stubs, adds repo root to sys.path, loads
# cloud_client via spec_from_file_location, and exposes connect().
# All probes in this directory use the same bootstrap; see _probe_common.py.
from _probe_common import connect

TOOL_META = {
    "domain": "probes",
    "run_by": "owner",
    "when": "When checking whether our OBJ-list 3dmap object matches the dense PCD the app renders.",
    "summary": "List 3dmap OBJ objects, fetch newest, decode PCD header, print name/bytes/point-count vs app reference.",
}


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _pcd_points(body: bytes) -> int | str:
    """Parse the declared point count from a PCD ASCII header (the `POINTS <n>`
    line lives in the first few hundred bytes, before `DATA binary`). Done inline
    to avoid importing protocol.pcd, which would trigger the integration package
    __init__ (homeassistant.*) that the probe stubs don't cover."""
    import re
    head = body[:512].decode("ascii", "replace")
    m = re.search(r"^POINTS\s+(\d+)", head, re.MULTILINE)
    return int(m.group(1)) if m else "no POINTS line in header"


def main() -> None:
    cloud = connect()
    names = cloud.list_3dmap_objects()
    print(f"[{_ts()}] list_3dmap_objects → {names!r}")
    if not names:
        print("No 3dmap objects from OBJ-list (None=80001/failure, []=empty).")
        return
    for name in names[:3]:
        url = cloud.get_interim_file_url(name)
        body = cloud.get_file(url) if url else None
        if not body:
            print(f"[{_ts()}] {name}: no body")
            continue
        print(f"[{_ts()}] {name}: {len(body)} bytes, points={_pcd_points(body)}")
    print("App reference: <did>_154157120.0550.bin, 153261 points, 2026/04/20.")


if __name__ == "__main__":
    main()
