# Live Map Overlay Implementation Plan (Plan E.1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the active mowing session's position, path trail, obstacle markers, and charger location as `extra_state_attributes` on the existing `camera.dreame_a2_map` entity — consumable by a Lovelace map card (e.g. `lovelace-xiaomi-vacuum-map-card`) for live rendering.

**Architecture:** New `live_map.py` module with a pure `LiveMapState` state machine (unit-testable) plus a `DreameA2LiveMap` HA glue layer that subscribes to coordinator updates, applies user-configurable X/Y calibration factors, and pushes attribute snapshots via a dispatcher signal. Camera entity is patched to merge those attributes into its `extra_state_attributes`. Options flow adds two calibration factor fields. A dev service reconstructs a past session from a probe-log file for validation.

**Tech Stack:** Python 3.14, Home Assistant `DataUpdateCoordinator` + dispatcher signals, existing Plan B/C decoder infrastructure, pytest with the same pythonpath setup.

---

## Environment & credentials

- **Fork working copy:** `/data/claude/homeassistant/ha-dreame-a2-mower/`
- **HA server:** `10.0.0.30`, HAOS 2026.4.2. Credentials at `/data/claude/homeassistant/ha-credentials.txt` (outside repo).
- **Starting HEAD:** current `main` (latest commit `b5638f0` adds the E.1 spec).
- **Probe-log fixtures:** existing `/data/claude/homeassistant/probe_log_20260417_095500.jsonl` (5 sessions) and the new 2026-04-18 run log if present.
- No HA dep in unit tests (pythonpath trick from Plan B still in effect).

## Code layout context (pre-existing, referenced but not rewritten)

- `custom_components/dreame_a2_mower/coordinator.py` — `DreameMowerDataUpdateCoordinator`. Instantiates `DreameMowerDevice`. We'll add a `DreameA2LiveMap` instance field.
- `custom_components/dreame_a2_mower/camera.py` (~988 lines) — `DreameMowerCameraEntity`. Has an `extra_state_attributes` property at line 868. We'll extend (not replace) it to merge live-map attributes.
- `custom_components/dreame_a2_mower/config_flow.py` — `DreameMowerOptionsFlowHandler` at line 69. We add two fields to its schema.
- `custom_components/dreame_a2_mower/__init__.py` — registers integration setup. We'll register the options-update listener and the import service here.
- `custom_components/dreame_a2_mower/protocol/telemetry.py`, `replay.py` — Plan B decoders we reuse.
- `custom_components/dreame_a2_mower/dreame/device.py` — has `mowing_telemetry`, `obstacle_detected`, `status.started` properties added in Plan C.

## File structure (Plan E.1)

```
custom_components/dreame_a2_mower/
├── live_map.py                         # NEW: LiveMapState + DreameA2LiveMap + service handler
└── services.yaml                       # MODIFY: add import_path_from_probe_log service

tests/live_map/
├── __init__.py                         # NEW: empty
├── test_live_map_state.py              # NEW: unit tests for pure state machine
└── test_live_map_integration.py        # NEW: probe-log replay test
```

Modified (small surgical patches):
- `custom_components/dreame_a2_mower/coordinator.py` — instantiate `DreameA2LiveMap`.
- `custom_components/dreame_a2_mower/camera.py` — merge live-map attrs into `extra_state_attributes`.
- `custom_components/dreame_a2_mower/config_flow.py` — add X/Y calibration fields.
- `custom_components/dreame_a2_mower/__init__.py` — register options listener + services.

---

### Task 1: Test infra for live_map

**Files:**
- Create: `tests/live_map/__init__.py`
- Create: `tests/live_map/test_live_map_state.py` (empty shell for now)

- [ ] **Step 1: Verify starting state**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git status
git log --oneline -2
```

Expected: clean tree, top commit `b5638f0 docs: add Plan E.1 spec ...`.

- [ ] **Step 2: Create test package**

```bash
touch tests/live_map/__init__.py
cat > tests/live_map/test_live_map_state.py <<'EOF'
"""Tests for custom_components.dreame_a2_mower.live_map — pure state machine."""

from __future__ import annotations

import pytest
EOF
```

- [ ] **Step 3: Verify pytest collects empty test file**

```bash
. .venv/bin/activate
pytest tests/live_map/ -v
```

Expected: `no tests ran` (exit code 5). That's fine — just confirms the dir is picked up.

- [ ] **Step 4: Commit**

```bash
git add tests/live_map/
git commit -m "test: scaffold tests/live_map/ package"
```

---

### Task 2: `LiveMapState` dataclass — path dedupe

**Files:**
- Create: `custom_components/dreame_a2_mower/live_map.py`
- Modify: `tests/live_map/test_live_map_state.py`

- [ ] **Step 1: Write failing tests for path append + dedupe**

Replace the contents of `tests/live_map/test_live_map_state.py` with:

```python
"""Tests for custom_components.dreame_a2_mower.live_map — pure state machine."""

from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.live_map import LiveMapState


def test_new_state_has_empty_path_and_obstacles():
    s = LiveMapState()
    assert s.path == []
    assert s.obstacles == []


