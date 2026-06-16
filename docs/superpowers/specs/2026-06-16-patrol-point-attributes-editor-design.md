# Patrol-point attributes (cycles + auto-capture) in the map editor — design

**Date:** 2026-06-16
**Status:** approved (brainstorm) — pending spec review → implementation plan
**Scope:** read + write the per-point patrol attributes (Number of Patrol Cycles 1/2/3,
Auto-Capture & Upload Photos on/off) from the dashboard map-editor card, plus surface the
read values on the existing patrol-points sensor.

---

## Background / wire facts (already established, this session)

Patrol points have two independent surfaces on the g2408:

- **Geometry** — `o=223 {id, points:[x,y,heading]}`, edited inside the map-editor `edit_map`
  transaction (`o=204` begin → mutations → `o=201` commit). Already shipped: create / move /
  delete in `dreame-map-editor-card.js` + `create_patrol_point` / `delete_map_object` services.
- **Per-point attributes** — cycles + auto-capture. NOT in `o=223`, the `o=107` run payload,
  `s2p56`, or the session summary. They live in a **standalone `CRUISED` CFG write** and are
  **read back** via the **`CRUISE.0` device-data key** (see `inventory.yaml § CRUISED`):
  - **Write:** `action s2.50 {m:'s', t:'CRUISED', d:{idx:<map index>, value:[-1, point_id,
    auto_capture(0/1), cycles(1/2/3)]}}`. `value[0]=-1` is a constant sentinel (not mirrored on
    read). One write per point.
  - **Read:** `CRUISE.0` is a sibling of `MAP.*` in the `getDeviceData` response (which the map
    fetch already pulls; `getDeviceData` ignores the key filter). It is a JSON-string per-map
    outer array: `[{version, settings:{<point_id>:{num:<cycles>, ap:<auto_capture bool>}}}, …]`
    (element[0]=map 0, element[1]=map 1; unused map = `{version:-1, settings:{}}`; `version` is
    device-owned, increments per edit). Sibling key `CRUISE.info=107` (the patrol opcode).
  - **Round-trip confirmed:** write `[-1,3,1,3]` → `CRUISE.0` `settings '3':{num:3, ap:true}`.
  - No `m:g` getter exists on `t:CRUISED` (returns `r=-3`); `CRUISE.0` device-data is the only
    read path. Both are wire-verified (app-MITM 2026-06-16).

## Decisions (from brainstorm)

1. **Commit model:** write **immediately** on change. Selecting a patrol point shows an inline
   panel; changing cycles or auto-capture fires the `CRUISED` write right away, independent of
   the geometry Save. (CRUISED is its own CFG write, not part of the geometry txn.)
2. **Scope:** **existing (committed) points only** for v1. A newly-created point defaults to
   **cycles=1 / auto-capture off** (the app/device sets these on create), so no deferred-write or
   draft-id correlation is needed — the user selects the now-committed point and edits it via the
   same panel. The attribute panel is hidden for an uncommitted draft point.
3. **Read surfacing (approach A):** the single `CRUISE.0` parse feeds BOTH the editor
   (`editable_objects` patrol entries) AND the existing per-map patrol-points sensor (whose
   `cycles`/`auto_capture` items are currently `null`). Closes the "surface from CRUISE.0" TODO.

---

## Architecture

Three small units, one per layer, each independently testable.

### 1. `CRUISE.0` parser (pure) — `protocol/`
A pure function `parse_cruise_config(raw) -> dict[int, dict[int, dict]]`:
- Input: the `CRUISE.0` value (JSON string or already-parsed list).
- Output: `{map_index: {point_id: {"cycles": int, "auto_capture": bool}}}`.
- Tolerances (no raises): non-JSON / wrong shape → `{}`; `version:-1` or empty `settings` →
  that map contributes nothing; per-point entry missing `num`/`ap` → skip; **non-integer
  settings key** (the un-disambiguated `"1,0"` comma-key) → skip + `LOGGER.debug` (parked
  open-question in `inventory.yaml § CRUISED`, not blocking).
- Lives beside the other cloud-JSON parsers; named `parse_*` per the decoder-naming convention.

### 2. Read wiring (coordinator → sensor + camera)
- The map / `getDeviceData` fetch path extracts `CRUISE.0` and runs `parse_cruise_config`,
  storing the result on the coordinator keyed by map (alongside the existing cruise-points data).
- **Patrol-points sensor** (`sensor.dreame_a2_mower_map_N_patrol_points`): fill each item's
  `cycles` / `auto_capture` (currently `null`) from the parsed config for that map+point; leave
  `null` when no entry exists.
