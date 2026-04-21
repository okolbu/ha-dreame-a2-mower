# Live-map mode refactor implementation plan

> **For agentic workers:** Execute inline with superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the four-option Live / Blank / Latest / `<date>` replay picker with three well-defined modes (Latest / Blank / `<date>`) where Latest auto-tracks the most recent or in-progress run, date choices are pinned, and Blank is a true empty canvas.

**Architecture:** Add a `mode` enum to `LiveMapState` that unambiguously determines snapshot composition. Coordinator ticks only mutate state in `LATEST` mode. A single `set_mode()` entry point replaces `clear_replay()` / `render_blank()` / `replay_session()` / `replay_latest_session()` branching. Camera composed-cache is invalidated on every mode transition so dashboard refresh is reliable.

**Tech Stack:** Python (HA custom component), pytest.

**Spec:** `docs/superpowers/specs/2026-04-21-live-map-mode-refactor-design.md`

---

## File structure

- `custom_components/dreame_a2_mower/live_map.py` — add `MapMode` enum, `mode`/`pinned_md5` fields on `LiveMapState`, `set_mode()` method, rework `DreameA2LiveMap._handle_coordinator_update` to be mode-aware. Remove `_pending` buffer, `flush_pending()`, `clear_replay()`, `render_blank()`.
- `custom_components/dreame_a2_mower/select.py` — rewrite `DreameReplaySessionSelect` to use `set_mode()` and persist sticky date selection across archive changes. Remove `_OPT_LIVE`, `_OPT_NONE`.
- `custom_components/dreame_a2_mower/camera.py` — on mode-change snapshot, clear `_composed_cache` unconditionally.
- `tests/live_map/test_live_map_state.py` — update. Remove `_pending` buffer tests. Add mode-transition tests.
- `tests/live_map/test_summary_overlay.py` — update `test_overlay_survives_start_session` to the new LATEST semantics.
- `tests/live_map/test_mode_transitions.py` — **new**. End-to-end for `DreameA2LiveMap.set_mode()`.
- `dashboards/mower.yaml` — update picker comment.

---

## Task 1: LiveMapState mode field + set_mode()

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map.py:77-201` (LiveMapState)
- Modify: `tests/live_map/test_live_map_state.py:152-188` (delete pending buffer tests)
- Test: `tests/live_map/test_live_map_state.py` (add mode tests)

- [ ] **Step 1.1: Write failing mode tests** — append to `tests/live_map/test_live_map_state.py`:

```python
from live_map import LiveMapState, MapMode


def test_new_state_defaults_to_latest_mode():
    s = LiveMapState()
    assert s.mode == MapMode.LATEST
    assert s.pinned_md5 is None


def test_set_mode_to_blank_clears_all_layers():
    s = LiveMapState()
    s.append_point(1.0, 2.0)
    s.append_obstacle(3.0, 4.0)
    s.lawn_polygon = [[0.0, 0.0], [1.0, 0.0]]
    s.completed_track = [[[0.0, 0.0]]]
    s.summary_md5 = "abc"

    s.set_mode(MapMode.BLANK)

    assert s.mode == MapMode.BLANK
    assert s.path == []
    assert s.obstacles == []
    assert s.lawn_polygon == []
    assert s.completed_track == []
    assert s.summary_md5 is None


def test_set_mode_to_session_stores_pinned_md5_and_clears_live():
    s = LiveMapState()
    s.append_point(1.0, 2.0)
    s.append_obstacle(3.0, 4.0)

    s.set_mode(MapMode.SESSION, pinned_md5="deadbeef")

    assert s.mode == MapMode.SESSION
    assert s.pinned_md5 == "deadbeef"
    assert s.path == []
    assert s.obstacles == []


def test_set_mode_to_latest_clears_pinned_md5_and_live():
    s = LiveMapState()
    s.set_mode(MapMode.SESSION, pinned_md5="deadbeef")
    s.set_mode(MapMode.LATEST)

    assert s.mode == MapMode.LATEST
    assert s.pinned_md5 is None
    assert s.path == []


def test_to_attributes_includes_mode():
    s = LiveMapState()
    s.set_mode(MapMode.BLANK)
    attrs = s.to_attributes(position=None, x_factor=1.0, y_factor=1.0)
    assert attrs["mode"] == "blank"
