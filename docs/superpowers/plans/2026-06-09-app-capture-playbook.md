# Missing-knowledge capture playbook — Implementation Plan (Spec B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the in-tree capture playbook — the ordered list of in-app actions for the next Mac MITM session, each mapped to the wire it reveals and the Phase 2 item / `open_questions` ID it unblocks — and wire it into the existing capture-procedures + inventory contract.

**Architecture:** One new Tier-3 dated research doc (`docs/research/g2408-app-capture-playbook-2026-06-09.md`), cross-linked from `g2408-capture-procedures.md`. It references `inventory.yaml` `open_questions` IDs (created by the Phase 1 plan, Tasks 1–2) as the closure contract. No code.

**Tech Stack:** Markdown only.

**Spec:** `docs/superpowers/specs/2026-06-09-app-capture-playbook-design.md`

**Dependency:** Run *after* (or alongside) Phase 1 Tasks 1–2, which create the
`open_questions` IDs this doc cites. If run first, the IDs are forward-references
that Phase 1 then fills — acceptable, but note it in the doc header.

---

## Conventions

- **Documentation canonicity (CLAUDE.md):** this is a Tier-3 dated
  capture-procedures companion — it stays in-tree (capture how-tos are cited by
  Tier-2 docs) and carries the standard non-authoritative banner. Facts it helps
  capture get promoted into `inventory.yaml` after the capture, not left here.
- **Epistemic tags:** every wire claim carries `[dreame-app-implementation-guide-2026-06-09.md]` (app-observed) or `[UNKNOWN — to capture]` (the gap this entry exists to close). No bare wire declaratives.
- **Commit after each task.** Use the Phase 1 branch (`feat/app-capture-phase1`) or a sibling `docs/app-capture-playbook` branch.

---

## File structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `docs/research/g2408-app-capture-playbook-2026-06-09.md` | Create | The action→wire→`open_questions` capture matrix (Tier-3) |
| `docs/research/g2408-capture-procedures.md` | Modify | Cross-link to the playbook |
| `custom_components/dreame_a2_mower/inventory.yaml` | Verify | The `open_questions` IDs the playbook cites exist |

---

## Task 1: Author the capture-playbook research doc

**Files:**
- Create: `docs/research/g2408-app-capture-playbook-2026-06-09.md`

- [ ] **Step 1: Confirm the standard non-authoritative banner used by sibling dated docs**

Run: `head -15 docs/research/g2408-research-journal.md`
Expected: shows the "read for context, not current truth — inventory.yaml wins" banner. Reuse it verbatim at the top of the new doc.

- [ ] **Step 2: Write the doc**

Create `docs/research/g2408-app-capture-playbook-2026-06-09.md` with:
- The non-authoritative banner from Step 1.
- A one-paragraph purpose: the running shopping list of in-app actions for the next Mac MITM session (rig at `/Users/ok/dreame-mitm/`), closing the gaps the 2026-06-08/09 session left open.
- The entry format key: **Need / App action / Expected wire / Unblocks / Closes** — where **Closes** names the inventory **entry id** (the t-key, e.g. `MPOS`/`AIOBS`) for read-key gaps, or the string-prefixed token (e.g. `pre-layout`) for gaps inside multi-purpose entries. (`open_questions` are plain strings in this inventory, not `{id,text}` — see Task 3.)
- **Tier 1 — closeable from the HA box (no Mac rig)** table, transcribed from the spec §3: `MPOS PREI/PRE AIOBS RGBPSTA MITRC SCHDTV3` reads → run via `tools/probes/read_key_probe.py`; Closes the matching t-key entries `MPOS`, `PREI` (+ token `pre-layout`), `AIOBS` (token `aiobs-photo-index`), `RGBPSTA`, `MITRC`, `SCHDTV3`.
- **Tier 2 — needs the Mac app-MITM** entries §4.1–4.8 from the spec, verbatim, each with its `Closes:` reference: token `schdtv3-set`, tokens `pre-layout`+`pre-edgemaster-bit`, token `task-variant-params`, token `transient-obstacle-photo-api`, token `patrol-photo-bucket`, entry `AIOBS`/token `aiobs-photo-index`, token `cfg-write-path`, token `lidar-dense-source` (the last conditional on the Phase 1 LiDAR-parity finding).
- **Parked** §5: TIME write (conflicts with `project_g2408_app_only_settings`), Meari `video_tx` camera, backend-C adoption.
- **Artifact conventions** §6: `logs/miio-13267.jsonl`, `logs/api-calls.jsonl`, `relay/mqtt.log`, parser `scripts/parse-mqtt.py` (action params nested at `params.in[]`); media samples stay off-repo (privacy).
- A closing **closure protocol**: after each capture, write the decoded wire into `inventory.yaml` (`partial`→`confirmed`), close the matching `open_questions` ID, journal it; then the matching Phase 1-plan/Phase 2 item is ready to build.

