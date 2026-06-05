# Parent-directory Reorganization — Design

**Date:** 2026-06-05
**Status:** approved (brainstorming → ready for writing-plans)

## Goal

Reorganize the dev-box parent directory `/data/claude/homeassistant/` into a small
set of domain directories so that scripts and output stop accumulating at the top
level — both for the current mess and for future debugging/investigations. Move
**everything** outside the untouched prod/infra/archive set into a relevant domain,
including the load-bearing items the repo's tools read by hardcoded path
(probe-log corpus, credentials, cloud-dump dirs), updating every reference.

## Why

`/data/claude/homeassistant/` has accumulated ~18 loose scripts, ~300 MB of probe
logs, 6 stale HA-log downloads, credentials, and a dozen output/reference
directories (five of them 163 MB of finished migration output). It is hard to tell
prod code from scratch, capture output from reference data, or live corpus from
dead one-offs. The fix is the same pattern used for the `tools/` cleanup: a handful
of well-named domain directories, scripts at each domain root, output flat in a
per-domain subdirectory, dead/finished artifacts evicted to `OLD/`, and a written
convention so new work lands in the right place instead of the top level.

## Design principles (user-decided)

- **Move everything**, including credentials and the prod-read corpus/dump dirs;
  update every hardcoded reference (grep-swept, like the tools cleanup).
- **All probe logs stay live** — every `probe_log_*.jsonl` (even the oldest) is
  actively used, so they all move into the probe domain's output dir, none evicted.
- **Output is flat files in one dir per domain.** Timestamped output *files* (the
  probe logs) live flat in a single directory for overview/readability — NOT in
  per-timestamp subdirectories. Only genuinely multi-file capture *sets* keep a
  per-capture subdir.
- **Archive dead/finished work to `OLD/`** (consistent with the docs/tools eviction
  pattern); nothing deleted.
- **A documented convention, no helper script.** A top-level `README.md` describes
  the domain map and the "where new things go" rule; discipline + memory enforce it.
- **The live integration is unaffected** — it runs on the HA box and reads none of
  these `/data/claude/...` paths at runtime (verified: zero credential/corpus refs
  in `custom_components/` runtime code). Only dev tools and scripts read them.

## Target layout

```
/data/claude/homeassistant/
  ── untouched: prod + infra + archive ──
  ha-dreame-a2-mower/              # prod integration (HACS)
  ha-dreame-a2-mower-worktrees/    # git worktrees
  OLD/                             # archive (grows)
  .venv-vanilla/  .claude/  .pytest_cache/  .playwright-mcp/  __pycache__/

  ── working domains ──
  probe/                           # MQTT wire capture
    probe_a2_mqtt.py  probe_a2.py  probe_a2_endpoints.py
    mower_tail.py  map_event_watcher.sh
    logs/                          # ALL probe_log_*.jsonl (flat, ~300 MB)
  cloud/                           # cloud / app-API probing
    dreame_cloud_dump.py  probe_ai_photo.py  fetch_session_photos.py
    capture_ai_obstacle.py  probe_obj_types.py
    dumps/                         # was dreame_cloud_dumps/ + api_discovery_raw_batch.json
    oss/                           # was oss_dumps/
    captures/                      # ai_obstacle_capture_*/ , patrol_oss_*/ (multi-file sets)
  analysis/                        # corpus analysis / investigations
    motion_vectors_correlate.py  analyze_move_corpus.py
  artifacts/                       # device-side reference blobs (read-only, large)
    apks/  fw_download/  lidar_scans/  proxyman/

  ── support ──
  secrets/                         # *-credentials.txt
  ha-logs/                         # downloaded HA logs (future home; documented)
  notes/                           # startup.md  patrol_capture_*.md
                                   # dreame-app-sessions-*.txt  install.sh
  README.md                        # the conventions doc
```

## Full disposition table

Every current top-level item maps to exactly one destination.

