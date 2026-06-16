<!-- DO NOT EDIT BY HAND. Source: docs/research/inventory/inventory.yaml. Regenerate via `python tools/inventory/inventory_gen.py`. -->

# g2408 Protocol — Canonical Reference

## Properties

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p1 | heartbeat | 20-byte blob | WIRED |  |
| s1p2 | ota_state | int (enum) | DECODED-UNWIRED |  |
| s1p3 | ota_progress | int 0..100 | DECODED-UNWIRED | % (×1.0) |
| s1p4 | mowing_telemetry | 33-byte / 8-byte / 10-byte variants | WIRED |  |
| s1p5 | hardware_serial | string (e.g., "G2408000TESTSN0000") | WIRED | string (×1.0) |
| s1p50 | state_change_ping | empty_dict | WIRED |  |
| s1p51 | dock_position_update_trigger | empty_dict | WIRED |  |
| s1p52 | task_end_flush | empty_dict | WIRED |  |
| s1p53 | bluetooth_connected | bool | WIRED |  |
| s2p1 | mode | int (enum) | WIRED |  |
| s2p2 | error_code | int (state/error code) | WIRED |  |
| s2p50 | task_envelope | TASK envelope; multiple op-code classes | WIRED |  |
| s2p51 | multiplexed_config | shape varies by setting | WIRED |  |
| s2p52 | preference_update_trigger | empty_dict | WIRED |  |
| s2p53 | voice_download_progress | int 0..100 | SEEN-UNDECODED |  |
| s2p54 | lidar_upload_progress | int 0..100 | WIRED | % (×1.0) |
| s2p55 | ai_obstacle_report | list | WIRED |  |
| s2p56 | task_state | {status: list of [task_type, ...] tuples} | WIRED |  |
| s2p57 | robot_shutdown_trigger | scalar int — observed value 1 [probe_log_20260612_174439.jsonl@2026-06-14T04:42:16]; NOT the apk-hypothesized dict | SEEN-UNDECODED |  |
| s2p58 | self_check_result | dict {d: {mode, id, result}} | APK-KNOWN |  |
| s2p61 | map_update_trigger | dict (map update signal) | APK-KNOWN |  |
| s2p62 | task_progress_flag | int | SEEN-UNDECODED |  |
| s2p65 | slam_task_label | string | WIRED |  |
| s2p66 | lawn_area_snapshot | list[float, int] | WIRED | m² (×1.0) |
| s3p1 | battery_level | int 0..100 | WIRED | % (×1.0) |
| s3p2 | charging_status | int (enum) | WIRED |  |
| s4p21 | obstacle_avoidance | int (enum) | UPSTREAM-KNOWN |  |
| s4p22 | ai_detection | int (enum) | UPSTREAM-KNOWN |  |
| s4p23 | cleaning_mode | int (enum) | UPSTREAM-KNOWN |  |
| s4p26 | customized_cleaning | string (JSON) | UPSTREAM-KNOWN |  |
| s4p27 | child_lock | bool (0/1) | UPSTREAM-KNOWN |  |
| s4p44 | cruise_type | int (enum) | UPSTREAM-KNOWN |  |
| s4p47 | scheduled_clean | string (JSON) | UPSTREAM-KNOWN |  |
| s4p49 | intelligent_recognition | int (enum / bool) | UPSTREAM-KNOWN |  |
| s4p59 | pet_detective | int (enum / bool) | UPSTREAM-KNOWN |  |
| s4p68 | device_snapshot_bundle | list of {code, did, piid, siid, value} property snapshots — bulk multi-property read, NOT a single-value property | UNCLASSIFIED |  |
| s4p83 | device_capability | int (bitmask) | UPSTREAM-KNOWN |  |
| s5p104 | slam_relocate_counter | int | WIRED |  |
| s5p105 | s5p105_raw | int (small enum) | WIRED |  |
| s5p106 | s5p106_raw | int | WIRED |  |
| s5p107 | energy_index | int | WIRED | energy_index (×1.0) |
| s5p108 | s5p108_raw | int | SEEN-UNDECODED |  |
| s6p1 | map_data_signal | int — observed values {200, 201, 300} | WIRED |  |
| s6p2 | frame_info | list[int, int, bool, int] len 4 | WIRED |  |
| s6p3 | wifi_signal_push | list[bool, int] | WIRED |  |
| s6p117 | dock_nav_state | int | WIRED |  |
| s99p20 | lidar_object_name | string (OSS object key) | WIRED |  |

### s1p1 — `heartbeat`

Mower-alive ping sent every ~45 seconds regardless of state, plus extra
emissions during state transitions. 0xCE delimiters at bytes [0] and [19].

Key decoded bytes (partial — full catalog in heartbeat_bytes section, Task 9):
- [1] & 0x01: Bumper hit (no corresponding s2p2 transition)
- [1] & 0x02: Drop / Robot tilted
- [2] & 0x02: Lift / Robot lifted
- [3] & 0x80: Lift lockout / PIN required
- [6] & 0x08: Charging paused — battery temperature too low
- [10] & 0x02: One-shot active-alert flag (self-clears 30–90 s)
- [10] & 0x80: Latched low-temp event flag (set since last power-cycle)
  — see 2026-05-30 corpus verification: NOT an off-dock flag (it is set
  ~93% of docked+warm samples too); a single-run off-dock hypothesis was
  refuted. Trigger still not cleanly pinned, but "mostly-set" is
  consistent with a since-power-cycle latch.
- [11] & 0x7F: battery % (== s3p1 in 99.3% of corpus)
- [11] & 0x80: charging flag
- [12] >> 4: 4-bit rolling heartbeat counter (the real per-frame counter)
- [16]: constant 0x80 (framing/reserved)
- [17]: WiFi RSSI, signed dBm (b if b<128 else b−256)
- [18]: cellular/LTE signal (signed dBm, presumed)

Per-byte decode lives in the heartbeat_bytes section (Task 9).
Confirmed 2026-04-17 through 2026-05-05 across the full probe corpus.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1`

### s1p2 — `ota_state`

OTA firmware-update state. Apk-documented via OTAState enum (L57342):
0=UNDEFINED, 1=IDLE, 2=UPGRADING, 3=UPGRADE_SUCCESS, 4=UPGRADE_FAILED,
5=CANNOT_UPGRADE. Apk subscribes to this property at L181402-181404 and
surfaces it in the OTA progress UI.

WIRE-VERIFIED [app-mitm:2026-06-16-firmware-ota]: live 0550→0625 update
captured end-to-end. Observed transitions: 1 (idle, update available but
not started) → 2 (UPGRADING, held throughout download+install) → 3
(UPGRADE_SUCCESS, transient, 1 sample on reconnect) → back to 1.

VALUE-MAP CONFLICT RESOLVED: the upstream dreame-mower fork lineage
(2=new_firmware_available) is DISPROVED — s1p2 read 1=IDLE while
hasNewFirmware:true and no update was in progress. The apk OTAState
lineage (2=UPGRADING, 3=UPGRADE_SUCCESS, 4=UPGRADE_FAILED) is CONFIRMED.

"New firmware available" is NOT signalled by s1p2. The signal is the
cloud checkDeviceVersion endpoint (iotuserbind/checkDeviceVersion →
hasNewFirmware:true). See api_endpoints entry ota_check_version.

**Open questions:**
- Does g2408 emit CANNOT_UPGRADE (5) when battery is too low for OTA?

**See also:** `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:2`

### s1p3 — `ota_progress`

OTA firmware-update download progress counter, 0..100. Apk-documented
at L181422-181424; surfaces as the progress bar in the OTA update UI.

WIRE-VERIFIED [app-mitm:2026-06-16-firmware-ota]: live 0550→0625 update
captured. s1p3 climbed 0→3→19→33→47→61→74→89→100 during DOWNLOAD (matched
the app's % readout exactly). During the subsequent install phase (app showed
24→50→75→99%), s1p3 stayed PINNED at 100 — the install % is app-local, not
on the wire. s1p3 reset to 0 after UPGRADE_SUCCESS.

This property tracks DOWNLOAD PERCENT ONLY. Install progress is not
wire-exposed; the second "% installed" counter shown by the app is
computed app-side / device-side-during-flash.

**See also:** `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:3`

### s1p4 — `mowing_telemetry`

Position, phase, area, and distance telemetry. Three frame lengths observed
on g2408: 33-byte (full telemetry during active mowing), 8-byte (beacon
variant during idle/docked, start-of-leg preamble, BUILDING sessions, and
post-FTRTS dock-navigation), 10-byte (one per BUILDING session at zone-save
moment).

All variants share 0xCE delimiters and a common X/Y position at bytes [1-5]
(20-bit signed packed decode, both axes in map-scale mm). X-axis confirmed
via fixture; Y-axis decode corrected in alpha.98 (prior code had a 16× Y
overshoot compensated by scattered 0.625 factors, all removed).

The 33-byte frame additionally carries: sequence (bytes [6-7]), phase_raw
(byte [8] — index into firmware's per-zone task plan, NOT a mowing/transit
enum), motion vectors / path history (bytes [10-21]), distance_deci
(bytes [24-25], ÷10 → m), total_area_cent (bytes [26-27], ÷100 → m²),
area_mowed_cent (bytes [29-30], ÷100 → m²). area_mowed_cent advancing while
position is stationary is the blades-on detector.

Per-byte decode lives in telemetry_fields and telemetry_variants sections
(Task 10). Confirmed 2026-04-17 through 2026-05-05.

NO obstacle/AI-detection flag in s1p4 (or s1p1). Byte-by-byte verified
2026-05-31 during a real AI obstacle detection (user walked in front
mid-mow; both apps captured a photo at 12:40:48): every s1p4 byte that
changed in that window is an already-decoded pose/area/counter field —
pose deltas (bytes 1-5,10-21), path-point sequence (6-9), percent (24-25),
total area (26-28), mowed area (29-31; byte[30] is the *middle* byte of the
finish_uint24 area counter — its bump ~9 s after the photo was just area
crossing a 256-centiare boundary, NOT a detection). s1p1 likewise: byte[7]
(mow-active) + byte[10] (0x80 latched-temp) set at mow START not at the
photo, byte[11]=battery, byte[18]=RSSI. The detection is invisible across
ALL backend-A surfaces (telemetry, properties, events, device-data) — see
[[s2p55]]; it is an app-backend (B/C) artifact only.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:4`

### s1p5 — `hardware_serial`

Hardware serial as printed on the device chassis. Fetched on demand
via cloud RPC `get_properties(siid=1, piid=5)`; never pushed
spontaneously via MQTT (it never changes after manufacturing).

Confirmed across all 4 cloud dumps captured 2026-05-04 → 2026-05-06:
consistent value `"G2408000TESTSN0000"`. The integration's
coordinator handles the field at coordinator/_property_apply.py § apply_property_to_state —
`_apply_property_to_state` checks for (1, 5) and writes the string
to `MowerState.hardware_serial` if non-empty. Surfaced as
`sensor.hardware_serial` (sensor.py:516) plus the `device-info
"Serial Number"` field. Distinct from `cfg_individual.DEV.sn`
which is the authoritative source preferred by the coordinator's
`_refresh_dev` path; s1p5 is the fallback when DEV's RPC fails.

**See also:** `coordinator/_property_apply.py § apply_property_to_state`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s1p50 — `state_change_ping`

Lightweight "something changed, consider re-fetching" ping. No payload.
Fires at session start (paired with s1p51), at BUILDING zone-save (multiple
pulses in the same second), at zone/exclusion edits (paired with s2p50
o=215), at maintenance-point save (two pulses 1 s apart), AND at
every map-swap (one pulse per swap, 2026-05-07 confirmed across
multiple swaps in a single session).

A standalone s1p50 (no s1p51, no s2p50) is the signal to re-fetch whatever
the integration caches from the cloud — in practice, the MAP.* dataset
and/or MAPL for active-map detection. Map-swap pulses are the most
reliable per-swap signal (s2p50 o:200 is conditional — fires on
some swaps but not others; see o200 entry).

See docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes for the full role catalogue and
the correction note (2026-04-23) on earlier session-boundary hypotheses.

**Open questions:**
- The app's 'Reorienting' popup is NOT driven by the MQTT /status/ stream. A clean popup-timed capture 2026-05-30 (move @ 17:25): user-noted popup START 17:25:42, STOP 17:26:17 — BOTH land inside the 41 s MQTT-silent reorient window (undock 17:25:37-38 → s1p50/s1p51 17:26:19), i.e. popup START ≈ undock+5 s, popup STOP ≈ s1p50/s1p51−2 s. The only wire traffic at those two instants is a routine s1p1 heartbeat whose 20 bytes are identical to neighbours except the counter (byte[11-12]) and a non-binary byte[14] (0 docked→64 undock→4→5→7→135) — NO clean popup on/off flag. So the popup driver is off the sniffed wire (cloud poll/push suspected); the integration cannot reproduce its exact timing from MQTT — best proxy is the bracket [undock transition → s1p50/s1p51]. LEAD for a future capture: popup START and STOP each coincided with an s1p1 emission (s1p1 fires extra heartbeats on state transitions) — check whether popup edges ALWAYS coincide with a heartbeat across captures before trusting it.
- Housekeeping slots seen DURING the silence (candidates for what the firmware does while it spins): s6p1 map_data_signal {200,201,300} at ~+20 s (5/66; likely the LiDAR-map load), s5p107 energy_index at ~+13 s (53/66), and the UNDER-DECODED s5p106 (purpose unknown, values 1-8; 7/66 at ~+12 s) and s5p105 (enum {1,2,4}; 3/66 at ~+13 s). The clean 360 relocate does NOT emit the SLAM counter (s5p104/s2p65 fire only on the failed-relocate case, 1/66).

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:50`

### s1p51 — `dock_position_update_trigger`

Dock-position-update trigger per apk decompilation. Fires when the dock pose
changes; consumer should re-fetch via the routed getDockPos action (siid:2
aiid:50 m:'g' t:'DOCK'). Also fires co-incident with s1p50 at every mowing
session start (the firmware emits both in the same second when a run begins),
but the primary semantic is dock-pose change, not session boundary.

2026-04-23 correction: earlier hypothesis called this a "session-start
companion to s1p50 based on observed co-occurrence". Co-occurrence is real
but the apk specifies dock-pose change as the primary trigger.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:51`

### s1p52 — `task_end_flush`

Task-ended flush/commit ping. No payload. Fires at session complete
(s2p2 = 48) on both natural end (12:33:09 on 2026-04-20) and user-cancel
(18:06:19). Does not fire at BUILDING end. Also fires immediately before
the cloud event_occured siid=4 eiid=1 session-summary push (2026-04-22
16:35:17).

2026-04-23 correction: the earlier "s1p52 + s2p52 bracket session ends"
hypothesis is wrong per apk decompilation. s2p52's primary semantic is
mowing-preference-update trigger, not session-end. The apparent co-occurrence
at session boundaries is firmware bookkeeping (re-emitting prefs as part of
teardown).

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:52`

### s1p53 — `bluetooth_connected`

Controlling-app BLUETOOTH connection status (bool). True while a Dreame app
has a BLE connection to the robot; toggles when the app is foregrounded /
backgrounded. The apk's own name for this slot is "BLE Connection Status",
and the sibling dreame-mower integration names siid:1 piid:53
"bluetooth_connected" — both agree, and the user reproduced it at will
2026-06-05 by entering/leaving the phone app.

NOT obstacle detection. The earlier "obstacle_flag" reading was a
correlation artifact: the 26 toggles seen "near an exclusion zone" coincided
with the user handling the phone app during that window, not with obstacle
events. Obstacle/person/animal events are cloud-side push notifications, not
this MQTT bool.

Integration surface: binary_sensor `bluetooth_connected`
(device_class CONNECTIVITY). (Was mislabelled `obstacle_detected` /
MowerState.obstacle_flag before the 2026-06-05 relabel.)

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:61 + binary_sensor.py (bluetooth_connected)`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 1 piid:53; OLD/dreame-mower const.py:53 bluetooth_connected`

### s2p1 — `mode`

Mower mode/activity enum per apk decompilation. Previously hypothesized as
a mystery enum {1, 2, 5}; apk reveals the full mapping. Note the upstream
dreame-mova-mower mapping swaps (2,1) and (2,2) vs g2408 actual — the g2408
overlay in types.py swaps them back.

Value 16 is labelled STATION_RESET in the legacy upstream enum (still used in
lawn_mower.py for now); the actual semantics are "docked, refusing to charge
because battery is below safe-charge temperature" — confirmed 2026-04-26
across 5 occurrences during cold morning hours, every entry coincident with
s1p1 byte[6]=0x08.

Value 3 (PAUSED) confirmed in probe corpus: 5 observations in two files
(2026-04-17 and 2026-04-22/28/29), always co-incident with s2p56
status=[[1,4]]. Previously thought to fold into mode 1.

Value 11 (BUILDING) confirmed 2026-04-20 17:00:09 when user triggered
"Expand Lawn" from the Dreame app.

Enum gaps — values 7, 8, 9, 10, 12 are RESERVED/UNUSED on g2408: not named
in ANY source (cloud keyDefine {1-6,11,13-16}, Flutter app asset
common_mower_protocol.json {1-6,11,13,14}, or the integration/upstream
enum) and never observed on the wire across the 9-log probe corpus
(~66k samples). The numbering simply jumps 6→11. Observed values:
{1,2,3,4,5,6,11,13,16}. Named-but-unobserved (await OTA / hot-battery
charge): 14 (Updating), 15 (charge-paused temp-too-high). Don't invent
names for 7-10/12.

**Open questions:**
- Accepted gap: if the mower docks while HA is down, location may read stale ON_LAWN until the next s2p1 push; self-heals on the next 6↔13 charge cycle. A future cloud-props→s2p1 feed (same signal, slower transport) could close it without reintroducing a second authority.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:1`

### s2p2 — `error_code`

Numeric state / fault code — one discrete value per push (NOT a bitfield,
NOT a state machine). The g2408 meanings are mostly NOT the apk's
vacuum-lineage FaultIndex labels; treat the vacuum forks as unreliable here
and rely on the per-code table below (full detail + evidence trail in the
`state_codes:` section and in this entry's `verifications:`).

Current g2408 meanings — wire- and/or cloud-verified (one code per line):
Faults:
- 2  Robot trapped
- 4  Left drive wheel error
- 5  Right drive wheel error
- 23 Lift lockout (emergency stop)
- 31 Failed to return to station
- 33 Positioning / relocate failed (drives state-machine STUCK)
- 36 Failed to start task
Lifecycle:
- 27 Idle / human-detected marker
- 50 Manual or mow session start
- 53 Scheduled session start
- 70 Mowing / continue unfinished task
- 48 Mowing complete
- 54 Low battery — returning to station
- 56 Rain protection activated (rising edge only)
- 60 Frost-protection-suppressed
- 63 Scheduled task cancelled — robot working (busy)
- 71 Standby outside station too long — auto-return
- 74 Patrol ended / cancelled
- 75 Arrived at maintenance point
- 76 Cannot reach maintenance point — task ended (give-up + return)
- 24 Battery low (warning threshold — not a stuck-state; see open_questions re 24 vs 54)
- 43 Battery temperature low — charging paused (environmental; mower self-protects)
Maintenance push (cloud-gated, not errors):
- 28 Blades severely worn (cloud wear%-gated push)
- 30 Maintenance reminder — maintain robot soon
Observed on g2408, decode CROSS-REFERENCED from the sibling dreame-mower
integration's device_code.py (siid:2 piid:2 — SAME channel; its table matches
ALL our independently-confirmed g2408 codes: 24/28/30/43/51/54/71). NOT yet
g2408-wire-LABELLED, so kept OUT of error_codes.py per the confidence gate:
- 20 — "Sensor error" (dreame-mower name SENSOR, type ERROR). [presumed]
  Corpus: x3 in probe_log_20260520, in a maintenance/mow sequence before 33/36/63.
- 72 — "Returning to dock after pause timeout" (dreame-mower PAUSE_TIMEOUT_RETURNING,
  type INFO). [partial] — sibling of confirmed 71 (idle-timeout-returning) AND
  corroborated by the g2408 corpus (72 fires near s2p1 state=5 returning, x3 in
  probe_log_20260520). Further corroborated 2026-06-13 by the pause-timeout
  TIMING: s2p1=4 (auto/hold pause) fired at 21:45:19 and s2p2=72 fired at
  22:45:18 — exactly ~1 h later — i.e. the pause hit its 1-hour timeout and
  the mower began returning, matching PAUSE_TIMEOUT_RETURNING. (That return
  ultimately failed — mower stuck on lawn → battery 5% → s2p57 firmware
  self-shutdown 2026-06-14; see § s2p57.) Still kept OUT of error_codes.py
  until a cloud-LABELLED fire is captured (the slug name is still borrowed).

Watch out — corrected vs earlier / vacuum readings (evidence in verifications):
- 28 is the cloud wear%-gated BLADE-WEAR push, NOT an off-dock-relocate
  marker (the "fires 14/14 on every undock" reading was debunked by
  full-corpus analysis).
- 71 is "standby-too-long auto-return", NOT "positioning failed".
- The off-dock 360 reorient carries NO dedicated s2p2 code.

The per-fire user-visible TEXT is composed by Dreame's cloud, not carried on
the wire — the integration relays cloud pushes (coordinator/_notifications.py)
and must not synthesize text from a raw s2p2 transition. Any value outside the
known set emits a one-shot [PROTOCOL_NOVEL] s2p2 WARNING. Upstream
dreame-mova-mower maps (2,2)=ERROR / (2,1)=STATE — reversed vs g2408; the
g2408 overlay corrects this.

**Open questions:**
- What wire surface carries the user's 'Continue' tap that clears rain-protection early? Candidate: an s2p50 op-code or an s2p2 transition out of the suppressed window. Capture during a live Continue press.
- g2408 meaning of s2p2 20 and 33 — both fired in the 2026-05-25 12:32 off-dock-failure burst alongside 'Sensor error' / 'positioning failed' app notifications, but neither is in the cloud's recent-history window (likely pruned). Need either a controlled repro within the cloud's retention window, the apk full 78-entry FaultIndex (bundle L94618-94697, not in apk.md), or text via an API-on-demand fetch the next time these codes fire.
- s2p2=71 = idle-too-long-return vs broader non-battery return? Core meaning text-confirmed (standby-too-long → auto-return) and the slug/sensor are fixed. Still open: is 71 strictly the idle-timeout reason, or ANY non-battery return? 3 of 5 corpus occurrences fire while already returning (prev=5). Capture other return triggers (user-recall, end-of-task) to see if they also carry 71; if 71 is broader than idle-timeout, broaden the slug name accordingly.
- Remaining single-observation fault codes from the 2026-05-30 stuck-patrol (user-confirmed app text; confirm exact string via device-messages/v2): s2p2=2 = 'Robot trapped. Tap to view the solution' (22:44:40, stuck on hose); s2p2=74 = patrol ended/cancelled (23:02:12, fired with s2p1→2 when the user cancelled the patrol → return to dock). Both co-incident with a pause/end (s2p1=4/2, s2p56=[[1,0,4]] paused) and present in the s4 eiid1 arg13 fault timeline. apk FaultIndex 2 was unmapped/vacuum-derived on g2408 — this is the real g2408 meaning. RESOLVED out of this list: the drive-wheel pair 4='Left drive wheel error' (2026-05-30) and 5='Right drive wheel error' (2026-06-01) are now in the state_codes table + error_codes.py (decoded: confirmed).
- s2p2 24 'Battery low' vs 54 'Low battery — returning to station' overlap: confirm the distinction (hypothesis: 24 = low-battery WARNING threshold, informational; 54 = the low-battery event that TRIGGERS return-to-dock). Capture both firing in one session to pin the trigger points, then rename 24 to something unambiguous (tentative: 'Battery low (warning)'). presumed until a capture confirms.
- s2p2 codes 0/1/9/23 are the s2p2 echoes of the s1p1 safety bits (bumper/tilt/lift/PIN), confirmed by the 2026-04-30 19:37–19:39 controlled test. Open: redundant with the s1p1 binary_sensors, or do they carry extra info worth a dedicated surface?
- s2p2=0: strictly the bumper/hanging event, or also the post-event return-to-idle value? Corpus has only 6 transitions-to-0; need captures that disambiguate a bumper press from a generic clear-to-0.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:62`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:2`

### s2p50 — `task_envelope`

TASK envelope — multiple operation classes sharing this slot. Two major
shapes observed:

1. Flat fields (session-task metadata, session start): {area_id, exe,
   o:100, region_id:[1], time, t:'TASK'}
2. Wrapped map-edit: {d:{exe, o, status, ...}, t:'TASK'}

Confirmed opcode catalog (partial — full catalog in opcodes section, Task 8):
o=100 global mow start, o=101 edge mow, o=102 zone mow, o=103 spot mow,
o=109 task-start failed, o=201 operation completed, o=204 map-edit request,
o=215 map-edit confirm (carries id and ids), o=218 delete, o=234 save zone
geometry, o=401 takePic, o=-1 error abort, o=3 task cancelled, o=6 explicit
Recharge.

The cloud occasionally drops s2p50 deliveries under load. The integration
triggers a MAP rebuild on o=215 or o=201 with status:true && error:0.
The s2p50 echo is NOT a faithful copy of the input (firmware canonicalizes
payloads). Detailed opcode catalog lives in opcodes section (Task 8).

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:50`

### s2p51 — `multiplexed_config`

All "More Settings" toggles in the Dreame app that travel via cloud share
this single property. The payload shape discriminates the setting. Confirmed
shapes include: {end, start, value} for DND; {value: [enabled, start, end]}
for Low-Speed Nighttime; {value: 0|1} for single-toggle settings (Child
Lock, Frost Protection, Auto Recharge Standby, AI Obstacle Photos,
Navigation Path); {value: [b,b,b,b]} for 4-bool settings (MSG_ALERT /
VOICE — wire-ambiguous, disambiguated via getCFG diff); {value: [6-element
list]} for Charging config; {value: [8-element list]} for LED Period;
{value: [3-element list]} for Anti-Theft; {value: [9-element list]} for
Human Presence Alert; {text, voice} for Language; {time, tz} for timestamp
heartbeat.

Also overloads to a consumables runtime counter shape {value: [blade_min,
brush_min, robot_min, link_module_min]} — discriminated from the 4-bool
shape by any element > 1 or < 0.

Shape {result, time}: first seen 2026-06-09 18:17:34 during app-MITM.
LEAD: matches PIN read response shape from the findings doc — m:g t:'PIN'
→ {result(0=ok), time(lockout_ms)}. [UNKNOWN — to verify by correlating
the 18:17:34 capture with PIN-read activity in the MITM log]

Detail in s2p51_shapes section (Task 11). Confirmed 2026-04-17 through
2026-04-30 via live toggle testing.

**Open questions:**
- Undecoded s2p51 shape {'type': 0|1} — NOT handled by decode_s2p51 (raises S2P51DecodeError 'unknown payload shape' at config_s2p51.py:125 → _property_apply logs a one-shot [PROTOCOL_NOVEL] WARNING and drops it). First seen 2026-06-03 20:04-20:05 during patrol-point editing; a single-key 0/1 value. LEAD (dreame-mower cross-ref): that integration treats ALL of s2p51 as a GENERIC 'settings change acknowledgment — re-fetch' trigger (property_misc.py SettingsChangeHandler), not a self-contained value. So {'type': N} is likely a which-category-changed re-fetch trigger (like s2p52), and the actual change lands via a getCFG re-fetch — NOT a value to decode in place. Confirm via CFG-DIFF (toggle a patrol/map setting, watch s2p51 {type} then diff getCFG).

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:51`

### s2p52 — `preference_update_trigger`

Mowing-preference-update trigger per apk decompilation. Fires when PRE
settings change; consumer should re-fetch via the routed getCFG action
(siid:2 aiid:50 m:'g' t:'CFG').

2026-04-23 correction: previously hypothesized as a session-end companion
to s1p52 based on observed co-occurrence at session end (16:35:17.786 →
18.031). Per apk, the semantic is preference-change, not session-end. The
firmware fires s2p52 at session end because it re-emits prefs as part of
teardown, not because this is a dedicated session-end signal.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:52`

### s2p53 — `voice_download_progress`

Apk says VOICE_DOWNLOAD_PROGRESS_PCT — progress counter for downloading a
voice pack to the mower. Observed 5 times in the probe corpus but never
pushing meaningful progress on g2408 (values all near 0 or 100 with no
intermediate ticks). No voice-pack download was initiated during the corpus
capture window, so these may be startup-time residue or idle-state pings.

Confirm by triggering a language change from the app while probe is running.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §VOICE_DOWNLOAD_PROGRESS_PCT`

### s2p54 — `lidar_upload_progress`

LiDAR point-cloud upload progress counter, 0..100. Published roughly once
per second while the upload runs. Triggered by the user tapping "View LiDAR
Map" in the Dreame app, provided the current scan differs from the last-
uploaded one (reopening with no scan change is a no-op).

Confirmed 2026-04-20 17:41:58–17:42:28: s2p54 = 0 at upload start, then
10, 16, 21..45, 61, 100. Total wire time: 30 seconds, 2.45 MB PCD.

s99p20 (the OSS object key) arrives BEFORE s2p54 = 100 (at 61% in the
observed capture). The integration keys off s99p20 rather than waiting for
s2p54 = 100.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Events`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:54`

### s2p55 — `ai_obstacle_report`

Apk says AI_OBSTACLE_REPORT — a list of AI-camera-detected obstacle events.
Observed 14 times in the probe corpus but always an empty list on g2408.
No AI camera triggers were observed in the user's corpus: the g2408 may
require AOP (AI Obstacle Photos) to be enabled and an actual obstacle to be
encountered, or the AI report may only populate when the Dreame cloud
processes a captured image.

Cannot confirm semantics without a corpus capture that includes an actual
AI detection event.

AI-photo cloud-endpoint hunt (2026-05-31, probe_ai_photo.py + /tmp
history/ipc sweeps): the obstacle-photo *list* is NOT on any device-keyed
cloud surface reachable with the integration's Dreame-Auth token. Ruled
out: (a) batch device-data — `getDeviceData` ignores the `key` filter and
dumps the full model; no AI/photo key exists; (b) `iotstatus/history`
property-history for s2p55/s2p51/s1p53 → all `{"list":[]}` (also empty for
s2p1/s2p2, so this device historises nothing server-side); (c) siid=1/2
event-history (eiid 1..20) → empty; (d) `message-record/list` categories
1..20 → 0 records; (e) `device-messages/v2` → empty (short ~6-7d
retention); (f) guessed `/dreame-*/ {ai-photo,obstacle-photos,
device-photos}` paths → 404. The only live lead is
`/smart-app/ipc/detection/event/list` (libapp.so has a full IPC event
model: imageUrl/picUrl/confidence/eventType; detection classes
Human/Bird/Fire/Crying) — it accepts our token (HTTP 400 "Missing
necessary request parameters", not 404/auth) but the g2408 device record
has `videoStatus:null` + `featureCode:-1`, i.e. the mower is NOT enrolled
as an IPC/camera device, so this is most likely the Dreame security-camera
product line, not the mower; 7 param shapes all stayed at 400.
CLARIFICATION [app-mitm:2026-06-12-live-video]: "not IPC-enrolled" does NOT
mean "no camera". The g2408 HAS a camera — it is enrolled under Tencent IoT
Video (feature:"video_tx") and reached via the `dreame-third-video/tx/*`
cred chain + XP2P P2P stream (see api_endpoints § tencent_video), a DIFFERENT
path from the `/smart-app/ipc/*` security-camera surface that returns
videoStatus:null here. The AI-obstacle-photo hunt below is unaffected by this
correction — those photos still live on the OSS gallery (userDidOssList),
reached separately from the live-video stream. Meanwhile
the feature is ON at the cloud level — CFG.AOP=1 and REC[7] photo_consent=1
across all dumps — and the user reports the photo set syncing to a 2nd app
device, so photos DO exist cloud-side.

UPDATE 2026-05-31 — Tasshack/dreame-vacuum analogue (likely supersedes the
"needs a separate endpoint / MITM" conclusion above). The vacuum integration
reads obstacle photos with NO dedicated endpoint: each photo is an inline
entry in the map blob's `ai_obstacle` array (the SAME field name our
session_summary.py already parses, empty in our corpus). Per
OLD/.../dreame-vacuum/dreame/map.py (~L2086) each entry is
`[x, y, type, possibility, key, file_name, random]` — a photo exists only
when `len>=7 and int(key)>=1000`; a 4-element entry is a detection-only
marker. `possibility` = the "human 80%" confidence (×100), `type` = obstacle
class (vacuum enum 128-139 = furniture/clutter; the MOWER's classes will
differ — Human/Animal/Object per the app), `file_name` = an OSS object name
fetched via `get_interim_file_url(file_name)` (the SAME OSS path our mower
already uses for maps/LiDAR — cloud_client/_oss.py). The vacuum AES-CBC
decrypts the crop (aes_iv+key) because its maps are encrypted binary; the
g2408's maps are PLAINTEXT JSON, so the mower's file_name is likely a
plaintext OSS key (decryption need TBD). The "2nd-device same set" =
both apps read the same cloud blob's ai_obstacle + fetch the same OSS
objects (no per-account gallery service). Historical photos: the vacuum
pulls them via OBJECT_NAME property-history; the mower equivalent is the
MAPL/map-object history. STATUS: structural template only — NOT yet
g2408 wire-confirmed (our ai_obstacle has always been empty). Confirm by
capturing the live MAP blob + session summary during/after a REAL detection
and checking whether ai_obstacle populates with 7-element entries; if so,
fetch file_name via the existing get_interim_file_url. This is MITM-FREE and
replaces the earlier blocked-by-MITM next step.

**See also:** `protocol/session_summary.py:140,385 (ai_obstacle already parsed); cloud_client/_oss.py (get_interim_file_url already present)`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §AI_OBSTACLE_REPORT; apks/aa/lib/arm64-v8a/libapp.so (IpcEventModel)`

### s2p56 — `task_state`

Cloud status push — internal task-state ack. Wire envelope has two
observed shapes on g2408:

  2-element variant — full-area mows (most common, 163/213 in corpus):
    {"status": []}            no active task
    {"status": [[1, 0]]}      running
    {"status": [[1, 2]]}      complete / transitional
    {"status": [[1, 4]]}      paused-pending-resume / recharge boundary

  3-element variant — SCHEDULED mows (since 2026-04-27); a value is inserted
  in the MIDDLE so the stage moves to the LAST element. Structure is
  [task_id, X, stage] where X is always 0 (undecoded — likely a segment/lap
  index) and the STAGE is the LAST element (decoded 2026-05-30):
    {"status": [[1, 0, 0]]}   running — last value 0
    {"status": [[1, 0, 4]]}   PAUSED  — last value 4 (e.g. stuck/rain mid-run)
    {"status": [[1, 0, 2]]}   DONE    — last value 2
  [1,0,2] = SESSION-DONE (NOT a "segment" that resumes). Corpus-verified
  2026-05-30: across all 10 [1,0,2] events the mower DOCKS within ~1 min
  (s2p1→6) and NONE is preceded by a rain code (s2p2=56). The few later
  re-activations are SEPARATE mows 15-25 min after docking, not resumes.
  DEBUNKED: the 2026-05-16 claim that "[1,0,2] at 19:13 then ran 19 h
  rain-spanned (2026-05-09 edge mow)" is FALSE — that mow docked at 19:14.
  Treat that whole "segment vs archive session / rain-spans-[1,0,2]" story
  (incl. an earlier version of THIS note) as guesswork that was wrong.
  Consequence: the integration now reads status[0][-1] (the LAST element) as
  task_state_code — correct for both 2- and 3-element, and it surfaces the
  3-element PAUSE [1,0,4] which the old middle-read missed. (v1.0.x 2026-05-30;
  property_mapping.py (2,56).)
  NB the earlier "3-element = edge/spot/zone mows" attribution is imprecise:
  3-element correlates with SCHEDULED runs (morning all-area mode=100 included),
  not mow type. App-triggered runs (points, manual, the 2-spot mow) stay 2-element.
  [CORRECTED 2026-06-07 — see verifications: the split tracks MOW TYPE = EDGE.
  3-element ⟺ EDGE mow; 2-element ⟺ all-area / zone / spot / manual. Confirmed by
  14/14 days of 07:58 all-area = 2-element, scheduled zone = 2-element, and all 10
  three-element days being short evening edge sessions. NOT scheduled-correlated.]

The integration extracts status[0][-1] (the LAST element = stage) as
task_state_code: 0=running, 4=paused, 2=complete, None=no task. This is
correct for both 2-element (last == [1]) and 3-element (last is the stage,
not the constant-0 middle). Pre-2026-05-30 it read status[0][1], which on
3-element runs returned the middle 0 and hid done/paused — a workaround
built on the now-debunked 19h-rain story (see above). The session-end
signal can be either the [1,0,2]/empty `[]` event OR the integration's
cloud-summary gate. The probe sometimes misses the `[]` event (HA restart,
probe truncation) in which case the HA
archive's recorded `start` / `end` fields are the ground truth.

The session-state machine uses task_state_code for begin_session /
begin_leg / session-end transitions: 0→4→0 is a recharge round-trip;
4→0 triggers begin_leg; prev∈{0,4} and new∈{2,None} means session ended.

Confirmed g2408 sub-state values from 2026-04-29/30 corpus. Note: wire shape
is a dict, not a bare int — a common decode trap for apk-decompiled code.

**Open questions:**
- 3-element MIDDLE value (the X in [task_id, X, stage]) = the EDGE INDEX within the zone — WHICH edge to mow (user insight 2026-06-07, discussed before but lost from docs; supersedes the old 'segment/lap index' guess). Maps to the app's schedule naming: 'Edge mowing Zone1-1' carries an edge selector → 3-element, while 'Zone mowing Zone1' and 'All-area' have none → 2-element. Always 0 because only ONE edge is currently defined (Zone1's single perimeter); a SECOND edge should make X=1 — the way to confirm. Likely the same value as the SCHEDULE blob's edge record (action=2) extra byte rec[7] (schedule_decode.py, currently 'reserved2'). [UNVERIFIED]
- 3-element ⟺ EDGE mow (resolved 2026-06-07, see verifications; status partial). Remaining gap: independently confirm (via cloud summary.mode or s2p50 envelope) that the non-2026-06-06 evening 3-element days (2026-05-09/16/17/23/30, 2026-06-03/04) are all edge mows — currently inferred from timing/duration. (The middle value's meaning — edge index — is the separate open-question below.)

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:80`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:56`

### s2p57 — `robot_shutdown_trigger`

Robot shutdown trigger. Apk subscribes at L181482-181512 and dispatches
a 5-second-delay sequence culminating in a firmware shutdown or reboot.
Described in apk as "Robot Shutdown" — fires during OTA reboot or device
power-down cycles. Consumer is expected to wait 5 s then treat the device
as offline.

First captured on the g2408 wire 2026-06-14: a single standalone
properties_changed push carrying the bare scalar `value: 1` (the only
param in the message) [probe_log_20260612_174439.jsonl@2026-06-14T04:42:16].
The observed payload is a bare int, NOT the previously-hypothesized
`dict (shutdown signal)`. This particular fire was a LOW-BATTERY FIRMWARE
SELF-SHUTDOWN, not an OTA reboot and not a manual power-down: the mower was
stuck on the lawn unable to make it back to the dock, and when the battery
drained to 5% the firmware shut the robot down on its own (presumably to
avoid a full discharge). It woke again only when physically carried to the
charging dock and plugged in [user-observation:2026-06-14]. So at least one
s2p57=1 trigger is a firmware-initiated protective shutdown at the ~5%
battery floor. Other triggers (OTA reboot, thermal cutoff, manual
power-down) remain plausible per the apk but are still unconfirmed on the
g2408 wire — do not attribute a future s2p57=1 to a manual shutdown without
a correlated marker.

**Open questions:**
- Are there OTHER s2p57=1 triggers besides the ~5% low-battery self-shutdown (OTA reboot, thermal cutoff, manual power-down)? The low-battery cause is now confirmed for one occurrence; capture a correlated OTA/offline marker if s2p57=1 ever fires outside a low-battery context.
- Are there other s2p57 values (e.g. distinguishing reboot vs shutdown), or is it always 1?
- Is this a command echo or a push the device sends spontaneously?

**See also:** `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:57`

### s2p58 — `self_check_result`

Self-check / diagnostics result. Apk subscribes at L141634 and L142731;
payload shape is {d: {mode, id, result}}. Triggered by the apk's
setSelfCheck command ({m:'s', t:'CHECK', d:{mode, status}}). The apk
renders these as in-app diagnostic results for each subsystem.

Never observed in g2408 probe corpus. To capture: trigger "Self-Check"
from the Dreame app's Maintenance → Self-Diagnosis menu.

**Open questions:**
- What mode/id/result values does g2408 emit? Trigger Self-Check from Maintenance menu.
- How many s2p58 pushes appear per self-check run (one per subsystem or a summary)?

**See also:** `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:58`

### s2p61 — `map_update_trigger`

Map-update trigger. Apk subscribes at L181514-181515 and calls
loadMap() on receipt. Signals that a new map snapshot is available
on the cloud. Similar in spirit to s1p50 (state_change_ping) and
s6p1 (map_data_signal) but a distinct slot targeting the full map
reload path.

Never observed in g2408 probe corpus. May fire after map-building
sessions or when the device uploads a new map version. Distinct from
s6p1 = 300 (which fires at recharge-leg boundaries), this appears to
be the "full map pushed to cloud" notification.

**Open questions:**
- When exactly does s2p61 fire relative to s6p1 and s1p50 in a map-building session?
- Confirm payload shape (empty dict or carries map metadata).

**See also:** `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 2 piid:61`

### s2p62 — `task_progress_flag`

Apk says task progress flag. Observed 16 times in the probe corpus. Semantic
on g2408 not yet pinned — values and timing have not been correlated with
specific task events in the available captures. Needs a dedicated
toggle-correlation test.

**Open questions:**
- What values appear and when? Cross-correlate with s2p1 and s2p2 transitions.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §task_progress_flag`

