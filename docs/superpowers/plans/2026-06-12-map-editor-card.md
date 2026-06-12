# Interactive Map-Editor Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dedicated Lovelace card to draw/select/resize/rotate/move/delete map shapes (no-go, ignore-obstacle, mow-shapes), writing them via the F2a services + edit-in-place.

**Architecture:** Backend adds an `object_id` edit param to the create services and publishes `editable_objects` (vector geometry in edit-frame meters) on the map camera. Frontend adds a pure node-testable geometry module + a vanilla-element card with a transform-handle editor. A gating frame-verification task locks the pixel↔meter mapping first.

**Tech Stack:** Python 3.13 + pytest (vanilla venv `/data/claude/homeassistant/.venv-vanilla`); ES-module JS tested via `node` v22 (`/usr/bin/node`).

---

## File Structure

- Create: `tests/www/geom_harness.mjs` + `tests/www/test_map_edit_geom.py` (pytest runs node).
- Create: `custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js` — pure geometry (ES module).
- Create: `custom_components/dreame_a2_mower/www/dreame-map-editor-card.js` — the card.
- Modify: `coordinator/_writes.py` — `object_id` param on the three create wrappers.
- Modify: `services.py` + `services.yaml` — `object_id` field on create_no_go_zone / create_ignore_obstacle / create_mow_shape.
- Modify: `map_decoder.py` — `ExclusionZone.points_m`.
- Modify: `_camera_map.py` — `editable_objects` attribute.
- Modify: `inventory.yaml`, `docs/research/app-integration-roadmap.md`, `docs/research/knowledge-gaps.md` — facts.
- Create: `docs/research/wire-captures/map-edit-frame-verification-2026-06-12.md` — Task 1 result.
- Tests: `tests/integration/test_map_edit_in_place.py`, `tests/integration/test_editable_objects_attr.py`, `tests/protocol/test_exclusion_points_m.py`.

