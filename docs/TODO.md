# Dreame A2 (`g2408`) — Open Work

Actionable items only. Each entry follows the shape:

```
### <One-line action title>

**Why:** brief reason this is open (1-3 sentences).
**Done when:** verifiable acceptance condition.
**Status:** {open, in-progress, blocked-by-X}
**Cross-refs:** journal topic, inventory row(s), spec/plan if any.
```

For resolved / closed items see `docs/DONE.md`.
For the protocol *blank-spots* (undecoded bits/bytes, uncertain slots, corpus
coverage + how to validate each) see `docs/research/knowledge-gaps.md`.
For shipped versions, resolved findings, and the RE journey see
`docs/research/g2408-research-journal.md`.
For overall protocol architecture see `docs/research/g2408-protocol.md`.
For per-slot detail see `docs/research/inventory/generated/g2408-canonical.md`.

---

## Open

### Sweep probe logs 2026-06-13 21:44 → now for novel slots/values (app "Bumper error" 21:45)

**Why:** A "Bumper error" appeared in the Dreame **app** logs ~2026-06-13 21:45 — likely a
new fault not yet reflected in the wire inventory. Same pattern that just surfaced s2p57
(first wire capture caught via the corpus). Worth a focused sweep of the capture window for
other firsts while it's fresh.
**Done when:** every novel `(siid, piid)` slot AND novel value in `probe/logs/probe_log_*.jsonl`
from 2026-06-13 21:44 through the latest capture is enumerated; the bumper-error event is
located on the wire (`error_code` s2p2 / s1p1 bumper bit / a new slot) and, if new, recorded in
`inventory.yaml` with evidence (+ `error_codes.py` only if the `state_codes` row reaches
confirmed/partial, per the confidence gate).
**Status:** open
**Cross-refs:** inventory `s2p57` (recorded 2026-06-14), `binary_sensor.bumper`,
`mower/error_codes.py` + inventory `state_codes`, `tools/probes/`, `docs/research/knowledge-gaps.md`.

### Control honesty — residual follow-ups (core shipped 2026-06-04)

**Core DONE** — the audit + `control_mode` classification + padlock/snap-back read-only
representation shipped in v1.0.22a4. See `DONE.md` "Make controllable entities honest"
and `docs/research/control-honesty-audit-2026-06-03.md`. What remains:

1. ~~**Mark provisional `device_write_unproven` controls.**~~ **DONE (2026-06-04).**
   `_ControlHonestyMixin` gained a `provisional` flag (= `device_write_unproven`) exposed via
   the `provisional` + `control_mode` extra-state-attributes; `_DreameA2ActionButton` (pause/
   stop/recharge/lock_bot/generate_3dmap) now carries it, and `select.active_map` inherits it
   from the mixin. Lightweight by design — operable, no padlock/snap-back, just a queryable
   attribute (dashboards can template a badge on `provisional`). They still need adding to the
   Phase-3 app-RPC capture list (folded into #2's bucket-B probes).
2. **Live re-probes to finalize uncertain classifications** (device-blocked):
   - **WRP, LANG (lcd/voice), AI_HUMAN** — held at `read_only_pending` due to the same-day
     (2026-05-09) contradiction: `cfg-write-regression` ("no setter, r=-3") vs the
     `_build_wrp`/`_build_text_language` docstrings ("verified live"). Re-probe via the
     current `set_cfg` (parses `out[0].r`): r=0+behaviour ⇒ flip to `device_writable`; r=-3
     ⇒ `read_only_confirmed` and retract the docstring claim. One line in `CONTROL_MODES` +
     the matching inventory row per flip (the sync test enforces both).
   - **Bucket B actions:** s5a2/3/4 (may 80001), op=200, op=10, op=12 — confirm they land.
   Probe tooling: `tools/probes/probe_pre_write.py`.
3. ~~**Inventory accuracy:** `o10` name drift + stale `actions.py` line numbers.~~
   **DONE (2026-06-04).** o10 corrected (it DOES fire op=10 via GENERATE_3D_MAP; the
   apk-uploadMap vs integration-generate_3dmap name conflict is now a flagged open question +
   capture step); 17 stale `actions.py:NNN` refs refreshed to current `ACTION_TABLE` lines.
4. **Coverage gaps (separate features the audit surfaced):**
   - ~~phantom-sensor prose for `WRF`/`TIME`/`VER`~~ **DONE (2026-06-04).** Built as
     disabled-by-default DIAGNOSTIC sensors (`sensor.dreame_a2_mower_weather_forecast_reference`
     / `_timezone` / `_cfg_version`): CFG→MowerState port in
     `cfg_to_state_updates`, descriptors in `sensor_device.py`, inventory rows + the prose
     corrected with retraction records. The claims are now true.
   - **`MISTA` area fallback sensor — deferred (not blocked, but non-trivial).** Needs a
     dedicated cloud-fetch of the MISTA `cfg_individual` endpoint (not currently polled) and
     is **mid-run-only** (returns r=-1/-3 when idle, per `project_g2408_mista_decoded`), so it
     would be unavailable except while mowing — a niche MQTT-down fallback. Build only if the
     s1p4 MQTT area stream proves unreliable.
   - ~~Patrol trigger~~ **SHIPPED (2026-06-04, feat/patrol-point-surfacing).** Point
     patrol (o107) + edge patrol (o108) triggers, cruise points parsed from MAP
     `cruisePoints` (type=8) + rendered as green-P markers + surfaced as
     `sensor.…_patrol_points`/`_patrol_edges` (generic `items` attr) + a generic
     `dreame-multi-select-card` + `start_point_patrol`/`start_edge_patrol` services.
     **Both o107 (point) and o108 (edge) SEND shapes are now VERIFIED LIVE (2026-06-04 —
     real patrols fired from the card moved the mower in both modes).** Zone/spot
     multi-select can now reuse the same sensor+service+card pattern.
   - **[FIXED — live-confirmed 2026-06-04, v1.0.23a1] Patrol mis-typed `maintenance_run`
     ("To Point") + lost return leg.** Root cause: a point patrol's only reliable type
     signal is `s2p2=51`, which arrives AT session start (before `begin_session`) and was
     dropped by `_capture_telemetry_sample`'s `is_active()` guard; the `s2p50` op echo is
     NOT reliably delivered to the integration (v1.0.22a9 latched it in vain). Fix: latch
     `s2p2=51` ungated into `_pending_saw_patrol_start`, durable `live_map.saw_patrol_start`
     seeded at `begin_session`, OR'd into `classify`. Live trace confirmed: typed `patrol`,
     real cloud md5, full out-and-back track. Correct typing ALSO fixed the early-finalize
     (return leg now captured) and the OSS-fetch expiry (clean cloud-finalize path) — both
     were downstream symptoms. See inventory `o107` verifications (2026-06-04).
   - **[FIXED — striped background during patrol]** Resolved across two fixes: (a) v1.0.23a3
     thread-safety (the s2p50-triggered render was raising off-loop and aborting); (b)
     v1.0.23a4 `background_mode_for` — `PATROL_POINT`/`PATROL_EDGE` were missing from
     `_ACTIVE_ACTIVITIES`, so the base flipped to idle stripes once a patrol settled into
     those activities. Both live-confirmed 2026-06-04.
   - **[TODO minor] `RuntimeWarning: coroutine '_RenderingMixin._render_base' was never
     awaited`** — `sensor_device.py:611` is only the GC site (a novel_observations attr
     read); the real un-awaited call is an entity-write handler calling `render_fn()` without
     await (candidates `number.py:678`, `select_global.py:989/1020`). Fold into the log-health
     sweep.
   - **[TODO] Patrol replay doesn't VISUALISE the on-the-spot 360° spins** (render-side, not
     capture). CORRECTED 2026-06-04: `cloud_track` is EMPTY for patrols, so the replay already
     uses the LOCAL track — which DOES capture the spins (archive `2026-06-04_1780607797`: 5
     consecutive points at `(x,y)≈(-4.2,-1.66)` with headings `255°→8°→112°→217°→321°`). They
     render as a stationary dot because the trail is `(x,y)` line segments. Fix is render-side:
     show heading/rotation at fixed-position points in the replay, NOT the dedup/capture path.
   - **[TODO] Patrol trail starts ~48s late (no dock→first-point leg).** The mower undocks and
     reorients for ~48s emitting NO `s1p4`, so the local track's first point is +48s into the
     session, near the dock but not AT it (archive `1780607797`: first pt `(-0.81,-0.15)@+48s`).
     The outbound MOVEs are all captured; what's missing is the leg FROM the dock. Fix idea:
     seed the trail with the dock position at session start so the first segment connects
     dock→first-real-point.
   - **[TODO minor] Live-map background stays green ~50-90s after the mower physically docks.**
     It follows the session state, which stays active through the dock-return + OSS-fetch
     finalize window (archive `1780607797`: archived 23:17:58, striped 23:18:06). Could flip to
     the idle preview as soon as the mower is docked+charging, before the archive finalize.
   - **[DONE — v1.0.23a4] `[F5-DIAG]` confirmation logs removed** after the thread-safety fix
     was live-confirmed (`seed at begin: last_op=107`). All temporary patrol diagnostics gone.
   - **[DONE — v1.0.23a5] Log-health sweep.** Audited `system_log/list` (WS) and fixed every
     real dreame WARNING: (B1) blocking `read_text(manifest.json)` on the loop → read once at
     import; (B2) deprecated `TrackerEntity` import → new path; (B3) `picked_session` attrs
     >16KB recorder reject → `_unrecorded_attributes = {"*"}`; (B4) `get_interim_file_url("")`
     → 40020 → empty-object_name guard; (C1) `80001` device-offline + `routed-action error`
     NoneType spam → DEBUG; (D) 15 operational `[F5]`/`[novel]` flow/success logs → DEBUG
     (caught-exception `[F5]` logs kept at WARNING).
   - **[DONE — v1.0.23a6] Log-health tail + NOVEL-probe audit.** (1) `_render_base "never
     awaited"` RuntimeWarning was a *side-effect* of the a3 thread-safety raise (orphaned
     coroutine) — already gone, verified in the live log, no code change. (2) Stale
     CloudState-migration notice → DEBUG. (3) `s2p2=54` false-novel notif: gated the "novel
     source" WARNING on `value not in S2P2_EVENT_TYPES` (a known code's first-cloud-text-this-
     session → DEBUG). NOVEL audit (per the caution that old NOVEL lines may already be
     addressed): `s2p1 state=4` + `s4 eiid1 piids 10/12` were ALREADY documented after their
     first-sighting (historical artifacts, no action); `s2p2=20`/`72` and the `s2p51
     {type:0|1}` shape were genuinely undocumented → recorded in `inventory.yaml` (s2p2
     "Observed but UNDECODED" + s2p51 open_question, kept OUT of error_codes.py per the
     confidence gate). Decoding them needs a labelled live capture.
   - **[FIXED — v1.0.23a3] MQTT callback aborted by off-loop `async_create_task` (HA 2026.6).**
     The activity-transition render trigger called `hass.async_create_task(self._render_base())`
     directly on paho's MQTT thread; HA 2026.6 RAISES on off-loop `async_create_task`, which
     aborted the whole MQTT message callback — taking out the render (striped background) AND
     the s2p50 op-echo latch that runs right after it (so `last_task_op` stayed None; the
     s2p2=51 latch saved the type). Fix: `_RenderingMixin._schedule_render_base()` hops to the
     loop via `call_soon_threadsafe` before `async_create_task`; all 4 `_render_base` triggers
     in `_mqtt_handlers.py` route through it. Live trace 2026-06-04: echo arrived
     (`[F5-RAW]` s2p50 o:107) but `_handle_task_op_echo` never ran due to the raise.
   - **Patrol per-point cycles + auto-capture — find the cloud source (no good candidate
     yet).** The app shows per-point cycle count (×1/×2/×3) and an auto-capture camera
     toggle, and they sync across app instances → cloud-persisted somewhere — but NOT in
     the MAP `cruisePoints` blob (only id/path/time/etime), NOT in the patrol summary
     `param:{}` (empty), NOT on `/status/`. The sensor `items` reserve `cycles:null` /
     `auto_capture:null` for when a source is found (surface read-only first, then writable
     when a write endpoint is found). No promising endpoint identified yet — needs an
     app-backend / batch-key sweep (likely MITM-gated, see `reference_app_api_probe`).

