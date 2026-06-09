# App-findings Phase 0 — Knowledge Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the 2026-06-09 app-MITM settings sweep into the source-of-truth files (`inventory.yaml`, `entity-inventory.yaml`, `knowledge-gaps.md`) and reconcile/supersede stale Tier-2 docs, with correct epistemic status and zero runtime behavior change.

**Architecture:** Pure documentation/data sweep. No `.py` edits. Tasks are sequenced by surface group so that the two shared YAML files are written serially (no clobbering). "TDD" adapts to data work: each task makes its edit, then **runs the relevant inventory validator/audit as the test** (expected: green), then commits. The full suite + a completeness critic run last.

**Tech Stack:** YAML inventories, the repo's `tools/inventory/*` validators (`inventory_gen.py --validate-only`, `inventory_audit.py`, `entity_inventory_audit.py`, `wire_census.py`, `journal_completeness_check.py`, `audit_outstanding_retractions.py`), pytest (vanilla venv at `/data/claude/homeassistant/.venv-vanilla`).

**Source evidence (out-of-tree raw):**
- `/data/claude/homeassistant/dreame-app-findings-2026-06-09-settings-sweep.md`
- `/data/claude/homeassistant/dreame-app-WRITE-implementation-guide-2026-06-09.md`

**Design:** `docs/superpowers/specs/2026-06-09-app-findings-phase0-knowledge-capture-design.md`

**Conventions for every inventory edit (read once, apply throughout):**
- Append (never overwrite) a record to the entry's `verifications:` list:
  ```yaml
  verifications:
    - date: "2026-06-09"
      status: verified            # or partial / presumed / retracted
      claim: "<one-line statement of what's true>"
      evidence: "app-mitm:2026-06-09-settings-sweep"   # omit when status=presumed
      # retracts: "<prior claim verbatim>"   # required when status=retracted
      # reason: "<why>"                       # required when status=retracted
  ```
- Bump the entry's `status.last_seen: "2026-06-09"`.
- When promoting confidence, update `status.decoded:` (`hypothesized`→`confirmed`, etc.).
- Every prose sentence about a wire surface carries an inline epistemic tag (`[app-mitm:2026-06-09-settings-sweep]`, `[UNVERIFIED]`, or `[UNKNOWN — to capture]`) per CLAUDE.md fact discipline.
- **Honesty boundary:** do NOT edit `control_honesty.py` or any `.py` file. Verdicts stay read-only until each feature sub-project wires the write.

---

### Task 1: In-tree wire-capture citation target

**Files:**
- Create: `docs/research/wire-captures/app-settings-sweep-2026-06-09.md`

- [ ] **Step 1: Create the condensed Tier-3 wire-capture**

Use the same banner the other `wire-captures/*.md` files use. Confirm the exact banner text first:

```bash
head -8 docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md
```

Then create the file with that banner + a compact resolution table. Content:

```markdown
<!-- Tier-3 dated evidence — read for context, NOT current truth. inventory.yaml wins. -->

# App settings-sweep — wire capture (2026-06-09)

Condensed index of the 2026-06-09 Android-app MITM settings sweep (app 2.5.6.4
→ `eu.iot.dreame.tech:13267` relay + miio-MQTT). Full raw detail lives
out-of-tree at:
- `/data/claude/homeassistant/dreame-app-findings-2026-06-09-settings-sweep.md`
- `/data/claude/homeassistant/dreame-app-WRITE-implementation-guide-2026-06-09.md`

Facts below are promoted into `inventory.yaml` (the SoT); cite this file as
`app-mitm:2026-06-09-settings-sweep` in `verifications:`.

## Resolved this sweep
| Surface | Resolution |
|---|---|
| PRE indices 3,4,5,6,7,9,10,12,13,14,15,16 | Each mapped + value-confirmed by isolated toggle |
| PRE[0]/[1]/[2] | version byte / map index / zone index |
| CFG WRP/FDP/PATH/DND/LOW/PROT/BAT/BP/STUN/AOP/CLS/PIN/VOICE/VOL/LANG/MSG_ALERT/ATA/REC/LIT | exact write payloads |
| PREP | per-zone General↔Custom enable {idx,value} |
| Routed opcodes 3,4,5,6,9,13,100–103,107,200,201,204,208,215,218,219,220,221,234,400 | confirmed |
| Schedule write | SCHDDV3 (chunked protobuf, format known via schedule_decode.py) + SCHDIV3 + SCHDSV3 |
| MAP.* | decoded-map JSON cached in iotuserdata |
| OSS photos/video | userDidOssList + embedded-JPEG metadata + checkDevOssStorage + addOssNew/ossUploaded |
| GPS | location/getRecords (WGS84 strings, ATA[2]-gated) |
| NET / REMOTE | wifi list / 4G SIM |
| Message center | message-record/list v1, device-messages, share-messages |
| Tencent video | /dreame-third-video/tx/* cred chain (stream off-relay) |

## Supersedes
- `app-api-surface-2026-05-25.md`: marketing System Messages ARE reachable via
  `message-record/list?version=v1` (the earlier probe used `/v2/`, which was empty).
```

- [ ] **Step 2: Add a journal line**

Append one dated line to `docs/research/g2408-research-journal.md` (under its latest-dated section):

```markdown
- 2026-06-09 — App settings-sweep MITM complete; facts promoted to inventory.yaml. See `wire-captures/app-settings-sweep-2026-06-09.md`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/research/wire-captures/app-settings-sweep-2026-06-09.md docs/research/g2408-research-journal.md
git commit -m "docs: add 2026-06-09 app settings-sweep wire-capture (Tier-3 citation target)"
```

---

### Task 2: inventory.yaml — PRE index map

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (the `id: "PRE"` entries near line 4577 and 5350)

- [ ] **Step 1: Locate and read the PRE entries**

```bash
grep -n 'id: "PRE"' custom_components/dreame_a2_mower/inventory.yaml
```

Read both entries (cfg_keys §4577 and the second §5350) to see the current index map and `decoded` status.

- [ ] **Step 2: Update the PRE index map**

Set/confirm these indices in the PRE entry's `semantic:` index table and append the verification. Indices and target status:

| idx | meaning | status |
|----:|---|---|
| 0 | version/checksum byte (app writes 0, fw reads 123) | confirmed |
| 1 | map index | confirmed |
| 2 | zone index (was "custom-scope") | confirmed — **retraction** of the prior "PRE[2]=custom-scope" reading |
| 3 | Mowing Efficiency 0=Standard/1=Efficient | confirmed |
| 4 | Mowing Height cm×10 (30–70) | confirmed |
| 5 | Mowing Direction mode 0=Crisscross/1=Customize/2=Chequerboard | confirmed |
| 6 | Mowing Direction angle (deg, Customize only) | confirmed |
| 7 | Automatic Edge Mowing 0/1 | confirmed |
| 9 | Obstacle Avoidance on Edges 0/1 | confirmed |
| 10 | EdgeMaster 0/1 | confirmed |
| 12 | LiDAR Obstacle Recognition 0/1 | confirmed |
| 13 | Obstacle Avoidance Height 5/10/15/20 cm | confirmed |
| 14 | Obstacle Avoidance Distance 10/15/20 cm | confirmed |
| 15 | AI Recognition bitmask bit0=Human/bit1=Animal/bit2=Object | confirmed |
| 16 | Safe Edge Mowing 0/1 | confirmed |
| 8,11,17,18 | reserved / unknown | unknown |

Append two verification records (one normal, one retraction):

