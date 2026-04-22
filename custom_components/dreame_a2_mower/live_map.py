"""Live-map state machine and Home Assistant glue for Plan E.1.

`LiveMapState` is a pure Python state machine that turns a stream of
telemetry/obstacle events into a snapshot dict consumable by a Lovelace
map card. It has no HA dependency and is unit-testable in isolation.

See docs/superpowers/specs/2026-04-18-live-map-overlay-design.md for the
design rationale and attribute schema.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum

_LOGGER = logging.getLogger(__name__)

PATH_DEDUPE_METRES = 0.2
OBSTACLE_DEDUPE_METRES = 0.5


class MapMode(str, Enum):
    """Replay-picker selection. Determines what the camera snapshot shows.

    - LATEST:  auto-track. Shows the current run live, or the most recent
               archived session when no run is active. New run starting
               wipes the overlay and begins drawing the new run.
    - SESSION: pinned to one archived session, frozen until another mode
               is selected. Mower activity does not affect it.
    - BLANK:   empty canvas, for screenshots. Not touched by telemetry.
    """

    LATEST = "latest"
    SESSION = "session"
    BLANK = "blank"


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

    mode: MapMode = MapMode.LATEST
    pinned_md5: str | None = None

    path: list[list[float]] = field(default_factory=list)
    obstacles: list[list[float]] = field(default_factory=list)
    session_id: int = 0
    session_start: str | None = None

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
            "mode": self.mode.value,
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

    def set_mode(self, mode: "MapMode", pinned_md5: str | None = None) -> None:
        """Switch to ``mode``, clearing fields that don't belong there.

        LATEST:  live accumulators + overlay + pinned_md5 all cleared.
                 Caller is expected to reload the newest archive (if any)
                 after this so the snapshot reflects the last run.
        SESSION: live accumulators cleared, pinned_md5 set. Caller is
                 expected to load the pinned archive into the overlay.
        BLANK:   everything cleared; session_id reset.
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

# Mower deck width in metres — used as the swath width when estimating
# in-progress mowed area from the live path. Approximation only: the
# real area depends on overlap pattern. Cloud-summary `areas` overrides
# this once a leg completes.
_LIVE_AREA_SWATH_M = 0.32


def _iso_to_unix(iso: str | None) -> int:
    """Parse an ISO-8601 timestamp into a unix int. 0 on failure."""
    if not iso:
        return 0
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (TypeError, ValueError):
        return 0


