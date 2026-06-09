# g2408 Knowledge Gaps — MQTT push & cloud-API retvals

A **blank-spots companion** to `inventory.yaml`. The inventory records what is
*known* (and how confident we are); this file is the inverse view — the *missing*
and *uncertain* understanding, gathered in one place because gaps are hard to
find by reading the known-facts docs slot-by-slot.

Covers **both** wire surfaces, because going slot-by-slot in the integration
turns up unknowns in each:
- **MQTT `/status/` push** — `properties_changed` (siid/piid): s1p*, s2p*, s5p*, s6p*.
- **Cloud-API retvals** — CFG keys, routed-action opcodes, batch device-data
  (MAP*/MISTA/MITRC/OBS), OSS session-summary JSON, device events.

## How to keep this in sync (don't hand-maintain in parallel)

`inventory.yaml` stays the **single source of truth**. This file is a curated
cross-cut that can be **regenerated**: an entry belongs here iff its
`status.decoded != confirmed` **or** it has `open_questions`. Skeleton refresh:

```python
import yaml
d = yaml.safe_load(open('custom_components/dreame_a2_mower/inventory.yaml'))
def walk(n):
    if isinstance(n, dict):
        if 'id' in n and ('status' in n or 'semantic' in n):
            st = n.get('status', {}) or {}
            yield n['id'], n.get('name'), st.get('decoded'), len(n.get('open_questions') or [])
        for v in n.values(): yield from walk(v)
    elif isinstance(n, list):
        for it in n: yield from walk(it)
for id_, name, dec, oq in walk(d):
    if dec != 'confirmed' or oq: print(id_, name, dec, oq)
```

Corpus numbers below are from `probe_log_*.jsonl` (9 logs, 2026-04-17…05-30;
66,149 s1p1 + 69,254 s1p4 frames) via the census snippet at the end. Baseline
inventory tally at time of writing (2026-05-30, post fault-code + s4-eiid1 decode):
**195 confirmed / 116 hypothesized / 10 unknown / 6 partial / 4 verified**
across 331 entries. Last updated 2026-06-09 (app-MITM sweep: resolved
SCHDTV3/GPS/PATH/PIN/REMOTE/photo-metadata/map-edit/message-record gaps;
added SCHDSV3 v-layout, BAT[2], LIT.fill, draw-by-driving, OTA flow,
XP2P stream, per-pathway, shape ids 12/14/15/16, MAP.* freshness, Tencent
getIdentity).