```yaml
    verifications:
      - date: "2026-06-09"
        status: verified
        claim: "PRE write array indices 3,4,5,6,7,9,10,12,13,14,15,16 each mapped
          and value-confirmed by isolated app toggles; [0]=version byte (app writes
          0/fw reads 123), [1]=map index, [2]=zone index. [15] bitmask bit0=Human
          bit1=Animal bit2=Object; [5] 0=Crisscross/1=Customize/2=Chequerboard."
        evidence: "app-mitm:2026-06-09-settings-sweep"
      - date: "2026-06-09"
        status: retracted
        claim: "PRE[2] is the zone index, not a generic custom-scope flag."
        retracts: "PRE[2]=1 marks custom/zone scope"
        reason: "Post-split per-zone PRE writes showed [1]=map index and [2]=zone
          index (new zones got zone-index 1 and 2). app-mitm:2026-06-09-settings-sweep"
```

> NOTE: `retracts:` must quote the prior claim **verbatim**. Grep the PRE `semantic:` block for the actual "custom-scope" wording and use it exactly; adjust the quote above to match.

- [ ] **Step 3: Run the schema validator**

```bash
python tools/inventory/inventory_gen.py --validate-only
```
Expected: PASS (exit 0, no schema errors).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml
git commit -m "inventory: PRE index map confirmed (2026-06-09 app sweep); retract PRE[2] custom-scope"
```

---

### Task 3: inventory.yaml — CFG keys promote/reconcile

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (`cfg_keys:` §4222, `cfg_individual:` §4865)

- [ ] **Step 1: For each CFG key below, append a 2026-06-09 verification + bump last_seen + promote decoded status**

Keys and the confirmed write payload to record in `semantic:`/`payload_shape:`:

| key | confirmed write payload | status / note |
|---|---|---|
| WRP | `{value, time(hrs), sen}` | confirmed (live-confirms ioBroker shape) |
| FDP | `{value}` 0/1 | confirmed |
| PATH | `{value}` 0/1 master enable | confirmed (resolves PATH semantics) |
| DND | `{value, time:[start_min,end_min]}` | confirmed |
| LOW | `{value, time:[start_min,end_min]}` | confirmed |
| PROT | `{value}` 0=Direct/1=Smart | confirmed |
| BAT | **typed key**: `{type:"charging", value:[en,start_min,end_min]}` and `{type:"power", value:[recharge%,resume%,flag]}` | confirmed write is typed — RECONCILE against the existing 6-int read shape; record both the read list and the typed write |
| BP | `{on:bool, day:1-7}` = [Start-from-Stop-Point, Stop-Point-Term] | confirmed — **retraction** of the existing `bp_unknown`/"meaning unknown" entry |
| STUN | `{value}` 0/1 (Auto-Recharge after Standby; own key, NOT BAT.power[2]) | confirmed |
| AOP | `{value}` 0/1 (already confirmed; add that re-enable shows privacy screen but no consent on wire) | confirmed |
| CLS | `{value}` 0/1 (CLS is the writable surface; s4p27 is read-side) | confirmed |
| PIN | `{type:"auth"\|"update", value:<plaintext int>}`; read `{result,time}` | confirmed (resolves PIN encoding; values redacted) |
| VOICE | `{value:[Regular,WorkStatus,SpecialStatus,Error]}` | confirmed |
| VOL | `{value:0-100}` | confirmed (currently only 3 hits — likely needs a fuller entry) |
| LANG | `{type:"voice"\|"text", value:idx}` (En=0,No=7,Da=9) | confirmed |
| MSG_ALERT | `{value:[Anomaly,Error,Task,Consumable]}` | confirmed — **device-writable**, refutes any app_only classification |
| ATA | `{value:[lift,offmap,realtime]}` | confirmed (already) |
| REC | `{value, sen:0/1/2, mode:[Standby,Mowing,Recharge,Patrol], report:[VoiceInApp, CaptureHumanPhotos, PushInterval{3,10,20}]}` | confirmed |
| LIT | `{value, time:[start,end], light:[Standby,Working,Charging,Error], fill}` | confirmed (residual: `fill` partial) |
| PREP | `{idx:<zone0>, value:0/1}` General(0)/Custom(1) per zone | confirmed |

Residual `partial`/open items to record as `open_questions` (do not claim confirmed): `BAT.power value[2]` flag, `LIT.fill`.

Worked example (BP — the retraction case):

```yaml
  - id: "BP"
    name: "start_from_stop_point"          # rename from bp_unknown
    category: "cfg"
    payload_shape: "list[int(2)] [start_from_stop_point(0/1), stop_point_term_days(1-7)]"
    semantic: |
      Start-from-Stop-Point + Stop-Point Term. [app-mitm:2026-06-09-settings-sweep]
      Write payload {on:bool, day:1-7}: on=Start-from-Stop-Point boolean,
      day=Stop-Point Term in days. CFG read BP:[1,4]=[on,day]. Sample: [1,4].
    status:
      seen_on_wire: true
      first_seen: "2026-04-23"
      last_seen: "2026-06-09"
      decoded: confirmed
    references:
      apk: "ioBroker.dreame/apk.md §setX BP"
      integration_code: "custom_components/dreame_a2_mower/protocol/cfg_action.py"
      protocol_doc: "docs/research/inventory/generated/g2408-canonical.md § CFG keys"
    verifications:
      - date: "2026-06-09"
        status: retracted
        claim: "BP = [start_from_stop_point, stop_point_term_days]; write {on,day}."
        retracts: "TBD. Same shape as WRP list(2). Sample: [1, 4]. No toggle-correlation test performed; semantics unknown."
        reason: "App Start-from-Stop-Point toggle + Term picker wrote BP{on,day}. app-mitm:2026-06-09-settings-sweep"
