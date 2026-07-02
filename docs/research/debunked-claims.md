# Debunked claims register (negative knowledge — D-ids are citable)

> ⚠️ Every claim in this table is FALSE. This file exists so greps and future
> sessions find the debunking WITH the claim. Rules: (1) never copy a claim out
> of this table as fact; (2) tombstones and retractions cite "debunked-claims.md
> § D<n>"; (3) the truth column CITES inventory ids, it never restates values;
> (4) additions go through the inventory retraction flow (CLAUDE.md § Fact
> discipline) — this register indexes it, it does not replace it.

D1–D14 are unchanged from v0. D15–D20 are Track-1 additions, each with the
debunking evidence AND where the dead claim last lived (or still lives) on main.
Repo-relative paths are under `/data/claude/homeassistant/ha-dreame-a2-mower/`.

| # | DEBUNKED claim | Status of the truth | Evidence pointer |
|---|---|---|---|
| D1 | Settings the integration can't write are Bluetooth-mediated ("BT-vs-Cloud" framing) | g2408 has NO BT transport for settings; failures were cloud-cache-only | user ruling (memory feedback_no_bt_transport); inventory settings-transport sections |
| D2 | s2p2=28 is an "off-dock marker" | s2p2=28 = blade-wear; validated across the full probe corpus (~66 undocks) | inventory.yaml § s2p2; memory feedback_corpus_validate_protocol_claims |
| D3 | PRE properties are absent/unwritable on g2408 | PRE IS writable; the old negative was a wrong envelope | inventory.yaml § PRE; corrected app-MITM 2026-06 findings |
| D4 | FAULT_CODES table is the fault source of truth | DELETED; the RN-plugin fault catalog is wire-authoritative (fault_tier/event_slug derivation) | /data/claude/homeassistant/artifacts/g2408-plugin-extract/; fault-catalog specs 2026-06-19 (docs/superpowers/specs/) |
| D5 | MISTA r=-1/-3 means the endpoint is unsupported | MISTA mirrors s1p4 area counters (centiares); r=-1/-3 = idle, pollable mid-run only | inventory.yaml § MISTA |
| D6 | MIHIS.start is the per-unit first-mowing date | 1704038400 is a firmware-hardcoded sentinel (2023-12-31 UTC) | inventory.yaml § MIHIS |
| D7 | Album/AI photos live in Xiaomi FDS (479D) | They are in the dreame-eu Aliyun OSS bucket (app-MITM resolved 2026-06-09) | docs/research/g2408-app-capture-playbook-2026-06-09.md |
| D8 | Patrol cycles/auto-capture writes "don't stick" | Write WORKS (o=111+CRUISED, byte-exact); apparent failure was CRUISE.0 read-back lag | inventory.yaml § CRUISED; v1.0.29a3 notes |
| D9 | op=12 (lock) and op=10 (3dmap) do something | Both accepted-but-no-effect on g2408 (r=0, no behavior) | inventory.yaml § routed ops; live probes 2026-06 |
| D10 | s1p1 heartbeat carries numeric fault codes | s1p1 is a boolean-flag blob; the 45 "heartbeat codes" never fire on g2408 (93,888-sample corpus) | fault-catalog P4 finding; inventory.yaml § s1p1 |
| D11 | The live app map needs only what siid:6 offers | App live dense-LiDAR uses a surface our siid:6 path can't reach; needs app-RPC capture (open gap) | memory project_g2408_op10_3dmap_negative; docs/research/knowledge-gaps.md |
| D12 | upstream dreame-vacuum *CLEAN* property mappings apply to mowers | Vacuum-only; mower mappings differ | memory feedback_check_cloud_dump_first; /data/claude/homeassistant/cloud/dumps/ inventory |
| D13 | OTA `sign` is reproducible client-side | Token-auth no-sign path is what works; MD5 formula never reproduced golden | memory project_firmware_ota_findings_plan + project_getdevicefile_signer |
| D14 | Track over-segmentation markers are meaningful geometry | TRACK_BREAK_MARKER mid-mow creates junk single-point segments; trigger unknown (open) | inventory.yaml § summary_map_track |
| D15 | Cloud→device commands are dead on g2408 (80001 "consistently"); the integration is inherently **read-mostly**, and app config writes ride Bluetooth | The integration WRITES via cloud: routed s2.50 envelope (actions, TASK), CFG named-key, PRE, map-edit CRUD txn (o=200/204/201 family), schedule transport. Only certain direct MIoT paths 80001 (e.g. get_properties, s6.aiid=4). | Debunked by: inventory.yaml § routed-action opcodes (e.g. id `o223` confirmed), § CRUISED, § PRE; docs/research/cloud-write-reference.md. Dead claim STILL LIVES: docs/research/g2408-protocol.md:44-58 (Track-1 finding T1-2). |
| D16 | s1p53 is an "obstacle detected" flag | s1p53 = controlling-app BLE connection status (app foreground/background toggles it; user-reproducible at will) | Debunked by: inventory.yaml § s1p53 `bluetooth_connected` (apk name "BLE Connection Status" + live repro); relabel commit 9f551585. Dead claim last lived: pre-relabel binary_sensor (tombstone comment binary_sensor.py:98-104). |
| D17 | Pre-catalog / apk-lineage s2p2 names are current: 31/33 = "positioning-failed-stuck", 50 = "normal mow active", 71 = "positioning failure" (and ~15 other vacuum-lineage names) | S2P2_EVENT_TYPES is DERIVED from the wire-authoritative app catalog (`[apk:g2408-plugin-ext1423]`); 71 = standby-outside-station-too-long auto-return, NOT positioning-failed. Do not copy code→meaning pairs from any doc — read inventory.yaml § state_codes + mower/error_codes.py. | Debunked by: inventory.yaml § state_codes (incl. the explicit "71 is NOT positioning failed" note ~line 762); mower/error_codes.py:41-69 catalog derivation; vacuum-name cleanup commit ee2c999a; CI confidence gate (tests/inventory/test_error_codes_confidence_gate.py). Dead claim STILL LIVES: docs/research/g2408-protocol.md §6 table (Track-1 finding T1-1). |
| D18 | LOCN routed action is the mower GPS-position source (feeds position_lat/lon / device_tracker) | LOCN position write RETIRED; `_refresh_gps` (location/getRecords) is the sole position_lat/lon writer; s2p1 is the sole map-frame location authority. `fetch_locn` survives only as an unscheduled fetcher with zero integration callers. | Debunked by: retirement commit 1fa47a5b + dead-code removal 5f6d7068; coordinator/_core.py:673 comment; CLAUDE.md refresher-cadence note. Dead claim STILL LIVES: mower/state.py:166 source annotation (Track-1 finding T1-7). |
| D19 | Direct MIoT `s6.aiid=4` requests a fresh WiFi heatmap on demand | That RPC returns 80001 on g2408 (siid-6 tunnel closed); the device generates heatmaps on its own schedule, and only already-cached OSS objects are fetchable | Debunked by: inventory.yaml § wifi-map trigger verification (evidence lines ~2510-2517, live tests 2026-05-09 + 2026-05-31). Dead belief STILL ENCODED: `MowerAction.REQUEST_WIFI_MAP` mower/actions.py:322-327, test-only callers (Track-1 finding T1-5). |
| D20 | "Rain protection active" can be read as `error_code == 56` | s2p2=56 is true only for the instant of the rain push; the rain-delay WINDOW is tracked by coordinator `rain_delay_active` (start-ts + resume_hours) | Debunked by: entity-inventory retraction (archived per retraction policy in OLD/…/inventory-history/); corrected implementation + tombstone comment binary_sensor.py:110-118. |

