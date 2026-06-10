# Schedule Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mower schedule edits reach the device by replacing `write_schedule`'s ignored `SCHEDULE.*` KV write with the authoritative `SCHD*V3` routed-action chunked transaction.

**Architecture:** New protocol-only module `protocol/schedule_action.py` provides `chunk_row_json`, `read_schedule_rows` (RMW base via `SCHDTV3`→`SCHDIV3`/`SCHDDV3` `m:'r'`) and `write_schedule_row` (`SCHDIV3` header + N `SCHDDV3` ≤50-byte chunks sharing one txn id + `SCHDSV3` state), all over the existing `send_action(siid=2, aiid=50, [{"m","t","d"}])` plumbing. `coordinator.write_schedule` becomes an RMW that re-encodes each changed slot with the already-correct `encode_schedule_blob` and writes it via the new transport. The existing `set_schedule_plans` service + dashboard card are unchanged.

**Tech Stack:** Python 3.13, Home Assistant custom integration, pytest (vanilla stubbed-HA venv at `/data/claude/homeassistant/.venv-vanilla`).

---

## File Structure

- Create: `custom_components/dreame_a2_mower/protocol/schedule_action.py` — the SCHD*V3 transport (protocol-only, no HA imports).
- Create: `tests/unit/test_schedule_action.py` — chunker, write envelope, read reassembly.
- Create: `tests/unit/test_schedule_blob_samples.py` — byte-identical regression vs the 3 captured samples.
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py` — rewrite `write_schedule`; add `_next_schedule_txn_id`.
- Modify: `custom_components/dreame_a2_mower/protocol/schedule_encode.py` — remove `build_schedule_set_value` (KV builder, now unused) and drop it from the `protocol/schedule.py` re-export shim.
- Modify: `custom_components/dreame_a2_mower/protocol/schedule.py` — update `__all__`.
- Modify: `tests/...` — adjust any test importing `build_schedule_set_value`.
- Modify: `custom_components/dreame_a2_mower/time.py` — correct the stale class docstring.
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`, `inventory.yaml` — retraction + verification records.
- Modify: `CLAUDE.md`, `docs/research/app-integration-roadmap.md`, `docs/research/knowledge-gaps.md` — fact-discipline rule + roadmap + open items.
- Modify: `custom_components/dreame_a2_mower/manifest.json` — version bump.

Run all tests with:
```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -q
```

---

### Task 1: `chunk_row_json` helper

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/schedule_action.py`
- Test: `tests/unit/test_schedule_action.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_schedule_action.py
from custom_components.dreame_a2_mower.protocol import schedule_action as sa


def test_chunk_row_json_offsets_and_reassembly():
    s = "x" * 123  # 123 bytes -> 50 + 50 + 23
    chunks = sa.chunk_row_json(s)
    assert [off for off, _ in chunks] == [0, 50, 100]
    assert [len(c.encode("utf-8")) for _, c in chunks] == [50, 50, 23]
    assert "".join(c for _, c in chunks) == s


def test_chunk_row_json_short_string_single_chunk():
    s = "[0,1,\"n\",\"AA==\"]"
    chunks = sa.chunk_row_json(s)
    assert len(chunks) == 1
    assert chunks[0] == (0, s)


