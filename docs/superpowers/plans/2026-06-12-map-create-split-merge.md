# Map Create / Split / Merge Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the wire-verified create (`o=215`/`o=234`), split (`o=220`) and merge (`o=221`) map-edit ops as coordinate-driven services through the existing `edit_map` transaction.

**Architecture:** Pure validation/builder helpers + five coordinator wrapper methods that each emit one mutation via `edit_map` (from Phase F part 1). Five services expose them. No decoder/sensor/entity changes; no frontend.

**Tech Stack:** Python 3.13, Home Assistant custom integration, pytest (vanilla stubbed-HA venv at `/data/claude/homeassistant/.venv-vanilla`).

---

## File Structure

- Create: `custom_components/dreame_a2_mower/protocol/map_edit_shapes.py` — pure shape→type maps + point coercion/validation (no HA imports).
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py` — five wrapper methods on `_WritesMixin`.
- Modify: `custom_components/dreame_a2_mower/services.py` + `services.yaml` — five services.
- Modify: `inventory.yaml`, `docs/research/app-integration-roadmap.md`, `docs/research/knowledge-gaps.md` — fact discipline.
- Tests: `tests/unit/test_map_edit_shapes.py`, `tests/integration/test_map_create_wrappers.py`, `tests/integration/test_map_create_services.py`.

Run tests: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -q`

---

### Task 1: Pure shape helpers (maps + point validation)

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/map_edit_shapes.py`
- Test: `tests/unit/test_map_edit_shapes.py`

**Context:** `o=215` type codes: no-go line=1, polygon=2, circle=3; mow-shapes square=9, circle=12, heart=13, triangle=14, teardrop=15, mushroom=16, cloud=17, rainbow=18. Point-count rules: line=2, polygon≥3, circle=1, square=4, other mow-shapes=2. These helpers are pure (no HA, no cloud) so they unit-test fast and the wrappers stay thin.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_map_edit_shapes.py
import pytest
from custom_components.dreame_a2_mower.protocol import map_edit_shapes as mes


def test_as_pairs_coerces_and_validates():
    assert mes.as_pairs([[1, 2], (3.5, 4)]) == [[1.0, 2.0], [3.5, 4.0]]
    with pytest.raises(ValueError):
        mes.as_pairs([[1, 2, 3]])      # not a 2-tuple
    with pytest.raises(ValueError):
        mes.as_pairs([])               # empty
    with pytest.raises(ValueError):
        mes.as_pairs("nope")


def test_nogo_type_and_validation():
    assert mes.nogo_type("line") == 1
    assert mes.nogo_type("polygon") == 2
    assert mes.nogo_type("circle") == 3
    with pytest.raises(ValueError):
        mes.nogo_type("blob")
    # point-count validation
    mes.validate_nogo("line", [[0, 0], [1, 1]], radius=0)        # ok
    mes.validate_nogo("polygon", [[0, 0], [1, 0], [1, 1]], radius=0)  # ok
    mes.validate_nogo("circle", [[0, 0]], radius=1.5)            # ok
    with pytest.raises(ValueError):
        mes.validate_nogo("line", [[0, 0]], radius=0)           # need 2
    with pytest.raises(ValueError):
        mes.validate_nogo("polygon", [[0, 0], [1, 1]], radius=0)  # need >=3
    with pytest.raises(ValueError):
        mes.validate_nogo("circle", [[0, 0]], radius=0)         # radius must be >0


def test_mow_shape_type_and_validation():
    assert mes.mow_shape_type("square") == 9
    assert mes.mow_shape_type("heart") == 13
    assert mes.mow_shape_type("rainbow") == 18
    with pytest.raises(ValueError):
        mes.mow_shape_type("hexagon")
    mes.validate_mow_shape("square", [[0, 0], [1, 0], [1, 1], [0, 1]])   # 4 ok
    mes.validate_mow_shape("heart", [[0, 0], [1, 1]])                    # 2 ok
    with pytest.raises(ValueError):
        mes.validate_mow_shape("square", [[0, 0], [1, 1]])              # need 4
    with pytest.raises(ValueError):
        mes.validate_mow_shape("cloud", [[0, 0], [1, 1], [2, 2]])       # need 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_map_edit_shapes.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

```python
# custom_components/dreame_a2_mower/protocol/map_edit_shapes.py
"""Pure shape→type maps + point validation for the map-edit create ops.

Wire facts: dreame-app-capture-2026-06-09 (o=215/o=234) + IMG_4615.PNG (the
"Shapes" screen: Square/Circle/Heart/Triangle/Teardrop/Mushroom/Cloud/Rainbow).
No HA / cloud imports — keeps the coordinator wrappers thin and fast to test.
"""
from __future__ import annotations

