# Refactor v2 — P1 Dead-Code & Docs Purge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute Act III Phase P1 — remove code and docs built on superseded backend understanding (register R-9, R-21..R-28-partial, R-34a, R-47, R-57, R-61, R-62b), land the debunked-claims register in gated docs, and fold the archived § s6.2 wire-shape into inventory — leaving decode semantics byte-identical.

**Architecture:** Pure deletion/documentation phase per the approved target architecture (`docs/superpowers/specs/2026-07-02-refactor-v2-target-architecture.md` § 9 P1). No moves, no restructures (those are P3). The corpus-replay golden is the semantic gate: every task must replay IDENTICAL against the baseline.

**Tech Stack:** Python 3.13 (`/data/claude/homeassistant/.venv-vanilla/bin/python`), pytest, ruff (F401 gate), git.

## Global Constraints

- Branch: `refactor-v2/p1-dead-code` off current `main`. All tasks commit there; Task 8 fast-forward-merges to main, pushes, and releases via `tools/release/release.sh`.
- Venv: `/data/claude/homeassistant/.venv-vanilla/bin/python`, run from repo root. Full-suite baseline at branch time: run once and record (was 2653 passed / 5 skipped / 1 xfailed before the OQ-3 corpus excerpts landed; use the actual current count).
- **Corpus gate (every task):** `.venv-vanilla/bin/python -m tools.replay.corpus_replay --corpus-dir /data/claude/homeassistant/probe/logs --diff /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json` must print `IDENTICAL` (exit 0). P1 changes no decode semantics, ever.
- Stage by explicit path only (never `git add -A` — a concurrent process sweeps).
- Inventory rules (repo CLAUDE.md § Fact discipline): entity-inventory/inventory edits must pass `tools/inventory/inventory_gen.py --validate-only`; regenerate `g2408-canonical.md` after any inventory.yaml edit; superseded claims go to `OLD/ha-dreame-a2-mower-docs/inventory-history/<section>.md`, never inline-retracted.
- CLAUDE.md is load-bearing: any deletion this plan makes that is described in a CLAUDE.md table/paragraph MUST update that CLAUDE.md text in the same commit (rows are named per task).
- Deletions of dead-assumption code carry a one-line tombstone comment ONLY where a future reader would plausibly re-derive the dead idea (register rule: tombstone cites `docs/research/debunked-claims.md` § D-id, never restates the dead claim). Shim deletions need no tombstone.
- Evidence pointers for what to delete live in `/data/claude/homeassistant/refactor-2026-07-02/findings/track-1-archaeology.md` (T1-ids) — read the cited T1 entry before deleting; if the code has changed since Act I, re-verify with grep before acting.

---

## Task 1: Branch + unused-import purge + F401 CI gate (R-9/T2-2)

**Files:**
- Create: `ruff.toml` (repo root)
- Modify: `custom_components/dreame_a2_mower/**/*.py` (mechanical F401 fixes)
- Modify: `.github/workflows/ci.yml` (add ruff job)

**Interfaces:**
- Produces: the branch `refactor-v2/p1-dead-code` all later tasks commit to; a CI gate preventing import-header rot recurrence.

- [ ] **Step 1: Create the branch and record the baseline**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git checkout -b refactor-v2/p1-dead-code
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q 2>&1 | tail -1
```
Record the exact counts — they are the phase baseline.

- [ ] **Step 2: Install ruff and write the config**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/pip install -q ruff
```

Create `ruff.toml`:

