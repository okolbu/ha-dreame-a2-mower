# Cloud read/write reference (g2408)

> **Status — AUTHORITATIVE.** Last live-verified 2026-06-09 against g2408 fw 4.3.6_0550 / int v1.0.2a10. Sections labelled **TBD** at the bottom of the file are research-only — everything above is verified live unless explicitly flagged otherwise. Per-entity read/write paths live in `custom_components/dreame_a2_mower/entity-inventory.yaml`; this doc covers the *transport layer* (auth, endpoints, payload framing, response codes).

This document is the canonical reference for talking to g2408's Dreame
Cloud (`eu.iot.dreame.tech:19973`). It covers both READ and WRITE paths
across all surfaces the integration uses.

## Authentication

`DreameA2CloudClient(username, password, country="eu")` then
`client.login()`. Region for the user's account is `eu`. After login,
call `client.get_devices()` to discover the device, then
`client.get_device_info()` to populate `_host` (needed for routing).

## READ — `get_batch_device_datas([])`

The empty-list batch returns ALL chunked keys the device has.
Endpoint: `dreame-user-iot/iotuserdata/getDeviceData` (via wrapper).
Payload: `{"did": <did>, "model": [<key_list_or_empty>]}`.
Returns: `{<key>: <value>, ...}` dict.

Confirmed key families (g2408 fw 4.3.6_0550):
- `MAP.0..45 + MAP.info` — boundary geometry, mowing zones, exclusion
  zones, etc. Map 0 + Map 1 split at MAP.info byte offset.
- `M_PATH.0..N + M_PATH.info` — persisted mow trajectories from prior
  sessions. Per-map split at M_PATH.info byte offset.
- `SETTINGS.0..N + SETTINGS.info` — per-map mowing-behaviour settings
  (mowingHeight, mowingDirection, edgeMowingAuto, etc.). Dual-level
  structure: two top-level entries, both `mode: 0`. **Entry 0 is the
  user-saved entry** (apps and HA both read and write here; `version`
  field increments on each save). **Entry 1 is a firmware-applied
  mirror** that lags arbitrarily and stays at `version: 0` until the
  device pushes its applied state back. The integration reads `raw[0]`
  and writes to ALL entries — see "Dual-entry semantic" below.
- `SCHEDULE.0 + SCHEDULE.info` — schedule slots + plans. JSON shape
  `{"d": [[id, mode, name, base64_blob], ...], "v": version}`. The
  per-slot `mode` field (entry index 1, NOT the SETTINGS top-level
  `mode`) is **1 for the active/primary slot, 0 for an empty/secondary
  slot** — must be round-tripped on writes; hardcoding 0 turns an
  active slot off (verified 2026-05-09 by parse/encode round-trip
  against live cloud value, byte-identical).
- `AI_HUMAN.0` — Capture Photos AI Obstacles toggle. JSON-encoded bool.
- `FBD_NTYPE.0 + .info` — forbidden-area node types per map.
- `OTA_INFO.0 + .info` — firmware update status `(int, percent_int)`.
- `TASKID.0 + .info` — current/last task ID.
- `prop.s_*` — Xiaomi-style standalone properties (auth_config, auto_upgrade, pri_plugin).

## WRITE — `setDeviceData` (the chunked-batch write surface)

**Confirmed working 2026-05-08 for AI_HUMAN, SCHEDULE, SETTINGS.**

Endpoint: `dreame-user-iot/iotuserdata/setDeviceData`
Payload: `{"did": <did>, "data": {<key>: <value>, ...}}`
Wrapper: `cloud_client.set_batch_device_datas(props)` (the wrapper
sends payload under `data`, NOT `model`).

**Server-enforced cap: 1024 chars per value.** Large blobs need
chunking: `KEY.0..N + KEY.info(total_length_str)`.

Use `cloud_client.write_chunked_key(key_prefix, value, info=None)` —
handles chunking automatically. `info` defaults to `str(len(value))`
when chunking; omitted for single-chunk writes (matches the
AI_HUMAN.0 / SCHEDULE.0 single-chunk pattern observed live).

