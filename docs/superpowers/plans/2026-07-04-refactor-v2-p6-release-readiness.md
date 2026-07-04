# Refactor-v2 P6 — Release Readiness → v2.0.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the integration installable and safe for any g2408 owner, then cut **v2.0.0**.

**Architecture:** Public-release hardening only — config-flow UX, diagnostics privacy, HACS/store hygiene, docs. No protocol changes; corpus-replay stays IDENTICAL. One branch (`refactor-v2/p6-release`), per-task TDD, `tools/release/release.sh` for the final cut.

**Tech Stack:** HA config entries + `ConfigFlow`/`OptionsFlow`, `async_get_config_entry_diagnostics`, voluptuous, HACS metadata, pytest (vanilla stubbed-HA venv `/data/claude/homeassistant/.venv-vanilla`).

## Global Constraints

- **Break freely** (pre-public) — entity ids / service names / option keys may change; prefer stability where free.
- Secrets used **in-situ** only (never copied out of `secrets/`).
- Landing version **v2.0.0**; release via `tools/release/release.sh` (never manual `gh release`); respect the HACS alpha digit-count ladder for any pre-release cuts.
- Corpus digest IDENTICAL (`tools/replay/corpus_replay.py --diff goldens/baseline-v1.0.31a5.json`) — P6 must not touch decode/state.
- Every fact-bearing doc edit follows CLAUDE.md fact-discipline (cite `inventory.yaml` §, don't restate wire values).
- Live-HA A/B after each sub-phase via MCP; suite green before merge.

## Decisions (defaults chosen 2026-07-04 while user AFK — confirm on review)

- **Offline last-known persistence** (deferred from P5.5, `docs/TODO.md`): IN P6 as a **separable late sub-phase (P6.7)** so v2.0.0 can ship with or without it.
- **Multi-device (R-43):** **Guard + document** — config flow explicitly selects/pins one g2408, warns on multiple, README states single-device support. NOT full per-device entries (over-engineering for a single-user-going-public release; cf. `feedback_no_migration_overengineering`).
- **Region (R-45):** label EU-verified; other regions "best-effort, please report" + a community-verify path. No region gating.

## Findings mapped to sub-phases

| Sub-phase | Findings | Deliverable |
|---|---|---|
| P6.1 Config-flow UX | R-2, R-44, R-45, R-43(guard) | validate creds on setup; reauth; ConfigEntryAuthFailed/NotReady; g2408 model gate; region label; single-device pin+warn |
| P6.2 Diagnostics privacy | R-3, R-60(part) | redact-by-ALLOWLIST rewrite; drop false "encrypted-at-rest" claim; did/MAC log level demote |
| P6.3 HACS/repo hygiene | R-60 | hacs.json country whitelist decision; `.github/ISSUE_TEMPLATE/`; document the wire-trace instrument; remove stale migration notice |
| P6.4 Docs sweep | R-47 | purge dev-box paths / stale citations / archived-doc refs from README + docstrings |
| P6.5 CI + tooling | R-67, R-53 | www-test CI node setup; Pillow-14 deprecation note (deadline 2027-10); release.sh schedule-card version-banner sync |
| P6.6 README productization | R-45, R-43, general | public install/usage README: strategy dashboard, single-device, region status, experimental gate |
| P6.7 Offline persistence (separable) | P5.5 TODO | last-known across restart + config availability policy + persist active_map_id |
| P6.8 Release | — | fresh-install walkthrough on live HA → **v2.0.0** |

---

### Task 1 (P6.1a): Credential validation on setup

**Files:** Modify `custom_components/dreame_a2_mower/config_flow.py:63` (`async_step_user`). Test: `tests/config_flow/test_validation.py` (new).

**Interfaces:** `async_step_user` currently sets unique_id to username and creates the entry WITHOUT trying to log in. Add a real login attempt via `DreameA2CloudClient` (same construction as `__init__.py` setup uses) inside the flow; map outcomes to form errors.

- [ ] Write failing test: bad creds → form re-shown with `errors["base"]=="invalid_auth"`; cloud unreachable → `"cannot_connect"`; success → entry created. Use a stubbed cloud client (monkeypatch the login to raise / succeed).
- [ ] Implement: in `async_step_user`, on submit, construct the client and `await client.login()` inside `try/except`; on auth failure set `invalid_auth`, on transport failure `cannot_connect`, else proceed to `async_create_entry`. Keep `async_set_unique_id(username)` + `_abort_if_unique_id_configured()`.
- [ ] Add `strings.json`/`en.json` error keys `invalid_auth`, `cannot_connect`, `unknown`.
- [ ] Run `pytest tests/config_flow/test_validation.py -v`; suite green.
- [ ] Commit.

### Task 2 (P6.1b): Reauth flow + ConfigEntryAuthFailed

**Files:** Modify `config_flow.py` (add `async_step_reauth` + `async_step_reauth_confirm`); `__init__.py` (`async_setup_entry`) + the coordinator boot path to raise `ConfigEntryAuthFailed` on login failure (ties to R-41 rc=5, already wired in P2 — reauth is the UI surface). Test: `tests/config_flow/test_reauth.py`.

**Interfaces:** Cloud login raises a distinguishable auth error. On auth failure at setup or during the rc=5 recovery giving up, raise `homeassistant.exceptions.ConfigEntryAuthFailed` so HA starts the reauth flow.

- [ ] Failing test: entry in reauth state → `async_step_reauth_confirm` accepts a new password, re-logs in, updates `entry.data`, reloads. Bad new creds → `invalid_auth`, stays in reauth.
- [ ] Implement reauth steps (standard HA pattern: `async_step_reauth(entry_data)` stashes the entry, `async_step_reauth_confirm` shows password form, validates, `self.async_update_reload_and_abort`).
- [ ] Ensure setup/boot raises `ConfigEntryAuthFailed` on unrecoverable auth (verify the rc=5 give-up path from P2/P3 surfaces it, not `ConfigEntryNotReady`).
- [ ] Tests green; commit.

### Task 3 (P6.1c): g2408 model gate + region label + single-device pin/warn

**Files:** `config_flow.py` (after login, list devices, pick g2408); `strings.json`/`en.json`; `const.py` (region label constant if needed). Test: `tests/config_flow/test_device_select.py`.

**Interfaces:** `client.get_devices()` / `select_first_g2408()` exist (`cloud_client/_discovery.py`). Use them to (a) reject accounts with no g2408 (`no_supported_device`), (b) if multiple g2408s, pin the first and set a repair/log warning + note single-device support, (c) if a `dreame.mower.*` non-g2408 appears, warn model-unverified (R-44).

- [ ] Failing test: account with a g2408 → entry pinned to it; account with none → abort `no_supported_device`; multiple → first pinned, warning issued.
- [ ] Implement device discovery + pin in the flow; store the chosen `did`/SN in `entry.data`. Region: add the selected country to entry data (already collected); README carries the eu-verified labeling (Task 12) — no gating here.
- [ ] Tests green; commit.

### Task 4 (P6.2a): Diagnostics redact-by-allowlist rewrite

**Files:** Rewrite `custom_components/dreame_a2_mower/diagnostics.py`. Test: rewrite `tests/**/test_diagnostics*.py` (find + update).

**Interfaces:** Current `redact()` is a DENYLIST (`REDACTION_KEYS`) — leaks did/uid/uuid/subscribe_topic + the whole `state` (GPS `position_lat`/`position_lon`, `wifi_ssid`, `wifi_ip`, serial). Replace with an explicit ALLOWLIST: dump only fields known-safe for a bug report; everything else omitted or `**REDACTED**`.

- [ ] Failing test: assert the diagnostics output contains NONE of {a sample GPS lat/lon, an SSID, a LAN IP, the serial, `did`, `uid`, `uuid`, `subscribe_topic`, MQTT topic}; and DOES contain the safe debugging fields (state machine phase, entity counts, versions, archive counts, redaction markers).
- [ ] Implement allowlist redaction; keep structure stable for existing consumers where possible (break freely if needed).
- [ ] Remove the docstring's redaction-keys promise; ensure no "encrypted at rest" claim remains (grep repo).
- [ ] Tests green; commit.

### Task 5 (P6.2b): Log-level demotion of identifiers

**Files:** grep for `_LOGGER.info(`/`LOGGER.info(` lines emitting `did`/MAC/serial/SSID/IP; demote to DEBUG. Test: none (log-level change) — spot-check via grep gate.

- [ ] grep the codebase for INFO logs that print `did`, MAC, serial, SSID, or IP; demote each to `.debug(`.
- [ ] Add a tiny guard test or a `tools/` grep check if one fits the existing pattern; else note in the PR.
- [ ] Commit.

### Task 6 (P6.3a): hacs.json country whitelist + homeassistant floor

**Files:** `hacs.json`. Decision needed: the `country` array (NO/GB/US/FR/DE/ES/IT/NL/SE/PL) limits HACS visibility by country — for a public release either (a) remove it (visible everywhere; matches "eu-verified, others best-effort") or (b) keep + document. Recommend (a) REMOVE, and rely on README region labeling.

- [ ] Remove the `country` key from `hacs.json` (or per user ruling on review). Keep `homeassistant: "2025.4.0"` floor (verify it still matches the lowest API used).
- [ ] Add a validation check (hacs-action already in CI?) passes.
- [ ] Commit.

### Task 7 (P6.3b): Issue templates + wire-trace doc + stale-notice removal

**Files:** Create `.github/ISSUE_TEMPLATE/bug_report.yml` + `feature_request.yml` + `config.yml`; document the gated wire-trace instrument (`/config/dreame_a2_wire_trace.enabled`) in a Tier-2 doc / README troubleshooting; grep + remove any stale migration notice (R-60).

- [ ] Add issue templates (bug report asks for the REDACTED diagnostics file — safe after Task 4 — HA version, integration version, and NOT to paste secrets).
- [ ] Document the wire-trace toggle (what it captures, that it may contain identifiers, how to disable) in the troubleshooting section.
- [ ] grep for and remove the stale migration notice / any `async_migrate_entry` dead notice.
- [ ] Commit.

### Task 8 (P6.4): Docs sweep — dev-box paths + stale citations (R-47)

**Files:** `README.md`, docstrings across `custom_components/`. Test: a grep gate.

- [ ] grep README + docstrings for dev-box paths (`/data/claude/`, `/config/dreame_a2_wire_trace`, personal SSIDs/SNs, `/tmp` evidence cites, archived-doc `docs/superpowers/...` in-tree refs) and fix/remove.
- [ ] Add/extend a CI grep gate that fails on `/data/claude/` or personal identifiers in shipped files (`custom_components/**`, `README.md`).
- [ ] Commit.

### Task 9 (P6.5a): www-test CI node setup + Pillow-14 note (R-67)

**Files:** `.github/workflows/ci.yml`. Test: CI itself.

- [ ] Add a Node setup step so `tests/www/*.mjs` harnesses run in CI (currently py-only). Wire `node tests/www/strategy_harness.mjs` + `card_core_harness.mjs` into a CI job.
- [ ] Add a tracked note (TODO.md) for the Pillow-14 deprecation deadline (2027-10) with the specific deprecated call sites.
- [ ] Commit.

### Task 10 (P6.5b): release.sh schedule-card version banner (R-53)

**Files:** `tools/release/release.sh` (CARD_VERSION sync pattern). Test: run release.sh dry portion / inspect.

**Interfaces:** release.sh syncs `CARD_VERSION` in bundled cards but the schedule card's banner was frozen at v1.0.2a3 — the sed/grep pattern misses it.

- [ ] Fix the sync pattern to cover `dreame-a2-schedule-card.js`'s version string; verify all `www/*.js` CARD_VERSION strings update on a bump.
- [ ] Commit.

### Task 11 (P6.6): README productization

**Files:** `README.md`.

- [ ] Rewrite for a public g2408 owner: install via HACS, add integration (credentials + country), create ONE dashboard with `strategy: custom:dreame-a2-mower`, what entities appear, the experimental-features gate (default off), single-device support note, region status (EU-verified; others best-effort/report), privacy note (redacted diagnostics only), link to issue templates.
- [ ] Remove all showcase/SCP-deploy/personal content.
- [ ] Commit.

### Task 12 (P6.7 — SEPARABLE): Offline last-known persistence

> Gate: only if the user keeps this IN v2.0.0. Otherwise split to v2.0.1 and skip to Task 13.

**Files:** `state/snapshot.py` (extend persisted fields), the restore path, entity `available` props on the settings switches, `domain/render.py` + boot (persist/restore `_active_map_id`). Tests: restore-round-trip + availability.

- [ ] Decide the policy (record in the spec): (a) persist slowly-changing read-only values (consumables, totals, SIM, dock, firmware, device-wide time windows) across restart and show last-known; (b) config switches present last-known + fail only the write when offline (vs. stay unavailable); (c) persist `_active_map_id` so `render_base` produces the Overview base offline. Resolve the connectivity group ONE way (RSSI already persists via snapshot; make ssid/ip consistent) + a snapshot staleness policy so a stale value never reads as "connected".
- [ ] TDD each: restore round-trip test (persist → reload → value present); availability test (offline → switch shows last-known, write raises); active_map_id restore → render_base produces base.
- [ ] Live-verify while the mower is offline; corpus IDENTICAL.
- [ ] Commit.

### Task 13 (P6.8): Fresh-install walkthrough + v2.0.0

**Files:** none (release). Live HA.

- [ ] Whole-branch review (subagent-driven final review) of P6.
- [ ] On live HA: remove + re-add the integration from scratch (fresh config flow: creds validated, g2408 pinned, region); confirm entities populate, strategy dashboard renders, diagnostics download is clean of secrets.
- [ ] `tools/release/release.sh 2.0.0` (NOT a pre-release) — verify HACS sees v2.0.0 as Latest.
- [ ] Update memory + move P6 spec/plan to OLD/ per the doc-lifecycle rule.

## Self-review checklist (run before execution)

- Spec coverage: every P6-tagged finding (R-2, R-3, R-43, R-44, R-45, R-47, R-53, R-60, R-67) maps to a task ✓
- The two scope decisions (offline-persistence IN as separable P6.7; multi-device guard+document) are recorded and flagged for user confirmation ✓
- No task touches decode/state (corpus stays IDENTICAL) except P6.7, which gates persistence and must prove IDENTICAL ✓
