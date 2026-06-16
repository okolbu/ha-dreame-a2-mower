# Patrol-point attributes (cycles + auto-capture) in the map editor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read and write a patrol point's per-point cycles (1/2/3) + auto-capture (on/off) from the dashboard map-editor card, and surface the read values on the patrol-points sensor.

**Architecture:** Parse the `CRUISE.0` device-data key (already in the cloud-state batch) into a per-map → per-point `{cycles, auto_capture}` map on `CloudState`; the patrol-points sensor and the camera's `editable_objects` read it. Writes go through a new `set_patrol_point_config` service → `coordinator.write_patrol_point_config` → `cloud_client.set_cfg("CRUISED", {idx, value})`. The map-editor card shows an inline panel on patrol-point select that calls the service and optimistically updates its own panel state.

**Tech Stack:** Python (HA custom integration, frozen dataclasses, voluptuous service schemas), vanilla-JS Lovelace card, pytest (stubbed-HA venv at `/data/claude/homeassistant/.venv-vanilla`), node for the card harness.

**Test interpreter:** `/data/claude/homeassistant/.venv-vanilla/bin/python` (system python3 is broken). Run pytest from the repo root `/data/claude/homeassistant/ha-dreame-a2-mower`.

**Concurrency note:** another agent edits `inventory.yaml` on a Mac without git; treat unexpected `inventory.yaml` diffs as theirs — never `git checkout` it; stage by explicit path.

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `protocol/cruise_config.py` | Pure parser: `CRUISE.0` JSON → `{map_idx: {point_id: {cycles, auto_capture}}}` | **Create** |
| `cloud_state.py` | `CloudState` frozen dataclass | **Modify** — add `cruise_config_by_map` field |
| `cloud_client/_fetchers.py` | `parse_full_cloud_state` | **Modify** — parse `CRUISE.0`, pass to `CloudState` |
| `entities/sensor/map.py` | `DreameA2PatrolPointsSensor` | **Modify** — fill `cycles`/`auto_capture` from cloud_state |
| `camera/map.py` | `editable_objects` patrol entries | **Modify** — add `cycles`/`auto_capture` |
| `coordinator/_writes.py` | `write_patrol_point_config` | **Modify** — add write method |
| `services.py` | `set_patrol_point_config` schema + handler + register | **Modify** |
| `services.yaml` | service doc | **Modify** |
| `www/dreame-map-editor-card.js` | inline cycles/auto-capture panel | **Modify** |
| `tests/protocol/test_cruise_config.py` | parser tests | **Create** |
| `tests/integration/test_patrol_point_config.py` | sensor/camera/write/service tests | **Create** |
| `tests/www/patrol_attr_panel_harness.mjs` + `test_patrol_attr_panel.py` | card harness | **Create** |

---

### Task 1: `CRUISE.0` parser (pure)

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/cruise_config.py`
- Test: `tests/protocol/test_cruise_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/protocol/test_cruise_config.py
from custom_components.dreame_a2_mower.protocol.cruise_config import parse_cruise_config


def test_parses_per_map_per_point():
    raw = (
        '[{"version":3,"settings":{"3":{"num":3,"ap":true}}},'
        '{"version":-1,"settings":{}}]'
    )
    out = parse_cruise_config(raw)
    assert out == {0: {3: {"cycles": 3, "auto_capture": True}}}


def test_accepts_already_parsed_list():
    raw = [{"version": 1, "settings": {"5": {"num": 1, "ap": False}}}]
    assert parse_cruise_config(raw) == {0: {5: {"cycles": 1, "auto_capture": False}}}


def test_skips_comma_key_and_bad_entries():
    raw = [{"version": 2, "settings": {
        "3": {"num": 2, "ap": True},
        "1,0": {"num": 1, "ap": True},   # comma-joined key — un-disambiguated, skip
        "7": {"ap": True},                # missing num — skip
        "9": "garbage",                   # non-dict — skip
    }}]
    assert parse_cruise_config(raw) == {0: {3: {"cycles": 2, "auto_capture": True}}}


