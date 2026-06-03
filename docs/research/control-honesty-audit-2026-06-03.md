# Control-honesty audit — read-only-until-proven vs known-writable (2026-06-03)

**Lifecycle:** dated audit snapshot driving the TODO "Make controllable entities
honest." It cites the source-of-truth (`inventory.yaml`, `entity-inventory.yaml`,
the 2026-05-09 wire-captures) and flags contradictions — it does NOT assert new
protocol truth. Move to `OLD/` once the verdict lands as a `control_mode:` field
in `entity-inventory.yaml` and the representation work ships.

## What this audits

Every entity on a *control* platform (`number`, `select`, `switch`, `time`,
`lawn_mower`, `button`) classified by what its write handler ACTUALLY does on the
g2408 device — reconciling current code against `entity-inventory.yaml`
(`write_path` / `seen_working`) and `inventory.yaml` (protocol `decoded` +
`verifications`). Plus protocol knowledge in `inventory.yaml` not surfaced in code.

`entity-inventory.yaml`'s `seen_working: false` is NOT a verdict that a control
fails — for most it was simply never flipped. Classification is by code behaviour
+ wire evidence, not that flag.

## Buckets

- **A device-write-confirmed** — reaches firmware AND proven applied (live r=0 +
  behavioural/app proof or a `verified` inventory note). Honest.
- **B device-write-presumed** — real device RPC, NOT live-proven on g2408
  (untested / confirmed-by-analogue / accepted-but-no-observed-effect).
- **C cloud-cache-only / no-setter** — cloud accepts but firmware does NOT apply
  (`setDeviceData` SETTINGS surface, or CFG int-list keys returning `r=-3`).
  **MISLEADING**: the control looks operable and "sticks" but does nothing.
- **D read-only no-op** — renders an interactive control whose handler logs and
  returns (cfg_key omitted). **MISLEADING** by rendering as operable.
- **E integration-local (honest)** — no device write by design but legitimately
  controls integration state / rendering / selection. Operable and honest.

The honesty problem is **buckets C + D**. A and E are fine; B needs a probe.

## Classification (by entity class / template)

### A — device-write-confirmed (honest)
| entity | wire | evidence |
|---|---|---|
| `number.volume` (VOL) | CFG simple-int via `set_cfg {value}` | working-9 set [cfg-write-regression-2026-05-09.md:72] |
| `select.navigation_path` (PROT) | CFG simple-int 0/1 | working-9 set [cfg-write-regression-2026-05-09.md:72] |
| `switch.child_lock` (CLS) | CFG simple-int | behavioural cold-app test [cfg-write-regression-2026-05-09.md:65] |
| `switch.frost_protection` (FDP), `auto_recharge_standby` (STUN), `ai_obstacle_photos` (AOP) | CFG simple-int | working-9 [cfg-write-regression-2026-05-09.md:72] |
| `switch.anti_theft_lift_alarm`/`offmap_alarm`/`realtime_location` (ATA×3) | CFG all-bool list | working-9 [cfg-write-regression-2026-05-09.md:72] |
| `switch.msg_alert_*` (MSG_ALERT×4), `switch.voice_*` (VOICE×4) | CFG all-bool list | working-9 [cfg-write-regression-2026-05-09.md:72] |
| `button.start_mowing` + `lawn_mower.async_start_mowing` | s5a1 → routed op=100/101/102/103 | o100 seen_on_wire; o103 `verified` live 2026-05-31 [inventory o100/o103] |
| `button.find_bot` | routed op=9 | r:0 live 2026-05-31 [inventory o103 verification: "op=9 … r:0"] |
| `button.map_N_head_to_point` | routed op=109 | live-verified 2026-05-31 (drove to point) [inventory o109 verification] |

