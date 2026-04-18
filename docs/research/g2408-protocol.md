# Dreame A2 (`g2408`) Protocol Reference

Consolidated findings from MQTT + Dreame cloud probing of a live A2 mower. Complements
[`2026-04-17-g2408-property-divergences.md`](./2026-04-17-g2408-property-divergences.md)
(property-mapping divergence catalog) with wire-level detail for each property and a
map-fetch flow model.

Primary probe tool: `probe_a2_mqtt.py` (top-level in repo — authenticates as the Dreame
app, subscribes to `/status/<did>/...` and passes raw payloads through a pretty-printer).
Findings cover model `dreame.mower.g2408`, region `eu`, firmware as shipped 2026-04 on
the user's device.

---

## 1. Transport layer

Two communication channels reach the mower, **plus a mobile-only third one**:

| Channel | Direction | Works on g2408? |
|---|---|---|
| Dreame cloud MQTT — device → cloud | **push from mower** | ✅ consistently |
| Dreame cloud HTTP `sendCommand` — cloud → device | **commands to mower** | ❌ returns HTTP code `80001` ("device unreachable") even while actively mowing |
| Bluetooth (phone ↔ mower direct) | **config writes from app** | ✅ but invisible from cloud/HA |

The HA integration's `protocol.py` has fallback logic for the HTTP failure path. In
practice the integration is **read-mostly** on g2408: telemetry arrives reliably via
the MQTT push; any property the mower exposes only in response to an HTTP poll is
effectively unavailable.

### 1.1 Cloud endpoints (region `eu`)

| Purpose | Endpoint |
|---|---|
| Auth | `https://eu.iot.dreame.tech:13267/dreame-user-iot/iotuserbind/` |
| Device info | `POST /dreame-user-iot/iotuserbind/device/info` |
| OTC info | `POST /dreame-user-iot/iotstatus/devOTCInfo` |
| MQTT broker | `10000.mt.eu.iot.dreame.tech:19973` (TLS) |
| MQTT status topic | `/status/<did>/<mac-hash>/dreame.mower.g2408/eu/` |
| `sendCommand` | `POST /dreame-iot-com-10000/device/sendCommand` (fails with 80001) |

### 1.2 `80001` failure mode

`cloud → mower` RPCs fail as `{"code": 80001, "msg": "device unreachable"}` **even while**
the mower is pushing live telemetry over MQTT on the same connection. Observed 373
instances across one ~90 min session. This asymmetry has persisted across every
observed session.

**Working hypothesis:** the g2408's cloud-RPC tunnel opens only during a narrow post-
handshake window; our fork has never hit one in practice. Historical probe logs from
2026-04-17 captured 5 `s6p1: 200 ↔ 300` cycles over 12 hours that DID trigger successful
map fetches, suggesting the tunnel does open intermittently but not predictably.

---

## 2. MQTT property catalog

Siid/piid combinations observed on g2408. All properties arrive as JSON-encoded
`properties_changed` or `event_occured` messages on the `/status/.../eu/` topic.

### 2.1 Summary table

