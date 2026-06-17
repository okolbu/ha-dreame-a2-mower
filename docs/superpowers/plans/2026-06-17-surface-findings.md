# Surface the 2026-06-13→17 findings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface six 2026-06-13→17 protocol findings in the integration and dashboard: fix the create-shape type table, add a per-zone progress sensor, an `s2p57` self-shutdown lifecycle event, a Turning Method per-map select, an Update Station Location button, and correct the `s2p2=72` text/slug.

**Architecture:** Each item is independent. Pure protocol/mapping changes (`map_edit_shapes.py`, `error_codes.py`, `property_mapping.py`) are layer-2 and unit-tested in isolation. Entity items follow existing patterns: per-map selects mirror `DreameA2PerMapMowingDirectionModeSelect` (PRE write via `pre_settings_optimistic_write`); action buttons mirror `DreameA2CancelDockReturnButton` (`MowerAction` + `ACTION_TABLE` `routed_o`); lifecycle events mirror `_fire_rain_delay_started_if_edge`. Name joins for zones use `MowingZone.name` (decoded wire name) at the sensor layer.

**Tech Stack:** Python 3.13, Home Assistant custom component, pytest. Test venv: `/data/claude/homeassistant/.venv-vanilla` (baseline 1591 passed/4 skipped). Run tests with `.venv-vanilla/bin/pytest`.

**Cross-cutting CI gates** (every new entity/event trips these — each item below includes the chore):
- `tools/state_machine/state_machine_audit_expectations.yaml` — rows for new sensors/selects/buttons (idle + reboot yellows); audit test `tests/.../test_audit_exit_zero_when_no_reds`.
- `entity-inventory.yaml` — CI-gated entity SoT (`inventory-touch-gate`); new entities need entries (`presumed`).
- `inventory.yaml` — wire facts + `verifications:` (fact-discipline rule); regen canonical doc.
- control-honesty — `CONTROL_MODES` + inventory row for writable select/button; `test_control_entities_wired`.
- wire-census — `tools/wire_census.py` accounting for new wire values.

**Pre-flight:**

- [ ] **Confirm baseline green.** Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && /data/claude/homeassistant/.venv-vanilla/bin/pytest -q` — Expected: ~1591 passed, 4 skipped. If red, stop and report.
- [ ] **Branch.** Run: `git checkout -b feat/surface-2026-06-17-findings`

---

## Item 1 — Fix create-shape type table

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/map_edit_shapes.py:11-21`
- Test: `tests/protocol/test_map_edit_shapes.py`

- [ ] **Step 1: Write failing tests for the corrected map.**

Add to `tests/protocol/test_map_edit_shapes.py`:

```python
import pytest
from custom_components.dreame_a2_mower.protocol.map_edit_shapes import mow_shape_type


@pytest.mark.parametrize("name,expected", [
    ("square", 9), ("circle", 11), ("heart", 13), ("triangle", 14),
    ("teardrop", 15), ("mushroom", 16), ("cloud", 17), ("rainbow", 18),
    ("moon", 19), ("star", 20), ("butterfly", 21), ("blob", 22),
    ("tree", 23), ("carrot", 24),
])
def test_mow_shape_type_wire_confirmed(name, expected):
    assert mow_shape_type(name) == expected


def test_mow_shape_type_rejects_unused_and_unknown():
    # 10 and 12 are firmware-unused; there is no name that maps to them.
    assert 10 not in __import__(
        "custom_components.dreame_a2_mower.protocol.map_edit_shapes",
        fromlist=["MOW_SHAPE_TYPE"]).MOW_SHAPE_TYPE.values()
    assert 12 not in __import__(
        "custom_components.dreame_a2_mower.protocol.map_edit_shapes",
        fromlist=["MOW_SHAPE_TYPE"]).MOW_SHAPE_TYPE.values()
    with pytest.raises(ValueError):
        mow_shape_type("pentagon")
```

- [ ] **Step 2: Run to verify failure.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/protocol/test_map_edit_shapes.py -q`
Expected: FAIL — `circle` returns 12, `moon`/`star`/etc. raise `ValueError`.

- [ ] **Step 3: Correct the map.**

Replace `map_edit_shapes.py:11-21` with:

```python
NOGO_TYPE = {"line": 1, "polygon": 2, "circle": 3}
# Mow-shape (decorative "novelty") type ids — FULL set wire-confirmed
# 2026-06-17 by drawing each in app 2.5.8.1 and reading the o:215 `type`
# [app-mitm:2026-06-17]. 10 and 12 are firmware-UNUSED (the picker skips
# them); Circle is 11 (parametric centre+radius), NOT 12.
# inventory.yaml § s2p50 o=215.
MOW_SHAPE_TYPE = {
    "square": 9, "circle": 11, "heart": 13, "triangle": 14,
    "teardrop": 15, "mushroom": 16, "cloud": 17, "rainbow": 18,
    "moon": 19, "star": 20, "butterfly": 21, "blob": 22,
    "tree": 23, "carrot": 24,
}
```

- [ ] **Step 4: Run to verify pass.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/protocol/test_map_edit_shapes.py -q`
Expected: PASS.

- [ ] **Step 5: Update the create-shape service options.**

Find the service that calls `mow_shape_type` (grep: `grep -rn "mow_shape_type\|create_mow_shape\|create_shape" custom_components/dreame_a2_mower/`). In the service schema / `services.yaml` selector that lists shape names, replace the 8-name list with the 14-name list (`square, circle, heart, triangle, teardrop, mushroom, cloud, rainbow, moon, star, butterfly, blob, tree, carrot`). If `entity-inventory.yaml` documents the shape names for this service, update them there too.

- [ ] **Step 6: Verify no other test references the old `circle:12`.**

Run: `grep -rn "\"circle\": 12\|circle.*12\|12.*circle" tests/ custom_components/` — Expected: no hits in source/tests (inventory.yaml prose mentioning the old guess in archived context is fine, but live `MOW_SHAPE_TYPE` must be 11).

