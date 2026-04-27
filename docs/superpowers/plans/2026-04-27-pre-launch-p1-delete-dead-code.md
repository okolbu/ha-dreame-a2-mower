# P1 — Delete Dead Upstream-Vacuum / Non-g2408 Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete clearly-dead vacuum and non-g2408-mower code from the
integration so the remaining codebase reflects only the single-model
g2408 reality. This is the foundation priority — every later plan
becomes cheaper against a smaller codebase.

**Architecture:** Pure deletion + capability flattening. No feature
changes, no behavior changes intended. The deletion targets are
either provably-unused (no external references) or
runtime-equivalent-to-constants (the per-model capability blob). The
plan is bite-sized so each commit is reversible if a hidden caller
turns up.

**Tech Stack:** Python 3, Home Assistant custom-integration scaffold,
pytest. Tests run via `pytest` from repo root.

**Spec:** `docs/superpowers/specs/2026-04-27-pre-launch-review-design.md`
priority 1.

**Working discipline:** Per spec §8, push to `origin/main` after each
phase completes. Commits are small, frequent, traceable. `main` is
allowed to be temporarily not-installable during the cleanup —
priority is bisectability and audit trail, not release readiness.

---

## File map

Files this plan modifies, with the responsibility of each cluster of
edits:

- `custom_components/dreame_a2_mower/dreame/types.py`
  - Delete unused `DreameMowerDustCollection`, `DreameMowerAutoEmptyStatus`,
    `DreameMowerSelfCleanArea` enums (lines 332, 340, 349).
  - Delete `DreameMowerFloorMaterial`, `DreameMowerFloorMaterialDirection`
    enums (lines 397, 406) and the only consumer at line 1756.
  - Replace `DreameMowerDeviceCapability` (lines 1218–1347) runtime
    `refresh()` with a frozen-constants form for g2408.
- `custom_components/dreame_a2_mower/dreame/const.py`
  - Delete `FLOOR_MATERIAL_*` constants (lines 137–138) and lookup
    tables (lines 590–599).
  - Delete `CLEANING_MODE_MOWING: Final = "sweeping"` legacy alias
    (line 28) and the consumer at line 587, replacing with the
    direct string.
  - Delete `DREAME_MODEL_CAPABILITIES` blob and `DeviceCapability`
    enum after capability flattening lands.
- `custom_components/dreame_a2_mower/dreame/__init__.py`
  - Drop re-exports of deleted symbols (lines 17, 18, 28, 29).
- `custom_components/dreame_a2_mower/dreame/device.py`
  - Drop import of `FLOOR_MATERIAL_CODE_TO_NAME`,
    `FLOOR_MATERIAL_DIRECTION_CODE_TO_NAME` (lines 86–87).
  - Drop `floor_material_list` /
    `floor_material_direction_list` instance attributes
    (lines 6839–6840).
  - Drop import of `DREAME_MODEL_CAPABILITIES` (line 95) and the
    runtime decode call (line 1455).
  - Audit `disable_sensor_cleaning` checks (lines 2013, 4046, 8076)
    — the value is statically False on g2408 after flattening, so
    the surrounding `if not …` branches become dead.
- `custom_components/dreame_a2_mower/sensor.py`, `button.py`,
  `coordinator.py`
  - Audit `exists_fn=lambda description, device:
    not device.capability.disable_sensor_cleaning`
    closures (sensor.py:392, 400; button.py:330; coordinator.py:590).
    If the flag is statically False on g2408, the closures always
    return True — drop the `exists_fn` entirely.
- `tests/` — add a regression test that asserts the post-flattening
  capability shape matches the pre-flattening shape captured at the
  start of phase 4. No other test changes expected; existing tests
  must stay green throughout.

---

## Phase 1 — Delete unused enums (DustCollection, AutoEmptyStatus, SelfCleanArea)

These three enum classes are defined in `dreame/types.py` but are
never imported elsewhere in the codebase. The earlier exploration
pass confirmed zero external references. Pure deletion.

### Task 1.1: Verify zero external references

**Files:**
- Read: `custom_components/dreame_a2_mower/dreame/types.py:332-356`

- [ ] **Step 1: Run grep to confirm no external references**

```bash
grep -rn "DreameMowerDustCollection\|DreameMowerAutoEmptyStatus\|DreameMowerSelfCleanArea" \
    --include="*.py" .
```

Expected output: only `dreame/types.py` lines (the definitions themselves) appear.
If any other file references these symbols, STOP — they are not actually
unused. Report what you found and pause.

- [ ] **Step 2: Confirm full test suite passes baseline**

Run: `pytest -x`
Expected: PASS. If not, fix the failure before proceeding — don't
introduce deletion changes against a broken baseline.