| siid.piid | Name | Shape | Meaning |
|---|---|---|---|
| 1.1 | `HEARTBEAT` | 20-byte blob | Mower-alive ping; state machine hints; see §3.2 |
| 1.4 | `MOWING_TELEMETRY` | 33/10/8-byte blob | Position, phase, area, distance; see §3.1 |
| 1.50 | — | `{}` | Empty dict at session boundaries |
| 1.51 | — | `{}` | Empty dict at session boundaries |
| 1.52 | — | `{}` | Empty dict at session boundaries |
| 1.53 | `OBSTACLE_FLAG` | bool | Obstacle / person detected near mower (§5) |
| 2.1 | (misc mode byte) | `{1, 2, 5}` | **Not STATE** — small enum, semantic TBD |
| 2.2 | `STATE` (g2408) | `{27, 48, 50, 54, 70, ...}` | Mower state machine (§4) |
| 2.50 | Session task metadata | `{area_id, exe, o, region_id, time, t}` | Emitted at session start |
| 2.51 | `MULTIPLEXED_CONFIG` | shape varies | App "More Settings" writes (§6) |
| 2.56 | Cloud status push | `{status}` | Internal ack |
| 2.66 | — | `[379, 1394]` | 2-element list, unknown |
| 3.1 | `BATTERY_LEVEL` | int `0..100` | % battery |
| 3.2 | `CHARGING_STATUS` | int `{0, 1, 2}` | `0`=not charging on g2408 (enum offset vs upstream) |
| 5.105 | — | `1` | Mid-session appearance, unknown |
| 5.106 | — | `{3, 5, 7}` | Dynamic, unknown |
| 5.107 | — | `{133, 176, 250, 158}` | Dynamic, unknown |
| 6.1 | `MAP_DATA` | `{200, 300}` | Map-readiness signal; triggers fetch (§7) |
| 6.2 | `FRAME_INFO` | list len 4 | Map frame metadata |
| 6.3 | `OBJECT_NAME` | string | OSS object key for the uploaded map (§7) |

### 2.2 Upstream-divergence cheat-sheet

The upstream `dreame-mova-mower` mapping is built for other Dreame mowers and swaps
two critical properties at siid=2:

| | upstream | g2408 actual |
|---|---|---|
| `(2, 1)` | `STATE` | misc mode (1/2/5) |
| `(2, 2)` | `ERROR` | `STATE` codes (48, 54, 70, 50, 27, …) |

The g2408 overlay (`_G2408_OVERLAY` in `types.py`) swaps these back. See
`2026-04-17-g2408-property-divergences.md` for the full divergence catalog.

---

## 3. Blob decoders

### 3.1 `s1p4` — MOWING_TELEMETRY (33-byte frame)

Full frame, used throughout an active mowing task:

```
offset  type         field
[0]     uint8        0xCE          frame delimiter
[1-2]   int16_le     x_cm          X position in centimetres (charger-relative)
[3-4]   int16_le     y_mm          Y position in millimetres (charger-relative)
[5]     uint8        0x00          static
[6-7]   uint16_le    sequence
[8]     uint8        phase         0=MOWING, 1=TRANSIT, 2=PHASE_2, 3=RETURNING
[9]     uint8        0x00          static
[10-17] 4× int16_le  motion vectors; mv1 ≈ X velocity (mm/s);
                     mv2 ≈ Y velocity; others likely heading / angular rate
[18-21] 2× int16_le  paired sentinel/active pattern, unknown quantity
[22-23] flags        [22] 0→1 after init; [23]=2
[24-25] uint16_le    distance_deci      ÷ 10 → metres
[26-27] uint16_le    total_area_cent    ÷ 100 → m² (total mowable area)
[28]    uint8        0x00          static
[29-30] uint16_le    area_mowed_cent    ÷ 100 → m² (area cut this session)
[31]    uint8        0x00          static
[32]    uint8        0xCE          frame delimiter
```

Distance / area counters reset at the start of each mowing session.

#### Coordinate frame (charger-relative)

- **Origin (0, 0) = charging station.** Verified by convergence on return-to-dock.
- **+X axis points toward the house** (the nose direction when the mower is docked).
  -X points away from the house into the lawn.
- **±Y is perpendicular**, left/right when facing the house.
- The lawn polygon sits at whatever angle fences happen to take relative to this
  mower frame — there is no rotation applied per session.
- X is in **cm** at bytes [1-2]. Y is in **mm** at bytes [3-4]. The axes use
  different scales on the wire.

#### Y-axis calibration

The Y wheel's encoder reports ~1.6× the true distance. Multiply raw `y_mm` by **0.625**
(configurable per-install) to land in real metres. X needs no calibration.

Origin of the 0.625 factor is tape-measure-verified across two sessions:

| Mower position | Laser-measured | Decoder Y (mm) | Factor (actual / decoder) |
|---|---|---|---|
| Paused on Y-aligned straight-line at dock | 10.3 m | 16624 | 0.620 |
| Peak session Y during mow | ~10.0 m (est) | 15855 | 0.631 |

Cross-tested 2026-04-17 under both X-axis and Y-axis mowing patterns: the 0.625
constant applies to Y regardless of which axis is sweeping, so it's firmware /
encoder — not turn-drift accumulation.

#### Phase byte semantics — **byte [8] is a zone-ID, not a routing mode**

Byte `[8]` drives the `Phase` enum. Current labels (`MOWING / TRANSIT / PHASE_2 /
RETURNING`) reflect an **earlier, incorrect interpretation** — they should be
considered placeholders. The real semantic, confirmed 2026-04-18:

Session 2 trajectory analysis showed the four observed phase values occupying
**four non-overlapping X regions** with exactly one transition at each boundary:

| phase_raw | X range | Y range (calibrated) | Notes |
|---|---|---|---|
| 1 | -10.3 .. -9.0 m | -5.7 .. 6.8 m | Tiny — just the transit corridor out of the dock |
| 2 | -10.4 .. 2.9 m | -9.8 .. 15.0 m | Main area west of X ≈ 2.86 m |
| 3 | 0.2 .. 14.4 m | -9.8 .. 4.5 m | Middle strip between X ≈ 2.86 m and X ≈ 14.35 m |
| 4 | 14.3 .. 20.1 m | -0.2 .. 6.7 m | Area east of X ≈ 14.35 m — newly-added-and-merged zone on user's lawn |

Three transitions observed in one session, each at a crisp X coordinate:

```
19:08:01  ph 1 → 2    at x = -10.21 m   (dock exit → main area)
19:35:56  ph 2 → 3    at x =   2.86 m   (zone boundary)
20:56:01  ph 3 → 4    at x =  14.35 m   (zone boundary into user's new merged area)
```

No flip-flopping, no mid-zone phase changes, no correlation with micro-turns or
battery thresholds. Each phase value is stable over hundreds of samples while
the mower is inside its corresponding zone.

**Conclusion: `phase_raw` is the zone-ID the firmware is currently mowing in.**
This explains a user observation that the firmware still treats a *merged* zone
(one that was added in-app, which overlapped an existing zone and thus got
consolidated on close) as two zones internally — the mower stops and turns at
the former boundary (an "invisible line" to the app map), which is exactly where
`phase_raw` flips.

**Practical implications:**
- The `Phase` enum labels (`MOWING=0, TRANSIT=1, PHASE_2=2, RETURNING=3`) should
  be retired and replaced with something like `ZONE_0, ZONE_1, …`, or dropped
  entirely in favour of exposing the raw integer as a `zone_id` sensor.
- The earlier "ph=1 = pre-return narrow turning" table in the session-handoff
  was wrong: narrow turning is a micro-behaviour, not a zone change.
