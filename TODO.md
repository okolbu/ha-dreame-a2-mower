# TODO

Open work items for the ha-dreame-a2-mower integration. Closed items
live in git history — don't recreate them here after resolution.

## Path rendering granularity

**Observed**: during an active mow the HA Live Map paints new path
segments in visible chunks, whereas the Dreame app renders a smooth
progression at roughly the mower's real travel speed.

**Likely causes (ranked)**:
1. MQTT delivers `s1p4` telemetry in bursts (mower buffers and flushes
   multiple frames at once), so `LiveMapState.append_point` receives
   clusters of coords rather than a steady stream.
2. `TrailLayer` redraws on camera refresh, which is tied to the HA
   camera-entity polling cadence rather than the per-frame telemetry
   arrival.
3. `PATH_DEDUPE_METRES = 0.2` in `live_map.py` drops any point within
   20 cm of the previous — fine while mowing forward, but on slow
   turns this may elide points that the app keeps.

**Next steps**:
- Instrument the s1p4 arrival cadence (timestamp per frame) during a
  real run, confirm whether chunks come from the mower or the HA side.
- If mower-side: add a client-side interpolator that smoothly
  "animates" between two known coords at expected mower speed. Purely
  cosmetic — don't fabricate points for the stored path.
- If HA-side: decouple the camera refresh from the coordinator tick;
  force a re-composite when `append_point` ran regardless of the
  camera's polling interval. See `_on_live_map_update` in `camera.py`
  for the current cache invalidation.

**Acceptance**: path progresses at the mower's actual speed in the
dashboard, not in visible chunks. No synthetic data in archived
sessions (interpolation is a render-time effect only).

## In-progress session architecture (landed)

The `drafts/live_path_*.json` file has been replaced by
`sessions/in_progress.json`, managed by
`SessionArchive.{read,write,delete,promote}_in_progress`. The
in-progress entry is a first-class row in
`SessionArchive.list_sessions()` (sorts to the top by `last_update_ts`)
and `latest()`. The replay picker shows it as `YYYY-MM-DD HH:MM —
X m² (N min, still running)`; selecting it routes through
`MapMode.LATEST` (no wire-format to replay from). Leg-per-recharge
cycles are absorbed by merging each `event_occured` leg's
`track_segments` into the in-progress entry while `started==True`.

Auto-close triggers on the coordinator tick where
`_session_status_known=True and not device.status.started and
_prev_session_active`. If no leg summary ever fired during the run
(HA was down through the end), `live_map.finalize_session()`
synthesizes an "(incomplete)" archive entry from the captured
live path + session_start_ts before deleting the in-progress file.

A user-facing button (`button.dreame_a2_mower_finalize_session`)
exposes the same finalize path for the stuck case where s2p56 never
resumes — e.g. mower permanently offline mid-run.

## LiDAR card popout / fullscreen view

**Context**: `custom:dreame-a2-lidar-card` (served from
`custom_components/dreame_a2_mower/www/dreame-a2-lidar-card.js`)
renders an interactive 3D point cloud with orbit/zoom controls.
At dashboard size the scene is too small to inspect detail —
splat texture, base-map underlay, and LiDAR features are all
cramped.

**Needed**:
- Add a fullscreen toggle button (overlay corner of the card,
  e.g. bottom-right). Tap → call `element.requestFullscreen()`
  on the host element so the canvas fills the viewport. ESC or
  re-tap exits.
- Listen for `fullscreenchange` on the document and resize the
  WebGL renderer + camera aspect to match the new dimensions
  (and resize back when exiting).
- Persist orbit camera state across the fullscreen transition
  so the user doesn't lose their viewpoint.
- Confirm controls (drag-orbit, wheel-zoom, splat-size /
  soft-edge / underlay sliders) remain reachable in fullscreen
  — overlay them with the same z-index they have in the small
  view.

**Optional but nice**: also support an HA-popup-style enlarged
modal for users on Safari iOS where `requestFullscreen` is
restricted — open in a `<dialog>` element sized to ~95vw × 95vh.

**Acceptance**: a one-tap "expand" gesture brings the LiDAR
viewer to fullscreen at full resolution; orbit/zoom continue to
work; ESC or re-tap returns to the dashboard layout with the
previous camera position restored.

## Cloud MAP payload — deeper RE pass

**Context**: a one-shot `[MAP_SCHEMA]` WARNING dump in
`device.py:1963` lists the 17 top-level keys of the cloud MAP
payload by *shape only* — `dict(keys=...)`, `list(len=N)`, etc.
Original purpose was to discover keys beyond the four we already
parse (`boundary`, `mowingAreas`, `forbiddenAreas`, `contours`).
Now that the rest of the protocol is mapped, expand this RE work.

**Known top-level keys (2026-04-22 sample)**: `boundary`,
`cleanPoints`, `contours`, `cruisePoints`, `cut`,
`forbiddenAreas`, `hasBack`, `mapIndex`, `md5sum`, `merged`,
`mowingAreas`, `name`, `notObsAreas`, `obstacles`, `paths`,
`spotAreas`, `totalArea`. Most of the value-bearing ones are
`{dataType, value}` envelopes.

**Next steps**:
- Replace the shape-only dump with a full-depth recursive dump
  guarded by a config-entry option (`debug_map_schema`) so the
  WARNING doesn't fire by default. Walk dicts/lists; sample
  first/last entries from large lists; truncate strings >120
  chars. Emit one tree per fetched map.
- Once dumps are in hand, document each key in
  `docs/research/g2408-protocol.md` §7 alongside the existing
  map-fetch flow, with field semantics + observed value ranges.
- Promote interesting keys (e.g. `cleanPoints`, `cruisePoints`,
  `paths`) to first-class fields in `protocol/cloud_map.py` if
  they unlock new HA features (path replay, cruise-point pins,
  etc.). `notObsAreas` and `cut` are unknown — likely
  zone-modifier types (no-obstacle-detection zones, cut-line
  geometry) but unverified.

**Acceptance**: every top-level key has a documented role + at
least one decoded value-shape example in the protocol doc, and
the integration consciously chooses to ignore vs surface each one.