Python tests: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -q`

---

### Task 1: Frame verification (GATING — documented numeric check)

**Files:**
- Create: `docs/research/wire-captures/map-edit-frame-verification-2026-06-12.md`

**Context:** The card converts pixels→meters and publishes object geometry in meters; both must match the `o=215` edit-frame. `projectPoint(x_m,y_m,proj)` renders the position trail correctly today, so the position frame is the anchor. We must confirm `o=215` meters == that frame.

- [ ] **Step 1: Get a map + its projection.** Load a real `MAP.*` payload that contains a no-go (forbidden) area. Sources, in order: (a) `/data/claude/homeassistant/cloud/dumps/` dumps (grep for `forbiddenAreas`); (b) the capture `dreame-app-capture-2026-06-09/miio-cloud-13267-http.jsonl` MAP reads after the `o=215` creates. Decode it with the integration's `map_decoder` to get `bx2`, `by2`, `pixel_size_mm`, `width_px`, `height_px` and the rendered base PNG.

- [ ] **Step 2: Project a captured o=215 rectangle.** Take a captured create, e.g. `o=215 type:2 points:[[9.65,-0.13],[4.12,-0.13],[4.12,5.01],[9.65,5.01]]` (or one whose map you decoded). Compute `projectPoint` for each corner:
  `px = (bx2*1000? )` — NOTE the decoder's `bx2` is already in mm; `projectPoint` uses `bx2_mm`. Use the same `map_projection` values the camera publishes. Print the 4 pixel corners.

- [ ] **Step 3: Confirm overlay.** Verify the 4 pixels (a) lie within `[0,width_px]×[0,height_px]` and (b) sit over that no-go on the rendered PNG (open the PNG, or compare to the decoded `ExclusionZone` pixel bbox for the same object). Record: PASS (edit-frame == projectPoint frame, inverse is the plain algebra in the spec) or the exact correction needed (reflection/offset) with the corrected inverse formula.

- [ ] **Step 4: Lock the rotation sign for `points_m`.** Using the same object, determine whether the edit-frame meters of an exclusion object = `rotate(raw_path_mm, +angle)/1000` or `-angle` — by checking which makes `projectPoint(points_m)` overlay the rendered object. Record the verified formula (used by Task 3 + Task 4).

- [ ] **Step 5: Write the result doc** `docs/research/wire-captures/map-edit-frame-verification-2026-06-12.md` with the numbers, the verdict, the locked `pixelToMeters` inverse, and the locked `points_m` formula. Commit.

```bash
git add docs/research/wire-captures/map-edit-frame-verification-2026-06-12.md
git commit -m "docs(map-edit): frame verification — lock pixel<->meter inverse + points_m formula"
```

> Downstream Tasks 3 and 4 MUST use the formulas this task records. If Step 3
> finds a non-trivial reflection, surface it before proceeding.

---

### Task 2: Edit-in-place `object_id` param

**Files:**
- Modify: `coordinator/_writes.py` (`create_no_go`, `create_ignore_obstacle`, `create_mow_shape`)
- Modify: `services.py` + `services.yaml`
- Test: `tests/integration/test_map_edit_in_place.py`

**Context:** `id:-1` = create; `id:<real>` = edit-in-place (same `o=215`/`o=234`). Add `object_id: int = -1` to each create wrapper; pass it as the payload `id`. Add an optional `object_id` service field (default -1).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_map_edit_in_place.py
from unittest.mock import AsyncMock
import pytest
from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin


def _coord():
    c = _WritesMixin()
    c.edit_map = AsyncMock(return_value=True)
    return c


@pytest.mark.asyncio
async def test_create_defaults_to_minus_one():
    c = _coord()
    await c.create_no_go(0, "polygon", [[1, 2], [3, 4], [5, 6]])
    assert c.edit_map.await_args.args[1][0][1]["id"] == -1


@pytest.mark.asyncio
async def test_edit_in_place_uses_real_id():
    c = _coord()
    await c.create_no_go(0, "polygon", [[1, 2], [3, 4], [5, 6]], object_id=101)
    op, payload = c.edit_map.await_args.args[1][0]
    assert op == 215 and payload["id"] == 101
    await c.create_ignore_obstacle(0, [[1, 2], [3, 4], [5, 6]], object_id=205)
    assert c.edit_map.await_args.args[1][0][1]["id"] == 205
    await c.create_mow_shape(0, "heart", [[0, 0], [1, 1]], object_id=302)
    assert c.edit_map.await_args.args[1][0][1]["id"] == 302
```

- [ ] **Step 2: Run → fail.** `…/pytest tests/integration/test_map_edit_in_place.py -q` (TypeError: unexpected kwarg).

- [ ] **Step 3: Implement.** Add `object_id: int = -1` to each of `create_no_go`, `create_ignore_obstacle`, `create_mow_shape`; replace the literal `"id": -1` with `"id": int(object_id)`. (Signatures: `create_no_go(self, map_id, shape, points, radius=0.0, object_id=-1)`, `create_ignore_obstacle(self, map_id, points, object_id=-1)`, `create_mow_shape(self, map_id, shape, points, object_id=-1)`.) In `services.py`, add `vol.Optional("object_id", default=-1): vol.Coerce(int)` to the three create schemas and pass `call.data.get("object_id", -1)` through each handler. In `services.yaml`, add an optional `object_id` field to those three services (description: "-1 to create new; an existing object id to edit it in place").

- [ ] **Step 4: Run → pass.** Same pytest command.

- [ ] **Step 5: Commit.**

```bash
git add custom_components/dreame_a2_mower/coordinator/_writes.py custom_components/dreame_a2_mower/services.py custom_components/dreame_a2_mower/services.yaml tests/integration/test_map_edit_in_place.py
git commit -m "feat(map-edit): object_id edit-in-place param on create services"
```

---

### Task 3: Decoder `points_m` + camera `editable_objects`

**Files:**
- Modify: `map_decoder.py` (`ExclusionZone`, `_collect_exclusion_entries`, the build loop)
- Modify: `_camera_map.py` (`extra_state_attributes`)
- Test: `tests/protocol/test_exclusion_points_m.py`, `tests/integration/test_editable_objects_attr.py`

