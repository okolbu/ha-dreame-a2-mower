# Catalog-driven event layer (P3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive the s2p2 notification event-slug per code from the authoritative app-catalog `fault_name`, carry tier/category/severity into the event payload, and collapse the four hand-maintained lockstep lists into catalog-derived values.

**Architecture:** New pure `event_slug(code)` in `mower/fault_catalog.py`. `mower/error_codes.py` computes `S2P2_EVENT_TYPES` (+ a tiny `_SLUG_SUPPLEMENT` for wire code 47, absent from the catalog) and defines `NOTIFICATION_EVENT_TYPES` from it. `const.py` re-exports that. The notification payload (`coordinator/_device_sync.py`) gains tier/category/severity; the resolver (`coordinator/_notifications.py`) falls back to catalog text; the logbook drops its hand table; `device_trigger.py` adopts the corrected slugs; the confidence gate flips to slug-integrity.

**Tech Stack:** Python, Home Assistant custom integration, pytest. Test runner: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest` run from repo root `/data/claude/homeassistant/ha-dreame-a2-mower`.

**Spec:** `docs/superpowers/specs/2026-06-18-fault-catalog-p3a-event-layer-design.md`

**Pure-module note:** `mower/fault_catalog.py` and `mower/error_codes.py` are layer-2 (no `homeassistant` import). `mower/__init__.py` is empty. `const.py` (HA layer) may import from `mower.error_codes`; the reverse is forbidden.

**Verified catalog facts (do not re-derive):** all 69 iot codes have a `fault_name`; code 47 is NOT in the catalog (needs the supplement); two intentional slug collisions exist — `battery_overheat` ← 11(FAULT)/42(ALERT), `battery_temp_low` ← 43(ALERT)/59(FAULT). `S2P2_EVENT_TYPES` ends with 70 keys and ~68 distinct values. NEVER reverse-map slug→code; NEVER assert value-uniqueness.

---

### Task 1: `event_slug` in fault_catalog.py

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/fault_catalog.py` (add after `fault_name`, ~line 87)
- Test: `tests/inventory/test_fault_catalog_valid.py` (append) — or `tests/mower/` if preferred; append to the existing fault_catalog test module.

- [ ] **Step 1: Write the failing test**

