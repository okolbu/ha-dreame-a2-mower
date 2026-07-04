# Refactor v2 — P4 Entity Surface & Experimental Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute Act III Phase P4 — reshape the entity surface to its ideal v2 form (renames, metadata fixes, deletions), add the experimental opt-in gate, rebuild translations, rewrite contract tests to the new surface, and clean the live registry. This is the first phase that INTENTIONALLY breaks entity_ids (break-freely ruling).

**Architecture:** Per `docs/superpowers/specs/2026-07-02-refactor-v2-target-architecture.md` §4 (entity layer) + §6 (experimental gate). The draft v2 canonical entity table in `/data/claude/homeassistant/refactor-2026-07-02/findings/track-5-entity-surface.md` is the SoT for verdicts.

**Tech Stack:** Python 3.13 (`/data/claude/homeassistant/.venv-vanilla/bin/python`), pytest, ruff, HA MCP (live registry), git.

## Global Constraints

- Branch: `refactor-v2/p4-entity-surface` off main (@ 263c585c / v1.0.31a8 or later). Commit locally per task; push at phase wrap.
- Venv: `/data/claude/homeassistant/.venv-vanilla/bin/python` from repo root. Baseline: 2798 passed / 1 skipped / 1 xfailed.
- **Corpus GUARD (every task):** `python -m tools.replay.corpus_replay --corpus-dir /data/claude/homeassistant/probe/logs --diff /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json` → IDENTICAL. P4 is entity-layer only; it must NOT touch the decode/state pipeline. Corpus IDENTICAL is the guard that it didn't.
- `ruff check custom_components/` clean; render golden green; layer/census/getattr gates green.
- **Entity-inventory lockstep (CLAUDE.md fact-discipline):** every entity rename/delete/gate/metadata change updates its `entity-inventory.yaml` row IN THE SAME COMMIT (+ `inventory_gen.py --validate-only`). The entity-inventory-coverage audit + state_machine_audit expectations update in lockstep too. This is the CI SoT for the 86 entity classes.
- **Entity surface CHANGES this phase (the point) — so the OLD contract tests get REWRITTEN, not preserved.** `test_card_contract.py` + `test_per_map_entity_names.py` are updated to the v2 surface as part of the task that changes each entity; a diff that changes an entity_id without updating its contract test is incomplete.
- Break-freely: renames create NEW object_ids (entity_id derives from the NAME slug). Recorder history + old registry rows for renamed entities are expendable (user ruling); the live registry sweep (final task) removes the orphans.
- Evidence: track-5 verdict table (T5-ids) + register rows R-12/R-28/R-46/R-49/R-50/R-51/R-52/R-64. Re-locate every symbol by grep (P3 moved entity files into `entities/`).
- Stage by explicit path. `.superpowers/sdd/` is gitignored scratch.
- Live registry work (final task) uses the HA MCP + `secrets/ha-credentials.txt` in-situ.

---

## Task 1: Experimental gate mechanism (R-52)

**Files:** `custom_components/dreame_a2_mower/config_flow.py` (options flow: add `experimental_features` bool, default False; migrate/absorb `debug_services`); the descriptor base classes in `entities/*/base.py` + `_sensor_base`/`_select_base`/etc (add `experimental: str | None` field — the tier name or None); the platform `async_setup_entry`s (skip descriptors whose `experimental` tier is set when the option is off; when on, create with `entity_registry_enabled_default=False`); `services.py`/`services/` (gated services raise a clear error when off); `const.py` (tier constants).

- [ ] **TDD the mechanism ONLY (no entities gated yet):** a test descriptor with `experimental="T1"` is NOT created when the option is off, IS created (disabled-by-default) when on; a gated service raises `HomeAssistantError`/`ServiceValidationError` with a clear message when off. The `debug_services` option folds into `experimental_features` (the 2 debug services become gated-when-off). Config-flow options test.
- [ ] entity-inventory: add the `experimental` field to the schema (inventory_gen validator `_UNIT_VOCAB`-style frozenset if needed); no rows populated yet.
- [ ] Gates; commit `feat(p4): experimental-features opt-in gate mechanism (R-52)`.

## Task 2: Entity + service deletions (R-28 + T5-8/T5-12/T5-16)

