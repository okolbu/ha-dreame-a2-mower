# Phase 0 — App-findings knowledge capture (design)

**Date:** 2026-06-09
**Status:** design, awaiting user review → writing-plans
**Scope:** Documentation / source-of-truth only. **Zero runtime behavior change.**

## Context

A multi-day Android-app MITM review (app `2.5.6.4` → `eu.iot.dreame.tech:13267`
relay + miio-MQTT) produced near-complete read/write patterns for almost every
g2408 attribute. Findings are captured in two parent-dir (out-of-tree) raw docs:

- `/data/claude/homeassistant/dreame-app-findings-2026-06-09-settings-sweep.md`
- `/data/claude/homeassistant/dreame-app-WRITE-implementation-guide-2026-06-09.md`

These resolve a large set of previously-open write paths and reveal new read
sources (OSS photos/video, GPS, NET/REMOTE, decoded `MAP.*` cache, message
center, Tencent live video). The integration **already has the transport** the
app uses — `routed_action` (s2.a50 `{m:"a",o:N}`), `set_cfg`/`set_pre`
(`{m:"s",t:KEY}`), `write_settings`, `dispatch_action`. So the new work is a
*payload dictionary*, not a transport rebuild.

This effort is decomposed into Phase 0 (this spec) + feature sub-projects A–G,
each with its own brainstorm→spec→plan→build cycle, executed one-by-one in order
(cadence: plan/build/plan/build, not one monolithic upfront plan). The A→G
sequence and the guiding principles live in a new roadmap doc (see §5).

## Goal & non-goals

**Goal:** every fact in the two findings docs is recorded in the source-of-truth
files with correct epistemic status, so (a) no future session re-derives it and
(b) each feature sub-project inherits a ready payload checklist.

**Non-goals (these belong to Phase A+):**
- Wiring any write handler.
- Flipping a `CONTROL_MODES` verdict to writable.
- Adding/renaming/removing entities.
- Live re-verification on the mower (the app MITM **is** the evidence for
  Phase 0; live re-verification is each feature sub-project's job when it wires
  the corresponding write).

**Net effect on the running integration: none.** Phase 0 touches **no `.py`
files** — inventory + docs only.

## §1 The honesty boundary (load-bearing)

Phase 0 must NOT flip read-only entities to `DEVICE_WRITABLE` in
`control_honesty.py`. An entity that advertises "writable" while its handler
still no-ops is exactly the dishonesty `control_honesty` exists to prevent. The
"a write path now exists but isn't wired yet" fact is recorded in
`entity-inventory.yaml` as a `verification` record on each affected entity
instead. The code verdict flips in Phase A, in the same change that wires the
write and live-verifies it.

Consequence: the CI **control_mode code-sync** test stays green because
`CONTROL_MODES` is untouched.

## §2 Evidence handling & canonicity

- **Raw findings docs stay out-of-tree** (parent dir), cited by the SoT as raw
  evidence (an extension of the `OLD/` archive convention).
- **One condensed in-tree wire-capture** at
  `docs/research/wire-captures/app-settings-sweep-2026-06-09.md` — standard
  Tier-3 non-authoritative banner, a compact table of what the sweep resolved,
  and a pointer back to the parent-dir raw docs. Matches the existing
  `wire-captures/*.md` pattern so Tier-2 docs / the journal have an in-tree
  citation target.
- **Evidence-pointer format** in `verifications:`:
  `app-mitm:2026-06-09-settings-sweep` for toggle-diff facts,
  `app-screenshot:<page>` where a UI page correlated it, `apk:<ref>` for static.
  These are real captures → status `verified`, except items the sweep itself
  flagged uncertain (see §3), which are `partial`.
- Evidence flow: raw (out-of-tree) → condensed wire-capture (in-tree Tier-3) →
  facts promoted into `inventory.yaml` (Tier-1 SoT) with pointers. Journal gets
  one dated line citing the wire-capture.

## §3 `inventory.yaml` updates (protocol SoT)

Every entry carries the inline epistemic tag per the repo fact-discipline rule.
Most CFG/PRE keys already have entries → this is mostly *promote/reconcile + add
a 2026-06-09 verification*, not net-new.

### Promote / reconcile (entries exist)

- **`PRE` index map** — `verified` for indices 3, 4, 5, 6, 7, 9, 10, 12, 13, 14,
  15, 16 (all isolated-toggle confirmed; **[15] AI bitmask bit0=Human/bit1=Animal/
  bit2=Object is `verified`** per user). `[5]` mode order
  (0=Crisscross/1=Customize/2=Chequerboard) `verified`. `[0]`=version byte (app
  writes 0 / fw reads 123); `[1]`=map index; `[2]`=zone index (refines the prior
  "custom-scope" reading — record as a `retraction`+correction of that claim);
  `[8,11,17,18]` stay `unknown`/reserved.
