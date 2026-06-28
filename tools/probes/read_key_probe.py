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

# d-args are the app's MITM-confirmed shapes [app-mitm:2026-06-09/19]; None → bare
# GET (no d field sent — matches the app exactly). Per-map/paged keys probed at idx 0+1.
KEYS = [
    # Confirmed-shape reads — parity re-pull
    ("MPOS", None), ("PRE", None), ("MAPL", None), ("MISTA", None), ("SCHDTV3", None),
    ("RGBPSTA", {"idx": 0}), ("RGBPSTA", {"idx": 1}),
    ("PREI", {"idx": 0}), ("PREI", {"idx": 1}),
    ("MAPI", {"idx": 0}), ("MAPI", {"idx": 1}),
    ("MAPD", {"start": 0, "size": 400}),
    ("MITRC", {"idx": 0, "size": 60}),
    ("OBS", {"idx": 0}), ("AIOBS", {"idx": 0}),
    # Still-open individual keys — old r=-3 was a wrong endpoint/args; re-probe the app path.
    # If one path returns r=-3, the key may resolve on the getCFG bundle instead (multi-path).
    ("IOT", None), ("PREP", {"idx": 0}),
    ("ARM", None), ("CHECK", None), ("RPET", None), ("WINFO", None),
]


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main() -> None:
    cloud = connect()
    for key, d in KEYS:
        # Match the app exactly: omit the d field for bare GETs (sending d:null can
        # spuriously r=-3 on keys the app reads with no args).
        param = {"m": "g", "t": key}
        if d is not None:
            param["d"] = d
        try:
            resp = cloud.action(siid=2, aiid=50, parameters=[param])
        except Exception as ex:  # noqa: BLE001
            print(f"[{_ts()}] t={key}: raised {ex!r}")
            continue
        print(f"[{_ts()}] t={key}  d={d} →")
        print(json.dumps(resp, indent=2, default=str)[:2000])
        print("-" * 60)


if __name__ == "__main__":
    main()
