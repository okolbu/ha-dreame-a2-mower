# tools/ Reorganization + Self-Documenting README — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `tools/` into five domain subdirectories, make each tool self-declare its domain/run-by/when so a generated README and a `--help` banner never go stale, and evict dead/one-off scripts to `OLD/`.

**Architecture:** Five package subdirs (`inventory/ probes/ state_machine/ session/ release/`). Each entry-point tool carries a `TOOL_META` literal (or a `# tool-meta:` header for shell). A shared `_toolmeta.py` injects a `--help` banner; `gen_readme.py` ast-extracts the metadata and regenerates `README.md`; `test_readme_in_sync.py` CI-gates it. Nesting tools one level deeper breaks every `parent.parent`/`parents[1]` repo-root computation, so each moved tool's `__file__` depth is corrected.

**Tech Stack:** Python 3.13 (venv at `/data/claude/homeassistant/.venv-vanilla`), pytest, argparse, `ast`. Repo root: `/data/claude/homeassistant/ha-dreame-a2-mower`.

**Spec:** `docs/superpowers/specs/2026-06-05-tools-reorg-readme-design.md`

---

## Conventions for every task

- **Run pytest with the vanilla venv:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest …` (see `reference_test_env_setup`; system python is broken).
- **All `git`/`pytest` commands run from the repo root** `/data/claude/homeassistant/ha-dreame-a2-mower`.
- **Stage by explicit path** in every commit (`git add <paths>`), never `git add -A` — a second process commits to this repo and `-A` would absorb its changes (`feedback_concurrent_git_sweeps`).
- **Do not push or cut a release.** These are tooling changes; no version bump (`feedback_cleanup_push_cadence`).
- **`git mv` for in-repo moves** (preserves history). **Evictions to `OLD/` are out-of-repo** (`OLD/` is a sibling of the repo), so use plain `mv` then stage the deletion.

---

## TOOL_META reference (used in Tasks 4–9)

Each **entry-point** tool gets this literal near the top of the file (after the module docstring, before code). Helper/lib modules (`wire_census_lib`, the four `state_machine_audit_*` helpers, everything in `_rebuild_session_lib/`) get **no** `TOOL_META` — `gen_readme.py` skips any file without one.

```python
# inventory/inventory_gen.py
TOOL_META = {"domain": "inventory", "run_by": "ci",
    "when": "Every CI build (--validate-only); locally before shipping an inventory change.",
    "summary": "Generate canonical inventory docs from inventory.yaml and validate its schema."}

# inventory/inventory_audit.py
TOOL_META = {"domain": "inventory", "run_by": "ci",
    "when": "Every CI build; locally before shipping a fact-heavy change.",
    "summary": "Cross-check inventory.yaml for internal contradictions and value-catalog gaps."}

# inventory/entity_inventory_audit.py
TOOL_META = {"domain": "inventory", "run_by": "ci",
    "when": "Every CI build; after adding or changing an entity.",
    "summary": "Verify entity-inventory.yaml covers every integration entity class."}

# inventory/audit_outstanding_retractions.py
TOOL_META = {"domain": "inventory", "run_by": "ci",
    "when": "Every CI build (notice-only); when reviewing retraction debt.",
    "summary": "List inventory retractions that lack a re-verified replacement claim."}

# inventory/journal_completeness_check.py
TOOL_META = {"domain": "inventory", "run_by": "owner",
    "when": "When auditing the research journal for analysis not promoted into inventory.yaml.",
    "summary": "Flag research-journal paragraphs that were never folded into inventory.yaml."}

# inventory/wire_census.py
TOOL_META = {"domain": "inventory", "run_by": "owner",
    "when": "After a new probe capture lands, to regenerate the wire census and find unparked values.",
    "summary": "Regenerate docs/research/wire-census.json and report wire values missing from inventory."}

# probes/inventory_probe.py
TOOL_META = {"domain": "probes", "run_by": "owner",
    "when": "When verifying an inventory claim against live cloud property values (read-only).",
    "summary": "Read-only Dreame-cloud probe that dumps device properties for inventory verification."}

# probes/probe_cruise_to_point.py
TOOL_META = {"domain": "probes", "run_by": "owner",
    "when": "When reverse-engineering cruise-to-point (op=109) payloads. WRITES to the live device.",
    "summary": "Probe candidate cruise-to-point command payload shapes on the live g2408."}

# probes/probe_add_maintenance_point.py
TOOL_META = {"domain": "probes", "run_by": "owner",
    "when": "When reverse-engineering maintenance-point map edits. WRITES to the live device.",
    "summary": "Probe candidate map-edit payloads for adding a maintenance point."}

# probes/probe_pre_write.py
TOOL_META = {"domain": "probes", "run_by": "owner",
    "when": "When testing whether CFG.PRE (mowing efficiency) is device-writable. WRITES to the live device.",
    "summary": "Probe whether CFG.PRE is writable on the g2408 vs cloud-cache-only."}

# state_machine/state_machine_audit.py
TOOL_META = {"domain": "state_machine", "run_by": "owner",
    "when": "When verifying entity value-source wiring after coordinator/entity changes.",
    "summary": "Audit how every entity sources its value (sourcing/idle/reboot/orphan-field checks)."}