Append to `tests/inventory/test_fault_catalog_valid.py`:
```python
def test_event_slug_strips_prefix_and_lowercases():
    assert fc.event_slug(27) == "human_detected"   # FAULT_HUMAN_DETECTED
    assert fc.event_slug(31) == "back_charge_failed"  # ALERT_BACK_CHARGE_FAILED (was wrong)
    assert fc.event_slug(48) == "task_finish"      # INFO_TASK_FINISH
    assert fc.event_slug(75) == "go_to_cleanpoint_success"  # FAULT_GO_TO_CLEANPOINT_SUCCESS


def test_event_slug_none_for_absent_code():
    assert fc.event_slug(47) is None   # not in the catalog
    assert fc.event_slug(9999) is None


def test_event_slug_covers_every_iot_code():
    for c in fc.known_codes("iot"):
        assert fc.event_slug(c), f"code {c} has no slug"
```
(The module already does `from custom_components.dreame_a2_mower.mower import fault_catalog as fc`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_fault_catalog_valid.py -k event_slug -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'event_slug'`

- [ ] **Step 3: Write minimal implementation**

In `mower/fault_catalog.py`, after `fault_name` (~line 87):
```python
def event_slug(code: int, channel: str = "iot") -> str | None:
    """HA event_type slug for a code: the fault_name minus its tier prefix,
    lowercased (FAULT_HUMAN_DETECTED -> "human_detected",
    ALERT_BACK_CHARGE_FAILED -> "back_charge_failed"). None if the code is not
    in the catalog. Two FAULT/ALERT variant-pairs intentionally collide on one
    slug (battery_overheat: 11/42; battery_temp_low: 43/59) — callers must NOT
    reverse-map slug->code."""
    fn = fault_name(code, channel)
    if not fn:
        return None
    for p in ("FAULT_", "ALERT_", "INFO_"):
        if fn.startswith(p):
            return fn[len(p):].lower()
    return fn.lower()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_fault_catalog_valid.py -k event_slug -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/fault_catalog.py tests/inventory/test_fault_catalog_valid.py
git commit -m "feat(p3a): event_slug() — catalog fault_name -> HA event_type slug"
```

---

### Task 2: Compute `S2P2_EVENT_TYPES` + `NOTIFICATION_EVENT_TYPES` from the catalog

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/error_codes.py:52-85` (replace the hand dict; add NOTIFICATION_EVENT_TYPES)
- Test: `tests/mower/test_error_codes.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/mower/test_error_codes.py`:
```python
def test_s2p2_event_types_derived_from_catalog():
    from custom_components.dreame_a2_mower.mower.error_codes import S2P2_EVENT_TYPES
    from custom_components.dreame_a2_mower.mower import fault_catalog as fc
    # corrected slugs
    assert S2P2_EVENT_TYPES[31] == "back_charge_failed"
    assert S2P2_EVENT_TYPES[33] == "locating_failed_with_map"
    assert S2P2_EVENT_TYPES[50] == "task_start"
    # supplement for the catalog-absent wire code
    assert S2P2_EVENT_TYPES[47] == "task_cancelled"
    # every catalog code present + value matches event_slug
    for c in fc.known_codes("iot"):
        assert S2P2_EVENT_TYPES[c] == fc.event_slug(c)
    # 70 keys (69 catalog + 47), values NOT unique (11/42, 43/59 collide)
    assert len(S2P2_EVENT_TYPES) == 70
    assert S2P2_EVENT_TYPES[11] == S2P2_EVENT_TYPES[42] == "battery_overheat"
    assert S2P2_EVENT_TYPES[43] == S2P2_EVENT_TYPES[59] == "battery_temp_low"


def test_notification_event_types_derived_and_deduped():
    from custom_components.dreame_a2_mower.mower.error_codes import (
        NOTIFICATION_EVENT_TYPES, S2P2_EVENT_TYPES, S2P2_UNKNOWN_EVENT_TYPE,
    )
    assert NOTIFICATION_EVENT_TYPES == tuple(
        sorted(set(S2P2_EVENT_TYPES.values())) + [S2P2_UNKNOWN_EVENT_TYPE]
    )
    assert NOTIFICATION_EVENT_TYPES.count("battery_overheat") == 1
    assert NOTIFICATION_EVENT_TYPES[-1] == "unknown_s2p2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_error_codes.py -k "derived" -q`
Expected: FAIL (`S2P2_EVENT_TYPES[31]` is still `"positioning_failed_stuck"`; `NOTIFICATION_EVENT_TYPES` not importable from error_codes)

- [ ] **Step 3: Write minimal implementation**

In `mower/error_codes.py`, replace the entire hand dict block (current lines 38-85, from the `# ---...` comment block through `S2P2_UNKNOWN_EVENT_TYPE = "unknown_s2p2"`) with:
```python
# ---------------------------------------------------------------------------
# s2p2 notification SLUG table — keyed off s2p2 value, value = HA event_type
# slug. DERIVED from the authoritative app catalog fault_name
# [apk:g2408-plugin-ext1423] via fault_catalog.event_slug (strips the
# FAULT_/ALERT_/INFO_ prefix, lowercases), plus _SLUG_SUPPLEMENT for wire codes
# the catalog omits. This is the pure, layer-2 module so external dev tools
# (mower_tail.py, probe_a2_mqtt.py) can import it WITHOUT pulling homeassistant.
# The user-visible text per fire comes from the catalog / cloud payload — slugs
# only here.
#
# NOTE: two FAULT/ALERT variant-pairs intentionally share a slug
# (11/42 -> battery_overheat, 43/59 -> battery_temp_low). The per-fire payload
# carries the distinguishing code + tier. Do NOT reverse-map slug->code.

# Codes observed on the g2408 wire that the app catalog does NOT classify, so
# event_slug() returns None for them and they need an explicit slug here.
_SLUG_SUPPLEMENT: dict[int, str] = {
    47: "task_cancelled",  # mova [MOWER] community-confirmed; absent from the catalog
}


def _derive_iot_slugs() -> dict[int, str]:
    out: dict[int, str] = {}
    for c in sorted(fault_catalog.known_codes("iot")):
        slug = fault_catalog.event_slug(c)
        if slug:
            out[c] = slug
    out.update(_SLUG_SUPPLEMENT)
    return out


S2P2_EVENT_TYPES: dict[int, str] = _derive_iot_slugs()

# Slug fired when s2p2 carries a value not in S2P2_EVENT_TYPES — the cloud still
# provides authoritative text in the payload; the slug is generic so HA can
# register the event_type up-front.
S2P2_UNKNOWN_EVENT_TYPE = "unknown_s2p2"

# The event_types advertised by event.dreame_a2_mower_notification: the unique
# derived slugs (sorted for stability) plus the unknown sentinel. Defined here
# (catalog-authoritative home) and re-exported by const.py.
NOTIFICATION_EVENT_TYPES: tuple[str, ...] = tuple(
    sorted(set(S2P2_EVENT_TYPES.values())) + [S2P2_UNKNOWN_EVENT_TYPE]
)
```
Keep `describe_error` (above) and `is_fault` (below) unchanged.

- [ ] **Step 4: Run the new tests, then the full error_codes + fault-events modules**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_error_codes.py tests/coordinator/test_fault_events.py -q`
Expected: the two new tests PASS. **Some pre-existing tests that pin OLD slug literals will FAIL** (e.g. `tests/mower/test_error_codes.py:118/135`, `tests/coordinator/test_fault_events.py:239`). For each failure, convert the OLD slug literal to the catalog-derived value (look it up via `fault_catalog.event_slug(code)` — e.g. `mowing_started`→`task_start`, `mowing_complete`→`task_finish`, `arrived_at_maintenance_point`→`go_to_cleanpoint_success`). Do NOT re-pin a different hard-coded literal where the test could instead assert against `event_slug(code)` / `S2P2_EVENT_TYPES[code]`. Re-run until green.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/error_codes.py tests/mower/test_error_codes.py tests/coordinator/test_fault_events.py
git commit -m "feat(p3a): derive S2P2_EVENT_TYPES + NOTIFICATION_EVENT_TYPES from catalog"
```

---

### Task 3: `const.py` re-exports `NOTIFICATION_EVENT_TYPES`

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py:60-103` (remove the hand literal + its docstring; add the re-export)
- Test: `tests/` — append a one-liner to `tests/mower/test_error_codes.py` (no HA needed) OR rely on the existing event/device-trigger tests. Add the import-equality check below.

- [ ] **Step 1: Write the failing test**

Append to `tests/mower/test_error_codes.py`:
```python
def test_const_reexports_same_notification_event_types():
    from custom_components.dreame_a2_mower import const
    from custom_components.dreame_a2_mower.mower.error_codes import (
        NOTIFICATION_EVENT_TYPES as SRC,
    )
    assert const.NOTIFICATION_EVENT_TYPES is SRC
```
(If importing `const` pulls `homeassistant` and the vanilla env lacks it, move this assertion into an HA-aware test dir — but `const` only imports `homeassistant.const`, which the stubbed env provides; the existing `tests/` already import `const` indirectly. If it genuinely can't import, delete this test and rely on Task 6's device-trigger test, which imports `const` transitively.)

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_error_codes.py -k reexports -q`
Expected: FAIL (`const.NOTIFICATION_EVENT_TYPES` is a separate hand literal, not `is` the error_codes object)

- [ ] **Step 3: Write minimal implementation**

In `const.py`, replace the whole block from `NOTIFICATION_EVENT_TYPES: Final[tuple[str, ...]] = (` (line 60) through the closing docstring `"""` (line 103) with:
```python
# HA event_type slugs fired by event.dreame_a2_mower_notification, DERIVED from
# the app catalog (see mower/error_codes.py). Re-exported here for the consumers
# that import event-type lists from const (event.py, device_trigger.py). The
# per-notification user-visible text is the cloud/catalog string in the event
# payload's `text`; the slug is only a stable HA identifier.
# Source: [apk:g2408-plugin-ext1423].
from .mower.error_codes import (  # noqa: E402 — re-export
    NOTIFICATION_EVENT_TYPES as NOTIFICATION_EVENT_TYPES,
)
```
Leave `LIFECYCLE_EVENT_TYPES` (above, lines 30-58) untouched.

- [ ] **Step 4: Run test + event/device-trigger imports**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_error_codes.py -k reexports tests/ -k "event or device_trigger or notification" -q`
Expected: PASS (event entity advertises the derived list; const re-export identity holds)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/const.py tests/mower/test_error_codes.py
git commit -m "refactor(p3a): const re-exports catalog-derived NOTIFICATION_EVENT_TYPES"
```

---

### Task 4: tier/category/severity on the notification payload

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_device_sync.py` (`_fire_notification`, ~lines 415-466; add the import + payload keys)
- Test: `tests/coordinator/test_fault_events.py` (or the existing notification-event test module — append)

- [ ] **Step 1: Write the failing test**

Append to `tests/coordinator/test_fault_events.py` (mirror the existing `_fire_notification`/notification-entity test setup in that file — reuse its coordinator/entity fixtures; do not invent a new harness):
```python
def test_fire_notification_payload_carries_tier(make_coordinator_with_notification_entity):
    # Reuse the existing helper/fixture pattern in this module that builds a
    # coordinator with a registered notification event entity and captures
    # trigger() calls. If none exists, build it the same way the nearby
    # notification test does.
    coord, captured = make_coordinator_with_notification_entity()
    coord._fire_notification(
        event_type="human_detected", text="A person was detected", code=27,
        siid=2, piid=2, send_time=None, message_id="m1", now_unix=0,
    )
    et, payload = captured[-1]
    assert et == "human_detected"
    assert payload["tier"] == "attention"      # FAULT + work_message
    assert payload["category"] == "FAULT"
    assert payload["severity"] == "work_message"


def test_fire_notification_unknown_code_omits_tier(make_coordinator_with_notification_entity):
    coord, captured = make_coordinator_with_notification_entity()
    coord._fire_notification(
        event_type="unknown_s2p2", text="x", code=9999,
        siid=2, piid=2, send_time=None, message_id="m2", now_unix=0,
    )
    _, payload = captured[-1]
    assert "tier" not in payload   # trigger() drops None-valued keys
```
> NOTE to implementer: if `tests/coordinator/test_fault_events.py` has no reusable fixture, replicate the construction used by the existing notification test in the SAME file (it already exercises `_fire_notification`/the notification entity per the Explore of `event.py`+`_device_sync.py`). Keep the fixture local to this module.

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_fault_events.py -k "payload_carries_tier or unknown_code_omits" -q`
Expected: FAIL (`payload` has no `tier` key)

- [ ] **Step 3: Write minimal implementation**

In `coordinator/_device_sync.py`, ensure the module imports the catalog (top of file, with the other `from ..mower...` imports):
```python
from ..mower import fault_catalog
```
Then in `_fire_notification`, extend the `payload` dict (currently 7 keys) to:
```python
        payload = {
            "text": text,
            "code": code,
            "siid": siid,
            "piid": piid,
            "send_time": send_time,
            "message_id": message_id,
            "source": "cloud",
            "tier": fault_catalog.fault_tier(code),
            "category": fault_catalog.fault_category(code),
            "severity": fault_catalog.fault_severity(code),
        }
```
The entity's `trigger` already strips None-valued keys, so unknown codes (tier/category/severity all None) simply omit them.

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_fault_events.py -q`
Expected: PASS (new + existing notification tests green)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_device_sync.py tests/coordinator/test_fault_events.py
git commit -m "feat(p3a): notification payload carries tier/category/severity"
```

---

### Task 5: resolver catalog-text fallback + drop the logbook hand table

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_notifications.py:209` (text fallback)
- Modify: `custom_components/dreame_a2_mower/logbook.py:46-78,100-102` (delete `_NOTIFICATION_MESSAGES`; simplify the fallback)
- Test: `tests/` logbook test module (append) + a resolver test if one exists

- [ ] **Step 1: Write the failing test**

Append to the logbook test module (find it: `tests/**/test_logbook*.py`; if none, create `tests/test_logbook.py` importing `from custom_components.dreame_a2_mower.logbook import _format`):
```python
def test_logbook_notification_prefers_payload_text():
    from custom_components.dreame_a2_mower.logbook import _format
    msg = _format("event.x_notification", "human_detected", {"text": "A person was detected"})
    assert msg == "A person was detected"


def test_logbook_notification_no_text_falls_back_to_slug_words():
    from custom_components.dreame_a2_mower.logbook import _format
    # no payload text → humanised slug (the hand table is gone)
    msg = _format("event.x_notification", "back_charge_failed", {})
    assert msg == "back charge failed"


def test_logbook_notification_messages_table_removed():
    import custom_components.dreame_a2_mower.logbook as lb
    assert not hasattr(lb, "_NOTIFICATION_MESSAGES")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "logbook_notification" -q`
Expected: FAIL (`_NOTIFICATION_MESSAGES` still present; `back_charge_failed` not in old table so returns humanised words already — the *removed* assertion fails)

- [ ] **Step 3: Write minimal implementation**

(a) In `logbook.py`, DELETE the entire `_NOTIFICATION_MESSAGES` dict (lines 46-78, including its 3-line comment). In `_format`, change the notification branch's fallback (lines 100-102) from:
```python
        return _NOTIFICATION_MESSAGES.get(
            event_type, event_type.replace("_", " ")
        )
```
to:
```python
        return event_type.replace("_", " ")
```
Keep the `text = attrs.get("text")` preference above it unchanged.

(b) In `coordinator/_notifications.py`, ensure the module imports the catalog (near the other `from ..mower...` imports):
```python
from ..mower import fault_catalog
```
Then change line 209 from:
```python
        text = _english_text(matching) or ""
```
to:
```python
        # Prefer the cloud's authoritative English push text; fall back to the
        # bundled app catalog so the payload (and logbook) still get a real
        # string when the cloud push briefly lacks one.
        text = _english_text(matching) or fault_catalog.fault_text(value, "en") or ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "logbook" -q`
Expected: PASS. Fix any existing logbook test that asserted an OLD `_NOTIFICATION_MESSAGES` string (convert to either the payload-`text` path or the humanised-slug fallback).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/logbook.py custom_components/dreame_a2_mower/coordinator/_notifications.py tests/
git commit -m "feat(p3a): resolver catalog-text fallback; drop logbook hand table"
```

---

### Task 6: device-trigger corrected slugs

**Files:**
- Modify: `custom_components/dreame_a2_mower/device_trigger.py:72-99` (the `_EXPOSED_NOTIFICATION_EVENT_TYPES` tuple + docstring counts)
- Test: `tests/` device-trigger test module (append)

- [ ] **Step 1: Write the failing test**

Append to the device-trigger test module (`tests/**/test_device_trigger*.py`):
```python
def test_exposed_triggers_use_corrected_catalog_slugs():
    from custom_components.dreame_a2_mower.device_trigger import (
        _EXPOSED_NOTIFICATION_EVENT_TYPES as EXP, TRIGGER_TYPES,
    )
    from custom_components.dreame_a2_mower.mower.error_codes import S2P2_EVENT_TYPES
    # corrected vocabulary present, old wrong slugs gone
    assert "back_charge_failed" in EXP           # was positioning_failed_stuck (31)
    assert "go_to_cleanpoint_success" in EXP      # was arrived_at_maintenance_point (75)
    assert "trapped" in EXP                       # was robot_trapped (2)
    for stale in ("positioning_failed_stuck", "robot_trapped", "arrived_at_maintenance_point"):
        assert stale not in EXP
    # every exposed slug is a real catalog-derived notification slug
    valid = set(S2P2_EVENT_TYPES.values())
    for slug in EXP:
        assert slug in valid, f"exposed trigger {slug!r} not a derived slug"
    assert set(EXP) <= set(TRIGGER_TYPES)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "exposed_triggers_use_corrected" -q`
Expected: FAIL (EXP still has `positioning_failed_stuck`, `robot_trapped`, etc.)

- [ ] **Step 3: Write minimal implementation**

In `device_trigger.py`, replace the `_EXPOSED_NOTIFICATION_EVENT_TYPES` tuple (lines 74-93) with the corrected slugs (same 18 codes):
```python
_EXPOSED_NOTIFICATION_EVENT_TYPES: tuple[str, ...] = (
    "human_detected",           # 27
    "trapped",                  # 2
    "emergency_stop",           # 23
    "blade_loss",               # 28
    "left_wheel",               # 4
    "right_wheel",              # 5
    "hanging",                  # 0
    "back_charge_failed",       # 31
    "locating_failed_with_map", # 33
    "task_start_failed",        # 36
    "battery_temp_low",         # 43 (shared slug with 59 FAULT variant)
    "battery_low_returning",    # 54
    "bad_weather_protecting",   # 56
    "idle_timeout_returning",   # 71
    "pause_timeout_returning",  # 72
    "top_cover_open",           # 73
    "go_to_cleanpoint_success", # 75
    "go_to_cleanpoint_failed",  # 76
)
```
Also update the module docstring counts (lines 16-17, 24): "28 NOTIFICATION_EVENT_TYPES" → the derived count is now ~68; reword to "the catalog-derived `NOTIFICATION_EVENT_TYPES`" without pinning a stale number, and "we expose the high-value 18" stays accurate.

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "device_trigger" -q`
Expected: PASS. Convert any existing device-trigger test pinning an old slug to the corrected one.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/device_trigger.py tests/
git commit -m "feat(p3a): device-trigger uses corrected catalog slugs"
```

---

### Task 7: confidence gate → slug-integrity

**Files:**
- Modify: `tests/inventory/test_error_codes_confidence_gate.py` (rewrite)

- [ ] **Step 1: Write the new test (replaces the old source-parsing gate)**

Replace the entire file with:
```python
"""CI gate: S2P2_EVENT_TYPES is DERIVED from the authoritative app catalog
[apk:g2408-plugin-ext1423], not hand-curated. This gate guards the derivation
integrity: every mapped code must be a catalog code (slug == event_slug) or an
explicit wire supplement, so apk/vacuum-lineage names can't creep back in."""
from custom_components.dreame_a2_mower.mower import fault_catalog as fc
from custom_components.dreame_a2_mower.mower.error_codes import (
    _SLUG_SUPPLEMENT,
    S2P2_EVENT_TYPES,
)


def test_every_mapped_code_is_catalog_or_supplement():
    catalog = fc.known_codes("iot")
    for code, slug in S2P2_EVENT_TYPES.items():
        if code in _SLUG_SUPPLEMENT:
            assert slug == _SLUG_SUPPLEMENT[code]
            assert code not in catalog, (
                f"code {code} is now in the catalog — drop it from _SLUG_SUPPLEMENT"
            )
        else:
            assert code in catalog, f"mapped code {code} not in catalog and not supplemented"
            assert slug == fc.event_slug(code), (
                f"slug for {code} ({slug!r}) != event_slug ({fc.event_slug(code)!r})"
            )


def test_every_catalog_code_is_mapped():
    for code in fc.known_codes("iot"):
        assert code in S2P2_EVENT_TYPES, f"catalog code {code} missing a slug"
```

- [ ] **Step 2: Run it**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_error_codes_confidence_gate.py -q`
Expected: PASS (both tests). If it errors importing `_SLUG_SUPPLEMENT`, confirm Task 2 named it exactly that.

- [ ] **Step 3: (sanity) Prove the gate bites**

Temporarily add `999: "bogus"` to `_SLUG_SUPPLEMENT` in a scratch edit, run the gate, confirm `test_every_mapped_code_is_catalog_or_supplement` still passes (999 not in catalog, slug matches) — then add `0: "wrong"` override and confirm it FAILS (slug != event_slug(0)). Revert the scratch edit. (Do not commit the scratch edit.)

- [ ] **Step 4: Commit**

```bash
git add tests/inventory/test_error_codes_confidence_gate.py
git commit -m "test(p3a): confidence gate -> catalog slug-integrity"
```

---

### Task 8: inventory, docs, canonical regen, full suite, release

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (s2p2 section — slug provenance)
- Modify: `OLD/ha-dreame-a2-mower-docs/inventory-history/s2p2.md` (retraction append)
- Modify: `docs/events.md` if it enumerates the old slugs
- Regenerate: `docs/research/g2408-canonical.md` (via `inventory_gen.py` no-flag — per the canonical-drift rule)

- [ ] **Step 1: Inventory provenance + retraction**

In `inventory.yaml` § s2p2, record that the notification event slugs are now derived from the app catalog `fault_name` `[apk:g2408-plugin-ext1423]`; the prior hand-curated slug table (with its wrong entries — 31 `positioning_failed_stuck`, 33 `positioning_failed_transient`, etc.) is retired. Per the retraction rule, append the prior wrong-slug claims (verbatim, with reason) to `OLD/ha-dreame-a2-mower-docs/inventory-history/s2p2.md`. Add a 2026-06-18 `verified` row noting the derive rule + the 70-key map (69 catalog + 47 supplement) + the two intentional collisions.

- [ ] **Step 2: Validate inventory schema + regenerate canonical**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only`
Expected: OK. Then regenerate the canonical doc:
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py`
(Commit only the intended canonical churn; do not sweep unrelated wire-census count drift — per the canonical-drift memory.)

- [ ] **Step 3: docs/events.md**

If `docs/events.md` lists the old notification slugs, update them to the corrected vocabulary (or replace the enumeration with "derived from the app catalog; see `mower/error_codes.py:S2P2_EVENT_TYPES`"). If it doesn't enumerate them, no change.

- [ ] **Step 4: Full suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: all pass (baseline was 2535 passed / 4 skipped before P3a — expect the same count ± the new tests, zero failures). Investigate any remaining OLD-slug assertion and convert it.

- [ ] **Step 5: Commit + release**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml docs/ OLD/
git commit -m "docs(p3a): inventory slug provenance + retraction + canonical regen"
```
Then release via the canonical tool (NOT a manual gh release — HACS needs it):
```bash
tools/release/release.sh
```
(release.sh auto-bumps the alpha — note the HACS digit-boundary rule: if the counter would grow a digit, it bumps the patch. Expect ~v1.0.30a1.) After release, the controller live-verifies on HA (integration loads clean; `event.dreame_a2_mower_notification` advertises the derived event_types; device-trigger list shows the corrected names).

---

## Self-Review notes
- **Spec coverage:** A→T1, B→T2, C→T3, D→T4, E→T5, F→T6, G→T7, H→T8. All covered.
- **Slug collisions:** handled explicitly in T1/T2 tests (no value-uniqueness assertions; both pairs asserted equal).
- **Type consistency:** `event_slug(code, channel="iot") -> str | None`, `_SLUG_SUPPLEMENT: dict[int,str]`, `S2P2_EVENT_TYPES: dict[int,str]`, `NOTIFICATION_EVENT_TYPES: tuple[str,...]` — consistent across tasks.
- **Test-env imports:** layer-2 modules import cleanly in `.venv-vanilla` (existing tests do `from custom_components.dreame_a2_mower.mower import fault_catalog`); `const` imports only `homeassistant.const` (stubbed). Task 3's test has a fallback note if `const` import is unavailable.
- **No reverse slug→code mapping introduced** anywhere (resolver forward; logbook reads payload; triggers map type→entity).