```toml
# refactor-v2 P1 (R-9): F401 gate — import headers rotted to 640 unused imports
# after the 2026-05 decompositions. Only F401 is enforced repo-wide for now;
# broader lint adoption is a P3+ decision.
target-version = "py313"

[lint]
select = ["F401"]

[lint.per-file-ignores]
# Public re-export surfaces are intentional F401:
"custom_components/dreame_a2_mower/**/__init__.py" = ["F401"]
# Root re-export shims (die in P0-contract-rewrite/P3, not here):
"custom_components/dreame_a2_mower/sensor_*.py" = ["F401"]
"custom_components/dreame_a2_mower/select_*.py" = ["F401"]
"custom_components/dreame_a2_mower/switch_*.py" = ["F401"]
"custom_components/dreame_a2_mower/_camera_*.py" = ["F401"]
"custom_components/dreame_a2_mower/_render_*.py" = ["F401"]
"custom_components/dreame_a2_mower/_sensor_base.py" = ["F401"]
"custom_components/dreame_a2_mower/_select_base.py" = ["F401"]
"custom_components/dreame_a2_mower/_switch_base.py" = ["F401"]
"custom_components/dreame_a2_mower/wifi_*.py" = ["F401"]
"custom_components/dreame_a2_mower/map_decoder.py" = ["F401"]
"custom_components/dreame_a2_mower/protocol/schedule.py" = ["F401"]
# const.py re-exports mower.error_codes names until the P3 inversion (R-30):
"custom_components/dreame_a2_mower/const.py" = ["F401"]
```

- [ ] **Step 3: Preview, then auto-fix**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/ruff check custom_components/ --statistics | head -5
/data/claude/homeassistant/.venv-vanilla/bin/ruff check custom_components/ --fix
/data/claude/homeassistant/.venv-vanilla/bin/ruff check custom_components/
```
Expected: first check reports ~600+ F401; after `--fix`, zero findings. Eyeball `git diff --stat` — ONLY import lines may change. If any deleted import was a side-effect import (module registers something at import time), the test suite will catch it; none are expected.

- [ ] **Step 4: Run the suite + corpus gate**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q 2>&1 | tail -1
/data/claude/homeassistant/.venv-vanilla/bin/python -m tools.replay.corpus_replay --corpus-dir /data/claude/homeassistant/probe/logs --diff /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json | tail -1
```
Expected: baseline counts; `IDENTICAL`.

- [ ] **Step 5: Add the CI job**

In `.github/workflows/ci.yml`, add alongside the existing lint/test jobs:

```yaml
  ruff-f401:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.13"}
      - run: pip install ruff
      - run: ruff check custom_components/
```

- [ ] **Step 6: Commit**

```bash
git add ruff.toml .github/workflows/ci.yml custom_components/
git commit -m "chore(p1): strip 600+ rotted unused imports; add ruff F401 CI gate (R-9)"
```

---

## Task 2: Delete the 7 zero-importer shims + junk dotfiles (R-34a, R-62b)

**Files:**
- Delete: `custom_components/dreame_a2_mower/{sensor_session.py,_sensor_base.py,_select_base.py,_camera_lidar.py,_camera_views.py,_camera_wifi.py,_render_dotted.py}`
- Modify: `CLAUDE.md` (shim lists in § Rendering structure / § entities package name these files as "keep the shims" — update those sentences to record the 7 deletions and that remaining shims die in P3)

- [ ] **Step 1: Re-verify zero importers (evidence may have aged)**

```bash
for s in sensor_session _sensor_base _select_base _camera_lidar _camera_views _camera_wifi _render_dotted; do
  echo "$s: $(grep -rln "import $s\|from .$s\|from custom_components.dreame_a2_mower.$s\|from ..$s" custom_components/ tests/ tools/ 2>/dev/null | grep -v "dreame_a2_mower/$s.py" | wc -l) importers"; done
```
Expected: `0 importers` for all 7. Any non-zero → STOP, report, exclude that shim.

- [ ] **Step 2: Delete + clean dotfiles**

```bash
git rm custom_components/dreame_a2_mower/sensor_session.py custom_components/dreame_a2_mower/_sensor_base.py custom_components/dreame_a2_mower/_select_base.py custom_components/dreame_a2_mower/_camera_lidar.py custom_components/dreame_a2_mower/_camera_views.py custom_components/dreame_a2_mower/_camera_wifi.py custom_components/dreame_a2_mower/_render_dotted.py
git status --porcelain | grep '^??' | head   # untracked junk dotfiles (T2-14) — rm them (they are untracked; plain rm, no git)
```

- [ ] **Step 3: Update CLAUDE.md shim prose** — in § "Rendering structure" and the entities/camera/wifi shim paragraphs, replace the blanket "Keep the shims." statements with: the 7 files above are deleted (P1, zero importers — T2-7); the remaining shims are kept ONLY until the P3 import-path rewrite and the contract-test replacement, per the target-architecture § 2 deletions list.

