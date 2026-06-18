# Tier classification + app-faithful ERROR latch (P2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-curated 6-code `FAULT_CODES` with an app-derived tier classifier (`fault_tier`), making `is_fault` / the `lawn_mower` ERROR latch faithful to the app's FAULT/ALERT/INFO × severity classification.

**Architecture:** A pure `fault_tier(code)` in `mower/fault_catalog.py` maps each code to `error`/`attention`/`alert`/`info` from the catalog's `category`+`severity`. `is_fault(code)` becomes `fault_tier(code) == "error"`; `FAULT_CODES` is deleted. The state-machine latch (unchanged in shape) then drives `lawn_mower` ERROR + the Error sensor + fault events off the 26 app-derived error-tier codes.

**Tech Stack:** Python (HA custom component); vanilla-pytest venv at `/data/claude/homeassistant/.venv-vanilla/bin/python`.

**Test command:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -q`. System python3 broken. Stage by EXPLICIT path; never `git add -A` (untracked `tools/probes/oss_*` are NOT ours).

**The 26 error-tier codes** (`FAULT` & `anomaly`|`malfunction`): `{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,17,20,21,22,23,24,26,37,59,73}`. Notably 73 (top-cover-open) and 0 (lifted) are NEW error-tier; 31 (back-charge-failed) and 36 (task-start-failed) are now `alert` (NOT error).

---

### Task 1: `fault_tier` + `error_tier_codes` in fault_catalog

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/fault_catalog.py`
- Test: `tests/unit/test_fault_catalog.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_fault_catalog.py`:

```python
def test_fault_tier_maps_category_and_severity():
    assert fc.fault_tier(4) == "error"        # FAULT + malfunction
    assert fc.fault_tier(0) == "error"        # FAULT + anomaly
    assert fc.fault_tier(73) == "error"       # FAULT + malfunction (top cover)
    assert fc.fault_tier(27) == "attention"   # FAULT + work_message (human)
    assert fc.fault_tier(28) == "attention"   # FAULT + consumable (blade worn)
    assert fc.fault_tier(31) == "alert"       # ALERT
    assert fc.fault_tier(48) == "info"        # INFO
    assert fc.fault_tier(99999) is None       # unknown


def test_error_tier_codes_is_the_pinned_26():
    assert fc.error_tier_codes("iot") == frozenset(
        {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17,
         20, 21, 22, 23, 24, 26, 37, 59, 73}
    )
    assert 31 not in fc.error_tier_codes("iot")  # ALERT, not error
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_fault_catalog.py -q`
Expected: FAIL — `fault_tier` / `error_tier_codes` undefined.

- [ ] **Step 3: Implement**

In `mower/fault_catalog.py`, add (after `fault_category` / `fault_severity`):

```python
def fault_tier(code: int, channel: str = "iot") -> str | None:
    """App-derived surfacing tier for a code, or None if unknown. Tier names
    track the app vocabulary (alert/info = category words; error/attention =
    the FAULT category split by severity).

      error     = FAULT + (anomaly|malfunction)     — mower can't continue / needs help
      attention = FAULT + (work_message|consumable) — attention, not broken
      alert     = ALERT (any severity)              — recoverable operation failure
      info      = INFO  (any severity)              — lifecycle/status
    """
    cat = fault_category(code, channel)
    if cat is None:
        return None
    sev = fault_severity(code, channel)
    if cat == "FAULT":
        return "error" if sev in ("anomaly", "malfunction") else "attention"
    if cat == "ALERT":
        return "alert"
    if cat == "INFO":
        return "info"
    return None


def error_tier_codes(channel: str = "iot") -> frozenset[int]:
    """The codes whose tier is 'error' (the HA error-latch set)."""
    return frozenset(
        c for c in known_codes(channel) if fault_tier(c, channel) == "error"
    )
```

- [ ] **Step 4: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_fault_catalog.py -q`
Expected: PASS. (If `test_error_tier_codes_is_the_pinned_26` fails because the real set differs, print `sorted(fc.error_tier_codes("iot"))` and reconcile — the catalog is the source of truth; update the pinned set in the test to match the real catalog AND note the difference in your report, since the spec asserted exactly these 26.)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/fault_catalog.py tests/unit/test_fault_catalog.py
git commit -m "feat(faults): fault_tier classifier (error/attention/alert/info) + error_tier_codes"
```

---

