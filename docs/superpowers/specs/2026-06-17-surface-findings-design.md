# Spec — Surface the 2026-06-13→17 protocol findings

**Date:** 2026-06-17
**Status:** approved design, pre-plan
**Base version:** 1.0.29a3

## Background

The 2026-06-13→17 commit run was almost entirely `inventory.yaml` knowledge
hardening (closing open questions, retracting debunked claims, the siid:4 purge).
Most of it needs **no** code change — in several cases the code was already correct
ahead of the docs (OTA entity, `PAUSED_HOLD=4` state, all siid:4 props confirmed
absent and already capability-gated).

Six findings, however, are not yet reflected in the integration or dashboard. This
spec covers surfacing those six. Each is independent; they are bundled into one
spec/plan because four are small and share the same CI-coupling chores.

## Goals

Surface, in the integration and (where user-facing) the dashboard:

1. **Create-shape type table fix** — the shipped create-shape service sends wrong
   shape type ids.
2. **Per-zone mow progress** — `s2p56` carries per-zone progress; only the first
   zone's stage is consumed today.
3. **`s2p57` low-battery self-shutdown alert** — newly seen on the wire; unhandled.
4. **Turning Method select** — new `PRE[19]` field (post-0625 OTA); no entity.
5. **Update Station Location button** — new `o=19` routed action; no entity.
6. **`s2p2=72` authoritative text** — cloud-labelled fire now captured; the static
   fallback text is the borrowed (wrong) slug.

## Non-goals

- The broader reserved **Alert-tier event surface** TODO (lifted/tilted/stuck/
  bumper/emergency-stop migration/`CONF_NOTIFY`). Only the single `s2p57` event is
  in scope; the rest stays in `docs/TODO.md`.
- `PRE[20]` (cutterPositionHeight) entity, `AUTO_TIMEZONE`, `FBD_NTYPE` — out of
  scope (no UI requested / codes undecoded).
- Live verification that `PRE[19]` writes are firmware-honored (deferred, same
  status as the other PRE selects).

---

## Item 1 — Fix create-shape type table

**File:** `custom_components/dreame_a2_mower/protocol/map_edit_shapes.py`

The `SHAPE_TYPE` map is wrong/incomplete. Wire-confirmed truth (inventory.yaml
verification 2026-06-17, `o=215` draws in app 2.5.8.1):

```
9=Square  11=Circle(parametric center+radius)  13=Heart  14=Triangle
15=Teardrop  16=Mushroom  17=Cloud  18=Rainbow  19=Moon  20=Star
21=Butterfly  22=Blob  23=Tree  24=Carrot
10 & 12 = UNUSED (firmware ACKs but renders nothing)
```

Current code has `"circle": 12` (12 is now **unused**; circle is **11**) and is
missing `19–24`. `teardrop=15`/`mushroom=16` were `[UNVERIFIED]`, now confirmed.

**Change:**
- Correct `circle 12→11`.
- Add `moon=19, star=20, butterfly=21, blob=22, tree=23, carrot=24`.
- Remove the `[UNVERIFIED]` comments for teardrop/mushroom.
- Reject `10`/`12` if passed (known-unused).
- Update the create-shape service `options`/docs and `entity-inventory.yaml` so the
  service advertises the full confirmed shape set.

**Tests:** extend `tests/protocol/test_map_edit_shapes.py` — every confirmed name
maps to its confirmed id; `circle→11`; unknown/unused names rejected.

**Risk:** low; pure mapping fix. This is a correctness bug in the shipped
v1.0.25a7 service (drawing a "circle" today sends a no-render type).

---

## Item 2 — Per-zone mow progress sensor

**Source:** `s2p56` (`task_state`). Full shape is `{status: [[zone_id, stage], …]}`,
one pair per zone/target. Stage enum: `-1 = queued`, `0 = active`, `2 = done`.
Current zone = the entry whose `stage == 0`. `zone_id` joins to
`MAP.*.mowingAreas` ids. Pushed on task-state changes (not in polls).
(FINDING-s2p56-per-zone-status-2026-06-16; verified on a 2-zone Map2 all-area mow.)

**Today:** `property_mapping.py (2,56)` extracts only `status[0][-1]` →
`task_state_code`. That stays unchanged (it remains the single overall stage).