**Files:** `button.py` (delete lock_robot op=12 + generate_3dmap op=10 buttons — D9 accepted-but-no-effect); `services.py`/`services/` (delete the 2 op-button services + the ~4 parameterless dup services T5-12: recharge/find_bot/set_child_lock-form/finalize_session/refresh_cloud_state/move_lidar_scan per the register's "6 services" — verify each against services.yaml + track-5); the language select + 2 index sensors + data_freshness/mqtt_age_s sensors + picked_session sensor (T5 deletes — grep each, confirm dead/redundant); `services.yaml` (drop deleted service schemas); `mower/actions.py` (drop the op=12/op=10 ACTION_TABLE rows if now unused).

- [ ] For EACH deletion: grep consumers (dashboards/, tests/, automations) — dashboards may reference them (P5 rebuilds, but note); delete the entity/service + its descriptor row + its entity-inventory row + strings.json keys; update state_machine_audit expectations (−2 rows per deleted sensor). The op=10/12 ACTION_TABLE deletion may leave dispatch_action's fallback test (P1.5's) needing a different fake entry — check.
- [ ] Registry: deleted entities leave orphan registry rows on the live instance → handled in Task 7. Note the deleted unique_ids.
- [ ] Gates (corpus IDENTICAL — deletes don't touch decode); commit(s) `feat(p4)!: delete op=10/12 no-effect buttons + dup services + dead sensors (R-28, T5-8/12/16)`.

## Task 3: Entity metadata fixes (R-50, R-51)

**Files:** the descriptor tables (`entities/sensor/*.py`, `entities/switch/*.py`, `entities/select/*.py`, `number.py`, `binary_sensor.py`, `time.py`). NO entity_id/name changes this task — metadata only.

- [ ] Apply the track-5 metadata column verdicts: (a) entity_category — ~30 settings controls uncategorized → CONFIG (child_lock/dnd/rain_protection/led_*/msg_alert/voice_*/human_presence_alert etc.); 6 controls mis-tagged DIAGNOSTIC → CONFIG. (b) device_class/unit — the invalid "x" unit → none (mowing_count); raw-epoch sensors → TIMESTAMP (last_settings_change, latest_session_unix_ts); DURATION for *_min/*_duration/sim_left_days/latest_video; AREA for *_area_m2; DATE where applicable. (c) state_class — 4 position sensors (position_x/y/north/east) demote from MEASUREMENT → drop state_class (T5-15, recorder churn); mowing_phase drop state_class.
- [ ] (R-51) staleness consolidation: 3 staleness surfaces → consolidate on mqtt_connectivity (data_freshness deleted in Task 2; mqtt_age_s deleted; the remaining staleness reads mqtt_connectivity).
- [ ] (T5-17) raw-code shadow sensors (charging_status_code_raw/task_state_code/mowing_phase/slam_task + s5pXXX_raw) → entity_registry_enabled_default=False for public.
- [ ] entity-inventory rows updated per change (device_class/unit/category fields); state_machine_audit unaffected (no class add/remove). Card-contract unaffected (no id change).
- [ ] Gates; commit(s) `feat(p4): entity metadata — categories, device_classes, units, state_class (R-50/51)`.

## Task 4: Experimental gate population (R-52, T5-9)

**Files:** the descriptor rows for the 13 gated entities + `update.py` (firmware install) + `camera/photos.py` (obstacle_photo) + `services.py` (create_patrol_point).

- [ ] Set `experimental=<tier>` on: **T1** — sensor.mpos + button.refresh_mpos, s5p104/105/106/107_raw + s6p1_raw probes, sensor.api_endpoints_supported, sensor.novel_observations, service create_patrol_point. **T2** — update.firmware install path, select.active_map. **T3** — camera.obstacle_photo (also renamed in Task 5). Each row's entity-inventory gains `experimental: <tier>` + a verifications note citing the promotion evidence (what would flip it to non-gated).
- [ ] TDD: with the option OFF, none of the 13 are created; with it ON, all created disabled-by-default; the gated services raise when off. On the LIVE instance the option defaults off, so these 13 vanish from the surface (registry orphans → Task 7).
- [ ] Correct the spec's o=223 example already done (P2); confirm inventory says o223 confirmed and create_patrol_point gating rationale is "integration send not live-confirmed" (T1), consistent.
- [ ] Gates; commit `feat(p4): populate experimental gate — 13 entities/services tiered (R-52/T5-9)`.

## Task 5: Renames — the entity_id break (R-64, T5-11) — HIGH-BLAST

**Files:** the renamed classes' descriptor `name`/`key` + their entity-inventory rows + `test_card_contract.py` + `test_per_map_entity_names.py` + strings.json + `dashboards/mower/dashboard.yaml` (note-only; P5 rebuilds, but update the entity_ids the strategy will need).

- [ ] Apply the 14 renames from the track-5 verdict table (entity_id derives from the NAME slug — changing the descriptor name changes the object_id): camera.map→live_map "Live map", camera.work_log→session_replay "Session replay", camera.obstacle_photo→latest_obstacle_capture, work-log SELECT→session_replay picker, the colon-name families (human_presence_scenario_* / human_presence_alert_voice / msg_alert_* → "Anomaly notifications" etc / voice_* → "Voice prompt — …"), latest_video→"Latest video duration", + the rest in the table. Each rename: descriptor name + entity-inventory row (the `object_id` field T5-13 gets added so inventory tracks the name-derived id, not just the key) + card-contract test + strings.json key.
- [ ] **Root-cause the floor_0_outside_ prefix (R-11/T5-2) BEFORE renaming those 4:** the prefix comes from the device-name-at-creation-time (a per-map or area-associated device). Find the creation-time source (grep `_devices.py` map_device_info / the area/device assoc); confirm a FRESH install would not get the prefix (document the mechanism); the 4 stale ids (obstacle_photo/sim_out_of_warranty/obstacle_markers/sim_data_remaining) then get canonical object_ids. If the mechanism can't be root-caused cleanly, the registry rename (Task 7) still fixes the live instance but REPORT the risk that new installs could recur.
- [ ] The old entity_ids become orphan registry rows on live → Task 7 sweep.
- [ ] Gates (corpus IDENTICAL; card-contract REWRITTEN to v2 ids; per-map-naming green); commit(s) `feat(p4)!: v2 entity renames — new object_ids (R-64/T5-11)`.

## Task 6: Translation rebuild + contract-test finalization (R-46)

**Files:** `strings.json` + `translations/en.json` + `test_card_contract.py` (final v2 pin) + any contract test the P0-era pinned to old names.

- [ ] Rebuild strings.json against the FINAL v2 entity surface (post Tasks 2-5): drop the 40 stale keys (T4-7), remove the D16 obstacle_detected remnant, dedupe the 5× language surfaces (language select deleted in Task 2 → its keys go), add keys for the renamed entities. `en.json` regenerated to match. A test asserting strings.json ↔ actual-entity-keys parity (if one exists; else add a light one).
- [ ] Contract tests: the card-contract + any attribute-shape contract now pins the v2 surface (camera map attrs, picked_session→whatever replaced it, editable_objects). Confirm every card-consumed attribute still published post-rename (the cameras renamed but their attrs unchanged).
- [ ] Gates; commit `feat(p4): rebuild translations to v2 surface + finalize contracts (R-46)`.

## Task 7: Live registry cleanup + phase wrap

- [ ] **Root-cause confirmation (R-11):** with the deploy, confirm on the live instance whether the floor_0_outside_ prefix recurs for freshly-created entities (it should not, post-Task-5). If it does, that's a blocker — fix before release.
- [ ] Full gate battery: suite; ruff; validate-only; findings_fold; corpus IDENTICAL; render golden; collect-only; all audits (entity-inventory coverage, state_machine, layer, census, getattr, control-honesty).
- [ ] ff-merge → push → `release.sh` (release notes: **user-visible entity_id changes** — list the renames + deletions + the experimental-features option; warn that dashboards/automations referencing old ids need updating; P5 rebuilds the bundled dashboard).
- [ ] Live deploy: HACS download + restart. Then via HA MCP: (a) the deleted + experimental-gated entities are GONE (274 → ~274−10−13 ≈ 251, verify the exact expected count); (b) the renamed entities appear under NEW object_ids; (c) the OLD renamed/deleted ids are orphan `unavailable` rows → **remove them via WS config/entity_registry/remove** (the entity-rename-orphan procedure from memory: `feedback_entity_rename_orphan`); (d) the 2 R-49 orphan rows removed; (e) error log clean; (f) a settings write round-trip (e.g. toggle a CONFIG switch) proves the writes service + new metadata.
- [ ] Ledger + working-dir README + memory update + branch delete.

---

## Self-review record

- **Register coverage (P4-tagged):** R-52→T1+T4, R-28→T2, R-50/R-51→T3, R-52/T5-9→T4, R-64/R-11→T5, R-46→T6, R-49/R-12→T7 (+T2 for the OTA-rows-source), R-64 residuals (dup services T5-12, picked_session T5-16, raw-code default T5-17, lawn_mower/button overlap doc T5-18)→T2/T3. The lawn_mower/button intentional-overlap doc (T5-18, an `idea`) → a CLAUDE.md note in T2.
- **Proof model:** unlike P3, corpus-IDENTICAL is a GUARD here (entity layer doesn't drive the digest), not the headline proof. The headline proof is: rewritten contract tests + entity-inventory coverage + LIVE registry verification (the deleted/gated entities gone, renames landed, orphans removed, a write round-trip). The live step is load-bearing for P4.
- **Ordering rationale:** gate-mechanism (1) before gate-population (4); deletes (2) + metadata (3) before renames (5) so the id-break pass moves the fewest things; strings/contracts (6) after all surface changes; live cleanup (7) last.
- **Placeholder scan:** the exact rename/delete/metadata lists live in the cited track-5 verdict table (SoT) rather than restated line-by-line — the implementer reads the table. Each task names its register R-id + T5-ids + the grep to re-locate.
