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

## Finalize-in-progress-session (explicit override)

**Context**: v44 added auto-close for orphan drafts — on s2p56=empty
the `<ha_config>/dreame_a2_mower/drafts/live_path_*.json` file and
the 30-min fallback-active window are dropped automatically. That
covers the common "mow finished while HA was down" case.

**Gap**: if s2p56 never comes back (firmware silent, device offline),
the draft lingers until its 12h freshness window elapses. A user who
knows the mow ended and wants the draft cleared / saved as an archive
entry has no UI handle for it.

**Needed**:
- Button entity `button.dreame_a2_mower_finalize_session` under the
  mower device card. Press action:
  1. Read current `LiveMapState.path` + `session_start`.
  2. Build a minimal `SessionSummary` (start_ts from session_start,
     end_ts = now, path = [[state.path]], synthetic md5 from path
     hash, area_mowed_m2 approximate or 0 with an "incomplete" flag).
  3. Hand to `session_archive.archive(summary)` so it shows in the
     replay picker.
  4. Delete the draft + clear fallback window.
- Decide whether to compute an approximate area (shoelace on the
  bounding polygon) or leave as 0 with a label suffix like
  "(incomplete)". Approximation risks being misleading; 0 + label is
  honest but forces the user to check the path visually.

**Acceptance**: a stranded draft can be promoted to a first-class
archive entry via one button press, and the resulting entry appears
in the replay dropdown with a clear "(incomplete)" marker.
