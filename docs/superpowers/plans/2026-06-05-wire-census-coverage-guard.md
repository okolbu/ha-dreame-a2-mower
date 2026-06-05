# Wire-Census Coverage Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CI-gated guarantee that `inventory.yaml` accounts for every `(siid,piid)` and (for discrete props) every distinct value the g2408 sends, via a committed wire-census artifact distilled from the probe corpus — failing CI on unparked novelties while letting undecoded values be parked `unknown`.

**Architecture:** A pure census builder reads the raw `mqtt_message` stream from `probe_log_*.jsonl` and classifies each property by its value's Python type (`bool`/`int`→discrete, `dict`→nested shape-sig, `list`/`str`→blob). `tools/wire_census.py` writes `docs/research/wire-census.json` (the in-repo CI bridge). `inventory.yaml` entries gain `value_kind` + `observed_values`/`observed_shapes`. A pure coverage checker + `tests/inventory/test_wire_coverage.py` gate the diff. The census is **naming-agnostic** — names live only in inventory (the probe's names mirror our possibly-stale ones, so using them would feed stale names back).

**Tech Stack:** Python 3.13 (stubbed-HA vanilla venv: `/data/claude/homeassistant/.venv-vanilla/bin/python`), pytest, PyYAML. Probe logs at `/data/claude/homeassistant/probe_log_*.jsonl` (parent dir, NOT in repo). Branch: `feat/wire-census-coverage-guard` (spec already committed).

**Spec:** `docs/superpowers/specs/2026-06-05-wire-census-coverage-guard-design.md`

---

## Corpus facts (verified 2026-06-05, ground the code)

- `probe_log_*.jsonl` entries have `type` ∈ {`session_start`,`mqtt_connected`,`mqtt_message`,`pretty`,`deep`}. Only `mqtt_message` is read for the census.
- An `mqtt_message` entry: `{"type":"mqtt_message","timestamp":"YYYY-MM-DD HH:MM:SS","topic":...,"payload":{"data":{"method":"properties_changed","params":[{"siid":N,"piid":M,"value":V},...]}}}`. The `params` may be nested under `payload.data`; values appear as `{siid,piid,value}` dicts somewhere inside `payload`.
- Value Python-type per property (authoritative): `s1p53`=**bool**; `s2p1/s2p2/s2p53/s2p54/s2p62/s3p1/s3p2/s5p104-108/s6p1/s6p117`=**int**; `s1p50/51/52/s2p50/51/52/55/56`=**dict**; `s1p1/s1p4/s2p66/s6p2/s6p3`=**list** (byte arrays); `s2p65/s99p20`=**str**.

## File Structure

| File | Responsibility |
|---|---|
| Create `tools/wire_census_lib.py` | Pure functions: `build_census(lines)`, `check_coverage(census, inventory)`, `seed_blocks(census)` — no I/O, unit-testable |
| Create `tools/wire_census.py` | CLI: default (write json), `--seed`, `--unknowns`; reads probe dir, calls the lib |
| Create `docs/research/wire-census.json` | Committed census artifact (CI bridge) |
| Modify `custom_components/dreame_a2_mower/inventory.yaml` | `value_kind` + `observed_values`/`observed_shapes` per observed entry |
| Modify `tools/inventory_gen.py` | Schema validator accepts/validates the new fields |
| Create `tests/tools/test_wire_census.py` | Unit tests for the lib (parser + checker + seed) |
| Create `tests/inventory/test_wire_coverage.py` | CI gate: wire-census.json ⊆ inventory |

---

## Task 1: Census builder — value-type classification

**Files:**
- Create: `tools/wire_census_lib.py`
- Test: `tests/tools/test_wire_census.py`

- [ ] **Step 1: Write the failing test**

Create `tests/tools/test_wire_census.py`:

```python
from __future__ import annotations
import json
from tools.wire_census_lib import build_census


def _line(siid, piid, value, ts="2026-05-20 13:00:00"):
    return json.dumps({
        "type": "mqtt_message", "timestamp": ts,
        "payload": {"data": {"method": "properties_changed",
                             "params": [{"siid": siid, "piid": piid, "value": value}]}},
    })


def test_build_census_classifies_by_value_type():
    lines = [
        _line(5, 104, 7), _line(5, 104, 12),          # int -> discrete enum
        _line(1, 53, True), _line(1, 53, False),       # bool -> discrete
        _line(2, 50, {"d": {"o": 107}, "t": "TASK"}),  # dict -> nested shape-sig
        _line(1, 1, [206, 0, 0]),                      # list -> blob
        _line(99, 20, "abc"),                          # str -> blob
    ]
    c = build_census(lines)
    assert c["s5p104"]["values"] == [7, 12]
    assert c["s5p104"]["value_kind_hint"] == "enum"
    assert set(c["s1p53"]["values"]) == {0, 1}          # bool normalised to 0/1
    assert c["s2p50"]["shape_sigs"] == ["d,t"]          # sorted top-level keys
    assert c["s2p50"]["value_kind_hint"] == "nested"
    assert c["s1p1"]["is_blob"] is True
    assert c["s1p1"]["value_kind_hint"] == "blob"
    assert c["s99p20"]["is_blob"] is True


def test_build_census_counter_hint_for_wide_int_spread():
    lines = [_line(5, 107, v) for v in range(0, 200, 2)]  # 100 distinct, wide
    c = build_census(lines)
    assert c["s5p107"]["value_kind_hint"] == "counter"


def test_build_census_first_seen_records_earliest_ts():
    lines = [_line(5, 104, 12, "2026-05-25 12:32:24"),
             _line(5, 104, 12, "2026-05-26 09:00:00")]
    c = build_census(lines)
    assert c["s5p104"]["first_seen"]["12"] == "2026-05-25 12:32:24"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_wire_census.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.wire_census_lib'`.

- [ ] **Step 3: Implement the builder**

Create `tools/wire_census_lib.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_wire_census.py -v`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add tools/wire_census_lib.py tests/tools/test_wire_census.py
git commit -m "feat(census): pure wire-census builder (value-type classification)"
```

---

## Task 2: Coverage checker

**Files:**
- Modify: `tools/wire_census_lib.py`
- Test: `tests/tools/test_wire_census.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/tools/test_wire_census.py`:

```python
from tools.wire_census_lib import check_coverage


def _census(**props):
    return props


def test_check_coverage_passes_when_all_values_parked():
    census = {"s5p104": {"siid": 5, "piid": 104, "value_kind_hint": "enum",
                         "values": [7, 12], "shape_sigs": [], "is_blob": False}}
    inv = {(5, 104): {"value_kind": "enum",
                      "observed_values": [{"value": 7, "status": "confirmed"},
                                          {"value": 12, "status": "unknown"}]}}
    assert check_coverage(census, inv) == []


def test_check_coverage_flags_unparked_value():
    census = {"s5p105": {"siid": 5, "piid": 105, "value_kind_hint": "enum",
                         "values": [1, 2, 3, 4, 5], "shape_sigs": [], "is_blob": False}}
    inv = {(5, 105): {"value_kind": "enum",
                      "observed_values": [{"value": v, "status": "confirmed"} for v in (1, 2, 4)]}}
    viols = check_coverage(census, inv)
    assert any("s5p105" in v and "3" in v for v in viols)
    assert any("s5p105" in v and "5" in v for v in viols)


def test_check_coverage_flags_unregistered_property():
    census = {"s9p9": {"siid": 9, "piid": 9, "value_kind_hint": "enum",
                       "values": [1], "shape_sigs": [], "is_blob": False}}
    viols = check_coverage(census, {})
    assert any("s9p9" in v and "no inventory entry" in v for v in viols)


def test_check_coverage_skips_counter_value_enumeration():
    census = {"s5p107": {"siid": 5, "piid": 107, "value_kind_hint": "counter",
                         "values": list(range(256)), "shape_sigs": [], "is_blob": False}}
    inv = {(5, 107): {"value_kind": "counter", "observed_values": []}}
    assert check_coverage(census, inv) == []


