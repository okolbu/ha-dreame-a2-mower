# Parent-directory Reorganization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `/data/claude/homeassistant/` into domain directories (probe, cloud, analysis, artifacts, secrets, ha-logs, notes), moving everything — including the prod-read corpus, credentials, and cloud-dump dirs — and updating every hardcoded reference, so scripts/output stop piling up at the top level.

**Architecture:** Two kinds of action. (1) **Filesystem moves** in `/data/claude/homeassistant/` — `mv` operations on the dev box, NOT git-tracked, no commit. (2) **Repo reference edits** in `ha-dreame-a2-mower/` (tool defaults, credential paths, `inventory.yaml`/doc evidence paths, regenerated canonical doc) — committed on a feature branch, merged at the end. Both happen together so the moved data and the updated paths stay consistent.

**Tech Stack:** bash `mv`/`mkdir`, Python (venv at `/data/claude/homeassistant/.venv-vanilla`), pytest, `sed`, git, `gh`. Repo root: `/data/claude/homeassistant/ha-dreame-a2-mower`. Parent dir: `/data/claude/homeassistant`.

**Spec:** `docs/superpowers/specs/2026-06-05-parent-dir-reorg-design.md`

---

## Conventions for every task

- **pytest via the vanilla venv:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest …` (system python is broken).
- **Repo git commands run from** `/data/claude/homeassistant/ha-dreame-a2-mower`. **Filesystem moves run from** `/data/claude/homeassistant`.
- **Stage repo commits by EXPLICIT path** (`git add <paths>`), never `git add -A` — a separate process commits to this repo.
- **Same-filesystem `mv` is instant and safe** for the big items (296 MB corpus, 2.2 GB `apks/`, 163 MB `session_migrate_*`). Never `cp` these.
- **Do NOT push or merge** until the final task. Do NOT cut a release.
- The **live HA integration is unaffected** (it reads none of these paths) — no HA restart.
- Filesystem-move-only tasks have **no git commit** — their "verification" is `ls`/running a script.

---

## Setup: create the feature branch

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git checkout -b chore/parent-dir-reorg
git rev-parse --abbrev-ref HEAD   # expect: chore/parent-dir-reorg
```
Commit the spec + plan to the branch:
```bash
git add docs/superpowers/specs/2026-06-05-parent-dir-reorg-design.md docs/superpowers/plans/2026-06-05-parent-dir-reorg.md
git commit -m "docs: parent-dir reorg spec + plan

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 1: `probe/` domain — capture scripts + the corpus

**Filesystem moves** (parent dir):
```bash
cd /data/claude/homeassistant
mkdir -p probe/logs
mv probe_a2_mqtt.py probe_a2.py probe_a2_endpoints.py mower_tail.py map_event_watcher.sh probe/
mv probe_log_*.jsonl probe/logs/
```

**Parent-dir script edit** — `probe/probe_a2_mqtt.py` write target. Around line 1267-1269 it currently does:
```python
    if not log_file:
        ...
        log_file = f"probe_log_{ts}.jsonl"
```
Change so the default write lands in the `logs/` subdir next to the script (confirm `import os` is present at the top — add if missing):
```python
    if not log_file:
        ...
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"probe_log_{ts}.jsonl")
```
(Read the exact surrounding lines first; keep the `ts` computation as-is.)

**Repo edits** (commit) — update the three tools' corpus-default to `probe/logs/`:
- `tools/inventory/wire_census.py:29`
  `_DEFAULT_LOG_DIR = os.path.dirname(_REPO)  # /data/claude/homeassistant`
  → `_DEFAULT_LOG_DIR = os.path.join(os.path.dirname(_REPO), "probe", "logs")  # /data/claude/homeassistant/probe/logs`
- `tools/inventory/inventory_audit.py:380`
  `default=str(REPO_ROOT.parent / "probe_log_*.jsonl"),`
  → `default=str(REPO_ROOT.parent / "probe" / "logs" / "probe_log_*.jsonl"),`
