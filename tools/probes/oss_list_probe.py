"""LIVE read-only probe: list what photos are actually in cloud OSS right now.

Calls list_oss_media('jpg') (iotoss/userDidOssList) directly against the cloud,
independent of whether the app has opened the gallery. Prints recent records
with decoded detection timestamps so we can confirm a given photo exists.

Dev-box only, read-only. Usage:
  python tools/probes/oss_list_probe.py [substring-to-grep]
"""
from __future__ import annotations

import re
import sys
from datetime import datetime

import os

from _probe_common import connect

# Mac mount uses /Volumes/claude; server uses /data/claude. Pick whichever exists.
_CREDS = next(
    (p for p in (
        "/Volumes/claude/homeassistant/secrets/server-credentials.txt",
        "/data/claude/homeassistant/secrets/server-credentials.txt",
    ) if os.path.isfile(p)),
    None,
)


def _decode_ts(name: str) -> str:
    m = re.match(r"(\d{10})", name or "")
    if not m:
        return ""
    try:
        return datetime.fromtimestamp(int(m.group(1))).strftime("%m-%d %H:%M:%S")
    except Exception:
        return ""


def main(grep: str | None) -> None:
    cloud = connect(_CREDS) if _CREDS else connect()
    recs = cloud.list_oss_media("jpg", size=20, max_pages=10) or []
    print(f"total jpg records in cloud OSS: {len(recs)}")
    rows = []
    for r in recs:
        if not isinstance(r, dict):
            continue
        # surface the filename from whatever field carries it
        fp = r.get("filepath") or r.get("filePath") or r.get("name") or ""
        leaf = str(fp).split("?", 1)[0].rstrip("/").split("/")[-1]
        rows.append((leaf, r))
    # sort by leading epoch desc
    def keyf(t):
        m = re.match(r"(\d{10})", t[0])
        return int(m.group(1)) if m else 0
    rows.sort(key=keyf, reverse=True)
    print("most recent 25 (decoded detection time | leaf):")
    for leaf, r in rows[:25]:
        mark = "  <<<" if (grep and grep in leaf) else ""
        print(f"  {_decode_ts(leaf):>17}  {leaf}{mark}")
    if grep:
        hit = [leaf for leaf, _ in rows if grep in leaf]
        print(f"\ngrep '{grep}': {len(hit)} match(es) -> {hit[:10]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