**Cross-refs:** `control_honesty.py` (`CONTROL_MODES` single SoT); `entity-inventory.yaml`
(`control_mode` per row); `docs/research/wire-captures/{settings-surface-cloud-only,
cfg-write-regression}-2026-05-09.md`, `pre-write-r3-2026-06-03.md`; the Phase-3 app-RPC TODO
below; auto-memory `project_control_honesty_markers`, `feedback_no_migration_overengineering`.

### s2p2 fault-surfacing — follow-ups after the FAULT_CODES partition

**Why:** The fault-partition feature shipped on branch `fix/s2p2-fault-partition`
(2026-06-01): `FAULT_CODES={2,4,5,23,31,36}` (verified, intervention-only) latches
into `snapshot.errors`, clears on movement/undock/mow-start, drives the Error
sensor + `lawn_mower` ERROR (+ `pin_required`), and fires `fault_detected` /
`fault_cleared` lifecycle events (plus a local entry for unknown codes). These
loose ends remain:
- **Deferred borderline codes:** revisit `9` (lifted — s1p1 bit too), `24`/`43`
  (battery — now Lifecycle), `33` (positioning — owned by `positioning_health`),
  `46`/`59`/`64-67`/`78` (navigational/self-recover) for FAULT_CODES membership if
  a live app-fault correlation shows the app surfacing them as faults.
- **24 vs 54 rename:** `24 "Battery low"` is vague vs `54 "Low battery — returning
  to station"`. Hypothesis: 24 = warning threshold, 54 = the return trigger.
  (Recorded as an `inventory.yaml § s2p2` open_question; needs a capture of both
  firing in one session, then rename 24.)