def _approximate_area(path: list[list[float]]) -> float:
    """Rough mowed-area estimate: path length × deck swath width.

    Used only for the in-progress picker label so users see a
    plausible "X m²" while a run is in progress. Replaced by the
    authoritative cloud `areas` value once a leg summary lands.
    """
    if not path or len(path) < 2:
        return 0.0
    total = 0.0
    prev = path[0]
    for pt in path[1:]:
        dx = pt[0] - prev[0]
        dy = pt[1] - prev[1]
        total += math.hypot(dx, dy)
        prev = pt
    return round(total * _LIVE_AREA_SWATH_M, 2)


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
        # In-progress entry persistence: while a logical mow is active
        # (started==True, possibly across recharge legs) the live path
        # accumulator is written to `<config>/dreame_a2_mower/sessions/
        # in_progress.json` every ~10s. An HA restart mid-mow restores
        # this entry so the Latest view picks up where it left off. The
        # picker surfaces it like any completed run, sorted to the top
        # by `last_update_ts`. See session_archive.SessionArchive.
        # Migration: any leftover legacy `drafts/` files are unlinked
        # on first boot — keeping that path alive isn't worth the
        # divergence with the new design (user agreed to discard).
        self._last_persist_at: float = 0.0
        # Track which leg md5s we have already merged into the
        # in-progress entry. Each cloud `event_occured` summary fires
        # a leg; multi-leg recharge cycles merge into one in-progress
        # entry until `started` finally drops.
        self._in_progress_leg_md5s: list[str] = []
        try:
            self._migrate_legacy_drafts(hass)
        except Exception:  # pragma: no cover — best-effort cleanup
            pass
        if self._restore_in_progress():
            # Seed `_prev_session_active = True` so the first
            # coordinator tick doesn't treat us as a fresh
            # session-start and wipe the just-restored path.
            self._prev_session_active = True

    def _migrate_legacy_drafts(self, hass) -> None:
        """One-shot cleanup of the old `drafts/live_path_*.json` files.

        Replaced by sessions/in_progress.json (managed via
        SessionArchive). Anything in drafts/ would be stale after this
        rewrite anyway — wipe it so two stores can't disagree.
        """
        from pathlib import Path as _Path
        try:
            from .const import DOMAIN as _DOMAIN
        except ImportError:
            _DOMAIN = "dreame_a2_mower"
        legacy = _Path(hass.config.path(_DOMAIN, "drafts"))
        if not legacy.exists():
            return
        for child in legacy.glob("live_path_*.json"):
            try:
                child.unlink()
            except OSError:
                pass
        try:
            legacy.rmdir()
        except OSError:
            pass

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
        _LOGGER.debug("live_map: subscribed to coordinator updates")

    @callback
    def async_unload(self) -> None:
        if self._unsub_listener:
            self._unsub_listener()
            self._unsub_listener = None

    def _persist_in_progress(self) -> None:
        """Write the current live path to the in-progress archive entry.

        Throttled to one disk write per ~10s so even devices that push
        s1p4 telemetry at several Hz don't cause excessive I/O on the
        coordinator's hot path. Called from `_handle_coordinator_update`
        while a session is active.

        The payload mirrors what `LiveMapState` would render: live path,
        live obstacles, plus the static overlay (lawn polygon /
        exclusions / dock / completed_track) carried forward from any
        leg summaries already merged. That way a restart reconstructs
        a visually-identical Latest view immediately rather than
        waiting for the cloud to re-push the geometry.
        """
        import time as _time
        archive = getattr(self._coordinator, "session_archive", None)
        if archive is None:
            return
        now = _time.monotonic()
        if now - self._last_persist_at < 10.0:
            return
        self._last_persist_at = now
        payload = {
            "session_id": self._state.session_id,
            "session_start": self._state.session_start,
            "session_start_ts": _iso_to_unix(self._state.session_start),
            "live_path": self._state.path,
            "obstacles": self._state.obstacles,
            "leg_md5s": list(self._in_progress_leg_md5s),
            "completed_track": self._state.completed_track,
            "lawn_polygon": self._state.lawn_polygon,
            "exclusion_zones": self._state.exclusion_zones,
            "obstacle_polygons": self._state.obstacle_polygons,
            "dock_position": self._state.dock_position,
            "summary_md5": self._state.summary_md5,
            "summary_end_ts": self._state.summary_end_ts,
            # Coarse derived fields so the picker label has something
            # meaningful even when no leg summary has arrived yet.
            "area_mowed_m2": _approximate_area(self._state.path),
            "map_area_m2": 0,
        }
        archive.write_in_progress(payload)

    def _restore_in_progress(self) -> bool:
        """Repopulate `self._state` from a persisted in-progress entry.

        Returns True if an entry was loaded so the caller can seed
        `_prev_session_active = True` and avoid re-firing the
        fresh-session wipe on the very next tick.
        """
        archive = getattr(self._coordinator, "session_archive", None)
        if archive is None:
            return False
        data = archive.read_in_progress()
        if data is None:
            return False
        try:
            self._state.session_id = int(data.get("session_id", 0))
            self._state.session_start = data.get("session_start")
            self._state.path = [list(p) for p in data.get("live_path", [])]
            self._state.obstacles = [list(p) for p in data.get("obstacles", [])]
            # Self-heal: in-progress files written between the in-progress
            # refactor (alpha.46) and the leg-merge timestamp gate
            # (alpha.47) may carry the previous run's tracks merged
            # into completed_track. If the persisted `summary_end_ts`
            # falls *before* this session's start, the merge was bogus
            # and we drop the overlay carry-over (the picker / Latest
            # view will re-populate from the next legitimate leg).
            sst = _iso_to_unix(self._state.session_start)
            sumend = data.get("summary_end_ts") or 0
            if sst and sumend and int(sumend) < sst:
                self._state.completed_track = []
                self._state.lawn_polygon = []
                self._state.exclusion_zones = []
                self._state.obstacle_polygons = []
                self._state.dock_position = None
                self._state.summary_md5 = None
                self._state.summary_end_ts = None
                self._in_progress_leg_md5s = []
            else:
                self._state.completed_track = [
                    [list(p) for p in seg] for seg in data.get("completed_track", [])
                ]
                self._state.lawn_polygon = [
                    list(p) for p in data.get("lawn_polygon", [])
                ]
                self._state.exclusion_zones = [
                    [list(p) for p in z] for z in data.get("exclusion_zones", [])
                ]
                self._state.obstacle_polygons = [
                    [list(p) for p in o] for o in data.get("obstacle_polygons", [])
                ]
                dock = data.get("dock_position")
                self._state.dock_position = (
                    [dock[0], dock[1]] if dock else None
                )
                self._state.summary_md5 = data.get("summary_md5")
                self._state.summary_end_ts = data.get("summary_end_ts")
                self._in_progress_leg_md5s = list(data.get("leg_md5s", []))
        except (TypeError, ValueError):
            return False
        return True

    def _delete_in_progress(self) -> None:
        archive = getattr(self._coordinator, "session_archive", None)
        if archive is not None:
            archive.delete_in_progress()
        self._in_progress_leg_md5s = []

    def finalize_session(self) -> dict[str, Any]:
        """Close out the current in-progress entry, archiving if needed.

        Two cases:

        1. The cloud already shipped one or more leg summaries during
           the run — they're already in the per-leg archive (one entry
           per leg, written by the coordinator). Nothing to synthesize;
           just delete the in-progress aggregator.
        2. No leg summaries arrived (HA was down through the entire
           run, or the cloud was silent / the device offline). The
           live_path is the only record. Synthesize an "(incomplete)"
           archive entry from it so the run shows up in the picker
           with whatever path data we managed to capture, then delete.

        Returns a small result dict for the caller (e.g. the finalize
        button) so it can surface the outcome in the UI / logs.
        """
        archive = getattr(self._coordinator, "session_archive", None)
        if archive is None:
            return {"result": "no_archive"}
        data = archive.read_in_progress()
        if data is None:
            return {"result": "no_in_progress"}
        leg_md5s = list(data.get("leg_md5s", []))
        live_path = list(data.get("live_path", []))
        result: dict[str, Any] = {"result": "deleted"}
        if not leg_md5s and len(live_path) >= 2:
            entry = self._archive_incomplete_session(archive, data)
            if entry is not None:
                result = {
                    "result": "archived_incomplete",
                    "filename": entry.filename,
                    "area_mowed_m2": entry.area_mowed_m2,
                    "duration_min": entry.duration_min,
                }
        archive.delete_in_progress()
        self._in_progress_leg_md5s = []
        # Reset live state so the next tick starts clean.
        self._state.path = []
        self._state.obstacles = []
        self._state.completed_track = []
        self._state.lawn_polygon = []
        self._state.exclusion_zones = []
        self._state.obstacle_polygons = []
        self._state.dock_position = None
        self._state.summary_md5 = None
        self._state.summary_end_ts = None
        self._prev_session_active = False
        return result

    def _archive_incomplete_session(self, archive, data) -> Any:
        """Synthesize an "(incomplete)" archive entry from in-progress data.

        Used when no cloud leg summary ever arrived (e.g. HA missed the
        `event_occured` window). Stores enough so the picker shows
        the run with its captured path; flagged so the loader and any
        future analyser can tell this isn't an authoritative cloud
        summary.
        """
        import time as _time
        import hashlib as _hashlib
        start_ts = int(data.get("session_start_ts") or 0)
        end_ts = int(_time.time())
        live_path = [list(p) for p in data.get("live_path", [])]
        obstacles = [list(p) for p in data.get("obstacles", [])]
        area = _approximate_area(live_path)
        duration_min = max(0, (end_ts - start_ts) // 60) if start_ts else 0
        # md5 over the synthesized payload — gives a stable filename
        # and lets archive.has() dedupe if the user mashes the button
        # twice. Hex-truncated to match the cloud-summary md5 width.
        digest = _hashlib.md5(
            f"incomplete:{start_ts}:{end_ts}:{len(live_path)}".encode()
        ).hexdigest()
        raw = {
            "_incomplete": True,
            "_synthesized_by": "finalize_session",
            "start": start_ts,
            "end": end_ts,
            "areas": area,
            "map_area": int(data.get("map_area_m2", 0) or 0),
            "md5": digest,
            "dock": data.get("dock_position"),
            "live_path": live_path,
            "obstacles": obstacles,
            "lawn_polygon": data.get("lawn_polygon", []),
            "exclusion_zones": data.get("exclusion_zones", []),
            "obstacle_polygons": data.get("obstacle_polygons", []),
        }
        # Minimal stub matching the attrs SessionArchive.archive() reads
        # off the summary object. Not a real SessionSummary — this
        # path won't survive parse_session_summary, hence _incomplete.
        from types import SimpleNamespace as _NS
        stub = _NS(
            md5=digest,
            start_ts=start_ts,
            end_ts=end_ts,
            duration_min=duration_min,
            area_mowed_m2=area,
            map_area_m2=int(data.get("map_area_m2", 0) or 0),
        )
        return archive.archive(stub, raw_json=raw)

    @callback
    def _handle_coordinator_update(self) -> None:
        device = self._coordinator.device
        if device is None:
            _LOGGER.debug("live_map tick: device=None, skip")
            return

        # Live path accumulation runs on every tick regardless of the
        # picker's current mode. Users who click into a SESSION replay
        # during a mow expect the full current-run path to be waiting
        # for them when they return to Latest — not just what happened
        # after the click. If we gated accumulation on mode, switching
        # to Latest mid-mow would show the path truncated at the
        # switch point. Only the display/dispatch is gated on LATEST.
        try:
            active = bool(device.status.started)
        except AttributeError:
            active = False
        _LOGGER.debug(
            "live_map tick: mode=%s active=%s prev_active=%s "
            "session_known=%s path_len=%d",
            self._state.mode.value, active, self._prev_session_active,
            getattr(device, "_session_status_known", False),
            len(self._state.path),
        )

        # Auto-close in-progress entry: if the device has definitively
        # reported no active session (s2p56 known + started=False),
        # the in-progress file is obsolete. Either the cloud summary
        # already arrived and the coordinator promoted it, or no
        # summary will come for this run. Either way the entry
        # should not linger.
        # `_session_status_known` distinguishes "we haven't heard yet"
        # from "we asked and got empty", so a just-restored entry
        # isn't discarded during boot before the first s2p56 push.
        session_known = getattr(device, "_session_status_known", False)
        if session_known and not active and self._prev_session_active:
            # Logical session just ended. If any leg summary fired
            # during the run, the per-leg archive entries are already
            # on disk — `finalize_session` will simply drop the
            # in-progress aggregator. If no leg ever fired (e.g. HA
            # was down through the entire run, mower offline at the
            # cloud-event window), the captured live_path is the
            # only record — `finalize_session` synthesizes an
            # "(incomplete)" archive entry for it before deleting.
            self.finalize_session()

        # Session-boundary wipe: only clear the LATEST overlay when a
        # new session starts. In SESSION/BLANK mode this still resets
        # the accumulator so the buffered live path matches the new
        # run (rather than carrying forward stale points from the
        # previous run once the user eventually returns to Latest).
        if active and not self._prev_session_active:
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._state.start_session(now_iso)
            self._in_progress_leg_md5s = []
            if self._state.mode is MapMode.LATEST:
                self._state.lawn_polygon = []
                self._state.exclusion_zones = []
                self._state.completed_track = []
                self._state.obstacle_polygons = []
                self._state.dock_position = None
                self._state.summary_md5 = None
                self._state.summary_end_ts = None
        self._prev_session_active = active

        # Merge any newly-arrived leg summary into the live overlay so
        # the in-progress entry reflects the cloud's authoritative
        # geometry (lawn polygon, exclusions, completed_track) as
        # legs complete. Each leg's md5 is tracked so we don't
        # re-merge on subsequent ticks.
        #
        # CRITICAL gate: `device.latest_session_summary` is sticky — the
        # device keeps the previous run's summary in memory until a new
        # event_occured fires. Without a timestamp check, every fresh
        # session would absorb the *previous* run's tracks the moment
        # start_session() emptied `_in_progress_leg_md5s` (regression
        # observed 2026-04-22 right after the in-progress refactor:
        # Latest view rendered the previous run's path on top of an
        # empty live trail). Only merge a leg whose start_ts falls
        # inside the current logical session's window — i.e. >= the
        # session_start we wrote when start_session() fired (with a
        # small tolerance for clock skew across cloud/device).
        try:
            summary = getattr(device, "latest_session_summary", None)
        except Exception:
            summary = None
        leg_md5 = getattr(summary, "md5", None) if summary is not None else None
        if (
            summary is not None
            and leg_md5
            and leg_md5 not in self._in_progress_leg_md5s
        ):
            session_start_unix = _iso_to_unix(self._state.session_start)
            leg_start_unix = int(getattr(summary, "start_ts", 0) or 0)
            if active:
                # Multi-leg merge — but only if this leg actually
                # belongs to the current session (or session_start is
                # unknown, which is the cold-boot fallback).
                belongs_to_session = (
                    session_start_unix == 0
                    or leg_start_unix >= session_start_unix - 300
                )
                if belongs_to_session:
                    self._state.completed_track.extend(
                        [list(p) for p in seg] for seg in summary.track_segments
                    )
                    self._state.load_from_session_summary(summary)
                    self._in_progress_leg_md5s.append(leg_md5)
                else:
                    # Stale summary from the prior run — record the md5
                    # so we don't keep evaluating it on every tick, but
                    # don't import its data into this session.
                    self._in_progress_leg_md5s.append(leg_md5)
            elif self._state.mode is MapMode.LATEST:
                # Between-runs path: just adopt the summary as the
                # new Latest overlay (replaces whatever the picker
                # was showing). Path is wiped because there is no
                # live mow to extend it.
                if self._state.load_from_session_summary(summary):
                    self._state.path = []
                    self._state.obstacles = []

        pos_source = getattr(device, "latest_position", None)
        if pos_source is None:
            telem = getattr(device, "mowing_telemetry", None)
            if telem is not None:
                pos_source = (telem.x_cm, telem.y_mm)

        position = None
        if active and pos_source is not None:
            x_cm, y_mm = pos_source
            x_m = (x_cm / 100.0) * self.x_factor
            y_m = (y_mm / 1000.0) * self.y_factor
            position = [round(x_m, 3), round(y_m, 3)]
            # Accumulate into state.path in every mode — see top of
            # function. SESSION/BLANK simply won't dispatch this, but
            # the buffer survives for a subsequent Latest switch.
            self._state.append_point(x_m, y_m)

        try:
            obstacle_on = bool(device.obstacle_detected)
        except AttributeError:
            obstacle_on = False

        if obstacle_on and position is not None:
            self._state.append_obstacle(position[0], position[1])

        # Persist the in-progress entry while active so an HA restart
        # mid-mow can recover it. Throttled internally to ~10s.
        if active:
            self._persist_in_progress()

        # Only LATEST drives the displayed snapshot; SESSION/BLANK
        # remain frozen on whatever set_mode() last pushed.
        if self._state.mode is not MapMode.LATEST:
            _LOGGER.debug("live_map tick: mode=%s, skipping dispatch", self._state.mode.value)
            return

        attrs = self._state.to_attributes(
            position=position,
            x_factor=self.x_factor,
            y_factor=self.y_factor,
        )
        _LOGGER.debug(
            "live_map dispatch: signal=%s path=%d ct=%d pos=%s",
            LIVE_MAP_UPDATE_SIGNAL, len(attrs.get("path") or []),
            len(attrs.get("completed_track") or []), attrs.get("position"),
        )
        async_dispatcher_send(self._hass, LIVE_MAP_UPDATE_SIGNAL, attrs)

    @callback
    def handle_options_update(self) -> None:
        """Called by the __init__ options listener when the user edits calibration."""
        # Re-push a snapshot with the new calibration so the card sees it.
        self._handle_coordinator_update()

    def set_mode(
        self,
        mode: "MapMode",
        archive_entry=None,
    ) -> dict[str, Any]:
        """Switch the replay picker mode and dispatch a fresh snapshot.

        - LATEST: reset to auto-track. Loads the newest archive entry
          into the overlay (if any) so the card shows the most recent
          run. A subsequent session-start transition will wipe this
          overlay and begin drawing the new run live.
        - SESSION: pin the map to ``archive_entry``. Coordinator ticks
          will be ignored until the mode changes again.
        - BLANK: empty canvas. Same freeze behaviour as SESSION.

        Runs on a worker thread (blocking JSON parse) — callers in HA
        should dispatch through ``hass.async_add_executor_job``.
        """
        # If switching to LATEST mid-mow, preserve any live path already
        # accumulated so the user doesn't lose visible progress on
        # mode-switch. set_mode() on the state wipes path/obstacles
        # unconditionally; we snapshot first and restore below.
        preserved_path: list[list[float]] | None = None
        preserved_obstacles: list[list[float]] | None = None
        preserved_session_id: int | None = None
        preserved_session_start: str | None = None
        if mode is MapMode.LATEST:
            try:
                active = bool(self._coordinator.device.status.started)
            except AttributeError:
                active = False
            if active:
                preserved_path = list(self._state.path)
                preserved_obstacles = list(self._state.obstacles)
                preserved_session_id = self._state.session_id
                preserved_session_start = self._state.session_start

        self._state.set_mode(mode, pinned_md5=getattr(archive_entry, "md5", None))

        result: dict[str, Any] = {"mode": mode.value}
        if mode is MapMode.LATEST:
            if preserved_path is not None:
                # Mid-mow: leave overlay fields empty (already wiped
                # by set_mode), restore live accumulators so the user
                # keeps seeing progress they'd already watched.
                self._state.path = preserved_path
                self._state.obstacles = preserved_obstacles or []
                self._state.session_id = preserved_session_id or 0
                self._state.session_start = preserved_session_start
                result["mid_mow"] = True
            else:
                archive = getattr(self._coordinator, "session_archive", None)
                latest = archive.latest() if archive else None
                if latest is not None:
                    path = archive.root / latest.filename
                    try:
                        replay_from_archive_file(
                            self._state, str(path), self.x_factor, self.y_factor
                        )
                        self._state.pinned_md5 = None
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
