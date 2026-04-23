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

## Auto-finalize ambiguity around CHARGING_COMPLETED

**Context** (2026-04-22): the alpha.52 finalize gate suppresses
auto-close while the status enum is in any "recharge state"
(BACK_HOME / CHARGING / CHARGING_COMPLETED / RETURNING / …) so
mid-run recharges can't be misread as session end. But this
also suppresses finalize when a run *truly* ended and the
mower charged back to full — the user is left with a stale
in_progress entry until they press the Finalize button.

**The disambiguator**: `_task_pending_resume` (s2p56 code 4)
and `_task_running_s2p56`. If both are False AND status is
CHARGING_COMPLETED, the run is genuinely done — the device
isn't planning to resume. If pending_resume is True, mid-run.

**Needed**:
- Tighten the recharge gate in `live_map._handle_coordinator_update`
  so CHARGING_COMPLETED *only* suppresses finalize while
  `_task_pending_resume or _task_running_s2p56`. Otherwise the
  120s sustained-idle timer should be allowed to count down.
- Verify against the captured probe log around 2026-04-22 11:53
  (mid-run recharge with pending_resume) and a future "true end"
  capture for contrast.

**Acceptance**: a run that ended while HA was down auto-cleans
within ~2 min of HA boot once s2p56 confirms no pending_resume.
A mid-run recharge keeps the in_progress entry indefinitely.

## "Mowing Session Active = Off" at reboot