def test_check_coverage_checks_nested_shape_sigs():
    census = {"s2p50": {"siid": 2, "piid": 50, "value_kind_hint": "nested",
                        "values": [], "shape_sigs": ["d,t", "exe,o,status"], "is_blob": False}}
    inv = {(2, 50): {"value_kind": "nested",
                     "observed_shapes": [{"sig": "d,t", "status": "confirmed"}]}}
    viols = check_coverage(census, inv)
    assert any("s2p50" in v and "exe,o,status" in v for v in viols)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_wire_census.py -k check_coverage -v`
Expected: FAIL — `ImportError: cannot import name 'check_coverage'`.

- [ ] **Step 3: Implement the checker**

Append to `tools/wire_census_lib.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_wire_census.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add tools/wire_census_lib.py tests/tools/test_wire_census.py
git commit -m "feat(census): coverage checker (parked/unparked/nested/counter)"
```

---

## Task 3: `--seed` block generator

**Files:**
- Modify: `tools/wire_census_lib.py`
- Test: `tests/tools/test_wire_census.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/tools/test_wire_census.py`:

```python
import yaml
from tools.wire_census_lib import seed_blocks


def test_seed_blocks_emits_valid_yaml_for_enum_and_nested():
    census = {
        "s5p104": {"siid": 5, "piid": 104, "value_kind_hint": "enum",
                   "values": [7, 12], "shape_sigs": [], "is_blob": False},
        "s2p50": {"siid": 2, "piid": 50, "value_kind_hint": "nested",
                  "values": [], "shape_sigs": ["d,t"], "is_blob": False},
        "s1p1": {"siid": 1, "piid": 1, "value_kind_hint": "blob",
                 "values": [], "shape_sigs": [], "is_blob": True},
    }
    text = seed_blocks(census)
    parsed = yaml.safe_load(text)
    assert parsed["s5p104"]["value_kind"] == "enum"
    assert {ov["value"] for ov in parsed["s5p104"]["observed_values"]} == {7, 12}
    # all seeded values start parked as unknown (decoder fills in meaning later)
    assert all(ov["status"] == "unknown" for ov in parsed["s5p104"]["observed_values"])
    assert parsed["s2p50"]["observed_shapes"][0]["sig"] == "d,t"
    assert parsed["s1p1"]["value_kind"] == "blob"
    assert "observed_values" not in parsed["s1p1"]  # blobs: presence only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_wire_census.py -k seed -v`
Expected: FAIL — `ImportError: cannot import name 'seed_blocks'`.

- [ ] **Step 3: Implement seed_blocks**

Append to `tools/wire_census_lib.py` (add `import yaml` near the top imports):

```python
def seed_blocks(census: dict[str, dict]) -> str:
    """Emit a YAML mapping {sNpM: {value_kind, observed_values|observed_shapes}}
    for one-time merge into inventory. All values start status: unknown (parked);
    the dev re-classifies value_kind (the hint is advisory) and decodes later.
    """
    out: dict[str, dict] = {}
    for key, c in census.items():
        block: dict = {"value_kind": c["value_kind_hint"]}
        if c["value_kind_hint"] == "enum":
            block["observed_values"] = [{"value": v, "status": "unknown"} for v in c["values"]]
        elif c["value_kind_hint"] == "nested":
            block["observed_shapes"] = [{"sig": s, "status": "unknown"} for s in c["shape_sigs"]]
        # counter/continuous/blob: no value list
        out[key] = block
    return yaml.safe_dump(out, sort_keys=False, default_flow_style=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_wire_census.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add tools/wire_census_lib.py tests/tools/test_wire_census.py
git commit -m "feat(census): --seed block generator (parked-unknown bootstrap)"
```

---

## Task 4: `tools/wire_census.py` CLI

**Files:**
- Create: `tools/wire_census.py`
- Test: `tests/tools/test_wire_census.py` (extend — CLI smoke via tmp dir)

