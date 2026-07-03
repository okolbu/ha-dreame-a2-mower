# Refactor v2 — P3 Structural Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute Act III Phase P3 — dissolve the coordinator god-object into the approved layered architecture (`docs/superpowers/specs/2026-07-02-refactor-v2-target-architecture.md` §§1-3), unify the map decode frame, split MowerState into domain containers, and retire the shim layer — with decode semantics byte-identical and the entity surface untouched.

**Architecture:** The target tree in the architecture doc §2 is the destination; this plan sequences the migration. Order (per §9): enablers (test factory, getattr burn-down) → protocol/map unification → transport split → state containers → ingress + domain services → thin coordinator → renames/shim retirement → test-suite structure. Every step: corpus `--diff IDENTICAL`, render golden GREEN (pixel-identical, no re-bless), suite green, audits consciously re-baselined.

**Tech Stack:** Python 3.13 (`/data/claude/homeassistant/.venv-vanilla/bin/python`), pytest, ruff, git.

## Global Constraints

- Branch: `refactor-v2/p3-structure` off main (@ 1d39650a or later). Commit locally per task (multi-commit tasks fine — name each); push at phase wrap.
- **Entity surface frozen:** NO entity_id, unique_id, name, attribute, or service changes this phase (P4 owns those). `tests/integration/test_card_contract.py` and per-map naming tests must stay green UNMODIFIED (moves may retarget patch strings — justify each edit). Dashboards keep working unchanged.
- **Gates per task:** full suite; `ruff check custom_components/`; corpus `python -m tools.replay.corpus_replay --corpus-dir /data/claude/homeassistant/probe/logs --diff /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json` → IDENTICAL; `tests/integration/test_map_render_golden.py` GREEN (never re-bless in P3); `inventory_gen.py --validate-only`; audits (`state_machine_audit`, `entity_inventory_audit`, wire-census) green or re-baselined in-commit with one-line justification.
- **CI-lockstep on EVERY move** (same commit): `tools/entity_source_inventory.py` ENTITY_SOURCE_FILES; `tools/inventory/entity_inventory_audit.py` discovery; `.github/workflows/ci.yml` inventory-touch globs; `ruff.toml` per-file-ignores (dead entries removed); `tools/` probes with `spec_from_file_location` hardcoded paths (dev-box only — fix opportunistically, note if skipped); entity-inventory `class_file:` fields for moved entity sources; CLAUDE.md load-bearing structure sections (coordinator/cloud-client/rendering/entities) rewritten to match reality IN THE SAME TASK that changes each.
- **Behavior preservation:** corpus-validated logic (session begin/end inference, finalize ordering, role classification, decode subtleties) is MOVED verbatim, never reimplemented. A move task that finds a bug reports it; only P2-inherited items explicitly assigned below get fixed in-phase.
- Evidence: architecture doc §2 tree + track-2 autopsies (`/data/claude/homeassistant/refactor-2026-07-02/findings/track-2-architecture.md`) are the split blueprints; P2-inheritance list in `.superpowers/sdd/progress.md` + the P2 final-review output. Re-locate all symbols by grep.
- Stage by explicit path. `.superpowers/sdd/` is gitignored scratch.
- **Go/no-go:** Tasks 3, 6, 8, 9 end with a coordinator checkpoint (controller verifies gates + reads the structural diff-stat before the next task dispatches).

---

## Task 1: Test factory + stub hardening (R-16, T7-7/T7-8, P2-inherit)

**Files:** Create `tests/factories.py`; modify `tests/conftest.py` (root HA stub); create `tests/audit/test_no_new_coordinator_bypass.py`; modify `custom_components/dreame_a2_mower/_settings_writes.py` (remove the Task-6 redundant direct `coord.data =` once the stub is real).

