# Patrol-point surfacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface predefined cruise (patrol) points on the map and let the user launch point patrols (op=107) and edge patrols (op=108) from HA via a generic multi-select card.

**Architecture:** Parse `MAP.cruisePoints` (type=8) into `MapData.patrol_points`; render them as green "P" markers; expose patrol points and edge contours as two per-map sensors using a generic `items` attribute; add `start_point_patrol`/`start_edge_patrol` actions+services that route to op=107/108; a generic Lovelace card reads any `items` sensor and calls the configured service. Read-only (no map edits). o107/o108 SEND shapes ship `[UNVERIFIED]` until a live launch confirms `status:true`.

**Tech Stack:** Python 3.13, Home Assistant entity/service platforms (stubbed in the vanilla venv), Pillow (map render), pytest, a vanilla-JS custom element.

**Spec:** `docs/superpowers/specs/2026-06-04-patrol-point-surfacing-design.md`
**Test runner:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest`
**Commit policy:** feature branch (see Task 0); stage by explicit path; end commit messages with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- `custom_components/dreame_a2_mower/map_decoder.py` — `PatrolPoint` dataclass, `_parse_cruise_points`, `MapData.patrol_points` (Task 1).
- `custom_components/dreame_a2_mower/map_render/_geometry.py` + `map_render/base_map.py` — green-"P" marker (Task 2).
- `custom_components/dreame_a2_mower/sensor_map.py` + `sensor.py` + `entity-inventory.yaml` — two `items` sensors (Task 3).
- `custom_components/dreame_a2_mower/mower/actions.py` — two actions + payloads (Task 4).
- `custom_components/dreame_a2_mower/coordinator/_writes.py` — two coordinator methods (Task 5).
- `custom_components/dreame_a2_mower/services.yaml` + `services.py` — two services (Task 6).
- `custom_components/dreame_a2_mower/www/dreame-multi-select-card.js` + `dashboards/mower/dashboard.yaml` — generic card (Task 7).
- `custom_components/dreame_a2_mower/inventory.yaml` — o107/o108 SEND `[UNVERIFIED]` (Task 8).

---

## Task 0: Branch

- [ ] **Step 1: Create the feature branch**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git checkout main && git pull --ff-only origin main
git checkout -b feat/patrol-point-surfacing
```

---

## Task 1: Parse cruise points → `MapData.patrol_points`

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_decoder.py`
- Test: `tests/protocol/test_cruise_points.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/protocol/test_cruise_points.py`:

```python
"""cruisePoints (patrol points, type=8) parsing."""
from custom_components.dreame_a2_mower.map_decoder import (
    PatrolPoint, _parse_cruise_points,
)

_CLOUD = {
    "cruisePoints": {"dataType": "Map", "value": [
        [3, {"id": 3, "type": 8, "shapeType": 5, "path": [{"x": -3050, "y": -5480}], "time": 60, "etime": 60}],
        [4, {"id": 4, "type": 8, "shapeType": 5, "path": [{"x": -1980, "y": 6340}], "time": 60, "etime": 60}],
    ]}
}


def test_parse_cruise_points_basic():
    pts = _parse_cruise_points(_CLOUD)
    assert pts == [
        PatrolPoint(point_id=3, x_mm=-3050.0, y_mm=-5480.0),
        PatrolPoint(point_id=4, x_mm=-1980.0, y_mm=6340.0),
    ]


def test_parse_cruise_points_empty():
    assert _parse_cruise_points({"cruisePoints": {"dataType": "Map", "value": []}}) == []
    assert _parse_cruise_points({}) == []


def test_parse_cruise_points_skips_pathless():
    bad = {"cruisePoints": {"value": [[9, {"id": 9, "type": 8}]]}}  # no path
    assert _parse_cruise_points(bad) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_cruise_points.py -q`
Expected: FAIL — `ImportError: cannot import name 'PatrolPoint'`.

- [ ] **Step 3: Add `PatrolPoint` + `_parse_cruise_points`**

In `map_decoder.py`, immediately AFTER the `MaintenancePoint` dataclass (ends ~line 157), add:

```python
@dataclass(frozen=True, slots=True)
class PatrolPoint:
    """Cruise / patrol point in raw cloud-frame mm.

    From the MAP blob key ``cruisePoints`` (type=8) — distinct from
    maintenance ``cleanPoints`` (type=6). Coordinates kept in the cloud
    frame, mirroring MaintenancePoint.
    """

    point_id: int
    x_mm: float
    y_mm: float
