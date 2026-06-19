# Tier-derived device-trigger exposure (P3c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive the exposed device-trigger notification set from tier (error/attention/alert; info excluded) instead of a hand-curated list of 18, and expand+unify the trigger UI labels to cover the derived 43.

**Architecture:** New pure `triggerable_notification_slugs()` in `mower/error_codes.py` returns the non-info notification slugs. `device_trigger.py` sets `_EXPOSED_NOTIFICATION_EVENT_TYPES = triggerable_notification_slugs()`. The `device_automation.trigger_type` labels (in `strings.json` + `translations/en.json`) are expanded to cover all exposed slugs, sourced from the existing notification `event_type.state` labels (single wording source).

**Tech Stack:** Python, Home Assistant custom integration, pytest. Test runner (from repo root): `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-19-fault-catalog-p3c-tier-device-triggers-design.md`

**Verified facts:**
- Tier counts: error 26, attention 8, alert 11, info 24. **Exposed = non-info = 43 distinct slugs.**
- The current hand-curated 18 includes **4 info-tier slugs that will be DROPPED**: `battery_low_returning` (54), `bad_weather_protecting` (56), `idle_timeout_returning` (71), `pause_timeout_returning` (72). They remain fully available as raw notification events; they're just removed from the device-trigger picker.
- `error_codes.py` already imports `from . import fault_catalog` and defines `S2P2_EVENT_TYPES`.
- `device_trigger.py`: `_EXPOSED_NOTIFICATION_EVENT_TYPES` at lines 74-93; `TRIGGER_TYPES = (*LIFECYCLE_EVENT_TYPES, *_EXPOSED_NOTIFICATION_EVENT_TYPES)` at 96-99; module docstring lines 1-42 describes the "curated 18".
- `tests/integration/test_device_trigger.py` has helpers `_trigger_labels(rel)` (reads `device_automation.trigger_type`) and `_notif_event_labels(rel)` (reads `entity.event.notification.state_attributes.event_type.state`), plus guards `test_every_trigger_type_has_a_label_in_both_files`, `test_no_stale_old_trigger_slugs_remain`, `test_exposed_triggers_use_corrected_catalog_slugs`, `test_get_triggers_returns_one_per_supported_type`.
- `LIFECYCLE_EVENT_TYPES` has 12 entries (const.py); the 12 lifecycle trigger labels stay unchanged.
- Lifecycle slug set and notification slug set are disjoint (lifecycle: mowing_*, dock_*, charging_*, rain_delay_started, fault_detected/cleared, self_shutdown; notification: catalog-derived fault slugs).

---

### Task 1: Derive `_EXPOSED` from tier + expand/unify trigger labels

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/error_codes.py` (add `triggerable_notification_slugs`)
- Modify: `custom_components/dreame_a2_mower/device_trigger.py` (derive `_EXPOSED`, docstring)
- Modify: `custom_components/dreame_a2_mower/strings.json` + `translations/en.json` (trigger_type labels)
- Test: `tests/integration/test_device_trigger.py` + `tests/mower/test_error_codes.py`

- [ ] **Step 1: Write the derivation test (pure).** Append to `tests/mower/test_error_codes.py`:
```python
def test_triggerable_notification_slugs_is_non_info():
    from custom_components.dreame_a2_mower.mower.error_codes import (
        triggerable_notification_slugs, S2P2_EVENT_TYPES,
    )
    from custom_components.dreame_a2_mower.mower import fault_catalog as fc
    slugs = triggerable_notification_slugs()
    # sorted, unique
    assert list(slugs) == sorted(set(slugs))
    # every returned slug has at least one non-info code; no purely-info slug
    for s in slugs:
        codes = [c for c, sl in S2P2_EVENT_TYPES.items() if sl == s]
        tiers = {fc.fault_tier(c) for c in codes}
        assert tiers & {"error", "attention", "alert"}, f"{s} has no non-info tier"
    # every error/attention/alert catalog slug IS present
    expected = {
        sl for c, sl in S2P2_EVENT_TYPES.items()
        if fc.fault_tier(c) in ("error", "attention", "alert")
    }
    assert set(slugs) == expected
    assert len(slugs) == 43
    # info-only slugs are excluded (these 4 were in the old curated set)
    for dropped in ("battery_low_returning", "bad_weather_protecting",
                    "idle_timeout_returning", "pause_timeout_returning"):
        assert dropped not in slugs
```

- [ ] **Step 2: Run, verify fail.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_error_codes.py -k triggerable -q`
Expected: FAIL (`triggerable_notification_slugs` not defined).

- [ ] **Step 3: Implement the pure helper.** In `mower/error_codes.py`, after `NOTIFICATION_EVENT_TYPES` (the derived tuple), add:
```python
def triggerable_notification_slugs() -> tuple[str, ...]:
    """Notification slugs worth exposing as HA device-triggers: every slug whose
    tier is error/attention/alert. Info is excluded — it's lifecycle/status that
    overlaps the LIFECYCLE_EVENT_TYPES triggers. Derived from the app catalog
    [apk:g2408-plugin-ext1423]; a slug is included if ANY of its codes is non-info
    (the two error/alert collision slugs qualify). Sorted for stable output."""
    return tuple(sorted({
        slug for code, slug in S2P2_EVENT_TYPES.items()
        if fault_catalog.fault_tier(code) in ("error", "attention", "alert")
    }))
```