### Task 1.2: Delete the three enum classes

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/types.py:332-356`

- [ ] **Step 1: Read current contents**

Read `custom_components/dreame_a2_mower/dreame/types.py` lines 330–360
to capture the surrounding context. Note the exact start and end of
each `class` block (they are typically 4–8 lines each including the
`class` line, members, and a trailing blank line).

- [ ] **Step 2: Delete the class definitions**

Use the Edit tool to remove the three classes. Each replacement is
the class block → empty (collapsed adjacent blank lines).

For `DreameMowerDustCollection` (line 332):

```python
class DreameMowerDustCollection(IntEnum):
    UNKNOWN = -1
    NOT_SET = 0
    SMART = 1
    DAILY = 2
    SAVE = 3
```

→ delete the whole block.

For `DreameMowerAutoEmptyStatus` (line 340):

```python
class DreameMowerAutoEmptyStatus(IntEnum):
    UNKNOWN = -1
    IDLE = 0
    EMPTYING = 1
    PAUSED = 2
    NOT_PERFORMED = 3
```

→ delete.

For `DreameMowerSelfCleanArea` (line 349):

```python
class DreameMowerSelfCleanArea(IntEnum):
    UNKNOWN = -1
    SMALL = 0
    MEDIUM = 1
    LARGE = 2
```

→ delete.

(Use Read first to capture the exact lines including each enum's
members; the Edit tool requires the exact `old_string`.)

- [ ] **Step 3: Run import smoke test**

Run: `python -c "from custom_components.dreame_a2_mower.dreame import types; print('ok')"`
Expected: `ok`. If `ImportError` or `NameError`, the symbol was used
somewhere step 1 missed — restore and re-grep.

- [ ] **Step 4: Run full test suite**

Run: `pytest -x`
Expected: PASS. No tests should reference these enums.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/dreame/types.py
git commit -m "$(cat <<'EOF'
P1.1: delete unused vacuum enums DustCollection / AutoEmptyStatus / SelfCleanArea

These enums were holdovers from the upstream vacuum integration. No
references anywhere else in the codebase (confirmed via grep).
g2408 has no concept of dust collection, auto-emptying, or
self-clean-area selection.

Spec: docs/superpowers/specs/2026-04-27-pre-launch-review-design.md P1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Push**

Run: `git push origin main`
Expected: clean push, no rejection.

---

## Phase 2 — Delete FloorMaterial machinery

`DreameMowerFloorMaterial` and `DreameMowerFloorMaterialDirection`
are vacuum concepts (tile / wood / vertical / horizontal flooring) —
irrelevant for a lawn mower. Slightly deeper integration than phase 1
because `dreame/__init__.py` re-exports them, `dreame/const.py`
defines lookup tables, and `dreame/device.py` instantiates lookup
dicts. Single use site exists at `dreame/types.py:1756` (an attribute
setter inside an unrelated dict-builder function).

### Task 2.1: Map all references

**Files:**
- Read all the file references from the grep below.

- [ ] **Step 1: Grep for every use site**

```bash
grep -rn "DreameMowerFloorMaterial\|DreameMowerFloorMaterialDirection\|FLOOR_MATERIAL_CODE_TO_NAME\|FLOOR_MATERIAL_DIRECTION_CODE_TO_NAME\|FLOOR_MATERIAL_NONE\|FLOOR_MATERIAL_TILE\|FLOOR_MATERIAL_WOOD\|FLOOR_MATERIAL_DIRECTION_VERTICAL\|FLOOR_MATERIAL_DIRECTION_HORIZONTAL\|ATTR_FLOOR_MATERIAL\|floor_material_list\|floor_material_direction_list" \
    --include="*.py" .
```

Expected: results clustered in `dreame/types.py`, `dreame/const.py`,
`dreame/__init__.py`, `dreame/device.py`. If any HA entity file
(`sensor.py`, `select.py`, etc.) shows up, the deletion is bigger
than this task assumes — report and pause.

- [ ] **Step 2: Read each site to confirm the mechanical removal**

Read each file at the line numbers from step 1. Confirm:
- `dreame/types.py:1756` — single attribute set into a dict; safe to
  delete that line.
- `dreame/types.py:103` — `ATTR_FLOOR_MATERIAL_DIRECTION` constant —
  used only on line 1756; both go together.
- `dreame/__init__.py` — import + re-export only.
- `dreame/const.py` — constant strings + lookup tables only.
- `dreame/device.py` — import + two attribute initializations only.

If anything else turns up, STOP and report.

### Task 2.2: Delete the floor-material code

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/types.py` — delete
  classes at 397, 406; delete `ATTR_FLOOR_MATERIAL_DIRECTION` at 103;
  delete the single attribute line at 1756.