**Zone/map names come from the wire.** The app lets the user name maps and zones,
and those names are already decoded: `map_decoder.py:462`
(`zdata.get("name", f"Zone {zone_id}")` → `MowingZone.name`) and `:929`
(`cloud_response.get("name")` → map name). So the join uses the **decoded
`MowingZone.name`** (the user's app-assigned name), with the synthetic `"Zone {id}"`
only as a fallback when the wire genuinely carries no name. The same applies to the
map name shown in the card (use the decoded map name, fallback `"Map {N+1}"`).
**Constraint:** wire names drive *display* (friendly names, card titles, sensor
attributes) only — entity_ids/`unique_id`s MUST stay in the
`dreame_a2_mower_map_N_*` namespace per the per-map naming convention (renaming
entity_ids to custom names would break the namespace + orphan the registry).

**Change:**
- New coordinator-derived field (e.g. `zone_progress`) holding the parsed list of
  `{id, name, status}`, where `status ∈ {queued, active, done}` and `name` is the
  decoded `MowingZone.name` (wire/app name; synthetic fallback only when absent).
  Built in the property-apply / state path that already sees the raw `s2p56` dict.
- New `sensor.dreame_a2_mower_zone_progress`:
  - **state:** `"Mowing zone N of M"` where N = 1-based index of the active zone,
    M = total; `"Idle"` (or `None`) when no active task / empty status; degrades to
    a single-zone string when only one zone.
  - **attributes:** `current_zone_id`, `current_zone_name` (wire name),
    `zones: [{id, name, status}]`.
- Single-zone and empty-array inputs must not error.

**Dashboard:** one card on the mower dashboard rendering the `zones` attribute
(markdown or entities card), placed near the existing task/area cards.

**Tests:** extractor unit tests for the 2-zone progression in the finding
(`[[1,0],[2,-1]] → [[1,0],[2,0]] → [[1,2],[2,0]]`), single-zone, empty, and
3-element-entry inputs; sensor state/attribute snapshot.

**Risk:** medium — new entity + new coordinator field + dashboard. No change to the
existing `task_state_code` path.

---

## Item 3 — `s2p57` low-battery self-shutdown alert

**Source:** `s2p57` (`robot_shutdown_trigger`). First seen on the wire
2026-06-14 as a standalone `properties_changed` push carrying bare scalar
`value: 1` (NOT the apk-hypothesized dict). The confirmed cause for this
occurrence is a **low-battery firmware self-shutdown** (mower stranded, battery
hit ~5%, firmware shut down protectively). Other triggers remain unconfirmed.

**Change:**
- Add `(2, 57)` to `property_mapping.py` as a bare-int field.
- Add a new lifecycle event type constant `EVENT_TYPE_SELF_SHUTDOWN`
  (slug e.g. `self_shutdown`) to `const.py` `LIFECYCLE_EVENT_TYPES`. (The reserved
  `alert` event entity was renamed to `notification` and is cloud-`s2p2`-sourced;
  `s2p57` is device telemetry, so it belongs on the **lifecycle** event entity,
  which also auto-exposes it as a device trigger via `device_trigger.py`.)
- On `s2p57 == 1`, fire `self_shutdown` on the lifecycle event entity, payload
  carrying at least the raw value + a `reason` of `low_battery` (the only confirmed
  cause; documented as such).
- Add the slug to `translations/en.json` (and `strings.json` if lifecycle slugs are
  listed there).

**Tests:** firing test (push `s2p57=1` → lifecycle event fires once with the slug);
non-1 / repeat-value behaviour documented.

**Risk:** low-medium — one event type + one mapping. No emergency_stop migration.

---

## Item 4 — Turning Method select (`PRE[19]`)

**Source:** `PRE[19]` — appeared on the 0550→0625 OTA (PRE grew 19→21 ints,
`[19]`/`[20]` appended; indices 0–18 unchanged). `PRE[19] = Turning Method`:
`0 = Efficient`, `1 = Lawn-Care` (= SETTINGS `steeringMode`). App 2.5.8.1 added a
"Turning Method Settings" sub-page. (inventory.yaml:5663, :5716.)

**Change:**
- New per-map select mirroring `DreameA2PerMapMowingDirectionModeSelect`
  (`entities/select/map_settings.py`), which writes a single PRE index via the
  existing `set_pre(map_id, pre_index, pre_value)` helper. Use `pre_index=19`.
  - `unique_suffix`/key: `map_N_settings_turning_method`
    (per-map naming convention — must keep the `dreame_a2_mower_map_N_*` namespace).
  - options: `Efficient` (0) / `Lawn-Care` (1).
  - `control_mode` via `resolve_control_mode(platform="select",
    key="map_N_settings_turning_method")` — ships **writable**, same status as its
    PRE siblings (firmware honoring unverified, not padlocked).
- **Firmware guard:** on fw with a 19-int PRE (≤0550) there is no `[19]`; the
  current value read must handle a short array → entity reports unknown/unavailable
  rather than erroring. The RMW write path already fetches the full array and
  patches one index, so a 21-int round-trip is safe.

**Tests:** option↔value mapping; write builds `set_pre(..., 19, idx)`; short-array
(19-int) read does not raise; current-value read from a 21-int PRE.

**Risk:** low — follows an established, tested pattern.

---

## Item 5 — Update Station Location button (`o=19`)

**Source:** `o=19` — parameterless routed action `{m:'a', p:0, o:19}` (r=0), new in
app 2.5.8.1 ("Update station location"). Makes the mower re-localize its dock
(undock + LiDAR reorient spin, no coordinates sent). Result reads back via
`m:g DOCK` (x/y/yaw); `s1p51` signals the pose change. (inventory.yaml:3657, :3691.)

**Change:**
- New `DreameA2UpdateStationLocationButton` in `button.py` (subclass of
  `_DreameA2ActionButton`), `unique_suffix=update_station_location`, sending the
  `o=19` routed action with `p=0` via the existing `routed_action`/`call_action_op`
  path. Add the write to `_writes` as needed.
- The existing `dock_x`/`dock_y`/`dock_yaw` sensors already read `DOCK`; the button
  triggers a refresh so the re-localized pose surfaces. No new sensor.
- `control_mode`: writable (this is a real, accepted action — unlike the
  padlocked lock_bot/generate_3dmap no-ops).

**Dashboard:** add the button near the existing action buttons.

**Tests:** button press issues `o=19, p=0`; control-honesty wiring test passes.

**Risk:** low.

---

## Item 6 — `s2p2=72` authoritative text + `71` finalize

**Finding:** two stored notifications correlate to the second against the probe-log
`s2p2` fires on 2026-06-17:

| Cloud notification text | Time | Probe-log fire |
|---|---|---|
| "The robot is on standby outside the station for too long. Automatically returning to the station." | 11:28 | `11:28:49 → 71` (s2p1 2→5 RETURNING) |
| "Task paused for too long. Automatically returning to the station to wait." | 12:38 | `12:38:22 → 72` (s2p1 3 PAUSED→2→5 RETURNING) |

This is the cloud-labelled `72` fire the confidence gate was waiting for. `72` is
already in `error_codes.py` (added 2026-06-17) but with the **borrowed** dreame-mower
text "Returning to dock after pause timeout".

**Change:**
- `mower/error_codes.py`: correct `72` text to the cloud-authoritative
  **"Task paused for too long. Automatically returning to the station to wait."**
- Rename `S2P2_EVENT_TYPES[72]` slug `return_after_pause_timeout` →
  `paused_too_long_returning` (match the confirmed cloud text); update ALL consumers
  — `strings.json`, `translations/en.json`, `device_trigger.py`, `logbook.py`, and
  any tests referencing the old slug. (Pre-production, no backcompat needed.)
- Confirm `71`'s static text matches the now-correlated standby text; adjust if
  drifted.
- `inventory.yaml`: record both MQTT↔cloud correlations; promote `72`
  `observed_values` `partial→confirmed`/`verified`; drop the now-stale "kept OUT of
  error_codes.py until a cloud-labelled fire is captured" note.

**Note:** the user-visible notification text already comes from the cloud
`localizationContents` at runtime (the `_NotificationsMixin`), so this item aligns
the **static fallback / logbook / device-trigger slug** and the inventory record —
not the live notification string.

**Tests:** map lookups for `72`/`71` return the corrected text/slug; any slug-rename
consumers updated.

**Risk:** low — string/slug + doc alignment.

---

## Cross-cutting CI couplings (apply to items 2, 3, 4, 5)

Every new entity/event/slug in this project trips known CI gates. Each item's plan
tasks MUST include the matching chore or CI goes red:

- **`tools/state_machine/state_machine_audit_expectations.yaml`** — new sensors/
  selects/buttons need rows (idle + reboot yellows); attribute-only MowerState
  fields need `_KNOWN_ATTRIBUTE_SURFACED_FIELDS`.
- **`entity-inventory.yaml`** — CI-gated entity SoT; new entities need entries
  (mark `presumed` until live-verified).
- **control-honesty** (`CONTROL_MODES` + inventory row) — the writable select
  (#4) and button (#5) need control-mode entries; `test_control_entities_wired`
  guards.
- **wire-census** (`inventory.yaml` / `tools/wire_census.py`) — new wire values
  (`s2p57=1`, `s2p56` per-zone semantics) must be accounted for.
- **canonical doc** — regenerate `docs/research/inventory/generated/g2408-canonical.md`
  via `inventory_gen.py` after inventory edits (CI only validates schema, not the
  rendered doc).

## Dashboard (items 2, 4, 5)

Add to `dashboards/mower/dashboard.yaml`: per-zone progress card (#2), Turning
Method select (#4), Update Station Location button (#5). Deploy via the SCP
procedure to `/config/dashboards/mower/` (HACS does not ship dashboards); back up
first; browser-reload, no HA restart.

## Release

Per project process: bump version (watch the HACS digit-boundary ladder — from
`1.0.29a3`, the next alpha is fine until a digit grows), `tools/release/release.sh`
(bump + tag + push + GitHub Release + HACS refresh). A GitHub **Release** is
required — HACS reads Releases, not commits/tags.

## Testing strategy

- Unit tests per item (above), run in the vanilla stubbed-HA venv
  (`.venv-vanilla`, py3.13; baseline 1591 passed/4 skipped).
- Full suite green incl. the CI-coupling audit tests (`test_audit_exit_zero_when_no_reds`,
  `test_control_entities_wired`, wire-census, entity-inventory, inventory schema).
- Live deploy + A/B verify on the running HA (per project resume doc): per-zone
  sensor on the next multi-zone mow; Turning Method write; Update Station button;
  `s2p57`/`s2p2=72` are event-driven (validate opportunistically).