def test_tolerates_garbage():
    assert parse_cruise_config(None) == {}
    assert parse_cruise_config("not json") == {}
    assert parse_cruise_config("{}") == {}      # dict, not the expected list
    assert parse_cruise_config("[]") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_cruise_config.py -q`
Expected: FAIL — `ModuleNotFoundError: ...protocol.cruise_config`

- [ ] **Step 3: Write the parser**

```python
# custom_components/dreame_a2_mower/protocol/cruise_config.py
"""Parse the CRUISE.0 device-data key into per-map per-point patrol config.

CRUISE.0 (sibling of MAP.* in the getDeviceData response) is a JSON-string
per-map outer array:
  [{version, settings:{<point_id>:{num:<cycles>, ap:<auto_capture bool>}}}, …]
element[i] = map index i; an unused map carries {version:-1, settings:{}}.
There is NO m:g getter on t:CRUISED (returns r=-3) — CRUISE.0 is the only read
path. See inventory.yaml § CRUISED. WRITE is the CRUISED CFG key.
"""
from __future__ import annotations

import json
from typing import Any

from ..const import LOGGER


def parse_cruise_config(raw: Any) -> dict[int, dict[int, dict[str, Any]]]:
    """Return ``{map_idx: {point_id: {"cycles": int, "auto_capture": bool}}}``.

    Tolerant: never raises. Non-JSON / wrong shape → ``{}``; ``version:-1`` or
    empty ``settings`` contribute nothing; entries missing ``num`` are skipped;
    non-integer settings keys (the un-disambiguated ``"1,0"`` comma-key) are
    skipped + debug-logged.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    if not isinstance(raw, list):
        return {}
    out: dict[int, dict[int, dict[str, Any]]] = {}
    for map_idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        settings = entry.get("settings")
        if not isinstance(settings, dict):
            continue
        per_point: dict[int, dict[str, Any]] = {}
        for key, val in settings.items():
            try:
                pid = int(key)
            except (TypeError, ValueError):
                LOGGER.debug("parse_cruise_config: skipping non-int point key %r", key)
                continue
            if not isinstance(val, dict) or "num" not in val:
                continue
            try:
                cycles = int(val["num"])
            except (TypeError, ValueError):
                continue
            per_point[pid] = {"cycles": cycles, "auto_capture": bool(val.get("ap"))}
        if per_point:
            out[map_idx] = per_point
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_cruise_config.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/cruise_config.py tests/protocol/test_cruise_config.py
git commit -m "feat(patrol): parse CRUISE.0 device-data into per-point cycles/auto-capture"
```

---

### Task 2: Add `cruise_config_by_map` to `CloudState` + populate it

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_state.py:111-127` (CloudState fields)
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py:523-537` (construction)
- Test: `tests/integration/test_patrol_point_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_patrol_point_config.py
from custom_components.dreame_a2_mower.cloud_state import CloudState


def _bare_cloud_state(**over):
    base = dict(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={}, settings=None,
        schedule=None, ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={}, mapl=None, mihis={},
        fetched_at_unix=0,
    )
    base.update(over)
    return CloudState(**base)


def test_cloud_state_has_cruise_config_default_empty():
    cs = _bare_cloud_state()
    assert cs.cruise_config_by_map == {}


def test_cloud_state_carries_cruise_config():
    cs = _bare_cloud_state(cruise_config_by_map={0: {3: {"cycles": 2, "auto_capture": True}}})
    assert cs.cruise_config_by_map[0][3]["cycles"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_point_config.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'cruise_config_by_map'`

- [ ] **Step 3: Add the field to `CloudState`**

In `cloud_state.py`, the `CloudState` dataclass (`@dataclass(frozen=True, slots=True)`), append after `fetched_at_unix: int` (last field):

```python
    fetched_at_unix: int
    # Per-map patrol-point config from the CRUISE.0 device-data key:
    # {map_idx: {point_id: {"cycles": int, "auto_capture": bool}}}. Empty when
    # CRUISE.0 is absent. See protocol/cruise_config.py + inventory.yaml § CRUISED.
    cruise_config_by_map: dict = field(default_factory=dict)
```

Ensure `from dataclasses import dataclass, field` is imported at the top of the file (it already uses `@dataclass`; add `field` to the import if missing).

- [ ] **Step 4: Populate it in `parse_full_cloud_state`**

In `cloud_client/_fetchers.py`, the local import line (~330) already does `from ..cloud_state import CloudState, ScheduleData, SettingsRoot`. Add the parser import beside it:

```python
        from ..cloud_state import CloudState, ScheduleData, SettingsRoot
        from ..protocol.cruise_config import parse_cruise_config
```

Then in the `return CloudState(` call (~523), add the new keyword (the batch dict is `batch`):

```python
            mihis=mihis,
            fetched_at_unix=int(_time.time()),
            cruise_config_by_map=parse_cruise_config(batch.get("CRUISE.0")),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_point_config.py -q`
Expected: PASS (2 passed)

- [ ] **Step 6: Run the cloud-state suite to confirm no constructor breakage**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "cloud_state or full_cloud_state or empty_batch" -q`
Expected: PASS (defaulted field — existing constructors unaffected). If a test constructs `CloudState` positionally and breaks, it will surface here — fix by passing the new kw or relying on the default.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_state.py custom_components/dreame_a2_mower/cloud_client/_fetchers.py tests/integration/test_patrol_point_config.py
git commit -m "feat(patrol): carry CRUISE.0 cruise_config_by_map on CloudState"
```

---

### Task 3: Fill the patrol-points sensor `cycles`/`auto_capture`

**Files:**
- Modify: `custom_components/dreame_a2_mower/entities/sensor/map.py:157-173`
- Test: `tests/integration/test_patrol_point_config.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_patrol_point_config.py
from types import SimpleNamespace
from unittest.mock import MagicMock


def _patrol_sensor(map_id, points, cruise_cfg):
    from custom_components.dreame_a2_mower.entities.sensor.map import DreameA2PatrolPointsSensor
    sensor = DreameA2PatrolPointsSensor.__new__(DreameA2PatrolPointsSensor)
    md = SimpleNamespace(patrol_points=points)
    sensor._map = lambda: md
    sensor.coordinator = SimpleNamespace(
        cloud_state=_bare_cloud_state(cruise_config_by_map=cruise_cfg)
    )
    sensor._map_id = map_id
    return sensor


def test_patrol_sensor_fills_cycles_and_auto_capture():
    pts = [SimpleNamespace(point_id=3, x_mm=-3050, y_mm=-5480)]
    s = _patrol_sensor(0, pts, {0: {3: {"cycles": 3, "auto_capture": True}}})
    item = s.extra_state_attributes["items"][0]
    assert item["cycles"] == 3 and item["auto_capture"] is True


def test_patrol_sensor_defaults_when_no_config():
    pts = [SimpleNamespace(point_id=4, x_mm=0, y_mm=0)]
    s = _patrol_sensor(0, pts, {})
    item = s.extra_state_attributes["items"][0]
    assert item["cycles"] == 1 and item["auto_capture"] is False
```

> Note: confirm the per-map sensor stores the map id as `self._map_id` (read `entities/sensor/map.py` `_DreameA2PerMapSensorBase`). If the attribute differs, use the real one in both the test and the implementation.

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_point_config.py -k patrol_sensor -q`
Expected: FAIL — `cycles` is `None`, not `3`/`1`.

- [ ] **Step 3: Implement — read cruise_config in `extra_state_attributes`**

Replace the `extra_state_attributes` body (lines ~157-173) with:

```python
    @property
    def extra_state_attributes(self):
        m = self._map()
        pts = (getattr(m, "patrol_points", None) or ()) if m is not None else ()
        cfg = (
            self.coordinator.cloud_state.cruise_config_by_map.get(self._map_id, {})
            if getattr(self.coordinator, "cloud_state", None) is not None
            else {}
        )
        items = []
        for p in pts:
            pc = cfg.get(p.point_id) or {}
            items.append({
                "id": p.point_id,
                "label": f"Patrol point {p.point_id}",
                "x_mm": p.x_mm,
                "y_mm": p.y_mm,
                # Defaults match the app's new-point defaults (1 cycle, off).
                "cycles": pc.get("cycles", 1),
                "auto_capture": pc.get("auto_capture", False),
            })
        return {"items": items}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_point_config.py -k patrol_sensor -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the patrol-points sensor's existing tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "patrol_points or multi_select" -q`
Expected: PASS (the item shape gained no keys; values changed null→default — update any test that asserted `cycles is None`).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/entities/sensor/map.py tests/integration/test_patrol_point_config.py
git commit -m "feat(patrol): surface cycles/auto-capture on the patrol-points sensor from CRUISE.0"
```

---

### Task 4: Add `cycles`/`auto_capture` to the camera `editable_objects` patrol entries

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera/map.py:208-219`
- Test: `tests/integration/test_patrol_point_config.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_patrol_point_config.py
def test_editable_objects_patrol_carries_cycles_auto():
    from custom_components.dreame_a2_mower.camera.map import DreameA2MapCamera
    cam = DreameA2MapCamera.__new__(DreameA2MapCamera)
    md = SimpleNamespace(
        patrol_points=[SimpleNamespace(point_id=3, x_mm=-3050, y_mm=-5480)],
        exclusion_zones=(), spot_zones=(), maintenance_points=(),
    )
    cam.coordinator = SimpleNamespace(
        _active_map_id=0,
        cloud_state=_bare_cloud_state(
            maps_by_id={0: md},
            cruise_config_by_map={0: {3: {"cycles": 2, "auto_capture": True}}},
        ),
    )
    objs = cam._editable_objects_from_map(md)
    patrol = [o for o in objs if o.get("kind") == "patrol"][0]
    assert patrol["cycles"] == 2 and patrol["auto_capture"] is True
```

> Note: `_editable_objects_from_map` takes the map_data (`md`). To find the map_id for the cruise lookup, use `self.coordinator._active_map_id` (the camera renders the active map). Confirm by reading `camera/map.py` around the method signature; if it already has the map_id in scope, use that.

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_point_config.py -k editable_objects_patrol -q`
Expected: FAIL — `KeyError: 'cycles'`.

- [ ] **Step 3: Implement — add cycles/auto_capture to the patrol entry**

In `camera/map.py`, the patrol loop (lines ~208-219). Just before the loop, resolve the active map's cruise config; inside, add the two fields:

```python
        # Patrol / cruise points (cruisePoints, o=223) — single-point objects.
        _cruise = {}
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is not None:
            _cruise = cs.cruise_config_by_map.get(self.coordinator._active_map_id, {})
        for p in getattr(map_data, "patrol_points", ()):
            if getattr(p, "point_id", None) is None:
                continue
            _pc = _cruise.get(p.point_id) or {}
            out.append(
                {
                    "id": p.point_id,
                    "op": 223,
                    "type": 2,
                    "kind": "patrol",
                    "point_m": [p.x_mm / 1000.0, p.y_mm / 1000.0],
                    "cycles": _pc.get("cycles", 1),
                    "auto_capture": _pc.get("auto_capture", False),
                }
            )
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_point_config.py -k editable_objects_patrol -q`
Expected: PASS

- [ ] **Step 5: Run the editable_objects / card-contract tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "editable_objects or card_contract" -q`
Expected: PASS (additive keys).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/camera/map.py tests/integration/test_patrol_point_config.py
git commit -m "feat(patrol): add cycles/auto-capture to editable_objects patrol entries"
```

---

### Task 5: `coordinator.write_patrol_point_config`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py` (add after `create_patrol_point`, ~880)
- Test: `tests/integration/test_patrol_point_config.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_patrol_point_config.py
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_write_patrol_point_config_builds_cruised():
    from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin
    c = _WritesMixin.__new__(_WritesMixin)
    c._cloud = SimpleNamespace(set_cfg=MagicMock(return_value=True))
    async def _exec(fn, *a): return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    ok = await c.write_patrol_point_config(
        map_id=0, point_id=3, cycles=3, auto_capture=True
    )
    assert ok is True
    c._cloud.set_cfg.assert_called_once_with(
        "CRUISED", {"idx": 0, "value": [-1, 3, 1, 3]}
    )


@pytest.mark.asyncio
async def test_write_patrol_point_config_rejects_bad_cycles():
    from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin
    c = _WritesMixin.__new__(_WritesMixin)
    with pytest.raises(ValueError):
        await c.write_patrol_point_config(map_id=0, point_id=3, cycles=4, auto_capture=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_point_config.py -k write_patrol_point_config -q`
Expected: FAIL — `AttributeError: ... has no attribute 'write_patrol_point_config'`

- [ ] **Step 3: Implement the method**

In `coordinator/_writes.py`, add after `create_patrol_point` (it returns ~line 880):

```python
    async def write_patrol_point_config(
        self, *, map_id: int, point_id: int, cycles: int, auto_capture: bool
    ) -> bool:
        """Set a patrol point's per-point cycles + auto-capture (CRUISED CFG key).

        Standalone CFG write (NOT part of the o=223 geometry txn). idx = the
        0-based map index (== map_id, same convention as PRE). value =
        [-1, point_id, auto_capture(0/1), cycles]; value[0]=-1 is a constant
        sentinel. Read-back is via the CRUISE.0 device-data key (no m:g getter
        on t:CRUISED). See inventory.yaml § CRUISED. Returns the device verdict
        (set_cfg → out[0].r==0).
        """
        if int(cycles) not in (1, 2, 3):
            raise ValueError(f"cycles must be 1, 2 or 3, got {cycles!r}")
        value = [-1, int(point_id), 1 if auto_capture else 0, int(cycles)]
        return bool(
            await self.hass.async_add_executor_job(
                self._cloud.set_cfg, "CRUISED", {"idx": int(map_id), "value": value}
            )
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_point_config.py -k write_patrol_point_config -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_writes.py tests/integration/test_patrol_point_config.py
git commit -m "feat(patrol): write_patrol_point_config -> CRUISED CFG write"
```

---

### Task 6: `set_patrol_point_config` service

**Files:**
- Modify: `custom_components/dreame_a2_mower/services.py` (constant ~57, schema ~190, handler ~930, register ~1042)
- Modify: `custom_components/dreame_a2_mower/services.yaml` (after `create_patrol_point`)
- Test: `tests/integration/test_patrol_point_config.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_patrol_point_config.py
@pytest.mark.asyncio
async def test_set_patrol_point_config_service_handler_calls_coordinator():
    from custom_components.dreame_a2_mower import services as svc
    coord = SimpleNamespace(
        write_patrol_point_config=AsyncMock(return_value=True),
        _active_map_id=0,
    )
    call = SimpleNamespace(data={"point_id": 3, "cycles": 2, "auto_capture": True})
    # _resolve_coordinator/_run helpers are exercised via the real handler;
    # call the inner coroutine builder directly:
    await coord.write_patrol_point_config(
        map_id=0, point_id=3, cycles=2, auto_capture=True
    )
    coord.write_patrol_point_config.assert_awaited_once_with(
        map_id=0, point_id=3, cycles=2, auto_capture=True
    )
```

> This is a thin guard around the call shape. The handler wiring itself is verified by the integration smoke test in Task 9 + the live deploy.

- [ ] **Step 2: Add the service constant + schema**

In `services.py`, after `SERVICE_CREATE_PATROL_POINT = "create_patrol_point"` (line 55):

```python
SERVICE_SET_PATROL_POINT_CONFIG = "set_patrol_point_config"
```

After `SCHEMA_CREATE_PATROL_POINT` (line ~190):

```python
SCHEMA_SET_PATROL_POINT_CONFIG = vol.Schema({
    vol.Optional("map_id"): vol.Coerce(int),
    vol.Required("point_id"): vol.Coerce(int),
    vol.Required("cycles"): vol.All(vol.Coerce(int), vol.In((1, 2, 3))),
    vol.Required("auto_capture"): vol.Coerce(bool),
})
```

- [ ] **Step 3: Add the handler**

After `_handle_create_patrol_point` (ends ~929). This is a direct write (not an `edit_map` txn), so use the bool-write runner the other CFG services use — confirm the helper name by reading how a non-edit-map write service (e.g. `_handle_set_child_lock`) wraps `raise_for_write_result` / its result, and mirror it. Pattern:

```python
@service_handler
async def _handle_set_patrol_point_config(
    coordinator: DreameA2MowerCoordinator, call: ServiceCall
) -> None:
    """Set a patrol point's cycles + auto-capture (CRUISED CFG write)."""
    map_id = call.data.get("map_id")
    if map_id is None:
        map_id = getattr(coordinator, "_active_map_id", None) or 0
    ok = await coordinator.write_patrol_point_config(
        map_id=int(map_id),
        point_id=int(call.data["point_id"]),
        cycles=int(call.data["cycles"]),
        auto_capture=bool(call.data["auto_capture"]),
    )
    if not ok:
        raise HomeAssistantError(
            f"set_patrol_point_config: device rejected (map {map_id}, "
            f"point {call.data['point_id']})"
        )