- **Camera `editable_objects`** (`camera/map.py`): each patrol entry gains `cycles` +
  `auto_capture` fields (the editor's read source).
- A point with no `CRUISE.0` entry yet (e.g. freshly created, or `CRUISE.0` not present) shows
  the defaults **cycles=1 / auto_capture=false** so the panel is always populated.

### 3. Write path (coordinator + service)
- `coordinator.write_patrol_point_config(*, map_id, point_id, cycles, auto_capture) -> WriteResult`:
  resolves `map_id → idx` (the map's index, same `idx` used by `CRUISED`/`PRE`), builds
  `value=[-1, int(point_id), 1 if auto_capture else 0, int(cycles)]`, and issues the
  `action s2.50 {m:'s', t:'CRUISED', d:{idx, value}}` CFG write via the established CFG-write
  transport (`protocol/cfg_action.py`-style helper). Validates `cycles ∈ {1,2,3}`.
- **Optimistic update:** on success, update the coordinator's parsed-config cache for that
  map+point so the sensor + `editable_objects` reflect the new value immediately (the `CRUISE.0`
  read lags until the next fetch). Broadcast so the card re-reads.
- Service `set_patrol_point_config` in `services.yaml` (mirrors `create_patrol_point`):
  fields `map_id`, `point_id`, `cycles` (selector 1/2/3), `auto_capture` (bool).

### 4. Editor card UI (`dreame-map-editor-card.js`)
- When the selected object is a patrol point (existing/committed — has a real id), render an
  inline panel below the map, pre-filled from the point's `cycles` / `auto_capture`:
  ```
  ┌─ Patrol point <id> ───────────┐
  │ Cycles:        [1] [2] (3)    │   segmented control
  │ Auto-capture:  ( ●)  on       │   toggle
  └───────────────────────────────┘
  ```
- On change → call the `set_patrol_point_config` service with `map_id` + `point_id` + the new
  value; optimistically update the card's local draft so the control reflects the change at once.
- Geometry editing (place/move/delete) is unchanged; the panel is independent and writes
  immediately (no Save dependency). Hidden for an uncommitted draft point (no real id yet).

---

## Data flow

```
getDeviceData ──► CRUISE.0 (JSON string)
                     │  parse_cruise_config()
                     ▼
        {map_idx: {point_id: {cycles, auto_capture}}}   (coordinator cache)
              │                         │
              ▼                         ▼
   patrol-points sensor items     camera editable_objects (patrol entries)
                                        │
                                        ▼
                              map-editor card inline panel
                                        │ user changes cycles / auto-capture
                                        ▼
                         service set_patrol_point_config
                                        ▼
            coordinator.write_patrol_point_config  ──►  CRUISED CFG write
                                        │
                                        ▼ optimistic cache update + broadcast
                              (panel + sensor reflect new value)
```

## Error handling
- Parser never raises (all tolerances above → partial/empty result).
- Write: invalid `cycles` (∉{1,2,3}) → `ServiceValidationError`. Cloud/transport failure →
  surfaced via the existing `raise_for_write_result` path; the optimistic update only applies on
  success.
- Card: panel only renders for a point with a real id; service-call failure leaves the prior
  value (no optimistic apply on error).

## Risks to verify on the live mower (mower is live again)
1. **Map-active requirement:** a `CRUISED` write may require the target map to be active first
   (PRE does). If so, gate the write (or auto-activate). Verify with a write to a non-active map.
2. **`"1,0"` comma-key:** parser tolerates it (skip+log); a follow-up capture (set one distinct
   point, diff which key changes) disambiguates it — tracked as an inventory open-question, not a
   blocker here.
3. **New-point `CRUISE.0` population:** confirm a freshly-created point appears in `CRUISE.0` at
   `{num:1, ap:false}` (device default) rather than absent; either way the read defaults to 1/off.

## Testing
- **Parser** (pure unit): array→dict; `version:-1` / empty `settings` skipped; missing `num`/`ap`
  skipped; `"1,0"` key tolerated; non-JSON → `{}`; multi-map indexing.
- **Builder** (pure unit): `map_id→idx`, `value` order `[-1, id, auto(0/1), cycles]`, cycles
  validation.
- **Sensor**: item `cycles`/`auto_capture` populated from a fixture config; `null` when absent.
- **Camera**: `editable_objects` patrol entries carry `cycles`/`auto_capture`.
- **Service**: `set_patrol_point_config` → `write_patrol_point_config` called with the right args;
  optimistic cache update applied on success only.
- **Card** (node render-harness, per the www-test pattern): selecting a patrol point renders the
  panel pre-filled; a cycles/auto change produces the expected service-call payload.
- Existing `edit_map` / patrol-geometry / patrol-points-sensor tests remain green.

## Out of scope (v1)
- Setting attributes on an uncommitted draft point (deferred-write/id-correlation).
- Disambiguating the `"1,0"` comma-key and the `value[0]=-1` sentinel (inventory open-questions).
- Any change to geometry editing or the patrol-run services (`start_point_patrol`, `o=111`).

## Lifecycle
This spec + its plan move to `OLD/ha-dreame-a2-mower-docs/superpowers/` when the feature ships
(per CLAUDE.md documentation lifecycle).