- **CFG keys** WRP / FDP / PATH / DND / LOW / PROT / BAT / BP / STUN / AOP / CLS /
  PIN / VOICE / VOL / LANG / MSG_ALERT / ATA / REC / LIT → `verified` with exact
  payload shapes from the sweep. Residual `partial` sub-fields: `BAT.power[2]`
  flag, `LIT.fill`. `PIN` value recorded as plaintext-int (TLS-only).
- **`PREP`** (General↔Custom per-zone enable, `{idx,value}`) → `verified`.
- **Routed opcodes** — extend the opcode map to `verified`: 3, 4, 5, 6, 9, 13,
  100–103, 107, 200, 201, 204, 208, 215, 218, 219, 220, 221, 234, 400. Map-edit
  `type` taxonomy: 234=ignore-obstacle (`verified`); 215=no-go with shape 1=line/
  2=poly/3=circle (`verified`) + mowing-shape ids 9 (Square), 13 (Heart), 17
  (Cloud), 18 (Rainbow) `verified`; 12/14/15/16 `partial` (inferred from the run).
- **`AI_HUMAN.0`** consent KV → `verified`: `iotuserdata` KV, JSON-string bool,
  bidirectional cascade with `REC.report[1]`. Capture requires `AOP=1` +
  `REC.report[1]=1` + `AI_HUMAN.0=true`.

### Net-new entries

- **Schedule write transport** `SCHDSV3` / `SCHDDV3` / `SCHDIV3` 3-key txn (shared
  `v` ms txn-id) → transport `verified`. **The chunked `SCHDDV3` entry blob is the
  SAME protobuf the integration already decodes via `protocol/schedule_decode.py`
  → `verified` (cite that decoder; format is NOT re-derived).** The lone residual
  `partial`: the `SCHDSV3 {v:<packed int>}` seasonal-slot summary integer
  (18696/32923/65535) — per-day/time bit layout not part of the display decode.
- **`MAP.*` decoded-cache shortcut** (`getDeviceData {keys:["MAP.0",…]}` → concat
  JSON array of maps) → `verified`, with element-type enum (0=mow, 1=path,
  3=spot, 6=cleanPoint, 7=contour, 8=cruise, 10=ignore-obstacle). Caveat
  recorded: written by the app on map view → may be stale; a read-side
  populated-check is a Phase-C step.
- **OSS photos/video** — `userDidOssList {did,type}` (jpg=photos / thumb=videos,
  server returns signed `filepath`), embedded-JPEG COM-marker metadata
  (`{d:[{c,f,x,y,w,h}],o,s,sub}`), `checkDevOssStorage` quota (200 MB), 6-mo
  retention, `addOssNew`/`ossUploaded` client-upload (manual capture) → `verified`.
- **GPS** `dreame-mower-service-app/location/getRecords` → `verified` (WGS84
  decimal-degree strings, 4G-SIM reported, `ATA[2]`-gated, ~4 m accurate,
  `records` = history).
- **`NET`** (wifi current+list, RSSI dBm) and **`REMOTE`** (4G SIM
  activeTime/cardId/expiredTime/leftDays) → `verified`.
- **Message-center** `message-record/list?version=v1` (System+Service+Activity),
  `device-messages` (per-device, carries `source{siid,piid,value}`),
  `share-messages`, `message-record/homestat` (unread), push-prefs
  `message-set`/`message-settings` → `verified`.
- **Tencent live video** `/dreame-third-video/tx/*` cred chain (accesstoken,
  isDevUser, getIdentity, getP2PInfo → XP2P string) → cred-fetch chain
  `verified`; the stream itself `unknown — to capture` (off-relay P2P, no bytes).

### CI vocab sync

Any new `decoded:` / `unit:` vocabulary added must be mirrored into the inventory
schema validator frozensets (`inventory_gen.py` `_DECODED_VALUES` / `_UNIT_VOCAB`)
in the same pass, or the "Inventory schema validation" CI gate goes red.

## §4 `entity-inventory.yaml` updates

For each entity whose write path the sweep resolved (the ~30 read-only/pending
controls in `CONTROL_MODES`), add a `verification` record: **"write path captured
2026-06-09, not yet wired"** + evidence pointer. This bridges the honesty gap —
the code verdict stays read-only (§1) while the SoT records that the path is
known, giving Phase A a ready checklist. No entity *fields* change (sources,
unique_ids untouched); only `verifications:` lists grow + `status.last_seen`
bumps.

