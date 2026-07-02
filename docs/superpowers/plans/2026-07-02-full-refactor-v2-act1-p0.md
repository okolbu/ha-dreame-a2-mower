# Full Refactor v2 — Act I (Review) + P0 (Corpus-Replay Harness) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute Act I of the approved full-refactor-v2 spec — seed the anti-resurrection blocklist, build the P0 corpus-replay golden harness, run the seven review tracks, synthesize the findings register — and gate into Act II (target architecture).

**Architecture:** Main session orchestrates; each review track is a read-only research subagent writing an evidence-cited findings doc out-of-tree at `/data/claude/homeassistant/refactor-2026-07-02/`. The only in-repo code in this plan is the replay harness (`tools/replay/` + a committed sanitized corpus excerpt + CI golden test). Acts II–III are user-gated placeholders at the end.

**Tech Stack:** Python 3.13 (`/data/claude/homeassistant/.venv-vanilla/bin/python`), pytest, JSONL corpus replay, subagent dispatch.

**Spec:** `docs/superpowers/specs/2026-07-02-full-refactor-v2-design.md` (approved 2026-07-02).

## Global Constraints

- Test venv: `/data/claude/homeassistant/.venv-vanilla/bin/python` (system python3 is broken). Run pytest from the repo root `/data/claude/homeassistant/ha-dreame-a2-mower`.
- Secrets (`/data/claude/homeassistant/secrets/*.txt`): use **in-situ only** — never copy values into any file, findings doc, prompt, or commit.
- Git: stage by **explicit path only** (a concurrent process commits with `add -A`). Push after each committed task (traceability; no release/version-bump gating during this plan).
- Out-of-tree review dir: `/data/claude/homeassistant/refactor-2026-07-02/` — findings, goldens, register drafts. **Never committed.**
- **Verification rule (spec):** no claim that code is dead/wrong without discharged evidence (grep hit, corpus query, MITM excerpt, or live probe). Wire claims need multi-run corpus validation, never a single sample.
- **Blocklist rule (spec):** every subagent brief embeds the debunked-claims register (Task 1). Nothing from git history enters a finding as *truth* unless corroborated by current `inventory.yaml`/`entity-inventory.yaml` or fresh corpus/MITM evidence.
- Evidence corpus paths: probe MQTT logs `/data/claude/homeassistant/probe/logs/*.jsonl` (~17 files, 388 MB); MITM captures under `/data/claude/homeassistant/analysis/` and `/data/claude/homeassistant/OLD/FINDING-*.md`; cloud dumps `/data/claude/homeassistant/cloud/dumps/`; app plugin extract `artifacts/g2408-plugin-extract/`.
- Canonical backend truth: `custom_components/dreame_a2_mower/inventory.yaml` (wire) + `entity-inventory.yaml` (entities) + `docs/research/` (gated docs). Docs/memories may be stale; inventory wins.
- No feature work, no backend changes. Feature ideas discovered in review go into the findings doc, tagged `idea`, not into code.
- Live HA (for read-only checks): use the home-assistant MCP tools; host credentials in `secrets/ha-credentials.txt` (in-situ).
- CI gates that this plan can trip: tools/README sync (`python tools/gen_readme.py` after any `TOOL_META` change), full-test-suite job, inventory-touch gate (not expected to trip — no inventory edits in this plan).

---

## Task 0: Scaffold the out-of-tree review directory

**Files:**
- Create: `/data/claude/homeassistant/refactor-2026-07-02/README.md`
- Create: `/data/claude/homeassistant/refactor-2026-07-02/findings/` (dir)
- Create: `/data/claude/homeassistant/refactor-2026-07-02/goldens/` (dir)

**Interfaces:**
- Produces: the working directory every later task writes into.

- [ ] **Step 1: Create the directory tree**

```bash
mkdir -p /data/claude/homeassistant/refactor-2026-07-02/findings \
         /data/claude/homeassistant/refactor-2026-07-02/goldens
```

- [ ] **Step 2: Write README.md**

Write `/data/claude/homeassistant/refactor-2026-07-02/README.md`:

```markdown
# Full Refactor v2 — Act I working directory (out-of-tree, never committed)

Spec: ha-dreame-a2-mower/docs/superpowers/specs/2026-07-02-full-refactor-v2-design.md
Plan: ha-dreame-a2-mower/docs/superpowers/plans/2026-07-02-full-refactor-v2-act1-p0.md

- `debunked-register-v0.md` — seed blocklist (Task 1); v1 produced by track 1.
- `findings/track-<n>-<name>.md` — review-track outputs (Tasks 4–10).
- `findings/findings-register.md` — synthesized, severity-ranked (Task 11).
- `goldens/` — full-corpus replay digests (Task 3). Re-run per migration phase:
  see "Full-corpus replay" in ha-dreame-a2-mower/tools/replay/corpus_replay.py docstring.
- `target-architecture.md` — Act II deliverable (Task 12).

Baseline: main @ v1.0.31a5. Status header updated as tasks complete.
```

- [ ] **Step 3: Verify**

Run: `ls /data/claude/homeassistant/refactor-2026-07-02/`
Expected: `README.md  findings  goldens`

---

## Task 1: Seed the debunked-claims blocklist (v0)

**Files:**
- Create: `/data/claude/homeassistant/refactor-2026-07-02/debunked-register-v0.md`

**Interfaces:**
- Produces: the v0 blocklist embedded verbatim in every review-track brief (Tasks 4–10). Track 1 (Task 4) supersedes it with `debunked-register-v1.md`.

The v0 register is seeded from the spec's known-reversals list, cross-checked against current inventory/docs. Each entry: the dead claim, what's true instead (as a **citation**, not a restated value — per the no-restate rule), and the evidence pointer.

- [ ] **Step 1: Cross-check each seed entry against current docs**

For each claim below, confirm the "cite" target exists before writing the file:

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
grep -n "knowledge-gaps" docs/research/knowledge-gaps.md | head -1
grep -rn "id: " custom_components/dreame_a2_mower/inventory.yaml | wc -l   # inventory present
ls docs/research/g2408-app-capture-playbook-2026-06-09.md
```

Expected: all three resolve (adjust cite paths in the register if any moved).

- [ ] **Step 2: Write debunked-register-v0.md**

Write `/data/claude/homeassistant/refactor-2026-07-02/debunked-register-v0.md` with exactly this structure (entries may be *extended* with evidence pointers found in Step 1, never trimmed):

```markdown
# Debunked-claims register v0 (seed — Track 1 produces v1)

