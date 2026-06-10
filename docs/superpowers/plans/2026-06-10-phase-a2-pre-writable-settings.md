# Phase A2 — PRE writable per-map settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the per-map General-Mode settings (efficiency/height/direction/edge/OA/AI/EdgeMaster) change the mower by writing PRE (the firmware-read CFG, via the app's scoped bare-array envelope) and mirroring to SETTINGS (the cloud record the entities read), then flip the 14 controls to DEVICE_WRITABLE.

**Architecture:** Fix `set_pre` to emit a bare array; add a scoped `get_pre(idx,region)`; add pure `apply_pre`/`apply_pre_ai_bit` RMW builders; add coordinator dual-write methods (scoped get → set_pre → optional write_settings, revert on PRE failure); wire the per-map entities to them; flip verdicts. `edgemaster` is PRE-only (reads the s6p2 shadow).

**Tech Stack:** Python, vanilla pytest venv (`/data/claude/homeassistant/.venv-vanilla/bin/python`), inventory validators.

**Spec:** `docs/superpowers/specs/2026-06-10-phase-a2-pre-writable-settings-design.md`

**Reference data (capture 2026-06-09):**
- PRE SET = bare array `d:[ver=0, idx, region, ...settings]` (map at `[1]`, zone at `[2]`).
- PRE GET = `{"m":"g","t":"PRE","d":{"idx":<map>,"region":<zone>}}` → response payload `d` = the array.
- General baseline PRE array: `[0,0,0,0,55,1,8,1,0,1,1,2,1,20,10,7,1,2,0]` (idx [3]=eff,[4]=height×10,[5]=dirmode,[6]=angle,[7]=autoedge,[9]=OA-edges,[10]=edgemaster,[12]=lidar,[13]=OAheight,[14]=OAdist,[15]=AIbitmask,[16]=safeedge).
- SETTINGS per-map record fields: efficientMode, mowingHeight(cm float), mowingDirection(deg), mowingDirectionMode, edgeMowingAuto, edgeMowingSafe, edgeMowingObstacleAvoidance, obstacleAvoidanceEnabled, obstacleAvoidanceHeight, obstacleAvoidanceDistance, obstacleAvoidanceAi (+ the deferred cutterPosition/cutterPositionHeight/edgeMowingNum/edgeMowingWalkMode/obstacleAvoidanceSensitivity/edgeCuttingAttachment). NO edgemaster field.

**Per-control mapping (entity → PRE idx / SETTINGS field / value transform):**
| entity | PRE idx | SETTINGS field | transform |
|---|---|---|---|
| mowing_efficiency | 3 | efficientMode | passthrough 0/1 |
| mowing_height | 4 | mowingHeight | SETTINGS cm float; PRE = round(cm×10) |
| mowing_direction_mode | 5 | mowingDirectionMode | passthrough (verify order) |
| mowing_direction | 6 | mowingDirection | passthrough degrees |
| automatic_edge_mowing | 7 | edgeMowingAuto | passthrough 0/1 |
| obstacle_avoidance_on_edges | 9 | edgeMowingObstacleAvoidance | passthrough 0/1 |
| edgemaster | 10 | (none — PRE-only) | passthrough 0/1 |
| lidar_obstacle_recognition | 12 | obstacleAvoidanceEnabled | passthrough 0/1 |
| obstacle_avoidance_height | 13 | obstacleAvoidanceHeight | passthrough |
| obstacle_avoidance_distance | 14 | obstacleAvoidanceDistance | passthrough |
| safe_edge_mowing | 16 | edgeMowingSafe | passthrough 0/1 |
| ai_recognition_humans/animals/objects | 15 bit 0/1/2 | obstacleAvoidanceAi | bitmask RMW |

**Conventions for every task:**
- Python: `/data/claude/homeassistant/.venv-vanilla/bin/python` (`python` on PATH is broken).
- Stage commits by explicit path (concurrent process commits here; never `git add -A`).
- Co-Authored-By trailer for Claude Opus 4.8 on every commit.
- Branch is already `phase-a2-pre-writable-settings`.

---

### Task 1: Extend the capture fixture with PRE shapes

**Files:** Modify `tests/fixtures/cfg_envelopes_2026-06-09.json`

- [ ] **Step 1: Add a `pre` block** to the existing JSON (alongside `writes`/`reads`):

```json
  "pre": {
    "baseline": [0,0,0,0,55,1,8,1,0,1,1,2,1,20,10,7,1,2,0],
    "get_args_examples": [{"idx":0,"region":0},{"idx":1,"region":1},{"idx":1,"region":2}],
    "set_is_bare_array": true,
    "index_map": {"version":0,"map_idx":1,"region":2,"efficiency":3,"height_x10":4,"direction_mode":5,"direction_angle":6,"auto_edge":7,"oa_on_edges":9,"edgemaster":10,"lidar":12,"oa_height":13,"oa_distance":14,"ai_bitmask":15,"safe_edge":16}
  }
```