| Item (current) | Destination | Note |
|---|---|---|
| `probe_a2.py`, `probe_a2_mqtt.py`, `probe_a2_endpoints.py` | `probe/` | MQTT capture scripts |
| `mower_tail.py`, `map_event_watcher.sh` | `probe/` | live monitoring |
| `probe_log_*.jsonl` (9 files) | `probe/logs/` | the corpus, flat |
| `dreame_cloud_dump.py`, `probe_ai_photo.py`, `fetch_session_photos.py`, `capture_ai_obstacle.py`, `probe_obj_types.py` | `cloud/` | cloud/API scripts |
| `dreame_cloud_dumps/` (rename) | `cloud/dumps/` | cited evidence — see ripple |
| `api_discovery_raw_batch.json` | `cloud/dumps/` | |
| `oss_dumps/` (rename) | `cloud/oss/` | |
| `ai_obstacle_capture_20260531_123842/`, `patrol_oss_20260603/` | `cloud/captures/` | multi-file capture sets keep their dir |
| `motion_vectors_correlate.py`, `analyze_move_corpus.py` | `analysis/` | reads the corpus |
| `apks/`, `fw_download/`, `lidar_scans/`, `proxyman/` | `artifacts/` | reference blobs |
| `ha-credentials.txt`, `server-credentials.txt`, `location-credentials.txt`, `ha-web-credentials.txt` | `secrets/` | 7-file ref ripple |
| `startup.md`, `patrol_capture_20260603.md`, `dreame-app-sessions-2026-05-15.txt`, `install.sh` | `notes/` | reference notes/setup |
| `session_migrate_20260528-*` (×5, 163 MB) | `OLD/` | finished migration output |
| `_b4b10.py`, `_corpus.py`, `_reorient.py`, `_s1p1.py`, `_scan2.py`, `_slotscan.py`, `_win.py` | `OLD/` | scratch |
| `_handoff/` (`RESUME.md`) | `OLD/` | stale handoff |
| `home-assistant_*.log` (×6) | `OLD/` | stale HA-log downloads |
| `url` | `OLD/` | stale signed camera URL |
| `.claude/`, `.playwright-mcp/`, `.pytest_cache/`, `.venv-vanilla/`, `__pycache__/`, `OLD/`, `ha-dreame-a2-mower/`, `ha-dreame-a2-mower-worktrees/` | — | untouched |

Evictions go to `OLD/` mirroring a sensible path, e.g.
`OLD/ha-dreame-a2-mower-host/<original-name>` (a single bucket for host-level
dead artifacts), keeping them recoverable but out of the active tree.

## Load-bearing migrations (the reference ripple)

These four relocations require updating hardcoded paths. The plan must
**grep-sweep all of `/data/claude/homeassistant/` (repo + top-level scripts)** for
each moved name, not rely only on the lists below.

### A. Corpus → `probe/logs/`
- `ha-dreame-a2-mower/tools/inventory/wire_census.py:29` —
  `_DEFAULT_LOG_DIR = os.path.dirname(_REPO)` →
  `os.path.join(os.path.dirname(_REPO), "probe", "logs")`
- `ha-dreame-a2-mower/tools/inventory/inventory_audit.py:380` —
  `default=str(REPO_ROOT.parent / "probe_log_*.jsonl")` →
  `REPO_ROOT.parent / "probe" / "logs" / "probe_log_*.jsonl"`
- `ha-dreame-a2-mower/tools/session/rebuild_session.py:284` —
  `default="/data/claude/homeassistant/probe_log_*.jsonl"` →
  `".../probe/logs/probe_log_*.jsonl"`
- `probe/probe_a2_mqtt.py` — its write target (`log_file = f"probe_log_{ts}.jsonl"`,
  relative to CWD) must default to the `logs/` subdir so future captures land in
  `probe/logs/` (write to `<script_dir>/logs/probe_log_{ts}.jsonl`).
- `analysis/motion_vectors_correlate.py`, `analysis/analyze_move_corpus.py`,
  `probe/mower_tail.py` — update their corpus paths.

### B. Credentials → `secrets/` (7 referencing files)
- `ha-dreame-a2-mower/tools/release/release.sh`, `.../release/promote-latest.sh`
  (`HA_CRED="/data/claude/homeassistant/ha-credentials.txt"` →
  `.../secrets/ha-credentials.txt`)
- `ha-dreame-a2-mower/tools/probes/probe_add_maintenance_point.py`,
  `.../probes/probe_cruise_to_point.py`, `.../probes/probe_pre_write.py`
- `ha-dreame-a2-mower/tools/session/rebuild_session.py`
- `cloud/dreame_cloud_dump.py`
- Sweep for `server-credentials.txt`, `location-credentials.txt`,
  `ha-web-credentials.txt` too.