# session/rebuild_session.py
TOOL_META = {"domain": "session", "run_by": "owner",
    "when": "When reconstructing a session archive from probe logs (dev box only).",
    "summary": "End-to-end rebuild of a session archive from MQTT probe logs."}

# session/state_partition.py
TOOL_META = {"domain": "session", "run_by": "owner",
    "when": "When verifying a session archive's time breakdown against probe-log ground truth.",
    "summary": "Check a session JSON's time partition against probe-log evidence."}
```

Shell headers (replace nothing else; insert below the existing shebang+title comment):

```bash
# tools/release.sh
# tool-meta: domain=release run_by=maintainer
# tool-when: After pushing integration commits, to cut a HACS-visible release.
# tool-summary: Bump version, tag, push, create the GitHub Release, and refresh HACS.

# tools/promote-latest.sh
# tool-meta: domain=release run_by=maintainer
# tool-when: When GitHub demoted the newest release off "Latest".
# tool-summary: Force the highest-version release to be marked Latest (not prerelease).
```

---

## `__file__` depth-fix reference (used in Tasks 4–8)

Every moved tool gains one directory level, so each repo-root computation needs **+1 level**. Exact edits:

| File (after move) | Old | New |
|---|---|---|
| `inventory/audit_outstanding_retractions.py:28` | `Path(__file__).resolve().parents[1]` | `Path(__file__).resolve().parents[2]` |
| `inventory/inventory_gen.py:23` | `Path(__file__).resolve().parents[1]` | `Path(__file__).resolve().parents[2]` |
| `inventory/inventory_audit.py:29` | `Path(__file__).resolve().parents[1]` | `Path(__file__).resolve().parents[2]` |
| `inventory/entity_inventory_audit.py:36` | `pathlib.Path(__file__).resolve().parent.parent` | `pathlib.Path(__file__).resolve().parent.parent.parent` |
| `inventory/wire_census.py:21` | `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` | `os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` |
| `probes/inventory_probe.py:21` | `Path(__file__).resolve().parents[1]` | `Path(__file__).resolve().parents[2]` |
| `probes/probe_pre_write.py:114` | `Path(__file__).resolve().parent.parent` | `Path(__file__).resolve().parent.parent.parent` |
| `probes/probe_add_maintenance_point.py:67` | `Path(__file__).resolve().parent.parent` | `Path(__file__).resolve().parent.parent.parent` |
| `probes/probe_cruise_to_point.py:87` | `Path(__file__).resolve().parent.parent` | `Path(__file__).resolve().parent.parent.parent` |
| `state_machine/state_machine_audit_discover.py:19` | `Path(__file__).resolve().parent.parent` | `Path(__file__).resolve().parent.parent.parent` |
| `state_machine/state_machine_audit_fake_coord.py:23` | `Path(__file__).resolve().parent.parent` | `Path(__file__).resolve().parent.parent.parent` |
| `state_machine/state_machine_audit_checks.py:52` | `Path(__file__).resolve().parent.parent / "tests"` | `Path(__file__).resolve().parent.parent.parent / "tests"` |
| `state_machine/state_machine_audit_checks.py:268` | `Path(__file__).resolve().parent.parent / "tests"` | `Path(__file__).resolve().parent.parent.parent / "tests"` |
| `session/rebuild_session.py:25` | `Path(__file__).resolve().parent.parent` | `Path(__file__).resolve().parent.parent.parent` |
| `session/state_partition.py:79` | `Path(__file__).resolve().parent.parent` | `Path(__file__).resolve().parent.parent.parent` |

**No change** to `state_machine/state_machine_audit.py:22` (`Path(__file__).resolve().parent / "state_machine_audit_expectations.yaml"`) — the yaml moves into the same subdir, so `parent` stays correct.

`wire_census.py:18` (`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`) and `:22` (`_DEFAULT_LOG_DIR = os.path.dirname(_REPO)`) need **no** change — `:18` adds the tool's own (new) dir for the sibling `from wire_census_lib import …`, and `:22` is relative to the now-corrected `_REPO`.

---

### Task 1: Evict dead + one-off tools to `OLD/`

**Files:**
- Move out (delete from repo): `tools/retrofit_local_legs.py`, `tools/migrate_sessions_to_track.py`, `tools/backfill_wifi_samples.py`, `tools/recover_sessions.py`, `tools/install_recovered.py`, `tools/cleanup_entity_orphans.py`, `tools/recovered_sessions/` (dir, 27 JSONs)
- Move out (tests): `tests/tools/test_migrate_sessions.py`, `tests/tools/test_backfill_wifi_samples.py`
- Modify: `custom_components/dreame_a2_mower/archive/session.py:260`

- [ ] **Step 1: Create the OLD subtree and move the tools + tests out**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
OLD=/data/claude/homeassistant/OLD/ha-dreame-a2-mower-tools
mkdir -p "$OLD/tools" "$OLD/tests/tools"
mv tools/retrofit_local_legs.py tools/migrate_sessions_to_track.py \
   tools/backfill_wifi_samples.py tools/recover_sessions.py \
   tools/install_recovered.py tools/cleanup_entity_orphans.py "$OLD/tools/"
mv tools/recovered_sessions "$OLD/tools/"
mv tests/tools/test_migrate_sessions.py tests/tools/test_backfill_wifi_samples.py "$OLD/tests/tools/"
```