- `tools/session/rebuild_session.py:284`
  `default="/data/claude/homeassistant/probe_log_*.jsonl",`
  → `default="/data/claude/homeassistant/probe/logs/probe_log_*.jsonl",`

- [ ] **Step 1** — run the filesystem moves above. Verify: `ls probe/ probe/logs/ | head` shows the 5 scripts and 9 `probe_log_*.jsonl`; `ls /data/claude/homeassistant/probe_log_*.jsonl 2>&1` reports "No such file" (none left at top level).
- [ ] **Step 2** — apply the `probe_a2_mqtt.py` write-target edit (parent-dir file).
- [ ] **Step 3** — apply the three repo corpus-default edits.
- [ ] **Step 4 — verify the corpus is found at the new path.** The wire-census regenerates from the default log dir; if the path is right and the corpus intact, the committed JSON is unchanged:
  ```bash
  cd /data/claude/homeassistant/ha-dreame-a2-mower
  /data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/wire_census.py
  git diff --stat docs/research/wire-census.json
  ```
  Expected: `wrote …/wire-census.json` AND **an empty diff** (same corpus → same census; proves the 9 logs were found at `probe/logs/`). If the diff is large/non-empty, the path is wrong — STOP and fix.
- [ ] **Step 5 — repo suite still green:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q` → all pass.
- [ ] **Step 6 — commit the repo edits** (explicit paths; the parent-dir moves + `probe_a2_mqtt.py` are not git-tracked):
  ```bash
  git add tools/inventory/wire_census.py tools/inventory/inventory_audit.py tools/session/rebuild_session.py
  git commit -m "chore(tools): point corpus defaults at probe/logs/ after parent-dir reorg

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: `cloud/` domain — cloud scripts, dumps, oss, captures (heaviest ripple)

**Filesystem moves** (parent dir):
```bash
cd /data/claude/homeassistant
mkdir -p cloud
mv dreame_cloud_dump.py probe_ai_photo.py fetch_session_photos.py capture_ai_obstacle.py probe_obj_types.py cloud/
mv dreame_cloud_dumps cloud/dumps
mv api_discovery_raw_batch.json cloud/dumps/
mv oss_dumps cloud/oss
mkdir -p cloud/captures
mv ai_obstacle_capture_20260531_123842 patrol_oss_20260603 cloud/captures/
```

**Parent-dir script edits** — `cloud/dreame_cloud_dump.py`:
- line ~386 `default="/data/claude/homeassistant/dreame_cloud_dumps"` → `default="/data/claude/homeassistant/cloud/dumps"`
- line ~4 docstring `./dreame_cloud_dumps/` → `./cloud/dumps/`
(The credential default on line ~381 is handled in Task 3.)
And `cloud/probe_ai_photo.py` line ~10 docstring `dreame_cloud_dumps/` → `cloud/dumps/`.

**Repo edits** (commit):
- `tools/inventory/inventory_audit.py:384`
  `default=str(REPO_ROOT.parent / "dreame_cloud_dumps" / "dump_*.json"),`
  → `default=str(REPO_ROOT.parent / "cloud" / "dumps" / "dump_*.json"),`
- `tools/probes/inventory_probe.py:66` docstring `dreame_cloud_dumps/*.json` → `cloud/dumps/*.json`
- **`custom_components/dreame_a2_mower/inventory.yaml`** — mechanical evidence-path sweep. Use the BARE names (not `name/`) — one evidence string is `"oss_dumps patrol …"` with no trailing slash. `dreame_cloud_dumps` (plural dir) does NOT match the `dreame_cloud_dump.py` script name (singular), so this is safe:
  ```bash
  cd /data/claude/homeassistant/ha-dreame-a2-mower
  sed -i 's#oss_dumps#cloud/oss#g; s#dreame_cloud_dumps#cloud/dumps#g' custom_components/dreame_a2_mower/inventory.yaml
  ```
  (11 `oss_dumps` + 3 `dreame_cloud_dumps` evidence pointers → the new relative paths.)