def test_append_point_stores_tuple_in_path():
    s = LiveMapState()
    s.append_point(1.5, 2.5)
    assert s.path == [[1.5, 2.5]]


def test_append_point_dedupes_near_last():
    s = LiveMapState()
    s.append_point(0.0, 0.0)
    # Less than 0.2 m away — skip.
    s.append_point(0.1, 0.1)
    assert s.path == [[0.0, 0.0]]


def test_append_point_accepts_when_far_enough():
    s = LiveMapState()
    s.append_point(0.0, 0.0)
    # Exactly at 0.2 m — accept.
    s.append_point(0.2, 0.0)
    s.append_point(0.4, 0.0)
    assert s.path == [[0.0, 0.0], [0.2, 0.0], [0.4, 0.0]]


def test_append_point_rounds_to_3_decimals():
    s = LiveMapState()
    s.append_point(1.2345678, 2.9876543)
    assert s.path == [[1.235, 2.988]]
```

Note: the test file uses `from custom_components.dreame_a2_mower.live_map import LiveMapState` — but Plan B's pytest config uses `pythonpath = ["custom_components/dreame_a2_mower"]`. Replace with the short import form: `from live_map import LiveMapState`.

Corrected import section:

```python
from live_map import LiveMapState
```

- [ ] **Step 2: Run test, verify failure**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: `ModuleNotFoundError: No module named 'live_map'`.

- [ ] **Step 3: Write minimal implementation**

Create `custom_components/dreame_a2_mower/live_map.py`:

```python
"""Live-map state machine and Home Assistant glue for Plan E.1.

`LiveMapState` is a pure Python state machine that turns a stream of
telemetry/obstacle events into a snapshot dict consumable by a Lovelace
map card. It has no HA dependency and is unit-testable in isolation.

See docs/superpowers/specs/2026-04-18-live-map-overlay-design.md for the
design rationale and attribute schema.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

PATH_DEDUPE_METRES = 0.2


@dataclass
class LiveMapState:
    """Pure state machine tracking the current session's map data."""

    path: list[list[float]] = field(default_factory=list)
    obstacles: list[list[float]] = field(default_factory=list)
    session_id: int = 0
    session_start: str | None = None

    def append_point(self, x_m: float, y_m: float) -> None:
        """Append a position to the path unless it's within PATH_DEDUPE_METRES of the last point."""
        point = [round(x_m, 3), round(y_m, 3)]
        if self.path:
            last = self.path[-1]
            dx = point[0] - last[0]
            dy = point[1] - last[1]
            if math.hypot(dx, dy) < PATH_DEDUPE_METRES:
                return
        self.path.append(point)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map.py tests/live_map/test_live_map_state.py
git commit -m "feat(live_map): LiveMapState with append_point + 0.2m dedupe + 3-decimal rounding"
```

---

### Task 3: `LiveMapState.append_obstacle` — proximity dedupe

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map.py`
- Modify: `tests/live_map/test_live_map_state.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/live_map/test_live_map_state.py`:

```python
def test_append_obstacle_stores_tuple():
    s = LiveMapState()
    s.append_obstacle(1.0, 2.0)
    assert s.obstacles == [[1.0, 2.0]]


def test_append_obstacle_dedupes_by_proximity():
    s = LiveMapState()
    s.append_obstacle(0.0, 0.0)
    # Within 0.5 m of existing — skip.
    s.append_obstacle(0.3, 0.3)
    # Exactly at 0.5 m — boundary is skip.
    s.append_obstacle(0.5, 0.0)
    # Beyond 0.5 m — accept.
    s.append_obstacle(0.6, 0.0)
    assert s.obstacles == [[0.0, 0.0], [0.6, 0.0]]


def test_append_obstacle_rounds_to_3_decimals():
    s = LiveMapState()
    s.append_obstacle(1.2345678, 2.9876543)
    assert s.obstacles == [[1.235, 2.988]]


def test_append_obstacle_checks_all_existing_not_just_last():
    """Dedupe considers ALL existing obstacles, not just the last one."""
    s = LiveMapState()
    s.append_obstacle(0.0, 0.0)
    s.append_obstacle(5.0, 5.0)
    # Close to first obstacle (not last) — should still dedupe.
    s.append_obstacle(0.1, 0.0)
    assert s.obstacles == [[0.0, 0.0], [5.0, 5.0]]
```

- [ ] **Step 2: Run, verify new tests fail**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: 5 existing pass, 4 new fail with `AttributeError: 'LiveMapState' object has no attribute 'append_obstacle'`.

- [ ] **Step 3: Implement**

Append to `custom_components/dreame_a2_mower/live_map.py`:

```python
OBSTACLE_DEDUPE_METRES = 0.5


# … add as a method on LiveMapState (insert before the closing of the class):
```

Actually add as a method by editing the class definition. Replace the `LiveMapState` class with:

```python
@dataclass
class LiveMapState:
    """Pure state machine tracking the current session's map data."""

    path: list[list[float]] = field(default_factory=list)
    obstacles: list[list[float]] = field(default_factory=list)
    session_id: int = 0
    session_start: str | None = None

    def append_point(self, x_m: float, y_m: float) -> None:
        """Append a position to the path unless it's within PATH_DEDUPE_METRES of the last point."""
        point = [round(x_m, 3), round(y_m, 3)]
        if self.path:
            last = self.path[-1]
            dx = point[0] - last[0]
            dy = point[1] - last[1]
            if math.hypot(dx, dy) < PATH_DEDUPE_METRES:
                return
        self.path.append(point)

    def append_obstacle(self, x_m: float, y_m: float) -> None:
        """Append an obstacle position unless any existing marker is within OBSTACLE_DEDUPE_METRES."""
        point = [round(x_m, 3), round(y_m, 3)]
        for existing in self.obstacles:
            dx = point[0] - existing[0]
            dy = point[1] - existing[1]
            if math.hypot(dx, dy) <= OBSTACLE_DEDUPE_METRES:
                return
        self.obstacles.append(point)
```

Also add the `OBSTACLE_DEDUPE_METRES = 0.5` constant at module top, just below `PATH_DEDUPE_METRES`.

- [ ] **Step 4: Run tests**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map.py tests/live_map/test_live_map_state.py
git commit -m "feat(live_map): append_obstacle with 0.5m proximity dedupe"
```

---

### Task 4: `LiveMapState.start_session` — session boundaries

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map.py`
- Modify: `tests/live_map/test_live_map_state.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/live_map/test_live_map_state.py`:

```python
def test_start_session_resets_path_and_obstacles_increments_id():
    s = LiveMapState()
    s.append_point(1.0, 2.0)
    s.append_obstacle(3.0, 4.0)
    assert s.path != []
    assert s.obstacles != []
    assert s.session_id == 0

    s.start_session("2026-04-18T12:00:00")

    assert s.path == []
    assert s.obstacles == []
    assert s.session_id == 1
    assert s.session_start == "2026-04-18T12:00:00"


def test_start_session_increments_id_on_each_call():
    s = LiveMapState()
    s.start_session("t1")
    s.start_session("t2")
    s.start_session("t3")
    assert s.session_id == 3
    assert s.session_start == "t3"
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: 2 new tests fail with `AttributeError: 'LiveMapState' object has no attribute 'start_session'`.

- [ ] **Step 3: Implement**

Add method to `LiveMapState` (append inside the class body):

```python
    def start_session(self, session_start_iso: str) -> None:
        """Reset per-session state and bump session_id."""
        self.path = []
        self.obstacles = []
        self.session_id += 1
        self.session_start = session_start_iso
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map.py tests/live_map/test_live_map_state.py
git commit -m "feat(live_map): start_session resets path+obstacles, increments session_id"
```

---

### Task 5: `LiveMapState.to_attributes` — snapshot dict for HA

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map.py`
- Modify: `tests/live_map/test_live_map_state.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/live_map/test_live_map_state.py`:

```python
def test_to_attributes_matches_schema_when_empty():
    s = LiveMapState()
    attrs = s.to_attributes(
        position=None,
        x_factor=1.0,
        y_factor=0.625,
    )
    assert attrs == {
        "position": None,
        "path": [],
        "obstacles": [],
        "charger_position": [0.0, 0.0],
        "session_id": 0,
        "session_start": None,
        "calibration": {"x_factor": 1.0, "y_factor": 0.625},
    }


def test_to_attributes_includes_current_state():
    s = LiveMapState()
    s.start_session("2026-04-18T12:00:00")
    s.append_point(1.0, 2.0)
    s.append_point(1.5, 2.5)
    s.append_obstacle(3.0, 4.0)

    attrs = s.to_attributes(
        position=[1.5, 2.5],
        x_factor=1.0,
        y_factor=0.625,
    )

    assert attrs["position"] == [1.5, 2.5]
    assert attrs["path"] == [[1.0, 2.0], [1.5, 2.5]]
    assert attrs["obstacles"] == [[3.0, 4.0]]
    assert attrs["charger_position"] == [0.0, 0.0]
    assert attrs["session_id"] == 1
    assert attrs["session_start"] == "2026-04-18T12:00:00"
    assert attrs["calibration"] == {"x_factor": 1.0, "y_factor": 0.625}
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: 2 new tests fail with `AttributeError` on `to_attributes`.

- [ ] **Step 3: Implement**

Add to `LiveMapState` class body:

```python
    def to_attributes(
        self,
        position: list[float] | None,
        x_factor: float,
        y_factor: float,
    ) -> dict:
        """Produce the extra_state_attributes dict consumable by a Lovelace map card."""
        return {
            "position": position,
            "path": list(self.path),
            "obstacles": list(self.obstacles),
            "charger_position": [0.0, 0.0],
            "session_id": self.session_id,
            "session_start": self.session_start,
            "calibration": {"x_factor": x_factor, "y_factor": y_factor},
        }
```

- [ ] **Step 4: Run**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map.py tests/live_map/test_live_map_state.py
git commit -m "feat(live_map): to_attributes snapshot matches Plan E.1 attribute schema"
```

---

