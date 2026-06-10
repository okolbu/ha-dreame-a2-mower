# Phase B — Core-control verdicts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the capture-confirmed routed opcodes to pause/stop/dock/recharge so they reach the mower (they were 80001 no-ops via direct siid:5), flip those buttons to DEVICE_WRITABLE, and add Resume (o=5) + Cancel-dock-return (o=13) buttons.

**Architecture:** `dispatch_action` uses `routed_action(o)` when an `ACTION_TABLE` entry has `routed_o`, else falls back to the direct `action(siid,aiid)` path (which returns 80001 on g2408). Adding `routed_o` to the existing pause/stop/dock entries fixes them; two new `MowerAction`s + buttons add resume/cancel-dock-return. Verdicts then flip `_U → _W`.

**Tech Stack:** Python, vanilla pytest venv (`/data/claude/homeassistant/.venv-vanilla/bin/python`), inventory validators.

**Spec:** `docs/superpowers/specs/2026-06-10-phase-b-core-control-verdicts-design.md`

**Reference (capture 2026-06-09, all `verified` in inventory Phase 0):** routed `s2.a50 {m:"a",o:N}` — stop=3, pause=4, resume=5, dock/recharge=6, cancel-dock-return=13. All no-payload.

**Current `ACTION_TABLE` entries (mower/actions.py ~L260-263):**
```python
    MowerAction.PAUSE: {"siid": 5, "aiid": 4},
    MowerAction.DOCK: {"siid": 5, "aiid": 3},
    MowerAction.RECHARGE: {"siid": 5, "aiid": 3},  # same wire call as DOCK
    MowerAction.STOP: {"siid": 5, "aiid": 2},
```
**Button pattern:** `_DreameA2ActionButton.__init__(coordinator, unique_suffix, name, icon)` sets `self._control_mode = resolve_control_mode(platform="button", key=unique_suffix)`; subclass sets `self._action`; `async_press` calls `coordinator.dispatch_action(self._action, self._params or {})`.

**Conventions:** Python = `/data/claude/homeassistant/.venv-vanilla/bin/python`. Stage by explicit path (never `git add -A`). Co-Authored-By trailer for Claude Opus 4.8. Branch is `phase-b-core-control-verdicts`.

---

### Task 1: ACTION_TABLE — routed_o + RESUME + CANCEL_DOCK_RETURN

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/actions.py`
- Test: `tests/unit/test_core_control_opcodes.py` (create)

- [ ] **Step 1: Write the failing test** (`tests/unit/test_core_control_opcodes.py`):

```python
from custom_components.dreame_a2_mower.mower.actions import ACTION_TABLE, MowerAction


def test_pause_stop_dock_have_routed_opcodes():
    assert ACTION_TABLE[MowerAction.PAUSE]["routed_o"] == 4
    assert ACTION_TABLE[MowerAction.STOP]["routed_o"] == 3
    assert ACTION_TABLE[MowerAction.DOCK]["routed_o"] == 6
    assert ACTION_TABLE[MowerAction.RECHARGE]["routed_o"] == 6


def test_resume_and_cancel_dock_return_exist():
    assert ACTION_TABLE[MowerAction.RESUME]["routed_o"] == 5
    assert ACTION_TABLE[MowerAction.CANCEL_DOCK_RETURN]["routed_o"] == 13
    # no-payload routed actions: no payload_fn
    assert "payload_fn" not in ACTION_TABLE[MowerAction.RESUME]
    assert "payload_fn" not in ACTION_TABLE[MowerAction.CANCEL_DOCK_RETURN]
```

- [ ] **Step 2: Run, expect fail**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_core_control_opcodes.py -q`
Expected: FAIL — no `routed_o` on PAUSE/STOP/DOCK/RECHARGE; `RESUME`/`CANCEL_DOCK_RETURN` enum members don't exist.

- [ ] **Step 3: Add the enum members** to `MowerAction` (in `mower/actions.py`, after `STOP = auto()`):

```python
    RESUME = auto()  # op=5 continue a paused mow
    CANCEL_DOCK_RETURN = auto()  # op=13 cancel an in-progress dock-return (distinct from STOP)
```

