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
| A2 | Writable PRE General-Mode per-map settings (needs the `d:[...]` envelope fix; efficiency/height/direction/edge/OA/AI-recognition) | planned (next) |
| B | Core-control verdict confirm (pause/stop/dock/resume + cancel-dock-return o=13) | planned |
| C | New read sources (GPS, NET/REMOTE, MAP.* decoded cache, message center) | planned |
| D | Photo & video archive (OSS: userDidOssList + embedded-JPEG metadata + quota + mp4) | planned |
| E | Schedule editing (encode direction + chunked SCHDDV3/SCHDIV3/SCHDSV3 transport; protobuf format already known via `protocol/schedule_decode.py`) | planned |
| F | Map editing (zone/no-go/ignore-obstacle/rename/split/merge CRUD via routed opcodes; draw-by-driving over BT deferred) | planned |
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