```

> For each key, grep its current `semantic:` and quote it verbatim in any `retracts:`.

- [ ] **Step 2: Validate**

```bash
python tools/inventory/inventory_gen.py --validate-only
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml
git commit -m "inventory: confirm CFG write payloads from 2026-06-09 app sweep (WRP/DND/LOW/PROT/BAT/BP/STUN/PIN/VOICE/VOL/LANG/MSG_ALERT/REC/LIT/PREP/PATH/FDP)"
```

---

### Task 4: inventory.yaml — routed opcodes

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (`opcodes:` §3066)

- [ ] **Step 1: Add/confirm opcode entries**

For each opcode, ensure an entry exists with `decoded: confirmed` (or `partial` where noted) and a 2026-06-09 verification:

| op | name | payload | status |
|---:|---|---|---|
| 3 | end/stop | none | confirmed |
| 4 | pause | none | confirmed |
| 5 | resume | none | confirmed |
| 6 | recharge/dock | none | confirmed |
| 9 | locate / find-my-robot | none | confirmed |
| 13 | cancel-dock-return | none | confirmed (distinct from stop o=3) |
| 100 | start / all-area mow | `{need_bp}` | confirmed |
| 101 | edge mow | `{edge:[[map,contour]]}` | confirmed |
| 102 | zone mow | `{region:[zoneIds]}` | confirmed |
| 103 | spot mow | `{area:[spotIds]}` | confirmed |
| 107 | point patrol | `{point:[cruisePointIds]}` | confirmed |
| 200 | select-map | `{idx}` | confirmed |
| 201 | map-edit commit | none | confirmed |
| 204 | map-edit begin | none | confirmed |
| 208 | FULL-state backup | `{idx}` ⚠ restore resets all | confirmed |
| 215 | add no-go | `{id,type,points,radius}` type 1=line/2=poly/3=circle; 9,12-18=mowing-shapes | confirmed (shape ids 12/14/15/16 partial — inferred) |
| 218 | delete-object | `{id,type}` | confirmed |
| 219 | rename-zone | `{region,name}` | confirmed |
| 220 | split-zone | `{id,line_start,line_end}` ⚠ destructive | confirmed |
| 221 | merge-zones | `{ids:[]}` ⚠ destructive | confirmed |
| 234 | add ignore-obstacle | `{id:-1,type:0,points}` (object category 4) | confirmed |
| 400 | camera/live-view on/off | `{on}` | confirmed |

Use the existing opcode entry schema (see `o_minus_1` at §3068) as the template. For the map-edit shape-id partials, add an `open_questions:` line naming ids 12/14/15/16 as inferred.

- [ ] **Step 2: Validate**

```bash
python tools/inventory/inventory_gen.py --validate-only
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml
git commit -m "inventory: confirm routed opcode map from 2026-06-09 app sweep (control + map-edit + camera)"
```

---

### Task 5: inventory.yaml — net-new read/write surfaces

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`