**Success response:** `{"code": 0, "success": true, "msg": "设置成功"}`
("setup successful" in Chinese).

**Common failure response:**
- `{"code": 10007, "msg": "value值不能超过1024个字符"}` — value > 1024
  chars not chunked.
- `{"code": 10007, "msg": "data:must not be empty"}` — payload sent
  under wrong field name (e.g. `model` instead of `data`).
- `{"code": 80001, "msg": "设备可能不在线..."}` — wrong RPC path
  entirely (this is the rejection direct `set_properties` gives for
  most siids on g2408 — use this endpoint instead).

## Confirmed-writable keys (Phase 1)

| Key | Single-chunk? | Notes |
|---|---|---|
| `AI_HUMAN.0` | yes | JSON-encoded bool: `'"true"'` / `'"false"'` |
| `SCHEDULE.0` | yes (typically <500 chars) | Bump `v` field on each write; preserve per-slot `mode` (1=active, 0=empty) |
| `SETTINGS.0..N` | no — dual-level structure ~1780 chars | Read entry 0 (user-saved); writes propagate to ALL entries |

## Dual-entry semantic (SETTINGS)

`SETTINGS` always carries TWO top-level dict entries, both with
`mode: 0` and the same `settings` map_id keys. Despite the matching
keys their *values* can diverge — they are NOT interchangeable.

**Roles confirmed via controlled cloud diff 2026-05-09** (g2408 fw
4.3.6_0550, two app instances + HA, snapshot before/after a Save in
the Dreame app):

- **Entry 0** = user-saved settings.
  - The `version` int inside each map's settings increments on every
    user save (78 → 79 in the captured diff).
  - All cloud writers (app and HA via `setDeviceData`) land here.
  - The Dreame app reads here. Confirmed because (a) the app device
    that performed the Save shows the new value immediately, and
    (b) a *second* app device on the same account, restarted right
    after the Save, also shows the new value — proving the source of
    truth is the cloud, not the local writer's cache.
- **Entry 1** = firmware-applied mirror.
  - The `version` int stays at 0; the device firmware updates this
    entry on its own schedule (after it actually applies a setting,
    which can lag arbitrarily — sometimes hours, sometimes never).
  - In the captured diff, the user toggled Animals OFF in the app
    (entry 0 went `obstacleAvoidanceAi: 6 → 5`) but entry 1 went
    `obstacleAvoidanceAi: 6 → 7` — reverting to a firmware-known
    value rather than tracking the user's request.

Concrete rule for any client:

1. **Read** entry 0 (`raw[0]`) as the canonical source of truth.
2. **Write** by mutating the target field on every entry that carries
   the target `map_id`. Other map_ids in those entries are left alone
   (preserves per-map customisation). Writing both entries is
   defensive — a reader of entry 1 (e.g. a future tool, a stale
   fixture) won't see a stale-mirror value.

### Cloud-side propagation lag

Captured 2026-05-09: a `setDeviceData` write of SETTINGS takes
**~5 minutes** to be reflected in a follow-up
`get_batch_device_datas` read. A read taken immediately after a
write returns the pre-write value. The integration's polling cadence
should account for this — a single 10-min poll right after a save
may still see stale data.

### Earlier misdiagnosis (commit `db507c9`)

An earlier hypothesis labelled entry 1 "firmware-authoritative"
based on the app appearing to ignore an HA write that touched only
entry 0. That conclusion was wrong: the test had the app open on
the AI Obstacle Recognition screen during the write, and the app's
cached UI never refreshed. Once the app forces a refresh (Save tap,
cold-start of a second device), it reads entry 0. The
"writing to BOTH entries" patch from `db507c9` is still kept as
defensive belt-and-braces — it doesn't hurt anything and it keeps
entry 1 in sync until the firmware mirrors back.

## SCHEDULE per-slot mode flag

The wire shape `[slot_id, mode, name, blob_b64]` carries a per-slot
`mode` (entry index 1) that is distinct from the SETTINGS top-level
`mode` field. Live values (verified 2026-05-09):

