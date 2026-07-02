# Refactor v2 — P2 Correctness & Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the confirmed correctness/lifecycle defects from the Act I register (R-4..R-7, R-17, R-35..R-42, R-53, R-58, R-63, R-66-part) plus the items inherited from P1 reviews and live verification — every fix TDD'd, decode semantics still byte-identical.

**Architecture:** Behavior-fixing phase per `docs/superpowers/specs/2026-07-02-refactor-v2-target-architecture.md` § 9 P2. No structural moves (P3). Session-code tasks write their race/interleaving tests FIRST (they are P3's safety net too). Entity *surface* stays unchanged except where a fix requires new attributes (error_samples) or corrected state derivation (error sensor ≤255) — no renames, no deletions (P4).

**Tech Stack:** Python 3.13 (`/data/claude/homeassistant/.venv-vanilla/bin/python`), pytest, ruff, git.

## Global Constraints

- Branch: `refactor-v2/p2-correctness` off main (@ 499e4a26 or later). Commit locally per task; push at phase wrap only.
- Venv: `/data/claude/homeassistant/.venv-vanilla/bin/python` from repo root. Suite baseline at branch time: **2664 passed / 1 skipped / 1 xfailed** (record actual; it grows as tasks add tests — track the arithmetic per task).
- **Corpus gate (every task):** `python -m tools.replay.corpus_replay --corpus-dir /data/claude/homeassistant/probe/logs --diff /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json` → `IDENTICAL`. P2 fixes glue/lifecycle/entity behavior, never the pure decode pipelines the digest captures.
- `ruff check custom_components/` clean per task.
- TDD is mandatory: failing test → verify fail → fix → verify pass → full suite → commit. Every fix names its failure scenario.
- Evidence pointers: track findings in `/data/claude/homeassistant/refactor-2026-07-02/findings/track-{3,5,6,7}-*.md` (T-ids cited per task). LINE NUMBERS HAVE DRIFTED (P1 deleted ~5,900 lines) — re-locate every cited symbol by grep before editing; if the code changed materially since Act I, re-verify the finding still holds and say so in the report.
- Fact discipline (CLAUDE.md): entity-behavior changes that alter what a sensor/attribute reports need the matching `entity-inventory.yaml` row updated in the same commit (+ `--validate-only`). No wire claims without inventory citation.
- Stage by explicit path. The `.superpowers/sdd/` dir is gitignored scratch.
- state_machine_audit + control-honesty + card-contract gates: if a task trips one, update the gate's expectation in the SAME commit with a one-line justification (expected for T4's new attribute and T3's error-sensor state change).

---

## Task 1: MQTT freshness — `is_connected` property bug + shape-census gate (R-4 / T3-1 / T7-1 / T7-2)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` (the `mqtt_is_fresh` property — currently calls `mqtt.is_connected()`; `is_connected` is a `@property` on `mqtt_client.py`, so the call raises TypeError which the surrounding try/except swallows, returning False whenever cloud is also stale → the MQTT availability gate has NEVER worked)
- Modify: `tests/integration/test_availability.py` (`_FakeMqtt` defines `is_connected` as a METHOD — the mock-mask; convert to property)
- Create: `tests/audit/test_mock_shape_census.py` (the permanent T7-2 gate)
- Test: `tests/integration/test_availability.py`

**Interfaces:**
- Produces: `coordinator.mqtt_is_fresh` actually consulting broker state; an AST-based census test asserting no test fake defines as a METHOD anything the production class defines as a PROPERTY (for the classes fakes stand in for: `DreameA2MqttClient`, `DreameA2CloudClient`, coordinator).

- [ ] **Step 1: Write the failing test** — in `test_availability.py`: with a REAL `DreameA2MqttClient` instance (no fake) whose `_connected=True` and a recent heartbeat timestamp, `mqtt_is_fresh` must be True; with `_connected=True` but heartbeat stale (> HB_STALENESS_S), False. (The first assertion fails today with the TypeError swallowed → False.) Also convert `_FakeMqtt.is_connected` to a `@property` and confirm which existing tests break — those breakages are the mask being lifted; fix their expectations to the now-correct semantics.
- [ ] **Step 2: Run; verify the new test FAILS on current code** (and capture the swallowed-TypeError proof: temporarily log inside the except in your local run, or assert via `mqtt.is_connected` truthiness path).
- [ ] **Step 3: Fix** — `_core.py`: use the property (`if mqtt.is_connected:`). Audit the SAME file for any other `.is_connected()` call (grep repo-wide: `is_connected()`).
- [ ] **Step 4: Shape-census gate** — `tests/audit/test_mock_shape_census.py`: walk `tests/` ASTs; for each class whose name matches `_Fake*`/`Fake*`/`Mock*` stand-ins of the three production classes (map by name heuristics documented in the test docstring), compare each attribute it defines against the production class: `property` on prod ⇒ must not be `FunctionDef` on the fake. Seed with the exact production-class list; the test must FAIL if you revert `_FakeMqtt` (prove by ablation, state it in the report).
- [ ] **Step 5: Gates + commit** — suite (expect +N new tests, all green), ruff, corpus IDENTICAL. Commit: `fix(p2): mqtt_is_fresh called the is_connected property — availability gate never worked (R-4)`.

---

## Task 2: `cloud_state=None` setup crash + 0/3-map parametrization (R-5 / T3-2, R-58 / T7-22)

**Files:**
- Modify: `custom_components/dreame_a2_mower/__init__.py` and/or `coordinator/_core.py` (first-refresh contract: if the initial `fetch_full_cloud_state` fails, `coordinator.cloud_state` stays None but setup proceeds → five platform `async_setup_entry`s crash on `coordinator.cloud_state.maps_by_id`; grep `cloud_state.maps_by_id` in select.py/switch.py/number.py + 2 more to enumerate)
- Test: `tests/integration/test_setup_cloud_blip.py` (new), plus parametrized 0-map/3-map additions where the welded 2-map fixture lives (`tests/integration/conftest.py`)

**Decision (locked):** raise `ConfigEntryNotReady` when the FIRST cloud fetch fails (HA retries setup with backoff — the correct public-install semantics), rather than guarding every platform loop. Platform loops ALSO get a cheap `maps_by_id = coordinator.cloud_state.maps_by_id if coordinator.cloud_state else {}` guard as defense-in-depth (reload with a mid-life None must not crash either).

- [ ] **Step 1: Failing test** — simulate first-refresh cloud failure (mock `fetch_full_cloud_state` raising / returning None) → assert `ConfigEntryNotReady` raised from setup, AND platform setups with `cloud_state=None` build zero per-map entities without raising.
- [ ] **Step 2: Verify fail** (today: AttributeError). **Step 3: Fix** per the locked decision. **Step 4:** parametrize the per-map fixture for 0 and 3 maps in the touched tests (T7-22 scope: entity setup counts scale correctly; don't boil the whole suite). **Step 5:** gates + commit `fix(p2): first-refresh cloud failure → ConfigEntryNotReady; platforms tolerate cloud_state=None (R-5)`.

---

## Task 3: Small entity-truth fixes — integration_version + error-sensor 255-char overflow (R-6 / T5-1 + live finding 2026-07-03)

**Files:**
- Modify: `custom_components/dreame_a2_mower/entities/sensor/device.py` — (a) `_read_manifest_version()` resolves `Path(__file__).parent / "manifest.json"` = `entities/sensor/` — two levels short; fix to the package root (`parents[2]`); (b) the error sensor: with ≥~3 concurrent faults the localized-text state exceeds HA's 255-char limit → HA drops it to `unknown` (live-verified 2026-07-02 restart, 5 faults). New contract: **state = comma-joined fault SLUGS (catalog event_slug), truncated safe**; full localized text moves to attributes (`faults`: list of {code, slug, text} — derive from the existing catalog surface; cite catalog, don't restate strings).
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml` — both rows (state semantics change on error sensor; verifications record with today's live evidence)
- Test: `tests/integration/test_version_sensor.py` (or nearest existing), `tests/integration/test_error_sensor_value.py`

- [ ] **Step 1: Failing tests** — (a) version sensor returns the real manifest version (not "unknown"); (b) error sensor with 5 active catalog faults: `len(state) <= 255`, state is the slug list, attributes carry all 5 full texts.
- [ ] **Step 2-4:** verify fail → fix → pass. state_machine_audit expectations may need the attribute addition — update in-commit.
- [ ] **Step 5:** gates (+ `--validate-only`) + commit `fix(p2): version-sensor manifest path; error-sensor slug state ≤255 w/ text attrs (R-6 + live)`.

---

## Task 4: Publish `error_samples` + pin the replay-card contract (R-7 / T6-3)

**Files:**
- Modify: `custom_components/dreame_a2_mower/session_card.py` (`build_picked_session_summary` — publishes `state_samples` at ~line 595 but never `error_samples`, though raw_dict carries it and the card's rain-delay overlay reads `a.error_samples` at `www/dreame-mower-replay-card.js:422`)
- Modify: `tests/integration/test_card_contract.py` (pin the key)
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml` (picked_session attrs row)
- Test: existing card-contract + a new focused test

- [ ] **Step 1: Failing test** — build a picked-session summary from a raw_dict containing `error_samples` (shape: list of [ts, code] — cite inventory § error/state samples for the exact row shape; mirror how `state_samples` is normalized at :595) → assert the summary dict contains `error_samples` with the same normalization; card-contract test asserts the key exists.
- [ ] **Step 2-4:** fail → implement (mirror the `state_samples` publication path exactly) → pass. Verify the card side needs NO change (it already reads the attr — that's the finding).
- [ ] **Step 5:** gates + commit `fix(p2): publish error_samples in picked_session attrs — rain-delay overlay was dead (R-7)`.

---

## Task 5: Write honesty completion — CFG/PRE/settings paths (R-35 / T3-3, T7-9, T7-23)

The largest task. Current state (re-verify): `routed_action`/`dispatch_action` return `WriteResult`, but `set_cfg`/`set_pre`-driven writes (switch/number/select/time settings paths through `_settings_writes.py` + `coordinator/_writes.py:write_settings/write_setting/_dispatch_cfg_write`) are fire-and-forget bools or log-only on rejection; schedule + map-edit families return bare bools; the three "accepted-path" tests assert nothing (T7-9 names them).

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py` (`set_cfg`, `set_pre` → return `WriteResult` — they already parse result codes internally; surface them)
- Modify: `custom_components/dreame_a2_mower/coordinator/_writes.py` (settings/schedule/map-edit families → propagate `WriteResult`; kill bool returns; `_writes.py` callers of set_cfg/set_pre)
- Modify: `custom_components/dreame_a2_mower/_settings_writes.py` + the entity write handlers that call it (switch/number/select/time bases) → on `not result` raise `HomeAssistantError` via the existing `coordinator/_write_errors.py:raise_for_write_result`
- Modify: `custom_components/dreame_a2_mower/services.py` handlers for schedule/map-edit → same surfacing
- Test: `tests/integration/test_write_honesty_cfg.py` (new): for EACH family (CFG switch, PRE number, settings select, time, schedule set, one map-edit op) — mock a device rejection (r=-3 style per the family's transport; cite inventory for the code) → entity/service call raises; mock accepted → state applied. Replace the three assert-nothing tests with real assertions.

- [ ] Steps: enumerate current bool-return sites (grep `-> bool` in _writes.py + `_settings_writes.py`); failing tests per family; fix transport→coordinator→entity chain; verify each rejection test fails before the surfacing lands (ablation); full suite; corpus IDENTICAL; commit `fix(p2): WriteResult end-to-end for CFG/PRE/settings/schedule/map-edit; rejections raise (R-35)`.
- [ ] NOTE: optimistic-overlay code paths touched here must not regress Task 6's fix if it lands first — coordinate via rebase, the overlay call sites are shared.

---

## Task 6: Optimistic writes broadcast correctly + stripe preview refresh (R-37 / T3-5, R-36 / T3-4)

**Files:**
- Modify: the optimistic-write helpers that assign `coord.data = ...` directly (T3-5 — grep `\.data = ` under custom_components/dreame_a2_mower/ excluding coordinator internals' legitimate sites; the finding names entity-side helpers) → route through `async_set_updated_data` so sibling entities + freshness see the write and reverts.
- Modify: the mowing-direction select handler + `coordinator/_rendering.py:_render_base` dedup key (T3-4: direction change never re-renders the stripe preview — no render trigger fires and the dedup key omits the direction input).
- Test: focused tests for both (render-trigger spy for direction change; a sibling-entity-sees-optimistic-value test).

- [ ] TDD both; gates; commit `fix(p2): optimistic writes broadcast via async_set_updated_data; direction change re-renders stripe preview (R-36/R-37)`.

---

## Task 7: Session-race hardening — dock-wait single-flight + finalize interleaving tests (R-38 / T3-6, R-17 / T7-19)

Tests-first task: these tests are ALSO P3's safety net for the session-service extraction.

**Files:**
- Test (first): `tests/coordinator/test_finalize_interleavings.py` (new) — pin: (a) `_do_oss_fetch` × `_run_finalize_incomplete` cross-writer race (both reach finalize; latch must serialize; no double archive-write — use the barrier-executor pattern from `tests/coordinator/test_finalize_latch.py`); (b) restore-at-boot × finalize; (c) rain-veto during route-arm.
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py` — dock-wait re-entry (T3-6): the 60s tick re-enters `_wait_for_dock_return` stacking waiters on the single `_pending_finalize_done` Event (stamp lands only after the wait) → make it single-flight (guard flag or task handle; the plan mandates the BEHAVIOR: N concurrent tick entries produce one waiter, one attempt stamp, correct Event lifecycle).

- [ ] Write the interleaving tests; any that EXPOSE a real defect beyond T3-6 → fix it in this task (report each); dock-wait single-flight fix + its test; gates; commit `fix(p2)+test: finalize interleaving pins; dock-wait single-flight (R-17/R-38)`.

---

## Task 8: Lifecycle & teardown — cancel everything, wire rc=5, unload order (R-40 / T3-8, R-41 / T3-9, R-63 / T3-13+T3-12, R-18-part / T7-20)

**Files:**
- Modify: `coordinator/_core.py` / `__init__.py` / `coordinator/_session.py` / `coordinator/_mqtt_handlers.py`: (a) track + cancel on unload: the 3 `call_later` timers, the 10s s2p2 resolver, the ≤10-min dock-wait task; remove the dead `_pending_finalize_task` slot (T3-8 names all — re-locate by grep `call_later\|async_call_later`); (b) unload ORDER: platforms unload BEFORE transports disconnect; a failed platform-unload must not strand dead transports (T3-13); (c) `_persist_in_progress` vs `delete_in_progress` TOCTOU (T3-12): make finalize's delete + the periodic persist mutually exclusive (reuse the finalize latch or a small lock).
- Modify: `custom_components/dreame_a2_mower/mqtt_client.py` + `coordinator/_core.py`: WIRE the existing-but-orphaned rc=5 path — `register_auth_error_callback`/`update_credentials` exist unused (T3-9); on rc=5 the coordinator must refresh cloud creds (re-login via cloud client) and reconnect MQTT with the new token instead of looping.
- Test: `tests/integration/test_unload_lifecycle.py` (new): unload cancels all named timers/tasks (spy on cancel), platform-then-transport order asserted, reload leaves no extra thread (thread-count pattern exists from P1.5-era lifecycle tests); rc=5 test: fake CONNACK rc=5 → assert re-login called + reconnect attempted with refreshed creds.

- [ ] TDD; note which T7-20 assertions remain impossible against the current HA stub (report them for the P3 factory — do NOT build stub infrastructure here); gates; commit `fix(p2): unload cancels timers/tasks, platform-first order, rc=5 auth-refresh wired, persist/delete TOCTOU (R-40/R-41/R-63)`.

---

## Task 9: Paho-thread stale-base decode (R-39 / T3-7)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` — `handle_property_push` currently reads `self.data` as the apply-base ON THE PAHO THREAD; a concurrent loop-side update (optimistic write, cloud refresh) between read and the loop-side broadcast gets reverted. Move the base-read + `apply_property_to_state` call INTO the loop-side closure (the P1.3-era pattern: paho thread = pure payload decode only). Corpus bound (all 235,725 corpus messages are single-param) means per-message multi-param self-clobber is unobserved — but the cross-source revert is real.
- Test: extend `tests/coordinator/test_sm_thread_safety.py`-style spy: assert `apply_property_to_state` executes on the loop, not the calling thread; a loop-side `data` mutation between message receipt and apply is NOT reverted (deterministic interleaving via the barrier executor).

- [ ] TDD; **corpus gate is the critical proof here — must stay IDENTICAL** (ordering within a single-threaded replay is unchanged); gates; commit `fix(p2): property apply reads state base on the event loop — no cross-source revert (R-39)`.

---

## Task 10: Small-fix batch — GPS keep-last, CARD_VERSION sync, gate hygiene (R-42 / T3-10, R-53 / T6-7, T7-17, T7-25)

- [ ] `coordinator/_refreshers.py:_refresh_gps` (T3-10): transient fetch failure currently clears tracker/position (failure conflated with no-data). Fix: exception/None-fetch → keep last fix (optionally mark stale); only an explicit empty-data response clears. TDD.
- [ ] `tools/release/release.sh` CARD_VERSION sync (T6-7): the sed/grep pattern misses `dreame-a2-schedule-card.js` (banner frozen at v1.0.2a3 while siblings track releases). Fix the pattern to cover ALL `www/*.js` with a CARD_VERSION banner; verify by dry-run grep listing every banner file. Also bump the schedule card's banner to current so the next release syncs it.
- [ ] `tests/inventory/test_control_entities_wired.py` (T7-17): the wiring gate silently `continue`s on ImportError → a broken entity module skips its own gate. Fix: ImportError = test failure with the module name.
- [ ] `tests/archive/` (T7-25): add the corrupt-session-body-JSON load test (archive returns a clean error/skip, no crash).
- [ ] Gates; commit `fix(p2): gps keep-last, release.sh card-version sync, wiring-gate ImportError, corrupt-archive load (R-42/R-53/T7-17/T7-25)`.

---

## Task 11: P1-inherited residue sweep (final-review inherit list)

- [ ] `tests/protocol/test_fetch_full_cloud_state.py` ~:83: the `client.fetch_locn = MagicMock()` + `assert_not_called()` guard is vacuous post-deletion — delete those lines (keep the test's real assertions).
- [ ] `docs/research/state-machines/reboot-and-idle.md` ~:217: the `wifi_map_data` row cites deleted `fetch_wifi_map` and a MowerState field that no longer exists — delete/correct the row (grep `wifi_map_data` first).
- [ ] `docs/research/app-api-surface-2026-05-25.md`: add the Tier-3 non-authoritative banner (matches the journal's banner style) — it recommends changes to the deleted `_poll_slow_properties`.
- [ ] `cloud_client/_oss.py` ~:120: `list_wifi_candidates` docstring still compares to deleted `fetch_wifi_map` — reword.
- [ ] `docs/research/debunked-claims.md` era-row nits: BT era points at `_property_apply.py:108` (comment now lives ~:70-71, corrected in P1); pre-catalog era row's "shipped in-tree specs (T1-9)" was resolved by the P1.6 move — update both status clauses.
- [ ] Gates (docs+test-only; suite + ruff; corpus not needed if zero .py under custom_components changed EXCEPT the _oss.py docstring — state the diff scope); commit `docs(p2): P1-inherited residue sweep`.

---

## Task 12: Phase wrap — merge, release, live verify

- [ ] Full gate battery (suite, ruff, `--validate-only`, corpus IDENTICAL, `findings_fold_check`).
- [ ] `git checkout main && git pull --rebase && git merge --ff-only refactor-v2/p2-correctness && git push origin main`.
- [ ] Release via `tools/release/release.sh`; HACS refresh; HA restart.
- [ ] Live verification via MCP: entry `loaded`; **error sensor now shows slug-state (not unknown) with the 5 active faults**; `integration_version` sensor shows the real version; no new dreame errors in `system` log; entity count unchanged (±0 — this phase adds/removes no entities).
- [ ] Ledger + working-dir README status + delete branch.

---

## Self-review record

- **Register coverage (P2-tagged):** R-4→T1, R-5+R-58→T2, R-6→T3, R-7→T4, R-17→T7, R-35→T5, R-36/37→T6, R-38→T7, R-39→T9, R-40/41→T8, R-42/53→T10, R-63→T8, R-66-part→T10 (T7-11 paint-order and golden-semantic-diff explicitly DEFERRED to P3 test work — recorded here, not silently dropped). R-18 is split: unload tests in T8, the full setup_entry factory is P3 (R-16) by design. Live-finding error-overflow→T3. P1-inherit→T11.
- **Placeholder scan:** tasks carry locked decisions (T2's ConfigEntryNotReady, T3's slug-state contract) instead of TBDs; symbol relocation via grep is the mechanism for drifted line numbers, stated in Global Constraints.
- **Consistency:** corpus command identical throughout; branch name consistent; WriteResult surfacing reuses `raise_for_write_result` everywhere; T5/T6 shared-call-site coordination noted.
