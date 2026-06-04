# Control-honesty markers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every read-only control entity wear a padlock and snap back (instead of faking a save), driven by a single `control_mode` source of truth, so a future write-path unlock is a one-line flip.

**Architecture:** A pure-Python `control_honesty.py` holds the `ControlMode` enum, `READ_ONLY_MODES`, a `CONTROL_MODES` map (keyed by the same entity-id templates as `entity-inventory.yaml`), an entity→mode resolver, and a `_ControlHonestyMixin`. Each control base class mixes it in, resolves its mode in `__init__`, sets a padlock icon + `read_only` attribute when read-only, and short-circuits its write handler to a snap-back. A CI test asserts `CONTROL_MODES` equals the inventory verdict.

**Tech Stack:** Python 3.13, Home Assistant entity platforms (stubbed in the vanilla test venv), pytest, PyYAML.

**Spec:** `docs/superpowers/specs/2026-06-04-control-honesty-markers-design.md`
**Audit:** `docs/research/control-honesty-audit-2026-06-03.md`

**Test runner (this repo):** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest`
**Commit policy:** main branch, stage by explicit path, end messages with the repo Co-Authored-By trailer.

---

## File Structure

- **Create** `custom_components/dreame_a2_mower/control_honesty.py` — enum, `READ_ONLY_MODES`, `CONTROL_MODES`, `resolve_control_mode()`, `_ControlHonestyMixin`. Pure Python (no `homeassistant.*` import) so the sync test loads it in the vanilla venv.
- **Create** `tests/inventory/test_control_mode_code_sync.py` — code↔inventory equality gate.
- **Create** `tests/unit/test_control_honesty.py` — resolver + mixin behaviour unit tests.
- **Modify** `entity-inventory.yaml` — re-key the two generic `control_mode_by_key` maps to the entity-key leaf.
- **Modify** `_switch_base.py`, `_select_base.py`, `number.py`, `time.py` — mix in `_ControlHonestyMixin`, resolve mode in `__init__`, add the snap-back guard to write handlers.
- **Modify** `dashboards/mower/dashboard.yaml` — one header note.

Only the four platforms with read-only members (number/select/switch/time) wire the mixin. `button` / `lawn_mower` have no read-only members; their ids appear in `CONTROL_MODES` for the sync test only — no entity wiring.

---

## Task 1: Re-key the generic `control_mode_by_key` maps to the entity-key leaf

Entities resolve their mode by the entity-id leaf (descriptor `.key`, e.g. `child_lock`), not the CFG key (`CLS`). Re-key the two generic rows so code and inventory share keys.

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`

- [ ] **Step 1: Replace the switch `<key>` `control_mode_by_key` block**

Find the block under `id: "switch.dreame_a2_mower_<key>"` and replace the whole `control_mode_by_key:` mapping with (keys = descriptor `.key`):

```yaml
    control_mode_by_key:
      child_lock: device_writable
      anti_theft_lift_alarm: device_writable
      anti_theft_offmap_alarm: device_writable
      anti_theft_realtime_location: device_writable
      frost_protection: device_writable
      auto_recharge_standby: device_writable
      ai_obstacle_photos: device_writable
      msg_alert_anomaly: device_writable
      msg_alert_error: device_writable
      msg_alert_task: device_writable
      msg_alert_consumables: device_writable
      voice_regular_notification: device_writable
      voice_work_status: device_writable
      voice_special_status: device_writable
      voice_error_status: device_writable
      dnd: read_only_confirmed
      low_speed_at_night: read_only_confirmed
      custom_charging_period: read_only_confirmed
      rain_protection: read_only_pending
      led_period: read_only_noop
      led_in_standby: read_only_noop
      led_in_working: read_only_noop
      led_in_charging: read_only_noop
      led_in_error: read_only_noop
      human_presence_alert: read_only_noop
```

- [ ] **Step 2: Replace the number `<key>` `control_mode_by_key` block**

Under `id: "number.dreame_a2_mower_<key>"`, replace its `control_mode_by_key:` with:

```yaml
    control_mode_by_key:
      volume: device_writable
      auto_recharge_battery_pct: read_only_confirmed
      resume_battery_pct: read_only_confirmed
```

- [ ] **Step 3: Verify YAML + existing gate still pass**

