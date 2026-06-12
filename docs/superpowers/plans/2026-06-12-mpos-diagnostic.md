# MPOS diagnostic entity + refresh button — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the routed-get `MPOS` reading (`{x,y,yaw}`) as a read-only diagnostic sensor plus an on-demand "Refresh MPOS" button — raw values, no coordinate transform, no position-driving — so MPOS can be characterized against the physical mower later.

**Architecture:** A `fetch_mpos()` routed-get on the cloud client returns `{"result": ok|idle|error, x,y,yaw}`. A pure `apply_mpos_result()` helper merges that into new `MowerState` fields; the coordinator's `_refresh_mpos()` wires fetch→apply→`async_set_updated_data`. A diagnostic sensor reflects the fields; a diagnostic button calls `_refresh_mpos()`. Button-only refresh (no scheduling).

**Tech Stack:** Python 3.13, Home Assistant custom integration, pytest via `/data/claude/homeassistant/.venv-vanilla/bin/python`.

**Spec:** `docs/superpowers/specs/2026-06-12-mpos-diagnostic-design.md`

---

## Conventions

- **Branch:** already on `feat/mpos-diagnostic` (off `main` = 1.0.25a7). Do NOT create a new branch; commit onto this one.
- **Run tests:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -v` from repo root `/data/claude/homeassistant/ha-dreame-a2-mower`.
- **Epistemic discipline (CLAUDE.md):** MPOS frame/units are UNVERIFIED. Code/docs must NOT claim a transform or a "position". Entity-inventory rows are `presumed`. The `MPOS` protocol fact already exists in `inventory.yaml § MPOS` (status partial) — do not upgrade it.
- **Commit after every task.**
- Adding entities triggers the `inventory-touch-gate` → `entity-inventory.yaml` MUST be updated (Task 6).

---

## File structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `custom_components/dreame_a2_mower/cloud_client/_fetchers.py` | Modify | `fetch_mpos()` routed-get |
| `tests/cloud_client/test_fetch_mpos.py` | Create | fetch_mpos unit tests |
| `custom_components/dreame_a2_mower/mower/state.py` | Modify | 5 `mpos_*` MowerState fields |
| `custom_components/dreame_a2_mower/coordinator/_refreshers.py` | Modify | pure `apply_mpos_result()` + `_refresh_mpos()` |
| `tests/coordinator/test_apply_mpos_result.py` | Create | apply_mpos_result unit tests |
| `custom_components/dreame_a2_mower/sensor_device.py` | Modify | `_mpos_value`/`_mpos_attrs` + descriptor |
| `tests/integration/test_mpos_sensor.py` | Create | sensor value/attrs tests |
| `custom_components/dreame_a2_mower/button.py` | Modify | `DreameA2RefreshMposButton` + register |
| `tests/integration/test_mpos_button.py` | Create | button press test |
| `custom_components/dreame_a2_mower/entity-inventory.yaml` | Modify | sensor + button rows |

---

## Task 1: `fetch_mpos()` routed-get

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py`
- Test: `tests/cloud_client/test_fetch_mpos.py`

Models the existing routed-get fetchers but returns a `result` discriminator so the diagnostic can show `ok`/`idle`/`error` (MPOS returns `r:0` with data even at dock-idle; `r:-1/-3` when idle/no-data per the MISTA pattern).

- [ ] **Step 1: Write the failing test**

