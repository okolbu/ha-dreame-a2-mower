# g2408 targeted capture plan — closing the open read/write tail (2026-06-28)

> **Read for action, not as truth.** Confirmed facts live in `inventory.yaml`.
> This plan lists the still-open items and the *correct* way to capture each.

## Framing (load-bearing — why the old probes failed)

The earlier probe sessions logged ~7,500 `api_probe` records that mostly returned
`property_count: 0, error: "device may be unreachable"`. That was **NOT genuine
unreachability** — it was the probes hitting **wrong backend endpoints**, chosen by
pattern-matching guesses against sibling repos / the apk. The 2026-06-09…-19
app-MITM runs (`miio-13267.jsonl`) revealed the **app's actual targets and
envelopes**, which we now know work (the integration uses them in production). So:

- The default assumption for an "open" item is **re-probe with the app's known
  endpoint**, not "needs a new MITM run." Most should now succeed directly.
- **Some attributes have MULTIPLE paths** (a few old trials *did* go through). E.g.
  `PRE` reads via the all-keys `getCFG` bundle AND the individual routed-get;
  `CRUISED` writes routed (`o=111`/CFG) but reads back via `CRUISE.0`. When one
  path 80001s, try the alternate and **record which path works per attribute.**
- The working transport is the app path: `action(siid:2, aiid:50)
  {"m":"g"|"s", "t":<KEY>, "d":<args>}` on `device/sendCommand` (code:0), and
  `get_properties` for siid/piid reads. Both are wired in `cloud_client`.

## Tooling (already exists — no new harness needed)

| Tool | Use |
|---|---|
| `tools/probes/_probe_common.py` `connect()` | auth + logged-in `DreameA2CloudClient` (creds from `server-credentials.txt`) |
| `tools/probes/read_key_probe.py` | routed-get for the app t-key vocabulary; pretty-prints raw responses. **Update its `KEYS` list with the MITM-confirmed `d:` args.** |
| `tools/probes/inventory_probe.py` | `get_properties` for apk-known unseen piids (siid-4 etc.); emits a delta JSON to merge by hand |
| `tools/probes/probe_settings_dump.py` | `fetch_full_cloud_state` — SETTINGS + map keying |
| `tools/probes/probe_pre_write.py` / `probe_cruise_to_point.py` / `probe_draw_shape.py` / `probe_add_maintenance_point.py` | write-path probes (use the app envelope) |

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/<tool>.py`

---

## TIER 1 — Direct re-probe (no MITM; correct app-target now known)

One read-only pass closes a cluster. Update `read_key_probe.py` `KEYS`/`d:` args from
the MITM, run it + `inventory_probe.py`, merge the delta.

| Open item(s) | Correct call (app target) | Closes |
|---|---|---|
| `s4p68` device_snapshot_bundle, `s4p83` device_capability, `s4p44` | `get_properties([{siid:4,piid:68/83/44}])` — siid-4 is poll-only (never pushes), old probes used wrong path | shape + presence on g2408 |
| `MAPI`/`MAPD` reassembly | `MAPI {idx}` → hash/size, then `MAPD {start,size}` paged | already decoded — re-pull to **reassemble full map JSON** as a parity check |
| `MITRC` track layout | already have a non-empty page (`id:3272`, base64) — **decode the captured base64**, no new capture | mission-track byte layout |
| `DEV.ota`, `DOCK.near_x/y/yaw`, `PIN.result/time`, `CMS[3]`, `DLS` | routed-get `{m:g,t:KEY}` (or `getCFG` bundle) | the residual fields on confirmed entries |
| `ARM`, `CHECK`, `RPET`, `WINFO`, `IOT` | routed-get with the app's `d:` args (old r=-3 was wrong args) | enum/shape of each; `IOT.status` confirmed true |
| `PREP.idx`, `MAPL[2..4]` | read now for baseline (full decode needs a 2nd zone / an edit — see Tier 3) | baseline values |

**Multi-path check:** for `PRE`, `MISTA`, `CRUISED`, run BOTH the routed-get and the
bundle/readback path; record which returns data (some only resolve on one path).

---

## TIER 2 — Trigger then read (direct action + read result)

| Item | Action | Read |
|---|---|---|
| `s2p58` self_check_result, `CHECK` self_check_command | trigger Self-Diagnosis (app Maintenance menu) **or** call the self-check action if its envelope is in the MITM | capture `s2p58` push + `CHECK` values |

---

## TIER 3 — App-MITM session (2nd device) — only for app-originated multi-sample / edits

These genuinely need the app to author them (single-variable diffs we can't synthesize):

- **`SCHD*V3` protobuf layout** — edit the schedule **one field at a time** (day, time,
  task, enable), capturing each `SCHDIV3`/`SCHDDV3`/`SCHDSV3` blob → map fields by diff.
- **Map-edit** — rename / delete / create a zone, set mowing-direction per map → closes
  `MAPL[2..4]` movement, `o=219` echo, and whether mowing-zone (not just exclusion) delete works.
- **Patrol variations** — patrol with different cycles/auto-capture + a multi-point route →
  `summary_point` third element, patrol summary field variation (corpus has only 1 patrol).
- **Manual-drive ×2+** (`o=15` echo reliability) and **multi-map-swap** (`o=200` echo conditionality).
- **Value-tied PRE `[8]/[11]/[17]/[18]`** (cutterPosition/edgeMowingNum/walkMode/OA-sensitivity):
  capture ONLY if the app exposes a control that varies them — user confirmed **no UI on 2.5.8.1**,
  so likely **unreachable**; do not chase unless a firmware update adds the control.

---

## TIER 4 — Physical / opportunistic (no MITM, no app — just trigger the condition)

Several "never-fired" catalog s2p2 codes are **physically triggerable** — induce the
condition during a short mow and the code pushes on `s2p2`:

| Code | How to induce |
|---|---|
| `38` ALERT_LIDAR_DIRTY | smear / cover the LiDAR briefly |
| `40`/`41` camera abnormal/blocked | cover the front camera |
| `37` FAULT_PATH_IMPASSABLE | block the path mid-mow |
| `20` FAULT_SENSOR (seen 1×) | reproduce to characterise which sensor |
| `OBS`/`AIOBS` non-empty rows | walk an obstacle in front during a mow (closes the row layout) |
| `IOT.status:false` | pull the device's network briefly |

**Permanently contributor-dependent** (cannot induce on this unit): the uint24 high
bytes `s1p4 [28]/[31]` need a lawn **>655 m²** (yours is 384 m²). Leave open, flagged.

---

## Priority / sequence

1. **Tier 1 read-only pass** (one `read_key_probe.py` + `inventory_probe.py` run) — highest
   yield, zero risk, no MITM. Do first; merge the delta into `inventory.yaml`.
2. **Tier 2** self-check trigger (quick).
3. **Tier 4** physical fault induction (a 10-minute mow with a few induced conditions
   closes several catalog codes + the obstacle row layout).
4. **Tier 3** one focused app-MITM session covering schedule + map-edit + patrol +
   manual-drive + map-swap in a single sweep (the toggle-by-toggle method that already
   worked on 06-16/06-19).
5. Leave the large-lawn uint24 bytes open (contributor-dependent).

Every captured value → record in `inventory.yaml` with provenance, per the fact-discipline
rule; note the **path that worked** (multi-path attributes). Fold this file into `TODO.md`
once the Tier-1 pass is done.