RULES FOR ALL AGENTS: (1) Never write any claim below into code, docs, or findings
as if true. (2) If git history or an old doc asserts one of these, that is evidence
of DEAD CODE or STALE DOC, not of fact. (3) Cite current inventory.yaml ids instead
of restating wire values. (4) Missing knowledge stays a gap ("unknown — see
docs/research/knowledge-gaps.md"), never back-filled from pre-reversal material.

| # | DEBUNKED claim | Status of the truth | Evidence pointer |
|---|---|---|---|
| D1 | Settings the integration can't write are Bluetooth-mediated ("BT-vs-Cloud" framing) | g2408 has NO BT transport for settings; failures were cloud-cache-only | user ruling (memory feedback_no_bt_transport); inventory settings-transport sections |
| D2 | s2p2=28 is an "off-dock marker" | s2p2=28 = blade-wear; validated across the full probe corpus (~66 undocks) | inventory.yaml § s2p2; memory feedback_corpus_validate_protocol_claims |
| D3 | PRE properties are absent/unwritable on g2408 | PRE IS writable; the old negative was a wrong envelope | inventory.yaml § PRE; corrected app-MITM 2026-06 findings |
| D4 | FAULT_CODES table is the fault source of truth | DELETED; the RN-plugin fault catalog is wire-authoritative (fault_tier/event_slug derivation) | artifacts/g2408-plugin-extract/; fault-catalog specs 2026-06-19 |
| D5 | MISTA r=-1/-3 means the endpoint is unsupported | MISTA mirrors s1p4 area counters (centiares); r=-1/-3 = idle, pollable mid-run only | inventory.yaml § MISTA |
| D6 | MIHIS.start is the per-unit first-mowing date | 1704038400 is a firmware-hardcoded sentinel (2023-12-31 UTC) | inventory.yaml § MIHIS |
| D7 | Album/AI photos live in Xiaomi FDS (479D) | They are in the dreame-eu Aliyun OSS bucket (app-MITM resolved 2026-06-09) | docs/research/g2408-app-capture-playbook-2026-06-09.md |
| D8 | Patrol cycles/auto-capture writes "don't stick" | Write WORKS (o=111+CRUISED, byte-exact); apparent failure was CRUISE.0 read-back lag | inventory.yaml § CRUISED; v1.0.29a3 notes |
| D9 | op=12 (lock) and op=10 (3dmap) do something | Both accepted-but-no-effect on g2408 (r=0, no behavior) | inventory.yaml § routed ops; live probes 2026-06 |
| D10 | s1p1 heartbeat carries numeric fault codes | s1p1 is a boolean-flag blob; the 45 "heartbeat codes" never fire on g2408 (93,888-sample corpus) | fault-catalog P4 finding; inventory.yaml § s1p1 |
| D11 | The live app map needs only what siid:6 offers | App live dense-LiDAR uses a surface our siid:6 path can't reach; needs app-RPC capture (open gap) | memory project_g2408_op10_3dmap_negative; knowledge-gaps.md |
| D12 | upstream dreame-vacuum *CLEAN* property mappings apply to mowers | Vacuum-only; mower mappings differ | memory feedback_check_cloud_dump_first; cloud/dumps/ inventory |
| D13 | OTA `sign` is reproducible client-side | Token-auth no-sign path is what works; MD5 formula never reproduced golden | memory project_firmware_ota_findings_plan + project_getdevicefile_signer |
| D14 | Track over-segmentation markers are meaningful geometry | TRACK_BREAK_MARKER mid-mow creates junk single-point segments; trigger unknown (open) | inventory.yaml § summary_map_track |

Known-reversal ERAS for archaeology (Track 1 walks these; not themselves claims):
pre-CloudState `_cached_*` caching era; single-map era (pre v1.0.3a9);
pre-catalog fault surfacing era; pre-CRUISED patrol era; LOCN endpoint era;
`_poll_slow_properties` era; BT-framing era; entity-validation-matrix era.
```

- [ ] **Step 3: Verify the register parses as a complete table**

Run: `grep -c '^| D' /data/claude/homeassistant/refactor-2026-07-02/debunked-register-v0.md`
Expected: `14`

---

## Task 2: P0 corpus-replay harness — replay core (TDD)

**Files:**
- Create: `tools/replay/__init__.py`
- Create: `tools/replay/corpus_replay.py`
- Test: `tests/tools/test_corpus_replay.py`

**Interfaces:**
- Consumes: `custom_components.dreame_a2_mower.coordinator.apply_property_to_state(state, siid, piid, value) -> MowerState` (pure); `custom_components.dreame_a2_mower.mower.state.MowerState` (dataclass, `MowerState()` default-constructible); `custom_components.dreame_a2_mower.mower.state_machine.MowerStateMachine` (`.handle_mqtt_property(siid, piid, value, now_unix)`, `.handle_heartbeat(hb, now_unix)`, `.snapshot()`); `custom_components.dreame_a2_mower.protocol.heartbeat.decode_s1p1(data: bytes)`.
- Produces: `iter_pushes(path: Path) -> Iterator[tuple[int, int, int, Any]]` (ts_unix, siid, piid, value); `replay(paths: list[Path]) -> dict` (the digest); `digest_diff(a: dict, b: dict) -> list[str]` (human-readable mismatches, empty = identical); CLI `python -m tools.replay.corpus_replay`. Tasks 3, 3b and every migration phase consume these.

Digest schema (stable, `"schema": 1`): `push_count`, `per_slot` (`"s{siid}p{piid}" -> {"count": int, "last_value_sha1": str}`), `rolling_sha256` (hash chained over every *state-changing* apply: canonical JSON of `[siid, piid, changed_field_names]`), `final_mower_state` (dict), `final_snapshot` (dict), `sm_transitions` (count of snapshot-changing SM calls). Canonical JSON everywhere: `json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tools/test_corpus_replay.py`:

```python
"""Tests for the corpus-replay golden harness (refactor-v2 P0)."""
from __future__ import annotations

import json
from pathlib import Path

from tools.replay.corpus_replay import digest_diff, iter_pushes, replay

_LINES = [
    # non-mqtt lines must be skipped
    {"type": "session_start", "timestamp": "2026-04-17 09:31:27", "device": {"did": "-1"}},
    {"type": "api_probe", "timestamp": "2026-04-17 09:31:35"},
    # battery scalar (s3p1) — mapped in PROPERTY_MAPPING and in the SM
    {
        "type": "mqtt_message",
        "timestamp": "2026-04-17 09:31:55",
        "params": [{"did": "-1", "siid": 3, "piid": 1, "value": 62}],
    },
    # two params in one message
    {
        "type": "mqtt_message",
        "timestamp": "2026-04-17 09:32:00",
        "params": [
            {"did": "-1", "siid": 3, "piid": 1, "value": 63},
            {"did": "-1", "siid": 3, "piid": 2, "value": 1},
        ],
    },
]


def _write_jsonl(path: Path, rows) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def test_iter_pushes_yields_only_property_params(tmp_path):
    log = _write_jsonl(tmp_path / "probe.jsonl", _LINES)
    pushes = list(iter_pushes(log))
    assert [(s, p, v) for _, s, p, v in pushes] == [(3, 1, 62), (3, 1, 63), (3, 2, 1)]
    # timestamps are unix ints and non-decreasing
    ts = [t for t, *_ in pushes]
    assert all(isinstance(t, int) for t in ts) and ts == sorted(ts)


def test_replay_digest_shape_and_determinism(tmp_path):
    log = _write_jsonl(tmp_path / "probe.jsonl", _LINES)
    d1 = replay([log])
    d2 = replay([log])
    assert d1 == d2  # byte-determinism
    assert d1["schema"] == 1
    assert d1["push_count"] == 3
    assert d1["per_slot"]["s3p1"]["count"] == 2
    assert d1["final_mower_state"]["battery_level"] == 63
    assert d1["final_snapshot"]["battery_percent"] == 63
    assert isinstance(d1["rolling_sha256"], str) and len(d1["rolling_sha256"]) == 64


def test_replay_survives_malformed_and_unknown_lines(tmp_path):
    rows = list(_LINES) + [
        {"type": "mqtt_message", "timestamp": "2026-04-17 09:33:00",
         "params": [{"did": "-1", "siid": 99, "piid": 99, "value": {"x": 1}}]},
    ]
    log = _write_jsonl(tmp_path / "probe.jsonl", rows)
    log.write_text(log.read_text() + "not json at all\n")
    d = replay([log])  # must not raise
    assert d["push_count"] == 4
    assert d["per_slot"]["s99p99"]["count"] == 1


def test_digest_diff_reports_and_clears(tmp_path):
    log = _write_jsonl(tmp_path / "probe.jsonl", _LINES)
    a = replay([log])
    assert digest_diff(a, replay([log])) == []
    b = json.loads(json.dumps(a))
    b["final_mower_state"]["battery_level"] = 1
    b["rolling_sha256"] = "0" * 64
    problems = digest_diff(a, b)
    assert any("battery_level" in p for p in problems)
    assert any("rolling_sha256" in p for p in problems)
```

Note on `final_snapshot["battery_percent"]`: confirm the actual `StateSnapshot` field name with `grep -n "battery" custom_components/dreame_a2_mower/mower/state_snapshot.py` before running; if it differs (e.g. `battery_level`), fix the **test** to the real field name — the harness never renames fields.

- [ ] **Step 2: Run tests to verify they fail**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_corpus_replay.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.replay'`

- [ ] **Step 3: Implement the harness**

Create `tools/replay/__init__.py` (empty) and `tools/replay/corpus_replay.py`:

```python
"""Corpus-replay golden harness (refactor-v2 P0 centerpiece).

Replays probe-log JSONL (external MQTT probe format: ``mqtt_message``
lines with ``params: [{siid, piid, value}]``) through BOTH pure state
pipelines — ``apply_property_to_state`` (MowerState) and
``MowerStateMachine`` (StateSnapshot) — and emits a deterministic JSON
digest. Identical digests across a refactor == byte-identical decode
semantics over months of real wire traffic.

Full-corpus replay (dev box, per migration phase):

    .venv-vanilla/bin/python -m tools.replay.corpus_replay \
        --corpus-dir /data/claude/homeassistant/probe/logs \
        --out /data/claude/homeassistant/refactor-2026-07-02/goldens/<name>.json

    # afterwards, compare:
    .venv-vanilla/bin/python -m tools.replay.corpus_replay \
        --corpus-dir /data/claude/homeassistant/probe/logs \
        --diff /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json

Exit code 0 = identical, 1 = mismatch (mismatches printed), 2 = usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TOOL_META = {
    "name": "corpus_replay",
    "description": "Replay probe-log MQTT corpus through the decode/state pipelines; emit or diff a deterministic golden digest",
    "usage": "python -m tools.replay.corpus_replay --corpus-dir DIR [--out FILE | --diff GOLDEN]",
}

# Probe timestamps are local wall-clock on the dev box; pin the zone so
# digests are machine-independent and DST-deterministic (fold=0).
_TZ = ZoneInfo("Europe/Oslo")

_CANON = {"sort_keys": True, "separators": (",", ":"), "default": str}


def _canon(obj: Any) -> str:
    return json.dumps(obj, **_CANON)


def _ts_to_unix(ts: str) -> int:
    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_TZ)
    return int(dt.timestamp())


def iter_pushes(path: Path) -> Iterator[tuple[int, int, int, Any]]:
    """Yield (ts_unix, siid, piid, value) for every property push in one log."""
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") != "mqtt_message":
                continue
            try:
                ts = _ts_to_unix(row["timestamp"])
            except (KeyError, ValueError):
                continue
            for p in row.get("params") or []:
                if isinstance(p, dict) and "siid" in p and "piid" in p:
                    yield ts, int(p["siid"]), int(p["piid"]), p.get("value")


def replay(paths: list[Path]) -> dict:
    """Replay logs (sorted by name = chronological) into a digest dict."""
    # Imports deferred so `--help` works without the integration on path.
    from custom_components.dreame_a2_mower.coordinator import (
        apply_property_to_state,
    )
    from custom_components.dreame_a2_mower.mower.state import MowerState
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.protocol import heartbeat as _hb
    import dataclasses

    state = MowerState()
    sm = MowerStateMachine()
    rolling = hashlib.sha256()
    per_slot: dict[str, dict[str, Any]] = {}
    push_count = 0
    sm_transitions = 0

    for path in sorted(paths, key=lambda p: p.name):
        for ts, siid, piid, value in iter_pushes(path):
            push_count += 1
            key = f"s{siid}p{piid}"
            slot = per_slot.setdefault(key, {"count": 0, "last_value_sha1": ""})
            slot["count"] += 1
            slot["last_value_sha1"] = hashlib.sha1(
                _canon(value).encode()
            ).hexdigest()

            # Pipeline 1: pure MowerState apply.
            new_state = apply_property_to_state(state, siid, piid, value)
            if new_state != state:
                changed = sorted(
                    f.name
                    for f in dataclasses.fields(new_state)
                    if getattr(new_state, f.name) != getattr(state, f.name)
                )
                rolling.update(_canon([siid, piid, changed]).encode())
                state = new_state

            # Pipeline 2: state machine (same slots the coordinator routes).
            before = sm.snapshot()
            try:
                if (siid, piid) == (1, 1):
                    if isinstance(value, (list, bytes, bytearray)):
                        sm.handle_heartbeat(_hb.decode_s1p1(bytes(value)), ts)
                else:
                    sm.handle_mqtt_property(siid, piid, value, ts)
            except Exception as ex:  # decode crash IS a finding, not an abort
                rolling.update(_canon([siid, piid, "SM_ERROR", str(ex)]).encode())
            if sm.snapshot() != before:
                sm_transitions += 1

    return {
        "schema": 1,
        "push_count": push_count,
        "per_slot": dict(sorted(per_slot.items())),
        "rolling_sha256": rolling.hexdigest(),
        "sm_transitions": sm_transitions,
        "final_mower_state": json.loads(_canon(dataclasses.asdict(state))),
        "final_snapshot": json.loads(
            _canon(dataclasses.asdict(sm.snapshot()))
        ),
    }


def digest_diff(a: dict, b: dict) -> list[str]:
    """Human-readable differences between two digests ([] == identical)."""
    problems: list[str] = []

    def walk(pa: str, va: Any, vb: Any) -> None:
        if isinstance(va, dict) and isinstance(vb, dict):
            for k in sorted(set(va) | set(vb)):
                walk(f"{pa}.{k}", va.get(k), vb.get(k))
        elif va != vb:
            problems.append(f"{pa}: {va!r} != {vb!r}")

    walk("digest", a, b)
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=TOOL_META["description"])
    ap.add_argument("--corpus-dir", type=Path, required=True)
    ap.add_argument("--glob", default="probe_log_*.jsonl")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--diff", type=Path)
    args = ap.parse_args(argv)

    paths = sorted(args.corpus_dir.glob(args.glob))
    if not paths:
        print(f"no logs match {args.glob} in {args.corpus_dir}", file=sys.stderr)
        return 2
    digest = replay(paths)
    print(f"replayed {digest['push_count']} pushes from {len(paths)} logs")

    if args.out:
        args.out.write_text(json.dumps(digest, indent=1, sort_keys=True))
        print(f"wrote {args.out}")
    if args.diff:
        golden = json.loads(args.diff.read_text())
        problems = digest_diff(golden, digest)
        for p in problems:
            print(f"MISMATCH {p}")
        print("IDENTICAL" if not problems else f"{len(problems)} mismatches")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_corpus_replay.py -v`
Expected: 4 PASS. If `final_snapshot` field-name assert fails, fix the test's field name to the real one (see Step 1 note) — do not touch integration code.

- [ ] **Step 5: Regenerate tools README (CI sync gate) and run the tools test bucket**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/gen_readme.py
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/ -q
```
Expected: README regenerated with the new `replay` section; tools tests green.

- [ ] **Step 6: Commit**

```bash
git add tools/replay/__init__.py tools/replay/corpus_replay.py \
        tests/tools/test_corpus_replay.py tools/README.md
git commit -m "tools(replay): corpus-replay golden harness (refactor-v2 P0)"
git push origin main
```

---

## Task 3: Committed corpus excerpt + CI golden test

**Files:**
- Modify: `tools/replay/corpus_replay.py` (add `--extract` mode)
- Create: `tests/fixtures/corpus/replay_excerpt.jsonl` (generated, sanitized, ≤ 500 KB)
- Create: `tests/fixtures/corpus/replay_excerpt.golden.json` (generated)
- Test: `tests/integration/test_corpus_replay_golden.py`

**Interfaces:**
- Consumes: `iter_pushes`, `replay`, `digest_diff` from Task 2.
- Produces: the CI-side golden gate; `--extract`/`--bless` CLI modes reused whenever the excerpt is re-blessed after an *intentional* semantic change.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_corpus_replay_golden.py`:

```python
"""CI golden gate: the committed corpus excerpt must replay to the
blessed digest. A mismatch means decode/state semantics changed — either
a regression (fix it) or an intentional change (re-bless:
`python -m tools.replay.corpus_replay --corpus-dir tests/fixtures/corpus
 --glob 'replay_excerpt.jsonl' --out tests/fixtures/corpus/replay_excerpt.golden.json`
and justify in the commit message)."""
from __future__ import annotations

import json
from pathlib import Path

from tools.replay.corpus_replay import digest_diff, replay

_FIX = Path(__file__).parent.parent / "fixtures" / "corpus"
_EXCERPT = _FIX / "replay_excerpt.jsonl"
_GOLDEN = _FIX / "replay_excerpt.golden.json"


def test_excerpt_replays_to_golden():
    digest = replay([_EXCERPT])
    golden = json.loads(_GOLDEN.read_text())
    assert digest_diff(golden, digest) == []


def test_excerpt_is_sanitized_and_meaningful():
    text = _EXCERPT.read_text()
    golden = json.loads(_GOLDEN.read_text())
    # sanitizer replaced the real device id everywhere
    assert "SANITIZED" in text
    # excerpt exercises a real mow: heartbeats + task-state + telemetry
    for slot in ("s1p1", "s2p1", "s1p4"):
        assert golden["per_slot"].get(slot, {"count": 0})["count"] > 0, slot
    assert golden["sm_transitions"] > 10
```

- [ ] **Step 2: Run to verify failure**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_corpus_replay_golden.py -v`
Expected: FAIL — fixture files missing.

- [ ] **Step 3: Add `--extract` mode to the harness**

In `tools/replay/corpus_replay.py`, add after `digest_diff`:

```python
def extract_excerpt(
    src: Path, dst: Path, start: str, end: str, max_bytes: int = 500_000
) -> int:
    """Copy sanitized mqtt_message lines with start <= timestamp < end.

    Sanitization: the device id (read from the log's own lines) and any
    MAC-shaped string are replaced. Returns lines written; raises if the
    result exceeds max_bytes or the real did survives.
    """
    import re

    did: str | None = None
    out: list[str] = []
    with src.open() as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if did is None:
                d = row.get("device") or {}
                if d.get("did"):
                    did = str(d["did"])
                params = row.get("params") or []
                if params and isinstance(params[0], dict) and params[0].get("did"):
                    did = str(params[0]["did"])
            if row.get("type") != "mqtt_message":
                continue
            ts = row.get("timestamp", "")
            if not (start <= ts < end):
                continue
            keep = {
                "type": "mqtt_message",
                "timestamp": ts,
                "params": row.get("params") or [],
            }
            text = json.dumps(keep)
            if did:
                text = text.replace(did, "SANITIZED_DID")
            text = re.sub(
                r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", "SANITIZED_MAC", text
            )
            out.append(text)
    blob = "\n".join(out) + "\n"
    if did and did in blob:
        raise RuntimeError("sanitization failed: device id survived")
    if len(blob.encode()) > max_bytes:
        raise RuntimeError(f"excerpt too large: {len(blob.encode())} bytes")
    dst.write_text(blob)
    return len(out)
```

And extend `main()` argparse + dispatch (before the `paths =` line):

```python
    ap.add_argument("--extract-src", type=Path)
    ap.add_argument("--extract-start")
    ap.add_argument("--extract-end")
    ap.add_argument("--extract-dst", type=Path)
```

```python
    if args.extract_src:
        if not (args.extract_start and args.extract_end and args.extract_dst):
            ap.error("--extract-* flags must be given together")
        n = extract_excerpt(
            args.extract_src, args.extract_dst,
            args.extract_start, args.extract_end,
        )
        print(f"extracted {n} sanitized lines -> {args.extract_dst}")
        return 0
```

- [ ] **Step 4: Find a window containing a complete mow session**

Scan for a session (s2p1 task-state entering and leaving an active value) in a mid-corpus log:

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
/data/claude/homeassistant/.venv-vanilla/bin/python - <<'EOF'
import json
from pathlib import Path
for log in sorted(Path("/data/claude/homeassistant/probe/logs").glob("probe_log_*.jsonl")):
    first = last = None; n = 0
    for line in open(log):
        if '"siid": 2, "piid": 1' not in line and '"siid":2,"piid":1' not in line:
            continue
        row = json.loads(line)
        for p in row.get("params") or []:
            if p.get("siid") == 2 and p.get("piid") == 1:
                n += 1
                if first is None: first = (row["timestamp"], p["value"])
                last = (row["timestamp"], p["value"])
    print(log.name, "s2p1 pushes:", n, "first:", first, "last:", last)
EOF
```

Pick a log with many s2p1 pushes; choose `--extract-start/--extract-end` bracketing one full session (~1–2 h wall-clock) and run:

```bash
mkdir -p tests/fixtures/corpus
/data/claude/homeassistant/.venv-vanilla/bin/python -m tools.replay.corpus_replay \
  --corpus-dir /data/claude/homeassistant/probe/logs \
  --extract-src /data/claude/homeassistant/probe/logs/<chosen>.jsonl \
  --extract-start "<YYYY-MM-DD HH:MM:SS>" --extract-end "<YYYY-MM-DD HH:MM:SS>" \
  --extract-dst tests/fixtures/corpus/replay_excerpt.jsonl
```

Expected: `extracted N sanitized lines` with N in the hundreds–thousands and file ≤ 500 KB (narrow the window if the size guard trips).

- [ ] **Step 5: Bless the golden and verify the tests pass**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m tools.replay.corpus_replay \
  --corpus-dir tests/fixtures/corpus --glob 'replay_excerpt.jsonl' \
  --out tests/fixtures/corpus/replay_excerpt.golden.json
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_corpus_replay_golden.py -v
```
Expected: both tests PASS (if `test_excerpt_is_sanitized_and_meaningful` fails on slot counts, the window missed the session — re-pick in Step 4).

- [ ] **Step 6: Full suite + commit**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q
git add tools/replay/corpus_replay.py tests/integration/test_corpus_replay_golden.py \
        tests/fixtures/corpus/replay_excerpt.jsonl tests/fixtures/corpus/replay_excerpt.golden.json \
        tools/README.md
git commit -m "test(replay): committed sanitized corpus excerpt + CI golden gate"
git push origin main
```
Expected: full suite green (record the exact `N passed / M skipped` count in the commit message — this is the P0 baseline the spec calls for).

---

## Task 3b: Full-corpus baseline golden

**Files:**
- Create: `/data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json` (out-of-tree)

**Interfaces:**
- Consumes: Task 2 CLI.
- Produces: the baseline digest every Act III phase diffs against.

- [ ] **Step 1: Generate the baseline (twice — determinism proof)**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
time /data/claude/homeassistant/.venv-vanilla/bin/python -m tools.replay.corpus_replay \
  --corpus-dir /data/claude/homeassistant/probe/logs \
  --out /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json
/data/claude/homeassistant/.venv-vanilla/bin/python -m tools.replay.corpus_replay \
  --corpus-dir /data/claude/homeassistant/probe/logs \
  --diff /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json
```
Expected: second run prints `IDENTICAL`, exit 0. Record the runtime in the goldens README line (Task 0 file) so phase-gating knows the cost. If it exceeds ~15 min, note that per-phase diffs can use `--glob` to run the largest 5 logs only, with the full run reserved for phase checkpoints.

- [ ] **Step 2: Record SM_ERROR count**

Run: `grep -c "SM_ERROR" /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json || true`
Any SM_ERROR hashes embedded in `rolling_sha256` are invisible here — instead check push totals: `python -c "import json;d=json.load(open('/data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json'));print(d['push_count'], d['sm_transitions'])"`.
Expected: pushes in the tens of thousands; sm_transitions > 100. Note both numbers in the goldens README line.

---

## Tasks 4–10: the seven review tracks

Common machinery for every track task below:

- **Dispatch:** one `general-purpose` subagent per track (tracks are independent — dispatch in parallel batches of 2–3 to keep evidence-tool contention low). Each brief = the *Common preamble* + the track's *Mission block*. Subagents get read access everywhere but may **write only** to `/data/claude/homeassistant/refactor-2026-07-02/findings/`.
- **Common preamble (verbatim in every brief):**

```text
You are a review agent for the ha-dreame-a2-mower full-refactor-v2 (Act I).
Repo: /data/claude/homeassistant/ha-dreame-a2-mower (main @ v1.0.31a5).
Read the spec first: docs/superpowers/specs/2026-07-02-full-refactor-v2-design.md.
Read the blocklist and OBEY its 4 rules:
/data/claude/homeassistant/refactor-2026-07-02/debunked-register-v0.md

EVIDENCE SOURCES, in trust order:
1. custom_components/dreame_a2_mower/inventory.yaml + entity-inventory.yaml
   + docs/research/ (canonical backend truth; cite ids, never restate values)
2. code + git history (git log --follow, git log -S<symbol>)
3. probe corpus /data/claude/homeassistant/probe/logs/*.jsonl (388MB JSONL;
   grep/python one-liners; multi-run validation required for wire claims)
   + MITM findings in /data/claude/homeassistant/OLD/FINDING-*.md
4. live HA via the home-assistant MCP tools (read-only)
NEVER copy values out of /data/claude/homeassistant/secrets/* into anything.

VERIFICATION RULE: every finding must carry discharged evidence — file:line,
grep output, corpus line, inventory id, or live-HA readout. "Looks dead/wrong"
without evidence => tag it hypothesis, list what check would discharge it.

OUTPUT: write exactly one markdown file (path given in your mission).
Findings numbered <TRACK>-<n>, each with fields:
  severity: HIGH (correctness/public-blocker) | MED (structural/debt) |
            LOW (polish) | idea (out-of-scope feature thought)
  claim: one sentence
  evidence: the discharged proof (or 'HYPOTHESIS + discharge check')
  affected: files/entities/docs
  proposed_action: delete/fix/restructure/gate/document — one sentence
End with a summary table (id | severity | claim). Your final message: the
output path + counts by severity. Do not modify any repo file.
```

- **Verify step (every track):** main session reads the findings doc; for the 3 highest-severity findings, independently re-run the cited evidence (grep/corpus/live check); reject-and-redispatch the specific finding if evidence doesn't reproduce. Then mark the task complete.

### Task 4: Track 1 — Assumption archaeology + debunked register v1

**Files:**
- Create (by agent): `/data/claude/homeassistant/refactor-2026-07-02/findings/track-1-archaeology.md`
- Create (by agent): `/data/claude/homeassistant/refactor-2026-07-02/debunked-register-v1.md`

**Interfaces:**
- Consumes: v0 register (Task 1).
- Produces: v1 register — **from this task on, later dispatches embed v1 instead of v0**; dead-code deletion list for Act III P1.

- [ ] **Step 1: Dispatch with this Mission block appended to the common preamble**

```text
MISSION — TRACK 1: ASSUMPTION ARCHAEOLOGY.
Backend understanding reversed 180° repeatedly. For EACH register entry D1–D14
and EACH listed era (bottom of the register): (a) git log -S the key symbols to
find code written under the dead belief; (b) determine whether that code path
still exists on main; (c) if it exists, is it reachable? Evidence: file:line +
a reachability argument (imports, callers via grep, entity wiring).
Also sweep generally: grep for comments/docstrings/docs asserting anything the
register debunks; TODO/FIXME referencing dead eras; config options, constants,
suppressed-slot entries, and services whose rationale died.
DELIVERABLE 2: debunked-register-v1.md — same format as v0, extended with any
additional overturned claims you can EVIDENCE from history + inventory (cite
both the debunking evidence and where the dead claim last lived). v1 must be a
superset of v0. Output findings to findings/track-1-archaeology.md.
```

- [ ] **Step 2: Verify (common verify step)** — additionally: confirm v1 is a superset of v0 (`grep -c '^| D' debunked-register-v1.md` ≥ 14) and every NEW claim cites evidence.

### Task 5: Track 2 — Architecture & layering

**Files:**
- Create (by agent): `/data/claude/homeassistant/refactor-2026-07-02/findings/track-2-architecture.md`

- [ ] **Step 1: Dispatch with this Mission block**

```text
MISSION — TRACK 2: ARCHITECTURE & LAYERING.
Target-architecture principles are in the spec §"Act II" — judge current code
against them. Produce:
(a) MODULE MAP: for custom_components/dreame_a2_mower/, every package/module
    >200 LOC with LOC, one-line responsibility, and its imports of OTHER
    integration modules (this yields the coupling graph; call out back-edges,
    i.e. lower layers importing upward, and god-modules).
(b) SHIM CENSUS: every re-export shim file (root sensor_*/select_*/switch_*/
    _camera_*/wifi_*/map_decoder.py etc), its importer count (grep), and
    whether anything but tests/tools still uses it.