### Task 2: Retire `FAULT_CODES`; `is_fault` → tier-derived; fix affected tests

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/error_codes.py`
- Modify: `tests/mower/test_error_codes.py`
- Modify: `tests/state_machine/test_state_machine_faults.py`

- [ ] **Step 1: Rewrite the `is_fault` tests + state-machine non-fault test**

In `tests/mower/test_error_codes.py`:
- Remove `FAULT_CODES` from the import (keep `is_fault`, `S2P2_EVENT_TYPES`, etc.).
- Replace `test_genuine_faults_are_faults` with:
  ```python
  def test_genuine_faults_are_error_tier():
      from custom_components.dreame_a2_mower.mower import fault_catalog as fc
      # error-tier (FAULT + anomaly|malfunction) → latches
      for code in (0, 1, 2, 4, 5, 7, 23, 73):
          assert is_fault(code), f"expected {code} to be an error-tier fault"
      # 31/36 are ALERT in the app → NO LONGER error-tier
      assert not is_fault(31)
      assert not is_fault(36)
  ```
- Replace `test_status_lifecycle_and_unverified_codes_are_not_faults` with a
  principled check (no hand-list that drifts):
  ```python
  def test_non_error_tier_codes_do_not_latch():
      from custom_components.dreame_a2_mower.mower import fault_catalog as fc
      # attention / alert / info codes must NOT latch ERROR
      for code in (27, 28, 30, 31, 36, 47, 48, 50, 51, 54, 56, 70, 71, 74, 75, 76):
          assert fc.fault_tier(code) != "error"
          assert not is_fault(code), f"{code} (tier={fc.fault_tier(code)}) must not latch"
  ```
- Replace `test_fault_codes_are_all_described` (which iterated `FAULT_CODES`) with:
  ```python
  def test_error_tier_codes_all_have_catalog_text():
      from custom_components.dreame_a2_mower.mower import fault_catalog as fc
      codes = fc.error_tier_codes("iot")
      assert len(codes) == 26
      for code in codes:
          assert fc.fault_text(code, "en"), f"error code {code} missing catalog text"
  ```
- Keep `test_is_fault_handles_none_and_unknown` (None/999 → False) unchanged.

In `tests/state_machine/test_state_machine_faults.py`, `test_non_fault_does_not_evict_latched_fault` uses `value=73` as a "non-fault" — but 73 is now error-tier. Change it to an `info`/`attention` code:
```python
    m.handle_mqtt_property(siid=2, piid=2, value=50, now_unix=1001)  # 50 = mow started (info), not a fault
```
(and update the inline comment). The other tests use 5/2 (still error-tier) — unchanged.

- [ ] **Step 2: Run, verify FAIL**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_error_codes.py tests/state_machine/test_state_machine_faults.py -q`
Expected: FAIL — `FAULT_CODES` import gone but `is_fault` still uses it (or the new assertions fail until is_fault is tier-based).

- [ ] **Step 3: Rewrite `error_codes.py`**

In `mower/error_codes.py`:
1. DELETE the `FAULT_CODES: frozenset[int] = frozenset({ ... })` literal AND the comment block above it that explains the curated set / "Add here ONLY once confirmed on g2408".
2. Replace `is_fault`:
   ```python
   def is_fault(code: int | None) -> bool:
       """True if a code is the app's 'error' tier (FAULT + anomaly|malfunction):
       the mower can't continue without intervention. Drives the latched error
       state (lawn_mower ERROR + Error sensor + fault events). Sourced from the
       app catalog [apk:g2408-plugin-ext1423] via fault_tier — no hand-curated
       list. None / unknown codes → False (surfaced via the notification event +
       [NOVEL] log, not latched)."""
       return code is not None and fault_catalog.fault_tier(int(code)) == "error"
   ```
   (`fault_catalog` is already imported at the top of `error_codes.py` from P1.)

- [ ] **Step 4: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_error_codes.py tests/state_machine/test_state_machine_faults.py -q`
Expected: PASS.

- [ ] **Step 5: Add a state-machine test for a NEW error-tier latch**

Append to `tests/state_machine/test_state_machine_faults.py`:
```python
def test_newly_classified_error_code_latches():
    # 73 (top-cover-open, FAULT/malfunction) was NOT in the old FAULT_CODES;
    # the app-derived error tier now latches it.
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=73, now_unix=1000)
    assert 73 in m.snapshot().errors


