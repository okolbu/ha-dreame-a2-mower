# Patrol Session-Type Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record a session's task type reliably at session start (from MQTT clues, ungated by session-active state and persisted across boot) so patrols stop mis-typing as `maintenance_run` and finalizing early.

**Architecture:** A new coordinator latch `_pending_task_op` captures every `s2p50` op echo unconditionally; `begin_session()` seeds `live_map.last_task_op` from it; a tiny `pending_task_op.json` sidecar persists it across a restart that straddles the op-echo→begin window; and `classify_session_type` warns when it falls through to `maintenance_run` with no positive signal.

**Tech Stack:** Python 3.13 (stubbed-HA vanilla venv), pytest. Test interpreter: `/data/claude/homeassistant/.venv-vanilla/bin/python`. Branch: `fix/patrol-session-type-recording` (already created; spec committed).

**Spec:** `docs/superpowers/specs/2026-06-04-patrol-session-type-recording-design.md`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `custom_components/dreame_a2_mower/archive/session.py` | Session archive + in-progress sidecar I/O | Add `pending_task_op.json` read/write/delete (mirrors `*_in_progress`). |
| `custom_components/dreame_a2_mower/coordinator/_core.py` | Coordinator `__init__` shared state | Add `self._pending_task_op` attribute. |
| `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` | MQTT routing + state-update glue | Add `_latch_task_op`, `_handle_task_op_echo`, `_seed_session_type_from_pending`; wire them into the `s2p50` echo block and after `begin_session()`. |
| `custom_components/dreame_a2_mower/coordinator/_session.py` | Restore / finalize | Read sidecar on restore; delete sidecar on finalize. |
| `custom_components/dreame_a2_mower/live_map/classify.py` | Finalize-stage classifier | Warn on no-signal `maintenance_run` fall-through. |
| `custom_components/dreame_a2_mower/inventory.yaml` | Wire/protocol truth | Update o108 `open_question` to note the recording fix (presumed until live-confirmed). |

Test files (created/extended):
- `tests/archive/test_session.py` — sidecar I/O.
- `tests/coordinator/test_pending_task_op.py` (new) — latch / echo-parse / seed.
- `tests/coordinator/test_pending_task_op_restore_clear.py` (new) — restore + finalize-clear.
- `tests/live_map/test_classify_session_type.py` — no-signal warning.
- `tests/integration/test_patrol_session_recording.py` (new) — dock-start race reproduction.

---

## Task 1: Sidecar I/O on SessionArchive

**Files:**
- Modify: `custom_components/dreame_a2_mower/archive/session.py` (constants near `:42`, new methods after `delete_in_progress` `:432`)
- Test: `tests/archive/test_session.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/archive/test_session.py`:

```python
def test_pending_task_op_roundtrip(tmp_path):
    from custom_components.dreame_a2_mower.archive.session import SessionArchive
    arc = SessionArchive(tmp_path)
    assert arc.read_pending_op() is None
    arc.write_pending_op(107)
    assert arc.read_pending_op() == 107
    arc.write_pending_op(108)          # last-wins, no window
    assert arc.read_pending_op() == 108
    arc.delete_pending_op()
    assert arc.read_pending_op() is None


def test_pending_task_op_bad_file_returns_none(tmp_path):
    from custom_components.dreame_a2_mower.archive.session import (
        PENDING_OP_NAME,
        SessionArchive,
    )
    arc = SessionArchive(tmp_path)
    (tmp_path / PENDING_OP_NAME).write_text("not json{")
    assert arc.read_pending_op() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/archive/test_session.py::test_pending_task_op_roundtrip -v`
Expected: FAIL — `AttributeError: 'SessionArchive' object has no attribute 'read_pending_op'`.

- [ ] **Step 3: Add the constant**

In `archive/session.py`, after `IN_PROGRESS_MAX_AGE_S = 12 * 3600` (`:44`):

```python
PENDING_OP_NAME = "pending_task_op.json"
```

- [ ] **Step 4: Add the three methods**

In `archive/session.py`, immediately after `delete_in_progress` (ends `:441`):

