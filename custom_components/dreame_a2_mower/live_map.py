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


def replay_from_archive_file(
    state: "LiveMapState",
    file_path,
    x_factor: float,
    y_factor: float,
) -> dict:
    """Load an archived session-summary JSON and replay it into
    ``state`` — populating both the overlay fields and the ``path`` list.

    Pure helper; no HA types. The caller is responsible for dispatching
    the resulting snapshot.

    Returns a small result dict: ``md5``, ``path_points``, ``path``.
    Raises ``FileNotFoundError`` if the file does not exist, or
    ``ValueError`` if the file is not valid JSON / not a session
    summary.
    """
    from pathlib import Path
    import json
    try:
        from .protocol.session_summary import parse_session_summary, InvalidSessionSummary
    except ImportError:
        # Test harness runs outside the HA package layout.
        from protocol.session_summary import parse_session_summary, InvalidSessionSummary

    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"session archive not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as ex:
        raise ValueError(f"archive file is not valid JSON: {ex}") from ex
    try:
        summary = parse_session_summary(data)
    except InvalidSessionSummary as ex:
        raise ValueError(f"archive file is not a session summary: {ex}") from ex

    state.load_from_session_summary(summary)

    # Do NOT flatten completed_track into state.path — each track
    # segment represents a continuous pen-down stroke, and the pen-up
    # gaps between them correspond to dock visits / path-planner
    # jumps that should NOT be drawn as connecting lines. A flat
    # `path` would render a straight line across every such gap
    # (user reported "ghost segments" 2026-04-19). The TrailLayer's
    # `reset_to_session` draws each segment separately as a distinct
    # `ImageDraw.line` call, so the gaps stay invisible.
    state.path = []

    total_track_points = sum(len(seg) for seg in state.completed_track)
    return {
        "md5": state.summary_md5,
        "path_points": total_track_points,
        "segments": len(state.completed_track),
    }


@dataclass
class LiveMapState:
    """Pure state machine tracking the current session's map data.

    Two layers of data coexist:

    - **Live stream** (during an active session): `path` accumulates s1p4
      positions with dedupe; `obstacles` accumulates s1p53 trigger points.
    - **Session-summary overlay** (populated once per completed session from
      the OSS JSON): `lawn_polygon`, `exclusion_zones`, `completed_track`,
      and `obstacle_polygons` persist the mower's authoritative map so the
      card has a stable underlay even while docked.
    """

    path: list[list[float]] = field(default_factory=list)
    obstacles: list[list[float]] = field(default_factory=list)
    session_id: int = 0
    session_start: str | None = None
    _pending: list[list[float]] = field(default_factory=list)

    # Fields sourced from the session-summary JSON. All coordinates are
    # metres in the mower / charger-relative frame (no calibration needed —
    # the JSON emits cm on both axes and the parser converts).
    lawn_polygon: list[list[float]] = field(default_factory=list)
    exclusion_zones: list[list[list[float]]] = field(default_factory=list)
    completed_track: list[list[list[float]]] = field(default_factory=list)
    obstacle_polygons: list[list[list[float]]] = field(default_factory=list)
    dock_position: list[float] | None = None
    summary_md5: str | None = None
    summary_end_ts: int | None = None

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

    def load_from_session_summary(self, summary) -> bool:
        """Populate overlay fields from a `protocol.session_summary.SessionSummary`.

        Returns `True` if the state actually changed (new summary arrived),
        `False` if the given summary matches what we already have. Idempotent
        so the caller can invoke this unconditionally on every update tick
        without churning the snapshot dispatcher.
        """
        if summary is None:
            return False
        new_md5 = getattr(summary, "md5", None) or None
        new_end = getattr(summary, "end_ts", None) or None
        if self.summary_md5 == new_md5 and self.summary_end_ts == new_end and new_md5 is not None:
            return False
        self.lawn_polygon = [list(p) for p in summary.lawn_polygon]
        self.exclusion_zones = [
            [list(p) for p in ex.points] for ex in summary.exclusions
        ]
        self.completed_track = [
            [list(p) for p in seg] for seg in summary.track_segments
        ]
        self.obstacle_polygons = [
            [list(p) for p in o.polygon] for o in summary.obstacles
        ]
        dock = getattr(summary, "dock", None)
        self.dock_position = [dock[0], dock[1]] if dock else None
        self.summary_md5 = new_md5
        self.summary_end_ts = new_end
        return True

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
            # Session-summary overlay — static once per completed session.
            "lawn_polygon": list(self.lawn_polygon),
            "exclusion_zones": [list(z) for z in self.exclusion_zones],
            "completed_track": [list(s) for s in self.completed_track],
            "obstacle_polygons": [list(o) for o in self.obstacle_polygons],
            "dock_position": list(self.dock_position) if self.dock_position else None,
            "summary_end_ts": self.summary_end_ts,
            "summary_md5": self.summary_md5,
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