- [ ] **Step 2: Redirect the runtime message that names a moved tool**

Edit `custom_components/dreame_a2_mower/archive/session.py` line 260.
Old:
```python
                "Run tools/recover_sessions.py to retro-fit, or wipe and rebuild.",
```
New:
```python
                "Run tools/session/rebuild_session.py to rebuild, or wipe and rebuild.",
```

- [ ] **Step 3: Verify no in-tree CODE/CI/test reference to any evicted tool remains**

Run:
```bash
grep -rnE 'tools/(recover_sessions|install_recovered|retrofit_local_legs|migrate_sessions_to_track|backfill_wifi_samples|cleanup_entity_orphans)|tools\.(migrate_sessions_to_track|backfill_wifi_samples|recover_sessions|install_recovered|cleanup_entity_orphans|retrofit_local_legs)' \
  custom_components tests .github tools CLAUDE.md
```
Expected: **no output** (only `docs/` may still mention them as historical breadcrumbs — those are handled in Task 10). If `tests/protocol/data/sessions/short.json` appears, ignore it — it is fixture data containing the string `rec_…`, not a reference.

- [ ] **Step 4: Run the suite to confirm green after eviction**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q`
Expected: PASS (the two evicted tests are gone; nothing imports the evicted tools).

- [ ] **Step 5: Commit**

```bash
git add tools tests/tools custom_components/dreame_a2_mower/archive/session.py
git commit -m "chore(tools): evict dead + one-off scripts to OLD/

retrofit_local_legs (dead), migrate_sessions_to_track, backfill_wifi_samples,
recover_sessions, install_recovered, cleanup_entity_orphans + their tests move
to OLD/ha-dreame-a2-mower-tools/. Redirect the recover_sessions runtime hint to
rebuild_session.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Add the `_toolmeta.py` `--help` banner helper

**Files:**
- Create: `tools/_toolmeta.py`
- Test: `tests/tools/test_toolmeta.py`

- [ ] **Step 1: Write the failing test**

Create `tests/tools/test_toolmeta.py`:
```python
from __future__ import annotations

import argparse

from tools._toolmeta import add_to_parser, format_banner

META = {
    "domain": "inventory",
    "run_by": "ci",
    "when": "Every CI build.",
    "summary": "Do the thing.",
}


def test_format_banner_contains_all_fields():
    text = format_banner(META)
    assert "inventory" in text
    assert "ci" in text
    assert "Every CI build." in text
    assert "Do the thing." in text


def test_add_to_parser_puts_banner_in_help():
    parser = argparse.ArgumentParser(description="x")
    add_to_parser(parser, META)
    help_text = parser.format_help()
    assert "Domain: inventory" in help_text
    assert "Run by: ci" in help_text
    assert "Do the thing." in help_text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_toolmeta.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools._toolmeta'`.

- [ ] **Step 3: Implement `tools/_toolmeta.py`**

```python
"""Shared --help banner derived from a tool's TOOL_META.

Entry-point tools declare a module-level TOOL_META dict and call
add_to_parser(parser, TOOL_META) so `--help` prints their domain, who runs
them, and when. The same dict feeds gen_readme.py, so help and README never
drift.
"""
from __future__ import annotations

import argparse

_RUN_BY_LABEL = {"ci": "ci", "owner": "owner", "maintainer": "maintainer"}


def format_banner(meta: dict) -> str:
    """Return a 3-line banner: domain/run-by, when, summary."""
    return (
        f"Domain: {meta['domain']}   Run by: {_RUN_BY_LABEL[meta['run_by']]}\n"
        f"When: {meta['when']}\n"
        f"{meta['summary']}"
    )


def add_to_parser(parser: argparse.ArgumentParser, meta: dict) -> None:
    """Append the metadata banner to a parser's --help epilog."""
    banner = format_banner(meta)
    parser.epilog = f"{banner}\n\n{parser.epilog}" if parser.epilog else banner
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_toolmeta.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add tools/_toolmeta.py tests/tools/test_toolmeta.py
git commit -m "feat(tools): add _toolmeta --help banner helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Create the five subdir packages (empty, with `__init__.py`)

**Files:**
- Create: `tools/inventory/__init__.py`, `tools/probes/__init__.py`, `tools/state_machine/__init__.py`, `tools/session/__init__.py` (each empty). `tools/release/` is created by the move in Task 8 and needs no `__init__.py` (shell only, never imported).

- [ ] **Step 1: Create the package dirs**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
for d in inventory probes state_machine session; do
  mkdir -p "tools/$d"
  : > "tools/$d/__init__.py"
done
```

- [ ] **Step 2: Confirm they import**

