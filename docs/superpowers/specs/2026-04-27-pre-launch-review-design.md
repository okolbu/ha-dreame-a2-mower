# Pre-Launch Code Review — Structured Cleanup Plan

**Date**: 2026-04-27
**Scope**: `custom_components/dreame_a2_mower/` (~24K LOC + entity files)
**Output**: this spec (findings + disposition + sequencing) → one or
more follow-up implementation plans under `docs/superpowers/plans/`.

---

## 1. Why this review now

Two converging pressures:

1. **Soft-launch is approaching.** Most protocol decoding is in
   place. Once the integration is shared, today's
   "free-to-rename / free-to-delete" surface (entity_ids, on-disk
   schemas, Python attribute names) becomes a backwards-compat
   liability. Doing the heavy lifting now is *much* cheaper than
   doing it after others ingest data.
2. **Protocol-RE work is being slowed by code sprawl.** The
   `dreame/device.py` + `dreame/map.py` monolith (~16K LOC) and the
   ad-hoc split between `dreame/` and `protocol/` makes new
   findings hard to land. Every new property / event / blob field
   spawns scattered touch-points, scattered logging, and scattered
   tests. A structured cleanup unblocks the next wave of decoding,
   regardless of launch timing.

The review's purpose is to identify *what to delete*, *what to
restructure*, and *what to instrument* — and to sequence the work
so each step makes the next one cheaper.

## 2. Scope and immutables

**Mutable** (free to break):

- Entity IDs and their unique-ids (one cutover per phase, group
  breakage so the dashboard re-fix is one-shot).
- Config-entry options (`CONF_*`).
- On-disk archive schemas (`<config>/dreame_a2_mower/sessions/`,
  `lidar/`, `mqtt_archive/`, `in_progress.json`, `index.json`).
  **No migrator.** On schema break, delete-on-upgrade is fine; old
  session JSONs can be regenerated from `probe_log_*.jsonl` raw
  MQTT captures if needed.
- All internal Python: classes, attribute names, module layout,
  enum identifiers, `dreame/` vs `protocol/` package shape.