- [ ] **Step 7: Record the fact in inventory.**

In `inventory.yaml` § the `o=215` entry, ensure the `verifications:` already records the 2026-06-17 full type map (it does, at the line documenting "Circle is 11 not 12"). No new verification needed — this item only aligns code to the already-recorded fact. Confirm with: `grep -n "Circle is 11" custom_components/dreame_a2_mower/inventory.yaml`.

- [ ] **Step 8: Run full protocol suite + commit.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/protocol/ -q` — Expected: PASS.

```bash
git add custom_components/dreame_a2_mower/protocol/map_edit_shapes.py tests/protocol/test_map_edit_shapes.py
git add -p   # stage services.yaml / entity-inventory.yaml shape-list edits explicitly
git commit -m "fix(map-edit): correct create-shape type table (circle 12→11, add moon/star/butterfly/blob/tree/carrot)"
```

---

## Item 6 — `s2p2=72` authoritative text + `71` finalize

(Done early — pure tables, and the confidence gate requires the inventory row first.)

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (§ s2p2 / state_codes)
- Modify: `custom_components/dreame_a2_mower/mower/error_codes.py:90-91,153`
- Modify: `custom_components/dreame_a2_mower/translations/en.json`, `strings.json`
- Grep-and-update consumers of the old slug: `device_trigger.py`, `logbook.py`
- Test: `tests/inventory/test_error_codes_confidence_gate.py` (must stay green), plus a new assertion

- [ ] **Step 1: Update inventory FIRST (confidence gate + fact discipline).**

In `inventory.yaml` § s2p2:
1. In `observed_values`, change `- {value: 72, status: partial}` → `- {value: 72, status: confirmed}`.
2. Append to the s2p2 `verifications:` list:

```yaml
      - date: "2026-06-17"
        status: verified
        claim: |
          s2p2=72 cloud-LABELLED fire captured — resolves the borrowed-slug gate.
          Two stored cloud notifications correlate to the second with probe-log
          s2p2 fires on 2026-06-17: "Task paused for too long. Automatically
          returning to the station to wait." ↔ s2p2 50→72 @12:38:22 (s2p1 3
          PAUSED→2→5 RETURNING); and (sibling 71) "The robot is on standby
          outside the station for too long. Automatically returning to the
          station." ↔ s2p2 74→71 @11:28:49. So 72's authoritative g2408 text is
          "Task paused for too long. Automatically returning to the station to
          wait." — NOT the borrowed dreame-mower "Returning to dock after pause
          timeout". error_codes.py text + S2P2_EVENT_TYPES slug updated to match.
        evidence: "probe/logs/probe_log_20260612_174439.jsonl@2026-06-17T12:38:22 (s2p2=72) + @11:28:49 (s2p2=71); integration-stored cloud notifications (localizationContents) at 12:38 / 11:28"
```
3. Remove the now-stale prose in the s2p2 `semantic:` block that says 72 is "Still kept OUT of error_codes.py until a cloud-LABELLED fire is captured" / "the slug name is still borrowed" (two occurrences near the `72 —` bullet and the 2026-06-15 verification). Per the retraction rule, append the verbatim removed sentences to `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/inventory-history/s2p2.md` with date 2026-06-17 and the reason ("cloud-labelled fire captured 2026-06-17, gate satisfied").

- [ ] **Step 2: Write the failing test for the corrected text/slug.**

Add to `tests/inventory/test_error_codes_confidence_gate.py` (or a sibling test file `tests/mower/test_error_codes_text.py` if cleaner):

```python
from custom_components.dreame_a2_mower.mower.error_codes import (
    ERROR_CODE_DESCRIPTIONS, S2P2_EVENT_TYPES,
)

def test_s2p2_72_authoritative_text_and_slug():
    assert ERROR_CODE_DESCRIPTIONS[72] == (
        "Task paused for too long. Automatically returning to the station to wait."
    )
    assert S2P2_EVENT_TYPES[72] == "paused_too_long_returning"

def test_s2p2_71_text_matches_cloud():
    assert "standby outside station" in ERROR_CODE_DESCRIPTIONS[71].lower()
    assert S2P2_EVENT_TYPES[71] == "standby_outside_station_too_long"
```

- [ ] **Step 3: Run to verify failure.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/inventory/test_error_codes_confidence_gate.py -q -k "72 or 71"`
Expected: FAIL — 72 text/slug still the borrowed values.

- [ ] **Step 4: Update `error_codes.py`.**

`error_codes.py:90-91` — replace:
```python
    # 72: wire-confirmed 2026-06-17 — a PAUSED mower (~1h) auto-returns. inventory § s2p2.
    72: "Returning to dock after pause timeout",
```
with:
```python
    # 72: cloud-LABELLED fire captured 2026-06-17 — authoritative g2408 text
    # (the dreame-mower "Returning to dock after pause timeout" slug was borrowed
    # and is now superseded). Fires from s2p1=3 (deliberate pause) or =4 (auto-hold)
    # after the ~1h pause timeout. inventory § s2p2 (verified 2026-06-17).
    72: "Task paused for too long. Automatically returning to the station to wait.",
```

`error_codes.py:153` — replace:
```python
    72:  "return_after_pause_timeout",      # wire-confirmed 2026-06-17 (paused ~1h -> auto-return; from s2p1=3 or 4)
```
with:
```python
    72:  "paused_too_long_returning",       # cloud-labelled 2026-06-17 ("Task paused for too long. Automatically returning to the station to wait.")
```

- [ ] **Step 5: Update all consumers of the old slug.**

Run: `grep -rn "return_after_pause_timeout" custom_components/ tests/`
For each hit (`strings.json`, `translations/en.json`, `device_trigger.py`, `logbook.py`, any test), replace `return_after_pause_timeout` → `paused_too_long_returning`. In `translations/en.json` / `strings.json` update the human label under the event trigger block to "Task paused too long — returning".

