# P2 — Audit and Lock Entity Inventory + On-Disk Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a per-entity audit table that classifies every entity descriptor in the integration against the g2408 protocol doc §2.1, then either (a) apply the audit decisions surgically or (b) hand off to a greenfield-extract spec. The same plan also stamps `schema_version` on every on-disk archive format so future schema breaks log+skip cleanly.

**Architecture:** Audit-first, decide-then-act. Phase 1 is research only — no code edits, just markdown tables. Phase 2 is a hard decision gate where we choose between surgical cleanup (Phase 3) or greenfield extraction (separate spec). Phase 4 (schema versioning) is independent of that decision and runs either way.

**Tech Stack:** Python 3, Home Assistant custom-integration scaffold, pytest. Reading: `docs/research/g2408-protocol.md` §2.1 is the source-of-truth for which (siid, piid) pairs / events / actions are real on g2408. The dispositions follow the rule from
`docs/superpowers/specs/2026-04-27-pre-launch-review-design.md` §3.1:

| §2.1 status of the underlying property/event | Disposition |
|---|---|
| Confirmed (decoded shape, semantic clear) | **Keep** as production or observability |
| Partial (shape known, semantic unclear) | **Keep** as observability |
| Documented as TBD on g2408 (might exist, unprobed) | **Keep, flag for discussion** (experimental) |
| Vacuum / MOVA / non-g2408, no g2408 evidence | **Delete** |

**Spec:** `docs/superpowers/specs/2026-04-27-pre-launch-review-design.md` priority 2.

**Working discipline:** Per spec §8, push to `origin/main` after each phase. Audit phases are research-only commits (markdown tables); cutover phase is a single mechanical commit.

**Hard pause point:** Phase 2 is a user-facing decision gate. Do not proceed past it without explicit user choice between surgical (Phase 3) and greenfield (separate spec).

---

## Scope inventory (post-P1)

Total entity descriptors to audit: **~198** across 9 files.

| File | Descriptor count | Audit batch |
|---|---:|---|
| `binary_sensor.py` | ~8 | 1.1 |
| `camera.py` | ~7 | 1.1 |
| `lawn_mower.py` | ~1 | 1.1 |
| `device_tracker.py` | ~0 (single class) | 1.1 |
| `select.py` | ~12 | 1.2 |
| `number.py` | ~5 | 1.2 |
| `time.py` | ~7 | 1.2 |
| `button.py` | ~27 | 1.3 |
| `switch.py` | ~47 | 1.4 |
| `sensor.py` | ~84 | 1.5 |

Plus on-disk archive surfaces (Phase 4):
- `<config>/dreame_a2_mower/sessions/index.json`
- `<config>/dreame_a2_mower/sessions/*.json`
- `<config>/dreame_a2_mower/sessions/in_progress.json`
- `<config>/dreame_a2_mower/lidar/index.json`
- `<config>/dreame_a2_mower/lidar/*.pcd`
- `<config>/dreame_a2_mower/mqtt_archive/YYYY-MM-DD.jsonl` (optional)

---

## Output artifact: master audit table

The deliverable from Phase 1 is a single markdown table at:

`docs/superpowers/plans/2026-04-27-p2-entity-audit-table.md`

Schema (one row per entity descriptor):

```
| File | Class/key | Computed entity_id | Underlying property/action | §2.1 citation | Classification | Proposed entity_id (if rename) | Proposed entity_category | Proposed enabled_by_default | Reason / notes |
```

Classifications use exactly these labels:
- **PRODUCTION** — user-actionable, confirmed protocol mapping, enabled by default
- **OBSERVABILITY** — protocol-debugging, `entity_category=DIAGNOSTIC`, enabled by default
- **EXPERIMENTAL** — TBD on g2408, `entity_category=DIAGNOSTIC`, **disabled by default**, suffix `_experimental`
- **DELETE** — no §2.1 evidence, vacuum/MOVA holdover

The §2.1 citation column should be a short reference like `s2.66`, `event_occured siid=4 eiid=1`, `BLADES_LEFT (CFG)`, or `none` (= deletion candidate). If the property exists in `DreameMowerProperty` enum but is NOT in §2.1, the citation is `enum-only` and the row is a DELETE candidate.

---

## Phase 1 — Per-entity audit

Phase 1 is split into 5 batches (one subagent dispatch each). Each batch produces a section of the master audit table. The controller merges sections after each completes.

Phase 1 deliverable per batch: a partial markdown table appended to
`docs/superpowers/plans/2026-04-27-p2-entity-audit-table.md`. Each batch commits its section, so the plan is bisectable per batch.