def _send_update(hass, signal: str, attrs) -> None:
    """Fire a dispatcher signal from any thread.

    HA's `async_dispatcher_send` is event-loop-only; calling it from a
    worker thread raises the "calls async_dispatcher_send from a thread
    other than the event loop" warning and may be refused entirely in
    newer HA versions. `replay_session` and friends run inside
    `hass.async_add_executor_job` (I/O + JSON parse on a worker), so
    the final dispatch has to hop back onto the loop via
    `call_soon_threadsafe`. When called from the event loop the hop is
    a no-op.
    """
    if hass is None:
        return
    loop = getattr(hass, "loop", None)
    if loop is None:
        async_dispatcher_send(hass, signal, attrs)
        return
    loop.call_soon_threadsafe(async_dispatcher_send, hass, signal, attrs)

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
            # Preserve the static overlay (lawn polygon, exclusions, prior
            # completed track, obstacle polygons) across sessions — only
            # clear the live-stream accumulators.
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._state.start_session(now_iso)
            self._state.flush_pending()
        self._prev_session_active = active

        # 1b) Pick up a newly-fetched session summary (happens once per
        # session completion on g2408).
        try:
            summary = getattr(device, "latest_session_summary", None)
        except Exception:
            summary = None
        if summary is not None:
            self._state.load_from_session_summary(summary)

        # 2) Position from telemetry. Prefer `latest_position` (tuple set by
        # the blob decoder on every s1p4 arrival, including the 8-byte idle
        # beacon) so the map overlay moves during remote-drive / learn
        # modes, not just active mow sessions. Fall back to `mowing_telemetry`
        # when that's all we have.
        pos_source = getattr(device, "latest_position", None)
        if pos_source is None:
            telem = getattr(device, "mowing_telemetry", None)
            if telem is not None:
                pos_source = (telem.x_cm, telem.y_mm)

        position = None
        if pos_source is not None:
            x_cm, y_mm = pos_source
            x_m = (x_cm / 100.0) * self.x_factor
            y_m = (y_mm / 1000.0) * self.y_factor
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

    def replay_session(self, file_path: str) -> dict[str, Any]:
        """Replay an archived session-summary JSON into the camera.

        Reads ``<file_path>`` (typically under
        `<config>/dreame_a2_mower/sessions/<YYYY-MM-DD>_<ts>_<md5>.json`),
        parses it, populates this live-map state's overlay fields plus
        the path list, and dispatches a snapshot so the map card
        redraws with the historical run frozen in place.

        Used by the `dreame_a2_mower.replay_session` HA service.
        """
        result = replay_from_archive_file(
            self._state, file_path, self.x_factor, self.y_factor
        )
        attrs = self._state.to_attributes(
            position=None,  # no live mower position during replay
            x_factor=self.x_factor,
            y_factor=self.y_factor,
        )
        # `_send_update` hops to the event loop if we're on a worker
        # thread — replay_session is routed through
        # `hass.async_add_executor_job` by the `replay_session` service
        # and the session-picker select, both of which call us from a
        # non-loop thread.
        _send_update(self._hass, LIVE_MAP_UPDATE_SIGNAL, attrs)
        return result

    def replay_latest_session(self) -> dict[str, Any]:
        """Convenience: replay the most recently archived session.

        Looks up the latest entry in the coordinator's session archive
        and delegates to :meth:`replay_session`.
        """
        coord = self._coordinator
        archive = getattr(coord, "session_archive", None) if coord else None
        if archive is None:
            raise ValueError("session archive is not available")
        latest = archive.latest()
        if latest is None:
            raise ValueError("no archived sessions to replay")
        path = archive.root / latest.filename
        return self.replay_session(str(path))

    def clear_replay(self) -> None:
        """Clear the session-summary overlay so the map shows only the
        live base data (zones, calibration, current position). Used by
        the session-picker entity when the user selects "None".
        """
        self._state.lawn_polygon = []
        self._state.exclusion_zones = []
        self._state.completed_track = []
        self._state.obstacle_polygons = []
        self._state.dock_position = None
        self._state.summary_md5 = None
        self._state.summary_end_ts = None
        # No live position argument — the coordinator's next tick will
        # push the current mower position through the normal path. If
        # the mower is docked right now, this leaves `position: None`
        # which is what the base-map renderer expects.
        attrs = self._state.to_attributes(
            position=None,
            x_factor=self.x_factor,
            y_factor=self.y_factor,
        )
        # Thread-safe: the session-picker select calls us via
        # `hass.async_add_executor_job`.
        _send_update(self._hass, LIVE_MAP_UPDATE_SIGNAL, attrs)

    def render_blank(self) -> None:
        """Wipe BOTH the session-summary overlay AND the live path so
        the camera shows only the static base map (zones + exclusions
        + charger, no trail, no mower marker).

        Distinct from `clear_replay()` which keeps the live stream so
        a trail reappears the instant the mower reports a new
        position. This method zeroes out the live accumulators too;
        the next `_handle_coordinator_update` with a live position
        WILL repopulate state.path, so the effect of "Blank" is only
        durable while no s1p4 arrives — i.e. while the mower is
        parked / silent. This is the expected UX: a clean static map
        for screenshots or when the user explicitly wants to see only
        the lawn layout.
        """
        self._state.lawn_polygon = []
        self._state.exclusion_zones = []
        self._state.completed_track = []
        self._state.obstacle_polygons = []
        self._state.dock_position = None
        self._state.summary_md5 = None
        self._state.summary_end_ts = None
        self._state.path = []
        self._state.obstacles = []
        self._state._pending = []
        self._state.session_id = 0
        self._state.session_start = None
        attrs = self._state.to_attributes(
            position=None,
            x_factor=self.x_factor,
            y_factor=self.y_factor,
        )
        _send_update(self._hass, LIVE_MAP_UPDATE_SIGNAL, attrs)

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
        # Same thread-safety note as replay_session / clear_replay —
        # `import_path_from_probe_log` runs this through the executor.
        _send_update(self._hass, LIVE_MAP_UPDATE_SIGNAL, attrs)
        return {
            "path_points": len(self._state.path),
            "session_index": idx,
            "total_sessions": len(sessions),
            "start_timestamp": target[0].timestamp,
        }
