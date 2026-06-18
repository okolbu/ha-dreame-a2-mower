# Catalog-driven event layer (P3a) — design

**Date:** 2026-06-18 · **Status:** approved, pre-implementation
**Program:** `2026-06-18-fault-catalog-program-overview.md`. Builds on P0–P2.

## Goal
Make the s2p2 notification-event layer **catalog-driven**: derive the event slug
per code from the authoritative `fault_name` (fixing the wrong hand-rolled slugs
and covering all codes), carry the **tier**/category/severity into the event
payload, and **derive the four lockstep lists from the catalog** so they stop
drifting. App-faithful slugs (no friendly overrides — per decision).

## Today's four hand-maintained lists (the drift problem)
- `error_codes.py:S2P2_EVENT_TYPES` (27 code→slug; several wrong, e.g. 31).
- `const.py:NOTIFICATION_EVENT_TYPES` ("keep in lockstep with S2P2_EVENT_TYPES.values()").
- `logbook.py:_NOTIFICATION_MESSAGES` (per-slug fallback text).
- `device_trigger.py:_EXPOSED_NOTIFICATION_EVENT_TYPES` (18 curated slugs).
After P3a, all four derive from the catalog (+ a tiny explicit supplement).

## Components

### A. `event_slug` — `mower/fault_catalog.py` (pure)
```python
def event_slug(code: int, channel: str = "iot") -> str | None:
    """HA event_type slug for a code: the fault_name minus its tier prefix,
    lowercased (FAULT_HUMAN_DETECTED -> "human_detected",
    ALERT_BACK_CHARGE_FAILED -> "back_charge_failed"). None if not in catalog."""
    fn = fault_name(code, channel)
    if not fn:
        return None
    for p in ("FAULT_", "ALERT_", "INFO_"):
        if fn.startswith(p):
            return fn[len(p):].lower()
    return fn.lower()
```

### B. `S2P2_EVENT_TYPES` computed from the catalog — `mower/error_codes.py`
Replace the hand dict with a computed mapping over the iot catalog, plus an
explicit `_SLUG_SUPPLEMENT` for codes seen on g2408 wire but absent from the
catalog:
```python
# Codes observed on the g2408 wire that the app catalog doesn't classify.
_SLUG_SUPPLEMENT: dict[int, str] = {47: "task_cancelled"}

S2P2_EVENT_TYPES: dict[int, str] = {
    **{c: fault_catalog.event_slug(c) for c in sorted(fault_catalog.known_codes("iot"))
       if fault_catalog.event_slug(c)},
    **_SLUG_SUPPLEMENT,
}
```
This expands coverage from 27 → 69 catalog codes (every catalog code has a
`fault_name` → slug) + the `47` supplement = 70 mapped codes, correcting the wrong
slugs. `S2P2_UNKNOWN_EVENT_TYPE` stays.

**Slug collisions (intentional, two pairs).** Stripping the prefix makes two
FAULT/ALERT variant-pairs of the same physical condition share a slug:
`battery_overheat` ← 11 (`FAULT_BATTERY_OVERHEAT`, error tier) + 42
(`ALERT_BATTERY_OVERHEAT`, alert tier); `battery_temp_low` ← 43
(`ALERT_BATTERY_TEMP_LOW`, alert tier) + 59 (`FAULT_BATTERY_TEMP_LOW`, error tier).
This is fine and kept: the slug is a *grouping* `event_type`; the per-fire payload
carries the distinguishing `code` + `tier`, and per-tier surfacing (P3b) keys off
that payload `tier`, never the slug. So a shared slug still routes its FAULT fire
to a persistent notice and its ALERT fire to a transient one. Consequences the code
must respect: `S2P2_EVENT_TYPES` has 70 keys but ~68 distinct values — **no consumer
may reverse-map slug→code**, and tests must NOT assert value-uniqueness. (No current
consumer reverse-maps: the resolver is forward code→slug; the logbook reads payload
`text`+`code`; device-triggers map trigger-type→entity.)

### C. `NOTIFICATION_EVENT_TYPES` derived — `mower/error_codes.py`
Define it next to `S2P2_EVENT_TYPES` (catalog-authoritative home) and remove the
hand literal from `const.py`:
```python
NOTIFICATION_EVENT_TYPES: tuple[str, ...] = tuple(
    sorted(set(S2P2_EVENT_TYPES.values())) + [S2P2_UNKNOWN_EVENT_TYPE]
)
```
`const.py` re-exports it: `from .mower.error_codes import NOTIFICATION_EVENT_TYPES`
(verify no import cycle — `error_codes` must NOT import `const`; if it does for an
`EVENT_TYPE_*` constant, move the re-export to the consumers instead). `event.py`
+ `device_trigger.py` keep importing `NOTIFICATION_EVENT_TYPES` unchanged.

### D. tier/category/severity on the notification payload — `coordinator/_device_sync.py`
In `_fire_notification`, enrich the payload from the catalog:
```python
        payload = {
            "text": text, "code": code, "siid": siid, "piid": piid,
            "send_time": send_time, "message_id": message_id, "source": "cloud",
            "tier": fault_catalog.fault_tier(code),
            "category": fault_catalog.fault_category(code),
            "severity": fault_catalog.fault_severity(code),
        }
```
(import `from ..mower import fault_catalog`). The entity's `trigger` already drops
None-valued keys, so unknown codes (tier None) simply omit those keys.

