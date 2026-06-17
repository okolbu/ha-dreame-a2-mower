# Schedule enable/disable toggle (todo7 #3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-season schedule on/off toggle (slot 0 = Spr & Sum, slot 1 = Aut & Win) in HA, mirroring the app — mutually exclusive, blockable during an active task — plus fix a latent edit-path bug in the SCHDSV3 enabled-state write.

**Architecture:** A standalone `SCHDSV3 {i:0, v, s:[slot0,slot1]}` routed write sets the full per-slot enabled array (mutual exclusion is device-enforced). A new pure protocol helper builds the write; a coordinator method reads the fresh version + current array and computes the new one; a service guards against active tasks and dispatches; the bundled schedule card gains a header toggle. The same s-array fix is applied to the existing `write_schedule_row` so editing one season's plans no longer flips the active season.

**Tech Stack:** Python (Home Assistant custom component), pure-protocol layer, vanilla-pytest test venv at `/data/claude/homeassistant/.venv-vanilla/bin/python`, JS Lovelace card.

**Test command (use throughout):**
`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -q`

**Wire reference (verified — `inventory.yaml § SCHDSV3`):**
`action(2,50,[{m:'s', t:'SCHDSV3', d:{i:0, v:<current schedule version>, s:[slot0_enabled, slot1_enabled]}}])`. `s` is the full atomic array; enabling one slot auto-disables the other; `[0,0]` = both off. `v` = the current version read fresh via `SCHDIV3 {i:0}` (the existing `read_live_schedule()` returns it). App blocks the toggle during an active task.

---

### Task 1: Sensor exposes per-slot `enabled`

**Files:**
- Modify: `custom_components/dreame_a2_mower/entities/sensor/device.py` (`DreameA2ScheduleCountSensor.extra_state_attributes`, ~line 1262)
- Test: `tests/integration/test_cloud_state_sensors.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_cloud_state_sensors.py`:

```python
def test_schedule_count_sensor_exposes_enabled_per_slot():
    """Each slot dict carries `enabled` (bool of ScheduleSlot.mode) so the
    card can render the on/off toggle."""
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        DreameA2ScheduleCountSensor,
    )
    from custom_components.dreame_a2_mower.cloud_state import (
        ScheduleData, ScheduleSlot,
    )
    from types import SimpleNamespace

    sensor = object.__new__(DreameA2ScheduleCountSensor)
    sensor.coordinator = SimpleNamespace(
        cloud_state=SimpleNamespace(
            schedule=ScheduleData(
                version=5,
                slots=(
                    ScheduleSlot(slot_id=0, name="Spr & Sum", raw_blob_b64="", plans=(), mode=1),
                    ScheduleSlot(slot_id=1, name="", raw_blob_b64="", plans=(), mode=0),
                ),
            )
        )
    )
    attrs = sensor.extra_state_attributes
    assert attrs["slots"][0]["enabled"] is True
    assert attrs["slots"][1]["enabled"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_cloud_state_sensors.py::test_schedule_count_sensor_exposes_enabled_per_slot -q`
Expected: FAIL with `KeyError: 'enabled'`.

- [ ] **Step 3: Add the field**

In `extra_state_attributes`, add `"enabled"` to each slot dict (right after `"name": s.name,`):

```python
                {
                    "slot_id": s.slot_id,
                    "name": s.name,
                    "enabled": bool(s.mode),
                    "plans": [
```

- [ ] **Step 4: Run test to verify it passes**

Run: same command as Step 2. Expected: PASS.

- [ ] **Step 5: Run the existing sensor tests to catch exact-dict assertions**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_cloud_state_sensors.py -q`
Expected: PASS. If a pre-existing test asserts the slots dict by exact equality and now fails on the extra key, add `"enabled": <bool>` to that expected dict.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/entities/sensor/device.py tests/integration/test_cloud_state_sensors.py
git commit -m "feat(schedule): expose per-slot enabled in schedule_count sensor"
```

---

### Task 2: Protocol — toggle helper + fix `write_schedule_row` s-array

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/schedule_action.py` (`write_schedule_row`, ~line 46; add new helper)
- Test: `tests/unit/test_schedule_action.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_schedule_action.py`:

```python
def test_write_schedule_enabled_state_envelope():
    calls = []
    sa.write_schedule_enabled_state(
        _fake_send_action(calls), version=58177, enabled=[0, 1]
    )
    assert len(calls) == 1
    siid, aiid, payload = calls[0]
    assert (siid, aiid) == (2, 50)
    assert payload["t"] == "SCHDSV3"
    assert payload["d"] == {"i": 0, "v": 58177, "s": [0, 1]}