- Modify: `custom_components/dreame_a2_mower/dreame/const.py` — delete
  imports at 16–17; delete constants at 137–138; delete lookup tables
  at 590–599.
- Modify: `custom_components/dreame_a2_mower/dreame/__init__.py` —
  drop re-exports at 17, 18, 28, 29.
- Modify: `custom_components/dreame_a2_mower/dreame/device.py` — drop
  imports at 86–87 and instance attributes at 6839–6840.

- [ ] **Step 1: Edit `dreame/types.py`**

Read the file at the four locations (103, 397, 406, 1756). For each:
delete the line(s) comprising the symbol's definition. Specifically:

- Line 103: `ATTR_FLOOR_MATERIAL_DIRECTION: Final = "floor_material_direction"`
  → delete.
- Lines around 397: `class DreameMowerFloorMaterial(IntEnum): ...`
  block (typically 4 members) → delete.
- Lines around 406: `class DreameMowerFloorMaterialDirection(IntEnum):
  ...` block (typically 3 members) → delete.
- Line 1756: the single line that does
  `attributes[ATTR_FLOOR_MATERIAL_DIRECTION] =
  DreameMowerFloorMaterialDirection(...)`. Delete that line and any
  immediately-adjacent helper conditional (read 1750–1770 for
  surrounding context first).

- [ ] **Step 2: Edit `dreame/const.py`**

- Line 16: `DreameMowerFloorMaterial,` (within an import block) → delete.
- Line 17: `DreameMowerFloorMaterialDirection,` → delete.
- Line 137–138: `FLOOR_MATERIAL_DIRECTION_VERTICAL: Final = "vertical"`
  and `FLOOR_MATERIAL_DIRECTION_HORIZONTAL: Final = "horizontal"`
  → delete.
- Lines 590–595: the `FLOOR_MATERIAL_CODE_TO_NAME` dict → delete the
  whole block (likely 5 lines including the `}`).
- Lines 596–599: the `FLOOR_MATERIAL_DIRECTION_CODE_TO_NAME` dict
  → delete the whole block (4 lines).

Also grep within `const.py` for `FLOOR_MATERIAL_NONE`,
`FLOOR_MATERIAL_TILE`, `FLOOR_MATERIAL_WOOD` constants and delete those
declarations if they exist (they appear above the lookup tables).

- [ ] **Step 3: Edit `dreame/__init__.py`**

Drop the four re-export lines:

```python
    DreameMowerFloorMaterial,
    DreameMowerFloorMaterialDirection,
```

and

```python
    FLOOR_MATERIAL_CODE_TO_NAME,
    FLOOR_MATERIAL_DIRECTION_CODE_TO_NAME,
```

(They're in `from .types import (...)` and `from .const import (...)`
import-block lists respectively.)

- [ ] **Step 4: Edit `dreame/device.py`**

- Lines 86–87: drop the two `FLOOR_MATERIAL_*_TO_NAME` imports.
- Lines 6839–6840: drop the two `self.floor_material_list = ...`
  and `self.floor_material_direction_list = ...` lines.

- [ ] **Step 5: Run import smoke test**

Run: `python -c "from custom_components.dreame_a2_mower.dreame import types, const; from custom_components.dreame_a2_mower.dreame.device import DreameMowerDevice; print('ok')"`
Expected: `ok`. If `ImportError`, restore and re-investigate.

- [ ] **Step 6: Run full test suite**

Run: `pytest -x`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/dreame/
git commit -m "$(cat <<'EOF'
P1.2: delete FloorMaterial machinery

DreameMowerFloorMaterial and DreameMowerFloorMaterialDirection
encode tile/wood/vertical/horizontal flooring concepts that apply
only to vacuums. The single in-codebase consumer was an attribute
setter inside an unrelated dict builder. No g2408 protocol coverage
mentions floor material — confirmed against
docs/research/g2408-protocol.md §2.1.

Spec: docs/superpowers/specs/2026-04-27-pre-launch-review-design.md P1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Push**

Run: `git push origin main`

---

## Phase 3 — Delete CLEANING_MODE_MOWING legacy alias

`CLEANING_MODE_MOWING: Final = "sweeping"` (const.py:28) is a string
alias whose value is the upstream-vacuum word "sweeping". The alias
maps `DreameMowerCleaningMode.MOWING` to the string at line 587. The
alias name is defensive but the value is misleading — for a mower,
the displayed string should be `"mowing"`, not `"sweeping"`.

This phase **changes a user-visible string**: the cleaning_mode
sensor's text representation flips from `"sweeping"` to `"mowing"`.
That's a behavior change but firmly in-scope for the cleanup
(spec §2 mutability list permits internal Python and entity-state
text changes).

### Task 3.1: Audit similar aliases first

