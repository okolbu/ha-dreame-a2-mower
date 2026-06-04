# Surface & launch point patrols (cruise points) — design (2026-06-04)

## Problem

The g2408 supports **point patrol** (op=107, `startCruisePoint`): the mower visits a
user-placed list of map points, blades-up. Points are pre-defined in the app
("place points") then a subset is selected to launch a patrol. The integration
currently has no surface for any of this — patrols are only typed post-hoc.

Live cloud investigation (2026-06-04) established the facts this design rests on:

- **Patrol points live in the MAP blob key `cruisePoints`** (sibling of
  `cleanPoints`), `type=8` (maintenance points are `type=6`). Entry shape:
  `[id, {id, type:8, shapeType:5, path:[{x,y}], time:60, etime:60}]`. We already
  fetch this (`cloud_client.fetch_map`); confirmed populated + cloud-relayed
  (synced across app instances).
- **The wire already takes lists.** Routed actions are list-shaped:
  point-patrol `{"point":[ids]}` (op=107), zone `{"region":[ids]}` (102), spot
  `{"area":[ids]}` (103), edge-patrol `{"edge":[[pairs]]}` (108). So multi-select
  is a UI/state problem, not a protocol one. op=107 send shape is high-confidence
  by analogy to the live-confirmed go-to-point (`{"point":[id]}`, op=109).
- **Per-point cycles + auto-capture are NOT readable** anywhere found (not in the
  map blob, not in the patrol summary `param:{}`, not on `/status/`). They sync
  across app instances → cloud-stored somewhere unlocated. Surfacing them is
  blocked on a source-discovery probe; reserved here, not wired.
- We do **not** know the map-edit write path, so creating/moving/deleting points
  stays in the app — this feature is **read + select + launch only**.

## Decisions (user-approved)

- **Scope: BOTH patrol actions** — point patrol (o107, cruise points) AND edge
  patrol (o108, contours). Wiring both lets you test each on the card, and exercises
  the generic card across two action types. Zone/spot mow multi-select stays a
  deferred follow-up (same pattern).
- **Multi-select pattern:** the integration exposes each action's selectable items
  as a **consistent sensor-attribute shape** + a **list-taking service**; a single
  **generic custom card** consumes any such sensor+service. First run wires only
  the cruise-point sensor + `start_point_patrol`.
- **Selection is ephemeral** (select-then-go, like the app) — held in the card,
  passed to the service on launch. The integration stays stateless about selection.
- **Rendering:** green circle + white "P" marker, mirroring the existing
  maintenance-point "M" block. (Teardrop pin deferred — custom PIL shape, marginal
  gain.)
- **Cycles/auto-capture:** reserved as `null` per-point fields, shown read-only when
  present; a separate probe locates the source (read-only first, writable when the
  write endpoint is found). Not blocking.

## Data flow

```
cloud MAP.cruisePoints (type=8)
 → map_decoder._parse_cruise_points → DecodedMap.patrol_points [PatrolPoint(id, x_mm, y_mm)]
 → (a) base_map: green "P" markers (after the maintenance "M" block)
 → (b) sensor.…_map_N_patrol_points  state=count;  attr items=[{id, label, x_mm, y_mm, cycles:null, auto_capture:null}]
 generic card (reads attr `items`) → checkboxes → "Start patrol" button
 → service dreame_a2_mower.start_point_patrol(map_id, point_ids=[…])
 → coordinator.start_point_patrol → _ensure_active_map → routed_action(107, {"point":[ids]})
```

## Components (each a small, testable unit)

### 1. Parse — `map_decoder.py`
`_parse_cruise_points(cloud_response) -> list[PatrolPoint]`, mirroring
`_parse_maintenance_points`: read `cloud_response["cruisePoints"]["value"]`, take
each `[id, {path:[{x,y}], type, …}]`, keep coords in raw cloud-frame mm. New
`PatrolPoint` dataclass (`point_id: int, x_mm: float, y_mm: float`). Add
`patrol_points: tuple[PatrolPoint, ...]` to `DecodedMap`, populated in the same
place `maintenance_points` is. Empty/missing `cruisePoints` → `()`.