- Value `4` (currently decoded as `Phase.UNKNOWN` because it's not in the enum)
  is not a bug — it's a real zone the user has. Decoder should accept it.
- `RETURNING=3` is a particularly misleading label: in session 2 the mower
  mowed ph=3 for 28 minutes in the middle of the lawn and then dock-approached
  from within ph=3 when battery hit 38%. "Returning" is orthogonal to the zone;
  it's the dock-approach behaviour, not a phase value.

Follow-up data collection would pin down zone polygons (these X boundaries are
1D projections — the real zones are 2D polygons on the map).

### 3.2 `s1p4` — 8-byte beacon variant

Emitted while mower is idle/docked or under remote control. X and Y at the same
offsets as the 33-byte frame, no phase/session/area fields.

```
[0]     0xCE
[1-2]   int16_le   x_cm
[3-4]   int16_le   y_mm
[5]     0x00
[6]     ?
[7]     0xCE
```

### 3.3 `s1p4` — 10-byte BUILDING variant

Emitted while the mower is in BUILDING state (map-learn / zone-expand). Same X/Y
header as the beacon plus two uncharacterized bytes at [6-7]:

```
[0]     0xCE
[1-2]   int16_le   x_cm
[3-4]   int16_le   y_mm
[5]     0x00
[6-7]   ??         purpose not yet decoded
[8]     ?
[9]     0xCE
```

### 3.4 `s1p1` — HEARTBEAT (20-byte blob)

Sent every ~45 seconds regardless of state. `0xCE` delimiters at the ends.

| bytes | meaning |
|---|---|
| [4] | pulse `0x00 → 0x08 → 0x00` lasting ~0.8 s during a **human-presence-detection event**. Evidence: session 2 (2026-04-18) showed byte[4]=0x08 exactly twice at 21:04:39.580 and 21:04:40.210; the user confirmed the Dreame app raised a human-in-mapped-area alert at that same moment. Byte is `0x00` at all other times across the whole session. Single-event datapoint — reproduce before relying on it. |
| [7] | 0=idle, 1 or 4 = state transitions |
| [9] | 0/64 pulse at mow start |
| [11-12] | monotonic counter |
| [14] | state machine during startup: 0 → 64 → 68 → 4 → 5 → 7 → 135 |

Related coincident MQTT events at the same human-presence moment (21:04:39):
- `s2p2 = 27` (IDLE) emitted **twice** in a single second while the mower was
  demonstrably still moving (MOWING_TELEMETRY position continued changing through
  the window). So `s2p2 = 27` at runtime is not literal "idle" — it may be a
  query-response or alert-acknowledgement token.
- `s1p53` (OBSTACLE_FLAG) went `True → False` 7 s later at 21:04:46 — but it had
  been latched True since 20:43:16 (an earlier obstacle, ~21 min prior), so the
  clear is not directly tied to the human event; more likely a side-effect of
  whatever state transition happened.

### 3.5 `s1p53` — OBSTACLE_FLAG

Boolean. Set `True` when the mower detects an obstacle/person/animal during mowing.
**Never sent `False` automatically** — HA entity must auto-clear after ~30 s of no
refresh, otherwise it latches indefinitely. See Open Item 0e in
`project_g2408_reverse_eng` memory.

---

## 4. State machine

### 4.1 `s2p2` state codes

| Value | Meaning |
|---|---|
| 27 | idle |
| 48 | mowing complete |
| 50 | session started |
| 54 | returning |
| 70 | mowing (edge / standard) |

### 4.2 `s2p1` mode enum (separate from state)

| Value | Meaning |
|---|---|
| 1 | MOWING |
| 2 | IDLE |
| 5 | RETURNING |
| 6 | CHARGING |

### 4.3 Observed session transitions

**Low-battery auto-return** (well-formed; triggers map push):
```
MOWING(1) → IDLE(2) → RETURNING(5) → CHARGING(6)
s2p2: 70 → 54
s6p1:    → 300   ← MAP_DATA ready signal
s2p56:   → [[1,4]]
s1p4 converges to (0,0)
```

**Manual "End" while docked** (no map push):
```
s2p2 → 48 (MOWING_COMPLETE)
s1p52 → {}
s2p50 → {task metadata}
no s6p1, no state transitions
```

**Session start** (from dock):
```
s2p56: [[1,4]] → []
s2p2:   → 50
CHARGING → MOWING
s2p50 gains {area_id, exe, o:100, region_id:[1], time:10510, t:'TASK'}
s5p107 changes dynamically: 176 → 250 → 133 → 158 (driver unknown)
```

**Mid-task recharge** (observed 2026-04-18): the mower can pause for a mid-task
recharge and resume mowing once topped off. The task is not considered complete
during this pause; `s1p4` telemetry continues throughout the return leg. No map
push observed at the pause itself — only at true session completion.

### 4.4 `s1p4` telemetry lifecycle

Position telemetry fires throughout an active TASK, including the return-to-dock
leg of a low-battery auto-recharge. It stops only when the task itself ends
(`s2p1` transitions to `2` = complete / cancelled).

---

## 5. Obstacle detection

`s1p53` fires `True` near obstacles and excluded areas during mowing. Observed
26 triggers in ~15 min near an exclusion zone, mean duration ~6.6 s. Separate
from human-presence detection (which goes through the Dreame cloud push-notification
service directly, not via MQTT — HA integration cannot observe it).

---

## 6. `s2p51` — multiplexed configuration writes

All "More Settings" toggles in the Dreame app that travel via cloud share this
single property. The payload shape discriminates the setting:

| Setting | Payload |
|---|---|
| Do Not Disturb | `{'end': min, 'start': min, 'value': 0\|1}` |
| Low-Speed Nighttime | `{'value': [enabled, start_min, end_min]}` |
| Navigation Path | `{'value': 0\|1}` (0=Direct, 1=Smart) |
| Charging config | `{'value': [recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min]}` |
| Auto Recharge Standby | `{'value': 0\|1}` |
| LED Period | `{'value': [enabled, start_min, end_min, standby, working, charging, error, reserved]}` |
| Anti-Theft | `{'value': [lift_alarm, offmap_alarm, realtime_location]}` |
| Child Lock | `{'value': 0\|1}` |
| Rain Protection | `{'value': [enabled, resume_hours]}` |
| Frost Protection | `{'value': 0\|1}` |
| AI Obstacle Photos | `{'value': 0\|1}` |
| Human Presence Alert | `{'value': [enabled, sensitivity, standby, mowing, recharge, patrol, alert, photos, push_min]}` |
| Timestamp event | `{'time': 'unix_ts', 'tz': 'Europe/Oslo'}` |

Times are minutes from midnight. All confirmed via live toggle testing.

### 6.1 Cloud-visible vs Bluetooth-only settings

**Cloud/MQTT (visible in `s2p51`):** Do Not Disturb, Low-Speed Nighttime,
Navigation Path, Charging config, Auto Recharge Standby, LED Period, Anti-Theft,
Child Lock, Rain Protection, Frost Protection, AI Obstacle Photos, Human Presence
Detection Alert.

**Bluetooth-only (completely invisible from cloud/HA):**
- Obstacle Avoidance Distance
- Obstacle Avoidance Height
- Start from Stop Point
- Pathway Obstacle Avoidance
- Obstacle Avoidance on Edges
- Mowing Direction — verified BT-only (toggled 180°↔90°, zero MQTT traffic)
- Likely all General Mode settings: Mowing Efficiency, Mowing Height, Automatic
  Edge Mowing, Safe Edge Mowing, EdgeMaster, LiDAR Obstacle Recognition, AI
  Recognition sub-toggles, schedule changes, Robot Voice/Volume.

The Dreame app holds a direct BT connection to the mower while open. Write-path
settings chosen by the app code itself; the user has no control over which
transport is used. For the HA integration this means **entities for BT-only
settings cannot exist** — users must be told explicitly in the README which
settings will be missing.

---

## 7. Map-fetch flow (s6p1 / s6p3 + OSS)

This is the active investigation thread. The A2 does **not** push the map as a
single MQTT blob the way some older Dreame devices do. Instead:

```
┌─────────┐   1. map ready    ┌──────────────┐   2. upload    ┌──────────────┐
│  Mower  │ ───────────────→  │ Dreame cloud │ ─────────────→ │ Aliyun OSS   │
└─────────┘   (MQTT push)     └──────────────┘                │ bucket       │
     │                                                        └──────────────┘
     │ 3. push s6p1, s6p3 via MQTT                                      ▲
     │    - s6p1 value cycles 200 ↔ 300 to signal "new map available"  │
     │    - s6p3 carries the object-name key inside the bucket         │
     ▼                                                                  │
┌─────────┐   4. observe s6p3         ┌──────────────┐   5. HTTP fetch  │
│   HA    │ ─────────────────────────▶ │ OSS signed  │ ─────────────────┘
│  fork   │   getFileUrl(object_name)  │ URL (short- │
└─────────┘ ◀───────────────────────── │  lived)     │
                  PNG map data         └──────────────┘
```

### 7.1 Trigger conditions (from historical observations)

`s6p1` value transitions and map-fetch correlation, 2026-04-17 probe log:

| Event | `s6p1` | Map fetched? |
|---|---|---|
| Low-battery auto-return | `200 → 300` | ✅ yes |
| User tap "End" while docked | no change | ❌ |
| Manual pause | no change | ❌ |
| Session start | `300 → 200` | ❌ (but prepares for next) |

In 12 hours of observation, **5** `200 ↔ 300` cycles were seen. Not every mowing
session triggers a fresh upload; the cycle appears tied to "mower has observed
enough new map data to be worth uploading" rather than to session lifecycle.

### 7.2 Failure modes seen on our fork

1. **`getFileUrl("")` returns 404** — querying the OSS URL without the object
   name yields a signed URL that 404s, confirming the bucket is empty for the
   object name we guess.
2. **`get_properties(s6p3)` returns `None` while mower is idle** — the property
   only materializes when there's a pending map.
3. **`get_properties(anything)` returns `{"code":10001,"msg":"消息不能读取"}` when the
   mower is idle** — Chinese "message cannot be read"; the cloud→mower RPC
   channel is quiescent, so no property snapshot can be pulled on demand.
4. **Our fork's `_request_current_map()` fails with `80001`** during active mowing
   for the same reason `sendCommand` always fails — see §1.2.

### 7.3 What we know works

- The mower → cloud MQTT push pipeline works reliably.
- Mid-task recharge does **not** trigger a fresh map push; only actual session
  completion does.
- Historical 2026-04-17 data shows the upstream A1 Pro client DID fetch our A2's
  map successfully (file `map_live.png`), so the OSS side of the flow works —
  our fork just hasn't caught an `s6p3` push yet.

### 7.4 Diagnostic logging currently enabled

`MAP_TRACE` INFO logs added in `dreame/map.py` at five branch points in
`update()` to trace the fetch decision. Enable at runtime via:

```bash
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -X POST "http://$HA_HOST:8123/api/services/logger/set_level" \
  -d '{"custom_components.dreame_a2_mower.dreame.map":"debug",
       "custom_components.dreame_a2_mower.dreame.device":"debug",
       "custom_components.dreame_a2_mower.dreame.protocol":"debug"}'
```

Reverts on HA restart.

---

## 8. Known unknowns

See `project_g2408_reverse_eng.md` memory for the full open-items list. The
shorter version here:

- `s2p1` small enum `{1, 2, 5}`: not the state, not the error. Possibly warning
  or mode sub-state.
- `s5p105 / s5p106 / s5p107`: dynamic telemetry values. No user-facing event
  correlates cleanly.
- `s1p4` motion-vector bytes `[10-21]`: velocity hints identified, full decode
  open.
- `s1p50 / s1p51 / s1p52`: empty dicts at session boundaries — may carry data
  in other scenarios.
- `s2p66`: `[379, 1394]` list — unknown.
- `s6p2` FRAME_INFO: 4-tuple `[35, 0, True, 2]`, shape suggests
  `[battery_pct, flag, bool, version]` but not verified.

---

## 9. References

- `probe_a2_mqtt.py` — live probe + pretty-printer
- `custom_components/dreame_a2_mower/protocol/telemetry.py` — `s1p4` decoder
- `custom_components/dreame_a2_mower/dreame/map.py` — map-fetch coordinator
- `docs/research/2026-04-17-g2408-property-divergences.md` — property-mapping catalog
- Probe-log samples under `/data/claude/homeassistant/probe_log_*.jsonl` (off-repo)