**Files:**
- Read: `custom_components/dreame_a2_mower/dreame/const.py:1-50`
- Read: `custom_components/dreame_a2_mower/dreame/const.py:580-600`

- [ ] **Step 1: Find all CLEANING_MODE_* aliases**

```bash
grep -n "^CLEANING_MODE_\|CLEANING_MODE_NAME_TO_CODE\|CLEANING_MODE_CODE_TO_NAME" \
    custom_components/dreame_a2_mower/dreame/const.py
```

Expected: a small set of aliases plus the lookup table. Note which
ones have vacuum-only meaning (sweeping, mopping, sweeping_and_mopping,
mopping_first_then_sweeping, etc.) versus mower-relevant ones (mowing,
building_outline / mapping).

- [ ] **Step 2: Find consumers of the lookup table**

```bash
grep -rn "CLEANING_MODE_CODE_TO_NAME\|CLEANING_MODE_NAME_TO_CODE" --include="*.py" .
```

Expected: `dreame/device.py` and possibly an entity file. Each one
needs to remain working after the rename.

### Task 3.2: Rename the alias and audit fallout

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/const.py:28` — change
  the string value from `"sweeping"` to `"mowing"`.
- Modify: `custom_components/dreame_a2_mower/dreame/const.py:587` —
  unchanged (it still references the constant by name).
- Possibly modify: any `select.py` translation file or `strings.json`
  that maps the old "sweeping" string.

- [ ] **Step 1: Edit the alias value**

In `dreame/const.py`:

```python
CLEANING_MODE_MOWING: Final = "sweeping"
```

→

```python
CLEANING_MODE_MOWING: Final = "mowing"
```

- [ ] **Step 2: Search for any code that hardcodes the string "sweeping"**

```bash
grep -rn '"sweeping"' --include="*.py" --include="*.json" --include="*.yaml" .
```

Expected: every hit should be in a translation/strings file or in a
test that asserts the user-facing string. For each translation file,
update the entry. For each test, update the expected string.

- [ ] **Step 3: Run full test suite**

Run: `pytest -x`
Expected: PASS. If a test asserted the old "sweeping" string,
update it to "mowing" in the same commit.

- [ ] **Step 4: Smoke-test the integration loads**

```bash
python -c "from custom_components.dreame_a2_mower.dreame import const; assert const.CLEANING_MODE_MOWING == 'mowing'; print('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/dreame/const.py \
    custom_components/dreame_a2_mower/translations/ \
    tests/
git commit -m "$(cat <<'EOF'
P1.3: rename cleaning-mode "sweeping" → "mowing"

CLEANING_MODE_MOWING was aliased to the literal string "sweeping" —
a vacuum legacy artifact. The string is user-visible via the
cleaning_mode sensor; flipping it to "mowing" matches the mower's
actual behavior. Translation strings updated to match.

Note: this changes a user-visible state value. Acceptable per the
review spec §2 mutability list.

Spec: docs/superpowers/specs/2026-04-27-pre-launch-review-design.md P1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Push**

Run: `git push origin main`

---

## Phase 4 — Flatten `DREAME_MODEL_CAPABILITIES` to g2408 constants

This is the biggest deletion in P1 and the only one with risk. The
encoded blob `DREAME_MODEL_CAPABILITIES` (in `dreame/const.py:340`,
~5 KB of base64-zlib-encoded JSON) is the multi-model capability
registry inherited from the upstream vacuum integration. At runtime
`device.py:1455` decompresses it, looks up the g2408 entry, and sets
flags on `self.capability`. For a permanent single-model integration
this is dead weight and the lookup adds nothing the code couldn't
spell directly.

The strategy is **freeze the runtime values, not rewrite the contract**.
The `DreameMowerDeviceCapability` class stays — its 40+ flags are
read everywhere. Only `__init__` and `refresh()` change: from
"defaults + decode + per-flag runtime check" to "frozen g2408 values".

### Task 4.1: Snapshot current capability values from a live g2408

**Files:**
- Read: `custom_components/dreame_a2_mower/dreame/types.py:1218-1347`

This phase needs a ground-truth snapshot of what the existing code
produces at runtime on the user's actual g2408 mower. Without that
snapshot the flattening could silently change behavior.

- [ ] **Step 1: Add a one-shot diagnostic log line**

Open `custom_components/dreame_a2_mower/dreame/types.py` and at the end
of `DreameMowerDeviceCapability.refresh()` (around line 1347), add:

```python
        # P1.4: capture current capability snapshot for the
        # constants-flattening migration. Logs once per HA boot.
        # Remove this block in P1.4.4 below after the snapshot is
        # captured and the constants are encoded.
        if not getattr(self, "_p1_snapshot_logged", False):
            import logging as _l
            _logger = _l.getLogger("custom_components.dreame_a2_mower.dreame.types")
            snapshot = {
                p: getattr(self, p)
                for p in dir(self)
                if not p.startswith("_") and not callable(getattr(self, p))
                and p != "list"
            }
            _logger.warning("[P1.4_SNAPSHOT] capability snapshot: %s", snapshot)
            self._p1_snapshot_logged = True
```

- [ ] **Step 2: Reload the integration on the live mower**

Either restart Home Assistant or `Settings → Devices & Services →
ha-dreame-a2-mower → ⋮ → Reload`. Wait for the integration to fully
boot and the first MQTT update to land (the `refresh()` call fires
when capabilities are first computed).

- [ ] **Step 3: Capture the snapshot from the HA log**

```bash
grep "P1.4_SNAPSHOT" /config/home-assistant.log | tail -1
```

Expected: a single log line ending with the dict of capability
flag → bool/value pairs. Save the dict to
`docs/superpowers/plans/2026-04-27-p1-capability-snapshot.md`
with the timestamp.

- [ ] **Step 4: Commit the snapshot file**

```bash
git add docs/superpowers/plans/2026-04-27-p1-capability-snapshot.md
git commit -m "$(cat <<'EOF'
P1.4.1: snapshot live g2408 capability values

Captured runtime DreameMowerDeviceCapability state before the
flattening rewrite, so the rewrite is provably equivalent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4.2: Add a regression test that asserts the snapshot

**Files:**
- Create: `tests/dreame/test_capability_g2408_snapshot.py`

- [ ] **Step 1: Write the failing test**

Create `tests/dreame/test_capability_g2408_snapshot.py`:

```python
"""Regression test: g2408 capability snapshot.

Locks in the values DreameMowerDeviceCapability resolves to on
g2408. Originally captured live before flattening; now serves as
the contract that the post-flattening code must satisfy.

If this test fails after a refactor, the refactor changed observed
capability state — investigate before silencing the test.
"""
import pytest
from custom_components.dreame_a2_mower.dreame.types import (
    DreameMowerDeviceCapability,
    RobotType,
)


# Filled from docs/superpowers/plans/2026-04-27-p1-capability-snapshot.md.
# Update this dict if the snapshot file is regenerated.
G2408_CAPABILITY_SNAPSHOT = {
    # Paste the snapshot dict from the snapshot doc here.
    # Each key is a capability attribute name; each value is the
    # observed bool / RobotType / etc.
    # Example shape:
    # "lidar_navigation": True,
    # "ai_detection": True,
    # ...
}


def test_g2408_capability_matches_snapshot():
    """The live g2408 capability dict equals the captured snapshot."""
    # This test has two modes:
    #
    #   Pre-flattening (current code): instantiate the dataclass
    #   with a stubbed-out device, call refresh() with the same
    #   inputs that produced the snapshot, assert equality.
    #
    #   Post-flattening: instantiate the dataclass directly (no
    #   refresh() call needed because the values are constants),
    #   assert equality.
    #
    # The test is identical from the caller's perspective; the
    # implementation under test changes between the two phases.
    cap = DreameMowerDeviceCapability(device=None)
    # If pre-flattening, the test will need to call refresh() with
    # mock inputs. If post-flattening, the constructor sets the
    # values directly. Either way, this final equality is what we
    # assert.
    actual = {
        p: getattr(cap, p)
        for p in dir(cap)
        if not p.startswith("_") and not callable(getattr(cap, p))
        and p != "list"
    }
    for key, expected in G2408_CAPABILITY_SNAPSHOT.items():
        assert actual[key] == expected, (
            f"{key} drifted: snapshot={expected!r} actual={actual[key]!r}"
        )
```

- [ ] **Step 2: Fill in `G2408_CAPABILITY_SNAPSHOT`**

Open the snapshot doc you wrote in 4.1 and copy each
`key: value` pair into the dict literal. Convert string-form
RobotType values to `RobotType.LIDAR` (or whichever).

- [ ] **Step 3: Run the test, expect pre-flattening behaviour**

Run: `pytest tests/dreame/test_capability_g2408_snapshot.py -v`

Expected: this test currently exercises the pre-flattening code
path (defaults + refresh()). It will fail at this point because
the test stubs out `device=None` but `refresh()` accesses
`self._device.get_property(...)`. That's intentional — the test
is the contract; we'll make it pass in 4.3 by flattening.

If the test fails for a different reason (import error, etc.),
fix that before continuing.

### Task 4.3: Replace `DreameMowerDeviceCapability` runtime body with frozen constants

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/types.py:1218-1347`

- [ ] **Step 1: Read the existing class body**

Read `dreame/types.py` lines 1218–1347. Map each `__init__` default
and each `refresh()` line to the snapshot value it ultimately
produces on g2408.

