# Phase A2 — PRE General-Mode per-map writable settings (design)

**Date:** 2026-06-10
**Status:** design, awaiting user review → writing-plans
**Phase:** A2 of the app-integration roadmap (`docs/research/app-integration-roadmap.md`).
**Predecessors:** Phase 0 (knowledge capture), Phase A1 (CFG single-key writable settings, shipped v1.0.24a9).

## Context

The per-map **General-Mode** settings (mowing efficiency/height/direction, edge
toggles, obstacle-avoidance, AI recognition, EdgeMaster) are currently read-only
in the integration. The 2026-06-09 app-MITM capture shows the Dreame app writes
two stores on a General-Mode change:

- **PRE** (s2.50 routed CFG `{m:"s",t:"PRE",d:[…]}`) — the array the firmware
  actually reads while mowing. Scoped per map/zone: the SET embeds map at array
  index `[1]` and zone/region at `[2]`; the GET passes them as named args
  `{m:"g",t:"PRE",d:{idx:<map>,region:<zone>}}`. 56 PRE writes captured.
- **SETTINGS** (iotuserdata KV) — the *full* per-map settings record
  (`{mode, settings:{"<region>":{…all fields…}}}`), including fields not in PRE.
  2 writes captured.

This explains the integration's `_C` ("read-only-confirmed") verdict on these
controls: the existing `write_settings` writes only SETTINGS (the cloud record),
but the firmware reads PRE — so a SETTINGS-only write changes the cloud cache
without changing mower behavior. The app keeps both in sync.

It also debunks the `r=-3` "no PRE setter on g2408" claim: the integration's
`cfg_action.set_pre` sends `{m:"s",t:"PRE",d:{value:[…]}}` (array wrapped under
`value`); the app sends `{m:"s",t:"PRE",d:[…]}` (bare array). `r=-3` was a
wrong-envelope artifact, not a firmware limitation.

**Honesty basis (per the user):** the app capture is the wire verification.
Older "no PRE setter" claims are wrong-envelope artifacts and are retracted here.

## Goal & scope

**Goal:** make the per-map General-Mode settings change the mower, by writing
**PRE** (device, app's scoped envelope) and **SETTINGS** (the cloud record the
entities read), and flip the controls to `DEVICE_WRITABLE`.

**In scope — 14 controls (confirmed PRE index):**
- selects: `mowing_efficiency` (PRE[3]), `mowing_direction` (PRE[6]),
  `mowing_direction_mode` (PRE[5])
- numbers: `mowing_height` (PRE[4]), `obstacle_avoidance_height` (PRE[13]),
  `obstacle_avoidance_distance` (PRE[14])
- switches: `automatic_edge_mowing` (PRE[7]), `safe_edge_mowing` (PRE[16]),
  `obstacle_avoidance_on_edges` (PRE[9]), `lidar_obstacle_recognition` (PRE[12]),
  `edgemaster` (PRE[10]), `ai_recognition_humans/animals/objects` (PRE[15] bits
  0/1/2)

**Deferred to a TODO (SETTINGS-only, no PRE index, device-effectiveness
unverified):** `cutterPosition`, `cutterPositionHeight`, `edgeMowingNum`,
`edgeMowingWalkMode`, `obstacleAvoidanceSensitivity`, `edgeCuttingAttachment`.
Recorded in `knowledge-gaps.md` + an inventory open-question; revisit later.

**Non-goals:** the A2 write does not change the cloud transport beyond the
`set_pre` envelope fix; no new per-map PRE polling timer (scoped fresh read on
write is sufficient); no re-sourcing of entity reads (they keep reading SETTINGS,
except `edgemaster` which keeps reading the s6p2 PRE shadow).

## §1 Read-source split (load-bearing)