(c) HOTSPOT AUTOPSIES: for each file >800 LOC (entities/sensor/device.py 1739,
    cloud_client/_fetchers.py, coordinator/_mqtt_handlers.py, coordinator/
    _session.py, services.py, entities/select/global_.py, coordinator/_core.py,
    protocol/map_decoder.py, coordinator/_writes.py, coordinator/_lidar_oss.py,
    mower/state_machine.py, ...): what distinct responsibilities cohabit, and a
    proposed split with target module names.
(d) FRESH JUDGMENT on the three previously-deferred items (prior rulings in
    repo docs/TODO.md and /data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/
    superpowers/refactor-2026-06-13/): (1) MowerState per-domain split,
    (2) coordinator attr-bundling (~67 attrs, incl. the string-getattr
    consumers trap documented in TODO.md), (3) decoder/render transform
    untangle + zone-type unification. The prior "over-engineering" rulings are
    NOT binding — re-derive from today's code + the break-freely rule, and give
    a recommendation each WITH the prior ruling's key counter-evidence addressed.
Findings to findings/track-2-architecture.md.
```

- [ ] **Step 2: Verify (common verify step)** — additionally spot-check the coupling graph on 2 modules by re-running the import grep.

### Task 6: Track 3 — Correctness & lifecycle

**Files:**
- Create (by agent): `/data/claude/homeassistant/refactor-2026-07-02/findings/track-3-correctness.md`

- [ ] **Step 1: Dispatch with this Mission block**

```text
MISSION — TRACK 3: CORRECTNESS & LIFECYCLE.
Hunt bugs and fragility, prioritizing classes with prior recurrences:
(a) THREADING: the paho-thread boundary (coordinator/_mqtt_handlers.py) — the
    2026-06 refactor moved SM mutations onto the loop; verify NOTHING added in
    the 281 commits since violates that (grep new call sites on the paho path).