### Task 6: Buffer-before-session helper

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map.py`
- Modify: `tests/live_map/test_live_map_state.py`

**Background:** Per spec §"Error handling": telemetry that arrives before the session_active flag is known should be buffered (up to 20 frames) and flushed once the session starts.

- [ ] **Step 1: Append failing tests**

```python
def test_pending_point_is_buffered_before_session_starts():
    s = LiveMapState()
    # No session started yet — these should NOT go into path directly.
    s.buffer_pending_point(1.0, 2.0)
    s.buffer_pending_point(1.5, 2.5)
    assert s.path == []

    s.start_session("2026-04-18T12:00:00")
    s.flush_pending()

    assert s.path == [[1.0, 2.0], [1.5, 2.5]]


def test_buffer_limited_to_max_20_frames():
    s = LiveMapState()
    for i in range(30):
        s.buffer_pending_point(i * 1.0, 0.0)

    s.start_session("t1")
    s.flush_pending()

    # Should have at most 20 points from the buffered 30.
    assert len(s.path) == 20
    # The OLDEST frames are dropped; newest 20 retained.
    assert s.path[0] == [10.0, 0.0]
    assert s.path[-1] == [29.0, 0.0]


def test_flush_pending_clears_buffer():
    s = LiveMapState()
    s.buffer_pending_point(1.0, 2.0)
    s.start_session("t1")
    s.flush_pending()
    # Further flush has no effect.
    s.flush_pending()
    assert s.path == [[1.0, 2.0]]
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: 3 new tests fail on missing `buffer_pending_point` / `flush_pending`.

- [ ] **Step 3: Implement**

Add a `_pending` field and two methods to `LiveMapState`:

```python
    _pending: list[list[float]] = field(default_factory=list)

    def buffer_pending_point(self, x_m: float, y_m: float) -> None:
        """Buffer a point until a session has started. Keeps most recent 20 only."""
        self._pending.append([round(x_m, 3), round(y_m, 3)])
        if len(self._pending) > 20:
            self._pending = self._pending[-20:]

    def flush_pending(self) -> None:
        """Apply buffered points to the current session path (subject to dedupe)."""
        for pt in self._pending:
            self.append_point(pt[0], pt[1])
        self._pending = []
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map.py tests/live_map/test_live_map_state.py
git commit -m "feat(live_map): buffer_pending_point + flush_pending (20-frame rolling)"
```

---

### Task 7: Integration test — probe-log replay for session reconstruction

**Files:**
- Create: `tests/live_map/test_live_map_integration.py`

- [ ] **Step 1: Write the test**

Create `tests/live_map/test_live_map_integration.py`:

```python
"""Integration test — reconstruct a real session from the probe log.

Uses the 2026-04-17 probe log's Y-axis session (session index 4:
22:14-23:09) to validate that LiveMapState produces a reasonable
path when driven by real telemetry.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from live_map import LiveMapState
from protocol.replay import iter_probe_log
from protocol.telemetry import decode_s1p4

PROBE_LOG = Path("/data/claude/homeassistant/probe_log_20260417_095500.jsonl")


def _parse(ts: str) -> datetime.datetime:
    return datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def _sessions_from_probe_log(path: Path) -> list[list]:
    """Group probe-log telemetry events into sessions by >3-minute gaps."""
    telem = []
    for ev in iter_probe_log(path):
        if (ev.siid, ev.piid) != (1, 4):
            continue
        if not isinstance(ev.value, list) or len(ev.value) != 33:
            continue
        telem.append(ev)

    sessions: list[list] = []
    current: list = []
    for ev in telem:
        t = _parse(ev.timestamp)
        if current and (t - _parse(current[-1].timestamp)).total_seconds() > 180:
            sessions.append(current)
            current = []
        current.append(ev)
    if current:
        sessions.append(current)
    return sessions


@pytest.mark.skipif(not PROBE_LOG.exists(), reason="probe log fixture missing")
def test_y_axis_session_reconstructs_with_calibrated_points():
    sessions = _sessions_from_probe_log(PROBE_LOG)
    assert len(sessions) >= 5, (
        f"expected at least 5 sessions in the probe log, got {len(sessions)}"
    )

    # Session 4 = 2026-04-17 22:14-23:09 Y-axis mow (per memory).
    y_axis_session = sessions[4]
    assert len(y_axis_session) > 400, (
        f"Y-axis session should have >400 frames, got {len(y_axis_session)}"
    )

    s = LiveMapState()
    s.start_session(y_axis_session[0].timestamp)

    x_factor = 1.0
    y_factor = 0.625

    for ev in y_axis_session:
        telem = decode_s1p4(bytes(ev.value))
        x_m = (telem.x_cm / 100.0) * x_factor
        y_m = (telem.y_mm / 1000.0) * y_factor
        s.append_point(x_m, y_m)

    # Plan C recorded X span ~5m and Y calibrated span ~20m for this session.
    xs = [p[0] for p in s.path]
    ys = [p[1] for p in s.path]
    x_span = max(xs) - min(xs)
    y_span = max(ys) - min(ys)

    assert 3.0 < x_span < 7.0, f"X span {x_span:.2f} m outside expected 3-7 m window"
    assert 14.0 < y_span < 22.0, f"Y span {y_span:.2f} m outside expected 14-22 m window"

    # After dedupe, path should be 300-700 points (mower frames deduped at 0.2 m).
    assert 200 < len(s.path) < 700, f"path length {len(s.path)} outside 200-700"
```