### s2p65 — `slam_task_label`

SLAM / nav task-type string. Three values confirmed on g2408:

'TASK_SLAM_RELOCATE' — fires 3× in ~1 second when the mower kicks off a
LiDAR relocalization to re-anchor against the saved map. Paired with s5p104
(SLAM relocate counter = 7) in the same burst. Occurs after the mower wakes
in an unknown position (e.g. manual mode ended outside the known map area).

'TASK_NAV_DOCK' — fires once at the start of an explicit dock-navigation
phase. Confirmed 2026-05-05 across two integration-launched edge runs:
fires when the mower enters the post-FTRTS retry path (not on clean
autonomous returns). Paired with s6p117 = 1 in the same second.

'TASK_NAV_CHECK' — fires periodically during long path-traversal phases.
Confirmed 2026-05-07 mowing of newly-created Map2 (which has a connecting
path from dock to mowable area): fired 3× over ~3 minutes at 20:00:42,
20:01:04, 20:03:06 between mow-start command and actual blade engagement
at 20:04:25. Hypothesized to be a "stop-and-verify-direction" check during
pathing (~1 per minute cadence is too slow to be one-time repositioning;
repositioning is 10–20 s). Not seen during regular intra-map mowing.

Not seen during clean autonomous returns where s2p1: 5→6 fires directly
without intervening NAV_DOCK.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:92`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s2p66 — `lawn_area_snapshot`

Lawn-size snapshot. First element = total mowable lawn area in m² (matches
event_occured piid 14 from the session-summary exactly). Second element
unknown — decreased by 8 when area grew by 5 m², so not
perimeter-proportional; candidates include blade-hours ×10, unique path
segments, or a total-distance-mown counter.

Observed [379, 1394] on 2026-04-17, [384, 1386] on 2026-04-20 after a
manual "Expand Lawn". Fires at the end of a BUILDING session and probably
periodically during mowing. First element can be float on the wire
(e.g., 383.5 after partial-area expansion) — cast to float before use.

The integration uses the session-summary's map_area field as the primary
source for total_lawn_area_m2, since s2p66 pushes infrequently (multi-day
gaps in probe corpus).

**Open questions:**
- What does the second list element represent? Candidates: blade-hours ×10, path segments, total-distance-mown counter.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:95`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s3p1 — `battery_level`

Battery percentage. Integer 0..100. Pushes on change during mowing and
charging. The primary battery-state signal for the HA integration.
Confirmed across the full probe corpus 2026-04-17 through 2026-05-05.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:57`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 3 piid:1`

### s3p2 — `charging_status`

Charging status enum. On g2408, value 0 means "not charging" (enum offset
vs upstream — upstream mapping expects 1 for not-charging). Confirmed across
the full probe corpus: transitions to 1 when mower docks and charging starts,
drops to 0 when mowing resumes.

Used in the integration as the authoritative "charging started" signal
(s3p2 → 1) to confirm dock arrival, particularly when s2p50 o=6 echo is
unreliable.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:58`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 3 piid:2`

### s4p21 — `obstacle_avoidance`

Obstacle-avoidance mode selector. Upstream mower forks define OBSTACLE_AVOIDANCE
at (4, 21) in DreameMowerPropertyMapping. The legacy integration reads and writes
this property to control AI-obstacle avoidance sensitivity. On g2408 obstacle
behaviour is governed by s2p1 and s2p2, but this property slot may co-exist.

**Open questions:**
- Is s4p21 present on g2408 firmware? Probe with a direct SIID 4 PIID 21 GET to confirm.
- If present, does the enum match the legacy ObstacleAvoidance values (0=disabled, 1=enabled, 2=intensive)?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:687)`, `github.com/nicolasglg/dreame-mova-mower (types.py:740)`

### s4p22 — `ai_detection`

AI-based pet/obstacle detection mode. Upstream mower forks define AI_DETECTION
at (4, 22) in DreameMowerPropertyMapping. Controls whether the camera-based AI
detection is active during mowing.

CORRECTION: the g2408 DOES have a camera (feature:"video_tx", Tencent IoT
Video / XP2P — see api_endpoints § tencent_video). The earlier "no camera
module has been confirmed on g2408" note here was stale and is retracted.
[app-mitm:2026-06-12-live-video] What remains UNVERIFIED is whether THIS
property slot (s4p22) is the control surface for camera AI detection on g2408:
the camera is driven via the o=400 live-view toggle plus the
dreame-third-video/tx credential chain, and AI-obstacle capture is gated by
CFG.AOP (not by any observed s4p22 write). s4p22 has never been seen on the
g2408 wire; it may be a no-op, a read-back, or absent. [UNVERIFIED]

**Open questions:**
- Is s4p22 the g2408's camera-AI control surface, or is AI capture wholly gated by CFG.AOP + o=400? s4p22 unseen on the wire.
- Does s4p22 interact with s4p59 (PET_DETECTIVE)?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:688)`, `github.com/nicolasglg/dreame-mova-mower (types.py:741)`

### s4p23 — `cleaning_mode`

Mowing / cleaning mode selector. Upstream mower forks define CLEANING_MODE
at (4, 23). Controls the active mowing behaviour (e.g. edge-only, zone, spot).
On g2408 the equivalent is the task-type sent via the s5a1 action envelope;
this property slot may be a read-back or may not be used.

**Open questions:**
- Is s4p23 present on g2408 firmware? Probe with direct GET to confirm.
- If present, does the enum match the legacy CleaningMode (0=standard, 1=quiet, 2=boost)?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:689)`, `github.com/nicolasglg/dreame-mova-mower (types.py:742)`

### s4p26 — `customized_cleaning`

Per-zone customised cleaning settings. Upstream mower forks define
CUSTOMIZED_CLEANING at (4, 26) — carries a JSON blob with per-zone
pass-count and cutting-height overrides. On g2408 these settings are
embedded in the s5a1 task envelope; this property may carry a persisted
read-back of the last settings.

**Open questions:**
- Is s4p26 present on g2408 firmware? Probe with direct GET.
- If present, does the JSON schema match the legacy CustomizedCleaning format?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:691)`, `github.com/nicolasglg/dreame-mova-mower (types.py:744)`

### s4p27 — `child_lock`

Child-lock / panel-lock property. Upstream mower forks define CHILD_LOCK
at (4, 27). On g2408 child-lock is toggled via the cfg_toggle mechanism
(setting key 'CLS') which writes through s2a50 o:8, NOT by directly
writing s4p27. The property slot may still exist as a read-back surface.

**Open questions:**
- Is s4p27 present on g2408 firmware? The greenfield uses cfg CLS not a direct property write.
- If present, does writing s4p27=1 work on g2408, or must the cfg_toggle path be used?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:692)`, `github.com/nicolasglg/dreame-mova-mower (types.py:745)`

### s4p44 — `cruise_type`

Cruise / patrol mode type. Upstream mower forks define CRUISE_TYPE at (4, 44).
Controls whether the mower follows cruise points or a fixed patrol pattern.

CORRECTION: the g2408 DOES expose cruise/patrol behaviour — point patrol
(o107) and edge patrol (o108) are live-confirmed, cruise points are parsed
from the MAP blob's cruisePoints array (type=8), and a patrol auto-enables the
camera (o=400) for auto-capture. So the earlier "does not expose cruise-point
behaviour in current captures" note was stale. [app-mitm:2026-06-12-live-video]
What remains UNVERIFIED is whether THIS property slot (s4p44) carries the
patrol mode-type on g2408: patrol is driven via the s2.50 o107/o108 routed
actions, not an observed s4p44 write; s4p44 has never been seen on the g2408
wire. [UNVERIFIED]

**Open questions:**
- Does s4p44 carry the patrol mode-type on g2408, or is patrol wholly driven by the o107/o108 routed actions? s4p44 unseen on the wire.
- Does cruisePoints in the OSS map blob connect to s4p44?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:699)`, `github.com/nicolasglg/dreame-mova-mower (types.py:752)`

### s4p47 — `scheduled_clean`

Schedule configuration property. Upstream mower forks define SCHEDULED_CLEAN
at (4, 47). Carries a JSON blob describing the active mowing schedule(s).
On g2408 scheduling is managed through the s2p50 / cfg mechanism (fields SCH,
SNS, etc.); this s4p47 slot may carry a read-back or may be the canonical
schedule store.

**Open questions:**
- Is s4p47 present on g2408 firmware? Probe with direct GET.
- If present, is this the canonical schedule store or a read-back of what went through s2p50?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:700)`, `github.com/nicolasglg/dreame-mova-mower (types.py:753)`

### s4p49 — `intelligent_recognition`

Intelligent multi-map recognition flag. Upstream mower forks define
INTELLIGENT_RECOGNITION at (4, 49). In the legacy integration this is
exposed as the 'multi_map' attribute; when enabled the device can maintain
separate maps for different lawn areas. Status on g2408 is unknown.

**Open questions:**
- Is s4p49 present on g2408 firmware? Probe with direct GET.
- Does multi-map capability affect the s6p8 MAP_LIST behaviour on g2408?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:702)`, `github.com/nicolasglg/dreame-mova-mower (types.py:755)`

### s4p59 — `pet_detective`

Pet-detection mode. Upstream mower forks define PET_DETECTIVE at (4, 59).
Enables AI-based pet detection so the mower can avoid animals during mowing.
Requires camera AI (s4p22).

CORRECTION: the g2408 DOES have a camera (feature:"video_tx", Tencent XP2P —
see api_endpoints § tencent_video), so the earlier "no camera module confirmed
→ likely absent" reasoning here was stale and is retracted.
[app-mitm:2026-06-12-live-video] The presence of a camera does NOT establish
that pet-detection is a g2408 feature: s4p59 has never been seen on the g2408
wire, the app exposes a Human-Presence detection surface (REC settings) but no
observed "pet" toggle, and AI-obstacle classes captured so far are person /
patrol / obstacle. Whether s4p59 exists / does anything on g2408 stays
UNVERIFIED. [UNVERIFIED]

**Open questions:**
- Does the g2408 firmware implement a pet-detection mode at all? Camera exists, but no 'pet' toggle observed (the app surfaces Human-Presence, not pet).
- If present, does it interact with s4p22 (AI_DETECTION)?

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:706)`, `github.com/nicolasglg/dreame-mova-mower (types.py:759)`

### s4p68 — `device_snapshot_bundle`

Discovered 2026-05-06 in `cloud/dumps/dump_20260506T110907.json`
via `dreame_cloud_dump.py`'s `_PROP_PROBES` sweep. Calling
`get_properties(siid=4, piid=68)` returns a curated bundle of
multiple unrelated properties' current values rather than a
single-property value. The 2026-05-06 capture returned 8 entries:
s1p1 (heartbeat blob), s1p2 (OTA state), s1p3 (OTA progress),
s1p4 (mowing telemetry — empty list when no session), s1p5 (HW
serial), s2p1 (mode = 13 CHARGING_COMPLETED), s3p1 (battery
%), s3p2 (charging status).

This is the FIRST observed cloud-RPC-only slot (no MQTT push
observed in the probe corpus). It behaves like apk-style "bulk
device snapshot" / "loadStatus" endpoints documented in upstream
mower / vacuum code. The exact meaning of the (4, 68) coordinate
itself is unclear: it's not a property-value but an action that
happens to be invoked via `get_properties`. The bundle's
contents — heartbeat + OTA state + telemetry + serial + mode +
battery + charging — match what an "is the device alive and
what's it doing" snapshot endpoint would return.

Practical use: the integration could call this once at config-
flow init / coordinator startup to seed initial state without
waiting for the first MQTT push. That's an axis-4-style enhancement
worth considering once the response shape is confirmed across
more dumps.

**Open questions:**
- Confirm response shape across more dumps — does the bundle always carry exactly these 8 entries, or does it expand based on device state?
- Is the bundle's content static (always s1p1-5, s2p1, s3p1-2) or dynamic (e.g., includes s1p4 telemetry only during active mowing)? The 2026-05-06 capture had s1p4 empty (idle); a mowing-time capture would test this.
- Is there an aiid=68 action that takes a parameter list of (siid, piid) pairs and returns a custom bundle? The fact that get_properties accepts (4, 68) and returns multi-property data suggests so.
- Are there sibling slots s4p67 or s4p69 with similar bundle behaviour? Probe sweep can confirm.
- Capture procedure: see g2408-capture-procedures.md §7 cloud-dump cadence re-test — running the dump with --no-properties=false during different device states (idle, mowing, charging, post-FTRTS) will populate the slot's behaviour catalog.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s4p83 — `device_capability`

Device capability bitmask. Upstream mower forks define DEVICE_CAPABILITY at
(4, 83). A bitmask advertising optional feature support (camera AI, multi-map,
cruise, etc.). Useful for probing g2408 to understand which optional features
the firmware exposes without needing to test each individually.

NOTE: several capabilities this bitmask would advertise are now independently
confirmed present on g2408 — the camera (feature:"video_tx", Tencent XP2P —
see api_endpoints § tencent_video), multi-map, and patrol/cruise points
(cruisePoints type=8; o107/o108 patrol live-confirmed). So a g2408 read of
s4p83 should be non-trivial; the exact bit→feature layout is still
[UNKNOWN — to capture] (probe with a direct GET). [app-mitm:2026-06-12-live-video]

**Open questions:**
- Is s4p83 present on g2408 firmware? Probe with direct GET — value would reveal camera/AI/cruise capability flags.
- What bitmask values correspond to which features? Cross-reference with legacy DreameDeviceCapability enum.

**See also:** `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:709)`, `github.com/nicolasglg/dreame-mova-mower (types.py:762)`

### s5p104 — `slam_relocate_counter`

SLAM relocate counter. Fires exclusively alongside s2p65 = 'TASK_SLAM_RELOCATE'
bursts — three pushes in ~1 second at each relocalization start. Value has
been 7 in every capture across the probe corpus; role unclear (retry count?
relocate mode enum?).

Quiet-listed in the integration so it does not re-fire [PROTOCOL_NOVEL] on
every relocate. Surfaced as a default-disabled raw diagnostic sensor.

**Open questions:**
- 7/12 a relocate mode/result enum (fires with s2p65 relocate)? 'counter' name is doubtful (only 2 fixed values). dreame-mower potential: 'task_status'.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:131`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s5p105 — `s5p105_raw`

Small enum. Full-corpus distribution (130 pushes, 2026-04-17 → 2026-06-04):
1× steady (109), then transient 2 (13), 3 (4), 4 (3), 5 (1). Value 1 is the
steady-state; 2-5 fire transiently.

STRUCTURE (corpus-verified, see verifications): s5p105 is one member of a
periodic siid5 diagnostic frame emitted as a back-to-back burst of separate
properties_changed messages in fixed order 107 → 105 → 106 → 108 (consecutive
MQTT message ids). s5p105 and s5p107 co-fire in ALL 130 pushes; s5p106 and
s5p108 join the burst only when their own value changes (push-on-change). The
MEANING of the 1-5 enum is still unknown (POTENTIAL only). dreame-mower carries
no name (generic service5_property_105); ioBroker has none either.

Surfaced as a default-disabled raw diagnostic sensor.

**Open questions:**
- What triggers the transient values 2-5? Frame structure is known; the enum's meaning is not. Correlate non-1 values against s2p1/positioning context.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:135`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s5p106 — `s5p106_raw`

Purpose unknown. 157 observations across 5 days show values 1-8 with rare 9
(1×) and 11 (1×, 2026-04-24 14:43). Not a clean decimal or hex counter
(value 10 / 0xA never observed), and not a clean bitfield (10/12-15 also
missing).

Cadence is usually ~30 min between pushes but occasionally multi-hour gaps,
after which the jump is not monotonic (e.g. 1 at 11:12 → 11 at 14:43 → 4
at 15:13). No clear correlation with mowing state or battery; periodic
pushes fire while the mower is docked.

Surfaced as a default-disabled raw diagnostic sensor.

**Open questions:**
- GPS-satellite-count hypothesis (see verifications) — confirm by correlating s5p106 against GPS fix quality / sky obstruction. dreame-mower names it only generically (service5_property_106); the GPS name is ioBroker's.
- Leaf-cover test inconclusive (no under-tree samples in corpus; spatial pattern is a distance-from-dock gradient, not a localized dip). Needs a TARGETED capture: s5p106 under the apple-tree crown vs an adjacent open-lawn spot.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:139`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s5p107 — `energy_index`

Energy / discharge index property (upstream dreame-mower const.py:83,
comment "energy/discharge index property"). Observed range 1–250. Upstream
stores the raw int and computes energy_delta = new - old on every update.

Treat as push-on-change, not periodic. A stable load may produce no push
for tens of minutes; pushes mark transitions between discharge regimes
(entering a slope, hitting a tuft, blade-load change).

80 pushes across 4 weeks; stratified by s2p1 mode shows a load-weighted
gradient: CHARGED median 63, CHARGING 100, MOWING median 133 (n=53).
Within-MOWING range 4–246 is wide enough to encode slope/turn-rate/blade-
load. Pearson against battery-drop-rate over preceding 10 min is +0.24
(n=40) — direction-correct but noisy due to integer-quantized battery and
event-driven cadence.

Often fires alongside s5p105 / s5p106 in the same second. Surfaced as
sensor.energy_index (diagnostic, default-disabled) once flat-vs-slope
decode is confirmed.

**Open questions:**
- Does median energy_index rise on sloped lawns vs flat? User's lawn is flat — needs a sloped-lawn contributor to confirm mWh-over-interval interpretation.
- TENSION: s5p107 anchors a periodic ~30-min siid5 frame (107→105→106→108) alongside positioning-ish props. Re-examine whether 'energy_index' is right, or whether the frame is a periodic GNSS/diagnostic sample where 107 is a quality/sequence figure rather than discharge energy. Energy reading is corpus-supported (load gradient) but the periodic-frame membership wasn't known when it was decoded.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:143`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `alternatives/dreame-mower/dreame/types.py (const.py:83)`

### s5p108 — `s5p108_raw`

Rare member of the periodic siid5 diagnostic frame (see s5p105). 6 pushes
across the full corpus (2026-04-20 → 2026-06-03), values 1 (×3) and 2 (×3).
Every push rides the siid5 burst and is emitted LAST in the fixed order
107 → 105 → 106 → 108 (consecutive MQTT message ids). Because it is
push-on-change and binary-ish (1/2), it appears only when its value flips —
most frames omit it. Meaning UNKNOWN (POTENTIAL only); dreame-mower has just
a generic service5_property_108, ioBroker has no name.

**Open questions:**
- What does the 1↔2 flip mark? It is the last member of the siid5 positioning/diagnostic frame; correlate the flip against fix-quality or a positioning state change.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s6p1 — `map_data_signal`

Map-readiness signal. Cycles among {200, 201, 300} to signal "new
map available" (and possibly map-pipeline lifecycle phases).

Value 300 fires at auto-recharge-leg-start (the exact millisecond
s2p2 → 54 and s2p1 → 2 → 5), confirmed twice in the 2026-04-20
full-run at 09:14:09 and 11:13:04. Primary mid-session "map may
have been refreshed" signal; triggers the upstream map pipeline.

NOT a session-completion signal — that is the event_occured
siid=4 eiid=1. The 2026-04-20 run produced two s6p1=300 pushes
(one per recharge interrupt) plus one event_occured.

Value 200 observed during normal mowing states.
Value 201 first observed 2026-05-15 12:18:49 — semantic unknown;
possibly an intermediate map-state phase or a per-firmware-build
variant of 200. Worth capturing more occurrences with surrounding
context to decode.

Surfaced as s6p1_raw diagnostic sensor.

**Open questions:**
- Does s6p1 fire at any session-interrupt OTHER than low-battery and rain (e.g., emergency stop, top-cover-open, fault recovery)? The corpus we have hasn't captured those — likely sparse observations.
- Are there s6p1 values beyond {200, 201, 300}? value_catalog might be larger; capture novel observations into a persistent log (see project-persistent-novel-log-todo) to find out.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:147`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### s6p2 — `frame_info`

FRAME_INFO / Mowing Settings page save reflector. Per-active-map on
g2408 (verified 2026-05-14). Four-element list; three of four elements
decoded:

[0] = Mowing Height in millimetres — observed 70→60→50 while user stepped
app slider 7.0cm→6.0cm→5.0cm. Range 30-70mm in 5mm steps (matches app's
3-7cm in 0.5cm increments). Surfaced as sensor.mowing_height (cm).

[1] = Mowing Efficiency — 0=Standard, 1=Efficient. Surfaced as
sensor.mow_mode.

[2] = EdgeMaster — bool. False/True. Toggles cleanly per save.
Surfaced as switch.edgemaster (parent, active-map only) and
switch.map_N_edgemaster (per-map, preferred).

[3] = Unknown — usually 2, but NOT strictly constant. One outlier of
198 observed 2026-05-10 17:04:16 during a mid-mow efficiency change
(`[60, 0, True, 198]`). Earlier ruled out as Safe Edge Mowing,
Automatic Edge Mowing, Mowing Direction, Obstacle Avoidance on
Edges, LiDAR Obstacle Recognition, or its sub-setting. Meaning
still unknown; the 198 outlier suggests a mid-session status flag.

Per-map emission rule: every Save-button press in the Dreame app's
Mowing Settings emits s6p2, regardless of whether the value
changed (verified 2026-05-14 via 3 noop saves at 21:08, all
emitted identical `[60, 0, True, 2]`). The "silent" path is "no
save happened" (user dismissed the unsaved-changes warning).
Switching maps does NOT itself emit s6p2 — the next save on the
new map reflects that map's stored values.

**Open questions:**
- What is byte[3]? Usually 2, one 198 outlier — possibly a mid-session status flag or schema/frame-type marker. Needs more samples around mid-mow setting changes.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:110`, `docs/research/g2408-protocol.md § s6.2`

### s6p3 — `wifi_signal_push`

WiFi signal push on g2408: [cloud_connected, rssi_dbm]. NOT the OSS object
key that upstream calls OBJECT_NAME — upstream's slot is unused on g2408
(the session-summary key arrives via event_occured instead, see §7.4).

The integration's overlay remaps OBJECT_NAME to 999/998 so the map handler
does not misinterpret s6p3 pushes as map-object-name strings.

cloud_connected (bool): true if the mower has an active cloud connection.
rssi_dbm (int): WiFi RSSI in dBm. The live s1p1 byte[17] RSSI value takes
over after startup; s6p3 seeds the initial rssi_dbm value.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:112`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s6p117 — `dock_nav_state`

Dock-nav state marker. Confirmed 2026-05-05 as a dock-navigation state
marker that fires at the start of explicit TASK_NAV_DOCK phases, paired
with s2p65 = 'TASK_NAV_DOCK' in the same second.

Three captures: (a) 2026-04-24 13:30:14 value 1 after mowing-complete +
stuck-on-garden-hose situation. (b) 2026-05-05 08:59:03 transition ?→1
paired with TASK_NAV_DOCK after run 1's FTRTS-then-retry path. (c)
2026-05-05 09:24:02 transition 3→1 paired with TASK_NAV_DOCK after run 2's
FTRTS.

Pattern: fires only on the explicit dock-nav retry path that follows an
FTRTS bounce — not on clean autonomous returns where s2p1: 5→6 happens
directly. Hypothesis: s6p117 is a dock-nav sub-state counter; 1 = "active
dock-approach", 3 = some earlier state (relocate? planning? not always
observed because the property only pushes on transition).

Suppressed in coordinator via _SUPPRESSED_SLOTS (no NOVEL warnings while
semantics are being confirmed).

**Open questions:**
- What does value 3 represent? Not always observed at the start of TASK_NAV_DOCK — may be a prior-state read.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Properties`

### s99p20 — `lidar_object_name`

LiDAR point-cloud OSS object key. Published by the mower each time the user
taps "View LiDAR Map" in the Dreame app and the current scan differs from
the last-uploaded one. Arrives BEFORE s2p54 = 100 (at 61% progress in the
observed capture).

Key format: ali_dreame/YYYY/MM/DD/<master-uid>/<did>_HHMMSSmmm.MMMM.bin
Example: "ali_dreame/2026/04/20/BM16nnnn/-11229nnnn_154157120.0550.bin"

The integration's _handle_lidar_object_name fetches the binary blob via
cloud.get_interim_file_url (getDownloadUrl endpoint) → OSS signed URL →
HTTP GET → writes to LidarArchive under
<config>/dreame_a2_mower/lidar/YYYY-MM-DD_<ts>_<md5>.pcd.
Content-addressed by md5; re-tapping the same scan is a no-op.

PULL-BASED ALTERNATIVE (2026-05-31): these exact objects are also listed by
the OBJ routed action `s2.50 m='g' t='OBJ' d={type:'3dmap'}` → {out:[{d:
{name:[<obj>,...]}}]}, newest-first. Confirmed identical: s99.20 announced
04-19/04-20/05-10; the 3dmap list returned 04-20+05-10 (newest ~2; 04-19
had aged out); fetching the 05-10 object yields a `# .PCD v0.7` point cloud
(831 KB). So `3dmap` == the s99.20 LiDAR PCDs. The s99.20 MQTT push is the
primary (free, rides the stream we already consume); the 3dmap OBJ list is
a backfill option — limited retention (newest ~2) and via the 80001-flaky
relay, so NOT a full archive. WIRED 2026-05-31: cloud_client.list_3dmap_objects()
+ coordinator._backfill_lidar_from_3dmap() run once per session from
_refresh_cloud_state (after _apply_mapl), fetching any 3dmap object not already
archived (dedup by object_name → no re-download) into the active map's
LidarArchive. Relay 80001 leaves it unretried-this-cycle and the next refresh
tries again; the live s99.20 push remains the primary source for new scans.

**Open questions:**
- Default-render-densest-vs-newest UX: integration renders latest-by-timestamp (05/10, 51932 pts); the Dreame app showed the older denser scan (04/20, 153261 pts). Should the integration offer a 'densest scan' picker or always show latest? [UX decision — Phase 2].

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:125`, `docs/research/inventory/generated/g2408-canonical.md § Events`, `apk: ioBroker.dreame/apk.md §MQTT Property Subscriptions SIID 99 piid:20`

## Events

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| event_s4eiid1 | session_complete | list of {piid, value} args | WIRED |  |

### event_s4eiid1 — `session_complete`

Fires once per completed (or user-aborted) mowing session. Distinct from
the properties_changed MQTT method — this arrives as event_occured with
siid=4 eiid=1.

piid 9 carries the session-summary OSS object key (.json file). The
integration keys off piid 9 to fetch and archive the full session summary.

Key piids observed across 6 captures (2026-04-17..2026-04-20, including
one user-cancel): piid 1 (always 100), piid 2 (end-code enum: 31/36/69/
128/170/195/217; 36=user-cancel), piid 3 (area mowed × 100 in centiares),
piid 7 (stop-reason: 1=natural, 3=user-cancel), piid 8 (unix session-start
timestamp), piid 9 (OSS key), piid 11 (0 or 1), piid 60 (-1 normal, 101
user-cancel), piid 13 (always []), piid 14 (total mowable lawn area m²
rounded int), piid 15 (always 0).

See docs/research/inventory/generated/g2408-canonical.md § Events for the full piid catalog and
§7.5 for the OSS fetch flow. A one-shot [PROTOCOL_NOVEL] WARNING fires the
first time a new piid appears in the arguments list.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`, `apk: ioBroker.dreame/apk.md §MAP Daten userData Keys`

## Actions

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1a3 | reset_lensbrush |  | APK-KNOWN |  |
| s4a3 | suppress_fault |  | WIRED |  |
| s5a1 | start_mowing |  | WIRED |  |
| s5a1_zone | start_zone_mow |  | WIRED |  |
| s5a1_edge | start_edge_mow |  | WIRED |  |
| s5a1_spot | start_spot_mow |  | WIRED |  |
| s5a2 | stop |  | WIRED |  |
| s5a3 | dock |  | WIRED |  |
| s5a4 | pause |  | WIRED |  |
| s7a1 | find_bot |  | WIRED |  |
| s9a1 | reset_blades |  | APK-KNOWN |  |
| s10a1 | reset_side_brush |  | APK-KNOWN |  |
| s11a1 | reset_filter |  | APK-KNOWN |  |
| s16a1 | reset_sensor |  | APK-KNOWN |  |
| s17a1 | reset_tank_filter |  | APK-KNOWN |  |
| s19a1 | reset_silver_ion |  | APK-KNOWN |  |
| s24a1 | reset_squeegee |  | APK-KNOWN |  |
| cfg_write_cls | lock_bot_toggle |  | WIRED |  |
| local_only_finalize | finalize_session |  | WIRED |  |

### s1a3 — `reset_lensbrush`

Reset the Lens Brush wear counter. From legacy DreameMowerActionMapping
RESET_LENSBRUSH (types.py:831). Note: the worklist incorrectly listed
this as (s27, a1); the canonical legacy mapping is {siid:1, aiid:3}.
Lens brush is a camera-cleaning accessory on vacuums; unclear whether
g2408 uses this siid/aiid pair for any mower accessory.

**Open questions:**
- Does action(1,3) apply to g2408? siid:1 is the heartbeat/telemetry service — aiid:3 on siid:1 is unusual. Verify legacy mapping is not a typo.

**See also:** `apk: ioBroker.dreame/apk.md §siid:1 aiid:3`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:831)`

### s4a3 — `suppress_fault`

Suppress / clear the current active fault or warning. Wired via routed
action s2a50 with o:11 (suppressFault opcode). Verified in legacy
DreameMowerActionMapping as CLEAR_WARNING (types.py:813).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:237`, `apk: ioBroker.dreame/apk.md §Actions o:11 suppressFault`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:813)`

### s5a1 — `start_mowing`

Trigger a global all-area mowing run. On g2408 the direct action(siid=5,
aiid=1) call returns 80001 ("device unreachable"); the working path is
the routed action siid=2 aiid=50 {m:'a', o:100, t:'TASK'}.

The same (siid=5, aiid=1) wire entry is shared by START_ZONE_MOW
(o:102), START_EDGE_MOW (o:101), and START_SPOT_MOW (o:103) — they
differ only in the routed_o opcode and the payload. See opcodes o100,
o101, o102, o103 for the respective TASK envelope shapes.

**Open questions:**
- Direct action(5,1) consistently returns 80001; routed path via s2a50 o:100 is the confirmed working path.
- task-variant-params: Capture app TASK starts (all-areas o=100 / edge o=101 / zone o=102 / pause / resume / dock o=6 / stop) to confirm params vs our builders [UNKNOWN — to capture].

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:195`, `apk: ioBroker.dreame/apk.md §Actions o:100 globalMower`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a1_zone — `start_zone_mow`

Zone-specific mowing run. Same (siid=5, aiid=1) wire entry as
start_mowing but dispatched via routed action s2a50 with o:102 and
payload {m:'a', p:0, o:102, d:{region:[zone_ids]}}.