- [ ] `make_coordinator(**overrides)` factory that runs the REAL `DreameA2MowerCoordinator.__init__` against stub hass/entry/clients (mock transports at the client boundary, never `object.__new__`). The integration conftest's dead richer stub (T7-7) is folded in or deleted.
- [ ] Root-stub upgrades (minimal, faithful): `DataUpdateCoordinator.async_set_updated_data` assigns `.data` + notifies listeners; `async_add_listener` returns a working unsubscribe; a tiny fake platform-forward registry sufficient for setup→unload→re-setup tests (T7-20 items 1-3 become assertable — add the three previously-impossible tests: per-timer cancel identity, reload idempotency, no thread leak on reload).
- [ ] Migrate a PILOT set (the coordinator-heavy files: test_finalize_interleavings, test_mqtt_auth_recovery, test_setup_cloud_blip) to the factory; the remaining ~36 `object.__new__` files migrate opportunistically in later tasks' moves. Gate: `test_no_new_coordinator_bypass.py` — census of `object.__new__(DreameA2MowerCoordinator)` pinned to the CURRENT count, must only ever DECREASE (assert count <= recorded baseline, update baseline downward per task).
- [ ] Remove `_settings_writes.py`'s compat direct-assign (P2.6 note) now that the stub notifies; its tests assert via listener path.
- [ ] Gates; commit(s) `refactor(p3): coordinator test factory + listener-aware stub (R-16)`.

## Task 2: String-getattr burn-down (T2-16 pre-step)

**Files:** the 37 production `getattr(coordinator, "_private", ...)` sites (census in track-2 §d2: `_cloud`×9, `_active_map_id`×8, `_wifi_archive_index`×4, `_render_base`×3, …) + their owners.

- [ ] Enumerate with a script (commit it as `tools/probes/getattr_census.py` or inline in the report); replace each with a typed accessor/property on the coordinator (transitional home — the accessor moves WITH its attr during service extraction). Zero string-getattr on private coordinator attrs remains in entity/camera/service layers (grep-gate added to `tests/audit/`).
- [ ] Gates; commit `refactor(p3): typed accessors replace 37 string-getattr sites (T2-16 pre-step)`.

## Task 3: protocol/map unification (T2-17, R-10) — GO/NO-GO after

**Files:** `protocol/map_decoder.py` → `protocol/map/{types,parse,parts,geom,shapes}.py`; `map_render/_geometry.py` (+ new Projection builder); `coordinator/_rendering.py`; root `map_decoder.py` shim retargeted (deleted in Task 10); `www` parity harness.

- [ ] Single frame convention: ALL decoder dataclasses carry raw cloud-mm + `angle`/`shape_type` verbatim; rotation, reflection, bbox/`cloud_*_reflect` derivation move into a render-side `Projection` builder (`map_render/_geometry.py` owns it — architecture §2). One `Zone(kind=…)` replaces ExclusionZone/SpotZone (+MowingZone if field-compatible — track-2 d3 scope). `DECORATIVE_SHAPE_TYPES` moves to `protocol/map/shapes.py` (cite inventory § shapeType); PNG masks stay in render. The dual `points`/`points_m` twin dies — `points_m` becomes a derivation, map-editor `editable_objects` output byte-identical (its tests pin it).
- [ ] Proof obligations: render golden GREEN un-re-blessed (pixel-identical by construction); corpus IDENTICAL; Python↔JS parity test extended to the unified Zone; `apply_session_geometry`/session replay unchanged (session tests).
- [ ] Lockstep: 29 test files import via the map_decoder shim — retarget the shim to the new package (1 line) so they keep passing; their import rewrite is Task 10. CLAUDE.md § decode→render frame contract rewritten.
- [ ] Gates; commits staged (types → parse split → transform move → zone unify). **CHECKPOINT.**

## Task 4: const inversion + protocol output dataclasses (R-30, R-29a)

- [ ] `const.py` stops importing `mower.error_codes` — event-type constants live in const (or a leaf `events_const.py`); `mower/error_codes.py` imports const; `event.py`/`device_trigger.py` re-pointed. Import-graph gate: add `tests/audit/test_layer_imports.py` asserting protocol/ imports nothing from state/domain/entities/render layers and const imports no domain module (AST-based; this is the durable back-edge gate — seed with the layer map from architecture §1).
- [ ] `SettingsRoot`/`ScheduleData`/`SchedulePlan`/`ScheduleSlot`/`MowPathData` move from root `cloud_state.py` into `protocol/` (settings.py/m_path.py/schedule.py own their outputs); `cloud_state.py` keeps the CloudState aggregate only (its composition moves in Task 6).
- [ ] Gates; commit.