- [ ] **Step 4: Run the pure test, verify pass.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_error_codes.py -k triggerable -q`
Expected: PASS.

- [ ] **Step 5: Derive `_EXPOSED` in device_trigger.py.** Replace the hand tuple (lines 74-93) with:
```python
# Notification slugs exposed as device-triggers — DERIVED from tier
# (error/attention/alert; info excluded as lifecycle-ish, overlapping the
# LIFECYCLE_EVENT_TYPES triggers). No hand-curated list; see
# error_codes.triggerable_notification_slugs.
_EXPOSED_NOTIFICATION_EVENT_TYPES: tuple[str, ...] = triggerable_notification_slugs()
```
Add the import near the other `.mower` / `.const` imports (with the const block ~line 63):
```python
from .mower.error_codes import triggerable_notification_slugs
```
Then rewrite the module docstring's "Curated exposed set" section (lines 19-41) to describe the tier rule: all 12 LIFECYCLE_EVENT_TYPES + every notification slug whose tier is error/attention/alert (info excluded), derived from the catalog — no hand-curated list. Remove the now-inaccurate omitted-and-why bullets.

- [ ] **Step 6: Expand + unify the trigger_type labels.** In BOTH `strings.json` and `translations/en.json`, the `device_automation.trigger_type` block must contain exactly: the 12 lifecycle labels (unchanged) + one label per exposed notification slug, where each notification label EQUALS that slug's label in `entity.event.notification.state_attributes.event_type.state` (same block you authored in P3a/P3b). Concretely:
  - Keep the 12 lifecycle keys (`mowing_started`, `mowing_paused`, `mowing_resumed`, `mowing_ended`, `dock_arrived`, `dock_departed`, `charging_started`, `charging_complete`, `rain_delay_started`, `fault_detected`, `fault_cleared`, `self_shutdown`) and their existing labels.
  - Remove ALL existing notification keys from `trigger_type` (including the 4 dropped info ones: `battery_low_returning`, `bad_weather_protecting`, `idle_timeout_returning`, `pause_timeout_returning`).
  - For each slug in `triggerable_notification_slugs()` (43), add `trigger_type[slug] = event_type_state[slug]` (copy the string from the same file's notification `event_type.state` block).
  Do this by reading each file's existing `event_type.state` block as the source of label strings; keep both files' `trigger_type` blocks identical. Valid JSON, UTF-8 em-dashes as-is.
  TIP: you may compute the exact mapping with the venv python to avoid manual error, e.g.:
  `/data/claude/homeassistant/.venv-vanilla/bin/python -c "import json; from custom_components.dreame_a2_mower.mower.error_codes import triggerable_notification_slugs as T; d=json.load(open('custom_components/dreame_a2_mower/translations/en.json')); st=d['entity']['event']['notification']['state_attributes']['event_type']['state']; print(json.dumps({s: st[s] for s in T()}, ensure_ascii=False, indent=2))"`
  …then splice those into both files' `trigger_type` blocks alongside the 12 lifecycle entries.

- [ ] **Step 7: Update/repair the device-trigger tests.** In `tests/integration/test_device_trigger.py`:
  - Replace `test_exposed_triggers_use_corrected_catalog_slugs` with a derivation assertion:
```python
def test_exposed_triggers_are_tier_derived():
    from custom_components.dreame_a2_mower.device_trigger import (
        _EXPOSED_NOTIFICATION_EVENT_TYPES as EXP, TRIGGER_TYPES,
    )
    from custom_components.dreame_a2_mower.mower.error_codes import (
        triggerable_notification_slugs,
    )
    from custom_components.dreame_a2_mower.const import LIFECYCLE_EVENT_TYPES
    assert set(EXP) == set(triggerable_notification_slugs())
    assert len(EXP) == 43
    # dropped info-tier slugs are no longer exposed
    for dropped in ("battery_low_returning", "bad_weather_protecting",
                    "idle_timeout_returning", "pause_timeout_returning"):
        assert dropped not in EXP
    # newly-exposed examples present
    for added in ("cutter", "tilted", "lidar_abnormal", "docking_failed", "maintain_loss"):
        assert added in EXP
    # lifecycle and notification trigger sets are disjoint
    assert set(EXP).isdisjoint(set(LIFECYCLE_EVENT_TYPES))
    assert set(EXP) <= set(TRIGGER_TYPES)


