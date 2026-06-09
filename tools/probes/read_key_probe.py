"""LIVE read-only probe: issue routed-get for the app's t-key vocabulary.

[dreame-app-implementation-guide-2026-06-09.md] The app reads via
action(siid:2,aiid:50) {"m":"g","t":<KEY>,"d":<args>}. This issues that for each
key and pretty-prints the raw response inline with timestamps, so the responses
can be decoded into Phase 2 entities without the Mac MITM rig. Read-only; dev-box only.

Usage: /data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/read_key_probe.py
"""
from __future__ import annotations

import json
from datetime import datetime

# _probe_common injects HA stubs, adds repo root to sys.path, loads
# cloud_client via spec_from_file_location, and exposes connect().
# All probes in this directory use the same bootstrap; see _probe_common.py.
from _probe_common import connect

TOOL_META = {
    "domain": "probes",
    "run_by": "owner",
    "when": "When mapping app t-key vocabulary to Phase 2 entity values. Read-only.",
    "summary": "Issue routed-get for each app t-key and pretty-print raw responses inline with timestamps.",
}

KEYS = [
    ("MPOS", None), ("PREI", None), ("PRE", None), ("AIOBS", None),
    ("RGBPSTA", None), ("MITRC", {"idx": 0, "size": 20}), ("SCHDTV3", None),
    ("MAPI", None), ("MAPL", None), ("MISTA", None), ("OBS", None),
]


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main() -> None:
    cloud = connect()
    for key, d in KEYS:
        try:
            resp = cloud.action(siid=2, aiid=50, parameters=[{"m": "g", "t": key, "d": d}])
        except Exception as ex:  # noqa: BLE001
            print(f"[{_ts()}] t={key}: raised {ex!r}")
            continue
        print(f"[{_ts()}] t={key}  d={d} →")
        print(json.dumps(resp, indent=2, default=str)[:2000])
        print("-" * 60)


if __name__ == "__main__":
    main()