### 2. Render — `map_render/base_map.py` + `_geometry.py`
A `_PATROL_POINT_*` marker (green circle, 2× dock radius, white "P"), drawn
immediately after the maintenance-point block in `render_base_map`, iterating
`getattr(map_data, "patrol_points", ())`. Coords are cloud-frame mm → `_cloud_to_px`
(same as maintenance points). Reuse the maintenance "M" compositing helper with a
green fill + "P" glyph.

### 3. Data sources — two per-map sensors exposing the generic `items` attr
**`DreameA2MapPatrolPointsSensor`** (point patrol):
- state = `len(patrol_points)`.
- `extra_state_attributes = {"items": [ {"id": pid, "label": f"Patrol point {pid}",
  "x_mm": …, "y_mm": …, "cycles": None, "auto_capture": None }, … ]}`.

**`DreameA2MapPatrolEdgesSensor`** (edge patrol):
- state = number of contours available for edge patrol.
- `extra_state_attributes = {"items": [ {"id": [a, b], "label": f"Edge {a}"}, … ]}`,
  the `id` being the contour pair the o108 payload needs. Reuses the contour data
  the integration already parses for edge-mow (`active_selection_edge_contours` /
  the edge-target select source) — no new parsing if that's already on `DecodedMap`;
  otherwise add a `_parse_contours`-style read.

Both: dynamic (recomputed each cloud refresh); `items` is the **generic attribute key
every multi-select sensor uses**; per-map, static-at-setup; read-only (sensor).

### 4. Actions + services (BOTH patrols)
**Point patrol (o107):**
- `MowerAction.START_POINT_PATROL` in `mower/actions.py`; `_point_patrol_payload`
  → `{"point": [int(i) for i in point_ids]}`; ACTION_TABLE entry
  `{"siid":2, "aiid":50, "routed_t":"TASK", "routed_o":107}`.
- `coordinator.start_point_patrol(map_id, point_ids)` (in `coordinator/_writes.py`):
  `_ensure_active_map(map_id)` then `dispatch_action(START_POINT_PATROL, {"point_ids": point_ids})`.
  Mirrors `start_mowing_spot` / `start_go_to_point`.
- `services.yaml`: `start_point_patrol(map_id?, point_ids: list[int] ≥1)`.

**Edge patrol (o108):**
- `MowerAction.START_EDGE_PATROL`; `_edge_patrol_payload` →
  `{"edge": contour_ids}` where each id is a contour pair `[a, b]` (e.g. `[1, 0]`);
  ACTION_TABLE entry `{routed_o:108, …}`. **[UNVERIFIED]** SEND shape — the echo
  `s2p56=[[1,0,0]]` matches the map `contours` id `[1,0]` and `edge` is the op=101
  edge-mow d-key, so `{"edge":[[1,0]]}` is the high-confidence hypothesis; tag the
  inventory `o108` SEND claim `[UNVERIFIED]` until a live launch returns
  `s2p50 o:108 status:true`. If rejected, fall back to `{"contour":…}` / `{"region":…}`.
- `coordinator.start_edge_patrol(map_id, contour_ids)`: `_ensure_active_map` then dispatch.
- `services.yaml`: `start_edge_patrol(map_id?, contour_ids: list[list[int]] ≥1)`.

Both service handlers live alongside the existing mow services and call the
coordinator methods.

### 5. Generic card — `dashboards/cards/dreame-multi-select-card.js`
A small attribute card (no image → not the redraw-risk class). Config:
```yaml
type: custom:dreame-multi-select-card
entity: sensor.dreame_a2_mower_map_1_patrol_points   # any sensor exposing attr `items`
service: dreame_a2_mower.start_point_patrol
id_param: point_ids            # service field that takes the id list
title: Point Patrol            # optional
action_label: Start patrol     # optional, default "Start"
```
Behaviour: read `entity`'s `items` attr → render a checkbox + `label` per item (plus
read-only `cycles`/`auto_capture` chips when non-null) → on the action button,
`hass.callService(domain, service, {[id_param]: checkedIds})`. **Each item's `id` is
opaque** — an `int` (point patrol) or a `[a,b]` pair (edge patrol); the card collects
the checked ids verbatim into the list, so the same card drives both. Selection is
local to the card. **Two card instances** ship on the dashboard for v1 (point patrol →
`patrol_points` + `start_point_patrol`; edge patrol → `patrol_edges` +
`start_edge_patrol`); zone/spot later just add a third instance. Registered as a
Lovelace resource.