- [ ] **Step 2: Replace `__init__` with the snapshot values directly**

For every attribute on `self.X = …` in `__init__`, set it to the
snapshot's value for `X`. The class body becomes:

```python
class DreameMowerDeviceCapability:
    """Capability flags for the Dreame A2 mower (g2408).

    This integration is permanently single-model. Each flag is a
    constant derived from the live snapshot captured during P1.4
    (see docs/superpowers/plans/2026-04-27-p1-capability-snapshot.md).
    """

    def __init__(self, device=None) -> None:
        # The device argument is retained for call-site compatibility
        # with the previous multi-model API, but is unused now.
        self.list = None
        self.lidar_navigation = True
        self.multi_floor_map = False        # snapshot: g2408 has one lawn
        self.ai_detection = True
        self.customized_cleaning = False
        # ... fill every attribute from the snapshot, in order ...
        self.disable_sensor_cleaning = False  # snapshot: g2408 has no cleaning sensor
        # ... etc ...
        self.robot_type = RobotType.LIDAR

    def refresh(self, device_capabilities=None) -> None:
        """No-op preserved for call-site compatibility.

        Capability flags are now constants for g2408. This method
        accepts but ignores `device_capabilities` so existing
        callers do not need to change.
        """
```

(Use the snapshot dict from the doc to fill every attribute.
Don't omit any attribute that appears in the snapshot. If the
snapshot has an attribute the existing class doesn't, that's a
bug in the snapshot — re-capture.)

- [ ] **Step 3: Remove the snapshot-logging block from 4.1.1**

Delete the block you added at the end of `refresh()` in step 4.1.1.
The snapshot doc preserves the value; the runtime log line is no
longer needed.

- [ ] **Step 4: Run the regression test**

Run: `pytest tests/dreame/test_capability_g2408_snapshot.py -v`
Expected: PASS. (The test now instantiates the class with
`device=None` and the values come from the constants directly.)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -x`
Expected: PASS.

- [ ] **Step 6: Smoke-test the integration loads**

```bash
python -c "from custom_components.dreame_a2_mower.dreame.types import DreameMowerDeviceCapability; c = DreameMowerDeviceCapability(); c.refresh(); print(c.lidar_navigation, c.ai_detection)"
```

Expected: prints `True True` (or whatever the snapshot says).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/dreame/types.py \
    tests/dreame/test_capability_g2408_snapshot.py
git commit -m "$(cat <<'EOF'
P1.4.3: flatten DreameMowerDeviceCapability to g2408 constants

Replaces the runtime-decode-and-merge of DREAME_MODEL_CAPABILITIES
with frozen constants captured from a live g2408 snapshot. The
integration is permanently single-model (per spec §8 resolution 3),
so per-model lookups add no value.

Adds tests/dreame/test_capability_g2408_snapshot.py as a regression
contract.

Spec: docs/superpowers/specs/2026-04-27-pre-launch-review-design.md P1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Push**

Run: `git push origin main`

### Task 4.4: Delete the now-unused `DREAME_MODEL_CAPABILITIES` blob

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/const.py` — delete
  the `DREAME_MODEL_CAPABILITIES` constant (line 340, ~5 KB
  base64 string).
- Modify: `custom_components/dreame_a2_mower/dreame/__init__.py` —
  drop `DREAME_MODEL_CAPABILITIES` re-export if present.
- Modify: `custom_components/dreame_a2_mower/dreame/device.py:95` —
  drop the `DREAME_MODEL_CAPABILITIES` import.
- Modify: `custom_components/dreame_a2_mower/dreame/device.py:1455` —
  drop the `json.loads(zlib.decompress(base64.b64decode(...)))`
  call and the `self.capability.refresh(...)` call site that
  consumed its result.

- [ ] **Step 1: Read each site**

Read each of the four locations to confirm exact line numbers
(line numbers may have shifted slightly after phase 1–3 commits).

- [ ] **Step 2: Delete `DREAME_MODEL_CAPABILITIES` from const.py**

Find the line that starts `DREAME_MODEL_CAPABILITIES: Final = "..."`
and delete the entire assignment (one logical line, may be wrapped
across multiple physical lines). Also delete any
`# DREAME_MODEL_CAPABILITIES: Final = (` comment block immediately
above it.

If `DeviceCapability` enum is also defined in const.py and used only
by the deleted decode call, delete it too. Verify with:

```bash
grep -n "DeviceCapability" custom_components/dreame_a2_mower/dreame/const.py
grep -rn "from .const import .*DeviceCapability\|DeviceCapability\." --include="*.py" .
```

If the only references are the definition + the deleted decode loop,
delete the enum.

- [ ] **Step 3: Drop the import in device.py**