Run: `python3 -c "import yaml; yaml.safe_load(open('custom_components/dreame_a2_mower/entity-inventory.yaml'))"`
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_control_mode_gate.py -q`
Expected: YAML loads; gate PASSES (values are still valid modes).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml
git commit -m "refactor(inventory): re-key control_mode_by_key to entity-key leaf

Aligns the generic switch/number by_key maps with the descriptor .key the
entities resolve by, so the upcoming code-sync test is a direct comparison.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `control_honesty.py` — enum, modes, CONTROL_MODES, resolver

**Files:**
- Create: `custom_components/dreame_a2_mower/control_honesty.py`
- Test: `tests/unit/test_control_honesty.py`

- [ ] **Step 1: Write the failing resolver test**

Create `tests/unit/test_control_honesty.py`:

```python
"""Unit tests for control_honesty resolver + modes."""
from custom_components.dreame_a2_mower.control_honesty import (
    ControlMode, READ_ONLY_MODES, CONTROL_MODES, resolve_control_mode,
)


def test_read_only_modes_membership():
    assert ControlMode.READ_ONLY_CONFIRMED in READ_ONLY_MODES
    assert ControlMode.DEVICE_WRITABLE not in READ_ONLY_MODES
    assert ControlMode.INTEGRATION_LOCAL not in READ_ONLY_MODES


def test_resolve_direct_scalar_id():
    # per-map settings → 1:1 row, scalar
    assert resolve_control_mode(
        platform="number", key="map_N_settings_mowing_height"
    ) is ControlMode.READ_ONLY_CONFIRMED


def test_resolve_generic_switch_by_leaf():
    # falls back to switch.<key> sub-map, keyed by descriptor leaf
    assert resolve_control_mode(platform="switch", key="child_lock") is ControlMode.DEVICE_WRITABLE
    assert resolve_control_mode(platform="switch", key="dnd") is ControlMode.READ_ONLY_CONFIRMED
    assert resolve_control_mode(platform="switch", key="led_period") is ControlMode.READ_ONLY_NOOP


def test_resolve_setting_select_is_direct_scalar():
    assert resolve_control_mode(platform="select", key="navigation_path") is ControlMode.DEVICE_WRITABLE
    assert resolve_control_mode(platform="select", key="lcd_language") is ControlMode.READ_ONLY_PENDING


def test_resolve_unknown_raises():
    import pytest
    with pytest.raises(KeyError):
        resolve_control_mode(platform="number", key="does_not_exist")
```

- [ ] **Step 2: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_control_honesty.py -q`
Expected: FAIL — `ModuleNotFoundError: control_honesty`.

- [ ] **Step 3: Create `control_honesty.py` (enum + modes + CONTROL_MODES + resolver)**