(b) LIFECYCLE: async_unload_entry / reload — every thread, task, timer,
    session, and file handle created anywhere: is each cancelled/joined/closed
    on unload? (cloud_client worker, MQTT client, OSS fetchers, photo/lidar
    downloads, archive writers, render debouncers.)
(c) WRITE HONESTY: WriteResult end-to-end — which writes still return
    fire-and-forget? (settings set_cfg/set_pre switch/number paths and
    edit_map were known deferred follow-ups; verify current state.)
(d) RACE FAMILIES: camera access_token rotation (broadcast→render→broadcast
    pattern — audit ALL entity-write handlers for the single-broadcast bug);
    session finalize latch coverage (any finalize writer outside
    _finalize_with_latch?); optimistic-overlay vs read-back lag patterns.
(e) ASYNC HYGIENE: blocking I/O on the event loop (requests/file/PIL calls not
    behind executors), unawaited tasks, broad except swallowing.
(f) ERROR SURFACING: cloud/API failure paths that leave stale entity state
    without flipping availability.
For each finding include a concrete failure scenario (inputs/state → wrong
outcome). Findings to findings/track-3-correctness.md.
```

- [ ] **Step 2: Verify (common verify step).**

### Task 7: Track 4 — Public-release readiness

**Files:**
- Create (by agent): `/data/claude/homeassistant/refactor-2026-07-02/findings/track-4-public-release.md`

- [ ] **Step 1: Dispatch with this Mission block**

```text
MISSION — TRACK 4: PUBLIC-RELEASE READINESS.
Judge "could a stranger with a g2408 install and run this from HACS today?":
(a) CONFIG FLOW: config_flow.py — credential UX, error handling on bad creds /
    unreachable cloud, re-auth flow, region/server selection (3 known backends),
    multi-device accounts, options flow completeness.