### B — device-write-presumed (real RPC, needs live proof)
| entity | wire | status | settling capture |
|---|---|---|---|
| `button.pause_mowing` + `lawn_mower.async_pause` | s5a4 direct (no routed_o) | confirmed-by-analogue, not verified [inventory s5a4] | mow → Pause → capture s2p1 WORKING→PAUSED or r:0 (direct path may 80001) |
| `button.stop_mowing` | s5a2 direct | confirmed, not verified [inventory s5a2] | mow → Stop → capture transition/r:0 |
| `button.recharge` + `lawn_mower.async_dock` | s5a3 direct | confirmed, not verified [inventory s5a3] | press → capture any→RETURNING→CHARGING |
| `select.active_map` | routed op=200 changeMap | inbound echo confirmed; no captured commit [inventory o200] | capture op=200 out[0].r=0 + MAPL flip |
| `button.lock_bot` | routed op=12 | **accepted-but-no-observed-effect** [project memory lock_robot_op12_incident]; inventory o12 `hypothesized` | likely stays B — no observable effect to confirm |
| `button.generate_3dmap` | routed op=10 `{idx:0}` | inventory o10 `hypothesized` AND named **uploadMap** (semantic drift — see below) | resolve name drift, then press docked & watch s2p54 progress + LiDAR slot |

NB the s5a2/3/4 family all use the **direct** siid/aiid path (no `routed_o`), which
returns 80001 on g2408 unless the cloud RPC tunnel is open — a single observation of
any one landing vs 80001 resolves the transport question for the whole non-routed set.

### C — cloud-cache-only / no-setter (MISLEADING — looks operable, device ignores)
Per-map SETTINGS surface (`setDeviceData` chunked-batch, cloud-cache-only on g2408)
[settings-surface-cloud-only-2026-05-09.md]:
- numbers: `mowing_height`, `cutter_position`, `cutter_position_height`,
  `edge_mowing_num`, `obstacle_avoidance_height`, `obstacle_avoidance_distance`,
  `obstacle_avoidance_sensitivity`
- selects: `mowing_direction`, `mowing_direction_mode`, `edge_walk_mode`
- switches: `automatic_edge_mowing`, `safe_edge_mowing`,
  `obstacle_avoidance_on_edges`, `lidar_obstacle_recognition`,
  `ai_recognition_humans`/`animals`/`objects` (obstacleAvoidanceAi bitmask — the
  exact field the cloud-cache-only test used)

CFG int-list / mixed keys with **no setter** (`r=-3`, fail honestly since set_cfg
parses `out[0].r`) [cfg-write-regression-2026-05-09.md:143]:
- `switch.dnd` (DND), `switch.low_speed_at_night` (LOW),
  `switch.custom_charging_period` (BAT), `number.auto_recharge_battery_pct` +
  `number.resume_battery_pct` (BAT)
- `switch.rain_protection` (WRP) + `select.rain_protection_resume_hours` (WRP) — **CONTRADICTION, see below**

Likely-C, untested:
- `switch.cloud_state_ai_human_enabled` (AI_HUMAN) — same `setDeviceData` transport;
  explicitly left untested [settings-surface-cloud-only-2026-05-09.md §AI_HUMAN]

### D — read-only no-op (renders interactive control, does nothing)
cfg_key omitted → handler logs + returns. Same pattern as the EdgeMaster precedent.
- `number.human_presence_alert_sensitivity` (REC[1]) — REC is a 9-elem list; only
  [0]/[1] stored, write would corrupt [2..8]
- `select.language` (raw LANG, diagnostic), `select.map_N_mowing_efficiency` (PRE —
  `r=-3`, no setter [pre-write-r3-2026-06-03.md])
- `switch.led_period`/`led_in_standby`/`led_in_working`/`led_in_charging`/`led_in_error` (LIT×5)
- `switch.human_presence_alert` (REC[0]), `switch.map_N_edgemaster` (PRE no-op precedent)

### E — integration-local (honest, no device write by design)
- `number.station_bearing_deg` (entry options + re-project), `number.trail_render_width` (render pref)
- `select.action_mode`, `work_log`, `lidar_archive`, `wifi_archive`,
  `map_N_zone_target`/`spot_target`/`edge_target`/`maintenance_point` (selection),
  `map_N_mowing_mode` (fires the op=100-103 launchers — the actions are bucket A)
