# Localized error display (P1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sensor.dreame_a2_mower_error` (and the other `describe_error` consumers) show the authoritative app wording in the user's HA language, sourced from the P0 catalog; retire the hand-curated `ERROR_CODE_DESCRIPTIONS`.

**Architecture:** `describe_error(code, lang="en")` becomes a thin catalog lookup over `mower/fault_catalog.py`. The error sensor resolves `resolve_lang(hass.config.language)` and localizes its value + adds detail/fault_name/category attributes. The device-sync fault banner localizes too. `ERROR_CODE_DESCRIPTIONS` is deleted; the confidence gate drops it but keeps gating `S2P2_EVENT_TYPES`.

**Tech Stack:** Python (HA custom component); vanilla-pytest venv at `/data/claude/homeassistant/.venv-vanilla/bin/python`.

**Test command:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -q`. System python3 broken. Stage by EXPLICIT path; never `git add -A` (untracked `tools/probes/oss_*` are NOT ours).

**P0 carry-forward:** `fault_catalog.fault_text(code, lang)` does NOT resolve the language; callers do `lang = fault_catalog.resolve_lang(hass.config.language)` first. Default `lang="en"`. The diagnostic-sensor descriptor's `extra_state_attributes_fn(coord)` is already wired (device.py:1197) — use it.

---

### Task 1: `describe_error` → catalog-backed; retire `ERROR_CODE_DESCRIPTIONS`

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/error_codes.py`
- Modify: `tests/mower/test_error_codes.py`
- Modify: `tests/inventory/test_error_codes_confidence_gate.py`

- [ ] **Step 1: Write/adjust the failing tests**

In `tests/mower/test_error_codes.py`: read the file first. Change the import line that pulls `describe_error, ERROR_CODE_DESCRIPTIONS, S2P2_EVENT_TYPES` to drop `ERROR_CODE_DESCRIPTIONS` and add a `fault_catalog` import; then make these edits:
- The assertion `assert describe_error(24) == ERROR_CODE_DESCRIPTIONS[24]` → 
  ```python
  from custom_components.dreame_a2_mower.mower import fault_catalog as _fc
  assert describe_error(24) == _fc.fault_text(24, "en")
  ```
- Keep the unknown-code test but pin it: `assert describe_error(9999) == "Unknown error 9999"`.
- The assertion `assert ERROR_CODE_DESCRIPTIONS[72] == "Task paused for too long. ..."` →
  ```python
  assert describe_error(72, "en") == _fc.fault_text(72, "en")
  assert describe_error(72, "nb") != describe_error(72, "en")  # localizes
  ```
- Leave the `S2P2_EVENT_TYPES[72]` / `[71]` assertions unchanged.
- Read the rest of the file for ANY other `ERROR_CODE_DESCRIPTIONS` reference and convert it to a `_fc.fault_text(code, "en")` comparison.

Add a new explicit localization test:
```python
def test_describe_error_localizes_and_falls_back():
    from custom_components.dreame_a2_mower.mower.error_codes import describe_error
    from custom_components.dreame_a2_mower.mower import fault_catalog as fc
    assert describe_error(27, "en") == fc.fault_text(27, "en")
    assert describe_error(27, "nb") == fc.fault_text(27, "nb")
    assert describe_error(27, "nb") != describe_error(27, "en")
    assert describe_error(123456) == "Unknown error 123456"
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_error_codes.py -q`
Expected: FAIL — `ERROR_CODE_DESCRIPTIONS` import/usage broken OR the new test fails (describe_error not yet catalog-backed / no `lang` param).

- [ ] **Step 3: Rewrite `describe_error` + delete the dict**

In `mower/error_codes.py`:
1. Add the import (top, after `from __future__ import annotations`):
   ```python
   from . import fault_catalog
   ```
2. DELETE the entire `ERROR_CODE_DESCRIPTIONS: dict[int, str] = { ... }` assignment (the whole dict literal). Also trim the now-stale comment block immediately above it that describes the dict (the lines explaining "Confirmed entries... lifted from legacy DreameMowerErrorCode enum...").
3. Replace `describe_error` with:
   ```python
   def describe_error(code: int, lang: str = "en") -> str:
       """Authoritative localized fault text for an s2p2 (iot) code, or a fallback.

       Sourced from the bundled app catalog (mower/fault_catalog.py,
       [apk:g2408-plugin-ext1423]). Returns "Unknown error N" for codes absent
       from the catalog (which also surface via the [PROTOCOL_NOVEL] /
       unknown_s2p2 paths). `lang` must be a resolved catalog language — callers
       resolve via fault_catalog.resolve_lang(hass.config.language); defaults to
       English.
       """
       return fault_catalog.fault_text(int(code), lang) or f"Unknown error {code}"
   ```
4. Keep `S2P2_EVENT_TYPES`, `FAULT_CODES`, and everything else.

- [ ] **Step 4: Update the confidence gate**