```python
    # ------------------ pending task-op sidecar ------------------

    def _pending_op_path(self) -> Path:
        return self._root / PENDING_OP_NAME

    def read_pending_op(self) -> int | None:
        """Load the persisted pending task op, or None.

        The op echo (s2p50) is a one-shot command-ack that never replays, so
        it is persisted to survive a restart that lands between the echo and
        begin_session. No CRC/age guard: a single int, cleared on finalize.
        """
        path = self._pending_op_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return int(data["op"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def write_pending_op(self, op: int) -> None:
        """Persist the pending task op (last-wins, no window)."""
        path = self._pending_op_path()
        try:
            path.write_text(json.dumps({"op": int(op)}))
        except (OSError, ValueError, TypeError) as ex:
            _LOGGER.warning("SessionArchive: failed to write pending op: %s", ex)

    def delete_pending_op(self) -> None:
        try:
            self._pending_op_path().unlink(missing_ok=True)
        except OSError:
            pass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/archive/test_session.py -v`
Expected: PASS (both new tests + existing archive tests green).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/archive/session.py tests/archive/test_session.py
git commit -m "feat(archive): pending_task_op.json sidecar I/O"
```

---

## Task 2: Coordinator latch + echo-parse helpers

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py:148` (add attr beside `_prev_s2p56_empty`)
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` (add helpers on `_MqttHandlersMixin`, after `capture_session_type_signals`'s class methods — place near `_on_state_update`)
- Test: `tests/coordinator/test_pending_task_op.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/coordinator/test_pending_task_op.py`:

```python
"""Pending task-op latch: capture every s2p50 op echo ungated, write sidecar."""
from __future__ import annotations

from custom_components.dreame_a2_mower.archive.session import SessionArchive
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def _coord(tmp_path):
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = SessionArchive(tmp_path)
    c.live_map = LiveMapState()
    c._pending_task_op = None
    return c


def test_latch_sets_attr_and_sidecar_ungated_by_active(tmp_path):
    c = _coord(tmp_path)
    assert not c.live_map.is_active()          # no session yet
    c._latch_task_op(107)
    assert c._pending_task_op == 107
    assert c.session_archive.read_pending_op() == 107


def test_latch_last_wins_no_window(tmp_path):
    c = _coord(tmp_path)
    c._latch_task_op(108)
    c._latch_task_op(102)
    assert c._pending_task_op == 102
    assert c.session_archive.read_pending_op() == 102


def test_handle_task_op_echo_parses_d_o(tmp_path):
    c = _coord(tmp_path)
    c._handle_task_op_echo({"d": {"o": 107}})
    assert c._pending_task_op == 107


def test_handle_task_op_echo_parses_flat_o(tmp_path):
    c = _coord(tmp_path)
    c._handle_task_op_echo({"o": 108})
    assert c._pending_task_op == 108


def test_handle_task_op_echo_ignores_missing_op(tmp_path):
    c = _coord(tmp_path)
    c._handle_task_op_echo({"d": {}})
    assert c._pending_task_op is None
    assert c.session_archive.read_pending_op() is None


def test_handle_task_op_echo_when_active_sets_last_task_op(tmp_path):
    c = _coord(tmp_path)
    c.live_map.begin_session(1000)             # active mid-session
    c._handle_task_op_echo({"d": {"o": 102}})
    assert c.live_map.last_task_op == 102       # immediate set for live session
    assert c._pending_task_op == 102
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_pending_task_op.py -v`
Expected: FAIL — `AttributeError: ... has no attribute '_latch_task_op'`.

- [ ] **Step 3: Add the `__init__` attribute**

In `coordinator/_core.py`, immediately after `self._prev_s2p56_empty: bool | None = None` (`:148`):

```python
        # Pending task op (s2p50 echo) latched ungated by session-active so a
        # patrol/mow/etc. commanded from the dock is recorded before
        # begin_session exists to hold it. Seeded into live_map.last_task_op at
        # begin_session; persisted via the pending_task_op sidecar. See
        # docs/superpowers/specs/2026-06-04-patrol-session-type-recording-design.md
        self._pending_task_op: int | None = None