### C. `oss_dumps/` → `cloud/oss/`
- **`inventory.yaml` cites `oss_dumps/` ~11× as evidence-path pointers** (e.g.
  `oss_dumps/ali_dreame_…`, `oss_dumps/INDEX.txt`) — a mechanical `oss_dumps/` →
  `cloud/oss/` sweep, then regenerate `g2408-canonical.md`.
- Plus any script refs (`cloud/dreame_cloud_dump.py` etc.).

### D. `dreame_cloud_dumps/` → `cloud/dumps/` (heaviest ripple — 8 refs)
- `ha-dreame-a2-mower/tools/inventory/inventory_audit.py`,
  `.../tools/probes/inventory_probe.py`
- `cloud/dreame_cloud_dump.py`, `cloud/probe_ai_photo.py`
- **`ha-dreame-a2-mower/custom_components/dreame_a2_mower/inventory.yaml`** (evidence
  strings), `.../docs/TODO.md`, `.../docs/research/g2408-capture-procedures.md`
- `.../docs/research/inventory/generated/g2408-canonical.md` — **regenerate** after
  the inventory.yaml edit (`python tools/inventory/inventory_gen.py`), do not hand-edit.

## Forward convention (`README.md` at parent root)

A short doc containing:
1. The domain map (the layout above) — what each directory is for.
2. The rule: **new scripts live in their domain dir; output files go flat in that
   domain's output subdir (`probe/logs/`, `cloud/dumps/`, …); multi-file capture
   sets get one subdir under `<domain>/captures/`; finished one-offs and scratch are
   archived to `OLD/` when done; nothing accumulates at the top level.**
3. A pointer to the load-bearing paths a new contributor must not break
   (`probe/logs/` corpus, `secrets/`), and that the live integration reads none of
   these.

## Verification

- The live HA integration is unaffected (it reads no `/data/claude/...` path) — no
  HA restart needed; spot-check the mower is still functional.
- Each relocated dev tool still runs from the repo: `wire_census.py --log-dir`
  default resolves to `probe/logs/` and finds the 9 logs; `inventory_audit.py`
  walks the corpus from the new path; `rebuild_session.py --help` shows the new
  default; `release.sh` reads creds from `secrets/`.
- `python -m pytest tests/ -q` in the repo stays green (tests use fixtures, not the
  live corpus; the committed `wire-census.json` bridge is unchanged).
- `git status` in the repo shows only the intended ripple edits (tool defaults,
  cred paths, dreame_cloud_dumps refs, regenerated canonical doc) — and the repo's
  CI gates still pass (`inventory_gen --validate-only`, the wire-coverage gate).
- `ls /data/claude/homeassistant/` shows only the untouched set + the new domain
  dirs + `README.md` — no loose scripts, logs, or output files at the top level.

## Out of scope / non-goals

- **No deletion** — everything dead is archived to `OLD/`, not removed.
- **No change to the live integration's runtime behavior.**
- **No timestamped output subdirectories** — output files stay flat per domain.
- **No helper/automation** for the convention — documentation only.
- The repo internals (already reorganized) are touched ONLY for the reference-path
  updates above; no further tool reorganization.

## Edge cases & risks

- **The repo gets touched again** (tool defaults, cred paths, `dreame_cloud_dumps`
  refs, a regenerated canonical doc). This belongs on its own branch with the
  inventory-touch gate satisfied (the `inventory.yaml` evidence-path edits + canonical
  regen keep them in sync). It is the second repo change after the tools reorg.
- **`dreame_cloud_dumps` → `cloud/dumps/` edits `inventory.yaml`** (confirmed by the
  user 2026-06-05: move it and update the pointers). These are evidence *path
  pointers* (same class as the tool-path fixes already shipped), so updating them
  keeps the pointers valid; regenerate `g2408-canonical.md` afterward.
- **Large moves are same-filesystem `mv`** (instant): the 296 MB corpus, 2.2 GB
  `apks/`, 163 MB `session_migrate_*`. Never `cp` these.
- **The capture script's write target** must change with the move, or new captures
  silently land in the wrong place — easy to forget; explicitly in scope (item A).
- **Stale refs that don't exist** (`ha-token.txt`, `dreame-a2-icon-large.jpg`,
  `heading_correlate.py`) — do not create or chase them; leave the stale comment refs.
- **The spec/plan themselves** live in the repo's `docs/superpowers/` and move to
  `OLD/` when this ships (finishing-a-development-branch wrap-up).
