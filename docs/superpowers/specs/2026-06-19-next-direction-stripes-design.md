# Authoritative next-direction stripes — design

**Date:** 2026-06-19 · **Status:** approved, implementing.
**Source finding:** `artifacts/g2408-plugin-extract/FINDING-mowing-direction-next-2026-06-19.md`.

## Problem

The between-sessions live-map stripe preview (`BackgroundMode.STRIPES`, idle
ALL_AREAS/ZONE) currently draws stripes at an angle **inferred** from the last
session's track: `next_direction(last_all_area_mow_direction_deg[map_id], mode)`
applies a client-side `+45°/+90°` rotation. The finding proves this is wrong:

- The device **stores** the next-run angle in the cloud field `mowingDirection`
  and **rewrites it after each mow** (checkerboard rotation is device-side,
  ~90°/mow). `[app-observed 2026-06-19 + cloud SETTINGS pull 2026-06-19]`
- The official app draws stripes at the **stored** angle with **no** parity /
  rotation math, pixel angle `= 180 − mowingDirection` (`cvtMowingDirection`).
- `mowingDirectionMode` enum (apk): `0=NONE(single) / 1=ROTATION / 2=CHEESSBOARD
  (checkerboard)` `[apk:g2408-plugin-ext1423]` — NOT the
  `Striped/Crisscross/Chequerboard` the renderer's comments claim.

The integration already ingests the field as `settings_mowing_direction` (the
active map's value, `coordinator/_cloud_state.py:235`) but the renderer ignores
it.

## Change

### 1. Render (`map_render/main_view.py`)
`_render_pre_start_with_stripes`: replace the inferred angle with
```
sd = getattr(state, "settings_mowing_direction", None)
if sd is None: return render_base_map(map_data, palette, lawn_mode="dark")  # no guess
angle = (180 - int(sd)) % 180
```
Feed `angle` into the unchanged `compute_stripe_overlay → render_base_map`
pipeline, so the existing live→pixel handling (flip + midline reflection)
applies uniformly. `settings_mowing_direction_mode` stays metadata only — mode
does NOT change rendering (the app draws single-direction stripes at the stored
angle regardless). Drop the `next_direction_fn` / `last_all_area_mow_direction_deg`
parameters.

**Frame convention (owner-observed 2026-06-19, post-release a7):** our rendered
map's display angle reads **0°=left, 90°=up, 180°=right** on the pixel-map axes
(NOT dock/mower axes). That is the left↔right mirror of the app's
`cvtMowingDirection` (`180−value`) frame, so the overlay input is
`180 − (180 − value) = value` — the two flips cancel and the renderer feeds the
stored `settings_mowing_direction` **directly** (in pixel-map axes). The initial
`180−value` shipped in a7 looked wrong on the lawn; corrected to `value` for a8.

### 2. Retire the inference chain (full removal)
It exists solely to feed the removed `next_direction`:
- `map_render/direction.py`: delete `next_direction`, `infer_mow_direction`,
  `MOWING_PATTERN_*` (whole module → the file becomes empty/removed; update the
  `_render_direction.py` re-export shim accordingly).
- `MowerState.last_all_area_mow_direction_deg` field + its population in
  `coordinator/_lidar_oss.py` and persist/restore in `coordinator/_session.py`
  + `coordinator/_restore_merge.py`.
- Tests referencing them (`tests/map_render/test_render_base.py`,
  `tests/unit/test_mower_state_last_direction.py`).

No migration code (single-user; old archives' extra key is ignored — repo's
no-migration rule). Net: removes one orphan MowerState field.

### 3. Inventory / fact-discipline
- `inventory.yaml`: `mowingDirectionMode` enum `0=NONE/1=ROTATION/2=CHEESSBOARD`
  `[apk:g2408-plugin-ext1423]`; `mowingDirection` is the device-maintained
  **next-run** angle (rewritten per mow), display `180−value`
  `[app-observed 2026-06-19 + cloud SETTINGS pull 2026-06-19]`. Archive any
  superseded "inferred next direction" claim to
  `OLD/.../inventory-history/`.
- Regenerate `g2408-canonical.md` after the inventory edit.

### 4. Testing (TDD)
- New `map_render` test: STRIPES render passes `180 − settings_mowing_direction`
  to `compute_stripe_overlay`; plain dark base when the field is `None`.
- Update/remove the `last_all_area_mow_direction_deg` tests.
- Regenerate the golden PNG (`DREAME_REGEN_GOLDEN=1`).
- Full suite + state-machine audit + inventory schema all green.

### 5. Live verification + ship
Deploy to HA, idle in all-areas, compare the live-map stripe angle to the app.
Fix the formula if off by 90/180; then cut a release.

### 6. Follow-ons from live verification (a7→a9)
Live eyeball surfaced two more defects, fixed in the same line of work:

- **a8 — frame:** the `180−value` convention shipped in a7 was mirrored; the
  render frame is `0°=left/90°=up/180°=right` on the pixel-map axes, so the
  overlay input is the stored value directly. (§1 updated.)
- **a9 — two bugs:**
  1. **All zones striped.** `_render_pre_start_with_stripes` only striped
     `mowing_zones[0]`; a map's other zones rendered solid. Now builds one
     overlay per zone (same angle + canvas-origin band phase) and composites.
  2. **SETTINGS model misread (root cause of "map2 shows horizontal").** A live
     `[probe:settings_dump@2026-06-19]` showed the SETTINGS batch is
     **top-level index = map**, inner `"0"` = the map's general setting — NOT
     the documented "entry0=user-saved / entry1=firmware-mirror, inner=map id".
     The integration read map2's direction from map1's zone-1 slot (180→
     horizontal) instead of map2's general (118→62°). Fixed `parse_settings_batch`
     (reads) + `write_setting` (writes target only the map's `"0"` slot; the old
     write-every-entry clobbered other maps). Fixes ALL per-map settings for
     map 2+, not just stripes. Old claim archived to
     `OLD/.../inventory-history/cfg_individual.md`. Read-back verified live
     (`by_map_id_canonical[1].mowingDirection == 118`).