```

- [ ] **Step 4: Add the helpers**

In `coordinator/_mqtt_handlers.py`, inside `_MqttHandlersMixin`, just above `def _on_state_update` (`:358`):

```python
    def _latch_task_op(self, op: int) -> None:
        """Record the latest task op (s2p50 echo), ungated by session-active.

        Persisted to the sidecar (last-wins, no window) so it survives a
        restart that lands before begin_session. If a session is already
        active, also set last_task_op directly so a mid-session op change
        (e.g. a new command without docking) is reflected immediately.
        """
        self._pending_task_op = int(op)
        try:
            self.session_archive.write_pending_op(int(op))
        except Exception:  # pragma: no cover - sidecar write is best-effort
            LOGGER.exception("_latch_task_op: sidecar write failed")
        if self.live_map.is_active():
            self.live_map.last_task_op = int(op)

    def _handle_task_op_echo(self, value: Any) -> None:
        """Extract the op from an s2p50 value and latch it.

        s2p50 value is `{"d": {"o": <op>, ...}, ...}`; some payloads carry the
        op flat as `{"o": <op>}`. Non-dict / missing-op payloads are ignored.
        """
        if not isinstance(value, dict):
            return
        inner = value.get("d")
        src = inner if isinstance(inner, dict) else value
        op = src.get("o")
        if op is None:
            return
        try:
            self._latch_task_op(int(op))
        except (TypeError, ValueError):
            return

    def _seed_session_type_from_pending(self) -> None:
        """Seed live_map.last_task_op from the pending latch at session birth.

        begin_session() nulls last_task_op; this re-stamps it from the op echo
        that arrived before the session existed. No-op when nothing is latched
        or no session is active.
        """
        if self._pending_task_op is not None and self.live_map.is_active():
            self.live_map.last_task_op = self._pending_task_op
```

(`Any` and `LOGGER` are already imported in this module.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_pending_task_op.py -v`
Expected: PASS (all 6).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_core.py \
        custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py \
        tests/coordinator/test_pending_task_op.py
git commit -m "feat(coordinator): _pending_task_op latch + s2p50 echo parse"
```

---

## Task 3: Seed at begin_session + wire the echo handler

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py:406` (call seed after `begin_session`) and `:284-302` (route echo through `_handle_task_op_echo`)
- Test: `tests/coordinator/test_pending_task_op.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/coordinator/test_pending_task_op.py`:

```python
from custom_components.dreame_a2_mower.mower.state import MowerState


def _coord_for_state_update(tmp_path):
    from unittest.mock import MagicMock
    c = _coord(tmp_path)
    c.data = MowerState()
    c._prev_task_state = None
    c._real_task_state_observed = True
    c._begin_live_stream = lambda: None
    c._fire_lifecycle = lambda *a, **k: None
    hass = MagicMock()
    hass.async_create_task = lambda *a, **k: None
    c.hass = hass
    # build_settings_snapshot_v2 reads many attrs; stub the session snapshot
    # by pre-seeding settings so begin path doesn't explode. Patch the symbol.
    import custom_components.dreame_a2_mower.coordinator._mqtt_handlers as mh
    c.__class__._orig_bss = getattr(mh, "build_settings_snapshot_v2")
    mh.build_settings_snapshot_v2 = lambda *a, **k: None
    return c, mh


def test_begin_session_seeds_pending_op(tmp_path):
    c, mh = _coord_for_state_update(tmp_path)
    try:
        c._latch_task_op(107)                  # echo arrived BEFORE session
        assert not c.live_map.is_active()
        s = MowerState()
        s.task_state_code = 0                  # idle -> running triggers begin
        c._on_state_update(s, now_unix=2000)
        assert c.live_map.is_active()
        assert c.live_map.last_task_op == 107  # SEEDED at birth
    finally:
        mh.build_settings_snapshot_v2 = c.__class__._orig_bss


def test_begin_session_seeds_non_patrol_op(tmp_path):
    c, mh = _coord_for_state_update(tmp_path)
    try:
        c._latch_task_op(109)                  # cruise-to-point, not patrol
        s = MowerState()
        s.task_state_code = 0
        c._on_state_update(s, now_unix=2000)
        assert c.live_map.last_task_op == 109
    finally:
        mh.build_settings_snapshot_v2 = c.__class__._orig_bss
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_pending_task_op.py::test_begin_session_seeds_pending_op -v`
Expected: FAIL — `assert None == 107` (seed not wired into `_on_state_update` yet).