```

Ensure `from homeassistant.exceptions import HomeAssistantError` is imported in `services.py` (it likely is — check the import block; add if missing).

- [ ] **Step 4: Register the service**

After the `create_patrol_point` registration (lines ~1041-1042):

```python
    hass.services.async_register(DOMAIN, SERVICE_SET_PATROL_POINT_CONFIG,
                                  _handle_set_patrol_point_config,
                                  schema=SCHEMA_SET_PATROL_POINT_CONFIG)
```

- [ ] **Step 5: Document in `services.yaml`**

After the `create_patrol_point:` block:

```yaml
set_patrol_point_config:
  name: Set patrol point config
  description: >
    Set a patrol point's Number of Patrol Cycles (1/2/3) and Auto-Capture &
    Upload Photos (on/off) — the CRUISED CFG attributes. Standalone write, not
    part of the geometry edit. Read back via the patrol-points sensor / map
    editor (CRUISE.0 device-data).
  fields:
    map_id:
      name: Map ID
      description: 0-based map index. Defaults to the active map when omitted.
      required: false
      example: 0
      selector:
        number: {min: 0, max: 10, mode: box}
    point_id:
      name: Point ID
      description: The patrol point's id (from sensor.dreame_a2_mower_map_N_patrol_points).
      required: true
      example: 3
      selector:
        number: {min: 0, max: 99, mode: box}
    cycles:
      name: Cycles
      description: Number of patrol cycles at this point.
      required: true
      example: 2
      selector:
        select:
          options: ["1", "2", "3"]
    auto_capture:
      name: Auto-capture
      description: Capture & upload photos at this point.
      required: true
      example: true
      selector:
        boolean:
```

- [ ] **Step 6: Run tests + import check**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_point_config.py -q && /data/claude/homeassistant/.venv-vanilla/bin/python -c "import ast; ast.parse(open('custom_components/dreame_a2_mower/services.py').read())"`
Expected: tests PASS; services.py parses.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/services.py custom_components/dreame_a2_mower/services.yaml tests/integration/test_patrol_point_config.py
git commit -m "feat(patrol): set_patrol_point_config service"
```

---

### Task 7: Map-editor card — inline cycles/auto-capture panel

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-map-editor-card.js`
- Create: `tests/www/patrol_attr_panel_harness.mjs`, `tests/www/test_patrol_attr_panel.py`

**Context:** the card already tracks a selected object and reads `editable_objects` (now carrying `cycles`/`auto_capture`). Read the card to find: (a) the selected-object accessor (the draft/selected descriptor), (b) where per-selection UI is rendered, (c) how it calls services (look for an existing `hass.callService` / `this._hass.callService('dreame_a2_mower', ...)`), and (d) the `map_id` it uses (`a.map_id` from attrs). Extract the panel value-mapping into a tiny pure helper so it's node-testable.

- [ ] **Step 1: Write the failing test (pure helper)**

```python
# tests/www/test_patrol_attr_panel.py
import subprocess, shutil, pathlib, pytest
NODE = shutil.which("node")
HARNESS = pathlib.Path(__file__).parent / "patrol_attr_panel_harness.mjs"

@pytest.mark.skipif(NODE is None, reason="node not available")
def test_patrol_attr_panel_harness():
    r = subprocess.run([NODE, str(HARNESS)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "OK" in r.stdout
```

