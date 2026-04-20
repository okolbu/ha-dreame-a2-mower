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

### 1.2 `80001` failure mode — expected, not a bug

`cloud → mower` RPCs (`set_properties`, `action`, `get_properties`) fail as
`{"code": 80001, "msg": "device unreachable"}` **even while** the mower is
pushing live telemetry over MQTT on the same connection. The HA log surfaces
this as:

```
WARNING ... Cloud send error 80001 for get_properties (attempt 1/1): 设备可能不在线，指令发送超时。
WARNING ... Cloud request returned None for get_properties (device may be in deep sleep)
WARNING ... Cloud send error 80001 for action (attempt 1/3): 设备可能不在线，指令发送超时。
WARNING ... Cloud request returned None for action (device may be in deep sleep)
```

**This is the g2408's normal behaviour, not a transient error.** Treat these
WARNINGs as signal that the cloud-RPC write path is unavailable. Don't open
issues for them; they are already documented here. They persist across every
observed session (373 instances in one ~90 min session observation).

**Scope of what 80001 breaks:**
- ❌ `lawn_mower.start` / `.pause` / `.dock` service calls route via `action()`
  → hit 80001, silent no-op from the user's perspective.
- ❌ `set_property` writes (config changes) route the same way.
- ❌ `get_properties(...)` one-shot pulls.

**Scope of what still works** (different cloud endpoint, different auth path):
- ✅ MQTT property push from the mower → HA coordinator (the whole read pipeline).
- ✅ Session-summary JSON fetch via `get_interim_file_url` + OSS signed URL.
- ✅ LiDAR PCD fetch via the same getDownloadUrl / OSS path.
- ✅ Login / device discovery / getDevices.

So historically we've pulled session-summary JSONs and LiDAR point clouds
successfully even while the command path was returning 80001 the entire
session. The two paths share the account session cookie but hit different
endpoints on the Dreame cloud; the write path needs the mower's RPC tunnel
to be open, the fetch path does not.

**Working hypothesis** (unchanged): the g2408's cloud-RPC tunnel opens only
during a narrow post-handshake window; our fork has never hit one in
practice. The 2026-04-17 probe captured 5 `s6p1: 200 ↔ 300` cycles over
12 hours that DID trigger successful map fetches — but those were using
the getDownloadUrl / OSS path, not the RPC tunnel.