Validation-process shorthands are defined in [§Validation playbook](#validation-playbook).

---

## 1. s1p1 heartbeat — byte/bit gaps (20-byte push, 66,149 frames)

| Byte/bit | Status | Corpus | Gap | Validate |
|---|---|---|---|---|
| `[5]` | unknown | 99% `0x00`, rare {2,16,18} | purpose of the rare non-zero flags | LABEL: timestamp the rare frames vs device events |
| `[8]` | unknown | 97% `0x00`, rare {1,16,128,129} | rare flag; distinct from `[9]` mow_start_pulse | LABEL |
| `[13]` | **partial** | 19 vals; 255 docked, 35 mowing, 40 returning, 17-27 building | not pinned to an enum; companion to `[14]`? | XTAB by mode + LABEL transitions; test `[13][14][15]` as one block |
| `[14]` | **partial** | 28 vals; 0 docked, 135 mowing, 0x80-range returning/idle, 164 tilt-lockout | enumerate the 0x80-range sub-states | LABEL: a clean return-to-dock; tilt/fault captures extend it |
| `[15]` | **partial** | 11 vals {0,1,2,3,4,5,6,17,18,20,54}; 54 at undock-onset, 18 in reorient | likely a **bitfield**, not enum | LABEL: separate the bits across idle/returning/reorient |
| `[18]` | unknown | 90% `186`, rare {126,127,180,196,203} | rare status/flag | LABEL |
| `[4]` sub-bits | confirmed (name) | multi-bit: 0(68%),0x10(16%),0x08(8%),0x40(6%) | only "human_presence" named; the other bits uncharacterized | XTAB each bit vs state |
| `[1][2][3][6][10]` other bits | confirmed (some bits) | flags 99% clear | only specific bits decoded (tilt/bumper/lift/PIN/temp/safety/latch); **remaining bits never examined** | LABEL safety/fault events |
| `[10]&0x80` | confirmed | 93% set (docked+warm too) | labelled "low-temp latch" but trigger not cleanly pinned (see 2026-05-30 note — it is NOT off-dock) | capture a cold-night→warm power-cycle to see if it ever clears |

Solidly known: `[0]`/`[19]`=0xCE delims, `[16]`=128 const, `[7]` state marker,
`[9]` mow_start_pulse, `[11-12]` counter, `[17]` RSSI.

---

## 2. s1p4 telemetry — byte gaps (33-byte push, 68,801 frames; +449 8-byte, +4 10-byte)

| Field | Status | Gap | Validate |
|---|---|---|---|
| `[10-21]` motion vectors / path history (`delta_2`,`delta_3`) | hypothesized | not decoded — likely per-axis velocity / recent-path deltas | XTAB deltas vs frame-to-frame (dx,dy); the heading validator at `heading_correlate.py` is the template |
| `[22]` region_id / `[23]` task_id (`flag_22`,`flag_23`) | hypothesized | values seen but mapping to map regions/tasks unconfirmed | LABEL: run zone/region-specific mows |
| `[28]`,`[31]` static bytes | hypothesized | assumed static; semantic unknown | scan corpus for any non-static occurrence |
| 10-byte BUILDING variant `[6-7]` | unknown | two extra bytes during map-learn not decoded | LABEL: capture an Expand-Lawn / map-build |
| overlapping reads `[24-25]` (percent vs distance), `[26-28]`/`[29-31]` (uint24 vs uint16 area) | confirmed-both | the "Task 4" field-validation never blessed ONE interpretation; both still computed | pick a known-area mow, compare both decodes vs app-reported area |

---

## 3. s2p* status / event slots

| Slot | Status | Corpus | Gap | Validate |
|---|---|---|---|---|
| s2p2 codes 20, 33 | hypothesized | fired only in the 2026-05-25 12:32 failure burst | text cloud-pruned; meaning unknown | repro within cloud retention, then device-messages/v2 fetch; or apk FaultIndex L94618-94697 |
| s2p2 conflicts 23/43/75 | mixed | seen | apk fault-label vs event-slug disagree | controlled trigger per code |
| s2p2 catalog 37-78 (RIGHT_MAGNET, FLOW_ERROR, …) | hypothesized | mostly **never observed** | vacuum/apk-derived; may not exist on g2408. EXCEPTIONS now observed+decoded (2026-05-30, real g2408 meanings, apk labels were wrong): 51=patrol-start, 71=standby-too-long-return, 74=patrol-ended, 76=cannot-reach-maint-point. Codes 2=robot-trapped, 4=left-drive-wheel-error also decoded (single obs, `partial`). The rest of 37-78 remains unobserved. | wait-for-event; treat unobserved as unconfirmed |
| s2p53 voice_download_progress | hypothesized | 5 occ {0,50,100} | shape presumed | LABEL: trigger a voice-pack download |
| s2p55 ai_obstacle_report | hypothesized | 23 dict | wire shape unknown (no AI-obstacle capture) | wait-for-event (AI obstacle w/ photo) |
| s2p57 / s2p58 / s2p61 / s2p62 | hypothesized | s2p62 always `0`; others sparse | shutdown/self-check/map-update/progress semantics presumed | LABEL respective triggers |
| s2p65 slam_relocate | (str) | 18 occ | only fires on relocate (mostly the FAILED one) | already partly mapped; capture a clean relocate |
| s2p66 lawn_area_snapshot | confirmed | 2 occ | very rare; trigger unclear | LABEL |
| **s2p56 3-element MIDDLE value** | partial | `[1,0,0]`/`[1,0,2]` | DECODED 2026-05-30: 3-element = `[task_id, X, stage]`, stage is the LAST element (0=start/2=done; `[1,0,2]`=segment-done, 10/10 at s2p56-empty). Remaining gap: the MIDDLE `X` is always 0 (likely segment/lap index — undecoded). Also: 3-element correlates with SCHEDULED (not edge/spot/zone — a morning all-area mode=100 mow was 3-element). | capture a multi-segment (rain-paused) run to see if X increments; correlate 3-element vs `summary.mode` |

Confirmed-with-followups: s2p1 (mode enum — value 3/14 + s2p56-umbrella open, see
TODO), s2p51 (multiplexed config — shapes catalogued, some sub-shapes presumed),
s2p56 (lifecycle + **multi-target list now decoded**; the 3rd-value axis above is the
remaining gap), s2p50 (TASK envelope opcodes — see §6).

---

## 4. s5p* / s6p* slots

| Slot | Status | Corpus | Gap | Validate |
|---|---|---|---|---|
| **s5p105** | hypothesized | 106 occ, vals {1,2,3,4} | small enum, meaning unknown; fires during reorient (~+13s) | LABEL: correlate value vs activity phase |
| **s5p106** | hypothesized | **1426 occ**, vals 1-20 | fires often, purpose unknown; reorient housekeeping candidate | XTAB vs mode/phase; high frequency = good signal to crack |
| s5p107 energy_index | confirmed | 279 occ, 1-250 | units/derivation (discharge index) not fully pinned | compare vs battery-drop rate |
| s5p108 | **unknown** | 3 occ, val {1} | almost never fires; semantic unknown | wait-for-more-data |
| s6p1 map_data_signal | confirmed | 68 occ {200,201,300} | the 200/201/300 transition semantics (which = "new map ready") | LABEL: map-edit / swap events |
| s6p2 frame_info | confirmed | 93 occ, list[4] | per-field meaning of the 4 ints | LABEL |
| s6p3 Link Module | (list[2]) | 124 occ | cellular daily ping; field meaning | n/a unless cracking cellular |
| s6p117 dock_nav_state | confirmed | 11 occ {1,3} | the value enum (only 1,3 seen) | LABEL dock approach |

---

## 5. Documented but NEVER seen on g2408 (vacuum-inherited)

Census over 66k+ frames shows **zero occurrences** — these are upstream/apk
catalog carried into the integration that the g2408 firmware does not emit on the
`/status/` topic. Since inventory.yaml now lists only g2408-relevant rows, these
belong OUT of the inventory (or carry `decoded: hypothesized` if kept for
reference) so they stop reading as live gaps:

- **s4p21, s4p22, s4p23, s4p26, s4p27, s4p44, s4p47, s4p49, s4p59, s4p68, s4p83**
  (obstacle_avoidance / ai_detection / cleaning_mode / child_lock / cruise_type /
  scheduled_clean / pet_detective / device_capability / device_snapshot_bundle…)
  — all vacuum-side MIoT properties; the g2408 surfaces these via CFG/SETTINGS instead.
- **s1p2 / s1p3** (OTA state/progress) — never captured (no firmware update during
  probe period). Genuinely g2408 but **wait-for-OTA**.
- Reset actions **s9a1/s10a1/s11a1/s16a1/s17a1/s19a1/s24a1/s1a3** and many opcodes
  are *action* surfaces (aiid), not push — they won't appear in this census; see §6.

**Validation:** the absence is itself corpus-confirmed (9 logs). Low-risk to
deprioritize; if any ever appears, it's a `[PROTOCOL_NOVEL]` and will be flagged.

---

## 6. Cloud-API retval gaps (not MQTT push)

These return from cloud calls (routed-action / getCFG / batch device-data / OSS),
so they need an integration-slot or a probe call to observe — not the status tail.

**CFG keys (getCFG / setX):**
| Key | Status | Gap | Validate |
|---|---|---|---|
| BP | hypothesized | `BP` semantics still unknown; companion `PATH` **confirmed** as Pathway Obstacle Avoidance master enable 2026-06-09 | CFG-DIFF: create a pathway in app, snapshot getCFG before/after |
| DLS | hypothesized | daylight-savings flag, stable 0 | CFG-DIFF across a DST boundary |
| PRE / PREI | hypothesized | g2408 PRE=[0,0]; not the vacuum 10-elt shape | confirmed-absent shape; encoder over-inflates (see TODO PRE bug) |
| AIOBS / OBS | hypothesized | AI-obstacle data blob shape | wait-for-event |
| CMS[3] | **partial** | unidentified (Link/Garage/MCA10/summary) — -1 always here | needs a unit WITH one of those accessories |
| IOT, ARM, WINFO, CHECK, RPET | hypothesized | connection-status / alarm / weather / self-check / rain-end-time (`REMOTE` **confirmed** 2026-06-09 as 4G SIM status {activeTime, cardId, expiredTime, leftDays}) | CFG-DIFF or LABEL per feature |
| SCHDSV3 `v` field | **partial** | `{i, v, s:[...]}` shape confirmed 2026-06-09; `v` is a packed int encoding day-of-week + time per seasonal slot — **bit layout unknown** `[UNKNOWN — to capture]` | edit individual days then times in isolation, diff `v` before/after |
| BAT `value[2]` / flag | **partial** | BAT typed-write shape confirmed; `value[2]` (third element) purpose unknown — NOT STUN `[UNKNOWN — to capture]` | CFG-DIFF: toggle auto-recharge-after-standby + diff BAT write |
| LIT `fill` field | **partial** | LIT write shape confirmed; `fill` present in payload (observed as 1) — purpose unknown `[UNKNOWN — to capture]` | CFG-DIFF: toggle LIT settings in app, diff fill field |

**Schedule write transport** — resolved 2026-06-09: SCHDTV3 is a read-side scalar
only; the write is a 3-key transaction (SCHDDV3 chunked protobuf + SCHDIV3 length
descriptor + SCHDSV3 enable/summary), all tied by a shared `v` ms-timestamp txn-id.
Open sub-gap: SCHDSV3 `v` packed-int bit layout (see CFG-keys table above).
`PIN` write shape — resolved 2026-06-09: `{type:'auth'|'update', value:<plaintext int>}`.
Photo metadata source — resolved 2026-06-09: embedded JPEG COM marker (FFFE) + index
from `userDidOssList`. Map-edit write path — resolved 2026-06-09: confirmed sequence
o:204 (begin) → o:215/o:218/o:234 (add/delete/add-ignore) → o:201 (commit) → o:-1
(teardown). Message-record reachability — resolved 2026-06-09: v1 endpoint confirmed
(GET `/dreame-message-push/v1/message-record/list?version=v1`; v2 returns 0 records).

**Batch device-data / map retvals:** MAPD, MAPI, MITRC, OBS (hypothesized);
MAPL, MISTA (confirmed w/ open qs). Gap: per-field decode of the map-info and
mission-track structures. Validate: fetch via probe + diff against a known map state.

**MAP.* cache freshness** — `[UNKNOWN — to capture]` Is MAP.* populated on a fresh
mower that has never had the app open to the map view? Does the integration's
10-min refresh pull a stale/empty blob if the phone app has never been opened?
Capture: reset or provision a mower without opening the app, run
`DreameA2CloudClient.fetch_map()` and confirm whether MAP.* carries live data.

**Routed-action opcodes (s2p50 TASK / o-codes):** many hypothesized — o104/105
(plan/obstacle mower), o107/108 (cruise point/side), o110 (learn map), o205/206
(clear/expand map), o400 (binocular), o503 (cutter bias), o8 (OTA), o12 (lock — see
lock_robot incident memory), o15 (remote setting), joystick o2/4/5/7. Gap: confirm
each fires the intended action on g2408. Validate: **docked-window probe only**
(the o-code brute-force start-action incident — never blind-probe aiid≠50).

**OSS session-summary fields:** `mode` now **confirmed** (100=all/101=edge/102=zone/
103=spot/108=patrol — the mow-type op) and `start_mode` **partial** (1=scheduled,
0=manual/app; open: do voice/HA-service starts collapse to 0?). Still
hypothesized/unknown: result, stop_reason, pre_type, region_status, faults,
edge_status — value enums. Validate: collect summaries across varied session outcomes
(complete / rain-stop / fail-to-reach / zone / edge) and diff.

**Device events (s4 eiid1 args):** DECODED 2026-05-30 (patrol capture): arg1=mode/op
(=summary.mode / s2p50 op; patrol carried 108), arg9=OSS session-summary object key,
arg13=fault/event timeline `[[unix_ts, s2p2_code]]` (empty on clean runs) — these are
now `verified`, not gaps. Still open: arg2 (end_code, hypothesized), arg11/arg15
(unknown), arg60 (abort_reason, hypothesized). NEW unknowns: piids 10 and 12 first
appeared on the patrol event — undecoded (not yet inventory entries; see TODO cleanup).
Validate: correlate event args with the session that fired them.

---

## 7. Cross-surface / behavioral gaps (tracked in TODO.md)

- **Reorient popup driver** — off the sniffed wire (popup edges land in the MQTT
  silent window on bare heartbeats; cloud poll/push suspected). Best MQTT proxy is
  the `[undock → s1p50/s1p51]` bracket. (inventory § s1p51 open_q.)
- **GPS world-coordinate read path** — **resolved 2026-06-09**: confirmed via
  `POST eu.iot.dreame.tech/dreame-mower-service-app/location/getRecords`; response
  carries `{gpsLat, gpsLong, card4G(ICCID)}`. Integration wiring deferred (Phase B).
- **Write path (Phase 3)** — integration write path for ~28 entities is now partially
  captured (app-MITM 2026-06-09: `device/sendCommand` code:0 via `:13267`; CFG and
  action writes confirmed; schedule write transport confirmed). Remaining open:
  confirming HA uses the same `sendCommand` path vs. the 80001 relay for CFG writes
  `[UNKNOWN — to capture]`. Map-edit opcodes (204/215/218/234/201) confirmed.
- **summary_map track over-segmentation** — TRACK_BREAK_MARKER trigger unknown. (TODO.)
- **Draw-by-driving zone definition wire** — BT-gated feature; wire shape unknown
  `[UNKNOWN — to capture]`. Capture when a BT-enabled probe session is available:
  use app to draw a zone by driving, capture the MQTT/cloud command emitted.
- **OTA apply flow** — s1p2 (OTA state) / s1p3 (OTA progress) never captured
  (no real pending update during any probe session) `[UNKNOWN — to capture]`.
  Capture: keep probe running through a real firmware update event.
- **Live-camera XP2P stream payload** — Tencent IoT-Video SDK off-relay P2P;
  credential chain confirmed (user/accesstoken → isDevUser → getIdentity → getP2PInfo)
  but stream bytes not captured `[UNKNOWN — to capture]`. Codec (H.264 vs H.265)
  and container format unknown. Capture: Tencent IoT-Video XP2P SDK intercept.
- **Tencent `getIdentity` secret rotation / stream codec** — `[UNKNOWN — to capture]`
  How frequently does getIdentity rotate secretId/secretKey? Can an open-source XP2P
  client consume the stream, or does it require the proprietary SDK?
- **Per-pathway selection sub-menu** — app shows a per-map pathway-ID selector when
  Pathway Obstacle Avoidance is enabled; write transport unknown `[UNKNOWN — to capture]`
  (deferred: needs pathways drawn first, then CFG-DIFF on the per-pathway list).
- **Map-edit mowing-shape type ids 12/14/15/16** — o:215 `type` field confirmed for
  9=Square/13=Heart/17=Cloud/18=Rainbow; Circle(12)/Triangle(14)/Droplet(15)/
  Mushroom(16) are inferred from APK labels, not captured `[UNKNOWN — to capture]`.
  Capture: draw each shape in app-MITM session, read `type` in the o:215 payload.

---

## Validation playbook

Referenced as shorthands above:

- **XTAB** — corpus cross-tab: bucket the byte/value by a known condition
  (s2p1 mode, dock-state, temp-state) over all 9 logs. Proves/【dis】proves a
  hypothesis without a new capture. Tooling pattern: stream `probe_log_*.jsonl`,
  build per-event timelines, `Counter` per bucket. (See the s1p1/s2p2 work
  2026-05-30.) **A claim is not `verified` from one run — it must hold corpus-wide**
  ([[feedback-corpus-validate-protocol-claims]]).
- **LABEL** — labelled-event capture: timestamp a physical/app action (±1-2 s) and
  diff the wire in that window. Used for tilt/lift/lid, undock/reorient, popup edges.
- **CFG-DIFF** — toggle one setting in the app, snapshot getCFG (or the empty-batch
  read) before/after, diff the changed key. The canonical write-surface probe.
- **wait-for-event** — rare triggers (OTA, AI-obstacle, Patrol, firmware update):
  keep the probe running; the slot is `[PROTOCOL_NOVEL]`-flagged when it first fires.
- **device-messages/v2 fetch** — for s2p2 notification *text*: GET the cloud message
  store within its (~10-record) retention window after the code fires.
- **docked-window probe** — for action/opcode confirmation: only probe with the
  mower docked and watched; never brute-force siid/aiid (start-action incident).

## Priority blank-spots (most-fireable, best ROI first)

1. **s1p1 `[13][14][15]` state block** — fires every heartbeat; XTAB + one labelled
   return-to-dock likely cracks the locomotion sub-states (and gives an on-wire
   reorient signal).
2. **s5p106** (1426 occ) + **s5p105** — frequent, unknown, fire during reorient.
3. **s2p2 codes 20/33** — need a repro within cloud retention for the text.
4. **s1p4 `[10-21]` motion vectors** — high-value for richer telemetry; XTAB-able now.
5. **CFG BP** — one app-side pathway creation + CFG-DIFF closes it (`PATH` confirmed 2026-06-09; `BP` semantics still open).
</content>
