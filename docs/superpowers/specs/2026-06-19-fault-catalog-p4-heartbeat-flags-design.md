# Heartbeat (s1p1) flag enrichment (P4, reframed) — design

**Date:** 2026-06-19 · **Status:** approved, pre-implementation
**Program:** `2026-06-18-fault-catalog-program-overview.md`. Final phase. Builds on P0–P3.

## Reframing (the original premise was wrong)
The program's P4 was "apply the catalog treatment to the 45 heartbeat codes."
**Wire reality (verified):** the catalog's `heartbeat` channel is a 100%-subset of
the iot codes (identical `fault_name`s) that **never fires as numeric codes on
g2408**. s1p1 is a 20-byte blob of **boolean status flags**; the probe corpus has
**93,888 s1p1 samples**, all flag blobs, zero numeric heartbeat codes. So the real
s1p1 "faults" are the flags, and the 45 numeric codes are a non-firing app artifact.

P4 therefore: (1) **enrich the code-mapped s1p1 flag binary_sensors** with the
catalog's localized text/tier/detail (the same quality s2p2 faults get); (2)
**document** the 45 numeric heartbeat codes as a verified non-firing artifact; (3)
ensure **entity-inventory** coverage.

## The s1p1 flags → catalog code map
From `protocol/heartbeat.py` / `_apply_s1p1_heartbeat` (`MowerState` flags), and the
catalog (iot channel — same fault_names as heartbeat):

| flag (binary_sensor) | iot code | fault_name | tier | s2p2 mirror? |
|---|---|---|---|---|
| `bumper` | 9 | FAULT_CRASH_PLATE | error | **NO** (`heartbeat.py:22` "NOT mirrored to s2p2") — sole signal |
| `drop_tilt` | 1 | FAULT_TILTED | error | likely yes |
| `lift` | 0 | FAULT_HANGING | error | likely yes |
| `battery_temp_low` | 43 | ALERT_BATTERY_TEMP_LOW | alert | likely yes |
| `emergency_stop` | 23 | FAULT_EMERGENCY_STOP | error | yes (+ P3b PIN notice) |
| `safety_alert_active` | — | (no code; transient UI marker) | — | — |

`safety_alert_active` has no catalog code → **not enriched** (stays a bare
binary_sensor). The other five are code-mapped and get catalog attributes.

## Components

### A. Flag→code mapping + catalog attributes — `binary_sensor.py`
Add a module constant:
```python
# s1p1 heartbeat flags that map to a catalog fault concept (iot channel — the
# heartbeat catalog channel is a non-firing artifact, so we read iot text/tier).
# safety_alert_active has no catalog code and is intentionally absent.
_S1P1_FLAG_FAULT_CODE: dict[str, int] = {
    "bumper": 9,            # FAULT_CRASH_PLATE  (sole signal — not mirrored to s2p2)
    "drop_tilt": 1,         # FAULT_TILTED
    "lift": 0,              # FAULT_HANGING
    "battery_temp_low": 43, # ALERT_BATTERY_TEMP_LOW (charging-paused condition)
    "emergency_stop": 23,   # FAULT_EMERGENCY_STOP (also has the P3b PIN notice)
}
```
Add an `extra_state_attributes_fn` to those five binary_sensor descriptions that
returns the localized catalog context for the mapped code:
```python
def _flag_fault_attrs(coord, code: int) -> dict[str, Any]:
    from .mower import fault_catalog
    lang = fault_catalog.resolve_lang(getattr(getattr(coord, "hass", None), "config", None)
                                      and coord.hass.config.language)
    return {
        "fault_text": fault_catalog.fault_text(code, lang),
        "tier": fault_catalog.fault_tier(code),
        "fault_detail": fault_catalog.fault_detail(code, lang),
        "fault_code": code,
    }
```
Wire each of the five descriptions with
`extra_state_attributes_fn=lambda coord, c=<code>: _flag_fault_attrs(coord, c)` (bind
the code per description). Drop None-valued keys if the description base doesn't
already (match the existing binary_sensor attribute convention — check whether the
platform's attribute handler tolerates None; if not, filter). These attributes are
constant per sensor (they annotate what the flag means + how to fix it + its tier),
present regardless of on/off — analogous to how the Error sensor exposes
`error_detail`/`fault_names`.

> Implementation note: confirm `DreameA2BinarySensorEntityDescription` supports an
> `extra_state_attributes_fn` (the sensor platform's descriptor does — P1). If the
> binary_sensor descriptor lacks the field, add it to the descriptor dataclass +
> wire it in the entity's `extra_state_attributes` property (mirror the sensor
> platform). Keep that plumbing minimal.

### B. Document the non-firing heartbeat codes — inventory + knowledge-gaps
- `inventory.yaml § s1p1`: add a 2026-06-19 `verified` note — the catalog `heartbeat`
  channel (45 codes) is a non-firing app artifact: a subset of the iot fault_names
  that never appears as numeric codes on g2408 s1p1 (which carries a 20-byte boolean
  flag blob; 93,888 corpus samples, zero numeric codes). The real s1p1 faults are the
  decoded flags; their catalog-quality text/tier is now surfaced via the flag→iot-code
  map on the binary_sensors `[apk:g2408-plugin-ext1423]`.
- `docs/research/knowledge-gaps.md`: record the heartbeat-channel disposition (closed:
  non-firing artifact, not a gap to chase).

### C. entity-inventory coverage
Verify the six s1p1 binary_sensors (`bumper`, `drop_tilt`, `lift`, `emergency_stop`,
`battery_temp_low`, `safety_alert_active`) are present in `entity-inventory.yaml`; add
any missing rows (the platform file is touched, so the inventory-touch-gate applies).
Record the new `fault_text`/`tier`/`fault_detail`/`fault_code` attributes on the five
enriched sensors. If adding attributes trips `state_machine_audit` expectations, add
the required rows (per the recurring gotcha — verify against a clean run, don't assume).

## Out of scope
- Persistent notices for the flags (they're transient; emergency-stop keeps its
  dedicated notice). 
- `safety_alert_active` catalog mapping (no code; intentional).
- Any decode of numeric heartbeat codes on s1p1 (they don't fire).

## Testing
- `_flag_fault_attrs`: for code 9 returns `fault_text` containing the catalog text,
  `tier == "error"`, non-empty `fault_detail`, `fault_code == 9`; localized (nb≠en for
  a code that differs).
- mapping: `_S1P1_FLAG_FAULT_CODE` has the five flags with the right codes; tiers via
  `fault_catalog.fault_tier` match the table (9/1/0/23 → error, 43 → alert).
- each enriched binary_sensor description exposes the attributes for its flag's code;
  `safety_alert_active` has NO fault attributes.
- a guard test: every key in `_S1P1_FLAG_FAULT_CODE` is a real `MowerState`
  flag/binary_sensor and a real catalog code (`fault_tier` not None).
- Full suite green (incl. entity-inventory + state_machine_audit gates).

## Verification (live, after release)
Integration loads clean; `binary_sensor.dreame_a2_mower_bumper` (and the other four)
carry `fault_text` / `tier` / `fault_detail` attributes with the localized catalog
text. The heartbeat-channel disposition is documented; no numeric heartbeat codes are
surfaced (none fire).