```javascript
// tests/www/patrol_attr_panel_harness.mjs
import assert from "node:assert";
import { patrolConfigServiceData }
  from "../../custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js";

// Maps a selected patrol object + new control values to the service payload.
const obj = { id: 3, kind: "patrol", cycles: 1, auto_capture: false };
assert.deepStrictEqual(
  patrolConfigServiceData(0, obj, { cycles: 3 }),
  { map_id: 0, point_id: 3, cycles: 3, auto_capture: false },
  "cycles change keeps current auto_capture",
);
assert.deepStrictEqual(
  patrolConfigServiceData(1, obj, { auto_capture: true }),
  { map_id: 1, point_id: 3, cycles: 1, auto_capture: true },
  "auto change keeps current cycles",
);
console.log("OK");
```

- [ ] **Step 2: Run to verify it fails**

Run: `node tests/www/patrol_attr_panel_harness.mjs`
Expected: FAIL — no export `patrolConfigServiceData`.

- [ ] **Step 3: Add the pure helper**

In `www/_dreame-map-edit-geom.js` (the card's pure-geometry helper module — confirm it's the one the editor imports), add + export:

```javascript
// Build the set_patrol_point_config service payload from the selected patrol
// object's current cycles/auto_capture, overridden by the changed control.
export function patrolConfigServiceData(mapId, obj, change) {
  return {
    map_id: mapId,
    point_id: obj.id,
    cycles: change.cycles != null ? change.cycles : (obj.cycles ?? 1),
    auto_capture: change.auto_capture != null ? change.auto_capture : !!obj.auto_capture,
  };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `node tests/www/patrol_attr_panel_harness.mjs`
Expected: `OK`

- [ ] **Step 5: Render the panel + wire the service call (in the card)**

In `dreame-map-editor-card.js`, where the selected-object detail is rendered, when the selected object's `kind === "patrol"` AND it has a real id (`id >= 0`, i.e. committed — not a new draft), render:

```html
<div class="patrol-attr">
  <div class="row">Cycles:
    <button data-cyc="1">1</button><button data-cyc="2">2</button><button data-cyc="3">3</button>
  </div>
  <label class="row"><input type="checkbox" id="pp-auto"> Auto-capture</label>