**Context:** F-part-1 added `ExclusionZone.obj_id` and `_collect_exclusion_entries` returning `(obj_id, rotated, subtype)`. Add `points_m` (edit-frame meter corners) per the Task-1 formula. The raw cloud entry is `[id, {path, angle}]` (mm). `points_m` = the actual on-map corners in meters per Task 1 (e.g. `rotate(path, ±angle)/1000`). `_camera_map.extra_state_attributes` already builds `attrs` incl. `map_projection` (~line 119) — add `editable_objects` there.

- [ ] **Step 1: Write the failing tests**

```python
# tests/protocol/test_exclusion_points_m.py
from custom_components.dreame_a2_mower.map_decoder import _collect_exclusion_entries, ExclusionZone


def test_exclusion_zone_has_points_m_default_empty():
    z = ExclusionZone(points=((0.0, 0.0),))
    assert z.points_m == ()


def test_collect_returns_points_m_in_meters():
    # path in mm; axis-aligned (angle 0) -> points_m == path/1000
    wrapper = {"value": [[101, {"path": [{"x": 9650, "y": -130}, {"x": 4120, "y": -130},
                                          {"x": 4120, "y": 5010}, {"x": 9650, "y": 5010}], "angle": 0}]]}
    out = _collect_exclusion_entries(wrapper, None)
    obj_id, rotated, subtype, points_m = out[0]
    assert obj_id == 101
    assert points_m[0] == (9.65, -0.13) and points_m[2] == (4.12, 5.01)
```

```python
# tests/integration/test_editable_objects_attr.py
from types import SimpleNamespace
from unittest.mock import MagicMock
from custom_components.dreame_a2_mower._camera_map import DreameA2MapCamera  # adjust to real class
from custom_components.dreame_a2_mower.map_decoder import ExclusionZone


def test_editable_objects_attribute_shape():
    m = SimpleNamespace(exclusion_zones=(
        ExclusionZone(points=((0.0, 0.0),), subtype=None, obj_id=101, points_m=((9.65, -0.13), (4.12, 5.01))),
        ExclusionZone(points=((1.0, 1.0),), subtype="ignore", obj_id=102, points_m=((1.0, 2.0), (3.0, 4.0))),
        ExclusionZone(points=((2.0, 2.0),), subtype=None, obj_id=None, points_m=()),  # no id -> skip
    ))
    # build a coordinator/camera with this active map; call extra_state_attributes
    # (adapt to the real camera constructor + active-map accessor — see _camera_map.py).
    objs = DreameA2MapCamera._editable_objects_from_map(m)  # implement as a static/helper
    ids = {(o["id"], o["kind"], o["op"]) for o in objs}
    assert (101, "nogo", 215) in ids
    assert (102, "ignore", 234) in ids
    assert all(o["id"] is not None for o in objs)
    assert len(objs) == 2
```

> **Implementer note:** factor the editable-objects construction into a small pure
> helper (`_editable_objects_from_map(map_data) -> list[dict]`) so it unit-tests
> without building a full camera/coordinator. `extra_state_attributes` calls it
> with the active map. Match the real camera class name + active-map accessor.

- [ ] **Step 2: Run → fail.** Both test files.

- [ ] **Step 3: Implement.**
  - `ExclusionZone`: add `points_m: tuple[tuple[float, float], ...] = ()` (after `obj_id`).
  - `_collect_exclusion_entries`: compute `points_m` per the Task-1 formula (`rotate(path, ±angle)/1000`, sign from Task 1) and return 4-tuples `(obj_id, rotated, subtype, points_m)`. Update ALL consumers (F-part-1 had three: the type annotation ~685, the bbox loop ~701, the build loop ~728) to the 4-tuple; the build loop passes `points_m` to `ExclusionZone`. Geometry of the existing `points` must NOT change (run `tests/protocol/test_multi_map_decoder.py`).
  - `_camera_map.py`: add `_editable_objects_from_map(map_data)` → list of `{id, op, type, kind, points_m, radius}` for `exclusion_zones` with non-None `obj_id` (`kind="nogo"` op 215 type 2 for `subtype is None`; `kind="ignore"` op 234 type 0 for `subtype=="ignore"`; `radius` 0.0). In `extra_state_attributes`, set `attrs["editable_objects"] = self._editable_objects_from_map(<active map>)` using the same active-map source as `map_projection`.