zone_ids are scalar ints from MAP.*.mowingAreas.value. Alias
START_ZONE_MOW in MowerAction enum. Routed-action opcode see o102.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:199`, `apk: ioBroker.dreame/apk.md §Actions o:102 zoneMower`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a1_edge — `start_edge_mow`

Edge-mowing-only run (perimeter tracing). Same (siid=5, aiid=1) wire
entry dispatched via routed action s2a50 with o:101 and payload
{m:'a', p:0, o:101, d:{edge:[[map_id, contour_id], ...]}}.

Critical: d.edge must NOT be empty — the firmware interprets [] as
"every contour including merged sub-zone seams", draining the edge
budget on internal boundaries and causing wheel-bind → FTRTS. The app
sends explicit [[1, 0], ...] pairs (outer perimeter only). The
integration's _edge_mow_payload() enforces [[1,0]] as last-resort
fallback and prefers contour_ids populated from cached map data.

See docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes for the full failure-mode
write-up (2026-05-05, three live captures).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:204`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §Actions o:101 edgeMower`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a1_spot — `start_spot_mow`

Spot mowing run on defined spot areas. Same (siid=5, aiid=1) wire
entry dispatched via routed action s2a50 with o:103 and payload
{m:'a', p:0, o:103, d:{area:[spot_ids]}}.

spot_ids from MAP.*.spotAreas.value. Confirmed end-to-end live
2026-04-29 (per project memory). Echo: {area_id:[N], exe:T,
o:103, region_id:[], status:T, time:N}.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:209`, `apk: ioBroker.dreame/apk.md §Actions o:103 spotMower`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:808)`

### s5a2 — `stop`

Stop the current mowing run (without returning to dock). Verified in
legacy DreameMowerActionMapping (types.py:811). On g2408, direct
action returns 80001; routed path is the fallback.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:222`, `apk: ioBroker.dreame/apk.md §Actions o:3 stopControl`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:811)`

### s5a3 — `dock`

Send the mower back to the docking station (charge). Also used as
RECHARGE (alias for DOCK with the explicit "head to charger now"
semantic). Verified in legacy DreameMowerActionMapping (types.py:810).
On g2408, direct action returns 80001; routed path is the fallback.
Expected s2p1 transition: any → RETURNING → CHARGING.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:220`, `apk: ioBroker.dreame/apk.md §Actions o:7 stopBackCharge`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:810)`

### s5a4 — `pause`

Pause the current mowing run in-place. Verified in legacy
DreameMowerActionMapping (types.py:809). On g2408, direct action
returns 80001; the integration retries via routed action if needed.
Expected s2p1 transition: WORKING → PAUSED.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:219`, `apk: ioBroker.dreame/apk.md §Actions o:4 pauseControl`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:809)`

### s7a1 — `find_bot`

Trigger the "Find My Mower" beep/LED sequence on the robot. Wired via
routed action s2a50 with o:9 (findBot opcode). Verified in legacy
DreameMowerActionMapping as LOCATE (types.py:821). On g2408, the
routed path (o:9) is the working channel.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:225`, `apk: ioBroker.dreame/apk.md §Actions o:9 findBot`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:821)`

### s9a1 — `reset_blades`

Reset the Blades wear counter. From legacy DreameMowerActionMapping
RESET_BLADES (types.py:825). The g2408 CMS[0] tracks blade wear
(confirmed); whether sending this action resets CMS[0] on g2408
firmware is unconfirmed. Vacuum-derived — vacuum blades vs mower
blades may differ in firmware handler.

**Open questions:**
- Does action(9,1) reset CMS[0] (blade_min) on g2408? Needs live test.

**See also:** `apk: ioBroker.dreame/apk.md §siid:9 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:825)`

### s10a1 — `reset_side_brush`

Reset the Side Brush wear counter. From legacy DreameMowerActionMapping
RESET_SIDE_BRUSH (types.py:826). Side brush is a vacuum accessory; the
g2408 mower equivalent is the Cleaning Brush (CMS[1]). Whether
action(10,1) resets CMS[1] on g2408 is unconfirmed.

**Open questions:**
- Does action(10,1) reset CMS[1] (brush_min) on g2408? Needs live test.

**See also:** `apk: ioBroker.dreame/apk.md §siid:10 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:826)`

### s11a1 — `reset_filter`

Reset the Filter wear counter. From legacy DreameMowerActionMapping
RESET_FILTER (types.py:827). Filter is vacuum-specific; unclear whether
g2408 has a filter or which CMS slot this would reset.

**Open questions:**
- Does action(11,1) apply to g2408? No matching CMS slot identified.

**See also:** `apk: ioBroker.dreame/apk.md §siid:11 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:827)`

### s16a1 — `reset_sensor`

Reset the Sensor dirty-life counter. From legacy DreameMowerActionMapping
RESET_SENSOR (types.py:828). Sensor cleaning is a vacuum maintenance
item; whether g2408 exposes a sensor-dirty counter is unknown.

**Open questions:**
- Does action(16,1) apply to g2408? No sensor-dirty CMS slot confirmed.

**See also:** `apk: ioBroker.dreame/apk.md §siid:16 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:828)`

### s17a1 — `reset_tank_filter`

Reset the Tank Filter wear counter. From legacy DreameMowerActionMapping
RESET_TANK_FILTER (types.py:829). Tank filter is a vacuum/mop accessory;
g2408 has no tank/mop hardware.

**Open questions:**
- Does action(17,1) apply to g2408? g2408 has no tank/mop hardware.

**See also:** `apk: ioBroker.dreame/apk.md §siid:17 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:829)`

### s19a1 — `reset_silver_ion`

Reset the Silver Ion filter wear counter. From legacy
DreameMowerActionMapping RESET_SILVER_ION (types.py:830). Silver ion
filter is a vacuum/mop accessory; g2408 has no such accessory.

**Open questions:**
- Does action(19,1) apply to g2408? Silver ion is vacuum-only accessory.

**See also:** `apk: ioBroker.dreame/apk.md §siid:19 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:830)`

### s24a1 — `reset_squeegee`

Reset the Squeegee wear counter. From legacy DreameMowerActionMapping
RESET_SQUEEGEE (types.py:832). Squeegee is a mop/vacuum accessory;
g2408 has no squeegee.

**Open questions:**
- Does action(24,1) apply to g2408? g2408 has no squeegee.

**See also:** `apk: ioBroker.dreame/apk.md §siid:24 aiid:1`, `github.com/okolbu/ha-dreame-a2-mower-legacy (types.py:832)`

### cfg_write_cls — `lock_bot_toggle`

Toggle the child lock (mower panel lockout). No (siid, aiid) entry in
legacy or greenfield; CHILD_LOCK is a property write, not an action
call. The integration dispatches LOCK_BOT_TOGGLE via coordinator
write_setting("CLS", toggled_value) using the cfg_toggle_field
mechanism. Reads the current child_lock_enabled from coordinator.data,
computes not bool(current), and calls write_setting("CLS", toggled).
Confirmed g2408: CLS is the authoritative child-lock setting
(docs/research/inventory/generated/g2408-canonical.md § CFG keys).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:231`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`

### local_only_finalize — `finalize_session`

Integration-internal action; no cloud call is ever issued. The
dispatch_action local_only branch calls _run_finalize_incomplete()
(F5.10.1) to close out any session that ended without a clean
event_occured signal (e.g. session ended during HA restart).
local_only: true in the ActionEntry — the cloud-action path is
never reached.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:242`

## Routed-action opcodes

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| o_minus_1 | error_abort | {m:'a', d:{o:-1, status:true, exe:true}, t:'TASK'} | WIRED |  |
| o0 | reset_control | {m:'a', o:0} | APK-KNOWN |  |
| o2 | joystick_start | {m:'a', o:2} | APK-KNOWN |  |
| o3 | stop_end | SEND {m:'a', o:3} (app); ECHO {m:'a', d:{o:3}, t:'TASK'} (device → cloud) | WIRED |  |
| o4 | pause | SEND {m:'a', o:4} (app); no echo payload | APK-KNOWN |  |
| o5 | resume | SEND {m:'a', o:5} (app); no echo payload | APK-KNOWN |  |
| o6 | recharge_dock | SEND {m:'a', o:6} (app); ECHO {m:'a', d:{o:6}, t:'TASK'} (device → cloud) | WIRED |  |
| o7 | joystick_stop_back | {m:'a', o:7} | APK-KNOWN |  |
| o8 | set_ota | {m:'a', o:8, d:{...}} | APK-KNOWN |  |
| o9 | find_bot | SEND {m:'a', o:9} (app and integration); no echo observed | WIRED |  |
| o10 | upload_map (apk) / generate_3dmap (integration) — UNRESOLVED | {m:'a', o:10, d:{idx:<map_index>}} | WIRED |  |
| o11 | suppress_fault | {m:'a', o:11} | WIRED |  |
| o12 | lock_bot | {m:'a', o:12, d:{lock: 0|1}} | APK-KNOWN |  |
| o13 | cancel_dock_return | SEND {m:'a', o:13} (app); no echo observed | APK-KNOWN |  |
| o15 | remote_setting | {m:'a', p:0, o:15, d:{c: 0|1} | {h: height*10}} | SEEN-UNDECODED |  |
| o100 | global_mower | SEND {m:'a', o:100, d:{need_bp}} (app); ECHO {area_id:N, exe:T, o:100, region_id:[1], time:N, t:'TASK'} (flat-field, not wrapped in d:{}) | WIRED |  |
| o101 | edge_mower | SEND {m:'a', o:101, d:{edge:[[map_id, contour_id], ...]}} (app and integration) | WIRED |  |
| o102 | zone_mower | SEND {m:'a', o:102, d:{region:[zone_id, ...]}} (app and integration) | WIRED |  |
| o103 | spot_mower | SEND {m:'a', o:103, d:{area:[spot_id, ...]}} (app and integration) | WIRED |  |
| o104 | plan_mower | {m:'a', o:104, d:{...}} | APK-KNOWN |  |
| o105 | obstacle_mower | {m:'a', o:105, d:{...}} | APK-KNOWN |  |
| o107 | start_cruise_point | SEND {m:'a', o:107, d:{point:[cruisePointId, ...]}} (app and integration — confirmed live 2026-06-04); ECHO s2p50 {o:107, exe:true, status:true, error:0, estimate_time:N, time:T, t:'TASK'} | DECODED-UNWIRED |  |
| o108 | start_cruise_side | SEND {m:'a', o:108, d:{edge:[[m,c]]}} (contour pairs, CONFIRMED LIVE 2026-06-04); ECHO s2p50 {o:108, exe:true, status:true, t:'TASK'} | DECODED-UNWIRED |  |
| o109 | start_clean_point | SEND {m:'a', p:0, o:109, d:{point:[point_id]}} via routed_action; ECHO s2p50 {o:109, exe:true, status:true|false, [estimate_time, time]} | WIRED |  |
| o110 | start_learning_map | {m:'a', o:110} | APK-KNOWN |  |
| o111 | set_cruise_point_cycles | SEND {m:'a', o:111, d:{point:[point_id, cycles]}} | SEEN-UNDECODED |  |
| o200 | select_map | SEND {m:'a', o:200, d:{idx:N}} (app — confirmed 2026-06-09); ECHO {d:{exe:true, o:200, status:true}, t:'TASK'} | DECODED-UNWIRED |  |
| o201 | map_edit_commit | SEND {m:'a', o:201} (app — confirmed 2026-06-09); ECHO {m:'a', d:{o:201, status:true, error:0}, t:'TASK'} (device → cloud) | WIRED |  |
| o204 | map_edit_begin | SEND {m:'a', o:204} (app — confirmed 2026-06-09); ECHO {m:'a', d:{o:204, exe:T, status:T, ...}, t:'TASK'} (device → cloud) | WIRED |  |
| o205 | clear_map | {m:'a', o:205} | APK-KNOWN |  |
| o206 | expand_map | {m:'a', o:206} | APK-KNOWN |  |
| o208 | full_state_backup | SEND {m:'a', o:208, d:{idx:N}} (app — confirmed 2026-06-09) | APK-KNOWN |  |
| o214 | edit_spot | SEND {m:'a', o:214, d:{id:N, points:[[x,y],[x,y],[x,y],[x,y]]}} (app — confirmed 2026-06-12); commit via o:201 | DECODED-UNWIRED |  |
| o215 | add_no_go_zone | SEND {m:'a', o:215, d:{id:N, type:T, points:[...], radius:R}} (app — confirmed 2026-06-09); ECHO {m:'a', d:{o:215, id:N, ids:[...], exe:T, status:T}, t:'TASK'} | WIRED |  |
| o218 | delete_map_object | SEND {m:'a', o:218, d:{id:N, type:T}} (app — confirmed 2026-06-09); ECHO {m:'a', d:{o:218, id:N, ids:[], exe:T, status:T}, t:'TASK'} | WIRED |  |
| o219 | rename_zone | SEND {m:'a', o:219, d:{region:N, name:'...'}} (app — confirmed 2026-06-09) | APK-KNOWN |  |
| o220 | split_zone | SEND {m:'a', o:220, d:{id:N, line_start:{x,y}, line_end:{x,y}}} (app — confirmed 2026-06-09) | APK-KNOWN |  |
| o221 | merge_zones | SEND {m:'a', o:221, d:{ids:[N, ...]}} (app — confirmed 2026-06-09) | APK-KNOWN |  |
| o223 | edit_patrol_point | SEND {m:'a', o:223, d:{id:N, points:[x, y, heading]}} (app — confirmed 2026-06-15); commit via o:201 | DECODED-UNWIRED |  |
| o224 | edit_maintenance_point | SEND {m:'a', o:224, d:{id:N, points:[x, y, heading]}} (app — confirmed 2026-06-12); commit via o:201 | DECODED-UNWIRED |  |
| o234 | add_ignore_obstacle_zone | SEND {m:'a', o:234, d:{id:-1, type:0, points:[...]}} (app — confirmed 2026-06-09); ECHO {m:'a', d:{o:234, id:N, ids:[], exe:T, status:T}, t:'TASK'} | WIRED |  |
| o400 | camera_live_view | SEND {m:'a', o:400, d:{on:0|1}} (app — confirmed 2026-06-09) | APK-KNOWN |  |
| o401 | take_pic | {m:'a', o:401} | WIRED |  |
| o503 | cutter_bias | {m:'a', o:503, d:{...}} | APK-KNOWN |  |

### o_minus_1 — `error_abort`

Error abort / teardown cleanup marker. Fires on s2p50 immediately
after a failed task (typically paired with o:109 task-start-failed).
status=true indicates the cleanup is complete; no id/ids fields.
Firmware-idiomatic for "no specific op — this is a cleanup marker".

Observed 2026-04-20 19:34:20 immediately after an o:109 task-start
failure: mower emits s2p50 o:109 status:false, then 0 ms later
s2p50 o:-1 status:true (abort ack).

Also fires as teardown for map-edit sequences (§2.1): o:204 → o:234
(or o:215/o:218) → o:201 → o:-1.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §Actions o:-1 error abort`

### o0 — `reset_control`

Joystick reset — resets the manual joystick control state. Apk-
documented (ioBroker cross-reference §action operations). Not observed
on g2408 wire; likely only used during manual-control / BT joystick
sessions.

**Open questions:**
- Confirm g2408 responds to o:0 in any reachable state.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o2 — `joystick_start`

Joystick control — start moving. Part of the o:2–7 manual joystick
control group (start/stop/pause/continue/pauseBack/stopBack). Apk-
documented; not observed on g2408 wire.

**Open questions:**
- Confirm joystick opcodes 2-7 work on g2408 via cloud (vs BT-only).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o3 — `stop_end`

End / stop the current task. [app-mitm:2026-06-09-settings-sweep] The
app sends this as a routed action (s2a50 {m:'a', o:3}) with no payload to
stop an active session. Firmware echoes it on s2p50 when the user hits
Cancel / Stop, firing ~1 s after s2p2=48. Does not carry id/ids.

The integration sends o:3 (End/Stop) via the routed path
(ACTION_TABLE[MowerAction.STOP].routed_o=3) as of Phase B; the prior
direct action(siid=5,aiid=2) path returned 80001 on g2408.
[app-mitm:2026-06-09-settings-sweep] The o:3 s2p50 echo appears
regardless of which path the sender used.

Also listed in apk as joystick "stop" (o:2–7 group); in s2p50 echo
context it is the canonical "user-cancel" / stop marker.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §Actions o:3 stopControl`

### o4 — `pause`

Pause the current mowing session. [app-mitm:2026-06-09-settings-sweep]
The app sends this as a routed action (s2a50 {m:'a', o:4}) with no
payload to pause an active mow. DISTINCT from stop (o:3) — pause
preserves session state so the mower can resume; stop ends the task.

The integration sends o:4 (Pause) via the routed path
(ACTION_TABLE[MowerAction.PAUSE].routed_o=4) as of Phase B; the prior
direct action(siid=5,aiid=4) path returned 80001 on g2408.
[app-mitm:2026-06-09-settings-sweep]

Previously noted as "joystick control — pause" (part of the o:2–7 group).
The app-mitm sweep confirms this is the primary PAUSE command for all
session types, not only joystick sessions. Whether o:4 echoes on s2p50
is not yet observed on the g2408 wire. [UNKNOWN — to capture]

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o5 — `resume`

Resume a paused mowing session. [app-mitm:2026-06-09-settings-sweep]
The app sends this as a routed action (s2a50 {m:'a', o:5}) with no
payload to resume after a pause (o:4). Counterpart to o:4 pause.

The integration sends o:5 (Resume/continue a paused mow) via
ACTION_TABLE[MowerAction.RESUME].routed_o=5 as of Phase B (exposed as
the Resume button), distinct from START_MOWING (o=100).
[app-mitm:2026-06-09-settings-sweep] Whether o:5 echoes on s2p50 is
not yet observed. [UNKNOWN — to capture]

Previously noted as "joystick control — continue / resume" (part of the
o:2–7 group). App-mitm confirms this is the general RESUME command.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o6 — `recharge_dock`

Send mower home / recharge / dock. [app-mitm:2026-06-09-settings-sweep]
The app sends this as a routed action (s2a50 {m:'a', o:6}) with no
payload to command the mower to return to the dock.

Echo is unreliable: confirmed on s2p50 at 2026-04-20 18:09:56, 18:25:57,
04-27 10:12:18, 04-29 20:47:18, but on 2026-05-05 09:24 a confirmed app
Recharge that successfully drove the mower home fired zero o:6 echo. The
cloud occasionally drops this delivery.

Detection of Recharge should lean on s2p1: ?→5→6 plus s3p2→1, NOT on
the s2p50 o:6 echo.

The integration sends o:6 (Recharge/return-to-dock) via the routed path
(ACTION_TABLE[MowerAction.DOCK / RECHARGE].routed_o=6) as of Phase B;
the prior direct action(siid=5,aiid=3) path returned 80001 on g2408.
[app-mitm:2026-06-09-settings-sweep]

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §Actions o:6 pauseBackCharge`

### o7 — `joystick_stop_back`

Joystick control — stopBack. Part of the o:2–7 manual joystick control
group. Apk-documented; not observed on g2408 wire.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o8 — `set_ota`

Trigger OTA (over-the-air firmware update). Apk-documented; not observed
on g2408 wire. Expected to carry OTA metadata in d field.

**Open questions:**
- What is the d-field payload shape for OTA? Apk source needed.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o9 — `find_bot`

Find My Mower / locate — triggers audible beep and/or LED flash on the
robot. [app-mitm:2026-06-09-settings-sweep] The app sends this as a
routed action (s2a50 {m:'a', o:9}) with no payload. The integration also
uses o:9 via routed_action (MowerAction.FIND_BOT → ACTION_TABLE routed_o=9).
Apk-documented as findBot. No echo observed on s2p50 — command is
fire-and-forget.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:225`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o10 — `upload_map (apk) / generate_3dmap (integration) — UNRESOLVED`

NAME/SEMANTIC UNRESOLVED, untested on g2408. This row reads the apk opcode
as uploadMap (trigger map upload to cloud). The integration, however, maps
MowerAction.GENERATE_3D_MAP → routed_o=10 with d={idx:0} (the
DreameA2Generate3DMapButton), per the integration author's apk reading
("generate 3D map") — directly conflicting with this row's "uploadMap"
reading of the SAME opcode. One of the two apk readings is wrong; not
observed on the g2408 wire either way. [UNKNOWN — to capture] Resolve with a
live press while docked: a s2p54 3dmap-progress push + a new 3dmap OSS object
⇒ generate-3dmap; nothing (or an upload-only effect) ⇒ uploadMap. The
generate_3dmap button is bucket B (device_write_unproven) for exactly this
reason.

LIVE-TESTED 2026-06-08 (docked-idle): op=10 {idx:0} via routed_action is
ACCEPTED — cloud reply {code:0, out:[{m:'r', r:0}], siid:2}, r=0 on two
sends, relay awake (fetch_cfg OK). This is categorically unlike CFG.PRE
(r=-3 hard-reject). BUT it produced NO new 3dmap OSS object: list_3dmap_objects()
was identical before and 150 s after (2 objects, 2026/04/20 + 2026/05/10
.0550.bin — matching the only two LiDAR maps in ~2 months of running). So
op=10 on g2408 is ACCEPTED-BUT-NO-EFFECT (same class as lock_robot op=12),
NOT an on-demand 3D-map generator. 3D-map rendering is firmware-gated on
internal conditions (enough map change / completed mow) — there is no
user-facing trigger in the Dreame app either (no "generate map" button, just
a 3D-view page). The "generate-3dmap" decision branch (new object ⇒ generate)
is DISPROVEN for on-demand use; the apk name (uploadMap vs generate-3dmap)
stays ambiguous, but on-demand generate-3dmap is ruled out. The button was
reclassed _U → _N (read_only_noop) in Phase 2.1 (2026-06-14) now that the
accepted-but-no-effect behaviour is confirmed — see entity-inventory
button.generate_3dmap.

**Open questions:**
- apk NAME of op=10 (uploadMap vs generate-3dmap) stays ambiguous, but on-demand 3D-map GENERATION via op=10 is DISPROVEN (live 2026-06-08: accepted r=0, no new 3dmap object). What ACTUALLY triggers a 3dmap render on g2408 (the 2 existing maps are 2026-04-20 + 2026-05-10) is still unknown — likely an internal 'enough map change' / post-mow firmware condition, not a callable action. The real upload flow is the s2p54-progress(0→100) → s99p20(object-name at ~61%) → s2p54=100 sequence (see s2p54 entry); it has fired 0 times in the current 19-day capture (last snapshot 05-10).
- [UNVERIFIED] 2026-06-08: user removed a map exclusion zone; mower began re-mapping; a DENSER 3D point cloud (incl. the newly-un-excluded area) appeared in BOTH the phone app AND a cloud-only iPad app instance — i.e. cloud-resident — yet list_3dmap_objects() (t='3dmap' OBJ) still returned only the 2 old snapshots and NO s2p54/s99p20 fired in our capture. Leading hypothesis: the apps render the continuously cloud-synced WORKING/SLAM map (mapl), which reflects live remapping, while the persistent .0550.bin 3D snapshots only refresh on the periodic s2p54→s99p20 upload. So our integration's 2D map (mapl) should already show the new area, but the LiDAR camera (OSS snapshot) lags until the next snapshot uploads. CAPTURE NEXT: watch for the next s2p54 climb→s99p20 push (the integration auto-ingests it) to confirm the snapshot then matches the apps; and identify whether the app's live 3D view pulls a current-map cloud surface distinct from the t='3dmap' OBJ snapshot list.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:261`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o11 — `suppress_fault`

Suppress / clear the current active fault or warning. Used by the
integration's SUPPRESS_FAULT action via routed action s2a50. Apk-
documented as suppressFault.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:237`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o12 — `lock_bot`

Lock the mower (panel child lock). Apk-documented as lockBot. The
integration dispatches child-lock via CFG write ("CLS") rather than
this opcode; this opcode may be an alternative channel or app-only path.

**Open questions:**
- Does o:12 work in parallel with CFG.CLS write, or is one canonical?
- [UNKNOWN — to capture] No lock/unlock button exists in the current Dreame app UI for this device; the backend MAY add support later. On current g2408 firmware op=12 is ACCEPTED-BUT-NO-EFFECT (same class as op=10; no panel-lock observed, no echo on s2p50). Integration lock_bot entity stays DEVICE_WRITE_UNPROVEN. Capture step: watch for a future app lock control or backend flag that enables it.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o13 — `cancel_dock_return`

Cancel an in-progress dock-return (end returning to station).
[app-mitm:2026-06-09-settings-sweep] The app sends this as a routed
action (s2a50 {m:'a', o:13}) with no payload when the user taps to
cancel a return-to-dock in progress.

DISTINCT from stop (o:3): o:3 ends an active MOWING session; o:13
specifically cancels the dock-return leg (the mower is already heading
home but the user wants it to stop en route). Whether it echoes on
s2p50 is not yet observed. [UNKNOWN — to capture]

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o15 — `remote_setting`

Remote-control settings push. Apk-documented at L175109-175121 as
remoteSetting. Sent during a joystick-control session to adjust mower
parameters without stopping the joystick stream. Two observed d-field
shapes:
  - {c: 0|1}        — camera on/off during remote control
  - {h: height*10}  — cutting height in mm ×10 (e.g., 50mm → h:500)

Sent via BLE+IOT channel (not BLE-only like joystick data). Must be
sent while an active joystick session is running (between o:2 start
and o:3 stop). Not a standalone configuration path — only valid in
remote-control context.

NOW OBSERVED on g2408 (2026-05-30): op=15 also appears as an s2p50 TASK
envelope {exe:true, o:15, status:true} at the START of a manual/remote-control
session — distinct from the apk's d:{c}/{h} remoteSetting adjust. It is the
manual-drive START marker (see verification). The integration still does not
implement joystick driving.

**Open questions:**
- Are c and h the only sub-parameters, or can other fields be passed?
- Does op=15 reliably echo for every manual-drive start, or only sometimes (like other app-triggered ops)?

**See also:** `apk: ioBroker.dreame/apk.md §Remote Control remoteSetting L175109`

### o100 — `global_mower`

Start / all-area mow. [app-mitm:2026-06-09-settings-sweep] The app
sends routed action s2a50 {m:'a', o:100, d:{need_bp}} where need_bp
controls whether a boundary pre-pass is required before mowing.
The integration sends {m:'a', o:100} (no d field) for START_MOWING
via ACTION_TABLE; the need_bp field is app-specific. Apk-documented
as globalMower.

Observed as a flat-field s2p50 echo (not wrapped in d:{}) at session
start: {area_id:N, exe:T, o:100, region_id:[1], time:N, t:'TASK'}.
Echo arrives seconds after the routed action; confirms the mower has
accepted the task. See §4.3 "Session start" for the full sequence.

**Open questions:**
- need_bp exact semantics: 0=skip boundary pre-pass, 1=require it? [UNKNOWN — to capture] Exact value range and effect on session behaviour.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:195`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o101 — `edge_mower`

Edge mow. [app-mitm:2026-06-09-settings-sweep] App and integration both
send routed action s2a50 {m:'a', o:101, d:{edge:[[map_id, contour_id],...]}}
to launch an edge-mowing-only session. The firmware canonicalizes the
inbound d.edge [[m,c],...] list into group_id for its echo:
{exe:T, group_id:[[m,c],...], o:101, status:T, time:N}.

Echo is identical regardless of input (empty vs explicit contour list),
so the s2p50 echo cannot be used to discriminate launch paths.

Critical: d.edge:[] is NOT "all outer contours" — it is "every contour
including internal seam boundaries", causing wheel-bind → FTRTS. Always
send explicit [[map_id, contour_index], ...] pairs. Confirmed 2026-05-05
(three live edge-mow runs; see §4.6.1).

Observed in probe corpus from 2026-04-26 onward.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:204`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o102 — `zone_mower`

Zone mow. [app-mitm:2026-06-09-settings-sweep] App and integration both
send routed action s2a50 {m:'a', o:102, d:{region:[zoneId,...]}} to mow
one or more named zones. zone_ids are scalar ints from
MAP.*.mowingAreas.value. Distinct from o:101 edge contours (which use
[map_id, contour_index] 2-tuples). Observed in probe corpus per §4.6.

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:199`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o103 — `spot_mower`

Spot mow. [app-mitm:2026-06-09-settings-sweep] App and integration both
send routed action s2a50 {m:'a', o:103, d:{area:[spotId,...]}} to mow
one or more spot areas. spot_ids from MAP.*.spotAreas.value. Echo:
{area_id:[N], exe:T, o:103, region_id:[], status:T, time:N}. Confirmed
end-to-end live 2026-04-29. Cloud spotAreas.area=0 in echo — actual
spot coordinates from telemetry, not from echo (per project memory
g2408-session-archive-quirks).

**See also:** `custom_components/dreame_a2_mower/mower/actions.py:209`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o104 — `plan_mower`

Scheduled / planned mowing run. Apk-documented as planMower. Not
observed on g2408 wire; scheduled mowing is triggered by the Dreame
cloud at the configured time, not by the integration. d-field payload
shape unknown.

**Open questions:**
- What d-field does planMower carry? Apk source needed.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o105 — `obstacle_mower`

Obstacle-aware mowing mode. Apk-documented as obstacleMower. Not
observed on g2408 wire. Exact semantics and d-field unknown.

**Open questions:**
- How does obstacleMower differ from globalMower on g2408?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o107 — `start_cruise_point`

POINT PATROL (startCruisePoint) — the mower visits a user-placed list of
map points in sequence. CONFIRMED on g2408 2026-06-03: a user-triggered
double-point patrol emitted s2p50 op=107
{error:0, estimate_time:155, exe:true, o:107, status:true, time:10664} at
20:44:10, paired with s2p2=51 (patrol started, same as edge patrol) and
s2p56 going []→[[3,0],[4,-1]] (the point queue — two entries for the two
points; shape [point_id, state], state 0=active/-1=pending PRESUMED).
Runs blades-up (s1p4 area stays 0) with valid position telemetry, like the
edge patrol (o:108). estimate_time=155s for this 2-point route.
Companion to o:108 (cruise along an edge / zone edge).

NEGATIVE finding (capture limitation): the per-point app settings — Number
of Patrol Cycles (1/2/3) and "Auto Capture & Upload Photos at Patrol Points"
(on/off), set to point1=2cyc/ON, point2=1cyc/OFF this run — did NOT appear
in any captured /status/ device uplink. The MQTT monitor only receives the
device's /status/ topic (+ broker-permitted #); the app→device command
carrying the point list + settings is not relayed to it. So with the
current capture path, patrol settings are unobservable on the wire. Next
candidate is the s4 eiid1 session-summary OSS object at patrol end.

**Open questions:**
- RESOLVED 2026-06-16: per-point cycles + auto-capture are NOT in the o=107 payload — they live in a separate `CRUISED` CFG write (see cfg key `CRUISED`). The o=107 send remains the bare point-id list {point:[...]}; whether it carries per-point cycles inline is still UNVERIFIED (the app's o=111 setter is the per-point cycles path).
- s2p56 [[3,0],[4,-1]]: confirm point_id vs state field order and state vocab (0=active? -1=pending? 2=arrived as in o=109?) across more captures.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o108 — `start_cruise_side`

PATROL along an edge (startCruiseSide). CONFIRMED on g2408 2026-05-30: a
user-triggered Patrol of the zone-1 edge emitted s2p50 op=108
{error:0, estimate_time:900, exe:true, o:108, status:true, t:'TASK'} at
22:35:54, paired with s2p2=51 (patrol started) and s2p56=[[1,0,0]]. Runs
blades-up (area=0) with valid s1p4 position telemetry. estimate_time=900s
(15 min). Companion to o:107 (cruise to a point).

**Open questions:**
- Patrol session capture: a dock-started patrol intermittently mis-typed as maintenance_run and finalized early (CONFIRMED 2026-06-04 — 2nd point patrol + an edge patrol closed early, missing the return leg). ROOT-CAUSED + FIX IN REVIEW (branch fix/patrol-session-type-recording): begin_session wiped the pre-session s2p50 op echo + s2p2=51 clues, so classify fell through to maintenance_run. Fix latches the op ungated (_pending_task_op) and seeds last_task_op at begin_session. AWAITING LIVE RE-CONFIRMATION that a dock-started point + edge patrol both type as patrol and capture the return leg to dock.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o109 — `start_clean_point`

"Go to clean point" = Head to Maintenance Point. Apk-documents this as
startCleanPoint. SEND SHAPE CONFIRMED LIVE 2026-05-31:
routed_action(109, {"point":[point_id]}) — a bare per-map cleanPoint id on
the ACTIVE map — is accepted and the mower drives to the point. The d-key is
the target TYPE ("point"), matching the per-op convention (102 region / 103
area / 101 edge / 109 point); reusing spot's {area:[id]} with o=109 is
REJECTED (status:false), so the key matters, not just the opcode.

Lifecycle on accept (per 2026-05-12 app capture + 2026-05-31 live):
s2p50 {o:109, exe:true, status:true, error:0, estimate_time:N} → s2p56=[[id,0]]
(started) → [[id,2]] (arrived) → s2p1=2 → s2p2=75 arrived_at_maintenance_point
→ s1p52={}. Failure to reach → s2p2=76 "Cannot reach the maintenance point."

Echo can also be status:false = task rejected (mower in a bad state, e.g.
Positioning Failed s2p2=71, or a wrong d-shape). First seen 2026-04-20
19:34:20: o:109 status:false then o:-1 status:true (abort cleanup); the
integration monitors o:109 + status:false as the "task start failed" signal.

cleanPoints are PER-MAP (id is per-map; map 0 had ids 1,2 with type=6
shapeType=5 path=[{x,y}], map 1 had none), so a per-map button must target
the right map — set it active (op=200) first if it isn't, OR test whether
{point:[[map_id, id]]} also works (untested; bare id sufficed on the active map).

**Open questions:**
- TRANSPORT is solved (2026-05-31, see verifications): routed_action → /device/sendCommand works; 80001 is a wake-up timeout fixable by retry. The ONLY remaining unknown is the op=109 d-SHAPE. Re-probe with probe_cruise_to_point.py --routed-byid --retries 5 from a clean idle dock and read the cloud reply: r:0 = shape accepted (mower should head to the point + echo s2p56=[[id,0]]); r<0 or an o:109 status:false echo = shape wrong.
- d-shape LEAD: the s2p56 selector-id finding (2026-05-30) shows point-runs carry a stable per-target id as status[0][0] (corpus ids 2,1,1,2 == the map's two cleanPoints ids 1,2), so op=109's `d` likely references the point BY ID — `{point:[id]}` / `{area:[id]}`, same family as spot (o103 `{area:[id]}`) — not by coordinate. See docs/TODO.md 'Cruise-to-Point / Head-to-Maintenance-Point trigger (op=109)'.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o110 — `start_learning_map`

Start BUILDING mode (map learning / initial mapping run). Apk-documented
as startLearningMap. Used when the mower needs to build its first map or
expand an existing one. Not directly observed on g2408 wire in probe
corpus; the integration does not currently wire this action.

**Open questions:**
- Confirm g2408 honours o:110 for BUILDING mode start.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o111 — `set_cruise_point_cycles`

Per-point patrol CYCLES setter (net-new, app-MITM 2026-06-16). At patrol
run-start the app sends o=111 {point:[id, cycles]} alongside o=107 (run) and
o=400 {on:true} (camera). The authored per-point cycles + auto-capture are
ALSO persisted via the `CRUISED` CFG key (see cfg key CRUISED); the
relationship between the o=111 run-time send and the CRUISED stored value
(which is authoritative) is not yet established. [app-mitm:2026-06-16]

**Open questions:**
- o=111 vs CRUISED[3] cycles — which is authoritative, and is o=111 required or redundant at run time? [UNKNOWN — to capture].

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`

### o200 — `select_map`

Select active map. [app-mitm:2026-06-09-settings-sweep] App sends routed
action s2a50 {m:'a', o:200, d:{idx:N}} to switch the active map, where
idx is the target map index. The integration already uses this form
(MowerAction.SET_ACTIVE_MAP → routed_o=200, ACTION_TABLE payload_fn
_build_set_current_map_payload).

Echo (inbound s2p50) confirmed on g2408 wire 2026-05-07 during a
multi-map session when the user tapped the corner-window thumbnails in
the app to swap between Map 1 and Map 2.

o:200 echo is **conditional** — fires on some swaps but not others.
Two paired captures confirm: 21:52:05–07 (flip A→B, op:200 fired)
and 21:52:36–38 (flip B→A, op:200 did NOT fire). Hypothesis:
either direction-specific (only fires when going to a particular
map_id), or first-in-quiet-window (the next swap within ~30 s
suppresses the duplicate echo). More captures needed to settle.

Per-swap signal that IS reliable: `s1p50={}` empty-ping fires
on EVERY swap (confirmed on both 21:52:06 and 21:52:36 above).
The integration treats s1p50 as the MAPL-repoll trigger for
sub-second active-map detection.

**Open questions:**
- Does o:200 echo fire on every swap, or only the first/last in a quiet window? Today's session showed ~4 swap attempts but only 1 inbound echo.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o201 — `map_edit_commit`

Map-edit commit / exit build map. [app-mitm:2026-06-09-settings-sweep]
App sends routed action s2a50 {m:'a', o:201} with no payload to commit
and close a map-edit sequence. Apk documents this as exitBuildMap.

On g2408, o:201 is observed as a status echo on s2p50 that closes every
map-edit sequence (create zone, resize, delete): the always-trailing
{o:201, status:true, error:0} arrival is the integration's universal
"refetch + rebuild map" trigger.

The dual role (command: exit building mode / echo: map-edit complete)
reflects that the same opcode number is reused in both contexts by the
firmware. The integration keys on o:201 status:true error:0 for the
map rebuild trigger (§2.1). Sequence: o:204 (begin) → o:215/o:218/o:234
(edit action) → o:201 (commit) → o:-1 (teardown).

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o204 — `map_edit_begin`

Map-edit begin (enter map-edit mode). [app-mitm:2026-06-09-settings-sweep]
App sends routed action s2a50 {m:'a', o:204} with no payload to open a
map-edit session. Apk-documented as editMap. The firmware echoes o:204
(with exe:T, status:T) as the first signal in a zone / exclusion-zone
add / edit / delete sequence, before the save or delete confirmation
opcode. Full sequence: o:204 (begin) → o:215/o:218/o:234 (edit action)
→ o:201 (commit) → o:-1 (teardown).

Confirmed in the 2026-04-26 Designated Ignore Obstacle Zone
create/resize/delete corpus.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o205 — `clear_map`

Clear / wipe the current map. Apk-documented as clearMap. Not observed
on g2408 wire; the integration does not expose a clear-map action.

**Open questions:**
- Does clearMap fully wipe all zones and the map polygon on g2408?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o206 — `expand_map`

Expand the current lawn map (add new area to existing map). Apk-
documented as expandMap; also referenced in §4.3 "Expand Lawn" context.
Not directly observed on g2408 wire in probe corpus.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o208 — `full_state_backup`

Full-state backup / restore. [app-mitm:2026-06-09-settings-sweep]
App sends routed action s2a50 {m:'a', o:208, d:{idx:N}} where idx is
the backup slot index.

WARNING: restoring a backup resets ALL mower settings AND schedules
to the backed-up state. This is a destructive operation — any settings
or schedule changes made after the backup was created will be lost.

Whether this creates a new backup at idx or RESTORES from an existing
backup at idx is [UNKNOWN — to capture] — both operations likely use
this opcode (separate idx ranges or a type field may distinguish them).
No echo observed on s2p50 for this opcode. [UNKNOWN — to capture]

**Open questions:**
- Does o:208 {idx:N} CREATE a backup at slot N, or RESTORE from slot N? How many slots exist? Is there a separate 'restore' vs 'backup' form (e.g. a type field)? [UNKNOWN — to capture]

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o214 — `edit_spot`

Create / edit a spot map element — a single axis-aligned 4-corner
rectangle used to target a small area. [app-mitm:2026-06-12-mapedit-rotate-edit]
NET-NEW opcode this session — NOT in the prior g2408-canonical catalog.

Spot has its OWN dedicated in-app map editor (separate from the shared
shape/area editor that uses o:215). It has NO rotation — the UI only drags
a resize handle; all four corners stay axis-aligned. Geometry is the
4-corner rectangle carried entirely in `points` (metres).

`id` is the create/edit discriminator (same convention as o:215):
id:-1 = create new (device assigns a real id on commit — observed id 4);
id:<real> = edit/resize that spot in place. DELETE is via o:218
{id, type:1} (spot = category 1 in the o:218 delete enum), NOT o:214.