In `tests/inventory/test_error_codes_confidence_gate.py`, change the loop
`for var in ("ERROR_CODE_DESCRIPTIONS", "S2P2_EVENT_TYPES"):` to:
```python
    for var in ("S2P2_EVENT_TYPES",):
```
and update the module docstring's first sentence to: "every s2p2 code that
`error_codes.py` maps to an event-type slug (`S2P2_EVENT_TYPES`) must be backed
by an inventory state_codes row with decoded ∈ {confirmed, partial}." (The
display strings are now sourced from the authoritative app catalog, not gated here.)

- [ ] **Step 5: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_error_codes.py tests/inventory/test_error_codes_confidence_gate.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/error_codes.py tests/mower/test_error_codes.py tests/inventory/test_error_codes_confidence_gate.py
git commit -m "feat(faults): describe_error catalog-backed (localized); retire ERROR_CODE_DESCRIPTIONS"
```

---

### Task 2: Error sensor localized value + attributes

**Files:**
- Modify: `custom_components/dreame_a2_mower/entities/sensor/device.py`
- Test: `tests/integration/test_error_sensor_localized.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_error_sensor_localized.py`:

```python
from types import SimpleNamespace

from custom_components.dreame_a2_mower.entities.sensor.device import (
    _active_fault_text, _error_attrs,
)
from custom_components.dreame_a2_mower.mower import fault_catalog as fc


def _coord(language, errors):
    return SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(language=language)),
        state_machine=SimpleNamespace(snapshot=lambda: SimpleNamespace(errors=set(errors))),
    )


def test_active_fault_text_localizes_by_hass_language():
    c = _coord("nb", {27})
    assert _active_fault_text(c.state_machine.snapshot(), c) == fc.fault_text(27, "nb")


def test_active_fault_text_no_coord_is_english():
    snap = SimpleNamespace(errors={27})
    assert _active_fault_text(snap) == fc.fault_text(27, "en")


def test_active_fault_text_none_when_no_errors():
    assert _active_fault_text(SimpleNamespace(errors=set()), _coord("nb", set())) is None


def test_error_attrs_detail_names_categories():
    c = _coord("en", {27, 4})
    a = _error_attrs(c)
    assert "FAULT_HUMAN_DETECTED" in a["fault_names"]
    assert "FAULT" in a["categories"]
    assert a["error_detail"]  # joined localized detail text


def test_error_attrs_empty_when_no_errors():
    assert _error_attrs(_coord("en", set())) == {}
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_error_sensor_localized.py -q`
Expected: FAIL — `_error_attrs` undefined / `_active_fault_text` takes 1 arg.

- [ ] **Step 3: Add the lang helper + rewrite `_active_fault_text` + add `_error_attrs`**

In `entities/sensor/device.py`, ensure `fault_catalog` is imported (near the
`from ...mower.error_codes import describe_error` line, add):
```python
from ...mower import fault_catalog
```
Replace `_active_fault_text` (lines ~69-82) and add the helpers:

```python
def _coord_lang(coord) -> str:
    """Resolved catalog language from a coordinator's HA config (defensive)."""
    hass = getattr(coord, "hass", None)
    cfg = getattr(hass, "config", None)
    return fault_catalog.resolve_lang(getattr(cfg, "language", None))


def _active_fault_text(snapshot, coord=None) -> str | None:
    """Localized human text for the currently-latched fault(s), or None.

    Reads snapshot.errors (the latched fault set, not the raw s2p2). Prefers the
    user's HA language via coord.hass.config.language; falls back to English when
    no coord is supplied (audit eval-path). Multiple faults joined with '; '.
    """
    errors = getattr(snapshot, "errors", None)
    if not errors:
        return None
    lang = _coord_lang(coord) if coord is not None else "en"
    return "; ".join(describe_error(c, lang) for c in sorted(errors))


def _error_attrs(coord) -> dict:
    """Localized detail + language-neutral fault_names/categories for the latched
    faults. Empty dict when there are no faults."""
    snap = coord.state_machine.snapshot()
    errors = getattr(snap, "errors", None)
    if not errors:
        return {}
    lang = _coord_lang(coord)
    codes = sorted(errors)
    details = [d for d in (fault_catalog.fault_detail(c, lang) for c in codes) if d]
    names = [n for n in (fault_catalog.fault_name(c) for c in codes) if n]
    cats = sorted({c2 for c2 in (fault_catalog.fault_category(c) for c in codes) if c2})
    out: dict = {}
    if details:
        out["error_detail"] = "; ".join(details)
    if names:
        out["fault_names"] = names
    if cats:
        out["categories"] = cats
    return out
```

- [ ] **Step 4: Wire the error sensor descriptor**

Find the `key="error_description"` `DreameA2DiagnosticSensorEntityDescription`
(~line 670) and change it to pass `coord` + add the attributes fn:
```python
    DreameA2DiagnosticSensorEntityDescription(
        key="error_description",
        name="Error",
        availability_source="mqtt",
        value_fn=lambda coord: _active_fault_text(coord.state_machine.snapshot(), coord),
        extra_state_attributes_fn=lambda coord: _error_attrs(coord),
    ),
```

- [ ] **Step 5: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_error_sensor_localized.py -q`
Expected: PASS.

