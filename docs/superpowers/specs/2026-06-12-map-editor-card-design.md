# Phase F2b — Interactive map-editor card

**Status:** approved 2026-06-12. Wire facts: `dreame-app-capture-2026-06-09`
(create) + `dreame-app-mapedit-rotate-edit-2026-06-12.md` (rotate + edit-in-place).
Builds on F2a (create/split/merge services) and F-part-1 (`edit_map` transaction,
`ExclusionZone.obj_id`, `deletable_objects`).

## Goal

A dedicated Lovelace card that renders the mower map, lets the user drop / select
shapes and manipulate them with app-style bounding-box handles (resize corners,
rotate, move, delete), and writes them to the device via the F2a services +
edit-in-place. Replicates the app's create/edit workflow.

## Wire facts (verified)

- Create / edit / rotate all use `o=215` (shapes + no-go) / `o=234`
  (ignore-obstacle); `id` is the only create-vs-edit discriminator:
  `id:-1` = create new; `id:<real>` = replace that object in place. New objects
  get a device-assigned id after commit; reuse it to edit.
- **Rotate + resize are baked into `points`** — no angle field; a rotated shape
  is sent as already-rotated corner coords. (Proof: rotated square
  `type:9, points:[[-4.71,-9.87],[-6.05,-7.19],[-3.37,-5.85],[-2.03,-8.53]]`.)
- type: 1=line, 2=polygon, 3=circle (no-go); 9=square, 12-18=circle…rainbow
  (mow-shapes). Square = 4 corners; curved mow-shapes = 2-pt bbox.
- All inside the `o=204` begin / `o=201` commit transaction (one commit can batch
  several edits) — i.e. through the existing `edit_map`.

## Coordinate transform (the gating risk)

`www/_dreame-map-core.js::projectPoint(x_m, y_m, proj)` maps meters→pixels:
```
px = (bx2_mm − x_m*1000) / pixel_size_mm
py = height_px − (by2_mm − y_m*1000) / pixel_size_mm
```
Inverse (pixel→meters):
```
x_m = (bx2_mm − px*pixel_size_mm) / 1000
y_m = (by2_mm − (height_px − py)*pixel_size_mm) / 1000
```
`proj` = the `map_projection` attribute already on `camera.dreame_a2_mower_map`
(`bx2_mm, by2_mm, pixel_size_mm, width_px, height_px`).

**FRAME VERIFICATION (build Task 1, gating):** project a captured `o=215`
rectangle (e.g. `[[9.65,-0.13],[4.12,-0.13],[4.12,5.01],[9.65,5.01]]`) through
`projectPoint` using that map's projection and confirm the pixels overlay that
no-go on the rendered base PNG. This proves the `o=215` edit-frame == the
`projectPoint` (position/trail) frame. If it is reflected/offset, derive the
correction (the trail and mowing zones already render correctly via
`projectPoint`, so the position frame is the anchor) and bake it into BOTH the
card's inverse and the `editable_objects` publishing so they round-trip. Capture
the verification (numbers + outcome) in `docs/research/` and only then build on
it. Everything downstream depends on this single result.

## Architecture

### Backend (Python — pytest-testable)

**B1. Edit-in-place param.** Add `object_id: int = -1` to `create_no_go`,
`create_ignore_obstacle`, `create_mow_shape` (and their services). `-1` →
`id:-1` (create, current behaviour); a non-negative id → that `id` in the
`o=215`/`o=234` payload (edit-in-place). No other change — same transaction.

**B2. Publish editable geometry.** Add an `editable_objects` attribute to
`_camera_map.extra_state_attributes` (next to `map_projection`):
```
editable_objects: [
  { id: int, op: 215|234, type: int, kind: "nogo"|"ignore",
    points_m: [[x, y], …], radius: float },
  …
]
```
in the **edit-frame meters** verified in Task 1. Source = the decoder's no-go
(`forbiddenAreas`) + ignore-obstacle (`notObsAreas`) objects, which already carry
`obj_id` (F-part-1). The decoder is augmented to also expose each exclusion
object's corners in edit-frame meters (`points_m`) — derived from the raw cloud
`path` (mm) + `angle` (the actual on-map corners = rotate(path, angle) / 1000;
rotation sign locked by Task 1). `radius` defaults 0 (circles, if distinguishable,
carry their radius; otherwise the card treats a 2-corner no-go as a rect).
Mow-shapes are NOT decoded today, so they are NOT in `editable_objects` — existing
mow-shapes can't be selected/edited this phase (creation still works); noted in
knowledge-gaps.

**B3. Decoder geometry.** Augment the exclusion decode (`_collect_exclusion_entries`
+ `ExclusionZone`) to carry `points_m: tuple[tuple[float,float], …]` (edit-frame
meters) alongside the existing renderer-coord `points` and `obj_id`. Geometry/
rendering output of the existing `points` is unchanged (additive field). The
camera attribute (B2) reads `points_m`.

### Frontend (JS — node-testable pure math + manual-verified DOM)