- [ ] **Step 1: Add net-new entries**

Pick the section that fits each surface (`cfg_keys` for CFG-relayed keys; a microservice/API section for HTTP endpoints — grep for an existing API-endpoint entry e.g. `getRecords`/`userDidOssList` returned 0 hits, so add under the most appropriate existing section, or add a new `api_endpoints:` top-level section if none fits, matching the established entry schema). Entries to add:

- **Schedule write** `SCHDSV3` / `SCHDDV3` / `SCHDIV3` — transport `confirmed`; SCHDDV3 entry blob = same protobuf as `protocol/schedule_decode.py` (`confirmed`, cite the decoder); residual `partial`: `SCHDSV3 {v:<packed int>}` seasonal-slot summary layout.
  ```yaml
      verifications:
        - date: "2026-06-09"
          status: verified
          claim: "Schedule write = 3-key txn SCHDDV3(chunked, base64 protobuf —
            same format protocol/schedule_decode.py decodes) + SCHDIV3(len) +
            SCHDSV3(per-slot enable), tied by shared v=ms txn-id."
          evidence: "app-mitm:2026-06-09-settings-sweep"
      open_questions:
        - "SCHDSV3 {v:<packed int>} seasonal-slot summary (18696/32923/65535) —
          per-day/time bit layout not part of the display decode. [UNKNOWN — to capture]"
  ```
- **`MAP.*` decoded-cache** — `getDeviceData {keys:["MAP.0",…]}` concat = JSON array of maps; element-type enum 0=mow/1=path/3=spot/6=cleanPoint/7=contour/8=cruise/10=ignore-obstacle; `confirmed`. Caveat: written by app on map view, may be stale — `open_questions` records a read-side populated-check as a Phase-C step.
- **OSS photos/video** — `userDidOssList {did,type}` (jpg/thumb, server returns signed filepath), embedded-JPEG COM metadata `{d:[{c,f,x,y,w,h}],o,s,sub}`, `checkDevOssStorage` (200MB quota), `addOssNew`/`ossUploaded` client upload; 6-mo retention; `confirmed`.
- **GPS** — `dreame-mower-service-app/location/getRecords` → WGS84 decimal-degree strings, 4G-SIM reported, `ATA[2]`-gated, ~4 m accurate, records=history; `confirmed`.
- **`NET`** (wifi current+list, RSSI dBm) and **`REMOTE`** (4G SIM activeTime/cardId/expiredTime/leftDays) — `confirmed`. (REMOTE has 4 existing hits — reconcile.)
- **Message center** — `message-record/list?version=v1` (System+Service+Activity), `device-messages` (per-device, source{siid,piid,value}), `share-messages`, `message-record/homestat`; `confirmed`.
- **`AI_HUMAN.0`** — `iotuserdata` KV, JSON-string bool, cascades with `REC.report[1]`; capture gate = AOP=1 + REC.report[1]=1 + AI_HUMAN.0=true; `confirmed`. (Expand the 1-hit stub.)
- **Tencent live video** — `/dreame-third-video/tx/*` cred chain (accesstoken/isDevUser/getIdentity/getP2PInfo→XP2P) `confirmed`; stream off-relay `[UNKNOWN — to capture]`.