```python
# tests/cloud_client/test_fetch_mpos.py
from custom_components.dreame_a2_mower.cloud_client._fetchers import _FetchersMixin


class _FakeClient(_FetchersMixin):
    """Minimal stub — fetch_mpos only uses self.action."""
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
    def action(self, siid, aiid, parameters=None, retry_count=2):
        assert siid == 2 and aiid == 50
        assert parameters == [{"m": "g", "t": "MPOS", "d": None}]
        if self._exc:
            raise self._exc
        return self._resp


def _ok(d):
    return {"siid": 2, "aiid": 50, "code": 0, "out": [{"m": "r", "r": 0, "d": d}]}


def test_fetch_mpos_ok():
    c = _FakeClient(_ok({"x": 95, "y": -4, "yaw": 0}))
    assert c.fetch_mpos() == {"result": "ok", "x": 95, "y": -4, "yaw": 0}


def test_fetch_mpos_idle_r_negative():
    c = _FakeClient({"out": [{"m": "r", "r": -3}]})
    assert c.fetch_mpos() == {"result": "idle"}
    c2 = _FakeClient({"out": [{"m": "r", "r": -1}]})
    assert c2.fetch_mpos() == {"result": "idle"}


def test_fetch_mpos_malformed_is_error():
    assert _FakeClient({"out": [{"m": "r", "r": 0, "d": {"x": 1}}]}).fetch_mpos() == {"result": "error"}
    assert _FakeClient({"out": []}).fetch_mpos() == {"result": "error"}
    assert _FakeClient("not-a-dict").fetch_mpos() == {"result": "error"}


def test_fetch_mpos_exception_is_error():
    assert _FakeClient(exc=RuntimeError("boom")).fetch_mpos() == {"result": "error"}
```

- [ ] **Step 2: Run it, confirm FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/cloud_client/test_fetch_mpos.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'fetch_mpos'`.

- [ ] **Step 3: Implement `fetch_mpos` in `_fetchers.py`**

Add this method inside `class _FetchersMixin` (place it near `fetch_remote`, which is the closest routed-get sibling). Use `_LOGGER` (already imported in this module):

```python
    def fetch_mpos(self) -> dict:
        """Live mower position via routed-get m:g t:MPOS (DIAGNOSTIC, RAW).

        Returns one of:
          {"result": "ok", "x": int, "y": int, "yaw": int}  — r:0 with data
          {"result": "idle"}   — r:-1/-3 (mower idle / no data, like MISTA)
          {"result": "error"}  — transport failure or malformed payload

        [tools/probes/read_key_probe.py@2026-06-09] observed r:0
        d={"x":95,"y":-4,"yaw":0} at dock-idle. The values are RAW cloud frame —
        units/frame UNVERIFIED; never transform or treat as the integration's
        position. Never raises.
        """
        try:
            resp = self.action(
                siid=2, aiid=50,
                parameters=[{"m": "g", "t": "MPOS", "d": None}],
            )
        except Exception as ex:  # noqa: BLE001 — diagnostic read never breaks callers
            _LOGGER.warning("fetch_mpos: %s", ex)
            return {"result": "error"}
        if not isinstance(resp, dict):
            return {"result": "error"}
        out = resp.get("out") or []
        if not out or not isinstance(out[0], dict):
            return {"result": "error"}
        env = out[0]
        if env.get("r") != 0:
            return {"result": "idle"}
        d = env.get("d")
        if not isinstance(d, dict) or not all(k in d for k in ("x", "y", "yaw")):
            return {"result": "error"}
        return {"result": "ok", "x": d["x"], "y": d["y"], "yaw": d["yaw"]}
```

- [ ] **Step 4: Run the test, confirm PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/cloud_client/test_fetch_mpos.py -v`
Expected: PASS (4 passed). If the import `from ..._fetchers import _FetchersMixin` can't resolve, check how existing `tests/cloud_client/` tests import the mixin and match that; create `tests/cloud_client/__init__.py` only if sibling test dirs have one.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client/_fetchers.py tests/cloud_client/test_fetch_mpos.py
git commit -m "feat(mpos): fetch_mpos routed-get (ok/idle/error)"
```

---

## Task 2: MowerState fields + pure `apply_mpos_result()`

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py`
- Modify: `custom_components/dreame_a2_mower/coordinator/_refreshers.py`
- Test: `tests/coordinator/test_apply_mpos_result.py`

- [ ] **Step 1: Add the 5 fields to `MowerState`**

Open `mower/state.py`, find the `MowerState` dataclass, and add these fields among the other optional diagnostic fields (match the surrounding style — they are dataclass fields with `= None` defaults; if the dataclass uses `field(default=None)` for some, plain `= None` is fine for scalars):