- [ ] **Step 4: Run → pass** (new tests + `tests/protocol/test_multi_map_decoder.py` + `tests/protocol/test_exclusion_obj_id.py` still green).

- [ ] **Step 5: Commit.**

```bash
git add custom_components/dreame_a2_mower/map_decoder.py custom_components/dreame_a2_mower/_camera_map.py tests/protocol/test_exclusion_points_m.py tests/integration/test_editable_objects_attr.py
git commit -m "feat(map-edit): ExclusionZone.points_m + camera editable_objects attribute"
```

---

### Task 4: Pure geometry module + node tests

**Files:**
- Create: `custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js`
- Create: `tests/www/geom_harness.mjs`, `tests/www/test_map_edit_geom.py`

**Context:** Pure ES-module functions (no DOM) so they node-test. Use the Task-1-locked inverse. A pytest test subprocess-runs `node` on a harness that imports the module and asserts, so the geom stays in the pytest/release gate.

- [ ] **Step 1: Write the node harness + pytest wrapper (failing)**

`tests/www/geom_harness.mjs`:
```javascript
import assert from "node:assert";
import { pixelToMeters, rectCorners, rotatePointsAroundCentroid, circleFromCenterEdge, shapeToPoints }
  from "../../custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js";

const proj = { bx2_mm: 10000, by2_mm: 6000, pixel_size_mm: 50, width_px: 400, height_px: 240 };

// round-trip: meters -> pixel (projectPoint formula) -> meters
const x_m = 2.5, y_m = -1.0;
const px = (proj.bx2_mm - x_m * 1000) / proj.pixel_size_mm;
const py = proj.height_px - (proj.by2_mm - y_m * 1000) / proj.pixel_size_mm;
const [rx, ry] = pixelToMeters(px, py, proj);
assert.ok(Math.abs(rx - x_m) < 1e-6 && Math.abs(ry - y_m) < 1e-6, "round-trip");

// rectCorners: 2 drag points -> 4 corners
const rc = rectCorners([1, 1], [3, 4]);
assert.strictEqual(rc.length, 4);

// rotate a 3m axis-aligned square by ~26.565deg reproduces a skewed square (edge len preserved)
const sq = [[-1.5, -1.5], [1.5, -1.5], [1.5, 1.5], [-1.5, 1.5]];
const rot = rotatePointsAroundCentroid(sq, 26.565);
const edge = Math.hypot(rot[1][0] - rot[0][0], rot[1][1] - rot[0][1]);
assert.ok(Math.abs(edge - 3.0) < 1e-3, "rotation preserves edge length");

// circleFromCenterEdge
const c = circleFromCenterEdge([0, 0], [3, 4]);
assert.ok(Math.abs(c.radius - 5) < 1e-9, "circle radius");

// shapeToPoints: circle -> 1 point + radius; line -> 2; square -> 4
assert.strictEqual(shapeToPoints("nogo", "circle", { center: [0, 0], edge: [3, 4] }).points.length, 1);
assert.strictEqual(shapeToPoints("nogo", "line", { a: [0, 0], b: [1, 1] }).points.length, 2);

console.log("OK");
```

`tests/www/test_map_edit_geom.py`:
```python
import subprocess, shutil, pathlib, pytest

NODE = shutil.which("node")
HARNESS = pathlib.Path(__file__).parent / "geom_harness.mjs"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_map_edit_geom_harness():
    r = subprocess.run([NODE, str(HARNESS)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node harness failed:\n{r.stdout}\n{r.stderr}"
    assert "OK" in r.stdout
```

- [ ] **Step 2: Run → fail.** `…/pytest tests/www/test_map_edit_geom.py -q` (module/exports missing → node nonzero).

- [ ] **Step 3: Implement `_dreame-map-edit-geom.js`** with the Task-1-locked `pixelToMeters` inverse and the pure helpers (`rectCorners`, `bboxCorners`, `rotatePointsAroundCentroid`, `resizeUniform`, `circleFromCenterEdge`, `shapeToPoints`). `shapeToPoints(category, shape, state)` returns `{points: [[x,y]…], radius}` ready for the wire per the type table (no-go line/poly/circle; ignore polygon; mow-shape square=4/others=2). All pure, exported.

