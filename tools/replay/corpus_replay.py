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

from tools._toolmeta import add_to_parser

TOOL_META = {
    "domain": "replay",
    "run_by": "owner",
    "when": "Before/after any refactor-v2 migration phase, to prove decode/state "
    "semantics are byte-identical across months of real wire traffic.",
    "summary": "Replay probe-log MQTT corpus through the decode/state pipelines; "
    "emit or diff a deterministic golden digest.",
}

# Probe timestamps are local wall-clock on the dev box; pin the zone so
# digests are machine-independent and DST-deterministic (fold=0).
_TZ = ZoneInfo("Europe/Oslo")

_CANON = {"sort_keys": True, "separators": (",", ":"), "default": str}


def _canon(obj: Any) -> str:
    return json.dumps(obj, **_CANON)


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert sets/frozensets to sorted lists for stable JSON.

    Without this, StateSnapshot's ``errors`` frozenset falls through to
    ``default=str`` and gets repr-stringified — iteration-order-dependent,
    so not machine-independent.
    """
    if isinstance(obj, (set, frozenset)):
        return sorted((_to_jsonable(v) for v in obj), key=_canon)
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return obj


def _ensure_ha_stubs() -> None:
    """Import the test suite's HA stubs when running outside pytest.

    The vanilla venv has no real ``homeassistant``; under pytest,
    tests/conftest.py injects a stub, which bare ``python -m`` runs never
    see. Same precedent as tools/state_machine/
    state_machine_audit_fake_coord.py:_ensure_ha_stubs.
    """
    if "homeassistant" in sys.modules:
        return
    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tests"))
    import conftest  # noqa: F401 — side effect: stubs homeassistant


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
    _ensure_ha_stubs()
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
        "final_mower_state": json.loads(
            _canon(_to_jsonable(dataclasses.asdict(state)))
        ),
        "final_snapshot": json.loads(
            _canon(_to_jsonable(dataclasses.asdict(sm.snapshot())))
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
    ap = argparse.ArgumentParser(description=TOOL_META["summary"])
    ap.add_argument("--corpus-dir", type=Path, required=True)
    ap.add_argument("--glob", default="probe_log_*.jsonl")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--diff", type=Path)
    add_to_parser(ap, TOOL_META)
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
