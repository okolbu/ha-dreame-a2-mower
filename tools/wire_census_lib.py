"""Pure helpers for the wire-census coverage guard (no I/O).

The census keys purely on raw (siid,piid) + value from the probe's mqtt_message
stream. It is naming-agnostic and decode-agnostic on purpose: the probe's own
PRETTY names mirror the integration's (possibly stale) naming, so using them
would feed stale names back into inventory. Names/meaning live ONLY in
inventory.yaml.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

_COUNTER_DISTINCT_THRESHOLD = 32  # > this many distinct ints + wide range -> counter


def _walk_props(obj: Any):
    """Yield (siid, piid, value) for every property dict anywhere in a payload."""
    if isinstance(obj, dict):
        if "siid" in obj and "piid" in obj:
            yield (obj.get("siid"), obj.get("piid"), obj.get("value"))
        for v in obj.values():
            yield from _walk_props(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_props(v)


def _shape_sig(value: dict) -> str:
    """A stable signature for a nested (dict) value: sorted top-level key-set."""
    return ",".join(sorted(str(k) for k in value.keys()))


def _kind_hint(entry: dict) -> str:
    if entry["is_blob"]:
        return "blob"
    if entry["shape_sigs"]:
        return "nested"
    vals = entry["values"]
    if len(vals) > _COUNTER_DISTINCT_THRESHOLD and (max(vals) - min(vals)) > 64:
        return "counter"
    return "enum"


def build_census(lines: Iterable[str]) -> dict[str, dict]:
    """Aggregate probe-log jsonl lines into a per-property census.

    Returns {"sNpM": {siid, piid, value_kind_hint, values:[sorted int],
    shape_sigs:[sorted str], is_blob:bool, first_seen:{str(value):ts}, count:int}}.
    """
    acc: dict[str, dict] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") != "mqtt_message":
            continue
        ts = rec.get("timestamp", "")
        for siid, piid, value in _walk_props(rec.get("payload")):
            if siid is None or piid is None:
                continue
            key = f"s{siid}p{piid}"
            e = acc.setdefault(key, {
                "siid": int(siid), "piid": int(piid),
                "values": set(), "shape_sigs": set(), "is_blob": False,
                "first_seen": {}, "count": 0,
            })
            e["count"] += 1
            sig = None
            if isinstance(value, bool):
                sig = int(value)
                e["values"].add(sig)
            elif isinstance(value, int):
                sig = value
                e["values"].add(sig)
            elif isinstance(value, dict):
                sig = _shape_sig(value)
                e["shape_sigs"].add(sig)
            else:  # list / str / other -> opaque blob, presence only
                e["is_blob"] = True
            if sig is not None:
                e["first_seen"].setdefault(str(sig), ts)
    # finalise: sets -> sorted lists, add kind hint
    out: dict[str, dict] = {}
    for key in sorted(acc, key=lambda k: (acc[k]["siid"], acc[k]["piid"])):
        e = acc[key]
        e["values"] = sorted(e["values"])
        e["shape_sigs"] = sorted(e["shape_sigs"])
        e["value_kind_hint"] = _kind_hint(e)
        out[key] = e
    return out


def check_coverage(census: dict[str, dict], inventory: dict[tuple, dict]) -> list[str]:
    """Return a list of human-readable coverage violations (empty == pass).

    inventory: {(siid,piid): {value_kind, observed_values:[{value,status}],
    observed_shapes:[{sig,status}]}}. For value_kind 'enum' every census value
    must be parked in observed_values; 'nested' every shape-sig in observed_shapes;
    'counter'/'continuous'/'blob' -> property-presence only (no value check).
    """
    violations: list[str] = []
    for key, c in census.items():
        ident = (c["siid"], c["piid"])
        inv = inventory.get(ident)
        if inv is None:
            violations.append(f"{key}: seen on wire but no inventory entry")
            continue
        kind = inv.get("value_kind")
        if kind == "enum":
            parked = {ov["value"] for ov in (inv.get("observed_values") or [])}
            for v in c["values"]:
                if v not in parked:
                    violations.append(
                        f"{key}: unparked value {v} — decode it or add "
                        f"observed_values [{{value: {v}, status: unknown}}]")
        elif kind == "nested":
            parked = {ov["sig"] for ov in (inv.get("observed_shapes") or [])}
            for sig in c["shape_sigs"]:
                if sig not in parked:
                    violations.append(
                        f"{key}: unparked nested shape {sig!r} — add "
                        f"observed_shapes [{{sig: {sig!r}, status: unknown}}]")
        elif kind in ("counter", "continuous", "blob"):
            pass  # presence-only; the entry exists, that's enough
        else:
            violations.append(
                f"{key}: inventory entry missing value_kind "
                f"(enum|counter|continuous|blob|nested)")
    return violations