```python
    # MPOS diagnostic (routed-get m:g t:MPOS). RAW cloud values, untransformed —
    # NOT the integration's position. Surfaced for physical-match characterization.
    # [docs/superpowers/specs/2026-06-12-mpos-diagnostic-design.md]
    mpos_x: int | None = None
    mpos_y: int | None = None
    mpos_yaw: int | None = None
    mpos_updated_unix: int | None = None
    mpos_last_result: str | None = None
```

- [ ] **Step 2: Write the failing test for the pure helper**

```python
# tests/coordinator/test_apply_mpos_result.py
from custom_components.dreame_a2_mower.coordinator._refreshers import apply_mpos_result
from custom_components.dreame_a2_mower.mower.state import MowerState


def test_apply_ok_sets_fields_and_timestamp():
    s = MowerState()
    out = apply_mpos_result(s, {"result": "ok", "x": 95, "y": -4, "yaw": 0}, now_unix=1781000000)
    assert (out.mpos_x, out.mpos_y, out.mpos_yaw) == (95, -4, 0)
    assert out.mpos_updated_unix == 1781000000
    assert out.mpos_last_result == "ok"


def test_apply_idle_keeps_values_updates_result_only():
    s = MowerState(mpos_x=95, mpos_y=-4, mpos_yaw=0, mpos_updated_unix=1780000000, mpos_last_result="ok")
    out = apply_mpos_result(s, {"result": "idle"}, now_unix=1781000000)
    assert (out.mpos_x, out.mpos_y, out.mpos_yaw) == (95, -4, 0)   # unchanged
    assert out.mpos_updated_unix == 1780000000                     # NOT bumped
    assert out.mpos_last_result == "idle"


def test_apply_error_keeps_values_updates_result_only():
    s = MowerState(mpos_x=95, mpos_updated_unix=1780000000, mpos_last_result="ok")
    out = apply_mpos_result(s, {"result": "error"}, now_unix=1781000000)
    assert out.mpos_x == 95
    assert out.mpos_updated_unix == 1780000000
    assert out.mpos_last_result == "error"
```

- [ ] **Step 3: Run it, confirm FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_apply_mpos_result.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_mpos_result'`.

- [ ] **Step 4: Add the pure helper to `_refreshers.py`**

Add at module level (top of `coordinator/_refreshers.py`, alongside other module-level helpers; `dataclasses` is already imported there):

```python
def apply_mpos_result(state, res: dict, now_unix: int):
    """Merge a fetch_mpos() result into MowerState (pure, no side effects).

    On "ok": set mpos_x/y/yaw + mpos_updated_unix=now + mpos_last_result="ok".
    On "idle"/"error": keep the prior x/y/yaw + timestamp (no false "freshen"),
    only update mpos_last_result. RAW values — no transform.
    """
    import dataclasses
    if res.get("result") == "ok":
        return dataclasses.replace(
            state,
            mpos_x=res.get("x"), mpos_y=res.get("y"), mpos_yaw=res.get("yaw"),
            mpos_updated_unix=now_unix, mpos_last_result="ok",
        )
    return dataclasses.replace(state, mpos_last_result=res.get("result") or "error")
```

- [ ] **Step 5: Run the test, confirm PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_apply_mpos_result.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/state.py custom_components/dreame_a2_mower/coordinator/_refreshers.py tests/coordinator/test_apply_mpos_result.py
git commit -m "feat(mpos): MowerState fields + pure apply_mpos_result helper"
```

---

## Task 3: Coordinator `_refresh_mpos()`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_refreshers.py`

Wires fetch→apply→publish. Modeled exactly on `_refresh_remote` (same file, ~line 239) but button-triggered (NOT scheduled — do not add it to any `async_track_time_interval`).

- [ ] **Step 1: Confirm `time` is importable in this module**

