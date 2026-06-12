# Map Editing (rename zone + delete object) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the wire-verified `o=219` (rename zone) and `o=218` (delete object) map-edit operations through the device's `o=204`/`o=201` edit transaction, surfaced as services + per-map sensor attributes.

**Architecture:** Add a `p` param to the routed-action helpers (for the `p:1` commit). A coordinator `edit_map(map_id, mutations)` runs `o=200 select → o=204 begin → mutations → o=201 commit` and refreshes state. `rename_zone`/`delete_map_object` are thin wrappers. The map decoder surfaces the cloud object id on `ExclusionZone` so existing no-go/obstacle objects are deletable; per-map sensor attrs list renamable zones + deletable objects; two services expose it.

**Tech Stack:** Python 3.13, Home Assistant custom integration, pytest (vanilla stubbed-HA venv at `/data/claude/homeassistant/.venv-vanilla`).

---

## File Structure

- Modify: `custom_components/dreame_a2_mower/protocol/cfg_action.py` — `call_action_op` gains `p` kwarg.
- Modify: `custom_components/dreame_a2_mower/cloud_client/_rpc.py` — `routed_action` gains `p` kwarg.
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py` — `edit_map`, `rename_zone`, `delete_map_object`.
- Modify: `custom_components/dreame_a2_mower/map_decoder.py` — `ExclusionZone.obj_id`; `_collect_exclusion_entries` returns id; build + reflect sites preserve it.
- Modify: `custom_components/dreame_a2_mower/sensor_map.py` — `renamable_zones` + `deletable_objects` attrs.
- Modify: `custom_components/dreame_a2_mower/services.py` + `services.yaml` — two services.
- Modify: `inventory.yaml`, `entity-inventory.yaml`, `docs/research/app-integration-roadmap.md`, `docs/research/knowledge-gaps.md` — fact discipline.
- Tests: `tests/unit/test_routed_action_p.py`, `tests/integration/test_edit_map.py`, `tests/protocol/test_exclusion_obj_id.py`, `tests/integration/test_map_edit_sensor_attrs.py`, `tests/integration/test_map_edit_services.py`.

Run tests: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -q`

---

### Task 1: `p` parameter on the routed-action helpers

**Files:**
- Modify: `protocol/cfg_action.py` (`call_action_op`, ~line 197)
- Modify: `cloud_client/_rpc.py` (`routed_action`)
- Test: `tests/unit/test_routed_action_p.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_routed_action_p.py
from custom_components.dreame_a2_mower.protocol.cfg_action import call_action_op


def test_call_action_op_default_p_zero_and_d_nesting():
    calls = []
    def send(siid, aiid, params):
        calls.append((siid, aiid, params))
        return {"result": {"out": [{"m": "a", "r": 0}]}}
    call_action_op(send, 219, {"region": 1, "name": "X"})
    assert calls[0][0] == 2 and calls[0][1] == 50
    assert calls[0][2] == [{"m": "a", "p": 0, "o": 219, "d": {"region": 1, "name": "X"}}]


def test_call_action_op_p_one_commit_no_extra():
    calls = []
    def send(siid, aiid, params):
        calls.append(params)
        return {"result": {"out": [{"m": "a", "r": 0}]}}
    call_action_op(send, 201, p=1)
    assert calls[0] == [{"m": "a", "p": 1, "o": 201}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_routed_action_p.py -q`
Expected: FAIL (`call_action_op` has no `p` kwarg).

- [ ] **Step 3: Implement**

In `protocol/cfg_action.py`, change the signature + body of `call_action_op`:

```python
def call_action_op(send_action, op: int, extra: dict | None = None, *, p: int = 0) -> Any:
    # ...existing docstring...
    payload: dict = {"m": "a", "p": int(p), "o": int(op)}
    if extra:
        payload["d"] = extra
    return send_action(ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [payload])
```

In `cloud_client/_rpc.py`, thread `p` through `routed_action`:

```python
    def routed_action(
        self, op: int, extra: dict[str, Any] | None = None, *, p: int = 0
    ) -> dict[str, Any] | None:
        # ...existing docstring...
        from ..protocol.cfg_action import call_action_op  # type: ignore[import]
        self._last_send_error_code = None
        result = call_action_op(self.action, op, extra, p=p)
        # ...rest unchanged (endpoint_log + return)...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_routed_action_p.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/cfg_action.py custom_components/dreame_a2_mower/cloud_client/_rpc.py tests/unit/test_routed_action_p.py
git commit -m "feat(map-edit): p param on routed-action helpers for o=201 commit"
```

---

### Task 2: `edit_map` transaction + rename/delete wrappers

**Files:**
- Modify: `coordinator/_writes.py` (add methods to `_WritesMixin`)
- Test: `tests/integration/test_edit_map.py`

**Context:** `_WritesMixin` is the class. `self._cloud.routed_action(op, extra, p=…)` is the transport (Task 1). `self._chunked_write_lock` exists; `self._refresh_cloud_state()` re-reads cloud state incl. MAPL. Mirror the `write_schedule` style (executor jobs, lock, refresh, keep-going-on-failure but always commit).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_edit_map.py
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin


def _make_coord(results=None):
    c = _WritesMixin()
    calls = []
    seq = iter(results) if results else None

    def _routed(op, extra=None, *, p=0):
        calls.append((op, extra, p))
        return None if (seq is not None and not next(seq)) else {"ok": True}

    c._cloud = SimpleNamespace(routed_action=_routed)
    c._chunked_write_lock = asyncio.Lock()
    c._refresh_cloud_state = AsyncMock()

    async def _exec(fn, *a, **k):
        return fn(*a, **k)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    return c, calls


@pytest.mark.asyncio
async def test_edit_map_transaction_order_and_commit_p():
    c, calls = _make_coord()
    ok = await c.edit_map(1, [(219, {"region": 1, "name": "X"})])
    assert ok is True
    ops = [(op, p) for (op, _e, p) in calls]
    assert ops == [(200, 0), (204, 0), (219, 0), (201, 1)]
    assert calls[0][1] == {"idx": 1}        # select map
    assert calls[2][1] == {"region": 1, "name": "X"}
    c._refresh_cloud_state.assert_awaited()


@pytest.mark.asyncio
async def test_edit_map_always_commits_and_reports_failure(monkeypatch):
    # mutation (3rd call) fails -> overall False, but commit (o=201) still sent.
    c, calls = _make_coord(results=[True, True, False, True])
    ok = await c.edit_map(0, [(218, {"id": 101, "type": 0})])
    assert ok is False
    assert (201, 1) in [(op, p) for (op, _e, p) in calls]