def test_trigger_type_labels_match_notification_event_labels():
    """Single wording source: each exposed notification trigger label equals the
    notification event_type.state label, in both files."""
    from custom_components.dreame_a2_mower.device_trigger import (
        _EXPOSED_NOTIFICATION_EVENT_TYPES as EXP,
    )
    for rel in ("strings.json", "translations/en.json"):
        tt = _trigger_labels(rel)
        st = _notif_event_labels(rel)
        for slug in EXP:
            assert tt.get(slug) == st.get(slug), (
                f"{rel}: trigger_type[{slug}]={tt.get(slug)!r} != event[{slug}]={st.get(slug)!r}"
            )


def test_trigger_type_keys_are_exactly_trigger_types():
    """No stale/extra trigger_type keys; every TRIGGER_TYPE labeled (both files)."""
    from custom_components.dreame_a2_mower.device_trigger import TRIGGER_TYPES
    for rel in ("strings.json", "translations/en.json"):
        labels = set(_trigger_labels(rel))
        assert labels == set(TRIGGER_TYPES), (
            f"{rel}: trigger_type keys {labels ^ set(TRIGGER_TYPES)} differ from TRIGGER_TYPES"
        )
```
  - `test_get_triggers_returns_one_per_supported_type` (line 254): if it pins specific slugs that changed, update it to assert it returns one trigger per `TRIGGER_TYPES` entry (count-based), not specific old slugs. Keep its device-scoping assertions.
  - The existing `test_every_trigger_type_has_a_label_in_both_files` and `test_no_stale_old_trigger_slugs_remain` should now pass (the latter checks a fixed OLD-slug set; confirm none of those reappeared). `test_notification_event_type_labels_cover_all_slugs_in_both_files` is unaffected (event_type block unchanged).

- [ ] **Step 8: Run the device-trigger + error_codes suites.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_device_trigger.py tests/mower/test_error_codes.py -q`
Expected: PASS. Fix any test still pinning an old curated slug (convert to the derived assertion). Confirm `test_trigger_type_keys_are_exactly_trigger_types` passes (proves labels added + the 4 info ones removed).

- [ ] **Step 9: Commit** (stage by explicit path; never `git add -A`; do NOT stage `tools/probes/*`):
```bash
git add custom_components/dreame_a2_mower/mower/error_codes.py custom_components/dreame_a2_mower/device_trigger.py custom_components/dreame_a2_mower/strings.json custom_components/dreame_a2_mower/translations/en.json tests/integration/test_device_trigger.py tests/mower/test_error_codes.py
git commit -m "feat(p3c): derive device-trigger exposure from tier (non-info); expand labels"
```

---

### Task 2: Inventory note, full suite, release

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`
- Regenerate: `docs/research/inventory/generated/g2408-canonical.md`

- [ ] **Step 1: Inventory note.** In `inventory.yaml § s2p2`, add a 2026-06-19 `verified` note: HA device-trigger exposure is now DERIVED from tier — every notification slug with `fault_tier ∈ {error,attention,alert}` (43 distinct) is exposed; info excluded (lifecycle-ish); the prior hand-curated 18 is retired (4 info slugs `battery_low_returning`/`bad_weather_protecting`/`idle_timeout_returning`/`pause_timeout_returning` dropped from the picker, still available as raw notification events). Trigger UI labels unified to the notification event_type labels. Source `[apk:g2408-plugin-ext1423]` via `error_codes.triggerable_notification_slugs`. Match the existing YAML shape.

- [ ] **Step 2: Validate + regenerate canonical.**
```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py
```
Inspect `git diff` on the canonical doc; exclude unrelated churn.

- [ ] **Step 3: Full suite.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: all pass (baseline ~2609 + the new P3c tests; zero failures).

- [ ] **Step 4: Commit.**
```bash
git add custom_components/dreame_a2_mower/inventory.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "docs(p3c): inventory note for tier-derived device-trigger exposure"
```

- [ ] **Step 5: Release + live-verify (controller).** The controller merges the P3c branch to main, pushes (reconciling origin if a concurrent process advanced it), runs `tools/release/release.sh 1.0.30a3`, installs via HACS + restarts HA, and verifies: integration loads clean; the automation editor's device-trigger picker lists the 43 fault/attention/alert triggers with friendly labels + the 12 lifecycle, info codes absent.

---

## Self-Review notes
- **Spec coverage:** A (helper) → T1 S1-4; B (derive `_EXPOSED`) → T1 S5; C (labels) → T1 S6; D (tests) → T1 S1,7; inventory/release → T2.
- **Suite-green per task:** T1 lands the derive AND the labels together, so the coverage guard never goes red across a commit boundary.
- **Type consistency:** `triggerable_notification_slugs() -> tuple[str,...]`; `_EXPOSED_NOTIFICATION_EVENT_TYPES: tuple[str,...]`; `TRIGGER_TYPES` wiring unchanged.
- **Dropped info slugs** (54/56/71/72) are intentional per the tier rule — flagged in T1 facts + T2 inventory note. Still available as raw notification events.
- **Label single-source:** notification trigger labels == event_type.state labels (pinned by `test_trigger_type_labels_match_notification_event_labels`), fixing prior wording drift.
