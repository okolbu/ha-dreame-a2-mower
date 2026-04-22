# Latest-View Path Rendering — Failure Modes & Multi-Fix

**Date**: 2026-04-22
**Symptom**: After HA reboot with a populated `sessions/in_progress.json`
(44+ live path points), the dashboard's Latest camera view shows the
base map and mower icon but no live path strokes. Older session views
render fine. The picker label updates with growing area/time. The
trail layer never draws.
**Versions affected**: 2.0.0-alpha.46 → alpha.54.

## Pipeline (every gate, every assumption)

```
HA boot
 ├─ coordinator.__init__
 │   ├─ live_map.__init__
 │   │   ├─ _restore_in_progress() → state.path = [44 pts] from disk
 │   │   ├─ _prev_session_active = True
 │   │   └─ _have_active_in_progress = True
 │   └─ live_map.async_setup() → SUBSCRIBES to coordinator
 ├─ coordinator.async_config_entry_first_refresh()  ← FIRST FETCH
 │   └─ live_map._handle_coordinator_update()
 │       └─ async_dispatcher_send(LIVE_MAP_UPDATE_SIGNAL, attrs)  ← FIRES
 ├─ async_forward_entry_setups([camera, ...])
 │   └─ camera entity created
 │       └─ async_added_to_hass() → subscribes to LIVE_MAP_UPDATE_SIGNAL
 │                                  ← TOO LATE: previous fire is lost
 └─ subsequent MQTT pushes / coordinator triggers → dispatch fires again
```

## Failure modes (ranked likelihood)

### F1. Camera misses the first dispatch — startup ordering race ⭐

`async_config_entry_first_refresh()` runs before
`async_forward_entry_setups()` creates the camera entity. The first
`live_map._handle_coordinator_update()` dispatches the signal before
any subscriber exists. Camera attaches a few hundred ms later but
the signal is gone.

The coordinator has **no automatic update interval** — it only fires
when `async_set_updated_data` is called by an MQTT message handler
(or an explicit refresh request). A mower at dock charging may push
nothing for minutes. Until something triggers, the camera has no
attrs to act on.

### F2. Trail layer init bails on missing calibration

`_feed_trail_layer` early-returns if `_calibration_points` is None.
Calibration is set inside `_update_image` which only runs when
`map_data and self.device.cloud_connected and (map_index > 0 or
self.device.status.located)`. If `located` is False (mower not yet
re-localized after boot), `update()` skips the body and calibration
stays None even when dispatches do arrive.

### F3. Dispatch path silent during charge

During a dock charge, the mower stops emitting s1p4 telemetry. The
coordinator only updates on inbound MQTT messages. Sporadic battery
updates may not arrive frequently enough for the trail layer to
ever get a chance to init after a calibration becomes available.

### F4–F8 — secondary suspects

- F4: `attrs.path` not what we think it is (audited; intact post-alpha.54)
- F5: `reset_to_session` no-ops on `len(pts) < 2` (drawn segment-by-segment afterwards via extend_live)
- F6: `_m_to_px` produces off-canvas coordinates (older sessions render → calibration is good)
- F7: `_composed_image` cache returns stale bytes (`reset_to_session` always bumps `version`)
- F8: Logger debug filters not in effect — itself a diagnostic dead-end

## Multi-fix design

### F1+F3 — cached attrs + replay-on-subscribe + initial kickstart

**`live_map.DreameA2LiveMap`**
- Add `self._last_dispatched_attrs: dict | None = None`. Every call
  through `async_dispatcher_send(...)` from `_handle_coordinator_update`
  or `set_mode(...)` first stashes the snapshot.
- `async_setup()` schedules a one-shot `_handle_coordinator_update()`
  call at the end of the event loop's current cycle. This guarantees
  at least one dispatch attempt after subscribe, even before any
  external trigger.

**`camera.DreameMowerCameraEntity`**
- In `async_added_to_hass()`, after subscribing to the dispatcher,
  fetch `coordinator.live_map._last_dispatched_attrs`. If non-None,
  call `self._on_live_map_update(attrs)` directly. This recovers
  the missed first dispatch with zero latency.

### F2 — re-feed on calibration arrival

**`camera.DreameMowerCameraEntity._update_image`**
- After the line that newly populates `self._calibration_points`,
  if `self._live_map_attrs` is non-None and `self._trail_layer` is
  None, re-invoke `self._feed_trail_layer(self._live_map_attrs)`.
  The cached attrs from the most recent dispatch get a second
  chance to initialize the trail layer now that calibration is
  present.

### Instrumentation (one-shot WARNINGs)

Five WARNING-level breadcrumbs, each guarded by a `_logged_<phase>`
attribute so they fire at most once per HA process:

1. `live_map.async_setup`: `live_map subscribed to coordinator`
2. `live_map._handle_coordinator_update`: first call with active or path>0
3. `camera.async_added_to_hass`: `camera subscribed to LIVE_MAP_UPDATE`
4. `camera._feed_trail_layer`: `trail_layer first initialized (path=N)`
5. `camera._composed_image`: `trail compose succeeded (N path pts drawn)`

Promoted to WARNING so users never need to enable DEBUG to diagnose.
The set of breadcrumbs is small (~5 lines per HA process) so log
noise stays low.

## Tests

- `test_camera_subscribe_after_first_dispatch_replays_cached_attrs`:
  simulate live_map firing a dispatch, then camera subscribing; assert
  `_on_live_map_update` was invoked with the cached attrs.
- `test_calibration_arrives_late_re_feeds_trail_layer`: trail_layer
  is None due to missing calibration; populate calibration; verify
  trail_layer becomes non-None on the next image fetch.
- `test_initial_dispatch_after_async_setup`: verify
  `_last_dispatched_attrs` is populated within one event-loop cycle.

## Acceptance criteria

1. After HA boot with a populated in_progress.json, the Latest camera
   view shows the full restored path on first dashboard load.
2. The five WARNING breadcrumbs appear in the HA core log without
   logger config tweaks, allowing field-debug of any remaining
   regression.
3. SESSION → LATEST round-trip continues to preserve the live buffer
   (alpha.53 behavior intact).
4. Recharge cycles do not trigger phantom finalize/restart
   (alpha.52 behavior intact).
5. All existing 147 tests pass; 3 new tests added.