- [ ] **Step 4: Run → pass.** Also `node --check custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js`.

- [ ] **Step 5: Commit.**

```bash
git add custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js tests/www/geom_harness.mjs tests/www/test_map_edit_geom.py
git commit -m "feat(map-edit): pure pixel<->meter + shape geometry module (node-tested)"
```

---

### Task 5: Map-editor card — render + read-only overlays

**Files:**
- Create: `custom_components/dreame_a2_mower/www/dreame-map-editor-card.js`

**Context:** Mirror `dreame-mower-map-card.js` structure (vanilla `HTMLElement`, `setConfig`, `set hass`, SVG `viewBox 0 0 width_px height_px`, base `<image href=entity_picture>`). Import `projectPoint` from `_dreame-map-core.js` and the geom from `_dreame-map-edit-geom.js`. This task renders the map + draws each `editable_objects` entry as an SVG polygon overlay (projected via `projectPoint`) — NO interaction yet, just confirm it renders and overlays match the baked PNG.

- [ ] **Step 1: Implement the card skeleton** reading `camera.dreame_a2_mower_map` attrs (`map_projection`, `entity_picture`, `editable_objects`); render base image + one `<polygon>` per editable object (corners = `editable_objects[i].points_m` → `projectPoint`). `customElements.define("dreame-map-editor-card", …)`.

- [ ] **Step 2: `node --check`** the file. Run: `node --check custom_components/dreame_a2_mower/www/dreame-map-editor-card.js` → no error.

- [ ] **Step 3: Commit.**

```bash
git add custom_components/dreame_a2_mower/www/dreame-map-editor-card.js
git commit -m "feat(map-edit): map-editor card skeleton — render + editable-object overlays"
```

> Manual verification (post-merge): the overlays must sit exactly over the no-go/
> ignore areas baked into the PNG. If offset, the Task-1 formula / points_m is
> wrong — fix there, not by fudging the card.

---

### Task 6: Transform-handle editor (toolbar + drop + handles)

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-map-editor-card.js`

**Context:** This is the interactive core (manual-verified; geom math comes from Task 4's tested module). Add: a toolbar (shape picker: no-go rectangle/circle/line/polygon, ignore-obstacle polygon, mow-shapes square/circle/heart/triangle/teardrop/mushroom/cloud/rainbow; a map-id selector defaulting to active). Dropping a shape (or selecting an existing overlay) shows a bounding box with 4 corner resize handles, a rotate handle, a delete (X), and is move-draggable; lines show 2 endpoint handles + rotate + delete. Pointer events update an in-memory shape state via the Task-4 geom helpers and re-render live.

- [ ] **Step 1: Implement** the toolbar + selection state + handle rendering + pointer-drag math (delegating to `_dreame-map-edit-geom.js`). Keep all numeric math in the tested module; the card only does DOM + event plumbing.

- [ ] **Step 2: `node --check`** the file → no error.

- [ ] **Step 3: Commit.**

```bash
git add custom_components/dreame_a2_mower/www/dreame-map-editor-card.js
git commit -m "feat(map-edit): transform-handle editor (toolbar, drop, resize/rotate/move/delete)"
```

> Manual verification (post-merge): handles drag correctly; rotation visually
> tracks; non-rect shapes scale uniformly.

---

### Task 7: Wire Create / Save / Delete to services

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-map-editor-card.js`

**Context:** Convert the on-screen shape → meters (`pixelToMeters`) → final wire `points` (`shapeToPoints`) and call the right service. New shape → `id:-1` create; selected existing object → edit-in-place (`object_id` = its id); X on an existing object → `delete_map_object`.