- [ ] **Step 2: Validate JSON**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -c "import json; json.load(open('tests/fixtures/cfg_envelopes_2026-06-09.json')); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/cfg_envelopes_2026-06-09.json
git commit -m "test(a2): extend fixture with PRE baseline + index map

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Pure PRE builders in `cfg_payloads.py`

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/cfg_payloads.py`
- Modify: `tests/protocol/test_cfg_payloads.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/protocol/test_cfg_payloads.py`):

```python
PRE_BASE = _FIX["pre"]["baseline"]  # [0,0,0,0,55,1,8,1,0,1,1,2,1,20,10,7,1,2,0]


def test_apply_pre_sets_index_and_scope():
    out = cp.apply_pre(PRE_BASE, map_idx=1, index=4, value=60)
    assert out[0] == 0      # version write-byte
    assert out[1] == 1      # map idx
    assert out[2] == 0      # General region
    assert out[4] == 60     # height changed
    # everything else preserved
    assert out[3] == PRE_BASE[3] and out[5] == PRE_BASE[5] and out[16] == PRE_BASE[16]
    assert len(out) == len(PRE_BASE)


def test_apply_pre_efficiency_passthrough():
    out = cp.apply_pre(PRE_BASE, map_idx=0, index=3, value=1)
    assert out[3] == 1 and out[1] == 0 and out[2] == 0


def test_apply_pre_ai_bit_set_and_clear():
    # baseline [15]=7 (all three on); clear humans (bit0) -> 6
    out = cp.apply_pre_ai_bit(PRE_BASE, map_idx=0, bit=0, on=False)
    assert out[15] == 6
    # set bit0 back on from 6
    base6 = list(PRE_BASE); base6[15] = 6
    out2 = cp.apply_pre_ai_bit(base6, map_idx=0, bit=0, on=True)
    assert out2[15] == 7


def test_apply_pre_none_base():
    assert cp.apply_pre(None, map_idx=0, index=4, value=60) is None
    assert cp.apply_pre([0, 0], map_idx=0, index=16, value=1) is None  # too short for idx 16
    assert cp.apply_pre_ai_bit(None, map_idx=0, bit=0, on=True) is None
```

- [ ] **Step 2: Run, expect fail**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_cfg_payloads.py -q`
Expected: FAIL (`apply_pre`/`apply_pre_ai_bit` missing).

- [ ] **Step 3: Implement** (append to `custom_components/dreame_a2_mower/protocol/cfg_payloads.py`):

```python
# --- PRE (General-Mode per-map preferences) builders ---------------------
# PRE READS as a positional array via get PRE {idx,region}; WRITES as a bare
# array {m:s,t:PRE,d:[...]} with version at [0]=0, map at [1], region at [2].

_PRE_MIN_LEN = 17  # need index 16 (safe_edge) addressable


def apply_pre(raw: Any, *, map_idx: int, index: int, value: Any) -> list | None:
    """RMW one PRE index. Returns the full write array (version=0, map_idx,
    region=0 General, target index set, rest preserved) or None if the base
    is missing/too short."""
    if not raw or len(raw) < _PRE_MIN_LEN or index >= len(raw):
        return None
    out = [int(x) for x in raw]
    out[0] = 0                      # version write-byte (app writes 0)
    out[1] = int(map_idx)           # map index
    out[2] = 0                      # General region
    out[index] = _i(value)
    return out


def apply_pre_ai_bit(raw: Any, *, map_idx: int, bit: int, on: bool) -> list | None:
    """RMW one bit of PRE[15] (AI obstacle-recognition bitmask)."""
    if not raw or len(raw) < _PRE_MIN_LEN:
        return None
    out = [int(x) for x in raw]
    out[0] = 0
    out[1] = int(map_idx)
    out[2] = 0
    mask = 1 << int(bit)
    out[15] = (out[15] | mask) if on else (out[15] & ~mask)
    return out
```

- [ ] **Step 4: Run, expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_cfg_payloads.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/cfg_payloads.py tests/protocol/test_cfg_payloads.py
git commit -m "feat(a2): pure PRE RMW builders (apply_pre, apply_pre_ai_bit)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Fix the `set_pre` envelope (the bug fix)

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/cfg_action.py` (`set_pre` ~L161-174)
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py` (`set_pre` docstring — the "no setter / r=-3" note is now wrong)
- Test: `tests/protocol/test_set_pre_envelope.py` (create)

- [ ] **Step 1: Write the failing test** (`tests/protocol/test_set_pre_envelope.py`):