```

Also delete the pending-buffer tests at lines 152-188 (`test_pending_point_is_buffered_before_session_starts`, `test_buffer_limited_to_max_20_frames`, `test_flush_pending_clears_buffer`).

Also update `test_to_attributes_matches_schema_when_empty` to include `"mode": "latest"` in the expected dict.

- [ ] **Step 1.2: Run tests to verify failures**

```
cd /data/claude/homeassistant/ha-dreame-a2-mower
python -m pytest tests/live_map/test_live_map_state.py -v
```

Expected: FAIL with `ImportError: cannot import name 'MapMode'`.

- [ ] **Step 1.3: Implement MapMode + set_mode()**

In `live_map.py` at the top imports:
```python
from enum import Enum
```

Add after imports:
```python
class MapMode(str, Enum):
    """Replay-picker selection. Determines what the camera snapshot shows."""
    LATEST = "latest"
    SESSION = "session"
    BLANK = "blank"
```

Modify `LiveMapState` dataclass: add fields at the top of the dataclass:
```python
    mode: MapMode = MapMode.LATEST
    pinned_md5: str | None = None
```

Remove the `_pending` field.

Remove `buffer_pending_point` and `flush_pending` methods.

Add a method on `LiveMapState`:
```python
    def set_mode(self, mode: "MapMode", pinned_md5: str | None = None) -> None:
        """Switch to the given mode, clearing fields that don't belong in the new mode.

        LATEST:  clears live accumulators + overlay + pinned_md5 — caller is
                 expected to reload the newest archive (if any) after this.
        SESSION: clears live accumulators, sets pinned_md5. Caller is expected
                 to load the pinned archive into the overlay.
        BLANK:   clears everything.
        """
        self.mode = mode
        self.path = []
        self.obstacles = []
        if mode is MapMode.SESSION:
            self.pinned_md5 = pinned_md5
        else:
            self.pinned_md5 = None
        if mode in (MapMode.LATEST, MapMode.BLANK):
            self.lawn_polygon = []
            self.exclusion_zones = []
            self.completed_track = []
            self.obstacle_polygons = []
            self.dock_position = None
            self.summary_md5 = None
            self.summary_end_ts = None
        if mode is MapMode.BLANK:
            self.session_id = 0
            self.session_start = None
```

Update `to_attributes` to include `mode`:
```python
            "mode": self.mode.value,
```

- [ ] **Step 1.4: Run tests to verify pass**

```
python -m pytest tests/live_map/test_live_map_state.py -v
```

Expected: PASS for all new tests; old tests still green after pending-buffer deletions.

- [ ] **Step 1.5: Update test_summary_overlay — new LATEST semantics**

Modify `tests/live_map/test_summary_overlay.py:64-74` `test_overlay_survives_start_session` to become `test_overlay_cleared_by_set_mode_latest`:

```python
def test_overlay_cleared_by_set_mode_latest(summary):
    """Switching to LATEST clears the overlay — caller is expected to reload."""
    s = LiveMapState()
    s.load_from_session_summary(summary)
    assert s.lawn_polygon != []

    from live_map import MapMode
    s.set_mode(MapMode.LATEST)

    assert s.lawn_polygon == []
    assert s.summary_md5 is None
```

- [ ] **Step 1.6: Run summary-overlay tests**

```
python -m pytest tests/live_map/test_summary_overlay.py -v
```

Expected: all PASS.

- [ ] **Step 1.7: Commit**

```
git -C ha-dreame-a2-mower add custom_components/dreame_a2_mower/live_map.py tests/live_map/test_live_map_state.py tests/live_map/test_summary_overlay.py
git -C ha-dreame-a2-mower commit -m "refactor(live-map): add MapMode enum and set_mode() state-machine API"
```

---

## Task 2: DreameA2LiveMap coordinator-tick mode awareness

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map.py:264-485` (DreameA2LiveMap)
- Create: `tests/live_map/test_mode_transitions.py`

- [ ] **Step 2.1: Write failing integration tests** — new file `tests/live_map/test_mode_transitions.py`:

```python
"""Tests for DreameA2LiveMap.set_mode() and mode-aware coordinator ticks."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from live_map import DreameA2LiveMap, MapMode, LiveMapState


FIXTURE_PATH = (
    Path(__file__).parent.parent / "protocol" / "fixtures" / "session_summary_2026-04-18.json"
)


class FakeArchive:
    def __init__(self, entries):
        self._entries = entries
        self.root = Path("/tmp")

    def latest(self):
        return self._entries[0] if self._entries else None

    def list_sessions(self):
        return list(self._entries)


def _make_live_map(archive=None, device=None):
    hass = SimpleNamespace(loop=None)
    entry = SimpleNamespace(options={})
    coordinator = SimpleNamespace(
        session_archive=archive,
        device=device,
        async_add_listener=lambda cb: (lambda: None),
    )
    return DreameA2LiveMap(hass, entry, coordinator)


def test_set_mode_blank_clears_state():
    lm = _make_live_map()
    lm._state.append_point(1.0, 2.0)
    lm.set_mode(MapMode.BLANK)
    assert lm._state.mode is MapMode.BLANK
    assert lm._state.path == []


def test_set_mode_latest_reloads_newest_archive(tmp_path, monkeypatch):
    fixture = tmp_path / "summary.json"
    fixture.write_text(FIXTURE_PATH.read_text())
    entry = SimpleNamespace(filename="summary.json", md5="abc")
    archive = FakeArchive([entry])
    archive.root = tmp_path

    lm = _make_live_map(archive=archive)
    lm.set_mode(MapMode.LATEST)

    assert lm._state.mode is MapMode.LATEST
    assert len(lm._state.lawn_polygon) > 0  # archive loaded


def test_set_mode_latest_with_empty_archive_leaves_state_empty():
    lm = _make_live_map(archive=FakeArchive([]))
    lm.set_mode(MapMode.LATEST)
    assert lm._state.mode is MapMode.LATEST
    assert lm._state.lawn_polygon == []


def test_set_mode_session_loads_pinned_archive(tmp_path):
    fixture = tmp_path / "pinned.json"
    fixture.write_text(FIXTURE_PATH.read_text())
    entry = SimpleNamespace(filename="pinned.json", md5="pinhash")
    archive = FakeArchive([entry])
    archive.root = tmp_path

    lm = _make_live_map(archive=archive)
    lm.set_mode(MapMode.SESSION, archive_entry=entry)

    assert lm._state.mode is MapMode.SESSION
    assert lm._state.pinned_md5 == "pinhash"
    assert len(lm._state.lawn_polygon) > 0


def test_tick_ignores_telemetry_in_blank_mode():
    device = SimpleNamespace(
        status=SimpleNamespace(started=True),
        latest_position=(100, 100),  # 1 m, 0.1 m
        obstacle_detected=False,
        latest_session_summary=None,
    )
    lm = _make_live_map(device=device)
    lm._coordinator.device = device
    lm.set_mode(MapMode.BLANK)
    lm._handle_coordinator_update()
    assert lm._state.path == []
    assert lm._state.mode is MapMode.BLANK


def test_tick_ignores_telemetry_in_session_mode(tmp_path):
    fixture = tmp_path / "pinned.json"
    fixture.write_text(FIXTURE_PATH.read_text())
    entry = SimpleNamespace(filename="pinned.json", md5="pinhash")
    archive = FakeArchive([entry])
    archive.root = tmp_path
    device = SimpleNamespace(
        status=SimpleNamespace(started=True),
        latest_position=(100, 100),
        obstacle_detected=False,
        latest_session_summary=None,
    )
    lm = _make_live_map(archive=archive, device=device)
    lm.set_mode(MapMode.SESSION, archive_entry=entry)
    overlay_before = list(lm._state.lawn_polygon)
    lm._handle_coordinator_update()
    assert lm._state.path == []
    assert lm._state.lawn_polygon == overlay_before  # unchanged


def test_latest_mode_session_start_wipes_overlay():
    """In LATEST mode, when a new run begins, the previous-session overlay is wiped
    so the map shows a clean canvas + the new live path only."""
    device_state = {"started": False}
    device = SimpleNamespace(
        status=SimpleNamespace(),
        latest_position=None,
        obstacle_detected=False,
        latest_session_summary=None,
    )
    # dynamic started property
    type(device.status).started = property(lambda self: device_state["started"])

    lm = _make_live_map(device=device)
    lm._coordinator.device = device
    lm._state.lawn_polygon = [[0.0, 0.0], [1.0, 0.0]]
    lm._state.completed_track = [[[0.0, 0.0]]]
    lm._state.summary_md5 = "old"

    device_state["started"] = True
    lm._handle_coordinator_update()

    assert lm._state.lawn_polygon == []
    assert lm._state.completed_track == []
    assert lm._state.summary_md5 is None
```

- [ ] **Step 2.2: Run the new tests — expect failure**

```
python -m pytest tests/live_map/test_mode_transitions.py -v
```

Expected: FAILs — `set_mode` on DreameA2LiveMap not implemented, coordinator tick not mode-aware.