## §5 `knowledge-gaps.md`, reference docs, roadmap

**`knowledge-gaps.md`** (regenerable from inventory non-confirmed/open entries):
- *Remove resolved:* SCHDTV3 SET transport, GPS world-coord read, `PATH`
  semantics, `PIN` encoding, photo-metadata source, map-edit write.
- *Add new open:* `SCHDSV3` packed-`v` summary layout, `BAT.power[2]`,
  `LIT.fill`, draw-by-driving zone wire, OTA apply flow, live-camera XP2P stream,
  per-pathway selection, map-edit shape ids 12/14/15/16 (inferred).

**Tier-2 reference docs — reconcile-and-supersede, NOT append-only.** The newer
MITM evidence wins over older docs (`app-api-surface-2026-05-25.md` and others
may carry stale/incorrect claims):
- When a 2026-06-09 finding **contradicts** an older claim → record a
  `status: retracted` verification on the inventory entry (quoting the prior
  claim verbatim, per the fact-discipline rule) AND correct/delete the stale
  prose in the Tier-2 doc.
- When contradiction is only *suspected* (old doc asserts something the sweep
  didn't touch) → do NOT silently trust it; tag `[UNVERIFIED]` and add a
  verification step to knowledge-gaps.
- Known retractions to encode: the message-record **v1-not-v2** supersession
  (`app-api-surface` "marketing System Messages app-push-only / not in RE'd
  surface" is wrong); `app_api_probe` "0 records / not reachable" conclusions the
  sweep overturned; `app_only_settings` entries proven device-writable (e.g.
  `MSG_ALERT` notification types).
- Light touches (no narrative duplication) to: `g2408-protocol.md` (opcode map +
  PRE/CFG write surfaces), `app-api-surface-2026-05-25.md` (new microservice
  endpoints), `cloud-write-reference.md` (the confirmed write dictionary),
  `capture-procedures` / app-capture playbook (cross-link the sweep method).
  Journal gets one dated line citing the new wire-capture.

**New roadmap doc** `docs/research/app-integration-roadmap.md` — records the A→G
sub-project sequence, the **app-path-by-default** principle (use the app's
read/write path unless there's a strong reason not to; keep the old method as
fallback where one exists), the plan/build/plan/build cadence, and per-sub-project
status (Phase 0 = in progress; A–G = planned). This is where the sequencing
decision survives context loss.

### Sub-project roadmap (recorded for downstream cycles, NOT built in Phase 0)

| Phase | Scope | Notes |
|---|---|---|
| A | Writable-settings flip | ~30 read-only/pending controls → writable via PRE indices + CFG keys. Lowest risk, highest payoff. |
| B | Core-control verdict confirm | Flip `_U` buttons (pause/stop/dock/resume + dock-cancel o=13). |
| C | New read sources | GPS getRecords, NET/REMOTE, MAP.* cache, message center. |
| D | Photo & video archive | OSS list + embedded-JPEG metadata + quota + mp4 video. |
| E | Schedule editing | Encode direction + chunked SCHDDV3/IV3/SV3 transport (format already known). |
| F | Map editing | Zone/no-go/ignore-obstacle/rename/split/merge CRUD via routed opcodes. Draw-by-driving (BT) deferred. |
| G | Live camera | Tencent XP2P. Off-relay; may not be feasible in HA. Attempt last. |

## §6 Execution, verification & CI

**Execution shape:** large but mechanical sweep across `inventory.yaml` (10k+
lines), `entity-inventory.yaml`, and several docs. Subagent-driven: partition by
surface group (PRE, CFG keys, routed opcodes, OSS/photos, GPS/NET/REMOTE,
messages, schedule, MAP-cache, video). Subagents **research/draft** their slice
in parallel; a single **serialized apply** pass writes the two shared YAML files
to avoid clobbering. The plan encodes this.

**Verification (doc-integrity, not behavior — there is no behavior change):**
- `tools/inventory/inventory_audit.py` green.
- `tools/wire_census.py` regenerated; wire-census CI guard green.
- inventory schema validator (`inventory_gen.py --validate-only`) green, incl.
  new vocab in the frozensets.
- `error_codes.py` confidence gate green.
- control_mode code-sync test green (proves `CONTROL_MODES` untouched).
- Full vanilla test baseline (1591 passed / 4 skipped) unchanged.
- **Completeness critic:** a final pass confirming every fact line in the two
  findings docs maps to an inventory entry — the explicit "did we capture
  everything" gate (silent omission is the failure mode here).

No live mower verification in Phase 0.