### Task 1.1 — Audit small files (binary_sensor + camera + lawn_mower + device_tracker)

**Files:**
- Read: `custom_components/dreame_a2_mower/binary_sensor.py`
- Read: `custom_components/dreame_a2_mower/camera.py`
- Read: `custom_components/dreame_a2_mower/lawn_mower.py`
- Read: `custom_components/dreame_a2_mower/device_tracker.py`
- Read (reference): `docs/research/g2408-protocol.md` §2.1 (whole table)
- Modify: `docs/superpowers/plans/2026-04-27-p2-entity-audit-table.md` (create with header + section 1.1)

- [ ] **Step 1: Read the protocol doc §2.1 once**

```bash
grep -A1000 "^### 2.1 Summary table" docs/research/g2408-protocol.md | head -300
```

Build a mental index: which (siid.piid) are documented, with what status (confirmed / partial / TBD / mentioned-but-unprobed). Also note documented event ids (e.g., `event_occured siid=4 eiid=1`), CFG-derived properties (BLADES_LEFT, etc.), and §6/§7 sections describing structured blobs.

- [ ] **Step 2: For each entity descriptor in the four small files, populate a row**

For each `EntityDescription(...)` (or class like `DreameMowerLawnMowerEntity`) in scope:

a. Identify `description.key` (or class identity) — that's the "Class/key" column.
b. Compute the `entity_id` — typically `<platform>.<integration_slug>_<key>`. For lawn_mower, the entity is unique-named.
c. Identify the underlying source: `property_key=DreameMowerProperty.X`, `action=DreameMowerAction.Y`, `value_fn=lambda d: ...` (computed from `device.status`), or capability flag.
d. Look up the underlying property in §2.1. Cite the row (e.g., `s1.4 MOWING_TELEMETRY confirmed`, `s2.50 TASK envelope partial`, `s99.20 lidar trigger §7.3b`). If no row matches, write `none` in the citation column.
e. Apply the disposition rule. Write the classification.
f. If keeping with a rename: propose new entity_id in slug-case (e.g., `binary_sensor.dreame_a2_mower_rain_protection_active`). If keeping unchanged, leave that column blank.
g. Propose `entity_category`: `None` (production), `EntityCategory.DIAGNOSTIC` (observability/experimental), or N/A.
h. Propose `entity_registry_enabled_default`: `True` (production/observability), `False` (experimental).
i. Reason: 1–2 sentence explanation, with file:line evidence if helpful.

- [ ] **Step 3: Create the audit-table file with header + section 1.1**

Write `docs/superpowers/plans/2026-04-27-p2-entity-audit-table.md`:

```markdown
# P2 entity audit table

**Date**: 2026-04-27
**Plan**: docs/superpowers/plans/2026-04-27-pre-launch-p2-entity-audit.md
**Source-of-truth for §2.1 citations**: docs/research/g2408-protocol.md §2.1

## Disposition rules (recap)

[copy the table from the plan §"Disposition rules"]

## Section 1.1 — binary_sensor.py + camera.py + lawn_mower.py + device_tracker.py

| File | Class/key | Computed entity_id | Underlying property/action | §2.1 citation | Classification | Proposed entity_id | Proposed entity_category | Proposed enabled_by_default | Reason / notes |
|---|---|---|---|---|---|---|---|---|---|
| binary_sensor.py | ... | ... | ... | ... | ... | ... | ... | ... | ... |
...
```

- [ ] **Step 4: Commit section 1.1**