Run: `grep -n "^import time\|^import\|^from" custom_components/dreame_a2_mower/coordinator/_refreshers.py | head`
If `import time` is absent, add it to the module's import block.

- [ ] **Step 2: Add the method inside `_RefreshersMixin`**

Place next to `_refresh_remote`:

```python
    async def _refresh_mpos(self) -> None:
        """On-demand MPOS diagnostic fetch (button-triggered; not scheduled).

        Surfaces the RAW routed-get position for physical-match characterization.
        Never drives MowerState.position_* — diagnostic only.
        """
        if not hasattr(self, "_cloud"):
            return
        res = await self.hass.async_add_executor_job(self._cloud.fetch_mpos)
        new = apply_mpos_result(self.data, res, int(time.time()))
        if new != self.data:
            self.async_set_updated_data(new)
        LOGGER.info("mpos refresh: result=%s", (res or {}).get("result"))
```

> `LOGGER` is already imported in `_refreshers.py` (used by sibling refreshers). If not, import it from `..const` like the other refreshers do.

- [ ] **Step 3: Sanity-check it imports**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -c "import ast; ast.parse(open('custom_components/dreame_a2_mower/coordinator/_refreshers.py').read()); print('ok')"`
Expected: `ok`. (The behaviour is covered by Task 2's pure-helper tests + Task 5's button test which calls through; a full coordinator-instantiation test is not warranted for this 6-line wiring.)

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_refreshers.py
git commit -m "feat(mpos): coordinator _refresh_mpos (button-triggered, unscheduled)"
```

---

## Task 4: MPOS diagnostic sensor

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor_device.py`
- Test: `tests/integration/test_mpos_sensor.py`

Uses the coordinator-based diagnostic descriptor (`DreameA2DiagnosticSensorEntityDescription`, whose `value_fn`/`extra_state_attributes_fn` receive the COORDINATOR — same as `_freshness_value`/`_api_endpoints_attrs`). Read those two examples in `sensor_device.py` first to match the exact descriptor class + field names.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_mpos_sensor.py
from custom_components.dreame_a2_mower.sensor_device import _mpos_value, _mpos_attrs
from custom_components.dreame_a2_mower.mower.state import MowerState


class _Coord:
    def __init__(self, state): self.data = state


def test_mpos_value_blank_when_unset():
    assert _mpos_value(_Coord(MowerState())) is None


def test_mpos_value_formats_triple():
    s = MowerState(mpos_x=95, mpos_y=-4, mpos_yaw=0)
    assert _mpos_value(_Coord(s)) == "95, -4, 0"


def test_mpos_attrs_exposes_raw_fields_and_result():
    s = MowerState(mpos_x=95, mpos_y=-4, mpos_yaw=0, mpos_updated_unix=1781000000, mpos_last_result="ok")
    a = _mpos_attrs(_Coord(s))
    assert a["x"] == 95 and a["y"] == -4 and a["yaw"] == 0
    assert a["last_result"] == "ok"
    assert a["last_updated"] is not None        # ISO timestamp
    assert "raw" in a["note"].lower()           # honesty note present


def test_mpos_attrs_blank_timestamp_when_never_refreshed():
    a = _mpos_attrs(_Coord(MowerState()))
    assert a["last_updated"] is None and a["last_result"] is None
```

- [ ] **Step 2: Run it, confirm FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_mpos_sensor.py -v`
Expected: FAIL — `ImportError: cannot import name '_mpos_value'`.

- [ ] **Step 3: Add the value/attrs functions to `sensor_device.py`**

Place near `_freshness_value`/`_freshness_attrs` (module-level, coordinator-arg form):

```python
def _mpos_value(coord) -> str | None:
    s = coord.data
    if s.mpos_x is None or s.mpos_y is None or s.mpos_yaw is None:
        return None
    return f"{s.mpos_x}, {s.mpos_y}, {s.mpos_yaw}"