**Future work:** an MQTT-publish write path on the `/request/` or `/command/`
topic would bypass 80001 entirely. See open item 0 in the
`project_g2408_reverse_eng.md` memory.

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
| 2.50 | TASK envelope — multiple operation classes | shape varies by `d.o` | Session start (mowing): flat fields `{area_id, exe, o:100, region_id:[1], time, t:'TASK'}`. **Map-edit** (zone / exclusion-zone add/edit/delete): wrapped `{d:{exe, o, status, ...}, t:'TASK'}` with a pair of pushes per edit — request `o:204` then confirm `o:215` carrying `id` (edit-txn #), `ids` (affected zone ids), `error`. See §4.6. |
| 2.51 | `MULTIPLEXED_CONFIG` | shape varies | App "More Settings" writes (§6) |
| 2.56 | Cloud status push | `{status}` | Internal ack |
| 2.66 | Lawn-size snapshot | `[area_m2, ???]` | **First element = total mowable lawn area in m²** (matches `event_occured` piid 14 from the session-summary exactly). Observed `[379, 1394]` 2026-04-17, `[384, 1386]` 2026-04-20 after a manual "Expand Lawn". Second element unknown — decreased by 8 when area grew by 5 m², so not perimeter-proportional; candidates: blade-hours ×10, unique path segments, or a total-distance-mown counter. Fires at the end of a BUILDING session (§4.3) and probably periodically during mowing. |
| 3.1 | `BATTERY_LEVEL` | int `0..100` | % battery |
| 3.2 | `CHARGING_STATUS` | int `{0, 1, 2}` | `0`=not charging on g2408 (enum offset vs upstream) |
| 5.105 | — | `1` | Mid-session appearance, unknown |
| 5.106 | — | `1..7` | **Cycles 1→7 over ~3 hours**, ~30 min per step. Probably a rolling status-report counter (7 slots per cycle, one advance every ~30 min). Observed full 1-7 span across the 2026-04-20 run plus a spontaneous `value=7` push at 15:04:52 while the mower was docked. Not tied to mowing state. |
| 5.107 | — | `{14, 15, 43, 133, 158, 165, 176, 190, 196, 250}` | Dynamic, changes at session boundaries and mid-mow. Unknown. |
| 6.1 | `MAP_DATA` | `{200, 300}` | Map-readiness signal; `300` at auto-recharge-leg-start (§7.1). |
| 6.2 | `FRAME_INFO` | list len 4 | Map frame metadata |
| 6.3 | **WiFi signal push** (g2408) / `OBJECT_NAME` (upstream) | list `[bool, int]` on g2408 | `[cloud_connected, rssi_dbm]`. NOT the OSS object key — upstream's `OBJECT_NAME` slot is unused on g2408 (session-summary key arrives via `event_occured` instead, see §7.4). Our overlay remaps `OBJECT_NAME` to `999/998` so the map handler does not misinterpret s6p3 pushes. |

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

#### Phase byte semantics — **byte [8] is a task-phase index**

Byte `[8]` drives the `Phase` enum. Current labels (`MOWING / TRANSIT / PHASE_2 /
RETURNING`) reflect an **earlier, incorrect interpretation** — they should be
considered placeholders. The real semantic, confirmed 2026-04-18 via live
trajectory observation across a 3-hour session:

**`phase_raw` is the index into the mower firmware's pre-planned job sequence.**
The firmware decomposes each mowing task into an ordered list of sub-tasks
(area-fill of each zone, edge passes, …), and the byte reports which sub-task
the mower is currently on. Phase advances monotonically through the plan; once
a value is done the mower never returns to it in the same session.

Session 2 observations by phase:

| phase_raw | Samples | X range | Y range (cal) | Likely role |
|---|---|---|---|---|
| 1 | 33 | -10.3..-9.0 m | -5.7..6.8 m | Dock transit corridor |
| 2 | 329 | -10.4..2.9 m | -9.8..15.0 m | Zone area-fill (west) |
| 3 | 293 | 0.2..14.4 m | -9.8..4.5 m | Zone area-fill (middle strip) |
| 4 | 234+ | 12.1..20.5 m | -1.5..6.7 m | Zone area-fill (east / the user's newly-added-and-merged zone) |
| 5 | 22+ | 7.3..20.7 m | -5.1..1.5 m | **Edge mow** — narrow Y spread, spans multiple zones in X |
| 6 | 29+ | -6.6..8.6 m | -14.0..-6.2 m | Next edge/zone |
| 7 | 3+ | -9.6..-8.7 m | -8.4..-6.3 m | Just starting — semantic TBD |

Transitions (monotonic, non-repeating, each at a crisp coordinate):

```
19:08:01  ph 1 → 2    at x = -10.21 m   (dock exit)
19:35:56  ph 2 → 3    at x =   2.86 m   (zone boundary)
20:56:01  ph 3 → 4    at x =  14.35 m   (into user's merged zone)
21:15:41  ph 4 → 5    at x =  20.22 m   (far east — area-fill done, edge mow starts)
21:17:31  ph 5 → 6    at x =   8.18 m   (next edge/zone)
21:20:06  ph 6 → 7    at x =  -8.70 m
```

**`phase_raw = 15` during post-complete return** (new 2026-04-20): the last
23 `s1p4` frames of the full-run (12:33:11-12:33:56, *after* `s2p56=[[1,2]]`
and `s2p2=48` declared the task complete and before the mower reached the
dock) all reported `phase_raw = 15`. Counters were frozen at the session's
final values (`distance=10000` decis, `mowed=29358` centi-m²) — the mower
was no longer mowing, just driving home. Treat high phase values as
"return-home" rather than a real task index; the post-complete return
reuses the phase slot rather than emitting a separate state. Earlier phases
topped out at 7 so 8-15 are either edge-variant indices on denser lawns or
specific post-complete transport codes — more captures needed to separate.

The **first group** (low phase values) look like per-zone area-fills: each
occupies a distinct non-overlapping X region and is stable over hundreds of
samples inside it. The **later group** (higher values, starting around 5) have
different spatial shapes — narrow Y spread and crossing several zone
boundaries in X — consistent with perimeter / edge-mow passes once all the
bulk area-fill is done.

**User-visible artefact confirming the zone-indexed plan:** the user added a
new in-app zone that auto-merged with an existing one on close (area overlap
triggers auto-merge). The firmware still plans two separate area-fill phases
for the two components — mower stops and turns at the former-now-invisible
boundary at X=14.35 m, which is exactly where `phase_raw` flips 3→4. The
in-app merge collapsed the display but not the internal task plan.

**Practical implications:**
- The `Phase` enum labels `MOWING/TRANSIT/PHASE_2/RETURNING` should be retired.
  They carry meaning the byte does not have.
- Expose the raw integer as a `task_phase` or `mowing_zone` diagnostic sensor
  rather than translating through the misleading enum.
- Multiple values per session is expected — we saw 6 distinct values in one
  session here. Decoder should accept any small positive int.
- Different mowing jobs (all-zones vs single-zone vs edge-only) will likely
  expose different subsets of phase values.
- No single value is "edge mode" or "transit" universally — the meaning of a
  phase value is bound to the current task plan, which is itself determined by
  the zone layout. Cross-user portability of exact values is unlikely.

### 3.2 `s1p4` — 8-byte beacon variant

Emitted in **three** distinct situations, same layout:

1. **Idle / docked / remote control** — mower parked, sending position-only heartbeats.
2. **Start-of-leg preamble** — fired exactly once ~37-45 s after each `s2p1 → 1` transition (session start, and each resume after an auto-recharge interrupt). Three consecutive 8-byte frames observed during the 2026-04-20 full-run (07:58:40, 10:03:55, 12:07:50) before the 33-byte telemetry stream resumed for that leg.
3. **Throughout a BUILDING session** — during `s2p1 = 11` (manual map-learn / "Expand Lawn") the mower does **not** emit the 33-byte telemetry frame at all; every s1p4 push is an 8-byte frame carrying live position as the mower traces the new boundary. Confirmed 2026-04-20 17:00:09–17:04:00: 47 consecutive 8-byte frames at ~5 s cadence (no 33-byte frame in between), plus one 10-byte frame at 17:03:41 marking the save moment.

Layout (X/Y at the same offsets as the 33-byte frame, no phase/session/area fields):

```
[0]     0xCE
[1-2]   int16_le   x_cm               (small positive during preamble)
[3-4]   int16_le   y_mm               (near-zero / negative sentinel -64..-96)
[5]     0x00
[6]     uint8      123..125           TBD — monotonic across legs (see open item)
[7]     0xCE
```

Raw samples from 2026-04-20 run (leg-start preamble shape — Y=0xFFFF sentinel):
- `07:58:40  [0xCE, 19, 0, 192, 0xFF, 0xFF, 125, 0xCE]`
- `10:03:55  [0xCE, 20, 0, 160, 0xFF, 0xFF, 125, 0xCE]`
- `12:07:50  [0xCE, 30, 0, 192, 0xFF, 0xFF, 123, 0xCE]`

BUILDING-mode samples (same 8-byte shape, real Y values, byte[6] varies widely):
- `17:01:01  [0xCE, 6, 0, 192, 0xFF, 0xFF, 250, 0xCE]`  (at dock, sentinel Y)
- `17:01:11  [0xCE, 235, 255, 47, 3, 0, 69, 0xCE]`      (X=-21 cm, Y=815 mm)
- `17:02:16  [0xCE, 72, 1, 144, 73, 0, 4, 0xCE]`        (X=328 cm, Y=18.83 m)
- `17:03:11  [0xCE, 9, 2, 80, 110, 0, 126, 0xCE]`       (X=521 cm, Y=28.24 m)

byte[6] plays at least two roles depending on context: `123..125` during the
leg-start preamble (monotonic across legs), and highly variable during BUILDING
(values 0..252 span observed, no obvious pattern). Could be a heading angle,
course-correction code, or per-packet checksum; more captures needed.

The integration decodes the position correctly via `decode_s1p4_position`. As of
v2.0.0-alpha.7 each novel short-frame length also logs the raw bytes once at
WARNING (`[PROTOCOL_NOVEL] s1p4 short frame len=…`) so contributors capturing
future variants can see the undecoded bytes without running a separate probe
script.

### 3.3 `s1p4` — 10-byte BUILDING variant

Emitted **exactly once per BUILDING session**, at the moment the new zone is
saved — i.e. as the mower finishes the perimeter trace and the firmware
commits the map delta. Confirmed 2026-04-20 17:03:41 at the same second
`s1p50 = {}` fired (first of three in that second). The other 47 frames of
the BUILDING session were all the 8-byte variant (§3.2).

```
[0]     0xCE
[1-2]   int16_le   x_cm
[3-4]   int16_le   y_mm
[5]     0x00
[6-7]   uint16_le  ??  (observed 0x15C2 = 5570 on 2026-04-20; probably a
                       sequence counter, zone-id, or point count for the
                       new polygon — needs more captures to disambiguate)
[8]     0x00
[9]     0xCE
```

Sample: `[0xCE, 139, 0, 240, 77, 0, 194, 21, 0, 0xCE]` → X=139 cm, Y=19952 mm,
bytes[6-7] uint16_le = 5570.

### 3.4 `s1p1` — HEARTBEAT (20-byte blob)

Sent every ~45 seconds regardless of state. `0xCE` delimiters at the ends.

| bytes | meaning |
|---|---|
| [4] | pulse `0x00 → 0x08 → 0x00` lasting ~0.8 s during a **human-presence-detection event**. Evidence: session 2 (2026-04-18) showed byte[4]=0x08 exactly twice at 21:04:39.580 and 21:04:40.210; the user confirmed the Dreame app raised a human-in-mapped-area alert at that same moment. Byte is `0x00` at all other times across the whole session. Single-event datapoint — reproduce before relying on it. |
| [6] `& 0x08` | **Charging paused — battery temperature too low.** Asserted while the mower is docked but refusing to charge because the battery is below its safe-charge threshold; clears when the cell warms up (or momentarily, while the charger retries). Evidence: 2026-04-20 the Dreame app raised *"Battery temperature is low. Charging stopped."* at 06:25 and 07:54; at 06:25:42 byte[6] went `0x00 → 0x08` coincident with `s2p2` dropping from 48 (MOWING_COMPLETE) to 43, at 07:54:39 byte[6] flipped `0x08 → 0x00 → 0x08 → 0x00` while the mower bounced `STATION_RESET ↔ CHARGING_COMPLETED` and re-emitted `s2p2 = 43`. Cleared to 0 once charging resumed around 07:58 and stayed 0 through the following mowing session. |
| [7] | 0=idle, 1 or 4 = state transitions |
| [9] | 0/64 pulse at mow start |
| [10] `& 0x80` | **Latched** after the first low-temp charging-pause event of the day — observed to set at 06:25:42 together with byte[6]`=0x08` and remain `0x80` through the 07:54 re-trigger, the 07:58 mowing start, and every subsequent heartbeat in the session. Normal value at a cold-boot/idle charge is `0x00` (confirmed: 2026-04-19 13:04–14:29 all show byte[10]=0). Best guess: "battery-temp-low event has occurred since last power-cycle" maintenance flag. Cleared state unconfirmed (reproduce with a fresh boot after a warm day). |
| [11-12] | monotonic counter |
| [14] | state machine during startup: 0 → 64 → 68 → 4 → 5 → 7 → 135 |

See §4.4 for the companion `s2p2 = 43` signal and the app-notification semantics.

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
| 43 | **Battery temperature is low; charging stopped.** Drives the Dreame app notification of the same name. Observed to be republished on every (re-)entry into the condition — i.e. each re-emission causes a fresh app notification, not just the first one. See §4.4. |
| 48 | mowing complete |
| 50 | session started (manual start from the app) |
| 53 | **Scheduled-session start** — confirmed by two identical captures on 2026-04-20: morning run at 07:58:02 and afternoon run at 17:30:02. Both fired the exact same second-level sequence: `s2p56 → {'status':[]}` and `s2p2 → 53` in the same second, then `s3p2 → 0` + `s2p1 → 1 (MOWING)` one second later, then `s1p50/s1p51 → {}` and `s2p56 → [[1,0]]` ~40 s later when the mower starts emitting 33-byte telemetry. Distinct from manual starts which emit `s2p2 = 50` instead. Enum: `SESSION_STARTING_SCHEDULED`. |
| 54 | returning |
| 56 | **Rain protection activated** — water detected on the LiDAR. See §4.3 rain-pause. |
| 70 | mowing (edge / standard) |

Anything **outside** this set arriving on `s2p2` will log exactly one WARNING
(`[PROTOCOL_NOVEL] s2p2 carried unknown value=…`) so new firmware codes surface
without flooding the log.

### 4.2 `s2p1` mode enum (separate from state)

| Value | Meaning |
|---|---|
| 1 | MOWING |
| 2 | IDLE |
| 5 | RETURNING |
| 6 | CHARGING |
| 11 | **BUILDING** — manual map-learn / zone-expand. Confirmed 2026-04-20 17:00:09 when user triggered "Expand Lawn" from the Dreame app. Mower left the dock, drove the new perimeter for ~4 min, then returned. See §4.3 "Manual lawn expansion". |
| 13 | CHARGING_COMPLETED |
| 16 | STATION_RESET (battery-temp-low pause, see §4.4) |

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

**Manual session start** (user-initiated from the app):
```
s2p56: [[1,4]] → []
s2p2:   → 50                  ← manual-start code
CHARGING → MOWING
s2p50 gains {area_id, exe, o:100, region_id:[1], time:10510, t:'TASK'}
s5p107 changes dynamically: 176 → 250 → 133 → 158 (driver unknown)
```

**Scheduled session start** (cloud fires schedule at configured time — confirmed
2026-04-20 across two independent captures, 07:58:02 and 17:30:02):
```
HH:MM:02  s2p56 = {'status': []}   (task-list cleared ready for new task)
HH:MM:02  s2p2  = 53                ← scheduled-start code (distinct from 50)
HH:MM:03  s3p2  = 0                 (stops charging)
HH:MM:03  s2p1  = 1                 (MOWING)
HH:MM:46  s1p4 (33-byte) frames begin arriving
          (one observation had an 8-byte preamble at +37 s before the 33-byte
          stream resumed; the other went straight to 33-byte at +43 s)
HH:MM:44  s1p50 = {} + s1p51 = {}   (session-boundary markers)
HH:MM:45  s2p56 = {'status': [[1,0]]} (task now running)
```
**No `s2p50` fires on scheduled starts** — the task metadata block is only
emitted on manual starts. Scheduled runs rely on the cloud to know the plan.
**No `s6p1 = 300` either** — the map-ready signal is recharge-leg-only.

**Manual lawn expansion / zone edit** (observed 2026-04-20 17:00:09–17:06:06, user tapped *"Expand Lawn"* in the Dreame app):
```
CHARGING(6) → BUILDING(11) → IDLE(2) → RETURNING(5) → CHARGING(6)
              ↑ s2p1=11 (previously unlabelled, now confirmed)

s3p2: 1 → 0 (charging stops as mower prepares to leave dock)
s1p50 = {} + s1p51 = {}  (session-boundary markers, same as mowing)
s1p4  = 8-byte frames with real X/Y telemetry during the drive
        (not the 0xFFFF sentinel — active position tracking)
s1p4  = one 10-byte frame fires at the exact moment the expand
        completes (17:03:41 — same second s1p50 fires again).
        Likely the "zone saved" marker.
s6p2  = [60, 0, True, 2] at 17:03:42 (see §2.1). Previously [35,0,T,2]
s2p66 = [384, 1386] at 17:04:02 — mowable-area snapshot after save
        (first int matches event_occured piid=14 from morning run).
s1p53 = True  (obstacle flag — mower nosing around the boundary)
```
**No `event_occured` siid=4 eiid=1**, no `s2p2` code change, no `s2p50`.
These are mowing-session artefacts; BUILDING is a distinct session class.

Under-counting of newly-added area is likely if the new zone overlaps
an existing **exclusion zone** — the exclusion polygon filters BEFORE
the mowable-area sum, so any overlap subtracts from the reported
area. If `s2p66[0]` or event_occured piid=14 doesn't budge after an
expand, check for overlapping exclusions first.

**User-cancel abort** (observed 2026-04-20 18:06:18 — user hit *Cancel* from the Dreame app mid-session):
```
s2p1 = 2   (IDLE)             — task cancelled
s2p2 = 48  (MOWING_COMPLETE)  — reused for abort (same code as natural end)
s1p52 = {}                    — session-boundary marker
s2p50 = {'d':{'exe':True, 'o':3, 'status':True}, 't':'TASK'}
                              — NEW operation code o=3 for "cancelled"
event_occured siid=4 eiid=1   — session-summary JSON uploaded (!)
```

**The mower does NOT auto-return to dock after a cancel.** `s2p1` stops at
`2 (IDLE)` with no `→ 5 (RETURNING)` transition. The robot stays where
it last was on the lawn. To bring it home, the user must explicitly hit
*Recharge* in the app (which issues a separate `s2p1 → 5` RPC). This is
firmware behaviour, not an integration choice.

**Earlier "aborted sessions skip the summary" memory note was wrong** —
the abort DID emit `event_occured` with a fresh JSON OSS key. Distinguishing
fields from natural completion:
- `piid 7` = 3 (previously only 1 observed; 3 = user-cancel)
- `piid 2` = 36 (new end-code; naturals give 31/69/128/170/195)
- `piid 60` = 101 (first non-`-1` observation; maybe "abort reason")
- `piid 3` = centiares-mowed at abort time (here 6647 → 66.47 m²)

So the session-summary-JSON pipeline covers aborts too. Integration
behaviour is correct: `_fetch_session_summary` archives it and the
session-picker select shows "66.47 m² (N min)" for the cancelled run
alongside completed runs.

**Mid-task recharge** (observed 2026-04-18): the mower can pause for a mid-task
recharge and resume mowing once topped off. The task is not considered complete
during this pause; `s1p4` telemetry continues throughout the return leg. No map
push observed at the pause itself — only at true session completion.

### 4.4 Low-temp charging-pause event

Confirmed 2026-04-20 from two live notifications ("Battery temperature is low.
Charging stopped.") at 06:25 and 07:54. All three signals below fire as one
atomic MQTT burst at the moment the Dreame app issues the notification:

```
s2p1 (STATE)            → 16  (STATION_RESET)       -- was 13 (CHARGING_COMPLETED)
s2p2                    → 43  (low-temp signal)     -- was 48 (MOWING_COMPLETE)
s1p1 HEARTBEAT byte[6]  |= 0x08                     -- was 0x00
s1p1 HEARTBEAT byte[10] |= 0x80  (latches for the session, see §3.4)
```

A **re-entry** (07:54 in our capture) republishes `s2p2 = 43` and re-pulses
byte[6] — so one Dreame app notification arrives per republish, not just on
rising edge. The HA integration piggybacks on the byte[6]`&0x08` bit
(`Heartbeat.battery_temp_low_flag` from the s1p1 decoder) and raises a
persistent-notification + `dreame_a2_mower_warning` event on the rising edge;
see `coordinator._heartbeat_changed`. We don't currently attach to `s2p2 = 43`
directly because the upstream property overlay keeps ERROR (`s2p2`) disabled
on g2408 to avoid upstream's vacuum-era misinterpretation of the same slot
(§2.2).

### 4.5 `s1p4` telemetry lifecycle

Position telemetry fires throughout an active TASK, including the return-to-dock
leg of a low-battery auto-recharge. It stops only when the task itself ends
(`s2p1` transitions to `2` = complete / cancelled).

### 4.6 Map-edit transport via `s2p50`

Zone / exclusion-zone / no-go-zone adds / edits / deletes travel over MQTT as
two `s2p50` pushes, both with the shape `{d: {...}, t: 'TASK'}`:

```json
{"d": {"exe": true, "o": 204, "status": true}, "t": "TASK"}
        ^^^ request — map edit starting
{"d": {"error": 0, "exe": true, "id": 101, "ids": [1], "o": 215, "status": true}, "t": "TASK"}
        ^^^ confirm — edit applied; `ids` = affected zone id(s), `id` = tx counter
```

Captured 2026-04-20 17:15:41 → 17:17:16 when the user resized the single
exclusion zone from the Dreame app. Neither push triggers `s2p1 = 11` (BUILDING
is reserved for drive-the-boundary operations), `s6p1 = 300` (no map-ready
signal), `s2p66` (area snapshot — stale until the next BUILDING or session
start), or `event_occured`.

**Integration behaviour** (2.0.0-alpha.17): the `o=215` confirm push triggers an
immediate `_build_map_from_cloud_data()` rebuild + camera-state nudge so the
Mower dashboard's base-map image reflects the new exclusion polygon within a
few seconds of the edit. Prior to this version the camera kept drawing the
stale polygon until HA was restarted.

**Scheduled-mow add / edit / delete: no MQTT signal at all.** The Dreame cloud
stores schedules app-side; nothing appears on the mower's `/status/` topic when
the user adds or edits a schedule. The mower only learns about the schedule
when the cloud wakes it for the configured time. So there's nothing for the
integration to observe at edit time — the schedule list itself has to be pulled
from the cloud API separately (not yet wired).

**Other `s2p50` operation codes** (catalog, extend as new ones appear):

| `d.o` | Meaning | Occurs when |
|---|---|---|
| 3   | task cancelled | user hits *Cancel* / *Stop* during an active mowing session. Fires 1 s after `s2p2 = 48`. Does **not** carry `id`/`ids`. See "User-cancel abort" in §4.3. |
| 204 | map-edit request | zone / exclusion add / edit / delete: first of the pair |
| 215 | map-edit confirm | same edit: second of the pair, carries `id` and `ids` |

Flat-fields variants without the `d` wrapper are the session-task metadata
described under §4.3 "Session start" (`o: 100`).

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

> **See also:** [`cloud-map-geometry.md`](./cloud-map-geometry.md) for the
> coordinate-frame / rotation / reflection math every overlay writer needs
> after the map data is in memory.


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

Fully re-measured during the 2026-04-20 full-run (07:58 → 12:33, two auto-recharge interrupts, one clean session end). The mechanism is clearer now than it appeared from earlier partial captures:

| Event | MQTT artefact | Notes |
|---|---|---|
| **Auto-recharge begins** (MOWING → RETURNING for top-off) | `s6p1 = 300` | Fires at the exact ms `s2p2 → 54`, `s2p1 → 2 → 5`. Confirmed twice in the 2026-04-20 run at 09:14:09 and 11:13:04. This is the primary mid-session "map may have been refreshed" signal. |
| **True session completion** (task done, not recharge) | `event_occured siid=4 eiid=1`, `piid 9 = ali_dreame/…/*.json` | Fires once at session end (12:33:12 — 3 s after `s2p2 = 48`). Carries the *session-summary* OSS key. See §7.4. |
| **LiDAR point-cloud upload** | `s2p54` 0..100 progress counter + `s99p20 = ali_dreame/…/*.bin` | Only when the user opens "Download LiDAR map" in the Dreame app, and only if the scan has changed since last upload. Not pushed passively. See §7.4.1 for full sequence. |
| User taps "End" while docked (no actual mowing) | (none) | No map push, no summary event. |
| Manual pause mid-mow | (none) | No map push. |
| Session start from dock | `s2p56: [[1,4]] → []`, `s2p1 → 1`, `s2p2 → 50` or `53` | No map push — the mower is just starting to generate new data. |

Key corrections vs. earlier notes:
- `s6p1 = 300` is **not** a session-completion signal. It's a recharge-leg-start signal. The session-completion trigger is the `event_occured` on its own dedicated method — which the integration now handles (§7.4).
- The 2026-04-20 run produced **two** `s6p1 = 300` pushes (once per recharge interrupt) plus **one** `event_occured`. Three distinct "map-ish" artefacts per session, each with its own meaning.

**Silent inflection points** (mower's internal map changes, no MQTT signal):

The mower does NOT broadcast a map-ready signal for:
- Scheduled session starts (`s2p2 = 53`, `s2p1 → 1`).
- Manual session starts (`s2p2 = 50`, `s2p1 → 1`).
- BUILDING-end (user tapped *Expand Lawn* or *Add Zone*; `s2p1: 11 → 2`).
- App-driven zone / exclusion edits (`s2p50` `o=215`, see §4.6) — this one
  is discoverable from MQTT, just not as `s6p1 = 300`.

For the first three, the MAP.* cloud dataset may have changed server-side
during the previous session boundary but the integration would never know.
**As of v2.0.0-alpha.19** the integration proactively re-pulls the cloud map at
each of these inflection points (see `_schedule_cloud_map_poll`) — cheap
because `_build_map_from_cloud_data` md5-dedupes a no-change result into a
no-op. Triggers are:

| Trigger | Condition | Handler |
|---|---|---|
| Integration setup / HA startup | one-shot | `_build_map_from_cloud_data` |
| Periodic freshness check | every 6h | coordinator `async_track_time_interval` → `_schedule_cloud_map_poll` |
| s2p2 session-start code | `value ∈ {50, 53}` | `_message_callback` → poll |
| BUILDING complete | `s2p1: 11 → *` transition | `_state_transition_map_poll` → poll |
| Dock departure | `s2p1: 6 → *` transition | `_state_transition_map_poll` → poll |
| Map-edit confirm | `s2p50 d.o == 215` | `_message_callback` → poll (§4.6) |
| Auto-recharge leg start | `s6p1 = 300` | upstream map pipeline |

All five poll paths funnel into the same `_build_map_from_cloud_data`,
which fetches 28 MAP.* cloud keys (one HTTP round-trip, ~100–200 KB)
and compares the top-level `md5sum` against the previously-seen value.
**No lightweight probe exists** — the Dreame cloud stores the md5 inside
the compressed payload, so a full fetch IS the cheapest freshness
check. Unchanged md5 → no camera state change, no Lovelace reload.

**LiDAR archive cannot be proactively polled.** The mower only emits
`s99p20` when the user taps *Download LiDAR map* in the Dreame app and
the scan has actually changed. No passive endpoint exposes the current
scan's md5 or timestamp — the archive is as fresh as the last app view.

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
  map successfully (file `map_live.png`), so the OSS side of the flow works.
- **2026-04-19 discovery**: the session-summary OSS object key arrives not as
  an `s6p3` property-change but inside an `event_occured` MQTT message that the
  integration was never listening for. See §7.5.

### 7.3b LiDAR point-cloud upload sequence

Triggered by the user tapping *"View LiDAR Map"* in the Dreame app, provided
the current scan differs from the last-uploaded one (reopening the screen with
no scan change is a no-op). Confirmed 2026-04-20 17:41:58–17:42:28 with a
full progress sample at 1 Hz:

```
17:41:58  s2p54 = 0         ← upload requested, mower prepping
…six 0-s pushes…
17:42:04  s2p54 = 10        ← firmware started staging the PCD
17:42:08  s2p54 = 16
17:42:11  s2p54 = 21, 26, 26, 26, 26, 26, 32, 32, 37, 40, 45
17:42:22  s2p54 = 61        ← partway through OSS upload
17:42:28  s99p20 = "ali_dreame/2026/04/20/BM169439/-112293549_154157120.0550.bin"
17:42:28  s2p54 = 100       ← done
```

`s2p54` is a 0..100 progress percent, published roughly once per second while
the upload runs. `s99p20` arrives **before** the `s2p54 = 100` marker (today at
61 %) — the integration should therefore key off `s99p20` (which always lands
before the final tick) rather than waiting for `s2p54 = 100`.

Total wire time today: 30 seconds, 2.45 MB PCD (153 261 points). The HA
integration's `_handle_lidar_object_name` → `get_interim_file_url` → OSS
fetch → archive path completes within a few seconds of the `s99p20` arrival;
the new file lands under `<config>/dreame_a2_mower/lidar/YYYY-MM-DD_<ts>_<md5>.pcd`
and is content-addressed by md5 (re-tapping the same scan is a no-op).

### 7.4 `event_occured` at session completion — the missing trigger

Exactly once per completed mowing session, the mower posts a second MQTT method
(`event_occured`, vs. the usual `properties_changed`) with service-id 4,
event-id 1. Four of these have been captured across 2026-04-17 / 2026-04-18:

```json
{
  "id": 2376, "method": "event_occured",
  "params": {
    "did": "-112293549", "siid": 4, "eiid": 1,
    "arguments": [
      {"piid": 1,  "value": 100},
      {"piid": 2,  "value": 195},
      {"piid": 3,  "value": 31133},            ← area mowed in centiares (311.33 m²)
      {"piid": 7,  "value": 1},
      {"piid": 8,  "value": 1776522523},       ← unix timestamp
      {"piid": 9,  "value": "ali_dreame/2026/04/18/BM169439/-112293549_193738455.0550.json"},
      {"piid": 11, "value": 0}, {"piid": 60, "value": -1},
      {"piid": 13, "value": []}, {"piid": 14, "value": 384}, {"piid": 15, "value": 0}
    ]
  }
}
```

The `piid=9` value is the OSS object key for the session-summary JSON.

Decoded fields across six captures (2026-04-17..2026-04-20, incl. one user-cancel):

| piid | guess | observed values |
|---|---|---|
| 1 | constant / flag | always 100 |
| 2 | end-code | 31, 36, 69, 128, 170, 195 — the 36 comes from the 2026-04-20 18:06 user-cancel; the 31–195 band is from natural completions. So **36 appears to be the "user cancelled" marker**; further cancels will confirm. |
| 3 | area mowed × 100 (m² × 100) | 5232, 6647 (cancel, 66.47 m²), 10759, 19613, 28744, 31133 — matches the final `s1p4` `area_mowed_m2` reading at session end to within recharge-leg-transit overhead. |
| 7 | stop-reason-ish | 1 = natural completion; 3 = user-cancel (confirmed by the 2026-04-20 abort). |
| 8 | unix timestamp of session **start** | 2026-04-20 morning run: 1776664681 → 05:58:01 UTC = 07:58:01 local, exact match to `s2p1 → 1` at 07:58:03. The 18:06 user-cancel emitted 1776699000 = 15:30:00 UTC = 17:30:00 local — again session-start, not cancel-time. Confirms piid 8 is session-start, independent of end reason. |
| 9 | **OSS object key (`.json`)** | `ali_dreame/YYYY/MM/DD/<master-uid>/<did>_HHMMSSmmm.MMMM.json` — fires for both natural completion AND user-cancel. |
| 11 | ? | 0 or 1 |
| 60 | ? | -1 (normal) or 101 (user-cancel, first non-`-1` observation 2026-04-20 18:06). May be an abort-specific reason code. |
| 13 | empty list | `[]` |
| 14 | **total mowable lawn area (m², rounded int)** | 379 pre-2026-04-18, 384 after user added a zone in-app. Matches `map_area` and rounded `map[0].area` in the session-summary JSON — user-confirmed that the lawn grew by ~5 m² when the new zone was added. |
| 15 | ? | 0 |

A one-shot WARNING fires (`[PROTOCOL_NOVEL] event_occured …`) the first time a
given (siid, eiid) combo is seen, or when a known combo carries a new piid.
That makes silent firmware additions impossible to miss.

### 7.5 Fetching the session-summary JSON

Two distinct signed-URL endpoints on the Dreame cloud; the one that works for
this object key is the **interim** endpoint:

```
POST https://eu.iot.dreame.tech:13267/dreame-user-iot/iotfile/getDownloadUrl
body: {"did":"<did>","model":"dreame.mower.g2408","filename":"<obj-key>","region":"eu"}
→ {"code":0, "data":"https://dreame-eu.oss-eu-central-1.aliyuncs.com/iot/tmp/…?Expires=…&Signature=…", "expires_time":"…"}
```

The signed URL is valid for ~1 hour (no auth on the URL itself). `GET` it to
retrieve the full summary JSON (~56 KB for a 3-hour session).

The alternative endpoint `getOss1dDownloadUrl` (also signed) returned 404 —
that bucket is empty; it's for a different object class.

### 7.6 Session-summary JSON schema (as observed 2026-04-18)

```
{
  "start":        <unix>,                 mowing started
  "end":          <unix>,                 mowing ended
  "time":         <int>,                  duration in minutes
  "mode":         <int>,                  mode code (100 seen)
  "areas":        <float>,                m² mowed this session
  "map_area":     <int>,                  m² total mowable (383 on user's lawn)
  "result":       <int>,                  1 = success-ish
  "stop_reason":  <int>,                  -1 = normal end
  "start_mode":   <int>,
  "pre_type":     <int>,
  "md5":          <hex>,                  content hash
  "region_status": [[zone_id, status]...]
  "dock":         [<x>, <y>, <heading>],  dock coords in mower frame (cm)
  "pref":         [<int>...],
  "faults":       [],                     empty on normal completion
  "spot":         [],
  "ai_obstacle":  [],
  "obstacle":     [                        physical obstacles encountered
    {"id": <int>, "type": <int>,
     "data": [[x_cm, y_mm]...]}           polygon vertices
  ],
  "map":          [
    {  id: 1, type: 0, name: "",
       area: <float>, etime: <int>, time: <int>,
       data: [[x, y]...],                  lawn boundary polygon
       track: [[x, y] | [2147483647, 2147483647]...]   mow path; max-int = segment break
    },
    {  id: 101, type: 2,
       description: { type: 2, points: [[x,y]...] }   exclusion zone (4-point polygon)
    }
  ],
  "trajectory":   [
    {  id: [<int>, <int>],
       data: [[x, y]...]                   high-level planning path
    }
  ]
}
```

Coordinates are in the same mower frame as `s1p4` (x in cm, y in mm × some
scale — TBD whether it matches the 0.625 Y-calibration or needs a different
constant here).

### 7.7 Wiring state

| Piece | Status |
|---|---|
| Subscribe to `event_occured` | ✅ `device.py::_handle_event_occured` |
| Log object key at INFO | ✅ `[EVENT] event_occured siid=4 eiid=1 object_name=… area_mowed_m2=… total_lawn_m2=…` |
| Fetch + download the JSON | ✅ `device.py::_fetch_session_summary` — uses `cloud.get_interim_file_url` (the `getDownloadUrl` variant; the persistent `getOss1dDownloadUrl` 404s) |
| Decode JSON → typed dataclasses | ✅ `protocol/session_summary.py::parse_session_summary`, 18 unit tests |
| Expose overlay to camera/live-map | ✅ `live_map.LiveMapState.load_from_session_summary` — lawn polygon, exclusion zones, completed track segments, obstacle polygons, dock position all flow into `extra_state_attributes` automatically |
| Persist to disk | ✅ `session_archive.SessionArchive` — one JSON per session under `<ha_config>/dreame_a2_mower/sessions/`, content-addressed by `summary.md5`, idempotent re-archival |
| Expose archive as HA entity | ✅ `Archived Mowing Sessions` diagnostic sensor (state=count, attrs list recent 20 sessions) |
| Binary-blob map decoder (upstream-style encrypted) | ❌ not applicable to g2408 — superseded by the JSON path |

**Implementation is complete end-to-end.** Every time the mower finishes a session:

1. `event_occured` arrives on MQTT → `_handle_event_occured` parses the event
2. Inline fetch pulls the JSON from the Dreame cloud (signed OSS URL, ~1s)
3. `parse_session_summary` converts it to a `SessionSummary` dataclass
4. `device.latest_session_summary` / `.latest_session_raw` populated
5. `DreameA2LiveMap` picks it up on the next update tick and loads the overlay
6. Camera's `extra_state_attributes` gains `lawn_polygon`, `exclusion_zones`,
   `completed_track`, `obstacle_polygons`, `dock_position`
7. `SessionArchive` writes the raw JSON to disk and updates the index
8. `Archived Mowing Sessions` diagnostic sensor state increments

Off-repo helper `/data/claude/homeassistant/fetch_oss.py` can retrieve any
object key on demand for ad-hoc inspection.

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

### 7.5 `[PROTOCOL_NOVEL]` WARNING catalog (for issue reporters)

Everything below logs at WARNING level, exactly **once per process lifetime per
distinct shape**, at HA's default `logger.default: warning` — so they're safe
against log flooding and visible without any extra logger tuning.

| Message prefix | Trigger | What it tells us |
|---|---|---|
| `[PROTOCOL_NOVEL] MQTT message with unfamiliar method=…` | MQTT message arrives with a method other than `properties_changed` or `event_occured` (e.g. `props`, `request`). | Firmware has a verb we don't decode yet. |
| `[PROTOCOL_NOVEL] properties_changed carried an unmapped siid=… piid=…` | Push arrived on an (siid, piid) not in the property mapping and not intercepted by a specific handler. | New field on an existing service — either a new feature or a firmware revision. |
| `[PROTOCOL_NOVEL] event_occured siid=… eiid=… with piids=…` | First occurrence of an (siid, eiid) combo OR known combo with a new piid in the argument list. | New event class, or existing event gained a field (e.g. a new reason code). |
| `[PROTOCOL_NOVEL] s2p2 carried unknown value=…` | `s2p2` push outside the known set `{27, 43, 48, 50, 53, 54, 56, 70}`. | Firmware emitted a state code we don't recognise. See §4.1. |
| `[PROTOCOL_NOVEL] s1p4 short frame len=…` | `s1p4` push with a length other than 8 / 10 / 33. Raw bytes included in the log line. | Firmware emitted a telemetry frame variant we haven't reverse-engineered. The position is still decoded correctly; only the trailing bytes are un-decoded. |

When a user sees any of these, the right action is to open an issue with the
log line quoted verbatim — the raw values in the message are exactly what we
need to extend decoders.

**Not a `[PROTOCOL_NOVEL]` — don't report** (see §1.2 for the full story):

- `Cloud send error 80001 for get_properties/action (attempt X/Y)`
- `Cloud request returned None for get_properties/action (device may be in deep sleep)`

These are the g2408's expected response to cloud-RPC writes. They will repeat
every time the integration tries a write (buttons, services, config changes).
They do not indicate a new firmware issue.

**Observed but not yet mapped** (2026-04-20):

- `s2p66`, `s5p105`, `s5p106`, `s5p107` — already characterised in §2.1.
  These slots log at **DEBUG** with the prefix `[PROTOCOL_OBSERVED]`
  rather than `[PROTOCOL_NOVEL]` so they don't spam WARNING on every
  HA reload (the watchdog's in-memory dedup resets each time the device
  object is reconstructed). Anything outside this allowlist — a
  genuinely unmapped (siid, piid) — still produces the one-shot WARNING.
  If the user wants to confirm cadence or value range for these known-
  quiet slots, raise the integration's log level to DEBUG for
  `custom_components.dreame_a2_mower.dreame.device`.

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