- [ ] **Step 2: Validate**

```bash
python tools/inventory/inventory_gen.py --validate-only
```
Expected: PASS. If it fails on unknown `decoded`/`unit` vocab, that's handled in Task 6 — note the failing vocab and proceed to Task 6 before re-running.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml
git commit -m "inventory: add net-new surfaces (schedule write, MAP.* cache, OSS photos/video, GPS, NET/REMOTE, messages, AI_HUMAN, Tencent video)"
```

---

### Task 6: Schema-validator vocab sync (only if Task 5 introduced new vocab)

**Files:**
- Modify: `tools/inventory/inventory_gen.py` (`_DECODED_VALUES` / `_UNIT_VOCAB` frozensets)

- [ ] **Step 1: Run the validator to surface any new vocab**

```bash
python tools/inventory/inventory_gen.py --validate-only
```
If it reports an unregistered `unit:`/`decoded:` value, note it. If it passes, **skip this task entirely.**

- [ ] **Step 2: Add the new value(s) to the matching frozenset**

```bash
grep -nE "_UNIT_VOCAB|_DECODED_VALUES" tools/inventory/inventory_gen.py
```
Add the exact new token to the correct frozenset (decoded statuses use `confirmed/partial/hypothesized/unknown` — those already exist, so only a new `unit:` is likely).

- [ ] **Step 3: Re-validate**

```bash
python tools/inventory/inventory_gen.py --validate-only
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tools/inventory/inventory_gen.py
git commit -m "inventory: register new unit vocab for 2026-06-09 surfaces"
```

---

### Task 7: entity-inventory.yaml — write-path-captured records

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`

- [ ] **Step 1: Identify the affected entities**

These are the read-only/pending controls in `control_honesty.py` whose write path the sweep resolved. Cross-reference `CONTROL_MODES` (modes `_P`, `_C`, `_N` only) with the keys confirmed in Tasks 2–4. List includes (per `control_honesty.py`):
- selects: `rain_protection_resume_hours`, `lcd_language`, `voice_language`, per-map `mowing_direction`, `mowing_direction_mode`, `edge_walk_mode`, `mowing_efficiency`
- numbers: per-map `mowing_height`, `cutter_position(_height)`, `edge_mowing_num`, `obstacle_avoidance_height/distance/sensitivity`, `auto_recharge_battery_pct`, `resume_battery_pct`, `human_presence_alert_sensitivity`
- switches: per-map `automatic_edge_mowing`, `safe_edge_mowing`, `obstacle_avoidance_on_edges`, `lidar_obstacle_recognition`, `edgemaster`, `ai_recognition_humans/animals/objects`, `ai_human_enabled`, and `<key>` group `dnd`, `low_speed_at_night`, `custom_charging_period`, `rain_protection`, `led_*`, `human_presence_alert`

- [ ] **Step 2: For each, append a verification record (NO field changes)**

```yaml
    verifications:
      - date: "2026-06-09"
        status: verified
        claim: "Device write path captured (PRE[<idx>] / CFG <KEY> {<shape>}) but
          NOT yet wired in the integration; control_mode intentionally remains
          read-only until the feature sub-project wires + live-verifies it."
        evidence: "app-mitm:2026-06-09-settings-sweep"
```
Bump each entry's `status.last_seen: "2026-06-09"`. Do not change `control_mode`, `source`, or `unique_id` fields.

- [ ] **Step 3: Run the entity-inventory audit**

```bash
python tools/inventory/entity_inventory_audit.py
```
Expected: PASS.

- [ ] **Step 4: Verify control_honesty.py is untouched**

