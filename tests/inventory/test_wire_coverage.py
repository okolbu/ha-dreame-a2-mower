"""CI gate: every property/value in docs/research/wire-census.json must be
registered (or parked) in inventory.yaml. Fails on an unparked novelty or an
unregistered property — the durable "inventory can't silently drift from the
wire" guard.
"""
from __future__ import annotations

import json
import os
import sys

import yaml

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "tools", "inventory"))
from wire_census_lib import check_coverage  # noqa: E402


def _load_inventory_index() -> dict[tuple, dict]:
    path = os.path.join(_REPO, "custom_components", "dreame_a2_mower", "inventory.yaml")
    doc = yaml.safe_load(open(path))
    idx: dict[tuple, dict] = {}

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
    return idx


def test_wire_census_fully_covered_by_inventory():
    census = json.load(
        open(os.path.join(_REPO, "docs", "research", "wire-census.json")))
    inv = _load_inventory_index()
    violations = check_coverage(census, inv)
    assert not violations, (
        "Wire values not registered in inventory (decode them, or park as "
        "status: unknown via tools/inventory/wire_census.py --seed):\n  "
        + "\n  ".join(violations)
    )


_VALUE_KINDS = {"enum", "counter", "continuous", "blob", "nested"}
_STATUSES = {"confirmed", "partial", "presumed", "unknown"}


def test_value_kind_and_observed_fields_are_well_formed():
    """Catch typos / malformed value_kind / observed_values / observed_shapes
    (the schema validator is permissive about unknown keys, so guard them here)."""
    errs: list[str] = []
    for ident, e in _load_inventory_index().items():
        tag = f"s{ident[0]}p{ident[1]}"
        kind = e.get("value_kind")
        if kind not in _VALUE_KINDS:
            errs.append(f"{tag}: value_kind {kind!r} not in {sorted(_VALUE_KINDS)}")
        for ov in (e.get("observed_values") or []):
            if not isinstance(ov.get("value"), int) or ov.get("status") not in _STATUSES:
                errs.append(f"{tag}: bad observed_values entry {ov!r}")
        for os_ in (e.get("observed_shapes") or []):
            if not isinstance(os_.get("sig"), str) or os_.get("status") not in _STATUSES:
                errs.append(f"{tag}: bad observed_shapes entry {os_!r}")
    assert not errs, "Malformed value_kind/observed_* fields:\n  " + "\n  ".join(errs)
