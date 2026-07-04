# Refactor v2 — P5 Dashboard Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute Act III Phase P5 — ship the dashboard as a product: a registered Lovelace **strategy** that generates views from the live entity registry (no drift possible), eliminate the backend's dependency on dashboard-installed helper entities, harden the bundled cards, and cut the live instance over from the SCP-deployed YAML to the strategy.

**Architecture:** Per `docs/superpowers/specs/2026-07-02-refactor-v2-target-architecture.md` §5. Track-6's feasibility review (`/data/claude/homeassistant/refactor-2026-07-02/findings/track-6-dashboard.md`) is the SoT: the registered-strategy path is VIABLE, no hard blocker; plotly charts degrade to optional-if-installed, atomic-calendar → native calendar (user-approved OQ-4).

**Tech Stack:** Python 3.13 (`/data/claude/homeassistant/.venv-vanilla/bin/python`), pytest, node (card + strategy harness tests), ruff, HA MCP (live dashboard/registry), git.

## Global Constraints

- Branch: `refactor-v2/p5-dashboard` off main (@ v1.0.32a1 / 2e160860 or later). Commit locally per task; push at phase wrap.
- **Proof model (READ — different from P1–P4):** corpus IDENTICAL is still a GUARD (any backend change in P5.1 must not touch decode), and the pytest suite gates the backend. But the STRATEGY + CARD JS have no corpus/suite coverage — their proof is (a) **node-harness tests** (run the strategy generator + card render functions in node, assert the generated Lovelace config is valid and references only real entities; assert card render output), and (b) **LIVE browser render**, which the controller CANNOT fully auto-verify — the cutover task explicitly hands the user a "please eyeball" checkpoint. Do not claim visual correctness from node tests alone.
- Backend gates per task touching Python: full suite; ruff `custom_components/`; corpus IDENTICAL (`python -m tools.replay.corpus_replay --corpus-dir /data/claude/homeassistant/probe/logs --diff /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json`); render golden; tests/audit; inventory --validate-only.
- Frontend gates: `node --check` on every touched .js; the node-harness tests (extend the existing `tests/www/` node harness pattern — grep it); a strategy-generates-valid-config test.
- Entity-inventory lockstep: P5.1 ADDS backend entities (the ex-helper toggles) → new entity-inventory rows + entity-inventory-coverage + state_machine_audit expectations in the same commit. entity_id derives from name slug (v2 naming, has_entity_name).
- Evidence: track-6 T6-ids + register R-13/R-14/R-15/R-48/R-54/R-55/R-65. The P4 ledger's "P5-INPUT: 19 dashboard.yaml refs to renamed ids" — the strategy generates from the registry so it uses CURRENT ids automatically (no manual repoint), but the card-grouping manifest must use v2 unique_id suffixes / current entity_ids.
- Stage by explicit path. `.superpowers/sdd/` is gitignored scratch. Live work via HA MCP + `secrets/ha-credentials.txt` in-situ.
- **frontend-design skill:** load `frontend-design:frontend-design` before authoring the strategy views / card hygiene (the dashboard is a shippable UI product — design quality matters).

---

## Task 1: Backend helper elimination (R-15 / T6-18) — the enabler

The strategy can't ship helper `input_boolean`s if the BACKEND reads them. `camera/wifi.py` reads `input_boolean.dreame_a2_mower_wifi_flip_x/y` + `wifi_show_base`; there are also `input_number` heatmap-opacity / lidar-view-tilt reads (grep). Replace each backend helper-read with an integration-owned entity.

**Files:** `camera/wifi.py`, `camera/lidar.py` (the helper-id constants + reads); NEW switch/number descriptors for the ex-helpers (wifi_flip_x, wifi_flip_y, wifi_show_base → switches; heatmap_opacity, lidar_view_tilt → numbers) in `entities/switch/*` + `number.py`; `entity-inventory.yaml` rows; `strings.json`.