- [ ] **Step 6: Run to verify pass.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/inventory/ tests/mower/ -q`
Expected: PASS (incl. confidence gate — 72's `observed_values` is now `confirmed`).

- [ ] **Step 7: Regenerate the canonical doc + commit.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py` (no flag — regenerates `docs/research/inventory/generated/g2408-canonical.md`).

```bash
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/mower/error_codes.py
git add custom_components/dreame_a2_mower/translations/en.json custom_components/dreame_a2_mower/strings.json
git add custom_components/dreame_a2_mower/device_trigger.py custom_components/dreame_a2_mower/logbook.py
git add tests/ docs/research/inventory/generated/g2408-canonical.md
git commit -m "feat(s2p2): authoritative cloud text for code 72 (slug return_after_pause_timeout→paused_too_long_returning)"
```

---

## Item 3 — `s2p57` low-battery self-shutdown lifecycle event

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/property_mapping.py` (add `(2,57)`)
- Modify: `custom_components/dreame_a2_mower/mower/state.py` (add `robot_shutdown_trigger` field)
- Modify: `custom_components/dreame_a2_mower/const.py` (add `EVENT_TYPE_SELF_SHUTDOWN` + tuple)
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` (`_prev_shutdown_trigger` init)
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` (edge-fire method + call site)
- Modify: `custom_components/dreame_a2_mower/translations/en.json`, `strings.json`
- Modify: `inventory.yaml` (s2p57 already verified — add entity cross-ref); `entity-inventory.yaml`; `state_machine_audit_expectations.yaml`
- Test: `tests/mower/test_property_mapping.py`, `tests/integration/test_lifecycle_events.py` (or the existing event test file)

- [ ] **Step 1: Add the event-type constant (failing import first).**

`const.py` — after `EVENT_TYPE_FAULT_CLEARED` (line 42) add:
```python
EVENT_TYPE_SELF_SHUTDOWN: Final = "self_shutdown"
```
and add `EVENT_TYPE_SELF_SHUTDOWN,` to the `LIFECYCLE_EVENT_TYPES` tuple (after `EVENT_TYPE_FAULT_CLEARED,`).

- [ ] **Step 2: Add the MowerState field.**

`state.py` — near the OTA fields (~line 271), add:
```python
    # Source: s2p57 robot_shutdown_trigger via property_mapping. Bare int;
    # value 1 = firmware self-shutdown (confirmed low-battery protective cutoff
    # 2026-06-14; other triggers unconfirmed). inventory § s2p57.
    robot_shutdown_trigger: int | None = None
```

- [ ] **Step 3: Write the failing property-mapping test.**

Add to `tests/mower/test_property_mapping.py`:
```python
from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
from custom_components.dreame_a2_mower.mower.state import MowerState

def test_s2p57_maps_to_robot_shutdown_trigger():
    st = apply_property_to_state(MowerState(), 2, 57, 1)
    assert st.robot_shutdown_trigger == 1
```

- [ ] **Step 4: Run to verify failure.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/mower/test_property_mapping.py -q -k s2p57`
Expected: FAIL — field stays None (no mapping).

- [ ] **Step 5: Add the property mapping.**

`property_mapping.py` — in `PROPERTY_MAPPING`, after the s2p56 entry, add:
```python
    # s2.57 robot_shutdown_trigger — bare scalar int (NOT the apk-hypothesized
    # dict). value 1 = firmware self-shutdown. inventory § s2p57.
    (2, 57): PropertyMappingEntry(
        field_name="robot_shutdown_trigger",
        extract_value=lambda v: int(v) if isinstance(v, (int, float, bool)) else None,
    ),
```

- [ ] **Step 6: Run to verify pass.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/mower/test_property_mapping.py -q -k s2p57`
Expected: PASS.

- [ ] **Step 7: Add the `_prev_shutdown_trigger` init.**

`coordinator/_core.py` `_CoreMixin.__init__` — alongside the other `_prev_*` fields (grep `_prev_charging_status`), add:
```python
        self._prev_shutdown_trigger: int | None = None
```

- [ ] **Step 8: Write the failing lifecycle-fire test.**

Add to the existing lifecycle event test module (grep `EVENT_TYPE_CHARGING_STARTED` in `tests/` to find it, e.g. `tests/integration/test_lifecycle_events.py`). Mirror the charging-edge test:
```python
def test_self_shutdown_fires_once_on_s2p57_edge(coordinator_with_event_entity):
    coord = coordinator_with_event_entity
    coord._fire_self_shutdown_if_edge(old=None, new=1, now_unix=1000)  # primes, no fire
    coord._fire_self_shutdown_if_edge(old=None, new=1, now_unix=1001)  # still primed-equal
    # First real transition None/0 -> 1 fires exactly once:
    coord._prev_shutdown_trigger = 0
    coord._fire_self_shutdown_if_edge(old=0, new=1, now_unix=1002)
    fired = [c for c in coord._lifecycle_event.fired if c[0] == "self_shutdown"]
    assert len(fired) == 1
```
(Adapt the fixture/assertion to the test module's existing harness — e.g. a fake event entity that records `trigger()` calls. Match the pattern used for `charging_started`.)

- [ ] **Step 9: Run to verify failure.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/integration/test_lifecycle_events.py -q -k self_shutdown`
Expected: FAIL — method does not exist.

- [ ] **Step 10: Implement the edge-fire method + call site.**

`coordinator/_mqtt_handlers.py` — after `_fire_rain_delay_started_if_edge` (~line 371) add:
```python
    def _fire_self_shutdown_if_edge(
        self, *, old: int | None, new: int | None, now_unix: int
    ) -> None:
        """Fire self_shutdown on the s2p57 rising edge into 1 (firmware
        self-shutdown — confirmed low-battery protective cutoff 2026-06-14).
        First observation only primes _prev so a value already 1 at boot
        doesn't fire spuriously."""
        if new == 1 and old != 1:
            self._fire_lifecycle(
                EVENT_TYPE_SELF_SHUTDOWN,
                {"at_unix": int(now_unix), "reason": "low_battery", "value": int(new)},
            )
```
Add `EVENT_TYPE_SELF_SHUTDOWN` to the `from ..const import (...)` block in `_mqtt_handlers.py`.

