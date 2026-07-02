# Full Refactor → v2.0.0 — Design

**Date:** 2026-07-02 · **Status:** approved design, pre-plan
**Baseline:** `main` at v1.0.31a5 (~41k LOC Python / 174 files, ~4.8k LOC JS cards, 2,020-line SCP-deployed dashboard, 348 test files)
**Predecessor:** the 2026-06-13 cleanup/refactor (completed through v1.0.27a9; archived at `OLD/ha-dreame-a2-mower-docs/superpowers/refactor-2026-06-13/`). 281 commits have landed since.

## Goal

Take the integration from "feature-complete, grown over hundreds of iterations" to
**production-ready with explicit carveouts for the remaining backend uncertainties**, and
ship the dashboard as part of the product. Three co-equal objectives:

1. **Long-term maintainability** — top-down layered architecture (the project has only ever
   had bottom-up passes), small focused modules, shims gone.
2. **Public/community-release readiness** — installable and usable by any g2408 owner, not
   just this dev instance.
3. **Correctness/robustness hardening** — failure modes, lifecycle, write honesty.

Shrinking LOC is *not* a goal in itself. Removing code built on **superseded backend
understanding** is: backend understanding reversed 180° several times (BT-transport era,
pre-CloudState caching, FAULT_CODES→catalog, "PRE absent", s2p2=28-off-dock, MISTA,
single-map era, pre-CRUISED patrol, …) and reimplementations likely left the old paths
behind.

## Decisions record (user-approved 2026-07-02)

| Decision | Ruling |
|---|---|
| Compatibility | **Break freely** — last cheap moment pre-public. Entity ids, service names/schemas, attribute contracts, archive formats, import shims: all breakable. |
| Previously deferred items (MowerState split, coordinator attr-bundling, decoder/render untangle) | **Back in scope, judged fresh** against today's code — no pre-commitment either way. |
| Dashboard | **Ship with the integration** as a registered dashboard strategy (fallback: generated YAML + install service). SCP workflow retires. |
| Unverified-backend features | **One experimental opt-in gate**, default off. |
| Landing version | **v2.0.0**. |
| Corpus-replay harness | **Approved as P0 centerpiece.** |
| Data loss | Recorder history / attribute continuity loss is acceptable. Disk-persisted artifacts (session archives, photos, LiDAR/WiFi images) **must survive**. Session archives may be **rewritten to a new format** provided the result is feature-complete; sessions are rebuildable from raw MQTT logs (`tools/session/rebuild_session.py`) as a backstop. |

## Shape: three acts

**Act I — multi-agent review** of today's codebase → findings register (severity-ranked).
**Act II — target architecture document** — the top-down pass, written from the findings.
**Act III — gated migration phases** toward that target, one branch per phase, per-phase
release + live-HA validation.

Review artifacts live out-of-tree at `/data/claude/homeassistant/refactor-2026-07-02/`;
only this spec and the implementation plan are committed.

## Evidence sources & verification rule

In trust order:

1. `inventory.yaml` / `entity-inventory.yaml` / gated research docs — canonical backend truth.
2. Code + full git history (281 commits since last refactor; older history for archaeology).
3. Probe corpus (`/data/claude/homeassistant/probe/logs/`, ~3 months / 388 MB raw MQTT) +
   MITM captures (API + MQTT, incl. a **full app-initiated OTA transcript**).
4. Live HA via MCP — ground truth for entity surface and dashboard.
5. `secrets/` — used **in-situ only**; never copied out of those files.

**Verification rule:** no code is declared dead or wrong without discharged evidence
(grep, corpus query, MITM excerpt, or live probe). "Looks obsolete" is a hypothesis.
Wire claims are corpus-validated across runs, never from a single sample.

## Negative-knowledge register (anti-resurrection)

Debunked information has repeatedly crept back into docs/code. A refactor that has agents
reading old git history amplifies that risk. Countermeasures, all mandatory:

- The archaeology track produces a canonical **debunked-claims register** in the gated docs
  (as a `debunked:`/register surface compatible with the existing findings-fold-check CI
  gate): every overturned claim + the evidence that killed it.