## Cycles / auto-capture (reserved, not wired)
The per-item dicts carry `cycles: null` / `auto_capture: null`; the card hides or
greys them when null. A **separate sub-task** probes the cloud for the source
(device-independent — sweep other batch keys / app-backend), then populates
read-only; a later sub-task wires the write endpoint when found. No dependency for v1.

## Scope / non-goals
- **No map edits** (create/move/delete points/contours) — write path unknown; app-only.
- **Zone/spot mow multi-select deferred** — mechanical reuse of this sensor+service+
  card pattern (the wire already takes `{"region":[…]}` / `{"area":[…]}`); add a third
  card instance + service later.
- **No persistent selection entity** (YAGNI; card-local is enough).
- **o107/o108 SEND shapes ship provisional** (`[UNVERIFIED]` in inventory) until a live
  launch confirms `status:true`; the code ships, the protocol claim stays tagged.

## Testing (TDD)
- `_parse_cruise_points`: fixture with `cruisePoints` (type=8) → `PatrolPoint` list;
  empty/missing → `()`; coords preserved.
- Render: a map with one patrol point yields the green-"P" marker (pixel/marker
  assertion mirroring the maintenance-point render test).
- Sensor: state == count; `items` attribute shape (id/label/coords/null-settings).
- Action/wire (point): `start_point_patrol(map_id, [3,4])` →
  `routed_action(107, {"point":[3,4]})` with active-map ensured first. Empty → ValueError.
- Action/wire (edge): `start_edge_patrol(map_id, [[1,0]])` →
  `routed_action(108, {"edge":[[1,0]]})` with active-map ensured first. Empty → ValueError.
- Edge sensor: state == contour count; `items` shape (id is the `[a,b]` pair).
- Services: both `start_point_patrol` / `start_edge_patrol` route to the coordinator.
- Card: light/manual (JS) — backend tests carry the contract; verify the card passes
  scalar AND pair ids verbatim.

## Files touched
- Edit: `map_decoder.py` (cruisePoints parse + contour data if needed),
  `map_render/base_map.py` + `map_render/_geometry.py` (green-"P" marker),
  `mower/actions.py` (`START_POINT_PATROL` + `START_EDGE_PATROL` + payloads),
  `coordinator/_writes.py` (`start_point_patrol` + `start_edge_patrol`),
  `sensor.py`/`sensor_device.py` (the two new per-map sensors + setup),
  `services.yaml` + services handler (`start_point_patrol`, `start_edge_patrol`),
  `strings.json` + `translations/en.json` (sensor names), `entity-inventory.yaml`
  (two new sensor rows), `inventory.yaml` (o107/o108 SEND-shape claims, `[UNVERIFIED]`).
- New: `dashboards/cards/dreame-multi-select-card.js` (generic); two card instances
  + resource wiring on the mower dashboard.
- Tests: `tests/protocol/…` (parse), `tests/integration/…` (both sensors, both
  services, both wires), render test.

## Open / to-confirm during implementation
- **o107 SEND** (`{"point":[ids]}`) and **o108 SEND** (`{"edge":[[pair]]}`) are
  high-confidence-by-analogy but **not yet live-confirmed**. Ship the actions; tag the
  inventory `o107`/`o108` SEND claims `[UNVERIFIED]` until a live launch returns
  `status:true`. The card+services let the user run that confirmation; on first live
  `status:true`, flip the inventory tags to `verified` (one-line each).
- Whether `DecodedMap` already carries contour data usable for the edge sensor (it
  should, via edge-mow) — confirm during implementation; add a minimal parse if not.

## Lifecycle
Per repo doc-canonicity: this spec is in-tree during implementation and moves to
`OLD/ha-dreame-a2-mower-docs/superpowers/specs/` when the branch is finished.
