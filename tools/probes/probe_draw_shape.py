"""LIVE probe: draw a no-go shape of an arbitrary type via o:215.

Purpose: test the UNUSED novelty-shape type ids (10, 12) that have no app UI —
does the firmware have a hidden shape tied to them, or does it reject the type?

Sends the map-edit transaction the app uses for placing a Shapes-screen stencil:
  o:200 {idx} (activate map) -> o:204 (begin) -> o:215 {id:-1, type:T, points, radius}
  -> o:201 (commit). Prints each leg's device r-code.

Usage (dev-box OR mac, creds path auto-detected):
  python3 tools/probes/probe_draw_shape.py [TYPE] [MAP_IDX]
  e.g.  python3 tools/probes/probe_draw_shape.py 10
The created zone (if any) can be removed in-app or via o:218 {id, type:0}.
"""
from __future__ import annotations

import os
import sys
import time
import json

from _probe_common import connect

# /Volumes/claude (mac) and /data/claude (server) are the same NFS share.
_CRED_CANDIDATES = [
    "/data/claude/homeassistant/secrets/server-credentials.txt",
    "/Volumes/claude/homeassistant/secrets/server-credentials.txt",
]

TOOL_META = {
    "domain": "probes",
    "run_by": "owner",
    "when": "Testing whether unused o:215 shape types (10/12) have a hidden firmware shape.",
    "summary": "Draw a no-go shape of an arbitrary type via the o:204/215/201 map-edit txn.",
}


def _creds_path() -> str:
    for p in _CRED_CANDIDATES:
        if os.path.exists(p):
            return p
    return _CRED_CANDIDATES[0]


def _act(c, **item):
    return c.action(siid=2, aiid=50, parameters=[{"m": "a", "p": 0, **item}])


def main() -> int:
    shape_type = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    map_idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    # a point known to be on the lawn (reuse a coord from a captured draw, metres)
    cx, cy = -5.5, -2.3
    bbox = [[cx - 0.75, cy - 0.75], [cx + 0.75, cy + 0.75]]

    c = connect(_creds_path())
    print(f"# probe_draw_shape: type={shape_type} on map idx={map_idx} at ({cx},{cy}) m\n")

    print(f"Step 1: o:200 activate map idx={map_idx}")
    print("  ->", json.dumps(_act(c, o=200, d={"idx": map_idx}))[:160], "\n")

    print("Step 2: o:204 begin edit")
    print("  ->", json.dumps(_act(c, o=204))[:160], "\n")

    # send both a bbox (stencil style) AND a radius (parametric style) so either
    # shape kind has what it needs.
    d = {"id": -1, "type": shape_type, "points": bbox, "radius": 1.0}
    print(f"Step 3: o:215 add shape  d={json.dumps(d)}")
    res = _act(c, o=215, d=d)
    print("  ->", json.dumps(res)[:300], "\n")
    time.sleep(1)

    print("Step 4: o:201 commit")
    print("  ->", json.dumps(_act(c, o=201))[:160], "\n")

    print("Done. Check the app map for a shape; if one appeared, note its glyph.")
    print("Remove with: in-app delete, or o:218 {id:<assigned>, type:0}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