## Task 5: transport split (R-31, T2-6)

**Files:** `cloud_client/_fetchers.py` (1,278) → `cloud_client/{_state_fetch,_device_fetch,_messages,_media,_ota}.py` per autopsy #2; `set_cfg`/`set_pre`/`trigger_firmware_update` move OUT to `coordinator/_writes.py`'s realm (staging for Task 8's writes service — they land in the writes module directly if Task 8 hasn't run; sequence them so they move ONCE: this task splits fetch families only and leaves the three writers in a new `cloud_client/_writers.py`; Task 8 absorbs it).

- [ ] Fetchers return protocol types; `fetch_full_cloud_state` no longer CONSTRUCTS CloudState (returns the parts; composition goes to the coordinator/cloud-state refresh until Task 6 moves it to state/) — keep the 235-LOC method's DECOMPOSITION for Task 8; here only the family split + CloudState-construction extraction.
- [ ] CLAUDE.md cloud-client table rewritten; mixin-assembly updated; OTA write family gains WriteResult (P2-inherit) while it moves.
- [ ] Gates; commit(s).

## Task 6: state containers (T2-15, R-29b, R-33a) — GO/NO-GO after

**Files:** `mower/state.py` (164 fields) → `state/` package: `containers.py` (8 frozen sub-dataclasses: Identity, Settings, Telemetry, Consumables, Connectivity, SessionRefs, OtaState, Messages — seams per track-2 d1: wire-source domains visible in property_mapping + cfg_to_state_updates), `mower_state.py` (composition), `snapshot.py`/`machine.py` (moves from mower/), `cloud_state.py` (aggregate + composition from Task 5's parts), `apply.py` (from coordinator/_property_apply.py, pure, header already clean).

- [ ] Transition mechanics: MowerState exposes delegating read-properties for every field (mechanically generated, one per field, marked `# transitional — direct container access preferred`) so the ~59 prod `.data.<field>` sites and entity descriptors keep working unchanged this phase; writers go through container-scoped `replace_*` helpers used by apply.py + the refresh ports. dataclasses.asdict/astuple consumers (diagnostics, _snapshot.py string readers, archive payloads) are enumerated by grep FIRST and adapted; the session-archive on-disk format MAY change (user ruling: feature-complete result; deploy-order lesson applies — note for wrap).
- [ ] `mower/property_mapping.py` moves to `protocol/` (wire knowledge; architecture §2).
- [ ] state_machine_audit WILL re-baseline (field homes change) — one conscious re-baseline commit with the mapping table in its message. Corpus IDENTICAL is the semantic proof (apply.py + machine.py drive the digest).
- [ ] Gates; commits staged (package scaffold → containers+delegation → apply/machine moves → audit re-baseline). **CHECKPOINT.**

## Task 7: ingress funnel (autopsy #3)

**Files:** `coordinator/_mqtt_handlers.py` (1,274) → `domain/ingress.py` (thin routing; the paho-purity from P2.9 preserved) + `domain/session/lifecycle_events.py` (pure edge detectors from `_on_state_update`'s 375 LOC) + `domain/session/signals.py` (session-type capture); property dispatch table-driven from `protocol/property_mapping.py`.

- [ ] The begin/end inference and lifecycle-edge logic move VERBATIM (corpus-validated); `_on_state_update` decomposes along the autopsy's seams into named pure functions + one orchestrator. s2p2 resolver + heartbeat paths keep P2.8/P2.9 semantics (their tests pin).
- [ ] Gates (corpus gate is the proof); commit(s).

## Task 8: domain services extraction (T2-1 dissolution, autopsies #4/#5/#7/#10) — GO/NO-GO after

**Files:** `domain/session/{finalize,persistence,replay}.py` (from `_session.py` + `_lidar_oss.py` §1 + `session_card.py` contents — killing the T2-13 misnomer); `domain/writes/` (absorbs `_writes.py` families + Task 5's `_writers.py`; **P2-inherits fixed here:** write_setting per-field revert, AI-bit bare assigns); `domain/media/gallery.py`; `domain/wifi/service.py` (+ `_lidar_oss` wifi cache consolidation); `domain/lidar/service.py`; `domain/{notifications,faults,ota,device_sync,gps}.py`; `services/` package for HA services (registration + per-domain handlers + `debug.py`).

- [ ] Each service owns its attrs (moved from `_CoreMixin.__init__` — this is how T2-16's verdict lands: no standalone bundling, attrs move WITH their service); entities reach services via coordinator properties (Task 2's accessors relocate). Finalize/latch/dock-wait logic moves verbatim under the interleaving tests.
- [ ] rc=5 backoff escalation + on_unload canceller registry (P2-inherits) implemented in the lifecycle-owning service.
- [ ] Multi-commit by service; each commit gates. **CHECKPOINT.**

## Task 9: thin coordinator (autopsy #7) — GO/NO-GO after

- [ ] `coordinator/` package → single `coordinator.py` composition root (target ≤400 LOC, recorded exception allowed): constructs transports+services, owns the spine (`data`, `cloud_state`, `state_machine`, `live_map`), `_async_update_data` composes per-service refresh slices (the 450-LOC poll body dissolves along autopsy #7 seams). Public re-exports preserved via `coordinator/__init__` → module swap (import sites unchanged until Task 10).
- [ ] CLAUDE.md coordinator section REWRITTEN (the "package is the contract / don't bring back coordinator.py" rule is superseded by the approved architecture — say so explicitly, citing the architecture doc).
- [ ] Gates; commits. **CHECKPOINT.**

## Task 10: renames, shim retirement, import rewrite (R-34, T2-13)

- [ ] Delete ALL remaining root shims (10 tests-only + 4 prod + map_decoder retarget from Task 3): rewrite the 19 prod import sites + ~59 test-file imports to canonical paths. `mqtt_client.py` → `transport/mqtt.py`; `cloud_client/` → `transport/cloud/`; naming collisions resolved (root `cloud_state.py` content now lives in state/; `session_card.py` gone via Task 8; `map_render/` → `render/` only if cheap — optional, skip if churn>value, record decision).
- [ ] Lockstep sweep (ENTITY_SOURCE_FILES, audit discovery, ci globs, ruff.toml, entity-inventory class_file fields, CLAUDE.md).
- [ ] Gates + `pytest --collect-only` count unchanged; commit(s).

## Task 11: test-suite structure (T7-29, T7-13-residue, R-66-deferred)

- [ ] Split `tests/integration/test_coordinator.py` (3,465 lines/142 tests) along the new service boundaries; dedupe the 4 identical www harness shells (parametrized runner); merge the two near-duplicate invariant pairs (P1.5 note); add T7-11's real paint-order assertion; fix `test_fake_coord.py` stale docstring + error-sensor dup-slug dedup (P2 LOWs — slug list deduped, test).
- [ ] Gates; commit.

## Task 12: phase wrap

- [ ] Full battery (suite, ruff, validate-only, findings_fold, corpus IDENTICAL, render golden GREEN, collect-only, audits); architecture-conformance spot-check: `tests/audit/test_layer_imports.py` green = no back-edges; module-size census vs the ≤400 cap (record exceptions in the architecture doc's committed copy).
- [ ] ff-merge → push → `release.sh` (release notes: internal restructure, no user-visible changes expected — flag the archive-format change if Task 6 made one, with the deploy-order note) → HACS → restart → live verify (entry loaded, entity count ±0, error log clean, one write round-trip [e.g. a settings toggle] to prove the writes service, camera renders).
- [ ] Ledger + working-dir README + memory update + branch delete.

## Self-review record

- **Coverage:** R-8/R-10/R-16/R-29/R-30/R-31/R-32/R-33/R-34/R-56 → Tasks 1-10; T7-29/R-66-deferred → Task 11; every P2-inherit assigned (per-field revert+AI-bit → T8, rc=5 backoff+canceller registry → T8, OTA WriteResult → T5, class_file paths → T10, factory/stub → T1, dup-slug+docstring → T11). Program-level rain-edge decision deliberately NOT in P3 (user decision, park in TODO). R-28/renames/contract rewrites are P4.
- **Placeholders:** none; split blueprints live in the cited autopsies rather than restated.
- **Consistency:** writers move once (T5 stages, T8 absorbs); map_decoder shim retargeted T3, deleted T10; corpus/golden gates identical strings throughout.