- [ ] **Step 2.3: Implement `DreameA2LiveMap.set_mode()`**

Replace `clear_replay`, `render_blank`, `replay_session`, `replay_latest_session` methods with:

```python
    def set_mode(
        self,
        mode: "MapMode",
        archive_entry=None,
    ) -> dict[str, Any]:
        """Set the replay picker mode.

        LATEST:  load newest archive into overlay (if any); live accumulators reset.
        SESSION: archive_entry required; load that session into overlay and pin it.
        BLANK:   empty canvas.

        Emits a snapshot dispatch so the camera invalidates its composed cache
        and the dashboard refreshes.
        """
        self._state.set_mode(mode, pinned_md5=getattr(archive_entry, "md5", None))

        result: dict[str, Any] = {"mode": mode.value}
        if mode is MapMode.LATEST:
            archive = getattr(self._coordinator, "session_archive", None)
            latest = archive.latest() if archive else None
            if latest is not None:
                path = archive.root / latest.filename
                try:
                    replay_from_archive_file(
                        self._state, str(path), self.x_factor, self.y_factor
                    )
                    self._state.pinned_md5 = None  # LATEST is not pinned
                    result["md5"] = self._state.summary_md5
                except (FileNotFoundError, ValueError) as ex:
                    result["error"] = str(ex)
        elif mode is MapMode.SESSION:
            if archive_entry is None:
                raise ValueError("archive_entry is required for SESSION mode")
            archive = getattr(self._coordinator, "session_archive", None)
            if archive is None:
                raise ValueError("session archive unavailable")
            path = archive.root / archive_entry.filename
            replay_from_archive_file(
                self._state, str(path), self.x_factor, self.y_factor
            )
            self._state.pinned_md5 = archive_entry.md5
            result["md5"] = archive_entry.md5

        attrs = self._state.to_attributes(
            position=None,
            x_factor=self.x_factor,
            y_factor=self.y_factor,
        )
        _send_update(self._hass, LIVE_MAP_UPDATE_SIGNAL, attrs)
        return result
```

Make the coordinator tick mode-aware:

```python
    @callback
    def _handle_coordinator_update(self) -> None:
        device = self._coordinator.device
        if device is None:
            return

        # SESSION and BLANK freeze: no telemetry absorbed, no snapshot dispatched.
        # The snapshot pushed by set_mode() is the final word until the picker
        # changes again.
        if self._state.mode is not MapMode.LATEST:
            return

        try:
            active = bool(device.status.started)
        except AttributeError:
            active = False

        if active and not self._prev_session_active:
            # New run. Wipe the previous session's overlay — in LATEST mode we
            # want a clean canvas plus the new live path only. The previous
            # session's completed_track is no longer "the latest thing".
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._state.start_session(now_iso)
            self._state.lawn_polygon = []
            self._state.exclusion_zones = []
            self._state.completed_track = []
            self._state.obstacle_polygons = []
            self._state.dock_position = None
            self._state.summary_md5 = None
            self._state.summary_end_ts = None
        self._prev_session_active = active

        # Pick up a fresh session summary (fires once per session completion
        # on g2408). In LATEST mode, this becomes the new overlay.
        summary = getattr(device, "latest_session_summary", None)
        if summary is not None:
            if self._state.load_from_session_summary(summary):
                # New summary landed — the live path has been superseded.
                self._state.path = []
                self._state.obstacles = []

        pos_source = getattr(device, "latest_position", None)
        if pos_source is None:
            telem = getattr(device, "mowing_telemetry", None)
            if telem is not None:
                pos_source = (telem.x_cm, telem.y_mm)

        position = None
        if pos_source is not None and active:
            x_cm, y_mm = pos_source
            x_m = (x_cm / 100.0) * self.x_factor
            y_m = (y_mm / 1000.0) * self.y_factor
            position = [round(x_m, 3), round(y_m, 3)]
            self._state.append_point(x_m, y_m)

        try:
            obstacle_on = bool(device.obstacle_detected)
        except AttributeError:
            obstacle_on = False

        if obstacle_on and position is not None:
            self._state.append_obstacle(position[0], position[1])

        attrs = self._state.to_attributes(
            position=position,
            x_factor=self.x_factor,
            y_factor=self.y_factor,
        )
        async_dispatcher_send(self._hass, LIVE_MAP_UPDATE_SIGNAL, attrs)
```

- [ ] **Step 2.4: Run test_mode_transitions**

```
python -m pytest tests/live_map/test_mode_transitions.py -v
```