Run:
```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -c "import tools.inventory, tools.probes, tools.state_machine, tools.session; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add tools/inventory/__init__.py tools/probes/__init__.py tools/state_machine/__init__.py tools/session/__init__.py
git commit -m "chore(tools): create domain subdir packages

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Move the `inventory/` domain

**Files:**
- Move: `tools/{inventory_gen,inventory_audit,entity_inventory_audit,audit_outstanding_retractions,journal_completeness_check,wire_census,wire_census_lib}.py` → `tools/inventory/`
- Modify (depth + TOOL_META): the six entry points above (not `wire_census_lib`)
- Modify (CI): `.github/workflows/ci.yml` lines 167, 170, 180, 183, 190
- Modify (tests): `tests/tools/test_wire_census.py` (lines 3, 46, 92, 125)
- Modify (CLAUDE.md): `tools/inventory_audit.py` reference

- [ ] **Step 1: git-mv the seven files**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git mv tools/inventory_gen.py tools/inventory_audit.py tools/entity_inventory_audit.py \
       tools/audit_outstanding_retractions.py tools/journal_completeness_check.py \
       tools/wire_census.py tools/wire_census_lib.py tools/inventory/
```

- [ ] **Step 2: Fix `__file__` depths** per the depth-fix reference above for: `inventory/inventory_gen.py:23`, `inventory/inventory_audit.py:29`, `inventory/entity_inventory_audit.py:36`, `inventory/audit_outstanding_retractions.py:28`, `inventory/wire_census.py:21`. (`journal_completeness_check.py` has no repo-root computation in the reference table — leave it; confirm with `grep -n '__file__' tools/inventory/journal_completeness_check.py` and apply +1 only if a `parent.parent`/`parents[1]` appears.)

- [ ] **Step 3: Add `TOOL_META`** (from the TOOL_META reference) to each of the six entry points, and wire the banner. For each tool that builds an `argparse.ArgumentParser`, add after the parser is created:
```python
from tools._toolmeta import add_to_parser  # top-of-file import
...
add_to_parser(parser, TOOL_META)
```
`inventory_gen.py`, `inventory_audit.py`, `entity_inventory_audit.py`, `audit_outstanding_retractions.py`, `journal_completeness_check.py`, and `wire_census.py` all build a parser (`wire_census.py:33`, `inventory_gen.py:327`, etc.) — wire all six. `wire_census_lib.py` gets nothing.

- [ ] **Step 4: Update CI paths** in `.github/workflows/ci.yml`:
  - `167: python tools/entity_inventory_audit.py` → `python tools/inventory/entity_inventory_audit.py`
  - `170: python tools/inventory_gen.py --validate-only` → `python tools/inventory/inventory_gen.py --validate-only`
  - `180: python tools/inventory_audit.py` → `python tools/inventory/inventory_audit.py`
  - `183: python tools/inventory_audit.py --consistency` → `python tools/inventory/inventory_audit.py --consistency`
  - `190: python tools/audit_outstanding_retractions.py` → `python tools/inventory/audit_outstanding_retractions.py`

- [ ] **Step 5: Update test imports + subprocess path** in `tests/tools/test_wire_census.py`:
  - lines 3, 46, 92: `from tools.wire_census_lib import …` → `from tools.inventory.wire_census_lib import …`
  - line 125: `[sys.executable, "tools/wire_census.py", …]` → `[sys.executable, "tools/inventory/wire_census.py", …]`

- [ ] **Step 6a: Fix the breaking bare import in `tests/inventory/test_wire_coverage.py`** — line 16 does `from wire_census_lib import check_coverage` resolved via line 15's `sys.path.insert(0, os.path.join(_REPO, "tools"))`. After the move, change **line 15**:
  `sys.path.insert(0, os.path.join(_REPO, "tools"))` → `sys.path.insert(0, os.path.join(_REPO, "tools", "inventory"))`
  (Leaves the bare `from wire_census_lib import …` working. This is a real break — `tests/inventory` would error on collection otherwise.)

- [ ] **Step 6b: Update doc-string hint strings (non-breaking, for accuracy)**:
  - `tests/inventory/test_wire_coverage.py:45` text `tools/wire_census.py --seed` → `tools/inventory/wire_census.py --seed`
  - `tests/inventory/test_control_entities_wired.py:15` comment `tools/entity_inventory_audit.py` → `tools/inventory/entity_inventory_audit.py`

- [ ] **Step 7: Update CLAUDE.md** — change `tools/inventory_audit.py` to `tools/inventory/inventory_audit.py` (the "Related files" line near the bottom).

- [ ] **Step 8: Run the inventory + tools tests and the moved tools directly**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory tests/tools -q
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_audit.py --consistency
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/audit_outstanding_retractions.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/wire_census.py --help
```
Expected: tests PASS; `inventory_gen --validate-only` prints `ok: inventory schema valid`; `inventory_audit` runs clean; `wire_census.py --help` shows the `Domain: inventory   Run by: owner` banner.

- [ ] **Step 9: Commit**

```bash
git add tools/inventory tests/tools/test_wire_census.py tests/inventory/test_wire_coverage.py \
        tests/inventory/test_control_entities_wired.py .github/workflows/ci.yml CLAUDE.md
git commit -m "refactor(tools): move inventory gates into tools/inventory/

Fix __file__ repo-root depth (+1), add TOOL_META + --help banner, update CI
paths, wire_census test import/subprocess paths, and CLAUDE.md.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Move the `probes/` domain

**Files:**
- Move: `tools/{inventory_probe,probe_cruise_to_point,probe_add_maintenance_point,probe_pre_write}.py` → `tools/probes/`
- Modify (depth + TOOL_META): all four (no CI/test importers — these are manual owner tools)