- Every review/implementation agent receives the register as a **blocklist** in its prompt.
- Tombstones for deleted code cite the register entry — they never restate the old claim.
- **Explicit gaps stay gaps.** Missing knowledge is recorded as "unknown — see
  knowledge-gaps", never back-filled from pre-reversal historical material. Nothing enters
  docs/code from history unless corroborated by current inventory or fresh corpus/MITM
  evidence.

## Act I — review dimensions

Seven parallel tracks, each ending in a findings doc with per-finding evidence:

1. **Assumption archaeology** — for each known reversal, walk history, find the code written
   under the old belief, verify whether it died. Output: dead-code findings + the debunked
   register.
2. **Architecture & layering** — coupling map, module sizes (>400 LOC hotspots:
   `entities/sensor/device.py` 1,739; `cloud_client/_fetchers.py`, `coordinator/_mqtt_handlers.py`,
   `coordinator/_session.py`, `services.py` ≥1,100), the leftover shim layer, back-edges.
   Re-judges the three resurrected deferred items with rationale.
3. **Correctness & lifecycle** — threading (paho thread boundary), reload/unload, failure
   modes, write honesty end-to-end, recurring race families (camera token, finalize).
4. **Public-release readiness** — config flow (credential UX, re-auth, region), single-user
   assumptions, hardcoded personal values, secrets hygiene, HACS/store requirements,
   graceful behavior on other people's devices/maps.
5. **Entity surface** — all ~86 entity classes judged keep / rename-to-ideal /
   demote-diagnostic / gate-experimental / delete. Output: the new canonical entity table
   (v2 names — break-freely applies).
6. **Dashboard & cards** — the YAML + JS cards reviewed as a shippable product: what the
   strategy generates, what each card needs, card-quality issues.
7. **Test-suite quality** — mock-masking (SimpleNamespace lesson), dead fixtures, shallow
   tests, coverage gaps vs tracks 1–3 findings.

Synthesis gate: findings register merged, deduped, severity-ranked; conflicts resolved by
the verification rule before Act II is written.

## Act II — target architecture principles

The architecture doc is a review deliverable, but it must land within these principles:

- **Strict layering:** pure/stateless *protocol decode* ← *transport* (MQTT client, cloud
  RPC/OSS) ← *state* (one container per fact, one name per fact) ← *domain services*
  (session, map, wifi, faults, OTA, photos, schedule) ← *descriptor-driven entity layer* ←
  *presentation* (render, cards, dashboard strategy). No back-edges.
- **One write path** returning an honest `WriteResult`; services/entities surface rejection.
- No module >~400 LOC without recorded cause.
- **Every re-export shim deleted** (root `sensor_*/select_*/switch_*/map_decoder/_camera_*`
  layer from the 3b/3c moves).
- The experimental gate is an architectural feature, not an afterthought (see below).
- Deleted dead-assumption code leaves a one-line tombstone citing the debunked register.

## Safety net (P0): corpus-replay harness + rewritten contracts

- **Corpus-replay harness:** replay probe-log JSONL through decode→state→(headless render)
  and snapshot golden outputs. Any structural phase must replay byte-identical
  (render goldens re-blessed deliberately when render intentionally changes).
  This converts "break freely" from faith into measurement.
- **Contract tests are rewritten, not preserved:** external surfaces break by design, so the
  old card-contract/public-API tests are replaced with contracts against the *new intended*
  surface, written before the breaking phase lands.
- CI runs the full suite (`.venv-vanilla`, py3.13; exact green baseline recorded in P0);
  all existing lockstep gates (inventory-touch, state_machine_audit, entity-inventory
  coverage, wire-census, control-honesty, per-map naming, canonical-doc regen,
  findings-fold-check) stay green or are consciously re-baselined per phase.

## Act III — migration phases

Refined by Act I findings; ordering fixed:

| Phase | Content | Gate |
|---|---|---|
| **P0** | Safety net: corpus harness, CI full suite, new-contract scaffolding | harness green on baseline |
| **P1** | Dead-code purge (archaeology findings) + debunked register lands | evidence per deletion; suite green |
| **P2** | Correctness/lifecycle fixes | targeted TDD per fix |
| **P3** | Structural restructure toward Act II target (state containers, coordinator, decoder/render, services, entity packaging — as judged) | corpus replay identical; suite; per-sub-phase go/no-go |
| **P4** | Entity-surface break: v2 names, experimental gate wired, live registry cleanup, archive-format rewrite if the review calls for it | new contract tests; live-HA A/B; persisted artifacts verified intact |
| **P5** | Dashboard productization: strategy + cards | strategy renders on live HA; SCP dashboard retired |
| **P6** | Release readiness: config flow UX, README/docs, HACS metadata, **v2.0.0** | fresh-install walkthrough on live HA |

Per-phase machinery (proven in June): one branch per phase; full suite before merge;
`tools/release/release.sh` for bump+tag+push+GitHub-Release (HACS reads Releases; respect
the alpha digit-count ladder); deploy to live HA; verify via MCP + WS API; go/no-go.
Stopping after any phase leaves the repo strictly better than baseline.

## Dashboard productization (P5)

A **registered dashboard strategy** (`custom:dreame-a2-mower`): the integration generates
views from the live entity registry + `CONTROL_MODES`/entity-inventory, so the dashboard
cannot drift from the entity surface, per-map views appear automatically, and a public
user gets the full UI by creating one dashboard with one strategy line. The bundled JS
cards (already shipped via `www/` + resource registration) are its building blocks.
The personal SCP-deployed YAML at `/config/dashboards/mower/` retires; the live instance
switches to the strategy.

**Fallback** (decided by review track 6 if the strategy fights the heavy custom cards):
bundled generated YAML + an "install dashboard" service.

## Experimental gate

One config-entry option ("Enable experimental features"), default **off**.

- Descriptors gain `experimental: True` → entities not created when the option is off
  (and `entity_registry_enabled_default=False` when on); gated services raise a clear
  error when off.
- Docs list every gated feature and **what evidence promotes it**.
- **Carveout taxonomy** (initial population from review track 5):
  - *Speculative* — e.g. MPOS (frame/units unverified), patrol o=223 remnants.
  - *Wire-verified, client-unexercised* — e.g. OTA install: the app-initiated OTA MITM
    transcript verifies the wire format byte-level; only "initiated from our client" is
    unproven. The review diffs our built envelope against the transcript byte-for-byte,
    which may promote it without waiting for the next firmware.
  - *Fail-closed pending backend* — e.g. Track B obstacle-photo signer (UNVERIFIED).
  - *Accepted-but-no-effect* (op=10 3dmap, op=12 lock) — candidates for deletion rather
    than gating; review decides.

## Data & persistence policy

- Recorder/long-term-statistics continuity: **expendable** (user ruling).
- Disk-persisted artifacts — session archives, photos, LiDAR/WiFi images, `index.json` —
  **must survive** every phase. P4 verifies them intact on live HA.
- The session-archive format may be rewritten if the review recommends it; requirement is
  feature-completeness of the result, with `rebuild_session.py` + the raw MQTT corpus as
  the rebuild backstop. If the format changes, the archive-index backfill/deploy-ordering
  lessons apply (new code deploys before old rewrites).

## Non-goals

- No backend changes (someone else's API/MQTT) and no new feature work during the program
  (feature ideas found in review go to `docs/TODO.md`).
- No recorder/statistics migration code, no `async_migrate_entry` machinery beyond what a
  public install genuinely needs — reinstall remains acceptable for the dev instance.
- No rewrite-from-scratch of the core: the corpus-validated behavioral subtleties in
  session/finalize/state code are preserved through restructure, not reimplemented.

## Risks

- **Scale:** multi-session program (June's was). Mitigated by per-phase shippability.
- **Debunked-info resurrection** during history mining — mitigated by the register/blocklist.
- **Strategy-dashboard unknowns** — first time shipping one; fallback path defined.
- **Concurrent-process commits:** a second process has previously committed with `add -A`
  in this repo — all work on branches, staging by explicit path.
- **Live HA is the only real device** — destructive verification (fresh-install walkthrough)
  is scheduled, snapshot/backup first.