- [ ] **Step 6: Run pre-existing error-sensor tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q -k "error or fault or fake_coord" 2>&1 | tail -25`
Expected: PASS. `_describe_error_or_none` is unchanged (still `describe_error(code)` default-en), so `tests/audit/test_fake_coord.py` stays green. If a pre-existing test asserted the OLD English fault string for the error sensor, update it to `fc.fault_text(code, "en")`.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/entities/sensor/device.py tests/integration/test_error_sensor_localized.py
git commit -m "feat(faults): error sensor localizes by HA language + detail/name/category attrs"
```

---

### Task 3: Localize the device-sync fault banner

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_device_sync.py` (the fault_detected/cleared loop, ~lines 342-354)
- Test: covered by the full suite (Task 4); the change is mechanical.

- [ ] **Step 1: Localize the banner**

In `coordinator/_device_sync.py`, in the method firing `fault_detected` /
`fault_cleared` events, change the local import + the two `describe_error(int(code))`
calls to pass a resolved language:

```python
        from ..mower.error_codes import describe_error
        from ..mower import fault_catalog
        lang = fault_catalog.resolve_lang(
            getattr(getattr(self, "hass", None) and self.hass.config, "language", None)
        )
        for code in sorted(new_errors - prev_errors):
            self._fire_lifecycle(
                EVENT_TYPE_FAULT_DETECTED,
                {"code": int(code), "description": describe_error(int(code), lang),
                 "at_unix": int(now_unix)},
            )
        for code in sorted(prev_errors - new_errors):
            self._fire_lifecycle(
                EVENT_TYPE_FAULT_CLEARED,
                {"code": int(code), "description": describe_error(int(code), lang),
                 "at_unix": int(now_unix)},
            )
```
(The `getattr(... and self.hass.config, ...)` guard yields `"en"` if `hass` is
absent in a test fake.)

- [ ] **Step 2: Run the device-sync tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q -k "device_sync or lifecycle or fault" 2>&1 | tail -25`
Expected: PASS. If a device_sync test asserts the event's `description` equals the OLD English fault string, update it to `fc.fault_text(code, "en")` (the catalog wording).

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_device_sync.py
# include any device_sync test file you had to update
git commit -m "feat(faults): localize device-sync fault banner via HA language"
```

---

### Task 4: Full suite + release + live-verify

- [ ] **Step 1: Run the FULL suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q --ignore=tests/archive`
Expected: all pass (~2526 baseline + new tests). Fix any failure caused by this feature:
- A test asserting an old `describe_error` / error-sensor / fault-event English string → update to `fault_catalog.fault_text(code, "en")`.
- Any lingering `ERROR_CODE_DESCRIPTIONS` reference → remove/convert.
- An entity-inventory consistency test for the error sensor (it gained attributes) → if `tests/audit/*` or an entity-inventory coverage gate goes red, update the error-sensor entry (state machine audit: the error sensor isn't new, but attributes changed — add the attribute-surfaced fields if a gate requires).

- [ ] **Step 2: Update entity-inventory + (if needed) state-machine audit expectations**

Update `custom_components/dreame_a2_mower/entity-inventory.yaml`'s `error_description`
sensor entry: read source is now the localized app catalog
(`fault_catalog.fault_text` via `hass.config.language`) with static fallback
removed; new attributes `error_detail`/`fault_names`/`categories`. Add a
`verifications:` row dated 2026-06-18, status `presumed`. If the state-machine
audit (`tools/state_machine/state_machine_audit_expectations.yaml`) flags the
error sensor's new attribute surface, add the rows it asks for (per the recurring
gotcha: attribute-only fields need `_KNOWN_ATTRIBUTE_SURFACED_FIELDS` / audit rows).
Re-run the full suite until green.

- [ ] **Step 3: Commit docs**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml
# + any audit-expectations yaml you had to touch
git commit -m "docs(faults): entity-inventory for localized error sensor"
```

- [ ] **Step 4: Release + live-verify (controller does this; not a subagent step)**

Push; move untracked `tools/probes/oss_*` aside for a clean tree;
`tools/release/release.sh --notes "..."`; restore probes; install via HACS;
restart HA. Then verify on live HA:
1. `sensor.dreame_a2_mower_error` (when a fault is/was latched) shows the
   authoritative app wording in the HA UI language (Norwegian on this box).
2. Attributes `error_detail` / `fault_names` / `categories` are populated.
3. The displayed text changed from the old curated string to the catalog one
   (e.g. a hanging/lift fault reads the app wording).

---

## Notes / gotchas
- Test interpreter: `/data/claude/homeassistant/.venv-vanilla/bin/python`. Stage by explicit path; leave untracked `tools/probes/oss_*` alone.
- `describe_error(code, lang="en")` — the added `lang` is defaulted, so callers passing only `code` (e.g. `_describe_error_or_none`) keep working in English.
- The catalog deliberately CHANGES some displayed meanings to the authoritative app wording (confirmed acceptable) — update string-literal test assertions to compare against `fault_catalog.fault_text(...)`, not to re-pin old literals.
- This is the first user-visible phase → it releases (P0 ships out with it).