def _mpos_attrs(coord) -> dict:
    from datetime import UTC, datetime
    s = coord.data
    last_updated = (
        datetime.fromtimestamp(s.mpos_updated_unix, tz=UTC).isoformat()
        if s.mpos_updated_unix else None
    )
    return {
        "x": s.mpos_x,
        "y": s.mpos_y,
        "yaw": s.mpos_yaw,
        "last_updated": last_updated,
        "last_result": s.mpos_last_result,
        "note": (
            "Raw cloud MPOS reading, untransformed — NOT the integration's "
            "position. Frame/units unverified. Press 'Refresh MPOS' to update."
        ),
    }
```

- [ ] **Step 4: Add the descriptor**

In the diagnostic descriptions table (where `key="api_endpoints_supported"` / `key="hardware_serial"` live), add a `DreameA2DiagnosticSensorEntityDescription` (use the SAME class as the api_endpoints entry — confirm its exact name by reading that entry):

```python
    DreameA2DiagnosticSensorEntityDescription(
        key="mpos",
        name="MPOS",
        icon="mdi:crosshairs-gps",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_mpos_value,
        extra_state_attributes_fn=_mpos_attrs,
    ),
```
> If the diagnostic descriptor REQUIRES `translation_key` (a translations CI test fails), add `translation_key="mpos"` here and a `"mpos"` entry under the sensor section of `custom_components/dreame_a2_mower/translations/en.json` (and `strings.json` if the repo mirrors them). Prefer plain `name="MPOS"` first.

- [ ] **Step 5: Run the test + a sensor-platform smoke**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_mpos_sensor.py -v`
Expected: PASS (4 passed). Then run the existing sensor tests to confirm the descriptor table still builds: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "sensor" -q` — 0 failures.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor_device.py tests/integration/test_mpos_sensor.py
git commit -m "feat(mpos): diagnostic sensor (raw x/y/yaw + last_result)"
```

---

## Task 5: "Refresh MPOS" button

**Files:**
- Modify: `custom_components/dreame_a2_mower/button.py`
- Test: `tests/integration/test_mpos_button.py`

Modeled exactly on `DreameA2RefreshCloudStateButton` (button.py ~line 282): `CoordinatorEntity + ButtonEntity`, diagnostic, calls a coordinator refresh method.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_mpos_button.py
import asyncio
from custom_components.dreame_a2_mower.button import DreameA2RefreshMposButton


class _Coord:
    def __init__(self):
        self.calls = 0
        # CoordinatorEntity.__init__ reads these; set minimally.
        self.last_update_success = True
    async def _refresh_mpos(self):
        self.calls += 1


def _make(coord):
    # Bypass CoordinatorEntity.__init__ (needs HA runtime) like the sibling
    # camera/button tests do; set the coordinator attr directly.
    btn = DreameA2RefreshMposButton.__new__(DreameA2RefreshMposButton)
    btn.coordinator = coord
    return btn


def test_press_calls_refresh_mpos():
    coord = _Coord()
    btn = _make(coord)
    asyncio.run(btn.async_press())
    assert coord.calls == 1
```
> Check how `tests/integration/test_mpos_button.py`'s siblings construct a button/camera under the stub venv (e.g. `tests/integration/test_photo_camera.py` uses `__new__`). Match that exact construction style; adjust `_make`/`_Coord` minimally if the sibling pattern differs.

- [ ] **Step 2: Run it, confirm FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_mpos_button.py -v`
Expected: FAIL — `ImportError: cannot import name 'DreameA2RefreshMposButton'`.

- [ ] **Step 3: Add the button class**

In `button.py`, right after `DreameA2RefreshCloudStateButton`, add (mirroring it exactly — `EntityCategory`, `mower_unique_id`, `mower_device_info`, `LOGGER` are already imported there):