```

Then, immediately AFTER `_parse_maintenance_points` (ends ~line 473), add:

```python
def _parse_cruise_points(cloud_response: dict[str, Any]) -> list[PatrolPoint]:
    """Parse ``cruisePoints`` (patrol points, type=8) into PatrolPoint objects.

    Same wrapper shape as ``cleanPoints``:
    ``{dataType, value: [[id, {path:[{x,y}], type, ...}], ...]}``.
    Coordinates kept in raw cloud-frame mm.
    """
    pp_out: list[PatrolPoint] = []
    cruise_raw = cloud_response.get("cruisePoints", {})
    cp_entries = cruise_raw.get("value", []) if isinstance(cruise_raw, dict) else []
    for entry in cp_entries:
        if isinstance(entry, list) and len(entry) >= 2:
            point_id = entry[0]
            pdata = entry[1]
        elif isinstance(entry, dict):
            point_id = entry.get("id", 1)
            pdata = entry
        else:
            continue
        point_path = pdata.get("path") or []
        if not point_path:
            continue
        try:
            pt = point_path[0]
            pid = int(point_id) if isinstance(point_id, (int, float)) else int(pdata.get("id", len(pp_out) + 1))
            pp_out.append(PatrolPoint(point_id=pid, x_mm=float(pt["x"]), y_mm=float(pt["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    return pp_out
```

- [ ] **Step 4: Run to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_cruise_points.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Add the `MapData.patrol_points` field + populate it**

In `map_decoder.py`, in the `MapData` dataclass, add the field immediately AFTER `maintenance_points: tuple[MaintenancePoint, ...]` (~line 256) and BEFORE `dock_xy`:

```python
    patrol_points: tuple[PatrolPoint, ...]
```

In the decode function, immediately AFTER `mp_out = _parse_maintenance_points(cloud_response)` (~line 708), add:

```python
    pp_out = _parse_cruise_points(cloud_response)
```

In the `return MapData(...)` construction (~line 774), add this line immediately after `maintenance_points=tuple(mp_out),`:

```python
        patrol_points=tuple(pp_out),
```

- [ ] **Step 6: Add a MapData-construction test + run the full map_decoder suite**

Append to `tests/protocol/test_cruise_points.py`:

```python
def test_mapdata_carries_patrol_points_field():
    from custom_components.dreame_a2_mower.map_decoder import MapData
    assert "patrol_points" in MapData.__dataclass_fields__
```

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_cruise_points.py $(ls tests/protocol/*map_decoder* tests/protocol/*map_parse* 2>/dev/null) -q`
Expected: PASS (existing map_decoder tests still pass — the new field is always passed in construction, so no decode test breaks).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/map_decoder.py tests/protocol/test_cruise_points.py
git commit -m "feat(map): parse cruisePoints (type=8) into MapData.patrol_points

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Render green "P" patrol markers on the base map

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render/_geometry.py`, `map_render/base_map.py`
- Test: `tests/protocol/test_patrol_render.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/protocol/test_patrol_render.py`:

```python
"""Patrol points render as a green 'P' marker on the base map."""
from custom_components.dreame_a2_mower.map_render import render_base_map
from custom_components.dreame_a2_mower.map_decoder import PatrolPoint


class _FakeMap:
    """Minimal MapData stand-in for the renderer (only the fields it reads)."""
    md5 = "x"; width_px = 40; height_px = 40; pixel_size_mm = 50.0
    bx1 = 0.0; by1 = 0.0; bx2 = 2000.0; by2 = 2000.0
    cloud_x_reflect = 2000.0; cloud_y_reflect = 2000.0; rotation_deg = 0.0
    boundary_polygon = ((0.0, 0.0), (2000.0, 0.0), (2000.0, 2000.0), (0.0, 2000.0))
    mowing_zones = (); exclusion_zones = (); spot_zones = ()
    contour_paths = (); available_contour_ids = ()
    maintenance_points = ()
    patrol_points = (PatrolPoint(point_id=3, x_mm=1000.0, y_mm=1000.0),)
    dock_xy = None; total_area_m2 = 0.0; nav_paths = (); map_id = 0; name = ""


def _has_greenish_pixel(img):
    for px in img.convert("RGBA").getdata():
        r, g, b, a = px
        if a > 0 and g > 120 and g > r + 30 and g > b + 30:
            return True
    return False


def test_patrol_point_draws_green_marker():
    img = render_base_map(_FakeMap())
    assert _has_greenish_pixel(img), "expected a green patrol-point marker pixel"


def test_no_patrol_points_no_crash():
    m = _FakeMap(); m.patrol_points = ()
    render_base_map(m)  # must not raise
```

Note: if `render_base_map` returns PNG bytes rather than a PIL image in this repo, open it with `PIL.Image.open(io.BytesIO(...))` first — check the existing base-map render test (`grep -rl render_base_map tests/`) and match its return-handling.

- [ ] **Step 2: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_patrol_render.py -q`
Expected: FAIL (no green marker drawn).

- [ ] **Step 3: Add patrol-marker palette constants**

In `map_render/_geometry.py`, immediately AFTER the maintenance-point block (the `"mp_text": (255, 255, 255, 255),` line ~72), add:

```python
    # Patrol / cruise points — green circle 2x dock radius with white "P".
    "pp_fill": (60, 170, 90, 220),
    "pp_outline": (20, 90, 40, 255),
    "pp_text": (255, 255, 255, 255),
```

- [ ] **Step 4: Add the patrol-point render block**

In `map_render/base_map.py`, immediately AFTER the maintenance-point render block (ends ~line 379, the `image.paste(glyph, …)` call), add a parallel block (same structure, "P" glyph, `pp_` colours):

```python
    # -----------------------------------------------------------------------
    # 3.6. Patrol / cruise points — green 2× dock-radius circles with a "P"
    #      glyph. Same pattern as maintenance points (3.5). cruisePoints come
    #      in cloud-frame mm — use _cloud_to_px. The glyph is rotated 180° to
    #      cancel the canvas-end FLIP_TOP_BOTTOM (same trick as the "M").
    # -----------------------------------------------------------------------
    for pp in getattr(map_data, "patrol_points", ()) or ():
        ppx, ppy = _cloud_to_px(
            float(pp.x_mm), float(pp.y_mm), bx2, by2, grid,
        )
        draw.ellipse(
            [ppx - mp_radius_px, ppy - mp_radius_px,
             ppx + mp_radius_px, ppy + mp_radius_px],
            fill=p["pp_fill"],
            outline=p["pp_outline"],
            width=2,
        )
        try:
            font = ImageFont.truetype(
                "DejaVuSans-Bold.ttf", size=int(mp_radius_px * 1.4)
            )
        except (OSError, IOError):
            font = ImageFont.load_default()
        glyph_size = int(mp_radius_px * 3)
        glyph = Image.new("RGBA", (glyph_size, glyph_size), (0, 0, 0, 0))
        glyph_draw = ImageDraw.Draw(glyph)
        glyph_draw.text(
            (glyph_size / 2, glyph_size / 2),
            "P",
            fill=p["pp_text"],
            font=font,
            anchor="mm",
        )
        glyph = glyph.rotate(180)
        image.paste(
            glyph,
            (int(ppx - glyph_size / 2), int(ppy - glyph_size / 2)),
            glyph,
        )
```

(`mp_radius_px`, `draw`, `image`, `p`, `bx2`, `by2`, `grid`, `_cloud_to_px`, `ImageFont`, `Image`, `ImageDraw` are all already in scope from the maintenance block above.)

- [ ] **Step 5: Run to verify it passes + no render regressions**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_patrol_render.py $(ls tests/protocol/*render* tests/protocol/*base_map* 2>/dev/null) -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render/_geometry.py custom_components/dreame_a2_mower/map_render/base_map.py tests/protocol/test_patrol_render.py
git commit -m "feat(render): green 'P' markers for patrol points on the base map

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Two per-map `items` sensors (patrol points + patrol edges)

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor_map.py`, `sensor.py`, `entity-inventory.yaml`
- Test: `tests/integration/test_patrol_sensors.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_patrol_sensors.py`. Inspect an existing per-map sensor test (`grep -rl DreameA2MaintenancePointsSensor tests/`) for the coordinator-stub idiom, then:

```python
from unittest.mock import MagicMock
from custom_components.dreame_a2_mower.sensor_map import (
    DreameA2PatrolPointsSensor, DreameA2PatrolEdgesSensor,
)
from custom_components.dreame_a2_mower.map_decoder import PatrolPoint


def _coord_with_map(map_obj):
    coord = MagicMock()
    coord.cloud_state.maps_by_id = {0: map_obj}
    return coord


def test_patrol_points_sensor_items():
    m = MagicMock()
    m.name = "Map 1"
    m.patrol_points = (PatrolPoint(3, -3050.0, -5480.0), PatrolPoint(4, -1980.0, 6340.0))
    s = DreameA2PatrolPointsSensor(_coord_with_map(m), map_id=0)
    assert s.native_value == 2
    items = s.extra_state_attributes["items"]
    assert items[0] == {"id": 3, "label": "Patrol point 3", "x_mm": -3050.0,
                        "y_mm": -5480.0, "cycles": None, "auto_capture": None}


def test_patrol_edges_sensor_items_outer_only():
    m = MagicMock()
    m.name = "Map 1"
    m.available_contour_ids = ((1, 0), (1, 1), (2, 0))  # inner seam (1,1) excluded
    s = DreameA2PatrolEdgesSensor(_coord_with_map(m), map_id=0)
    assert s.native_value == 2
    items = s.extra_state_attributes["items"]
    assert items == [{"id": [1, 0], "label": "Edge 1"}, {"id": [2, 0], "label": "Edge 2"}]
```

- [ ] **Step 2: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_sensors.py -q`
Expected: FAIL — classes not defined.

- [ ] **Step 3: Add the two sensor classes**

In `sensor_map.py`, after `DreameA2MaintenancePointsSensor` (ends ~line 102), add:

```python
class DreameA2PatrolPointsSensor(_DreameA2PerMapSensorBase):
    """Per-map list of patrol (cruise) points.

    State = count; ``extra_state_attributes['items']`` is the generic
    multi-select shape consumed by dreame-multi-select-card. Decoded from
    MAP key ``cruisePoints`` (type=8). Read-only; placement is app-only.
    cycles/auto_capture are null — not readable from any known surface yet.
    """

    _attr_name = "Patrol points"
    _attr_icon = "mdi:map-marker-path"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "patrol_points"

    def _compute_value(self, m):
        return len(getattr(m, "patrol_points", None) or ())

    @property
    def extra_state_attributes(self):
        m = self._map()
        pts = (getattr(m, "patrol_points", None) or ()) if m is not None else ()
        return {
            "items": [
                {
                    "id": p.point_id,
                    "label": f"Patrol point {p.point_id}",
                    "x_mm": p.x_mm,
                    "y_mm": p.y_mm,
                    "cycles": None,
                    "auto_capture": None,
                }
                for p in pts
            ]
        }


class DreameA2PatrolEdgesSensor(_DreameA2PerMapSensorBase):
    """Per-map list of edge-patrol targets (outer-perimeter contours).

    State = count; ``extra_state_attributes['items']`` is the generic
    multi-select shape; each item's ``id`` is the ``[m, c]`` contour pair the
    op=108 payload needs. Only outer perimeters (c == 0) are offered, matching
    the app's per-zone edge selection.
    """

    _attr_name = "Patrol edges"
    _attr_icon = "mdi:vector-square"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _KEY = "patrol_edges"

    def _outer(self, m):
        cids = getattr(m, "available_contour_ids", None) or ()
        return [cid for cid in cids if len(cid) == 2 and cid[1] == 0]

    def _compute_value(self, m):
        return len(self._outer(m))

    @property
    def extra_state_attributes(self):
        m = self._map()
        outer = self._outer(m) if m is not None else []
        return {"items": [{"id": [cid[0], cid[1]], "label": f"Edge {cid[0]}"} for cid in outer]}
```

(Confirm `SensorStateClass` is already imported in `sensor_map.py`; the maintenance sensor uses it, so it is.)

- [ ] **Step 4: Register them in `async_setup_entry`**

In `sensor.py`, in the per-map loop (~line 95), add both classes to the `entities.extend([...])` list (next to `DreameA2MaintenancePointsSensor(coordinator, map_id=map_id),`):

```python
            DreameA2PatrolPointsSensor(coordinator, map_id=map_id),
            DreameA2PatrolEdgesSensor(coordinator, map_id=map_id),
```

Add them to the `from .sensor_map import (...)` import block in `sensor.py` (grep `from .sensor_map import` to find it).

- [ ] **Step 5: Run to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_sensors.py tests/inventory/ -q`
Expected: PASS — but `tests/inventory/test_entity_inventory_coverage.py` may FAIL now (two new entity classes lack inventory rows). Fix in Step 6.

- [ ] **Step 6: Add entity-inventory rows**

In `entity-inventory.yaml`, after the `sensor.dreame_a2_mower_map_N_maintenance_points` row (~line 453), add:

```yaml
  - id: "sensor.dreame_a2_mower_map_N_patrol_points"
    platform: sensor
    class: "DreameA2PatrolPointsSensor"
    class_file: "custom_components/dreame_a2_mower/sensor_map.py"
    device: per-map
    source:
      wire: "cloud MAP blob (cruisePoints, type=8)"
      state_path: "len(coordinator.cloud_state.maps_by_id[map_id].patrol_points)"
    write_path: read-only
    status:
      seen_working: false
      last_verified: "2026-06-04"
    verifications:
      - date: "2026-06-04"
        status: verified
        claim: "state = count of MapData.patrol_points; extra_state_attributes['items'] = [{id,label,x_mm,y_mm,cycles:null,auto_capture:null}]. cruisePoints live-confirmed type=8."
        evidence: "live fetch_map 2026-06-04 (cruisePoints ids 3,4,5); map_decoder._parse_cruise_points"
    references:
      wire_entry: "o107"
      code: "custom_components/dreame_a2_mower/sensor_map.py"
    notes: |
      Generic `items` attribute consumed by dreame-multi-select-card. cycles/
      auto_capture are null — not readable from any known cloud surface yet.

  - id: "sensor.dreame_a2_mower_map_N_patrol_edges"
    platform: sensor
    class: "DreameA2PatrolEdgesSensor"
    class_file: "custom_components/dreame_a2_mower/sensor_map.py"
    device: per-map
    source:
      wire: "cloud MAP blob (contours / available_contour_ids, outer perimeters c==0)"
      state_path: "outer-perimeter contour pairs of coordinator.cloud_state.maps_by_id[map_id].available_contour_ids"
    write_path: read-only
    status:
      seen_working: false
      last_verified: "2026-06-04"
    verifications:
      - date: "2026-06-04"
        status: presumed
        claim: "items = [{id:[m,0], label:'Edge m'}] for outer-perimeter contours; feeds the op=108 edge-patrol payload {edge:[[m,0]]}."
    references:
      wire_entry: "o108"
      code: "custom_components/dreame_a2_mower/sensor_map.py"
    notes: |
      Reuses available_contour_ids (already parsed for edge-mow). Generic
      `items` attribute consumed by dreame-multi-select-card.
```

- [ ] **Step 7: Run inventory gates**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/entity_inventory_audit.py` (expect exit 0)
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_sensors.py tests/inventory/ -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor_map.py custom_components/dreame_a2_mower/sensor.py custom_components/dreame_a2_mower/entity-inventory.yaml tests/integration/test_patrol_sensors.py
git commit -m "feat(sensor): per-map patrol_points + patrol_edges sensors (generic items attr)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `START_POINT_PATROL` + `START_EDGE_PATROL` actions

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/actions.py`
- Test: `tests/integration/test_patrol_actions.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_patrol_actions.py`:

```python
import pytest
from custom_components.dreame_a2_mower.mower.actions import (
    MowerAction, ACTION_TABLE, _point_patrol_payload, _edge_patrol_payload,
)


def test_point_patrol_payload():
    assert _point_patrol_payload({"point_ids": [3, 4, 5]}) == {"point": [3, 4, 5]}
    with pytest.raises(ValueError):
        _point_patrol_payload({"point_ids": []})


def test_edge_patrol_payload():
    assert _edge_patrol_payload({"contour_ids": [[1, 0]]}) == {"edge": [[1, 0]]}
    with pytest.raises(ValueError):
        _edge_patrol_payload({"contour_ids": []})


def test_action_table_entries():
    assert ACTION_TABLE[MowerAction.START_POINT_PATROL]["routed_o"] == 107
    assert ACTION_TABLE[MowerAction.START_POINT_PATROL]["payload_fn"] is _point_patrol_payload
    assert ACTION_TABLE[MowerAction.START_EDGE_PATROL]["routed_o"] == 108
    assert ACTION_TABLE[MowerAction.START_EDGE_PATROL]["payload_fn"] is _edge_patrol_payload
```

- [ ] **Step 2: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_actions.py -q`
Expected: FAIL — names not defined.

- [ ] **Step 3: Add enum members, payload builders, ACTION_TABLE entries**

In `mower/actions.py`, add to the `MowerAction` enum (after `SET_ACTIVE_MAP = auto()`):

```python
    START_POINT_PATROL = auto()  # op=107 startCruisePoint — point patrol
    START_EDGE_PATROL = auto()   # op=108 startCruiseSide — edge patrol
```

After `_go_to_point_payload` (~line 164), add:

```python
def _point_patrol_payload(params: dict[str, Any]) -> dict[str, Any]:
    """TASK envelope d-field for POINT patrol (op=107, startCruisePoint).

    [UNVERIFIED] SEND shape ``{"point":[ids]}`` — by direct analogy to the
    live-confirmed go-to-point (op=109 ``{"point":[id]}``), with a multi-element
    list (the patrol echo s2p56=[[3,0],[4,-1]] shows a 2-point queue). Confirm
    live; if rejected (status:false) the d-key is wrong, not the list. See
    inventory.yaml o107.
    """
    points = params.get("point_ids") or []
    if not points:
        raise ValueError("START_POINT_PATROL requires non-empty 'point_ids' list")
    return {"point": [int(p) for p in points]}


def _edge_patrol_payload(params: dict[str, Any]) -> dict[str, Any]:
    """TASK envelope d-field for EDGE patrol (op=108, startCruiseSide).

    [UNVERIFIED] SEND shape ``{"edge":[[m,c],...]}`` contour pairs — same d-key
    as edge-mow (op=101); the patrol echo s2p56=[[1,0,0]] matches contour id
    [1,0]. Confirm live; fall back to {"contour":…}/{"region":…} if rejected.
    See inventory.yaml o108.
    """
    contour_ids = params.get("contour_ids") or []
    if not contour_ids:
        raise ValueError("START_EDGE_PATROL requires non-empty 'contour_ids' list")
    return {"edge": [list(pair) for pair in contour_ids]}
```

In `ACTION_TABLE`, after the `GO_TO_POINT` entry (~line 214), add:

```python
    MowerAction.START_POINT_PATROL: {
        "siid": 5, "aiid": 1,
        "routed_t": "TASK", "routed_o": 107,
        "payload_fn": _point_patrol_payload,
    },
    MowerAction.START_EDGE_PATROL: {
        "siid": 5, "aiid": 1,
        "routed_t": "TASK", "routed_o": 108,
        "payload_fn": _edge_patrol_payload,
    },
```

- [ ] **Step 4: Run to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_actions.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/actions.py tests/integration/test_patrol_actions.py
git commit -m "feat(actions): START_POINT_PATROL (o107) + START_EDGE_PATROL (o108)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Coordinator `start_point_patrol` + `start_edge_patrol`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py`
- Test: `tests/integration/test_patrol_dispatch.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_patrol_dispatch.py`. Mirror the coordinator-stub idiom from an existing `start_mowing_spot`/`start_go_to_point` test (`grep -rl start_go_to_point tests/`):

```python
from unittest.mock import AsyncMock
import pytest
from custom_components.dreame_a2_mower.mower.actions import MowerAction


async def _make_coord():
    # Build a coordinator instance with dispatch/_ensure_active_map mocked.
    # Reuse the existing test's construction; here we patch the two seams.
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._ensure_active_map = AsyncMock()
    coord.dispatch_action = AsyncMock()
    return coord


async def test_start_point_patrol_routes():
    coord = await _make_coord()
    await coord.start_point_patrol(map_id=0, point_ids=[3, 4])
    coord._ensure_active_map.assert_awaited_once_with(0)
    coord.dispatch_action.assert_awaited_once_with(
        MowerAction.START_POINT_PATROL, {"point_ids": [3, 4]})


async def test_start_edge_patrol_routes():
    coord = await _make_coord()
    await coord.start_edge_patrol(map_id=0, contour_ids=[[1, 0]])
    coord._ensure_active_map.assert_awaited_once_with(0)
    coord.dispatch_action.assert_awaited_once_with(
        MowerAction.START_EDGE_PATROL, {"contour_ids": [[1, 0]]})
```

If `DreameA2MowerCoordinator.__new__` + attribute patching doesn't work cleanly (mixin MRO), instead copy the exact coordinator-fixture construction the existing `start_go_to_point` test uses and patch `_ensure_active_map`/`dispatch_action` on that instance.

- [ ] **Step 2: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_dispatch.py -q`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Add the two coordinator methods**

In `coordinator/_writes.py`, immediately AFTER `start_go_to_point` (~line 546), add:

```python
    async def start_point_patrol(self, *, map_id: int, point_ids: list[int]) -> None:
        """Launch a POINT patrol (op=107) over the given cruise points on map_id.

        point_ids are per-map cruisePoint ids, so the map must be active first.
        SEND shape is [UNVERIFIED] — see actions._point_patrol_payload / o107.
        """
        await self._ensure_active_map(map_id)
        await self.dispatch_action(
            MowerAction.START_POINT_PATROL, {"point_ids": [int(i) for i in point_ids]}
        )

    async def start_edge_patrol(self, *, map_id: int, contour_ids: list[list[int]]) -> None:
        """Launch an EDGE patrol (op=108) over the given contour pairs on map_id.

        contour_ids are [m, c] pairs (outer perimeters). SEND shape is
        [UNVERIFIED] — see actions._edge_patrol_payload / o108.
        """
        await self._ensure_active_map(map_id)
        await self.dispatch_action(
            MowerAction.START_EDGE_PATROL, {"contour_ids": [list(c) for c in contour_ids]}
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_dispatch.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_writes.py tests/integration/test_patrol_dispatch.py
git commit -m "feat(coordinator): start_point_patrol + start_edge_patrol (ensure-active-map then dispatch)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Services `start_point_patrol` + `start_edge_patrol`

**Files:**
- Modify: `custom_components/dreame_a2_mower/services.yaml`, `services.py`
- Test: `tests/integration/test_patrol_services.py` (create)

- [ ] **Step 1: Read the existing mow_spot wiring**

Run: `grep -n 'SERVICE_MOW_SPOT\|SCHEMA_MOW_SPOT\|_handle_mow_spot\|def _coordinator\|hass.data\[DOMAIN\]\|async_unregister_services' custom_components/dreame_a2_mower/services.py`
Read `_handle_mow_spot` and the schema + the coordinator-retrieval helper it uses. Mirror that exact idiom (how it gets the coordinator from `hass.data`, how it resolves a default map_id) in the new handlers below — match it rather than the illustrative version here.

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_patrol_services.py`:

```python
from unittest.mock import AsyncMock, MagicMock
from homeassistant.core import HomeAssistant  # stubbed in the vanilla venv
from custom_components.dreame_a2_mower.services import async_register_services
from custom_components.dreame_a2_mower.const import DOMAIN


async def test_start_point_patrol_service_calls_coordinator(hass: HomeAssistant, mock_entry_with_coordinator):
    # mock_entry_with_coordinator: reuse the existing services-test fixture that
    # puts a coordinator with AsyncMock methods into hass.data[DOMAIN]; grep
    # tests for the existing mow_spot service test fixture and mirror it.
    coord = mock_entry_with_coordinator
    coord.start_point_patrol = AsyncMock()
    await async_register_services(hass)
    await hass.services.async_call(
        DOMAIN, "start_point_patrol", {"map_id": 0, "point_ids": [3, 4]}, blocking=True)
    coord.start_point_patrol.assert_awaited_once()
```

If the repo's services tests don't use a `hass` fixture (vanilla venv stubs HA), copy the construction the existing `test_*mow_spot*`/`test_services*` file uses verbatim and adapt; the assertion (`coordinator.start_point_patrol` awaited with the ids) is the contract.

- [ ] **Step 3: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_services.py -q`
Expected: FAIL — service not registered.

- [ ] **Step 4: Add the service definitions to `services.yaml`**

Append to `services.yaml`:

```yaml
start_point_patrol:
  name: Start point patrol
  description: >
    Launch a point patrol (op=107) over the selected cruise points on a map.
    Cruise points are placed in the Dreame app; ids come from
    sensor.dreame_a2_mower_map_N_patrol_points (attribute items).
    SEND shape is provisional until live-confirmed.
  fields:
    map_id:
      description: Map id. Defaults to the active map if omitted.
      required: false
      example: 0
      selector:
        number: { min: 0, max: 10, step: 1, mode: box }
    point_ids:
      description: Cruise point ids to patrol.
      required: true
      example: "[3, 4]"
      selector:
        object:
start_edge_patrol:
  name: Start edge patrol
  description: >
    Launch an edge patrol (op=108) over the selected outer-perimeter contours.
    Contour pairs come from sensor.dreame_a2_mower_map_N_patrol_edges (items).
    SEND shape is provisional until live-confirmed.
  fields:
    map_id:
      description: Map id. Defaults to the active map if omitted.
      required: false
      example: 0
      selector:
        number: { min: 0, max: 10, step: 1, mode: box }
    contour_ids:
      description: Contour pairs [[m, c], ...] to patrol.
      required: true
      example: "[[1, 0]]"
      selector:
        object:
```

- [ ] **Step 5: Add handlers + registration to `services.py`**

Mirror the `mow_spot` block read in Step 1. Add string constants near the other `SERVICE_*`:

```python
SERVICE_START_POINT_PATROL = "start_point_patrol"
SERVICE_START_EDGE_PATROL = "start_edge_patrol"
```

Add schemas near the other `SCHEMA_*` (use the SAME `vol`/coordinator idiom as `SCHEMA_MOW_SPOT`):

```python
SCHEMA_START_POINT_PATROL = vol.Schema({
    vol.Optional("map_id"): vol.Coerce(int),
    vol.Required("point_ids"): [vol.Coerce(int)],
})
SCHEMA_START_EDGE_PATROL = vol.Schema({
    vol.Optional("map_id"): vol.Coerce(int),
    vol.Required("contour_ids"): [[vol.Coerce(int)]],
})
```

Add handlers (mirror `_handle_mow_spot`'s coordinator-retrieval idiom; `_get_coordinator(hass)`/`hass.data[DOMAIN]` — use whatever `_handle_mow_spot` uses):

```python
async def _handle_start_point_patrol(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call.hass)  # SAME helper _handle_mow_spot uses
    map_id = call.data.get("map_id")
    if map_id is None:
        map_id = getattr(coordinator, "_active_map_id", None) or 0
    await coordinator.start_point_patrol(map_id=int(map_id), point_ids=list(call.data["point_ids"]))


async def _handle_start_edge_patrol(call: ServiceCall) -> None:
    coordinator = _resolve_coordinator(call.hass)
    map_id = call.data.get("map_id")
    if map_id is None:
        map_id = getattr(coordinator, "_active_map_id", None) or 0
    await coordinator.start_edge_patrol(map_id=int(map_id), contour_ids=[list(c) for c in call.data["contour_ids"]])
```

Register them inside `async_register_services` (next to the `mow_spot` registration):

```python
    hass.services.async_register(DOMAIN, SERVICE_START_POINT_PATROL,
                                  _handle_start_point_patrol, schema=SCHEMA_START_POINT_PATROL)
    hass.services.async_register(DOMAIN, SERVICE_START_EDGE_PATROL,
                                  _handle_start_edge_patrol, schema=SCHEMA_START_EDGE_PATROL)
```

If `async_unregister_services` lists service names, add both there too.

- [ ] **Step 6: Run to verify it passes + service tests green**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_services.py $(ls tests/integration/*service* 2>/dev/null) -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/services.yaml custom_components/dreame_a2_mower/services.py tests/integration/test_patrol_services.py
git commit -m "feat(services): start_point_patrol + start_edge_patrol

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Generic multi-select card + dashboard wiring

**Files:**
- Create: `custom_components/dreame_a2_mower/www/dreame-multi-select-card.js`
- Modify: `dashboards/mower/dashboard.yaml`

- [ ] **Step 1: Create the generic card**

Create `custom_components/dreame_a2_mower/www/dreame-multi-select-card.js` (vanilla custom element, no build step; mirrors the `customElements.define` + `window.customCards.push` pattern of the existing bundled cards):

```javascript
// Generic multi-select card: reads `items` from a sensor attribute and calls a
// service with the checked item ids. Reusable across patrol points, patrol
// edges, and (later) zone/spot mow — set entity/service/id_param per instance.
class DreameMultiSelectCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("entity is required");
    if (!config.service) throw new Error("service is required (domain.service)");
    this._config = {
      items_attribute: "items",
      id_param: "ids",
      action_label: "Start",
      ...config,
    };
    this._checked = new Set();
    this._rendered = false;
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _items() {
    const st = this._hass && this._hass.states[this._config.entity];
    const attr = st && st.attributes[this._config.items_attribute];
    return Array.isArray(attr) ? attr : [];
  }

  _key(item) { return JSON.stringify(item.id); }

  _update() {
    const items = this._items();
    if (!this._rendered) {
      this.innerHTML = `
        <ha-card header="${this._config.title || ""}">
          <div class="dms-list" style="padding:0 16px"></div>
          <div style="padding:16px"><mwc-button raised class="dms-go"></mwc-button></div>
        </ha-card>`;
      this._list = this.querySelector(".dms-list");
      this._btn = this.querySelector(".dms-go");
      this._btn.textContent = this._config.action_label;
      this._btn.addEventListener("click", () => this._fire());
      this._rendered = true;
    }
    // Drop checks for items that disappeared.
    const present = new Set(items.map((i) => this._key(i)));
    for (const k of [...this._checked]) if (!present.has(k)) this._checked.delete(k);
    this._list.innerHTML = "";
    for (const item of items) {
      const k = this._key(item);
      const row = document.createElement("label");
      row.style.cssText = "display:flex;align-items:center;gap:8px;padding:4px 0;cursor:pointer";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = this._checked.has(k);
      cb.addEventListener("change", () => {
        if (cb.checked) this._checked.add(k); else this._checked.delete(k);
        this._btn.disabled = this._checked.size === 0;
      });
      const span = document.createElement("span");
      let extra = "";
      if (item.cycles != null) extra += ` ×${item.cycles}`;
      if (item.auto_capture != null) extra += item.auto_capture ? " 📷" : "";
      span.textContent = (item.label || k) + extra;
      row.appendChild(cb);
      row.appendChild(span);
      this._list.appendChild(row);
    }
    if (items.length === 0) this._list.textContent = "No items.";
    this._btn.disabled = this._checked.size === 0;
  }

  _fire() {
    const items = this._items();
    const ids = items.filter((i) => this._checked.has(this._key(i))).map((i) => i.id);
    if (ids.length === 0) return;
    const [domain, service] = this._config.service.split(".");
    const data = { [this._config.id_param]: ids };
    if (this._config.map_id != null) data.map_id = this._config.map_id;
    this._hass.callService(domain, service, data);
  }

  getCardSize() { return 3; }
}

if (!customElements.get("dreame-multi-select-card")) {
  customElements.define("dreame-multi-select-card", DreameMultiSelectCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "dreame-multi-select-card",
    name: "Dreame Multi-Select",
    description: "Pick items from a sensor's `items` attribute and call a service with the ids.",
  });
}
```

- [ ] **Step 2: Validate the JS parses**

Run: `node --check custom_components/dreame_a2_mower/www/dreame-multi-select-card.js` (if `node` is available) — expect no output (syntax OK). If `node` is unavailable, skip; the card is exercised manually in HA.

- [ ] **Step 3: Add two card instances to the dashboard**

In `dashboards/mower/dashboard.yaml`, on the Settings & Zones tab (or a new "Patrol" section — match the existing tab structure), add:

```yaml
              - type: custom:dreame-multi-select-card
                title: Point Patrol — Map 1
                entity: sensor.dreame_a2_mower_map_1_patrol_points
                service: dreame_a2_mower.start_point_patrol
                id_param: point_ids
                map_id: 0
                action_label: Start point patrol
              - type: custom:dreame-multi-select-card
                title: Edge Patrol — Map 1
                entity: sensor.dreame_a2_mower_map_1_patrol_edges
                service: dreame_a2_mower.start_edge_patrol
                id_param: contour_ids
                map_id: 0
                action_label: Start edge patrol
```

Add a comment in the dashboard header's "Required Lovelace resources" block:
```
#   - /dreame_a2_mower/dreame-multi-select-card.js  (generic multi-select; register as JavaScript Module)
```

- [ ] **Step 4: Validate the dashboard YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml')); print('OK')"`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-multi-select-card.js dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): generic dreame-multi-select-card + point/edge patrol instances

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(Deploy: copy the .js into HA's served path + register the resource (JavaScript Module) + SCP the dashboard per `reference_ha_dashboard_deploy` — out of plan scope; the user does this when testing.)

---

## Task 8: Inventory o107/o108 SEND `[UNVERIFIED]` + full-suite verify

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`
- Verify only otherwise.

- [ ] **Step 1: Record the shipped (provisional) SEND shapes**

In `inventory.yaml`, append a verification to the `o107` entry:

```yaml
      - date: "2026-06-04"
        status: partial
        claim: |
          The integration now SENDS op=107 as routed_action(107, {"point":[ids]})
          (ids from cruisePoints) via MowerAction.START_POINT_PATROL +
          coordinator.start_point_patrol. SEND shape [UNVERIFIED] — high-confidence
          by analogy to the live-confirmed go-to-point (o109 {"point":[id]}); flip
          to verified on first live s2p50 o:107 status:true.
        evidence: "mower/actions.py _point_patrol_payload + ACTION_TABLE; coordinator/_writes.py start_point_patrol"
```

And to the `o108` entry:

```yaml
      - date: "2026-06-04"
        status: partial
        claim: |
          The integration now SENDS op=108 as routed_action(108, {"edge":[[m,c]]})
          (outer-perimeter contour pairs) via MowerAction.START_EDGE_PATROL +
          coordinator.start_edge_patrol. SEND shape [UNVERIFIED] — the d-key `edge`
          mirrors edge-mow o:101 and the echo s2p56=[[1,0,0]] matches contour [1,0];
          flip to verified on first live s2p50 o:108 status:true.
        evidence: "mower/actions.py _edge_patrol_payload + ACTION_TABLE; coordinator/_writes.py start_edge_patrol"
```

- [ ] **Step 2: Validate inventory + regenerate canonical**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory_gen.py --validate-only` (expect `ok: inventory schema valid`)
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory_gen.py` (regenerate canonical)

- [ ] **Step 3: Full suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: all pass (baseline 1963 passed / 4 skipped before this feature; new tests add to the count, skipped stays 4).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "docs(inventory): o107/o108 SEND shapes shipped, tagged [UNVERIFIED]

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Update the TODO**

In `docs/TODO.md`, under the control-honesty residual or a new "Patrol" entry, note: point + edge patrol triggers shipped (o107/o108, SEND `[UNVERIFIED]` pending a live launch); cruise points rendered + selectable; cycles/auto-capture still need a source probe; zone/spot multi-select can now reuse the generic card. Commit + (on branch finish) push.

---

## Self-Review

**Spec coverage:**
- Parse `cruisePoints` (type=8) → `MapData.patrol_points` → Task 1. ✓
- Render green-"P" markers (mirror "M") → Task 2. ✓
- Two `items` sensors (patrol points + edges, generic attr) → Task 3. ✓
- `START_POINT_PATROL`/`START_EDGE_PATROL` actions + payloads → Task 4. ✓
- Coordinator `start_point_patrol`/`start_edge_patrol` (ensure-active-map) → Task 5. ✓
- `start_point_patrol`/`start_edge_patrol` services → Task 6. ✓
- Generic card (`items` attr + service, opaque ids) + two instances → Task 7. ✓
- Cycles/auto-capture reserved `null` (sensor + card) → Tasks 3, 7. ✓
- o107/o108 SEND `[UNVERIFIED]` → Task 8. ✓
- Read-only / no map edits → no write paths added; only reads + launch. ✓
- Edge items reuse `available_contour_ids` → Task 3 (no new parse). ✓

**Placeholder scan:** Tasks 1–5, 8 have complete code. Tasks 6 (services.py handler/coordinator-retrieval idiom) and 7-test rely on mirroring an existing local idiom (`_handle_mow_spot`, the services-test fixture) — flagged explicitly with a Step-1 "read it first" and the exact contract to assert; this is a known-pattern adaptation, not an undefined placeholder.

**Type/name consistency:** `PatrolPoint(point_id,x_mm,y_mm)`, `_parse_cruise_points`, `MapData.patrol_points`, `pp_fill/outline/text`, `DreameA2PatrolPointsSensor`/`DreameA2PatrolEdgesSensor` (`_KEY` `patrol_points`/`patrol_edges`, attr `items`), `MowerAction.START_POINT_PATROL`/`START_EDGE_PATROL`, `_point_patrol_payload`/`_edge_patrol_payload` (`point_ids`/`contour_ids` params → `{point:[…]}`/`{edge:[[…]]}`), `start_point_patrol`/`start_edge_patrol` (coordinator + service), `dreame-multi-select-card` (`items_attribute`/`id_param`) — consistent across tasks.

**Open risk for the implementer:** Task 6's `_resolve_coordinator`/`hass.data[DOMAIN]` idiom and the services-test fixture must be copied from the existing `mow_spot` service + its test (Step 1 reads them). Task 2's render test must match the existing base-map test's return-type handling (PIL image vs PNG bytes). Both flagged inline.
```