Read `dreame/device.py` line 95 area to find the import block; remove
`DREAME_MODEL_CAPABILITIES,` from the `from .const import (...)` block.

- [ ] **Step 4: Delete the runtime decode call in device.py**

Read lines 1450–1460 of `device.py` to capture the surrounding context.
The body looks like:

```python
            self.capability.refresh(
                json.loads(zlib.decompress(base64.b64decode(DREAME_MODEL_CAPABILITIES), zlib.MAX_WBITS | 32))
            )
```

Replace with:

```python
            self.capability.refresh()
```

(`refresh()` is now a no-op preserved for compatibility per
4.3.2.)

- [ ] **Step 5: Drop unused imports in device.py**

`json`, `zlib`, `base64` may have been imported only for this decode.
Check:

```bash
grep -n "^import json\|^import zlib\|^import base64\|json\.\|zlib\.\|base64\." \
    custom_components/dreame_a2_mower/dreame/device.py | head -30
```

For each of `json`, `zlib`, `base64` whose only usage was the decode
just removed, drop the `import` line. (If they're used elsewhere,
leave them.)

- [ ] **Step 6: Drop the `dreame/__init__.py` re-export**

```bash
grep -n "DREAME_MODEL_CAPABILITIES" custom_components/dreame_a2_mower/dreame/__init__.py
```

If found, delete the line.

- [ ] **Step 7: Run the regression test**

Run: `pytest tests/dreame/test_capability_g2408_snapshot.py -v`
Expected: PASS. The capability values are now sourced exclusively
from the constants in 4.3.2 — no blob to decode.

- [ ] **Step 8: Run the full test suite**

Run: `pytest -x`
Expected: PASS.

- [ ] **Step 9: Smoke-test the integration loads**

```bash
python -c "from custom_components.dreame_a2_mower.dreame.types import DreameMowerDeviceCapability; c = DreameMowerDeviceCapability(); c.refresh(); print('ok')"
```

Expected: `ok`.

- [ ] **Step 10: Commit**

```bash
git add custom_components/dreame_a2_mower/dreame/
git commit -m "$(cat <<'EOF'
P1.4.4: delete DREAME_MODEL_CAPABILITIES blob and decode site

The blob is the ~5 KB base64-zlib-encoded multi-model capability
registry from the upstream vacuum integration. After P1.4.3
flattened the capability values to g2408 constants, the blob and
its decode call are unreachable.

Drops:
- DREAME_MODEL_CAPABILITIES constant (dreame/const.py)
- DeviceCapability enum (if usage was solely the decode loop)
- Re-export from dreame/__init__.py
- json/zlib/base64 imports in dreame/device.py if unused elsewhere
- The decode-and-refresh-with-result call at device.py:~1455

Spec: docs/superpowers/specs/2026-04-27-pre-launch-review-design.md P1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 11: Push**

Run: `git push origin main`

---

## Phase 5 — Drop `disable_sensor_cleaning` dead branches

After phase 4, `capability.disable_sensor_cleaning` is a static
constant (per the snapshot it should be `False` for g2408 — the
integration treats g2408 as having a meaningful sensor-dirty signal).
With the value now compile-time-known, every
`if not self.capability.disable_sensor_cleaning:` branch is always
taken, and every `exists_fn=lambda d: not d.capability.disable_sensor_cleaning`
is the constant `True`.

If the snapshot value is `False`, simplify the call sites by deleting
the always-True branch. If the snapshot value is `True`, the call
sites become dead code instead — delete them and any associated
entities.

### Task 5.1: Verify snapshot value of `disable_sensor_cleaning`

- [ ] **Step 1: Read the constant from the flattened class**

```bash
grep -n "self\.disable_sensor_cleaning" custom_components/dreame_a2_mower/dreame/types.py
```

Expected: a single line in `__init__` like
`self.disable_sensor_cleaning = False  # snapshot: g2408 has no cleaning sensor`
or `self.disable_sensor_cleaning = True`.

Note the value. The branches below depend on it.

### Task 5.2: Simplify call sites based on the snapshot

**Files:**
- Modify (always): `custom_components/dreame_a2_mower/sensor.py:392`
- Modify (always): `custom_components/dreame_a2_mower/sensor.py:400`
- Modify (always): `custom_components/dreame_a2_mower/button.py:330`
- Modify (always): `custom_components/dreame_a2_mower/coordinator.py:590`
- Modify (always): `custom_components/dreame_a2_mower/dreame/device.py:2013`
- Modify (always): `custom_components/dreame_a2_mower/dreame/device.py:4046`
- Modify (always): `custom_components/dreame_a2_mower/dreame/device.py:8076`

If snapshot value is **False** (always-not-disabled = always-on):

- [ ] **Step F1: Drop `exists_fn` from sensor.py:392, 400 and button.py:330**