from typing import Any

NOGO_TYPE = {"line": 1, "polygon": 2, "circle": 3}
MOW_SHAPE_TYPE = {
    "square": 9, "circle": 12, "heart": 13, "triangle": 14,
    "teardrop": 15, "mushroom": 16, "cloud": 17, "rainbow": 18,
}


def as_pairs(points: Any) -> list[list[float]]:
    """Coerce an iterable of [x, y] into a list of [float, float]. Raises
    ValueError on a non-iterable, an empty list, or a non-2-element pair."""
    if isinstance(points, (str, bytes)) or not hasattr(points, "__iter__"):
        raise ValueError(f"points must be a list of [x, y] pairs, got {points!r}")
    out: list[list[float]] = []
    for p in points:
        if isinstance(p, (str, bytes)) or not hasattr(p, "__iter__"):
            raise ValueError(f"point must be [x, y], got {p!r}")
        pair = list(p)
        if len(pair) != 2:
            raise ValueError(f"point must have exactly 2 coords, got {pair!r}")
        out.append([float(pair[0]), float(pair[1])])
    if not out:
        raise ValueError("points is empty")
    return out


def pair(p: Any) -> list[float]:
    """Coerce a single [x, y] into [float, float]."""
    return as_pairs([p])[0]


def nogo_type(shape: str) -> int:
    try:
        return NOGO_TYPE[shape]
    except KeyError:
        raise ValueError(f"unknown no-go shape {shape!r}; expected one of {sorted(NOGO_TYPE)}")


def mow_shape_type(shape: str) -> int:
    try:
        return MOW_SHAPE_TYPE[shape]
    except KeyError:
        raise ValueError(f"unknown mow-shape {shape!r}; expected one of {sorted(MOW_SHAPE_TYPE)}")


def validate_nogo(shape: str, points: list[list[float]], *, radius: float) -> None:
    n = len(points)
    if shape == "line" and n != 2:
        raise ValueError(f"line no-go needs exactly 2 points, got {n}")
    if shape == "polygon" and n < 3:
        raise ValueError(f"polygon no-go needs >=3 points, got {n}")
    if shape == "circle":
        if n != 1:
            raise ValueError(f"circle no-go needs exactly 1 point, got {n}")
        if not radius > 0:
            raise ValueError(f"circle no-go needs radius > 0, got {radius}")


