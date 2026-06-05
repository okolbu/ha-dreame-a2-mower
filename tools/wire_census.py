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

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    # Implemented in Task 7; default no-op stub so the CLI parses.
    print("(--unknowns report implemented in Task 7)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