- [ ] **Step 4: Suite + collect + corpus gate**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q 2>&1 | tail -1
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ --collect-only -q 2>&1 | tail -2
/data/claude/homeassistant/.venv-vanilla/bin/python -m tools.replay.corpus_replay --corpus-dir /data/claude/homeassistant/probe/logs --diff /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json | tail -1
```

- [ ] **Step 5: Commit**

```bash
git add -u custom_components/ && git add CLAUDE.md
git commit -m "chore(p1): delete 7 zero-importer re-export shims + junk dotfiles (R-34a, T2-7)"
```

---

## Task 3: Dead code from superseded understanding (R-22, R-23, R-24, R-61)

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client/_oss.py` (delete `fetch_wifi_map` + `list_wifi_candidates` if it is fetch_wifi_map-only — verify)
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py` (delete `fetch_locn`)
- Modify: `custom_components/dreame_a2_mower/mower/actions.py` (delete `REQUEST_WIFI_MAP` enum member + dispatch row)
- Modify: `custom_components/dreame_a2_mower/_settings_writes.py` (delete the `map_id=None → _active_map_id` fallback)
- Modify: `custom_components/dreame_a2_mower/coordinator/_property_apply.py` (T1-12: BT-trigger comment)
- Modify: `CLAUDE.md` (cloud-client table row for `_oss.py`/`_fetchers.py` mention `fetch_wifi_map`/`fetch_locn`; the Refresher-cadence note says fetch_locn is "kept (unscheduled) for a future dock-location entity" — delete that sentence)
- Modify: affected tests (grep-drive: `tests/protocol/test_cloud_client_package.py` uses fetch_wifi_map; REQUEST_WIFI_MAP has test-only callers — delete those test cases)

Per-deletion procedure (repeat for each of the four code items):

- [ ] **Step 1: Re-verify deadness** — grep all callers in `custom_components/` (excluding the definition); expected zero. For `_settings_writes.py`: verify all call sites pass `map_id` explicitly (`grep -n "write_settings\|_settings_writes" custom_components/ -r`).
- [ ] **Step 2: Delete the code.** Where a future reader might re-derive the dead idea, leave a tombstone, e.g. in `mower/actions.py` at the former member's location:

```python
# REQUEST_WIFI_MAP (s6.aiid=4) deleted 2026-07-02 — dead belief; see
# docs/research/debunked-claims.md § D19.
```

and in `coordinator/_property_apply.py` replace the BT-trigger comment with a correct one citing § D1.

- [ ] **Step 3: Update the tests** that exercised the deleted symbol (delete those test functions; do not weaken unrelated asserts).
- [ ] **Step 4: Update the CLAUDE.md rows** named above in the same commit.
- [ ] **Step 5: Suite + corpus gate** (same two commands as Task 2 Step 4). Expected: passed count drops only by the deleted test functions; `IDENTICAL`.
- [ ] **Step 6: Commit**

```bash
git add -u custom_components/ tests/ && git add CLAUDE.md
git commit -m "chore(p1): delete LOCN/wifi-map-request/single-map dead paths (R-22/23/24/61, D18/D19)"
```

---

## Task 4: Stale annotations & doc rows (R-21, R-25, R-26, R-47)

**Files:**
- Modify: `CLAUDE.md` (Refresher-cadence table: delete the `_poll_slow_properties | 1 h` row — the method was removed 2026-05-26, T1-3; re-verify `grep -rn "def _poll_slow_properties" custom_components/` is empty first)
- Modify: `custom_components/dreame_a2_mower/mower/state.py` (position_lat/lon "Source: LOCN" docstrings → "Source: location/getRecords via _refresh_gps" — T1-7)
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml` (first_mowing_date row: "(MIHIS)" label → archive-sourced per code; add a `verifications:` record per CLAUDE.md fact-discipline, status `verified`, evidence: `coordinator/_core.py` archive-seed lines — T1-8/D6)
- Modify: `custom_components/dreame_a2_mower/_settings_writes.py` (T1-13: replace the `/tmp/probe_current_state.py` evidence citation with the inventory § id it proved)
- Modify: `README.md` + docstrings (R-47/T4-8): dev-box absolute paths (`/data/claude/...`) and citations of the archived `docs/research/g2408-protocol.md` — repoint to `inventory.yaml` § ids or the OLD path; sweep list comes from `grep -rn "docs/research/g2408-protocol.md" custom_components/ tests/ README.md` (code-comment cites are allowed to stay per the OLD-mirror convention — fix only the ones asserting it is a live doc) and `grep -rn "/data/claude" README.md docs/ custom_components/`.