Wire the call: locate where `_fire_rain_delay_started_if_edge` is invoked (the s2p2-transition handler that has access to old/new property values and `now_unix`). In the same property-push handler, after applying the property, compare the previous and new `robot_shutdown_trigger` and call:
```python
            self._fire_self_shutdown_if_edge(
                old=self._prev_shutdown_trigger,
                new=new_state.robot_shutdown_trigger,
                now_unix=now_unix,
            )
            self._prev_shutdown_trigger = new_state.robot_shutdown_trigger
```
(Use the same `new_state`/`now_unix` names already in scope at that handler — grep the surrounding lines to match.)

- [ ] **Step 11: Run to verify pass.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/integration/test_lifecycle_events.py -q -k self_shutdown`
Expected: PASS.

- [ ] **Step 12: Translations + CI-coupling chores.**

- `translations/en.json` + `strings.json`: add the `self_shutdown` event-trigger label ("Self-shutdown (low battery)") wherever the other lifecycle slugs are listed.
- `entity-inventory.yaml`: the lifecycle event entity already exists; add `self_shutdown` to its `event_types` list (mark `presumed`).
- `inventory.yaml` § s2p57: add an `integration_code` reference line noting it now fires `event.dreame_a2_mower_lifecycle` `self_shutdown` (this is an entity-source change → fact-discipline applies). Append a `verifications:` entry dated 2026-06-17 status `verified` claim "s2p57=1 now mapped to MowerState.robot_shutdown_trigger and fires lifecycle self_shutdown" evidence "probe_log_20260612_174439.jsonl@2026-06-14T04:42:16".
- `state_machine_audit_expectations.yaml`: `robot_shutdown_trigger` is an attribute-only MowerState field with no sensor → add it to `_KNOWN_ATTRIBUTE_SURFACED_FIELDS` (in `tools/entity_source_inventory.py` or wherever that set lives — grep `_KNOWN_ATTRIBUTE_SURFACED_FIELDS`). The new event_type does not add a sensor, so no idle/reboot yellow rows are needed; confirm by running the audit test.

- [ ] **Step 13: Run audit + full suite, commit.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/ -q -k "audit or lifecycle or property_mapping"`
Expected: PASS. Then regen canonical doc (`inventory_gen.py`).

```bash
git add custom_components/dreame_a2_mower/mower/property_mapping.py custom_components/dreame_a2_mower/mower/state.py
git add custom_components/dreame_a2_mower/const.py custom_components/dreame_a2_mower/coordinator/_core.py
git add custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py
git add custom_components/dreame_a2_mower/translations/en.json custom_components/dreame_a2_mower/strings.json
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml
git add tools/ tests/ docs/research/inventory/generated/g2408-canonical.md
git commit -m "feat(events): fire self_shutdown lifecycle event on s2p57=1 (low-battery firmware cutoff)"
```

---

## Item 2 — Per-zone progress sensor

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/property_mapping.py` (`(2,56)` → `multi_field`)
- Modify: `custom_components/dreame_a2_mower/mower/state.py` (add `zone_progress` field)
- Create/modify: `custom_components/dreame_a2_mower/entities/sensor/device.py` (new sensor class + description)
- Modify: `inventory.yaml` (s2p56 already verified — add entity ref); `entity-inventory.yaml`; `state_machine_audit_expectations.yaml`
- Modify: `dashboards/mower/dashboard.yaml`
- Test: `tests/mower/test_property_mapping.py`, `tests/.../test_zone_progress_sensor.py`

**Data model:** `(2,56)` carries `{"status": [[zone_id, stage], …]}`. `task_state_code` stays the stage of `status[0][-1]`. New `zone_progress` field = the full parsed list of `(zone_id, stage)` tuples. Stage enum: `-1` queued, `0` active, `2` done. The sensor joins `zone_id → MowingZone.name` from the active map at render time (the pure mapping layer has no map access).

- [ ] **Step 1: Write the failing multi_field extractor test.**

Add to `tests/mower/test_property_mapping.py`:
```python
def test_s2p56_multi_field_sets_task_state_and_zone_progress():
    v = {"status": [[1, 2], [2, 0]]}
    st = apply_property_to_state(MowerState(), 2, 56, v)
    assert st.task_state_code == 2            # status[0][-1] unchanged
    assert st.zone_progress == ((1, 2), (2, 0))

def test_s2p56_empty_status_clears_zone_progress():
    st = apply_property_to_state(MowerState(), 2, 56, {"status": []})
    assert st.task_state_code is None
    assert st.zone_progress == ()

def test_s2p56_three_element_entry_tolerated():
    # 3-element [id, 0, stage] — task_state_code uses last; zone_progress
    # uses (id, last).
    st = apply_property_to_state(MowerState(), 2, 56, {"status": [[1, 0, 4]]})
    assert st.task_state_code == 4
    assert st.zone_progress == ((1, 4),)
```

- [ ] **Step 2: Run to verify failure.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/mower/test_property_mapping.py -q -k s2p56`
Expected: FAIL — `zone_progress` attribute does not exist / not set.

- [ ] **Step 3: Add the `zone_progress` MowerState field.**

`state.py` — near `task_state_code` (line 316) add:
```python
    # Source: s2p56 status array via property_mapping multi_field — per-zone/
    # per-target progress as (target_id, stage) pairs. stage: -1 queued,
    # 0 active, 2 done. Active target = the pair whose stage == 0. target_id
    # joins MAP.*.mowingAreas ids. inventory § s2p56 (verified 2026-06-16).
    zone_progress: tuple[tuple[int, int], ...] = ()
```

- [ ] **Step 4: Convert `(2,56)` to `multi_field`.**