Known-reversal ERAS for archaeology (walked by Track 1, 2026-07-02; per-era verdicts):
- pre-CloudState `_cached_*` caching era — DEAD on main; sole mention is the
  tombstone at cloud_state.py:3.
- single-map era (pre v1.0.3a9) — two live remnants found: `_settings_writes.py`
  map_id fallback (T1-6) and `fetch_wifi_map` legacy path (T1-4). Per-map
  entities static-at-setup is DESIGN, not residue (CLAUDE.md).
- pre-catalog fault surfacing era — code clean (D4); doc remnants: protocol.md §6
  (T1-1/D17) + shipped in-tree specs (T1-9).
- pre-CRUISED patrol era — code clean; current code documents CRUISE.0 read-back
  lag correctly (D8).
- LOCN endpoint era — refresher dead; annotation remnant (T1-7/D18); `fetch_locn`
  kept-unscheduled (T1-11).
- `_poll_slow_properties` era — code dead since 2026-05-26 (d7f06555); stale row
  remains in CLAUDE.md cadence table (T1-3).
- BT-framing era — no code transport remnants; doc remnants: protocol.md §1
  (T1-2/D1/D15) + one comment (_property_apply.py:108, T1-12).
- entity-validation-matrix era — matrix retired to OLD/ 2026-05-31; two stale
  citations remain (cloud_client/_oss.py:208 inside dead code, T1-4/T1-14).