Expected: PASS.

- [ ] **Step 2.5: Run all live_map tests**

```
python -m pytest tests/live_map -v
```

Expected: PASS.

- [ ] **Step 2.6: Commit**

```
git -C ha-dreame-a2-mower add custom_components/dreame_a2_mower/live_map.py tests/live_map/test_mode_transitions.py
git -C ha-dreame-a2-mower commit -m "refactor(live-map): mode-aware coordinator tick via set_mode()"
```

---

## Task 3: Replace replay picker select

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py:290-448`

- [ ] **Step 3.1: Rewrite `DreameReplaySessionSelect`**

Replace the class body (from `class DreameReplaySessionSelect` to end of file) with:

```python
class DreameReplaySessionSelect(SelectEntity):
    """Dashboard picker for live-map mode selection.

    Options:

        "Latest"  — default. Shows the current run, or the newest archive
                    if no run is active. Auto-tracks: when a new run starts,
                    the map clears and begins drawing the new run live.
        "Blank"   — empty canvas (for screenshots).
        "<date>"  — pin the map to one archived session. Frozen: not affected
                    by mower activity or new archives arriving.

    Selecting an option calls `live_map.set_mode(...)` on an executor thread
    so the blocking JSON parse does not run on the event loop.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    _OPT_LATEST = "Latest"
    _OPT_BLANK = "Blank"

    def __init__(self, coordinator: DreameMowerDataUpdateCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_name = "Replay Session"
        self._attr_unique_id = f"{coordinator.device.mac}_replay_session"
        device = coordinator.device
        info = getattr(device, "info", None)
        from homeassistant.helpers.entity import DeviceInfo
        from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, device.mac)},
            identifiers={(DOMAIN, device.mac)},
            name=device.name,
            manufacturer=getattr(info, "manufacturer", None),
            model=getattr(info, "model", None),
            sw_version=getattr(info, "firmware_version", None),
            hw_version=getattr(info, "hardware_version", None),
        )
        self._attr_current_option = self._OPT_LATEST
        # md5 of the currently-pinned session (only set when user picked a date).
        # Survives archive growth so the label can be reconstructed if the
        # display string changes.
        self._pinned_md5: str | None = None
        self._refresh_options()

    @staticmethod
    def _format_label(entry) -> str:
        import datetime as _dt
        ts = _dt.datetime.fromtimestamp(entry.end_ts).strftime("%Y-%m-%d %H:%M")
        return f"{ts} — {entry.area_mowed_m2:.2f} m² ({entry.duration_min} min)"

    def _refresh_options(self) -> None:
        archive = self._coordinator.session_archive
        all_sessions = archive.list_sessions() if archive else []
        from .const import SESSION_REPLAY_PICKER_HARD_CAP
        sessions = all_sessions[:SESSION_REPLAY_PICKER_HARD_CAP]
        self._label_to_entry = {self._format_label(s): s for s in sessions}
        self._attr_options = [
            self._OPT_LATEST,
            self._OPT_BLANK,
            *self._label_to_entry.keys(),
        ]

    @property
    def available(self) -> bool:
        return self._coordinator.session_archive is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        prev_opts = tuple(self._attr_options)
        self._refresh_options()
        if tuple(self._attr_options) == prev_opts:
            return

        # If the user had pinned a specific session, try to preserve it by
        # locating the entry with the same md5. Its label may change (the
        # duration / area can drift if retention re-indexes) but the md5 is
        # stable.
        if self._pinned_md5 is not None:
            for label, entry in self._label_to_entry.items():
                if entry.md5 == self._pinned_md5:
                    self._attr_current_option = label
                    self.async_write_ha_state()
                    return
            # Pinned entry got evicted — fall back to Latest.
            self._pinned_md5 = None
            self._attr_current_option = self._OPT_LATEST
            self.async_write_ha_state()
            return

        # Non-pinned (Latest / Blank) — still valid, no change needed.
        if self._attr_current_option not in self._attr_options:
            self._attr_current_option = self._OPT_LATEST
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise HomeAssistantError(f"Unknown replay option: {option}")

        live_map = getattr(self._coordinator, "live_map", None)
        if live_map is None:
            raise HomeAssistantError("Live map is not available on this device")

        from .live_map import MapMode

        if option == self._OPT_LATEST:
            await self.hass.async_add_executor_job(live_map.set_mode, MapMode.LATEST)
            self._pinned_md5 = None
        elif option == self._OPT_BLANK:
            await self.hass.async_add_executor_job(live_map.set_mode, MapMode.BLANK)
            self._pinned_md5 = None
        else:
            entry = self._label_to_entry.get(option)
            if entry is None:
                raise HomeAssistantError(f"No archive entry for option {option}")
            await self.hass.async_add_executor_job(
                live_map.set_mode, MapMode.SESSION, entry
            )
            self._pinned_md5 = entry.md5

        self._attr_current_option = option
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._attr_current_option in (self._OPT_LATEST, self._OPT_BLANK):
            return {"pinned_md5": None}
        return {"pinned_md5": self._pinned_md5}
```

- [ ] **Step 3.2: Syntax check**

```
python -m py_compile custom_components/dreame_a2_mower/select.py
```

Expected: no output.

- [ ] **Step 3.3: Commit**

```
git -C ha-dreame-a2-mower add custom_components/dreame_a2_mower/select.py
git -C ha-dreame-a2-mower commit -m "refactor(select): drop Live option; use set_mode() + sticky md5 pin"
```

---

## Task 4: Camera composed-cache invalidation on mode change

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py:657-672` (_on_live_map_update)

- [ ] **Step 4.1: Edit `_on_live_map_update`**

Add tracking of the last seen mode and invalidate the composed cache on mode changes:

```python
    @callback
    def _on_live_map_update(self, attrs: dict) -> None:
        new_mode = attrs.get("mode")
        prev_mode = (self._live_map_attrs or {}).get("mode")
        self._live_map_attrs = attrs
        self._feed_trail_layer(attrs)
        # On mode change, nuke the composed cache unconditionally. The cache
        # key (id(base_image), trail_version) does not always invalidate
        # when the overlay changes without a new base PNG — user reported
        # 2026-04-20 that dashboard stayed on the old replay until the
        # more-info popup was opened. Always clear on mode change.
        if new_mode != prev_mode:
            self._composed_cache = None
        Camera.async_update_token(self)
        self.async_write_ha_state()
```

- [ ] **Step 4.2: Syntax check**

```
python -m py_compile custom_components/dreame_a2_mower/camera.py
```

- [ ] **Step 4.3: Commit**

```
git -C ha-dreame-a2-mower add custom_components/dreame_a2_mower/camera.py
git -C ha-dreame-a2-mower commit -m "fix(camera): invalidate composed cache on live-map mode change"
```

---

## Task 5: Dashboard yaml + ancillary docs

**Files:**
- Modify: `dashboards/mower.yaml:40-51`
- Possibly modify: `docs/dashboard-setup.md` (if present)

- [ ] **Step 5.1: Update picker comment in mower.yaml**

Replace the comment above the Replay entities card with:

```yaml
      # Session replay picker — controls what the Live map camera shows.
      #   "Latest": follows the current (or most recent) run live. When a
      #             new run starts the map clears and begins drawing it.
      #   "Blank":  empty canvas for screenshots; not affected by activity.
      #   "<date>": pins the map to one archived session, frozen until you
      #             pick something else. Mower activity does not affect it.
```

- [ ] **Step 5.2: Check dashboard-setup doc**

```
ls docs/dashboard-setup.md 2>/dev/null && grep -n "Live\|Latest\|Blank\|None" docs/dashboard-setup.md
```

If it mentions the picker options, update the listing to match.

- [ ] **Step 5.3: Commit**

```
git -C ha-dreame-a2-mower add dashboards/mower.yaml docs/
git -C ha-dreame-a2-mower commit -m "docs: update replay picker description for Latest/Blank/<date> modes"
```

---

## Task 6: Full test run + push

- [ ] **Step 6.1: Run complete test suite**

```
cd /data/claude/homeassistant/ha-dreame-a2-mower
python -m pytest tests/ -v
```

Expected: all green.

- [ ] **Step 6.2: Push upstream**

```
git -C ha-dreame-a2-mower push
```

Per memory: HACS pulls from origin/main, so don't let integration commits sit unpushed.

---

## Self-review

- Spec coverage: Tasks 1-5 cover removal of Live option, Latest auto-tracking, sticky date selection, blank canvas, dropped docked-mower special case, and composed-cache fix. ✓
- Placeholders: none. ✓
- Type consistency: `set_mode(mode, archive_entry=None)` in live_map.py; `live_map.set_mode(MapMode.SESSION, entry)` in select.py — names match. ✓
- `MapMode` import paths: from `live_map` in tests, `from .live_map import MapMode` in select.py. ✓