- `docs/TODO.md`, `docs/research/g2408-capture-procedures.md` — same bare-name sed:
  ```bash
  sed -i 's#oss_dumps#cloud/oss#g; s#dreame_cloud_dumps#cloud/dumps#g' docs/TODO.md docs/research/g2408-capture-procedures.md
  ```
- **Regenerate** the canonical doc (do NOT hand-edit it):
  ```bash
  /data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py
  ```

- [ ] **Step 1** — run the filesystem moves. Verify: `ls cloud/ cloud/dumps/ cloud/oss/ cloud/captures/` shows the 5 scripts, the dump JSONs + `api_discovery_raw_batch.json`, the oss blobs, and the 2 capture dirs; `ls /data/claude/homeassistant/{dreame_cloud_dumps,oss_dumps} 2>&1` reports "No such file".
- [ ] **Step 2** — apply the `cloud/dreame_cloud_dump.py` + `cloud/probe_ai_photo.py` docstring/default edits (parent-dir files).
- [ ] **Step 3** — apply the two repo code edits (`inventory_audit.py:384`, `inventory_probe.py:66`).
- [ ] **Step 4** — run the `sed` sweeps on `inventory.yaml`, `docs/TODO.md`, `docs/research/g2408-capture-procedures.md`. Verify no stale refs remain in those files: `grep -nE 'oss_dumps|dreame_cloud_dumps' custom_components/dreame_a2_mower/inventory.yaml docs/TODO.md docs/research/g2408-capture-procedures.md` → no output.
- [ ] **Step 5** — regenerate the canonical doc; sanity-check the diff is only path strings + whatever inventory already changed: `git diff --stat docs/research/inventory/generated/g2408-canonical.md` (small diff expected).
- [ ] **Step 6 — validate inventory + suite:**
  ```bash
  /data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only   # ok: inventory schema valid
  /data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory tests/tools -q          # all pass
  ```
