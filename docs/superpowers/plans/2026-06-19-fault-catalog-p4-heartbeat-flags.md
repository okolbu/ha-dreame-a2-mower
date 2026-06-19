# Heartbeat (s1p1) flag enrichment (P4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the five code-mapped s1p1 flag binary_sensors with the catalog's localized text/tier/detail attributes; document the 45 numeric heartbeat codes as a non-firing artifact; ensure entity-inventory coverage.

**Architecture:** Add an `extra_state_attributes_fn` field to `DreameA2BinarySensorEntityDescription` (mirroring the sensor platform from P1) + an `extra_state_attributes` property on the entity. A module helper `_flag_fault_attrs(coord, code)` returns localized `fault_text`/`tier`/`fault_detail`/`fault_code` from `fault_catalog` (iot channel). A `_S1P1_FLAG_FAULT_CODE` map wires each flag sensor to its catalog code.

**Tech Stack:** Python, HA custom integration, pytest. Test runner (from repo root): `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-19-fault-catalog-p4-heartbeat-flags-design.md`

**Verified facts:**
- `binary_sensor.py`: descriptor `DreameA2BinarySensorEntityDescription` (lines 31-43) has `value_fn` + `availability_source`, **no `extra_state_attributes_fn`**. Entity `DreameA2BinarySensor` (lines 328-353) has `is_on`, **no `extra_state_attributes`**.
- The five target descriptions read `coord.data.<flag>`: `drop_tilt` (142-149), `bumper` (150-157), `lift` (158-165), `emergency_stop` (166-173), `battery_temp_low` (115-123).
- `safety_alert_active` (174-189) has no catalog code → NOT enriched.
- `fault_catalog` exposes `fault_text(code, lang)`, `fault_tier(code)`, `fault_detail(code, lang)`, `resolve_lang(ha_lang)`.
- Flag→code: bumper 9 (error), drop_tilt 1 (error), lift 0 (error), emergency_stop 23 (error), battery_temp_low 43 (alert).

---

### Task 1: Attribute plumbing + flag enrichment

**Files:**
- Modify: `custom_components/dreame_a2_mower/binary_sensor.py`
- Test: `tests/` (new `tests/test_binary_sensor_flag_attrs.py` or append to an existing binary_sensor test module — grep `tests/ -l "binary_sensor"` and prefer an existing module)

- [ ] **Step 1: Write failing tests.** Create `tests/test_binary_sensor_flag_attrs.py`:
```python
import types

from custom_components.dreame_a2_mower import binary_sensor as bs
from custom_components.dreame_a2_mower.mower import fault_catalog as fc


def _coord(lang="en"):
    return types.SimpleNamespace(
        hass=types.SimpleNamespace(config=types.SimpleNamespace(language=lang)),
    )


def test_flag_fault_code_map():
    assert bs._S1P1_FLAG_FAULT_CODE == {
        "bumper": 9, "drop_tilt": 1, "lift": 0,
        "emergency_stop": 23, "battery_temp_low": 43,
    }
    # tiers match the spec
    assert fc.fault_tier(9) == "error"
    assert fc.fault_tier(43) == "alert"


def test_flag_fault_attrs_localized_and_complete():
    a = bs._flag_fault_attrs(_coord("en"), 9)
    assert a["fault_code"] == 9
    assert a["tier"] == "error"
    assert a["fault_text"] == fc.fault_text(9, "en")
    assert a["fault_detail"] == fc.fault_detail(9, "en")
    # localization: nb differs from en for code 9
    anb = bs._flag_fault_attrs(_coord("nb"), 9)
    assert anb["fault_text"] == fc.fault_text(9, "nb")
    assert fc.fault_text(9, "nb") != fc.fault_text(9, "en")


def test_enriched_descriptions_expose_attrs_and_safety_alert_does_not():
    by_key = {d.key: d for d in bs.BINARY_SENSORS}
    for key, code in bs._S1P1_FLAG_FAULT_CODE.items():
        d = by_key[key]
        assert d.extra_state_attributes_fn is not None, f"{key} missing attrs fn"
        attrs = d.extra_state_attributes_fn(_coord("en"))
        assert attrs["fault_code"] == code
        assert attrs["tier"] == fc.fault_tier(code)
    # safety_alert_active has no catalog code → no attrs fn
    assert by_key["safety_alert_active"].extra_state_attributes_fn is None


def test_entity_extra_state_attributes_property():
    by_key = {d.key: d for d in bs.BINARY_SENSORS}
    desc = by_key["bumper"]
    ent = bs.DreameA2BinarySensor.__new__(bs.DreameA2BinarySensor)
    ent.entity_description = desc
    ent._dreame_test_coord = _coord("en")
    # CoordinatorEntity exposes self.coordinator; stub it for the property.
    object.__setattr__(ent, "coordinator", _coord("en"))
    attrs = ent.extra_state_attributes
    assert attrs["fault_code"] == 9 and attrs["tier"] == "error"
    # a non-enriched sensor returns None
    desc2 = by_key["safety_alert_active"]
    ent2 = bs.DreameA2BinarySensor.__new__(bs.DreameA2BinarySensor)
    ent2.entity_description = desc2
    object.__setattr__(ent2, "coordinator", _coord("en"))
    assert ent2.extra_state_attributes is None
```
> If `coordinator` can't be set via `object.__setattr__` (CoordinatorEntity may define it as a slot/property), instead test the property by constructing through the normal `__init__` with a fuller coordinator stub, OR drop `test_entity_extra_state_attributes_property` to a direct call of the description's fn (the first three tests already cover the logic). Use your judgment; keep at least the fn-level + map + safety-alert assertions.

