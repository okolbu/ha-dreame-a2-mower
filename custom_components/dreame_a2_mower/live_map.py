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
OBSTACLE_DEDUPE_METRES = 0.5


@dataclass
class LiveMapState:
    """Pure state machine tracking the current session's map data."""

    path: list[list[float]] = field(default_factory=list)
    obstacles: list[list[float]] = field(default_factory=list)
    session_id: int = 0
    session_start: str | None = None
    _pending: list[list[float]] = field(default_factory=list)

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

    def start_session(self, session_start_iso: str) -> None:
        """Reset per-session state and bump session_id."""
        self.path = []
        self.obstacles = []
        self.session_id += 1
        self.session_start = session_start_iso

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


# -------------------------------------------------------------
# HA integration glue — below this line depends on homeassistant.
# -------------------------------------------------------------

from datetime import datetime, timezone
from typing import Any

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, callback
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    HA_AVAILABLE = True
except ImportError:
    HA_AVAILABLE = False
    ConfigEntry = None
    HomeAssistant = None
    callback = lambda f: f  # no-op decorator
    def async_dispatcher_send(*args, **kwargs): pass

# Import DOMAIN defensively (works both as relative and absolute)
try:
    from .const import DOMAIN
except ImportError:
    # When tests load via pythonpath, the module isn't part of a package —
    # fall back to importing const directly.
    try:
        from const import DOMAIN
    except ImportError:
        DOMAIN = "dreame_a2_mower"

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