</div>
```

Pre-fill from the selected object's `cycles` (highlight the active button) and `auto_capture` (checkbox). Import `patrolConfigServiceData` from `_dreame-map-edit-geom.js`. On a cycles button click or the checkbox change:

```javascript
const data = patrolConfigServiceData(this._mapId(), sel, { cycles: n });   // or {auto_capture: cb.checked}
this._hass.callService("dreame_a2_mower", "set_patrol_point_config", data);
// optimistic: update the selected object's local copy so the panel reflects at once
sel.cycles = data.cycles; sel.auto_capture = data.auto_capture;
this._renderSelectedPanel();   // or the card's existing re-render of the selection
```

Use the card's existing selected-object reference + map-id accessor (named per the card; match them). The panel is hidden for an uncommitted draft point (no real id yet) — new points default to 1/off on create, then become editable once committed.

- [ ] **Step 6: Syntax-check both JS files**

Run: `node --check custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js && node --check custom_components/dreame_a2_mower/www/dreame-map-editor-card.js`
Expected: no output (OK).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js custom_components/dreame_a2_mower/www/dreame-map-editor-card.js tests/www/patrol_attr_panel_harness.mjs tests/www/test_patrol_attr_panel.py
git commit -m "feat(patrol): map-editor inline cycles/auto-capture panel"
```