```bash
git add docs/superpowers/plans/2026-04-27-p2-entity-audit-table.md
git commit -m "$(cat <<'EOF'
P2.1.1: audit binary_sensor/camera/lawn_mower/device_tracker

First section of the per-entity audit table for the P2 pre-launch
review priority. Each row classifies one entity descriptor against
docs/research/g2408-protocol.md §2.1 per the spec's disposition rule.

Spec: docs/superpowers/specs/2026-04-27-pre-launch-review-design.md P2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

### Task 1.2 — Audit select.py + number.py + time.py (~24 descriptors)

Same shape as 1.1. Append section 1.2 to the audit-table file. Same step structure: read protocol doc, walk descriptors, classify, commit.

The §2.1 references for select/number/time entries are likely:
- `select.cleaning_mode` → § s6.2[1] (mowing efficiency / "Standard"/"Efficient" enum)
- `number.mowing_height` → § s6.2[0] (mowing height in mm, 30–70mm)
- `time.dnd_*` → § s5.4 (DND_TASK) — possibly real on g2408? Audit per the rule.
- Vacuum vocabulary entries (zone-cleaning numbers, customised cleaning selects) likely DELETE

Commit message: `P2.1.2: audit select/number/time`.

### Task 1.3 — Audit button.py (~27 descriptors)

Same shape. Buttons map to `DreameMowerAction` entries. Each action has a §2.1 row in the catalogued opcodes (`s2.50 TASK opcodes 100, 101, 204, 215, 218, 234, 401`, etc.) or it doesn't.

Commit message: `P2.1.3: audit button.py`.

### Task 1.4 — Audit switch.py (~47 descriptors)

Same shape. Switches typically wrap a property setter or a multi-select state. The post-P1 button.py + switch.py contains zone/spot mow selection switches added in alpha.163; those are in scope.

Commit message: `P2.1.4: audit switch.py`.

### Task 1.5 — Audit sensor.py (~84 descriptors)

Same shape, largest file. Many sensors are derived state (`value_fn=lambda d: d.status.X`) rather than direct property reads — note both the device.status accessor and the underlying property/blob.

Commit message: `P2.1.5: audit sensor.py`.

---

## Phase 2 — Consolidate + decision gate

### Task 2.1: Compute summary statistics

**Files:**
- Read: `docs/superpowers/plans/2026-04-27-p2-entity-audit-table.md`
- Modify: same file — append a "Summary" section at the bottom

- [ ] **Step 1: Count entries by classification**

For the merged audit table, count:
- Total entities audited
- PRODUCTION count + percentage
- OBSERVABILITY count + percentage
- EXPERIMENTAL count + percentage
- DELETE count + percentage

- [ ] **Step 2: Count remaining vacuum-vocabulary references**

Surface area beyond entity descriptors. Run:

```bash
grep -rncE '\b(clean|cleaning|carpet|mop|water_tank|dust|vacuum|silver_ion|squeegee|tank_filter|cruise|stream)\b' --include="*.py" custom_components/ | sort -t: -k2 -n -r | head -20
```

This is approximate but gives a sense of how much vacuum vocabulary survives in helper functions / attribute names / comments. Report the top 20 file:count results.

- [ ] **Step 3: Append summary section**

```markdown
## Summary

**Total entities audited**: N

| Classification | Count | % |
|---|---:|---:|
| PRODUCTION | x | x% |
| OBSERVABILITY | y | y% |
| EXPERIMENTAL | z | z% |
| DELETE | w | w% |

**Vacuum-vocabulary noise (top 20 files by reference count)**:

| File | Count |
|---|---:|
| ... | ... |