```python
class DreameA2RefreshMposButton(
    CoordinatorEntity[DreameA2MowerCoordinator], ButtonEntity
):
    """On-demand fetch of the RAW MPOS diagnostic reading.

    MPOS ({x,y,yaw}) is the cloud's routed-get position. Values are surfaced
    raw (untransformed) on sensor.dreame_a2_mower_mpos for physical-match
    characterization; this button refreshes them. Diagnostic category.
    [docs/superpowers/specs/2026-06-12-mpos-diagnostic-design.md]
    """

    _attr_has_entity_name = True
    _attr_name = "Refresh MPOS"
    _attr_icon = "mdi:crosshairs-gps"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "refresh_mpos")
        self._attr_device_info = mower_device_info(coordinator)

    async def async_press(self) -> None:
        LOGGER.info("button.refresh_mpos: pressed; refreshing MPOS diagnostic")
        await self.coordinator._refresh_mpos()
```

- [ ] **Step 4: Register it in `async_setup_entry`**

In `button.py`'s `async_setup_entry`, where the parent-device buttons are appended (near `DreameA2RefreshCloudStateButton`), add:
```python
    entities.append(DreameA2RefreshMposButton(coordinator))
```
Confirm by reading the existing `entities.append(...)` block; match its placement (parent-device buttons, before `async_add_entities(entities)`).

- [ ] **Step 5: Run the test + button platform regression**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_mpos_button.py tests/ -k "button" -q`
Expected: PASS, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/button.py tests/integration/test_mpos_button.py
git commit -m "feat(mpos): Refresh MPOS diagnostic button"
```

---

## Task 6: entity-inventory + gates + full suite

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`

- [ ] **Step 1: Add the two entity rows**

Read an existing diagnostic sensor row and the `refresh_cloud_state` button row in `entity-inventory.yaml`; mirror their schema. Add:
- `sensor.dreame_a2_mower_mpos` — class `DreameA2*` (the diagnostic descriptor produces a generic sensor entity; match how other descriptor-based sensors are inventoried — they may be keyed by `key`/`unique_id` rather than a class). read source: routed-get `MPOS` (`inventory.yaml § MPOS`, status partial). control: read-only. status: `presumed`. Note: RAW, untransformed, diagnostic.
- `button.dreame_a2_mower_refresh_mpos` — class `DreameA2RefreshMposButton`. read source: n/a (action). control: triggers `_refresh_mpos`. status: `presumed`.

Use epistemic honesty: the entities are code-wired but not physically validated → `presumed`; do not assert MPOS is a position.

- [ ] **Step 2: Run the entity-inventory audit + schema validate**

Run:
```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
```
Expected: audit `missing from inventory: 0`, exit 0; `ok: inventory schema valid`. If the audit reports the new entities as missing/stale, fix the rows until it passes (it maps entity classes ↔ inventory rows).

- [ ] **Step 3: Per-map-naming regression + full suite**

Run:
```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_per_map_entity_names.py -q
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q
```
Expected: per-map naming PASS (MPOS entities are parent-device, `_attr_name` entity-only); full suite 0 failures.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml
git commit -m "docs(entity-inventory): MPOS diagnostic sensor + refresh button (presumed)"
```

---

## Spec coverage self-check

| Spec section | Task |
|---|---|
| §3.1 `fetch_mpos()` | 1 |
| §3.2 MowerState fields (5) | 2 |
| §3.3 sensor (one entity, attrs incl. last_result/note) | 4 |
| §3.4 button (button-only) | 5 |
| §4 error handling (ok/idle/error; no false freshen) | 1, 2, 3 |
| §5 honesty (entity-inventory presumed, no transform claim) | 6 |
| §6 testing | 1, 2, 4, 5, 6 |
| §7 out-of-scope (no driving, no transform, no auto-poll) | enforced (no `position_*` writes; `_refresh_mpos` unscheduled) |

## Final verification

- [ ] `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/cloud_client/test_fetch_mpos.py tests/coordinator/test_apply_mpos_result.py tests/integration/test_mpos_sensor.py tests/integration/test_mpos_button.py -v` → all PASS
- [ ] Full suite + inventory + entity-inventory + per-map gates green (Task 6)
- [ ] No release yet — this is observe-only; the user runs the button against the physical mower to characterize MPOS before any release/Phase-2 driving decision.