Sequence: o:204 (begin) → o:214 {id} → o:201 (commit). NOTE: this spot
map ELEMENT (o:214) is distinct from the spot RUN action (o:103), which
only starts a mow at an already-existing spot.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: /data/claude/homeassistant/OLD/from-mitm-claude/dreame-app-mapedit-rotate-edit-2026-06-12.md § Spots`

### o215 — `add_no_go_zone`

Add / save a no-go zone (virtual boundary). [app-mitm:2026-06-09-settings-sweep]
App sends routed action s2a50 {m:'a', o:215, d:{id, type, points, radius}}
to create a new exclusion zone. The firmware echoes o:215 on s2p50 with
id (assigned by server) and ids fields after the zone is saved.

Zone type encoding: [app-mitm:2026-06-09-settings-sweep]
  type 1 = line (2 points, radius=0)
  type 2 = polygon (corner points, radius=0)
  type 3 = circle (center point + radius)

Mowing-shape preset types (decorative/preset shapes):
  type 9  = Square (4 points)
  type 13 = Heart
  type 17 = Cloud
  type 18 = Rainbow

Sequence: o:204 (begin) → o:215 (add zone) → o:201 (commit) → o:-1 (teardown).
The integration triggers a MAP rebuild on o:215 OR o:201 with status:true
error:0 — covers both confirmation opcodes.

Earlier captures (2026-04-20) saw o:215 as a map-edit echo in the same
"second slot" position; the app-mitm sweep confirms it is also the SEND
command for adding no-go zones, not only a legacy echo.

**Open questions:**
- Shape type ids 9 (Square), 13 (Heart), 15 (Teardrop), 17 (Cloud), 18 (Rainbow) are WIRE-CONFIRMED (appear in o:215 capture payloads; 15 confirmed 2026-06-12 [app-mitm:2026-06-12-mapedit-rotate-edit]). Type ids 12 (Circle), 14 (Triangle), 16 (Mushroom) are [UNVERIFIED] — INFERRED from the Shapes-screen (IMG_4615.PNG) left→right ordering filling the 9,12-18 sequence, NOT seen on the wire. Capture: draw each in app-MITM and read its type in o:215 to confirm/correct. Type ids 10 and 11 (the gap between square=9 and circle=12) are [UNKNOWN — to capture] — no shape occupies them in this app's Shapes screen, so they appear unused on g2408.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §Actions map-edit confirm`

### o218 — `delete_map_object`

Delete a map object. [app-mitm:2026-06-09-settings-sweep] App sends
routed action s2a50 {m:'a', o:218, d:{id:N, type:T}} to delete a
map-layer object by its id and object-category type. type=4 is the
confirmed value for ignore-obstacle zones (object category 4).

The `type` field is the element-category enum, now FULLY mapped (0–4)
from the 2026-06-12 map-edit CRUD capture
[app-mitm:2026-06-12-mapedit-rotate-edit] plus the 2026-06-15 patrol
capture [app-mitm:2026-06-15-patrol-point-crud]:
  0 = no-go zone / mowing-shape
  1 = spot
  2 = patrol / cruise point   (create/move via o:223)
  3 = maintenance-point       (create/move via o:224)
  4 = ignore-obstacle zone    (add/edit via o:234 type:0)
(Quirk: the ignore-obstacle element is added & edited with type:0 in its
OWN opcode o:234, but is DELETED here with type:4 — the o:218 enum is the
canonical element category, distinct from the o:234 add-payload `type`.)
NOTE: patrol (2) and maintenance (3) are DISTINCT delete categories, the
same way their create opcodes (o:223 vs o:224) are distinct.

The firmware echoes o:218 on s2p50 carrying the deleted entity's id;
ids:[] in all observed captures. CONFIRMED via multiple captures
matching user-delete narrative in the 2026-04-26 Designated Ignore
Obstacle Zone corpus. One outlier capture from an untraced UI flow
(likely an edit-cancel processed as delete-and-recreate). Sequence:
o:204 → o:218 → o:201.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §Actions map-edit delete`

### o219 — `rename_zone`

Rename a zone / mowing area. [app-mitm:2026-06-09-settings-sweep]
App sends routed action s2a50 {m:'a', o:219, d:{region:N, name:'...'}}
to rename a named zone. `region` is the zone id; `name` is the new
display name string.

Whether the firmware echoes o:219 on s2p50 is not yet observed.
[UNKNOWN — to capture]

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o220 — `split_zone`

Split a zone by drawing a cut line. [app-mitm:2026-06-09-settings-sweep]
App sends routed action s2a50 {m:'a', o:220, d:{id, line_start, line_end}}
where id is the zone to split, and line_start/line_end are the endpoints
of the cut line in map coordinates.

WARNING: destructive operation — splitting clears that zone's schedule
and per-zone preferences. The two new sub-zones inherit neither; they
must be reconfigured. No echo observed on s2p50. [UNKNOWN — to capture]

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o221 — `merge_zones`

Merge two or more zones into one. [app-mitm:2026-06-09-settings-sweep]
App sends routed action s2a50 {m:'a', o:221, d:{ids:[zoneId,...]}} to
merge multiple zones. ids is a list of the zone ids to merge.

WARNING: destructive operation — the source zones and their schedules /
per-zone preferences are discarded; only the merged zone survives.
No echo observed on s2p50. [UNKNOWN — to capture]

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o223 — `edit_patrol_point`

Create / move a patrol / cruise point — a single ORIENTED point
[x, y, heading] (heading in radians). [app-mitm:2026-06-15-patrol-point-crud]
The element kind is now WIRE-CONFIRMED as the patrol/cruise point (the MAP
blob's cruisePoints, type=8) — patrol has its OWN dedicated in-app map
editor, like every other element kind. The earlier [UNVERIFIED] "inferred
cruise point" framing is upgraded to confirmed.

`id` is the create/edit discriminator (same convention as o:215/o:224):
id:-1 = create new (device assigns a real id on commit — observed id 6);
id:<real> = move/edit that patrol point in place. DELETE is via o:218
{id, type:2} (patrol = category 2 in the o:218 delete enum), NOT o:223.
(Resolves the old mystery: the historical o:223 {id:5/6} was a patrol-point
MOVE.)

Sequence: o:204 (begin) → o:223 {id} → o:201 (commit). Live captured:
create o:223 {id:-1, points:[-2.27, 9.66, 0.06]} → assigned id 6; then
move o:223 {id:6, points:[-6.58, 4.67, 0.06]}; then delete o:218 {id:6,
type:2}.

DISTINCT opcode from o:224 (maintenance point) — both are oriented
[x,y,heading] points but separate editors / opcodes / delete categories
(patrol=2, maintenance=3). Do not conflate.

Patrol points are CREATED via o:223 here, but RUN via o:107
(start_cruise_point {point:[ids]}) — separate concerns.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: /data/claude/homeassistant/FINDING-patrol-point-crud-2026-06-15.md § New this session`

### o224 — `edit_maintenance_point`

Create / edit a maintenance point — a single ORIENTED point
[x, y, heading] (heading in radians) marking where the mower parks for
maintenance. [app-mitm:2026-06-12-mapedit-rotate-edit] NET-NEW opcode this
session — NOT in the prior g2408-canonical catalog.

Maintenance point has its OWN dedicated in-app map editor (separate from
the shared shape/area editor). Unlike spot (o:214) and shapes (o:215), the
heading is carried EXPLICITLY as the third element of `points`, not baked
into corner coordinates.

`id` is the create/edit discriminator (same convention as o:215):
id:-1 = create new (device assigns a real id on commit — observed id 6);
id:<real> = move/edit that maintenance point in place. DELETE is via
o:218 {id, type:3} (maintenance-point = category 3 in the o:218 delete
enum), NOT o:224.

DISTINCT opcode from o:223 (patrol / cruise point) — both are oriented
[x,y,heading] points but separate editors / opcodes / delete categories
(maintenance=3, patrol=2). Do not conflate. [app-mitm:2026-06-15-patrol-point-crud]

Sequence: o:204 (begin) → o:224 {id} → o:201 (commit).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: /data/claude/homeassistant/OLD/from-mitm-claude/dreame-app-mapedit-rotate-edit-2026-06-12.md § Maintenance points`

### o234 — `add_ignore_obstacle_zone`

Add an ignore-obstacle zone (object category 4). [app-mitm:2026-06-09-settings-sweep]
App sends routed action s2a50 {m:'a', o:234, d:{id:-1, type:0, points:[...]}}
to create a new ignore-obstacle zone. id:-1 signals a new zone (server
assigns the real id); type:0 is the fixed object category for ignore-obstacle
zones (category 4 in the delete opcode context); points is an array of
polygon corner coordinates.

The firmware echoes o:234 on s2p50 carrying the server-assigned entity id;
ids:[] in all observed captures. Sequence: o:204 → o:234 → o:201.
Confirmed 2026-04-26 from Designated Ignore Obstacle Zone
create/resize/delete tests.

NOTE: earlier entries described this as "save zone / exclusion-zone
geometry" covering both create-new and resize-existing. The app-mitm
sweep shows the SEND form for the CREATE (id:-1) case.
Edit-in-place (resize/move/rotate) via id:<real> is now WIRE-CONFIRMED for
o:234 specifically [app-mitm:2026-06-12-mapedit-rotate-edit]: an existing
ignore-obstacle zone (id 101) was rotated ~9° and resized in place via
o:234 {id:101, type:0, points:[[-3.19,1.99],[-7.4,2.68],[-6.34,9.12],
[-2.13,8.43]]} — same opcode as create, id:<real> the only discriminator,
rotate/resize baked entirely into `points` (no angle field). This matches
the o:215 edit-in-place convention. The ignore-obstacle zone has its OWN
dedicated in-app editor (toolbar: Rectangle | Delete; rectangle primitive
only). DELETE is via o:218 {id, type:4}, NOT o:234.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §Actions map-edit save geometry`

### o400 — `camera_live_view`

Camera / live-view on/off. [app-mitm:2026-06-09-settings-sweep]
App sends routed action s2a50 {m:'a', o:400, d:{on:0|1}} to enable
(on=1) or disable (on=0) the live camera stream. Also fires automatically
at the start of a patrol run (the patrol feature turns the camera on
when it begins patrolling points to enable auto-capture).

Previously noted as "startBinocular" (apk name, no payload). The app-
mitm sweep confirms the actual SEND form includes {d:{on}} and the
opcode covers the live-view toggle, not only a discrete stream-start.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o401 — `take_pic`

Take a photo via the mower's onboard camera. Observed on s2p50 via
HA-integration button press (2026-04-27). Two distinct firmware echoes:
(a) docked: {o:401, exe:true, status:true, error:0} — accepted but
silently skipped (dock obscures camera); (b) lawn-stopped BT-disconnected:
{o:401, exe:true, status:false} — rejected.

NOTE: The Dreame app's Take Picture button does NOT use this opcode.
Comparison test 2026-04-27 10:59 showed zero MQTT traffic when the app
successfully captured an image — the app uses a separate cloud HTTP/OSS
surface. Integration use of o:401 is best-case a no-op, worst-case a
rejection. See §4.6 for the full comparison test write-up.

**See also:** `coordinator/ (see _property_apply.py § _SUPPRESSED_SLOTS + _mqtt_handlers.py § handle_property_push)`, `docs/research/inventory/generated/g2408-canonical.md § Routed-action opcodes`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

### o503 — `cutter_bias`

Blade calibration / bias correction. Apk-documented as cutterBias.
Referenced in §6.2 opcode list. Not observed on g2408 wire; the
integration does not currently expose a blade-calibration action. d-field
payload shape (calibration parameters) unknown.

**Open questions:**
- What d-field does cutterBias carry? When should calibration be triggered?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §m=a opcodes`

## CFG keys

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| AOP | ai_obstacle_photos | int {0,1} | WIRED |  |
| ATA | anti_theft_alarm | list[int(3)] [lift_alarm, offmap_alarm, realtime_location] | WIRED |  |
| BAT | charging_config | list[int(6)] [recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min] (READ); typed write: {type,value} | WIRED |  |
| BP | start_from_stop_point | list[int(2)] [start_from_stop_point(0/1), stop_point_term_days(1-7)] | WIRED |  |
| CLS | child_lock | int {0,1} | WIRED |  |
| CMS | consumables_wear_meters | list[int(4)] [blade_min, brush_min, robot_min, aux_min] | WIRED |  |
| CRUISED | patrol_point_attributes | {idx: int, value: list[int]} | SEEN-UNDECODED |  |
| CRUISED | patrol_point_settings | {idx:<map_index>, value:[-1, point_id, auto_capture(0/1), cycles(1/2/3)]} | WIRED |  |
| DLS | daylight_savings | int=0 | WIRED |  |
| DND | do_not_disturb | list[int(3)] [enabled, start_min, end_min] | WIRED |  |
| FDP | frost_protection | int {0,1} | WIRED |  |
| LANG | language | list[int(2)] [text_idx, voice_idx] | WIRED |  |
| LIT | lights_led_period | list[int(8)] [enabled, start_min, end_min, standby, working, charging, error, unknown] | WIRED |  |
| LOW | low_speed_nighttime | list[int(3)] [enabled, start_min, end_min] | WIRED |  |
| MSG_ALERT | notification_preferences | list[int(4)] [anomaly, error, task, consumables] | WIRED |  |
| PATH | pathway_obstacle_avoidance | int {0,1} | WIRED |  |
| PRE | mowing_preferences | list[int] — 19 ints on fw≤4.3.6_0550, 21 ints on fw≥4.3.6_0625 (two fields APPENDED at [19],[20]); indices 0–18 unchanged. transport action(siid:2,aiid:50) {m:'s',t:'PRE',d:[…ints…]} | WIRED |  |
| PROT | navigation_path | int {0,1} | WIRED |  |
| REC | human_presence_detection | list[int(9)] [enabled, sensitivity, standby, mowing, recharge, patrol, alert, photo_consent, push_min] | WIRED |  |
| STUN | auto_recharge_standby | int {0,1} | WIRED |  |
| TIME | timezone | str (IANA timezone name) | WIRED |  |
| VER | cfg_version | int (monotonic counter) | WIRED |  |
| VOICE | voice_prompt_modes | list[int(4)] [regular_notification, work_status, special_status, error_status] | WIRED |  |
| VOL | robot_voice_volume | int 0..100 | WIRED | % (×1.0) |
| WRF | weather_forecast_reference | int {0,1} | WIRED |  |
| WRP | rain_protection | list[int(2)] [enabled, resume_hours] | WIRED |  |

### AOP — `ai_obstacle_photos`

Capture Photos of AI-Detected Obstacles. Confirmed 2026-04-24 via
isolated single-toggle. Mapping {0: off, 1: on} matches the app.
Surfaced as sensor.ai_obstacle_photos. Sample: 1 (on).
Write payload: {value:0|1}. [app-mitm:2026-06-09-settings-sweep]
Re-enabling AOP via the app shows a privacy-policy screen, but no
consent payload is transmitted — only AOP{value:1} hits the wire;
the policy text is fetched as a static GET from
protocol.dreame.tech. [app-mitm:2026-06-09-settings-sweep]
Integration can set AOP=1 directly without any consent ceremony.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX AOP`

### ATA — `anti_theft_alarm`

Anti-Theft Alarm. Confirmed 2026-04-24, all three indices individually
verified 2026-04-27. Shape [lift_alarm, offmap_alarm, realtime_location]
matches the s2p51 ANTI_THEFT decoder exactly.
Toggle test: [0,0,0]→[1,0,0] Lift, →[1,1,0] Off-Map, →[1,1,1]
Real-Time Location. Each index ∈ {0,1}.
Write payload: {value:[lift,offmap,realtime]}. [app-mitm:2026-06-09-settings-sweep]
Surfaced as sensor.anti_theft (state=on if any sub-flag enabled,
per-flag bools in attributes). Sample: [0,0,0].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX ATA`

### BAT — `charging_config`

Charging config. Confirmed 2026-04-24. Read shape matches the s2p51
CHARGING decoder exactly: [recharge_pct, resume_pct, unknown_flag,
custom_charging, start_min, end_min].
recharge_pct = auto-recharge when battery drops below this;
resume_pct = resume mowing when battery above this;
unknown_flag [2] consistently observed =1 (purpose TBD — see open_questions);
custom_charging bool toggles the schedule window;
start_min/end_min = window in minutes-from-midnight.
Surfaced as sensor.charging_config.
Sample: [15, 95, 1, 0, 1080, 480] → recharge@15%, resume@95%, window
off, would-be 18:00→08:00.

WRITE payloads — BAT is a typed key (write only):
[app-mitm:2026-06-09-settings-sweep]
- Custom Charging Period: {type:"charging", value:[enabled(0/1), start_min, end_min]}
  e.g. {type:"charging", value:[1, 1080, 480]} = enable 18:00→08:00.
- Auto-Recharge / Resume thresholds: {type:"power", value:[recharge_pct, resume_pct, flag]}
  e.g. {type:"power", value:[10, 95, 1]}. value[0] choices: 10/15/20/25%.
  value[2] = 1 observed (purpose unknown — NOT Auto-Recharge-after-Standby,
  that toggle writes STUN separately). [UNKNOWN — to capture]

**Open questions:**
- unknown_flag [2] always=1 — purpose unknown. App charging-settings page exposes a control for every OTHER BAT index and has no unaccounted-for setting, so [2] has no user-facing mapping — likely firmware-reserved or not applicable to the g2408. Not worth wiring a write path; see TODO.md 'BAT[2] hardcoded 1' (left open as defensive cleanup only).
- BAT typed-write value[2]/flag: purpose still unknown — NOT STUN (auto-recharge-after-standby has its own STUN key). [UNKNOWN — to capture]

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX BAT`

### BP — `start_from_stop_point`

Start-from-Stop-Point + Stop-Point Term. [app-mitm:2026-06-09-settings-sweep]
Write payload {on:bool, day:1-7}: on=Start-from-Stop-Point boolean,
day=Stop-Point Term in days. CFG read BP:[1,4]=[on,day]. Sample: [1,4].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX BP`

### CLS — `child_lock`

Child Lock. Confirmed 2026-04-24 via isolated single-toggle.
Mapping {0: off, 1: on} matches the app. Surfaced as
sensor.child_lock_cfg. A switch.child_lock entity already exists
wired to DreameMowerProperty.CHILD_LOCK, but on g2408 the
authoritative read path is CFG.CLS. Sample: 0 (off).
Write payload: {value:0|1}. [app-mitm:2026-06-09-settings-sweep]
CLS is the WRITABLE surface (s4p27 set_properties is the read-side
only). [app-mitm:2026-06-09-settings-sweep]

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX CLS`

### CMS — `consumables_wear_meters`

Consumables wear meters. Wear meters in minutes. Apk documents 3
fields; g2408 has 4. Max-minutes: [6000, 30000, 3600, n/a].
CMS[0..2] = blade_min / brush_min / robot_min — confirmed vs app
(% + hours-left match the thresholds).
CMS[3] semantic UNCONFIRMED — only ever seen as -1 on this unit. Do NOT
assert a label: mower_tail.py's CONSUMABLE_SLOT_NAMES[3]="Link Module"
is an unverified guess, NOT app-confirmed (the "Link Module=n/a" string
seen in tail output is that guess, not the app). The app's consumables
page actually carries three further items beyond the wear trio — Link
Module (cellular SUBSCRIPTION, day-based: e.g. 904 days left, term
2025-11-19→2028-11-19; NOT a minutes wear-meter), Garage (dock roof),
and Charging Station MCA10 — so one CMS[3] slot cannot represent all
three, and the "minutes" framing doesn't fit Link. -1 most plausibly
means "accessory/feature absent" (this user has none of the three), but
which one (or a presence summary) is unproven. Samples: [3084,0,0,-1],
[495,3739,0,-1].

**Open questions:**
- CMS[3] semantic — does it track Link Module, Garage, MCA10, or a presence summary? Needs a unit that has one of those accessories (all -1 here). Note Link is a day-based subscription, not a minutes wear-meter, so a wear-meter interpretation of CMS[3] is suspect.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX CMS`

### CRUISED — `patrol_point_attributes`

Per-patrol-point attributes — cycles (1/2/3) and auto-capture-photos
toggle. Sent as a CFG write (m:s) with a named-key envelope, NOT via
o=223 (point geometry) or o=107 (run-patrol). One sample captured:
{idx:0, value:[-1,3,1,3]}. Field-map UNDECODED [UNVERIFIED]: field
order (which element = cycles, which = auto-capture) is NOT confirmed;
no read captured to establish the shape. Behaviour known: auto-capture
= fixed 3 photos/point → gallery. Cross-ref: cfg_individual patrol/
cruise-point (o=223 create/edit) for the geometry opcode.
[app-mitm:2026-06-16-firmware-ota]

**Open questions:**
- CRUISED field order — which element of value[] is cycles, which is auto-capture? No read captured.
- CRUISED value[-1,3,1,3]: is -1 a sentinel for 'applies to all points'? Undecoded.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § CFG keys`

### CRUISED — `patrol_point_settings`

PER-POINT patrol settings (one write per point). Transport: miio
action(siid:2,aiid:50) {m:'s', t:'CRUISED', d:{idx, value:[...]}} on
device/sendCommand. Wire-decoded by single-toggle diffs on fw 4.3.6_0625.
[app-mitm:2026-06-16]

  idx          = MAP index (1 = Map2; an earlier sample on another map was idx:0).
  value[0]     = -1  — constant sentinel (purpose TBD; likely a type/marker).
  value[1]     = point id — WHICH patrol point this write configures (NOT a
                 count). Switching the edited point 1→2 changed value[1] 1→2.
  value[2]     = Auto-Capture & Upload Photos at this point (0=off, 1=on).
                 UI: a camera icon next to the point (light=off / dark=on).
  value[3]     = patrol cycles for this point (1/2/3). UI: an ×1/×2/×3 badge.

Each point has its OWN cycles + auto-capture (hence the per-point camera +
×N icons). This is the ONLY surface carrying the authored per-point toggles —
they are NOT in the o=107 send, the s2p56 queue, or the .0550 session summary
(`param:{}`). Auto-capture behaviour: fixed 3 photos/point → userDidOssList
gallery (type-1 photos, lazy/on-demand — see api key getDownloadUrl).

NO routed-action getter, BUT READABLE via device-data: a live routed-get
{m:'g',t:'CRUISED',d:…} returns out[0].r=-3 for all d shapes, and CRUISED is
ABSENT from the getCFG bundle — so it can't be read at the s2.50 address.
HOWEVER the authored values ARE mirrored read-side in the **`CRUISE.0`
device-data key** (in the `getDeviceData` response, alongside `MAP.*`), as a
JSON-string per-map outer array:
  `[{version, settings:{<point_id>:{num:<cycles>, ap:<auto_capture bool>}}}, …]`
(element[0]=map0, element[1]=map1; unused map = `{version:-1, settings:{}}`;
`version` device-owned, increments per edit). Sibling key `CRUISE.info=107`
(the patrol opcode). Round-trip confirmed: write `CRUISED {idx:0,value:[-1,3,1,3]}`
→ `CRUISE.0` `settings '3':{num:3, ap:true}` with `version` bumped.
Field map: `value[1]`→settings KEY (point id), `value[2]`→`ap`, `value[3]`→`num`;
`value[0]=-1` NOT mirrored. So the patrol-points sensor CAN surface effective
cycles/auto-capture by parsing `CRUISE.0` from the existing map/getDeviceData
fetch — no round-trip, no telemetry reconstruction needed.
[app-mitm:2026-06-16-cruise-readback; live routed-get probe 2026-06-16 for the r=-3]

Patrol-point GEOMETRY is separate (o=223 {id, points:[x,y,heading]}, and the
cloud cruisePoints type=8 blob); it carries NO zone tag — the zone a point
sits in is derived from its coordinates.

**Open questions:**
- value[0]=-1 sentinel meaning (type/marker?) — not mirrored in CRUISE.0; likely a device-assign/version placeholder [UNKNOWN — to capture].
- CRUISE.0 settings comma-joined key '1,0' (vs the bare '3') — point id 1 with a sub-index, or a grouped pair? Set one distinct point and diff which settings key changes [partial — to capture].
- Relationship between CRUISED cycles and the o=111 {point:[id,cycles]} per-point cycles setter seen at run start — which is authoritative? [UNKNOWN — to capture].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py (write path TBD); coordinator/ patrol-point surfacing`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`

### DLS — `daylight_savings`

Daylight savings flag (hypothesized). Observed stable at 0 across
all captures. No toggle-correlation test performed. May be firmware-
managed automatically via TIME (IANA timezone). Sample: 0.

**Open questions:**
- DLS — is this firmware-managed when TIME is set, or user-settable? No toggle test done.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX DLS`

### DND — `do_not_disturb`

Do-Not-Disturb. Apk-catalogued. Shape [enabled, start_min, end_min]
with start_min/end_min in minutes-from-midnight. Sample: [0, 1260, 420]
= off, would-be 21:00→07:00.
Write payload: {value:0|1, time:[start_min, end_min]}.
[app-mitm:2026-06-09-settings-sweep] e.g. {value:0, time:[1260,420]}.
start_min/end_min confirmed as minutes-since-midnight (1260=21:00, 420=07:00).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX DND`

### FDP — `frost_protection`

Frost Protection. Confirmed 2026-04-24 via isolated single-toggle.
Mapping {0: off, 1: on} matches the app. Surfaced as
sensor.frost_protection. Sample: 1 (on).
Write payload: {value:0|1}. [app-mitm:2026-06-09-settings-sweep]

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX FDP`

### LANG — `language`

Language. Confirmed 2026-04-24. Shape [text_idx, voice_idx].
text_idx = app/UI language; voice_idx = robot voice language.
Observed indices: voice_idx=7 → Norwegian. Transported via s2p51
shape {"text": N, "voice": M} — decoded as Setting.LANGUAGE.
Surfaced as sensor.robot_voice (state = voice language name where
known, raw indices as attrs). Sample: [2, 7].
Write payload: typed key {type:"voice"|"text", value:idx}.
[app-mitm:2026-06-09-settings-sweep] voice and text are set
separately via the type discriminator. Confirmed indices: English=0,
Norwegian=7, Danish=9. Changing voice language triggers NO download
on g2408 — voice packs are device-side firmware.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX LANG`

### LIT — `lights_led_period`

Lights / LED period. Confirmed 2026-04-24. Shape matches the s2p51
LED_PERIOD decoder exactly: [enabled, start_min, end_min, standby,
working, charging, error, unknown].
[0] Custom LED Activation Period on/off, [1] window start
(min-from-midnight), [2] window end, [3] scenario "In Standby",
[4] "In Working", [5] "In Charging", [6] "In Error State", [7]
unknown trailing toggle (app-visible, purpose unclear).
Surfaced as sensor.headlight_enabled (on/off from [0]) +
sensor.headlight_schedule ([1]/[2] plus scenario flags and [7] as
attributes). Sample: [0, 480, 1200, 1, 1, 1, 1, 1] = LEDs off
(custom period disabled), would-be 08:00→20:00, all scenarios on.
Write payload: {value, time:[start,end], light:[Standby,Working,Charging,Error], fill}.
[app-mitm:2026-06-09-settings-sweep]
time=[start_min,end_min] in minutes-since-midnight (e.g. [480,1200]=08:00-20:00).
light order confirmed by sequential toggle: [0]=Standby, [1]=Working,
[2]=Charging, [3]=Error. [app-mitm:2026-06-09-settings-sweep]
fill = unknown purpose, observed as 1. [UNKNOWN — to capture]

**Open questions:**
- LIT[7] — unknown trailing toggle; app shows an extra field whose purpose isn't obvious.
- LIT.fill — present in write payload with value observed as 1; purpose unknown. [UNKNOWN — to capture]

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX LIT`

### LOW — `low_speed_nighttime`

Low-Speed Nighttime. Confirmed 2026-04-24 via live toggle. Shape
[enabled, start_min, end_min] with start_min/end_min in
minutes-from-midnight. Shape matches the s2p51 LOW_SPEED_NIGHT
decoder. User example: [1, 1200, 480] = enabled, 20:00→08:00 next
day. Surfaced as sensor.low_speed_nighttime.
Sample: [1, 1200, 480].
Write payload: {value:0|1, time:[start_min, end_min]}.
[app-mitm:2026-06-09-settings-sweep] Same shape as DND; time in
minutes-since-midnight (1200=20:00).

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX LOW`

### MSG_ALERT — `notification_preferences`

Notification Preferences. All 4 slots wire-confirmed 2026-04-30 via
single-row toggles: [anomaly_messages, error_messages, task_messages,
consumables_messages]. Default sample [1,1,1,1] = all four enabled.
Wire shape collides with VOICE — both ride s2p51 {value: [b,b,b,b]};
the decoder emits Setting.AMBIGUOUS_4LIST and resolution requires the
getCFG diff via sensor.cfg_keys_raw._last_diff.
Sample: [1, 1, 1, 1].
Write payload: {value:[Anomaly, Error, Task, Consumable]}.
[app-mitm:2026-06-09-settings-sweep] Each element 0/1; order confirmed
by sequential toggle. MSG_ALERT is a DEVICE-side CFG key, NOT
app-only — the notification-type filter IS an integration surface.
[app-mitm:2026-06-09-settings-sweep]

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX MSG_ALERT`

### PATH — `pathway_obstacle_avoidance`

Pathway Obstacle Avoidance master enable. [app-mitm:2026-06-09-settings-sweep]
Write payload: {value:0|1}. 0=disabled, 1=enabled. The per-map/per-pathway
selection sub-menu (map1/map2 pathway IDs) is a SEPARATE write — deferred
pending pathways being drawn. [app-mitm:2026-06-09-settings-sweep]
Sample: 1 (on/true).

**Open questions:**
- Per-pathway selection write (sub-menu with pathway IDs per map) — deferred, needs pathways drawn first. [UNKNOWN — to capture]

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX PATH`

### PRE — `mowing_preferences`

Mowing preferences write array. 19 elements confirmed by 2026-06-09
app-MITM sweep (28 toggle-and-back writes, each index isolated).
Transport: action(siid:2,aiid:50) {m:'s',t:'PRE',d:[…ints…]} via
device/sendCommand; app receives code:0 (r=0 equivalent).
[app-mitm:2026-06-09-settings-sweep]

OTA schema change: the 4.3.6_0550 → 4.3.6_0625 update extended PRE from
19 → 21 ints — two fields APPENDED at the end ([19]=0, [20]=30, semantics
TBD); existing indices 0–18 did NOT shift, so the index map below still
holds on 0625. [app-mitm:2026-06-16] General caveat: re-validate array-CFG
layouts (PRE, LIT, DND, …) after a firmware update — an OTA can extend them.
The integration RMW builder (protocol/cfg_payloads.py:apply_pre) copies the
full fetched array and patches one index, so a 21-int fetch round-trips
intact without code change.

Baseline (General Mode, all-on, 0550/19-int): [0,0,0,0,55,1,8,1,0,1,1,2,1,20,10,7,1,2,0]

Index map (all confirmed [app-mitm:2026-06-09-settings-sweep] unless noted):
  [0]  version/checksum byte — app writes 0, firmware echoes 123 on read.
  [1]  map index — which map these prefs apply to.
  [2]  zone index — 0=General Mode (all zones), 1…N=per-zone Custom Mode.
       After zone split, new zones received zone-index 1 and 2 respectively.
  [3]  Mowing Efficiency: 0=Standard, 1=Efficient. Confirmed by isolated toggle.
  [4]  Mowing Height: cm×10 (range 30–70; e.g. 55=5.5 cm). Multi-value confirmed.
  [5]  Mowing Direction mode: 0=Crisscross, 1=Customize (uses [6] angle),
       2=Chequerboard. 3-value confirmed by isolating each mode.
  [6]  Mowing Direction angle (degrees, used when [5]=1 Customize only).
       Confirmed: 8↔64 via isolated write.
  [7]  Automatic Edge Mowing: 0=off, 1=on. Confirmed by isolated toggle.
  [8]  reserved / unknown — unchanged across all 28 writes. [UNKNOWN — to capture]
  [9]  Obstacle Avoidance on Edges: 0=off, 1=on. Confirmed by isolated toggle.
  [10] EdgeMaster: 0=off, 1=on. Confirmed by isolated toggle (re-confirmed
       by a clean ON↔OFF single-index toggle on fw 0625 [app-mitm:2026-06-16]).
       Resolves the prior "AutoEdge/SafeEdge/EdgeMaster/OA-on-Edges order TBD".
       (Behaviour: after the area mow, two extra edge passes at 3 cm height with
       blades side-shifted toward the edge; PRE[10] is just the on/off.)
  [11] reserved / unknown — unchanged across all 28 writes. [UNKNOWN — to capture]
  [12] LiDAR Obstacle Recognition: 0=off, 1=on. Confirmed isolated; disabling
       greys out Obstacle Avoidance Height in the app.
  [13] Obstacle Avoidance Height: 5/10/15/20 cm. Multi-value confirmed.
  [14] Obstacle Avoidance Distance: 10/15/20 cm. Multi-value confirmed.
  [15] AI Obstacle Recognition bitmask: bit0(1)=Human, bit1(2)=Animal,
       bit2(4)=Object. All-on=7. Bit order confirmed: Human-off 7→6.
  [16] Safe Edge Mowing: 0=off, 1=on. Confirmed by isolated toggle.
  [17] reserved / unknown — unchanged across all 28 writes. [UNKNOWN — to capture]
  [18] reserved / unknown — unchanged across all 28 writes. [UNKNOWN — to capture]
  [19] NEW post-0625 (appended by the 0550→0625 OTA) — default 0. [UNKNOWN — to capture]
  [20] NEW post-0625 (appended by the 0550→0625 OTA) — default 30 (resembles a
       minutes/percent value). [UNKNOWN — to capture]

Per-zone (Custom Mode) writes use the same int array with [2] set to the
zone index. Enable custom-mode per zone via PREP first
({m:'s',t:'PREP',d:{idx:<zone_0based>,value:1}}).

Correct write envelope (bare-array, device-scoped):
  SET: action s2.a50 {m:s,t:PRE,d:[<19 ints>]} — d is the bare array, NOT
       wrapped under a 'value' key. [app-mitm:2026-06-09-settings-sweep]
  GET: action s2.a50 {m:g,t:PRE,d:{idx:<map_idx>,region:<zone_idx>}}
The app always dual-writes: PRE first (device firmware reads it), then
SETTINGS chunked-batch (cloud record for app-side readback). A SETTINGS-only
write is cloud-cache-only — the device firmware does NOT apply it, which is
why SETTINGS-only writes never changed mower behavior. [app-mitm:2026-06-09-settings-sweep]
The 2026-06-03 r=-3 probe used d:{value:[0,1]} (wrong envelope — array
wrapped under a 'value' key instead of bare); the r=-3 was a shape/path
mismatch, NOT a firmware veto of the PRE surface. [app-mitm:2026-06-09-settings-sweep]
Whether the g2408 firmware actually executes each PRE write is not yet
observed — device-side effect is `[UNVERIFIED]` pending live verification.

**Open questions:**
- cfg-write-path: Confirm the app uses the same device/sendCommand path (code:0) for CFG writes (height/RGBPSTA/notifications/rain/DND), a cleaner route than our 80001-prone path [UNKNOWN — to capture].
- pre-reserved: Confirm indices 8,11,17,18 are truly reserved (no-op) or locate their settings via Custom Mode or other pages [UNKNOWN — to capture].
- settings-only-fields: SETTINGS-only fields cutterPosition/cutterPositionHeight/edgeMowingNum/edgeMowingWalkMode/obstacleAvoidanceSensitivity/edgeCuttingAttachment have NO PRE index; whether a SETTINGS-only write changes the mower is unverified. Capture: toggle each in app-MITM and diff PRE vs SETTINGS to see which store carries it [UNKNOWN — to capture].

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX PRE`

### PROT — `navigation_path`

Navigation Path. Confirmed 2026-04-24 via isolated single-toggle with
cfg_keys_raw diff visible on HA alpha.123+. Mapping {0: "direct",
1: "smart"} matches the order shown in the app. Surfaced as
sensor.navigation_path. The field name is cryptic but the toggle
correlation is unambiguous: toggling Nav Path smart→direct flipped
PROT 1→0 with no other CFG key moving. Sample: 1 (smart).
Write payload: {value:0|1}. 0=Direct Path, 1=Smart Path.
[app-mitm:2026-06-09-settings-sweep]

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX PROT`

### REC — `human_presence_detection`

Human Presence Detection Alert. Confirmed 2026-04-24. Shape matches
the s2p51 HUMAN_PRESENCE_ALERT decoder exactly: [enabled, sensitivity,
standby, mowing, recharge, patrol, alert, photo_consent, push_min].
sensitivity ∈ {0,1,2} = low/medium/high (full enum end-to-end
re-verified 2026-05-16). scenario_* fields enable detection per
activity class. alert covers voice prompts + in-app notifications.
photo_consent is the privacy opt-in for sending captured human
photos. push_min is the push-notification cooldown in minutes
(observed: 3/10/20). Surfaced as sensor.human_presence_alert.
Sample: [1, 1, 1, 1, 1, 1, 0, 1, 3].
Write payload: {value, sen:0/1/2, mode:[Standby,Mowing,Recharge,Patrol],
report:[VoiceInApp, CaptureHumanPhotos, PushInterval{3,10,20}]}.
[app-mitm:2026-06-09-settings-sweep]
sen: 0=Low/1=Medium/2=High. mode = Activation Scenarios (each 0/1),
order confirmed by sequential toggle: [0]=In Standby, [1]=In Mowing,
[2]=Recharge, [3]=In Point Patrol. report: [0]=Voice-Prompts/In-App-
Notifications; [1]=Capture Human Photos and Send; [2]=Push Interval
(3/10/20 min). [app-mitm:2026-06-09-settings-sweep]

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX REC`

### STUN — `auto_recharge_standby`

Auto Recharge After Extended Standby. Confirmed 2026-04-24. Mapping
{0: off, 1: on}. Surfaced as sensor.auto_recharge_standby. Was
previously mislabelled as "Anti-Theft" in sensor.py (upstream vacuum
codebase naming that doesn't apply on g2408).
Behaviour observed 2026-04-27: when STUN=1 and the mower is idle
outside the dock for ~1 hour (BT-orphaned manual stop ~10:55 →
auto-return 11:52:47 = 57 min), the firmware fires s2p2=71 +
s2p1=5 simultaneously and self-navigates back to the dock. Dreame
app notification confirms: "The robot is on standby outside the
station for too long. Automatically returning to the station."
Whether the timeout duration is a firmware constant or stored in
another (still uncatalogued) CFG slot is unknown — STUN itself is
just an enable flag. Sample: 1 (on).
Write payload: {value:0|1}. [app-mitm:2026-06-09-settings-sweep]
STUN is its OWN key — NOT BAT.power[2] (confirmed by the sweep:
the Auto-Recharge-after-Standby toggle was NOT on the charging-settings
page with BAT). [app-mitm:2026-06-09-settings-sweep]

**Open questions:**
- STUN standby timeout duration — firmware constant or hidden CFG slot?

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX STUN`

