# tools/ Reorganization + Self-Documenting README — Design

**Date:** 2026-06-05
**Status:** approved (brainstorming → ready for writing-plans)

## Goal

Make every script in `tools/` self-evidently belong to a domain **without
anyone reading the README**, and make the README impossible to leave stale —
by moving tools into domain subdirectories, having each tool self-declare its
domain/run-by/when metadata, and generating both a `--help` banner and the
README from that single source. Simultaneously evict dead and one-off scripts
from the working tree.

## Why

`tools/` has grown to ~28 files. The README documents exactly one of them
(`recover_sessions.py`) and is otherwise stale. Three problems:

1. **No domain signal at browse time.** `ls tools/` is a flat blob; you cannot
   tell an inventory gate from a cloud probe from a one-off migration.
2. **Stale, unread README.** Hand-maintained and detached from the tools, so it
   rots and nobody consults it.
3. **Obsolete scripts linger.** Dead (`retrofit_local_legs.py`, injects a
   removed key) and done one-offs (migrations, recovery) sit alongside active
   tools, so every time a tool is needed someone re-validates whether these are
   still relevant.

## Design principles

- **Single source of truth.** Domain/run-by/when is declared once per tool;
  the `--help` banner and the README are both derived from it. They cannot
  drift.
- **Visible at all three moments.** Browse (`ls`/IDE → subdirs), run
  (`--help` → banner), look-up (README → generated table).
- **Generated artifacts are CI-gated.** A sync test fails the build if the
  committed README diverges from what the generator produces — matching the
  repo's existing pattern (`inventory_gen.py --validate-only`, the wire-census
  guard).
- **Out-of-tree for the dead/done.** Mirrors the documentation-canonicity rule
  in `CLAUDE.md`: historical artifacts move to `OLD/`, not deleted, but out of
  the working tree so they never cost re-validation time.
- **Minimise regression surface.** Files are *nested only* (no renames), so the
  diff is mechanical path-prefixing. Redundant prefixes (e.g.
  `inventory/inventory_gen.py`) are accepted as cosmetic.

## Target layout

```
tools/
  inventory/      # fact-discipline gates (mostly CI-run)
    inventory_gen.py
    inventory_audit.py
    entity_inventory_audit.py
    audit_outstanding_retractions.py
    journal_completeness_check.py
    wire_census.py
    wire_census_lib.py
    __init__.py
  probes/         # device/cloud probes (owner; some WRITE to the live device)
    inventory_probe.py
    probe_cruise_to_point.py
    probe_add_maintenance_point.py
    probe_pre_write.py
    __init__.py
  state_machine/  # entity-source / state-machine audit family
    state_machine_audit.py
    state_machine_audit_checks.py
    state_machine_audit_discover.py
    state_machine_audit_fake_coord.py
    state_machine_audit_render.py
    state_machine_audit_expectations.yaml
    __init__.py
  session/        # session rebuild & forensics
    rebuild_session.py
    state_partition.py
    _rebuild_session_lib/        # unchanged internal package
    __init__.py
  release/        # maintainer-only HACS publishing (this instance)
    release.sh
    promote-latest.sh
  gen_readme.py   # regenerates README.md from each tool's TOOL_META
  _toolmeta.py    # shared --help banner helper
  README.md       # GENERATED — header says do not hand-edit
  __init__.py
```

Five domains. `release/` holds only shell scripts (never imported, no
`__init__.py` needed). All other subdirs are regular packages with
`__init__.py` so `from tools.<domain>.<mod> import …` resolves.

### Domain assignment rationale

| Domain | Members | Why |
|---|---|---|
| `inventory` | gen, audit, entity_inventory_audit, audit_outstanding_retractions, journal_completeness_check, wire_census(+lib) | All keep the source-of-truth files (`inventory.yaml`, `entity-inventory.yaml`, docs) honest. wire_census is a coverage guard *over* inventory; journal_completeness_check guards the research docs. |
| `probes` | inventory_probe, probe_cruise_to_point, probe_add_maintenance_point, probe_pre_write | Owner-run cloud/device probes for fact-finding. Some WRITE to the live device. inventory_probe is read-only but is still a cloud probe. |
| `state_machine` | state_machine_audit + 4 helper modules + expectations.yaml | A distinct multi-file audit family (entity sourcing / idle / reboot / orphan-field). Kept separate from `inventory` because it audits *entity behaviour*, not inventory files. |
| `session` | rebuild_session(+`_rebuild_session_lib/`), state_partition | Reconstruct or verify session archives from probe logs. |
| `release` | release.sh, promote-latest.sh | This-maintainer-only HACS publishing. Not general-purpose. |

