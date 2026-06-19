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

**Frame convention:** `180 − value` is the first cut at the device→renderer
mapping. No calibration knob. If a live A/B against the Dreame app shows a
90°/180° offset, adjust the formula constant and re-release. `[UNVERIFIED until
live A/B]`

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