(b) SINGLE-USER RESIDUE: grep the integration + www/ + dashboards/ for
    hardcoded personal values: dids, MACs, IPs (10.0.0.*), hostnames, GPS
    coordinates, Norwegian strings, absolute /data/claude or /config paths,
    the developer's map ids/names. Check committed test fixtures too —
    tests/fixtures/ may embed real device identifiers (decide: acceptable or
    sanitize).
(c) ASSUMPTION HARDENING: what breaks with 0 maps? 3+ maps? no sessions yet?
    no photos? device model ≠ g2408 on the same integration type? HA restart
    mid-mow (restore paths)? Non-EU server?
(d) HACS/STORE: manifest.json correctness (integration_type, iot_class,
    requirements pins), strings/translations coverage, diagnostics redaction
    (secrets/tokens/coords in diagnostics dumps?), README install docs vs
    reality, LICENSE, issue template.
(e) SECRETS HYGIENE: any token/password/signature material logged at
    INFO/DEBUG or persisted to disk unredacted.
Findings to findings/track-4-public-release.md.
```

- [ ] **Step 2: Verify (common verify step).**

### Task 8: Track 5 — Entity surface

**Files:**
- Create (by agent): `/data/claude/homeassistant/refactor-2026-07-02/findings/track-5-entity-surface.md`

- [ ] **Step 1: Dispatch with this Mission block**

```text
MISSION — TRACK 5: ENTITY SURFACE (break-freely applies — propose the IDEAL).
Input: entity-inventory.yaml (~86 classes; 'presumed' rows are code-read, not
live-verified) + CONTROL_MODES + live HA registry via MCP (the ground truth of
what exists + what's disabled/unavailable).
For EVERY entity class output one verdict row:
  keep-as-is | rename (give the ideal v2 object_id + name) | demote-diagnostic |
  gate-experimental (cite which carveout tier from the spec §"Experimental
  gate") | delete (evidence it's dead/noop/redundant)
Judge against: HA entity naming guidelines (has_entity_name semantics — recall
entity_id derives from the NAME slug, not the key), device_class/unit/
state_class correctness, the per-map DEFAULT_NAME-prefix rule (CLAUDE.md
§ per-map naming), attribute-vs-entity choices (fat attributes that should be
entities or vice versa), duplicate/near-duplicate sensors, diagnostic
category correctness, entity_registry_enabled_default sanity.
Also: the services surface (services.yaml) — same verdict treatment; and the
event/device-trigger surface (catalog-derived slugs stay — cite, don't rejudge
the fault catalog).
Deliverable: the verdict table IS the draft v2 canonical entity table.
Findings + table to findings/track-5-entity-surface.md.
```

- [ ] **Step 2: Verify (common verify step)** — additionally: verdict rows must cover every class in `entity-inventory.yaml` (compare counts) and every service in `services.yaml`.

### Task 9: Track 6 — Dashboard & cards

**Files:**
- Create (by agent): `/data/claude/homeassistant/refactor-2026-07-02/findings/track-6-dashboard.md`

- [ ] **Step 1: Dispatch with this Mission block**

```text
MISSION — TRACK 6: DASHBOARD & CARDS AS A SHIPPABLE PRODUCT.
Inputs: dashboards/mower/dashboard.yaml (2020 lines, repo==live convention),
custom_components/dreame_a2_mower/www/*.js (9 files ~4.8k LOC), live HA via
MCP (read-only), HA dashboard-strategy docs (WebFetch
https://developers.home-assistant.io/docs/frontend/custom-ui/custom-strategy/
if reachable).
(a) STRATEGY FEASIBILITY (spec decision: registered dashboard strategy,
    fallback generated-YAML+install-service): inventory every card type used;
    which are custom (need JS resource registration — verify how www/ resources
    are registered today and whether that works on a fresh install); which
    views/cards can be generated from the entity registry + CONTROL_MODES vs
    genuinely hand-authored; what per-map views need. Conclude: strategy
    viable? What must the generator know? Any hard blockers -> fallback?
(b) CARD QUALITY: for each www/ card — LOC, duplicated logic across cards
    (projection/render/theme code vs _dreame-map-core.js), dead code, hardcoded
    entity_ids (break on rename in P4), error handling (setConfig validation),
    CARD_VERSION banner presence, cache-busting story.
(c) CONTENT AUDIT of the current dashboard: stale claims, dead entity refs
    (cross-check every entity_id against the live registry via MCP), views a
    public user needs that don't exist, developer-only views to gate.
(d) The dashboard↔backend attribute contracts (which card reads which attr —
    build the table; this becomes the new-contract test input for P0/P4).
Findings to findings/track-6-dashboard.md.
```

- [ ] **Step 2: Verify (common verify step)** — additionally re-check 3 claimed dead entity refs against the live registry.

### Task 10: Track 7 — Test-suite quality

**Files:**
- Create (by agent): `/data/claude/homeassistant/refactor-2026-07-02/findings/track-7-tests.md`

- [ ] **Step 1: Dispatch with this Mission block**

```text
MISSION — TRACK 7: TEST-SUITE QUALITY (348 test files; venv
/data/claude/homeassistant/.venv-vanilla/bin/python, run from repo root).
(a) MOCK-MASKING: find tests whose mocks would hide a real break — the known
    lesson class is SimpleNamespace stand-ins for coordinator/state objects
    that silently absorb renamed/removed attributes; also MagicMock-everything
    fixtures and patch-targets pointing at shim paths (those break when shims
    die in P3 — census them).
(b) SHALLOWNESS: tests asserting only "no exception" or only call-counts on
    heavily-mocked units; golden tests pinning known-buggy behavior (check the
    map-render golden docstrings); tests duplicating each other.
(c) DEAD WEIGHT: fixtures no test loads; skipped tests (why: the 4 baseline
    skips); tests for deleted features that pass vacuously; conftest stubs
    masking import errors.
(d) COVERAGE GAPS vs RISK: which of these high-risk areas lack real tests —
    finalize interleavings, reload/unload lifecycle, config_flow error paths,
    multi-map edge cases (0/3 maps), write-rejection surfacing, card-contract
    attrs, archive-format round-trip?
(e) STRUCTURE: runtime of the full suite; slowest 10 tests; any test touching
    the network or the real corpus paths (must skip gracefully — verify
    tests/integration/test_probe_regression.py behavior on a clean checkout).
Do NOT fix anything. Findings to findings/track-7-tests.md.
```

- [ ] **Step 2: Verify (common verify step).**

---

## Task 11: Synthesis gate — findings register

**Files:**
- Create: `/data/claude/homeassistant/refactor-2026-07-02/findings/findings-register.md`

**Interfaces:**
- Consumes: all seven track findings docs + v1 register.
- Produces: the single severity-ranked register that Act II and every Act III phase plan cite by finding id.

- [ ] **Step 1: Merge and dedupe (main session, not a subagent)**

Read all seven `findings/track-*.md`. Build `findings-register.md`: every finding, re-keyed `R-<n>`, cross-referencing duplicates (same defect found by 2 tracks = one entry, both source ids). Preserve each finding's evidence pointer verbatim.

- [ ] **Step 2: Resolve conflicts by the verification rule**

Where two tracks disagree (e.g. track 2 proposes deleting what track 3 calls load-bearing), re-derive from evidence; if undischargeable now, record as `OPEN-QUESTION` with the concrete check that would settle it (live probe, corpus query, next-firmware event).

- [ ] **Step 3: Rank and bucket**

Order: HIGH → MED → LOW → idea. Within HIGH, public-blockers first. Tag each finding with its destination phase (P1 dead-code / P2 correctness / P3 structure / P4 entity-surface / P5 dashboard / P6 release) — this tagging is the skeleton of the Act III plans.

- [ ] **Step 4: Spot-verify + user checkpoint**

Re-verify 5 randomly-chosen findings' evidence yourself. Then present to the user: counts by severity/phase, the full HIGH list, the three deferred-item verdicts, the strategy-feasibility conclusion, and any OPEN-QUESTIONs needing user input. **STOP for user review before Task 12.**

---

## Task 12 (GATED — user approved Task 11): Act II target architecture

**Files:**
- Create: `/data/claude/homeassistant/refactor-2026-07-02/target-architecture.md` (draft)
- Create (after approval): `docs/superpowers/specs/2026-07-02-refactor-v2-target-architecture.md` (committed)

- [ ] **Step 1: Author the target architecture** — main session, from the findings register, within the spec's Act II principles (layering, one-fact-one-name, ≤400 LOC, shims die, experimental gate architectural, write path honest). Must contain: the target package tree with per-module responsibilities; the state-container design (resolving the deferred-items verdicts); the domain-service boundaries; the entity-descriptor scheme incl. `experimental` flag; the dashboard-strategy component design; the v2 entity table (from track 5, as amended by synthesis); the new contract-test list; a findings-register coverage appendix (every HIGH/MED finding → where the target resolves it, or why deferred).
- [ ] **Step 2: Self-review** — placeholder scan, internal consistency, every register HIGH accounted for.
- [ ] **Step 3: User review gate** — present section-by-section. **STOP for approval.**
- [ ] **Step 4: Commit the approved doc** to `docs/superpowers/specs/` (explicit-path staging, push).

## Task 13 (GATED — user approved Task 12): Act III phase plans

Act III (P1–P6) is deliberately NOT planned here — each phase gets its own implementation plan via the writing-plans skill once the target architecture is approved, seeded from the phase-tagged findings register. Fixed per-phase machinery (from the spec): own branch; full suite; corpus-replay `--diff` against `goldens/baseline-v1.0.31a5.json` (re-blessed only with an intentional-change justification); `tools/release/release.sh`; live-HA deploy + MCP verification; go/no-go with the user. P0 exit criteria are already met by Tasks 2–3b of THIS plan.

- [ ] **Step 1: Write the P1 (dead-code purge) plan** via writing-plans, from register findings tagged P1 + debunked-register-v1 (which lands in gated docs as part of P1 itself).

---

## Self-review record

- **Spec coverage:** Act I tracks 1–7 → Tasks 4–10; verification rule + evidence sources → Global Constraints + common preamble; debunked register → Tasks 1/4 (+ in-repo landing assigned to P1 in Task 13); P0 harness + rewritten-contracts prep → Tasks 2/3/3b + track 6(d); synthesis → Task 11; Act II → Task 12; Act III gating + per-phase machinery → Task 13. Experimental-gate design, dashboard strategy build, entity renames are Act II/III work by design, not gaps.
- **Placeholder scan:** the `<chosen>`/`<YYYY-MM-DD...>` tokens in Task 3 Step 4 are runtime-selected inputs with the selection procedure given — not plan gaps.
- **Type consistency:** `iter_pushes`/`replay`/`digest_diff`/`extract_excerpt` signatures match across Tasks 2/3/3b; digest keys used in tests (`per_slot`, `sm_transitions`, `final_mower_state`, `final_snapshot`, `rolling_sha256`) match the implementation.