- [ ] **Step 2: Run test, verify pass**

```bash
pytest tests/live_map/test_live_map_integration.py -v
```

Expected: 1 passed (or skipped if probe log is missing).

- [ ] **Step 3: Commit**

```bash
git add tests/live_map/test_live_map_integration.py
git commit -m "test(live_map): integration replay of real Y-axis session from probe log"
```

---

### Task 8: `DreameA2LiveMap` HA glue

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map.py`

**Background:** Class that subscribes to coordinator updates, computes current position from `device.mowing_telemetry`, updates `LiveMapState`, and pushes attributes via a dispatcher signal. No HA framework tests — validated on the live HA in Task 14.

- [ ] **Step 1: Append the class to `live_map.py`**

Append to `custom_components/dreame_a2_mower/live_map.py`:

```python
# -------------------------------------------------------------
# HA integration glue — below this line depends on homeassistant.
# -------------------------------------------------------------

from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN

LIVE_MAP_UPDATE_SIGNAL = f"{DOMAIN}_live_map_update"

OPT_X_FACTOR = "live_map_x_factor"
OPT_Y_FACTOR = "live_map_y_factor"

DEFAULT_X_FACTOR = 1.0
DEFAULT_Y_FACTOR = 0.625


class DreameA2LiveMap:
    """HA-facing live map state manager.

    Responsibilities:
    - Subscribe to coordinator updates.
    - Maintain a LiveMapState per-session.
    - Apply calibration factors from config entry options.
    - Dispatch attribute snapshots on the LIVE_MAP_UPDATE_SIGNAL for the
      camera entity to merge into its extra_state_attributes.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._state = LiveMapState()
        self._prev_session_active: bool | None = None
        self._unsub_listener = None

    @property
    def x_factor(self) -> float:
        return float(self._entry.options.get(OPT_X_FACTOR, DEFAULT_X_FACTOR))

    @property
    def y_factor(self) -> float:
        return float(self._entry.options.get(OPT_Y_FACTOR, DEFAULT_Y_FACTOR))

    @callback
    def async_setup(self) -> None:
        self._unsub_listener = self._coordinator.async_add_listener(
            self._handle_coordinator_update
        )

    @callback
    def async_unload(self) -> None:
        if self._unsub_listener:
            self._unsub_listener()
            self._unsub_listener = None

    @callback
    def _handle_coordinator_update(self) -> None:
        device = self._coordinator.device
        if device is None:
            return

        # 1) Session-active transitions.
        try:
            active = bool(device.status.started)
        except AttributeError:
            active = False

        if active and not self._prev_session_active:
            # New session — snapshot ISO timestamp in UTC, reset state, flush buffered points.
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._state.start_session(now_iso)
            self._state.flush_pending()
        self._prev_session_active = active

        # 2) Position from telemetry.
        telem = getattr(device, "mowing_telemetry", None)
        position = None
        if telem is not None:
            x_m = (telem.x_cm / 100.0) * self.x_factor
            y_m = (telem.y_mm / 1000.0) * self.y_factor
            position = [round(x_m, 3), round(y_m, 3)]

            if active:
                self._state.append_point(x_m, y_m)
            else:
                self._state.buffer_pending_point(x_m, y_m)

        # 3) Obstacle: append if True and no recent dupe. Position must exist.
        try:
            obstacle_on = bool(device.obstacle_detected)
        except AttributeError:
            obstacle_on = False

        if obstacle_on and position is not None:
            self._state.append_obstacle(position[0], position[1])

        # 4) Push snapshot.
        attrs = self._state.to_attributes(
            position=position,
            x_factor=self.x_factor,
            y_factor=self.y_factor,
        )
        async_dispatcher_send(self._hass, LIVE_MAP_UPDATE_SIGNAL, attrs)

    @callback
    def handle_options_update(self) -> None:
        """Called by the __init__ options listener when the user edits calibration."""
        # Re-push a snapshot with the new calibration so the card sees it.
        self._handle_coordinator_update()

    def import_from_probe_log(self, path: str, session_index: int = -1) -> dict[str, Any]:
        """Reconstruct a session from a probe-log file (dev service)."""
        from pathlib import Path
        import datetime as _dt
        from .protocol.replay import iter_probe_log
        from .protocol.telemetry import decode_s1p4, InvalidS1P4Frame

        def _parse(ts: str) -> _dt.datetime:
            return _dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")

        telem_events = []
        for ev in iter_probe_log(Path(path)):
            if (ev.siid, ev.piid) != (1, 4):
                continue
            if not isinstance(ev.value, list) or len(ev.value) != 33:
                continue
            telem_events.append(ev)

        sessions: list[list] = []
        current: list = []
        for ev in telem_events:
            t = _parse(ev.timestamp)
            if current and (t - _parse(current[-1].timestamp)).total_seconds() > 180:
                sessions.append(current)
                current = []
            current.append(ev)
        if current:
            sessions.append(current)

        if not sessions:
            raise ValueError(f"No telemetry sessions found in {path}")

        idx = session_index if 0 <= session_index < len(sessions) else len(sessions) - 1
        target = sessions[idx]

        # Rebuild state.
        self._state = LiveMapState()
        self._state.start_session(target[0].timestamp)

        last_position = None
        for ev in target:
            try:
                telem = decode_s1p4(bytes(ev.value))
            except InvalidS1P4Frame:
                continue
            x_m = (telem.x_cm / 100.0) * self.x_factor
            y_m = (telem.y_mm / 1000.0) * self.y_factor
            self._state.append_point(x_m, y_m)
            last_position = [round(x_m, 3), round(y_m, 3)]

        attrs = self._state.to_attributes(
            position=last_position,
            x_factor=self.x_factor,
            y_factor=self.y_factor,
        )
        async_dispatcher_send(self._hass, LIVE_MAP_UPDATE_SIGNAL, attrs)
        return {
            "path_points": len(self._state.path),
            "session_index": idx,
            "total_sessions": len(sessions),
            "start_timestamp": target[0].timestamp,
        }
```

- [ ] **Step 2: Compile-check**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/live_map.py
```

Expected: silent.

- [ ] **Step 3: Re-run unit tests to confirm LiveMapState untouched**

```bash
pytest tests/live_map/test_live_map_state.py -v
```

Expected: 16 passed.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/live_map.py
git commit -m "feat(live_map): DreameA2LiveMap HA glue + probe-log import helper"
```

---

### Task 9: Coordinator — instantiate DreameA2LiveMap

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py`

- [ ] **Step 1: Locate coordinator init**

```bash
grep -n "class DreameMowerDataUpdateCoordinator\|self\._device = DreameMowerDevice" custom_components/dreame_a2_mower/coordinator.py | head -3
```

- [ ] **Step 2: Patch**

Open `custom_components/dreame_a2_mower/coordinator.py`. Immediately after `self._device = DreameMowerDevice(...)` is constructed (inside `__init__`), add:

```python
        from .live_map import DreameA2LiveMap
        self.live_map = DreameA2LiveMap(hass, entry, self)
        self.live_map.async_setup()
```

(The `hass` and `entry` variables already exist in this scope.)

Also add, in the coordinator's `async_shutdown` or equivalent teardown method (if one exists) / or where the device is unloaded, a call to `self.live_map.async_unload()`. If there isn't an obvious unload hook, skip this — the listener auto-cleans on HA restart.

- [ ] **Step 3: Compile-check**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/coordinator.py
```

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(coordinator): instantiate and setup DreameA2LiveMap"
```

---

### Task 10: Camera entity — merge live-map attributes

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py`

**Background:** The existing camera's `extra_state_attributes` at line 868 returns a dict. We need to merge in the live-map attributes when they've been dispatched. Use a per-instance buffer updated by the dispatcher signal.

- [ ] **Step 1: Inspect existing attribute builder**

```bash
sed -n '860,890p' custom_components/dreame_a2_mower/camera.py
```

Read the structure. Confirm it returns a dict (or None).

- [ ] **Step 2: Add imports and listener**

Add near the top of `camera.py` (below existing HA helper imports):

```python
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .live_map import LIVE_MAP_UPDATE_SIGNAL
```

In `DreameMowerCameraEntity.__init__` (find it by search), after `super().__init__(coordinator, description)`, add:

```python
        self._live_map_attrs: dict = {}
```

Override `async_added_to_hass` in the class to register for the signal:

```python
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                LIVE_MAP_UPDATE_SIGNAL,
                self._on_live_map_update,
            )
        )

    @callback
    def _on_live_map_update(self, attrs: dict) -> None:
        self._live_map_attrs = attrs
        self.async_write_ha_state()
```

Ensure `callback` is imported at the top: `from homeassistant.core import HomeAssistant, callback` (line already exists — append `callback` if missing).

- [ ] **Step 3: Merge attrs into existing `extra_state_attributes`**

Find the existing `extra_state_attributes` property (around line 868). Suppose it looks like:

```python
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        # ... existing dict construction ...
        return attrs
```

Modify the return to merge live-map attrs last (so live-map keys override any collisions, but in practice there are none):

```python
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        # ... existing dict construction ...
        return {**attrs, **self._live_map_attrs}
```

Adjust variable naming if the existing code uses a different local variable name.

- [ ] **Step 4: Compile-check**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/camera.py
```

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/camera.py
git commit -m "feat(camera): merge live-map attributes into extra_state_attributes"
```

---

### Task 11: Options flow — X/Y calibration factors

**Files:**
- Modify: `custom_components/dreame_a2_mower/config_flow.py`

- [ ] **Step 1: Locate options handler**

```bash
grep -n "class DreameMowerOptionsFlowHandler\|async_step_init" custom_components/dreame_a2_mower/config_flow.py
```

Line 69 per earlier check.

- [ ] **Step 2: Inspect the current schema**

```bash
sed -n '69,160p' custom_components/dreame_a2_mower/config_flow.py
```

Identify the data-schema construction inside `async_step_init`. It will have a `vol.Schema({...})` or similar where we add two numeric fields.

- [ ] **Step 3: Add calibration fields**

Add these imports at the top of `config_flow.py` if not already present:

```python
import voluptuous as vol
```

(Already imported, but include if missing.)

Add near the top where other constant strings are declared:

```python
from .live_map import OPT_X_FACTOR, OPT_Y_FACTOR, DEFAULT_X_FACTOR, DEFAULT_Y_FACTOR
```

In `DreameMowerOptionsFlowHandler.async_step_init`'s schema construction (the `vol.Schema({...})` call), add two fields:

```python
            vol.Optional(
                OPT_X_FACTOR,
                default=self.config_entry.options.get(OPT_X_FACTOR, DEFAULT_X_FACTOR),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0)),
            vol.Optional(
                OPT_Y_FACTOR,
                default=self.config_entry.options.get(OPT_Y_FACTOR, DEFAULT_Y_FACTOR),
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0)),
```

Placement: just before the closing `})` of the schema dict.

- [ ] **Step 4: Compile-check**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/config_flow.py
```

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/config_flow.py
git commit -m "feat(config_flow): expose X/Y calibration factors in Options Flow"
```

---

### Task 12: Options update listener + import service registration

**Files:**
- Modify: `custom_components/dreame_a2_mower/__init__.py`
- Modify: `custom_components/dreame_a2_mower/services.yaml`

- [ ] **Step 1: Add service to `services.yaml`**

Read the current file first, then append the new service definition:

```bash
tail -5 custom_components/dreame_a2_mower/services.yaml
```

Append to the end (preserving existing YAML structure — keep a blank line before the new entry):

```yaml
import_path_from_probe_log:
  target:
    entity:
      integration: dreame_a2_mower
      domain: camera
  fields:
    file:
      example: "/data/claude/homeassistant/probe_log_20260417_095500.jsonl"
      required: true
      selector:
        text:
    session_index:
      example: 4
      required: false
      default: -1
      selector:
        number:
          min: -1
          max: 20
          step: 1
          mode: box
```

Validate YAML parses:

```bash
python3 -c "import yaml; yaml.safe_load(open('custom_components/dreame_a2_mower/services.yaml'))" && echo OK
```

- [ ] **Step 2: Register the service and options-update listener in `__init__.py`**

Open `custom_components/dreame_a2_mower/__init__.py`. In `async_setup_entry`, after the coordinator is set up and stored in `hass.data`, add:

```python
    # Options-update listener re-broadcasts current state with new calibration.
    async def _options_updated(hass, entry):
        coord = hass.data[DOMAIN].get(entry.entry_id)
        if coord and hasattr(coord, "live_map"):
            coord.live_map.handle_options_update()

    entry.async_on_unload(entry.add_update_listener(_options_updated))

    # Import-from-probe-log service (dev tool).
    from homeassistant.helpers import service

    async def _handle_import(call):
        coord = next(iter(hass.data[DOMAIN].values()), None)
        if coord is None:
            raise ValueError("No Dreame A2 coordinator loaded")
        path = call.data.get("file")
        session_index = int(call.data.get("session_index", -1))
        if not path:
            raise ValueError("file is required")
        return coord.live_map.import_from_probe_log(path, session_index)

    hass.services.async_register(DOMAIN, "import_path_from_probe_log", _handle_import)
```

Place the service registration AFTER `hass.data[DOMAIN][entry.entry_id] = coordinator` and AFTER `await hass.config_entries.async_forward_entry_setups(...)`.

- [ ] **Step 3: Compile-check**

```bash
python3 -m compileall -q custom_components/dreame_a2_mower/__init__.py
```

- [ ] **Step 4: Run full test suite**

```bash
pytest -v 2>&1 | tail -5
```

Expected: all pre-existing tests pass plus the 16 new `test_live_map_state.py` tests plus the 1 integration test = total ~86 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/__init__.py custom_components/dreame_a2_mower/services.yaml
git commit -m "feat: options-update listener + import_path_from_probe_log service registration"
```

---

### Task 13: Push to GitHub + pre-deploy sanity

**Files:** none

- [ ] **Step 1: Secret sweep**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git ls-files -co --exclude-standard | xargs grep -HInE 'sshpass[[:space:]]+-p[[:space:]]+[^"$ ]|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}' 2>/dev/null || echo "TREE_CLEAN"
```

Expected: `TREE_CLEAN`.

- [ ] **Step 2: Push**

```bash
git push origin main 2>&1 | tail -3
```

Expected: success.

---

### Task 14: Deploy to HA and verify

**Prereqs:** load credentials from `/data/claude/homeassistant/ha-credentials.txt`:

```bash
export HA_HOST=$(sed -n '1p' /data/claude/homeassistant/ha-credentials.txt)
export HA_USER=$(sed -n '2p' /data/claude/homeassistant/ha-credentials.txt)
export HA_PASS=$(sed -n '3p' /data/claude/homeassistant/ha-credentials.txt)
```

- [ ] **Step 1: Redeploy via git clone-and-move**

```bash
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" \
  'cd /config/custom_components && rm -rf _a2_repo dreame_a2_mower && git clone --depth 1 https://github.com/okolbu/ha-dreame-a2-mower.git _a2_repo && mv _a2_repo/custom_components/dreame_a2_mower ./dreame_a2_mower && rm -rf _a2_repo && ha core restart'
```

- [ ] **Step 2: Wait for HA up**

```bash
until sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 "$HA_USER@$HA_HOST" 'curl -s -o /dev/null -w "%{http_code}" http://172.30.32.1:8123/' 2>/dev/null | grep -q 200; do sleep 5; done
echo HA_UP
```

- [ ] **Step 3: Check for fork errors in logs**

```bash
sshpass -p "$HA_PASS" ssh -o StrictHostKeyChecking=no "$HA_USER@$HA_HOST" \
  'ha core logs -n 500 2>&1 | grep -iE "dreame_a2_mower" | grep -vE "Cloud send error 80001|Cloud request returned None|deep sleep|Failed to build map|Get Device OTC|not been tested" | head -20'
```

Expected: no ERROR or Traceback lines. A warning about loading the custom integration is fine.

- [ ] **Step 4: Verify extra_state_attributes populated**

In HA UI → Developer Tools → States → `camera.dreame_a2_map` → check Attributes panel. Should include at minimum:

```
position: null (or [x, y])
path: []
obstacles: []
charger_position: [0.0, 0.0]
session_id: 0
calibration: {x_factor: 1.0, y_factor: 0.625}
```

- [ ] **Step 5: Verify options flow shows new fields**

HA UI → Settings → Devices & Services → Dreame A2 Mower → Configure. Should now show "X calibration factor" and "Y calibration factor" fields with default 1.0 and 0.625.

- [ ] **Step 6: Run the import service via UI**

HA UI → Developer Tools → Services → `dreame_a2_mower.import_path_from_probe_log`:

```yaml
file: /data/claude/homeassistant/probe_log_20260417_095500.jsonl
session_index: 4
```

(Note: the probe log is on the dev machine, not on HA. So this step will FAIL in this specific invocation because HA can't see that file. Document this as "run this from dev machine only" OR copy the probe log onto HA first:)

```bash
sshpass -p "$HA_PASS" scp -o StrictHostKeyChecking=no \
  /data/claude/homeassistant/probe_log_20260417_095500.jsonl \
  "$HA_USER@$HA_HOST:/config/probe_log_sample.jsonl"
```

Then call the service with `file: /config/probe_log_sample.jsonl`.

After service call, re-check `camera.dreame_a2_map` attributes: `path` should now have ~400-600 entries, `session_id` incremented.

- [ ] **Step 7: Document Lovelace card config in README** (optional but recommended in this task since users need it):

Append to the repo `README.md` a new section:

```markdown
## Map card configuration

The integration exposes mower position/trail/obstacles as attributes on the `camera.dreame_a2_map` entity. Use [lovelace-xiaomi-vacuum-map-card](https://github.com/PiotrMachowski/lovelace-xiaomi-vacuum-map-card) or a similar Lovelace map card to render them.

Example card configuration:

\`\`\`yaml
type: custom:xiaomi-vacuum-map-card
entity: vacuum.dreame_a2_mower  # or lawn_mower entity
map_source:
  camera: camera.dreame_a2_map
calibration_source:
  camera: true
map_locked: true
entities:
  - path: path
    icon: mdi:robot-mower
\`\`\`

You'll need to configure calibration_points specific to your lawn in the card config.
```

Commit separately:

```bash
git add README.md
git commit -m "docs(readme): Lovelace map card configuration example"
git push origin main
```

---

### Task 15: Tag v2.0.0-alpha.5

- [ ] **Step 1: Tag**

```bash
git tag -a v2.0.0-alpha.5 -m "Plan E.1 complete — live map overlay attributes + options flow + dev service"
git push origin v2.0.0-alpha.5
```

- [ ] **Step 2: Verify**

```bash
gh api repos/okolbu/ha-dreame-a2-mower/tags --jq '.[0].name'
```

Expected: `v2.0.0-alpha.5`.

---

## Done-definition for Plan E.1

- `live_map.py` module exists with `LiveMapState` (fully unit-tested) + `DreameA2LiveMap` HA glue.
- `camera.dreame_a2_map` carries the attribute schema (`position`, `path`, `obstacles`, `charger_position`, `session_id`, `session_start`, `calibration`) and updates them on every coordinator tick.
- Options flow has user-editable X/Y calibration factors (defaults 1.0 and 0.625).
- Service `dreame_a2_mower.import_path_from_probe_log` works and populates the map from a probe-log file.
- All pre-existing tests plus new live_map tests pass.
- Deployed to HA, integration loads without new errors, attributes visible in Developer Tools.
- Tag `v2.0.0-alpha.5` pushed.

## What Plan E.1 deliberately does NOT do

- Session persistence (disk) — Plan E.2.
- Session picker / replay selector entity — Plan E.3.
- Patrol logs / patrol events — separate future phase.
- Click-to-point commands / go-to — Plan D.
- Server-side image compositing — rendering is the map card's job.
- Zone/exclusion-zone attributes (already available from upstream's map subsystem).