def test_write_schedule_enabled_state_raises_on_error():
    import pytest
    with pytest.raises(sa.CfgActionError):
        sa.write_schedule_enabled_state(
            _fake_send_action([], fail_on="SCHDSV3"), version=1, enabled=[1, 0]
        )
```

- [ ] **Step 2: Update the existing `write_schedule_row` tests to the new signature**

In `tests/unit/test_schedule_action.py`, change `test_write_schedule_row_envelope`: replace the call args `enabled=1, ..., flag=0,` with `enabled_array=[1, 0],` and keep the final assertion `assert state == {"i": 0, "v": 5, "s": [1, 0]}`. Change `test_write_schedule_row_raises_on_error`: replace `enabled=1, ..., flag=0,` with `enabled_array=[1, 0],`.

The edited `test_write_schedule_row_envelope` call becomes:

```python
    sa.write_schedule_row(
        _fake_send_action(calls),
        slot=0, enabled_array=[1, 0], name="Spr", blob_b64="qghRIBIAAu0=",
        version=5, txn_id=1781118711306,
    )
```

And `test_write_schedule_row_raises_on_error`:

```python
        sa.write_schedule_row(
            _fake_send_action([], fail_on="SCHDSV3"),
            slot=0, enabled_array=[1, 0], name="Spr", blob_b64="qghRIBIAAu0=",
            version=5, txn_id=1,
        )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_schedule_action.py -q`
Expected: FAIL — `write_schedule_enabled_state` undefined; `write_schedule_row` got unexpected kwarg `enabled_array`.

- [ ] **Step 4: Change `write_schedule_row` signature + add the helper**

In `protocol/schedule_action.py`, replace `write_schedule_row` (lines 46-69) with:

```python
def write_schedule_row(
    send_action,
    *,
    slot: int,
    enabled_array: list[int],
    name: str,
    blob_b64: str,
    version: int,
    txn_id: int,
) -> None:
    """Write one schedule slot row via the chunked SCHD*V3 transaction.

    Order: SCHDIV3 header -> N SCHDDV3 chunks (shared txn_id) -> SCHDSV3 state.
    `version` is the schedule version (SCHDSV3 `v`); `txn_id` is the shared
    header/chunk `v`. `enabled_array` is the FULL [slot0_enabled, slot1_enabled]
    array — SCHDSV3 `s` is the whole per-slot enabled array, NOT [thisslot, flag]
    (sending [enabled, 0] would wrongly disable the OTHER season on an edit).
    Raises CfgActionError if any leg returns r!=0.
    """
    row_json = json.dumps([slot, enabled_array[slot], name, blob_b64], separators=(",", ":"))
    total_len = len(row_json.encode("utf-8"))
    _send(send_action, "SCHDIV3", {"i": slot, "l": total_len, "v": txn_id})
    for off, chunk in chunk_row_json(row_json):
        _send(send_action, "SCHDDV3",
              {"s": off, "l": len(chunk.encode("utf-8")), "d": chunk, "v": txn_id})
    _send(send_action, "SCHDSV3", {"i": slot, "v": version, "s": list(enabled_array)})


def write_schedule_enabled_state(send_action, *, version: int, enabled: list[int]) -> None:
    """Standalone schedule enable/disable write (the "season switch").

    Issues a single SCHDSV3 setter `{i:0, v:version, s:[slot0, slot1]}`. The
    full enabled array is written atomically; the device enforces mutual
    exclusion ([1,1] never occurs, [0,0] = both off). `version` MUST be the
    current schedule version read immediately before this write (it is a
    regenerated optimistic-concurrency token, not a counter). Raises
    CfgActionError on r!=0. [app-mitm:2026-06-17]
    """
    _send(send_action, "SCHDSV3",
          {"i": 0, "v": int(version), "s": [int(enabled[0]), int(enabled[1])]})
```

Note: `row_json`'s second element changes from `enabled` to `enabled_array[slot]` — the row's own enabled bit stays correct, while the SCHDSV3 `s` now carries the full array.

- [ ] **Step 5: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_schedule_action.py -q`
Expected: PASS (all, including the updated row tests).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/schedule_action.py tests/unit/test_schedule_action.py
git commit -m "feat(schedule): add SCHDSV3 toggle helper; write_schedule_row sends full enabled array"
```

---

### Task 3: Coordinator `write_schedule` passes the full enabled array (edit-path bug fix)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py` (`write_schedule`, lines 97-181)
- Test: `tests/integration/test_write_schedule_device_plane.py`