- [ ] **Step 2: Run, verify fail.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/test_binary_sensor_flag_attrs.py -q`
Expected: FAIL (`_S1P1_FLAG_FAULT_CODE` / `_flag_fault_attrs` / `extra_state_attributes_fn` not defined).

- [ ] **Step 3: Add the descriptor field.** In `binary_sensor.py`, extend the imports and descriptor. Add `Any` to the typing import (top of file): change `from collections.abc import Callable` area — add `from typing import Any`. Then in `DreameA2BinarySensorEntityDescription` (after `availability_source`):
```python
    #: optional per-row attribute provider — receives the coordinator, returns a
    #: dict of extra_state_attributes (None-valued keys are dropped). Used by the
    #: s1p1 flag sensors to carry catalog fault_text/tier/detail (P4).
    extra_state_attributes_fn: Callable[
        [DreameA2MowerCoordinator], dict[str, Any]
    ] | None = None
```

- [ ] **Step 4: Add the map + helper.** In `binary_sensor.py`, after the imports and before `BINARY_SENSORS` (e.g. after `_cloud_connected_value`):
```python
# s1p1 heartbeat flags that map to a catalog fault concept. The catalog's
# `heartbeat` channel is a non-firing artifact (a subset of the iot fault_names;
# s1p1 carries boolean flags, not numeric codes), so we read the iot channel for
# text/tier. safety_alert_active has no catalog code and is intentionally absent.
_S1P1_FLAG_FAULT_CODE: dict[str, int] = {
    "bumper": 9,            # FAULT_CRASH_PLATE  (sole signal — not mirrored to s2p2)
    "drop_tilt": 1,         # FAULT_TILTED
    "lift": 0,              # FAULT_HANGING
    "emergency_stop": 23,   # FAULT_EMERGENCY_STOP (also has the P3b PIN notice)
    "battery_temp_low": 43, # ALERT_BATTERY_TEMP_LOW (charging-paused condition)
}


def _flag_fault_attrs(coord: DreameA2MowerCoordinator, code: int) -> dict[str, Any]:
    """Localized catalog context for an s1p1 flag's mapped iot fault code:
    fault_text + tier + fault_detail + fault_code. Lang resolved from the HA
    config (defaults to English when unavailable, e.g. test stubs)."""
    from .mower import fault_catalog
    cfg = getattr(getattr(coord, "hass", None), "config", None)
    lang = fault_catalog.resolve_lang(getattr(cfg, "language", None))
    return {
        "fault_text": fault_catalog.fault_text(code, lang),
        "tier": fault_catalog.fault_tier(code),
        "fault_detail": fault_catalog.fault_detail(code, lang),
        "fault_code": code,
    }
```

- [ ] **Step 5: Wire the five descriptions.** Add `extra_state_attributes_fn` to each of the five target descriptions (use the map as single source). For `bumper` (lines 150-157):
```python
    DreameA2BinarySensorEntityDescription(
        key="bumper",
        translation_key="bumper",
        name="Bumper error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        availability_source="mqtt",
        value_fn=lambda coord: bool(coord.data.bumper),
        extra_state_attributes_fn=lambda coord: _flag_fault_attrs(
            coord, _S1P1_FLAG_FAULT_CODE["bumper"]
        ),
    ),
```
Do the same for `drop_tilt` (`_S1P1_FLAG_FAULT_CODE["drop_tilt"]`), `lift` (`["lift"]`), `emergency_stop` (`["emergency_stop"]`), `battery_temp_low` (`["battery_temp_low"]`). Leave `safety_alert_active` and all other descriptions unchanged.

- [ ] **Step 6: Add the entity property.** In `DreameA2BinarySensor` (after `is_on`, ~line 353):
```python
    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.extra_state_attributes_fn
        if fn is None:
            return None
        attrs = {k: v for k, v in fn(self.coordinator).items() if v is not None}
        return attrs or None
```

- [ ] **Step 7: Run tests, verify pass.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/test_binary_sensor_flag_attrs.py -q`
Expected: PASS. If `test_flag_fault_attrs_localized_and_complete` fails because code 9's nb==en, pick another enriched error code where they differ (e.g. 0 or 1) and update both assertions.