def test_chunk_row_json_empty():
    assert sa.chunk_row_json("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_schedule_action.py -q`
Expected: FAIL (module / function not defined).

- [ ] **Step 3: Write minimal implementation**

```python
# custom_components/dreame_a2_mower/protocol/schedule_action.py
"""Routed-action transport for the device-plane schedule (SCHD*V3).

The authoritative schedule write is NOT the SCHEDULE.* iotuserdata KV (that is
only the app's cache mirror, which the device ignores). It is a chunked
transaction over siid:2/aiid:50: a SCHDIV3 header, N SCHDDV3 data chunks
(<=50 bytes, sharing one txn id), then a SCHDSV3 state write.

Wire facts: dreame-app-schedule-write-2026-06-10.md (app<->mower MITM).
Protocol-only — no HA imports.
"""
from __future__ import annotations

import json
from typing import Any

from .cfg_action import (  # noqa: F401  (re-exported error type for callers)
    ROUTED_ACTION_AIID,
    ROUTED_ACTION_SIID,
    CfgActionError,
    _unwrap,
)

CHUNK_SIZE = 50


def chunk_row_json(row_json: str) -> list[tuple[int, str]]:
    """Split row_json into (offset, chunk) pairs of <=CHUNK_SIZE bytes.

    Offsets are byte offsets into the UTF-8 encoding, contiguous, covering the
    whole string exactly once. Our row JSON is ASCII (base64 + digits + simple
    names), so byte offset == char offset; we slice on bytes to stay exact.
    """
    raw = row_json.encode("utf-8")
    out: list[tuple[int, str]] = []
    for off in range(0, len(raw), CHUNK_SIZE):
        out.append((off, raw[off:off + CHUNK_SIZE].decode("utf-8")))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_schedule_action.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/schedule_action.py tests/unit/test_schedule_action.py
git commit -m "feat(schedule): chunk_row_json helper for SCHDDV3 transport"
```

---

### Task 2: `write_schedule_row` (header + chunks + state envelope)

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/schedule_action.py`
- Test: `tests/unit/test_schedule_action.py`

- [ ] **Step 1: Write the failing test**

```python
def _fake_send_action(calls, *, fail_on=None):
    """Return a send_action that records every call and returns a success
    envelope ({"result":{"out":[{"m":"s","r":0}]}}), or an r!=0 error envelope
    when the call's `t` matches fail_on."""
    def send(siid, aiid, params):
        payload = params[0]
        calls.append((siid, aiid, payload))
        r = 7 if (fail_on and payload.get("t") == fail_on) else 0
        return {"result": {"out": [{"m": "r", "r": r}]}}
    return send


def test_write_schedule_row_envelope():
    calls = []
    row = "[0,1,\"Spr\",\"qghRIBIAAu0=\"]"  # arbitrary but realistic
    sa.write_schedule_row(
        _fake_send_action(calls),
        slot=0, enabled=1, name="Spr", blob_b64="qghRIBIAAu0=",
        version=5, flag=0, txn_id=1781118711306,
    )
    # All on siid:2 aiid:50.
    assert all(c[0] == 2 and c[1] == 50 for c in calls)
    kinds = [c[2]["t"] for c in calls]
    assert kinds[0] == "SCHDIV3"
    assert kinds[-1] == "SCHDSV3"
    assert set(kinds[1:-1]) == {"SCHDDV3"}
    header = calls[0][2]["d"]
    expected_row = '[0,1,"Spr","qghRIBIAAu0="]'
    assert header == {"i": 0, "l": len(expected_row.encode()), "v": 1781118711306}
    # chunks share txn id, contiguous offsets, reassemble to the row JSON.
    chunks = [c[2]["d"] for c in calls[1:-1]]
    assert all(ch["v"] == 1781118711306 for ch in chunks)
    assert [ch["s"] for ch in chunks] == list(range(0, len(expected_row), 50))
    assert "".join(ch["d"] for ch in chunks) == expected_row
    assert all(ch["l"] == len(ch["d"].encode()) for ch in chunks)
    state = calls[-1][2]["d"]
    assert state == {"i": 0, "v": 5, "s": [1, 0]}


def test_write_schedule_row_raises_on_error():
    import pytest
    with pytest.raises(sa.CfgActionError):
        sa.write_schedule_row(
            _fake_send_action([], fail_on="SCHDSV3"),
            slot=0, enabled=1, name="Spr", blob_b64="qghRIBIAAu0=",
            version=5, flag=0, txn_id=1,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_schedule_action.py -k write_schedule_row -q`
Expected: FAIL (function not defined).

- [ ] **Step 3: Write minimal implementation**

Append to `schedule_action.py`:

```python
def _send(send_action, t: str, d: Any) -> None:
    """Fire one routed-action leg and raise if the device rejects it."""
    raw = send_action(ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "s", "t": t, "d": d}])
    _unwrap(raw)  # raises CfgActionError on r!=0 / malformed envelope


