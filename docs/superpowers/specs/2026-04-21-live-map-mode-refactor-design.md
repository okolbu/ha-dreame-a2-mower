# Live-map mode refactor

**Date:** 2026-04-21
**Status:** Approved (spec complete, plan in `docs/superpowers/plans/2026-04-21-live-map-mode-refactor.md`)

## Problem

The live-map camera on the Mower dashboard has three interlocking issues:

1. **Replay picker refresh is flaky.** Selecting a date from the picker often leaves the dashboard showing the previous choice (or no map at all). The camera only catches up when the more-info popup is opened and closed. The token-rotation workaround added 2026-04-20 (`camera.py:661-671`) does not reliably invalidate the composed-image cache.
2. **Mode semantics are confused.** The picker has four options (`Live`, `Blank`, `Latest`, `<date>`). `Live` clears the overlay while preserving the live accumulators; `Blank` clears everything; `Latest` freezes the newest archive; `<date>` freezes an older archive. The distinction between `Live` and `Latest` is not useful in practice — `Live` is just "show nothing cached, accept whatever is happening," and during a run `Latest` is stale until the new session summary lands.
3. **Docked-mower special casing.** The code avoids drawing the mower marker when docked by passing `position=None` through `clear_replay`. This is implicit behavior coupled to the `Live` option and leaks across mode boundaries.

## Goals

- One clear default: the picker always shows *the current run, or the most recent one if no run is active*.
- Session replays are sticky: pick a date, see that session until you pick something else. Mower activity does not affect it.
- Blank is a true empty canvas — for screenshots.
- The replay picker's selection reliably reflects on the dashboard image without more-info gymnastics.
- Remove bespoke "mower at charging station" handling. The trail ends where the last reported point is; that is sufficient.

## Non-goals

- No change to the on-disk session archive format, the TrailLayer compositor, the base-PNG renderer, or MQTT decoding.
- No change to calibration or coordinate-system semantics.
- No change to the lawn-mower entity or session-active binary sensor.

## Design

### Picker options

Three options only, plus one per archived session:

| Option | Meaning |
|---|---|
| `Latest` | Default. Shows the most recent or in-progress run. Auto-tracks newest session: when the mower starts a new run, the map clears and begins drawing the new run live. |
| `Blank` | Empty canvas. Not touched by telemetry or archive events. |
| `<YYYY-MM-DD HH:MM — Xm² (Nmin)>` | One entry per archived session, newest-first. Pinned to that session. Never updates. |

The `Live` option is removed. The legacy `_OPT_NONE` alias (pre-alpha.13 compatibility) is removed.

### State model

The `LiveMapState` dataclass gains a `mode` field:

```python
class MapMode(str, Enum):
    LATEST = "latest"
    SESSION = "session"
    BLANK = "blank"

@dataclass
class LiveMapState:
    mode: MapMode = MapMode.LATEST
    pinned_md5: str | None = None  # only set when mode == SESSION

    # Accumulating live data (populated only when mode == LATEST and a run is active)
    path: list[list[float]]
    obstacles: list[list[float]]
    session_id: int
    session_start: str | None

    # Overlay fields (populated from a session summary, used when mode in (LATEST, SESSION))
    lawn_polygon: list[list[float]]
    exclusion_zones: ...
    completed_track: ...
    obstacle_polygons: ...
    dock_position: ...
    summary_md5: str | None
    summary_end_ts: int | None
```

`set_mode(new_mode, archive_entry=None)` handles mode transitions:

- `→ LATEST`: clear pinned_md5, clear overlay, clear live accumulators, populate overlay from the latest archive if one exists.
- `→ SESSION(md5)`: clear live accumulators, load the pinned archive into the overlay, store pinned_md5.
- `→ BLANK`: clear both overlay and live accumulators.

The `_pending` buffer and `flush_pending()` method are removed. Idle-beacon points that arrive between sessions are discarded — in LATEST mode between runs we show the archived overlay, so we do not need buffered future-points.

