#!/usr/bin/env python3
"""Wire-census coverage guard CLI.

  python tools/wire_census.py                       # regenerate docs/research/wire-census.json
  python tools/wire_census.py --seed                # print inventory seed blocks
  python tools/wire_census.py --unknowns            # report unregistered values + circumstance

Probe logs default to the dev-box parent dir; override with --log-dir.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wire_census_lib import build_census, seed_blocks  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tools._toolmeta import add_to_parser  # noqa: E402

TOOL_META = {"domain": "inventory", "run_by": "owner",
    "when": "After a new probe capture lands, to regenerate the wire census and find unparked values.",
    "summary": "Regenerate docs/research/wire-census.json and report wire values missing from inventory."}

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_LOG_DIR = os.path.dirname(_REPO)  # /data/claude/homeassistant
_DEFAULT_OUT = os.path.join(_REPO, "docs", "research", "wire-census.json")


def _read_lines(log_dir: str):
    for f in sorted(glob.glob(os.path.join(log_dir, "probe_log_*.jsonl"))):
        with open(f) as fh:
            yield from fh


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log-dir", default=_DEFAULT_LOG_DIR)
    ap.add_argument("--out", default=_DEFAULT_OUT)
    ap.add_argument("--seed", action="store_true", help="print inventory seed blocks")
    ap.add_argument("--unknowns", action="store_true", help="report unregistered values")
    add_to_parser(ap, TOOL_META)
    args = ap.parse_args(argv)

    census = build_census(_read_lines(args.log_dir))
    if args.seed:
        print(seed_blocks(census))
        return 0
    if args.unknowns:
        return _report_unknowns(census)
    with open(args.out, "w") as fh:
        json.dump(census, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.out} ({len(census)} properties)")
    return 0


def _report_unknowns(census: dict) -> int:
    import yaml as _yaml

    from wire_census_lib import check_coverage

    inv_path = os.path.join(
        _REPO, "custom_components", "dreame_a2_mower", "inventory.yaml")
    doc = _yaml.safe_load(open(inv_path))
    idx: dict = {}

    def walk(n):
        if isinstance(n, dict):
            if "siid" in n and "piid" in n and "value_kind" in n:
                idx[(int(n["siid"]), int(n["piid"]))] = n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for it in n:
                walk(it)
    walk(doc)

    viols = check_coverage(census, idx)
    if not viols:
        print("No unregistered wire values — inventory fully covers the census.")
        return 0
    print(f"{len(viols)} unregistered wire value(s):\n")
    for v in viols:
        print("  -", v)
    print(
        "\nClassification aids: grep OLD/ (esp. dreame-mower device_code.py / "
        "const.py — its names matched ALL our confirmed codes); cross-check the "
        "value's first_seen timestamp against the s2p1/s2p2/activity window in the "
        "raw mqtt_message logs; or propose a labelled toggle/action test. Names + "
        "meaning go in inventory.yaml ONLY — never sourced from the probe's PRETTY "
        "names (those mirror our possibly-stale labels).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