def write_schedule_row(
    send_action,
    *,
    slot: int,
    enabled: int,
    name: str,
    blob_b64: str,
    version: int,
    flag: int,
    txn_id: int,
) -> None:
    """Write one schedule slot row via the chunked SCHD*V3 transaction.

    Order: SCHDIV3 header -> N SCHDDV3 chunks (shared txn_id) -> SCHDSV3 state.
    `version` is the schedule version (SCHDSV3 `v`); `txn_id` is the shared
    header/chunk `v`. Raises CfgActionError if any leg returns r!=0.
    """
    row_json = json.dumps([slot, enabled, name, blob_b64], separators=(",", ":"))
    total_len = len(row_json.encode("utf-8"))
    _send(send_action, "SCHDIV3", {"i": slot, "l": total_len, "v": txn_id})
    for off, chunk in chunk_row_json(row_json):
        _send(send_action, "SCHDDV3",
              {"s": off, "l": len(chunk.encode("utf-8")), "d": chunk, "v": txn_id})
    _send(send_action, "SCHDSV3", {"i": slot, "v": version, "s": [enabled, flag]})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_schedule_action.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/schedule_action.py tests/unit/test_schedule_action.py
git commit -m "feat(schedule): write_schedule_row SCHDIV3/SCHDDV3/SCHDSV3 transport"
```

---

### Task 3: `read_schedule_rows` (RMW base)

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/schedule_action.py`
- Test: `tests/unit/test_schedule_action.py`

**Context:** READ uses `SCHDTV3` (revision probe) then `SCHDIV3`/`SCHDDV3` with `m:"r"`; responses carry the same `[slot,enabled,name,b64]` rows. We model the read minimally: probe `SCHDTV3` to learn how many slots exist, then for each slot send `SCHDIV3 {m:"r", d:{i:slot}}` whose unwrapped payload `d` carries the reassembled row (the relay reassembles chunks on read; we accept the row directly from `d`). If the probe payload already contains the full rows, return them. Keep it tolerant: return `[]` on any malformed response.

- [ ] **Step 1: Write the failing test**

```python
def test_read_schedule_rows_from_probe_rows():
    # SCHDTV3 probe returns the full table in d.rows -> return as-is.
    def send(siid, aiid, params):
        t = params[0]["t"]
        if t == "SCHDTV3":
            return {"result": {"out": [{"m": "r", "r": 0, "d": {
                "rows": [[0, 1, "Spr", "qghRIBIAAu0="], [1, 0, "Aut", ""]],
            }}}]}
        raise AssertionError(f"unexpected t={t}")
    rows = sa.read_schedule_rows(send)
    assert rows == [[0, 1, "Spr", "qghRIBIAAu0="], [1, 0, "Aut", ""]]


def test_read_schedule_rows_malformed_returns_empty():
    def send(siid, aiid, params):
        return {"result": {"out": [{"m": "r", "r": 0, "d": {}}]}}
    assert sa.read_schedule_rows(send) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_schedule_action.py -k read_schedule_rows -q`
Expected: FAIL (function not defined).

- [ ] **Step 3: Write minimal implementation**

Append to `schedule_action.py`:

```python
def read_schedule_rows(send_action) -> list[list]:
    """Read the authoritative schedule rows for RMW.

    Probes SCHDTV3; the unwrapped payload's `d.rows` carries the
    [slot, enabled, name, b64blob] rows (the relay reassembles chunks on read).
    Returns [] on any malformed/empty response.
    """
    try:
        raw = send_action(ROUTED_ACTION_SIID, ROUTED_ACTION_AIID,
                          [{"m": "r", "t": "SCHDTV3"}])
        payload = _unwrap(raw)
    except CfgActionError:
        return []
    d = payload.get("d") if isinstance(payload, dict) else None
    rows = d.get("rows") if isinstance(d, dict) else None
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, list) and len(r) == 4]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_schedule_action.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/schedule_action.py tests/unit/test_schedule_action.py
git commit -m "feat(schedule): read_schedule_rows for RMW base"
```

> **Implementer note:** if a fresh capture later shows the read needs the
> per-slot `SCHDIV3 m:'r'` fan-out instead of `d.rows`, adjust here only — the
> coordinator treats `read_schedule_rows` as a black box returning rows.

---

### Task 4: byte-identical blob regression (encoder unchanged)

**Files:**
- Create: `tests/unit/test_schedule_blob_samples.py`

**Context:** `encode_schedule_blob` already emits the doc's 3-mode layout. This test pins it to the three wire-verified samples so a future refactor can't silently break it. `SchedulePlan(time_min, weekday_mask, action_type, zone_id, extra_bytes)`; weekday on the wire is Sun=0..Sat=6, but the mask bit is 0=Mon..6=Sun, so the encoder maps bit→tm_wday via `(bit+1)%7`. To target a single wire weekday W (Sun=0..Sat=6), set the mask bit `b` such that `(b+1)%7 == W` ⇒ `b = (W+6)%7`.

Samples (from `dreame-app-schedule-write-2026-06-10.md` §3):
- `aa07300c0300ed` — Wed(3) 13:00 all-area (mode 0, no zone)
- `aa085120120002ed` — Fri(5) 09:04 zone-2 full (mode 1)
- `aa0902e021000200ed` — Sun(0) 08:00 zone-2 edge (mode 2, seg 0)

- [ ] **Step 1: Write the test**

```python
import base64
from custom_components.dreame_a2_mower.cloud_state import SchedulePlan
from custom_components.dreame_a2_mower.protocol.schedule_encode import encode_schedule_blob


def _wire_weekday_to_maskbit(w):  # w: Sun=0..Sat=6 -> mask bit 0=Mon..6=Sun
    return (w + 6) % 7


def _blob_hex(plan):
    return base64.b64decode(encode_schedule_blob((plan,))).hex()


def test_all_area_sample():
    plan = SchedulePlan(time_min=780, weekday_mask=1 << _wire_weekday_to_maskbit(3),
                        action_type=0, zone_id=None, extra_bytes=b"")
    assert _blob_hex(plan) == "aa07300c0300ed"


def test_zone_full_sample():
    plan = SchedulePlan(time_min=544, weekday_mask=1 << _wire_weekday_to_maskbit(5),
                        action_type=1, zone_id=2, extra_bytes=b"")
    assert _blob_hex(plan) == "aa085120120002ed"


def test_zone_edge_sample():
    plan = SchedulePlan(time_min=480, weekday_mask=1 << _wire_weekday_to_maskbit(0),
                        action_type=2, zone_id=2, extra_bytes=bytes([0x00]))
    assert _blob_hex(plan) == "aa0902e021000200ed"
```

- [ ] **Step 2: Run test**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_schedule_blob_samples.py -q`
Expected: PASS (encoder already correct). If any FAIL, STOP and report — it means the encoder diverges from the wire-verified doc; do NOT "fix" the test to match the encoder. Investigate the encoder against the doc §3 byte table.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_schedule_blob_samples.py
git commit -m "test(schedule): pin encode_schedule_blob to 3 wire-verified samples"
```

---