- [ ] **Step 3: Wire the seed after begin_session**

In `coordinator/_mqtt_handlers.py`, inside `_on_state_update`, immediately after `self.live_map.begin_session(now_unix)` (`:406`):

```python
            self.live_map.begin_session(now_unix)
            # Seed the just-born session's type from the op echo that arrived
            # before it existed (begin_session nulled last_task_op). Fixes the
            # dock-start race where the s2p50 echo / s2p2=51 are lost.
            self._seed_session_type_from_pending()
```

- [ ] **Step 4: Route the s2p50 echo through the new handler**

In `coordinator/_mqtt_handlers.py`, replace the gated capture block (`:284-302`):

```python
                        if (_sm_siid, _sm_piid) == (2, 50):
                            _op = (
                                (_sm_value.get("d") or _sm_value).get("o")
                                if isinstance(_sm_value, dict)
                                else None
                            )
                            if _op is not None:
                                self.hass.loop.call_soon_threadsafe(
                                    lambda op=_op: (
                                        capture_session_type_signals(
                                            self.live_map,
                                            s2p56_status=None,
                                            s2p50_op=op,
                                            area_m2=None,
                                        )
                                        if self.live_map.is_active()
                                        else None
                                    )
                                )
```

with:

```python
                        if (_sm_siid, _sm_piid) == (2, 50):
                            # Latch the op UNGATED — a patrol/mow commanded from
                            # the dock echoes its op ~40s before begin_session
                            # exists to hold it. _handle_task_op_echo persists it
                            # and (if a session is already active) sets
                            # last_task_op immediately.
                            self.hass.loop.call_soon_threadsafe(
                                lambda v=_sm_value: self._handle_task_op_echo(v)
                            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_pending_task_op.py -v`
Expected: PASS (all 8).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py \
        tests/coordinator/test_pending_task_op.py
git commit -m "feat(coordinator): seed last_task_op at begin_session from pending latch"
```

---

## Task 4: Restore reads sidecar; finalize clears it

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py` — `_restore_in_progress` (`:863`) reads sidecar; the incomplete-finalize path (`_do_finalize_incomplete`, near `:832` where `delete_in_progress` is called) deletes it.
- Test: `tests/coordinator/test_pending_task_op_restore_clear.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/coordinator/test_pending_task_op_restore_clear.py`:

```python
"""Pending op survives a boot via sidecar; cleared on finalize."""
from __future__ import annotations

from custom_components.dreame_a2_mower.archive.session import SessionArchive
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_load_pending_op_from_sidecar(tmp_path):
    arc = SessionArchive(tmp_path)
    arc.write_pending_op(108)
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = arc
    c.live_map = LiveMapState()
    c._pending_task_op = None
    c._load_pending_op_from_sidecar()
    assert c._pending_task_op == 108


def test_clear_pending_op_removes_sidecar(tmp_path):
    arc = SessionArchive(tmp_path)
    arc.write_pending_op(107)
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = arc
    c._pending_task_op = 107
    c._clear_pending_op()
    assert c._pending_task_op is None
    assert arc.read_pending_op() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_pending_task_op_restore_clear.py -v`
Expected: FAIL — `AttributeError: ... '_load_pending_op_from_sidecar'`.

- [ ] **Step 3: Add the two small helpers**

In `coordinator/_session.py`, add to the session mixin (place near `_restore_in_progress`, `:863`):

```python
    def _load_pending_op_from_sidecar(self) -> None:
        """Restore the pending task op persisted before a boot (no live session
        yet). A reboot AFTER begin_session is covered separately by
        in_progress.json's last_task_op."""
        op = self.session_archive.read_pending_op()
        if op is not None:
            self._pending_task_op = op

    def _clear_pending_op(self) -> None:
        """Drop the pending op + its sidecar so a finished session's op cannot
        seed a later one (the no-window safety valve)."""
        self._pending_task_op = None
        self.session_archive.delete_pending_op()
```

- [ ] **Step 4: Call restore at boot**