- [ ] **Step 1: Write the failing test**

Append to `tests/tools/test_wire_census.py`:

```python
import subprocess, sys, os, glob as _glob


def test_cli_writes_census_json(tmp_path):
    logdir = tmp_path / "logs"
    logdir.mkdir()
    (logdir / "probe_log_1.jsonl").write_text(_line(5, 104, 7) + "\n" + _line(5, 104, 12) + "\n")
    out = tmp_path / "wire-census.json"
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run(
        [sys.executable, "tools/wire_census.py", "--log-dir", str(logdir), "--out", str(out)],
        cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    data = json.loads(out.read_text())
    assert data["s5p104"]["values"] == [7, 12]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_wire_census.py -k cli -v`
Expected: FAIL — `wire_census.py` does not exist (returncode != 0).

- [ ] **Step 3: Implement the CLI**

Create `tools/wire_census.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_wire_census.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add tools/wire_census.py tests/tools/test_wire_census.py
git commit -m "feat(census): wire_census.py CLI (default/--seed; --unknowns stub)"
```

---

## Task 5: Generate the real census + bootstrap inventory

**Files:**
- Create: `docs/research/wire-census.json` (generated)
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (add `value_kind` + `observed_values`/`observed_shapes` to the ~28 observed property entries)

This task is **data population**, not TDD. It makes the corpus real and parks every value.

- [ ] **Step 1: Generate the census artifact**

Run (note: writes into the repo):

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
/data/claude/homeassistant/.venv-vanilla/bin/python tools/wire_census.py
```

Expected: `wrote docs/research/wire-census.json (~28 properties)`.

- [ ] **Step 2: Emit the seed blocks for reference**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/wire_census.py --seed > /tmp/wire_seed.yaml
```

- [ ] **Step 3: Merge `value_kind` + `observed_values`/`observed_shapes` into each entry**

