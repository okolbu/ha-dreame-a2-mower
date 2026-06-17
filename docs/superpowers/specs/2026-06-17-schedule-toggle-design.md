# Schedule enable/disable toggle (todo7 #3) — design

**Date:** 2026-06-17 · **Status:** approved, pre-implementation

## Goal

Add a per-season schedule on/off control in HA that mirrors the Dreame app:
each schedule slot — **slot 0 = "Spr & Sum"**, **slot 1 = "Aut & Win"** — can be
the *sole active* schedule or off. Seasons are **mutually exclusive** (only one
active, or neither). Surfaced in the bundled schedule card as a header toggle by
the schedule name.

Also folds in a latent bug fix on the schedule **edit** path (see §6).

Out of scope: schedule name editing; fully decoding `SCHDSV3.i`.

## Wire facts (verified — `inventory.yaml § SCHDSV3`, app-mitm 2026-06-17)

- Enable/disable is a **standalone** routed write:
  `action(2, 50, [{m:'s', t:'SCHDSV3', d:{i:0, v:<version>, s:[slot0_enabled, slot1_enabled]}}])`.
- `s` is the **full atomic per-slot enabled array** `[slot0, slot1]`. To change a
  slot's state, write the whole array. Mutual exclusion is **device-enforced**:
  enabling Win writes `s:[0,1]` (auto-disables Spr); `s:[0,0]` = both off;
  `s:[1,1]` never occurs.
- `v` = the **current schedule version, regenerated on every write** (non-monotonic
  optimistic-concurrency token). Must read `SCHDIV3 {i:0}` for the fresh `v`
  immediately before each `SCHDSV3` write — done via the existing
  `read_live_schedule()` (shipped in #4), which returns both `v` and the current
  per-slot enabled rows in one call.
- `i = 0` (schedule-set index; not the changed slot; non-load-bearing).
- **App-side gate:** the app refuses enable/disable while a task is running
  ("end task before…") and never sends the write mid-task. The integration
  **replicates this as a hard block** (mower-side mid-task behavior is untested).

## Components

### 1. Sensor — expose `enabled`

`entities/sensor/device.py: DreameA2ScheduleCountSensor.extra_state_attributes`:
add `enabled: bool` to each slot dict, from `ScheduleSlot.mode` (wire element
`[1]`). This is the only new data the card needs. Update `entity-inventory.yaml`.

### 2. Protocol — `protocol/schedule_action.py`

New pure helper:

```python
def write_schedule_enabled(send_action, *, version: int, enabled: list[int]) -> None:
    """Standalone SCHDSV3 enable/disable write. `enabled` = full [slot0, slot1]
    array (mutual exclusion is the caller's responsibility). Raises CfgActionError
    on r!=0."""
    _send(send_action, "SCHDSV3", {"i": 0, "v": int(version), "s": [int(enabled[0]), int(enabled[1])]})
```

### 3. Edit-path fix — `write_schedule_row` (same file)

The current SCHDSV3 leg sends `s:[enabled, flag]` (flag=0). Since `s` is the full
`[slot0, slot1]` array, editing slot 1's plans while it is active would write
`s:[slot1_enabled, 0]` — wrongly enabling slot 0 and disabling slot 1 (flipping
the active season). Fix: replace the `enabled, flag` params with a single
`enabled_array: list[int]` (the full `[slot0, slot1]`), and send
`{"i": <slot>, "v": version, "s": enabled_array}`. The caller computes the array
once from the authoritative rows (it already reads them). `i` stays the slot
index on the edit path (unchanged, live-validated); `i` is non-load-bearing.

### 4. Coordinator — `coordinator/_writes.py`

**New** `write_schedule_enabled(self, slot_id: int, enabled: bool) -> bool`:
1. **Active-task guard (hard block):** if the mower is in an active task, raise
   `ServiceValidationError("End the current task before changing a schedule.")`.
   Predicate: the running-task signal already used elsewhere (state-machine
   in-session / lawn_mower in a mowing/returning state) — pinned during
   implementation against the existing helpers.
2. `read_live_schedule(self._cloud.action)` → current per-slot enabled + `v`.
   If unavailable, fall back to `cloud_state.schedule` for the current array and
   `version`.
3. Compute the new array:
   - **enable slot X** → `[1 if i == slot_id else 0 for i in (0, 1)]` (sole active).
   - **disable slot X** → current array with element `slot_id` set to 0.
4. `write_schedule_enabled(self._cloud.action, version=v, enabled=new_array)` via
   executor, under `self._chunked_write_lock`.
5. `await self._refresh_cloud_state()`; return ok.

**Fix** `write_schedule`: build `enabled_array = [by_slot[i][1] if i in by_slot
else 0 for i in (0, 1)]` from the live rows and pass it to `write_schedule_row`
(replacing the per-row `enabled`/`flag`). Preserves both seasons' states across a
plan edit.

### 5. Service — `services.py`

`dreame_a2_mower.set_schedule_enabled`, schema `{slot_id: int (0|1), enabled:
bool}` → `coordinator.write_schedule_enabled`. Errors surfaced via the existing
`raise_for_write_result` pattern.

### 6. Card — `www/dreame-a2-schedule-card.js`

- Read `slot.enabled` from sensor attrs.
- Header row under the tabs: selected schedule's name (left) + on/off toggle
  (right). Disabled tabs render dimmed so the active season is glanceable.
- The toggle is **disabled (greyed, with a hint)** while the mower is in an active
  task — read the lawn_mower entity state from `hass`.
- On toggle: `hass.callService("dreame_a2_mower", "set_schedule_enabled",
  {slot_id, enabled})`, optimistic re-render.
- `console.info` CARD_VERSION banner bumped by `release.sh`.

### 7. Tests

- **protocol:** `write_schedule_enabled` emits one `SCHDSV3 {i:0, v, s:[..]}`;
  `write_schedule_row` now emits the full `s` array (update
  `test_write_schedule_row_envelope`).
- **coordinator:** `write_schedule_enabled` — enable → sole-active array; disable
  → element zeroed; reads fresh `v`; **hard-blocks during an active task**
  (raises). `write_schedule` regression: editing slot 1 preserves
  `s:[slot0_enabled, 1]` (does not flip the season).
- **service wiring:** `set_schedule_enabled` registered + dispatches.

### 8. Inventory / docs

`inventory.yaml § SCHDSV3` already updated (this session). `entity-inventory.yaml`:
add the new service + the sensor `enabled` attribute. Regenerate
`g2408-canonical.md` if SCHDSV3 prose changed (it did).

## Verification

Release via `tools/release/release.sh`, install on live HA, then: toggle each
season on/off from the card and confirm `sensor.schedule_count` `enabled` flips
and mutual exclusion holds (enabling Win disables Spr). Confirm the toggle is
blocked while mowing. Confirm editing one season's plans does not flip the active
season.