- [ ] **Step 1: git-mv the four files**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git mv tools/inventory_probe.py tools/probe_cruise_to_point.py \
       tools/probe_add_maintenance_point.py tools/probe_pre_write.py tools/probes/
```

- [ ] **Step 2: Fix `__file__` depths** per the reference: `probes/inventory_probe.py:21`, `probes/probe_pre_write.py:114`, `probes/probe_add_maintenance_point.py:67`, `probes/probe_cruise_to_point.py:87`.

- [ ] **Step 3: Add `TOOL_META`** (from the reference) to all four, and `add_to_parser(parser, TOOL_META)` where a parser exists (`inventory_probe`, `probe_cruise_to_point`, `probe_pre_write` build parsers; `probe_add_maintenance_point` — add the import+call only if it builds one, else just the dict).

- [ ] **Step 4: Verify imports + banners (do NOT execute — these hit the live device)**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/inventory_probe.py --help
/data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/probe_pre_write.py --help
/data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/probe_cruise_to_point.py --help
/data/claude/homeassistant/.venv-vanilla/bin/python -c "import ast; [ast.parse(open(f).read()) for f in ['tools/probes/probe_add_maintenance_point.py']]; print('parses ok')"
```
Expected: each `--help` exits 0 and shows `Domain: probes   Run by: owner` with the `WRITES to the live device` note where applicable; the ast parse prints `parses ok`. **Never run these without `--help`** — they send commands to the mower.

- [ ] **Step 5: Commit**

```bash
git add tools/probes
git commit -m "refactor(tools): move cloud/device probes into tools/probes/

Fix __file__ depth (+1), add TOOL_META + --help banner.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Move the `state_machine/` domain

**Files:**
- Move: `tools/state_machine_audit.py`, `tools/state_machine_audit_checks.py`, `tools/state_machine_audit_discover.py`, `tools/state_machine_audit_fake_coord.py`, `tools/state_machine_audit_render.py`, `tools/state_machine_audit_expectations.yaml` → `tools/state_machine/`
- Modify (depth): `state_machine_audit_discover.py:19`, `state_machine_audit_fake_coord.py:23`, `state_machine_audit_checks.py:52,268`
- Modify (inter-tool imports): `state_machine_audit.py`, `state_machine_audit_checks.py`, `state_machine_audit_render.py`
- Modify (TOOL_META): `state_machine_audit.py` only
- Modify (tests): `tests/audit/test_checks.py`, `tests/audit/test_render.py`, `tests/audit/test_discover.py`, `tests/audit/test_discover_class_entities.py`, `tests/audit/test_fake_coord.py`

- [ ] **Step 1: git-mv the six files**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git mv tools/state_machine_audit.py tools/state_machine_audit_checks.py \
       tools/state_machine_audit_discover.py tools/state_machine_audit_fake_coord.py \
       tools/state_machine_audit_render.py tools/state_machine_audit_expectations.yaml \
       tools/state_machine/
```

- [ ] **Step 2: Fix `__file__` depths** per the reference: `state_machine/state_machine_audit_discover.py:19`, `state_machine/state_machine_audit_fake_coord.py:23`, `state_machine/state_machine_audit_checks.py:52` and `:268`. Leave `state_machine_audit.py:22` unchanged (yaml is a sibling).

- [ ] **Step 3: Update inter-tool imports** (the family imports itself via absolute `tools.` paths). In `tools/state_machine/`:
  - `state_machine_audit.py:12` `from tools.state_machine_audit_checks import (` → `from tools.state_machine.state_machine_audit_checks import (`
  - `state_machine_audit.py:20` `from tools.state_machine_audit_discover import discover_entities` → `from tools.state_machine.state_machine_audit_discover import discover_entities`
  - `state_machine_audit_render.py:4` `from tools.state_machine_audit_discover import EntityDescriptor, classify_holder` → `from tools.state_machine.state_machine_audit_discover import EntityDescriptor, classify_holder`
  - `state_machine_audit_render.py:5` `from tools.state_machine_audit_checks import Result` → `from tools.state_machine.state_machine_audit_checks import Result`
  - `state_machine_audit_checks.py:209` `from tools.state_machine_audit_discover import classify_holder` → `from tools.state_machine.state_machine_audit_discover import classify_holder`

- [ ] **Step 4: Add `TOOL_META`** to `state_machine/state_machine_audit.py` and wire `add_to_parser(parser, TOOL_META)` after its parser is built. The four helper modules get nothing.

- [ ] **Step 5: Update test imports** in `tests/audit/`:
  - `test_checks.py` lines 6, 24, 33, 34, 79, 129, 198: `from tools.state_machine_audit_checks import …` → `from tools.state_machine.state_machine_audit_checks import …`; line 33 `from tools.state_machine_audit_discover import EntityDescriptor` → `from tools.state_machine.state_machine_audit_discover import EntityDescriptor`
  - `test_render.py` lines 4, 5, 6: `state_machine_audit_render` / `_discover` / `_checks` → `tools.state_machine.state_machine_audit_*`
  - `test_discover.py` lines 4, 53 and `test_discover_class_entities.py:4`: `from tools.state_machine_audit_discover import …` → `from tools.state_machine.state_machine_audit_discover import …`
  - `test_fake_coord.py` lines 4, 30: `from tools.state_machine_audit_fake_coord import …` → `from tools.state_machine.state_machine_audit_fake_coord import …`

  (Do a sweeping check afterwards: `grep -rn 'tools.state_machine_audit' tests/` must return nothing.)