```python
from custom_components.dreame_a2_mower.protocol import cfg_action


def test_set_pre_emits_bare_array():
    captured = {}
    def fake_send(siid, aiid, params):
        captured["siid"] = siid; captured["aiid"] = aiid; captured["params"] = params
        return {"result": {"out": [{"m": "r", "r": 0}]}}
    arr = [0, 1, 0, 0, 60, 1, 8, 1, 0, 1, 1, 2, 1, 20, 10, 7, 1, 2, 0]
    cfg_action.set_pre(fake_send, arr)
    payload = captured["params"][0]
    assert payload["m"] == "s" and payload["t"] == "PRE"
    # d must be the BARE ARRAY, not {"value": [...]}
    assert payload["d"] == arr
    assert not isinstance(payload["d"], dict)
```

- [ ] **Step 2: Run, expect fail**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_set_pre_envelope.py -q`
Expected: FAIL — `payload["d"]` is `{"value": [...]}` today.

- [ ] **Step 3: Fix `cfg_action.set_pre`** — change the send line:

```python
    return send_action(
        ROUTED_ACTION_SIID,
        ROUTED_ACTION_AIID,
        [{"m": "s", "t": "PRE", "d": pre_array}],
    )
```
(Keep the `len(pre_array) < 10` validation and the docstring; update the docstring's RMW note to say `d` is the bare array.)

- [ ] **Step 4: Update `cloud_client/_fetchers.py:set_pre` docstring** — replace the "Known result on g2408 fw 4.3.6_0550: t='PRE' has NO setter … every PRE write returns out[0].r=-3" paragraph with: the prior `r=-3` was a wrong-envelope artifact (the array was wrapped under `value`); the app sends the bare array `d:[...]` and the device accepts it (capture 2026-06-09). Keep the `out[0].r==0` success-check logic unchanged.

- [ ] **Step 5: Run, expect pass + no regression**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_set_pre_envelope.py tests/ -k "pre or cfg_action" -q`
Expected: PASS. If an existing test asserted the OLD `{"value":...}` shape, update it to the bare array (note it in your report).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/cfg_action.py custom_components/dreame_a2_mower/cloud_client/_fetchers.py tests/protocol/test_set_pre_envelope.py
git commit -m "fix(a2): set_pre emits bare array d:[...] (debunks r=-3 no-setter)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Scoped `get_pre(idx, region)`

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/cfg_action.py` (add `get_pre`)
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py` (add `get_pre` method)
- Test: `tests/protocol/test_get_pre.py` (create)

- [ ] **Step 1: Write the failing test** (`tests/protocol/test_get_pre.py`):

```python
from custom_components.dreame_a2_mower.protocol import cfg_action


def test_get_pre_scoped_args_and_returns_array():
    arr = [0, 1, 0, 0, 60, 1, 8, 1, 0, 1, 1, 2, 1, 20, 10, 7, 1, 2, 0]
    captured = {}
    def fake_send(siid, aiid, params):
        captured["params"] = params
        return {"result": {"out": [{"m": "g", "t": "PRE", "d": arr}]}}
    out = cfg_action.get_pre(fake_send, idx=1, region=0)
    p = captured["params"][0]
    assert p == {"m": "g", "t": "PRE", "d": {"idx": 1, "region": 0}}
    assert out == arr
```

- [ ] **Step 2: Run, expect fail**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_get_pre.py -q`
Expected: FAIL (`get_pre` missing).

- [ ] **Step 3: Implement `cfg_action.get_pre`** (next to `get_cfg`):

```python
def get_pre(send_action, *, idx: int, region: int) -> list:
    """Read the PRE preferences array for map `idx`, zone `region`.
    Returns the bare array (the response payload's `d`)."""
    raw = send_action(
        ROUTED_ACTION_SIID, ROUTED_ACTION_AIID,
        [{"m": "g", "t": "PRE", "d": {"idx": int(idx), "region": int(region)}}],
    )
    payload = _unwrap(raw)
    d = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(d, list):
        raise CfgActionError(f"get_pre returned no array `d`: {payload!r}")
    return d
```

- [ ] **Step 4: Add `cloud_client/_fetchers.py:get_pre`** (mirror `set_pre`'s structure — runs `cfg_action.get_pre(self.action, idx=…, region=…)`, returns the list or `None` on error):

```python
    def get_pre(self, idx: int, region: int) -> list | None:
        """Scoped PRE read for map `idx`, zone `region`. None on failure."""
        from ..protocol import cfg_action  # type: ignore[import]
        try:
            return cfg_action.get_pre(self.action, idx=idx, region=region)
        except Exception as ex:  # pragma: no cover - defensive
            _LOGGER.warning("get_pre(idx=%s,region=%s) failed: %s", idx, region, ex)
            return None
```

- [ ] **Step 5: Run, expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_get_pre.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/cfg_action.py custom_components/dreame_a2_mower/cloud_client/_fetchers.py tests/protocol/test_get_pre.py
git commit -m "feat(a2): scoped get_pre(idx,region) routed read

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Coordinator dual-write methods

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py`
- Test: `tests/integration/test_pre_write.py` (create)