- [ ] **Step 8: Broader check.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "binary_sensor" -q`
Expected: PASS (no existing binary_sensor test broke).

- [ ] **Step 9: Commit** (stage by explicit path; never `-A`; do NOT stage `tools/probes/*`):
```bash
git add custom_components/dreame_a2_mower/binary_sensor.py tests/test_binary_sensor_flag_attrs.py
git commit -m "feat(p4): s1p1 flag sensors carry catalog fault_text/tier/detail attrs"
```

---

### Task 2: Documentation, entity-inventory, full suite, release

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify: `docs/research/knowledge-gaps.md`
- Regenerate: `docs/research/inventory/generated/g2408-canonical.md`

- [ ] **Step 1: Inventory s1p1 note.** In `inventory.yaml § s1p1` (the heartbeat blob property), add a 2026-06-19 `verified` note: the catalog `heartbeat` channel (45 codes) is a **non-firing app artifact** — a subset of the iot fault_names that never appears as numeric codes on g2408 s1p1 (which carries a 20-byte boolean-flag blob; 93,888 corpus samples, zero numeric codes). The real s1p1 faults are the decoded flags (bumper/drop_tilt/lift/emergency_stop/battery_temp_low); their catalog-quality `fault_text`/`tier`/`fault_detail` is now surfaced as binary_sensor attributes via the flag→iot-code map (`bumper`→9, `drop_tilt`→1, `lift`→0, `emergency_stop`→23, `battery_temp_low`→43). `safety_alert_active` has no catalog code. Source `[apk:g2408-plugin-ext1423]`. Match the existing YAML shape.

- [ ] **Step 2: knowledge-gaps disposition.** In `docs/research/knowledge-gaps.md`, record (or update) the heartbeat-channel entry as CLOSED: the heartbeat catalog channel is a non-firing artifact (not a gap to chase); s1p1 = boolean flags, enriched with catalog text/tier via iot codes in P4.

- [ ] **Step 3: entity-inventory coverage.** Run the inventory validation to see what the touch-gate requires:
```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
```
Then ensure `entity-inventory.yaml` has rows for the six s1p1 binary_sensors (`bumper`, `drop_tilt`, `lift`, `emergency_stop`, `battery_temp_low`, `safety_alert_active`) and records the new `fault_text`/`tier`/`fault_detail`/`fault_code` attributes on the five enriched ones. Add any missing rows in the file's existing schema (copy the shape of a sibling binary_sensor entry). Re-run `--validate-only` until clean.

- [ ] **Step 4: state_machine_audit.** Run the audit test:
```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "audit" -q
```
If it goes red (the recurring gotcha — attribute-surfaced fields may need rows in `tools/state_machine/state_machine_audit_expectations.yaml` and `_KNOWN_ATTRIBUTE_SURFACED_FIELDS`), add the required rows. The five flags are EXISTING MowerState fields already surfaced by these binary_sensors, so the audit likely needs NO change — but verify against a clean run, don't assume. If red, fix per the expectations file.

- [ ] **Step 5: Regenerate canonical + full suite.**
```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q
```
Expected: all pass (baseline 2612 passed / 5 skipped + the new P4 tests). Inspect the canonical diff; exclude unrelated churn.

- [ ] **Step 6: Commit.**
```bash
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml docs/research/knowledge-gaps.md docs/research/inventory/generated/g2408-canonical.md
# + tools/state_machine/state_machine_audit_expectations.yaml IF you changed it
git commit -m "docs(p4): heartbeat-channel non-firing note + entity-inventory for s1p1 flags"
```

- [ ] **Step 7: Release + live-verify (controller).** The controller merges the P4 branch to main, pushes (reconciling origin if advanced), runs `tools/release/release.sh 1.0.30a4`, installs via HACS + restarts HA, and verifies: integration loads clean; `binary_sensor.dreame_a2_mower_bumper` (and the other four) carry `fault_text`/`tier`/`fault_detail`/`fault_code` attributes with the localized catalog text; no numeric heartbeat codes surfaced.

---

## Self-Review notes
- **Spec coverage:** A (plumbing+helper+wiring) → T1; B (non-firing doc) → T2 S1-2; C (entity-inventory) → T2 S3-4. Testing → T1 S1.
- **Plumbing is additive:** new optional descriptor field (default None) + new entity property → no existing binary_sensor behavior changes; non-enriched sensors return None attrs.
- **Type consistency:** `extra_state_attributes_fn: Callable[[coord], dict[str,Any]] | None`; `_S1P1_FLAG_FAULT_CODE: dict[str,int]`; `_flag_fault_attrs(coord, code:int) -> dict[str,Any]`.
- **No state-machine change**; flags are existing MowerState fields. Audit verified, not assumed.
- **Localization** mirrors P1 (resolve_lang from hass.config.language; English fallback for stubs).