- [ ] **Step 6: Run the audit tests + the tool**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/audit -q
/data/claude/homeassistant/.venv-vanilla/bin/python tools/state_machine/state_machine_audit.py --help
```
Expected: tests PASS; `--help` shows `Domain: state_machine   Run by: owner`.

- [ ] **Step 7: Commit**

```bash
git add tools/state_machine tests/audit
git commit -m "refactor(tools): move state-machine audit family into tools/state_machine/

Fix __file__ depths (+1), rewrite inter-tool + test imports to tools.state_machine.*,
add TOOL_META + --help banner.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Move the `session/` domain

**Files:**
- Move: `tools/rebuild_session.py`, `tools/state_partition.py`, `tools/_rebuild_session_lib/` (whole package) → `tools/session/`
- Modify (depth): `session/rebuild_session.py:25`, `session/state_partition.py:79`
- Modify (inter-tool imports): `session/rebuild_session.py` (its `from tools._rebuild_session_lib.*` imports)
- Modify (TOOL_META): `rebuild_session.py`, `state_partition.py`
- Modify (tests): `tests/tools/test_state_replay.py`, `test_samples_replay.py`, `test_track_replay.py`, `test_rebuild_session_e2e.py`, `test_probe_reader.py`, `test_session_windows.py`, `test_ha_archive.py`, `test_wifi_replay.py`
- Modify (CLAUDE.md): `tools/rebuild_session.py` reference

- [ ] **Step 1: git-mv the two tools + the lib package**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git mv tools/rebuild_session.py tools/state_partition.py tools/_rebuild_session_lib tools/session/
```

- [ ] **Step 2: Fix `__file__` depths** per the reference: `session/rebuild_session.py:25`, `session/state_partition.py:79`.

- [ ] **Step 3: Update `rebuild_session.py` inter-tool imports** — every `from tools._rebuild_session_lib.<mod> import …` (lines 29, 32, 33, 34, 35, 39, 42, 46) becomes `from tools.session._rebuild_session_lib.<mod> import …`. (Confirm none remain: `grep -n 'tools._rebuild_session_lib' tools/session/rebuild_session.py`.)

- [ ] **Step 4: Add `TOOL_META`** to `session/rebuild_session.py` and `session/state_partition.py`; wire `add_to_parser(parser, TOOL_META)` where a parser is built.

- [ ] **Step 5: Update test imports** — in every `tests/tools/` file listed above, replace `from tools._rebuild_session_lib.<mod>` → `from tools.session._rebuild_session_lib.<mod>` and `from tools.rebuild_session import …` → `from tools.session.rebuild_session import …`. Note `test_track_replay.py:32` is a string literal embedding the import path inside generated test code — update it too:
  `"from tools._rebuild_session_lib.track_replay import _default_decoder\n"` → `"from tools.session._rebuild_session_lib.track_replay import _default_decoder\n"`.
  Sweep check: `grep -rn 'tools._rebuild_session_lib\|tools.rebuild_session' tests/` returns nothing.

- [ ] **Step 6: Update CLAUDE.md** — `tools/rebuild_session.py` → `tools/session/rebuild_session.py` (the "Session rebuild tool" / reference line).

- [ ] **Step 7: Run the tools tests + the tool**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools -q
/data/claude/homeassistant/.venv-vanilla/bin/python tools/session/rebuild_session.py --help
/data/claude/homeassistant/.venv-vanilla/bin/python tools/session/state_partition.py --help
```
Expected: tests PASS; both `--help` show `Domain: session   Run by: owner`.

- [ ] **Step 8: Commit**

```bash
git add tools/session tests/tools CLAUDE.md
git commit -m "refactor(tools): move session rebuild/forensics into tools/session/

Fix __file__ depths (+1), rewrite _rebuild_session_lib imports to
tools.session.*, add TOOL_META + --help banner, update CLAUDE.md.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Move the `release/` domain

**Files:**
- Move: `tools/release.sh`, `tools/promote-latest.sh` → `tools/release/`
- Modify: insert the `# tool-meta:` headers (from the TOOL_META reference)

- [ ] **Step 1: Create `tools/release/` and git-mv the two scripts** (no `__init__.py` — shell only, never imported)

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
mkdir -p tools/release
git mv tools/release.sh tools/promote-latest.sh tools/release/
```

- [ ] **Step 2: Insert the `# tool-meta:` header block** into each script immediately after the existing shebang + title comment lines (the three `# tool-meta:` / `# tool-when:` / `# tool-summary:` lines from the reference). These are comments — they do not change behaviour.

- [ ] **Step 3: Confirm the scripts still parse and self-reference correctly**