---

### Task 8: Document the integration entity/service in entity-inventory + record the live-verify items

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml` (the patrol-points sensor row — it now reads CRUISE.0; add the `set_patrol_point_config` service/write)
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` § CRUISED (note the integration now reads CRUISE.0 + writes via `write_patrol_point_config`/`set_patrol_point_config`) — **re-read the file first (concurrent Mac edits); stage by explicit path; never `git checkout` it**

- [ ] **Step 1: Update entity-inventory.yaml**

Add a verification to the patrol-points sensor entry noting `cycles`/`auto_capture` are now sourced from `CloudState.cruise_config_by_map` (parsed from CRUISE.0), and record the `set_patrol_point_config` service → `coordinator.write_patrol_point_config` → CRUISED write. Use `status: presumed` until live-verified (no live write done yet), evidence omitted.

- [ ] **Step 2: Update inventory.yaml § CRUISED references**

In the CRUISED entry's `references.integration_code`, replace the `(write path TBD)` note with the real path: `coordinator/_writes.py:write_patrol_point_config` (write via `cloud_client.set_cfg("CRUISED", {idx, value})`); read via `protocol/cruise_config.py:parse_cruise_config` → `CloudState.cruise_config_by_map`.

- [ ] **Step 3: Validate + regenerate canonical**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only && /data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py && /data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_audit.py --consistency; git checkout docs/research/wire-census.json 2>/dev/null || true`
Expected: schema valid; canonical rendered; consistency exit 0.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml custom_components/dreame_a2_mower/inventory.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "docs(patrol): record CRUISE.0 read + set_patrol_point_config write in inventories"
```