### Task 5: rewire `coordinator.write_schedule` to the device plane

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py:84-115`
- Test: `tests/integration/test_write_schedule_device_plane.py` (create)

**Context:** Current `write_schedule` builds a KV value via `build_schedule_set_value` and calls `self._cloud.write_chunked_key("SCHEDULE", …)` — the device-ignored path. Replace with: read authoritative rows, re-encode each incoming slot, write only changed slots via `write_schedule_row`, preserve `enabled`/`flag`, bump version, refresh. `self._cloud.action` is the `send_action` callable (same one `get_cfg(self.action)` uses). Generate the txn id in the coordinator (`import time` is already used elsewhere in the coordinator package).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_write_schedule_device_plane.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin  # adjust to real mixin name
from custom_components.dreame_a2_mower.cloud_state import (
    CloudState, ScheduleData, ScheduleSlot, SchedulePlan,
)


def _make_coord(rows, slots):
    c = _WritesMixin()
    captured = {"row_writes": [], "kv_writes": []}

    def _write_row(send_action, **kw):
        captured["row_writes"].append(kw)

    def _read_rows(send_action):
        return rows

    c._cloud = SimpleNamespace(
        action=lambda *a, **k: None,
        write_chunked_key=MagicMock(side_effect=lambda key, val: captured["kv_writes"].append(key) or (True, "")),
    )
    c._chunked_write_lock = __import__("asyncio").Lock()
    c.cloud_state = CloudState.empty().__class__  # placeholder; see note
    c._refresh_cloud_state = AsyncMock()

    async def _exec(fn, *a, **k):
        return fn(*a, **k)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    return c, captured, _write_row, _read_rows


@pytest.mark.asyncio
async def test_write_schedule_uses_device_plane_not_kv(monkeypatch):
    import custom_components.dreame_a2_mower.coordinator._writes as W
    rows = [[0, 1, "Spr", "OLD"], [1, 0, "Aut", ""]]
    new_plan = SchedulePlan(time_min=780, weekday_mask=0b100, action_type=0, zone_id=None, extra_bytes=b"")
    new_slots = [ScheduleSlot(slot_id=0, name="Spr", raw_blob_b64="", plans=(new_plan,), mode=1)]
    c, captured, write_row, read_rows = _make_coord(rows, new_slots)
    monkeypatch.setattr(W, "write_schedule_row", write_row, raising=False)
    monkeypatch.setattr(W, "read_schedule_rows", read_rows, raising=False)
    # cloud_state.schedule.version
    c.cloud_state = SimpleNamespace(schedule=ScheduleData(version=5, slots=()))

    ok = await c.write_schedule(new_slots)

    assert ok is True
    assert captured["kv_writes"] == []           # KV path retired
    assert len(captured["row_writes"]) == 1       # only the changed slot 0
    w = captured["row_writes"][0]
    assert w["slot"] == 0 and w["enabled"] == 1 and w["version"] == 6
    assert isinstance(w["txn_id"], int) and w["txn_id"] > 0
    c._refresh_cloud_state.assert_awaited()
```

> **Implementer note:** the exact mixin class name and `cloud_state` construction must match the real code — read `coordinator/_writes.py` and `cloud_state.py` and adapt the harness. The behavioural asserts (no KV write; one row write for the changed slot; version+1; refresh) are the contract; keep them.

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_write_schedule_device_plane.py -q`
Expected: FAIL (still calls KV / no row writes).

- [ ] **Step 3: Implement**

Add a txn-id helper and rewrite `write_schedule` in `coordinator/_writes.py`. Add near the top of the mixin:

```python
    def _next_schedule_txn_id(self) -> int:
        """Monotonic ms-epoch txn id (shared across a write's header+chunks)."""
        import time as _time
        txn = int(_time.time() * 1000)
        last = getattr(self, "_last_schedule_txn_id", 0)
        if txn <= last:
            txn = last + 1
        self._last_schedule_txn_id = txn
        return txn