Cosmetic but confusing: the binary_sensor reads `device.status.started`
which is False until the first s2p56 push lands and
`_session_status_known` flips True. Means the dashboard briefly
lies "no session" right after HA boots, even when a run is
ongoing. Fix candidates: (a) initial value `unknown` instead of
False until known; (b) cache the last-known-good state to disk
and restore on boot; (c) eager s2p56 probe at boot (already
exists per commit 36502b8 — verify it actually fires before the
binary_sensor's first state computation).

## Protocol-RE bridging plan — capture remaining unknowns

See `docs/superpowers/specs/2026-04-22-latest-view-path-rendering-design.md`
and chat 2026-04-22 structured review for the full context. Tier
catalog of known/partial/unknown lives in
`docs/research/g2408-protocol.md` §2.1.

### A — Value-history capture (LANDED alpha.64)

`UnknownFieldWatchdog.saw_value(siid, piid, value)` drives
`[PROTOCOL_VALUE_NOVEL]` WARNINGs for each new distinct value of
an unmapped property. Capped at 32 distinct values per property.
Lets us catalogue s5p106 (1..7 cycle), s5p107 (dynamic enum),
s2p66[1] mystery integer, s6p2[0] profile id, and all other
Tier 2 slots without manual probe analysis.

### B — Change-correlation tagger

**Goal**: derive semantics from CONCURRENT state when an unknown
property changes. Currently we log "s5p107 → 158" but not the
battery / phase / session-elapsed at that moment, so the
correlation has to be reconstructed manually.

**Proposal**: add a helper that captures a context snapshot and
logs it alongside each `[PROTOCOL_VALUE_NOVEL]` (or even on every
change of a Tier-2 property). Format:

```
[PROTOCOL_CORRELATION] s5p107 → 158 at battery=74%, s2p1=2,
  s2p2=48, since_session_start=2370s, mowing_phase=?
```

Snapshot fields: `battery_pct`, `s2p1`, `s2p2`, seconds since
current session start, seconds since last leg start, current
`mowing_phase`, current `x_m`/`y_m` rounded, `cleaning_paused`.

Implementation: `_capture_context()` method on device that
returns a formatted string; call it right before the
`[PROTOCOL_VALUE_NOVEL]` emission. Zero behaviour change.

### C — Switch entity `switch.dreame_a2_mower_re_capture`

**Goal**: self-service experiment mode the user can toggle in the
app without editing YAML. While ON:
- Every unknown-property change logs at WARNING (not just novel
  values — also CORRELATION breadcrumbs)
- Every MQTT message gets dumped via `_deep_format` to
  `<config>/dreame_a2_mower/debug/re_capture_<date>.jsonl`
  (bounded rotation at ~10 MB per file, 5 files kept)
- On turn-OFF, a summary report is emitted at WARNING listing:
  - Distinct values seen per property during the window
  - Count of each s2p1 / s2p2 code observed
  - Any novel events
  - Time range of capture

**Usage flow**: user enables Switch → does experiment X (e.g.
toggle Mowing Direction + Chequerboard + Schedule edits) → turns
Switch OFF → pastes the summary report.

### D — App-config experiment plan (manual, no code)

Run each of these experiments at least once under the RE-capture
Switch (alphabetical; update protocol doc §2.1 as each completes):

| # | Target | Experiment | Expected signal |
|---|--------|-----------|-----------------|
| 1 | `s5p106` cycle | Leave integration running overnight without interacting; correlate transitions with battery level and time-of-day | Confirm 30-min cadence + identify reset trigger (midnight? session boundary?) |
| 2 | `s6p2[0]` profile id | Visit BUILDING mode ("Expand Lawn"), run normal mow, run scheduled mow, run manual mow — capture s6p2 value at each | Map value → session class |
| 3 | `s2p2` state codes | Trigger every app action: Head to Maintenance, Cancel, Return to Base, manual drive, Find My Mower | Pin down `27`, `43`, `56`, `69`, `128`, `170` triggers |
| 4 | `s5p107` bitfield | Mow with Rain Protection on/off; Frost Protection on/off; AI Obstacle Photos on/off; obstacle-avoidance variants | Look for value bands per mode toggle |
| 5 | `s1p4` byte[6] | Drive manually in BUILDING mode varying heading; note if values correlate with cardinal direction | Confirm/refute heading hypothesis |
| 6 | MAP `cleanPoints` / `cruisePoints` / `notObsAreas` / `cut` | Set maintenance-point, add zone, add exclusion, add patrol-point — capture MAP payload before+after | Derive schema for each top-level key |
| 7 | `s2p1 {1,2,5}` small enum | Trigger every app action under every battery level | Catalog the 5 distinct values |
| 8 | `s1p4` bytes `[18-21]` | High-cadence capture during a straight-line run vs tight-turn run | Correlate with linear vs angular motion |

### E — OSS session-summary failure diagnostics (LANDED alpha.63/.64)

`_fetch_session_summary` now logs the cloud's full error response
on failure (alpha.64 protocol.py change). Next session-end will
show exactly why downloads fail when they do. After a week of
captures:
- Categorise the failure classes (deep-sleep, token, not-found, …)
- Pick an appropriate retry / backoff strategy
- Consider pre-fetching on the `s1p52 + s2p52` pair to
  minimise the cloud-deep-sleep race window

### F — Doc pipeline

**Goal**: close the loop so `[PROTOCOL_VALUE_NOVEL]` captures
propagate into §2.1 of the protocol doc without manual transcription.

**Proposal**: `scripts/update-protocol-doc.py` that:
- Reads a probe log or HA core log
- Extracts all `[PROTOCOL_VALUE_NOVEL]` lines
- Emits a markdown diff against §2.1 showing which rows gain
  which new values
- User reviews + commits

### G — In-integration deep-print

Currently the external `probe_a2_mqtt.py` has a `_deep_format`
helper that walks nested structures for log output. The
integration's `[PROTOCOL_NOVEL]` only logs `value=%r` which
truncates / loses nested detail for dicts and lists. Move
`_deep_format` into the integration (or import from the probe
package) so both tools render identical output.

---

## PROTOCOL_NOVEL entries — documented, but cloud session-summary download still failing

Audit of all PROTOCOL_NOVEL captures across `home-assistant*.log`
(2026-04-22):

1. **`s1p4 short frame len=8`** — already documented in protocol §7
   row of the PROTOCOL_NOVEL reference table; position decoded fine,
   trailing bytes un-RE'd. Logs once per length per HA process via
   `_protocol_novelty` set.
2. **`s1p50 = {}`** / **`s1p51 = {}`** — documented in protocol §4.7
   as session-start pair. Now in `known_quiet` set in device.py so
   the noise warning is suppressed (downgraded to DEBUG via
   `[PROTOCOL_OBSERVED]`).
3. **`s1p52 = {}`** — documented in protocol §4.7 as session-end
   flush ping. Now in `known_quiet`.
4. **`s2p52 = {}`** — NEWLY documented in protocol §4.7 (alpha.62)
   as cloud-side session-completion ping, paired with `s1p52`. Also
   in `known_quiet`.
5. **`event_occured siid=4 eiid=1` with piids `{1,2,3,7,8,9,11,13,14,15,60}`**
   — fully documented in protocol §7.4. The watchdog is now
   pre-seeded so the WARNING doesn't fire on every HA restart for
   this known shape (alpha.62).

**Remaining real bug** (separate from documentation): even though
the integration's `_handle_event_occured` handler IS called for
`siid=4 eiid=1` and DOES invoke `_fetch_session_summary(object_name)`,
the current run's summary somehow never lands in
`device.latest_session_summary`. As a result:

- The in-progress entry's `summary_md5` stays at the previous
  run's value (e5868865… from 2026-04-22 10:58 archive).
- The picker keeps showing "still mowing" until the user
  presses Finalize Session.
- The auto-finalize gate doesn't fire because no fresh leg
  summary marks the logical run as ended.

**Needed**:
- Trace why `_fetch_session_summary` apparently doesn't update
  `latest_session_summary`. Suspects: the OSS download URL fetch
  is failing silently (cloud "device may be in deep sleep" warnings
  appear nearby in the log), or the parsed summary's md5 matches
  the previous one and gets short-circuited.
- Add WARNING-level logs around `_fetch_session_summary`
  success/failure paths so future captures show the failure mode
  directly.
- Consider falling back to the `s1p52 + s2p52` empty-dict pair
  as the "session ended" signal when the cloud download fails —
  per protocol §4.7 those are the earliest predictive end-of-
  session signals (~4 s before `event_occured` lands).

**Acceptance**: a session that ends fires `event_occured`,
`_fetch_session_summary` populates `latest_session_summary` with
fresh data, leg-merge absorbs it, auto-finalize promotes the
in-progress entry to a completed archive, and the picker shows
the new entry without manual intervention.

## ioBroker.dreame cross-reference — major new RE (2026-04-23)

Cloned `https://github.com/TA2k/ioBroker.dreame` includes a full
APK decompilation (`apk.md`) of the Dreame Smart Life app + React
Native mower plugin. Targets g2568a firmware so binary-frame
findings need g2408 cross-validation, but the action-routing /
config schema is shared across mowers.

**Full cross-reference**:
`docs/research/2026-04-23-iobroker-dreame-cross-reference.md`

Highlights:
- **Settings via action call** — `siid:2 aiid:50` with
  `{m:'g', t:'CFG'}` returns ALL settings including the PRE
  array (cutting height, mow mode, edge mowing) we previously
  thought BT-only. Setter is `{m:'s', t:'PRE', d:{value: array}}`.
  Entire "BT-only inventory" turns out to be MQTT-accessible.
- **PRE schema verified**: `[zone, mode, height_mm, obstacle_mm,
  coverage%, direction_change, adaptive, ?, edge_detection,
  auto_edge]`.
- **s1p4 pose decoder differs** — apk says 12-bit packed across
  bytes 1-6 (3 packed values: x24, y24, angle8). We decode as
  int16_le. Likely "lucky" for small lawns but diverges beyond
  ±32 m. Plus: we're missing the angle byte (mower heading).
- **s1p4 task struct differs** — apk says bytes 22-31 hold
  `{regionId, taskId, percent, total, finish}` with uint24
  area fields. We treat as uint16+static — same low-2-bytes
  truncation issue.
- **Key piid corrections**: `s2p2` is *error code*, not state;
  `s1p51`/`s2p52` are *re-fetch triggers*, not session
  boundary markers. Our s1p52+s2p52 "session-end pair"
  hypothesis needs revisit.
- **More s1p4 frame lengths** — apk lists 7/10/13/22/33/44 byte
  variants. We handle 8/10/33.
- **NEW userData key**: `M_PATH.*` is a separate cloud blob
  with the full mowing path coordinates (sentinel
  `[32767, -32768]` = path break). Could hydrate trail layer
  on boot when in_progress is empty.
- **Many new actions / settings** — headlight (LIT 7-element),
  GPS (LOCN), cruise points, blade calibration (cutterBias),
  Find My Mower (findBot), suppressFault, etc.

### Prioritized action items (extracted from cross-ref doc)

**Immediate**:
1. Implement `getCFG` action call at coordinator init →
   read-only sensors for all settings.
2. Cross-validate pose decoder (apk 12-bit packed vs our
   int16_le) — write a side-by-side test with captured frames.
3. Update protocol doc §4.7 — s1p51 + s2p52 are NOT session
   markers (they're re-fetch triggers).
4. Re-examine s2p1 / s2p2 interpretations against apk's
   "1=Status, 2=Error".

**Medium-term**:
5. Number/Switch entities for PRE settings (cutting height,
   mow mode, edge mowing, etc).
6. Headlight entity group (LIT).
7. Wear-meter sensors via CMS.
8. Decode s1p4 task fields (regionId, taskId, percent).
9. `getDockPos` action call → dock-connection status sensor.

**Long-term**:
10. Pose decoder cross-check on lawn >32 m.
11. M_PATH userData fetch as alternate path source.
12. Map remaining piid handlers (53, 57, 58, 61).
13. cutterBias / suppressFault button entities.

## s1p4 phase byte semantics — protocol doc is wrong

Field-captured 2026-04-22 across 4 probe logs shows the s1p4
byte[8] ("phase") taking values 0..16+ — not the simple
{0:MOWING, 1:TRANSIT, 2:PHASE_2, 3:RETURNING} the protocol doc
§3.1 claims. Distribution across logs:

| Log file | Distinct phase values observed |
|---|---|
| 2026-04-17 | {0: 1378, 1: 530, 2: 540, 3: 348} |
| 2026-04-18 (1st) | {0: 536, 1: 414} |
| 2026-04-18 (2nd) | {3: 88, 4: 236, 5..15: ~25 each} |
| 2026-04-19 | {0: 2559, 1: 1568, 2: 1359, 3: 1006, 4..16: 33-567} |
| 2026-04-22 (current run) | {2: 129, 3: 49} — only two values, both during active mowing in unmowed area |

The 2026-04-22 capture rules out the doc's interpretation: the
mower was actively mowing in lines (visible mowing pattern in
unmowed area) but every single frame had phase ∈ {2, 3}. So
phase=2 and phase=3 cannot mean PHASE_2 / RETURNING in the
sense of "blades up". They're both valid mowing states.

**Hypothesis candidates** to test:
- Phase byte is a sub-pattern index (which row/segment of the
  programmed mowing pattern, increments through subroutines)
- Phase byte is a counter that wraps through 0..N per session
- Phase byte encodes a state machine that includes mowing-mode
  variants (edge mowing, fill-in, cleanup, etc.) plus transit
  states

**Needed**:
- Integration's PROTOCOL_VALUE_NOVEL (alpha.64) will catch new
  phase values as they appear. Cross-reference with
  visually-observed mower behaviour at the same timestamps.
- Manual experiments under the RE-capture switch (TODO item C):
  trigger BUILDING / Find Maintenance Point / cancel / each
  mode and look at the phase-byte timeline.
- Once the mapping is known, re-enable the area-calc filter in
  live_map._approximate_area and the TRANSIT_COLOR rendering
  in trail_overlay (both currently disabled, infra preserved
  via comments).

**Acceptance**: each phase-byte value documented with confirmed
behaviour, and the area calc + colour rendering filter only
on values we know are blades-up (most likely a single specific
value, not a range).

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

