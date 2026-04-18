---
name: Live Map Overlay (Plan E.1) — Design
date: 2026-04-18
status: draft
---

# Plan E.1 — Live Map Overlay

## Goals

Provide a Home Assistant camera experience equivalent to the Dreame app's live map view during a mowing session: the mower's current position, its full path during the active session, detected obstacle markers, and the charger location — overlaid on the existing base-map image. Read-only in this phase (no commands from the map).

Persisted session history and a "Work Logs" picker are explicitly deferred to Plans E.2 and E.3 respectively.

## Non-goals

- Disk persistence of session data (Plan E.2).
- Historical session selection / replay (Plan E.3).
- Patrol-log equivalent (separate phase).
- Zone / exclusion-zone attributes (already handled by upstream's map subsystem).
- Interactive map commands ("mow here", "go-to") — belong in Plan D's command pipeline.
- Server-side image compositing — deliberately pushed to the Lovelace map card.

## Rendering strategy

Client-side rendering via a Lovelace map card (user's preferred plugin, e.g. `lovelace-xiaomi-vacuum-map-card`). The integration emits state attributes describing position / path / obstacles in real-world metres, and the map card applies its own calibration-points config to map metres → pixel coordinates on top of the base image.

Rationale:
- Reuses the card's mature rendering code (trail smoothing, zoom/pan, icon handling) for free.
- Keeps integration code minimal and focused on data, not pixels.
- Per-installation alignment adjustment happens in Lovelace config, not integration code.
- Leaves upstream's `camera.dreame_a2_map` base image generation untouched (it works for static content; our additions ride on top).

## Coordinate format

All attributes carry coordinates in **metres**, charger-relative, in the mower's internal frame (X aligned with dock nose direction, Y perpendicular). X values use the decoder's cm-to-m conversion (raw / 100); Y values use the calibrated mm-to-m conversion (raw / 1000) multiplied by the user-configurable Y calibration factor (default 0.625 per Plan C findings).

Both X and Y calibration factors are configurable per-installation via an Options Flow (see Config). Factor changes apply to newly appended path points; existing path data is not retrospectively rewritten.

## Attribute schema

Attached to the existing `camera.dreame_a2_map` entity via `extra_state_attributes`:

```python
{
    "position": [x_m, y_m],                 # current calibrated position
    "path": [[x1, y1], [x2, y2], ...],      # full current-session trail
    "obstacles": [[x, y], ...],             # s1p53=True points
    "charger_position": [0.0, 0.0],         # static origin
    "session_id": int,                      # increments on each session start
    "session_start": "2026-04-18T11:17:00", # ISO string, set at session start
    "calibration": {"x_factor": 1.0, "y_factor": 0.625},  # active multipliers
}
```

All coordinate values rounded to 3 decimals (mm resolution) to keep JSON size predictable.

**Dedupe rules:**
- `path`: skip an append if the new point is within **0.2 m** of the last existing point. Protects against redundant "same position" frames while keeping fine resolution during active motion.
- `obstacles`: skip an append if the new point is within **0.5 m** of any existing obstacle marker. Prevents visual pile-up when the mower lingers near the same obstacle.

**Size budget:** a 1-hour mowing session at 5-second telemetry cadence yields at most ~720 frames. After dedupe, typically 400-600 unique path points × 2 numbers × ~8 bytes JSON ≈ 8-12 KB attribute payload. Within HA's safe state-size range.

## Architecture

One new module: `custom_components/dreame_a2_mower/live_map.py` with:

- **Class `DreameA2LiveMap`** — state machine, instantiated by the coordinator, does not render images. Subscribes to coordinator updates, maintains session state, writes attributes.
- **Class `LiveMapState`** — pure dataclass holding `path`, `obstacles`, `session_id`, `session_start`, etc. Separate from the HA-facing class so it can be unit-tested without HA.
- **Function `iter_probe_log_as_telemetry(path)`** — replay helper used by both tests and the dev import service.
- **Service `dreame_a2_mower.import_path_from_probe_log`** — registered at integration setup, exposes the dev tool.

`DreameA2LiveMap` does one job: turn a stream of telemetry events into attribute dicts. That's it. Rendering lives entirely in the Lovelace map card.

## Component boundaries

Each unit has one responsibility and a narrow interface:

- `LiveMapState` — appends points and obstacles, handles dedupe and session transitions. Pure state machine. Unit-testable with synthetic events.
- `DreameA2LiveMap` — glue between HA's coordinator lifecycle and `LiveMapState`. Reads calibration from config entry options, pushes attributes through a dispatcher signal, registers the dev service.
- **Camera attribute receiver** — existing `DreameMowerCameraEntity` subclass (upstream) gains an extra `extra_state_attributes` merge from the live-map state. Integration point is a small override, not a rewrite.

## Data flow

```
MQTT s1p4/s1p53 event
        ↓
DreameMowerDevice._handle_properties + _decode_blob_properties  (Plan C — existing)
        ↓
coordinator.async_update_listeners()
        ↓
DreameA2LiveMap._handle_update()
  ├── reads device.mowing_telemetry, device.obstacle_detected, device.status.started
  ├── applies x_factor / y_factor to compute metres
  ├── checks session-active flag for boundary transitions
  ├── delegates to LiveMapState.append_point / append_obstacle / start_session
  └── pushes via dispatcher signal "dreame_a2_mower_live_map_update"
        ↓
DreameMowerCameraEntity (patched)
  └── merges LiveMapState snapshot into extra_state_attributes
        ↓
HA state update → Lovelace map card re-renders
```

## Config

Options flow adds two numeric fields:
- **X calibration factor**: float, default 1.0, range 0.1–10.0
- **Y calibration factor**: float, default 0.625, range 0.1–10.0

Changing either triggers an `entry.options` update which `DreameA2LiveMap` receives via the standard HA update-listener mechanism. Attributes from that moment onward use the new values; pre-existing path history is not recomputed.

Options flow help text notes that in-flight sessions keep their original calibration for historical points.

## Error handling + edge cases

- **Telemetry before session-active flag is known**: buffer up to 20 frames internally; once session-active flips True, flush buffered frames into the new session's path.
- **Calibration factors change mid-session**: new points use new factors; existing path stays. Documented behaviour, not a bug.
- **HA restart / integration reload mid-session**: MVP loses the in-memory session. Accepted known limitation (E.2 adds persistence).
- **Camera entity absent during coordinator startup**: `DreameA2LiveMap` defers its first dispatcher push; once `camera.dreame_a2_map` appears in `hass.states`, start pushing. Uses a one-shot wait-for-entity helper.
- **Malformed telemetry (e.g. 8-byte `s1p4` frame)**: already handled upstream in Plan C's `_decode_blob_properties` — frame is discarded, no position update reaches the live map. Live map sees "no change" and keeps previous state.

## Testing

- **Unit tests for `LiveMapState`** — pure Python, no HA imports, driven by synthetic telemetry events:
  - Dedupe thresholds (path and obstacles)
  - Session boundary transitions (start, end, restart)
  - Calibration factor application
  - Buffer flush on session-active flip
- **Integration test via probe-log replay** — loads the 2026-04-17 sessions from `probe_log_20260417_095500.jsonl`, feeds them through `LiveMapState`, asserts expected path length, final position, and obstacle count based on session 4's known characteristics.
- **Manual validation** — user imports a past session via the dev service, confirms the Lovelace map card renders the full mowing pattern matching the Dreame app's Work Logs view.

## Dev tools

Service `dreame_a2_mower.import_path_from_probe_log` (registered at integration setup):

```yaml
service: dreame_a2_mower.import_path_from_probe_log
data:
  file: /data/claude/homeassistant/probe_log_20260417_095500.jsonl
  session_index: 4    # optional; pick Nth session from the file (default: most recent)
```

On invocation:
1. Reads the probe log via `protocol.replay.iter_probe_log`
2. Groups events into sessions (by time-gap heuristic from Plan B's replay test)
3. Picks the requested session index
4. Rebuilds `LiveMapState` from scratch using that session's events
5. Pushes result to the camera attributes

Lets the user pre-populate the map with real historical data to validate card configuration before waiting for a live run.

## Risks

- **Lovelace map card mismatch** — if user picks a card with incompatible attribute-name expectations, our schema won't work out-of-the-box. Mitigation: README documents the recommended card plus example card configuration YAML.
- **Calibration drift between sessions** — Plan C observed the 0.625 Y factor from two data points; if it varies session-to-session, per-session re-calibration might be needed. Mitigation: factor is user-configurable; if it needs to change, users change it without a code release.
- **Coordinate-frame rotation** — our assumption is mower X/Y frame = map-rendered frame (no rotation). If future work reveals rotation is needed, an angle option would be a minor additional Options Flow field. Not in MVP scope.

## Deferred / future phases

- **E.2 (session recording)** — persist sessions to disk (`/config/dreame_a2_sessions/*.json`), expose as sensor attributes, schema-compatible with E.1's attributes so map card config doesn't need to change.
- **E.3 (session replay)** — selector entity for picking a past session; on select, `DreameA2LiveMap` rewrites the live attributes with historical data.
- **Patrol logs** — separate feature, uses different MQTT topics / properties we haven't decoded.