For each entity description, the `exists_fn=lambda description, device:
not device.capability.disable_sensor_cleaning,` argument always
returns True. Delete the `exists_fn=` argument from the description
constructor (and the trailing comma if necessary).

- [ ] **Step F2: Simplify `if not capability.disable_sensor_cleaning:` blocks**

For coordinator.py:590, device.py:2013, 4046, 8076:

```python
if not self.capability.disable_sensor_cleaning:
    <body>
```

→

```python
<body>
```

(de-indent the body by one level).

- [ ] **Step F3: Run full test suite**

Run: `pytest -x`
Expected: PASS.

- [ ] **Step F4: Commit**

```bash
git add custom_components/dreame_a2_mower/
git commit -m "$(cat <<'EOF'
P1.5: drop always-True disable_sensor_cleaning gates

After P1.4 flattened capability flags to g2408 constants,
disable_sensor_cleaning is statically False. Every gate of the
form `if not capability.disable_sensor_cleaning:` was always
taken; every `exists_fn` returning the same expression was
always True. Both forms become dead noise.

Removes the gates and de-indents bodies; drops exists_fn from
sensor and button descriptors.

Spec: docs/superpowers/specs/2026-04-27-pre-launch-review-design.md P1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

If snapshot value is **True** (always-disabled = always-off):

- [ ] **Step T1: Audit each gated entity**

For each `exists_fn=lambda…not …disable_sensor_cleaning` site, the
entity is currently always-not-created. So the entity has been
invisible to users for the duration of this snapshot. Confirm with
the user that the entity should be permanently deleted (per the
spec's "no §2.1 citation = delete" rule, an unreachable entity is
also a deletion candidate).

- [ ] **Step T2: Delete the entity descriptor**

For sensor.py:392, 400 and button.py:330: delete the entire
`EntityDescription(...)` block. The dropped names should be
recorded in the commit message so the entity audit (P2) doesn't
re-introduce them.

- [ ] **Step T3: Delete the dead-branch bodies**

For coordinator.py:590, device.py:2013, 4046, 8076:

```python
if not self.capability.disable_sensor_cleaning:
    <body>
```

→ delete the whole `if` block (the body never runs).

- [ ] **Step T4: Run full test suite + commit + push**

Same as F3/F4 with adjusted commit message ("delete unreachable
sensor-cleaning entities and gates").

---

## Self-review checklist

Run before declaring P1 complete:

- [ ] `pytest -x` passes from a clean checkout.
- [ ] `python -c "from custom_components.dreame_a2_mower import *"`
  imports without error.
- [ ] HA reloads the integration successfully against a live g2408.
- [ ] `tests/dreame/test_capability_g2408_snapshot.py` passes.
- [ ] No reference remains to `DustCollection`,
  `AutoEmptyStatus`, `SelfCleanArea`, `FloorMaterial[Direction]`,
  `FLOOR_MATERIAL_*`, `ATTR_FLOOR_MATERIAL_DIRECTION`,
  `DREAME_MODEL_CAPABILITIES`, or (snapshot-dependent)
  `disable_sensor_cleaning` gates.
- [ ] `grep -rn "sweeping" --include="*.py" .` returns nothing in
  the integration's own source. (Translation files may still have
  it temporarily; that's a different concern.)
- [ ] All commits pushed to `origin/main`.

## What this plan does NOT do

Out-of-scope for P1, deferred to later plans:

- The full per-property audit (`CUSTOMIZED_CLEANING`,
  `SHORTCUTS`, `MULTI_FLOOR_MAP`, `CRUISE_SCHEDULE`,
  `TANK_FILTER_LEFT`, `STREAM_PROPERTY`, `STREAM_SPACE`, etc.)
  goes to **P2 entity audit** — each one needs a §2.1 citation
  check, and some may turn out to be supported on g2408 despite
  vacuum-sounding names.
- The encrypted-blob map decoder branches in `dreame/map.py`
  (`MapFrameType.I/P`, `_decode_map_partial`,
  `_queue_partial_map`) require correctness analysis (the cloud
  JSON path may share infrastructure) — defer to **P5b
  map.py decomposition**.
- The full coverage-tier reorganization of entities (production /
  observability / experimental-flagged) goes to **P2**.

---

## Followup tasks

After this plan lands and is pushed:

- [ ] Tag the commit range `git log --oneline 2588e6d..HEAD` for
  the user's notes (no formal release tag — per spec §8 we don't
  bump versions during the cleanup).
- [ ] Update `MEMORY.md` `feedback_cleanup_push_cadence.md` with
  total commits + LOC reduction observed.
- [ ] Move on to writing the P2 plan — the post-P1 file:line
  numbers will inform P2's entity audit.