- [ ] **Step 1: Write the failing regression test**

Add to `tests/integration/test_write_schedule_device_plane.py`:

```python
@pytest.mark.asyncio
async def test_write_schedule_preserves_other_season_enabled(monkeypatch):
    """Editing slot 1's plans while slot 1 is the active season must NOT flip
    the active season: SCHDSV3 s must be [slot0_enabled, slot1_enabled], not
    [thisslot_enabled, 0]."""
    import custom_components.dreame_a2_mower.coordinator._writes as W
    from custom_components.dreame_a2_mower.protocol.schedule_encode import (
        encode_schedule_blob,
    )

    # Live rows: slot0 OFF, slot1 ON.
    rows = [[0, 0, "Spr", "OLDSPR"], [1, 1, "Win", "OLDWIN"]]
    new_plan = SchedulePlan(
        time_min=600, weekday_mask=0b1, action_type=0, zone_id=None, extra_bytes=b""
    )
    new_slots = [
        ScheduleSlot(slot_id=1, name="Win", raw_blob_b64="", plans=(new_plan,), mode=1)
    ]
    c, captured, write_row, read_live = _make_coord(rows, version=7)
    monkeypatch.setattr(W, "write_schedule_row", write_row, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", read_live, raising=False)
    c.cloud_state = SimpleNamespace(schedule=ScheduleData(version=7, slots=()))

    ok = await c.write_schedule(new_slots)

    assert ok is True
    assert len(captured["row_writes"]) == 1
    assert captured["row_writes"][0]["slot"] == 1
    assert captured["row_writes"][0]["enabled_array"] == [0, 1]  # both seasons preserved
```

Also update the existing assertions in `test_write_schedule_uses_device_plane_not_kv` that reference removed kwargs:
- replace `assert w["enabled"] == 1` with `assert w["enabled_array"] == [1, 0]` (rows there are `[[0,1,...],[1,0,...]]`);
- **delete** `assert w["flag"] == 0` (the `flag` param no longer exists).

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_write_schedule_device_plane.py -q`
Expected: FAIL — `write_schedule` still passes `enabled=`/`flag=`, not `enabled_array=`.

- [ ] **Step 3: Update `write_schedule`**

In `coordinator/_writes.py`, after the `by_slot = {...}` block, add the enabled-array computation:

```python
    by_slot = {
        r[0]: r for r in rows if isinstance(r, list) and len(r) == 4
    }
    # SCHDSV3 `s` is the FULL per-slot enabled array; build it once from the
    # live rows so editing one season's plans preserves the OTHER season's
    # on/off (sending [thisslot, 0] would flip the active season).
    enabled_array = [
        int(by_slot[i][1]) if i in by_slot else 0 for i in (0, 1)
    ]
