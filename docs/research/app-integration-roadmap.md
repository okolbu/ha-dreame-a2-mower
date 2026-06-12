# App-integration roadmap (post 2026-06-09 MITM)

The 2026-06-09 app-MITM review produced read/write patterns for nearly every
g2408 attribute. Phase 0 captured those facts into `inventory.yaml` /
`entity-inventory.yaml` (the source of truth) and reconciled the Tier-2 docs.
Remaining work is sequenced into feature sub-projects, built one at a time —
each with its own brainstorm → spec → plan → build cycle.

## Guiding principles

- **App-path-by-default.** Use the app's read/write path — the `sendCommand`
  s2.a50 relay (`{m:"s",t:KEY}` CFG writes, `{m:"a",o:N}` routed actions) plus
  the microservice endpoints (OSS, location, message-record, Tencent video) —
  unless there's a strong reason not to. Keep the old method as a fallback where
  one exists; a fallback is optional, not required.
- **Honesty boundary.** A control's `control_mode` (in `control_honesty.py`)
  flips to writable ONLY in the same change that wires AND live-verifies its
  write on the mower, per the corpus-validate rule. A captured-but-unwired write
  path is recorded in `entity-inventory.yaml` verifications, not by flipping the
  verdict.
- **Cadence.** plan/build/plan/build — no monolithic upfront plan. What we learn
  building one sub-project informs the next.
- **Fact discipline.** Every new wire claim carries an inline epistemic tag and
  lands in `inventory.yaml` with a verification record; corrected prior claims
  get a verbatim retraction. (See the repo CLAUDE.md.)

## Sequence

| Phase | Scope | Status |
|---|---|---|
| 0 | Knowledge capture (inventory + docs) | done |
| A1 | Writable CFG "More Settings" (WRP/DND/LOW/BAT/LIT/REC/LANG → ~26 controls) | **done** (v1.0.24a9, 2026-06-10) |
| A2 | Writable PRE General-Mode per-map settings (efficiency/height/direction/edge/OA/AI-recognition/EdgeMaster) | **done** (v1.0.25a1, 2026-06-10). `set_pre` bare-array envelope fix (debunks r=-3); scoped get_pre + PRE↔SETTINGS dual-write. SETTINGS-only fields (cutterPosition/cutterPositionHeight/edgeMowingNum/edgeMowingWalkMode/OA-sensitivity/edgeCuttingAttachment) deferred — see knowledge-gaps. |
| B | Core-control verdict confirm (pause/stop/dock/recharge + resume o=5 + cancel-dock-return o=13) | **done** (v1.0.25a2, 2026-06-10). Added routed_o to pause(4)/stop(3)/dock+recharge(6) — were 80001 no-ops via direct siid:5; added Resume + Cancel-dock-return buttons. lock_bot (o=12) + generate_3dmap (o=10) stay unproven (open questions). |
| C | New read sources (GPS absolute via getRecords → device_tracker; REMOTE/4G-SIM sensors; message-record v1 unread sensor) | **done** (v1.0.25a3, 2026-06-10). NET wifi / MAP.* decoded cache / device-messages-v2 were already done. LOCN position-write retired (kept unscheduled for a future dock-location entity). |
| D | Photo & video archive (canonical userDidOssList; COM-metadata categorize person/patrol/obstacle; VideoArchive thumb+mp4; quota + count sensors; per-type disk caps) | **done** (v1.0.25a4, 2026-06-10). TODOs: type-3 map-icon→photo linkage (uncaptured wire; bytes archived), iotoss request-signing (confirm JWT-header vs body-sign live), mp4 media_source playback. |
| E | Schedule editing (encode direction + chunked SCHDDV3/SCHDIV3/SCHDSV3 transport; protobuf format already known via `protocol/schedule_decode.py`) | **done** (v1.0.25a5, 2026-06-10). write_schedule swapped from the device-ignored SCHEDULE.* KV to the SCHD*V3 chunked routed-action transport (protocol/schedule_action.py); encode_schedule_blob already emitted the verified 3-mode layout (no change). Existing set_schedule_plans service + dashboard card now reach the device. Granular per-run services / calendar-click editing deferred (TODO). |
| F | Map editing (zone/no-go/ignore-obstacle/rename/split/merge CRUD via routed opcodes; draw-by-driving over BT deferred) | **partial done** (v1.0.25a7, 2026-06-12). Part 1: rename zone (o=219) + delete object (o=218: zone/no-go cat 0, ignore-obstacle cat 4) wired via the o=204/o=201 edit transaction + o=200 map-select; services rename_zone / delete_map_object + per-map sensor attrs (renamable_zones, deletable_objects). Part 2: create (o=215 no-go line/poly/circle + mow-shapes 9/12-18, o=234 ignore-obstacle) + split (o=220) + merge (o=221) wired as coordinate-driven services create_no_go_zone / create_ignore_obstacle / create_mow_shape / split_zone / merge_zones (split/merge flagged destructive); coords are map edit-frame metres. DEFERRED: F2b interactive draw card (must first verify the edit-frame↔render-frame coordinate convention — does an o=215 metre point land where projectPoint expects, or is the edit frame reflected/rotated vs the renderer); rename-map/delete-map (uncaptured); draw-by-driving (BT). |
| G | Live camera (Tencent XP2P P2P; off-relay, may be infeasible in HA — attempt last) | planned |

## References

- Captured facts: `custom_components/dreame_a2_mower/inventory.yaml`,
  `custom_components/dreame_a2_mower/entity-inventory.yaml`.
- Condensed evidence: `docs/research/wire-captures/app-settings-sweep-2026-06-09.md`.
- Raw evidence (out-of-tree):
  `/data/claude/homeassistant/dreame-app-findings-2026-06-09-settings-sweep.md`,
  `/data/claude/homeassistant/dreame-app-WRITE-implementation-guide-2026-06-09.md`.
- Open gaps: `docs/research/knowledge-gaps.md`.
- Phase 0 spec/plan: `docs/superpowers/specs/2026-06-09-app-findings-phase0-knowledge-capture-design.md`,
  `docs/superpowers/plans/2026-06-09-app-findings-phase0-knowledge-capture.md`.