For every `sNpM` in `wire-census.json`, find its `inventory.yaml` entry and add the
fields. **Classify `value_kind` by hand** (the seed's hint is advisory):
- `enum` for code/flag sets: `s1p53` (bool), `s2p1`, `s2p2`, `s3p2`, `s2p53`, `s5p104`, `s5p105`, `s5p108`, `s6p1`, `s6p117`.
- `counter` for wide/monotone ints: `s3p1` (battery%), `s5p106`, `s5p107`, `s5p104`-style — inspect each via the census `values` range; if it's a 0–255 / large monotone span, mark `counter`.
- `nested` for dict props: `s1p50/51/52`, `s2p50/51/52/55/56`.
- `blob` for byte-array/str props: `s1p1`, `s1p4`, `s2p65`, `s2p66`, `s6p2`, `s6p3`, `s99p20`.
For `enum`, set `status: confirmed` on values whose meaning is ALREADY documented in
the entry (e.g. s2p2 codes in `state_codes`); set `status: unknown` on the rest
(e.g. `s5p104=12`, `s5p105=3` & `5`). For `nested`, park each shape-sig `unknown`
unless already decoded.

Each addition looks like:

```yaml
    value_kind: enum
    observed_values:
      - {value: 7, status: unknown}
      - {value: 12, status: unknown}
```

(Do this entry-by-entry; if a `(siid,piid)` in the census has NO inventory entry,
CREATE a minimal stub entry for it — `id`, `siid`, `piid`, `name: UNKNOWN`,
`semantic: "[UNKNOWN — to capture]"`, `status: {seen_on_wire: true, decoded: unknown}`
— so the gate's "no inventory entry" check passes.)

- [ ] **Step 4: Run the schema validator (will fail until Task 6 extends it)**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory_gen.py --validate-only`
Expected: it may reject the new fields — that's handled in Task 6. If it passes, good.

- [ ] **Step 5: Commit**

```bash
git add docs/research/wire-census.json custom_components/dreame_a2_mower/inventory.yaml
git commit -m "data(census): generate wire-census.json + park all wire values in inventory"
```

---

## Task 6: Extend the inventory schema validator

**Files:**
- Modify: `tools/inventory_gen.py`
- Test: `tests/inventory/test_wire_coverage.py` is Task 7; here just keep `--validate-only` green

- [ ] **Step 1: Inspect the validator's field allow-list / per-entry checks**

Run: `grep -n "value_kind\|observed_values\|allowed\|known_keys\|_VALIDATE\|def _validate\|decoded" tools/inventory_gen.py | head -30`
Read the function that validates each entry's keys (the one that knows `status`,
`semantic`, `verifications`, etc.).

- [ ] **Step 2: Write the failing check**

Add a tiny test `tests/inventory/test_value_kind_schema.py`:

```python
import subprocess, sys, os


def test_validate_only_accepts_value_kind_and_observed_values():
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    r = subprocess.run([sys.executable, "tools/inventory_gen.py", "--validate-only"],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "value_kind" not in (r.stdout + r.stderr).lower() or "invalid" not in (r.stdout + r.stderr).lower()
```

- [ ] **Step 3: Run it (fails if validator rejects the new fields)**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_value_kind_schema.py -v`
Expected: FAIL if the validator has a strict key allow-list rejecting `value_kind`/`observed_values`.

- [ ] **Step 4: Extend the validator**

In `tools/inventory_gen.py`, in the per-entry validation: add `value_kind`,
`observed_values`, `observed_shapes` to the allowed keys, and validate:
- `value_kind` ∈ `{enum, counter, continuous, blob, nested}`.
- `observed_values` is a list of `{value: int, status: <decoded-status>}`.
- `observed_shapes` is a list of `{sig: str, status: <decoded-status>}`.
- `status` ∈ the existing decoded vocab (`confirmed|partial|presumed|unknown`).

Mirror the existing validation style (the same frozensets the schema validator
already uses for `decoded`/status — keep them in sync, this is the recurring
`_DECODED_VALUES` gotcha).

- [ ] **Step 5: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory_gen.py --validate-only && /data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_value_kind_schema.py -v`
Expected: validator prints `ok`, test PASSES.

- [ ] **Step 6: Commit**

```bash
git add tools/inventory_gen.py tests/inventory/test_value_kind_schema.py
git commit -m "feat(inventory): validate value_kind + observed_values/_shapes fields"
```

---

## Task 7: The CI coverage gate + `--unknowns` report

**Files:**
- Create: `tests/inventory/test_wire_coverage.py`
- Modify: `tools/wire_census.py` (replace the `_report_unknowns` stub)

- [ ] **Step 1: Write the gate test**

Create `tests/inventory/test_wire_coverage.py`:

```python
"""CI gate: every property/value in docs/research/wire-census.json must be
registered (or parked) in inventory.yaml."""
from __future__ import annotations
import json, os
import yaml
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "tools"))
from wire_census_lib import check_coverage  # noqa: E402


def _load_inventory_index():
    path = os.path.join(_REPO, "custom_components", "dreame_a2_mower", "inventory.yaml")
    doc = yaml.safe_load(open(path))
    idx = {}

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
    census = json.load(open(os.path.join(_REPO, "docs", "research", "wire-census.json")))
    inv = _load_inventory_index()
    violations = check_coverage(census, inv)
    assert not violations, "Wire values not registered in inventory:\n" + "\n".join(violations)
```

- [ ] **Step 2: Run it**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_wire_coverage.py -v`
Expected: PASS if Task 5 parked everything; if it FAILS, the message lists the
exact unparked `sNpM=V` — go back to inventory and park/decode them, then re-run.
(This is the gate doing its job.)

- [ ] **Step 3: Implement `--unknowns`**

Replace `_report_unknowns` in `tools/wire_census.py`:

```python
def _report_unknowns(census: dict) -> int:
    import yaml as _yaml
    inv_path = os.path.join(_REPO, "custom_components", "dreame_a2_mower", "inventory.yaml")
    doc = _yaml.safe_load(open(inv_path))
    idx = {}

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

    from wire_census_lib import check_coverage
    viols = check_coverage(census, idx)
    if not viols:
        print("No unregistered wire values — inventory fully covers the census.")
        return 0
    print(f"{len(viols)} unregistered wire value(s):\n")
    for v in viols:
        print("  -", v)
    print("\nClassification aids: grep OLD/ (esp. dreame-mower device_code.py), "
          "check the value's first_seen timestamp vs the s2p1/s2p2 window in the "
          "raw mqtt_message logs, or propose a toggle/action test.")
    return 0
```

- [ ] **Step 4: Run the unknowns report (smoke)**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/wire_census.py --unknowns`
Expected: "No unregistered wire values…" (since Task 5 parked everything).

- [ ] **Step 5: Commit**

```bash
git add tests/inventory/test_wire_coverage.py tools/wire_census.py
git commit -m "feat(census): CI coverage gate + --unknowns classification report"
```

---

## Task 8: Wire into CI + full-suite green

**Files:**
- Modify: `.github/workflows/ci.yml` (ensure `tests/inventory/` + `tests/tools/` run)
- Verify: full suite

- [ ] **Step 1: Confirm the test jobs include the new tests**

Run: `grep -n "tests/inventory\|tests/tools\|pytest" .github/workflows/ci.yml | head`
If the CI runs the whole `tests/` tree, nothing to change. If it enumerates dirs,
add `tests/tools` (the inventory dir is presumably already run). Make the minimal
edit so both new test files run in CI.

- [ ] **Step 2: Run the FULL suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: all green — the new census/coverage tests pass, prior baseline (~2012
passed / 4 skipped) holds.

- [ ] **Step 3: Run the inventory validator + coverage gate together**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory_gen.py --validate-only && /data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_wire_coverage.py tests/tools/test_wire_census.py -q`
Expected: `ok: inventory schema valid` + all tests pass.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run wire-census coverage gate"
```

---

## Self-Review

**Spec coverage:**
- Census generator (naming-agnostic, raw mqtt, type-classification) → Task 1. ✓
- Coverage checker (enum/nested/counter/blob, parked vs unparked) → Task 2. ✓
- `--seed` bootstrap → Task 3; applied → Task 5. ✓
- `wire_census.py` CLI (default/`--seed`/`--unknowns`) → Tasks 4 + 7. ✓
- Committed `wire-census.json` CI bridge → Task 5 (generated), Task 7 (gate reads it). ✓
- Inventory `value_kind` + `observed_values`/`observed_shapes` + validator → Tasks 5 + 6. ✓
- CI gate (fail on unparked/unregistered) → Task 7. ✓
- `--unknowns` (circumstance + OLD/ grep) → Task 7. ✓
- Out-of-scope (s1p53 relabel, blob byte-decode) → not tasked here (correct; separate). ✓

**Placeholder scan:** Task 5 is data-population (no code), explicitly flagged as hand-classification with the exact field shape + the per-family `value_kind` guidance — not a vague placeholder. Task 6/8 have inspect-then-edit steps with the exact grep + the exact field rules. No "TBD"/"handle edge cases" remain.

**Type consistency:** `build_census` → census dict shape (`values`/`shape_sigs`/`is_blob`/`value_kind_hint`) is consumed identically by `check_coverage` and `seed_blocks`; the inventory index shape `{(siid,piid): {value_kind, observed_values:[{value,status}], observed_shapes:[{sig,status}]}}` matches across Task 2 (checker), Task 5 (data), Task 7 (gate loader). ✓

**Note for the implementer:** Task 5 (data) and Task 7 (gate) are coupled — the gate stays red until every census value is parked. Expect to iterate Task 5 ↔ Task 7 once. The `--unknowns` report (Task 7) is the tool for that loop. The circumstance-window enrichment in `--unknowns` is intentionally lightweight in v1 (it points at the logs + OLD/); deepening it (auto-pulling the s2p1/s2p2 window) is a fast-follow if the parked-unknown backlog warrants it.