```

Then in the loop, delete the `enabled = int(prev[1]) if prev else 1` and `flag = 0` lines, and change the `write_schedule_row` call to pass `enabled_array`:

```python
            txn_id = self._next_schedule_txn_id()
            try:
                await self.hass.async_add_executor_job(
                    lambda s=slot, b=blob_b64, t=txn_id, n=wire_name, ea=enabled_array: write_schedule_row(
                        self._cloud.action,
                        slot=s.slot_id,
                        enabled_array=ea,
                        name=n,
                        blob_b64=b,
                        version=new_version,
                        txn_id=t,
                    )
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_write_schedule_device_plane.py tests/integration/test_coordinator_writes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_writes.py tests/integration/test_write_schedule_device_plane.py
git commit -m "fix(schedule): preserve both seasons' enabled state on a plan edit"
```

---

### Task 4: Coordinator `write_schedule_enabled` (the toggle)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py` (add method; import the helper, line 59)
- Test: `tests/integration/test_write_schedule_device_plane.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_write_schedule_device_plane.py`:

```python
def _make_toggle_coord(rows, version):
    """Bare _WritesMixin with a captured SCHDSV3-only send path."""
    from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin
    c = _WritesMixin()
    captured = {"enabled_writes": []}

    def _write_enabled(send_action, *, version, enabled):
        captured["enabled_writes"].append({"version": version, "enabled": enabled})

    def _read_live(send_action):
        return {"d": rows, "v": version}

    c._cloud = SimpleNamespace(action=lambda *a, **k: None)
    c._chunked_write_lock = asyncio.Lock()
    c._refresh_cloud_state = AsyncMock()

    async def _exec(fn, *a, **k):
        return fn(*a, **k)

    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    return c, captured, _write_enabled, _read_live


@pytest.mark.asyncio
async def test_write_schedule_enabled_enable_makes_sole_active(monkeypatch):
    import custom_components.dreame_a2_mower.coordinator._writes as W
    rows = [[0, 1, "Spr", "B"], [1, 0, "Win", "B"]]  # Spr on
    c, captured, write_enabled, read_live = _make_toggle_coord(rows, version=99)
    monkeypatch.setattr(W, "write_schedule_enabled_state", write_enabled, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", read_live, raising=False)

    ok = await c.write_schedule_enabled(slot_id=1, enabled=True)

    assert ok is True
    assert captured["enabled_writes"] == [{"version": 99, "enabled": [0, 1]}]  # Win on, Spr off
    c._refresh_cloud_state.assert_awaited()


@pytest.mark.asyncio
async def test_write_schedule_enabled_disable_zeroes_slot(monkeypatch):
    import custom_components.dreame_a2_mower.coordinator._writes as W
    rows = [[0, 0, "Spr", "B"], [1, 1, "Win", "B"]]  # Win on
    c, captured, write_enabled, read_live = _make_toggle_coord(rows, version=42)
    monkeypatch.setattr(W, "write_schedule_enabled_state", write_enabled, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", read_live, raising=False)

    ok = await c.write_schedule_enabled(slot_id=1, enabled=False)

    assert ok is True
    assert captured["enabled_writes"] == [{"version": 42, "enabled": [0, 0]}]  # both off
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_write_schedule_device_plane.py -k enabled -q`
Expected: FAIL — `write_schedule_enabled` undefined.

- [ ] **Step 3: Update the import and add the method**

In `coordinator/_writes.py` line 59, add the helper to the import:

```python
from ..protocol.schedule_action import (
    read_live_schedule,
    write_schedule_enabled_state,
    write_schedule_row,
)
```

Add this method to `_WritesMixin` (right after `write_schedule`):

```python
    async def write_schedule_enabled(self, slot_id: int, enabled: bool) -> bool:
        """Enable or disable one schedule season via a standalone SCHDSV3 write.

        Seasons are mutually exclusive (device-enforced): enabling a slot makes
        it the sole active one; disabling a slot sets it off (and, since only one
        is ever on, leaves no schedule running). Reads the live schedule for the
        fresh version + current enabled states, then writes the full array.

        Does NOT guard against an active task — the service layer does (it owns
        the user-facing ServiceValidationError).
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_schedule_enabled: cloud client not ready")
            return False

        live = await self.hass.async_add_executor_job(
            read_live_schedule, self._cloud.action
        )
        if live is not None:
            rows = live.get("d") or []
            version = int(live.get("v") or 0)
            by_slot = {r[0]: r for r in rows if isinstance(r, list) and len(r) == 4}
            current = [int(by_slot[i][1]) if i in by_slot else 0 for i in (0, 1)]
        else:
            cs = self.cloud_state
            version = cs.schedule.version if cs is not None else 0
            current = [0, 0]
            if cs is not None:
                for s in cs.schedule.slots:
                    if s.slot_id in (0, 1):
                        current[s.slot_id] = int(s.mode)

        if enabled:
            new_array = [1 if i == slot_id else 0 for i in (0, 1)]  # sole active
        else:
            new_array = list(current)
            if slot_id in (0, 1):
                new_array[slot_id] = 0

        ok = True
        async with self._chunked_write_lock:
            try:
                await self.hass.async_add_executor_job(
                    lambda v=version, a=new_array: write_schedule_enabled_state(
                        self._cloud.action, version=v, enabled=a
                    )
                )
                LOGGER.info(
                    "[schedule-enable] slot %d -> %s, s=%s, v=%d",
                    slot_id, "on" if enabled else "off", new_array, version,
                )
            except Exception as exc:  # noqa: BLE001 — surface, keep going
                ok = False
                LOGGER.warning("[schedule-enable] slot %d rejected: %r", slot_id, exc)

        await self._refresh_cloud_state()
        return ok
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_write_schedule_device_plane.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_writes.py tests/integration/test_write_schedule_device_plane.py
git commit -m "feat(schedule): coordinator write_schedule_enabled (atomic mutual-exclusive toggle)"
```

---

### Task 5: Service `set_schedule_enabled` (with active-task guard)

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py` (add `SERVICE_SET_SCHEDULE_ENABLED`)
- Modify: `custom_components/dreame_a2_mower/services.py` (schema + handler + registration)
- Modify: `custom_components/dreame_a2_mower/services.yaml` (UI descriptor)
- Test: `tests/integration/test_set_schedule_plans_service.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_set_schedule_plans_service.py` (reuse that file's existing service-test scaffolding for registering services + building a fake coordinator; match its existing pattern for invoking a handler):

```python
@pytest.mark.asyncio
async def test_set_schedule_enabled_blocks_during_active_task(monkeypatch):
    """The service raises ServiceValidationError when a mow session is active,
    and never calls the coordinator write."""
    import custom_components.dreame_a2_mower.services as S
    from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession
    from homeassistant.exceptions import ServiceValidationError
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import pytest

    coordinator = SimpleNamespace(
        state_machine=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(mow_session=MowSession.IN_SESSION)
        ),
        write_schedule_enabled=AsyncMock(return_value=True),
    )
    call = SimpleNamespace(data={"slot_id": 0, "enabled": False})
    with pytest.raises(ServiceValidationError):
        await S._handle_set_schedule_enabled.__wrapped__(coordinator, call)
    coordinator.write_schedule_enabled.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_schedule_enabled_dispatches_when_idle(monkeypatch):
    import custom_components.dreame_a2_mower.services as S
    from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    coordinator = SimpleNamespace(
        state_machine=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(mow_session=MowSession.BETWEEN_SESSIONS)
        ),
        write_schedule_enabled=AsyncMock(return_value=True),
    )
    call = SimpleNamespace(data={"slot_id": 1, "enabled": True})
    await S._handle_set_schedule_enabled.__wrapped__(coordinator, call)
    coordinator.write_schedule_enabled.assert_awaited_once_with(slot_id=1, enabled=True)
