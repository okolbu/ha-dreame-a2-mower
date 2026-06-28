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
inventory tally (refreshed 2026-06-28, post wire-truth audit + five-source reconciliation):
**276 confirmed / 40 partial / 72 hypothesized / 3 unknown** across **391
entries**; **116** carry `open_questions`.

The 2026-06-28 audit reconciled the inventory against **five sources** and closed
the drift from each: the integration **code** (full-surface — schedule blob was
byte-exact in `schedule_decode.py` but marked "[UNKNOWN] protobuf"; +8 more drift
items), the full **probe corpus** (2.5 months / ~2M msgs, not "9 logs" — fixed
s2p2=24/20 seen_on_wire), the **MITM captures + FINDING docs** (OTA flow + the
getDeiviceFile photo-fetch endpoint shipped in code but absent from the SoT), the
**HA session archive** (98 live sessions — decoded result/stop_reason/region_status/
faults + 8 more summary fields the cloud-OSS window couldn't), and a **live device
probe** (OBS obstacle-row layout). A `tools/inventory/findings_fold_check.py` guard
now prevents the FINDING→inventory drift class recurring.

**What genuinely remains** (bucketed by what would close each — none is desk-work
on data already on disk except bucket 5):
1. **Needs a condition to fire** — ~15 rare fault s2p2 codes (never fired in 98
   sessions), a human-present recognition event, a `start_mode=2` origin, a lawn
   >655 m² (uint24 high bytes).
2. **Needs an app action under MITM** — schedule Edge-record byte-7; `MAPL[2..4]`;
   unexercised opcodes (o=104/105/205/206/503/8, o=208).
3. **BT-gated (rig has no Bluetooth)** — manual steering, live video.
4. **Relay-flaky retry** — siid-4 (`s4p68`/`s4p83`).
5. **Genuinely-undecoded bytes, data on disk** — `s1p1` 4/5/8/9/13-15/18 + [10]&0x80,
   `s1p4` deltas [10-21], `s5p104-108`/`s6p1` enums, `s2p51 {type}`, `s2p56` middle
   byte, `MITRC` flag 0/0xff. (The only true desk-work residuals.)
6. **Not reachable on the tried path** — ARM/CHECK/WINFO/PREP (null via routed-get).
7. **Cross-cutting crypto** — the `sign` field algorithm (getDeviceFile signer
   unreproduced).

Earlier sweeps (2026-06-09 app-MITM) resolved
SCHDTV3/GPS/PATH/PIN/REMOTE/photo-metadata/map-edit/message-record gaps; added
SCHDSV3 v-layout, BAT[2], LIT.fill, draw-by-driving, OTA flow, XP2P stream,
per-pathway, shape ids 12/14/15/16, MAP.* freshness, Tencent getIdentity.

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

**CLOSED 2026-06-19 — catalog `heartbeat` channel (45 codes):** This is a
non-firing app artifact — a subset of iot fault_names that never appears as
numeric codes on g2408 s1p1. Confirmed via 93,888 corpus frames (9 probe logs):
s1p1 carries a 20-byte boolean-flag blob, not numeric fault codes. The real
s1p1 faults are the decoded boolean flags; catalog-quality fault_text/tier/detail
is now surfaced via binary_sensor extra_state_attributes using a flag→iot-code
map (bumper→9, drop_tilt→1, lift→0, emergency_stop→23, battery_temp_low→43).
Not a gap to chase. Source: `[apk:g2408-plugin-ext1423]`.

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
| s2p2 catalog 37-78 (FAULT_PATH_IMPASSABLE, ALERT_LIDAR_DIRTY, …) | hypothesized | mostly **never observed** | 2026-06-28: 15 codes (37/38/40/41/44/49/57/58/59/61/62/64/65/66/67) had their old vacuum/apk names (RIGHT_MAGNET etc.) CORRECTED to the authoritative g2408 app fault catalog (`fault_catalog.json` [apk:g2408-plugin-ext1423]); the names are now correct but the codes remain **unobserved on the g2408 wire** (decoded:hypothesized = missing wire observation, not a missing name). Codes 39/45/46/47/78/117 are absent from the catalog — still speculative. EXCEPTIONS observed+decoded earlier (2026-05-30): 51=patrol-start, 71=standby-too-long-return, 74=patrol-ended, 76=cannot-reach-maint-point; 2=robot-trapped, 4=left-drive-wheel-error (single obs, `partial`). | wait-for-event; treat unobserved as unconfirmed |
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
| BP | **confirmed** (2026-06-09) | ~~semantics unknown~~ RESOLVED: `BP{on:bool, day:1-7}` confirmed by app-MITM sweep; `on`=Start-from-Stop-Point, `day`=Stop-Point Term 1–7 days. Read `BP:[1,4]=[on,day]`. See inventory § BP. | no further action needed |
| DLS | hypothesized | daylight-savings flag, stable 0 | CFG-DIFF across a DST boundary |
| PRE | **confirmed** (2026-06-09) | ~~g2408 PRE=[0,0]; not the vacuum 10-elt shape~~ RESOLVED: 19-element int array fully decoded by isolated app toggles; all 12 General Mode settings mapped (indices 3/4/5/6/7/9/10/12/13/14/15/16); [1]=map index, [2]=zone index. See inventory § PRE. | no further action needed |
| PREI | hypothesized | separate from PRE; semantics unknown | CFG-DIFF if seen in reads |
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
Schedule-blob run-record open items (from the 2026-06-10 schedule-write decode,
`[app-mitm:2026-06-10-schedule-write]`):
- **byte[5] meaning** — `[UNKNOWN — to capture]` always 0x00 in all 3 captured
  modes (all-area / zone-full / zone-edge); purpose unconfirmed. Capture: diff a
  run record where the app sets a value that lands in byte[5].
- **2nd-edge `seg=1`** — `[UNKNOWN — to capture]` only `seg=0` observed; the test
  device has a single edge/zone, so the second-edge selector is unconfirmed.
  Capture: define a second edge/zone and schedule an edge run on it.
- **multi-day-per-run** — `[UNKNOWN — to capture]` whether multiple weekdays for one
  run are a bitmask in byte[2] high bits vs. multiple run records is unconfirmed.
  Capture: schedule a run on two days, diff the blob.
- **SCHDSV3 `flag` (s[1])** — `[UNKNOWN — to capture]` second state element is 0 in
  all captures; semantics unknown. Capture: toggle schedule states, diff s[1].
- **slot allocation on add-new** — `[UNKNOWN — to capture]` how a brand-new schedule
  slot id is chosen on add (vs. edit of an existing slot) is unconfirmed. Capture:
  add a third schedule and observe the SCHDIV3 `i` / row slot index.
`PIN` write shape — resolved 2026-06-09: `{type:'auth'|'update', value:<plaintext int>}`.
Photo metadata source — resolved 2026-06-09: embedded JPEG COM marker (FFFE) + index
from `userDidOssList`. Map-edit write path — resolved 2026-06-09: confirmed sequence
o:204 (begin) → o:215/o:218/o:234 (add/delete/add-ignore) → o:201 (commit) → o:-1
(teardown). Message-record reachability — resolved 2026-06-09: v1 endpoint confirmed
(GET `/dreame-message-push/v1/message-record/list?version=v1`; v2 returns 0 records).

**Map-edit — rename/delete shipped, remaining gaps** (wired v1.0.25a6, 2026-06-12;
o=219 rename + o=218 delete via the o=204/o=201 transaction + o=200 select):
- **delete-category (`type`) codes** — `[UNKNOWN — to capture]` only `type=0` (zone /
  no-go) and `type=4` (ignore-obstacle) observed in the 2026-06-09 capture; any other
  category values for o=218 are unconfirmed. Capture: delete each remaining object kind
  (spot zone, patrol/cruise point, maintenance point) and diff the o=218 `type` field.
- **deleting a MOWING zone** — `[UNKNOWN — to capture]` the captured o=218 deletes were
  all exclusion objects (ids in the 100/300 object-id space, `type` 0/4), never a
  mowing-zone `region` (1-62). Whether a mowing zone is deletable via o=218 (and with
  which id/type) is unverified, so `deletable_objects` deliberately offers exclusions
  only; mowing zones are rename-only. Capture: delete a lawn zone in the app and diff
  the o=218 id/type vs the zone's region.
- **rename-map + delete-whole-map wire** — `[UNKNOWN — to capture]` only zone-rename
  (o=219) is captured; renaming an entire MAP and deleting a whole map are UNCAPTURED
  (opcode + payload unknown). Capture: rename a map then delete a map in the app and
  snoop s2a50.
- **create (o=215 / o=234) + split/merge (o=220 / o=221)** — WIRED (v1.0.25a7, 2026-06-12)
  as coordinate-driven services create_no_go_zone / create_ignore_obstacle /
  create_mow_shape / split_zone / merge_zones via the o=204/o=201 edit transaction; split/
  merge flagged destructive (clear zone schedule + per-zone prefs). Coords pass as map
  edit-frame metres. Still `[UNKNOWN — to capture]`: whether the firmware echoes
  o:219/o:220/o:221 on s2p50.
- **F2b interactive draw card + edit-frame↔render-frame coordinate verification** —
  **RESOLVED 2026-06-12.** Frame verified: the o=215 edit-frame metres ARE the
  `projectPoint` render frame (cloud-mm ÷ 1000) — no reflection/rotation/offset, inverse
  recovers the wire metres exactly (`map-edit-frame-verification-2026-06-12.md`). Interactive
  map-editor card shipped with create / edit-in-place / rotate / move / delete. Edit-in-place
  + rotate were confirmed to reuse o=215 with `id:<real>` as the only discriminator and
  rotate/resize baked into `points` (no angle field) — `dreame-app-mapedit-rotate-edit-2026-06-12.md`.
- **rotate + edit-in-place wire** — **RESOLVED 2026-06-12** (`[app-mitm:2026-06-12-mapedit-rotate-edit]`).
  o=215 edit-existing = same opcode as create, `id:<real>` replaces in place; rotate/resize are
  sent as already-transformed corner `points` (no angle field). STILL OPEN: o=234 (ignore-obstacle)
  edit-in-place is taken BY ANALOGY with o=215 — capture an o=234 with a real id to confirm.
- **curved mow-shape rotation point representation** — `[UNKNOWN — to capture]` The rotate
  capture covered the 2-pt-bbox / polygon-corner shapes (square, no-go poly, curved-shape bbox).
  How a CURVED preset shape (heart/cloud/rainbow/teardrop) encodes rotation in its 2-pt bbox —
  whether a rotated curved shape rides solely on the bbox corners or needs an extra orientation
  term — is not isolated. Capture: rotate a curved mow-shape in app-MITM and diff its o:215 points.
- **decode mow-shapes from the map blob** — `[UNKNOWN — to capture]` Placed decorative
  mow-shapes are NOT decoded out of the cloud map blob (only no-go/ignore/zone objects are), so
  the card cannot SELECT an existing mow-shape to edit/rotate/delete it (create-only). Capture/decode:
  find where placed mow-shapes live in the map structure so they surface as editable objects.

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

- **lock_bot (routed o=12):** `[UNKNOWN — to capture]` No lock/unlock button exists in
  the current Dreame app UI; the backend MAY add support in a future firmware/app
  version. On current g2408 firmware op=12 is ACCEPTED-BUT-NO-EFFECT (cloud r=0, no
  panel-lock observed, no s2p50 echo). Parallel channel to CFG.CLS write (child lock)
  — which one firmware reads is unknown. Integration `lock_bot` entity stays
  DEVICE_WRITE_UNPROVEN. Capture step: watch for a future app lock control or
  backend feature flag.

- **generate_3dmap (routed o=10):** `[UNKNOWN — to capture]` What ACTUALLY triggers a
  3D-map snapshot on g2408 is still unknown — op=10 is ACCEPTED-BUT-NO-EFFECT
  (live probe 2026-06-08: r=0 ×2, no new 3dmap OSS object). The 2 existing snapshots
  (2026-04-20, 2026-05-10) were created by an internal firmware condition (likely
  post-mow or enough-map-change), not a callable action. Integration `generate_3dmap`
  entity stays DEVICE_WRITE_UNPROVEN. Capture step: identify what fires the
  s2p54-progress(0→100) → s99p20(object-name) upload sequence on the next occurrence.

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
- **SETTINGS-only per-map fields (Phase A2 deferred)** — The per-map SETTINGS fields
  `cutterPosition`, `cutterPositionHeight`, `edgeMowingNum`, `edgeMowingWalkMode`,
  `obstacleAvoidanceSensitivity`, `edgeCuttingAttachment` have NO confirmed PRE
  index. Whether a SETTINGS-only write to these fields changes the mower's
  behavior is unverified — for the PRE-mapped fields, SETTINGS-only writes were
  confirmed cloud-cache-only (device firmware did NOT apply). Capture step: toggle
  each in an app-MITM session and diff PRE vs SETTINGS before/after to determine
  which store the firmware reads. `[UNKNOWN — to capture]`
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
- **Map-edit mowing-shape type ids** — WIRE-CONFIRMED for 9=square, 13=heart, 15=teardrop,
  17=cloud, 18=rainbow (these `type` values appear in o:215 capture payloads; 15 confirmed
  2026-06-12 `[app-mitm:2026-06-12-mapedit-rotate-edit]`). `[UNVERIFIED]` 12=circle, 14=triangle,
  16=mushroom — these are INFERRED from the Shapes-screen (IMG_4615.PNG) left→right ordering
  filling the 9,12-18 sequence, NOT seen on the wire. They are wired in `create_mow_shape` on that
  inference; if the firmware numbers them differently a "triangle" call would silently draw a
  different shape (no malformed payload, just wrong shape). Capture: draw each of
  circle/triangle/mushroom in an app-MITM session and read its `type` in the o:215 payload to
  confirm/correct the mapping. Also `[UNKNOWN — to capture]`:
  type ids 10 and 11 — no shape occupies the gap between square(9) and circle(12) in this app
  build, so they appear unused on g2408.
- **Type-3 transient (normal) obstacle photo** — `[UNKNOWN — to capture]`,
  verified-negative across the whole corpus as of 2026-06-12. There are THREE
  photo types: (1) patrol photos and (2) AI-obstacle photos both land in the
  persistent gallery (`userDidOssList`, Aliyun OSS `ali_dreame/` prefix —
  confirmed 2026-06-09); (3) **normal obstacle photos** captured each time the
  mower navigates around an obstacle are EPHEMERAL — viewable ONLY by tapping an
  obstacle icon on the LIVE session map, and the icons go dead once the session
  ends. Type-3 has NEVER been captured `[app-mitm:2026-06-12-obstacle-photos]`:
  the map-blob `ai_obstacle` array was empty in every capture, MQTT :19973
  carried zero photo refs, and no obstacle/detection/IPC endpoint was ever
  touched — because every capture was emulator-driven UI with no REAL mow + REAL
  detection, the only scenario that arms type-3. Two all-area/overnight mows in
  the 2026-06-16 session produced 0 new gallery objects. Two competing hypotheses
  for what tapping a live icon does, both `[UNVERIFIED]`: (a) read a now-populated
  `ai_obstacle [x,y,type,possibility,key,file_name,random]` entry from the live
  map blob and mint a signed URL to the SAME `ali_dreame/` OSS (dreame-vacuum
  analogue), or (b) hit a distinct endpoint (lead:
  `/smart-app/ipc/detection/event/list`). Capture step: during a REAL mow run
  `scripts/arm-obstacle-capture.sh` (snapshots gallery baseline + arms all 3
  surfaces), TAP each live obstacle icon while the session is active, then
  `scripts/harvest-obstacle-capture.sh` to diff for non-empty `ai_obstacle`,
  NEW OSS GETs, and any new detection/photo endpoint — a new object key OR a
  populated `ai_obstacle` confirms type-3 and disambiguates (a) vs (b).
  Status 2026-06-16: rig armed (`scripts/arm-obstacle-capture.sh`,
  `harvest-obstacle-capture.sh`, `obstacle-watch.sh` in MITM toolkit); needs
  a real mow + real detection + live obstacle-icon tap.

- **CRUISED patrol-attribute decode** — `[UNKNOWN — to capture]`. The CRUISED
  CFG write carries per-patrol-point cycles (1/2/3) and auto-capture-photos toggle.
  One sample captured 2026-06-16: `{idx:0, value:[-1,3,1,3]}`. Field order is
  UNDECODED [UNVERIFIED]: which element of `value[]` maps to cycles vs auto-capture
  is not established; no read of CRUISED was captured. Auto-capture behaviour known:
  3 photos/point → gallery. Blocked during a mow (cannot toggle safely mid-run).
  See inventory `cfg_keys § CRUISED` for the captured sample.
  Capture step: in an app-MITM session with the mower docked, toggle cycles 1→2→3
  and auto-capture on/off independently and diff the `CRUISED` write `value[]`
  between each toggle. Also capture a GET of CRUISED to confirm the read shape.

- **BT manual-drive / joystick steering** — `[UNKNOWN — to capture]` (BT GATT;
  off-cloud). Manual drive requires Bluetooth proximity (out-of-range = mower stops,
  controls vanish). Steering commands are BT GATT, NOT cloud — so they never appear
  on the :13267 miio or :19973 MQTT surfaces. Capture path: enable BT HCI snoop
  on a real Android phone (`adb shell settings put global bluetooth_hci_log 1`),
  drive the mower in manual mode, retrieve `btsnoop_hci.log` and open in Wireshark
  `btatt` / `btle` dissector. The emulator has NO host-BT passthrough (only simulated
  RootCanal/netsim) — this gap cannot be closed via the emulator rig.
  Note: the related **draw-by-driving** zone-definition wire is a separate BT gap at
  the "Draw-by-driving zone definition wire" entry above (same BT surface; different
  app flow). Both require the real-phone btsnoop capture path.
- **iotoss auth mode: JWT vs body sign** — the integration sends userDidOssList and
  checkDevOssStorage requests with a JWT Bearer header (standard for other endpoints).
  The app-MITM capture 2026-06-09 showed the app sends an additional body `sign`
  field `[UNKNOWN — to capture]`. If the endpoint rejects JWT-only auth live, the sign
  algorithm must be RE'd. Capture step: confirm the integration's live requests are
  accepted (r=0, records returned) on the next connected run; if rejected, diff the
  failing vs. app request and recover the sign computation.
- **mp4 HA Media browser playback** — the `sensor.dreame_a2_mower_latest_video`
  attribute `mp4_path` exposes the local filesystem path. Wiring this as a proper HA
  `media_source` provider (so the clip is playable in the Media browser) is a
  follow-up `[UNKNOWN — to capture]`; requires implementing the MediaSource integration
  platform and registering the video archive root as a browsable media directory.

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
6. **Photo AI-class vocabulary + obstacle-vs-manual discriminator** `[UNKNOWN — to capture]` —
   the gallery categorizer (`protocol/photo_category.py`) is wired but two parts are
   provisional, because the only detections in the 2026-06-09 capture corpus are
   `person`. (a) `ANIMAL_CLASSES` is a best-guess label set; any unknown COM `cls`
   currently falls through to `ai_object` (raw label preserved, no silent loss), so the
   human/animal/object split is unconfirmed for non-person detections. (b) The
   obstacle (COM `o` in mow modes 100-103 + empty detections) vs manual (no COM)
   discriminator may overlap if normal-obstacle photos turn out to carry no COM.
   **Capture:** during a real mow that produces an animal/object AI detection AND a
   navigated physical obstacle, log each new photo's COM `o`/`cls` (via
   `parse_jpeg_com`) alongside its userDidOssList record; confirm the animal/object
   `cls` vocabulary and whether obstacle photos have a COM at all. The userDidOssList
   server `category` is always 0, so it gives no help here — the COM is the only
   source (`inventory.yaml § oss_photo_list` verification 2026-06-13).
</content>