- [ ] **Step 1: Implement** Create / Save / Delete buttons:
  - no-go create/edit → `hass.callService("dreame_a2_mower", "create_no_go_zone", {map_id, shape, points, radius, object_id})` (`object_id:-1` for new, real id for edit).
  - ignore-obstacle → `create_ignore_obstacle` ({map_id, points, object_id}).
  - mow-shape create → `create_mow_shape` ({map_id, shape, points}) (existing mow-shapes aren't in editable_objects, so create-only).
  - delete → `delete_map_object` ({map_id, object_id, category}) where category = 0 (nogo) / 4 (ignore).
  After a successful call, clear the selection (the next camera refresh re-publishes `editable_objects`).

- [ ] **Step 2: `node --check`** → no error.

- [ ] **Step 3: Commit.**

```bash
git add custom_components/dreame_a2_mower/www/dreame-map-editor-card.js
git commit -m "feat(map-edit): wire card Create/Save/Delete to services (incl. edit-in-place)"
```

> Manual verification (post-merge): draw a no-go and Create → appears on the map
> after refresh; select it, resize, Save → updates in place; X → removed.

---

### Task 8: Fact discipline

**Files:**
- Modify: `inventory.yaml`, `docs/research/app-integration-roadmap.md`, `docs/research/knowledge-gaps.md`

- [ ] **Step 1: inventory.yaml** — add a `verified` record (taxonomy `status: verified` + `evidence:`) tagged `[app-mitm:2026-06-12-mapedit-rotate-edit]` on the `o215` (or map-edit transaction) entry: `id:-1`=create / `id:<real>`=edit-in-place (same o=215/o=234); rotate + resize baked into `points` (no angle field); type 15 now wire-seen. Evidence: `dreame-app-mapedit-rotate-edit-2026-06-12.md`. Update the F2a `[UNVERIFIED]` note: 15 now confirmed; 12/14/16 still inferred.

- [ ] **Step 2: roadmap** — row F → **done** (F2b interactive map-editor card: create/edit/rotate/move/delete). Remaining map work: rename-map/delete-map (uncaptured), existing-mow-shape edit (not decoded), draw-by-driving (BT).

- [ ] **Step 3: knowledge-gaps** — close the rotate + edit-in-place gaps (now wired). Keep open: `o=234` edit-in-place by-analogy (capture to confirm); curved mow-shape rotation point representation; decode mow-shapes so existing ones become editable.

- [ ] **Step 4: Gates.** `…/pytest tests/ -q -k "inventory or audit or census or honesty"` PASS; `…python -c "import yaml; yaml.safe_load(open('custom_components/dreame_a2_mower/inventory.yaml')); print('ok')"`.

- [ ] **Step 5: Commit.**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml docs/research/app-integration-roadmap.md docs/research/knowledge-gaps.md
git commit -m "docs(map-edit): rotate/edit-in-place verified; roadmap F done; knowledge-gaps"
```

---

### Task 9: Full suite + node check + gates

- [ ] **Step 1: Full suite.** `…/pytest tests/ -q` — PASS (baseline 2193 passed / 4 skipped from F2a, plus new tests; report totals). Do NOT bump `manifest.json` (release.sh owns it).

- [ ] **Step 2: Node check all cards.** `for f in custom_components/dreame_a2_mower/www/*.js; do node --check "$f" || echo "FAIL $f"; done` — no failures (release.sh also runs this).

- [ ] **Step 3: State-machine audit** (checked in Task 8) — no new entities, expect green.

---

## Self-Review (completed)

- **Spec coverage:** frame verification (T1), edit-in-place (T2), decoder+camera geometry (T3), pure geom + node tests (T4), card render (T5), handles (T6), service wiring (T7), facts (T8), suite (T9). All spec sections mapped.
- **Placeholders:** none — testable parts have exact code; DOM-heavy T5-T7 give structure + the service-call contracts + `node --check` gate + explicit manual-verification notes (the interactive DOM genuinely can't be auto-tested; the risky math is in T4's node-tested module).
- **Type/name consistency:** wrappers gain `object_id=-1`; `ExclusionZone(points, subtype, obj_id, points_m)`; `_collect_exclusion_entries → (obj_id, rotated, subtype, points_m)`; camera `_editable_objects_from_map` → `{id, op, type, kind, points_m, radius}`; geom exports `pixelToMeters/rectCorners/bboxCorners/rotatePointsAroundCentroid/resizeUniform/circleFromCenterEdge/shapeToPoints`; services add `object_id`. Consistent across tasks. Tasks 3 & 4 consume the Task-1 formulas.