Add `write_map_general_setting` (index) and `write_map_general_ai_bit` (bitmask), both sharing an internal `_write_pre_scoped(map_id, apply_fn)`.

- [ ] **Step 1: Write the failing test** (`tests/integration/test_pre_write.py`):

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin

PRE = [0, 0, 0, 0, 55, 1, 8, 1, 0, 1, 1, 2, 1, 20, 10, 7, 1, 2, 0]


def _coord():
    c = _WritesMixin()
    c._cloud = SimpleNamespace(
        get_pre=MagicMock(return_value=list(PRE)),
        set_pre=MagicMock(return_value=True),
    )
    async def _exec(fn, *a):  # emulate hass.async_add_executor_job
        return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    c.write_settings = AsyncMock(return_value=True)
    c._refresh_cloud_state = AsyncMock()
    return c


@pytest.mark.asyncio
async def test_write_map_general_setting_dual_writes():
    c = _coord()
    ok = await c.write_map_general_setting(
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert ok is True
    # scoped get for map 1 region 0
    c._cloud.get_pre.assert_called_once_with(1, 0)
    # set_pre got the RMW array: version 0, map 1, region 0, [4]=60
    arr = c._cloud.set_pre.call_args[0][0]
    assert arr[0] == 0 and arr[1] == 1 and arr[2] == 0 and arr[4] == 60
    # SETTINGS mirrored
    c.write_settings.assert_awaited_once_with(map_id=1, field="mowingHeight", value=6.0)


@pytest.mark.asyncio
async def test_pre_failure_skips_settings():
    c = _coord()
    c._cloud.set_pre = MagicMock(return_value=False)
    ok = await c.write_map_general_setting(
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert ok is False
    c.write_settings.assert_not_awaited()  # device write failed → no record write


@pytest.mark.asyncio
async def test_no_base_aborts():
    c = _coord()
    c._cloud.get_pre = MagicMock(return_value=None)
    ok = await c.write_map_general_setting(
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert ok is False
    c._cloud.set_pre.assert_not_called()
    c.write_settings.assert_not_awaited()


@pytest.mark.asyncio
async def test_edgemaster_pre_only():
    c = _coord()
    ok = await c.write_map_general_setting(map_id=0, pre_index=10, pre_value=1)
    assert ok is True
    arr = c._cloud.set_pre.call_args[0][0]
    assert arr[10] == 1 and arr[1] == 0
    c.write_settings.assert_not_awaited()  # no settings_field → PRE only


@pytest.mark.asyncio
async def test_ai_bit_dual_write():
    c = _coord()
    ok = await c.write_map_general_ai_bit(
        map_id=0, bit=0, on=False,
        settings_value=6,
    )
    assert ok is True
    arr = c._cloud.set_pre.call_args[0][0]
    assert arr[15] == 6
    c.write_settings.assert_awaited_once_with(map_id=0, field="obstacleAvoidanceAi", value=6)
```

- [ ] **Step 2: Run, expect fail**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_pre_write.py -q`
Expected: FAIL (methods missing).

- [ ] **Step 3: Implement** in `coordinator/_writes.py` (inside `_WritesMixin`):

```python
    async def _write_pre_scoped(self, map_id: int, apply_fn) -> bool:
        """Scoped PRE read for (map_id, region 0) → apply_fn(array) → set_pre.
        apply_fn returns the full write array or None (no base). Returns True
        only on device accept (set_pre out[0].r==0)."""
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("_write_pre_scoped: cloud client not ready")
            return False
        raw = await self.hass.async_add_executor_job(self._cloud.get_pre, map_id, 0)
        new_array = apply_fn(raw)
        if new_array is None:
            LOGGER.warning("_write_pre_scoped: no PRE base for map %s — aborted", map_id)
            return False
        return await self.hass.async_add_executor_job(self._cloud.set_pre, new_array)

    async def write_map_general_setting(
        self, *, map_id: int, pre_index: int, pre_value, 
        settings_field: str | None = None, settings_value=None,
    ) -> bool:
        """Dual-write a per-map General-Mode setting: PRE (device) first, then
        SETTINGS (cloud record) if settings_field given. A SETTINGS failure is
        logged but does NOT revert the device. Returns the PRE-write result."""
        from ..protocol import cfg_payloads
        ok = await self._write_pre_scoped(
            map_id,
            lambda raw: cfg_payloads.apply_pre(raw, map_idx=map_id, index=pre_index, value=pre_value),
        )
        if not ok:
            return False
        if settings_field is not None:
            s_ok = await self.write_settings(map_id=map_id, field=settings_field, value=settings_value)
            if not s_ok:
                LOGGER.warning(
                    "write_map_general_setting: PRE ok but SETTINGS %s failed (device changed; "
                    "cloud record stale until next reconcile)", settings_field,
                )
        return True

    async def write_map_general_ai_bit(
        self, *, map_id: int, bit: int, on: bool, settings_value: int,
    ) -> bool:
        """Dual-write one AI-recognition bit: PRE[15] bit + SETTINGS.obstacleAvoidanceAi."""
        from ..protocol import cfg_payloads
        ok = await self._write_pre_scoped(
            map_id,
            lambda raw: cfg_payloads.apply_pre_ai_bit(raw, map_idx=map_id, bit=bit, on=on),
        )
        if not ok:
            return False
        s_ok = await self.write_settings(
            map_id=map_id, field="obstacleAvoidanceAi", value=settings_value,
        )
        if not s_ok:
            LOGGER.warning("write_map_general_ai_bit: PRE ok but SETTINGS failed (stale until reconcile)")
        return True
```

- [ ] **Step 4: Run, expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_pre_write.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_writes.py tests/integration/test_pre_write.py
git commit -m "feat(a2): coordinator PRE dual-write (write_map_general_setting/_ai_bit)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Dual-write entity helper

**Files:**
- Modify: `custom_components/dreame_a2_mower/_settings_writes.py`
- Test: `tests/integration/test_pre_settings_helper.py` (create)

Add `pre_settings_optimistic_write` — like `settings_optimistic_write` but it calls the coordinator's PRE dual-write and reverts on failure.

- [ ] **Step 1: Write the failing test** (`tests/integration/test_pre_settings_helper.py`):

```python
import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from custom_components.dreame_a2_mower import _settings_writes as sw


def _entity(state_val):
    coord = SimpleNamespace()
    coord.data = SimpleNamespace(settings_mowing_height=state_val)
    # dataclasses.replace needs a real dataclass; use a lightweight one
    @dataclasses.dataclass
    class S:
        settings_mowing_height: float
    coord.data = S(settings_mowing_height=state_val)
    coord.write_map_general_setting = AsyncMock(return_value=True)
    ent = SimpleNamespace(coordinator=coord, entity_id="number.x",
                          async_write_ha_state=lambda: None,
                          hass=SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock())))
    return ent, coord


@pytest.mark.asyncio
async def test_pre_settings_helper_calls_dual_write():
    ent, coord = _entity(5.5)
    await sw.pre_settings_optimistic_write(
        ent, state_field="settings_mowing_height", new_value=6.0,
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert coord.data.settings_mowing_height == 6.0
    coord.write_map_general_setting.assert_awaited_once_with(
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )


@pytest.mark.asyncio
async def test_pre_settings_helper_reverts_on_failure():
    ent, coord = _entity(5.5)
    coord.write_map_general_setting = AsyncMock(return_value=False)
    await sw.pre_settings_optimistic_write(
        ent, state_field="settings_mowing_height", new_value=6.0,
        map_id=1, pre_index=4, pre_value=60,
        settings_field="mowingHeight", settings_value=6.0,
    )
    assert coord.data.settings_mowing_height == 5.5  # reverted
    ent.hass.services.async_call.assert_awaited()  # notified
```

- [ ] **Step 2: Run, expect fail** then **Step 3: implement** in `_settings_writes.py`:

```python
async def pre_settings_optimistic_write(
    entity, *, state_field: str, new_value, map_id: int,
    pre_index: int, pre_value, settings_field: str | None = None, settings_value=None,
) -> None:
    """Optimistic per-map General-Mode write via the coordinator PRE dual-write,
    reverting the local state + notifying if the device (PRE) write fails."""
    coord = entity.coordinator
    old_value = getattr(coord.data, state_field)
    coord.data = dataclasses.replace(coord.data, **{state_field: new_value})
    entity.async_write_ha_state()
    ok = await coord.write_map_general_setting(
        map_id=map_id, pre_index=pre_index, pre_value=pre_value,
        settings_field=settings_field, settings_value=settings_value,
    )
    if ok:
        return
    coord.data = dataclasses.replace(coord.data, **{state_field: old_value})
    entity.async_write_ha_state()
    await entity.hass.services.async_call(
        "persistent_notification", "create",
        service_data={
            "title": "Dreame A2 Mower: setting write rejected",
            "message": (
                f"The mower rejected the write of {state_field}={new_value!r}. "
                f"Reverted to {old_value!r}."
            ),
            "notification_id": f"dreame_a2_write_fail_{entity.entity_id}",
        },
        blocking=False,
    )


async def pre_settings_ai_bit_write(
    entity, *, state_field: str, new_value: bool, map_id: int, bit: int,
    settings_value: int,
) -> None:
    """AI-bit variant — calls coordinator.write_map_general_ai_bit."""
    coord = entity.coordinator
    old_value = getattr(coord.data, state_field)
    coord.data = dataclasses.replace(coord.data, **{state_field: new_value})
    entity.async_write_ha_state()
    ok = await coord.write_map_general_ai_bit(
        map_id=map_id, bit=bit, on=bool(new_value), settings_value=settings_value,
    )
    if ok:
        return
    coord.data = dataclasses.replace(coord.data, **{state_field: old_value})
    entity.async_write_ha_state()
    await entity.hass.services.async_call(
        "persistent_notification", "create",
        service_data={
            "title": "Dreame A2 Mower: setting write rejected",
            "message": f"The mower rejected the AI-recognition write. Reverted to {old_value!r}.",
            "notification_id": f"dreame_a2_write_fail_{entity.entity_id}",
        },
        blocking=False,
    )
```
(Some per-map entities read from `cloud_state.settings`, not `coord.data` — for those the optimistic local update may be a no-op on the read path; that's fine, the post-write cloud refresh reconciles. Keep `state_field` updates for the entities that do mirror into `coord.data`; if an entity has no matching `coord.data` field, pass its `_STATE_FIELD` if one exists, else this helper still drives the dual-write and the revert just re-reads cloud state. The build confirms each entity's state_field.)

- [ ] **Step 4: Run, expect pass** → **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/_settings_writes.py tests/integration/test_pre_settings_helper.py
git commit -m "feat(a2): pre_settings_optimistic_write + ai_bit helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Wire SETTINGS-reading selects + numbers

**Files:**
- Modify: `custom_components/dreame_a2_mower/select_map_settings.py`
- Modify: `custom_components/dreame_a2_mower/number.py`

Repoint these handlers from `settings_optimistic_write` (SETTINGS-only) to `pre_settings_optimistic_write` (dual-write), supplying the PRE index + PRE value.

- [ ] **Step 1: Read both files** to find each handler and its current `settings_optimistic_write(...)` call + the entity's `_map_id`, state_field, and how it computes the SETTINGS value.

- [ ] **Step 2: Update each handler.** Mapping (entity → pre_index, pre_value expr, settings_field, settings_value expr):

| entity (file) | pre_index | pre_value | settings_field | settings_value |
|---|---|---|---|---|
| mowing_direction select (select_map_settings) | 6 | `idx*90` | mowingDirection | `idx*90` |
| mowing_direction_mode select | 5 | `idx` | mowingDirectionMode | `idx` |
| mowing_efficiency select | 3 | `idx` | efficientMode | `idx` |
| mowing_height number | 4 | `round(value*10)` | mowingHeight | `value` (cm float) |
| obstacle_avoidance_height number | 13 | `int(value)` | obstacleAvoidanceHeight | `int(value)` |
| obstacle_avoidance_distance number | 14 | `int(value)` | obstacleAvoidanceDistance | `int(value)` |

Each handler keeps its read_only guard (it'll stop short-circuiting once Task 10 flips the verdict) and its option/value resolution; only the write call changes, e.g. for mowing_direction:
```python
        await pre_settings_optimistic_write(
            self, state_field="settings_mowing_direction", new_value=idx * 90,
            map_id=self._map_id, pre_index=6, pre_value=idx * 90,
            settings_field="mowingDirection", settings_value=idx * 90,
        )
```
Import `pre_settings_optimistic_write` from `._settings_writes`. Use each entity's real `_STATE_FIELD`/state field name (verify in file).

- [ ] **Step 3: Syntax check**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -c "import ast; [ast.parse(open(f).read()) for f in ['custom_components/dreame_a2_mower/select_map_settings.py','custom_components/dreame_a2_mower/number.py']]; print('ok')"`

- [ ] **Step 4: Run per-map select/number tests** (read-only assertions flip in Task 10; note expected failures):

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "map and (select or number)" -q`

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/select_map_settings.py custom_components/dreame_a2_mower/number.py
git commit -m "feat(a2): per-map direction/mode/efficiency/height/OA selects+numbers → PRE dual-write

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Wire SETTINGS-reading switches + AI bitmask

**Files:**
- Modify: `custom_components/dreame_a2_mower/switch_global.py` (AI recognition base `_AiRecognitionBitSwitch` in `_switch_base.py`) and the per-map SETTINGS switches (automatic_edge_mowing/safe_edge_mowing/obstacle_avoidance_on_edges/lidar_obstacle_recognition).
- Modify: `custom_components/dreame_a2_mower/_switch_base.py` (the `_AiRecognitionBitSwitch._toggle` + the per-map SETTINGS switch classes' handlers).

- [ ] **Step 1: Read** `_switch_base.py` for `_AiRecognitionBitSwitch` and the per-map SETTINGS switch classes (DreameA2EdgeMowingAutoSwitch etc.) to find their `_map_id`, state field, and current `_settings_switch_optimistic_write` calls.

- [ ] **Step 2: Repoint the 4 SETTINGS switches** to `pre_settings_optimistic_write`:

| switch | pre_index | settings_field |
|---|---|---|
| automatic_edge_mowing | 7 | edgeMowingAuto |
| safe_edge_mowing | 16 | edgeMowingSafe |
| obstacle_avoidance_on_edges | 9 | edgeMowingObstacleAvoidance |
| lidar_obstacle_recognition | 12 | obstacleAvoidanceEnabled |

pattern (async_turn_on with enabled=True / off with False):
```python
        await pre_settings_optimistic_write(
            self, state_field="settings_edge_mowing_auto", new_value=enabled,
            map_id=self._map_id, pre_index=7, pre_value=int(enabled),
            settings_field="edgeMowingAuto", settings_value=int(enabled),
        )
```
Use each switch's real state_field. Keep the read_only guard.

- [ ] **Step 3: Repoint `_AiRecognitionBitSwitch._toggle`** to compute the new bitmask and call `pre_settings_ai_bit_write`:
```python
    async def _toggle(self, on: bool) -> None:
        if self.read_only:
            return await self._reject_readonly_write()
        cs = getattr(self.coordinator, "cloud_state", None)
        old = (cs.settings.by_map_id_canonical.get(self._map_id, {}).get("obstacleAvoidanceAi") or 0) if cs else 0
        new_mask = (old | self._BIT) if on else (old & ~self._BIT)
        # _BIT is the mask (1<<bit); derive bit index:
        bit = self._BIT.bit_length() - 1
        await pre_settings_ai_bit_write(
            self, state_field="<ai state field or a noop>", new_value=on,
            map_id=self._map_id, bit=bit, settings_value=new_mask,
        )
```
Confirm `_BIT` is the mask (1/2/4) so `bit_length()-1` gives 0/1/2; if `_BIT` is already the bit index, pass it directly. Use the entity's real optimistic state field if it has one; if the AI switch reads only from cloud_state (no coord.data field), pass a state_field that exists or adapt the helper call so revert re-reads cloud state (the build resolves this — do not invent a non-existent dataclass field).

- [ ] **Step 4: Syntax + tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -c "import ast; ast.parse(open('custom_components/dreame_a2_mower/_switch_base.py').read()); print('ok')"`
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "ai_recognition or edge_mowing or map and switch" -q`
(read-only assertions flip in Task 10).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/_switch_base.py custom_components/dreame_a2_mower/switch_global.py
git commit -m "feat(a2): per-map edge/OA/lidar switches + AI-recognition bits → PRE dual-write

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Wire edgemaster (PRE-only)

**Files:**
- Modify: `custom_components/dreame_a2_mower/switch_map.py`

`edgemaster` reads the s6p2 PRE shadow (no SETTINGS field). Its write is PRE-only (settings_field omitted).

- [ ] **Step 1: Read** `switch_map.py:DreameA2MapEdgemasterSwitch` (`async_turn_on`/`async_turn_off`, currently `_reject_readonly_write`).

- [ ] **Step 2: Implement the handlers** to call the coordinator PRE-only write + optimistic-on-shadow:
```python
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        if self.read_only:
            return await self._reject_readonly_write()
        ok = await self.coordinator.write_map_general_setting(
            map_id=self._map_id, pre_index=10, pre_value=int(enabled),
        )  # PRE-only: no settings_field
        if not ok:
            await self.hass.services.async_call(
                "persistent_notification", "create",
                service_data={
                    "title": "Dreame A2 Mower: setting write rejected",
                    "message": f"The mower rejected EdgeMaster={enabled}.",
                    "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
                }, blocking=False,
            )
        self.async_write_ha_state()  # re-read shadow (refreshes from s6p2 push)
```
(EdgeMaster reads the shadow, which the device's s6p2 push updates after the write — no local optimistic dataclass field to set. The `async_write_ha_state()` re-publishes; the value updates when the shadow refreshes.)

- [ ] **Step 3: Test** — create `tests/integration/test_edgemaster_write.py` asserting `async_turn_on` calls `coordinator.write_map_general_setting(map_id=…, pre_index=10, pre_value=1)` with NO settings_field, and that read_only short-circuits when the verdict is read-only. Use the `object.__new__` construction pattern from `tests/integration/test_cfg_switch_writes.py`.

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_edgemaster_write.py -q`

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/switch_map.py tests/integration/test_edgemaster_write.py
git commit -m "feat(a2): edgemaster PRE-only write (reads s6p2 shadow)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Flip verdicts + update read-only tests

**Files:**
- Modify: `custom_components/dreame_a2_mower/control_honesty.py`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml` (control_mode fields)
- Modify: existing read-only tests for these controls

- [ ] **Step 1: Flip** in `control_honesty.py` `CONTROL_MODES` `_C`/`_N` → `_W` for these per-map leaves:
  `map_N_settings_mowing_direction`, `map_N_settings_mowing_direction_mode`, `map_N_mowing_efficiency`, `map_N_settings_mowing_height`, `map_N_settings_obstacle_avoidance_height`, `map_N_settings_obstacle_avoidance_distance`, `map_N_automatic_edge_mowing`, `map_N_safe_edge_mowing`, `map_N_obstacle_avoidance_on_edges`, `map_N_lidar_obstacle_recognition`, `map_N_edgemaster`, `map_N_ai_recognition_humans`, `map_N_ai_recognition_animals`, `map_N_ai_recognition_objects`.
  Do NOT flip the deferred SETTINGS-only leaves (`map_N_settings_cutter_position`, `map_N_settings_cutter_position_height`, `map_N_settings_edge_mowing_num`, `map_N_settings_obstacle_avoidance_sensitivity`, `map_N_edge_walk_mode`) — they stay read-only.

- [ ] **Step 2: Mirror** the same control_mode → `device_writable` in `entity-inventory.yaml`.

- [ ] **Step 3: Update read-only test assertions** for these 14 controls to expect writable (positive assertions, not deletions):
Run: `grep -rnE "read_only|READ_ONLY|device_writable|snap.?back" tests/ | grep -iE "map.*(mowing_direction|mowing_efficiency|mowing_height|obstacle_avoidance_(height|distance)|automatic_edge|safe_edge|obstacle_avoidance_on_edges|lidar|edgemaster|ai_recognition)"`
Update each.

- [ ] **Step 4: Run inventory + control-honesty tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/ tests/ -k "control_honesty or control_mode" -q`
Expected: code-sync test green; updated read-only tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/control_honesty.py custom_components/dreame_a2_mower/entity-inventory.yaml tests/
git commit -m "feat(a2): flip 14 per-map General-Mode controls to DEVICE_WRITABLE

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Inventory fact-discipline (retract r=-3, record PRE envelope, TODO)

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify: `docs/research/knowledge-gaps.md`

- [ ] **Step 1: Retract the r=-3 claim** in `inventory.yaml`. Grep the PRE entry (and the s6p2 entry) for the prior "no PRE setter / r=-3" claim:
Run: `grep -nE "no.*PRE setter|r=-3|no routed-action setter|has NO setter" custom_components/dreame_a2_mower/inventory.yaml`
Append a `status: retracted` verification to the PRE entry quoting the prior text VERBATIM, with reason: the prior r=-3 was a wrong-envelope artifact (`d:{value:[...]}`); the app sends the bare array `d:[...]` and the device accepts it. Append a `status: verified` record documenting the PRE write envelope (bare array; map at `[1]`, region at `[2]`; GET via `{idx,region}` named args) + the PRE↔SETTINGS dual-store relationship. Evidence `app-mitm:2026-06-09-settings-sweep`. Bump `last_seen: "2026-06-10"`.

- [ ] **Step 2: entity-inventory verifications** — for each of the 14 flipped controls, append a `status: verified` record: now wired + writable via PRE (+SETTINGS for the 13; PRE-only for edgemaster) RMW; bump `last_verified`.

- [ ] **Step 3: TODO for deferred fields** — add to `docs/research/knowledge-gaps.md` an `[UNKNOWN — to capture]` entry: SETTINGS-only per-map fields (cutterPosition, cutterPositionHeight, edgeMowingNum, edgeMowingWalkMode, obstacleAvoidanceSensitivity, edgeCuttingAttachment) — no PRE index; whether a SETTINGS-only write changes the mower is unverified; capture step = toggle each in the app, diff PRE vs SETTINGS to see which store carries it. Also add a matching `open_questions` line to the relevant inventory entry.

- [ ] **Step 4: Validate + gates**

Run:
```
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/audit_outstanding_retractions.py
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/ -q
```
Expected: validator ok; entity audit 0 missing; retraction audit clean; inventory tests green.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml docs/research/knowledge-gaps.md
git commit -m "inventory(a2): retract r=-3 PRE-no-setter; record bare-array PRE envelope + dual-store; TODO SETTINGS-only fields

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Full suite + final verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm map_id ↔ PRE idx + direction-mode enum order.** Read `coordinator/_cloud_state.py` / `cloud_state.py` to confirm `maps_by_id` keys equal the cloud `mapIndex` (the value passed as PRE `idx`). Read the mowing_direction_mode select's option list + the SETTINGS `mowingDirectionMode` values and confirm PRE[5] uses the same enum (Phase 0: PRE[5] 0=Crisscross/1=Customize/2=Chequerboard). If either differs, add the transform in the relevant Task-7 handler and re-commit. Record the confirmation (or the transform) in your report.

- [ ] **Step 2: Full suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: 0 failures; 4 skipped; passed count ≥ prior baseline + new A2 tests.

- [ ] **Step 3: Inventory gates**

Run:
```
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_audit.py --consistency
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/audit_outstanding_retractions.py
```
Expected: all clean.

- [ ] **Step 4: Report** the final pass/skip counts, the 14 controls flipped, the map_id↔idx + direction-mode confirmations, and confirm the deferred SETTINGS-only fields stayed read-only.