- [ ] **Step 1: Make the edits above** (each is a 1-5 line change; re-verify each claim with the named grep before editing).
- [ ] **Step 2: Inventory hygiene**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory tests/tools -q 2>&1 | tail -1
```

- [ ] **Step 3: Suite + corpus gate; commit**

```bash
git add CLAUDE.md README.md custom_components/dreame_a2_mower/mower/state.py custom_components/dreame_a2_mower/entity-inventory.yaml custom_components/dreame_a2_mower/_settings_writes.py
git commit -m "docs(p1): fix stale-era annotations — cadence row, LOCN sources, MIHIS label, dev-box cites (R-21/25/26/47)"
```
(Include any additional docstring files the R-47 sweep touched.)

---

## Task 5: Test-suite dead weight (R-57/T7-13/14/15)

**Files:**
- Modify/Delete: the 4 tests skipping on `dreame.types` (find: `grep -rn "dreame.types" tests/` — module never existed in this repo, lifted from legacy in commit 2bbf3260; DELETE the test functions, and the whole file if empty after)
- Delete: the 2 docstring-only placeholder test files that collect zero tests (find: `grep -rln "placeholder" tests/ | xargs -I{} sh -c '/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest {} --collect-only -q 2>&1 | tail -1 | grep -q "no tests" && echo {}'` — cross-check against T7-15 in `findings/track-7-tests.md`)
- Modify: the 7 duplicate test names across file pairs (T7-13 lists them) — rename the newer duplicate to describe its actual distinct scenario; if genuinely identical, delete one.

- [ ] **Step 1: Locate each item via the greps above; cross-check T7-13/14/15 for the exact lists.**
- [ ] **Step 2: Delete/rename.**
- [ ] **Step 3: Verify skip-count drops** — full suite: expected `N passed, 1 skipped` (5 baseline skips − 4 dreame.types) unless the OQ-3 excerpts changed counts; collect-only shows no duplicate-name warnings.
- [ ] **Step 4: Corpus gate; commit**

```bash
git add -u tests/
git commit -m "test(p1): drop never-existed-module skips, empty placeholders, duplicate names (R-57)"
```

---

## Task 6: Docs lifecycle — move shipped specs/plans to OLD (R-27/T1-9)

**Files:**
- Move OUT of tree: all `docs/superpowers/specs/2026-06-*.md` (11 files) and `docs/superpowers/plans/2026-06-*.md` (9 files) → `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/<specs|plans>/<same-name>`
- KEEP in-tree: the three `2026-07-02-*` files (active program) — design, act1-p0 plan, target architecture, this plan.
- Modify: any in-tree references to the moved files (find: `grep -rn "docs/superpowers/2026-06\|superpowers/specs/2026-06\|superpowers/plans/2026-06" --include='*.md' --include='*.py' . | grep -v OLD`) — repoint to the OLD absolute path.

- [ ] **Step 1: Copy each file to the OLD mirror path (create dirs), then `git rm` the in-tree copy.**
- [ ] **Step 2: Repoint references** found by the grep (code comments may keep the old relative path per the OLD-mirror convention; fix only doc-navigation links).
- [ ] **Step 3: Verify** — `ls docs/superpowers/specs docs/superpowers/plans` shows only 2026-07-02 files; grep from Step 0 returns nothing outside OLD/code-comments; suite green (docs-only change).
- [ ] **Step 4: Commit**

```bash
git add -u docs/ && git add <any repointed files>
git commit -m "docs(p1): archive 20 shipped 2026-06 specs/plans to OLD (R-27, canonicity rule)"
```

---

## Task 7: Debunked-claims register + § s6.2 fold (spec § Negative-knowledge register)

**Files:**
- Create: `docs/research/debunked-claims.md`
- Modify: `docs/research/knowledge-gaps.md` (link the register from its header)
- Modify: `CLAUDE.md` § Fact discipline (one paragraph: the register exists, agents treat it as a blocklist, tombstones cite § D-ids)
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (fold the § s6.2 PRE-family wire-shape from the ARCHIVED doc `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/research/g2408-protocol.md` § s6.2 into the existing s6.2 inventory entries as `semantic:`/`verifications:` content with the original evidence tags; then repoint the entry's `protocol_doc:` field — and the 3 `docs:` fields in `entity-inventory.yaml` — from the OLD doc path to the now-self-contained inventory section)
- Create (append): `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/inventory-history/` entries only if the fold supersedes anything (not expected — the fold adds, it does not retract)

- [ ] **Step 1: Build `docs/research/debunked-claims.md`** from `/data/claude/homeassistant/refactor-2026-07-02/debunked-register-v1.md` (D1–D20, verbatim table) with this banner prepended:

```markdown
# Debunked claims register (negative knowledge — D-ids are citable)