### E. logbook fallback from the catalog — `logbook.py` + `coordinator/_notifications.py`
- In `_resolve_s2p2_notification`, when the cloud push has no English text, fall
  back to the catalog: `text = _english_text(matching) or fault_catalog.fault_text(value, "en") or ""`.
  (Keep the existing account-language behavior; "en" is the stable default the
  payload already uses.) So the event payload's `text` is populated for any
  catalog code even if the cloud text is briefly missing.
- DELETE `logbook.py:_NOTIFICATION_MESSAGES`. The notification `_format` keeps
  preferring payload `text`; its final fallback becomes `event_type.replace("_"," ")`
  (already the last resort) for the rare no-text `unknown_s2p2`.

### F. device-trigger slugs — `device_trigger.py`
`_EXPOSED_NOTIFICATION_EVENT_TYPES` lists OLD slugs that change under B. Update it
to the SAME 18 curated codes' NEW slugs (mechanical rename so triggers keep working).
The exact new vocabulary (verified via `event_slug`):

| code | old slug | new slug |
|---|---|---|
| 27 | human_detected | `human_detected` |
| 2 | robot_trapped | `trapped` |
| 23 | emergency_stop | `emergency_stop` |
| 28 | blades_worn | `blade_loss` |
| 4 | left_wheel_error | `left_wheel` |
| 5 | right_wheel_error | `right_wheel` |
| 0 | hanging | `hanging` |
| 31 | positioning_failed_stuck | `back_charge_failed` |
| 33 | positioning_failed_transient | `locating_failed_with_map` |
| 36 | failed_to_start_task | `task_start_failed` |
| 43 | battery_temp_low_charging_paused | `battery_temp_low` |
| 54 | low_battery_return | `battery_low_returning` |
| 56 | rain_protection | `bad_weather_protecting` |
| 71 | standby_outside_station_too_long | `idle_timeout_returning` |
| 72 | paused_too_long_returning | `pause_timeout_returning` |
| 73 | top_cover_open | `top_cover_open` |
| 75 | arrived_at_maintenance_point | `go_to_cleanpoint_success` |
| 76 | cannot_reach_maintenance_point | `go_to_cleanpoint_failed` |

List them explicitly with an inline `# <code>` comment. (The full **tier-driven**
exposure rule is P3c — P3a only keeps the existing curated set valid under the new
vocabulary.) Also update the module docstring's "28 NOTIFICATION_EVENT_TYPES" /
"11+18" counts to the derived numbers.

### G. confidence gate → slug-integrity — `tests/inventory/test_error_codes_confidence_gate.py`
The gate currently checks `S2P2_EVENT_TYPES` codes against inventory `decoded`
status. Slugs are now catalog-derived (authoritative), so replace that check with:
**every code in `S2P2_EVENT_TYPES` must be in the catalog (`fault_catalog.known_codes("iot")`)
OR in `_SLUG_SUPPLEMENT`**, and every slug equals `event_slug(code)` or its
supplement value. This guards the derivation integrity without the inventory
coupling. Update the docstring.

### H. inventory + docs
Record (inventory.yaml § s2p2): event slugs are now derived from the app catalog
`fault_name` `[apk:g2408-plugin-ext1423]`; the prior hand-curated slug table (and
its wrong entries, e.g. 31 `positioning_failed_stuck`) is retired — archive the
superseded slug claims per the retraction rule. Update `docs/events.md` if it
enumerates the old slugs.

## Out of scope (later)
- Per-tier **persistent** surfacing (attention/error → persistent_notification with
  resident/detail; alert → transient; info → none) — **P3b**.
- **Tier-driven** device-trigger exposure (which tiers get triggers) — **P3c**.
- Heartbeat (s1p1) channel — **P4**.

## Testing
- `event_slug`: 27→"human_detected"; 31→"back_charge_failed"; 75→"go_to_cleanpoint_success";
  9999→None.
- `S2P2_EVENT_TYPES`: 31=="back_charge_failed" (corrected); 47=="task_cancelled"
  (supplement); has a slug for every iot catalog code (70 keys); every value ==
  `event_slug(code)` (or the supplement value for 47). Do NOT assert value-uniqueness
  (11/42 and 43/59 intentionally collide).
- `NOTIFICATION_EVENT_TYPES`: == `tuple(sorted(set(S2P2_EVENT_TYPES.values())) +
  ["unknown_s2p2"])`; contains "battery_overheat" exactly once; the notification
  event entity advertises them.
- payload: a fired notification for code 27 carries tier=="attention",
  category=="FAULT", severity=="work_message"; unknown code omits those keys.
- logbook: a notification bus event with no `text` but a catalog code renders the
  catalog text (via the resolver fallback) — and `_NOTIFICATION_MESSAGES` is gone.
- device_trigger: TRIGGER_TYPES contains the corrected slugs; a "human_detected"
  trigger still resolves; no stale old slug remains.
- confidence gate: green under the new slug-integrity rule; a deliberately-bad
  supplement entry (code not in catalog with a non-matching slug) would fail.
- Full suite green (event/notification/logbook/device-trigger tests reflect the
  new slugs — convert any test pinning an OLD slug literal to the catalog-derived
  value, NOT a re-pinned old literal).

## Verification (live, after release)
Integration loads clean; `event.dreame_a2_mower_notification` advertises the
catalog-derived event_types; (on the next notification) the logbook shows the
authoritative text and the payload carries `tier`. Device-trigger list in the
automation editor shows the corrected trigger names.