- [ ] Grep ALL backend reads of `input_boolean.dreame_a2_mower_*` / `input_number.dreame_a2_mower_*` (camera/wifi.py, camera/lidar.py, anywhere). For each: add an integration entity (switch for booleans, number for the opacity/tilt) with the same semantics, make the camera read the integration entity's state instead of the external helper. These are UI-preference toggles → CONFIG category, local-only (no wire write — they drive render params). TDD: the camera render reads the new entity; a test pins flip_x on/off changes the render orientation.
- [ ] The old external helper ids (`input_boolean.dreame_a2_mower_wifi_show_base` etc — currently user-created helpers on the live instance) become unused → note for the live cutover (Task 5 removes them from the live config OR they're just ignored). The integration no longer depends on them.
- [ ] Gates (corpus IDENTICAL — render-param toggles don't touch decode; suite; audits re-baseline for the new entities). Commit `feat(p5): backend owns its render-preference toggles — no dashboard-installed helpers (R-15)`.

## Task 2: Card hygiene pass (R-54)

**Files:** the 9 `www/*.js` cards + a NEW `www/_dreame-card-core.js` shared module (banner/registration/lightbox/missing-entity UX).

- [ ] Load `frontend-design:frontend-design`. Then: (a) shared `_dreame-card-core.js` — the CARD_VERSION banner helper, a guarded `defineCard(name, cls)` wrapper (no double-define — T6-8), a shared lightbox/overlay (dedupe across replay/lidar/photo cards — T6-17), a consistent missing-entity render (T6-20); (b) every card: guard `customElements.define`, take its entity via config (`config.entity`) instead of hardcoded entity_ids (T6-10 — so the strategy passes the right entity), add `schema_version` awareness on consumed attrs (T6-9 cache-bust coherence); (c) delete the dead `window.DreameMapCore` global (T6-12); (d) the multi-select card light-DOM → shadow-DOM consistency (T6-19) if cheap, else note.
- [ ] Node-harness: extend `tests/www/` — each card's render fn runs in node, asserts no throw on missing entity, asserts the guarded define. `node --check` all.
- [ ] CARD_VERSION sync (R-53, already fixed in P2.10 release.sh) — confirm the new shared banner is covered by the release.sh pattern.
- [ ] Gates (frontend: node checks + harness; no backend change so suite unaffected but run it). Commit(s) `feat(p5): card hygiene — shared core, guarded defines, config-driven entities (R-54)`.

## Task 3: The dashboard strategy (the centerpiece) — R-13/R-14

**Files:** NEW `www/dreame-a2-strategy.js` (the registered strategy) + a card-grouping manifest (baked into the strategy JS OR published by the backend — DECIDE per track-6: entity-inventory is CI-side not shipped, so bake a machine-readable grouping into the strategy JS, sourced/validated against entity-inventory at build/test time); `__init__.py` / resource registration (register the strategy resource).

- [ ] The strategy (`custom:dreame-a2-mower`): generate views from `hass.states` / the entity registry filtered to the dreame device(s). Group entities into views/cards via the manifest (Overview / Maps&Zones / Schedule / Sessions&History / Settings / Diagnostics / Photos — track-6's 7-tab model). Per-map views generated per registered map device (kills the hardcoded 2-map assumption R-48). The `attribute: current_map_id` conditionals (R-13) become state-compare conditionals the generator emits. The strategy references ONLY entities that exist in the registry (kills R-14 dead refs + the 3 phantom services — a generated dashboard can't reference a nonexistent entity/service).
- [ ] Degrade paths (OQ-4): probe `hass` for `custom:plotly-graph-card` resource → include the battery/wifi session charts only if present, else a simpler native history-graph fallback; calendar view uses the native `calendar` card (not atomic-calendar-revive).
- [ ] Dev-only content (R-55): MPOS/novel-log/experimental surfaces included in the generated views ONLY when `experimental_features` is on (probe the option or the entities' existence — since gated entities don't exist when off, generating from the registry naturally omits them; verify).
- [ ] Node-harness test: run the strategy's `generate()` against a captured `hass` fixture (states + registry snapshot — capture one from the live instance or synthesize from entity-inventory), assert the output is a valid Lovelace config (views/cards structure), assert every referenced entity_id exists in the fixture registry (no dead refs), assert per-map views scale (test with 1-map and 3-map fixtures). THIS is the strategy's proof.
- [ ] Gates: node checks + the generate-valid-config test. Commit `feat(p5): registered dashboard strategy — registry-generated views, no drift (R-13/R-14/R-48)`.

## Task 4: Content purge + resource consolidation (R-14/R-55/R-48/R-65)

**Files:** `dashboards/mower/` (delete the 2 .bak files + eventually the YAML), the resource registration, README/docs.

- [ ] Delete the 2 tracked `.bak` dashboard snapshots (R-48/T6-13). The 2020-line `dashboards/mower/dashboard.yaml` — KEEP in-repo as a reference/fallback for now but mark it superseded by the strategy (or delete if the strategy fully replaces it — DECIDE; the live cutover in Task 5 switches away from it regardless). Remove the phantom-service references (R-14) — moot if the YAML is retired, but if kept as fallback, purge them.
- [ ] Resource consolidation (T6-22/R-65): the strategy JS + cards register via ONE resource path; document the fresh-install resource registration (how a public user adds the strategy — one dashboard with `strategy: {type: custom:dreame-a2-mower}` + the resource). Remove the ad-hoc `?v=` duplicates from the live resource list (Task 5).
- [ ] README: document the strategy dashboard install (replaces the SCP-deploy instructions). The faults/attention view (R-65/T6-23) → `docs/TODO.md` as a post-P5 feature idea, NOT built here.
- [ ] Gates; commit `feat(p5): retire dashboard .baks + document strategy install (R-48/R-55/R-65)`.

## Task 5: Live cutover + phase wrap — USER EYEBALL CHECKPOINT

- [ ] Full backend gate battery (suite, ruff, corpus IDENTICAL, render golden, audits, inventory validate) + all node checks/harness.
- [ ] ff-merge → push → `release.sh` (release notes: dashboard is now a registered strategy; existing SCP-YAML users switch to the strategy dashboard; backend render-toggles are now integration switches/numbers — the old input_boolean/input_number helpers can be deleted).
- [ ] Live deploy: HACS download + restart. Register the strategy resource on the live instance (via the host `/config/lovelace.yaml` resources or the storage resource registry — match the existing mechanism; the SCP-deploy memory `reference_ha_dashboard_deploy` has the technique). Create a NEW dashboard using the strategy (or convert the existing mower dashboard to `strategy: {type: custom:dreame-a2-mower}`).
- [ ] **USER EYEBALL CHECKPOINT (load-bearing — controller cannot auto-verify render):** deploy the strategy dashboard, confirm via MCP that (a) the integration is loaded + no new errors, (b) the strategy resource is registered, (c) the generated dashboard's referenced entities all resolve. Then STOP and report to the user: the strategy dashboard is live; please open it in the browser and confirm the views render (maps, cameras, settings tabs, per-map views, no broken cards). List what to check. Do NOT claim the dashboard "renders correctly" — only that it deployed and its config is structurally valid.
- [ ] After user confirms render (or fixes any reported issue): remove the now-unused live helper entities (input_boolean.dreame_a2_mower_wifi_flip_x/y/show_base + the input_numbers) via MCP; clean the ad-hoc `?v=` resource duplicates. Retire the SCP YAML (back it up first).
- [ ] Ledger + working-dir README + memory update + branch delete.

---

## Self-review record

- **Register coverage (P5-tagged):** R-15→T1, R-54→T2, R-13/R-14→T3, R-48/R-55/R-65→T4, R-12(OTA rows, moot — entities gated in P4)→T3-generation, R-53(CARD_VERSION, done P2.10)→T2-confirm. R-65 faults-view → TODO.md (not built). R-11 (floor0) already fixed live in P4.
- **Proof-model honesty:** the strategy/card JS proof is node-harness (generates-valid-config + card-render-no-throw) + the LIVE user-eyeball checkpoint in Task 5. This is explicitly weaker than the corpus gate that carried P1–P4; the plan does not claim visual correctness from tooling. The backend change (P5.1) keeps full suite + corpus IDENTICAL coverage.
- **Ordering:** helper-elimination (1) unblocks the strategy shipping helper-free; card hygiene (2) makes cards config-driven so the strategy (3) can pass entities; content purge (4); live cutover (5) last with the user checkpoint.
- **Placeholder scan:** the card-grouping (which entity → which tab/card) is authored in Task 3's manifest from track-6's 7-tab model + the current dashboard.yaml's grouping as reference; not restated here line-by-line.