```python
"""Single source of truth for control-honesty: which control entities reach
the g2408 firmware and which are read-only-until-a-write-path-is-found.

Pure Python (NO homeassistant import) so the CI sync test can load it in the
vanilla stubbed-HA venv. The mixin lives here too but only references HA via
duck-typing at call time, never at import.

CONTROL_MODES is keyed by the SAME entity-id templates as entity-inventory.yaml
rows (`<platform>.dreame_a2_mower_<leaf>`), with two generic <key> rows carrying
a per-leaf sub-map. Keep both in sync — tests/inventory/test_control_mode_code_sync
enforces it. See docs/research/control-honesty-audit-2026-06-03.md.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any


class ControlMode(StrEnum):
    DEVICE_WRITABLE = "device_writable"
    DEVICE_WRITE_UNPROVEN = "device_write_unproven"
    INTEGRATION_LOCAL = "integration_local"
    READ_ONLY_PENDING = "read_only_pending"
    READ_ONLY_CONFIRMED = "read_only_confirmed"
    READ_ONLY_NOOP = "read_only_noop"


READ_ONLY_MODES = frozenset({
    ControlMode.READ_ONLY_PENDING,
    ControlMode.READ_ONLY_CONFIRMED,
    ControlMode.READ_ONLY_NOOP,
})

_W = ControlMode.DEVICE_WRITABLE
_U = ControlMode.DEVICE_WRITE_UNPROVEN
_L = ControlMode.INTEGRATION_LOCAL
_P = ControlMode.READ_ONLY_PENDING
_C = ControlMode.READ_ONLY_CONFIRMED
_N = ControlMode.READ_ONLY_NOOP

CONTROL_MODES: dict[str, ControlMode | dict[str, ControlMode]] = {
    # ── number ──
    "number.dreame_a2_mower_human_presence_alert_sensitivity": _N,
    "number.dreame_a2_mower_trail_render_width": _L,
    "number.dreame_a2_mower_station_bearing_deg": _L,
    "number.dreame_a2_mower_map_N_settings_mowing_height": _C,
    "number.dreame_a2_mower_map_N_settings_cutter_position": _C,
    "number.dreame_a2_mower_map_N_settings_cutter_position_height": _C,
    "number.dreame_a2_mower_map_N_settings_edge_mowing_num": _C,
    "number.dreame_a2_mower_map_N_settings_obstacle_avoidance_height": _C,
    "number.dreame_a2_mower_map_N_settings_obstacle_avoidance_distance": _C,
    "number.dreame_a2_mower_map_N_settings_obstacle_avoidance_sensitivity": _C,
    "number.dreame_a2_mower_<key>": {
        "volume": _W,
        "auto_recharge_battery_pct": _C,
        "resume_battery_pct": _C,
    },
    # ── select ──
    "select.dreame_a2_mower_navigation_path": _W,
    "select.dreame_a2_mower_rain_protection_resume_hours": _P,
    "select.dreame_a2_mower_lcd_language": _P,
    "select.dreame_a2_mower_voice_language": _P,
    "select.dreame_a2_mower_work_log": _L,
    "select.dreame_a2_mower_lidar_archive": _L,
    "select.dreame_a2_mower_active_map": _U,
    "select.dreame_a2_mower_action_mode": _L,
    "select.dreame_a2_mower_wifi_archive": _L,
    "select.dreame_a2_mower_map_N_edge_target": _L,
    "select.dreame_a2_mower_map_N_mowing_mode": _L,
    "select.dreame_a2_mower_map_N_settings_mowing_direction": _C,
    "select.dreame_a2_mower_map_N_settings_mowing_direction_mode": _C,
    "select.dreame_a2_mower_map_N_edge_walk_mode": _C,
    "select.dreame_a2_mower_map_N_maintenance_point": _L,
    "select.dreame_a2_mower_map_N_mowing_efficiency": _N,
    "select.dreame_a2_mower_map_N_zone_target": _L,
    "select.dreame_a2_mower_map_N_spot_target": _L,
    # ── switch ──
    "switch.dreame_a2_mower_map_N_edgemaster": _N,
    "switch.dreame_a2_mower_map_N_automatic_edge_mowing": _C,
    "switch.dreame_a2_mower_map_N_safe_edge_mowing": _C,
    "switch.dreame_a2_mower_map_N_obstacle_avoidance_on_edges": _C,
    "switch.dreame_a2_mower_map_N_lidar_obstacle_recognition": _C,
    "switch.dreame_a2_mower_cloud_state_ai_human_enabled": _P,
    "switch.dreame_a2_mower_map_N_ai_recognition_humans": _C,
    "switch.dreame_a2_mower_map_N_ai_recognition_animals": _C,
    "switch.dreame_a2_mower_map_N_ai_recognition_objects": _C,
    "switch.dreame_a2_mower_<key>": {
        "child_lock": _W, "anti_theft_lift_alarm": _W, "anti_theft_offmap_alarm": _W,
        "anti_theft_realtime_location": _W, "frost_protection": _W, "auto_recharge_standby": _W,
        "ai_obstacle_photos": _W, "msg_alert_anomaly": _W, "msg_alert_error": _W,
        "msg_alert_task": _W, "msg_alert_consumables": _W, "voice_regular_notification": _W,
        "voice_work_status": _W, "voice_special_status": _W, "voice_error_status": _W,
        "dnd": _C, "low_speed_at_night": _C, "custom_charging_period": _C,
        "rain_protection": _P,
        "led_period": _N, "led_in_standby": _N, "led_in_working": _N,
        "led_in_charging": _N, "led_in_error": _N, "human_presence_alert": _N,
    },
    # ── time ──
    "time.dreame_a2_mower_<key>": _N,
    # ── lawn_mower / button (dict-only; no entity wiring) ──
    "lawn_mower.dreame_a2_mower": _W,
    "button.dreame_a2_mower_map_N_head_to_point": _W,
    "button.dreame_a2_mower_refresh_cloud_state": _L,
    "button.dreame_a2_mower_refresh_wifi_heatmaps": _L,
    "button.dreame_a2_mower_finalize_session": _L,
    "button.dreame_a2_mower_start_mowing": _W,
    "button.dreame_a2_mower_pause_mowing": _U,
    "button.dreame_a2_mower_stop_mowing": _U,
    "button.dreame_a2_mower_recharge": _U,
    "button.dreame_a2_mower_find_bot": _W,
    "button.dreame_a2_mower_lock_bot": _U,
    "button.dreame_a2_mower_generate_3dmap": _U,
}


def resolve_control_mode(*, platform: str, key: str) -> ControlMode:
    """Resolve an entity's ControlMode from its platform + entity-key leaf.

    `key` is the inventory leaf: descriptor `.key` for parent entities,
    `map_N_<KEY>` for per-map entities. Tries the direct 1:1 id first, then
    falls back to the generic `<key>` sub-map keyed by the same leaf.
    """
    direct = f"{platform}.dreame_a2_mower_{key}"
    val = CONTROL_MODES.get(direct)
    if isinstance(val, ControlMode):
        return val
    generic = CONTROL_MODES.get(f"{platform}.dreame_a2_mower_<key>")
    if isinstance(generic, dict) and key in generic:
        return generic[key]
    raise KeyError(f"no control_mode for {platform}.* key={key!r}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_control_honesty.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/control_honesty.py tests/unit/test_control_honesty.py
git commit -m "feat(control-honesty): ControlMode enum + CONTROL_MODES map + resolver

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: CI sync gate — code CONTROL_MODES == inventory verdict

**Files:**
- Create: `tests/inventory/test_control_mode_code_sync.py`

- [ ] **Step 1: Write the failing test**

```python
"""CONTROL_MODES (code) must equal the control_mode verdicts in the inventory.

Keeps the runtime source (control_honesty.CONTROL_MODES) and the documentation
source (entity-inventory.yaml control_mode / control_mode_by_key) from drifting.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from custom_components.dreame_a2_mower.control_honesty import CONTROL_MODES

INV = Path(__file__).resolve().parents[2] / "custom_components" / "dreame_a2_mower" / "entity-inventory.yaml"
CONTROL_PLATFORMS = {"number", "select", "switch", "time", "lawn_mower", "button"}


def _inventory_modes() -> dict[str, object]:
    data = yaml.safe_load(INV.read_text())
    out: dict[str, object] = {}
    for e in data["entities"]:
        if e.get("platform") not in CONTROL_PLATFORMS:
            continue
        if str(e.get("class", "")).startswith("("):  # tombstone
            continue
        mode = e["control_mode"]
        out[e["id"]] = e["control_mode_by_key"] if mode == "per_key" else mode
    return out


def _code_modes() -> dict[str, object]:
    out: dict[str, object] = {}
    for k, v in CONTROL_MODES.items():
        out[k] = {kk: str(vv) for kk, vv in v.items()} if isinstance(v, dict) else str(v)
    return out


def test_code_and_inventory_control_modes_match():
    code, inv = _code_modes(), _inventory_modes()
    only_code = sorted(set(code) - set(inv))
    only_inv = sorted(set(inv) - set(code))
    mismatched = {k: (code[k], inv[k]) for k in set(code) & set(inv) if code[k] != inv[k]}
    assert not only_code, f"ids in CONTROL_MODES but not inventory: {only_code}"
    assert not only_inv, f"control ids in inventory but not CONTROL_MODES: {only_inv}"
    assert not mismatched, f"control_mode mismatches (code, inventory): {mismatched}"
```

- [ ] **Step 2: Run to verify it fails-or-passes correctly**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_control_mode_code_sync.py -q`
Expected: PASS if Task 1 + Task 2 maps agree. If it FAILS, the diff names the exact divergent ids — fix `CONTROL_MODES` or the inventory row until green (do NOT weaken the test).

- [ ] **Step 3: Commit**

```bash
git add tests/inventory/test_control_mode_code_sync.py
git commit -m "test(inventory): gate CONTROL_MODES == entity-inventory control_mode

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `_ControlHonestyMixin` — padlock, attribute, snap-back

**Files:**
- Modify: `custom_components/dreame_a2_mower/control_honesty.py`
- Test: `tests/unit/test_control_honesty.py`

- [ ] **Step 1: Write failing mixin tests**

Append to `tests/unit/test_control_honesty.py`:

```python
from custom_components.dreame_a2_mower.control_honesty import _ControlHonestyMixin, ControlMode


class _FakeEntity(_ControlHonestyMixin):
    """Minimal stand-in: no HA base, just the mixin + the hooks it reads."""
    def __init__(self, mode):
        self._control_mode = mode
        self.wrote = False
        self.published = 0
        self._attr_icon = "mdi:knob"
    def async_write_ha_state(self):
        self.published += 1


def test_read_only_property():
    assert _FakeEntity(ControlMode.READ_ONLY_CONFIRMED).read_only is True
    assert _FakeEntity(ControlMode.DEVICE_WRITABLE).read_only is False


def test_padlock_icon_only_when_read_only():
    assert _FakeEntity(ControlMode.READ_ONLY_PENDING).icon == "mdi:lock-outline"
    assert _FakeEntity(ControlMode.DEVICE_WRITABLE).icon == "mdi:knob"


def test_extra_state_attributes_marks_read_only():
    a = _FakeEntity(ControlMode.READ_ONLY_NOOP).extra_state_attributes
    assert a == {"control_mode": "read_only_noop", "read_only": True}
    assert _FakeEntity(ControlMode.INTEGRATION_LOCAL).extra_state_attributes == {
        "control_mode": "integration_local", "read_only": False,
    }


async def test_reject_readonly_write_republishes_and_does_not_write():
    e = _FakeEntity(ControlMode.READ_ONLY_CONFIRMED)
    await e._reject_readonly_write()
    assert e.published == 1 and e.wrote is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_control_honesty.py -q`
Expected: FAIL — `_ControlHonestyMixin` not defined / no `read_only`.

- [ ] **Step 3: Add the mixin to `control_honesty.py`**

Append:

```python
import logging

_LOGGER = logging.getLogger(__name__)
_PADLOCK_ICON = "mdi:lock-outline"


class _ControlHonestyMixin:
    """Adds the honesty verdict to a control entity.

    Subclasses MUST set ``self._control_mode`` (a ControlMode) in __init__,
    typically via ``resolve_control_mode(...)``. When the mode is read-only the
    mixin shows a padlock, marks the entity via extra-state-attributes, and the
    write handler is expected to call ``_reject_readonly_write`` instead of
    writing. Operable modes are pass-through.
    """

    _control_mode: ControlMode = ControlMode.INTEGRATION_LOCAL

    @property
    def control_mode(self) -> ControlMode:
        return self._control_mode

    @property
    def read_only(self) -> bool:
        return self._control_mode in READ_ONLY_MODES

    @property
    def icon(self) -> str | None:
        if self.read_only:
            return _PADLOCK_ICON
        # Defer to whatever the entity/description would otherwise use.
        attr = getattr(self, "_attr_icon", None)
        if attr is not None:
            return attr
        desc = getattr(self, "entity_description", None)
        return getattr(desc, "icon", None) if desc is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        base: dict[str, Any] = {}
        parent = super()
        parent_attrs = getattr(parent, "extra_state_attributes", None)
        if isinstance(parent_attrs, dict):
            base.update(parent_attrs)
        base["control_mode"] = str(self._control_mode)
        base["read_only"] = self.read_only
        return base

    async def _reject_readonly_write(self) -> None:
        _LOGGER.info(
            "%s: write ignored — no device write path yet (control_mode=%s)",
            getattr(self, "entity_id", type(self).__name__), self._control_mode,
        )
        self.async_write_ha_state()  # re-publish unchanged state → UI snaps back
```

- [ ] **Step 4: Run to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_control_honesty.py -q`
Expected: PASS (all unit tests). If the async test needs `pytest.mark.asyncio`, add `import pytest` and the marker — check the repo's pytest asyncio mode in `pyproject.toml`/`pytest.ini` and match it.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/control_honesty.py tests/unit/test_control_honesty.py
git commit -m "feat(control-honesty): _ControlHonestyMixin (padlock + attr + snap-back)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire the switch platform

**Files:**
- Modify: `custom_components/dreame_a2_mower/_switch_base.py`
- Test: `tests/integration/test_control_honesty_switch.py` (create)

`DreameA2Switch` (descriptor-driven, key = `description.key`) and `_AiRecognitionBitSwitch` (per-map, hand-coded subclasses) both need the mixin + a guard. The 3 AI bit-switch subclasses (`DreameA2AiRecognitionHumansSwitch`/`Animals`/`Objects`) live in `switch_global.py` and pass `map_id`; their inventory leaf is `map_N_ai_recognition_<x>`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_control_honesty_switch.py`. Use the repo's existing switch-test fixtures (copy the coordinator/stub setup from `tests/integration/test_switch*.py`). Assert:

```python
# A read-only CFG switch (DND) snaps back and never calls write_setting.
async def test_readonly_cfg_switch_snaps_back(make_switch):
    sw = make_switch(key="dnd")           # helper builds DreameA2Switch w/ DND descriptor
    sw.coordinator.write_setting = _spy()
    await sw.async_turn_on()
    assert sw.coordinator.write_setting.called is False
    assert sw.read_only is True and sw.icon == "mdi:lock-outline"

# A writable CFG switch (CLS) still writes.
async def test_writable_cfg_switch_writes(make_switch):
    sw = make_switch(key="child_lock")
    sw.coordinator.write_setting = _spy(return_value=True)
    await sw.async_turn_on()
    assert sw.coordinator.write_setting.called is True
    assert sw.read_only is False
```

(Adapt `make_switch`/`_spy` to the repo's existing switch test helpers — grep `tests/integration/test_switch` for the fixture names.)

- [ ] **Step 2: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_control_honesty_switch.py -q`
Expected: FAIL — `read_only` AttributeError / write_setting still called.

- [ ] **Step 3: Wire `DreameA2Switch`**

In `_switch_base.py`: add the mixin to the imports and bases, set the mode in `__init__`, and guard `_async_set_value`.

```python
from .control_honesty import _ControlHonestyMixin, resolve_control_mode
```

Change the class header (line 55):

```python
class DreameA2Switch(
    _ControlHonestyMixin, CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
```

In `__init__` (after line 75 `self._attr_device_info = ...`):

```python
        self._control_mode = resolve_control_mode(platform="switch", key=description.key)
```

At the TOP of `_async_set_value` (before line 108 `desc = ...`):

```python
        if self.read_only:
            return await self._reject_readonly_write()
```

- [ ] **Step 4: Wire `_AiRecognitionBitSwitch`**

Class header (line 152):

```python
class _AiRecognitionBitSwitch(
    _ControlHonestyMixin, CoordinatorEntity[DreameA2MowerCoordinator], SwitchEntity
):
```

It has no `entity_description`; it needs a per-subclass leaf. Add a class attr `_HONESTY_LEAF: str = ""` and set `self._control_mode` in `__init__` (after line 172):

```python
        self._control_mode = resolve_control_mode(
            platform="switch", key=f"map_N_{self._HONESTY_LEAF}",
        )
```

Then in `switch_global.py`, set `_HONESTY_LEAF = "ai_recognition_humans"` (resp. `_animals`, `_objects`) on the three subclasses.

Guard the TOP of `_toggle` (before line 192 `coord = ...`):

```python
        if self.read_only:
            return await self._reject_readonly_write()
```

- [ ] **Step 5: Run to verify it passes + no regressions**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_control_honesty_switch.py tests/integration/test_switch*.py -q`
Expected: PASS. (The pre-existing `available` property still returns False until first read — unchanged.)

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/_switch_base.py custom_components/dreame_a2_mower/switch_global.py tests/integration/test_control_honesty_switch.py
git commit -m "feat(switch): control-honesty padlock + snap-back

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Wire the number platform

**Files:**
- Modify: `custom_components/dreame_a2_mower/number.py`
- Test: `tests/integration/test_control_honesty_number.py` (create)

Three write paths: `DreameA2Number` (descriptor, key = `description.key`), `_PerMapSettingsNumberBase` (per-map, leaf = `map_N_<self._KEY>`), and the two integration-local numbers (`DreameA2StationBearingNumber`, `DreameA2TrailRenderWidthNumber`) which are NOT read-only (no guard needed, but they still mix in for the attribute + sync).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_control_honesty_number.py` (reuse `tests/integration/test_number*.py` fixtures):

```python
async def test_per_map_setting_snaps_back(make_per_map_mowing_height):
    n = make_per_map_mowing_height(map_id=0)
    n.coordinator.write_settings = _spy()
    await n.async_set_native_value(5)
    assert n.coordinator.write_settings.called is False   # _settings_optimistic_write never reached
    assert n.read_only is True and n.icon == "mdi:lock-outline"

async def test_volume_number_still_writes(make_volume_number):
    n = make_volume_number()
    n.coordinator.write_setting = _spy(return_value=True)
    await n.async_set_native_value(50)
    assert n.coordinator.write_setting.called is True
    assert n.read_only is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_control_honesty_number.py -q`
Expected: FAIL.

- [ ] **Step 3: Wire `DreameA2Number`**

`number.py`: import `from .control_honesty import _ControlHonestyMixin, resolve_control_mode`.
Add mixin to `DreameA2Number` bases (line 250). In `__init__` after line 269:

```python
        self._control_mode = resolve_control_mode(platform="number", key=description.key)
```

Guard TOP of `async_set_native_value` (before line 279 `if desc.cfg_key is None`):

```python
        if self.read_only:
            return await self._reject_readonly_write()
```

- [ ] **Step 4: Wire `_PerMapSettingsNumberBase`**

Add mixin to its bases (line 324). In `__init__` after line 352:

```python
        self._control_mode = resolve_control_mode(
            platform="number", key=f"map_N_{self._KEY}",
        )
```

Guard TOP of its `async_set_native_value` (before line 381 `await _settings_optimistic_write(`):

```python
        if self.read_only:
            return await self._reject_readonly_write()
```

- [ ] **Step 5: Wire the two integration-local numbers (mixin only, no guard)**

Add `_ControlHonestyMixin` to the bases of `DreameA2StationBearingNumber` (line 491) and `DreameA2TrailRenderWidthNumber` (line 581). Set in each `__init__` (after the `_attr_unique_id` line):

```python
        self._control_mode = resolve_control_mode(platform="number", key="station_bearing_deg")
```
```python
        self._control_mode = resolve_control_mode(platform="number", key="trail_render_width")
```

(No write guard — they are `integration_local`, `read_only` is False, behaviour unchanged.)

- [ ] **Step 6: Run to verify it passes + no regressions**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_control_honesty_number.py tests/integration/test_number*.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/number.py tests/integration/test_control_honesty_number.py
git commit -m "feat(number): control-honesty padlock + snap-back

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Wire the select platform

**Files:**
- Modify: `custom_components/dreame_a2_mower/_select_base.py`, `select_global.py`, `select_map_settings.py`
- Test: `tests/integration/test_control_honesty_select.py` (create)

Selects span: `DreameA2SettingSelect` (descriptor, key = `.key`; PROT writable, WRP/LANG pending), per-map settings selects (`map_N_settings_mowing_direction*`, `map_N_edge_walk_mode` → read-only), `map_N_mowing_efficiency` (read-only), and many `integration_local` selects (targets, archives, action_mode, active_map=unproven). Identify each select class's leaf and add the mixin at the shared bases; only the read-only ones need the guard.

- [ ] **Step 1: Map the select classes to leaves**

Run: `grep -nE 'class .*Select|_attr_unique_id|map_unique_id|mower_unique_id|description.key|async_select_option|unique_suffix|self\._KEY' custom_components/dreame_a2_mower/_select_base.py custom_components/dreame_a2_mower/select_global.py custom_components/dreame_a2_mower/select_map_settings.py`
Record, per class: platform=`select`, and its leaf (descriptor `.key` for `DreameA2SettingSelect`; `map_N_<suffix>` for per-map; the fixed key for singletons like `action_mode`, `active_map`, `work_log`, `lidar_archive`, `wifi_archive`).

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_control_honesty_select.py` (reuse `tests/integration/test_select*.py` fixtures):

```python
async def test_readonly_setting_select_snaps_back(make_mowing_direction_select):
    s = make_mowing_direction_select(map_id=0)
    s.coordinator.write_settings = _spy()
    await s.async_select_option(s.options[0])
    assert s.coordinator.write_settings.called is False
    assert s.read_only is True and s.icon == "mdi:lock-outline"

async def test_navigation_path_select_still_writes(make_navigation_path_select):
    s = make_navigation_path_select()
    s.coordinator.write_setting = _spy(return_value=True)
    await s.async_select_option("Smart Path")
    assert s.coordinator.write_setting.called is True
    assert s.read_only is False

async def test_integration_local_select_unaffected(make_action_mode_select):
    s = make_action_mode_select()
    assert s.read_only is False and s.extra_state_attributes["control_mode"] == "integration_local"
```

- [ ] **Step 3: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_control_honesty_select.py -q`
Expected: FAIL.

- [ ] **Step 4: Wire the select bases + classes**

Add `from .control_honesty import _ControlHonestyMixin, resolve_control_mode` to each file. For every concrete select class:
- add `_ControlHonestyMixin` as the FIRST base,
- set `self._control_mode = resolve_control_mode(platform="select", key=<leaf>)` in `__init__` after the `_attr_unique_id` assignment,
- guard the TOP of `async_select_option` with `if self.read_only: return await self._reject_readonly_write()`.

Where classes share a base (`_DreameA2DynamicTargetSelect`, the per-map settings select base, `DreameA2SettingSelect`), do it once on the base; the leaf is derived from the per-instance key already passed to `*_unique_id`. Concretely, the base must capture its leaf into an attribute at `__init__` time (the value passed as the `key`/`unique_suffix` argument) and call `resolve_control_mode(platform="select", key=<that leaf, with map_N normalization>)`.

- [ ] **Step 5: Run to verify it passes + no regressions**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_control_honesty_select.py tests/integration/test_select*.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/_select_base.py custom_components/dreame_a2_mower/select_global.py custom_components/dreame_a2_mower/select_map_settings.py tests/integration/test_control_honesty_select.py
git commit -m "feat(select): control-honesty padlock + snap-back

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Wire the time platform

**Files:**
- Modify: `custom_components/dreame_a2_mower/time.py`
- Test: add a case to `tests/unit/test_control_honesty.py` or `tests/integration/test_control_honesty_time.py`

`DreameA2Time` is already read-only; it just needs the padlock + attribute. Its inventory row is the generic `time.dreame_a2_mower_<key>` (scalar `read_only_noop`), so `resolve_control_mode(platform="time", key=<descriptor.key>)` must hit the generic fallback — but the generic value here is a SCALAR, not a dict. Update the resolver fallback to also return a scalar generic value.

- [ ] **Step 1: Extend the resolver test (failing)**

Add to `tests/unit/test_control_honesty.py`:

```python
def test_resolve_generic_scalar_time():
    assert resolve_control_mode(platform="time", key="anything") is ControlMode.READ_ONLY_NOOP
```

- [ ] **Step 2: Run to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_control_honesty.py::test_resolve_generic_scalar_time -q`
Expected: FAIL (KeyError — generic scalar not handled).

- [ ] **Step 3: Handle a scalar generic in the resolver**

In `resolve_control_mode`, after the dict-generic branch, add:

```python
    if isinstance(generic, ControlMode):
        return generic
```

- [ ] **Step 4: Wire `DreameA2Time`**

Find the class header + `__init__` (`grep -n 'class DreameA2Time\|_attr_unique_id\|description.key' time.py`). Add `_ControlHonestyMixin` as the first base and set `self._control_mode = resolve_control_mode(platform="time", key=description.key)` in `__init__`. No write guard (already read-only).

- [ ] **Step 5: Run to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_control_honesty.py tests/integration/test_time*.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/control_honesty.py custom_components/dreame_a2_mower/time.py tests/unit/test_control_honesty.py
git commit -m "feat(time): control-honesty padlock + scalar generic resolver

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Dashboard header note

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`

- [ ] **Step 1: Add the legend to the Settings & Zones tab header**

Find the `_tab_header_settings_zones` anchor (around line 64) and append to its markdown content a line:

```
🔒 = control is present but the device write path isn't unlocked yet (changes snap back).
```

- [ ] **Step 2: Validate the YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "docs(dashboard): padlock legend on Settings & Zones header

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(Deploy via the SCP procedure in `reference_ha_dashboard_deploy` when ready — out of scope for this plan.)

---

## Task 10: Full-suite verification + finish

**Files:** none (verification)

- [ ] **Step 1: Run the entire suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: all pass (baseline was 1878 passed / 4 skipped after part (a); this plan adds tests, so the passed count grows, skipped stays 4).

- [ ] **Step 2: Run the inventory gates explicitly**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/ -q`
Expected: PASS — both `test_control_mode_gate` (presence) and `test_control_mode_code_sync` (code↔inventory) green.

- [ ] **Step 3: Manual spot-check a read-only + a writable entity (optional, if a live HA is available)**

Deploy, then confirm: `number.<map>_settings_mowing_height` shows a padlock and snaps back; `switch.<...>_child_lock` toggles normally. Otherwise rely on the integration tests.

- [ ] **Step 4: Push**

```bash
git push origin main
```

- [ ] **Step 5: Update the TODO**

In `docs/TODO.md` "Make controllable entities honest", mark done-when #2 (representation) DONE, leaving #3 (mark provisional `device_write_unproven` controls) and the WRP/LANG/AI_HUMAN re-probe as the remaining open items. Commit + push.

---

## Self-Review

**Spec coverage:**
- §1 code-side SoT → Task 2 (`control_honesty.py` + `CONTROL_MODES`). ✓
- §2 mixin (padlock + attr + snap-back) → Task 4. ✓
- §3 per-platform guards (uniform snap-back incl. pending) → Tasks 5–8. ✓
- §4 CI sync gate → Task 3. ✓
- §5 flip workflow → enabled by Tasks 2–8 (change one `CONTROL_MODES` line + inventory row; Task 3 enforces both move). ✓
- §6 dashboard note → Task 9. ✓
- §7 testing (TDD, mixin + per-platform + full suite) → Tasks 2–8, 10. ✓
- Re-key prerequisite (code resolves by entity-key leaf, not CFG key) → Task 1. ✓

**Type/name consistency:** `ControlMode`, `READ_ONLY_MODES`, `CONTROL_MODES`, `resolve_control_mode(platform=, key=)`, `_ControlHonestyMixin`, `read_only`, `control_mode`, `_reject_readonly_write`, `_control_mode`, `_HONESTY_LEAF` used consistently across tasks. Resolver returns scalar OR generic-scalar OR generic-dict-by-leaf (Tasks 2 + 8).

**Non-goals honored:** no WRP/LANG/AI_HUMAN probe (they ride `read_only_pending`); sensors untouched; `device_write_unproven` renders normally; buttons/lawn_mower are dict-only (no entity wiring) — their snap-back is N/A since none are read-only.

**Open risk flagged for the implementer:** Tasks 5–8 reference existing test fixtures (`make_switch`, `_spy`, etc.) generically — grep the real fixture names in `tests/integration/test_{switch,number,select}*.py` and adapt. The per-map leaf normalization (`map_N_<KEY>` / `map_N_<suffix>`) must match the inventory ids exactly; the Task 3 sync test + the resolver `KeyError` will catch any leaf that doesn't map.