```

Replace the body of `write_schedule`:

```python
    async def write_schedule(
        self,
        new_slots: tuple[Any, ...] | list[Any],
    ) -> bool:
        """Push changed schedule slots to the device via the SCHD*V3 transport.

        new_slots is a sequence of ScheduleSlot dataclasses (.plans is the
        source of truth; .raw_blob_b64 is ignored — re-encoded). Reads the
        authoritative rows, writes only slots whose re-encoded blob or name
        changed, preserving each slot's enabled/flag, bumping the schedule
        version. The SCHEDULE.* KV is intentionally NOT written (the device
        ignores it; see dreame-app-schedule-write-2026-06-10.md).
        """
        from ..protocol.schedule_action import read_schedule_rows, write_schedule_row
        from ..protocol.schedule_encode import encode_schedule_blob

        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_schedule: cloud client not ready")
            return False

        cs = self.cloud_state
        base_version = cs.schedule.version if cs is not None else 0
        new_version = base_version + 1

        rows = await self.hass.async_add_executor_job(
            read_schedule_rows, self._cloud.action
        )
        by_slot = {r[0]: r for r in rows if isinstance(r, list) and len(r) == 4}

        ok = True
        async with self._chunked_write_lock:
            for slot in new_slots:
                blob_b64 = encode_schedule_blob(tuple(slot.plans))
                prev = by_slot.get(slot.slot_id)
                prev_blob = prev[3] if prev else None
                prev_name = prev[2] if prev else None
                if prev is not None and blob_b64 == prev_blob and slot.name == prev_name:
                    continue  # unchanged — skip (idempotent, no version churn)
                enabled = int(prev[1]) if prev else 1
                flag = 0  # SCHDSV3 second state element; 0 in every capture
                txn_id = self._next_schedule_txn_id()
                try:
                    await self.hass.async_add_executor_job(
                        lambda s=slot, b=blob_b64, e=enabled, t=txn_id: write_schedule_row(
                            self._cloud.action,
                            slot=s.slot_id, enabled=e, name=s.name, blob_b64=b,
                            version=new_version, flag=flag, txn_id=t,
                        )
                    )
                    LOGGER.info(
                        "[schedule-write] slot %d, %d plan(s), v→%d, blob_len=%d",
                        slot.slot_id, len(slot.plans), new_version, len(blob_b64),
                    )
                except Exception as exc:  # noqa: BLE001 — surface, keep going
                    ok = False
                    LOGGER.warning("[schedule-write] slot %d rejected: %r", slot.slot_id, exc)

        await self._refresh_cloud_state()
        return ok
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_write_schedule_device_plane.py -q`
Expected: PASS.

- [ ] **Step 5: Retire the KV builder**

Remove `build_schedule_set_value` from `protocol/schedule_encode.py` and from the `protocol/schedule.py` re-export `__all__` + import. Grep first:

```bash
grep -rn "build_schedule_set_value" custom_components tests
```

Update/delete every reference (no production caller remains after Task 5; fix any test that imported it).

- [ ] **Step 6: Run the schedule + coordinator test subset**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_schedule_action.py tests/unit/test_schedule_blob_samples.py tests/integration/test_write_schedule_device_plane.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_writes.py custom_components/dreame_a2_mower/protocol/schedule_encode.py custom_components/dreame_a2_mower/protocol/schedule.py tests/
git commit -m "feat(schedule): write_schedule via SCHD*V3 device plane; retire KV path"
```

---

### Task 6: `set_schedule_plans` service regression

**Files:**
- Test: `tests/integration/test_set_schedule_plans_service.py` (create or extend existing service test)

**Context:** The service handler `_handle_set_schedule_plans` rebuilds `new_slots` from `cloud_state.schedule.slots` (replacing one slot) and calls `coordinator.write_schedule`. Confirm it still reaches `write_schedule` with the rebuilt slot list after the transport swap.

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_set_schedule_plans_service.py
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from custom_components.dreame_a2_mower import services
from custom_components.dreame_a2_mower.cloud_state import ScheduleData, ScheduleSlot, SchedulePlan