### Coordinator tick behavior (`DreameA2LiveMap._handle_coordinator_update`)

Only **LATEST** mode mutates state on coordinator ticks. SESSION and BLANK are frozen.

In LATEST mode:

1. **Session-start transition** (`active` False → True): clear overlay (it represented the previous run) and reset live accumulators. Start collecting live path/obstacles. The picker does not change.
2. **Active session**: append positions to `path` and obstacles to `obstacles`. The current mower position is included in the snapshot.
3. **Session-end transition** (`active` True → False): no immediate action. Points stop arriving; the last point remains as the trail terminus.
4. **New session summary arrives** (`device.latest_session_summary` changes its md5): load it into the overlay. Clear `path` and `obstacles` (the summary's `completed_track` supersedes the live accumulation). `session_id` stays; `session_start` is cleared.
5. **Idle** (no active session, no new summary): snapshot continues to reflect the overlay. Position is `None` when not active — no mower icon at the dock.

### Snapshot composition

`to_attributes(position)` composition rules:

- BLANK: everything empty, `position=None`.
- SESSION: overlay fields from the pinned archive, `path=[]`, `position=None`.
- LATEST between runs: overlay fields from newest archive, `path=[]`, `position=None`.
- LATEST during a run: overlay fields empty (or from previous archive if we want a "ghost" underlay — **decision: empty, to match the "no special case for dock" requirement**), `path=<live>`, `position=<current>`.

### Refresh reliability fix

The camera's `_composed_cache` is keyed on `(id(self._image), trail_layer.version)`. When the session picker changes modes without the base PNG changing, `id(self._image)` stays the same; if `trail_layer.version` does not bump (e.g. the TrailLayer was only partially reset), the cache serves stale bytes.

Fix: when the live-map dispatcher emits a snapshot with a *mode transition* (indicated by a new `mode` attribute or a change in `summary_md5` + empty path), the camera clears `_composed_cache` unconditionally and rotates the access token. Never rely on implicit TrailLayer version bumps to invalidate the cache.

This is a belt-and-suspenders change. The real bug is that the cache has multiple independent invalidation paths that can get out of sync; we add one more that always fires on mode-change.

### Select entity

`DreameReplaySessionSelect`:

- Default option = `Latest`.
- `_OPT_LIVE` and `_OPT_NONE` deleted.
- Options list = `[Latest, Blank, *<dates>]`.
- On archive grow: if user had a concrete date selected and it was not evicted, keep it selected. If it was evicted, fall back to `Latest`.
- `async_select_option` dispatches a single `live_map.set_mode(...)` call via executor. No more branching on four different cases.

## Affected files

- `custom_components/dreame_a2_mower/live_map.py` — state machine + HA glue
- `custom_components/dreame_a2_mower/select.py` — replay picker
- `custom_components/dreame_a2_mower/camera.py` — cache invalidation on mode change
- `dashboards/mower.yaml` — picker comment
- `tests/live_map/*.py` — unit tests for new semantics
- `docs/dashboard-setup.md` — update if it enumerates picker options (only if present)

## Migration / back-compat

- Users with the `Live` option selected at upgrade time will have the select entity fall back to `Latest` on next coordinator tick (existing invalid-option fallback logic).
- No persisted state changes. The select's state is not saved across restarts; HA recomputes from current archive.
- No API changes: the `dreame_a2_mower.replay_session` service still accepts a file path and pins to that session (equivalent to `SESSION` mode).

## Testing

- Unit tests for `LiveMapState.set_mode()` transitions.
- Unit tests for coordinator-tick behavior in each mode (LATEST active, LATEST idle, SESSION, BLANK).
- Integration test for the picker: selecting a date calls `set_mode(SESSION, md5=...)`; selecting Latest calls `set_mode(LATEST)`; selecting Blank calls `set_mode(BLANK)`.
- Regression test: mode change snapshot causes camera `_composed_cache` to be cleared.