In `coordinator/_session.py`, at the top of `_restore_in_progress` (just inside the method, after the opening log at `:881`):

```python
        # Recover the pending task op latched before the previous shutdown,
        # in case the restart straddled the op-echo -> begin_session window.
        self._load_pending_op_from_sidecar()
```

- [ ] **Step 5: Call clear on incomplete finalize**

In `coordinator/_session.py`, in `_do_finalize_incomplete`, immediately after the `delete_in_progress` executor call (`:832`):

```python
            self._clear_pending_op()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_pending_task_op_restore_clear.py -v`
Expected: PASS (both).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py \
        tests/coordinator/test_pending_task_op_restore_clear.py
git commit -m "feat(coordinator): restore pending op on boot, clear on finalize"
```

---

## Task 5: Clear pending op on the cloud-finalized path too

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py` — the cloud-finalized completion path in `_dispatch_finalize_action` / its archive-write helper (after the cloud-summary archive write succeeds).
- Test: `tests/coordinator/test_pending_task_op_restore_clear.py` (extend)

- [ ] **Step 1: Locate the cloud-finalized completion point**

Run: `grep -n "delete_in_progress\|_promote_in_progress\|archive write\|def _dispatch_finalize_action\|FINALIZE_COMPLETE" custom_components/dreame_a2_mower/coordinator/_session.py`
Expected: shows the cloud-finalized path's success site (where `in_progress.json` is promoted/deleted after the cloud summary is archived). Use that exact site in Step 3.

- [ ] **Step 2: Write the failing test**

Append to `tests/coordinator/test_pending_task_op_restore_clear.py`:

```python
def test_clear_is_idempotent_when_no_sidecar(tmp_path):
    arc = SessionArchive(tmp_path)
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = arc
    c._pending_task_op = None
    c._clear_pending_op()                 # must not raise when nothing to clear
    assert c._pending_task_op is None
    assert arc.read_pending_op() is None
```

- [ ] **Step 3: Add the clear call to the cloud-finalized success path**

At the cloud-finalized completion site found in Step 1 (where the session
archive entry is written and `in_progress.json` is removed after a successful
cloud-summary fetch), add:

```python
        self._clear_pending_op()
```

Place it adjacent to the existing `delete_in_progress` / promote call so the
pending op is cleared exactly when the session is fully archived (mow OR
patrol). Do not clear it on the AWAIT/retry branch — only on terminal success.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_pending_task_op_restore_clear.py -v`
Expected: PASS (all 3).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py \
        tests/coordinator/test_pending_task_op_restore_clear.py
git commit -m "feat(coordinator): clear pending op on cloud-finalized completion"
```

---

## Task 6: classify warns on no-signal maintenance_run

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/classify.py:89-98`
- Test: `tests/live_map/test_classify_session_type.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/live_map/test_classify_session_type.py`:

```python
import logging


def test_no_signal_maintenance_run_warns(caplog):
    from custom_components.dreame_a2_mower.live_map.classify import (
        classify_session_type,
    )
    with caplog.at_level(logging.WARNING):
        t, outcome = classify_session_type(
            last_task_op=None,
            saw_mow_start=False,
            area_ever_positive=False,
            last_point_end_code=None,
            saw_patrol_start=False,
        )
    assert t == "maintenance_run"
    assert any(
        "no positive session-type signal" in r.message for r in caplog.records
    )