`property_mapping.py` — replace the existing `(2, 56)` entry's body with a `multi_field` form. Add two module-level helpers above `PROPERTY_MAPPING` (next to other extract helpers):
```python
def _s2p56_stage(v: Any) -> int | None:
    if (isinstance(v, dict) and isinstance(v.get("status"), list)
            and v["status"] and isinstance(v["status"][0], list)
            and len(v["status"][0]) >= 2):
        return int(v["status"][0][-1])
    return None

def _s2p56_zone_progress(v: Any) -> tuple[tuple[int, int], ...]:
    if not (isinstance(v, dict) and isinstance(v.get("status"), list)):
        return ()
    out: list[tuple[int, int]] = []
    for entry in v["status"]:
        if isinstance(entry, list) and len(entry) >= 2:
            out.append((int(entry[0]), int(entry[-1])))
    return tuple(out)
```
Then:
```python
    (2, 56): PropertyMappingEntry(
        multi_field=(
            ("task_state_code", _s2p56_stage),
            ("zone_progress", _s2p56_zone_progress),
        ),
    ),
```
Keep the existing explanatory comment block above the entry; append a note that `zone_progress` is the full per-target array (see inventory § s2p56 2026-06-16). NOTE: confirm `apply_property_to_state` assigns `multi_field` results even when an extractor returns `()` / falsy (it does — `_property_apply.py:781-785` assigns `updates[field]` unconditionally inside the try). The empty-status test (Step 1) guards this.

- [ ] **Step 5: Run to verify pass.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/mower/test_property_mapping.py -q -k s2p56`
Expected: PASS.

- [ ] **Step 6: Write the failing sensor test.**

Create `tests/integration/test_zone_progress_sensor.py`. Use the project's existing sensor-test harness (grep an existing `tests/integration/test_*sensor*.py` for the coordinator/entity fixture pattern). Assert:
```python
def test_zone_progress_sensor_state_and_attrs(zone_progress_coordinator):
    # coordinator.data.zone_progress = ((1,2),(2,0),(3,-1)); active map has
    # mowing zones {1:"Front",2:"Back",3:"Side"}.
    sensor = make_zone_progress_sensor(zone_progress_coordinator)
    assert sensor.native_value == "Mowing zone 2 of 3"
    attrs = sensor.extra_state_attributes
    assert attrs["current_zone_id"] == 2
    assert attrs["current_zone_name"] == "Back"
    assert attrs["zones"] == [
        {"id": 1, "name": "Front", "status": "done"},
        {"id": 2, "name": "Back", "status": "active"},
        {"id": 3, "name": "Side", "status": "queued"},
    ]

def test_zone_progress_sensor_idle_when_empty(idle_coordinator):
    sensor = make_zone_progress_sensor(idle_coordinator)
    assert sensor.native_value in (None, "Idle")
    assert sensor.extra_state_attributes["zones"] == []
```

- [ ] **Step 7: Run to verify failure.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/integration/test_zone_progress_sensor.py -q`
Expected: FAIL — sensor class undefined.

- [ ] **Step 8: Implement the sensor.**