```

Note: `.__wrapped__` calls the handler body directly, bypassing the `@service_handler` decorator's coordinator-resolution. If the existing service tests in this file invoke handlers a different way (e.g. via a registered `hass.services` stub), mirror that pattern instead and keep the two assertions (raises-when-in-session / dispatches-when-idle).

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_set_schedule_plans_service.py -k set_schedule_enabled -q`
Expected: FAIL — `_handle_set_schedule_enabled` undefined.

- [ ] **Step 3: Add the const**

In `const.py`, next to `SERVICE_SET_SCHEDULE_PLANS`, add:

```python
SERVICE_SET_SCHEDULE_ENABLED = "set_schedule_enabled"
```

- [ ] **Step 4: Add schema, handler, registration in services.py**

Near `SCHEMA_SET_SCHEDULE_PLANS` add:

```python
SCHEMA_SET_SCHEDULE_ENABLED = vol.Schema({
    vol.Required("slot_id"): vol.All(vol.Coerce(int), vol.In([0, 1])),
    vol.Required("enabled"): vol.Coerce(bool),
})
```

Near `_handle_set_schedule_plans` add (import `MowSession` at the top of the handler, matching the file's local-import style):

```python
@service_handler
async def _handle_set_schedule_enabled(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Enable/disable one schedule season (mutually exclusive). Blocked while a
    mow session is active — the Dreame app forbids this mid-task; we replicate
    the guard (the mower's mid-task behavior is untested)."""
    from .mower.state_snapshot import MowSession

    sm = getattr(coordinator, "state_machine", None)
    if sm is not None and sm.snapshot().mow_session == MowSession.IN_SESSION:
        raise ServiceValidationError(
            "End the current mowing task before changing a schedule's on/off state."
        )
    slot_id = int(call.data["slot_id"])
    enabled = bool(call.data["enabled"])
    ok = await coordinator.write_schedule_enabled(slot_id=slot_id, enabled=enabled)
    LOGGER.info("set_schedule_enabled: slot %d -> %s, accepted=%s",
                slot_id, "on" if enabled else "off", ok)
    if not ok:
        raise ServiceValidationError(
            f"Set schedule enabled: device rejected the write for slot {slot_id}"
        )
```

Near the other `async_register` calls add:

```python
    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE_ENABLED,
                                 _handle_set_schedule_enabled, schema=SCHEMA_SET_SCHEDULE_ENABLED)
```

Add `SERVICE_SET_SCHEDULE_ENABLED` to the `from .const import (...)` block in services.py.

- [ ] **Step 5: Add the services.yaml descriptor**

Append to `services.yaml`:

```yaml
set_schedule_enabled:
  name: Set schedule enabled
  description: >-
    Enable or disable a mowing schedule season (Spr & Sum = slot 0,
    Aut & Win = slot 1). Seasons are mutually exclusive: enabling one disables
    the other; disabling the active one leaves no schedule running. Blocked
    while the mower is in an active task.
  fields:
    slot_id:
      name: Slot
      description: 0 = Spr & Sum, 1 = Aut & Win.
      required: true
      selector:
        number:
          min: 0
          max: 1
          mode: box
    enabled:
      name: Enabled
      description: Turn this schedule on (and the other off) or off.
      required: true
      selector:
        boolean:
```

- [ ] **Step 6: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_set_schedule_plans_service.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/const.py custom_components/dreame_a2_mower/services.py custom_components/dreame_a2_mower/services.yaml tests/integration/test_set_schedule_plans_service.py
git commit -m "feat(schedule): set_schedule_enabled service with active-task guard"
```

---

### Task 6: Schedule card — header toggle + dimmed tabs + task-disable

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-a2-schedule-card.js`
- Verify: node syntax check + render-fn harness (no pytest for JS).

- [ ] **Step 1: Add a config field for the mower entity**

In `setConfig` (line 33-35), add:

```javascript
  setConfig(config) {
    this._sensor = config.sensor || "sensor.dreame_a2_mower_schedule_count";
    this._mowerEntity = config.mower_entity || "lawn_mower.dreame_a2_mower";
  }
```

- [ ] **Step 2: Render the header toggle + dim disabled tabs**

In `_render(state)`, after the `tabs` const, compute the active slot's enabled + task state, and build a header row. Replace the tabs/grid section of the template. First, after `const active = slots[this._activeSlot] || ...;` add:

```javascript
    const activeEnabled = !!active.enabled;
    const mowerState = (this._hass.states[this._mowerEntity] || {}).state;
    const taskActive = ["mowing", "returning", "paused"].includes(mowerState);
    const toggleTitle = taskActive
      ? "End the current task to change schedules"
      : (activeEnabled ? "Schedule is ON — click to turn off"
                       : "Schedule is OFF — click to turn on");
    const header = `
      <div class="sched-header">
        <span class="sched-name">${active.name || SLOT_DEFAULTS[active.slot_id] || `Schedule ${active.slot_id + 1}`}</span>
        <button class="toggle ${activeEnabled ? "on" : "off"}" ${taskActive ? "disabled" : ""} title="${toggleTitle}">
          ${activeEnabled ? "ON" : "OFF"}
        </button>
      </div>`;
```

Change the tab button markup so disabled tabs are dimmed — replace the `.tab` button template with:

```javascript
          `<button class="tab ${i === this._activeSlot ? "active" : ""} ${s.enabled ? "" : "tab-off"}" data-slot="${i}">${
            s.name || SLOT_DEFAULTS[s.slot_id] || `Schedule ${s.slot_id + 1}`
          }</button>`,
```

Insert `${header}` into the card body, right after `<div class="tabs">${tabs}</div>`:

```javascript
      <ha-card>
        <div class="tabs">${tabs}</div>
        ${header}
        ${grid}
```

Add styles inside the `<style>` block:

```css
        .sched-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
        .sched-name { font-weight: bold; }
        .toggle { padding: 4px 14px; border-radius: 12px; border: 1px solid var(--divider-color); cursor: pointer; }
        .toggle.on { background: var(--primary-color); color: var(--text-primary-color); }
        .toggle.off { background: transparent; color: var(--secondary-text-color); }
        .toggle:disabled { opacity: 0.5; cursor: not-allowed; }
        .tab.tab-off { opacity: 0.5; }
```

- [ ] **Step 3: Wire the toggle click**

In `_render`, after the existing `.tab` click wiring (after the `querySelectorAll(".tab")` block), add:

```javascript
    const toggleBtn = this.shadowRoot.querySelector(".toggle");
    if (toggleBtn && !toggleBtn.disabled) {
      toggleBtn.addEventListener("click", () => {
        const slot = slots[this._activeSlot];
        this._hass.callService("dreame_a2_mower", "set_schedule_enabled", {
          slot_id: slot.slot_id,
          enabled: !slot.enabled,
        });
        // Optimistic: reflect immediately; the next cloud refresh confirms.
        slot.enabled = !slot.enabled;
        this._render(this._stateRef);
      });
    }
```

- [ ] **Step 4: Bump the card banner**

Change the final `console.info(...)` line to mention the toggle, e.g.:

```javascript
console.info("dreame-a2-schedule-card v1.0.2a2 (full UX + on/off toggle) loaded");
```

(release.sh rewrites `CARD_VERSION`; this card has none, so the banner string is informational only.)

- [ ] **Step 5: Verify JS syntax**

Run: `node --check custom_components/dreame_a2_mower/www/dreame-a2-schedule-card.js` if node is available; otherwise rely on `release.sh`'s node check at release time. Expected: no output (OK).

- [ ] **Step 6: Verify the render path in a node harness**

Per `feedback_frontend_card_verification`, exercise `_render` with a stub `hass` having `states["sensor..."].attributes.slots = [{slot_id:0,name:"Spr",enabled:true,plans:[]},{slot_id:1,name:"",enabled:false,plans:[]}]` and `states["lawn_mower.dreame_a2_mower"].state="docked"`. Confirm the produced `shadowRoot.innerHTML` contains a `.toggle.on` for slot 0 and, after switching to slot 1, a `.toggle.off`; and with mower state `"mowing"` the toggle button has `disabled`. Write this as a throwaway node script (jsdom or a minimal HTMLElement shim) — it does not need to live in the repo.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-a2-schedule-card.js
git commit -m "feat(schedule): card header on/off toggle + dimmed disabled tabs"
```

---

### Task 7: Entity inventory, canonical doc, full suite, release

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify (generated): `docs/research/inventory/generated/g2408-canonical.md`

- [ ] **Step 1: Record the new service + sensor attr in entity-inventory.yaml**

Add an entry for the `set_schedule_enabled` service (mirror the `set_schedule_plans` entry's shape: read/write source, verification status `presumed` until live-verified) and note the `enabled` attribute added to `sensor.dreame_a2_mower_schedule_count`. Use today's date.

- [ ] **Step 2: Regenerate the canonical doc**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py`
Then `git diff --stat docs/research/inventory/generated/g2408-canonical.md` — confirm only the SCHDSV3 section changed; do NOT commit unrelated wire-census count churn (per `reference_canonical_doc_drift`).

- [ ] **Step 3: Validate inventory schema**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only`
Expected: `ok: inventory schema valid`.

- [ ] **Step 4: Run the FULL test suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q --ignore=tests/archive`
Expected: all pass (baseline ~2548 + the new tests). Fix any audit-gate failures: a new service usually needs no audit row, but if `tests/audit/*` or `state_machine_audit_expectations.yaml` goes red, add the expected row (per `project_app_findings_phase0_shipped` recurring-gotcha note).

- [ ] **Step 5: Commit docs**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "docs(schedule): inventory + canonical for set_schedule_enabled"
```

- [ ] **Step 6: Release + live-verify**

Push, then `tools/release/release.sh --notes "..."`. Install via HACS, restart HA. Verify on live HA:
1. `sensor.dreame_a2_mower_schedule_count` slots carry `enabled`.
2. Card header toggle flips a season on/off; enabling Win disables Spr (mutual exclusion); `enabled` updates after refresh.
3. Toggle is blocked (service raises) and the card button is disabled while mowing.
4. Editing one season's plans does NOT flip the active season (the Task 3 fix).

---

## Notes / gotchas (carried from memory + this session)

- Test interpreter: `/data/claude/homeassistant/.venv-vanilla/bin/python`. System `python3` is a broken 3.14.
- `cv.string` is broken in the test stub — use `vol.Coerce(str)`; for the bool/int here use `vol.Coerce(bool)` / `vol.Coerce(int)` + `vol.In`.
- Stage commits by explicit path — a second process commits with `git add -A`.
- The active-task guard lives in the **service** (correct `ServiceValidationError` context); the coordinator method does not raise.
- Mutual exclusion is **device-enforced** — we still write the full array so the device sees the intended state in one atomic write.
- The toggle uses the **current** schedule version (read fresh), NOT a bumped one (unlike the edit path's `new_version`).