def test_alert_code_does_not_latch():
    # 31 (back-charge-failed) is ALERT in the app → alert tier, not error.
    m = MowerStateMachine()
    m.handle_mqtt_property(siid=2, piid=2, value=31, now_unix=1000)
    assert m.snapshot().errors == frozenset()
```

- [ ] **Step 6: Run, verify PASS**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/state_machine/test_state_machine_faults.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/error_codes.py tests/mower/test_error_codes.py tests/state_machine/test_state_machine_faults.py
git commit -m "feat(faults): is_fault = app error tier (FAULT+anomaly|malfunction); retire FAULT_CODES"
```

---

### Task 3: Inventory reconciliation, full suite, release + live-verify

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`
- Append: `OLD/ha-dreame-a2-mower-docs/inventory-history/s2p2.md` (out of tree)

- [ ] **Step 1: Reconcile the inventory FAULT_CODES claim**

Read the `inventory.yaml § s2p2` property's verification that states
`FAULT_CODES={2,4,5,23,31,36}` (grep `FAULT_CODES` in inventory.yaml — it's a
`verifications:` claim). Per the repo retraction rule:
1. APPEND the verbatim prior claim + reason to
   `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/inventory-history/s2p2.md`
   (one entry: the old `FAULT_CODES={2,4,5,23,31,36}` claim, the date, and the
   reason — superseded by the app-derived error tier).
2. REWORD the inline claim to: the HA error latch is the app-derived **error
   tier** = `FAULT` & (`anomaly`|`malfunction`) (26 codes
   `{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,17,20,21,22,23,24,26,37,59,73}`), via
   `fault_catalog.fault_tier` `[apk:g2408-plugin-ext1423]`; `FAULT_CODES` retired.
   31 (back-charge-failed) and 36 (task-start-failed) are now the **alert** tier,
   no longer latching ERROR.
3. Add a `verifications:` row dated 2026-06-18, status `verified`, claim
   summarizing the tier rule + the 26-code error set + the 31/36 reclassification,
   evidence `apk:g2408-plugin-ext1423 (fault_catalog.fault_tier)`.
Update `status.last_seen` to 2026-06-18.

- [ ] **Step 2: Validate inventory schema**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only`
Expected: `ok: inventory schema valid`.

- [ ] **Step 3: Run the FULL suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q --ignore=tests/archive`
Expected: all pass (~2531 baseline + new tests, minus the removed `FAULT_CODES` test asserts). Fix any failure caused by the expanded error set:
- A `lawn_mower` / Error-sensor / fault-event test that asserted a SPECIFIC code is NOT an error (e.g. a code now in the 26) → update it to the new tier reality (use `fault_tier`/`is_fault`, not a hard literal).
- An entity-inventory or audit gate referencing the error latch → reconcile (the error sensor/lawn_mower behavior shape is unchanged; only the code set expanded — no new entity/attribute, so no audit-expectations row needed; but if a test pins the old 6-set, update it).
- Any other `FAULT_CODES` import in tests/ → convert to `error_tier_codes()`/`is_fault()`.
Re-run until green.

- [ ] **Step 4: Commit docs**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml
# (the OLD/ archive append is outside the repo — not git-added here)
git commit -m "docs(faults): reconcile s2p2 error-latch to app-derived error tier (P2)"
```

- [ ] **Step 5: Release + live-verify (controller does this; not a subagent step)**

Push; move untracked `tools/probes/oss_*` aside for a clean tree;
`tools/release/release.sh --notes "..."`; restore probes; install via HACS;
restart HA. Then verify on live HA:
1. The integration loads clean (no import error from the retired `FAULT_CODES`).
2. (When a fault next occurs) the mower entity goes ERROR for an error-tier code,
   and `sensor.dreame_a2_mower_error` reflects it. Until a live fault occurs, the
   expanded latch is covered by the suite.

---

## Notes / gotchas
- Test interpreter: `/data/claude/homeassistant/.venv-vanilla/bin/python`. Stage by explicit path; leave untracked `tools/probes/oss_*` alone.
- The behavior change: `lawn_mower` ERROR + Error sensor latch expands from 6 → 26 app-derived codes; 31/36 drop to the alert tier. This is intentional + app-faithful.
- `is_fault` keeps its `None`/unknown → False contract; `fault_tier(unknown)` → None → not error.
- P2 does NOT add a new entity/attribute (no audit-expectations change expected); it only changes which codes latch the existing error surfaces.
- Attention/alert/info SURFACING + slug corrections are P3; heartbeat is P4.