@pytest.mark.asyncio
async def test_set_schedule_plans_calls_write_schedule(monkeypatch):
    existing = ScheduleSlot(slot_id=0, name="Spr", raw_blob_b64="", plans=(), mode=1)
    coord = SimpleNamespace(
        cloud_state=SimpleNamespace(schedule=ScheduleData(version=1, slots=(existing,))),
        write_schedule=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(hass=SimpleNamespace(), data={
        "slot_id": 0,
        "plans": [{"time_min": 780, "weekday_mask": 4, "action_type": 0}],
    })
    await services._handle_set_schedule_plans(call)
    coord.write_schedule.assert_awaited_once()
    (slots_arg,), _ = coord.write_schedule.await_args
    assert any(s.slot_id == 0 and len(s.plans) == 1 for s in slots_arg)
```

- [ ] **Step 2: Run test**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_set_schedule_plans_service.py -q`
Expected: PASS (handler unchanged). If FAIL on import/signature, adapt the harness to the real handler signature (read `services.py:240`).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_set_schedule_plans_service.py
git commit -m "test(schedule): set_schedule_plans service reaches write_schedule"
```

---

### Task 7: Fact discipline — retraction, verification, docs

**Files:**
- Modify: `custom_components/dreame_a2_mower/time.py` (class docstring)
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml:3545` (retraction)
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (verification record)
- Modify: `CLAUDE.md` (fact-discipline rule)
- Modify: `docs/research/app-integration-roadmap.md` (row E done)
- Modify: `docs/research/knowledge-gaps.md` (open items)

- [ ] **Step 1: Correct the stale `time.py` class docstring**

Replace the `DreameA2Time` docstring lines:
```
    Displays schedule slot start/end times. async_set_value is a no-op
    with a warning — schedule editing is BT-only on g2408 in F4.
```
with:
```
    Backs DND / charging / low-speed-at-night CFG time fields (NOT the mow
    schedule). Writable entities write via coordinator.write_setting; the
    rest reject writes via the control-honesty mixin.
```
(The old text was doubly wrong: these are CFG times, not the mow schedule, and "schedule editing is BT-only" is debunked — see inventory.yaml:2115 and the mow-schedule SCHD*V3 write path.)

- [ ] **Step 2: Retract the BT-only claim in `entity-inventory.yaml:3545`**

Edit the `sensor`/`time` entry's verification block to add a `retracts` record (verbatim) and corrected claim:
```yaml
        retracts: "schedule editing is BT-only per protocol-doc §1.1 on g2408"
        reason: "Mow-schedule editing is writable via the SCHD*V3 routed-action transport (siid:2/aiid:50); BT-only was already debunked for settings (inventory.yaml:2115). The time.* entities are DND/charging/low-speed CFG times, not the mow schedule. [app-mitm:2026-06-10-schedule-write]"
```
Adjust the `claim:` wording to drop "schedule editing is BT-only".

- [ ] **Step 3: Add the schedule-write verification record in `inventory.yaml`**

Find the schedule wire entry (grep `SCHEDULE`/`scheduled_clean`) and add a verification noting the device-plane write:
```yaml
      - status: confirmed
        date: 2026-06-10
        claim: "Mow schedule writes via SCHD*V3 chunked routed-action transaction (SCHDIV3 header + SCHDDV3 <=50B chunks sharing one txn id + SCHDSV3 state) on siid:2/aiid:50. Row = [slot,enabled,name,b64blob]; blob = concatenated 7/8/9-byte run records (mode 0/1/2). SCHEDULE.* KV is a cache mirror the device ignores. [app-mitm:2026-06-10-schedule-write]"
        source: "dreame-app-schedule-write-2026-06-10.md (app<->mower MITM, records 3237+)"
```

- [ ] **Step 4: Add the wire-verification-equivalence rule to `CLAUDE.md`**

In the fact-discipline section, add (place near the corpus-validate / verification-status rules):
```markdown
- **App-MITM is wire-verified.** Captures from snooping the app↔mower link
  (mitmproxy on :13267, e.g. the 2026-06-09 settings sweep and 2026-06-10
  schedule-write decode) count as wire-verification across the board — not only
  for calendar entities, and not limited to integration-originated wire. A claim
  proven by a clean single-variable diff against an app↔mower capture may be
  marked `confirmed` and a control flipped writable, tagged
  `[app-mitm:<date>-<topic>]`.
```

- [ ] **Step 5: Mark roadmap row E done**

In `docs/research/app-integration-roadmap.md`, change the E row Status from `planned` to:
```
**done** (v1.0.25a5, 2026-06-10). write_schedule swapped from the device-ignored SCHEDULE.* KV to the SCHD*V3 chunked routed-action transport (protocol/schedule_action.py); encode_schedule_blob already emitted the verified 3-mode layout (no change). Existing set_schedule_plans service + dashboard card now reach the device. Granular per-run services / calendar-click editing deferred (TODO).
```

- [ ] **Step 6: Carry open items to `docs/research/knowledge-gaps.md`**

Add the doc §6 open items: byte[5] meaning (always 0x00, present in all 3 modes); 2nd-edge `seg=1` unconfirmed (test device has one edge/zone); multi-day-per-run (bitmask in byte[2] high bits vs multiple records) unconfirmed; SCHDSV3 `flag` second element semantics (0 in all captures); slot allocation on add-new.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/time.py custom_components/dreame_a2_mower/entity-inventory.yaml custom_components/dreame_a2_mower/inventory.yaml CLAUDE.md docs/research/app-integration-roadmap.md docs/research/knowledge-gaps.md
git commit -m "docs(schedule): retract BT-only claim; app-MITM=wire-verified rule; roadmap E done"
```

---

### Task 8: Version bump, full suite, inventory/audit gates

**Files:**
- Modify: `custom_components/dreame_a2_mower/manifest.json`

- [ ] **Step 1: Bump version**

`manifest.json` `"version": "1.0.25a4"` → `"1.0.25a5"`.

- [ ] **Step 2: Run the inventory-schema + wire-census + state-machine-audit gates**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q -k "inventory or audit or census or honesty"
```
Expected: PASS. If the state-machine audit goes red, it is because of a new/changed entity — add the honest expectations rows in `tools/state_machine/state_machine_audit_expectations.yaml` (do NOT weaken the gate; verify against `main` that the red is new to this branch). No new entities are expected this phase, so most likely green.

- [ ] **Step 3: Run the full test suite**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q
```
Expected: PASS (baseline was 2156 passed / 4 skipped on the Phase D branch; this phase adds tests and removes the `build_schedule_set_value` tests). Report the new totals.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/manifest.json
git commit -m "chore: bump to 1.0.25a5 (schedule editing via SCHD*V3)"
```

---

## Self-Review (completed)

- **Spec coverage:** transport (T1–T3), encoder reuse + pin (T4), coordinator swap + KV retirement (T5), service regression (T6), honesty/retraction/docs/roadmap/knowledge-gaps (T7), version + gates (T8). All spec sections mapped.
- **Placeholders:** none — all steps carry concrete code/commands; the two implementer notes (mixin name in T5, read shape in T3) point at real files to adapt, with the behavioural contract fixed.
- **Type consistency:** `write_schedule_row(send_action, *, slot, enabled, name, blob_b64, version, flag, txn_id)`, `read_schedule_rows(send_action) -> list[list]`, `chunk_row_json(str) -> list[tuple[int,str]]`, `encode_schedule_blob(tuple[SchedulePlan,...]) -> str` used consistently across tasks. `ScheduleSlot(slot_id, name, raw_blob_b64, plans, mode)` and `SchedulePlan(time_min, weekday_mask, action_type, zone_id, extra_bytes)` match `cloud_state.py`.