---

### Task 9: Full suite + live verification

- [ ] **Step 1: Full test suite green**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: all pass (baseline + the new tests), 0 failures.

- [ ] **Step 2: Deploy to the live mower (it's up)**

Deploy the changed Python files + the two card JS files + dashboard if needed via the SCP procedure (`reference_ha_dashboard_deploy` / the box at `root@10.0.0.30`, `/config/custom_components/dreame_a2_mower/`), restart HA (Python changed), hard-refresh the browser (cards cache hard). Back up first (`*.bak-patrolattr`).

- [ ] **Step 3: Live verification checklist**

- Read: `sensor.dreame_a2_mower_map_N_patrol_points` items now show real `cycles`/`auto_capture` (not null) matching the app for each point.
- Write: in the map editor, select a committed patrol point → panel shows current values → change cycles to 2 and toggle auto-capture → the service call returns success; after the next cloud refresh (or a manual `refresh_cloud_state`) the sensor reflects the new values; confirm in the Dreame app that the point's cycles/auto-capture changed.
- **Risk 1 (map-active):** test setting a point on a NON-active map. If the write is rejected (`set_cfg` returns False → service raises), gate `write_patrol_point_config` to activate the map first (mirror `create_patrol_point`'s "editing a non-active map makes it active" via the edit_map `o=200` select, or document the active-map requirement in the service). Record the outcome in `inventory.yaml § CRUISED`.
- **Risk 2 (`"1,0"` key):** if a real config shows a comma-joined key, capture which point it maps to (set one distinct point, diff CRUISE.0) and update the parser + inventory open-question.
- **Risk 3 (new-point CRUISE.0):** create a patrol point, confirm it appears in CRUISE.0 at `{num:1, ap:false}` (or is absent → the defaults cover it).

- [ ] **Step 4: On ship — move the spec + this plan out of tree**

Per CLAUDE.md documentation lifecycle, `git mv` (or move) `docs/superpowers/specs/2026-06-16-patrol-point-attributes-editor-design.md` and `docs/superpowers/plans/2026-06-16-patrol-point-attributes-editor.md` to `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/{specs,plans}/`. Cut a release via `tools/release/release.sh` if shipping to HACS.

---

## Self-review notes
- **Spec coverage:** read (Tasks 1-4), write (Tasks 5-6), editor UI (Task 7), sensor surfacing (Task 3), inventory (Task 8), risks + live verify (Task 9). Approach A (editor + sensor) covered by Tasks 3+4. New-point defaults (1/off) handled in Tasks 3/4 defaults + Task 7 (panel hidden for uncommitted draft).
- **No new transport:** reuses `cloud_client.set_cfg` (dict value → `d` directly), confirmed `set_cfg` semantics.
- **map_id == 0-based idx** confirmed from `services.yaml` create_patrol_point + PRE convention.
- **Unverified-at-write-time anchors the implementer must confirm by reading (flagged inline):** the per-map sensor's map-id attribute name (Task 3), `_editable_objects_from_map`'s map-id-in-scope (Task 4), the non-edit-map write-service runner pattern (Task 6), and the card's selected-object + map-id accessors + callService idiom (Task 7).