def test_to_point_op109_maintenance_run_does_not_warn(caplog):
    from custom_components.dreame_a2_mower.live_map.classify import (
        classify_session_type,
    )
    with caplog.at_level(logging.WARNING):
        t, outcome = classify_session_type(
            last_task_op=109,                 # genuine to-point run
            saw_mow_start=False,
            area_ever_positive=False,
            last_point_end_code=75,
            saw_patrol_start=False,
        )
    assert (t, outcome) == ("maintenance_run", "arrived")
    assert not any(
        "no positive session-type signal" in r.message for r in caplog.records
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_classify_session_type.py::test_no_signal_maintenance_run_warns -v`
Expected: FAIL — no warning emitted.

- [ ] **Step 3: Add the logger + warning**

In `live_map/classify.py`, after the imports (`:23`):

```python
import logging

_LOGGER = logging.getLogger(__name__)
```

Then replace the fall-through (`:95-98`):

```python
    outcome = {75: "arrived", 76: "could_not_reach"}.get(
        last_point_end_code, "unknown"
    )
    return "maintenance_run", outcome
```

with:

```python
    if last_task_op is None:
        # No op, no mow evidence, no patrol start, no to-point op. The type was
        # never recorded — a real to-point run carries op=109 (handled by the
        # block above via last_point_end_code), so a None op here means the
        # start clues were lost. Surface it instead of masking behind the
        # default. See 2026-06-04 patrol-session-type-recording fix.
        _LOGGER.warning(
            "classify_session_type: no positive session-type signal "
            "(last_task_op=None, no mow/area/patrol) — defaulting to "
            "maintenance_run; the session start clues may have been lost"
        )
    outcome = {75: "arrived", 76: "could_not_reach"}.get(
        last_point_end_code, "unknown"
    )
    return "maintenance_run", outcome
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/live_map/test_classify_session_type.py -v`
Expected: PASS (both new + existing classify tests green).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map/classify.py \
        tests/live_map/test_classify_session_type.py
git commit -m "feat(classify): warn on no-signal maintenance_run fall-through"
```

---

## Task 7: End-to-end dock-start race reproduction

**Files:**
- Test: `tests/integration/test_patrol_session_recording.py` (new)

This is the load-bearing regression: a dock-started patrol whose op echo +
`s2p2=51` arrive while inactive must (a) be typed `patrol` and (b) NOT
finalize on the first `s2p2=75` arrival. It drives the real seed path and the
real `_provisional_session_is_cloud_finalized` guard.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_patrol_session_recording.py`:

```python
"""Regression: a dock-started patrol is typed `patrol` and not finalized on
the first point arrival.

Reproduces the 2026-06-04 bug: s2p50 op echo + s2p2=51 arrive before
begin_session, are lost, so classify falls through to maintenance_run and the
s2p2=75 gate finalizes early. With the pending-op latch, begin_session seeds
last_task_op=107 so the session is cloud-finalized (patrol) and the early gate
is skipped.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.session import SessionArchive
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState


def _coord(tmp_path, monkeypatch):
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = SessionArchive(tmp_path)
    c.live_map = LiveMapState()
    c.data = MowerState()
    c._pending_task_op = None
    c._prev_task_state = None
    c._real_task_state_observed = True
    c._active_map_id = 0
    c._begin_live_stream = lambda: None
    c._fire_lifecycle = lambda *a, **k: None
    hass = MagicMock()
    hass.async_create_task = MagicMock()
    hass.loop.call_soon_threadsafe = lambda fn, *a: fn(*a)
    c.hass = hass
    import custom_components.dreame_a2_mower.coordinator._mqtt_handlers as mh
    monkeypatch.setattr(mh, "build_settings_snapshot_v2", lambda *a, **k: None)
    return c


def test_dock_started_point_patrol_typed_patrol_not_finalized(tmp_path, monkeypatch):
    c = _coord(tmp_path, monkeypatch)

    # 1. op echo arrives while inactive (dock-start) — latched ungated.
    c._handle_task_op_echo({"d": {"o": 107}})
    assert not c.live_map.is_active()
    assert c.live_map.last_task_op is None      # not yet seeded

    # 2. first position push: idle -> running fires begin_session + seed.
    s = MowerState()
    s.task_state_code = 0
    c._on_state_update(s, now_unix=2000)
    assert c.live_map.is_active()
    assert c.live_map.last_task_op == 107        # SEEDED

    # 3. provisional type is patrol -> cloud-finalized -> early gate skips.
    assert c._provisional_session_type() == "patrol"
    assert c._provisional_session_is_cloud_finalized() is True

    # 4. s2p2=75 (arrived at point) must NOT schedule an immediate finalize.
    c.hass.async_create_task.reset_mock()
    c.live_map.append_point(
        t=2100.0, x_m=1.0, y_m=1.0, area_m2=0.0, heading_deg=0.0
    )
    # gate guard: is_active AND not cloud_finalized -> here cloud_finalized True
    assert not (
        c.live_map.is_active() and not c._provisional_session_is_cloud_finalized()
    )
```

(`append_point(t, x_m, y_m, area_m2, heading_deg)` — verified signature, no
`task_state` arg. The assertion that matters is the final guard expression, not
the point append.)

- [ ] **Step 2: Run test to verify it passes (seed already implemented)**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_patrol_session_recording.py -v`
Expected: PASS — Tasks 2-3 already implement the seed. (This test is the
end-to-end proof; it codifies the bug scenario as a permanent regression.)

Note: if it FAILS on a missing attr/signature, fix the test harness (not the
production code) to match the real `_on_state_update` / `append_point`
contract, then re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_patrol_session_recording.py
git commit -m "test(integration): dock-started patrol typed patrol, not early-finalized"
```

---

## Task 8: Inventory note + full-suite regression

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (o108 `open_question`)
- Modify: `docs/TODO.md` (mark the patrol bug fixed pending live-confirm)

- [ ] **Step 1: Update the o108 open_question**

In `inventory.yaml`, find the o108 entry's `open_question` (the patrol
session-tracking text). Append a presumed verification noting the fix, WITHOUT
claiming live confirmation:

```yaml
    verifications:
      - date: "2026-06-04"
        status: presumed
        claim: "Patrol mis-type/early-finalize root-caused to begin_session wiping the pre-session s2p50 op echo + s2p2=51 clues; fixed by latching the op ungated (_pending_task_op) and seeding last_task_op at begin_session. Awaiting live re-confirmation that a dock-started point + edge patrol both type as patrol and capture the return leg."
```

(Do not change the `status:` of existing verified rows. Update
`status.last_seen` to `2026-06-04` if the entry carries one.)

- [ ] **Step 2: Update docs/TODO.md**

Edit the patrol-bug TODO item (the `[BUG] Patrol sessions finalize early...`
block) to add a leading line:

```markdown
   - **[FIX IN REVIEW 2026-06-04 — branch `fix/patrol-session-type-recording`]**
     Root cause + fix: pending task-op latch seeds session type at begin_session.
     Awaiting live re-confirmation (dock-started point + edge patrol type as
     Patrol, return leg captured). Remove this item once confirmed.
```

- [ ] **Step 3: Run the FULL suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: all green — new tests pass, prior baseline (~1980 passed / 4 skipped)
holds. Investigate any regression before proceeding; the early-finalize and
session-boundary suites (`tests/integration/test_session_boundary_split.py`,
`tests/state_machine/test_to_point_session_end.py`) are the highest-risk
neighbours — they must stay green.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml docs/TODO.md
git commit -m "docs(inventory,todo): record patrol session-type recording fix (presumed)"
```

---

## Self-Review

**Spec coverage:**
- §1 Capture ungated → Task 2 (`_latch_task_op`) + Task 3 (echo wiring removing the `is_active()` gate). ✓
- §2 Seed at begin_session for all ops → Task 3 (`_seed_session_type_from_pending` + call site); generality covered by `test_begin_session_seeds_non_patrol_op`. ✓
- §3 No window → `test_latch_last_wins_no_window`. ✓
- §4 Sidecar persist/restore/clear → Task 1 (I/O), Task 4 (restore + incomplete-clear), Task 5 (cloud-finalized clear). ✓
- §5 Observability warning → Task 6. ✓
- Downstream early-finalize (no code change) → proven by Task 7. ✓
- Inventory/fact-discipline note → Task 8. ✓

**Placeholder scan:** Task 5 Step 1 and Task 7 Step 1 intentionally include a
locate-then-use step because the exact cloud-finalized clear site and
`append_point` signature must be read from the live file; both give the exact
grep and the exact line to add, not a vague "handle it." No "TBD"/"add error
handling" placeholders remain.

**Type consistency:** `_pending_task_op: int | None`, `_latch_task_op(op:int)`,
`_handle_task_op_echo(value)`, `_seed_session_type_from_pending()`,
`_load_pending_op_from_sidecar()`, `_clear_pending_op()`, and
`SessionArchive.{read,write,delete}_pending_op` are named identically across all
tasks. ✓
