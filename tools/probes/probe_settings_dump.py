#!/usr/bin/env python3
"""READ-ONLY: dump the live SETTINGS structure + map keying to diagnose the
per-map mowingDirection mis-read (map2 reads 180, app uses 118).

Reuses probe_pre_write's module bootstrap + credential/client setup. Makes a
single read (`fetch_full_cloud_state`) and prints:
  - settings.raw: each top-level entry's settings-dict keys, with
    mowingDirection / mowingDirectionMode per key (the 5 "sets").
  - by_map_id_canonical: what the integration actually resolves per key.
  - maps_by_id keys (cloud map ids) + mapl (active map).

No writes. Credentials: see probe_pre_write.py.
"""
from __future__ import annotations

import json

from probe_pre_write import _build_cloud_client, DEFAULT_CREDS_PATH


def _pick(d, *keys):
    return {k: d.get(k) for k in keys if isinstance(d, dict)}


def main() -> int:
    client = _build_cloud_client(DEFAULT_CREDS_PATH)
    cs = client.fetch_full_cloud_state()
    if cs is None:
        print("fetch_full_cloud_state returned None (relay asleep?)")
        return 1

    print("=== maps_by_id keys (cloud map ids) ===")
    print(sorted(cs.maps_by_id.keys()))
    print("=== mapl (active-map list) ===")
    print(json.dumps(cs.mapl)[:500])

    print("\n=== settings.raw: top-level entries ===")
    raw = cs.settings.raw or []
    print(f"entry count: {len(raw)}")
    for ei, entry in enumerate(raw):
        sd = entry.get("settings") if isinstance(entry, dict) else None
        mode = entry.get("mode") if isinstance(entry, dict) else None
        print(f"\n-- entry[{ei}] mode={mode} version={entry.get('version') if isinstance(entry, dict) else None}")
        if not isinstance(sd, dict):
            print("   (no settings dict)")
            continue
        print(f"   settings keys: {list(sd.keys())}")
        for k, v in sd.items():
            if isinstance(v, dict):
                print(f"   [{k}] {_pick(v, 'mowingDirection', 'mowingDirectionMode', 'mowingHeight')}")

    print("\n=== by_map_id_canonical (what the integration resolves) ===")
    for k, v in sorted(cs.settings.by_map_id_canonical.items()):
        print(f"   map_id={k}: {_pick(v, 'mowingDirection', 'mowingDirectionMode', 'mowingHeight')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