## Single source of truth: `TOOL_META`

Each Python tool gains a module-level literal near the top:

```python
TOOL_META = {
    "domain": "inventory",      # must equal the containing subdir name
    "run_by": "ci",             # one of: ci | owner | maintainer
    "when": "Every CI build; locally before shipping a fact-heavy change.",
    "summary": "Validate inventory.yaml schema + regenerate canonical docs.",
}
```

Shell tools carry the equivalent as a comment header the generator parses:

```bash
# tool-meta: domain=release run_by=maintainer
# tool-when: After pushing integration commits, to cut a HACS-visible release.
# tool-summary: Bump version, tag, push, create the GitHub Release, refresh HACS.
```

**Field semantics**

- `domain` — must match the subdir; a test asserts this (catches a tool placed
  in the wrong folder or a typo'd domain).
- `run_by` — `ci` (runs automatically in CI; you rarely invoke by hand),
  `owner` (a person running the integration invokes it for debugging/fact-
  finding), `maintainer` (specific to this repo's maintainer, e.g. publishing).
- `when` — one sentence: the circumstance under which to run it.
- `summary` — one sentence: what it does.

## Derived output 1: `--help` banner

`tools/_toolmeta.py` exposes:

```python
def format_banner(meta: dict) -> str: ...
    # → "Domain: inventory   Run by: ci\nWhen: <when>\n<summary>"

def add_to_parser(parser, meta: dict) -> None: ...
    # sets parser.epilog (or appends) and
    # parser.formatter_class = argparse.RawDescriptionHelpFormatter
```

Each Python tool with an argparse parser calls
`add_to_parser(parser, TOOL_META)` so `--help` prints the domain/run-by/when
block. Tools without argparse still carry `TOOL_META` (for the README); the
`--help` banner is best-effort there and not required.

Shell tools already print a usage block on `-h`/bad args; the design adds the
`when`/`summary` lines into that existing usage text (no new framework).

## Derived output 2: generated README

`tools/gen_readme.py`:

- Walks `tools/<domain>/` subdirs.
- For each `.py`, parses the file with `ast` and extracts the `TOOL_META`
  dict via `ast.literal_eval` on the assignment node — **never imports the
  tool** (tools have heavy deps; importing would be slow and fragile).
- For each `.sh`, parses the `# tool-meta:` / `# tool-when:` / `# tool-summary:`
  comment header.
- Groups by domain, emits `tools/README.md` with:
  - A top banner: "GENERATED by `gen_readme.py` — do not hand-edit."
  - A short intro + a legend for the `run_by` tags (🤖 ci / 👤 owner / 🔧 maintainer).
  - One section per domain, each listing its tools with: summary, when, run-by,
    and the exact invocation command.
  - A closing pointer: historical one-off tools live in
    `OLD/ha-dreame-a2-mower-tools/`.
- CLI: `python tools/gen_readme.py` writes the file; `--check` prints a diff and
  exits non-zero if the committed file is out of date (for the test/CI).

### Sync gate

`tests/tools/test_readme_in_sync.py`:

- Asserts `gen_readme.py --check` reports no diff (committed README ==
  generated output).
- Asserts every tool's `TOOL_META["domain"]` equals its containing subdir.
- Asserts `run_by` ∈ {ci, owner, maintainer} and required keys are present.

This runs in the existing `tests/tools` CI job. From here on, any tool added,
moved, or re-described **must** regenerate the README or CI goes red — the
durable anti-stale guarantee.

## Evictions → `OLD/ha-dreame-a2-mower-tools/`

Mirror the tools-relative path under the new OLD subtree (analogous to
`OLD/ha-dreame-a2-mower-docs/`):

| Moved | Reason |
|---|---|
| `retrofit_local_legs.py` | Dead — injects `_local_legs`, removed for good by the 2026-05-28 replay rewrite. |
| `migrate_sessions_to_track.py` | Done migration (one-time, 2026-05-28). |
| `backfill_wifi_samples.py` | Done one-time field back-fill. |
| `recover_sessions.py` | Superseded by the active `rebuild_session.py`. |
| `install_recovered.py` | Pairs with `recover_sessions.py`. |
| `cleanup_entity_orphans.py` | One-off for past naming-scheme migrations (now settled). |
| `recovered_sessions/` (27 JSONs) | Output of `recover_sessions.py`. |

Rider tests travel with their tool, mirrored under
`OLD/ha-dreame-a2-mower-tools/tests/tools/`:

- `tests/tools/test_migrate_sessions.py`
- `tests/tools/test_backfill_wifi_samples.py`

(After the move, no in-tree test references any evicted tool, so the suite
still collects cleanly.)

## Ripple updates (all bounded, all CI-verified)

| Surface | Edit |
|---|---|
| `.github/workflows/ci.yml` | 4 invocations → `tools/inventory/…` (`inventory_gen`, `inventory_audit`, `entity_inventory_audit`, `audit_outstanding_retractions`). |
| Tests — state_machine | `from tools.state_machine_audit_*` → `from tools.state_machine.state_machine_audit_*` (16 refs across audit tests). |
| Tests — inventory | `from tools.wire_census_lib` → `tools.inventory.wire_census_lib` (3); `tools/wire_census` invocation paths (2); `tools/entity_inventory_audit` path (1). |
| Tests — session | `from tools._rebuild_session_lib…` → `from tools.session._rebuild_session_lib…` (17 refs); `from tools.rebuild_session` → `tools.session.rebuild_session`. |
| `CLAUDE.md` | `tools/inventory_audit.py` → `tools/inventory/inventory_audit.py`; `tools/rebuild_session.py` → `tools/session/rebuild_session.py`. |
| `custom_components/dreame_a2_mower/archive/session.py:260` | Runtime message "Run tools/recover_sessions.py …" → "Run tools/session/rebuild_session.py …" (active successor). |
| `docs/` | Redirect user-facing how-to references (e.g. `docs/research/g2408-capture-procedures.md`, `docs/research/state-machines/README.md`) to new paths. Leave journal/wire-capture breadcrumbs as historical (they may cite old or OLD/ paths per the canonicity breadcrumb rule). |

Inter-tool imports also update under the same rule (mechanical prefixing):

- `state_machine_audit.py`, `state_machine_audit_render.py`,
  `state_machine_audit_checks.py` import each other →
  `from tools.state_machine.state_machine_audit_*`.
- `wire_census.py` imports `wire_census_lib` → `from tools.inventory.wire_census_lib`.
- `rebuild_session.py` imports `_rebuild_session_lib.*` →
  `from tools.session._rebuild_session_lib.*`.

## Verification

- `pytest tests/ -q` green (full suite, not just `tests/tools`).
- `python tools/gen_readme.py --check` exits 0.
- `ls tools/` shows exactly: `inventory/ probes/ session/ state_machine/
  release/ gen_readme.py _toolmeta.py README.md __init__.py` (+ `__pycache__`).
- CI inventory gates run from their new `tools/inventory/…` paths (confirm by
  reading the updated `ci.yml`).
- No in-tree reference to any evicted tool remains:
  `grep -rE 'tools/(recover_sessions|install_recovered|retrofit_local_legs|
  migrate_sessions_to_track|backfill_wifi_samples|cleanup_entity_orphans)'`
  returns only historical doc breadcrumbs (if any), not code/CI/test refs.

## Out of scope / non-goals

- **No filename renames** beyond the subdir move (no `inventory_gen.py` →
  `gen.py`). Redundant prefixes are tolerated to keep the diff mechanical.
- **No behaviour changes** to any tool — pure relocation + metadata addition.
- **No new domains** beyond the five. A tool that fits none gets the closest
  domain, not a new folder.
- **No `__init__.py` for `release/`** — shell only, never imported.

## Edge cases & risks

- **`ast.literal_eval` on `TOOL_META`** requires the dict to be a pure literal
  (no computed values). The plan enforces this convention; the sync test fails
  loudly if a tool's metadata can't be statically extracted.
- **A tool placed in the wrong subdir** is caught by the domain==subdir test.
- **Evicted tools' broken imports** (e.g. `migrate_sessions_to_track` importing
  `tools._rebuild_session_lib`) don't matter — they're archived, not run.
- **`__pycache__` directories** are gitignored; ignore during moves.
- **Two tools could claim CI ownership incorrectly** — `run_by` is declarative
  and not auto-verified against `ci.yml`; reviewer confirms during the metadata
  pass. (Auto-verifying run_by against CI is a possible later enhancement, out
  of scope here.)