- **13 SETTINGS-reading controls** → **dual-write** PRE (device) + SETTINGS (so
  the entity's read reflects the change): mowing_efficiency, mowing_height,
  mowing_direction, mowing_direction_mode, automatic_edge_mowing,
  safe_edge_mowing, obstacle_avoidance_on_edges, lidar_obstacle_recognition,
  obstacle_avoidance_height, obstacle_avoidance_distance,
  ai_recognition_humans/animals/objects.
- **1 PRE-shadow-reading control** → **PRE-only** write: `edgemaster` reads
  `state_machine.snapshot().pre_shadow_by_map_id[map_id]["edgemaster"]` (fed by
  s6p2 MQTT pushes). No SETTINGS field exists for it. After the PRE write the
  device's s6p2 push refreshes the shadow; the optimistic update bridges the
  latency.

## §2 Architecture — the fix + three new pieces

1. **Fix `protocol/cfg_action.py:set_pre`** — emit `{"m":"s","t":"PRE","d":
   pre_array}` (bare array), not `{"d":{"value":pre_array}}`. The load-bearing
   change. Global, but no live caller succeeds today, so no regression.

2. **Scoped PRE read** — new `cloud_client.get_pre(idx, region)` →
   `{"m":"g","t":"PRE","d":{"idx":idx,"region":region}}`, returns the array for
   that map+zone. `cloud_state.cfg["PRE"]` holds only one map's array, so per-map
   RMW needs this fresh scoped read.

3. **Pure PRE builders** (extend `protocol/cfg_payloads.py`, unit-tested against
   the capture):
   - `apply_pre(current_array, *, map_idx, index, value) -> list | None` —
     returns the write array with `[0]=0` (version write-byte), `[1]=map_idx`,
     `[2]=0` (General region), `[index]=value`, all other slots preserved.
   - `apply_pre_ai_bit(current_array, *, map_idx, bit, on) -> list | None` —
     RMW one bit of PRE[15].
   Both return `None` when the base array is missing/too short (caller reverts).

4. **Coordinator dual-write** — `write_map_general_setting(map_id, *, pre_index,
   pre_value, settings_field=None, settings_value=None)`:
   1. `get_pre(idx=map_id, region=0)` — fresh scoped read.
   2. `apply_pre(...)` (or `apply_pre_ai_bit`) → `set_pre(array)` (device). On
      failure (`r!=0` / None base) → revert optimistic, notify, STOP (no SETTINGS
      write).
   3. On PRE success, if `settings_field` given → `write_settings(map_id,
      settings_field, settings_value)` (cloud record). A SETTINGS failure here is
      logged but does NOT revert the device change (next poll reconciles).
   4. Optimistic local update + revert-on-PRE-failure.

   `edgemaster` calls this with `settings_field=None` (PRE-only).

**map_id ↔ PRE idx:** assumed equal (capture showed idx 0/1 for the two maps);
the build confirms against the cloud `mapIndex`.

## §3 Per-control mapping

| entity | reads | PRE idx | SETTINGS field | value transform |
|---|---|---|---|---|
| mowing_efficiency | SETTINGS.efficientMode | 3 | efficientMode | 0/1 passthrough |
| mowing_height | SETTINGS.mowingHeight | 4 | mowingHeight | SETTINGS = cm float; **PRE = round(cm×10)** |
| mowing_direction_mode | SETTINGS.mowingDirectionMode | 5 | mowingDirectionMode | enum passthrough — *build verifies PRE[5] order == SETTINGS order* |
| mowing_direction | SETTINGS.mowingDirection | 6 | mowingDirection | degrees passthrough (idx×90) |
| automatic_edge_mowing | SETTINGS.edgeMowingAuto | 7 | edgeMowingAuto | 0/1 |
| obstacle_avoidance_on_edges | SETTINGS.edgeMowingObstacleAvoidance | 9 | edgeMowingObstacleAvoidance | 0/1 |
| edgemaster | PRE shadow (s6p2) | 10 | none — PRE-only | 0/1 |
| lidar_obstacle_recognition | SETTINGS.obstacleAvoidanceEnabled | 12 | obstacleAvoidanceEnabled | 0/1 |
| obstacle_avoidance_height | SETTINGS.obstacleAvoidanceHeight | 13 | obstacleAvoidanceHeight | passthrough (5/10/15/20) |
| obstacle_avoidance_distance | SETTINGS.obstacleAvoidanceDistance | 14 | obstacleAvoidanceDistance | passthrough (10/15/20) |
| safe_edge_mowing | SETTINGS.edgeMowingSafe | 16 | edgeMowingSafe | 0/1 |
| ai_recognition_humans | SETTINGS.obstacleAvoidanceAi bit0 | 15 (bit0) | obstacleAvoidanceAi | bitmask RMW |
| ai_recognition_animals | SETTINGS.obstacleAvoidanceAi bit1 | 15 (bit1) | obstacleAvoidanceAi | bitmask RMW |
| ai_recognition_objects | SETTINGS.obstacleAvoidanceAi bit2 | 15 (bit2) | obstacleAvoidanceAi | bitmask RMW |

The SETTINGS half already writes correct values in the entities today; A2 computes
the PRE value (height ×10, AI bitmask, rest passthrough) and writes it alongside.

## §4 Verdict flip & fact-discipline

- **`control_honesty.py`:** flip the 14 controls (`_C`/`_N` → `_W`), mirrored into
  `entity-inventory.yaml` `control_mode` (code-sync test enforces both).
- **`inventory.yaml`:** **retract the `r=-3` "no PRE setter on g2408" claim
  verbatim** (wrong-envelope artifact); record the correct PRE write envelope
  (bare array, scoped via `[1]=idx`/`[2]=region`; GET via `{idx,region}` named
  args) as `verified` (`app-mitm:2026-06-09-settings-sweep`); record the
  PRE↔SETTINGS dual-store relationship.
- **`entity-inventory.yaml`:** supersede each control's Phase-0 "captured, not
  wired" record with "wired + writable via PRE (+SETTINGS) RMW."
- **TODO:** the SETTINGS-only fields → `knowledge-gaps.md` open gap + inventory
  open-question.

## §5 Testing (TDD)

- Extend `tests/fixtures/cfg_envelopes_2026-06-09.json` with PRE read arrays, the
  scoped get args (`{idx,region}`), and the bare-array set shape.
- **Pure builder tests** (`apply_pre` / `apply_pre_ai_bit`): RMW one index
  preserves the rest; `[0]=0`/`[1]=idx`/`[2]=0`; AI bit-set; None-base → None.
  Assert against captured arrays.
- **`set_pre` envelope test:** emitted payload is `{"m":"s","t":"PRE","d":[…]}`
  (bare array) — guards the bug fix.
- **`get_pre` test:** emits `{"m":"g","t":"PRE","d":{"idx":M,"region":0}}`.
- **Coordinator `write_map_general_setting` test:** scoped get → set_pre with the
  right array → write_settings with the right field/value; PRE-failure → no
  SETTINGS write + revert; SETTINGS-failure → device change kept; edgemaster path
  writes PRE only (no SETTINGS).
- **Entity-handler tests** per platform (select/number/switch); **control_mode
  code-sync**; full suite green.

## §6 Risks & edge cases

- **`set_pre` envelope fix is global** — no live caller succeeds today (always
  r=-3), so no regression; this fix is the point.
- **map_id ↔ PRE idx** — build confirms against cloud `mapIndex`.
- **mowing_height unit** (PRE ×10 vs SETTINGS float) — explicit transform,
  unit-tested.
- **mowing_direction_mode enum order** PRE[5] vs SETTINGS — build verifies; add a
  transform if they differ.
- **edgemaster** was `_N` (write-no-effect under the *wrong* envelope) — flipped
  per "capture is truth"; the s6p2 shadow + optimistic update reflect it; if the
  device still ignores PRE[10], the shadow simply won't update (visible, not
  silent).
- **Dual-write partial failure** — PRE first (device is what matters); a
  subsequent SETTINGS-record failure is logged but does NOT revert the device.

## Out-of-scope follow-ups (TODO, not built here)

- SETTINGS-only per-map fields (cutterPosition, cutterPositionHeight,
  edgeMowingNum, edgeMowingWalkMode, obstacleAvoidanceSensitivity,
  edgeCuttingAttachment) — confirm device-effectiveness, then wire.
- Per-zone (Custom Mode) PRE writes (`region!=0` + `PREP` enable) — A2 covers
  General Mode (region 0) only.
- A per-map PRE polling timer (only if the scoped-read-on-write proves
  insufficient).