```bash
git diff --name-only | grep -q control_honesty.py && echo "ERROR: control_honesty.py changed" || echo "OK: control_honesty.py untouched"
```
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml
git commit -m "entity-inventory: record write-paths-captured (not wired) for read-only controls (2026-06-09)"
```

---

### Task 8: knowledge-gaps.md regen

**Files:**
- Modify: `docs/research/knowledge-gaps.md`

- [ ] **Step 1: Remove resolved gaps**

Read `docs/research/knowledge-gaps.md` (221 lines). Remove entries now resolved: SCHDTV3 SET transport, GPS world-coordinate read, `PATH` semantics, `PIN` encoding, photo-metadata source, map-edit write. (Check §6 cloud-API retval gaps and §7 cross-surface for these.)

- [ ] **Step 2: Add new open gaps**

Add: `SCHDSV3` packed-`v` summary layout; `BAT.power[2]` flag; `LIT.fill`; draw-by-driving zone wire; OTA apply flow; live-camera XP2P stream (off-relay); per-pathway selection; map-edit shape ids 12/14/15/16 (inferred). Each as a `[UNKNOWN — to capture]` line with a capture step.

- [ ] **Step 3: Verify against the doc's own sync note**

The doc header (§"How to keep this in sync") says it's regenerable from inventory non-confirmed/open entries. Confirm each added gap corresponds to a `partial`/`unknown`/`open_questions` inventory entry from Tasks 2–5.

- [ ] **Step 4: Commit**

```bash
git add docs/research/knowledge-gaps.md
git commit -m "docs: regen knowledge-gaps for 2026-06-09 sweep (drop resolved, add new opens)"
```

---

### Task 9: Tier-2 reconcile-and-supersede

**Files:**
- Modify: `docs/research/app-api-surface-2026-05-25.md`
- Modify: `docs/research/g2408-protocol.md`
- Modify: `docs/research/cloud-write-reference.md`
- Modify: `docs/research/g2408-app-capture-playbook-2026-06-09.md`

- [ ] **Step 1: Supersede stale claims in app-api-surface**

Find the message-record claim that marketing/System Messages are app-push-only / not in the RE'd surface and **correct it**: `message-record/list?version=v1` returns System+Service+Activity incl. marketing; the earlier probe used `/v2/` (empty). Scan the rest of the doc for `0 records`/`not reachable` conclusions the sweep overturned (OSS photos, GPS, messages) and correct or delete them. For each correction, also append a `status: retracted` verification on the matching inventory entry (quote the prior doc claim verbatim).

- [ ] **Step 2: Light touches to the other Tier-2 docs**

- `g2408-protocol.md`: ensure the opcode map + PRE/CFG write surfaces point at the confirmed inventory entries (no narrative duplication — one-line pointers).
- `cloud-write-reference.md`: add the confirmed CFG/PRE/routed write dictionary as a pointer to inventory.
- `g2408-app-capture-playbook-2026-06-09.md`: cross-link the settings-sweep wire-capture.

- [ ] **Step 3: Suspected-but-unconfirmed handling**

For any older claim the sweep did NOT touch but which looks doubtful, do NOT promote it — tag `[UNVERIFIED]` in place and add a verification step to `knowledge-gaps.md` instead.

- [ ] **Step 4: Run the outstanding-retractions audit**

```bash
python tools/inventory/audit_outstanding_retractions.py
```
Expected: PASS (no dangling retracted-claim prose left un-reworded).

- [ ] **Step 5: Commit**

```bash
git add docs/research/app-api-surface-2026-05-25.md docs/research/g2408-protocol.md docs/research/cloud-write-reference.md docs/research/g2408-app-capture-playbook-2026-06-09.md custom_components/dreame_a2_mower/inventory.yaml
git commit -m "docs: reconcile Tier-2 docs against 2026-06-09 sweep (supersede message v1/v2, OSS/GPS reachability)"
```

---

### Task 10: Roadmap doc

**Files:**
- Create: `docs/research/app-integration-roadmap.md`

- [ ] **Step 1: Create the roadmap**

```markdown
# App-integration roadmap (post 2026-06-09 MITM)