@pytest.mark.asyncio
async def test_rename_and_delete_wrappers_build_mutations():
    c, calls = _make_coord()
    await c.rename_zone(2, 3, "Lawn")
    await c.delete_map_object(0, 102, 4)
    muts = [(op, e) for (op, e, _p) in calls]
    assert (219, {"region": 3, "name": "Lawn"}) in muts
    assert (218, {"id": 102, "type": 4}) in muts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_edit_map.py -q`
Expected: FAIL (`edit_map` not defined).

- [ ] **Step 3: Implement**

Add to `_WritesMixin` in `coordinator/_writes.py`:

```python
    async def edit_map(
        self, map_id: int, mutations: list[tuple[int, dict | None]]
    ) -> bool:
        """Run a map-edit transaction on `map_id`, then refresh state.

        Sequence: o=200{idx:map_id} -> o=204(p:0) begin -> each mutation(p:0)
        -> o=201(p:1) commit. The target map becomes (and stays) active. Each
        leg is sent via routed_action; a None result marks overall failure but
        the commit is ALWAYS sent so the device never stays in edit mode.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("edit_map: cloud client not ready")
            return False

        async def _send(op, extra=None, *, p=0):
            return await self.hass.async_add_executor_job(
                lambda: self._cloud.routed_action(op, extra, p=p)
            )

        ok = True
        async with self._chunked_write_lock:
            if await _send(200, {"idx": int(map_id)}) is None:
                ok = False
            if await _send(204) is None:
                ok = False
            for op, payload in mutations:
                if await _send(op, payload) is None:
                    ok = False
            if await _send(201, p=1) is None:
                ok = False
        LOGGER.info(
            "[map-edit] map %d, %d mutation(s), ok=%s", map_id, len(mutations), ok
        )
        await self._refresh_cloud_state()
        return ok

    async def rename_zone(self, map_id: int, region: int, name: str) -> bool:
        """Rename mowing zone `region` on `map_id` (o=219)."""
        return await self.edit_map(
            int(map_id), [(219, {"region": int(region), "name": str(name)})]
        )

    async def delete_map_object(
        self, map_id: int, object_id: int, category: int
    ) -> bool:
        """Delete a map object by id+category on `map_id` (o=218).

        category: 0 = zone/no-go, 4 = ignore-obstacle (confirmed values).
        """
        return await self.edit_map(
            int(map_id), [(218, {"id": int(object_id), "type": int(category)})]
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_edit_map.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_writes.py tests/integration/test_edit_map.py
git commit -m "feat(map-edit): edit_map transaction + rename_zone/delete_map_object"
```

---

### Task 3: Surface the cloud object id on `ExclusionZone`

**Files:**
- Modify: `map_decoder.py` (`ExclusionZone` ~line 87; `_collect_exclusion_entries` ~296; build loop ~720-726; reflect helper ~887)
- Test: `tests/protocol/test_exclusion_obj_id.py`

**Context:** `_collect_exclusion_entries(entries_wrapper, subtype)` currently returns `(rotated_path, subtype)` pairs, parsing `entry[1]` as geometry and DISCARDING `entry[0]` (the cloud object id — same `entry[0]=id` convention spots/zones use). Two callers (~lines 679-680): forbidden (subtype None) + ignore (subtype "ignore"). The build loop (~720-726) unpacks the pairs and does `ExclusionZone(points=pts, subtype=subtype)`. A reflect helper (~line 887) reconstructs `ExclusionZone(points=_reflect(p), subtype=None)` from existing zones. **Geometry must not change** — only add an id field.

- [ ] **Step 1: Write the failing test**

```python
# tests/protocol/test_exclusion_obj_id.py
from custom_components.dreame_a2_mower.map_decoder import _collect_exclusion_entries, ExclusionZone


def test_exclusion_entries_carry_obj_id():
    wrapper = {"value": [
        [101, {"path": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]}],
    ]}
    out = _collect_exclusion_entries(wrapper, None)
    assert len(out) == 1
    obj_id, rotated, subtype = out[0]
    assert obj_id == 101 and subtype is None and len(rotated) == 3


def test_exclusion_entries_missing_id_is_none():
    wrapper = {"value": [
        {"path": [{"x": 0, "y": 0}, {"x": 1, "y": 0}]},  # dict form, no id
    ]}
    out = _collect_exclusion_entries(wrapper, "ignore")
    assert out[0][0] is None and out[0][2] == "ignore"


def test_exclusion_zone_has_obj_id_default_none():
    z = ExclusionZone(points=((0.0, 0.0),))
    assert z.obj_id is None
    z2 = ExclusionZone(points=((0.0, 0.0),), subtype="ignore", obj_id=102)
    assert z2.obj_id == 102
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_exclusion_obj_id.py -q`
Expected: FAIL (`obj_id` field / triple return missing).

- [ ] **Step 3: Implement**

(a) Add the field to `ExclusionZone` (after `subtype`):
```python
    points: tuple[tuple[float, float], ...]
    subtype: str | None = None
    obj_id: int | None = None
```

(b) `_collect_exclusion_entries` — return triples and parse `entry[0]`:
```python
    result: list[tuple[int | None, list[dict], str | None]] = []
    entries = entries_wrapper.get("value", []) if isinstance(entries_wrapper, dict) else []
    for entry in entries:
        obj_id: int | None = None
        if isinstance(entry, list) and len(entry) >= 2:
            try:
                obj_id = int(entry[0])
            except (TypeError, ValueError):
                obj_id = None
            zdata = entry[1]
        elif isinstance(entry, dict):
            zdata = entry
        else:
            continue
        path = zdata.get("path", [])
        if not path:
            continue
        raw_angle = zdata.get("angle")
        rot_angle = -raw_angle if raw_angle is not None else None
        rotated = _rotate_path_around_centroid(path, rot_angle)
        result.append((obj_id, rotated, subtype))
    return result
```

(c) Update the build loop (~720-726) to unpack the triple and pass `obj_id`:
```python
    for (obj_id, rp, subtype) in rotated_exclusions:   # was (rp, subtype)
        pts = tuple(
            (float(x_reflect - pt["x"]), float(y_reflect - pt["y"]))
            for pt in rp
        )
        if pts:
            excl_out.append(ExclusionZone(points=pts, subtype=subtype, obj_id=obj_id))
```
(Read the actual variable name the loop iterates — it is the spread result of the two `_collect_exclusion_entries(...)` calls at ~lines 679-680. Update that loop's unpack from 2-tuple to 3-tuple.)

(d) Reflect helper (~line 887) — preserve `obj_id`:
```python
        ExclusionZone(points=_reflect(p), subtype=z.subtype, obj_id=z.obj_id)
```
(Read the loop variable — it iterates over `map_data.exclusion_zones`; carry each zone's `subtype` and `obj_id` through instead of hardcoding `subtype=None`.)

- [ ] **Step 4: Run test + the full decoder suite (geometry must stay green)**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_exclusion_obj_id.py tests/protocol/test_multi_map_decoder.py tests/protocol/test_cloud_client_fetch_map.py -q`
Expected: PASS (new test + all existing decoder tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/map_decoder.py tests/protocol/test_exclusion_obj_id.py
git commit -m "feat(map-edit): surface cloud obj_id on ExclusionZone for delete targeting"
```

---

### Task 4: Per-map sensor attributes (renamable zones + deletable objects)

**Files:**
- Modify: `sensor_map.py`
- Test: `tests/integration/test_map_edit_sensor_attrs.py`

**Context:** `sensor_map.py` has per-map sensors extending `_DreameA2PerMapSensorBase` (carries `self._map_id`; reaches the map via `coordinator.cloud_state.maps_by_id[map_id]` — read the base class + an existing sensor like `DreameA2MapSegmentCountSensor` for the exact accessor). Add the two attribute lists to the existing `DreameA2MapSegmentCountSensor` (it already reads `mowing_zones`) via `extra_state_attributes`. Category derivation: mowing zone → 0; exclusion `subtype is None` → 0 (no-go); `subtype == "ignore"` → 4. Only include exclusions with a non-None `obj_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_map_edit_sensor_attrs.py
from types import SimpleNamespace
from custom_components.dreame_a2_mower.sensor_map import DreameA2MapSegmentCountSensor
from custom_components.dreame_a2_mower.map_decoder import MowingZone, ExclusionZone


def _coord_with_map(map_obj):
    return SimpleNamespace(cloud_state=SimpleNamespace(maps_by_id={0: map_obj}))


def test_segment_sensor_exposes_rename_and_delete_targets():
    m = SimpleNamespace(
        mowing_zones=(MowingZone(zone_id=1, name="Zone1", path=((0.0, 0.0),), area_m2=5.0),),
        exclusion_zones=(
            ExclusionZone(points=((0.0, 0.0),), subtype=None, obj_id=101),
            ExclusionZone(points=((1.0, 1.0),), subtype="ignore", obj_id=102),
            ExclusionZone(points=((2.0, 2.0),), subtype=None, obj_id=None),  # no id -> skip
        ),
    )
    s = DreameA2MapSegmentCountSensor(_coord_with_map(m), map_id=0)
    attrs = s.extra_state_attributes
    assert {"region": 1, "name": "Zone1"} in attrs["renamable_zones"]
    cats = {(o["id"], o["category"]) for o in attrs["deletable_objects"]}
    assert (1, 0) in cats          # mowing zone, category 0
    assert (101, 0) in cats        # no-go
    assert (102, 4) in cats        # ignore-obstacle
    assert all(o["id"] is not None for o in attrs["deletable_objects"])
    assert 3 == len(attrs["deletable_objects"])  # the id-less exclusion is skipped
```

> **Implementer note:** match the real `DreameA2MapSegmentCountSensor.__init__` signature and the base-class map accessor (read `sensor_map.py`). If that sensor's constructor differs, adapt the harness; the contract is the two attribute lists with the shapes above. If `extra_state_attributes` already exists on a sibling, follow that pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_edit_sensor_attrs.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add an `extra_state_attributes` property to `DreameA2MapSegmentCountSensor` (read the base class for the map accessor; use it instead of the inline `cloud_state.maps_by_id` if the base provides a helper):

```python
    @property
    def extra_state_attributes(self):
        m = self._map()  # or the base-class accessor; returns the MapData or None
        if m is None:
            return {}
        renamable = [
            {"region": z.zone_id, "name": z.name}
            for z in getattr(m, "mowing_zones", ())
        ]
        deletable = [
            {"id": z.zone_id, "category": 0, "label": z.name or f"Zone {z.zone_id}"}
            for z in getattr(m, "mowing_zones", ())
        ]
        for z in getattr(m, "exclusion_zones", ()):
            if z.obj_id is None:
                continue
            cat = 4 if z.subtype == "ignore" else 0
            kind = "Ignore" if z.subtype == "ignore" else "No-go"
            deletable.append({"id": z.obj_id, "category": cat, "label": f"{kind} #{z.obj_id}"})
        return {"renamable_zones": renamable, "deletable_objects": deletable}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_edit_sensor_attrs.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor_map.py tests/integration/test_map_edit_sensor_attrs.py
git commit -m "feat(map-edit): per-map sensor attrs for renamable zones + deletable objects"
```

---

### Task 5: Services `rename_zone` + `delete_map_object`

**Files:**
- Modify: `services.py` (constants ~line 26-45; handlers; register ~693; unregister ~750)
- Modify: `services.yaml`
- Test: `tests/integration/test_map_edit_services.py`

**Context:** Follow the existing service pattern (`_coordinator_from_call`, schema with `vol`, `hass.services.async_register`). Add to the unregister tuple too.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_map_edit_services.py
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from custom_components.dreame_a2_mower import services


@pytest.mark.asyncio
async def test_rename_zone_service(monkeypatch):
    coord = SimpleNamespace(rename_zone=AsyncMock(return_value=True))
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(hass=SimpleNamespace(), data={"map_id": 1, "zone": 3, "name": "Lawn"})
    await services._handle_rename_zone(call)
    coord.rename_zone.assert_awaited_once_with(1, 3, "Lawn")


@pytest.mark.asyncio
async def test_delete_map_object_service(monkeypatch):
    coord = SimpleNamespace(delete_map_object=AsyncMock(return_value=True))
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(hass=SimpleNamespace(), data={"map_id": 0, "object_id": 102, "category": 4})
    await services._handle_delete_map_object(call)
    coord.delete_map_object.assert_awaited_once_with(0, 102, 4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_edit_services.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `services.py` add constants, schemas, handlers, registration:

```python
SERVICE_RENAME_ZONE = "rename_zone"
SERVICE_DELETE_MAP_OBJECT = "delete_map_object"

SCHEMA_RENAME_ZONE = vol.Schema({
    vol.Required("map_id"): vol.Coerce(int),
    vol.Required("zone"): vol.Coerce(int),
    vol.Required("name"): cv.string,
})
SCHEMA_DELETE_MAP_OBJECT = vol.Schema({
    vol.Required("map_id"): vol.Coerce(int),
    vol.Required("object_id"): vol.Coerce(int),
    vol.Required("category"): vol.Coerce(int),
})


async def _handle_rename_zone(call):
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    await coordinator.rename_zone(
        int(call.data["map_id"]), int(call.data["zone"]), str(call.data["name"])
    )


async def _handle_delete_map_object(call):
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    await coordinator.delete_map_object(
        int(call.data["map_id"]), int(call.data["object_id"]), int(call.data["category"])
    )
```

Register in `async_register_services` (match the existing call style; confirm whether `cv` is imported — if not, use `vol.Coerce(str)`/existing helpers):
```python
    hass.services.async_register(DOMAIN, SERVICE_RENAME_ZONE,
                                 _handle_rename_zone, schema=SCHEMA_RENAME_ZONE)
    hass.services.async_register(DOMAIN, SERVICE_DELETE_MAP_OBJECT,
                                 _handle_delete_map_object, schema=SCHEMA_DELETE_MAP_OBJECT)
```

Add `SERVICE_RENAME_ZONE, SERVICE_DELETE_MAP_OBJECT` to the unregister list (~line 750).

In `services.yaml`, add both with fields + descriptions (note in `delete_map_object` that category 0=zone/no-go, 4=ignore-obstacle; in both that editing a non-active map makes it active):

```yaml
rename_zone:
  name: Rename mowing zone
  description: Rename a mowing zone on a map. Editing a non-active map makes it the active map.
  fields:
    map_id:
      name: Map ID
      description: 0-based map index.
      required: true
      example: 0
      selector: { number: { min: 0, max: 10, mode: box } }
    zone:
      name: Zone number
      description: The zone/region number to rename (see the map sensor's renamable_zones).
      required: true
      example: 1
      selector: { number: { min: 1, max: 62, mode: box } }
    name:
      name: New name
      required: true
      example: Front lawn
      selector: { text: {} }
delete_map_object:
  name: Delete map object
  description: Delete a mowing zone, no-go area, or ignore-obstacle area by id+category (see the map sensor's deletable_objects). Editing a non-active map makes it the active map.
  fields:
    map_id:
      name: Map ID
      required: true
      example: 0
      selector: { number: { min: 0, max: 10, mode: box } }
    object_id:
      name: Object ID
      description: Cloud object id from the map sensor's deletable_objects.
      required: true
      example: 101
      selector: { number: { min: 0, mode: box } }
    category:
      name: Category
      description: 0 = zone/no-go, 4 = ignore-obstacle.
      required: true
      example: 0
      selector: { number: { min: 0, max: 10, mode: box } }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_edit_services.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/services.py custom_components/dreame_a2_mower/services.yaml tests/integration/test_map_edit_services.py
git commit -m "feat(map-edit): rename_zone + delete_map_object services"
```

---

### Task 6: Fact discipline (inventory + roadmap + knowledge-gaps)

**Files:**
- Modify: `inventory.yaml`, `entity-inventory.yaml`, `docs/research/app-integration-roadmap.md`, `docs/research/knowledge-gaps.md`

- [ ] **Step 1: Add the map-edit verification to `inventory.yaml`**

Find the routed-action / map area (grep `routed_action`, `o=200`, `MAPL`, or the actions section) and add a verification record using the EXISTING taxonomy (`status: verified` + `evidence:`, NOT `confirmed`/`source:`):
```yaml
      - status: verified
        date: 2026-06-12
        claim: "Map-edit runs as a routed-action transaction on siid:2/aiid:50: o=204(p:0) begin -> mutations(p:0) -> o=201(p:1) commit, on the selected map (o=200{idx} selects + makes active). Confirmed mutations: o=219{region,name} rename zone; o=218{id,type} delete object (type 0=zone/no-go, 4=ignore-obstacle observed). [app-mitm:2026-06-09-map-edit]"
        evidence: "dreame-app-capture-2026-06-09/miio-cloud-13267-http.jsonl (m:a o:204/218/219/201/200 payloads observed in capture order)"
```

- [ ] **Step 2: Note the writable map-edit capability in `entity-inventory.yaml`**

If there is a map/zone-related entry (grep `exclusion`, `mowing_zone`, `map`), add a verification noting rename/delete are now wired via services (`status: verified`, evidence pointer + the `[app-mitm:2026-06-09-map-edit]` tag). If no suitable row exists, skip (the inventory.yaml record is sufficient) — do not invent an entity row.

- [ ] **Step 3: Roadmap F → partial done**

In `docs/research/app-integration-roadmap.md`, change row F status to:
```
**partial done** (v1.0.25a6, 2026-06-12). Rename zone (o=219) + delete object (o=218: zone/no-go cat 0, ignore-obstacle cat 4) wired via the o=204/o=201 edit transaction + o=200 map-select; services rename_zone / delete_map_object + per-map sensor attrs (renamable_zones, deletable_objects). DEFERRED: create no-go/mow/ignore (o=215/o=234, needs an interactive draw card), split/merge (o=220/o=221, destructive), rename-map/delete-map (uncaptured), draw-by-driving (BT).
```

- [ ] **Step 4: Knowledge-gaps**

In `docs/research/knowledge-gaps.md`, record: delete-category codes — only 0 (zone/no-go) and 4 (ignore-obstacle) observed; others unconfirmed. Rename-map + delete-whole-map wire UNCAPTURED. Create (o=215/o=234) + split/merge (o=220/o=221) deferred (need draw card / destructive). Use the file's established `[UNKNOWN — to capture]` / open-item format.

- [ ] **Step 5: Verify the inventory/audit gates stay green**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q -k "inventory or audit or census or honesty"`
Expected: PASS. If the inventory schema validator rejects a field, match a neighbouring record's exact shape (decoded status ∈ {confirmed, partial, hypothesized, unknown}; verification status ∈ {verified, partial, presumed, retracted}). Also confirm both YAML files parse:
`/data/claude/homeassistant/.venv-vanilla/bin/python -c "import yaml; [yaml.safe_load(open(f)) for f in ['custom_components/dreame_a2_mower/inventory.yaml','custom_components/dreame_a2_mower/entity-inventory.yaml']]; print('yaml ok')"`

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml docs/research/app-integration-roadmap.md docs/research/knowledge-gaps.md
git commit -m "docs(map-edit): verification records + roadmap F partial + knowledge-gaps"
```

---

### Task 7: Full suite + gates (no version bump — release.sh owns it)

- [ ] **Step 1: Run the full test suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q`
Expected: PASS (baseline 2167 passed / 4 skipped from Phase E, plus the new tests; report the new totals). Do NOT edit `manifest.json` — `release.sh` performs the bump at release time.

- [ ] **Step 2: Confirm no new entities broke the state-machine audit**

The audit was checked in Task 6 Step 5. If it is red and it is due to a new entity, add honest rows to `tools/state_machine/state_machine_audit_expectations.yaml` (do not weaken the gate) and verify against `main` that the red is new to this branch. No new entities are expected (services + sensor attrs only).

---

## Self-Review (completed)

- **Spec coverage:** transport p-param (T1), edit transaction + wrappers (T2), decoder id surfacing (T3), sensor attrs (T4), services (T5), fact discipline (T6), suite/gates (T7). All spec sections mapped.
- **Placeholders:** none — every step has concrete code/commands; implementer notes point at exact files/lines to adapt (sensor base accessor, exclusion build-loop variable, `cv` import) with the contract fixed.
- **Type/name consistency:** `routed_action(op, extra=None, *, p=0)`, `call_action_op(send_action, op, extra=None, *, p=0)`, `edit_map(map_id, mutations: list[tuple[int, dict|None]])`, `rename_zone(map_id, region, name)`, `delete_map_object(map_id, object_id, category)`, `ExclusionZone(points, subtype=None, obj_id=None)`, `_collect_exclusion_entries → list[tuple[int|None, list[dict], str|None]]` used consistently across tasks. `_WritesMixin` and `MowingZone.zone_id`/`SpotZone.spot_id` match the real code.