All wire references carry `[dreame-app-implementation-guide-2026-06-09.md]` or `[UNKNOWN — to capture]`.

- [ ] **Step 3: Lint-check the markdown renders (no broken tables)**

Run: `grep -c "Closes" docs/research/g2408-app-capture-playbook-2026-06-09.md`
Expected: ≥ 12 (one per gap entry). Eyeball the file for table alignment.

- [ ] **Step 4: Commit**

```bash
git add docs/research/g2408-app-capture-playbook-2026-06-09.md
git commit -m "docs(research): app-capture playbook — in-app actions → wire → open_questions"
```

---

## Task 2: Cross-link from the capture-procedures doc

**Files:**
- Modify: `docs/research/g2408-capture-procedures.md`

- [ ] **Step 1: Find the intro / index section**

Run: `sed -n '1,40p' docs/research/g2408-capture-procedures.md`
Expected: shows where to add a pointer near the top.

- [ ] **Step 2: Add the cross-link**

Insert near the top:
```markdown
> **App-side write/photo captures:** for the specific in-app actions that
> reveal write formats and photo APIs we don't yet have (schedule SET, PRE
> OFF/ON diff, TASK variants, real-mow obstacle photos, patrol photos), see
> [g2408-app-capture-playbook-2026-06-09.md](g2408-app-capture-playbook-2026-06-09.md).
> That doc maps each gap to the exact app action and the `inventory.yaml`
> `open_questions` ID it closes.
```

- [ ] **Step 3: Commit**

```bash
git add docs/research/g2408-capture-procedures.md
git commit -m "docs(research): link capture-procedures → app-capture playbook"
```

---

## Task 3: Verify the `open_questions` contract

**Files:**
- Verify: `custom_components/dreame_a2_mower/inventory.yaml`

- [ ] **Step 1: Check every gap the playbook references exists in the inventory**

`open_questions` here are **plain strings** (not `{id,text}`). Read-key gaps are
keyed by the inventory **entry id** (the t-key); the rest are string-prefixed
tokens inside multi-purpose entries. Check both:

```bash
# Read-key gaps — keyed by entry id (the t-key)
for k in MPOS AIOBS RGBPSTA SCHDTV3 MAPI MAPL MISTA OBS PREI REMOTE IOT MITRC; do
  grep -q "id: \"$k\"" custom_components/dreame_a2_mower/inventory.yaml && echo "OK   $k" || echo "MISS $k";
done
# String-token gaps inside multi-purpose entries
for t in pre-layout pre-edgemaster-bit transient-obstacle-photo-api patrol-photo-bucket aiobs-photo-index schdtv3-set task-variant-params cfg-write-path; do
  grep -q "$t" custom_components/dreame_a2_mower/inventory.yaml && echo "OK   $t" || echo "MISS $t";
done
```
Expected: all `OK`. A `MISS` on a read-key means Phase 1 Task 1 didn't add that
t-key entry — fix there. A `MISS` on a string token means the gap isn't recorded
yet: `schdtv3-set`, `task-variant-params`, `cfg-write-path` are write-capture
gaps the playbook introduces — add them as plain-string `open_questions`
(prefixed `<token>:`) on the relevant entries (`SCHDTV3` / the routed-action
TASK entry / `cfg_individual`) now.

- [ ] **Step 2: If any were added, validate + commit**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
git add custom_components/dreame_a2_mower/inventory.yaml
git commit -m "docs(inventory): add playbook open_questions (patrol-photo-bucket, cfg-write-path)"
```

---

## Spec coverage self-check

| Spec B section | Task |
|---|---|
| §3 Tier 1 (HA-box reads) | 1 (table) + cross-ref to Phase 1 Task 9 |
| §4 Tier 2 (Mac MITM) entries 4.1–4.8 | 1 |
| §5 Parked notes | 1 |
| §6 Artifact conventions | 1 |
| `open_questions` closure contract | 1, 3 |
| Cross-link to capture-procedures | 2 |