### TIME — `timezone`

Timezone IANA name, e.g. 'Europe/Oslo'. Surfaced as the
disabled-by-default diagnostic sensor.timezone (added 2026-06-04).
Sample: "Europe/Oslo".

**See also:** `custom_components/dreame_a2_mower/sensor_device.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX TIME`

### VER — `cfg_version`

CFG-update revision counter. Corrected 2026-04-24 — was previously
mis-labelled "firmware version". Monotonic increment on every
successful CFG write; useful as a tripwire for toggle-correlation
research. Distinct from the actual firmware version surfaced by
sensor.firmware_version (which reads device.info.version, a separate
cloud field). Surfaced as the disabled-by-default diagnostic
sensor.cfg_version (added 2026-06-04). Sample: 444.

**See also:** `custom_components/dreame_a2_mower/sensor_device.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX VER`

### VOICE — `voice_prompt_modes`

Voice Prompt Modes. All 4 slots wire-confirmed 2026-04-30 via
single-row toggles: [regular_notification_prompt, work_status_prompt,
special_status_prompt, error_status_prompt].
Wire shape collides with MSG_ALERT — both ride s2p51 {value: [b,b,b,b]};
the decoder emits Setting.AMBIGUOUS_4LIST and resolution requires the
getCFG diff via sensor.cfg_keys_raw._last_diff.
Surfaced as sensor.voice_prompt_modes (state = count enabled 0..4,
per-mode bools in attrs). Sample: [1, 1, 1, 1].
Write payload: {value:[Regular, WorkStatus, SpecialStatus, Error]}.
[app-mitm:2026-06-09-settings-sweep] Each element 0/1; order confirmed
by sequential toggle.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX VOICE`

### VOL — `robot_voice_volume`

Robot Voice Volume. Confirmed 2026-04-24. Mapping is percentage 0..100.
Surfaced as sensor.robot_voice_volume. Also controls the camera page
volume slider (no separate camera-volume key). Sample: 72.
Write payload: {value:0-100}. [app-mitm:2026-06-09-settings-sweep]
e.g. {value:51} for 51% volume.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX VOL`

### WRF — `weather_forecast_reference`

Weather Forecast Reference. Mapping {0: off, 1: on}. Surfaced as
the disabled-by-default diagnostic sensor.weather_forecast_reference
(added 2026-06-04). Sample: 1 (on).

**See also:** `custom_components/dreame_a2_mower/sensor_device.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX WRF`

### WRP — `rain_protection`

Rain Protection. Confirmed 2026-04-24 via live toggle. Shape
[enabled, resume_hours]. enabled ∈ {0,1}; resume_hours ∈ {0..24}
where 0 = "Don't Mow After Rain" (no auto-resume), 1..24 resumes N
hours after rain ends. Wire shape mirrors the s2p51 RAIN_PROTECTION
decoder. Surfaced as sensor.rain_protection. Distinct from
binary_sensor.rain_protection_active which tracks "raining right now"
via s2p2=56. Sample: [1, 4].
Write payload: {value:0|1, time:N_hours, sen:sensitivity_level}.
[app-mitm:2026-06-09-settings-sweep] value=on/off; time=resume delay
in HOURS (e.g. 4→5 confirmed); sen=sensitivity level.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX WRP`

## cfg_individual endpoints

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| AIOBS | ai_obstacle_data | (observed: r=-3 in all 3 cloud dumps and live probe 2026-06-09; payload-on-success unknown) | APK-KNOWN |  |
| AI_HUMAN | ai_human_photo_consent | iotuserdata KV: AI_HUMAN.0=JSON-string-encoded bool; AI_HUMAN.info=counter int | UNCLASSIFIED |  |
| ARM | arm_alarm | {m:'s', t:'ARM', d:{value}} | APK-KNOWN |  |
| CFG | all_keys_cfg | {d: {AOP, ATA, BAT, BP, CLS, CMS, DLS, DND, FDP, LANG, LIT, LOW, MSG_ALERT, PATH, PRE, PROT, REC, STUN, TIME, VER, VOICE, VOL, WRF, WRP}} | WIRED |  |
| CHECK | self_check_command | {m:'s', t:'CHECK', d:{mode, status}} | APK-KNOWN |  |
| CMS | consumables_individual | {value: [blade_min, brush_min, robot_min, aux_min]} | WIRED |  |
| DEV | device_info | {fw, mac, ota, sn} | WIRED |  |
| DOCK | dock_state_and_position | {dock: {connect_status, in_region, x, y, yaw, near_x, near_y, near_yaw, path_connect}} | WIRED |  |
| IOT | iot_connection_status | {status: bool} | APK-KNOWN |  |
| LOCN | dock_gps_origin | {pos: [lon, lat]} | WIRED |  |
| MAPD | map_data | (observed: r=-3 in all 3 cloud dumps so far; payload-on-success unknown) | APK-KNOWN |  |
| MAPI | map_info | (observed: r=-3 in all 3 cloud dumps + live probe 2026-06-09; payload-on-success unknown — requires args) | APK-KNOWN |  |
| MAPL | map_list | list[[int×5], ...] — one row per map_id | SEEN-UNDECODED |  |
| MAP_cache | decoded_map_cache | iotuserdata KV: MAP.0, MAP.1, … MAP.N (concat = JSON array of map objects) | UNCLASSIFIED |  |
| MIHIS | lifetime_mowing_aggregates | {area, count, start, time} | WIRED |  |
| MISTA | mission_status | {fin: int (centiares mowed), prg: int (basis points = round(fin*10000/total)), status: [[task_type, sub_state]], total: int (centiares planned)} | DECODED-UNWIRED |  |
| MITRC | mission_track | (observed: r=-1 in all 3 cloud dumps and live probe 2026-06-09; payload-on-success unknown — idle-only; mid-run likely required) | APK-KNOWN |  |
| MPOS | live_position | {x: int, y: int, yaw: int} — map-frame position; units/frame not yet cross-checked | SEEN-UNDECODED |  |
| NET | wifi_info | {current: ssid, list: [{ip, rssi, ssid}, ...]} | WIRED |  |
| OBS | obstacle_data | (observed: r=-3 in all 3 cloud dumps + live probe 2026-06-09; payload-on-success unknown — requires args) | APK-KNOWN |  |
| PIN | pin_status | write: {type:'auth'|'update', value:<int>}; read (m:g): {result, time} | DECODED-UNWIRED |  |
| PRE | preference_endpoint | (observed: r=-3 on individual fetch in all 3 cloud dumps + live probe 2026-06-09; SAME-NAMED key in cfg_keys IS readable via all-keys CFG) | APK-KNOWN |  |
| PREI | preference_info | {type: int, ver: [[map_id, version], ...]} — per-map PRE version counters | SEEN-UNDECODED |  |
| PREP | zone_preference_mode | {idx:<zone0based>, value:0|1} | WIRED |  |
| REMOTE | sim_4g_status | {activeTime, cardId(ICCID), expiredTime, leftDays} | UNCLASSIFIED |  |
| RGBPSTA | led_state | (observed: r=-3 bare GET; payload-on-success unknown — requires args or different call path) | UNCLASSIFIED |  |
| RPET | rain_protection_end_time | {endTime: int} | APK-KNOWN |  |
| SCHDDV3 | schedule_data_v3_write | {s:<offset>, l:<len>, d:"<base64 chunk>", v:<txn_ms>} | WIRED |  |
| SCHDIV3 | schedule_index_v3_write | {i:<index>, l:<total_len>, v:<txn_ms>} | UNCLASSIFIED |  |
| SCHDSV3 | schedule_slot_enable_v3 | {i:<slot 0|1>, v:<packed int>, s:[enabled, flag]} | UNCLASSIFIED |  |
| SCHDTV3 | schedule_v3 | int (scalar — likely schedule version or active-plan count; semantics unknown) | SEEN-UNDECODED |  |
| WINFO | app_weather_info | {m:'s', t:'WINFO', d:{appWeather}} | APK-KNOWN |  |

### AIOBS — `ai_obstacle_data`

APK-documented endpoint. The 3 cloud dumps so far all returned
r=-3. Was once suspected absent on g2408, but MISTA reversed that
when it flipped from r=-3/r=-1 to a successful payload between
dump 2 and dump 3 — establishing that error responses are stateful
or transient, not negative proof of firmware support. With only 3
data points this row is kept at `decoded: hypothesized`.
App-MITM 2026-06-09 confirms the app issues routed-get t=AIOBS;
response shape is [UNKNOWN — to capture] — likely the photo index
call (see tools/probes/read_key_probe.py).
Live probe 2026-06-09 bare GET returned r=-3 (mower docked, idle) —
bare GET requires args; the app likely sends additional arguments.

**Open questions:**
- Capture this endpoint during an AI-obstacle detection event (cloud-side trigger; s1p53 is the BLE-connection flag, NOT an obstacle signal).
- Test whether more cloud dumps over time produce a successful response (cf. MISTA).
- Does AIOBS response carry the photo index (photo_list)? App-MITM suggests this is the AI-obstacle photo-index call [UNKNOWN — to capture].
- Bare GET returns r=-3 — capture the args the app sends with AIOBS to get a successful response.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX AIOBS`

### AI_HUMAN — `ai_human_photo_consent`

Per-device human-photo send consent, stored in the iotuserdata
key-value store (NOT in CFG). Transport:
  POST :13267/dreame-user-iot/iotuserdata/setDeviceData
    {did, data:{"AI_HUMAN.0":"\"true\"|\"false\"", "AI_HUMAN.info":"<N>"}, sign, timestamp}
  GET …/getDeviceData {keys:["AI_HUMAN.0"]} → {"AI_HUMAN.0":"\"true\""}
[app-mitm:2026-06-09-settings-sweep]
AI_HUMAN.0 = send-human-photos consent, encoded as a JSON-string bool
("\"true\"" / "\"false\""). AI_HUMAN.info = counter/version int (6 and
7 both seen); NOT a fixed version number. [app-mitm:2026-06-09-settings-sweep]
Revoking consent cascades automatically: sets REC.report[1]
(Capture Human Photos) → 0. [app-mitm:2026-06-09-settings-sweep]
Human-photo capture requires ALL of: AOP=1 AND REC.report[1]=1 AND
AI_HUMAN.0="true". [app-mitm:2026-06-09-settings-sweep]
iotuserdata/{get,set}DeviceData is a general account-preference KV
store keyed by did+sign; other keys include AUTO_TIMEZONE.0
(app timezone auto-sync preference — NOT a mower CFG) and
prop.s_auto_upgrade (firmware auto-update preference).
[app-mitm:2026-06-09-settings-sweep]

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`

### ARM — `arm_alarm`

Arm/disarm the anti-theft alarm. Apk SET command at setArm sends
{m:'s', t:'ARM', d:{value}} to enable or disable the device alarm.
Distinct from ATA (Anti-Theft Alarm configuration) and STUN (Auto
Recharge After Extended Standby).

Likely overlaps with or complements the PIN lock system. Never directly
observed on g2408; the Dreame app exposes this via Security settings.
The payload value enum is unknown (0=disarm, 1=arm is the likely mapping).

**Open questions:**
- value enum: 0=disarm, 1=arm? Or is there a third state (e.g., partial-arm)?
- How does ARM interact with ATA and PIN? Are they layered or mutually exclusive?

**See also:** `apk: ioBroker.dreame/apk.md §SET-Befehle ARM setArm`

### CFG — `all_keys_cfg`

The all-keys CFG fetch — getCFG t:'CFG' returns the full 24-key
settings dict. This is the primary mechanism for reading all CFG
keys in a single call; individual keys are documented in the
cfg_keys section. Already wired via cfg_action.py.
Sample: full dict with 24 keys as documented in cfg_keys section.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §getX CFG`

### CHECK — `self_check_command`

Self-check / diagnostics trigger. Apk-documented SET command at L176631:
setSelfCheck sends {m:'s', t:'CHECK', d:{mode, status}} to launch the
self-diagnostic sequence. The result arrives on s2p58 (siid:2 piid:58)
as {d:{mode, id, result}}.

Never wired in the integration — the Dreame app's Self-Diagnosis flow
is the primary user surface. Not a GET (no read endpoint). The paired
subscribe slot is s2p58.

mode and status semantics for the d-field are unknown; presumably
mode selects which subsystem to check (motor, blades, sensors, etc.)
and status starts or cancels the check.

**Open questions:**
- What values does mode take for each subsystem check on g2408?
- Trigger from Maintenance → Self-Diagnosis in Dreame app and capture s2p58 result.

**See also:** `apk: ioBroker.dreame/apk.md §SET-Befehle CHECK setSelfCheck`

### CMS — `consumables_individual`

Consumables wear meters via the individual endpoint — same data as
CFG.CMS but wrapped in {value: [...]}. Not separately wired;
integration reads CMS data via the all-keys CFG fetch.
Sample: {value: [3084, 0, 0, -1]}.

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX CMS`

### DEV — `device_info`

Authoritative device identifiers. Wired in v1.0.0a76. sn is the
hardware serial (replaces flaky s1p5 cloud RPC), fw is the firmware
version, mac cross-checks the cloud device record's mac.
Transport: siid:2 aiid:50 {m:'g', t:'DEV'} — all four fields
(fw, mac, ota, sn) confirmed in one routed read alongside the OTA
flow [app-mitm:2026-06-16-firmware-ota].
ota flag: observed =1 — semantics SOFT [UNVERIFIED]: "OTA-capable
or update-pending — NOT the app Auto-update Firmware toggle" (values
disagree with the Auto-update setting). Sample: {fw: "4.3.6_0550",
mac: "00:00:00:00:00:00", ota: 1, sn: "G2408000TESTSN0000"}.

**Open questions:**
- ota field — NOT the Auto-update Firmware toggle; =1 observed; OTA-capable or update-pending [UNVERIFIED].

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX DEV`

### DOCK — `dock_state_and_position`