**Estimated post-cutover entity count**: PRODUCTION + OBSERVABILITY + EXPERIMENTAL = ?
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-04-27-p2-entity-audit-table.md
git commit -m "P2.2.1: audit summary + vocabulary noise counts"
git push origin main
```

### Task 2.2: User decision gate (HARD PAUSE)

**Files:** none — this is a conversation step.

- [ ] **Step 1: Present the audit summary to the user**

Show the totals. Show the top vocabulary-noise files. Frame the decision:

> The audit shows **N** entities to keep (P+O+E) and **W** to delete (W%). Vacuum-vocabulary references in the surviving code total ~X across the top 20 files.
>
> Two paths forward:
>
> A) **Surgical cleanup** — apply the audit decisions in one cutover commit (delete the W entities, rename per the table, set entity_category / enabled_default). Then continue with P3 (observability) → P4 (finalize) → P5 (decompose) → P6 (tests) → P7 (package reconcile). The hundreds of `*CLEAN*` references will be reduced incrementally as each priority touches the code, but some will persist as scar tissue.
>
> B) **Greenfield extract** — write a new spec for a from-scratch integration that imports only the protocol/ codecs and the g2408-specific glue. The audit table becomes the surface specification. P3-P7 are replaced by "build the new integration", which is one spec + one big plan rather than five.
>
> Recommendation depends on the totals. Rough guide:
> - If P+O+E ≤ 50 entities and >40% of grep hits are vacuum-vocab → **B (greenfield)** is probably less work overall.
> - If P+O+E > 80 entities or grep hits are dominated by mower-relevant keywords (e.g., "cleaning_paused" is real for the mower's pause state) → **A (surgical)** is fine.

- [ ] **Step 2: Wait for explicit user choice**

Do not proceed without the user's answer.

- [ ] **Step 3: Update the plan to reflect the choice**

Edit this plan file: append a "Decision (2026-MM-DD)" section under Phase 2 saying "User chose A (surgical)" or "User chose B (greenfield); see new spec at ...".

If user chose A → continue to Phase 3.
If user chose B → close out P2 here. Phase 4 (schema versioning) still runs. Phases 3 is replaced by new-spec brainstorming.

---

## Phase 3 — Surgical cutover (only if user chose A in Phase 2)

### Task 3.1: Apply DELETE classifications

**Files:** every file containing a DELETE-classified entity descriptor + their `DreameMowerProperty` / `DreameMowerAction` enum entries + their translation file entries.

This is one large cutover commit because the renames and deletions need to land together — partial state would leave broken entity IDs and orphaned translations.

- [ ] **Step 1: Re-verify clean baseline**

```bash
git status   # clean
pytest -x    # baseline
```

If anything fails, STOP. Don't introduce changes against a degraded baseline.

- [ ] **Step 2: For each DELETE entry, delete:**

a. The `EntityDescription(...)` block in the entity file.
b. The `DreameMowerProperty.X` enum entry in `dreame/types.py` IF no other entity references it. Confirm with grep before deleting.
c. The corresponding entry in `DreameMowerPropertyMapping` dict.
d. The corresponding entry in the `_G2408_OVERLAY` if it's overlaid.
e. The corresponding `DreameMowerAction.Y` enum entry IF no other consumer references it.
f. The corresponding entry in `DreameMowerActionMapping`.
g. The corresponding `ATTR_*` constant in `dreame/types.py` if used only by deleted entities.
h. The corresponding `CONSUMABLE_*` constant in `dreame/const.py` if used only by deleted entities.
i. The translation entries in `strings.json` and `translations/*.json` for the deleted entity (state strings, name strings).
j. Any `value_fn=lambda d: d.status.X` or `exists_fn=lambda…` closures that reference deleted properties.

This is mechanical but needs grep-before-each-deletion to verify no other reference.

- [ ] **Step 3: Apply renames**

For each non-DELETE entry where the audit table has a "Proposed entity_id" rename:

a. Edit `description.key` (entity_id is computed from this) — change the slug.
b. Update the corresponding translation entry — rename the key under `state.<entity_type>.<old_key>` to `<new_key>`, and update the displayed string if needed.
c. Don't re-name the underlying `DreameMowerProperty.X` enum (those are wire-format-bound; only the user-facing entity name changes).

- [ ] **Step 4: Apply entity_category / enabled_default**

For each entity not currently matching the proposed values:

a. Set `entity_category=EntityCategory.DIAGNOSTIC` for OBSERVABILITY and EXPERIMENTAL entries.
b. Set `entity_registry_enabled_default=False` for EXPERIMENTAL entries.
c. Add `_experimental` suffix to the EXPERIMENTAL entries' `description.key`.

- [ ] **Step 5: Run pytest**

```bash
pytest -x
```

Expected: same baseline (no new failures). The snapshot regression test should still pass — none of these changes touch `DreameMowerDeviceCapability`.

If any test fails because it referenced an entity by old name, update the test to the new name in the same commit.

- [ ] **Step 6: Smoke-test imports**

```bash
python3 -c "
import sys, importlib.util
for f in ('types', 'const'):
    spec = importlib.util.spec_from_file_location(
        f'{f}_mod',
        f'custom_components/dreame_a2_mower/dreame/{f}.py'
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules[f'{f}_mod'] = m
    spec.loader.exec_module(m)
print('ok')
"
```

- [ ] **Step 7: Commit and push**

```bash
git add custom_components/dreame_a2_mower/ tests/
git commit -m "$(cat <<'EOF'
P2.3: apply audit decisions — delete unreferenced vacuum entities, rename and tier remaining ones

Cutover commit. Per the audit table at
docs/superpowers/plans/2026-04-27-p2-entity-audit-table.md:

  - Deleted N entities classified DELETE (no g2408 §2.1 citation)
    plus their DreameMowerProperty enum entries, action mappings,
    and translation strings (where unique to the deleted entity)
  - Renamed M entities for protocol-doc consistency
  - Tagged K entities entity_category=DIAGNOSTIC,
    entity_registry_enabled_default=False as EXPERIMENTAL with
    _experimental suffix per spec §3.1

Single cutover so user dashboard re-fix is one-shot. Audit
table doc remains as the historical record.

Spec: docs/superpowers/specs/2026-04-27-pre-launch-review-design.md P2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

The cutover commit message should also list (in the body, expanded) the specific entity_ids deleted, renamed, and re-tiered, so the user has a one-stop reference for fixing their dashboard.

---

## Phase 4 — On-disk schema-version stamping

Runs regardless of Phase 2 choice. The four archive classes get a `schema_version` field and a version-mismatch handler.

### Task 4.1: Identify archive classes

**Files:**
- Read: `custom_components/dreame_a2_mower/session_archive.py`
- Read: `custom_components/dreame_a2_mower/lidar_archive.py`
- Read: `custom_components/dreame_a2_mower/protocol/mqtt_archive.py`

For each, identify:
- The class that owns the on-disk format (`SessionArchive`, `LidarArchive`, `MqttArchive`)
- The serialization method (often `to_dict()` or `__init__()` from a JSON dict)
- The deserialization method (often `from_dict(cls, d)` or `read_index()`)

### Task 4.2: Add `schema_version` field

For each archive class:

- [ ] **Step 1: Define the version constant**

In each archive module, near the top:

```python
SCHEMA_VERSION = 1
```

- [ ] **Step 2: Stamp on serialization**

In each `to_dict()` / index-write path, include `"schema_version": SCHEMA_VERSION`.

- [ ] **Step 3: Validate on deserialization**

In each `from_dict()` / index-read path, check the loaded dict's `schema_version`:

```python
loaded_version = data.get("schema_version", 0)
if loaded_version != SCHEMA_VERSION:
    LOGGER.warning(
        "%s schema_version mismatch: got %s, expected %s — "
        "skipping this entry. To regenerate, delete the file or run "
        "the regeneration script.",
        cls.__name__, loaded_version, SCHEMA_VERSION,
    )
    return None
```

The `version=0` fallback for missing `schema_version` is intentional — every existing archive predates the version field, so it gets logged + skipped on first read after this lands. Per the spec §2 mutability, on-disk schema is mutable: delete-on-upgrade is fine; users can regenerate from `probe_log_*.jsonl` if they cared about old session data.

### Task 4.3: Tests

For each archive class, add a focused test in `tests/`:

```python
def test_session_archive_skips_old_schema_version(tmp_path):
    archive_root = tmp_path / "sessions"
    archive_root.mkdir()
    # Write an index file with the wrong schema_version
    (archive_root / "index.json").write_text('{"schema_version": 0, "entries": []}')
    archive = SessionArchive(archive_root, retention=10)
    archive.load_index()
    # The mismatch should not raise; it should log a warning and load empty
    assert archive.list_sessions() == []
```

(Same shape for lidar_archive and mqtt_archive.)

### Task 4.4: Commit and push

```bash
git add custom_components/dreame_a2_mower/session_archive.py \
        custom_components/dreame_a2_mower/lidar_archive.py \
        custom_components/dreame_a2_mower/protocol/mqtt_archive.py \
        tests/
git commit -m "$(cat <<'EOF'
P2.4: stamp schema_version=1 on archive formats; mismatch → log+skip

Adds schema_version to SessionArchive, LidarArchive, and MqttArchive
on-disk formats. Per spec §2 mutability: no migrator. On version
mismatch, log a WARNING and skip the entry; users can regenerate
from probe_log_*.jsonl if needed.

Existing archives (which lack the field) are read with default
schema_version=0 → mismatched against constant 1 → log+skip on
first read after this lands. This is intentional one-time data
loss in exchange for a clean schema-versioning foundation.

Spec: docs/superpowers/specs/2026-04-27-pre-launch-review-design.md P2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

---

## Self-review checklist

Run before declaring P2 complete:

- [ ] All 5 audit-table sections (1.1–1.5) committed with §2.1 citations.
- [ ] Phase 2 summary appended; user decision recorded inline in the plan.
- [ ] If surgical: cutover commit pushed; pytest green; smoke-test green.
- [ ] If greenfield: handoff spec linked from this plan.
- [ ] Schema-version stamp landed for all three archive classes; mismatch tests pass.
- [ ] All commits on `origin/main`; no detached HEADs.

## What this plan does NOT do

Out-of-scope, deferred to later plans:

- The full **vacuum-vocabulary purge** in helper functions / attribute names / comments. The audit cuts entities; the helper-function rename is grep-and-rename work that gets folded into P5 decomposition where each module is touched anyway.
- The `_check_consumable` helper and CONSUMABLE_* constants — touched here only insofar as a deleted entity made them unreferenced. Standalone audit deferred to P5.
- The **`Furniture` / `Furnitures` dataclasses** in `dreame/types.py:2169` — vacuum concept; deletion folds into P5 decomposition.
- The **encrypted-blob map decoder** branches in `dreame/map.py` — defer to P5b.
- **`DEVICE_KEY` and `DREAME_STRINGS` blobs** — defer to P5/P5b, contingent on whether their consumers survive the decomposition.
- **`capability.floor_material`** flag in `DreameMowerDeviceCapability` (per P1.6 commit) — fold into Phase 3 cutover here if surgical, or into greenfield if not.