**F1. Pure geometry module** `www/_dreame-map-edit-geom.js` (ES module, node-testable):
- `pixelToMeters(px, py, proj)` — the inverse above (+ any Task-1 correction).
- `metersToPixel` — re-export `projectPoint`.
- `rectCorners(p0, p1)` / `bboxCorners(p0, p1)` — 2 drag points → 4 corner pts.
- `rotatePointsAroundCentroid(points, deg)` — rotate a polygon's corners.
- `resizeUniform(corners, handleIdx, newPos)` — corner-drag → scaled corners
  (uniform for non-rect to keep aspect).
- `circleFromCenterEdge(center, edge)` — center + edge pt → {center, radius}.
- `shapeToPoints(kind, shape, state)` — final `points` (meters) + `radius` for the
  wire, per shape/type.
These are pure functions with no DOM — unit-tested in node.

**F2. The card** `www/dreame-map-editor-card.js` (vanilla `HTMLElement`, like the
live map card; reuses `_dreame-map-core.js` + `_dreame-map-edit-geom.js`):
- Renders the base PNG `<image>` (from `entity_picture`) in an SVG
  `viewBox 0 0 width_px height_px`, plus interactive vector overlays for each
  `editable_objects` entry (projected via `projectPoint`).
- **Toolbar:** shape picker — no-go (rectangle / circle / line / polygon),
  ignore-obstacle (polygon), mow-shapes (square / circle / heart / triangle /
  teardrop / mushroom / cloud / rainbow). A map-id selector (defaults to active).
- **Transform-handle component:** a selected/new shape shows a bounding box with
  4 resize corners, a rotate handle, a delete (X), and is move-draggable. Lines
  show 2 endpoint handles + rotate + delete. Pointer events drive
  `_dreame-map-edit-geom` math; the shape re-renders live.
- **Actions:** Create (new shape → `id:-1` service call); Save (selected existing
  object → edit-in-place service with its real id); Delete (X on an existing
  object → `delete_map_object`). On Save/Create the card converts the on-screen
  pixel geometry → meters via `pixelToMeters`, computes final `points` via
  `shapeToPoints`, and calls `hass.callService("dreame_a2_mower", …)`.
- Service mapping: no-go → `create_no_go_zone` (+ `object_id` for edit);
  ignore-obstacle → `create_ignore_obstacle`; mow-shape create →
  `create_mow_shape`; delete → `delete_map_object`.

### Deploy

The card JS is already served from `www/` (static path registered in
`__init__.py`). It is registered as a Lovelace resource and placed on a new
"Map editor" dashboard view — a separate dashboard-deploy step (SCP per the
dashboard-deploy procedure), NOT shipped by HACS.

## Testing

- **Node** (`www/` pure geom): `pixelToMeters`∘`projectPoint` round-trips a known
  point; `rectCorners`/`bboxCorners` produce the 4 expected corners;
  `rotatePointsAroundCentroid` reproduces the captured rotated square
  (`[[-4.71,-9.87],…]`) from an axis-aligned 3 m square + ~26.6°;
  `circleFromCenterEdge` radius; `shapeToPoints` emits the right point count +
  radius per shape/type. Run via `node` (see project card-verification rule — a
  node harness executing the exported functions; `node --check` alone is
  insufficient).
- **pytest:** `create_no_go(object_id=101)` emits `o=215 {id:101,…}` (edit);
  default `object_id=-1` unchanged; `editable_objects` attribute shape + that
  id-less exclusions are excluded; decoder `points_m` present + geometry
  (existing `points`) unchanged.
- **Frame verification (Task 1):** documented numeric check, not a unit test.
- **Manual (post-merge):** drop/resize/rotate/move/create/select/edit/delete on
  the dashboard; cards cache hard — hard-refresh. The interactive DOM is not
  auto-tested; the geometry math (the risky part) is node-tested.

## Honesty + fact discipline

- Rotate + edit-in-place now wire-verified → `inventory.yaml` record tagged
  `[app-mitm:2026-06-12-mapedit-rotate-edit]`: `id:-1`=create / `id:<real>`=edit
  (same `o=215`/`o=234`); rotate/resize baked into `points`; type 15 now
  wire-seen (still infer 12/14/16 names). Taxonomy `status: verified` + `evidence:`.
- `docs/research/app-integration-roadmap.md`: row F → **done** (F2b: interactive
  map-editor card; create/edit/rotate/delete). Remaining map work = rename-map /
  delete-map (uncaptured), mow-shape existing-edit (not decoded), draw-by-driving
  (BT).
- `docs/research/knowledge-gaps.md`: close rotate/edit gaps; keep
  `o=234`-edit-in-place by-analogy (capture to confirm), curved-shape-rotation
  point representation, mow-shape decode (so existing mow-shapes become editable).
- No new HA entities (camera attr + a JS card) → no state-machine-audit rows;
  verify the audit still exits 0.

## Versioning / release

Do NOT pre-bump `manifest.json` — `release.sh` owns it (a7 → **a8**). On
completion: merge to `main`, push, `release.sh`. The dashboard view is deployed
separately (SCP) after the release.