> ⚠️ Every claim in this table is FALSE. This file exists so greps and future
> sessions find the debunking WITH the claim. Rules: (1) never copy a claim out
> of this table as fact; (2) tombstones and retractions cite "debunked-claims.md
> § D<n>"; (3) the truth column CITES inventory ids, it never restates values;
> (4) additions go through the inventory retraction flow (CLAUDE.md § Fact
> discipline) — this register indexes it, it does not replace it.
```

- [ ] **Step 2: Cross-link** — knowledge-gaps.md header + the CLAUDE.md fact-discipline paragraph.
- [ ] **Step 3: The s6.2 fold** per the file list above. Then:

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/findings_fold_check.py
```
Expected: valid; canonical regenerated (commit it); fold-check green.

- [ ] **Step 4: Suite + corpus gate; commit**

```bash
git add docs/research/debunked-claims.md docs/research/knowledge-gaps.md CLAUDE.md custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml docs/research/inventory/generated/g2408-canonical.md
git commit -m "docs(p1): land debunked-claims register (D1-D20) + fold s6.2 wire-shape into inventory"
```

---

## Task 8: Phase wrap — merge, release, live verification

- [ ] **Step 1: Full gate battery on the branch**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q 2>&1 | tail -1
/data/claude/homeassistant/.venv-vanilla/bin/ruff check custom_components/
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python -m tools.replay.corpus_replay --corpus-dir /data/claude/homeassistant/probe/logs --diff /data/claude/homeassistant/refactor-2026-07-02/goldens/baseline-v1.0.31a5.json | tail -1
```
All green + `IDENTICAL`.

- [ ] **Step 2: Merge + push**

```bash
git checkout main && git pull --rebase origin main && git merge --ff-only refactor-v2/p1-dead-code && git push origin main
```
(If ff-only fails because main moved, rebase the branch first.)

- [ ] **Step 3: Release** via `tools/release/release.sh` (it bumps, tags, pushes, creates the GitHub Release, refreshes HACS; respects the alpha digit-boundary ladder). NEVER a manual `gh release create`.

- [ ] **Step 4: Live verification** — HACS-update the live instance, reload, then via the HA MCP: integration loads clean; spot-check that no entity went unexpectedly missing (the P1 scope deletes NO live entities — op=10/12 buttons are P4 scope (R-28), NOT this phase); `system_log/list` free of dreame errors.

- [ ] **Step 5: Bookkeeping** — append phase result to `/data/claude/homeassistant/refactor-2026-07-02/README.md` status header; update the progress ledger; delete the now-merged branch.

---

## Self-review record

- **Register coverage:** P1-tagged rows all appear: R-9 (T1), R-34a+R-62b (T2), R-22/23/24/61 (T3), R-21/25/26/47 (T4), R-57 (T5), R-27 (T6), register+fold (T7). R-1 was executed early (done). R-28 explicitly deferred to P4 (live entities — noted in Task 8 Step 4).
- **Placeholder scan:** grep lists are the discovery mechanism by design (counts drift); every task names its exact files/symbols plus a re-verify step. No TBDs.
- **Consistency:** corpus gate command identical everywhere; branch name consistent; CLAUDE.md lockstep edits named in the same task as their code deletion.