The 2026-06-09 app-MITM review produced read/write patterns for nearly every
g2408 attribute (Phase 0 captured them into inventory.yaml). Remaining work is
sequenced into feature sub-projects, built one at a time.

## Guiding principles
- **App-path-by-default.** Use the app's read/write path (the `sendCommand`
  s2.a50 relay: `{m:"s",t:KEY}` CFG / `{m:"a",o:N}` routed actions, plus the
  microservice endpoints) unless there's a strong reason not to. Keep the old
  method as a fallback where one exists.
- **Honesty boundary.** A control's `control_mode` flips to writable only in the
  same change that wires AND live-verifies its write (per the corpus-validate rule).
- **Cadence.** plan/build/plan/build — each sub-project gets its own
  brainstorm→spec→plan→build cycle; no monolithic upfront plan.

## Sequence
| Phase | Scope | Status |
|---|---|---|
| 0 | Knowledge capture (inventory + docs) | in progress |
| A | Writable-settings flip (~30 controls via PRE/CFG) | planned |
| B | Core-control verdict confirm (pause/stop/dock/resume + o=13) | planned |
| C | New read sources (GPS, NET/REMOTE, MAP.* cache, messages) | planned |
| D | Photo & video archive (OSS) | planned |
| E | Schedule editing (encode + chunked SCHDDV3/IV3/SV3) | planned |
| F | Map editing (zone/no-go/ignore CRUD; draw-by-driving deferred) | planned |
| G | Live camera (Tencent XP2P; may be infeasible in HA) | planned |
```

- [ ] **Step 2: Commit**

```bash
git add docs/research/app-integration-roadmap.md
git commit -m "docs: add app-integration roadmap (A-G sub-project sequence + principles)"
```

---

### Task 11: Completeness critic + full CI/test baseline

**Files:** none (verification only)

- [ ] **Step 1: Completeness critic — every finding maps to an inventory entry**

Re-read both findings docs and confirm each fact line is now represented in `inventory.yaml`/`entity-inventory.yaml`/`knowledge-gaps.md`. Produce a short checklist mapping each finding-doc section → inventory entry. Any unmapped fact → go back and add it (new commit). This is the explicit "did we capture everything" gate.

- [ ] **Step 2: Run the full inventory tool suite**

```bash
python tools/inventory/inventory_gen.py --validate-only
python tools/inventory/inventory_audit.py
python tools/inventory/inventory_audit.py --consistency
python tools/inventory/entity_inventory_audit.py
python tools/inventory/wire_census.py
python tools/inventory/journal_completeness_check.py
python tools/inventory/audit_outstanding_retractions.py
```
Expected: all PASS / clean exit. `wire_census.py` regenerates `docs/research/wire-census.json` — if it changes, commit it.

- [ ] **Step 3: Run the full test baseline**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q
```
Expected: 1591 passed, 4 skipped (unchanged baseline). The control_mode code-sync test under `tests/inventory/` must pass, proving `CONTROL_MODES` is untouched.

- [ ] **Step 4: Confirm zero `.py` source changes**

```bash
# 8d3cff3 = the spec commit, immediately before all Phase 0 work.
git diff --stat 8d3cff3..HEAD -- 'custom_components/dreame_a2_mower/**/*.py'
```
Expected: empty output — no `custom_components/dreame_a2_mower/*.py` changes. (Task 6's edit is to `tools/inventory/inventory_gen.py`, which this glob excludes.)

- [ ] **Step 5: Final commit (if wire-census.json or any completeness fix changed)**

```bash
git add -A docs/ custom_components/dreame_a2_mower/*.yaml
git commit -m "inventory: Phase 0 completeness sweep + regenerate wire-census"
```

> Per `feedback_push_upstream_regularly` / `feedback_tag_after_push`: Phase 0 is docs-only (not installable behavior), so a GitHub Release is NOT required. Push the branch when done so the work isn't stranded.