**Immutable** (read-only — we don't control upstream):

- MQTT wire format: siid/piid/eiid identifiers, value shapes,
  blob layouts. We *interpret* what the firmware emits; we never
  rename it on the wire.
- Cloud HTTP endpoints, auth flow, OSS download path.
- Error codes the mower emits. (Their *display* and *internal
  Python name* is mutable; the integer code is not.)

This boundary is rigid throughout the cleanup. A finding that
would require changing what we send to the mower or how we
parse what arrives is out of scope for this review.

## 3. Disposition rules

### 3.1 Entity disposition rule

For every entity in `binary_sensor.py`, `sensor.py`, `switch.py`,
`button.py`, `number.py`, `select.py`, `time.py`, `camera.py`,
`device_tracker.py`, `lawn_mower.py`:

| Underlying property/event status in `docs/research/g2408-protocol.md` §2.1 | Disposition |
|---|---|
| Confirmed mapping (decoded shape, semantic clear) | **Keep**. Classify production vs observability based on user-actionable vs protocol-debugging. |
| Partial mapping (shape known, semantic unclear or fragmentary) | **Keep**, mark as observability. |
| Documented as TBD on g2408 (might exist, not yet probed) | **Keep**, **flag for discussion** in the per-entity table. Don't auto-delete; these encode hypotheses. |
| Vacuum / MOVA / non-g2408 mower vocabulary, no g2408 evidence | **Delete** (no replacement). |

Each entity in the audit gets a citation to the §2.1 row that
justifies its existence. No-citation = candidate for deletion.

### 3.2 Code disposition rule

For every module / class / function:

- **Reachable + g2408-relevant** → keep, restructure as needed.
- **Reachable but only via vacuum/MOVA paths the integration no
  longer enters** → delete.
- **Unreachable** (no caller after deletion of vacuum entities) →
  delete.
- **Reachable on g2408 but only as a degraded fallback** (e.g.
  upstream encrypted-blob map decoder when g2408 always emits the
  cloud-JSON path) → delete the unreachable branch, keep the
  active path.

## 4. Long-term observability — three-layer design

This is the centerpiece of the review. Today's silent-drop sites
(see priority 4 below) become tomorrow's "it just doesn't work
for that user and we don't know why". The fix is one
observability mechanism applied uniformly, surfaced as data the
user can hand back to us.

### Layer 1 — Unified novel-token registry

One entry point. Replaces the scattered `_KNOWN_S2P2_STATES`,
`_KNOWN_VALUE_CATALOGUE`, `_KNOWN_UNMAPPED_QUIET_SLOTS`,
`_EMPTY_DICT_SENTINEL_SLOTS` (all in `dreame/device.py:168–200`)
plus ad-hoc warnings throughout the codebase.

```python
device.observation_log.saw(
    category="error_code",     # or "charging_status", "task_status",
                               # "action", "response_code",
                               # "segment_type", "frame_type", ...
    token=value,               # the unfamiliar value we didn't expect
    context={"siid": 2, "piid": 2, "battery_pct": 74, ...},
)
```

- **One log prefix family**: `[NOVEL/{category}]`.
- **Once-per-process at WARNING**, then DEBUG.
- **One quiet-list mechanism**, one place to add new entries when
  a value gets explained.
- Every existing silent-drop site gets converted.

### Layer 2 — Schema-validated structured blobs

For each firmware-emitted structured blob — session_summary, MAP,
event_occured.arguments, CFG response, s2p51 multiplexed config,
s1p4 telemetry frames — declare a Python schema (dataclass or
TypedDict) listing every known key + expected type. A single
validator emits `[NOVEL_KEY/{blob_name}]` when the firmware
includes a key not in the schema.

This is exactly where firmware adds new fields we *want* to know
about.

### Layer 3 — Diagnostic surface that survives logs

Two outputs, both reading the same registry from layer 1:

1. **`sensor.dreame_a2_mower_novel_observations`** (diagnostic,
   enabled by default). State = count of distinct novel tokens
   this process. Attributes = the full set, grouped by category.
   When a user reports a problem, "what's the state of this
   sensor?" answers most diagnostic questions in one shot.
2. **HA's built-in `download_diagnostics`**. Dumps the registry
   in full with redacted context. Becomes the standard ask in any
   GitHub issue template.

The post-launch effect is the multiplier: the integration
self-reports its gaps to every user, instead of relying on you
reading every user's logs.

## 5. Findings & priorities

Seven priorities, sequenced so each makes the next cheaper. Each
item carries a soft-launch tag (**must-ship** / **post-launch
debt**) and a plan-shape estimate.

### Priority 1 — Delete dead upstream-vacuum / non-g2408 code

**Soft-launch impact**: must-ship. These are the largest LOC
pollution and they actively obscure the g2408 codepaths.

**Findings** (concrete examples; not exhaustive):

- `dreame/types.py:332` — `DreameMowerDustCollection` enum: never
  referenced outside `types.py`.
- `dreame/types.py:340` — `DreameMowerAutoEmptyStatus`: same.
- `dreame/types.py:349` — `DreameMowerSelfCleanArea`: same.
- `dreame/const.py:590-599` — `FloorMaterial` /
  `FloorMaterialDirection` mappings; no entity uses them.
- `dreame/const.py:28` — `CLEANING_MODE_MOWING: "sweeping"`
  legacy alias.
- `dreame/const.py` — entire customised-cleaning, cruise-schedule,
  icemaker, water-tank, dust-collection vocabulary chains. To be
  audited end-to-end.
- `dreame/device.py` — `_check_consumable` paths for non-mower
  consumables (water tank filter, sensor brush): need per-entry
  audit to confirm each consumable is real on g2408 vs upstream-
  vacuum holdover.
- `dreame/map.py` — frame-type dispatch (`MapFrameType.I`,
  `MapFrameType.P`) and partial-map queueing pipelines that
  apply only to the upstream encrypted-blob map format. g2408's
  cloud-map JSON path bypasses these entirely. Audit and remove
  the unreachable branch.
- Any property in `DreameMowerProperty` that the `_G2408_OVERLAY`
  (in `types.py`) has zeroed out and that nothing references in
  the entity files.
- **`DREAME_MODEL_CAPABILITIES` machinery and `capability.disable_*`
  checks** (`dreame/const.py`, `dreame/device.py`). Multi-model
  capability flags are dead weight for a one-model integration.
  We've established with high confidence that g2408 shares too
  little with other Dreame mowers for future merge to be plausible
  — the integration is permanently single-model. Flatten the
  capability lookups to constants and remove the per-model
  branching.

**Disposition**: delete with no replacement. Where a deletion
breaks an entity, the entity is also deleted (per §3.1 rule —
no g2408 §2.1 entry = no entity).

**Plan-shape**: 1 plan, ~5–8 phases, mostly mechanical.
Per-module: types → const → device methods → map methods →
entity files. Each phase is "delete X, run tests, commit".

---

### Priority 2 — Audit and lock entity inventory + on-disk schema

**Soft-launch impact**: must-ship. After launch, every entity
rename costs user dashboards. Every on-disk schema change costs
user data unless a migrator ships.

**Findings**:

- ~84 sensor descriptors (`sensor.py`), ~36 switches, ~20 buttons,
  plus binary_sensors / numbers / selects / times. Many predate
  the protocol-doc rule and need a citation audit.
- Entities with comments like "may not exist", "unknown if
  implemented", "confirmed YYYY-MM-DD" need explicit tier
  assignment (production / observability / experimental-flagged).
- On-disk: `sessions/index.json`, `sessions/*.json`, `lidar/index.json`,
  `lidar/*.pcd`, `in_progress.json`, `mqtt_archive/YYYY-MM-DD.jsonl`.
  Schema versioning today: implicit. Add an explicit `schema_version`
  field per file family — but **no migrator**. On version mismatch,
  log a WARNING and skip the file (or wipe-and-rebuild the index).
  Old session JSONs can be regenerated from `probe_log_*.jsonl` if
  needed.

**Disposition**:

- Per-entity table in the plan: name, current entity_id,
  underlying property, §2.1 doc citation, classification
  (production / observability / experimental-flagged / DELETE),
  proposed new entity_id (if rename), proposed `entity_category`
  / `entity_registry_enabled_default`.
- Per-on-disk-file table: current shape, frozen v1 shape, version
  field placement, version-mismatch behavior (log + skip).
- Final entity_id renames + schema-version stamp ship in **one
  cutover commit** so the dashboard fix is one-shot.

**Plan-shape**: 1 plan, ~3 phases. (a) audit table —
mostly research, no code. (b) entity_id + schema-version
freeze — one mechanical pass. (c) version-mismatch handler
in each archive class.

---

### Priority 3 — Unified observability (three-layer design from §4)

**Soft-launch impact**: must-ship. The whole multi-user model
depends on this; without it, post-launch protocol divergences
are silent.

**Findings**:

- Existing watchdog (`dreame/device.py:695` — `UnknownFieldWatchdog`)
  covers novel siid/piid and novel values for known properties.
  Limited surface.
- Five separate hand-maintained "known-quiet" data structures in
  `dreame/device.py:168-200`. Each grew organically; merging
  them into one mechanism is structural cleanup independent of
  the new layers below.
- No watchdog for: enum fallbacks (`ERROR_CODE_TO_ERROR_NAME.get(...)`,
  `CHARGING_STATUS_CODE_TO_NAME.get(...)`,
  `TASK_STATUS_CODE_TO_NAME.get(...)`), API response shapes
  (`response.get("code") == 0` paths), missing/novel dict keys in
  structured blobs (session_summary, MAP, CFG, event_occured),
  action dispatch (`if action not in self.action_mapping` →
  silent None), segment-type / frame-type defaults.
- No diagnostic-sensor surface. No `download_diagnostics`
  integration.

**Disposition**: implement the three-layer design from §4.
Layer 1 first (registry + conversion of every silent-drop site),
then layer 2 (schema validators for the four structured blobs),
then layer 3 (diagnostic sensor + download_diagnostics).

**Plan-shape**: 1 plan, ~4 phases:
- Phase 1: registry skeleton + migration of existing watchdog +
  merging of the five quiet-lists.
- Phase 2: convert silent-drop sites by category (one commit
  per category — error_code, charging_status, task_status,
  action, response_code, segment_type).
- Phase 3: schema validators for the structured blobs.
- Phase 4: diagnostic sensor + download_diagnostics.

---

### Priority 4 — Session-finalize correctness

**Soft-launch impact**: must-ship. A live bug today; users will
hit it.

**Findings** (from `TODO.md` "PROTOCOL_NOVEL entries" section,
`dreame/device.py:1170–1261`, `live_map.py:984–1050`,
`session_archive.py`):

- **Cloud retry has no max-age**. `_pending_session_object_name`
  is retried on every coordinator update; if the OSS object 404s
  permanently (e.g. cloud-side eviction), the retry loop is
  infinite, throttled-but-spinning. `device.py:1205-1222`.
- **Fallback finalize silent-skip**. `live_map.finalize_session()`
  returns silently if `coordinator.session_archive is None`
  (`live_map.py:1003`). Live path lost on HA restart between
  session-end and successful summary fetch.
- **Auto-finalize gate over-suppresses CHARGING_COMPLETED**.
  Documented in `TODO.md`; the gate suppresses end-of-run
  finalize whenever status is in any "recharge state". The
  disambiguator (`_task_pending_resume + _task_running_s2p56`)
  is identified but not yet wired.
- **`_fetch_session_summary` doesn't always update
  `latest_session_summary`** (TODO §"PROTOCOL_NOVEL ... cloud
  session-summary download still failing"). Trace why — likely
  silent failure inside the cloud fetch, masked by the same
  silent-drop pattern as priority 4 above.

**Disposition**: each issue is a discrete fix; together they form
one plan.

- Cloud retry: add `max_retries` + `max_age_s` to
  `_pending_session_object_name` semantics. After exhaustion,
  promote the live_path to an "(incomplete)" archive entry and
  clear the pending state.
- Fallback finalize: replace the silent-return with a WARNING +
  archive-disabled fallback (write to a recovery directory), so
  the data isn't lost even when archival was disabled.
- Auto-finalize gate: implement the disambiguator.
- Summary-fetch trace: requires priority 3 to be in place
  (response-shape watchdog), so the failure mode self-reports.

**Plan-shape**: 1 plan, ~4 phases — one per finding, in order.
Phase 4 (summary-fetch trace) is *blocked* on priority 3.

---

### Priority 5 — Decompose `dreame/device.py` and `dreame/map.py`

**Soft-launch impact**: must-ship. Directly unblocks protocol-RE
iteration speed; launch is gated on all seven priorities, not
calendar.

**Findings** (from background-agent exploration):

- `dreame/device.py` (8.3K LOC):
  - ~11 side-effect handler functions (lines 235–386).
  - Main `DreameMowerDevice` class (lines 433–8223) — 100+
    property accessors, task-state machine, action dispatcher,
    cloud integration, MQTT callback routing all in one class.
  - `DreameMowerDeviceStatus` (line 6816+) — 300+ lines of
    computed properties.
  - `_handle_event_occured`, `_fetch_session_summary`, session-end
    detection, fallback finalization.
- `dreame/map.py` (8.1K LOC):
  - Cloud map request pipeline (`_request_*_map`).
  - Partial-map queueing (`_queue_partial_map`,
    `_unqueue_next_partial_map`).
  - Blob decoding (`_decode_map_partial`, `_add_cloud_map_data`,
    I/P frame dispatch).
  - Rendering support.

**Disposition**: extract along clear seams. Each becomes a
500–1000 LOC module with a focused test surface.

Suggested decomposition for `device.py`:
- `device/core.py` — connection, MQTT routing, message callback,
  dispatch.
- `device/properties.py` — property store, mapping, getters.
- `device/actions.py` — action dispatch, action_mapping,
  validation.
- `device/status.py` — `DreameMowerDeviceStatus`, all computed
  properties.
- `device/session.py` — `_handle_event_occured`,
  `_fetch_session_summary`, session-end detection.
- `device/side_effects.py` — `_SIDE_EFFECTS` registry + handlers.
- `device/state_machine.py` — task-state, status transitions.

Suggested decomposition for `map.py`:
- After Priority 1 deletes the upstream encrypted-blob branches,
  the residual is ~half size and naturally splits into:
  - `map/manager.py` — orchestration.
  - `map/cloud_fetch.py` — HTTP / OSS / `getMapData`.
  - `map/decode.py` — JSON-shape decoding only (the partial-map
    queue is upstream and goes away).
  - `map/render_support.py` — what's left.

**Plan-shape**: 2 plans (one per file). Each ~5 phases:
extract module skeleton → move methods one cluster at a time
with green tests → finalize imports → delete dead originals →
post-condition verification. Each phase is one commit.

---

### Priority 6 — Test coverage for post-decomposition modules

**Soft-launch impact**: must-ship. Cheap once priority 5 is done,
impossible while it isn't.

**Findings** (from background-agent exploration):

- `protocol/` decoders are well-tested.
- `dreame/device.py` — zero direct tests. Side effects untested.
  Task-state machine (1895–1945) untested.
- `live_map.py` (1.7K) — zero direct tests. Session finalization
  path (984–1050) untested.
- `coordinator.py` (806) — zero direct tests.
- `dreame/map.py` (8K) — partial coverage via `protocol/` tests
  on shared decoders; frame-type dispatch, partial-map queueing,
  retry logic untested. Most of this becomes moot after
  priority 1 + 5.
- `camera.py` (1.5K) — zero direct tests.

**Disposition**: focused tests per post-decomposition module.
Aim for the seams: action dispatch, session lifecycle, side-
effect registry, state transitions, session-finalize edge
cases. Don't aim for line coverage; aim for behavior coverage
of the parts that the seven priorities together touched.

**Plan-shape**: 1 plan, ~4 phases — one per critical module.

---

### Priority 7 — Reconcile `dreame/` vs `protocol/` package layout

**Soft-launch impact**: must-ship. Cosmetic-but-load-bearing for
contributors; ship before others see the package shape.

**Findings**:

- `dreame/` was forked from upstream — name reflects "the upstream
  device package". After priorities 1 + 5 most of it has been
  rewritten or deleted.
- `protocol/` is a grab-bag — `mqtt_archive`, `pcd`, `pose`,
  `session_summary`, `cfg_action`, `replay`, `unknown_watchdog`,
  `properties_g2408`, … Some are codecs (well-named), some are
  validators (now under priority 3), some are subsystem entry
  points.
- After priorities 1, 3, 5 the natural shape is:
  - `protocol/` — pure codecs (encode/decode) and schema
    validators (priority 3 layer 2).
  - `device/` — runtime state, dispatch, lifecycle (priority 5
    decomposition).
  - `archive/` — `session_archive`, `lidar_archive`, `mqtt_archive`
    (currently scattered between `protocol/` and root).
  - `observability/` — registry from priority 3 layer 1, watchdog,
    diagnostic-sensor backing data.

**Disposition**: rename + reorganize the package after
priorities 1, 3, 5 land. Pure mechanical move; tests prove
correctness.

**Plan-shape**: 1 plan, 1–2 phases. Module moves +
import-fixup pass.

---

### 5.8 Documentation discipline — `ioBroker.dreame` apk cross-reference

Not a priority — a *rule for the protocol doc* that the seven plans
must respect.

`ioBroker.dreame` ships an apk decompilation of the Dreame Smart
Life app. It targets a different mower (g2568a). Findings derived
from that apk are **lower confidence than our own g2408 captures**
and must not silently override our decoders.

Discipline:

1. Where our decoder agrees with apk findings: cite the apk as
   corroboration in the protocol doc §2.1 row.
2. Where our decoder *differs* from apk findings: keep our
   decoder, mark the row as "apk reports X; we observe Y;
   future testing required" so future probes can disambiguate.
   Examples already known:
   - **s1p4 12-bit packing**: apk says bytes 1–6 are 3 packed
     12-bit values (x24, y24, angle8). We decode as int16_le.
     Likely diverges beyond ±32 m. Apk says we're missing the
     angle byte.
   - **s1p4 task struct**: apk says bytes 22–31 hold
     `{regionId, taskId, percent, total, finish}` with uint24
     area fields; we treat as uint16+static.
   - **More s1p4 frame lengths**: apk lists 7/10/13/22/33/44
     byte variants; we handle 8/10/33.
   - **s1p51 / s2p52**: apk says re-fetch triggers, not session
     boundary markers (our current reading).
3. No "validate-against-apk" sub-task in the seven plans. The
   discipline applies whenever a priority touches a row in §2.1.

## 6. Implementation order and gates

All seven priorities are must-ship. Launch waits on all of them,
not on calendar.

```
P1: Delete dead code         ─── (depends on: nothing)
P2: Lock entity + on-disk    ─── (depends on: nothing — parallel with P1)
P3: Unified observability    ─── (depends on: nothing — parallel with P1, P2)
P4: Session-finalize fix     ─── Phase 4 depends on P3
P5: Decompose device.py/map.py  (depends on P1)
P6: Tests for post-decomp    ─── (depends on P5)
P7: Package reconciliation   ─── (depends on P1, P3, P5)
```

Parallelism notes:
- P1, P2, P3 can run concurrently (different file sets).
- P4 phases 1–3 can run concurrently with P3; phase 4 waits on P3.
- P5 waits on P1 (no point decomposing code about to be deleted).
- P6 waits on P5.
- P7 waits on P1, P3, P5 — runs last, package shape settles after
  the others have moved their code.

Suggested execution order if working serially:
**P1 → P2 → P3 → P4 → P5 → P6 → P7**. P1 first because every
later step is cheaper against a smaller codebase. P3 before P4
because P4 phase 4 depends on P3. P7 last because it reorganizes
files that the other priorities still touch.

## 7. What this spec produces

After this spec is approved:

1. **One implementation plan per priority** (P1–P7) — except P5,
   which produces two plans (one for `device.py` decomposition,
   one for `map.py` decomposition). Each plan lives under
   `docs/superpowers/plans/2026-04-27-pre-launch-pN-*.md` with
   its own concrete phase breakdown, file lists, acceptance
   criteria.
2. **Per-entity audit table** (priority 2 deliverable) — the table
   itself ships in the P2 plan.
3. **Per-on-disk-schema audit table** (priority 2 deliverable) —
   same.

## 8. Working discipline during the cleanup

Process notes that apply to every plan under this spec:

- **Commit cadence**: small, frequent commits with descriptive
  messages. Each phase of every plan should land as one or
  more focused commits.
- **Push to `origin/main` regularly** so the GitHub repo
  reflects current state. Pushing is for traceability, not for
  releasability — there is no need to keep `main` always
  installable during the cleanup, no need to bump versions,
  no need to gate commits on green CI for HACS-pulls-this-now
  reasons. Bisectability and "what changed and when" matter;
  release readiness does not.
- **No versioning churn**: don't bump `manifest.json` /
  `pyproject.toml` versions per phase. A single version bump
  at the end of each priority is fine if natural.
- **Existing memory** *"Push upstream regularly — HACS pulls
  from origin/main"* still applies for *cadence*; the
  installability bar is relaxed for the duration of these
  plans only.

## 9. Resolutions

Open questions raised during brainstorming, with resolutions:

1. **Soft-launch line position.** *Resolved 2026-04-27*: All
   seven priorities are in scope; launch waits on all of them.
   "Soft-launch impact" tags throughout §5 read "must-ship".
2. **On-disk schema migrator.** *Resolved 2026-04-27*: No
   migrator. Delete-on-upgrade is acceptable; old session JSONs
   can be regenerated from `probe_log_*.jsonl` if ever needed.
   Folded into §2 and P2.
3. **Capability flag flattening.** *Resolved 2026-04-27*: Done
   under P1. Single-model is permanent — g2408 shares too little
   with other Dreame mowers for future merge to be plausible, so
   `DREAME_MODEL_CAPABILITIES` and `capability.disable_*` machinery
   become dead code and get flattened to constants.
4. **`ioBroker.dreame` apk cross-reference.** *Resolved
   2026-04-27*: Not a sub-task; a documentation discipline. apk
   findings are lower-confidence than our own captures (apk
   targets a different mower model). Where decoders agree, cite
   the apk as corroboration; where they differ, keep our decoder
   and mark §2.1 rows as "future testing target". See §5.8.