- [ ] **Step 4: Add routed_o to the 4 existing entries + add the 2 new entries.** Replace the PAUSE/DOCK/RECHARGE/STOP block:

```python
    MowerAction.PAUSE: {"siid": 5, "aiid": 4, "routed_o": 4},
    MowerAction.DOCK: {"siid": 5, "aiid": 3, "routed_o": 6},
    MowerAction.RECHARGE: {"siid": 5, "aiid": 3, "routed_o": 6},  # same wire call as DOCK
    MowerAction.STOP: {"siid": 5, "aiid": 2, "routed_o": 3},
    # RESUME — op=5 continue a paused mow (app capture 2026-06-09, no payload).
    MowerAction.RESUME: {"siid": 5, "aiid": 1, "routed_o": 5},
    # CANCEL_DOCK_RETURN — op=13 cancel an in-progress dock-return; distinct
    # from STOP (op=3). App capture 2026-06-09, no payload.
    MowerAction.CANCEL_DOCK_RETURN: {"siid": 5, "aiid": 1, "routed_o": 13},
```
(The `siid`/`aiid` on RESUME/CANCEL are nominal fallbacks; `routed_o` is what dispatch uses. Keeping `siid`/`aiid` matches the existing entries' shape and the `ActionEntry` TypedDict requiring them.)

- [ ] **Step 5: Run, expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/unit/test_core_control_opcodes.py -q`
Expected: PASS.

- [ ] **Step 6: Add a dispatch-routing test** to the same file (assert dispatch_action uses the routed path):

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin


def _coord():
    c = _WritesMixin()
    c._cloud = SimpleNamespace(routed_action=MagicMock(return_value={"out": [{"r": 0}]}),
                               action=MagicMock(return_value={"out": [{"r": 0}]}))
    async def _exec(fn, *a):
        return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    return c


@pytest.mark.asyncio
@pytest.mark.parametrize("action,op", [
    (MowerAction.PAUSE, 4), (MowerAction.STOP, 3), (MowerAction.DOCK, 6),
    (MowerAction.RECHARGE, 6), (MowerAction.RESUME, 5), (MowerAction.CANCEL_DOCK_RETURN, 13),
])
async def test_dispatch_uses_routed_opcode(action, op):
    c = _coord()
    await c.dispatch_action(action, {})
    c._cloud.routed_action.assert_called_once()
    assert c._cloud.routed_action.call_args[0][0] == op
    c._cloud.action.assert_not_called()  # NOT the direct 80001 path
```
Run it; if `dispatch_action` needs more coordinator attrs (e.g. `_active_map_id`), add minimal SimpleNamespace fields until it runs (these actions take no payload_fn so the path is short). Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/actions.py tests/unit/test_core_control_opcodes.py
git commit -m "feat(b): routed opcodes for pause/stop/dock/recharge + RESUME(5)/CANCEL_DOCK_RETURN(13)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Resume + Cancel-dock-return buttons (self-consistent: code + verdict + inventory together)

**Files:**
- Modify: `custom_components/dreame_a2_mower/button.py`
- Modify: `custom_components/dreame_a2_mower/control_honesty.py`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Test: `tests/integration/test_core_control_buttons.py` (create)

The new buttons call `resolve_control_mode(platform="button", key=<suffix>)` in `__init__`, which raises `KeyError` if the key isn't in `CONTROL_MODES` — so the CONTROL_MODES entries AND the entity-inventory entries must land in this same task (keeps the code-sync test green).

- [ ] **Step 1: Add the two control_mode entries** in `control_honesty.py` `CONTROL_MODES` (near the other `button.dreame_a2_mower_*` entries), both `_W`:

```python
    "button.dreame_a2_mower_resume_mowing": _W,
    "button.dreame_a2_mower_cancel_dock_return": _W,
```

- [ ] **Step 2: Add the button classes** in `button.py` (after `DreameA2StopMowingButton`, mirroring the `_DreameA2ActionButton` pattern):

```python
class DreameA2ResumeMowingButton(_DreameA2ActionButton):
    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "resume_mowing", "Resume", "mdi:play-circle")
        self._action = MowerAction.RESUME


class DreameA2CancelDockReturnButton(_DreameA2ActionButton):
    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "cancel_dock_return", "Cancel dock return", "mdi:home-export-outline")
        self._action = MowerAction.CANCEL_DOCK_RETURN
```
Confirm `MowerAction` is imported in button.py (it is — used by the other buttons). Match the exact `__init__` signature/type hints of the sibling classes.

- [ ] **Step 3: Register both** in `async_setup_entry`'s `entities` list (after `DreameA2RechargeButton(coordinator),`):

```python
        DreameA2ResumeMowingButton(coordinator),
        DreameA2CancelDockReturnButton(coordinator),
```

- [ ] **Step 4: Add entity-inventory entries** for the 2 new buttons in `entity-inventory.yaml`. Mirror an existing button entry's schema (e.g. the `recharge`/`stop_mowing` entry) — `control_mode: device_writable`, source = routed action op (resume=5 / cancel_dock_return=13), `last_verified: "2026-06-10"`, a verification citing `app-mitm:2026-06-09-settings-sweep`. Find the schema:
```
grep -n "stop_mowing\|recharge\|control_mode\|button\." custom_components/dreame_a2_mower/entity-inventory.yaml | head
```

- [ ] **Step 5: Write the test** (`tests/integration/test_core_control_buttons.py`):

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from custom_components.dreame_a2_mower import button as btn
from custom_components.dreame_a2_mower.mower.actions import MowerAction


def _coord():
    return SimpleNamespace(dispatch_action=AsyncMock())


@pytest.mark.asyncio
async def test_resume_button_dispatches_resume():
    b = btn.DreameA2ResumeMowingButton(_coord())
    await b.async_press()
    b.coordinator.dispatch_action.assert_awaited_once()
    assert b.coordinator.dispatch_action.call_args[0][0] == MowerAction.RESUME


@pytest.mark.asyncio
async def test_cancel_dock_return_button_dispatches():
    b = btn.DreameA2CancelDockReturnButton(_coord())
    await b.async_press()
    assert b.coordinator.dispatch_action.call_args[0][0] == MowerAction.CANCEL_DOCK_RETURN


def test_new_buttons_are_writable():
    from custom_components.dreame_a2_mower.control_honesty import resolve_control_mode, ControlMode
    assert resolve_control_mode(platform="button", key="resume_mowing") == ControlMode.DEVICE_WRITABLE
    assert resolve_control_mode(platform="button", key="cancel_dock_return") == ControlMode.DEVICE_WRITABLE
```
(If `DreameA2ResumeMowingButton(coord)` construction needs more than a bare coordinator — e.g. it reads `coordinator.cloud_state` in `__init__` — adapt with a minimal SimpleNamespace, or use `object.__new__` + set `_action`/`coordinator` like `tests/integration/test_cfg_switch_writes.py`.)

- [ ] **Step 6: Run + gates**

Run:
```
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_core_control_buttons.py -q
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/ -q
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
```
Expected: button tests pass; control_mode code-sync green; entity audit `missing from inventory: 0`.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/button.py custom_components/dreame_a2_mower/control_honesty.py custom_components/dreame_a2_mower/entity-inventory.yaml tests/integration/test_core_control_buttons.py
git commit -m "feat(b): add Resume (o=5) + Cancel-dock-return (o=13) buttons

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Flip pause/stop/recharge verdicts _U → _W

**Files:**
- Modify: `custom_components/dreame_a2_mower/control_honesty.py`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify: existing tests asserting these buttons are `_U`/provisional

- [ ] **Step 1: Flip in `control_honesty.py`** — change these from `_U` to `_W`:
```python
    "button.dreame_a2_mower_pause_mowing": _W,
    "button.dreame_a2_mower_stop_mowing": _W,
    "button.dreame_a2_mower_recharge": _W,
```
Leave `button.dreame_a2_mower_lock_bot` and `button.dreame_a2_mower_generate_3dmap` as `_U`.

- [ ] **Step 2: Mirror** the 3 control_mode → `device_writable` in `entity-inventory.yaml`.

- [ ] **Step 3: Update stale tests.** Find tests asserting these 3 are provisional/`_U`/`device_write_unproven`:
```
grep -rnE "provisional|DEVICE_WRITE_UNPROVEN|device_write_unproven|_U\b" tests/ | grep -iE "pause_mowing|stop_mowing|recharge"
```
Update each to expect `device_writable` / `provisional False`. (Do NOT touch lock_bot/generate_3dmap assertions — they stay unproven.)

- [ ] **Step 4: Gates**

Run:
```
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/ -q
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "button or control_honesty or control_mode" -q
```
Expected: code-sync green; button/honesty tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/control_honesty.py custom_components/dreame_a2_mower/entity-inventory.yaml tests/
git commit -m "feat(b): flip pause/stop/recharge buttons to DEVICE_WRITABLE

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Inventory fact-discipline + TODO

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify: `docs/research/knowledge-gaps.md`

- [ ] **Step 1: inventory.yaml** — the opcodes 3/4/5/6/13 are already `verified` (Phase 0). Append a `status: verified` verification (date 2026-06-10) to the relevant opcode entries (or the opcode-map entry) recording that the integration now WIRES them via `ACTION_TABLE.routed_o` for pause/stop/dock/recharge/resume/cancel-dock-return, replacing the direct `siid:5/aiid:N` path that returned 80001. Evidence `app-mitm:2026-06-09-settings-sweep`. Bump `last_seen: "2026-06-10"`. (No retraction unless you find a prior claim that's literally false — e.g. one asserting these opcodes don't exist / aren't honored; if so, retract verbatim.)

- [ ] **Step 2: entity-inventory.yaml** — for pause_mowing/stop_mowing/recharge append a verification: now wired + writable via routed o=4/3/6 (was 80001 no-op via direct siid:5). Bump `last_verified`.

- [ ] **Step 3: TODO in `knowledge-gaps.md`** — add `[UNKNOWN — to capture]` entries:
  - `lock_bot` (routed o=12): no lock button exists in the app; the backend may add support later; on current g2408 firmware it is accepted (r=0) but no-effect. Entity stays DEVICE_WRITE_UNPROVEN.
  - `generate_3dmap` (routed o=10): an unknown trigger snapshots the 3D map (multiple versions of the same map are observed in our data); capture step = identify what fires the snapshot. Entity stays DEVICE_WRITE_UNPROVEN.
  Add a matching `open_questions` line to the relevant inventory.yaml opcode entries (o12/o10) if not already present.

- [ ] **Step 4: Validate**

Run:
```
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/audit_outstanding_retractions.py
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/ -q
```
Expected: validator ok; entity audit 0 missing; retraction audit clean; inventory tests green.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml docs/research/knowledge-gaps.md
git commit -m "inventory(b): record routed core-control wiring; TODO lock_bot/generate_3dmap open questions

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Full suite + final verification

**Files:** none (verification only)

- [ ] **Step 1: Full suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: 0 failures; 4 skipped; passed count ≥ prior baseline + new B tests.

- [ ] **Step 2: Inventory gates**

Run:
```
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_audit.py --consistency
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/audit_outstanding_retractions.py
```
Expected: all clean.

- [ ] **Step 3: Confirm verdict state.** Verify: pause_mowing/stop_mowing/recharge/resume_mowing/cancel_dock_return are `device_writable`; lock_bot/generate_3dmap remain `device_write_unproven`. Quick check:
```
/data/claude/homeassistant/.venv-vanilla/bin/python -c "
from custom_components.dreame_a2_mower.control_honesty import resolve_control_mode as r
for k in ['pause_mowing','stop_mowing','recharge','resume_mowing','cancel_dock_return']:
    print(k, r(platform='button', key=k))
for k in ['lock_bot','generate_3dmap']:
    print(k, r(platform='button', key=k))
"
```
Expected: first five `DEVICE_WRITABLE`; last two `DEVICE_WRITE_UNPROVEN`.

- [ ] **Step 4: Report** final pass/skip counts, the 5 writable + 2 still-unproven controls, and confirm START (o=100) was untouched.