```bash
bash -n tools/release/release.sh && echo "release.sh syntax ok"
bash -n tools/release/promote-latest.sh && echo "promote-latest.sh syntax ok"
grep -n 'tool-meta' tools/release/release.sh tools/release/promote-latest.sh
```
Expected: both print `syntax ok`; the `tool-meta` lines are present. (The usage examples inside the scripts still say `tools/release.sh`; update those usage-comment paths to `tools/release/release.sh` and `tools/release/promote-latest.sh` for accuracy.)

- [ ] **Step 4: Commit**

```bash
git add tools/release
git commit -m "refactor(tools): move release scripts into tools/release/ + add tool-meta

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Build `gen_readme.py`, generate the README, add the sync gate

**Files:**
- Create: `tools/gen_readme.py`
- Create: `tests/tools/test_readme_in_sync.py`
- Replace: `tools/README.md` (generated)

- [ ] **Step 1: Write the failing test**

Create `tests/tools/test_readme_in_sync.py`:
```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "tools" / "gen_readme.py"
DOMAINS = {"inventory", "probes", "state_machine", "session", "release"}
RUN_BY = {"ci", "owner", "maintainer"}


def _scan():
    sys.path.insert(0, str(REPO))
    from tools.gen_readme import scan_tools  # noqa: E402

    return scan_tools(REPO / "tools")