```
[0, 1, "Spr & Sum Schedule", <blob with 5 plans>]   # active/primary
[1, 0, "",                   <blob with 1 plan>]    # empty/secondary
```

The flag survives across captures even when the same slot's plan
list is edited, so it does NOT track plan count. Best current
hypothesis: 1=user-active, 0=template/empty. Whether the slot's
"Enabled" toggle in the app maps to this byte is not yet confirmed
(the blob is byte-identical between toggled and untoggled states —
the toggle lives elsewhere, see g2408-research-journal.md).

Round-trip rule: parsers MUST capture this byte and encoders MUST
re-emit it. Earlier integration code hardcoded `0` and would have
silently disabled an active slot on every save via the
`set_schedule_plans` service.

## TBD (Phase 2/3)

| Key | Status | Notes |
|---|---|---|
| `MAP.0..N` | NOT TESTED | Risk: corrupting boundary geometry could brick the map. Phase 2 — needs auto-backup mechanism. |
| `M_PATH.0..N` | NOT TESTED | Likely writable (same surface) but writing prior trajectories has no obvious user value. |
| `OTA_INFO.0` | UNSAFE | Firmware-managed; do not write. |
| `TASKID.0` | UNSAFE | Firmware-managed; do not write. |
| `FBD_NTYPE.0` | NOT TESTED | Phase 2 — likely writable; correlates with map editing. |
| `prop.s_*` | NOT TESTED | Probably read-only Xiaomi metadata. |

## CFG write surface — `set_cfg` (routed-action s2.aiid=50, m='s')

**Distinct from the chunked-batch surface above.** CFG keys (CLS, VOL, FDP,
WRP, DND, LOW, ATA, MSG_ALERT, VOICE, ...) live behind the routed-action
endpoint, not `setDeviceData`.

Wrapper: `cloud_client.set_cfg(key, value)` →
`{m: 's', t: <key>, d: <d_payload>}` sent as `in[0]` of an
`siid=2 aiid=50` action call. The `d_payload` shape depends on whether the
caller passes a primitive or a dict:

| Caller passes | Wire `d` payload | Used for |
|---|---|---|
| primitive (int / bool / list) | `{"value": <primitive>}` | Simple keys: CLS, VOL, FDP, STUN, AOP, PROT (single int); ATA (3-bool list); MSG_ALERT, VOICE (4-bool lists) |
| dict | `<dict>` (verbatim) | Complex keys with named slots: WRP, DND, LOW, LIT |

**Live-verified named-key payloads on g2408 (2026-05-09):**

| Key | Wire `d` payload | Status |
|---|---|---|
| `WRP` Rain Protection | `{"value": <0|1>, "time": <hours>}` | ✓ end-to-end (HA → cloud → device → app live-confirmed by 4h→6h→4h round-trip) |
| `DND` Do Not Disturb | `{"value": <0|1>, "time": [<start_min>, <end_min>]}` | ✓ cloud round-trip (device-apply inferred from same-code-path WRP test) |
| `LOW` Low Speed at Night | `{"value": <0|1>, "time": [<start_min>, <end_min>]}` | ✓ cloud round-trip |
| `LIT` Headlight | `{"value": <0|1>, "time": [<start>, <end>], "light": [l0,l1,l2,l3], "fill": <0|1>}` | ✓ cloud round-trip (entity still read-only pending write-side design) |

**Important g2408 quirk:** the bare `{"value": 0}` form ioBroker.dreame
documents for "off" is **rejected with `out[0].r=-3`** on g2408 — always
send the full named-key form regardless of the enabled bit. Optional WRP
`sen` (rain-sensor sensitivity) field is silently accepted with
`sen ∈ {0,1,2,3}` but `getCFG` returns only the 2-element `[enabled, hours]`
shape and the Dreame app on this firmware doesn't surface a sensitivity
UI — omitted from our writes.