- `button.refresh_cloud_state`, `refresh_wifi_heatmaps`, `finalize_session` (local_only)
- `time.*` (read-only)

## Open contradiction — WRP & LANG (BLOCKER for their A-vs-C verdict)

Two **same-day (2026-05-09)** records flatly disagree; cannot be resolved from docs:
- `cfg-write-regression-2026-05-09.md:143` lists **WRP and LANG** among the 7 keys
  that "genuinely don't have a setter … No format variation will make them accept" → **C**.
- `switch_global.py:_build_wrp` docstring: "Verified live 2026-05-09 (cloud + device
  app round-trip 4h→6h→4h)" → **A**.
- `select_global.py:_build_text_language` docstring: "device-apply confirmed
  2026-05-09 by user physically reading the mower's LCD" → **A**.

Plausible reconciliation: the regression probe tested bare/wrapped/named-key shapes;
the docstrings claim the **tagged-union** shapes `LANG {type,value}` / `WRP {value,time}`
which the regression r=-3 table may not have covered. **[UNKNOWN — to re-probe.]**
**Settling capture:** flip each through the CURRENT `set_cfg` (now parses `out[0].r`)
and read the r-code: `r=0` + behavioural change (LCD/voice flip; rain-resume change)
⇒ A and the regression doc's "no setter" line must be narrowed; `r=-3` ⇒ C and the
docstrings' "verified" claims must be **retracted** per fact-discipline. Until then
WRP/LANG are classified **C provisionally** (the safe/honest default).

## Protocol knowledge not covered in code (the "interesting gaps")

- **Patrol (`o107` point / `o108` edge)** — confirmed user-triggerable g2408 feature
  (blades-up), but **no button/service triggers it** (only post-hoc session typing).
  Strongest new-control candidate; blocked on capturing the outbound SEND payload. [inventory o107/o108]
- **`MISTA` (mission_status)** — confirmed cloud-poll mirror of s1p4 area counters,
  consumed by decoder + services.yaml only; **no sensor**. Candidate MQTT-unavailable
  fallback sensor (inventory's own open_question). [inventory MISTA]
- **Phantom-sensor inventory prose (fact-discipline cleanup)** — `WRF`, `TIME`, `VER`
  each have `semantic:` claiming "Surfaced as sensor.X" but **no such entity exists**
  in any platform / strings.json. Either build the (trivial, scalar) diagnostic
  sensors or correct the prose. [inventory WRF/TIME/VER]
- **Known-writable but intentionally not exposed** — REC[1] sensitivity and LIT have
  confirmed enums/shapes but stay read-only because MowerState stores only part of the
  wire list; exposing safely needs storing the full list first (not a protocol gap).
- **Inventory pointer gaps (not code gaps)** — `MAPL` is `integration_code: None` but
  heavily consumed; `mower/actions.py` line numbers in several `s5*`/find_bot/lock_bot/
  generate_3dmap `evidence`/`references` are stale (FIND_BOT cited :206, actually :225, etc.).
- **`o10` name drift (genuine wire-semantic disagreement)** — inventory `o10` is named
  **`upload_map`** ("the integration does not use this opcode") but the code maps
  `GENERATE_3D_MAP → routed_o=10`. Opcode agrees, meaning disagrees. Re-check against apk.

### Code on shaky protocol ground
None. Hypothesized slots (s2p2 37-78/117, s5p104-106, BP/DLS/PATH) are unreferenced,
raw-diagnostic-only, or gated out by the `test_error_codes_confidence_gate` CI test.

## Headline

The misleading set is **buckets C + D** — ~17 per-map SETTINGS controls + ~7 CFG
int-list controls (C) and ~10 cfg_key-omitted no-op controls (D). These render as
live, operable HA controls that the g2408 firmware never applies. Buckets A
(working-9 CFG + the routed op=100/9/109 actions) and E (integration-local) are
honest. B (s5a2/3/4 direct actions, op=200, op=10/12) needs live probes. WRP/LANG
are the one unresolved A-vs-C call, blocked on a re-probe.