def test_readme_is_in_sync():
    result = subprocess.run(
        [sys.executable, str(GEN), "--check"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "tools/README.md is stale — run `python tools/gen_readme.py`:\n"
        + result.stdout + result.stderr
    )


def test_every_tool_domain_matches_its_subdir():
    bad = [
        (t["path"], t["domain"]) for t in _scan()
        if t["domain"] != Path(t["path"]).parent.name
    ]
    assert not bad, f"TOOL_META domain != containing subdir: {bad}"


def test_metadata_fields_well_formed():
    errs = []
    for t in _scan():
        if t["domain"] not in DOMAINS:
            errs.append(f"{t['path']}: bad domain {t['domain']!r}")
        if t["run_by"] not in RUN_BY:
            errs.append(f"{t['path']}: bad run_by {t['run_by']!r}")
        if not t["when"] or not t["summary"]:
            errs.append(f"{t['path']}: empty when/summary")
    assert not errs, "\n".join(errs)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_readme_in_sync.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.gen_readme'`.

- [ ] **Step 3: Implement `tools/gen_readme.py`**

```python
"""Regenerate tools/README.md from each tool's TOOL_META.

An entry-point tool is any .py under tools/<domain>/ that declares a literal
TOOL_META dict, or any .sh with a `# tool-meta:` header. Helper/lib modules
(no TOOL_META) are skipped. The README is GENERATED — edit the tools, not it.

  python tools/gen_readme.py            # rewrite tools/README.md
  python tools/gen_readme.py --check    # exit 1 (with diff) if README is stale
"""
from __future__ import annotations

import argparse
import ast
import difflib
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
DOMAIN_ORDER = ["inventory", "probes", "state_machine", "session", "release"]
DOMAIN_BLURB = {
    "inventory": "Fact-discipline gates — keep inventory.yaml / entity-inventory.yaml / docs honest.",
    "probes": "Device & cloud probes for owner fact-finding. Some WRITE to the live mower.",
    "state_machine": "Entity-source / state-machine audit (run after coordinator or entity changes).",
    "session": "Reconstruct or verify session archives from probe logs (dev box).",
    "release": "Maintainer-only HACS publishing for this repo. Not general-purpose.",
}
RUN_BY_ICON = {"ci": "🤖 ci", "owner": "👤 owner", "maintainer": "🔧 maintainer"}


def _extract_py_meta(path: Path) -> dict | None:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TOOL_META" for t in node.targets
        ):
            meta = ast.literal_eval(node.value)
            meta["path"] = str(path.relative_to(TOOLS_DIR.parent))
            meta["name"] = path.name
            return meta
    return None


def _extract_sh_meta(path: Path) -> dict | None:
    domain = run_by = when = summary = None
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("# tool-meta:"):
            for kv in s.removeprefix("# tool-meta:").split():
                k, _, v = kv.partition("=")
                if k == "domain":
                    domain = v
                elif k == "run_by":
                    run_by = v
        elif s.startswith("# tool-when:"):
            when = s.removeprefix("# tool-when:").strip()
        elif s.startswith("# tool-summary:"):
            summary = s.removeprefix("# tool-summary:").strip()
    if domain and run_by:
        return {"domain": domain, "run_by": run_by, "when": when or "",
                "summary": summary or "", "path": str(path.relative_to(TOOLS_DIR.parent)),
                "name": path.name}
    return None


def scan_tools(tools_dir: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(tools_dir.rglob("*.py")):
        if path.name in ("gen_readme.py", "_toolmeta.py") or "__pycache__" in path.parts:
            continue
        meta = _extract_py_meta(path)
        if meta:
            out.append(meta)
    for path in sorted(tools_dir.rglob("*.sh")):
        meta = _extract_sh_meta(path)
        if meta:
            out.append(meta)
    return out


def _invocation(meta: dict) -> str:
    if meta["name"].endswith(".sh"):
        return f"`{meta['path']}`"
    return f"`python {meta['path']}`"


def render(tools: list[dict]) -> str:
    lines = [
        "# tools/",
        "",
        "<!-- GENERATED by tools/gen_readme.py — do not hand-edit. "
        "Run `python tools/gen_readme.py` after changing a tool's TOOL_META. -->",
        "",
        "Helper scripts for this integration, grouped by domain. Each tool also "
        "prints its domain/run-by/when on `--help`.",
        "",
        "**Run by:** 🤖 `ci` runs automatically in CI (you rarely invoke by hand) · "
        "👤 `owner` you run for debugging/fact-finding · 🔧 `maintainer` repo-specific.",
        "",
    ]
    by_domain: dict[str, list[dict]] = {d: [] for d in DOMAIN_ORDER}
    for t in tools:
        by_domain.setdefault(t["domain"], []).append(t)
    for domain in DOMAIN_ORDER:
        items = sorted(by_domain.get(domain, []), key=lambda m: m["name"])
        if not items:
            continue
        lines += [f"## `{domain}/`", "", DOMAIN_BLURB.get(domain, ""), ""]
        for m in items:
            lines += [
                f"### {_invocation(m)}  —  {RUN_BY_ICON[m['run_by']]}",
                "",
                m["summary"],
                "",
                f"*When:* {m['when']}",
                "",
            ]
    lines += [
        "---",
        "",
        "Historical one-off migrations & recovery tools live in "
        "`OLD/ha-dreame-a2-mower-tools/` (out of the working tree).",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 with a diff if README.md is stale")
    args = ap.parse_args(argv)
    readme = TOOLS_DIR / "README.md"
    new = render(scan_tools(TOOLS_DIR))
    if args.check:
        old = readme.read_text() if readme.exists() else ""
        if old != new:
            sys.stdout.writelines(difflib.unified_diff(
                old.splitlines(True), new.splitlines(True),
                fromfile="README.md (committed)", tofile="README.md (generated)"))
            return 1
        return 0
    readme.write_text(new)
    print(f"wrote {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Generate the README and verify the tool runs**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/gen_readme.py
```
Expected: `wrote …/tools/README.md`. Open it and confirm five `## ` domain sections appear with the 15 tools.

- [ ] **Step 5: Run the sync test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/tools/test_readme_in_sync.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add tools/gen_readme.py tools/README.md tests/tools/test_readme_in_sync.py
git commit -m "feat(tools): generate README from TOOL_META + CI sync gate

gen_readme.py ast-extracts each tool's TOOL_META and rewrites tools/README.md;
test_readme_in_sync.py fails CI if it drifts or a tool sits in the wrong subdir.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Final sweep — docs breadcrumbs + full-suite verification

**Files:**
- Modify (user-facing how-to refs only): `docs/research/g2408-capture-procedures.md`, `docs/research/state-machines/README.md`, `docs/research/inventory/README.md`, `docs/TODO.md` (only where they tell a reader to *run* a moved tool)

- [ ] **Step 1: Find doc references to moved tools**

Run:
```bash
grep -rnE 'tools/(inventory_gen|inventory_audit|entity_inventory_audit|audit_outstanding_retractions|journal_completeness_check|wire_census|inventory_probe|probe_cruise_to_point|probe_add_maintenance_point|probe_pre_write|state_machine_audit|rebuild_session|state_partition|release|promote-latest)' docs/
```

- [ ] **Step 2: Redirect only the user-facing "run this" references** to their new subdir paths (e.g. `tools/wire_census.py` → `tools/inventory/wire_census.py`, `tools/rebuild_session.py` → `tools/session/rebuild_session.py`). **Leave** historical journal / wire-capture breadcrumbs unchanged — per the documentation-canonicity rule they may cite the old path (which now resolves under `OLD/` or the new tree); only fix lines a reader would copy-paste to run a tool today.

- [ ] **Step 3: Full suite + generator check + layout check**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q
/data/claude/homeassistant/.venv-vanilla/bin/python tools/gen_readme.py --check
ls tools/
```
Expected: full suite PASS; `gen_readme.py --check` exits 0 (no diff); `ls tools/` shows exactly `inventory/  probes/  session/  state_machine/  release/  gen_readme.py  _toolmeta.py  README.md  __init__.py` (plus `__pycache__`).

- [ ] **Step 4: Confirm CI references resolve**

Run: `grep -nE 'run: python tools/' .github/workflows/ci.yml`
Expected: every path is `tools/inventory/…` (the four inventory gates); no bare `tools/<name>.py` for a moved tool remains.

- [ ] **Step 5: Commit**

```bash
git add docs
git commit -m "docs(tools): redirect how-to references to new tools/ subdir paths

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification checklist (run after Task 10)

- [ ] `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q` → all pass.
- [ ] `python tools/gen_readme.py --check` → exit 0.
- [ ] `ls tools/` → 5 domain dirs + `gen_readme.py`, `_toolmeta.py`, `README.md`, `__init__.py`.
- [ ] `grep -rnE 'tools/(recover_sessions|install_recovered|retrofit_local_legs|migrate_sessions_to_track|backfill_wifi_samples|cleanup_entity_orphans)' custom_components tests .github tools CLAUDE.md` → no output.
- [ ] Each tool's `--help` shows its domain banner (spot-check one per domain).
- [ ] `OLD/ha-dreame-a2-mower-tools/` contains the 6 evicted tools + `recovered_sessions/` + the 2 rider tests.