**Response shape:** `{"code": <http_code>, "out": [{"r": <action_result>}]}`.
Both must be 0 for success — `code: 0` only confirms the cloud accepted
the request; `out[0].r: 0` confirms the device firmware accepted it.
Pre-v1.0.2a9 code only checked `code` and silently reported success while
every CFG write was being rejected with `r: -3`.

Source for the named-key catalog: ioBroker.dreame v0.3.7 (`OLD/alternatives_archive_2026-05-05/ioBroker.dreame/main.js:884-916, 3506-3565`). Per-key live-verification: `wire-captures/iobroker-write-catalog-2026-05-09.md`.

> **2026-06-09 confirmation:** The full CFG/PRE/routed write dictionary (all key names, d-payload shapes, and PRE index layout) is now confirmed by app-MITM — canonical record in `inventory.yaml § opcodes / cfg_keys`. Wire-capture evidence: `docs/research/wire-captures/app-settings-sweep-2026-06-09.md`. [app-mitm:2026-06-09-settings-sweep]

## CFG keys still rejected (Phase 3)

`BAT` (list[6] mixed), `REC` (list[9] mixed), `LANG` (list[2] mixed) all
return `r=-3` regardless of wrapped or named-key payload shape. ioBroker
doesn't enumerate them either. The Dreame app obviously writes them
(s2p51 push fires for these shapes have been observed weekly), so a
working write path exists — but it's not in our cloud_client repertoire
nor in ioBroker's. Needs an HTTPS sniff of the app's "Save" tap on the
notification-preferences / battery-window / language pages.

## Why `set_properties` (MIoT path) doesn't work for most siids

Direct MIoT `set_property(siid, piid, value)` rejects with **80001**
("device may be offline / command timeout") for most siids on g2408.
Tried 2026-05-08:
- `s8.2` (SCHEDULE per upstream docs) — 80001
- `s4.22` (AI_DETECTION per upstream docs) — 80001

The setDeviceData chunked-batch endpoint is the working alternative
for everything in the cloud-batch read surface. Direct MIoT may still
work for siids that came up in the integration's existing tested set
(`s2.50` routed_action for tasks, etc.).

## Live-test harness

Probes preserved in `/tmp/`:
- `probe_schedule_write.py` — schedule add/restore round-trip
- `probe_ai_human_write.py` — toggle round-trip
- `probe_writable_surface.py` — SETTINGS chunked round-trip
- `probe_batch_write.py` — payload-shape discovery (the original
  finding of `data` vs `model` field)

All bypass HA — pure Python with stubbed `homeassistant.const` import,
direct cloud_client usage. Useful template for Phase 2/3 probing.

## device/sendCommand — app-observed control path (2026-06-09, partial)

`POST eu.iot.dreame.tech:13267/dreame-iot-com-10000/device/sendCommand`
[dreame-app-implementation-guide-2026-06-09.md] — app-observed, not yet
re-verified on our client.

Outer: `{"id":N,"did":did,"data":{...},"sign":hmac,"timestamp":ms}`
Inner: `{"id":N,"did":did,"method":"action|get_properties|set_properties",
"from":"android","params":...}`. `action(siid:2,aiid:50)` multiplexes:
`{"m":"g","t":KEY,"d":args}` (read), `{"m":"s","t":KEY,"d":value}` (CFG write),
`{"m":"a","p":P,"o":opcode,"d":args}` (routed action). Spot mow live-confirmed:
`{"m":"a","p":0,"o":103,"d":{"area":[1]}}` → code:0.

**80001 reframe [app-observed only — UNVERIFIED on our client]:** the app's
`device/sendCommand` returned `code:0` online; whether the 80001 we see is
asleep/slow-prop-specific (vs RPC-inherent) is [UNKNOWN — to capture] — run
`tools/probes/read_key_probe.py` live against the online mower and compare
code:0 vs 80001 responses. See also sendCommand verification (Phase 1 Task 11).

### Our-client path vs the app (2026-06-09)

Code inspection of `cloud_client/_rpc.py` [cloud_client/_rpc.py:36–97,
99–190, 261–343]:

- **Endpoint:** Our client builds the URL as
  `f"{strings[37]}{host}/{strings[27]}/{strings[38]}"` → resolves to
  `dreame-iot-com{host}/device/sendCommand` (strings[37]="dreame-iot-com",
  strings[27]="device", strings[38]="sendCommand";
  `_rpc.py:69` and `_rpc.py:116`). That relative path is then prefixed by
  `get_api_url()` → `https://{country}.iot.dreame.tech:13267`
  (`_rpc.py:43–45`; strings[0]=".iot.dreame.tech", strings[1]="13267") via
  `_api_call` (`_rpc.py:36–41`). For `action` calls (the only method that
  reaches the device firmware on g2408), `host` is forced to `-10000` when the
  stored `_host` is non-numeric (`_rpc.py:64–66`, `_rpc.py:112–113`), so the
  full endpoint is `https://eu.iot.dreame.tech:13267/dreame-iot-com-10000/device/sendCommand`.
  **This is the same endpoint the app was observed hitting (`eu.iot.dreame.tech:13267
  /dreame-iot-com-10000/device/sendCommand`)** [dreame-app-implementation-guide-2026-06-09.md].

- **Inner envelope:** Our client sends
  `{"did": str(did), "id": N, "method": method, "params": params, "from": "XXXXXX"}`
  as the `data` field in the outer body (`_rpc.py:85–96` and `_rpc.py:131–144`).
  The app sends `{"id":N, "did":did, "method":"action|get_properties|set_properties",
  "from":"android", "params":...}` [dreame-app-implementation-guide-2026-06-09.md].
  The only structural difference is our `from` value (see below) and minor key
  ordering (immaterial to the server).

- **`from` value:** Our client sends `"from": "XXXXXX"` (`_rpc.py:93`,
  `_rpc.py:141`). The app sends `"from": "android"`. This is an obfuscated
  string in the legacy codebase. Whether the server validates this field is
  **[UNKNOWN — to capture]**: the integration has received `code:0` replies on
  `routed_action` calls (routed through this path) — suggesting the server
  either ignores the `from` field or accepts both values — but a controlled
  A/B test has not been run.

- **Outer envelope:** Our client does NOT add a `sign` (HMAC) or `timestamp`
  field to the outer JSON body (`_rpc.py:85–96`, `_rpc.py:131–144`). The app
  sends `{"id":N, "did":did, "data":{...}, "sign":hmac, "timestamp":ms}`
  [dreame-app-implementation-guide-2026-06-09.md]. The server accepts our
  unsigned requests — confirmed implicitly by `routed_action` `code:0` replies
  during live mow sessions — so sign/timestamp are either optional or
  server-generated server-side for the relay. **[UNKNOWN — to capture]** whether
  there is any scenario where the absent signature causes a rejection.

- **Content-Type:** The `request()` method (`_rpc.py:276–290`) has a
  `"Content-Type": "application/x-www-form-urlencoded"` literal key in the
  headers dict that is then overridden by `strings[51]: strings[52]` =
  `"Content-Type": "application/json"` (Python dict semantics: last assignment
  wins; `_rpc.py:284`). Effective Content-Type is therefore `application/json`,
  matching the app.

- **Verdict:** Our routed-action path **matches** the app's `device/sendCommand`
  endpoint on host, port, and path. The inner `method`/`params`/`did`/`id`
  envelope is structurally identical. The `from` string and missing
  `sign`/`timestamp` are differences, but the server accepts our payloads for
  `action` calls. No code change is needed based on the code-inspection evidence.
  If live tests reveal 80001 on paths that return `code:0` in the app, the first
  follow-up suspects are the `from` value and the absent signature (Phase 2).

**Deferred live check [UNKNOWN — to capture]:** run `tools/probes/read_key_probe.py`
against the live mower (online vs asleep) to confirm when `code:0` vs `80001`
actually occurs, validating the app-observed reframe that 80001 is
asleep/slow-prop-specific, not RPC-inherent.