- [ ] **Step 7 — commit** (explicit paths):
  ```bash
  git add tools/inventory/inventory_audit.py tools/probes/inventory_probe.py \
          custom_components/dreame_a2_mower/inventory.yaml docs/TODO.md \
          docs/research/g2408-capture-procedures.md docs/research/inventory/generated/g2408-canonical.md
  git commit -m "chore: repoint dump-dir evidence paths to cloud/{dumps,oss}/ after parent-dir reorg

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: `secrets/` domain — credentials

**Filesystem moves** (parent dir):
```bash
cd /data/claude/homeassistant
mkdir -p secrets
mv ha-credentials.txt server-credentials.txt location-credentials.txt ha-web-credentials.txt secrets/
```

**Repo edits** (commit) — repoint every credential reference to `secrets/`:
- `tools/release/release.sh:40` `HA_CRED="/data/claude/homeassistant/ha-credentials.txt"` → `.../secrets/ha-credentials.txt`
- `tools/release/promote-latest.sh:70` `HA_TOKEN_FILE="${HA_TOKEN_FILE:-/data/claude/homeassistant/ha-credentials.txt}"` → `.../secrets/ha-credentials.txt`
- `tools/probes/probe_cruise_to_point.py:264` `DEFAULT_CREDS_PATH = "/data/claude/homeassistant/server-credentials.txt"` → `.../secrets/server-credentials.txt` (and the docstring at line ~39)
- `tools/probes/probe_pre_write.py:209` same change (and docstring at line ~66)
- `tools/probes/probe_add_maintenance_point.py:95` `Path("/data/claude/homeassistant/server-credentials.txt")` → `Path(".../secrets/server-credentials.txt")`
- `tools/session/rebuild_session.py:289` `default="/data/claude/homeassistant/ha-credentials.txt",` → `.../secrets/ha-credentials.txt`

**Parent-dir script edit** — `cloud/dreame_cloud_dump.py:381` `default="/data/claude/homeassistant/server-credentials.txt"` → `.../secrets/server-credentials.txt`.

- [ ] **Step 1** — run the filesystem move. Verify `ls secrets/` shows the 4 cred files; `ls /data/claude/homeassistant/*-credentials.txt 2>&1` reports "No such file".
- [ ] **Step 2** — apply the 6 repo cred edits + the `cloud/dreame_cloud_dump.py` cred edit.
- [ ] **Step 3 — comprehensive sweep** for any missed credential path (repo + parent scripts):
  ```bash
  grep -rnE '/data/claude/homeassistant/(ha-credentials|server-credentials|location-credentials|ha-web-credentials)\.txt' \
    /data/claude/homeassistant/ha-dreame-a2-mower /data/claude/homeassistant/cloud /data/claude/homeassistant/probe /data/claude/homeassistant/analysis 2>/dev/null \
    | grep -v '/secrets/'
  ```
  Expected: no output (every cred path now goes through `secrets/`). Fix any hit.
- [ ] **Step 4 — verify release.sh reads creds from the new path** (dry, no release): confirm the path resolves —
  ```bash
  test -f "$(grep -oE '/data/claude/homeassistant/secrets/ha-credentials.txt' /data/claude/homeassistant/ha-dreame-a2-mower/tools/release/release.sh | head -1)" && echo "cred path OK"
  ```
  Expected: `cred path OK`.
- [ ] **Step 5 — repo suite green:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q`.
- [ ] **Step 6 — commit** (explicit paths):
  ```bash
  git add tools/release/release.sh tools/release/promote-latest.sh tools/probes/probe_cruise_to_point.py \
          tools/probes/probe_pre_write.py tools/probes/probe_add_maintenance_point.py tools/session/rebuild_session.py
  git commit -m "chore(tools): read credentials from secrets/ after parent-dir reorg

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: `analysis/` domain (parent-dir only — no commit)

```bash
cd /data/claude/homeassistant
mkdir -p analysis
mv motion_vectors_correlate.py analyze_move_corpus.py analysis/
```
Edit `analysis/analyze_move_corpus.py:45`:
`files = sorted(glob.glob("/data/claude/homeassistant/probe_log_*.jsonl"))`
→ `files = sorted(glob.glob("/data/claude/homeassistant/probe/logs/probe_log_*.jsonl"))`

- [ ] **Step 1** — move the two scripts; apply the corpus-path edit.
- [ ] **Step 2 — verify** `analyze_move_corpus.py` finds the corpus:
  ```bash
  /data/claude/homeassistant/.venv-vanilla/bin/python -c "import glob; print(len(glob.glob('/data/claude/homeassistant/probe/logs/probe_log_*.jsonl')), 'logs found')"
  ```
  Expected: `9 logs found`. (`motion_vectors_correlate.py` takes the log as argv — no path edit needed.)
- No commit (parent-dir files only).

---

### Task 5: `artifacts/` domain (parent-dir only — no commit)

Reference blobs that should have no abs-path references — verify, then move.

- [ ] **Step 1 — confirm nothing references them by abs path:**
  ```bash
  grep -rnE '/data/claude/homeassistant/(apks|fw_download|lidar_scans|proxyman)\b' \
    /data/claude/homeassistant/ha-dreame-a2-mower /data/claude/homeassistant/probe /data/claude/homeassistant/cloud /data/claude/homeassistant/analysis 2>/dev/null \
    | grep -vE 'OLD/|docs/research/(g2408-research-journal|wire-captures)'
  ```
  Expected: no output (only historical journal/wire-capture breadcrumbs are acceptable and stay). If a live code/tool ref appears, update it to `artifacts/<name>/` and note it.
- [ ] **Step 2 — run the move:**
  ```bash
  cd /data/claude/homeassistant
  mkdir -p artifacts
  mv apks fw_download lidar_scans proxyman artifacts/
  ```
  Verify `ls artifacts/` shows `apks  fw_download  lidar_scans  proxyman`; `ls -d /data/claude/homeassistant/{apks,fw_download,lidar_scans,proxyman} 2>&1` reports "No such file".
- No commit (unless Step 1 found a repo ref to update — then commit that file by explicit path).

---

### Task 6: `notes/` domain (parent-dir only — no commit)

```bash
cd /data/claude/homeassistant
mkdir -p notes
mv startup.md patrol_capture_20260603.md dreame-app-sessions-2026-05-15.txt install.sh notes/
```
- [ ] **Step 1** — run the move. Verify `ls notes/` shows the 4 files.
- No commit.

---

### Task 7: `ha-logs/` + evictions to `OLD/` (parent-dir only — no commit)

```bash
cd /data/claude/homeassistant
mkdir -p ha-logs
OLD=/data/claude/homeassistant/OLD/ha-dreame-a2-mower-host
mkdir -p "$OLD"
# evict finished/dead artifacts
mv session_migrate_20260528-202551 session_migrate_20260528-202925 session_migrate_20260528-203329 \
   session_migrate_20260528-212314 session_migrate_20260528-212403 "$OLD/"
mv _b4b10.py _corpus.py _reorient.py _s1p1.py _scan2.py _slotscan.py _win.py "$OLD/"
mv _handoff url "$OLD/"
mv home-assistant_*.log "$OLD/"
```
Create the `ha-logs/` README so the empty future-home dir is self-explaining:
```bash
printf '# ha-logs/\n\nDownloaded Home Assistant logs land here (e.g. via the HA web UI '"'"'Download full log'"'"').\nThe integration does not write logs to this dev box; these are manual pulls for debugging.\n' > ha-logs/README.md
```
- [ ] **Step 1** — run the evictions + create `ha-logs/README.md`. Verify:
  - `ls "$OLD"` shows the 5 `session_migrate_*`, 7 `_*.py`, `_handoff`, `url`, 6 `home-assistant_*.log`.
  - `ls /data/claude/homeassistant/_*.py /data/claude/homeassistant/session_migrate_* /data/claude/homeassistant/home-assistant_*.log 2>&1 | grep -c 'No such file'` ≥ 1 (none left at top level).
- No commit.

---

### Task 8: parent-root `README.md` convention doc (parent-dir only — no commit)

Create `/data/claude/homeassistant/README.md` (NOT in the repo — a dev-box convention doc):
```markdown
# /data/claude/homeassistant — dev-box layout

Working area for the Dreame A2 mower integration. Keep the top level clean:
**scripts live in their domain dir; output files go flat in that domain's output
subdir; multi-file capture sets get one subdir under `<domain>/captures/`;
finished one-offs and scratch are archived to `OLD/` when done.**

## Directories
- `ha-dreame-a2-mower/` — the integration (prod, HACS). Has its own `tools/`.
- `ha-dreame-a2-mower-worktrees/` — git worktrees.
- `OLD/` — archive of historical/finished artifacts (docs, tools, host one-offs). Read-only.
- `probe/` — MQTT wire capture. Scripts at root; **all `probe_log_*.jsonl` live flat in `probe/logs/`** (the corpus the repo tools read).
- `cloud/` — cloud / app-API probing. Scripts at root; `dumps/` (cloud dumps), `oss/` (OSS session blobs), `captures/` (multi-file capture sets).
- `analysis/` — corpus analysis / investigation scripts.
- `artifacts/` — large read-only device-side reference (`apks/`, `fw_download/`, `lidar_scans/`, `proxyman/`).
- `secrets/` — credential files. Dev tools read creds from here.
- `ha-logs/` — manually downloaded HA logs.
- `notes/` — markdown notes + setup scripts.

## Load-bearing paths (do not break)
- The repo's tools read the corpus from `probe/logs/` and credentials from `secrets/`.
- The live integration runs on the HA box and reads **none** of these dev-box paths.
```
- [ ] **Step 1** — create the file. Verify `head -3 /data/claude/homeassistant/README.md`.
- No commit.

---

### Task 9: Final verification + merge

- [ ] **Step 1 — top level is clean.** `ls /data/claude/homeassistant/` shows ONLY: `OLD  README.md  analysis  artifacts  cloud  ha-dreame-a2-mower  ha-dreame-a2-mower-worktrees  ha-logs  notes  probe  secrets` (+ dotfiles `.claude .playwright-mcp .pytest_cache .venv-vanilla` and `__pycache__`). No loose `.py`/`.sh`/`.jsonl`/`.log`/`.txt`/`.json`/`.md` (other than `README.md`) at the top level:
  ```bash
  ls -p /data/claude/homeassistant | grep -vE '/$|^README.md$'
  ```
  Expected: no output.
- [ ] **Step 2 — tools run from the new corpus path.** From the repo:
  ```bash
  /data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/wire_census.py && git diff --stat docs/research/wire-census.json
  /data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_audit.py
  /data/claude/homeassistant/.venv-vanilla/bin/python tools/session/rebuild_session.py --help | grep -i probe/logs
  ```
  Expected: wire-census diff empty (corpus found at `probe/logs/`); inventory_audit runs clean; rebuild_session `--help` shows the `probe/logs/` default.
- [ ] **Step 3 — full repo suite green + inventory valid:**
  ```bash
  /data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q
  /data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
  ```
  Expected: ~2013 passed / 4 skipped; `ok: inventory schema valid`.
- [ ] **Step 4 — no stale top-level abs-path refs remain in code:**
  ```bash
  grep -rnE '/data/claude/homeassistant/(probe_log_|ha-credentials|server-credentials|location-credentials|ha-web-credentials|dreame_cloud_dumps|oss_dumps)' \
    /data/claude/homeassistant/ha-dreame-a2-mower /data/claude/homeassistant/probe /data/claude/homeassistant/cloud /data/claude/homeassistant/analysis 2>/dev/null \
    | grep -vE 'probe/logs/|/secrets/|cloud/(dumps|oss)/|OLD/'
  ```
  Expected: no output (or only historical journal/wire-capture breadcrumbs under `docs/research/` describing past events — leave those).
- [ ] **Step 5 — merge to main** (the branch carries only the repo ref-edits; the filesystem moves are already live):
  ```bash
  cd /data/claude/homeassistant/ha-dreame-a2-mower
  git checkout main && git merge chore/parent-dir-reorg
  /data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q   # re-verify on merged main
  git branch -d chore/parent-dir-reorg
  ```
  (Pushing is a separate explicit step — do not push unless asked.)

---

## Final verification checklist (after Task 9)

- [ ] `ls /data/claude/homeassistant/` shows only the domain dirs + untouched set + `README.md`.
- [ ] `probe/logs/` holds all 9 `probe_log_*.jsonl`; nothing matches `/data/claude/homeassistant/probe_log_*.jsonl`.
- [ ] `secrets/` holds the 4 cred files; nothing matches `/data/claude/homeassistant/*-credentials.txt`.
- [ ] `cloud/dumps/`, `cloud/oss/`, `cloud/captures/` populated; `dreame_cloud_dumps`/`oss_dumps` gone from top level.
- [ ] `OLD/ha-dreame-a2-mower-host/` holds the 5 `session_migrate_*`, the `_*.py` scratch, `_handoff`, `url`, 6 HA logs.
- [ ] `git diff docs/research/wire-census.json` empty after regenerating (corpus intact at new path).
- [ ] Repo suite green on merged main; `inventory_gen --validate-only` OK.