Dock state + map-frame position. Wired in v1.0.0a78.
connect_status:1 → mower currently in dock (authoritative — more
reliable than inferring from s2p1==6 CHARGING). in_region flips
depending on whether the dock sits inside the mowable polygon.
yaw matches compass bearing for the X-axis of the dock-relative
frame (unit unclear; near_yaw:1912 suggests possibly deci-degrees
but doesn't fit if yaw:112 is degrees). x,y = dock position in
map frame — NOT necessarily (0,0) despite earlier assumptions.
near_*/path_connect semantics still TBD.
Sample: {connect_status:1, in_region:0, x:151, y:23, yaw:112,
near_x:19, near_y:-3, near_yaw:1912, path_connect:0}.

**Open questions:**
- near_x/near_y/near_yaw — approach point for path-to-dock?
- yaw unit — degrees fits yaw:112 but near_yaw:1912 doesn't.

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX DOCK`

### IOT — `iot_connection_status`

IoT cloud connection alive flag (presumed). Not wired. Semantic
unconfirmed; status:True observed when integration is online.
Sample: {status: true}.
App-MITM 2026-06-09 confirms the app issues routed-get t=IOT;
response shape is [UNKNOWN — to capture] — see tools/probes/read_key_probe.py.

**Open questions:**
- IOT.status — does it flip to false on cloud disconnect or always true while reachable?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX IOT`

### LOCN — `dock_gps_origin`

Dock GPS origin (not real-time mower position). Wired.
Confirmed 2026-04-27: response shape is a 2-element pos array, NOT
the iobroker-doc-implied {lon, lat} dict. Default value when dock's
GPS origin has never been written via setLOCN is [-1, -1] (sentinel
for "not configured"). Stores the dock origin, not the live mower
coordinate. The Dreame app's "real-time Google Maps view" is computed
client-side from this stored origin plus the mower's local-frame xy
plus MapHeader.heading_to_north_deg.
Sample: {pos: [-1, -1]} (not configured).

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX LOCN`

### MAPD — `map_data`

APK-documented endpoint. The 3 cloud dumps so far all returned
r=-3. r=-3 is empirically NOT proof of feature absence — see
MISTA which flipped from r=-3/r=-1 to a successful payload
between dump 2 and dump 3. Downgraded to `decoded: hypothesized`
pending further evidence.

**Open questions:**
- Capture during a map-edit operation (zone create/delete) — MAPD may carry the chunked map blob.
- Test whether more cloud dumps over time produce a successful response (cf. MISTA).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MAPD`

### MAPI — `map_info`

APK-documented endpoint. The 3 cloud dumps so far all returned
r=-3. r=-3 is empirically NOT proof of feature absence — see
MISTA which flipped from r=-3/r=-1 to a successful payload
between dump 2 and dump 3. Downgraded to `decoded: hypothesized`
pending further evidence.
App-MITM 2026-06-09 confirms the app issues routed-get t=MAPI
(map index); response shape is [UNKNOWN — to capture] —
see tools/probes/read_key_probe.py.
Live probe 2026-06-09 bare GET returned r=-3 (mower docked, idle) —
endpoint requires a map_index or similar argument; the app sends args.

**Open questions:**
- Capture with explicit map_index argument once we identify the inbound parameter shape.
- Test with values from cfg_individual.MAPL (map IDs 0, 1) to probe what MAPI returns per map.
- Bare GET returns r=-3 — capture the args the app sends with MAPI to get a successful response.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MAPI`

### MAPL — `map_list`

One row per map_id, observed shape [[int×5], ...]. Confirmed by
2026-05-07 multi-map creation:

  2026-05-04..06 (single map):       [[0, 1, 1, 1, 0]]
  2026-05-07 after Map2 creation:   [[0, 0, 1, 1, 0], [1, 1, 1, 1, 0]]

The first column is the map_id (0-indexed). The second column flips
between maps when the active map changes — Map0's index-1 went 1→0
while Map1 was added with index-1=1, suggesting an "is_active" flag.
Indices 2–4 stayed unchanged (1, 1, 0) across both samples; their
semantic is undecoded.
App-MITM 2026-06-09 confirms the app issues routed-get t=MAPL (map
list) [dreame-app-implementation-guide-2026-06-09.md].
Live routed-get confirmed 2026-06-09: r=0, d=[[0,1,1,1,0],[1,0,1,1,0]]
(2-map device idle at dock; map0 index-1=1=active, map1 index-1=0=inactive;
indices 2–4 semantics still unknown).

**Open questions:**
- MAPL[i][2..4] semantics — observed [1, 1, 0] in both samples; needs map-edit captures (rename, set-mowing-direction, etc.) to discriminate.
- Does MAPL[i][1] update on dock-side map switch, or only on the active mowing map?
- Live probe 2026-06-09 d=[[0,1,1,1,0],[1,0,1,1,0]]: confirm map0=active(index-1=1), map1=inactive(index-1=0) interpretation by triggering an active-map switch.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MAPL`

### MAP_cache — `decoded_map_cache`

App-side decoded map cache stored in the iotuserdata KV store. Transport:
  GET :13267/dreame-user-iot/iotuserdata/getDeviceData
    {keys:["MAP.0","MAP.1",…]} → concat values = JSON array of maps
[app-mitm:2026-06-09-settings-sweep]
Each map object (one per mapIndex, both maps present) contains all
decoded zone/point data: mowingAreas (type:0), forbiddenAreas,
paths (type:1), spotAreas (type:3, shapeType:7), cleanPoints (type:6,
shapeType:5), cruisePoints (type:8, shapeType:5, +time/etime),
obstacles, contours (type:7), notObsAreas (type:10=ignore-obstacle,
shapeType:2, +angle). Per-element path:[{x,y}] in MM.
Per-map: md5sum, totalArea, boundary:{x1,y1,x2,y2}, name, mapIndex,
cut, merged, hasBack. [app-mitm:2026-06-09-settings-sweep]
Element type enum confirmed: 0=mowing, 1=path, 3=spot, 6=cleanPoint,
7=contour, 8=cruise/patrol, 10=ignore-obstacle. [app-mitm:2026-06-09-settings-sweep]
Integration shortcut: read MAP.* to get the fully-decoded map without
parsing the binary OSS blob (same per-map md5sum). Written by the app
when viewing/editing the map — may be stale or absent without a prior
app session. [app-mitm:2026-06-09-settings-sweep]
A read-side populated-check is needed to confirm the cache is present
when the app has not recently viewed the map. [UNKNOWN — to capture]

**Open questions:**
- Is MAP.* populated on a fresh mower that has never had the app open to the map view? Confirm presence/absence without the app.
- MAP.info key: what fields does it carry (length, version, timestamp)?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`

### MIHIS — `lifetime_mowing_aggregates`

Authoritative lifetime mowing aggregates matching the app's Work Logs
header exactly. Wired in v1.0.0a79/a80. area = total m², time =
total minutes, count = sessions. start = a firmware-hardcoded
sentinel (`1704038400` = 2023-12-31 00:00:00 UTC), confirmed
identical across 5 cloud dumps 2026-05-04..06 while count/area/time
evolved (34→39 / 4745→5094 / 3134→3462). It predates user ownership
by 2+ years and the mower hadn't been on a shelf that long
(battery >50% from box), so it is NOT a per-unit factory test
timestamp — almost certainly the firmware's MIHIS-aggregator epoch.
Not surfaced as first_mowing_date for that reason; the integration's
local-archive earliest-session date is used instead.
Sample: {area:4745, count:34, start:1704038400, time:3134}.

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MIHIS`

### MISTA — `mission_status`

Current mission status — cloud-poll mirror of s1p4 33-byte
telemetry's area counters. Decoded 2026-05-06 by cross-correlating
7 cloud dumps with 120 s1p4 33-byte MQTT frames during the run
that started 17:47 (MQTT log: probe_log_20260419_130434.jsonl).

Field mapping (confirmed Δ ≤ 4 cs across all 7 paired samples,
most exact at the same wallclock second):

  - total ≡ s1p4_33b_total_area_centiares (bytes 26-27, uint16_le, ÷100 → m²)
  - fin   ≡ s1p4_33b_area_mowed_centiares (bytes 29-30, uint16_le, ÷100 → m²)
  - prg   = round(fin × 10000 / total) — basis points (per-myriad), redundant
  - status[0] = [task_type, sub_state] — same enum as s2p56

Unit: centiares (= dm² = 0.01 m² = 100 cm²). For this lawn,
total = 33900 cs = 339 m².

Net info value: strict subset of s1p4 + s2p56. No new data over
MQTT subscription; useful only when MQTT is unavailable or one
wants a single-poll progress probe.

Pollability quirk: returns r=-1 / r=-3 when mower is fully idle
(2026-05-04, 2026-05-05 morning dumps). Returns r=0 with
all-zeros {fin:0, prg:0, status:[[1,-1]], total:0} in
primed-but-not-running state. Returns r=0 with live counters
only when actively mowing. Use as a "mower running?" probe.

Envelope: m:"r" (response method), q (link/RSSI proxy 70-80
observed during run), r:0 (OK code).

**Open questions:**
- Worth wiring as axis-4 sensor when MQTT unavailable? Otherwise redundant with s1p4 + s2p56.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MISTA`

### MITRC — `mission_track`

APK-documented endpoint (apk-named "Mission Track" — likely
carries live trail / completed track). The 3 cloud dumps so far
all returned r=-1. r=-1 is empirically NOT proof of feature
absence — sibling MISTA flipped from r=-1 to a successful
payload between dump 2 and dump 3. Downgraded to
`decoded: hypothesized` pending further evidence.
App-MITM 2026-06-09 confirms the app issues routed-get t=MITRC
with paged {idx, size} arguments [dreame-app-implementation-guide-2026-06-09.md];
response shape is [UNKNOWN — to capture] — see tools/probes/read_key_probe.py.
Live probe 2026-06-09 sent {idx:0, size:20} and received r=-1 (mower
docked, idle) — consistent with all cloud dumps; r=-1=idle, mid-run probe
required to confirm whether it returns data during an active mission.

**Open questions:**
- Capture during an active mowing session — MITRC is apk-named 'mission tracking', likely carries live trail.
- Test whether more cloud dumps over time produce a successful response (cf. MISTA).
- Paged {idx, size} args confirmed by app-MITM [dreame-app-implementation-guide-2026-06-09.md] — what is the page size and total page count for a typical session?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX MITRC`

### MPOS — `live_position`

Live mower position read via routed-get t=MPOS. App-MITM 2026-06-09
confirms the app issues action(siid:2,aiid:50) {m:'g', t:'MPOS'} to read
the live mower position [dreame-app-implementation-guide-2026-06-09.md].
Response shape CONFIRMED 2026-06-09: r=0, d={x:95, y:-4, yaw:0} — three
integer fields. Shape-confirmed (x, y, yaw as ints); units/frame not yet
cross-checked vs s1p4 live-position pushes.
Possible use: live-position fallback when s1p4 MQTT push is unavailable
[UNVERIFIED — not yet tested with MQTT disabled].

**Open questions:**
- Cross-check MPOS {x, y, yaw} units and frame against s1p4 live-position pushes — do they match directly or need coordinate transform?
- Confirm MPOS is a viable live-position fallback when s1p4 MQTT is down — test with MQTT disabled [UNKNOWN — to capture].

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`

### NET — `wifi_info`

Currently-associated AP and per-AP last-seen RSSI. Wired in
v1.0.0a77 — populates wifi_ssid / wifi_ip and seeds wifi_rssi_dbm
at startup before s1p1 byte[17] live RSSI takes over.
Sample: {current:"REDACTED-SSID", list:[{ip:"192.0.2.128", rssi:-66, ssid:"REDACTED-SSID"}]}.
App-MITM 2026-06-09 confirms action m:g t='NET' → {current:<ssid>,
list:[{ip, rssi(dBm), ssid}]}; rssi in dBm (e.g. -64 ≈ 70-80% signal).
[app-mitm:2026-06-09-settings-sweep]

**See also:** `custom_components/dreame_a2_mower/cloud_client.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX NET`

### OBS — `obstacle_data`

APK-documented endpoint. The 3 cloud dumps so far all returned
r=-3. r=-3 is empirically NOT proof of feature absence — see
MISTA which flipped from r=-3/r=-1 to a successful payload
between dump 2 and dump 3. Downgraded to `decoded: hypothesized`
pending further evidence.
App-MITM 2026-06-09 confirms the app issues routed-get t=OBS
(obstacles); response shape is [UNKNOWN — to capture] —
see tools/probes/read_key_probe.py.
Live probe 2026-06-09 bare GET returned r=-3 (mower docked, idle) —
endpoint requires args; the app likely sends additional arguments.

**Open questions:**
- Capture immediately after an AI-obstacle event (cloud-side; s1p53 is BLE-connection, NOT obstacle — find the real on-wire trigger).
- Cross-reference with AIOBS — both apk-described as obstacle endpoints, semantics distinct.
- Bare GET returns r=-3 — capture the args the app sends with OBS to get a successful response.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX OBS`

### PIN — `pin_status`

PIN / lift-lockout code. [app-mitm:2026-06-09-settings-sweep]
Write: {type:"auth"|"update", value:<int>} where value is the PIN
as a PLAINTEXT INTEGER (not hashed; protected by TLS only).
type="auth" = verify/authenticate with the existing PIN;
type="update" = set a new PIN value. (Actual PIN values redacted.)
Read (m:g → t:PIN): {result, time} — result:0=no-PIN-required event
pending; time=last lockout timestamp (0=none).
Not wired in the integration. Sample read: {result:0, time:0}.

**Open questions:**
- PIN.result and PIN.time — exact semantics of the lift-lockout flow TBD (when does result become non-zero?).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX PIN`

### PRE — `preference_endpoint`

APK-documented endpoint. The individual `getCFG t:'PRE'` fetch
returns r=-3 in all 3 cloud dumps so far, but the **all-keys**
CFG fetch (`getCFG t:'CFG'`) DOES return a `PRE` key. PRE is a
19-element write array (shape corrected 2026-06-09 — see
`cfg_keys.PRE`). [app-mitm:2026-06-09-settings-sweep] So the
data exists on g2408 — only the individual-target fetch path
doesn't work. This is a clear case where r=-3 isn't proof of
feature absence; it just means "this endpoint name doesn't
accept the individual-fetch form on this firmware". Could also
be the same data via two different paths, or a different
endpoint that happens to share a name. `decoded: hypothesized`
because we haven't confirmed individual-fetch will never work;
with only 3 dumps the sample is too small.
Live probe 2026-06-09 bare GET confirmed r=-3 at idle — consistent
with cloud dumps; individual-fetch form still not working.

**Open questions:**
- Reconcile with cfg_keys.PRE: same name, different access paths. Same data via different paths, or different endpoints with shared name?
- Test whether the individual-fetch starts working in later dumps (cf. MISTA flip).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX PRE`

### PREI — `preference_info`

Per-map PRE (preference) version counters. type:0 observed; ver is a
per-map version array — ver:[[map_id, version], ...]. Live sample
2026-06-09: {type:0, ver:[[0,123],[1,3]]} — map0 at PRE version 123,
map1 at version 3. Each increment presumably reflects a preference
write on that map (zone settings, mowing mode, etc.).
Not wired; the per-map version could seed a cache-invalidation check.
App-MITM 2026-06-09 confirms the app issues routed-get t=PREI
[dreame-app-implementation-guide-2026-06-09.md].

**Open questions:**
- PREI.type field — purpose unknown; observed always 0. Does it ever take a non-zero value?
- Confirm that ver[i][1] increments on each PRE write to map i — capture before/after a zone-settings change.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX PREI`

### PREP — `zone_preference_mode`

Per-zone General↔Custom mode switch. [app-mitm:2026-06-09-settings-sweep]
Write: action s2.a50 {m:'s', t:'PREP', d:{idx:<zone_0based>, value:0|1}}.
value=0 = General Mode (zone uses global PRE settings);
value=1 = Custom Mode (zone has its own PRE array, PRE[2]=zone_index).
Response: {type:1}. idx is 0-based zone index.
Entering Custom Mode first enables PREP, then PRE writes with PRE[2]=zone_index
apply the per-zone settings. Exiting Custom Mode writes PREP{idx,value:0}.
Per zone; not a global flag. [app-mitm:2026-06-09-settings-sweep]

**Open questions:**
- PREP.idx with multiple zones: is idx 0-based zone index or zone id from MAPL? With 1 zone observed, idx=0 is unambiguous; confirm with 2+ zones. [UNKNOWN — to capture]

**See also:** `custom_components/dreame_a2_mower/protocol/cfg_action.py`, `docs/research/inventory/generated/g2408-canonical.md § CFG keys`, `apk: ioBroker.dreame/apk.md §setX PRE`

### REMOTE — `sim_4g_status`

4G SIM card status read. App-MITM 2026-06-09 confirmed via
action(siid:2, aiid:50) {m:'g', t:'REMOTE'} → {activeTime, cardId(ICCID),
expiredTime, leftDays}. [app-mitm:2026-06-09-settings-sweep]
Surfaced in the app's Connections / Link Module page. cardId is the
SIM ICCID — the same ICCID reported as card4G in the GPS getRecords
endpoint, confirming they share the same 4G SIM. [app-mitm:2026-06-09-settings-sweep]
leftDays seen as 894 while the app displayed 839 (different calculation
method). [app-mitm:2026-06-09-settings-sweep]
Wired in the integration: 4 diagnostic SIM sensors (cardId/activeTime/expiredTime/leftDays).
[app-mitm:2026-06-09-settings-sweep]

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`

### RGBPSTA — `led_state`

LED state read via routed-get t=RGBPSTA. App-MITM 2026-06-09 confirms
the app issues action(siid:2,aiid:50) {m:'g', t:'RGBPSTA'} to read the
LED/indicator-light state [dreame-app-implementation-guide-2026-06-09.md].
Live probe 2026-06-09 bare GET (also probed with "id":-1) returned r=-3
(mower docked, idle) — endpoint requires args or a different call pattern;
the app likely sends additional arguments. Response shape still
[UNKNOWN — to capture].

**Open questions:**
- Decode the RGBPSTA response shape; does it carry {r, g, b, brightness} or an enum mode?
- Is RGBPSTA read-write (is there a corresponding SET path)?
- Bare GET (and id:-1 variant) returns r=-3 — capture the args the app sends with RGBPSTA to get a successful response.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`

### RPET — `rain_protection_end_time`

Possibly schedule repeat-end timestamp or rain-protection-end
timestamp (0 = no end / not active). Not wired.
Sample: {endTime: 0}.

**Open questions:**
- RPET.endTime — rain-protection-end unix timestamp or schedule repeat-end? Needs non-zero capture.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`, `apk: ioBroker.dreame/apk.md §getX RPET`

### SCHDDV3 — `schedule_data_v3_write`

Schedule data write — chunked base64 protobuf blob. Part of a 3-key
write transaction (SCHDDV3 + SCHDIV3 + SCHDSV3) tied by shared v =
millisecond timestamp txn-id. Transport: action(siid:2, aiid:50)
{m:'s', t:'SCHDDV3', d:{s:<offset>, l:<len>, d:"<chunk>", v:<txn>}}.
[app-mitm:2026-06-09-settings-sweep]
Chunked by offset s; reassemble all chunks → JSON array
[seasonIdx, enabled, "<name>", "<base64 blob>"]. The base64 blob is
the protobuf that protocol/schedule_decode.py already decodes for the
read path — the encode direction + this transport is what Phase E adds.
[app-mitm:2026-06-09-settings-sweep]
Example (Spring/Summer, Thu 12:04 edge entry): 54-byte blob with
repeating edaa07*/edaa09* groups = per-entry records (day/time/task).
Protobuf field layout: diff known-schedule edits to map fields —
[UNKNOWN — to capture]. [app-mitm:2026-06-09-settings-sweep]
See also: SCHDIV3 (length descriptor), SCHDSV3 (slot enable/summary).

**Open questions:**
- Protobuf field layout of the base64 blob: diff one-day, one-time, one-task edits to map each wire field to its semantic.

**See also:** `custom_components/dreame_a2_mower/protocol/schedule_decode.py`, `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`

### SCHDIV3 — `schedule_index_v3_write`

Schedule length/index descriptor write. Part of the 3-key write
transaction with SCHDDV3 and SCHDSV3 (shared v = ms txn-id). Transport:
action(siid:2, aiid:50) {m:'s', t:'SCHDIV3', d:{i, l:<total len>, v:<txn>}}.
[app-mitm:2026-06-09-settings-sweep]
l = total reassembled length of the SCHDDV3 payload in bytes. Sent
alongside or after the SCHDDV3 chunks so the receiver knows when
reassembly is complete. [app-mitm:2026-06-09-settings-sweep]
i semantics [UNKNOWN — to capture]: likely the schedule slot index or
chunk sequence number. [app-mitm:2026-06-09-settings-sweep]

**Open questions:**
- SCHDIV3.i semantics: slot index, chunk count, or sequence number?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`

### SCHDSV3 — `schedule_slot_enable_v3`

Per-seasonal-slot enable/summary write. Part of the 3-key write
transaction with SCHDDV3 and SCHDIV3 (shared v = ms txn-id). Transport:
action(siid:2, aiid:50) {m:'s', t:'SCHDSV3', d:{i, v, s:[enabled, flag]}}.
[app-mitm:2026-06-09-settings-sweep]
i = schedule slot: 0 = Spring/Summer, 1 = Autumn/Winter.
s[0] = slot enabled (0=disabled, 1=enabled; confirmed by live toggle
Spring/Summer disabled→enabled = s[0] 0→1). [app-mitm:2026-06-09-settings-sweep]
s[1] = second flag, seen as 0; semantics [UNKNOWN — to capture].
v = packed integer encoding schedule days/times. Seen values: 18696,
32923, 65535 (0xFFFF). Bit layout [UNKNOWN — to capture]: needs
per-day/per-time isolated edits to decode. [app-mitm:2026-06-09-settings-sweep]
Also emitted standalone (without full SCHDDV3/SCHDIV3) when toggling
slot enabled/disabled only. [app-mitm:2026-06-09-settings-sweep]

**Open questions:**
- SCHDSV3.v packed-int bit layout: which bits encode day-of-week and which encode time? Decode by editing one day then one time in isolation.
- SCHDSV3.s[1] semantics: always 0? Or set in some schedule states?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`

### SCHDTV3 — `schedule_v3`

Schedule v3 endpoint. Live routed-get confirmed 2026-06-09: r=0, d=2
(scalar integer). Semantics unknown — could be the schedule-config
version counter, the number of active schedule entries, or a feature-
flag. Full schedule structure is NOT returned by bare GET [UNKNOWN —
the app may send args to retrieve the full list, or GET returns only
a version/count scalar and the schedule list is pushed separately].
App-MITM 2026-06-09 confirms the app issues action(siid:2,aiid:50)
{m:'g', t:'SCHDTV3'} [app-mitm:2026-06-09-settings-sweep].
The WRITE transport is a 3-key transaction using SCHDDV3/SCHDIV3/SCHDSV3
(see those cfg_individual entries); this key is the read-side scalar only.
[app-mitm:2026-06-09-settings-sweep]

**Open questions:**
- Decode SCHDTV3 scalar d=2 — is it the schedule-config version, the count of active entries, or a feature flag? Correlate with add/delete schedule operations.
- Does the app pass args to SCHDTV3 GET to retrieve the full schedule list, or is the full list pushed separately?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § cfg_individual endpoints`

### WINFO — `app_weather_info`

App-to-device weather push. Apk SET command sends the current app-side
weather observation to the mower firmware so it can make local rain-
protection decisions without a separate cloud weather lookup. Distinct
from WRP (rain protection settings) and the s2p2=56 rain-protection-
active signal.

No corresponding GET; this is a one-way app→device push. The appWeather
payload shape is not fully documented in the apk.

Never directly observed on g2408; fired by the app automatically when
it detects rain conditions or on a periodic sync interval.

**Open questions:**
- What is the appWeather payload shape? Temperature, precipitation, forecast array?
- How does firmware use appWeather vs internal rain sensor?

**See also:** `apk: ioBroker.dreame/apk.md §SET-Befehle WINFO setAppWeather`

## Heartbeat (s1p1) bytes

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p1_b0 | frame_delimiter_start | byte (likely 0xCE) | WIRED |  |
| s1p1_b1_bit0 | bumper_hit | single bit | WIRED | bool (×1.0) |
| s1p1_b1_bit1 | drop_tilt | single bit | WIRED | bool (×1.0) |
| s1p1_b2_bit1 | lift | single bit | WIRED | bool (×1.0) |
| s1p1_b3_bit7 | lift_lockout_pin_required | single bit | WIRED | bool (×1.0) |
| s1p1_b4 | human_presence_detection | byte | WIRED | byte (×1.0) |
| s1p1_b5 | offdock_event_flags | byte (sparse bitfield) | SEEN-UNDECODED |  |
| s1p1_b6_bit3 | charging_paused_batt_temp_low | single bit | WIRED | bool (×1.0) |
| s1p1_b7 | state_transition_marker | byte | WIRED | byte (×1.0) |
| s1p1_b8 | sparse_context_flags | byte (sparse bitfield) | SEEN-UNDECODED |  |
| s1p1_b9 | mow_start_pulse | byte | WIRED | byte (×1.0) |
| s1p1_b10_bit1 | safety_alert_active | single bit | WIRED | bool (×1.0) |
| s1p1_b10_bit7 | batt_temp_low_latched | single bit | WIRED | bool (×1.0) |
| s1p1_b11_b12 | battery_pct_and_charge_flag | byte[11]=battery; byte[12]=counter+flag (NOT a u16) | WIRED | % (×1.0) |
| s1p1_b13 | locomotion_state_b13 | byte (state enum) | SEEN-UNDECODED | byte (×1.0) |
| s1p1_b14 | locomotion_state | byte (state enum) | WIRED | byte (×1.0) |
| s1p1_b15 | substate_b15 | byte (small enum / bitfield) | SEEN-UNDECODED | byte (×1.0) |
| s1p1_b16 | constant_0x80 | byte (constant) | DECODED-UNWIRED |  |
| s1p1_b17 | wifi_rssi_dbm | byte (signed int8) | WIRED | dBm (×1.0) |
| s1p1_b18 | cellular_signal | byte (coarse cellular-signal metric) | SEEN-UNDECODED | raw (×1.0) |
| s1p1_b19 | frame_delimiter_end | byte (likely 0xCE) | WIRED |  |

### s1p1_b0 — `frame_delimiter_start`

Start-of-frame delimiter. Hypothesised 0xCE by analogy with
s1p4 telemetry framing; verify against probe-log heartbeat
captures.

**Open questions:**
- Cross-check b[0] = 0xCE against probe-log heartbeat captures.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py:70`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b1_bit0 — `bumper_hit`

Bumper hit — confirmed 2026-04-30 19:37:13 against the app's
"Bumper error" notification. Important: this event has no
corresponding s2p2 transition — it surfaces only via this bit.
Wire mask: byte[1] & 0x01.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b1_bit1 — `drop_tilt`

Drop / Robot tilted — set while the mower is held off-level.
Confirmed 2026-04-30 19:37:05 against the app's "Robot tilted"
notification; cleared at 19:37:13 when the mower was set back
down. Wire mask: byte[1] & 0x02.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b2_bit1 — `lift`

Lift / Robot lifted — confirmed 2026-04-30 19:37:57 against the
app's "Robot lifted" notification. Wire mask: byte[2] & 0x02.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b3_bit7 — `lift_lockout_pin_required`

Lift lockout / PIN required (the app calls this "Emergency stop
is activated"). Set on lift OR top-cover-open; cleared ONLY by
typing the PIN on the device. Re-confirmed 2026-05-04 across a
5-test controlled series: the bit clears ONLY on PIN entry; lid
close, set-down, or any other physical-state restoration does NOT
clear it. Smoking-gun was the dock-only test (lid open → lid
close, NO PIN typed) where the bit stayed asserted after the lid
closed. Then a follow-up test where the user opened lid → typed
PIN → closed lid showed byte[3] cleared at PIN time (lid still
open), confirming the trigger is the PIN, not the lid.
Wire mask: byte[3] & 0x80.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b4 — `human_presence_detection`

Human-presence-detection pulse. Pulses 0x00 → 0x08 → 0x00
lasting ~0.8 s during a human-presence-detection event.
Evidence: session 2 (2026-04-18) showed byte[4]=0x08 exactly
twice at 21:04:39.580 and 21:04:40.210; the user confirmed the
Dreame app raised a human-in-mapped-area alert at that same
moment. Byte is 0x00 at all other times across the whole session.
Single-event datapoint — reproduce before relying on it.

**Open questions:**
- Single-event datapoint. Reproduce with a controlled human-in-zone test to confirm 0x08 is the canonical sentinel value.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b5 — `offdock_event_flags`

Sparse off-dock event/error bitfield. 0x00 in 67,563/67,677 corpus
heartbeats; nonzero ONLY while off-dock (charging=0), never docked.
Observed bits (corpus 2026-05-31):
  - bit 4 (0x10) — associates with error/pause: dominates state=4
    ("Paused due to errors", 70/90 frames) and appears in state=2.
  - bit 1 (0x02) — transient during mowing/returning (state 1/5).
  - 0x12 = both bits together.
decoded: partial — the bit→event mapping is correlational (no
controlled trigger yet); bit 4 ≈ "error/pause active" is the
strongest read.

**Open questions:**
- Trigger a controlled error-pause and confirm byte[5] bit4 sets; identify bit1's event.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b6_bit3 — `charging_paused_batt_temp_low`

Charging paused — battery temperature too low. Asserted while
the mower is docked but refusing to charge because the battery
is below its safe-charge threshold; clears when the cell warms
up (or momentarily, while the charger retries). Evidence:
2026-04-20 the Dreame app raised "Battery temperature is low.
Charging stopped." at 06:25 and 07:54; at 06:25:42 byte[6] went
0x00 → 0x08 coincident with s2p2 dropping from 48 to 43; at
07:54:39 byte[6] flipped 0x08 → 0x00 → 0x08 → 0x00 while the
mower bounced STATION_RESET ↔ CHARGING_COMPLETED. Cleared to 0
once charging resumed around 07:58 and stayed 0 through the
following mowing session. Wire mask: byte[6] & 0x08.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b7 — `state_transition_marker`

State transition marker. Values: 0=idle, 1 or 4 = state
transitions. Exact semantics of 1 vs 4 not yet pinned down.
Decoded by the integration as state_raw on the Heartbeat
dataclass.

**Open questions:**
- Distinguish the semantic difference between value 1 and value 4; correlate with specific s2p1/s2p2 transitions.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b8 — `sparse_context_flags`

Sparse context flag byte. 0x00 in 66,074/67,677 corpus heartbeats.
Observed bits (corpus 2026-05-31):
  - bit 0 (0x01) — appears predominantly DOCKED (state 13 charge-
    complete: 881, state 6 charging: 317); a docked/settled context.
  - bit 7 (0x80) — appears during MOWING (state 1: 207) and returning;
    a motion/active context transient.
  - 0x81 = both (only seen docked, state 13).
decoded: partial — bit semantics are correlational only. NB: distinct
from byte[4] (the confirmed 0x08 human-presence pulse) and byte[5]
(off-dock error flags).

**Open questions:**
- Pin byte[8] bit0 (docked-context) and bit7 (mowing-context) to specific transitions.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b9 — `mow_start_pulse`

0/64 pulse at mow start. Pulses from 0 to 64 and back to 0
at the beginning of a mowing session. Exact timing relative to
s2p2/s2p1 transitions not yet pinned down. Single-class
datapoint.

**Open questions:**
- Is value 64 specific to mowing start or does it appear in other session types (BUILDING, edge)?

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b10_bit1 — `safety_alert_active`

One-shot active-alert flag (paired with the Dreame app's
"Emergency stop activated" push notification + the mower's red
LED + voice prompt). Pinned down 2026-05-04 across a 5-test
controlled series: sets ~1 s after byte[3] bit 7 sets (shortly
after the safety event); self-clears 30–90 s later regardless
of state — including while the lid is still open and PIN has not
been entered. Variable timer (4/18/33/53/77 s observed) suggesting
it is reset by sensor activity or an internal alert-window timer,
not a fixed value. NOT a "PIN-acceptance secondary latch" as the
earlier hypothesis claimed — the smoking-gun was the dock-only
test where byte[10] cleared at 20:20:24 with the lid still open
and no PIN ever typed. Independent of the byte[3] bit 7 lockout
(which only clears on PIN). The base 0x80 bit (latched low-temp
flag) stays asserted independently; only bit 1 is the alert.
Surfaced as binary_sensor.safety_alert_active.
Wire mask: byte[10] & 0x02.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b10_bit7 — `batt_temp_low_latched`

Latched battery-temp-low flag. Set after the first low-temp
charging-pause event of the day; remains set for the rest of
the session regardless of subsequent charge-resume. Observed to
set at 06:25:42 together with byte[6]=0x08 and remain 0x80
through the 07:54 re-trigger, the 07:58 mowing start, and every
subsequent heartbeat in the session. Normal value at a cold-boot
idle charge is 0x00 (confirmed: 2026-04-19 13:04–14:29 all show
byte[10]=0). Best guess: "battery-temp-low event has occurred
since last power-cycle" maintenance flag. Cleared state
unconfirmed (reproduce with a fresh boot after a warm day).
Wire mask: byte[10] & 0x80.

**Open questions:**
- When does this bit clear? Hypothesis is power-cycle reset — needs a warm-day fresh-boot capture to confirm.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b11_b12 — `battery_pct_and_charge_flag`

byte[11] = battery level + charge flag (corpus-decoded 2026-05-31,
RETRACTS the prior "uint16_le monotonic counter [11-12]" reading):
  - bits 0-6 (byte[11] & 0x7F) = battery percent. Matches s3p1
    battery EXACTLY in 99.3% of 67,677 corpus heartbeats
    (Pearson +0.9992). =100 docked-full (state 13), drains 100→low
    while mowing, =14-15 when returning on low battery (state 5).
  - bit 7 (byte[11] & 0x80) = "actively charging" flag. Tracks s3p2
    charging==1 exactly (set 10124/10172 while charging; clear when
    discharging or charge-complete). So 228 = 0x80|100 = charging at
    100%, 222 = charging at 94%, etc.

byte[12] is a SEPARATE field, NOT the high byte of a u16 with byte[11]:
  - high nibble (byte[12] >> 4) = a 4-bit rolling heartbeat counter
    (uniform 0-15, increments +1 per emission → consecutive byte
    deltas cluster on +16/+32). This is the actual per-frame counter
    the retracted reading was reaching for.
  - low nibble (byte[12] & 0x0F) = a sub-flag, almost always 1 or 5
    (differ by bit 2); meaning TBD.

NOTE: heartbeat.py:74 still reads `struct.unpack_from("<H", data, 11)`
as `counter` = battery | (byte[12]<<8). It changes every frame (byte[12]
high nibble ticks) so dedup happens to work, but the field is
semantically battery+counter, not a clean monotonic u16. Safe to leave
the code; this entry corrects the understanding.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py:74`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b13 — `locomotion_state_b13`

Mode-correlated state byte; a likely companion to byte[14]
locomotion_state. Corpus distribution (_s1p1.py, 66,083 frames /
9 logs) by s2p1 mode:
  - mode 13 (charge-done) → 255 (92%)
  - mode 6 (docked) → 36 (59%) / 255 (35%)
  - mode 1 (mowing) → 35 (95%)
  - mode 5 (returning) → 40 (68%) / 255 (31%)
  - mode 2 (idle) → 255 (60%) / 40 (19%) / 37 (13%)
  - mode 11 (building) → spread 17-27 (19/20/24/25…)
Not yet pinned to a clean enum, but clearly state-bearing rather
than noise (19 corpus values, tightly mode-segregated).

**Open questions:**
- Characterise byte[13] jointly with byte[14] — are they a 16-bit field or two independent state bytes? Building mode's 17-27 spread suggests a per-phase counter during map-build.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b14 — `locomotion_state`

Locomotion / activity-state byte (NOT a boot sequence — see
2026-05-30 retraction). Corpus-correlated with the s2p1 mode over
66,083 heartbeats across 9 logs:
  - mode 6/13 (charging / charge-done, i.e. DOCKED) → 0 (95-97%)
  - mode 1 (mowing) → 135 = 0x87 (95%); mode 11 (building) → 135 (86%)
  - mode 5 (returning) → spread of 0x80-range values
    (148/143/139/140/141/136…)
  - mode 2 (idle off-dock) → 132/135/139/143 (0x80-range)
  - undock transition → transient 64 → 68 → 4 → 5 → 7 before settling
    to 135 once the mower is moving
Reading: bit 7 (0x80) ≈ "off-dock / operating" (set in mowing,
returning, idle; clear when docked=0 and during the early undock
transients). The low bits look like an activity sub-state (mowing
pins to 0x87; returning steps through several 0x8x values). The
"0→64→68→4→5→7→135 sequence" the prior entry called a boot machine
is actually the undock→operating transition — i.e. the reorient
sub-state walk — and runs on EVERY undock, with docked steady-state
0 (not 135).

**Open questions:**
- Enumerate the 0x80-range sub-states: does the low nibble during 'returning' (136/139/140/141/143/148) step monotonically through return phases, or is it a flag field? Capture a labelled return-to-dock.
- byte[13] (undocumented, 19 corpus values) is ALSO mode-correlated (255 when docked/charge-done, 35 mowing, 40 returning, building-specific 17-27) — likely a companion state byte to [14]; characterise together.
- Maintenance/fault sub-states extend the 0x80 range: a 2026-05-30 at-point maintenance (deliberate tilt + lid-open + PIN) drove byte[14] 132→164 (0xA4) while the tilt/PIN-lockout was asserted (s2p2=1 tilted, 23 emergency_stop, 73 top_cover_open), then back to 132 on PIN clear — so 164 = a tilted/locked-out at-point sub-state. Consistent with 'activity+condition state', not boot.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b15 — `substate_b15`

State/sub-phase byte — corpus-characterised (_s1p1.py, 66,140 frames /
9 logs) but NOT cleanly pinned to an enum. Distribution by s2p1 mode:
  - mode 13 (charge-done) → 0 (94%); mode 6 (docked) → 0 (59%) / 1 (31%)
  - mode 1 (mowing) → 1 (46%) / 0 (41%) / 5 (6%) / 6 (3%)
  - mode 5 (returning) → 0 (48%) / 54 (31%) / 1 (17%)
  - mode 2 (idle) → 0 (67%) / 54 (23%)
  - mode 11 (building) → 1 (58%) / 4 (28%) / 17 / 20
Transition behaviour (raw undock frames): 0 docked → 54 at undock-onset
→ 18 during the reorient → small values in steady state. The 17/18/20/54
values (0x11/0x12/0x14/0x36) suggest a bitfield rather than a sequential
enum; needs a labelled capture to separate the bits. State-bearing, not
noise; sits alongside byte[13]/byte[14] as the s1p1 state block.

**Open questions:**
- Is byte[15] a bitfield? The {17,18,20,54}=0x11/0x12/0x14/0x36 values hint at bit combinations. Capture labelled idle/returning/reorient transitions to separate the bits, and check whether [13][14][15] form one multi-byte state block.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b16 — `constant_0x80`

Constant 0x80 (128). Held 128 in ALL 67,677 corpus heartbeats
(distinct value count = 1) across every state, charging mode, and
session. Most likely a fixed framing/format byte or a hard-wired
reserved flag, not a live signal. Corpus-checked 2026-05-31.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b17 — `wifi_rssi_dbm`

WiFi RSSI in dBm as a signed byte (b if b<128 else b−256).
Tracks the live signal to the currently associated AP. Confirmed
2026-04-30 20:09–20:16 by toggling APs and watching the app's
5-stage signal line move in lockstep: 0xBD = −67 dBm ("Strong"),
0xA8 = −88 dBm ("Weak" after killing closest AP and the mower
fell back to a more distant one), 0xC0 = −64 dBm (snapped onto
closer AP after restoration), 0x9F = −97 dBm (briefly during
dropout). No special "disconnected" sentinel observed — value
just keeps tracking whatever the radio detects.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b18 — `cellular_signal`

Cellular (LTE) signal strength — a SEPARATE radio from byte[17] WiFi
RSSI, with its own 4-bar gauge in the Dreame app (the g2408 has an LTE
modem; cellular is independent of WiFi). User-identified + live-confirmed
2026-05-31.

Evidence it is cellular (not WiFi):
  - INDEPENDENCE / stability: byte[18] changes in only 2.2% of frame-to-
    frame steps (6 distinct values / 67,714 frames) vs byte[17] WiFi RSSI
    at 62.1% (44 distinct) — 28× more stable, matching "cellular
    fluctuates much less than WiFi" (user).
  - LIVE LOCKSTEP: on 2026-05-31 13:20, while the app's cellular gauge
    read 1 of 4 bars (poor, back-yard), byte[18] held flat at 186 across
    consecutive heartbeats while byte[17] WiFi jittered (−67/−68 dBm).
    So the dominant value 186 == the current ~1-bar reading.
  - Distribution: 186 (90.7%), 196 (9.2%, more common off-dock: 5849 vs
    316 docked), rare 180/203; positive 126/127 appear ONLY docked — a
    no-signal / N/A sentinel.

UNIT UNCERTAIN: a naive signed-int8 read makes 186 = −70 dBm, but −70 dBm
is normally *decent* cellular yet the gauge shows 1/4 bars — so either the
modem's bar thresholds are conservative or byte[18] is a raw / RSRP-style
scale, not plain dBm. The byte↔bars mapping is the empirical anchor; the
physical unit is not yet pinned.

**Open questions:**
- Pin the byte→bars thresholds (and the physical unit) by sampling byte[18] at each of the 4 app bar-levels — e.g. move the mower/dock through good→poor cellular spots and record byte[18] at each bar count.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

### s1p1_b19 — `frame_delimiter_end`

End-of-frame delimiter. Hypothesised 0xCE by analogy with
s1p4 telemetry framing; verify against probe-log heartbeat
captures. Confirmed by the decode_s1p1 guard in heartbeat.py
which checks data[-1] == FRAME_DELIMITER (0xCE).

**Open questions:**
- Cross-check b[19] = 0xCE against probe-log heartbeat captures.

**See also:** `custom_components/dreame_a2_mower/protocol/heartbeat.py`, `docs/research/inventory/generated/g2408-canonical.md § Heartbeat (s1p1) bytes`

## Telemetry (s1p4) fields

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p4_8b_delim_start |  | byte (0xCE) | WIRED |  |
| s1p4_8b_x_mm |  | 20-bit signed; SAME decoder as 33-byte x_mm | WIRED | m (×0.001) |
| s1p4_8b_y_mm |  | 20-bit signed; SAME decoder as 33-byte y_mm | WIRED | m (×0.001) |
| s1p4_8b_static_b5 |  | byte (0x00) | WIRED |  |
| s1p4_8b_heading_byte |  | byte | WIRED | degrees (×1.4117647) |
| s1p4_8b_delim_end |  | byte (0xCE) | WIRED |  |
| s1p4_10b_delim_start |  | byte (0xCE) | WIRED |  |
| s1p4_10b_x_cm |  | int16_le | WIRED | m (×0.01) |
| s1p4_10b_y_mm |  | int16_le | WIRED | m (×0.001) |
| s1p4_10b_static_b5 |  | byte (0x00) | WIRED |  |
| s1p4_10b_unknown_6_7 |  | uint16_le (observed 5570 = 0x15C2) | SEEN-UNDECODED |  |
| s1p4_10b_static_b8 |  | byte (0x00) | SEEN-UNDECODED |  |
| s1p4_10b_delim_end |  | byte (0xCE) | WIRED |  |
| s1p4_33b_delim_start |  | byte (0xCE) | WIRED |  |
| s1p4_33b_x_mm |  | 20-bit signed; x = (b[2]<<28 | b[1]<<20 | b[0]<<12) >> 12 | WIRED | m (×0.001) |
| s1p4_33b_y_mm |  | 20-bit signed; y = (b[4]<<24 | b[3]<<16 | b[2]<<8) >> 12 | WIRED | m (×0.001) |
| s1p4_33b_static_b5 |  | byte (0x00) | WIRED |  |
| s1p4_33b_sequence |  | uint16_le | WIRED |  |
| s1p4_33b_start_index |  | uint24_le | WIRED |  |
| s1p4_33b_phase_raw |  | uint8 | WIRED |  |
| s1p4_33b_static_b9 |  | byte (0x00) | WIRED |  |
| s1p4_33b_delta_1 |  | 2 × int16_le (dx1, dy1) | WIRED |  |
| s1p4_33b_delta_2 |  | 2 × int16_le (dx2, dy2) | WIRED |  |
| s1p4_33b_delta_3 |  | 2 × int16_le (dx3, dy3) | WIRED |  |
| s1p4_33b_flag_22 |  | byte | WIRED |  |
| s1p4_33b_flag_23 |  | byte | WIRED |  |
| s1p4_33b_distance_dm |  | uint16_le; value / 10 → m | WIRED | m (×0.1) |
| s1p4_33b_total_area_centiares |  | uint16_le; counter / 100 → m² | WIRED | m² (×0.01) |
| s1p4_33b_static_b28 |  | byte (0x00 on small lawns) | WIRED |  |
| s1p4_33b_area_mowed_centiares |  | uint16_le; counter / 100 → m² | WIRED | m² (×0.01) |
| s1p4_33b_static_b31 |  | byte (0x00 on small lawns) | WIRED |  |
| s1p4_33b_delim_end |  | byte (0xCE) | WIRED |  |

### s1p4_8b_delim_start — ``

Start-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:180`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_8b_x_mm — ``

X position in the dock-relative coordinate frame (map-scale mm). Shared
decoder with the 33-byte frame. During idle/docked the value converges
near 0. During BUILDING sessions it tracks live mower X position as the
mower traces the new boundary.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_8b_y_mm — ``

Y position in the dock-relative coordinate frame (map-scale mm). Shared
decoder with the 33-byte frame. Leg-start preamble frames carry a
near-0xFFFF sentinel Y (the mower hasn't localised yet). BUILDING
frames carry live real Y coordinates as the mower traces the boundary.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_8b_static_b5 — ``

Static 0x00 byte. Present in all 8-byte captures including BUILDING mode.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:162`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_8b_heading_byte — ``

Mower heading in the dock-relative frame. Confirmed 2026-04-24 with
heading_correlate.py: compared 5,586 consecutive-pair samples from
probe_log_20260419_130434.jsonl — computed motion direction atan2(dy,dx)
vs byte[6]/255*360 decode. Result: median angular error 13°, 54% of
samples under 15° error, 67% under 30°. Clear central peak at 0-14°;
diffuse tail at pivot turns where atan2 is ill-conditioned (position
barely moves between frames). Leg-start preamble values (123-125) are
consistent with "~180° = mower facing away from dock while leaving".
Surfaced as sensor.heading_deg.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`, `apk: ioBroker.dreame/apk.md §parseRobotPose (angle field)`

### s1p4_8b_delim_end — ``

End-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:180`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_delim_start — ``

Start-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:180`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_x_cm — ``

X position at the moment the zone-save event fired. Likely same
dock-relative coordinate frame as the 8/33-byte variants. Single
capture only (2026-04-20 17:03:41, sample byte sequence
[0xCE, 139, 0, 240, 77, 0, 194, 21, 0, 0xCE]).

**Open questions:**
- Does [1-2] use int16_le or the same 20-bit packed decode as the 8/33-byte frames? Only 1 sample — needs more BUILDING captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:184`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_y_mm — ``

Y position at the zone-save moment. Sample value 19952 mm is consistent
with the mower being on the far side of the lawn during BUILDING.
Decoder provisional — only one capture available.

**Open questions:**
- Verify y decode on a second BUILDING capture.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:184`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_static_b5 — ``

Static 0x00 byte. Observed 0x00 in the single capture.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:184`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_unknown_6_7 — ``

Unknown uint16 at the zone-save moment. Observed 0x15C2 = 5570 on
2026-04-20 in the single capture. Candidates: sequence counter for the
new polygon's perimeter points, zone-id assigned by the firmware, or
a general capture-sequence counter. Needs more BUILDING sessions to
disambiguate.

**Open questions:**
- Decode bytes [6-7] — point count? zone id? sequence counter? Correlate with number of 8-byte frames in the preceding BUILDING session.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_static_b8 — ``

Static 0x00 byte. Observed 0x00 in the single capture.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b_delim_end — ``

End-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:180`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_33b_delim_start — ``

Start-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:193`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_x_mm — ``

X position in the dock-relative coordinate frame (map-scale mm).
Origin (0,0) = charging station. +X points toward the house (mower's
nose direction when docked); -X points into the lawn. X is in cm on
the old int16 layout; the 20-bit decode and ×10 scaling unifies both
axes to mm. See §3.1 coordinate-frame notes. apk-corrected decoder
landed in alpha.98.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_33b_y_mm — ``

Y position in the dock-relative coordinate frame (map-scale mm).
±Y is perpendicular to the X axis (left/right when facing the house).
Y-axis calibration: tape-measure-verified 0.625 factor (encoder
over-reports by ~1.6×); factor is per-install configurable. Confirmed
alpha.98 via full probe-corpus replay (14.7k frames).

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotPose`

### s1p4_33b_static_b5 — ``

Static 0x00 byte between the packed XY block and the sequence field.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:188`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_sequence — ``

Path-point sequence number (lower 16 bits of the uint24 start_index at
bytes [7-9]). Frame-over-frame increments monotonically; used by the
integration to detect skipped frames. Part of the start_index field
documented in apk §parseRobotTrace — the full counter is at bytes [7-9].

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_start_index — ``

Path-point sequence counter (uint24 LE). Confirmed on g2408: one-off
script over 14,684 consecutive-frame transitions found 5,796 increments
vs only 10 decrements; 10 decrements all look like new-session resets.
Zero INT24-MAX saturation. Distribution concentrated in 0..10k per
session. Matches apk §parseRobotTrace "uint24 LE path-point sequence
id" exactly.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

### s1p4_33b_phase_raw — ``

Index into the firmware's pre-planned job sequence. NOT a mowing/transit
enum — confirmed 2026-04-18 via live trajectory across a 3-hour session.
Phase advances monotonically through the plan; once a value is done it
never repeats in the same session.

Session 2 observations: phase 1=dock transit corridor, 2=zone area-fill
(west), 3=zone area-fill (middle), 4=zone area-fill (east), 5=edge mow,
6-7=next edge/zone passes. phase=15 observed in last 23 frames of
2026-04-20 full-run (post-complete return, counters frozen).

NOT zone-aligned (2026-06-16): phase_raw indexes whole task-plan ENTRIES
whose boundaries do NOT line up with zones. On a 2-zone Map2 all-area mow,
phase_raw=1 SPANNED the zone1-edge AND all of zone-2 while s2p56 had already
flipped zone-2 active — so the per-zone Session-2 mapping above is that one
plan's layout, not a general zone map. Do NOT use phase_raw to answer
"which zone" — use s2p56 (the per-target [[zone_id,stage]] queue).
EdgeMaster OFF did NOT remove the perimeter edge pass (still a phase_raw=1
entry) — the normal edge mow is separate from the EdgeMaster feature.

Current Phase enum labels (MOWING/TRANSIT/PHASE_2/RETURNING) are
placeholder and should be retired. Expose as task_phase diagnostic
sensor. Multiple values per session are normal.

**Open questions:**
- Values 8-14 unobserved — are they edge-variant indices on denser lawns or post-complete transport codes?
- Legacy protocol/trail_overlay.py used phase ∈ {1,3} to colour transit segments TRANSIT_COLOR (blue) vs mowing (dark grey); greenfield retired the entire phase-based colouring in favour of area-counter delta discrimination (live_map.py:147-152). Re-evaluate whether phase-byte colouring should be reinstated during axis 4 map-display work.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_static_b9 — ``

Static 0x00 byte separating phase_raw from the delta block.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:188`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_delta_1 — ``

First path-history delta (Δ1). Carries the offset from the current pose
to a recent prior path point. When |dx| > 32766 AND |dy| > 32766 the
Δ is ABSOLUTE (not relative) — the apk sentinel for relocalisation /
run-start jumps. Confirmed via ±INT16 saturation pattern across 14.6k
frames (motion_vectors_correlate.py).

Apk §parseRobotTrace: each 33-byte frame carries current pose PLUS
3 path-point offsets — so the integration receives 4 points per frame
without waiting for frame N+1.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

### s1p4_33b_delta_2 — ``

Second path-history delta (Δ2). Same sentinel rule as delta_1:
|dx|>32766 AND |dy|>32766 → ABSOLUTE. Caveat: Δ2 saturates more
regularly than Δ1/Δ3 during steady motion (often (+INT16_MAX,
-INT16_MIN)) — may be a reserved slot on g2408 where only Δ1+Δ3
carry real data, or a different sentinel semantic than described in
the apk. Full path-history decode validation needed before shipping
a decoder change (see §3.1 validation steps).

**Open questions:**
- Δ2 saturates more than Δ1/Δ3 — reserved slot or different sentinel? Validate with mid-session frame plot against known path.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

### s1p4_33b_delta_3 — ``

Third path-history delta (Δ3). Same sentinel rule as delta_1/delta_2.
Δ1.dx and Δ3.dx are often nearly equal magnitude in steady-motion
captures (−267 vs −262 mm/frame), suggesting Δ1/Δ3 may point to the
same prior point under different references, or the Δ ordering is
different on g2408 vs the apk description. Validated against 14.6k
frames — saturation pattern matches the apk sentinel.

**Open questions:**
- Δ1.dx ≈ Δ3.dx in steady motion — are Δ1/Δ3 pointing to the same prior point, or is the oldest→newest ordering different on g2408?

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTrace`

### s1p4_33b_flag_22 — ``

Initialisation-complete flag. Observed 0 at session start, transitions
to 1 after initialisation. Value stays 1 throughout the mowing session.

**Open questions:**
- What triggers the 0→1 transition exactly? Is it localisation-complete or first-pose-published?

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:239`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_flag_23 — ``

Observed constant value 2 across all captures. Likely a protocol-version
or frame-type marker. Not known to change.

**Open questions:**
- Does byte[23] ever differ from 2? If always 2, it may be a frame-format version constant.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:239`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_distance_dm — ``

Total distance driven in the current session, in decimetres (raw ÷ 10 → m).
Resets at session start. Ticks forward whenever the mower moves —
including blades-up transit legs. Frame-to-frame delta can detect
motion (non-zero) vs stationary. Used alongside area_mowed_cent for
blades-on/off detection (both counters tick when cutting, distance
alone ticks on transit).

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_33b_total_area_centiares — ``

Total mowable lawn area for the active session, INCLUDING area under
exclusion zones (user-confirmed 2026-04-25). area_mowed_cent plateaus
at (total - excluded), not at total. Resets each session. The apk
documents this as uint24 at bytes [26-28]; byte [28] is currently
treated as static on g2408 (small lawns keep it at 0x00).

**Open questions:**
- Switch to apk's uint24 decode for lawns > 655 m²; currently uint16 + static high byte.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_static_b28 — ``

High byte of the apk-documented uint24 total_area field at [26-28].
Treated as static (0x00) on the user's ~384 m² lawn where the uint16
[26-27] suffices. For lawns > 655 m² this byte will be non-zero and
must be included in the decode. See open question on total_area_centiares.

**Open questions:**
- Confirm byte[28] is non-zero on lawns > 655 m²; needs a contributor with a larger install.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:243`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_area_mowed_centiares — ``

Area mowed with blades down in the current session. Ticks ONLY when
blades are physically cutting (confirmed 2026-04-22 20:47-20:50: stayed
flat during dock-exit transit, started ticking the moment cutting
began). Used as the primary blades-on/off detector in
live_map.DreameA2LiveMap._handle_coordinator_update (each captured
path point tagged with cutting=1 if this counter ticked). Apk documents
as uint24 [29-31]; byte [31] currently static on g2408 small-lawn
captures.

**Open questions:**
- Switch to uint24 decode [29-31] for lawns where mowed area > 655 m².

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_static_b31 — ``

High byte of the apk-documented uint24 area_mowed field at [29-31].
Treated as static (0x00) on the user's lawn. Non-zero for installs
where the mowed area exceeds 655 m² in a single session.

**Open questions:**
- Confirm byte[31] is non-zero on large-lawn installs (mowed area > 655 m² per session).

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:244`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`, `apk: ioBroker.dreame/apk.md §parseRobotTask`

### s1p4_33b_delim_end — ``

End-of-frame delimiter. Always 0xCE on g2408 captures.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:195`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

## Telemetry frame variants

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s1p4_7b | unknown_g2568a_variant |  | APK-KNOWN |  |
| s1p4_8b | beacon |  | WIRED |  |
| s1p4_10b | building_save_marker |  | WIRED |  |
| s1p4_13b | unknown_other_model_variant |  | APK-KNOWN |  |
| s1p4_22b | unknown_other_model_variant_22 |  | APK-KNOWN |  |
| s1p4_33b | mowing_telemetry_full |  | WIRED |  |
| s1p4_44b | unknown_other_model_variant_44 |  | APK-KNOWN |  |

### s1p4_7b — `unknown_g2568a_variant`

Documented in apk for g2568a and other Dreame mower/vacuum models.
Never observed in any g2408 capture. If a future g2408 firmware update
or a different region variant surfaces this length, the integration
emits a one-shot [PROTOCOL_NOVEL] s1p4 short frame len=7 WARNING with
raw bytes.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

### s1p4_8b — `beacon`

Position-only beacon variant. Emitted in four situations on g2408:
(1) idle/docked/remote-control, (2) start-of-leg preamble (~37-45 s
after each s2p1→1, three consecutive frames observed 2026-04-20 before
33-byte stream resumed), (3) throughout BUILDING sessions (47 frames
at 5 s cadence during 2026-04-20 17:00-17:04), (4) post-FTRTS
dock-navigation phase (confirmed 2026-05-05: ~25 frames over ~90 s
when s2p65='TASK_NAV_DOCK' fires). Carries XY + heading byte; no
phase/area/distance fields.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_10b — `building_save_marker`

Fires exactly once per BUILDING session at the moment the new zone is
saved — confirmed 2026-04-20 17:03:41 coincident with the first
s1p50={} in that second. All other 47 frames of that BUILDING session
were 8-byte beacons. Bytes [6-7] carry an unidentified uint16
(observed 5570 = 0x15C2 — possibly point-count, zone-id, or sequence
counter).

**Open questions:**
- Decode bytes [6-7] — point count? zone id? sequence counter?
- Confirm this fires on every BUILDING session, not just map expansions.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py:162`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry frame variants`

### s1p4_13b — `unknown_other_model_variant`

Listed in apk for non-g2408 models. Never observed in any g2408 capture.
Integration emits [PROTOCOL_NOVEL] WARNING on first encounter.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

### s1p4_22b — `unknown_other_model_variant_22`

Listed in apk for non-g2408 models. Never observed in any g2408 capture.
Integration emits [PROTOCOL_NOVEL] WARNING on first encounter.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

### s1p4_33b — `mowing_telemetry_full`

Full mowing-session telemetry. Used throughout an active TASK including
auto-recharge return legs. Carries position (20-bit packed XY),
path-history deltas (Δ1/Δ2/Δ3), phase index, sequence counter, distance
driven, total lawn area, and area mowed (blades-down). Switches to the
8-byte beacon at session boundaries and during BUILDING.

**See also:** `custom_components/dreame_a2_mower/protocol/telemetry.py`, `docs/research/inventory/generated/g2408-canonical.md § Telemetry (s1p4) fields`

### s1p4_44b — `unknown_other_model_variant_44`

Listed in apk for non-g2408 models. Never observed in any g2408 capture.
Integration emits [PROTOCOL_NOVEL] WARNING on first encounter.

**See also:** `apk: ioBroker.dreame/apk.md §s1p4 lengths`

## s2p51 multiplexed-config shapes

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s2p51_ai_obstacle_photos |  | {value: 0|1} | WIRED |  |
| s2p51_ambiguous_4list |  | {value: [b, b, b, b]} | WIRED |  |
| s2p51_ambiguous_toggle |  | {value: 0|1} | WIRED |  |
| s2p51_anti_theft |  | {value: [lift_alarm, offmap_alarm, realtime_location]} | WIRED |  |
| s2p51_auto_recharge_standby |  | {value: 0|1} | WIRED |  |
| s2p51_charging_config |  | {value: [recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min]} | WIRED |  |
| s2p51_child_lock |  | {value: 0|1} | WIRED |  |
| s2p51_consumables_runtime |  | {value: [blades_min, brush_min, maintenance_min, link_module]} | WIRED |  |
| s2p51_dnd |  | {end: int, start: int, value: 0|1} | WIRED | HH:MM local (×1.0) |
| s2p51_frost_protection |  | {value: 0|1} | WIRED |  |
| s2p51_human_presence_alert |  | {value: [enabled, sensitivity, standby, mowing, recharge, patrol, alert, photos, push_min]} | WIRED |  |
| s2p51_language |  | {text: int, voice: int} | WIRED |  |
| s2p51_led_period |  | {value: [enabled, start_min, end_min, standby, working, charging, error, reserved]} | WIRED |  |
| s2p51_low_speed_nighttime |  | {value: [enabled, start_min, end_min]} | WIRED |  |
| s2p51_msg_alert |  | {value: [anomaly, error, task, consumables]} | WIRED |  |
| s2p51_navigation_path |  | {value: 0|1} | WIRED |  |
| s2p51_rain_protection |  | {value: [enabled, resume_hours]} | WIRED |  |
| s2p51_timestamp |  | {time: unix_ts_str, tz: 'IANA_timezone'} | WIRED | ISO8601 (×1.0) |
| s2p51_voice |  | {value: [regular_notif, work_status, special_status, error_status]} | WIRED |  |

### s2p51_ai_obstacle_photos — ``

AI Obstacle Photos single-toggle. Wire shape {value: 0|1}. On the wire
this shape is shared by four other single-bool CFG keys (CLS, FDP, STUN,
PROT) — see s2p51_ambiguous_toggle for the wire-level ambiguity.
At the slot level AOP is fully decoded: 0=off, 1=on (capture photos of
AI-detected obstacles). Confirmed 2026-04-24 via isolated single-toggle.
Disambiguated at runtime via getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_ambiguous_4list — ``

Wire-level ambiguous shape — two distinct CFG keys share this exact
payload on the wire: MSG_ALERT (Notification Preferences:
[anomaly, error, task, consumables]) and VOICE (Voice Prompt Modes:
[regular_notif, work_status, special_status, error_status]).

Both carry a 4-element list of booleans; the envelope carries no
key discriminator. The decoder emits Setting.AMBIGUOUS_4LIST and
the integration disambiguates via sensor.cfg_keys_raw._last_diff.

Discrimination from the CONSUMABLES shape (also a 4-element list)
is performed first: any element > 1 or < 0 routes to CONSUMABLES;
the remaining 4-bool list is then the ambiguous MSG_ALERT/VOICE shape.

All 8 slot semantics (4 from MSG_ALERT + 4 from VOICE) are
wire-confirmed 2026-04-30 via single-row toggles. This is a
wire-format limitation, not a missing decoder — both settings are
fully understood at the slot level (see s2p51_msg_alert,
s2p51_voice).

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_ambiguous_toggle — ``

Wire-level ambiguous shape — five distinct CFG keys share this exact
payload on the wire: CLS (Child Lock), FDP (Frost Protection),
STUN (Auto Recharge Standby), AOP (AI Obstacle Photos), PROT
(Navigation Path; {0: direct, 1: smart}).

The firmware does not name the setting in the s2p51 envelope; the
envelope only carries {value: 0|1} with no key discriminator. The
decoder emits Setting.AMBIGUOUS_TOGGLE and the integration
disambiguates via sensor.cfg_keys_raw._last_diff (which names the
actual CFG key that flipped on the next CFG snapshot).

This is a wire-format limitation, not a missing decoder — every
individual setting is fully understood at the slot level (see
s2p51_child_lock, s2p51_frost_protection, s2p51_auto_recharge_standby,
s2p51_ai_obstacle_photos, s2p51_navigation_path). Membership of the
5-key set is wire-confirmed 2026-04-30 (all five individually toggled).

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_anti_theft — ``

Anti-Theft Alarm. Three-element list:
  [0] lift_alarm — alarm on lift detection.
  [1] offmap_alarm — alarm when mower leaves mapped area.
  [2] realtime_location — enable real-time location sharing.
Each index ∈ {0,1}. Shape is unambiguous by list length (3-element;
distinct from LOW which is also 3-element but CFG key is different
and ATA uses security-semantics vs LOW's time-window semantics).
All three indices individually confirmed 2026-04-27 via single-slot
toggles: [0,0,0]→[1,0,0]→[1,1,0]→[1,1,1]. Disambiguated at runtime
via getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_auto_recharge_standby — ``

Auto Recharge After Extended Standby single-toggle. Wire shape {value: 0|1}.
On the wire this shape is shared by four other single-bool CFG keys (CLS,
FDP, AOP, PROT) — see s2p51_ambiguous_toggle for the wire-level ambiguity.
At the slot level STUN is fully decoded: 0=off, 1=on. Confirmed
2026-04-24 via isolated single-toggle. Disambiguated at runtime via
getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_charging_config — ``

Charging configuration. Six-element list:
  [0] recharge_pct — auto-recharge when battery drops below this percent.
  [1] resume_pct — resume mowing when battery rises above this percent.
  [2] unknown_flag — always observed =1; purpose TBD.
  [3] custom_charging — bool, enables the charging schedule window.
  [4] start_min — charging window start in minutes from midnight.
  [5] end_min — charging window end in minutes from midnight.
Shape is unambiguous by list length (6-element). Confirmed 2026-04-24.
Sample: [15, 95, 1, 0, 1080, 480] → recharge@15%, resume@95%, window
off, would-be 18:00→08:00.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_child_lock — ``

Child Lock (panel lockout) single-toggle. Wire shape {value: 0|1}.
On the wire this shape is shared by four other single-bool CFG keys
(FDP, STUN, AOP, PROT) — see s2p51_ambiguous_toggle for the
wire-level ambiguity. At the slot level CLS is fully decoded:
0=off, 1=on. Confirmed 2026-04-24 via isolated single-toggle.
Disambiguated at runtime via getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_consumables_runtime — ``

Consumables runtime counters. Four-element list of per-consumable
elapsed runtime in minutes:
  [0] blades_min — blade runtime (threshold 6000 min ≈ 100 h).
  [1] brush_min — cleaning brush runtime (threshold 30000 min ≈ 500 h).
  [2] maintenance_min — robot maintenance runtime (threshold 3600 min ≈ 60 h).
  [3] link_module — Link Module; -1 on g2408 (integrated, no wear timer).
The app displays (threshold − counter) / threshold as remaining percent.

Wire-level disambiguation from the 4-bool MSG_ALERT/VOICE shape: any
element > 1 or < 0 routes to CONSUMABLES; otherwise the payload is the
ambiguous 4-bool list (see s2p51_ambiguous_4list).

Confirmed 2026-04-30 19:57:16 by resetting the Cleaning Brush in the
app: array changed from [3084, 3084, 0, -1] to [3084, 0, 0, -1] (only
index 1 changed). Threshold cross-check: counter 3084 ≈ 51.4 h against
100 h total gives 48.6% remaining — matches app display.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_dnd — ``

Wired in s2p51 push when user toggles DND or edits the window.
Shape is unambiguous on the wire (named keys end/start/value, not a
list — no collision with any other s2p51 shape). start/end are
minutes from midnight; the active timezone is carried by CFG.TIME
(IANA name). Confirmed via live toggle 2026-04-24.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_frost_protection — ``

Frost Protection single-toggle. Wire shape {value: 0|1}. On the wire
this shape is shared by four other single-bool CFG keys (CLS, STUN,
AOP, PROT) — see s2p51_ambiguous_toggle for the wire-level ambiguity.
At the slot level FDP is fully decoded: 0=off, 1=on. Confirmed
2026-04-24 via isolated single-toggle. Disambiguated at runtime via
getCFG diff.

No wait-window parameter — distinct from WRP[1]. The associated
s2p2=60 "Frost-protection-suppressed" transition is reported by the
user as temperature-conditional (~6 °C threshold, self-clears on
warming) with no timer. Only one s2p2=60 event in the current probe
corpus (2026-04-27 07:58:02), so the clearing mechanism is not yet
observed end-to-end.

**Open questions:**
- Capture more s2p2=60 events with surrounding ambient-temperature data — does the device report temperature on a known property slot, or is the threshold inferred only by the firmware? If reported, which slot?
- Confirm 6 °C threshold by correlating s2p2=60 timestamps with weather-station data overnight.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_human_presence_alert — ``

Human Presence Detection Alert. Nine-element list:
  [0] enabled — detection on/off.
  [1] sensitivity — 0=low, 1=medium, 2=high.
  [2] standby — detect in standby scenario.
  [3] mowing — detect while mowing.
  [4] recharge — detect while recharging.
  [5] patrol — detect during patrol.
  [6] alert — emit voice prompt + in-app notification on detection.
  [7] photos — photo consent (privacy opt-in for sending captured images).
  [8] push_min — push-notification cooldown in minutes (observed: 3/10/20).
Shape is unambiguous by list length (9-element). Confirmed 2026-04-24.
Sample: [1, 1, 1, 1, 1, 1, 0, 1, 3].

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_language — ``

Language setting. Named-key dict (not a list):
  text — app/UI language index.
  voice — robot voice language index (e.g., 7 = Norwegian).
Shape is unambiguous on the wire (named keys text/voice distinguish it
from all list-shaped payloads). Confirmed 2026-04-24. Transported via
s2p51 shape {"text": N, "voice": M}; decoded as Setting.LANGUAGE.
Sample: {"text": 2, "voice": 7}.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_led_period — ``

LED / Headlight activation period. Eight-element list:
  [0] enabled — custom LED period on/off.
  [1] start_min — window start in minutes from midnight.
  [2] end_min — window end in minutes from midnight.
  [3] standby — LED on in standby scenario (bool).
  [4] working — LED on while mowing (bool).
  [5] charging — LED on while charging (bool).
  [6] error — LED on in error state (bool).
  [7] reserved — trailing toggle, app-visible; purpose unclear.
Shape is unambiguous by list length (8-element). Confirmed 2026-04-24.
Sample: [0, 480, 1200, 1, 1, 1, 1, 1] = LEDs off (custom period
disabled), would-be 08:00→20:00, all scenarios on.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_low_speed_nighttime — ``

Low-Speed Nighttime mode. Three-element list: [enabled, start_min, end_min].
enabled ∈ {0,1}; start_min and end_min are minutes from midnight.
User example: [1, 1200, 480] = enabled, 20:00 → 08:00 next day.
Shape is unambiguous by list length (3-element). Confirmed via live
toggle 2026-04-24 with CFG.LOW diff matching. start/end in
minutes-from-midnight; timezone from CFG.TIME.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_msg_alert — ``

Notification Preferences. Four-bool list:
  [0] anomaly — anomaly-type messages.
  [1] error — error messages.
  [2] task — task-related messages.
  [3] consumables — consumables messages.
Wire shape {value: [b, b, b, b]} is ambiguous with VOICE (see
s2p51_ambiguous_4list). Disambiguation requires getCFG diff via
sensor.cfg_keys_raw._last_diff on the next CFG snapshot. All four
slots individually wire-confirmed 2026-04-30 via single-row toggles.
Default: [1, 1, 1, 1] = all enabled.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_navigation_path — ``

Navigation Path single-toggle. Wire shape {value: 0|1}. On the wire
this shape is shared by four other single-bool CFG keys (CLS, FDP,
STUN, AOP) — see s2p51_ambiguous_toggle for the wire-level ambiguity.
At the slot level PROT is fully decoded: 0=Direct path, 1=Smart path.
Confirmed 2026-04-24 via isolated single-toggle with cfg_keys_raw
diff: toggling Nav Path smart→direct flipped PROT 1→0 with no other
CFG key changing. Disambiguated at runtime via getCFG diff.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_rain_protection — ``

Rain Protection. Two-element list:
  [0] enabled — rain protection on/off.
  [1] resume_hours — hours after rain stops before resuming mowing.
                     0 = "Don't Mow After Rain" (no auto-resume),
                     1..24 = resume N hours after rain ends.
Shape is unambiguous by list length (2-element). Confirmed 2026-04-24
via live toggle with CFG.WRP diff. Shape matches the WRP CFG key exactly.

WRP[1] is also the wait-window the app uses to derive "rain protection
active" state after an s2p2=56 transition: the app marks the mower as
"ACTIVE in rain protection" until (rain_detected_ts + resume_hours * 3600)
has passed, OR until the user taps Continue. The integration must
mirror this derivation (see s2p2 verifications 2026-05-15).

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_timestamp — ``

Timestamp heartbeat. Named-key dict overloading the s2p51 slot:
  time — string-encoded unix timestamp (seconds since epoch).
  tz — IANA timezone name matching CFG.TIME (e.g. 'Europe/Oslo').
Shape is unambiguous on the wire (named keys time/tz distinguish it
from all list-shaped and value-keyed payloads). Fires periodically as
a clock-sync or heartbeat signal; the integration uses it to confirm
the mower's configured timezone. Sample: {"time": "1714953600",
"tz": "Europe/Oslo"}.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

### s2p51_voice — ``

Voice Prompt Modes. Four-bool list:
  [0] regular_notif — regular notification prompts.
  [1] work_status — work status prompts.
  [2] special_status — special status prompts.
  [3] error_status — error status prompts.
Wire shape {value: [b, b, b, b]} is ambiguous with MSG_ALERT (see
s2p51_ambiguous_4list). Disambiguation requires getCFG diff via
sensor.cfg_keys_raw._last_diff on the next CFG snapshot. All eight
slot semantics (4 from MSG_ALERT + 4 from VOICE) wire-confirmed
2026-04-30. Default: [1, 1, 1, 1] = all enabled.

**See also:** `custom_components/dreame_a2_mower/protocol/config_s2p51.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p51 multiplexed-config shapes`

## s2p2 state codes

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s2p2_0 | BUMPER_HANGING |  | WIRED |  |
| s2p2_1 | ROBOT_TILTED |  | WIRED |  |
| s2p2_2 | ROBOT_TRAPPED |  | WIRED |  |
| s2p2_4 | LEFT_DRIVE_WHEEL_ERROR |  | WIRED |  |
| s2p2_5 | RIGHT_DRIVE_WHEEL_ERROR |  | WIRED |  |
| s2p2_9 | ROBOT_LIFTED |  | WIRED |  |
| s2p2_23 | LIFT_LOCKOUT_PIN_REQUIRED |  | WIRED |  |
| s2p2_24 | BATTERY_LOW |  | WIRED |  |
| s2p2_27 | IDLE |  | WIRED |  |
| s2p2_28 | BLADES_SEVERELY_WORN |  | WIRED |  |
| s2p2_30 | MAINTENANCE_REMINDER |  | WIRED |  |
| s2p2_31 | FAILED_TO_RETURN_TO_STATION |  | WIRED |  |
| s2p2_33 | FAILURE_TRANSITION |  | WIRED |  |
| s2p2_36 | FAILED_TO_START_TASK |  | WIRED |  |
| s2p2_37 | RIGHT_MAGNET |  | WIRED |  |
| s2p2_38 | FLOW_ERROR |  | WIRED |  |
| s2p2_39 | INFRARED_FAULT |  | WIRED |  |
| s2p2_40 | CAMERA_FAULT |  | WIRED |  |
| s2p2_41 | STRONG_MAGNET |  | WIRED |  |
| s2p2_43 | BATT_TEMP_LOW |  | WIRED |  |
| s2p2_44 | AUTO_KEY_TRIG |  | WIRED |  |
| s2p2_45 | P3V3_FAULT |  | WIRED |  |
| s2p2_46 | CAMERA_IDLE |  | WIRED |  |
| s2p2_47 | TASK_CANCELLED |  | WIRED |  |
| s2p2_48 | MOWING_COMPLETE |  | WIRED |  |
| s2p2_49 | LDS_BUMPER |  | WIRED |  |
| s2p2_50 | SESSION_STARTING_MANUAL |  | WIRED |  |
| s2p2_51 | PATROL_STARTED |  | WIRED |  |
| s2p2_53 | SESSION_STARTING_SCHEDULED |  | WIRED |  |
| s2p2_54 | RETURNING |  | WIRED |  |
| s2p2_56 | RAIN_PROTECTION |  | WIRED |  |
| s2p2_57 | EDGE_2 |  | WIRED |  |
| s2p2_58 | ULTRASONIC_FAULT |  | WIRED |  |
| s2p2_59 | NO_GO_ZONE |  | WIRED |  |
| s2p2_60 | FROST_SUPPRESSED_SCHEDULED |  | WIRED |  |
| s2p2_61 | ROUTE_FAULT |  | WIRED |  |
| s2p2_62 | ROUTE_2 |  | WIRED |  |
| s2p2_63 | SCHEDULED_TASK_CANCELLED_BUSY |  | WIRED |  |
| s2p2_64 | BLOCKED_3 |  | WIRED |  |
| s2p2_65 | RESTRICTED |  | WIRED |  |
| s2p2_66 | RESTRICTED_2 |  | WIRED |  |
| s2p2_67 | RESTRICTED_3 |  | WIRED |  |
| s2p2_70 | MOWING |  | WIRED |  |
| s2p2_71 | POSITIONING_FAILED_OR_AUTO_RECOVER |  | WIRED |  |
| s2p2_73 | TOP_COVER_OPEN |  | WIRED |  |
| s2p2_74 | PATROL_ENDED |  | WIRED |  |
| s2p2_75 | ARRIVED_AT_MAINTENANCE_POINT |  | WIRED |  |
| s2p2_76 | CANNOT_REACH_MAINTENANCE_POINT |  | WIRED |  |
| s2p2_78 | ROBOT_IN_HIDDEN_ZONE |  | WIRED |  |
| s2p2_117 | STATION_DISCONNECTED |  | WIRED |  |

### s2p2_0 — `BUMPER_HANGING`

Bumper / hanging — s2p2 echo of the s1p1 bumper bit. The 2026-04-30
19:37:13 controlled-safety test shows s2p2 transitioning 1→0 at the
exact moment the HB bumper bit was SET. Corpus has only 6
transitions-to-0, indicating this is an event code, NOT the resting
idle baseline.

Status is partial because it is ambiguous whether 0 also marks the
post-event return-to-idle: only 6 corpus transitions-to-0 exist and
they may include both bumper-event arrivals and generic clear-to-0
recoveries. Disambiguation requires targeted captures with known
bumper presses.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_1 — `ROBOT_TILTED`

Robot tilted — s2p2 echo of the s1p1 drop/tilt bit. Confirmed by the
2026-04-30 19:37:05 controlled-safety test: s2p2 transitioned 48→1 at
the exact moment the HB drop/tilt bit was SET. Also present in the
probe corpus (probe_log_20260514_211550.jsonl).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_2 — `ROBOT_TRAPPED`

Robot trapped — mower is stuck and cannot self-recover. User-confirmed
app notification text 2026-05-30. Present in the probe corpus
(probe_log_20260520_131350.jsonl).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_4 — `LEFT_DRIVE_WHEEL_ERROR`

Left drive wheel error — the left drive wheel cannot turn / is slipping
(observed 2026-05-30: left wheel spinning on a ledge during a stuck
patrol). User-confirmed app text "Left drive wheel error. Tap to view the
solution." Co-incident with a pause/end (s2p1=4 Paused, s2p56=[[1,0,4]])
and present in the s4 eiid1 arg13 fault timeline. apk FaultIndex had 4
unmapped / vacuum-derived; this is the real g2408 meaning. Symmetric
sibling of 5 (right drive wheel).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_5 — `RIGHT_DRIVE_WHEEL_ERROR`

Right drive wheel error — the right drive wheel cannot turn / is
slipping. First wire occurrence 2026-06-01 (probe_log_20260520_131350;
the value's first appearance corpus-wide, re-asserted 3× as the property
re-published). Corresponds to the app notification "Right drive wheel
error" (text user-confirmed; also downloadable via cloud
device-messages/v2). Symmetric sibling of 4 (left drive wheel); apk
FaultIndex had 5 unmapped / vacuum-derived — this is the real g2408
meaning.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_9 — `ROBOT_LIFTED`

Robot lifted — s2p2 echo of the s1p1 lift bit. Confirmed by the
2026-04-30 19:37:57 controlled-safety test: s2p2 transitioned 0→9 at
the exact moment the HB lift bit was SET. Also present in the probe
corpus (probe_log_20260419_130434.jsonl).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_23 — `LIFT_LOCKOUT_PIN_REQUIRED`

Lift lockout / PIN required (emergency stop) — s2p2 echo of the s1p1
emergency-stop/PIN bit. Confirmed by the 2026-04-30 19:39:35 controlled-
safety test: s2p2 transitioned 9→23 at the exact moment the HB PIN-
required bit was SET. Also present in the probe corpus
(probe_log_20260514_211550.jsonl).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_24 — `BATTERY_LOW`

Battery low — apk FaultIndex BATTERY_LOW. NOT observed on the g2408
wire (0 corpus hits across all 9 probe logs). Kept pending resolution
of the 24-vs-54 relationship: s2p2=54 is the confirmed low-battery
returning code; it is unclear whether 24 is a distinct low-battery
WARNING threshold (distinct from 54 = low-battery RETURNING) or
simply the vacuum FaultIndex label for the same event on a different
device model.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_27 — `IDLE`

Idle — steady-state code when the mower is at rest with no active
task. Also observed transiently (emitted twice in one second) during
BT-to-cloud session hand-off windows, so it is not literal "idle" at
every occurrence. A runtime value of 27 may be a brief in-between
marker during session transitions; correlate with s2p1 to confirm.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_28 — `BLADES_SEVERELY_WORN`

Blades severely worn — cloud wear%-gated push. Cloud device-messages/v2
maps this to "Blades are severely worn. Replace them soon." The cloud
only emits the push when blade wear% justifies (server-side gate);
integrations must NOT key blades_worn off s2p2=28 wire transitions
alone — relay only what the cloud actually pushes. Wire-present but
timing is cloud-gated (fires while docked in the worn-blade window,
not on every undock as previously hypothesized; see 2026-05-30
retraction in the s2p2 property verifications).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_30 — `MAINTENANCE_REMINDER`

Maintenance reminder — cloud-gated push for "Robot maintenance time
reached. Maintain the robot soon." Fires at task-start when
robot-maintenance% is at ~10% remaining (same-second as s2p2=50).
Cloud gate is server-side; fires on every mow in the maintenance
window until the user acknowledges. Confirmed 2026-05-26 controlled
blade-reset experiment.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_31 — `FAILED_TO_RETURN_TO_STATION`

Failed to return to station / idle-after-error. Two observed paths:
(a) 33→31 after a documented failure transition (positioning failed,
task-start failed). (b) 48→31 direct with no preceding 33 — the
firmware's post-edge auto-dock planner could not route home from a
stuck pose (confirmed 2026-05-05, two edge-mow runs). Recovery
requires an explicit Recharge command; the s2p50 op-code-6 echo is
unreliable, so detection relies on s2p1: 5→6 plus s3p2→1. The
integration maps this to binary_sensor.dreame_a2_mower_failed_to_
return_to_station (PROBLEM class).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_33 — `FAILURE_TRANSITION`

Failure transition — fires at the moment a task fails (positioning,
task-start, return). Precedes s2p1→2 (IDLE) and s2p2=31 by ~1 s.
The combined 33→31 pair is one of two paths into code 31; the other
is direct 48→31 after an edge-mow auto-dock failure.

Drives positioning state: as of 2026-05-30 the state machine sets
positioning_health = STUCK (+ location OUTSIDE_KNOWN_AREA) on s2p2=33 —
the real positioning/off-dock-relocate failure signal (e.g. the 12:32
relocate-fail → s2p1=4 Paused). Cleared back to LOCALIZED on a mowing
resume (s2p1=1). This replaced the old, never-firing 71+31 combination
(71 and 31/33 do not co-occur). 33 itself is orthogonal to 71/31:
33 = "positioning failed", 31 = "failed to return", 71 = "standby return".

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py; mower/state_machine.py § _apply_s2p2_event`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_36 — `FAILED_TO_START_TASK`

Failed to start task — cloud device-messages/v2 maps this to "Failed
to start the task. Please retry." Fires in the 2026-05-25 12:32
off-dock-failure burst (alongside 20/33). Cloud-verified 2026-05-26.
Also probe corpus (probe_log_20260419_130434.jsonl).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_37 — `RIGHT_MAGNET`

Right magnet hardware fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_38 — `FLOW_ERROR`

Flow error hardware fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_39 — `INFRARED_FAULT`

Infrared sensor fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_40 — `CAMERA_FAULT`

Camera sensor fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_41 — `STRONG_MAGNET`

Strong magnet hardware fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_43 — `BATT_TEMP_LOW`

Battery temperature is low; charging stopped. Drives the Dreame app
notification "Battery temperature is low. Charging stopped."
Confirmed 2026-04-20: byte[6]=0x08 in s1p1 heartbeat fires coincident
with this code. Republished on every re-entry into the condition
(each re-emission triggers a fresh app notification). Clears once
the battery warms and charging resumes.

Note: §8.3 apk catalog lists code 43 as "RTC" (clock / battery-backed
time); the wire-confirmed §4.1 semantics (low-temp charging hold) take
precedence for the g2408 model. The apk label may apply to a different
firmware variant.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_44 — `AUTO_KEY_TRIG`

Unintentional key press (auto key triggered). Lifted from
apk-decompiled DreameMowerErrorCode catalog. Not observed in our
probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_45 — `P3V3_FAULT`

3.3 V power rail fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_46 — `CAMERA_IDLE`

Camera idle (informational). Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_47 — `TASK_CANCELLED`

Scheduled task cancelled (status, not error). mova-community label;
not g2408 wire/cloud-confirmed. Not observed in our probe corpus on
the g2408 (manual cancels use code 48 + s2p50 op-code 3 instead;
scheduled-task-cancelled-while-busy uses code 63).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_48 — `MOWING_COMPLETE`

Mowing run finished cleanly. Also reused for user-cancel ("End" from
app) — distinguish via s2p50 op-code 3 (cancel echo) vs natural
completion (no op-code 3). Also precedes 48→31 on post-edge auto-dock
planner failure (the mower declares the task complete then immediately
fails to return).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_49 — `LDS_BUMPER`

Bumper / LDS event. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus
(bumper hits on the g2408 surface via s1p1 heartbeat byte[1]&0x01
with no corresponding s2p2 transition — see §5.3).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_50 — `SESSION_STARTING_MANUAL`

Session started via manual start from the app. Fires in the same
second as the cloud task envelope on s2p50. Distinct from code 53
(scheduled start). Observed during state transitions on 2026-04-29;
the §8.3 apk-decompiled enum has no name for this value — treat as a
status code rather than a fault.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_51 — `PATROL_STARTED`

PATROL STARTED. Observed 2026-05-30 22:35:11 the instant the user triggered
a Patrol (edge of zone 1) from the app — fired with s2p56=[] just before
s2p1→1 + s2p50 op=108 (cruise-side). The apk "FILTER_BLOCKED" name is
vacuum-derived and WRONG for g2408 (g2408 has no filter). This capture also
resolves the long-blocked "Patrol Logs: no known trigger" item.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_53 — `SESSION_STARTING_SCHEDULED`

Scheduled-session start — confirmed by two identical captures on
2026-04-20 (07:58:02 and 17:30:02). Fires in the same second as
s2p56→{'status':[]}, then s3p2→0 and s2p1→1 (MOWING) one second
later, then s1p50/s1p51→{} and s2p56→[[1,0]] ~40 s later. Distinct
from manual starts which emit code 50 instead. No s2p50 task-metadata
block fires on scheduled starts.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_54 — `RETURNING`

Returning to station. Fires alongside s2p1→5 (RETURNING) during
a low-battery auto-return sequence. Also listed in §8.3 as "EDGE"
(edge-mow fault) for other firmware variants; the wire-confirmed
g2408 meaning is returning-to-station.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_56 — `RAIN_PROTECTION`

Rain protection activated — water detected on the LiDAR. Fires
DURING a mowing run when precipitation is detected. Distinct from
code 60 (frost-suppressed scheduled task, which fires before a run
starts). Listed in §8.3 as "LASER (rain protection)".

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_57 — `EDGE_2`

Alternative edge-mow fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_58 — `ULTRASONIC_FAULT`

Ultrasonic sensor fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_59 — `NO_GO_ZONE`

Reached a no-go / exclusion zone. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_60 — `FROST_SUPPRESSED_SCHEDULED`

Frost-protection-suppressed scheduled task — fires at the configured
scheduled-start time when the firmware's ambient-temperature check
refuses to launch the mow. Confirmed 2026-04-27 07:58:02. Drives
the Dreame app notification "Temperature too low. Frost Protection is
activated. The Scheduled task will start later." The mower wakes
briefly, fires this code, then settles back to s2p1=13
(CHARGING_COMPLETED) ~10 minutes later. Distinct from code 53
(scheduled task did start) and code 56 (rain pause during a run).

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_61 — `ROUTE_FAULT`

Navigation route fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_62 — `ROUTE_2`

Alternative navigation route fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_63 — `SCHEDULED_TASK_CANCELLED_BUSY`

Scheduled task cancelled — robot working (busy). Cloud device-messages/v2
maps this to "Robot is working. Scheduled task cancelled." Fires when
the firmware cancels an incoming scheduled task because the robot is
already active. Wire-confirmed (9 corpus hits in probe corpus).
Previously misidentified as "Obstacle blocking (variant 2)" from the
apk FaultIndex — that was the vacuum-lineage label; the g2408 wire +
cloud confirm the real meaning.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_64 — `BLOCKED_3`

Obstacle blocking (variant 3). Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_65 — `RESTRICTED`

Restricted area. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_66 — `RESTRICTED_2`

Restricted area (alternative variant). Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_67 — `RESTRICTED_3`

Restricted area (second alternative variant). Lifted from
apk-decompiled DreameMowerErrorCode catalog. Not observed in our
probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_70 — `MOWING`

Mowing in progress (edge or standard). Fires during active mowing
to indicate the current mowing phase. Transitions to code 54
(RETURNING) on low-battery auto-return.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_71 — `POSITIONING_FAILED_OR_AUTO_RECOVER`

Positioning failure or auto-recovery from idle. Two distinct
contexts: (a) Hard-stuck "Positioning Failed" — mower cannot
localize on the saved map; app shows "Positioning Failed";
recovery requires a TASK_SLAM_RELOCATE pass. Confirmed 2026-04-20
19:28:19. (b) Auto-return-from-idle — confirmed 2026-04-27
11:52:47 after BT-orphaned manual stop left the mower idle for
~55 min; code 71 fired alongside s2p1=5 (RETURNING) and the
mower self-navigated home. The two contexts are distinguished by
what follows: 33→31 means stuck (user help needed); 5→telemetry→6
means self-recovery succeeded.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_73 — `TOP_COVER_OPEN`

Top cover open — mechanical fault. Fires when the top cover is lifted
while the robot is running. Wire-confirmed: 51 corpus hits across the
probe logs; confirmed 2026-04-30 (cover opened during PIN entry).
Drives binary_sensor.top_cover_open in the integration. Previously
marked hypothesized from the apk catalog only — the corpus and the
2026-04-30 controlled test confirm this is the correct g2408 meaning.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_74 — `PATROL_ENDED`

Patrol ended / cancelled. Fires when a Patrol (edge cruise) session
ends — either on completion or user cancel. Present in the probe
corpus and verified 2026-05-30.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_75 — `ARRIVED_AT_MAINTENANCE_POINT`

Arrived at Maintenance Point — confirmed 2026-04-20 18:18:05 when
the mower reached a user-set maintenance point after tapping "Head
to Maintenance Point". Fires in the same second as s2p1→2 (IDLE),
followed by s1p52={}. No event_occured summary for Head-to-MP tasks.

Note: §8.3 apk catalog lists code 75 as "LOW_BATTERY_TURN_OFF";
the wire-confirmed §4.1 semantics (arrived at MP) take precedence
for the g2408 model.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_76 — `CANNOT_REACH_MAINTENANCE_POINT`

Cannot reach maintenance point — task ended (give-up + return). Fires
once at the give-up moment when a head-to-maintenance-point move cannot
complete. Followed by s2p1→5 (auto-return to dock). Contrast with code
75 (arrived at maintenance point successfully), which is followed by
s2p1→2 (IDLE) and the mower stays at the point.

Wire context, probe_log_20260520 @ 2026-05-30 16:51:41: mower
stalled at obstruction, s2p1→2 (idle) at 16:51:40, s2p2=76 +
s1p52={} at 16:51:41, s2p1→5 (returning) at 16:51:42. User-confirmed
app notification "Cannot reach the maintenance point. Task ended."

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`

### s2p2_78 — `ROBOT_IN_HIDDEN_ZONE`

Robot in hidden zone — navigation fault. Lifted from apk-decompiled
DreameMowerErrorCode catalog. Not observed in our probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

### s2p2_117 — `STATION_DISCONNECTED`

Station (dock) communications disconnected. Lifted from
apk-decompiled DreameMowerErrorCode catalog. Not observed in our
probe corpus.

**See also:** `custom_components/dreame_a2_mower/mower/error_codes.py`, `docs/research/inventory/generated/g2408-canonical.md § s2p2 state codes`, `apk: ioBroker.dreame/apk.md §FaultIndex`

## s2p1 mode enum

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| s2p1_1 | MOWING |  | WIRED |  |
| s2p1_2 | IDLE |  | WIRED |  |
| s2p1_3 | PAUSED |  | DECODED-UNWIRED |  |
| s2p1_5 | RETURNING |  | WIRED |  |
| s2p1_6 | CHARGING |  | WIRED |  |
| s2p1_11 | BUILDING |  | WIRED |  |
| s2p1_13 | CHARGING_COMPLETED |  | WIRED |  |
| s2p1_14 | UPDATING |  | APK-KNOWN |  |
| s2p1_16 | BATT_TEMP_HOLD |  | WIRED |  |

### s2p1_1 — `MOWING`

Active mowing-related task. Real mowing, head-to-maintenance-point,
and manual mode all use this value. Distinguish the specific
operation via s2p2 code (50=manual start, 53=scheduled start,
70=mid-mow) or s2p50 envelope. Fires when mowing begins and stays
set for the duration of the mowing leg.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_2 — `IDLE`

Idle — no active task, mower is at rest (on or off the dock). Used
as the post-mow settled state (after MOWING_COMPLETE), after a
task cancel, and transiently between state transitions. Also
observed immediately after arriving at the maintenance point
(fires in the same second as s2p2=75).

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_3 — `PAUSED`

Pause / brief hold state. Per §2.1 apk decompilation and confirmed
in probe corpus: observed 5× across two probe log files
(2026-04-17 21:01:38, 2026-04-17 22:04:25, 2026-04-22 09:02:52,
2026-04-28 23:10:53, 2026-04-29 20:43:30), each co-incident with
s2p56 status=[[1,4]] — consistent with a sub-task transition or
a brief firmware-internal hold. The earlier hypothesis that "the
mower's pause UX folds into mode 1 with sub-state in s2p56" is
disproved by direct observation.

**Open questions:**
- What user action or firmware event triggers s2p1=3? Correlate timestamps against app UI actions.
- Is s2p56 status=[[1,4]] always co-incident or just coincidental in these 5 captures?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §s2.1 status enum`

### s2p1_5 — `RETURNING`

Returning to station. Fires during low-battery auto-return, after
user-cancel Recharge command, and during post-FTRTS dock-navigation
phases. During the post-FTRTS dock-nav path the mower emits 8-byte
beacon frames on s1p4 (not 33-byte telemetry) — see §3.2. Sequence:
MOWING(1)→IDLE(2)→RETURNING(5)→CHARGING(6) for a clean auto-return.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_6 — `CHARGING`

Charging — mower is docked and actively charging. Transitions
to CHARGING_COMPLETED (13) when full. Brief flicker entries into
BATT_TEMP_HOLD (16) are common when the battery is cold and the
charger retries (see §4.4).

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_11 — `BUILDING`

Manual map-learn / zone-expand. Confirmed 2026-04-20 17:00:09
when the user triggered "Expand Lawn" from the Dreame app. The
mower left the dock, drove the new perimeter for ~4 min emitting
8-byte s1p4 frames (not 33-byte telemetry), then returned. A
single 10-byte frame fires at the exact moment the expand
completes (zone-saved marker). Sequence:
CHARGING(6)→BUILDING(11)→IDLE(2)→RETURNING(5)→CHARGING(6).

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_13 — `CHARGING_COMPLETED`

Charging completed — mower is docked, battery is full, no active
task scheduled. Steady-state between mowing sessions. Also the
settled state after a frost-suppressed scheduled task (s2p2=60)
where the mower wakes briefly at schedule time and returns without
mowing.

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

### s2p1_14 — `UPDATING`

Firmware update in progress; the mower transitions through
s2p1=14 during OTA. Per apk decompilation in §2.1.

**Open questions:**
- Confirm transition through s2p1=14 by capturing during the next firmware update.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Properties`, `apk: ioBroker.dreame/apk.md §s2.1 status enum`

### s2p1_16 — `BATT_TEMP_HOLD`

Docked, refusing to charge because the battery is below its
safe-charge temperature. Misnamed STATION_RESET in the legacy
upstream enum (still used in lawn_mower.py for compatibility);
the actual semantics are pause-for-cold, not station-reset.
Re-confirmed 2026-04-26: 5 occurrences between 03:45–07:00
local (cold morning hours), every entry coincident with
s1p1[6]=0x08 (charging paused — temp low flag), every exit
coincident with s1p1[6]=0. Brief 2 s flicker entries common
(cold-check that immediately cleared); longer 1 h holds occur
when the cell needs to warm. Always transitions to either
CHARGING(6) or CHARGING_COMPLETED(13).

**See also:** `custom_components/dreame_a2_mower/mower/property_mapping.py:56`, `docs/research/inventory/generated/g2408-canonical.md § s2p1 mode enum`

## OSS map blob keys

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| map_key_boundary | boundary | {x1, y1, x2, y2} | WIRED |  |
| map_key_cleanPoints | cleanPoints | {dataType:'Map', value:[[pt_id, {id, type, shapeType, path:[{x,y}]}]...]} | WIRED |  |
| map_key_contours | contours | {dataType:'Map', value:[[[map_id, ?], {id, type, shapeType, path:[{x,y},...]}]]} | WIRED |  |
| map_key_cruisePoints | cruisePoints | {dataType:'Map', value:[]} | APK-KNOWN |  |
| map_key_cut | cut | [] | UNCLASSIFIED |  |
| map_key_forbiddenAreas | forbiddenAreas | {dataType:'Map', value:[[zone_id, {id, type, shapeType, path:[{x,y}...], angle}]...]} | WIRED |  |
| map_key_hasBack | hasBack | bool | WIRED |  |
| map_key_mapIndex | mapIndex | int | WIRED |  |
| map_key_md5sum | md5sum | hex string (MD5) | WIRED |  |
| map_key_merged | merged | bool | WIRED |  |
| map_key_mowingAreas | mowingAreas | {dataType:'Map', value:[[id, {name, path:[{x,y},...]}], ...]} | WIRED |  |
| map_key_name | name | string | WIRED |  |
| map_key_notObsAreas | notObsAreas | {dataType:'Map', value:[[zone_id, {id, type, shapeType, path:[{x,y}...], angle}]...]} | WIRED |  |
| map_key_obstacles | obstacles | {dataType:'Map', value:[]} | UNCLASSIFIED |  |
| map_key_paths | paths | {dataType:'Map', value:[]} | APK-KNOWN |  |
| map_key_spotAreas | spotAreas | {dataType:'Map', value:[[zone_id, {id, type, shapeType, path:[{x,y}...]}]...]} | WIRED |  |
| map_key_totalArea | totalArea | float (m²) | WIRED | m² (×1.0) |

### map_key_boundary — `boundary`

Axis-aligned bounding rectangle of the entire map area. Used by the integration
as the viewport extent when rendering the camera overlay image. Less detailed
than the contours polygon.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:240)`

### map_key_cleanPoints — `cleanPoints`

Maintenance Points — user-pinned markers in the app. Sample 2026-04-24 has
one entry at (2820, 12760) mm in cloud frame; the app supports multiple per
map. Consumed since alpha.91 (multi-point support since alpha.93):
sensor.maintenance_points_count carries the full list; the
dreame_a2_mower.mower_go_to_maintenance_point service selects by optional
point_id or defaults to the first point.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_contours — `contours`

Actual lawn outline polyline — 52-point polygon on a ~384 m² lawn (more
detailed than the axis-aligned boundary rectangle). Consumed since alpha.91:
drawn on the base-map PNG as a 2-px WALL outline in _build_map_from_cloud_data
so the real grass perimeter is visible over zone fills.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:230)`

### map_key_cruisePoints — `cruisePoints`

Patrol / cruise points the mower visits in sequence. Empty on all g2408
captures (value=[]). Purpose confirmed by apk; the container is present even
when empty.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `apk: ioBroker.dreame/apk.md §cruisePoints`

### map_key_cut — `cut`

Always empty on g2408 captures (bare list, no dataType wrapper). Purpose
unknown — possibly cut-line geometry for zone boundaries or a firmware
placeholder.

**Open questions:**
- Does cut ever populate? What triggers it? Is it zone-boundary cut lines or something else?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_forbiddenAreas — `forbiddenAreas`

Classic exclusion / no-go zones (red in the Dreame app). Each entry is a
[key, record] pair carrying a READ-side `shapeType` that the live-map
decoder now honors (was previously inferred from point-count only). Read
enum: 0=area, 1=line(2pt), 2=rotated-rect(4pt, angle=deg), 3=circle
(multi-pt polygon), 5=point, 7=spot, plus DECORATIVE silhouettes
9=square,12=circle,13=heart,14=triangle,15=teardrop,16=mushroom,
17=cloud,18=rainbow (stored as 2 bbox corners + angle; the app
tessellates client-side — the integration stamps a scaled+rotated mask).
For shapeType>=9 the path stays UN-rotated (raw bbox corners); for
line(1)/rect(2)/circle(3) the path is centroid-rotated by -angle at decode.
id matches the s2p50 entity id from create / delete events. Distinct from
notObsAreas despite sharing the same shape. Surfaced as
sensor.exclusion_zones (state=zone count, attrs.zones=per-zone geometry).

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:211)`

### map_key_hasBack — `hasBack`

Whether this map has a "back" (secondary map layer or reverse side). Meaning
not fully confirmed on g2408; consumed by the integration's map pipeline but
effect on rendering is not surfaced to the user.

**Open questions:**
- What does hasBack=true trigger in the app? Multi-level map? Reverse traversal?

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_mapIndex — `mapIndex`

Map index — identifies which saved map this blob represents. The integration
uses mapIndex when selecting the active map for rendering.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:249)`

### map_key_md5sum — `md5sum`

MD5 checksum of the map blob, used for deduplication in the integration's
map cache. A fresh fetch returns the same md5sum if the map has not changed
since the last pull.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_merged — `merged`

Whether this map is a merged composite of multiple partial maps. Consumed by
the integration; exact semantics not verified on g2408.

**Open questions:**
- Is merged ever true on g2408? Does it relate to the Expand Lawn workflow?

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_mowingAreas — `mowingAreas`

Zone polygons — the mowable areas the user has defined. Each entry carries an
id (used in o:102 zone-mow command), a name, and a path of {x,y} vertices in
cloud frame. The integration uses these for the zone-mow service and to
annotate the camera map overlay.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:186)`

### map_key_name — `name`

Human-readable map name as set by the user in the Dreame app.

**See also:** `custom_components/dreame_a2_mower/map_decoder.py:387`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_notObsAreas — `notObsAreas`

Designated Ignore Obstacle zones (green in the Dreame app). Separate top-level
key from forbiddenAreas despite identical payload shape. Confirmed 2026-04-27.
Sample: id=101, type=10, shapeType=2 (axis-aligned, angle=0).
Rendered in green via Area.subtype="ignore" in _build_map_from_cloud_data.
Surfaced as sensor.designated_ignore_zones.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_obstacles — `obstacles`

Auto-detected runtime obstacles. Empty on g2408 captures (value=[]). Populated
during / after a mow run — not by user drawings. Not to be confused with
notObsAreas (user-drawn ignore zones).

**Open questions:**
- When does obstacles populate? Is it the AI-detected obstacle list or physical obstacle markers?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`

### map_key_paths — `paths`

Historical or planned mow paths. Empty on g2408 captures. Per apk cross-
reference: connection paths between zones. May populate during an active
mowing session (not verified on g2408).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `apk: ioBroker.dreame/apk.md §paths`, `github.com/antondaubert/dreame-mower (map_data_parser.py:221 — inter-zone navigation paths)`

### map_key_spotAreas — `spotAreas`

Spot-mow target zones. type=3 (WorkingMode.SPOT), shapeType=7 (axis-aligned
rectangle, no angle field). Populated lazily — may take hours to sync after a
spot mow runs. Sample: 4-corner rectangle (-360,-5320)..(-3560,-2840).
Surfaced as sensor.spot_zones.

**See also:** `custom_components/dreame_a2_mower/dreame/map.py`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:200)`

### map_key_totalArea — `totalArea`

Total mowable area in m² as stored in the map blob. Matches event_occured
piid 14 (total lawn area rounded int) and session-summary map_area field
to within rounding.

**See also:** `custom_components/dreame_a2_mower/map_decoder.py:522`, `docs/research/inventory/generated/g2408-canonical.md § OSS map blob keys`, `github.com/antondaubert/dreame-mower (map_data_parser.py:247)`

## Session-summary JSON fields

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| archive_cloud_track | verbatim_cloud_track | [ [[x_m, y_m], ...], ... ] | WIRED | m |
| archive_track | per_point_track_stream | [{t: float, x_m: float, y_m: float, area_m2: float, heading_deg: float|null, task_state: int, role: str}, ...] | WIRED |  |
| event_s4eiid1_arg1 | mode_op | int (mode/op enum) | DECODED-UNWIRED |  |
| event_s4eiid1_arg11 | event_arg11 | int (0 or 1) | SEEN-UNDECODED |  |
| event_s4eiid1_arg13 | fault_event_timeline | list of [unix_ts, s2p2_code] | DECODED-UNWIRED |  |
| event_s4eiid1_arg14 | total_lawn_area_m2 | int (m² rounded) | WIRED | m² (×1.0) |
| event_s4eiid1_arg15 | event_arg15 | int (always 0) | SEEN-UNDECODED |  |
| event_s4eiid1_arg2 | end_code | int (enum) | SEEN-UNDECODED |  |
| event_s4eiid1_arg3 | area_mowed_centiares | int (centiares = m² × 100) | WIRED | m² (×0.01) |
| event_s4eiid1_arg60 | abort_reason | int (-1 or 101) | SEEN-UNDECODED |  |
| event_s4eiid1_arg7 | stop_reason | int (enum) | WIRED |  |
| event_s4eiid1_arg8 | session_start_unix | unix_seconds (int) | WIRED | ISO8601 local (×1.0) |
| event_s4eiid1_arg9 | session_summary_oss_object_key | string (OSS object key path) | WIRED |  |
| summary_areas | area_mowed_m2 | float (m²) | WIRED | m² (×1.0) |
| summary_complete_count | completed_target_count | int | UNCLASSIFIED |  |
| summary_dock | dock_pose | [x_cm, y_cm, heading_deg] | WIRED | m (×0.01) |
| summary_edge_status | edge_status | list[[int, int, int]]; presence-gated on mode 101 only | SEEN-UNDECODED |  |
| summary_end | session_end_unix | unix_seconds (int) | WIRED | ISO8601 local (×1.0) |
| summary_faults | faults | [] (empty on normal completion) | UNCLASSIFIED |  |
| summary_human_detected | human_detected_count | int | UNCLASSIFIED |  |
| summary_legs_meta | legs_meta | [{role: str, start_ts: int, end_ts: int}, ...] | WIRED |  |
| summary_map_area | total_lawn_area_m2 | int (m²) | WIRED | m² (×1.0) |
| summary_map_list | map_list | [{id, type, name, area, etime, time, data:[[x,y]...], track:[...]}, ...] | WIRED |  |
| summary_map_track | mow_path | [[x, y] | [2147483647, 2147483647], ...] | WIRED | m (×0.01) |
| summary_md5 | content_md5 | hex string (MD5) | WIRED |  |
| summary_mode | mode | int (enum) | WIRED |  |
| summary_obstacle | obstacle_list | [{id, type, data:[[x_cm, y_mm]...]}, ...] | WIRED |  |
| summary_photo_detected | photo_detected_flag | int (0/1) | UNCLASSIFIED |  |
| summary_photo_list | auto_capture_photo_list | [str, ...]  # bare leaf filenames, e.g. "1780512275.jpg" | UNCLASSIFIED |  |
| summary_point | patrol_point_route | [{id:int, param:{}, point:[x_cm, y_cm, ?], time:int_s, type:int}, ...] | UNCLASSIFIED |  |
| summary_point_status | patrol_point_status | [[point_id, stage], ...] | UNCLASSIFIED |  |
| summary_pre_type | pre_type | int | UNCLASSIFIED |  |
| summary_pref | global_pref | [int, int] | UNCLASSIFIED |  |
| summary_recognition | recognition_flag | int | UNCLASSIFIED |  |
| summary_region_status | region_status | [[zone_id, status], ...] | UNCLASSIFIED |  |
| summary_result | result | int | WIRED |  |
| summary_spot_track | spot_track | list[[x_cm, y_cm]]; sentinel [2147483647, 2147483647] marks track breaks | DECODED-UNWIRED |  |
| summary_start | session_start_unix | unix_seconds (int) | WIRED | ISO8601 local (×1.0) |
| summary_start_mode | start_mode | int | UNCLASSIFIED |  |
| summary_stop_reason | stop_reason | int | WIRED |  |
| summary_time | duration_minutes | int (minutes) | WIRED |  |
| summary_track_break_positions | track_break_marker_positions | list of [2147483647, 2147483647] rows interleaved with [x_cm, y_cm] rows | DECODED-UNWIRED |  |
| summary_trajectory | trajectory_list | [{id:[int, ...], data:[[x_cm, y_cm]...], track:[[x_cm, y_cm] | TRACK_BREAK_MARKER, ...]}, ...] | DECODED-UNWIRED |  |

### archive_cloud_track — `verbatim_cloud_track`

Integration-authored archive field (not from the cloud wire directly).
Stores the cloud session-summary track segments verbatim after the OSS
fetch in coordinator/_lidar_oss.py:_inject_live_map_into_raw_dict.
The outer list is segments (split by the max-int sentinel in the raw
cloud track); each segment is a list of [x_m, y_m] pairs.

The cloud wire shape (map[].track) is UNCHANGED — this field is just
the parsed + converted form stored inside the archive so the classifier
can re-run without a second OSS fetch.

Stored for reference only — NOT used to classify roles. A cloud-coverage
"rescue" (upgrade traversal→mowing when near the cloud path) was tried
and removed 2026-05-28: on a full-lawn mow the cloud's blades-down
segments blanket the lawn, so a cross-area traversal driving over
already-mowed grass sits on the cloud path and gets falsely greened.
Area-delta is the sole role authority. Do not re-add cloud-rescue.

No longer surfaced to the dashboard as a separate entity attribute;
the card reads legs_timeline derived from the `track` stream instead.

**See also:** `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py`, `custom_components/dreame_a2_mower/inventory.yaml § summary_map_track`

### archive_track — `per_point_track_stream`

Integration-authored archive field (not from the cloud).
Per-s1p4-point time-coded track stream written to every session archive
by coordinator/_lidar_oss.py:_inject_live_map_into_raw_dict since the
2026-05-28 session-replay rewrite.

Each row is a TrackPoint dict serialized from live_map.LiveMapState:
  t             — unix seconds (ms precision), from s1p4 arrival
  x_m, y_m     — cloud-frame metres, charger-relative
  area_m2       — cumulative mowed area from the same s1p4 push
  heading_deg   — mower heading from s1p4 if decoded, else null
  task_state    — latest s2p1 value at this point (diagnostic only)
  role          — "mowing" | "traversal"; set by area-delta at
                  append (area grew → mowing, flat → traversal) and
                  only SMOOTHED at finalize (lone stutters flipped).
                  Area-delta is the sole authority; no cloud-rescue.
                  The archived role is final.

Replaces: _local_legs, _legs_meta, _mowing_legs, _traversal_legs
(removed in the 2026-05-28 rewrite).

This is an integration storage artefact, not a cloud wire surface.
Versioned as load-bearing: coord._session.py and session_card.py
read it; entity sensor.dreame_a2_mower_picked_session surfaces
track_first_ts, track_last_ts, legs_timeline, distance_mowing_m,
distance_traversal_m all derived from this field.

**See also:** `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py`

### event_s4eiid1_arg1 — `mode_op`

The session's mode/op — same enum as summary.mode / the s2p50 TASK op:
100=all_areas, 101=edge, 102=zone, 103=spot, 108=patrol (cruise-side).
NOT a constant. The earlier "always 100 across six captures" reading was a
sampling artifact — all six were all-area mows (op 100). Disproved
2026-05-30 by a Patrol whose event carried piid=1 = 108.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg11 — `event_arg11`

Binary flag. Observed values: 0 and 1 across six captures. Semantics unknown.

**Open questions:**
- What does piid=11 flag? Correlate with session type or outcome.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg13 — `fault_event_timeline`

Per-session FAULT/EVENT timeline: a list of [unix_ts, s2p2_code] pairs for
the faults/interventions during the session. Empty on a clean run (which is
why all prior captures showed []). Decoded 2026-05-30 on a stuck patrol:
[[…,2],[…,23],[…,4],[…,23],[…,23]] = trapped(2) → lift(23) → pause(4) →
lift(23) → lift(23), each timestamp matching the wire s2p2 transitions.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg14 — `total_lawn_area_m2`

Total mowable lawn area in m² (rounded int). 379 pre-2026-04-18, 384 after
user added a zone in-app. Matches map_area and rounded map[0].area in the
session-summary JSON. User confirmed the lawn grew by ~5 m² when the new zone
was added.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg15 — `event_arg15`

Always 0 across all captures. Purpose unknown.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg2 — `end_code`

End-code enum. Observed values across six captures: 31, 36, 69, 128, 170, 195,
217. 36 confirmed as user-cancel (2026-04-20 18:06). Other values from natural
completions. Likely encodes finish-cause (scheduled vs manual, rain-interrupted,
normal, etc.); does NOT distinguish partial vs full coverage (confirmed: 323/384
ratio was full reachable area under an exclusion zone, not a partial run).

**Open questions:**
- Map the full enum: which value = scheduled-complete, rain-abort, fault-abort?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg3 — `area_mowed_centiares`

Area mowed this session in centiares (m² × 100). Observed values: 5232, 6647
(user-cancel at 66.47 m²), 10759, 19613, 28744, 31133. Matches the final
s1p4 area_mowed_m2 reading at session end to within recharge-leg-transit
overhead.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg60 — `abort_reason`

Abort-specific reason code. -1 on normal completion; 101 on the first
observed user-cancel (2026-04-20 18:06). The first non-(-1) value was
captured on the user-cancel run.

**Open questions:**
- Are there abort codes beyond 101? Does 101 always mean user-cancel?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg7 — `stop_reason`

Stop reason. 1 = natural completion; 3 = user-cancel (confirmed 2026-04-20
abort). Matches the stop_reason direction in the session-summary JSON (which
uses -1 for normal end — different encoding).

**Open questions:**
- Are there other stop-reason codes beyond 1 and 3 (rain, fault, etc.)?

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg8 — `session_start_unix`

Session start timestamp in Unix seconds. Confirmed: the 2026-04-20 morning
run value 1776664681 → 05:58:01 UTC = 07:58:01 local, exact match to s2p2
→ 1 at 07:58:03. The user-cancel run emitted 1776699000 = 15:30:00 UTC =
17:30:00 local — session-start, not cancel-time. Independent of end reason.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### event_s4eiid1_arg9 — `session_summary_oss_object_key`

Path to the session-summary JSON in Aliyun OSS. Format:
ali_dreame/YYYY/MM/DD/<master-uid>/<did>_HHMMSSmmm.MMMM.json.
The integration fetches this URL via cloud's getDownloadUrl
(the interim endpoint — getOss1dDownloadUrl returns 404 for this
object class) then GETs the OSS signed URL.
Fires for both natural completion and user-cancel.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### summary_areas — `area_mowed_m2`

Area mowed this session in m². Matches event_occured piid 3 (centiares ÷100)
to within recharge-leg-transit overhead.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_complete_count — `completed_target_count`

Number of targets completed in the session. =2 on the double-point patrol
(2 points), None/absent on a single-target all-area mow. It counts POINTS
(targets), NOT cycles — the user set 2+1 cycles but complete_count=2. Maps
to s4 eiid1 piid2 (=2 same run).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_dock — `dock_pose`

Dock coordinates and heading in mower frame. x, y in cm; heading in degrees.
Used by the live-map overlay to position the dock icon.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_edge_status — `edge_status`

Diagnostic enum present only in edge-mode (mode 101) session summaries.
Three observed edge mows (2026-05-16, 2026-05-17, 2026-05-23) all
carry the IDENTICAL value [[1, 0, 2]] despite very different durations
(13/15/27 min) and obstacle counts (4/4/13). No variance to decode the
individual columns further.

Likely a one-row [task_type, sub_state, terminal_result] tuple based
on the trailing 2 matching the session's `result: 1` mod 2 pattern,
but that's speculation.

Integration ignores this field — there is no derived entity surface
for it. Filed for future researchers if more edge mows ever produce
a different value (would indicate non-success edge cases worth
decoding).

**Open questions:**
- Does an interrupted / faulted edge mow produce a different edge_status row?
- Why does this field exist only for edge — what does it tell the cloud that result/stop_reason don't already?

### summary_end — `session_end_unix`

Session end timestamp in Unix seconds.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_faults — `faults`

Fault list recorded during the session. Empty on normal completion.
Not yet decoded from a faulted-session capture.

**Open questions:**
- What fault objects look like? Capture during an actual fault event.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_human_detected — `human_detected_count`

Count/flag of human detections during the session (=0 on the patrol). Likely
the AI human-detection counter; may align with s4 eiid1 piid11 (=0 same run).
Single sample — semantics presumed, not confirmed.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_legs_meta — `legs_meta`

Integration-authored field (underscore prefix = not from the cloud).
Parallel array to _local_legs. Each record carries the role ("mowing"
or "traversal") and unix start/end timestamps of that leg, captured at
LiveMapState set_mowing / begin_leg / pen-up boundaries. Surfaced
through session_card.build_picked_session_summary as the ordered
legs_timeline attribute. Replaces the post-hoc fuzzy split_trail
matching (deleted in Task 11 of the 2026-05-19 path-rendering overhaul
plan). Absent from sessions archived before v1.0.16a7; those sessions
still render via the _mowing_legs/_traversal_legs split if present,
else as a single-colour trail.

**See also:** `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py`

### summary_map_area — `total_lawn_area_m2`

Total mowable lawn area in m² (rounded int). Matches event_occured piid 14.
Primary source for total_lawn_area_m2 in the integration (preferred over s2p66
which pushes infrequently).

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_map_list — `map_list`

List of map area entries. Each entry carries the zone id, type (0=lawn area,
2=exclusion zone), optional name, area in m², timing fields, a data polygon
(lawn boundary), and a track array (mow path). Exclusion zones carry a
description sub-object instead of track.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_map_track — `mow_path`

Mow path as [x, y] pairs in cm. Max-int sentinel [2147483647, 2147483647]
marks segment breaks (e.g. between mowing legs separated by a dock-recharge).
Used by LiveMapState to draw completed track segments on the camera overlay.

As of the 2026-05-28 session-replay rewrite: the cloud wire shape is
UNCHANGED (parse_session_summary still yields track_segments). The
integration now stores the parsed cloud track verbatim under `cloud_track`
in the session archive and no longer surfaces the parsed track_segments to
the dashboard via a separate `_summary_trail_legs` path — the JS replay
card derives its trail entirely from the per-point `track` stream instead.

**Open questions:**
- Legacy live_map.py:20 defined PATH_DEDUPE_METRES = 0.2 m and skipped appending a path point if it was within 0.2 m of the last point (live_map.py:135-162), preventing micro-segment noise in the live trail. The greenfield dropped this deduplication during the rewrite. Re-evaluate during axis 4: does the session-summary track data contain enough micro-segments to warrant client-side deduplication when rendering, or is the firmware already deduping before archiving?
- TODO (cloud over-segmentation investigation): What event triggers the
cloud to emit a TRACK_BREAK_MARKER mid-mow, producing a single-point
or 2-point segment? Observations to date (as of 2026-05-15):
  - Distribution: 27 single-point / 43 two-point / 24 three-point
    segments out of 150 total for a 48-min session.
  - Points are on the eventual continuous path — not outliers.
  - Spatial distribution looks roughly perimeter-following, not
    clustered at one location.
  - Counts do not match any single MQTT property's emission rate
    in the same window (s1p4: 579, s1p1: 225, s1p53: 15, s2p55: 3).
  - User report: "they appear to show something significant" — not
    random noise.
Plausible triggers (none ruled out):
  (a) Pen-up detection via s1p4 position jumps (large delta between
      consecutive samples). Test: decode s1p4 byte layout to extract
      per-sample (x, y); align with segment boundaries.
  (b) Blade-state change (blade off then back on). Test: correlate
      with a blade-state signal — but s1p53 is now confirmed the BLE-connection flag (NOT blade-state), so this needs a different signal (none identified yet).
  (c) Cloud-side heartbeat / cadence trigger (e.g., break every N
      seconds). Test: timestamps aren't carried in map[].track,
      but s1p4 timestamps could be used to derive segment-time spans.
  (d) Path-planning event (waypoint reached, turn executed,
      obstacle re-routed). Test: correlate with s2p55 obstacle
      events and any planning property slots.
  (e) Mower-firmware "phase" change (edge → fill → edge transition).
      Test: see if segments cluster around planned phase boundaries.
Next step: decode the 20-byte s1p4 frame's position field, then
align per-sample timestamps with segment break indices in a
sample session's map[0].track.


**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_md5 — `content_md5`

MD5 content hash of this session-summary JSON. Used by
SessionArchive for deduplication — re-archiving the same session
is a no-op.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_mode — `mode`

Session mode code = the mow-type op: 100=all_areas, 101=edge, 102=zone,
103=spot, 107=patrol_point (cruise-point), 108=patrol (cruise-side / edge).
Identical to the s2p50 TASK op (100/101/102/103/107/108). This is the
RELIABLE per-session mow-type record — firmware-produced and present in the
OSS summary even for scheduled mows whose s2p50 op never echoed on MQTT.
Distinct from MowerState.action_mode (user dropdown intent, not a record).

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_obstacle — `obstacle_list`

Physical obstacles encountered during the session. Each entry has an id,
type int, and a data polygon of [x_cm, y_mm] vertex pairs. Rendered on
the camera map overlay as obstacle polygons via LiveMapState.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_photo_detected — `photo_detected_flag`

Whether the session captured any auto-capture photo. =1 on the patrol that
took 3 photos. Aligns with s4 eiid1 piid10 (=1 same run) — partial cross-walk
(single sample; needs a photo_detected=0 session to confirm piid10 mapping).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_photo_list — `auto_capture_photo_list`

Auto-Capture patrol photo references. List of bare leaf filenames (no path)
whose stems are UNIX-second timestamps in UTC (1780512275 = 2026-06-03
18:44:35Z = 20:44:35 local). This is THE photo surface for the mower — prior
photo hunts only checked the always-empty ai_obstacle[] and never found this
field. Photo timestamps fall inside the auto-capture-ON point's in-place
rotation window, so they double as the per-point auto-capture evidence.

As of 2026-06-03 the photo bytes were believed unreachable (479D/FDS bucket
hypothesis). App-MITM capture 2026-06-09 resolved this: photos ARE in the
dreame-eu OSS bucket, not 479D. The correct key layout is
oss/media/000000/oss/<uid>/<did>/ali_dreame/<unix_ts>[_person].jpg, where
the photo_list[] stems map 1:1 to these keys. See the 2026-06-09 partial
verification below and dreame-app-implementation-guide-2026-06-09.md §4.

**Open questions:**
- transient-obstacle-photo-api: The transient session-obstacle photos (live-map clickable icons that die after the session) use a different, uncaptured API — no real mow ran. Capture during a real obstacle-hitting mow.
- aiobs-photo-index: The pre-signed photo-index call (returns the album URL set) was not on HTTPS; likely a sendCommand t=AIOBS read or MQTT event (see the AIOBS inventory entry). Not needed for Phase 1 (photo_list suffices).

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_point — `patrol_point_route`

PATROL point route (present on mode=107 point-patrol summaries). One entry
per user-placed patrol point, in route order. Fields: id = per-map point id
(matches the s2p56 queue ids and point_status); point = [x_cm, y_cm, k] map
coords (k=2 observed; third element undecoded); time = the per-point dwell
budget in seconds (60 observed = the app's "1 min" per point); type = point
type (2 observed); param = a nested dict that is EMPTY {} in the only capture
— the requested per-point settings (Number of Patrol Cycles, Auto-Capture)
are NOT stored here. Those settings are command-only and unobservable on
every reachable surface; they are reconstructable from telemetry instead
(cycles = count of in-place ~360° rotations at the point; auto-capture =
whether photo_list timestamps fall in that point's dwell window). See o107.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_point_status — `patrol_point_status`

Final per-point completion state on a mode=107 patrol. Same [id, stage]
shape and vocab as the live s2p56 queue (stage 2 = arrived/done). NB the
order can differ from the `point` route order (observed reversed). Decoded
2026-06-03: point_status=[[4,2],[3,2]] (both points done) for a route
point=[id3, id4].

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_pre_type — `pre_type`

Mowing preference type. Not yet decoded from g2408 captures.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_pref — `global_pref`

Two-int preference array present in ALL session summaries (=[45,0] on both
the mode=107 patrol and a same-day mode=100 all-area mow). Because it is
identical across unrelated session types it is a GLOBAL/account preference,
NOT per-session or per-point input. DEBUNKED as a patrol-settings carrier
(two ints could not encode per-point settings for an arbitrary point count).
Exact meaning of the two ints undecoded.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_recognition — `recognition_flag`

Recognition/AI flag on the patrol summary (=1 observed). Exact meaning
undecoded — possibly whether AI recognition ran on the captured photos.
Recorded for completeness; do not assume semantics.

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_region_status — `region_status`

Per-zone mowing status list. Each entry is [zone_id, status_int].
Status values not fully decoded.

**Open questions:**
- What status values exist? Does 0=complete, 1=skipped, 2=partial?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_result — `result`

Session result code. Value 1 observed on normal completions. Enum not fully
decoded.

**Open questions:**
- What values indicate partial coverage, rain interrupt, or error?

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_spot_track — `spot_track`

Per-spot mowing path for spot-mode sessions (mode 103). The session JSON
carries a global spot[] array enumerating ALL spot areas defined on the
lawn; only the spot that was actually mowed in THIS session has its
`.track` field populated. Other spots in the array have just `.data`
(the corner polygon).

Coordinates are dock-relative centimetres (divide by 100 for metres).
Includes int32-max sentinel rows [2147483647, 2147483647] marking
track breaks (likely lift-up / pen-up moments), same role as
TRACK_BREAK_MARKER in map[].track.

The integration's parse_session_summary._decode_map_layer currently
handles type=0 (boundary) and type=2 (exclusion) but returns None for
type=3 (spot), so this field is silently dropped. Spot mows therefore
get cloud_legs=[] from the parser even though the path is in the blob.
Fix track: extend _decode_map_layer or add a sibling spot-track
extractor.

**Open questions:**
- What's the firmware's emit cadence for spot.track points? 60 pts over 6 min = ~10s/pt — much sparser than s1p4 live (5Hz). Is it a fixed time interval, distance interval, or curated/decimated?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_start — `session_start_unix`

Session start timestamp in Unix seconds. Matches event_occured piid 8
(session-start unix timestamp) to the second. Confirmed across four session
captures 2026-04-17..2026-04-20.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_start_mode — `start_mode`

Session start-trigger mode: 1 = scheduled, 0 = manual/app-triggered
(partial — decoded 2026-05-30; voice / HA-service start values not yet
distinguished, may also map to 0).

**Open questions:**
- Do voice and HA-service starts have distinct start_mode values, or do they collapse to 0 (manual/app)?

**See also:** `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_stop_reason — `stop_reason`

Stop reason code. -1 observed on normal session end.

**Open questions:**
- What stop_reason corresponds to user-cancel vs rain vs fault?

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_time — `duration_minutes`

Session duration in minutes. No scale conversion — value is directly in minutes.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py`, `docs/research/inventory/generated/g2408-canonical.md § Session-summary JSON fields`

### summary_track_break_positions — `track_break_marker_positions`

The int32-max sentinel ``[2147483647, 2147483647]`` appears in every
track field as a segment-break marker. ``_split_track`` splits the
track on these rows into continuous polyline segments. Verified
2026-05-26: 3260 occurrences across 17 OSS blobs, zero variants
(always exactly ``[2147483647, 2147483647]``, never an asymmetric
form with one column normal).

Open question: what triggers a sentinel? Hand-inspection shows
sentinels appearing INSIDE a rectangular spot mow where there is
no obstacle and no map corner to break the path — so the trigger
is something more subtle (lift-up event? brief localisation loss?
mid-row pause? blade-up transition?).

Hypothesis worth investigating: render each sentinel position
(start or end of the surrounding segment, whichever is closer)
as a red diagnostic dot on the work-log map. Plot many sessions'
sentinels together to look for a pattern (clustering near specific
regions, near obstacles, at consistent times-since-last-sentinel,
etc.). The neighbour-pattern analysis showed many sentinels where
``prev == next`` (mower stayed in place) suggesting brief pause/
hover events, but sometimes the next point IS offset by 5-20 cm
(mower drifted or repositioned during the lift-up).

The integration's session-archive currently throws away the sentinel
positions when ``_split_track`` consumes them. To investigate, we'd
either retain the positions on a sidecar (e.g., ``_track_breaks``
with the surrounding segment's start/end (x, y) and ts when
derivable) or re-parse from the raw JSON at render time.

**Open questions:**
- What event in the firmware triggers the sentinel? Lift-up detection? Brief localisation loss? Mid-row pause? Pattern unclear from cluster analysis.
- TODO: Plot sentinel positions as red dots on work-log map (at start OR end of surrounding segment, whichever is closer to the unknown drop position) to look for spatial clustering.

### summary_trajectory — `trajectory_list`

Each entry carries TWO fields with very different roles:

- ``data``: closed-loop lawn outline polygon, ~100-109 cm-encoded points
  (first ≈ last). Identical across every session captured against the
  same lawn snapshot; changes only when the user redraws the boundary
  in the Dreame app.
- ``track``: the actual mowed path for EDGE-MODE sessions (mode 101).
  Same wire convention as boundary.track — list of [x_cm, y_cm] rows
  interleaved with int32-max sentinel rows that split into continuous
  segments. Empty for non-edge modes.

So the field name "trajectory" is a misnomer: ``data`` is geometry,
``track`` is per-session path data — and only present for edge.

Coordinate frame: dock-relative centimetres.

Mode-to-path-source mapping (full survey):
  mode 100 (all_areas / zone) → map[i].track
  mode 101 (edge)             → trajectory[].track    ← here
  mode 102 (all_areas)        → map[i].track
  mode 103 (spot)             → spot[N].track for mowed N

## M_PATH encoding

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| m_path_chunked | chunked_assembly | M_PATH.0 + M_PATH.1 + ... + M_PATH.info | WIRED |  |
| m_path_scale | coordinate_scale_x10 | [x, y] int16 pairs | WIRED | m (×0.01) |
| m_path_sentinel | segment_break_sentinel | [32767, -32768] | WIRED |  |

### m_path_chunked — `chunked_assembly`

The M_PATH live trail is chunked across multiple userdata keys with
M_PATH.info supplying the split position. Reassemble by concatenating
M_PATH.0..N in order before parsing the points array.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py:129`, `docs/research/2026-04-23-iobroker-dreame-cross-reference.md §M_PATH`, `apk: ioBroker.dreame/apk.md §M_PATH`, `alternatives/dreame-mower/dreame/map_data_parser.py:256-284`

### m_path_scale — `coordinate_scale_x10`

M_PATH coordinates are ~10× smaller than MAP.* coordinates. Multiply each
raw [x, y] value by 10 before projecting onto the map image. The scale factor
was derived from the ioBroker cross-reference; not yet independently validated
against a g2408 capture where M_PATH and MAP.* are both present.

**Open questions:**
- Validate ×10 factor against a live g2408 M_PATH + MAP capture mid-mow.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py:129`, `docs/research/2026-04-23-iobroker-dreame-cross-reference.md §M_PATH`, `alternatives/dreame-mower/dreame/map_data_parser.py:256-284`

### m_path_sentinel — `segment_break_sentinel`

Sentinel value marking a path segment break in M_PATH. Equivalent in role to
the [2147483647, 2147483647] max-int sentinel in the session-summary map[].track
array, but using 16-bit max/min values because M_PATH coordinates are 16-bit
signed integers.

**See also:** `custom_components/dreame_a2_mower/protocol/session_summary.py:29`, `docs/research/2026-04-23-iobroker-dreame-cross-reference.md §M_PATH`, `alternatives/dreame-mower/dreame/map_data_parser.py:256-284`

## LiDAR PCD format

| id | name | shape | status | unit |
|----|------|-------|--------|------|
| pcd_ascii_header | pcd_ascii_header | ASCII text block terminated by 'DATA binary\n' | WIRED |  |
| pcd_data_binary | pcd_binary_body | N × bytes_per_point little-endian binary | WIRED |  |
| pcd_oss_path | pcd_oss_object_key | string (OSS object key, .bin extension) | WIRED |  |
| pcd_upload_trigger | pcd_upload_trigger | user-initiated via Dreame app 'View LiDAR Map' | WIRED |  |

### pcd_ascii_header — `pcd_ascii_header`

PCD v0.7 ASCII header. Required keys: VERSION, FIELDS, SIZE, TYPE, COUNT,
WIDTH, HEIGHT, POINTS, DATA (optional: VIEWPOINT). The g2408 firmware emits
a binary-DATA unorganised cloud (HEIGHT=1). The integration's decode_pcd_header
in pcd.py finds the DATA line, splits on newline, decodes key-value pairs,
and validates all required keys are present before advancing body_offset to
the first post-header byte.

Observed g2408 header shape:
  VERSION 0.7
  FIELDS x y z rgb
  SIZE 4 4 4 4
  TYPE F F F U
  COUNT 1 1 1 1
  WIDTH <N>
  HEIGHT 1
  VIEWPOINT 0 0 0 1 0 0 0
  POINTS <N>
  DATA binary

153 261 points confirmed in the 2026-04-20 capture (2.45 MB total).

**See also:** `custom_components/dreame_a2_mower/protocol/pcd.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### pcd_data_binary — `pcd_binary_body`

Binary point data block immediately following the header. Layout per field
descriptor from the header: each field is a little-endian word of the
declared SIZE bytes and TYPE. For the g2408 shape (FIELDS x y z rgb, SIZE 4
4 4 4, TYPE F F F U): 4× float32 per point = 16 bytes per point. The 'rgb'
field is packed as a uint32 (R<<16 | G<<8 | B). The integration uses
numpy.frombuffer with a structured dtype to decode all fields in one pass.

**See also:** `custom_components/dreame_a2_mower/protocol/pcd.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### pcd_oss_path — `pcd_oss_object_key`

Aliyun OSS path for the LiDAR PCD binary blob. Arrives in s99p20 BEFORE
s2p54 = 100 (at ~61% upload progress). Format:
ali_dreame/YYYY/MM/DD/<master-uid>/<did>_HHMMSSmmm.MMMM.bin.
The integration fetches via cloud.get_interim_file_url (getDownloadUrl
endpoint) → signed OSS URL → HTTP GET, then writes to the LiDAR archive
under <config>/dreame_a2_mower/lidar/YYYY-MM-DD_<ts>_<md5>.pcd.
Content-addressed by md5; re-tapping the same scan is a no-op.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

### pcd_upload_trigger — `pcd_upload_trigger`

The PCD upload is triggered by the user tapping "View LiDAR Map" in the
Dreame app, provided the current scan differs from the last-uploaded one.
Re-opening the screen with no scan change is a no-op (the firmware skips
the upload). The upload takes ~30 seconds for a 2.45 MB / 153 261-point
cloud over WiFi. s2p54 (0..100 progress) drives the progress indicator;
s99p20 signals completion before the final s2p54 = 100 tick.

**See also:** `custom_components/dreame_a2_mower/coordinator.py`, `docs/research/inventory/generated/g2408-canonical.md § Events`