In `entities/sensor/device.py`, add a parent-device sensor class. It needs `cloud_state` access for the name join, so it's a full `CoordinatorEntity` subclass (not a pure description with `value_fn`). Pattern:
```python
_STAGE_LABEL = {-1: "queued", 0: "active", 2: "done"}

class DreameA2ZoneProgressSensor(
    CoordinatorEntity[DreameA2MowerCoordinator], SensorEntity
):
    """Per-zone mow progress derived from s2p56. Names come from the active
    map's MowingZone.name (wire/app names); synthetic 'Zone N' fallback only."""

    _attr_has_entity_name = True
    _attr_translation_key = "zone_progress"
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "zone_progress")
        self._attr_name = "Zone progress"
        self._attr_device_info = mower_device_info(coordinator)

    def _zone_name(self, zone_id: int) -> str:
        cs = getattr(self.coordinator, "cloud_state", None)
        active = getattr(self.coordinator.data, "active_map_id", None)
        map_obj = cs.maps_by_id.get(active) if cs and active is not None else None
        zones = getattr(map_obj, "mowing_zones", None) or []
        for z in zones:
            if getattr(z, "zone_id", None) == zone_id and getattr(z, "name", None):
                return z.name
        return f"Zone {zone_id}"

    @property
    def _zones(self) -> list[dict]:
        prog = getattr(self.coordinator.data, "zone_progress", ()) or ()
        return [
            {"id": zid, "name": self._zone_name(zid),
             "status": _STAGE_LABEL.get(stage, "unknown")}
            for zid, stage in prog
        ]

    @property
    def native_value(self) -> str | None:
        zones = self._zones
        if not zones:
            return "Idle"
        active_idx = next(
            (i for i, z in enumerate(zones) if z["status"] == "active"), None
        )
        if active_idx is None:
            return "Idle"
        return f"Mowing zone {active_idx + 1} of {len(zones)}"

    @property
    def extra_state_attributes(self) -> dict:
        zones = self._zones
        active = next((z for z in zones if z["status"] == "active"), None)
        return {
            "current_zone_id": active["id"] if active else None,
            "current_zone_name": active["name"] if active else None,
            "zones": zones,
        }
```
Verify the field names against the codebase: confirm the active-map id field on `MowerState` (grep `active_map_id` — adjust if it's `current_map_id`), and the mowing-zone collection name on the map dataclass (grep `mowing_zones`/`MowingZone` in the decoder; `map_decoder.py:478` constructs `MowingZone(zone_id=..., name=...)` — find the attribute holding the list on the parsed map object). Register the sensor in `entities/sensor/device.py`'s setup list (grep how `DreameA2*Sensor` instances are appended in `async_setup_entry`/the entity-build function) so it's added once for the parent device.

- [ ] **Step 9: Run to verify pass.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/integration/test_zone_progress_sensor.py -q`
Expected: PASS.

- [ ] **Step 10: CI-coupling chores.**

- `entity-inventory.yaml`: add a row for `sensor.dreame_a2_mower_zone_progress` (`presumed`; source `s2p56` via `zone_progress`).
- `state_machine_audit_expectations.yaml`: add the two rows for the new sensor (idle + reboot yellows) per the convention; add `zone_progress` to `_KNOWN_ATTRIBUTE_SURFACED_FIELDS` if the audit flags the MowerState field.
- `inventory.yaml` § s2p56: append a `verifications:` entry dated 2026-06-17 noting the integration now surfaces per-zone progress via `sensor.zone_progress` (entity-source change → fact discipline). `translations/en.json` + `strings.json`: add the `zone_progress` sensor name.
- wire-census: run `tools/wire_census.py` if it flags the s2p56 multi-field; park any novelty.

- [ ] **Step 11: Dashboard card.**

In `dashboards/mower/dashboard.yaml`, add (near the task/area cards) a markdown card templating the `zones` attribute, e.g.:
```yaml
      - type: markdown
        title: Zone progress
        content: >
          {% set z = state_attr('sensor.dreame_a2_mower_zone_progress','zones') %}
          {% if z %}{% for zone in z %}
          {{ '✅' if zone.status=='done' else ('🟢' if zone.status=='active' else '⚪') }} {{ zone.name }}
          {% endfor %}{% else %}Idle{% endif %}
```
(Deploy via SCP in the release step, not here.)

- [ ] **Step 12: Run audit + full suite, commit.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/ -q -k "audit or zone_progress or property_mapping or entity_inventory"`
Expected: PASS. Regen canonical doc.

```bash
git add custom_components/dreame_a2_mower/mower/property_mapping.py custom_components/dreame_a2_mower/mower/state.py
git add custom_components/dreame_a2_mower/entities/sensor/device.py
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml
git add custom_components/dreame_a2_mower/translations/en.json custom_components/dreame_a2_mower/strings.json
git add tools/ tests/ dashboards/mower/dashboard.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "feat(sensor): per-zone mow progress from s2p56 (wire zone names, map-joinable)"
```

---

## Item 4 — Turning Method per-map select (`PRE[19]`)

**Files:**
- Modify: `custom_components/dreame_a2_mower/entities/select/map_settings.py` (new class)
- Modify: `custom_components/dreame_a2_mower/select.py` (register in per-map setup loop)
- Modify: control-honesty config (`CONTROL_MODES` — grep `resolve_control_mode` source)
- Modify: `entity-inventory.yaml`, `state_machine_audit_expectations.yaml`, `inventory.yaml`, `translations/en.json`, `strings.json`
- Modify: `dashboards/mower/dashboard.yaml`
- Test: `tests/.../test_map_settings_selects.py` (grep the existing per-map select test module)

**Wire:** `PRE[19]` = Turning Method, `0=Efficient`, `1=Lawn-Care` (= SETTINGS `steeringMode`). PRE grew 19→21 ints on the 0625 OTA; indices 0–18 unchanged; the RMW `set_pre` patches one index and round-trips the full array. On fw with a 19-int PRE there is no `[19]` → entity unavailable. The value reads back from `cs.settings.by_map_id_canonical[map_id]["steeringMode"]` (the SETTINGS dual-write half, same as `mowingDirectionMode`).

- [ ] **Step 1: Add the control-mode entry.**

Grep the `CONTROL_MODES` source (`grep -rn "def resolve_control_mode\|CONTROL_MODES" custom_components/dreame_a2_mower/`). Add `map_N_settings_turning_method` as a writable control (mirror `map_N_settings_mowing_direction_mode`).

- [ ] **Step 2: Write the failing select test.**

Find the per-map select test module (grep `DreameA2PerMapMowingDirectionModeSelect` in `tests/`). Add:
```python
def test_turning_method_options_and_current(turning_method_coordinator):
    # settings.by_map_id_canonical[0]["steeringMode"] = 1
    sel = DreameA2PerMapTurningMethodSelect(turning_method_coordinator, map_id=0)
    assert sel.options == ["Efficient", "Lawn-Care"]
    assert sel.current_option == "Lawn-Care"

async def test_turning_method_write_uses_pre_index_19(turning_method_coordinator, monkeypatch):
    sel = DreameA2PerMapTurningMethodSelect(turning_method_coordinator, map_id=0)
    calls = []
    monkeypatch.setattr(
        "custom_components.dreame_a2_mower.entities.select.map_settings."
        "pre_settings_optimistic_write",
        lambda *a, **k: calls.append(k) or _noop_awaitable(),
    )
    await sel.async_select_option("Efficient")
    assert calls[0]["pre_index"] == 19
    assert calls[0]["pre_value"] == 0
    assert calls[0]["settings_field"] == "steeringMode"
```
(Use the same fixture/await harness the existing direction-mode select test uses; `_noop_awaitable` = whatever no-op coroutine helper that module already has.)

- [ ] **Step 3: Run to verify failure.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/ -q -k turning_method`
Expected: FAIL — class undefined.

- [ ] **Step 4: Implement the select.**

`entities/select/map_settings.py` — add after `DreameA2PerMapMowingDirectionModeSelect` (copy its structure exactly, changing the 4 specifics):
```python
class DreameA2PerMapTurningMethodSelect(
    _FreshnessAvailableMixin,
    _ControlHonestyMixin,
    CoordinatorEntity[DreameA2MowerCoordinator],
    SelectEntity,
):
    """Per-map Turning Method — Efficient / Lawn-Care.

    Device enum (PRE[19] / SETTINGS.steeringMode): 0 = Efficient,
    1 = Lawn-Care. New post-0625-OTA field (app 2.5.8.1 "Turning Method
    Settings"). inventory § PRE[19] (verified 2026-06-17).
    """

    _OPTIONS = ("Efficient", "Lawn-Care")

    _attr_has_entity_name = True
    _availability_source = "cloud"
    _attr_translation_key = "settings_turning_method"
    _attr_options: ClassVar[list[str]] = list(_OPTIONS)
    _attr_should_poll = False

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(
            coordinator, map_id, "settings_turning_method"
        )
        self._control_mode = resolve_control_mode(
            platform="select", key="map_N_settings_turning_method"
        )
        map_obj = coordinator.cloud_state.maps_by_id.get(map_id)
        self._attr_name = "Turning Method"
        self._attr_device_info = map_device_info(
            coordinator, map_id, name=getattr(map_obj, "name", None),
        )

    @property
    def current_option(self) -> str | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        v = cs.settings.by_map_id_canonical.get(self._map_id, {}).get("steeringMode")
        if v is None:
            return None
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return None
        return self._OPTIONS[iv] if 0 <= iv < len(self._OPTIONS) else None

    @property
    def available(self) -> bool:
        if self.current_option is None:
            return False
        return super().available

    async def async_select_option(self, option: str) -> None:
        if self.read_only:
            return await self._reject_readonly_write()
        if option not in self._OPTIONS:
            return
        idx = self._OPTIONS.index(option)
        await pre_settings_optimistic_write(
            self, state_field="settings_turning_method", new_value=idx,
            map_id=self._map_id, pre_index=19, pre_value=idx,
            settings_field="steeringMode", settings_value=idx,
        )
```
NOTE on the fw-0550 short-PRE guard: `current_option` already returns `None` when `steeringMode` is absent (→ `available=False`), so a 19-int-PRE firmware (no `[19]`, no `steeringMode` in SETTINGS) shows the entity unavailable rather than erroring. Confirm `pre_settings_optimistic_write` / `set_pre` tolerate a write to index 19 when the fetched array is only 19 long — if `set_pre` indexes blindly, add a guard there or in the helper to refuse `pre_index >= len(array)`; cover with a test. (Grep `def set_pre` in `cloud_client/_fetchers.py`.)

- [ ] **Step 5: Register the select.**

`select.py` — in the per-map build loop (grep `DreameA2PerMapMowingDirectionModeSelect(`), append `DreameA2PerMapTurningMethodSelect(coordinator, map_id=map_id)` alongside it.

- [ ] **Step 6: Run to verify pass.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/ -q -k turning_method`
Expected: PASS.

- [ ] **Step 7: CI-coupling chores + state_field check.**

- `pre_settings_optimistic_write`'s `state_field="settings_turning_method"` — confirm whether that helper requires a matching MowerState field for the optimistic overlay (the direction-mode one uses `settings_mowing_direction_mode`). Grep the helper; if it writes an optimistic overlay to a MowerState/snapshot field, add `settings_turning_method` there too (mirror `settings_mowing_direction_mode`). If the overlay is keyed only on the SETTINGS dict, no field needed.
- control-honesty: `test_control_entities_wired` must pass with the new key.
- `entity-inventory.yaml`: add the per-map select row (`presumed`, writable, source PRE[19]/SETTINGS.steeringMode).
- `state_machine_audit_expectations.yaml`: per-map select rows as required by the convention.
- `inventory.yaml`: PRE[19] is already verified — add an `integration_code` ref + a 2026-06-17 `verifications:` entry noting the new `select.map_N_turning_method` reads SETTINGS.steeringMode / writes PRE[19] (entity-source change → fact discipline). `translations/en.json`+`strings.json`: add `settings_turning_method` name.

- [ ] **Step 8: Dashboard.**

Add the `select.dreame_a2_mower_map_1_turning_method` (and map_2) to the per-map settings card in `dashboards/mower/dashboard.yaml`.

- [ ] **Step 9: Run per-map naming + control tests + full suite, commit.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/ -q -k "turning_method or per_map_entity_names or control_entities_wired or audit"`
Expected: PASS. Regen canonical doc.

```bash
git add custom_components/dreame_a2_mower/entities/select/map_settings.py custom_components/dreame_a2_mower/select.py
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml
git add custom_components/dreame_a2_mower/translations/en.json custom_components/dreame_a2_mower/strings.json
git add custom_components/dreame_a2_mower/  # control-mode source + set_pre guard if added
git add tools/ tests/ dashboards/mower/dashboard.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "feat(select): per-map Turning Method (PRE[19] Efficient/Lawn-Care)"
```

---

## Item 5 — Update Station Location button (`o=19`)

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/actions.py` (enum + `ACTION_TABLE`)
- Modify: `custom_components/dreame_a2_mower/button.py` (new class + register)
- Modify: control-honesty `CONTROL_MODES`, `entity-inventory.yaml`, `state_machine_audit_expectations.yaml`, `inventory.yaml`, `translations/en.json`, `strings.json`
- Modify: `dashboards/mower/dashboard.yaml`
- Test: `tests/.../test_buttons.py` (grep the existing button test module)

**Wire:** `o=19` parameterless routed action `{m:'a', p:0, o:19}` (r=0) — `routed_action` default is `p=0`, so no extra args. Mirrors `CANCEL_DOCK_RETURN` (`routed_o=13`).

- [ ] **Step 1: Add the control-mode entry.**

In the `CONTROL_MODES` source, add `update_station_location` as a writable button control (mirror `cancel_dock_return`).

- [ ] **Step 2: Write the failing button test.**

Find the button test module (grep `DreameA2CancelDockReturnButton`/`dispatch_action` in `tests/`). Add:
```python
async def test_update_station_location_button_dispatches_o19(button_coordinator):
    calls = []
    button_coordinator.dispatch_action = lambda action, params: (
        calls.append((action, params)) or _ok_write_result()
    )
    btn = DreameA2UpdateStationLocationButton(button_coordinator)
    await btn.async_press()
    from custom_components.dreame_a2_mower.mower.actions import MowerAction
    assert calls[0][0] == MowerAction.UPDATE_STATION_LOCATION

def test_update_station_action_table_routed_o_19():
    from custom_components.dreame_a2_mower.mower.actions import ACTION_TABLE, MowerAction
    assert ACTION_TABLE[MowerAction.UPDATE_STATION_LOCATION]["routed_o"] == 19
```
(`_ok_write_result` = the WriteResult-success helper the existing button tests use.)

- [ ] **Step 3: Run to verify failure.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/ -q -k update_station`
Expected: FAIL — `MowerAction.UPDATE_STATION_LOCATION` undefined.

- [ ] **Step 4: Add the action.**

`actions.py` — in the `MowerAction` enum (after `START_EDGE_PATROL`, line 61):
```python
    UPDATE_STATION_LOCATION = auto()  # o=19 re-localize dock (app 2.5.8.1 "Update station location")
```
In `ACTION_TABLE` (after `CANCEL_DOCK_RETURN`, line 270):
```python
    MowerAction.UPDATE_STATION_LOCATION: {"siid": 2, "aiid": 50, "routed_o": 19},
```

- [ ] **Step 5: Add the button.**

`button.py` — after `DreameA2CancelDockReturnButton` add:
```python
class DreameA2UpdateStationLocationButton(_DreameA2ActionButton):
    """Re-localize the charging dock (o=19). The mower undocks, does a LiDAR
    reorient spin, and re-stores its dock pose; dock_x/y/yaw refresh after.
    inventory § s2p50 o=19 (verified 2026-06-17)."""

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(
            coordinator, "update_station_location",
            "Update station location", "mdi:map-marker-radius",
        )
        self._action = MowerAction.UPDATE_STATION_LOCATION
```
Register it in `button.py`'s `async_setup_entry` (grep where `DreameA2RechargeButton(coordinator)` etc. are appended to the parent-device `entities` list) — add `DreameA2UpdateStationLocationButton(coordinator)`.

- [ ] **Step 6: Run to verify pass.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/ -q -k update_station`
Expected: PASS.

- [ ] **Step 7: CI-coupling chores.**

- control-honesty: `test_control_entities_wired` green with `update_station_location`.
- `entity-inventory.yaml`: add `button.dreame_a2_mower_update_station_location` row (`presumed`, writable, action o=19).
- `state_machine_audit_expectations.yaml`: button rows per convention.
- `inventory.yaml` § o=19: already verified — add an `integration_code` ref + 2026-06-17 `verifications:` entry "surfaced as button.update_station_location dispatching routed o=19" (entity-source change). `translations/en.json`+`strings.json`: button name.

- [ ] **Step 8: Dashboard.**

Add the button to the actions card in `dashboards/mower/dashboard.yaml`.

- [ ] **Step 9: Run control + audit + full suite, commit.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest tests/ -q -k "update_station or control_entities_wired or audit"`
Expected: PASS. Regen canonical doc.

```bash
git add custom_components/dreame_a2_mower/mower/actions.py custom_components/dreame_a2_mower/button.py
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml
git add custom_components/dreame_a2_mower/translations/en.json custom_components/dreame_a2_mower/strings.json
git add custom_components/dreame_a2_mower/  # control-mode source
git add tools/ tests/ dashboards/mower/dashboard.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "feat(button): Update Station Location (routed o=19 dock re-localize)"
```

---

## Final — full verification, dashboard deploy, release

- [ ] **Step 1: Full suite green.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/pytest -q`
Expected: all pass (baseline 1591 + new tests), 4 skipped. If any CI-coupling test (`audit`, `control_entities_wired`, `entity_inventory`, `inventory schema`, `wire_census`, `per_map_entity_names`) is red, fix before proceeding — do NOT label it "pre-existing" without diffing against `main`.

- [ ] **Step 2: Canonical doc + inventory audit.**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py` then `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_audit.py` — Expected: clean.

- [ ] **Step 3: Deploy the dashboard.**

Per the dashboard deploy procedure (memory `reference_ha_dashboard_deploy`): back up `/config/dashboards/mower/dashboard.yaml`, SCP the updated file via `sshpass`, browser-reload (no HA restart). Verify the per-zone card, Turning Method select, and Update Station button render (check for `createErrorCardElement` in the HA log if a view is blank).

- [ ] **Step 4: Version bump + release.**

Watch the HACS digit-boundary ladder (memory `feedback_hacs_version_ladder`): from `1.0.29a3` the next alpha `1.0.29a4` is fine. Run `tools/release/release.sh` (bump + tag + push + GitHub Release + HACS refresh) — a GitHub **Release** is required (HACS reads Releases, not commits/tags). Do NOT use a manual `gh release` (memory `project_photo_categorization_shipped` — release.sh is the supported path).

- [ ] **Step 5: Live deploy + A/B verify.**

Per the project resume doc technique: deploy the new version to the running HA, reload the config entry, and verify on live:
- Turning Method select writes (set Efficient↔Lawn-Care, confirm PRE[19] round-trips — gated on fw 0625).
- Update Station Location button (press, confirm dock re-localize + dock_x/y/yaw refresh).
- Per-zone sensor on the next multi-zone mow (`sensor.zone_progress` shows current/done/queued with wire zone names).
- `s2p57` / `s2p2=72` are event-driven — validate opportunistically (next stranded/paused-timeout event).

- [ ] **Step 6: Finish the branch.**

Use superpowers:finishing-a-development-branch. Move this spec + plan to `OLD/ha-dreame-a2-mower-docs/superpowers/` per the documentation-lifecycle rule (target: zero `docs/superpowers/` in-tree).

---

## Self-review notes (for the executor)

- **Field-name verifications flagged inline** (must confirm against the codebase before implementing, not assume): `active_map_id` on MowerState (Item 2 Step 8), the mowing-zone list attribute on the parsed map object (Item 2 Step 8), `cs.settings.by_map_id_canonical` carries `steeringMode` (Item 4 — confirmed structurally identical to `mowingDirectionMode`), `set_pre` short-array behaviour (Item 4 Step 4), `pre_settings_optimistic_write` optional state-field overlay (Item 4 Step 7), the exact `_fire_rain_delay_started_if_edge` call site + in-scope variable names (Item 3 Step 10).
- **Order rationale:** Items 1 & 6 first (pure tables, lowest risk, and 6's inventory edit satisfies the confidence gate). Then 3 (event), 2 (sensor — depends on the `multi_field` mechanism), 4 (select), 5 (button). Each commits independently.
- **No item depends on another's code** — safe to reorder if a subagent prefers, except keep Item 6's inventory edit before touching `error_codes.py`.