def validate_mow_shape(shape: str, points: list[list[float]]) -> None:
    n = len(points)
    if shape == "square" and n != 4:
        raise ValueError(f"square mow-shape needs exactly 4 points, got {n}")
    if shape != "square" and n != 2:
        raise ValueError(f"{shape} mow-shape needs exactly 2 points (bbox), got {n}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_map_edit_shapes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/map_edit_shapes.py tests/unit/test_map_edit_shapes.py
git commit -m "feat(map-edit): pure shape->type maps + point validation"
```

---

### Task 2: Coordinator create/split/merge wrappers

**Files:**
- Modify: `coordinator/_writes.py` (add to `_WritesMixin`, near `rename_zone`/`delete_map_object` ~line 725)
- Test: `tests/integration/test_map_create_wrappers.py`

**Context:** `edit_map(self, map_id, mutations: list[tuple[int, dict|None]]) -> bool` already exists (part 1). Each wrapper validates (via Task 1 helpers — ValueError on bad input, BEFORE calling edit_map) then `return await self.edit_map(map_id, [mutation])`. Spy on `edit_map` by replacing it on the instance.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_map_create_wrappers.py
from unittest.mock import AsyncMock
import pytest
from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin


def _coord():
    c = _WritesMixin()
    c.edit_map = AsyncMock(return_value=True)
    return c


@pytest.mark.asyncio
async def test_create_no_go_polygon_circle_line():
    c = _coord()
    await c.create_no_go(0, "polygon", [[9.65, -0.13], [4.12, -0.13], [4.12, 5.01]])
    await c.create_no_go(0, "circle", [[-5.08, -4.97]], radius=1.5)
    await c.create_no_go(1, "line", [[6.48, 3.23], [-7.56, -5.81]])
    muts = [call.args[1][0] for call in c.edit_map.await_args_list]
    assert muts[0] == (215, {"id": -1, "type": 2, "points": [[9.65, -0.13], [4.12, -0.13], [4.12, 5.01]], "radius": 0.0})
    assert muts[1] == (215, {"id": -1, "type": 3, "points": [[-5.08, -4.97]], "radius": 1.5})
    assert muts[2] == (215, {"id": -1, "type": 1, "points": [[6.48, 3.23], [-7.56, -5.81]], "radius": 0.0})


@pytest.mark.asyncio
async def test_create_ignore_obstacle_has_no_radius():
    c = _coord()
    await c.create_ignore_obstacle(0, [[-2.49, -5.97], [-8.71, -5.97], [-8.71, -0.18]])
    op, payload = c.edit_map.await_args.args[1][0]
    assert op == 234 and payload["type"] == 0 and "radius" not in payload


@pytest.mark.asyncio
async def test_create_mow_shape():
    c = _coord()
    await c.create_mow_shape(0, "heart", [[0.57, -8.39], [-7.97, 0.15]])
    assert c.edit_map.await_args.args[1][0] == (215, {"id": -1, "type": 13, "points": [[0.57, -8.39], [-7.97, 0.15]], "radius": 0})


@pytest.mark.asyncio
async def test_split_and_merge():
    c = _coord()
    await c.split_zone(0, 1, [-0.19, -11.41], [-5.21, -6.22])
    await c.merge_zones(0, [2, 1])
    muts = [call.args[1][0] for call in c.edit_map.await_args_list]
    assert muts[0] == (220, {"id": 1, "line_start": [-0.19, -11.41], "line_end": [-5.21, -6.22]})
    assert muts[1] == (221, {"ids": [2, 1]})


@pytest.mark.asyncio
async def test_validation_rejects_before_wire():
    c = _coord()
    with pytest.raises(ValueError):
        await c.create_no_go(0, "line", [[0, 0]])           # need 2 points
    with pytest.raises(ValueError):
        await c.create_mow_shape(0, "square", [[0, 0], [1, 1]])  # need 4
    c.edit_map.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_create_wrappers.py -q`
Expected: FAIL (wrappers undefined).

- [ ] **Step 3: Implement**

Add to `_WritesMixin` (after `delete_map_object`). Import the helpers at module top of `_writes.py` (it already imports protocol modules inside methods; a top-level `from ..protocol import map_edit_shapes as _mes` is fine and keeps the wrappers terse):

```python
    async def create_no_go(self, map_id, shape, points, radius=0.0) -> bool:
        """Create a no-go area (o=215): shape line(2pt)/polygon(>=3pt)/circle(1pt+radius>0).

        points are [x, y] meter pairs in the map edit-frame.
        """
        from ..protocol import map_edit_shapes as _mes
        t = _mes.nogo_type(shape)
        pts = _mes.as_pairs(points)
        _mes.validate_nogo(shape, pts, radius=float(radius))
        return await self.edit_map(int(map_id), [(215, {
            "id": -1, "type": t, "points": pts, "radius": float(radius),
        })])

    async def create_ignore_obstacle(self, map_id, points) -> bool:
        """Create an ignore-obstacle area (o=234, polygon >=3 pt, no radius)."""
        from ..protocol import map_edit_shapes as _mes
        pts = _mes.as_pairs(points)
        if len(pts) < 3:
            raise ValueError(f"ignore-obstacle needs >=3 points, got {len(pts)}")
        return await self.edit_map(int(map_id), [(234, {
            "id": -1, "type": 0, "points": pts,
        })])

    async def create_mow_shape(self, map_id, shape, points) -> bool:
        """Create a decorative mow-shape (o=215 type 9/12-18). square=4pt, others=2pt bbox."""
        from ..protocol import map_edit_shapes as _mes
        t = _mes.mow_shape_type(shape)
        pts = _mes.as_pairs(points)
        _mes.validate_mow_shape(shape, pts)
        return await self.edit_map(int(map_id), [(215, {
            "id": -1, "type": t, "points": pts, "radius": 0,
        })])

    async def split_zone(self, map_id, zone_id, line_start, line_end) -> bool:
        """Split a zone by a line (o=220). DESTRUCTIVE: clears that zone's schedule/prefs."""
        from ..protocol import map_edit_shapes as _mes
        return await self.edit_map(int(map_id), [(220, {
            "id": int(zone_id),
            "line_start": _mes.pair(line_start),
            "line_end": _mes.pair(line_end),
        })])

    async def merge_zones(self, map_id, ids) -> bool:
        """Merge zones by id list (o=221). DESTRUCTIVE: resets merged prefs."""
        zone_ids = [int(i) for i in ids]
        if len(zone_ids) < 2:
            raise ValueError(f"merge needs >=2 zone ids, got {zone_ids}")
        return await self.edit_map(int(map_id), [(221, {"ids": zone_ids})])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_create_wrappers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_writes.py tests/integration/test_map_create_wrappers.py
git commit -m "feat(map-edit): create_no_go/ignore_obstacle/mow_shape + split/merge wrappers"
```

---

### Task 3: Services (5) + services.yaml

**Files:**
- Modify: `services.py` (constants ~46; handlers ~708; register ~781; unregister ~796)
- Modify: `services.yaml`
- Test: `tests/integration/test_map_create_services.py`

**Context:** Follow the part-1 pattern exactly (`_coordinator_from_call`, `vol.Schema`, register + add SERVICE_ constants to the unregister tuple). `cv.string` is broken in the vanilla stub — use `vol.Coerce(str)`/`vol.In(...)`. Points come in as a list of `[x,y]`; pass straight through (the wrappers coerce). Handlers must catch `ValueError` from the wrapper (bad shape/points) and log, not crash.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_map_create_services.py
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from custom_components.dreame_a2_mower import services


def _patch_coord(monkeypatch, **methods):
    coord = SimpleNamespace(**methods)
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    return coord


@pytest.mark.asyncio
async def test_create_no_go_zone_service(monkeypatch):
    coord = _patch_coord(monkeypatch, create_no_go=AsyncMock(return_value=True))
    call = SimpleNamespace(hass=SimpleNamespace(), data={
        "map_id": 0, "shape": "polygon", "points": [[1, 2], [3, 4], [5, 6]], "radius": 0,
    })
    await services._handle_create_no_go_zone(call)
    coord.create_no_go.assert_awaited_once_with(0, "polygon", [[1, 2], [3, 4], [5, 6]], 0.0)


@pytest.mark.asyncio
async def test_create_ignore_obstacle_service(monkeypatch):
    coord = _patch_coord(monkeypatch, create_ignore_obstacle=AsyncMock(return_value=True))
    call = SimpleNamespace(hass=SimpleNamespace(), data={"map_id": 0, "points": [[1, 2], [3, 4], [5, 6]]})
    await services._handle_create_ignore_obstacle(call)
    coord.create_ignore_obstacle.assert_awaited_once_with(0, [[1, 2], [3, 4], [5, 6]])


@pytest.mark.asyncio
async def test_create_mow_shape_service(monkeypatch):
    coord = _patch_coord(monkeypatch, create_mow_shape=AsyncMock(return_value=True))
    call = SimpleNamespace(hass=SimpleNamespace(), data={"map_id": 0, "shape": "heart", "points": [[0, 0], [1, 1]]})
    await services._handle_create_mow_shape(call)
    coord.create_mow_shape.assert_awaited_once_with(0, "heart", [[0, 0], [1, 1]])


@pytest.mark.asyncio
async def test_split_and_merge_services(monkeypatch):
    coord = _patch_coord(
        monkeypatch,
        split_zone=AsyncMock(return_value=True),
        merge_zones=AsyncMock(return_value=True),
    )
    await services._handle_split_zone(SimpleNamespace(hass=SimpleNamespace(), data={
        "map_id": 0, "zone": 1, "line_start": [0, 0], "line_end": [1, 1]}))
    await services._handle_merge_zones(SimpleNamespace(hass=SimpleNamespace(), data={
        "map_id": 0, "zones": [2, 1]}))
    coord.split_zone.assert_awaited_once_with(0, 1, [0, 0], [1, 1])
    coord.merge_zones.assert_awaited_once_with(0, [2, 1])


@pytest.mark.asyncio
async def test_handler_swallows_value_error(monkeypatch):
    coord = _patch_coord(monkeypatch, create_no_go=AsyncMock(side_effect=ValueError("bad")))
    # should not raise out of the handler
    await services._handle_create_no_go_zone(SimpleNamespace(hass=SimpleNamespace(), data={
        "map_id": 0, "shape": "line", "points": [[0, 0]], "radius": 0}))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_create_services.py -q`
Expected: FAIL (handlers undefined).

- [ ] **Step 3: Implement**

Add constants:
```python
SERVICE_CREATE_NO_GO_ZONE = "create_no_go_zone"
SERVICE_CREATE_IGNORE_OBSTACLE = "create_ignore_obstacle"
SERVICE_CREATE_MOW_SHAPE = "create_mow_shape"
SERVICE_SPLIT_ZONE = "split_zone"
SERVICE_MERGE_ZONES = "merge_zones"
```

Schemas (a point = list of 2 numbers; `points` = list of points):
```python
_POINT = vol.All([vol.Coerce(float)], vol.Length(min=2, max=2))
SCHEMA_CREATE_NO_GO_ZONE = vol.Schema({
    vol.Required("map_id"): vol.Coerce(int),
    vol.Required("shape"): vol.In(["line", "polygon", "circle"]),
    vol.Required("points"): [vol.Coerce(float)] and list,  # see note
    vol.Optional("radius", default=0.0): vol.Coerce(float),
})
```
> **Implementer note:** keep the `points` schema permissive — accept a `list`
> (`vol.Required("points"): list`) and let the wrapper's `as_pairs` do the real
> coercion/validation (so a bad point raises ValueError in the wrapper, which the
> handler catches). Do NOT over-constrain in voluptuous; the unit tests for
> shape/point validation live at the wrapper layer. Apply the same `list` shape
> to `line_start`/`line_end` (a 2-list) and `zones` (a list).

Handlers (each catches ValueError):
```python
async def _handle_create_no_go_zone(call: ServiceCall) -> None:
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    try:
        await coordinator.create_no_go(
            int(call.data["map_id"]), call.data["shape"],
            call.data["points"], float(call.data.get("radius", 0.0)),
        )
    except ValueError as err:
        LOGGER.warning("create_no_go_zone: %s", err)
```
(Write the analogous `_handle_create_ignore_obstacle`, `_handle_create_mow_shape`, `_handle_split_zone`, `_handle_merge_zones`, each resolving the coordinator, calling the wrapper with the right args, and catching ValueError.)

Register all five (match the existing call style) and add the five `SERVICE_` constants to the unregister tuple (~line 796).

Add all five to `services.yaml` with fields + selectors. Use `selector: { object: {} }` for `points`/`line_start`/`line_end`/`zones` (free-form lists), `vol.In` choices for `shape` as a `select` selector, and note in each description that coords are **map edit-frame meters** and that editing a non-active map makes it active. Flag `split_zone`/`merge_zones` as **destructive**. Example:
```yaml
create_no_go_zone:
  name: Create no-go zone
  description: Create a no-go area / virtual wall on a map. points are [x, y] pairs in map edit-frame metres. Editing a non-active map makes it active.
  fields:
    map_id: { name: Map ID, required: true, example: 0, selector: { number: { min: 0, max: 10, mode: box } } }
    shape:
      name: Shape
      required: true
      example: polygon
      selector: { select: { options: [line, polygon, circle] } }
    points:
      name: Points
      description: List of [x, y] metre pairs. line=2, polygon>=3, circle=1 (centre).
      required: true
      example: "[[9.65, -0.13], [4.12, -0.13], [4.12, 5.01]]"
      selector: { object: {} }
    radius:
      name: Radius (m)
      description: Circle radius in metres (circle shape only).
      required: false
      example: 1.5
      selector: { number: { min: 0, max: 50, step: 0.1, mode: box } }
```
(Write the analogous yaml blocks for create_ignore_obstacle [map_id, points], create_mow_shape [map_id, shape (square/circle/heart/triangle/teardrop/mushroom/cloud/rainbow), points], split_zone [map_id, zone, line_start, line_end — DESTRUCTIVE], merge_zones [map_id, zones — DESTRUCTIVE].)

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_create_services.py -q`
Expected: PASS.

- [ ] **Step 5: Verify services.yaml parses + the service tests + nearby service tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -c "import yaml; yaml.safe_load(open('custom_components/dreame_a2_mower/services.yaml')); print('yaml ok')"`
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_create_services.py tests/integration/test_map_edit_services.py -q`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/services.py custom_components/dreame_a2_mower/services.yaml tests/integration/test_map_create_services.py
git commit -m "feat(map-edit): create/split/merge services"
```

---

### Task 4: Fact discipline (inventory + roadmap + knowledge-gaps)

**Files:**
- Modify: `inventory.yaml`, `docs/research/app-integration-roadmap.md`, `docs/research/knowledge-gaps.md`

- [ ] **Step 1: Add create/split/merge verifications to `inventory.yaml`**

Find the `o215`/`o234`/`o220`/`o221` map-edit entries (part 1 anchored a transaction record on `o204`; grep `o215`, `o220`, `o221`, `o234`, or `map_edit`). Add a `verified` record (taxonomy `status: verified` + `evidence:`, matching neighbours) capturing the confirmed payload shapes + the `o=215` type table, tagged `[app-mitm:2026-06-09-map-edit]`:
```yaml
      - status: verified
        date: 2026-06-12
        claim: "Map create/split/merge wired via the o=204/o=201 edit transaction. o=215{id:-1,type,points,radius}: type 1=no-go line(2pt), 2=no-go polygon(Npt), 3=no-go circle(1pt+radius m); decorative mow-shapes 9=square(4pt),12=circle,13=heart,14=triangle,15=teardrop,16=mushroom,17=cloud,18=rainbow (2pt bbox). o=234{id:-1,type:0,points}=ignore-obstacle (no radius). o=220{id,line_start,line_end}=split zone (destructive). o=221{ids:[...]}=merge zones (destructive). Coords in metres. [app-mitm:2026-06-09-map-edit]"
        evidence: "dreame-app-capture-2026-06-09/miio-cloud-13267-http.jsonl (o:215/234/220/221 payloads); shape names from IMG_4615.PNG (Shapes screen)"
```
(If a single existing entry is the natural anchor, attach there; otherwise add to the `o215` entry. Do not duplicate part-1's `o204`/`o218`/`o219` records.)

- [ ] **Step 2: Roadmap F advance**

In `docs/research/app-integration-roadmap.md`, update row F to reflect create/split/merge now wired (services `create_no_go_zone`/`create_ignore_obstacle`/`create_mow_shape`/`split_zone`/`merge_zones`, v1.0.25a7, 2026-06-12). Remaining: F2b interactive draw card (+ edit-frame↔render-frame verification); rename-map/delete-map (uncaptured); draw-by-driving (BT).

- [ ] **Step 3: Knowledge-gaps**

In `docs/research/knowledge-gaps.md`, update the map-edit section: create (o=215/o=234) + split/merge (o=220/o=221) are now WIRED (move out of "deferred"). Keep as open: the F2b interactive draw card + the edit-frame↔render-frame coordinate verification (does an o=215 meter point land where projectPoint expects, or is the edit frame reflected/rotated vs the renderer frame); rename-map/delete-map uncaptured; mow-shape type 10/11 gap (unused).

- [ ] **Step 4: Verify gates**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q -k "inventory or audit or census or honesty"`
Expected: PASS. Match neighbouring record field shapes if the validator complains. Confirm yaml parses:
`/data/claude/homeassistant/.venv-vanilla/bin/python -c "import yaml; yaml.safe_load(open('custom_components/dreame_a2_mower/inventory.yaml')); print('ok')"`

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml docs/research/app-integration-roadmap.md docs/research/knowledge-gaps.md
git commit -m "docs(map-edit): create/split/merge verifications + roadmap + knowledge-gaps"
```

---

### Task 5: Full suite + gates (no version bump — release.sh owns it)

- [ ] **Step 1: Run the full test suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q`
Expected: PASS (baseline 2180 passed / 4 skipped from Phase F part 1, plus the new tests; report the new totals). Do NOT edit `manifest.json` — `release.sh` performs the bump.

- [ ] **Step 2: Confirm no new entities broke the state-machine audit**

The audit was checked in Task 4 Step 4. No new entities are expected (services only). If red and due to a new entity, add honest expectations rows (don't weaken the gate) and verify against `main` that the red is new to this branch.

---

## Self-Review (completed)

- **Spec coverage:** pure helpers (T1), wrappers (T2), services (T3), fact discipline (T4), suite/gates (T5). All spec sections mapped.
- **Placeholders:** none — every step has concrete code/commands; the `points` voluptuous-schema implementer note fixes the one ambiguous spot (keep it `list`, validate in the wrapper).
- **Type/name consistency:** helpers `nogo_type`/`mow_shape_type`/`as_pairs`/`pair`/`validate_nogo`/`validate_mow_shape`; wrappers `create_no_go(map_id, shape, points, radius=0.0)`, `create_ignore_obstacle(map_id, points)`, `create_mow_shape(map_id, shape, points)`, `split_zone(map_id, zone_id, line_start, line_end)`, `merge_zones(map_id, ids)`; all emit `(opcode, payload)` mutations via `edit_map`. Service handler names `_handle_create_no_go_zone`/`_handle_create_ignore_obstacle`/`_handle_create_mow_shape`/`_handle_split_zone`/`_handle_merge_zones` consistent across T3. Wire payloads match the capture exactly.