- **Vacuum-lineage descriptions** for the excluded codes (37/38/39/40/41/45/49/
  57/58/61/62/117) still sit in `ERROR_CODE_DESCRIPTIONS` and read as authoritative
  — fold into the existing cleanup TODO below ("audit hypothesized vacuum-lineage
  state_codes / error_codes").
**Done when:** borderline codes are decided against live evidence, 24 renamed,
and the vacuum descriptions are pruned/marked.
**Status:** open (feature shipped; these are refinements)
**Cross-refs:** `docs/superpowers/plans/2026-06-01-s2p2-fault-partition.md` (moved
to OLD on branch finish); `inventory.yaml § s2p2`; `mower/error_codes.py FAULT_CODES`.

### Probe for the AI-photo / obstacle-photo cloud endpoint

**Why:** The app shows AI obstacle photos with a confidence overlay (e.g. "human 80%"
= 80% it's a human in view). A SECOND app instance on another device shows the SAME
historical photo set → the photos sync via the cloud API, not BT. No "photo taken" MQTT
slot has been identified, so the photo list/metadata almost certainly lives behind a
cloud endpoint parallel to the `device-messages/v2` notification endpoint we already
found. Worth probing.
**Done when:** a photo/AI cloud endpoint (list + per-photo metadata incl. the
class+confidence overlay, e.g. "human 80%") is identified and documented, or ruled out.

**Progress (2026-05-31, `probe_ai_photo.py` + `iotstatus/history`/IPC sweeps):**
Systematically ruled the photo list OUT of every device-keyed surface reachable
with the integration's Dreame-Auth token (backend A):
- **batch device-data** — `getDeviceData` ignores the `key` filter and returns the
  full model; there is no AI/photo key. (Already true of every `cloud/dumps/`
  empty-batch read.)
- **`iotstatus/history`** (the device-data time-series query) — property-history for
  s2p55 / s2p51 / s1p53 → `{"list":[]}`; also empty for s2p1/s2p2 and siid=1/2
  event-history (eiid 1..20). This device historises nothing server-side.
- **`message-record/list`** categories 1..20 → 0 records (re-confirmed).
- **`device-messages/v2`** → empty (its ~6-7d retention window had no records at probe time).
- **guessed `/dreame-*/{ai-photo,obstacle-photos,device-photos}` paths** → 404.

**The one live lead:** `/smart-app/ipc/detection/event/list` — `libapp.so` carries a
full IPC event model (`imageUrl`, `picUrl`, `confidence`, `eventType`; detection
classes Human / Bird / Fire / Crying). It accepts our token (HTTP 400 *"Missing
necessary request parameters"*, **not** 404/auth), but the g2408 device record has
`videoStatus:null` + `featureCode:-1` → the mower is **not** enrolled as an IPC/camera
device, so this is most likely Dreame's security-camera product line. 7 param shapes
(deviceId/iotId/did × time/paging variants) all stayed at HTTP 400.

**Key state correction:** the feature is **ON at the cloud level** — `CFG.AOP=1` and
`REC[7] photo_consent=1` across all 8 dumps (2026-05-04..05-12). So the always-empty
`ai_obstacle[]` is **not** a disabled-feature artifact. This contradicts the stale
`reference_app_config` "Capture Photos AI Obstacles = Off" note (AOP maps to exactly
that switch — `switch_global.py:475/871`). Since the user reports the gallery syncing
to a 2nd app device, the photos DO exist cloud-side — on the app's own OAuth/Aliyun
backend (B/C), which our integration token can't fully drive.

**BREAKTHROUGH (2026-05-31) — Tasshack/dreame-vacuum analogue: there is NO separate
endpoint.** The vacuum integration reads obstacle photos inline from the map blob's
`ai_obstacle` array — the SAME field our `protocol/session_summary.py:140,385` already
parses (empty in our corpus). Per `OLD/.../dreame-vacuum/dreame/map.py:2086` +
`types.py:898`, each entry is `[x, y, type, possibility, key, file_name, random]`:
- photo exists only when `len>=7 and int(key)>=1000` (else it's a detection-only marker);
- `possibility` = the "human 80%" confidence (×100);
- `type` = obstacle class (vacuum enum 128-139 = furniture/clutter; the **mower's
  classes differ** — Human/Animal/Object per the app);
- `file_name` = an **OSS object name**, fetched via `get_interim_file_url(file_name)`
  — the SAME OSS path our mower already uses for maps/LiDAR (`cloud_client/_oss.py`).
The vacuum AES-CBC-decrypts the crop (its maps are encrypted binary); **g2408 maps are
plaintext JSON**, so the mower's `file_name` is likely a plaintext OSS key (decryption
need TBD). "2nd-device same set" = both apps read the same cloud blob's `ai_obstacle` +
fetch the same OSS objects — no per-account gallery service. Historical photos: vacuum
pulls them via `OBJECT_NAME` property-history; mower equivalent = MAPL/map-object history.

**LIVE TEST 2026-05-31 (partly refutes the vacuum analogue for LIVE surfaces).**
During a real walk-in-front mow where BOTH apps showed the new photo (mower still
mowing, not docked), every backend-A surface was empty: `getDeviceData` has NO
`ai_obstacle` key and all MAP `obstacles` are `[]`; siid=2/4/5 event-history + s2p55/
s2p51 property-history (last 90 min) empty; and the photo produced ZERO MQTT signal
(the `s2p51 {time,tz}` push is the clock heartbeat, not a detection). So unlike the
vacuum (ai_obstacle inline in the backend-A map blob), the g2408's LIVE photo lives
ONLY on the app's OAuth/Aliyun backend (B/C) — matching `/smart-app/ipc/detection/
event/list` accepting our token but rejecting all 24 param shapes. **The session-end
`.0550` `ai_obstacle` (the one backend-A field that's ever carried it) is still
unchecked for a detection session — that's the remaining MITM-free hope.** Tools:
`capture_ai_obstacle.py` (live MQTT) + `fetch_session_photos.py` (after-dock session
enumerator via `iotstatus/history` siid=4 eiid=1, piid=9=object_name).

**CONCLUSIVE 2026-05-31 — session-summary `ai_obstacle` REFUTED too.** The user gave
3 app-confirmed photo times; two (2026-05-30 19:15:20 + 19:22:54) fall inside the
05-30 19:00→19:27 session, yet that session's `.0550` summary has `ai_obstacle=[]`
(obstacle[LiDAR]=7). Photos captured but never written to ai_obstacle. Plus byte-diff
at all 3 photo times shows NO MQTT signal (byte[4] human-presence pulse never fired).
So the g2408's AI photos are on the app's B/C backend ONLY; `ai_obstacle` is a
vacuum-inherited slot the firmware never fills. The "MITM-free via session summary"
plan is dead.

**OBJ-list-by-type TESTED 2026-05-31 — negative.** The integration lists OSS objects
via `action(siid=2, aiid=50, [{m:'g', t:'OBJ', d:{type:'wifimap'}}])`. Swept ~40 types
while the mower was mowing (relay 80001 is intermittent — landed with retries; the
direct `dreame-iot-com-10000/device/sendCommand` call works, NOT probe_a2_mqtt's
`send()` which flaked). Result: the OBJ handler exposes ONLY map artifacts —
`wifimap` (1 obj `.0550.txt`) and `3dmap` (2 objs `.0550.bin` LiDAR) — every
photo/obstacle/human/camera/session/event name returned `{name:[]}`. Both real types
yield objects; no photo type does. So the OBJ list (the "list all images" candidate)
does NOT carry AI photos.

**Status:** backend-A EXHAUSTED — device-data, history, session-summary, MQTT, AND the
OBJ-list-by-type all tested empty for photos. Photos are B/C-backend-only. The ONLY
path is an **app HTTPS MITM** of the obstacle gallery (proxyman/) or cracking the
`/smart-app/ipc/detection/event/list` params (same wall as Phase-2 MAP write /
cruise-to-point). `fetch_session_photos.py` / `probe_obj_types.py` returning empty is
now confirmed-expected. Reframe the feature as MITM-gated.
**Next step (MITM-FREE):** capture the live MAP blob + session summary during/after a
**real detection** (walk in front of the mower mid-mow with AOP on) and check whether
`ai_obstacle` populates with 7-element entries; if so, fetch `file_name` via the existing
`get_interim_file_url`. Then surface as a per-obstacle camera/event entity. (The earlier
HTTPS-MITM step is now a fallback, not the primary path.)

**TOOL READY — `/data/claude/homeassistant/capture_ai_obstacle.py`** (dev-box only,
read-only; validated end-to-end 2026-05-31 against a real session summary — OSS
fetch + decode + obstacle-scan all confirmed working). Run it, then walk in front of
the mower mid-mow. It tails MQTT (flags s2p55/s2p51/s2p2/s1p1/s1p4 + event_occured
object_names), polls the cloud, downloads every OSS object it sees, dumps any
non-empty `ai_obstacle`/`obstacle` array (decoded per the vacuum analogue), and for
each `ai_obstacle` entry with a `file_name` downloads the photo bytes and classifies
them (JPEG/PNG/gzip/maybe-AES). Output → `ai_obstacle_capture_<ts>/` (capture.jsonl +
objects/ + SUMMARY.txt). `--test-object <name>` verifies the OSS path without waiting.
Once a capture confirms the on-wire `ai_obstacle` layout, wire the integration parse
(`session_summary.ai_obstacle` is already a raw tuple) + a per-obstacle camera/event entity.
**Implementation note:** `session_summary.ai_obstacle` is already parsed (raw tuple) and
`get_interim_file_url`/`get_file_url` already exist — wiring is mostly: parse the
7-element entry, fetch+maybe-decrypt `file_name`, expose confidence/type/coords.
**Cross-refs:** `OLD/alternatives_archive_2026-05-05/alternatives/dreame-vacuum`
(`dreame/map.py:2086`, `types.py:898`, `protocol.py:371`); GH `Tasshack/dreame-vacuum#1326`;
`inventory.yaml` § s2p55 (verifications 2026-05-31); `protocol/session_summary.py:140,385`;
`cloud_client/_oss.py`; `probe_ai_photo.py`; `docs/research/g2408-research-journal.md`.

---

### Probe `message-record/list` for the System/Sharing/Service/Activity tabs

**Why:** `device-messages/v2` returns only per-device (A2) records. The other
four tabs in the app come from `/dreame-message-push/v2/message-record/list`,
which returned `code=0 records=0` for `categories=[1..5]`. Possible reasons:
right category id is higher than 5, or `did` is the wrong filter for an
account-scoped endpoint, or content is behind v1 or a different service.
Not blocking the cloud-notification feature (we don't want Dreame-wide
announcements in the integration); just an open research question.
**Done when:** the actual category ids for System Messages and friends are
known, or we conclude the endpoint isn't reachable with current auth.
**Status:** open (low priority)
**Cross-refs:** `docs/research/app-api-surface-2026-05-25.md` § device-messages/v2; `probe_a2_endpoints.py`.

### Phase 2: MAP write — programmatic boundary/zone editing

**Why:** With chunked-batch writes confirmed working (Phase 1 done in
v1.0.2a1), the MAP surface is the next big capability. Drawing
boundaries and editing mowing/exclusion zones from HA without walking
the mower would be a major UX win.
**Done when:** A safe MAP write surface exists with auto-backup of the
current MAP blob before any write, restore-from-backup mechanism, and
a Lovelace card for boundary editing.
**What we tried (archived detail):** `probe_add_maintenance_point.py`
(2026-05-13) sent the `siid=2 aiid=50` TASK envelope for o:204→o:234→o:201
with 4 payload shapes — all HTTP 400 at `/device/sendCommand` (the cloud
doesn't route map-edit opcodes from us via this transport). Leading hypothesis:
the app POSTs geometry to a separate `/map`/`/region` HTTP endpoint and the
cloud emits the MQTT echoes server-side → needs an HTTPS MITM of a real
map-edit to find it. Fallback: `setDeviceData` MAP-blob write (risky; needs a
re-encode parity test first).
**Status:** open
**Cross-refs:** spec
`docs/superpowers/specs/2026-05-08-cloud-write-integration-design.md`
"Phase 2"; `docs/research/cloud-write-reference.md`; archived research
`OLD/ha-dreame-a2-mower-docs/research/map-edit-write-todo.md`.

### Re-verify EdgeMaster / Mowing Efficiency cloud-field correlations

**Why:** `docs/research/historical/g2408-protocol-PRESERVED-RAW-2026-05-06.md`
catalogued EdgeMaster (`s6p2[2]`) and Mowing Efficiency (`s6p2[1]`)
as BT-only / not-in-cloud-CFG. Those claims predate the
2026-05-08 cloud-discovery findings and may be outdated; both could
now be writable via `setDeviceData` if the cloud surfaces them under a
chunked-batch key we haven't probed.
**Done when:** Toggle each in the app while monitoring the empty-batch
read; if any chunked-batch key changes, surface as a new entity. If
neither changes, document as confirmed BT-only post-cloud-discovery.
**Status:** RESOLVED 2026-06-03 — confirmed no routed-action write surface.
The premise ("maybe cloud-writable post-discovery") was tested directly
rather than via the empty-batch route: Mowing Efficiency is `CFG.PRE[1]`,
and a live `set_pre` of the correct 2-element shape returned `out[0].r=-3`
(no setter for `t='PRE'`) with the findBot relay control confirmed awake
("Robot is here" + `r=0`). Per the 2026-05-09 r-code disambiguation `r=-3`
is target-level, so it is shape-independent. EdgeMaster (`s6p2[2]`) has no
`PRE` slot on g2408 and `PRE` has no setter regardless. So neither is
writable via the routed-action CFG surface; `s6p2` itself is a read-only
push reflector. `set_pre` now parses `out[0].r` and fails honestly instead
of reporting false success. The ONE remaining unknown — the app's actual
write RPC — is the Phase-3 HTTPS-sniff work tracked under "Determine whether
HA writes drive the device…" below; it is NOT specific to these two fields.
**Cross-refs:** `docs/research/wire-captures/pre-write-r3-2026-06-03.md`;
`tools/probes/probe_pre_write.py`; `inventory.yaml § PRE` + `§ s6p2` (2026-06-03
verifications); historical doc; `docs/research/cloud-write-reference.md`.

### SCHEDULE not refreshed — app schedule edits don't reach the integration

**Status:** RESOLVED 2026-06-08 — decoder bug, not a refresh/cloud-stale problem.

**Root cause (verified):** The cloud SCHEDULE blob WAS fresh and reaching the
integration (live empty-batch fetch showed `v=35422` with the new record present)
— hypotheses (a) periodic-refresh-missing and (c) cloud-stale are both DEBUNKED.
The new entry was a **Sunday** 21:30 zone mow, and the SCHEDULE wire weekday nibble
is `tm_wday` (0=Sun..6=Sat), NOT the `1=Mon..7=Sun` the decoder assumed. Sunday's
nibble is `0`, which `_decode_one_record`'s `1 <= weekday <= 7` guard rejected →
`_decode_blob` returned `()` for the **entire slot**, so the user's whole active
"Spr & Sum Schedule" went blank (not just the new line). Mon..Sat coincide between
the two conventions, which is why every prior schedule decoded fine and this hid
for weeks.

**Fix:** `protocol/schedule_decode.py` — weekday nibble accepted as 0..6 and
mapped to the mask bit via `(nibble+6)%7`; `_decode_blob` now SKIPS a single
content-malformed record instead of dropping the whole slot (defense in depth).
`protocol/schedule_encode.py` — inverse `(bit+1)%7` so Sunday round-trips to
nibble 0. Proven byte-exact against the live record `aa08010a150001ed`
(probe/probe_schedule_live.py, 2026-06-08). Tests:
`tests/protocol/test_schedule.py::test_decode_real_slot0_with_sunday_zone`,
`::test_roundtrip_sunday_zone_byte_identical`,
`::test_decode_skips_unknown_record_keeps_rest_of_slot`.
**Cross-refs:** `cloud_client/_fetchers.py` (`fetch_full_cloud_state` SCHEDULE branch);
`coordinator/_cloud_state.py` (`_refresh_cloud_state`, 2-min timer); `protocol/schedule_decode.py`.

### Capture zone / edge action codes for SCHEDULE blob

**Why:** The SCHEDULE blob format was decoded 2026-05-08 (see
`protocol/schedule.py` for the verified record layout). The action-
type nibble has only been observed as `0` (All-area mowing) — the
zone (1?) and edge (2?) codes are not yet pinned down. The user's
Dreame app supports All-area / Zone / Edge plans; capturing one of
each in the cloud blob would close out the catalogue.
**Done when:** the user adds a Zone-mowing and Edge-mowing schedule
in the app, the next cloud dump is captured, and the `_ACTION_LABELS`
dict in `sensor.py` is updated with the verified codes (plus
appropriate test fixtures in `tests/protocol/test_schedule.py`).
**Status:** RESOLVED 2026-06-08 — live capture (probe/probe_schedule_live.py)
caught a slot containing all three action types: all-area (`action=0`, 7-byte),
zone (`action=1`, 8-byte, `aa08010a150001ed` = Sun 21:30 zone_id=1), and edge
(`action=2`, 9-byte, `aa09627424000100ed` = Sat 19:00 zone_id=1 extra=0x00).
Action codes 0/1/2 confirmed against real data; `_ACTION_LABELS` (all_area/zone/edge)
already correct. The byte layout in `schedule_decode.py` is now live-verified
(only the weekday convention needed correcting — see the resolved SCHEDULE-refresh
item above). The edge `extra` byte (rec[7]) was 0x00 here; whether it is the
edge-index selector remains [UNVERIFIED] (needs a 2nd defined edge — see s99/TASKID
3-element note).
**Cross-refs:** `custom_components/dreame_a2_mower/protocol/schedule_decode.py`;
`probe/probe_schedule_live.py`

### OTA_INFO field semantics

**Why:** v1.0.0a100 surfaces `cloud_state.ota_status` as
`(int, int)` — the test fixture observed `(2, 100)`. We assume
the first field is a status code and the second is a percent (0-100),
but neither has been confirmed during a real OTA update. The
sensor uses `state = ota_status[0]` and `attr percent = ota_status[1]`;
mapping numeric statuses to human-readable strings (idle / downloading /
applying / failed / etc.) requires observation during an actual OTA.
**Done when:** the status-code → state-string mapping is documented
in `docs/research/g2408-research-journal.md` and the sensor either
returns the string directly or exposes both via attributes.
**Status:** blocked-by-OTA-observation (next firmware update).
**Cross-refs:** spec "Out of scope" item 5.

### Add integration icon via home-assistant/brands PR

**Why:** The HA Integrations page shows a blank square or nothing next to the
Dreame A2 Mower entry. Icons must come from `home-assistant/brands`, not the
integration's own folder.
**Done when:** A PR is merged to `home-assistant/brands` adding
`custom_integrations/dreame_a2_mower/icon.png` + `icon@2x.png`; the icon
appears on the Integrations page and in HACS.
**Status:** open
**Cross-refs:** upstream `home-assistant/brands` repo; source image at `/data/claude/homeassistant/dreame-a2-icon-large.jpg`

---

### Surface dock-departure repositioning UX

**Why:** The Dreame app shows a 3-stage popup ("Exiting the station" /
"Repositioning..." → "Reorienting" / "Repositioning Successful" → the task
message, e.g. "Starting to mow" for a mow, "Heading to maintenance point" for
op=109) at every dock departure, BEFORE the first move. No MQTT property
carrying this exact relocate-state has been identified — three dock departures
on 2026-05-05 produced no `s2p65` or `s5p104..107` events; the popup driver is
off the sniffed wire (cloud-only, like the Reorient popup).

**Partially shipped (2026-05-31):** the *command-time awareness* half is done —
on any task-start echo (`s2p50` status:true, op ∈ {100,101,102,103,108,109})
the integration now sets the task-appropriate `current_activity`, leaves the
`AT_DOCK` location (→ `ON_LAWN`), and switches the live map out of the striped
pre-start preview into trail mode IMMEDIATELY, instead of lagging ~45s until
`s1p4` position telemetry resumes (the undock reorientation silence). Applies to
all session types. See `mower/state_machine.py:_apply_s2p50_task_envelope`
(`_TASK_START_OPS`), `map_render/main_view.py` (`_is_active_non_mow_session`),
`coordinator/_mqtt_handlers.py` (command-time `_render_main_view`). This removed
a false `IN_SESSION+MOWING+AT_DOCK → CHARGE_RESUME` reconcile at startup.

**Wire signals IDENTIFIED (2026-05-31, user-annotated capture — see inventory
s2p1 verification):** the popup steps DO map to wire events (the op echo is at
the END of reorientation, not command-time):
  1. "Exiting the station"     = `s2p1 6/13→1 (working)` + `charge→not_charging`
  2. "Repositioning"           = app timer ~2-3 s later (no distinct wire event;
     ~40 s reorient turn, s1p4 silent)
  3. "Repositioning successful" = first `s1p4` MOVE + `s1p50 SESSION_BOUNDARY_PING`
     + `s1p51 DOCK_POS_UPDATE_TRIGGER`
  4. task message ("Heading to point"/"Starting to mow") = `s2p50` op echo +
     `s2p56` task-active

**Reorientation is INFERABLE, no wire message (2026-05-31 return-leg capture):**
the app's "Reorienting/Repositioning" popup is an inferred state = the window
between `s2p1` transitioning to a MOVING state and the first actual `s1p4` MOVE.
GENERAL across undock and return:
  - undock: `s2p1 → working(1)`  → ~40 s silent → first move
  - return (Recharge at point): `s2p1 standby(2) → returning(5)` → ~26 s silent → first move
So a "Repositioning" sub-state can be derived as: `s2p1 ∈ {1 working, 5 returning}`
AND no `s1p4` MOVE since that transition — covers both legs with one rule, no
cloud popup needed. (The return leg already labels activity **Returning** from the
`s2p1=5` transition; only the icon waits for `s1p4`. The `s1p1` heartbeat that lands
in the same second as an `s2p1` change is the documented "s1p1 fires extra
heartbeats on state transitions" — carries no repositioning info.)

**Remaining:** (a) extend the command-time awareness to key on the moving-state
transition (`s2p1→working` undock / generally the start signal) so the integration
reflects "Exiting the station" ~42 s earlier than the op echo (deferred
"Repositioning phase" / Option B — now unblocked); (b) confirm `s2p1→working(1)`
doesn't false-fire without a following task (gate with `charge→not_charging` if it
does); (c) decide whether to surface a distinct "Repositioning" activity/sensor
derived from the inference rule above (covers undock + return).
**Done when:** step-1 awareness is wired (or a decision to keep op-echo-only is
recorded) + the working(1) gating caveat is confirmed.
**Status:** command-time (op-echo) awareness DONE (v1.0.20a7); signals identified;
step-1 ("Exiting") awareness + caveat confirmation OPEN
**Procedure:** [docs/research/g2408-capture-procedures.md#3-active-mowing-s5p10x-sequence-capture](g2408-capture-procedures.md#3-active-mowing-s5p10x-sequence-capture)
**Cross-refs:** `docs/research/g2408-protocol.md §1` (80001 failure context); probe-log correlation needed

---

### Alert-tier event surface (follow-up to lifecycle PR)

**Why:** The lifecycle-tier event surface (a91) reserved
`event.dreame_a2_mower_alert` with empty `event_types`. Populate it
with `emergency_stop`, `lifted`, `tilted`, `stuck`, `bumper_error`,
`obstacle_with_photo`, `battery_low`, `battery_temperature_low`, `error`.
Add `CONF_NOTIFY` option toggle. Migrate the existing bespoke
`_handle_emergency_stop_transition` banner to a framework-managed
persistent_notification gated by CONF_NOTIFY.
**Done when:** All listed event_types fire from the appropriate
detection sites; `_handle_emergency_stop_transition` is replaced;
docs/events.md gains the alert section; emergency_stop banner
behavior is unchanged from the user's perspective.
**Status:** open
**Cross-refs:** `docs/superpowers/specs/2026-05-07-event-surface-design.md` § "Out of scope"

---

### Lifecycle event-surface PR — review-flagged cleanups

**Why:** The final whole-branch review of v1.0.0a91 (the lifecycle event
surface) flagged five non-blocking follow-ups that should not be lost:

1. **conftest.py placement** — `tests/event/conftest.py` stubs only
   `homeassistant.components.event` while the root `tests/conftest.py`
   already stubs every other HA component in one place. Fold into the
   root conftest for consistency.
2. **Unused `_attr_translation_key`** — both event entities set
   `_attr_translation_key="lifecycle"` / `"alert"` but `translations/en.json`
   has no `entity.event.*` block. Either add the translation entries
   or drop the unused keys.
3. **`_make_coordinator_for_persist_tests` fixture incomplete** —
   `tests/integration/test_coordinator.py` has three coordinator-stub
   fixtures; two set `_lifecycle_event` / `_alert_event` / `_prev_in_dock`,
   the persist one only sets `_prev_in_dock`. Latent foot-gun if a
   future test extends the persist case to call fire-paths.
4. **`mowing_ended` may double-fire on cloud md5 dedup hit** —
   `_do_oss_fetch` fires `_fire_mowing_ended` even when the cloud reused
   the md5 (dedup hit). The session was already finalized once; firing
   again is questionable. Add a guard or accept and document.
5. **`reason` heuristic in `mowing_paused`** — only emits
   `"recharge_required"` when `battery_level <= 20`; nullable
   `battery_level` always resolves to `"unknown"`. The threshold 20 is
   a magic number. Pull into a const, handle None explicitly, and
   consider expanding the reason vocabulary alongside the alert-tier PR.
**Done when:** Each of the five items is either fixed or explicitly
closed with a "won't fix because X" note.
**Status:** open
**Cross-refs:** final review on commit `e32c8f4..51f6883`;
`docs/superpowers/plans/2026-05-07-event-surface-lifecycle.md`

---

### Novel-observation sensor floods on continuous-integer slots

**Why:** `sensor.dreame_a2_mower_novel_observations` accumulated 51 entries
before a reboot 2026-05-07 and 5 since. All observed entries are
`category: value` for slots without a `value_catalog` — e.g. `s3p1`
battery_level (every new percentage triggers), `s5p107` energy_index
(int 1..250), `s1p53` bluetooth_connected (True/False both fire on first
observation). The registry's first-time-seen-value path is correct as
a log signal but is noise on the user-visible sensor.
**Done when:** The sensor's `observations` attribute filters out
`category: value` entries for slots whose `_INVENTORY.value_catalogs`
entry is None. INFO-level logging of those novelty events stays so
contributor diagnostics aren't lost.
**Status:** open
**Cross-refs:** `coordinator.py` novelty dispatch around line 2843;
`observability/registry.py`

---

### GPS world-coordinate read path — find the surface the Dreame app uses

**Why:** `device_tracker.dreame_a2_mower_location` is plumbed to the cloud `routed-action g.LOCN → {pos: [lon, lat]}` path, but on g2408 LOCN returns the `[-1, -1]` sentinel even with `switch.anti_theft_realtime_location` (CFG.ATA[2]) ON. The Dreame app's **Real-Time Location** sub-page nevertheless shows the mower at its correct world coordinates, so the app reads GPS from a different cloud / MQTT surface that the integration has not yet identified. The legacy fork hit the same wall (`coordinator.py:287-294`).

**Confirmed it's NOT**:
- `routed-action g.LOCN` (returns sentinel)
- LIDAR / odometry (those are mower-frame, not world-frame)
- a "dock GPS origin anchor" — user 2026-05-09 confirmed the mower has its own GNSS hardware
- the apk geofence subsystem (apk.md line 242 confirms it's for phone-GPS smart-lock auto-unlock, not the mower)

**Suspected candidates**:
- A different cloud routed-action key (`GPSPOS`, `GEOLOC`, etc.) we haven't probed
- An MQTT push: a `s2p51` message type beyond what we currently dispatch, or a broader robot-pose extension on `s1p4`
- A separate cloud HTTP endpoint outside the routed-action / chunked-batch surfaces
- ioBroker's apk catalog mentions `LOCN setLocation {pos}` for setting the GPS — the read counterpart on a healthy device may not be `getCFG` but rather a different envelope

**Done when:**
1. An HTTPS sniff of the Dreame app on the Real-Time Location page identifies the actual surface (request body + response shape).
2. `cloud_client` adds a fetch path (likely a new method, parallel to `fetch_locn`).
3. `_refresh_locn` is repointed (or a new `_refresh_gps_world` runs alongside).
4. `device_tracker.location` populates with valid lat/lon while ATA[2] is on; the dashboard's GPS map card renders.
5. Validation matrix row flips from ✗ live (KNOWN GAP) to ✓ end-to-end.

**Workaround for users right now**: open the Dreame app's Real-Time Location sub-page directly. The HA dashboard hides the map card while ATA[2] is off and falls back to a "toggle on to enable" notice — the same notice now mentions this gap so the user knows the integration's path isn't the same as the app's.

**Status:** open (Phase 3 — needs HTTPS capture). Recipe candidate to bundle with the broader Phase 3 sniff session (Phase 3 also covers SETTINGS / AI_HUMAN.0 / SCHEDULE writes).
**Cross-refs:** `docs/research/entity-validation-matrix.md` device_tracker row; `cloud_client.fetch_locn`; `coordinator._refresh_locn`; `OLD/alternatives_archive_2026-05-05/ha-dreame-a2-mower-legacy/custom_components/dreame_a2_mower/coordinator.py:287-294` (legacy reaching the same conclusion); archived negative-results detail `OLD/ha-dreame-a2-mower-docs/research/gps-tracking-todo.md`.

---

### `edgeMowingWalkMode` — identify the app-side setting

**Why:** The cloud SETTINGS field `edgeMowingWalkMode` is exposed as
`select.<map>_edge_walk_mode` (values `walk_0` / `walk_1`), but no
toggle in the Dreame app appears to correspond to it. Curiously the
JSON key order in `SETTINGS.0` roughly matches the order of toggles in
the app's Mowing Settings screen, and `edgeMowingWalkMode` sits
between `mowingHeight` and `edgeMowingAuto` — which is where the app
shows "Mowing Direction" (the Standard / Crisscross / Chequerboard
selector). That direction selector is already wired to the
`mowingDirectionMode` field (our `Mowing Pattern` select), so
`edgeMowingWalkMode` is plausibly something different — perhaps a
hidden/A-B flag, an edge-walk strategy parameter, or a deprecated
field.
**Done when:** Physical test: run an Edge mow on the same map twice,
once with `edgeMowingWalkMode=0` and once with `=1`, and observe
whether the mower's edge-tracing behaviour differs (path shape,
direction, lap count, speed). Either confirm a behavioural delta and
characterise it, or confirm no observable delta and document the
field as cosmetic/no-op so we can decide whether to keep the entity.
**Status:** open
**Cross-refs:** `select.py` § `DreameA2PerMapEdgeMowingWalkModeSelect`;
`docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json`
(field values observed: entry0/map0=0, entry0/map1=0, entry1/map0=1,
entry1/map1=1 — both states known to be accepted by the cloud).

---

### Audit protocol docs for debunked-knowledge leakage (corpus-validate conflicting claims)

**Why:** The s2p2=28 incident (2026-05-30) exposed a recurring failure mode:
a wrong reading derived from a **single biased log** ("28 = off-dock relocate
marker, fires 14/14 on every undock" — computed only from `probe_log_20260520`,
which happens to cover the worn-blade window) got promoted to a `verified:`
inventory entry and leaked into `error_codes.py`, the mova cross-check doc, and
the notification-history doc. The correct reading (28 = wear%-gated blade-wear
push) co-existed alongside it. A new session leaning on the "latest entry" nearly
re-propagated the wrong one. Two systemic risks: (a) conflicting doc entries where
"latest wins" silently regresses correct older info; (b) findings asserted from one
run that don't hold across the corpus.
**Done when:**
1. Sweep `inventory.yaml` + `docs/research/` for claims marked `verified` whose
   evidence is a **single** probe log, and re-validate each against the full
   corpus (`probe_log_*.jsonl`, 9 logs / ~66 undocks). Downgrade any that don't
   replicate corpus-wide to `partial`/`presumed` with a corpus note.
2. For every code/field with two or more conflicting `semantic:` or verification
   readings, add an explicit "current best reading + which older readings are
   superseded and why" so a future session can't silently pick the wrong one.
3. Document the rule in CLAUDE.md § Fact discipline: a wire-pattern claim is not
   `verified` from one run — it needs corpus-wide consistency; if it doesn't hold
   across the corpus it can't be confirmed. (Tooling: `_corpus.py` is a starting
   point — consider promoting it into `tools/`.)
**Status:** open
**Cross-refs:** `inventory.yaml § s2p2` (2026-05-30 retraction) + `§ s1p1`
(2026-05-30 corpus verification); `mower/error_codes.py` code 28; memory
`feedback_corpus_validate_protocol_claims`.

---

### Replace guesswork multi-variable state inferences with fact-based signals

**Why:** Reviewed (2026-05-30) every combination-gated state/action in
`mower/state_machine.py` + the `coordinator/` session handler. Most combinations are
**fact-based and fine** — keep them:
- `_apply_charging`: charging=True → location=AT_DOCK (physical invariant). ✓
- `_apply_cloud_dock`: ignore a stale cloud AT_DOCK while IN_SESSION+ON_LAWN (the
  5-10 min cloud DOCK lag is observed). ✓
- `_apply_s2p1_task_state`: s2p1=6 → CHARGE_RESUME vs IDLE by mow_session (real
  distinction; collapses two facts into one activity enum but the logic is sound). ✓
- `_apply_s2p56_lifecycle`: stage=2 + CRUISING_TO_POINT → AT_POINT (good composition:
  generic stage field + task type → meaning; redundant-but-consistent with s2p2=75). ✓

The **guesswork** combinations (your hunch — inference, not protocol fact):
1. `_reconcile_mow_activity` (state_machine.py ~434): IN_SESSION + MOWING + AT_DOCK →
   CHARGE_RESUME, comment literally "pick CHARGE_RESUME since that's how the mower
   behaves". Should read the actual charging/s3p2 signal, not guess from a triple.
2. `_reconcile_mow_activity` (~409): IN_SESSION + CHARGE_RESUME + off-dock + area>0 →
   MOWING — a 4-condition self-heal inference for a dropped MQTT push.
3. `_mqtt_handlers` (~376): pause **reason** = `recharge_required` if `battery<=20`
   (magic number, "best-effort") — should read the real pause cause (s2p2 in the pause
   window), not infer from battery. (Already noted in the lifecycle-review TODO.)
These are RECOVERY heuristics (self-heal stuck state from missing signals — see the
state-machine-audit), so they're load-bearing; **don't rip them out blindly**, replace
each with the fact-based signal where one exists, otherwise label it explicitly as an
inference fallback.
**Done when:** items 1-3 either read a direct signal or are explicitly marked
"inference fallback (no direct signal)"; a quick pass over `coordinator/_session.py`
finalize gate + `live_map/finalize.py` decide() confirms no other guesswork combos.
**Status:** open
**Cross-refs:** `mower/state_machine.py § _reconcile_mow_activity`;
`coordinator/_mqtt_handlers.py` pause-reason; memory `project_state_machine_audit`;
DONE.md "Decouple the s2p2 71/31/33 state model".

---

### Audit for misleading authoritative-sounding names on unverified/wrong meanings

**Why:** A sibling to the debunked-knowledge audit, but specifically about *names*:
apk/vacuum-derived identifiers that read as fact while the meaning is unverified or
wrong. Confirmed instances this session: s2p2=28 (off-dock-marker → blade-wear),
s2p2=71 (positioning_failure → standby-return), s1p1 byte[14] (startup_state_machine
→ locomotion_state), CMS[3] (Link Module → unidentified). Standing risks:
- `s2p2=20` is correctly flagged "NOT battery" in inventory + probe_a2_mqtt.py, BUT old
  probe jsonl entries have the stale `BATTERY_LOW` label baked in at capture time — a
  reader scanning a 05-25 log sees a wrong label with no caveat.
- Vacuum-side s4p* names (cleaning_mode, pet_detective…) for slots g2408 never emits.
- Hypothesized names in `mode_enum` / `s2p1 value_catalog` / other surfaces that aren't
  covered by the error_codes CI gate (see below).
- Analyzer labels in `probe_a2_mqtt.py` — unverified names baked into log output.

**DONE (2026-06-01) — `mower/error_codes.py` + `inventory.yaml § state_codes`:**
The 20 vacuum/apk-lineage s2p2 names (37/38/39/40/41/44/45/46/49/57/58/59/61/62/
64/65/66/67/78/117) that were never observed on g2408 have been deleted from
`ERROR_CODE_DESCRIPTIONS` and `S2P2_EVENT_TYPES`. `inventory.yaml § state_codes` is
now fully reconciled — complete per-code confidence, confirmed rows for 1/2/9/23/
28/30/36/74/76, partial rows for 0/24/47, corrected 63/73. A CI gate
(`tests/inventory/test_error_codes_confidence_gate.py`) now enforces that every
s2p2 code described in `error_codes.py` must have a `state_codes` row with
`decoded: confirmed` or `partial`; a `hypothesized`/`unknown`/absent code must NOT
appear — see `CLAUDE.md § error_codes confidence gate` for the durable rule.

**Still open:** the same misleading-name pattern in `inventory.yaml § mode_enum` /
`s2p1 value_catalog`, vacuum-side s4p* slots, `probe_a2_mqtt.py` analyzer labels,
and the old-probe-log stale `BATTERY_LOW` caveat. The gate PATTERN (cross-check
code-surfaced names against `inventory.yaml decoded` status) can be extended to
those surfaces when they're next touched.

**Done when (remaining):** a sweep of `inventory.yaml` (mode_enum / other non-state_codes
surfaces) and `probe_a2_*.py` flags every authoritative-looking name whose meaning is
`hypothesized`/`unknown`/contradicted and either neutralizes it or annotates it inline.
**Also (housekeeping, bundle while touching the probe tools):** the probe scripts
write log files (`probe_log_*.jsonl`) into `/data/claude/homeassistant/` root, which
is cluttered with test/log/temp files. Update the probe tooling to write into a
subdirectory (e.g. `probe_logs/`), and consider the same for the throwaway analysis
scripts (`_corpus.py`, `_reorient.py`, `_s1p1.py`, `_win.py`, …). Keep paths the
analysis scripts read in sync.
**Status:** in-progress — `error_codes.py` + `state_codes` done (CI-gated); other surfaces remain open
**Cross-refs:** `inventory.yaml` § state_codes (s2p2_37..117 hypothesized names);
`mower/error_codes.py`; `probe_a2_mqtt.py` (+ log-path); `docs/research/mova-mower-a1-crosscheck-2026-05-25.md`;
`tests/inventory/test_error_codes_confidence_gate.py`; sibling: "Audit protocol docs
for debunked-knowledge leakage"; memory `feedback_corpus_validate_protocol_claims`.

---

### s2p1 mode enum vs apk table — reconcile remaining conflicts + s2p56 umbrella question

**Why:** Folded in from `things.txt`. The apk's product-agnostic mode table lists
`3: "Working"`, but the probe corpus shows s2p1=3 always co-incident with s2p56
status `[[1,4]]` — decoded as "Paused" in `inventory.yaml § s2p1` (5 observations,
2026-04-17 and 2026-04-22/28/29). Value 16 ("Battery Temp Hold") is also ours, not
in the apk table. The label side is mostly reconciled already; the open part is the
**s2p56-vs-s2p1 relationship** — s2p56 also carries a task value, so one may be an
umbrella state ("in a session but currently charging") over the other. Side note
worth keeping: this is the *only* enum table the app exposes that is product-type
agnostic; every other table is vacuum-worded.
**Done when:** the s2p1↔s2p56 relationship is documented (is s2p56 the
session-umbrella state and s2p1 the instantaneous activity, or vice-versa?), and any
remaining apk-vs-wire label conflicts are annotated in `inventory.yaml § s2p1` /
`§ s2p56`.
**Status:** open (low priority — labels largely resolved; see `inventory.yaml § s2p1`)
**Cross-refs:** `inventory.yaml § s2p1`, `§ s2p56`; was `things.txt`.

---

### `summary_map[boundary_layer].track` over-segmentation — identify the break trigger

**Why:** The cloud's session-summary track field over-segments the mow path: in a
48-min Map 2 sample (2026-05-09), 27 single-point / 43 two-point / 24 three-point
segments out of 150 sit ON the eventual continuous trail (not outliers). The user's
read is "they appear to show something significant" — could be a load-bearing signal
we discard (pen-up / blade-state change / phase boundary / AI-obstacle proximity /
cloud heartbeat).
**Done when:** the break trigger is identified (the five candidate triggers + s1p4
decode steps are catalogued in `inventory.yaml § summary_map_track.open_questions`),
and the segments are either surfaced as a signal or documented as cloud-noise. NB the
replay card already filters <2-point legs, so this is a protocol question, not a
display bug.
**Status:** open (low priority)
**Cross-refs:** `inventory.yaml § summary_map_track.open_questions`;
`protocol/session_summary.py`; `live_map/trail.py`; memory
`project_track_oversegmentation_todo`.

---

### Session calendar — one-tap replay card

**Why:** The Sessions tab uses the HACS `atomic-calendar-revive` card, so
replaying a session is two surfaces / two clicks (find it on the calendar →
match the label in the Replay picker dropdown → tap). One-tap-from-the-calendar
isn't possible with either the HA-native `type: calendar` (hard-coded more-info
popup) or atomic-calendar-revive (its `tap_action` fires the same call for every
event — no per-event `{{event.summary}}` substitution). Both confirmed
2026-05-13.
**Done when:** a bundled custom JS card
(`www/dreame-a2-session-calendar.js`, registered like the existing lidar/schedule
cards) renders a month grid from `calendar.dreame_a2_mower_sessions` and, on a
session tap, calls `select.select_option` on `select.dreame_a2_mower_work_log`
with the event summary — driving the existing replay camera. Drops the
atomic-calendar-revive dep. (~half-day; the work_log label match is pinned by
`tests/integration/test_calendar.py`.)
**Status:** open (low priority — UX nicety).
**Cross-refs:** `www/dreame-a2-lidar-card.js` (bundled-card pattern);
`calendar.py::_event_from_entry`; archived design
`OLD/ha-dreame-a2-mower-docs/research/session-calendar-todo.md`.

---

### Live dense 3D/LiDAR map surface — the app shows it, we only ingest snapshots

**Why:** 2026-06-08 the user removed a map exclusion zone; the mower began
re-mapping the newly-opened area. BOTH app instances (action phone + cloud-only
iPad) immediately showed a DENSER 3D LiDAR point cloud including the new area —
i.e. it's cloud-resident and live. But our integration only ever sees the
**infrequent `.0550.bin` 3D snapshots** (the `s2.50 m='g' t='OBJ' d={type:'3dmap'}`
list, last objects 2026-04-20 + 2026-05-10) — the live dense map never appears
there. This area was skipped historically because we assumed the OBJ list was
the whole story.

**What's been ruled out (live probes 2026-06-08):**
- op=10 generate_3dmap — accepted (r=0) but no effect; does NOT trigger a render (see inventory op=10).
- OBJ-list `m='g' t='OBJ'` with 11 type values — only `3dmap` + `wifimap` return objects; `map`/`olmap`/`lidar`/`live`/`current`/`pointcloud`/`model`/`2dmap`/`mapbin` all r=0 but empty.
- Direct `siid:6` MIoT property read (`get_properties` p1–p4) → `null` (g2408 rejects direct reads; siid:6 is repurposed for SETTINGS/s6p2 on the mower, NOT the vacuum's MAP service).
- Direct property-SET of `siid:99 piid:20` (s99p20) → `80001` (both `{"frame_type":"I"}` and int values, 2026-06-08). s99p20 is a device→cloud OUTPUT (announces a finished `.0550.bin`), not a settable trigger — you can't "set s99p20" to make a map, and the s6p2 analogy doesn't hold (s6p2 is also a device→cloud push; settings change via the s2.50 routed CFG write, then the device echoes s6p2). The trigger must be an ACTION (cf. vacuum REQUEST_MAP siid:6 aiid:1), not a property write.
- The s2p54→s99.20 snapshot-upload flow has fired 0× in the 19-day capture (last snapshot 05-10), so no new 3dmap snapshot exists yet.

**The lead (from `OLD/`):** the **dreame-vacuum** integration has the full
live-map architecture the mower lineage descends from — a siid:6 MAP service
(`MAP_DATA` p1, `FRAME_INFO` p2, `OBJECT_NAME` p3, `MAP_EXTEND_DATA` p4,
`RECOVERY_MAP_LIST` p9) with a **`REQUEST_MAP` action (siid:6 aiid:1)** that
sends `{"frame_type":"I"}` (full I-frame keyframe request) and `UPDATE_MAP_DATA`
(aiid:2), fetched via `get_interim_file_url(obj_name)` and **polled every 120 s**
for the live map (`alternatives/dreame-vacuum/.../dreame/{device.py:request_map,map.py,types.py}`).
The g2408 moved its LiDAR-object push to s99.20 and repurposed siid:6, so the
exact aiid/piid differ — but the **REQUEST_MAP I-frame → OBJECT_NAME →
interim-URL** pattern is what to look for.
**Done when:** the cloud surface the app uses for the live dense 3D map is
identified and (if reachable) wired so the HA LiDAR camera tracks the live map,
not just the periodic snapshot.
**Method:** app-RPC capture (Phase 3) — sniff the action phone while opening the
3D-view, watch for an I-frame/request-map call + the object name it then fetches.
Blind-probing mower siid:6 actions is discouraged (cross-mower-type actions
misfire — cf. the siid:2 aiid:3 = return-to-dock incident).
**Status:** open (research — needs app-RPC capture).
**Cross-refs:** inventory.yaml op=10 "upload_map/generate_3dmap" + s2p54 entries;
memory `project_g2408_op10_3dmap_negative`;
`OLD/alternatives_archive_2026-05-05/alternatives/dreame-vacuum/custom_components/dreame_vacuum/dreame/` (device.py `request_map`, types.py siid:6 MAP service); the Phase 3 app-RPC capture section below.

---

### Photo/video archive — dashboard surfacing, the 3 photo sets, overlays, session-linking, boot backfill

**Why:** Folded in from `todo1.txt`. The OSS photo/video archive BACKEND shipped
(album-photos feature + person/patrol/obstacle categorisation, 1 h
`_refresh_oss_gallery` sync, quota/count sensors — see memory
`project_app_capture_phase1`). The open work is surfacing + completeness across the
**three distinct photo sets** the device produces:
  1. **Patrol photos** — long-term; shown in the app's archive (photo + video tabs).
  2. **AI Obstacle photos** — long-term; shown in the SAME app archive alongside
     patrol, with a class+confidence overlay.
  3. **Normal obstacle photos** — captured every time the mower works around an
     obstacle DURING a session. In the app these are ONLY reachable by tapping an
     obstacle icon in the LIVE session view; once the session ends the icons are no
     longer clickable, so there's no access. They are almost certainly still stored
     cloud-side and must be captured + retained too (this 3rd set may not yet be
     covered by the shipped categoriser).
**Open sub-items (todo1.txt 1-4):**
  - **Dashboard surfacing** of all three sets — a gallery view, ideally mirroring
    the app's photo/video tabs + per-type filtering.
  - **Link photo sets to sessions** — both the long-term patrol/AI sets and the
    ephemeral per-session obstacle shots. [BRAINSTORM] (see Patrol-Logs T4 +
    the session-format brainstorm for the patrol half.)
  - **Boot backfill** — post-fetch ALL upstream-available photos/videos for this HA
    instance, at least once at boot, so a fresh install on a device that already has
    historical cloud photos/videos catches up (the 1 h sync only goes forward).
  - **Photo overlays** — render date + (for AI obstacles) the class + confidence%
    ("human 80%") burned onto the photo OR as a caption/subtitle.
**Done when:** each sub-item is implemented or explicitly deferred with a reason;
all three sets are captured (incl. the ephemeral live-session obstacle shots),
surfaced on the dashboard with overlays, linked to sessions, and a boot backfill
exists.
**Status:** open (backend shipped; surfacing + the 3rd set + backfill + overlays +
session-linking remain).
**Cross-refs:** the (resolved) "Probe for the AI-photo / obstacle-photo cloud
endpoint" item above; "Patrol Logs" T4 (Auto-Capture photo retrieval) + the
session-format brainstorm; memory `project_app_capture_phase1` /
`project_g2408_ai_photo_probe`; `archive/videos.py`, `_refresh_oss_gallery`,
`protocol/photo_meta`; `docs/research/g2408-app-capture-playbook-2026-06-09.md`.

---

### Live video stream + snapshot/record — camera entity (Tencent XP2P)

**Why:** The app shows a live camera feed whenever the mower is off the dock, with
in-app photo/video capture buttons (captures land in the OSS gallery). The g2408 HAS
a camera — `feature:"video_tx"`, vendor `tx` = Tencent IoT Video — confirming the
earlier "no camera module on g2408" notes were stale (now retracted across
`inventory.yaml` s4p22/s4p44/s4p59/s4p83 + the s2p55 IPC clarification). The full
session-establishment chain is **wire-verified and captured**; the only uncaptured
piece is the raw media payload, which is Tencent XP2P / TRTC P2P-over-UDP (off-relay
by design) and needs the Tencent IoT-Video XP2P SDK to consume.

**What's captured (control plane, all on `eu.iot.dreame.tech:13267`):**
- Enable/disable: routed action `o=400 {on:1|0}` (auto-fires at patrol start;
  `o=15 {c:0|1}` is the separate remote-control-mode camera toggle).
- Cred chain on `dreame-third-video/tx/*`: `user/accesstoken` → `dev/isDevUser`
  → `mgr/dev/getIdentity` (secretId/secretKey/deviceId/deviceName/productId)
  → `dev/getP2PInfo` (XP2P connect string; SDK v2.4.49). Order: 1→2 at app start,
  3→4 just before live view; accesstoken ≈ 7-day life, p2pInfo per-session.
- Snapshot/record: client-side frame/clip grab → `iotoss/addOssNew` (signed PUT)
  → PUT → `iotoss/ossUploaded`; 60 s record cap; retrievable via `userDidOssList`.
- Two-way "Talk" audio and ambient audio ride entirely over the P2P stream — ZERO
  control command on the wire.

**Done when:** EITHER (a) a `camera` entity drives live view — run the `o=400` + cred
chain, feed creds + p2pInfo into an XP2P/IoTVideo P2P client usable from Python/HA,
expose still+stream, `o=400 {on:0}` + close on stop; OR (b) if no viable Python XP2P
client exists, the live-preview half is explicitly deferred and only the pure-HTTP
**snapshot/record + gallery playback** is built (fully reproducible without the SDK).
Either way the decision + rationale is recorded.

**Open questions / blockers:**
- **XP2P SDK in Python is THE blocker** — Tencent's SDK is C/Java/iOS-first; live
  preview is not implementable until a binding or P2P-handshake reimpl exists. The
  HTTP capture/gallery features are not blocked by this.
- Stream codec/container (H.264 vs H.265) — needed to wire an HA camera/stream.
- `sign` algorithm for the video endpoints assumed identical to the integration's
  existing Dreame request signer — confirm the `dreame-third-video/tx/*` endpoints
  accept the same scheme. `addOssNew.pwd` purpose unconfirmed. [UNVERIFIED]

**Status:** open (control-plane setup fully captured; live preview blocked-by-XP2P-SDK;
HTTP snapshot/record/gallery feasible now). Roadmap row G ("Live camera") — attempt last.
**Cross-refs:** `docs/research/live-video-stream-setup.md` (wire-verified handoff,
authoritative); `inventory.yaml` § `api_endpoints` (`tencent_video`, `oss_manual_upload`,
`oss_photo_list`, `oss_storage_quota`) + § `opcodes` (`o400`) + § s4p22/s4p44/s4p59/s4p83
(camera-presence corrections); `OLD/from-mitm-claude/live-video.txt` (raw Mac-MITM notes
this was folded from); `docs/research/app-integration-roadmap.md` row G; the Photo/video
archive item above (shares the OSS gallery).

---

### Extend the map-edit view to spots / maintenance points / patrol points (CRUD)

**Why:** Folded in from `todo1.txt`. The interactive map-editor card shipped this
session (Phase F2b — no-go / ignore-obstacle / mow-shape create + edit-in-place +
delete; the old "Phase 2: MAP write" research item above is now RESOLVED). The
MITM-emulator docs `dreame-app-mapedit-rotate-edit-2026-06-12.md` +
`dreame-app-WRITE-implementation-guide-2026-06-09.md` carry wire-validated CRUD for
**spots, maintenance points, and ignore-obstacle zones** (ignore-obstacle is already
wired in the editor), with **patrol points** to be added soon. In the Dreame app
each of these has its OWN separate map editor; for HA it makes more sense to make
them all editable in ONE map-edit view.
**Done when:** the map-editor view supports create/edit/move/delete for spots,
maintenance points, and patrol points (alongside the existing no-go / ignore /
mow-shapes), per the wire-validated opcodes in those docs; live-confirmed on the
device.
**Status:** open (depends on capturing the opcodes into inventory — see below).
**Cross-refs:** `/data/claude/homeassistant/dreame-app-mapedit-rotate-edit-2026-06-12.md`,
`dreame-app-WRITE-implementation-guide-2026-06-09.md`; the shipped F2b editor
(`www/dreame-map-editor-card.js`, `coordinator/_writes.py:edit_map`); `inventory.yaml`
`o215`/`o218`/`o234` + the map-edit transaction entries; the (resolved) "Phase 2:
MAP write" item above; memory `project_app_findings_phase0_shipped`.

---

### Capture all `dreame*.md` MITM findings into inventory.yaml (treat as wire-validated)

**Why:** Folded in from `todo1.txt`. The app↔mower MITM-emulator capture docs in
`/data/claude/homeassistant/dreame*.md` (settings sweep, schedule write, map-edit
rotate/edit, obstacle photos, the WRITE-implementation guide, etc.) are
write-validated by the MITM rig, but not all of their findings have been promoted
into `inventory.yaml` / `entity-inventory.yaml` — leaving some in prose only, which
is exactly the drift the fact-discipline rule guards against. Per CLAUDE.md,
app-MITM counts as wire-verification across the board.
**Done when:** every wire/protocol fact in the `dreame*.md` set has a corresponding
`inventory.yaml` (or `entity-inventory.yaml`) record with `status: verified` + an
`[app-mitm:<date>-<topic>]` evidence tag; the docs are reduced to pointers/context.
**Status:** open (housekeeping; partially done — schedule / map-edit / settings /
album-photo findings are largely recorded).
**Cross-refs:** `/data/claude/homeassistant/dreame*.md`; `inventory.yaml`;
`entity-inventory.yaml`; CLAUDE.md § Fact discipline (app-MITM = wire-verified).

---

### Move completed plans/specs out of the tree into OLD/

**Why:** Folded in from `todo1.txt`. Per CLAUDE.md § Documentation canonicity,
shipped specs/plans become historical the moment the work lands and must move to
`/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/` (same relative path) so a
future session's grep/Explore doesn't retrieve them as current truth. This session
shipped several map-editor specs/plans (`docs/superpowers/specs/2026-06-12-*`,
`docs/plans/2026-06-12-*`, `docs/superpowers/specs/2026-06-12-polygon-draw.md`) plus
earlier ones; target state is **zero `docs/superpowers/` in-tree**.
**Done when:** all completed specs/plans/handoffs are moved under
`OLD/ha-dreame-a2-mower-docs/...`; in-tree `docs/superpowers/` is empty (or holds
only genuinely-active plans); code/doc cross-refs still resolve via the mirrored OLD
path.
**Status:** open (housekeeping).
**Cross-refs:** CLAUDE.md § Documentation canonicity & lifecycle;
`/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/`.

---

### Phase 3a DEFERRED — move the render transform out of `map_decoder` + unify zone types

**Why:** The P3a frame-untangle (2026-06-14) shipped only the SAFE, render-output-
preserving subset (folded `_render_*` into `map_render/`, added the Python↔JS
projection-parity test, JS cleanup, card version banners + camera `schema_version`).
Two genuinely render-output-CHANGING pieces were explicitly DEFERRED because the
mower is dead and the plan's Checkpoint-3a requires a **live HA map-render visual
confirmation** (there is no golden-image test, so a compositing/orientation
regression wouldn't be caught automatically):
  1. Move rotation + midline-reflection OUT of `map_decoder.py` into a `map_render`
     presentation step — make `ExclusionZone.points` / `SpotZone.points` / `dock_xy`
     raw-cloud-mm, relocate the transform, and handle the bbox-expansion-depends-on-
     post-rotation-corners coupling at `map_decoder.py:716-729`.
  2. Unify `ExclusionZone` / `SpotZone` / `MowingZone` into one Zone type (only clean
     AFTER step 1 makes them all raw-frame).
**Done when:** with a live mower, the transform is relocated and a live HA map render
is visually confirmed unchanged (lawn/zones/dock/obstacles land identically); the new
`tests/www/test_projection_parity.py` still passes (it is the regression gate for the
transform-move); zone types are unified with all existing render/decoder tests green.
**Status:** blocked-by-dead-mower (needs revival + live map-render visual check).
**Cross-refs:** `refactor-2026-06-13/p3a-frame-spec.md` § "Explicitly DEFERRED";
`custom_components/dreame_a2_mower/map_decoder.py:716-729`;
`custom_components/dreame_a2_mower/map_render/_geometry.py` (`_cloud_to_px` /
`_renderer_to_px`); `tests/www/test_projection_parity.py`.

---

## In-progress

_(none currently)_

---

## Blocked

### Mowing direction / Crisscross / Chequerboard pattern

**Why:** No observable property on the device's MQTT `/status/` topic carries
mowing direction or pattern. An 8-change test on 2026-05-04 produced eight
`s6p2` events all with the identical payload — the actual setting value is
absent from the outbound MQTT. Likely cloud-resident or BT-only.
**Done when:** A CFG key carrying the direction value is found via `getCFG`
brute-force (try `MOWP`, `MD`, `DIR`, `ANG`, `PAT`) OR the feature is
confirmed cloud/BT-only and documented as unsurfaceable.
**Status:** blocked-by-investigation (BT-only suspected)
**Cross-refs:** `docs/research/g2408-protocol.md §1.2` (80001 / BT channel)

---

### `ai_obstacle` blob format

**Why:** `SessionSummary.ai_obstacle` is typed `tuple[Any, ...]` because no
captured session has produced a non-empty value. Need an AI-obstacle trigger
event to capture the wire shape.
**Done when:** A session produces `ai_obstacle: [...]` in the OSS JSON;
fixture saved under `tests/protocol/fixtures/`; decoder and renderer updated.
**Status:** blocked-by-capture (need mower to detect an obstacle with AI camera)
**Procedure:** [docs/research/g2408-capture-procedures.md#2-take-a-photo-flow-apk-s-takepic-vs-ha-integration-path](g2408-capture-procedures.md#2-take-a-photo-flow-apk-s-takepic-vs-ha-integration-path)
**Cross-refs:** `protocol/session_summary.py`; journal topic `apk cross-walk findings`

---

### Patrol Logs — remaining open items

**Trigger + capture + integration surfacing are closed — see `docs/DONE.md`**
("Patrol Logs — trigger and wire format"): a patrol was triggered and captured,
the integration types it `session_type=patrol`, replays it, and excludes it from
the "Mowing" aggregates (handled like `maintenance_run`). A few low-priority /
blocked bits remain:
**Remaining:**
- The app's "Patrol Logs" TAB is still empty (separate from the mower session
  archive — origin unknown).
- Per-field OSS schema for patrol keys: now mostly decoded 2026-06-03 — see
  `inventory.yaml § summary_point / summary_point_status / summary_complete_count /
  summary_photo_list / summary_photo_detected / summary_pref`. The s4 eiid1
  piid→summary cross-walk is partial (piid10≈photo_detected, piid2=complete_count,
  piid14≈map_area, piid60=stop_reason); still need a `photo_detected=0` session to
  confirm piid10, and piid3/7/11/12/15 remain ambiguous.

**Integration work surfaced by the 2026-06-03 point patrol (op=107):**
- **[T1] ✅ DONE (2026-06-03).** First-class patrol activities added. State machine
  maps s2p50 op=108→`patrol_edge`, op=107→`patrol_point` (`state_machine.py` op_map +
  the s2p1=1 working-tick override), so the activity sensor no longer sits at
  `repositioning` for the whole patrol. Flips at the op echo (the undock→first-point
  drive legitimately stays `repositioning` until then). Tests:
  `tests/state_machine/test_patrol_live_activity.py`.
- **[T2] ✅ DONE (2026-06-03).** Edge vs Point distinguished as the two activities
  above, labelled "Edge Patrol"/"Point Patrol" (`strings.json` + `translations/en.json`;
  `mode_enum` 107=Point Patrol / 108=Edge Patrol). lawn_mower projects both → MOWING.
- **[T3] PARTIAL (2026-06-03).** Root cause FIXED: `classify_session_type` now treats
  op=107 as patrol (was falling through → the new run mislabelled "Mowing"), and
  `mode_enum` has 107. So a freshly-finalized point patrol types `patrol` and the
  picker shows `[Patrol]`. **Remaining:** (a) the picker still shows a generic
  `[Patrol]` — to show `[Edge Patrol]`/`[Point Patrol]` the archive INDEX entry
  (`archive/session.py:ArchivedSession`) must carry the mode/subtype (persisted-format
  change); (b) sessions archived BEFORE this fix keep their old type on disk.
  **Both (a) and (b) are DEFERRED into the session-format brainstorm below.**

**[BRAINSTORM] Session title + archive-format design (decide before touching the
persisted format).** Scope agreed 2026-06-03:
  1. **Subtype in the picker title, for BOTH patrol and mow.** If patrol surfaces
     Edge/Point, mowing should match: `[Mowing — All areas]` / `[Mowing — Edge]` /
     `[Mowing — Zone]` / `[Mowing — Spot]` and `[Patrol — Edge]` / `[Patrol — Point]`.
     Patrol and mow should feel the same. Needs a persisted subtype/mode on
     `ArchivedSession` + a unified `format_session_label`.
  2. **Scheduled vs manual visual differentiation:** considered, NOT now (start_mode
     is decoded; revisit later).
  3. **Can a patrol be scheduled?** RESOLVED — NO. The app's schedule UI offers only
     mow types (All areas / Zone / Edge mow); there is no patrol option, so a patrol is
     manual-trigger only `[app-ui@2026-06-03]`. No integration action now — patrol
     scheduling has no surface to model. (NB the classifier already handles a non-echoed
     patrol via `saw_patrol_start`/s2p2=51, so if firmware ever emitted a scheduled
     patrol it would still type `patrol` — defensive only.)
  4. **House per-point/edge settings + `photo_list`** on the patrol session record so
     they're tied to the session — gated on T4 (image location) for the photos.
  5. **Migration:** rebuild existing sessions via `tools/session/rebuild_session.py` once the
     format lands (the 2026-06-03 point patrol currently reads `[Mowing]` on disk).
- **[T4] Auto-Capture photo retrieval (blocked-by-path).** Photos are referenced in
  the summary `photo_list` (real filenames) but the bytes are not yet fetchable — the
  bare leaf is NoSuchKey in the summary's Aliyun dir and the exact `479D/` Xiaomi-FDS
  subpath is unknown. Needs app-capture or APK; see `project_g2408_ai_photo_probe` +
  `inventory.yaml § summary_photo_list`. Also: `fetch_session_photos.py` only reads
  `ai_obstacle` — patch it to read `photo_list`.
- **[T6] Partial/interrupted edge patrol mis-typed `maintenance_run` ("To Point").**
  Observed 2026-06-03 on a real edge patrol (op=108) that was interrupted by a stuck
  event then by rain protection (OLD code — pre-T1/T3 deploy). It archived as a
  "To Point" session and finalized with location ON_LAWN although the mower was in
  fact docked. Two distinct defects to investigate (with POST-deploy data — re-test
  the edge patrol after the release):
    (a) **typing:** an op=108 patrol should classify `patrol`, but after a
    stuck/rain interruption it landed `maintenance_run`. Likely `last_task_op` got
    overwritten away from 108 by a return/cancel op AND `saw_patrol_start` (s2p2=51)
    didn't survive the interruption/session-split. Verify against the wire
    (`probe_log_20260520_131350.jsonl`, the ~21:xx edge patrol) — do NOT presume.
    (b) **location:** finalized ON_LAWN while docked — the dock-return s2p1 either
    wasn't seen or wasn't applied to the archived snapshot at finalize. Cross-ref
    `project_rain_reboot_session_fix`.
  Side observation (LEAVE debugging for now per user): rain protection appears to
  CANCEL a patrol (the app cancelled the session), unlike a mow which it pauses —
  TBD whether that's firmware behaviour.
- **[T5] Settings are reconstructable, not stored.** Per-point cycles =
  count of in-place ~360° rotations at the point; auto-capture = whether photo_list
  timestamps fall in that point's dwell window. If per-point patrol info is ever
  surfaced, derive it this way (the requested toggle values exist on no reachable
  surface). See `inventory.yaml § o107`.
**Procedure:** [docs/research/g2408-capture-procedures.md#4-patrol-log-trigger-investigation](g2408-capture-procedures.md#4-patrol-log-trigger-investigation)
**Cross-refs:** journal topic `s2p50 op-code catalog`; apk opcodes 107/108; DONE.md "Patrol Logs"

---

### Firmware update flow — capture wire sequence

**Why:** Only one firmware update has occurred on the user's mower, before the
integration was running. The MQTT sequence during an update (STATE=14,
s2p53 progress, s2p57 shutdown trigger) is undocumented.
**Done when:** An update is captured; MQTT sequence documented; HA behaviour
during update (sensors, entities) verified.
**Status:** blocked-by-rare-event (wait for next firmware update notification)
**Procedure:** [docs/research/g2408-capture-procedures.md#1-firmware-update-flow](g2408-capture-procedures.md#1-firmware-update-flow)
**Cross-refs:** journal topic `s2p50 op-code catalog`; inventory `s2p2_state_14`

---

### Change PIN Code — confirm wire format

**Why:** The app has a "Change PIN Code" action. The wire format is unknown —
likely BT-only given PIN is a security-critical local secret. The integration
cannot currently read or write PIN.
**Done when:** PIN change is attempted while probe log is running; result is
either a cloud wire sequence documented in `protocol/config_s2p51.py`, or
BT-only confirmed and documented in `docs/research/g2408-protocol.md §1`.
**Status:** blocked-by-capture
**Procedure:** [docs/research/g2408-capture-procedures.md#8-change-pin-code-wire-format](g2408-capture-procedures.md#8-change-pin-code-wire-format)
**Cross-refs:** journal topic `s1p1 byte[3] bit 7 PIN-required clarification`; `docs/research/g2408-protocol.md §1`

---

### Pathway Obstacle Avoidance test — CFG.BP / CFG.PATH semantics

**Why:** Two CFG keys (`BP`, `PATH`) still have placeholder semantics.
Hypothesis: they relate to Pathway Obstacle Avoidance. No pathways are defined
on the user's map so neither field has been observed changing.
**Done when:** A test pathway is created and toggled in the app; CFG snapshot
diff identifies which key(s) change and what values mean; entities added.
**Status:** blocked-by-test (user has no pathway defined; needs deliberate setup)
**Procedure:** [docs/research/g2408-capture-procedures.md#5-pathway-obstacle-avoidance-user-fakeable](g2408-capture-procedures.md#5-pathway-obstacle-avoidance-user-fakeable)
**Cross-refs:** journal topic `s2p51 multiplexed config — disambiguation evolution`; canonical § CFG keys

---

### `MowerAction.SUPPRESS_FAULT` semantics

**Why:** The service exists in the integration but has never been live-tested.
It is unclear whether "suppress fault" means acknowledge a technical
malfunction, clear a physical-alert latch, or is a generic dismiss. Adding
a UI button without knowing semantics risks confusing users or triggering
unintended state changes.
**Done when:** A known-safe fault is triggered (e.g. lift lockout), the
SUPPRESS_FAULT action is called, and the resulting state change is observed.
Outcome: either a button entity is added with the right display conditions, or
the service is documented as power-user-only.
**Status:** blocked-by-safe-test-design (need a controlled fault scenario)
**Cross-refs:** `custom_components/dreame_a2_mower/actions.py`; journal topic `s1p1 byte[3] bit 7 PIN-required clarification`

---

## Phase 3: capture the Dreame app's write RPC — covers 28+ entities across multiple cloud surfaces

**Why:** Audit Tasks 3 and 4 (2026-05-09) + the SCHEDULE round-up probe (also 2026-05-09) revealed that **multiple cloud surfaces the integration uses for writes are cloud-cache-only or have missing setters on g2408**. The Dreame app uses a different write surface that we haven't reverse-engineered.

**SCHEDULE-specific update 2026-05-09:** ran `/tmp/probe_schedule_write.py` testing 5 candidate paths against the SCHEDULE blob. All returned `r=0` (cloud accepts) but the `v` version field never bumped — meaning the cloud is silently dropping the writes on every alternative path too. Direct MIoT `s8.{1..5}` returns 80001 (RPC tunnel closed for siid=8 on this firmware). Confirms SCHEDULE is genuinely Phase 3: the Dreame app must use either MQTT-direct publish to `/cmd/<did>/` (bypassing cloud RPC) or a different HTTP endpoint outside the routed-action / chunked-batch / MIoT-property surfaces we've enumerated.

Affected entities (all silently fail to drive the device after the v1.0.2a9 partial fix):

1. **CFG int-list keys (7 entities + sub-rows):** DND, LOW, WRP, BAT, LIT, REC, LANG. The cloud's routed-action `s2.50 m='s' t=KEY` returns `r=-3` (no setter). Direct MIoT `set_property(siid, piid, value)` returns `80001`. `r=-3` confirmed to mean "no setter at this address" — not a wire-format issue (cloud is lenient on the keys it does support, e.g. coerced `[1,4]` to `1` for CLS). See `wire-captures/cfg-write-regression-2026-05-09.md`. **NEW HYPOTHESIS (2026-05-09):** ioBroker.dreame uses **named-key payloads** for these complex CFG keys instead of wrapped lists — e.g. `WRP = {value:1, time:8, sen:0}`, `DND = {value:1, time:[1200,480]}`, `LIT = {value:1, time:[480,1200], light:[1,1,1,1], fill:0}`. We always sent `{value: <list>}` which is rejected with r=-3. Likely fix: refactor `set_cfg` to accept arbitrary `d` dict, then live-probe one key at a time. Catalog and test cases: `wire-captures/iobroker-write-catalog-2026-05-09.md`.

2. **SETTINGS-backed entities (13 entities):** All "Mowing settings page" entities — number.mowing_height / _cutter_position / _cutter_position_height / _edge_mowing_num / _obstacle_avoidance_height / _distance / _sensitivity; select.mowing_direction / _mowing_direction_mode / _edge_walk_mode; switch.edge_mowing_auto / _safe / _obstacle_avoidance / .obstacle_avoidance_enabled; switch.ai_obstacle_recognition_humans / _animals / _objects. The `setDeviceData` chunked-batch surface accepts the writes and persists them in the cloud chunked-batch dump, but the device firmware never sees the change and the Dreame app reads from a different surface (verified live 2026-05-09 — Map 2 app showed all 3 AI bits on even after cold-restart, while cloud had ai=6). See `wire-captures/settings-surface-cloud-only-2026-05-09.md`.

3. **AI_HUMAN.0 (1 entity), SCHEDULE (1 service):** Same chunked-batch surface as SETTINGS — almost certainly the same cloud-cache-only behavior. Confirm in audit Tasks 5 and 6.

The Dreame app obviously has a working device-write path: 3 weeks of s2p51 push fires show settings actually changing on the device when the user toggles in the app. **The path is not in our cloud_client repertoire and not in the legacy integration's repertoire either.**

**Probe-safety incident** during Task 3 wire-format brute-forcing: an `s2.aiid=1` call inadvertently triggered a global-mower-start action (the device ignored `m='s' t='WRP'` and treated it as a normal start command). Brute-force search of siid/aiid combinations is therefore not safe. Future probing must EITHER stay on `aiid=50` (varying only m/t/d) OR run only when the mower is docked AND the user is watching.

**Done when:** an HTTPS sniff of the Dreame app's "Save" tap on the affected pages identifies the wire format. Likely candidates:
- MQTT direct command publish to a `/cmd/<did>/` topic (the legacy Xiaomi pattern)
- A different cloud HTTP endpoint we haven't probed
- A different `method=` field (not `set_properties` or `action`)
- A new siid/aiid combination not in the integration's repertoire

A single sniff session capturing 4-5 different settings (one mowing-settings-page toggle, one DND change, one AI_HUMAN toggle, one schedule edit) will likely reveal the missing surface — they probably all use the same one.

Once captured, the integration routes the affected ~28 entities through the new path, retests end-to-end, and the audit's ✗ rows flip to ✓.

**Status:** open (deferred — needs traffic capture; substantial follow-up code work after that). NB the CFG int-list portion may be solvable without a sniff — see the named-key hypothesis above and `iobroker-write-catalog-2026-05-09.md`.
**Cross-refs:** `docs/research/wire-captures/cfg-write-regression-2026-05-09.md`; `docs/research/wire-captures/settings-surface-cloud-only-2026-05-09.md`; `docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md`; probe-safety incident note in the CFG file.

---

## Determine whether HA writes drive the device, or only update the cloud cache

**Why:** A whole class of g2408 settings — AI Obstacle Recognition
(humans/animals/objects), Mowing Direction, Edge Mowing Auto/Safe/
Obstacle Avoidance, LiDAR Obstacle Recognition, Obstacle Avoidance
Distance/Height/Sensitivity, Mowing Height, Cutter Position,
Mowing Pattern, Edge Walk Mode, Edge Passes, Start from Stop Point,
Pathway Obstacle Avoidance, EdgeMaster — are all readable from the
cloud and propagate end-to-end across app instances (verified
2026-05-09 via two-device test: toggle in app A, cold-start app B
on a different device → app B reflects the change without any BT
involvement). The full list and per-entity status lives in
`docs/research/entity-sync-matrix.md`.

The integration writes via `setDeviceData`. The cloud accepts the
write (CFG.VER bumps, SETTINGS reflects, refresh-button confirms).
What's NOT yet established is whether the device *firmware* applies
the HA-initiated write — i.e. whether the mower's actual behaviour
changes. Earlier we suspected "no" because the original Dreame app
session kept showing the pre-HA-write value, but that may simply be
the app's settings-screen UI cache (the same cache that hides
app-to-app changes until forced refresh).

**Right test (not yet performed):** HA writes X to a setting; then
cold-start a Dreame app instance that has never seen the device's
local cache. If it shows X, HA writes propagate fully and the
"doesn't apply" theory was a UI-cache illusion. If it shows the
pre-HA-write value, HA's `setDeviceData` only updated the cloud
cache and the device firmware uses a different write surface.

If HA writes are confirmed insufficient, the next step is HTTPS-
sniffing the Dreame app's "Save" tap to capture the actual RPC the
app uses (likely a routed-action `setX` target we haven't enumerated,
since direct MIoT `set_property` returns 80001 for most siids).

**Done when:** the test above is performed live and either:
1. HA writes confirmed end-to-end propagating → close as "no action,
   the apparent gap was UI cache"; OR
2. HA writes confirmed insufficient → app's actual write RPC is
   captured, wired into a `coordinator.write_*` method, and a
   follow-up live test confirms full propagation.
**Status:** open (deferred — needs user-side cold-start test, then
possibly a traffic capture).
**Cross-refs:** `docs/research/entity-sync-matrix.md` (full list of
affected entities); `docs/research/g2408-research-journal.md` 2026-05-09
entry "BT-only classification retracted".

---

## BAT[2] hardcoded `1` in build helpers (write-path audit, 2026-05-09)

**Why:** The sole finding still open from the 2026-05-09 write-path audit —
which checked for structural read/write mismatches like the SETTINGS
dual-entry / SCHEDULE-mode bugs (commits `b25b5ac` / `4868016` /
`b89c574`) and found no other dual-source storage shapes. (The audit's
other finding, the PRE encoder inflation, is now closed — see DONE.md.)
Three build helpers — `_build_bat_auto_recharge` (number.py),
`_build_bat_resume` (number.py), `_build_bat_custom_charging`
(switch_global.py:130) — all hardcode `BAT[2] = 1` instead of reading it
from MowerState. The decoder explicitly drops `BAT[2]` with
`# unknown_flag (consistently 1; semantic TBD)`. Live data confirms
`BAT[2] = 1` today (2026-05-09), so writes are correct now, but the
"consistently 1" assumption is brittle — if firmware ever stores
something else there, every BAT-related write clobbers it.
**Done when:** `bat_unknown_flag` is added to MowerState, populated
from `bat_raw[2]` in the CFG decoder, and the three build helpers
pass `int(state.bat_unknown_flag or 1)` instead of the literal `1`.
**Status:** open (deferred — defensive cleanup, low priority)
**Cross-refs:** `custom_components/dreame_a2_mower/switch_global.py:130-147`;
`custom_components/dreame_a2_mower/number.py:79-118`;
`coordinator/_property_apply.py:566-574` (decoder dropping `bat_raw[2]`).
