# Tier-derived device-trigger exposure (P3c) — design

**Date:** 2026-06-19 · **Status:** approved, pre-implementation
**Program:** `2026-06-18-fault-catalog-program-overview.md`. Builds on P0–P3b.

## Goal
Replace the hand-curated 18-code `_EXPOSED_NOTIFICATION_EVENT_TYPES` with a set
**derived from tier**: every notification slug whose tier is error / attention /
alert is exposed as an HA device-trigger; **info is excluded** (lifecycle-ish,
overlaps the existing lifecycle triggers). Expand + unify the trigger UI labels to
cover the derived set.

## Exposure policy (decided)
Exposed = notification slugs with `fault_tier(code) ∈ {error, attention, alert}`.
Counts: error 26 + attention 8 + alert 11 = **43 distinct** slugs (two slugs —
`battery_overheat` 11/42, `battery_temp_low` 43/59 — collide across error/alert;
both are non-info so exposed once). Info (24) excluded. The supplement code 47
(`task_cancelled`) has no catalog tier → not exposed (consistent with "derive from
tier"). The 12 `LIFECYCLE_EVENT_TYPES` triggers are unchanged. Total device-trigger
types: 12 + 43 = 55.

## Components

### A. `triggerable_notification_slugs()` — `mower/error_codes.py` (pure)
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
(`fault_catalog` is already imported in `error_codes.py`.)

### B. Derive `_EXPOSED_NOTIFICATION_EVENT_TYPES` — `device_trigger.py`
Replace the hand tuple (~lines 74-93) with:
```python
from .mower.error_codes import triggerable_notification_slugs
...
# Notification slugs exposed as device-triggers — DERIVED from tier
# (error/attention/alert; info excluded). No hand-curated list. See
# error_codes.triggerable_notification_slugs.
_EXPOSED_NOTIFICATION_EVENT_TYPES: tuple[str, ...] = triggerable_notification_slugs()
```
`TRIGGER_TYPES = (*LIFECYCLE_EVENT_TYPES, *_EXPOSED_NOTIFICATION_EVENT_TYPES)` is
unchanged (now 55). Update the module docstring (~lines 16-24) to describe the
tier rule instead of "curated 18". `_source_entity_id_for_type` already routes by
`trigger_type in LIFECYCLE_EVENT_TYPES` — lifecycle and notification slug sets are
disjoint (verify in tests), so the mapping stays unambiguous.

### C. Expand + unify the trigger UI labels — `strings.json` + `translations/en.json`
The `device_automation.trigger_type` block currently has 30 keys (12 lifecycle +
18 notification). It must cover all 55 (12 lifecycle + 43 notification). Source the
notification labels from the **notification event_type labels** already authored in
P3a/P3b at `entity.event.notification.state_attributes.event_type.state` — i.e. for
every exposed notification slug, set `device_automation.trigger_type[slug]` equal to
`entity.event.notification.state_attributes.event_type.state[slug]`. This both adds
the ~25 missing labels and **unifies the wording** (the prior 18 trigger labels
drifted from the event_type wording — e.g. `trapped` was "Mower trapped" vs event
"Stuck — needs assistance"; unify to the event_type string). Lifecycle trigger
labels (12) are unchanged. Apply identically to both files.

### D. Guard tests — `tests/integration/test_device_trigger.py`
- **derivation:** `_EXPOSED_NOTIFICATION_EVENT_TYPES == triggerable_notification_slugs()`;
  every exposed slug has `fault_tier ∈ {error,attention,alert}` for at least one of
  its codes; no exposed slug is purely info; every error/attention/alert catalog
  slug IS exposed (count == 43).
- **disjoint:** `set(_EXPOSED_NOTIFICATION_EVENT_TYPES) & set(LIFECYCLE_EVENT_TYPES) == ∅`.
- **label coverage (existing guard, now 55):** every `TRIGGER_TYPE` has a
  `device_automation.trigger_type` label in BOTH files (the P3a
  `test_every_trigger_type_has_a_label_in_both_files` already enforces this — it
  will fail until the labels are added).
- **label consistency:** for every exposed notification slug, the
  `device_automation.trigger_type` label == the notification `event_type.state`
  label, in both files (pins single-source wording, prevents future drift).
- **no stale:** no old-curation-only slug remains as a trigger_type key that isn't
  in TRIGGER_TYPES (the P3a `test_no_stale_old_trigger_slugs_remain` guard + a new
  assertion that trigger_type keys ⊆ TRIGGER_TYPES).

## Out of scope (later)
- Heartbeat (s1p1) channel — **P4**.
- Per-tier action richness (actionable notifications, suggested fixes in the
  trigger) — user automations.

## Testing
Pure derivation tests on `triggerable_notification_slugs()` (no HA) +
device-trigger/translation guard tests. Full suite green. The label expansion is
TDD-driven: deriving `_EXPOSED` to 43 makes the existing coverage guard fail until
the labels are added.

## Verification (live, after release)
Integration loads clean; the automation editor's device-trigger picker for the
mower lists the 43 fault/attention/alert triggers (e.g. "Stuck — needs assistance",
"Blades worn", "Failed to return to station") with friendly labels, plus the 12
lifecycle triggers; info codes are absent.
