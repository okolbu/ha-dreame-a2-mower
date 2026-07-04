# Dreame A2 Mower — agent instructions

## Fact discipline (load-bearing)

This repo has had repeated incidents where the agent regenerated debunked
claims, lost track of which facts were wire-verified vs presumed, and let
documentation drift week after week. The cause is always the same: a
finding got recorded in prose but not in any structured place the next
session would find. This rule exists to stop that.

### Generation-time scope (load-bearing — the gate fires in conversation, not just at inventory-write)

The inventory rules below fire when you *write a file*. But presumptions are
born earlier — in conversational reasoning — and by the time you'd write
inventory you have already asserted the guess as fact and maybe acted on it.
So the gate must fire where the leak happens: **in the prose you generate.**

**Rule:** every sentence you write — in chat OR in a doc — that describes a
wire/protocol surface (where a value lives, what a byte means, what a payload
carries, when an event fires, how a setting is transported) MUST carry an
inline epistemic tag:

- `[<log_file>@<ts>]` or `[apk:<ref>]` / `[screenshot:<name>]` — direct evidence; matches `verified`.
- `[UNVERIFIED]` — hypothesis, no evidence yet; matches `presumed`. State the guess ONLY with this tag attached.
- `[UNKNOWN — to capture]` — a gap; the honest output here is a capture/verification step, not a description.

A bare declarative about the wire with no tag is the bug this rule exists to
catch. "Don't presume" failed as a prohibition because it gave no alternative
action; the alternative is: tag it `[UNVERIFIED]`, or convert it to a capture
step. Absence of evidence must be structurally visible in the sentence itself.
When you only have a guess, prefer producing the capture plan (what to grep /
trigger / diff) over volunteering an "analysis" that reads as fact.

### Don't restate decoded values — cite the inventory id (anti-drift)

`inventory.yaml` is the SINGLE place a decoded wire value lives. Prose
elsewhere — `README.md`, the Tier-2 docs, `knowledge-gaps.md`, code
comments, commit messages, AND the agent's own auto-memory — may **cite**
an inventory id/section but must **not restate the decoded value**. A
restated value (an s2p2 code→meaning table, a byte-layout, a threshold, a
"the Save path is X" claim) becomes a SECOND copy that drifts the moment
inventory is corrected, and the next session greps the stale copy and
regenerates it as truth. This is the exact failure the 2026-06-28 wire-truth
audit found: a debunked README "Save path is an open work item" resurrected
as open, 6 memory files contradicting inventory, ~19 wrong vacuum s2p2 names
duplicated across inventory + knowledge-gaps. Rule: when you would write a
wire value into a doc, write **"see `inventory.yaml` § \<section\> `<id>`"**
instead. If the value genuinely is not yet in inventory, that is the signal
to add it there FIRST (per the recording rule below), then cite it.

### When the rule fires

You MUST update an inventory file in the same response as any of:

- Observing a new fact about a protocol surface (wire shape, value
  semantics, emission trigger, encoding detail) — whether from a probe
  log, a cloud dump, an app screenshot, or an apk decompile.
- Retracting or correcting a prior claim, including one you wrote
  yourself earlier in the same session.
- Verifying that an integration entity reads from the source it claims to
  (or noticing that the source has changed).
- Adding, renaming, or removing an integration entity (any HA platform
  file: switch / sensor / select / number / binary_sensor / camera /
  button — coordinator is excluded).

### What to record

For protocol facts: `custom_components/dreame_a2_mower/inventory.yaml`.
For integration handling: `custom_components/dreame_a2_mower/entity-inventory.yaml`.

Append a record under the entry's `verifications:` list. Required fields:

```yaml
verifications:
  - date: "<YYYY-MM-DD>"            # today, from runtime context
    status: verified | partial | presumed
    claim: "one-line statement of what's true"
    evidence: "<log_file>@<rough-ts>" | "app-screenshot:<name>" | "apk:<ref>" | omit if status=presumed
```

Also update `status.last_seen` to today's date.

**Retractions / supersessions — do NOT leave `status: retracted` inline (policy 2026-06-16).**
`inventory.yaml` (and `entity-inventory.yaml`) hold **current truth only**: grep over an
inline retracted claim surfaces the debunked text without its retraction context and the
next session regenerates it as fact (this happened twice in one session — the
SETTINGS-writability and the PRE/EdgeMaster "not writable" mistakes). When you retract or
supersede a prior claim:
1. **Remove** the now-false content (the stale `semantic:` prose and/or the superseded
   `verifications:` item) from the inventory file.
2. **Append** the full record to the archive
   `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/inventory-history/<section>.md`
   — one entry per supersession: entry id, the **verbatim** prior claim, the reason, the
   date, and the evidence that superseded it. This archive is the durable, addressable
   record; it replaces the inline `retracted` log.

`status: retracted` is allowed ONLY as a transient marker within a single working session;
before handoff, fold it into the archive and delete it from the inventory.

### The honesty constraint

**Never invent an evidence pointer.** If you cannot point at a real probe
log, screenshot, or apk reference, the status is `presumed`, not
`verified`. Recording a `presumed` claim is better than no record;
recording a `verified` claim without evidence is worse than no record
because the next session will trust it.

For retractions, the only required honesty is that `retracts:` quotes
the prior claim that's being withdrawn — not a paraphrase. Grep for
the prose in the entry's `semantic:` block and flag it for the user if
it needs rewording.

- **App-MITM is wire-verified.** Captures from snooping the app↔mower link
  (mitmproxy on :13267, e.g. the 2026-06-09 settings sweep and 2026-06-10
  schedule-write decode) count as wire-verification across the board — not only
  for calendar entities, and not limited to integration-originated wire. A claim
  proven by a clean single-variable diff against an app↔mower capture may be
  marked `confirmed` and a control flipped writable, tagged
  `[app-mitm:<date>-<topic>]`.

- **Integration↔app passthrough is wire proof; app config is authoritative for
  device behaviour.** A setting that round-trips between the integration and the
  Dreame app in either direction — HA writes it and the app reflects it, or the
  app writes it and HA reads it back — is `confirmed` to be in effect on the
  mower, NOT merely "cloud-cached." The Dreame app is the vendor control surface:
  a setting it reflects IS what the mower operates under (otherwise the app would
  not control the mower — there would be no point having one). So do NOT split
  "cloud propagation" from "device-firmware execution" for an app-reflected
  setting, and do NOT keep a device-effect `[UNVERIFIED]` hedge on a write the
  integration issues with the app's own byte-identical envelope that round-trips
  to the app. The hedge survives ONLY for a write that does not round-trip to the
  app, or that uses a non-app envelope the app never sends. (Edge case to still
  flag if seen: a setting the app shows but is genuinely display-only in the app
  UI — rare; call it out explicitly rather than assuming it.)

### Provenance priority (app-MITM overrides)

**App-MITM observations are authoritative over older probe-only or APK-derived
claims.** When an app-MITM capture contradicts an earlier probe-log or
APK-catalogued "fact", the app-MITM finding wins: update the inventory to the
app-MITM truth and archive the older claim (per the retraction/supersession rule
above — remove inline, append to `OLD/.../inventory-history/`). Do not preserve the
contradicted older claim inline, even with a tag. (Mirrored at the top of
`inventory.yaml` in the PROVENANCE PRIORITY header note.)

### Debunked-claims register (negative knowledge)

`docs/research/debunked-claims.md` is the negative-knowledge companion to
`inventory.yaml`: a numbered table (D1–D20+) of claims that were once believed
and have since been proven false, plus a list of known-reversal "eras" (dead
assumption-generations) found during the 2026-07-02 archaeology pass. Treat it
as a **blocklist**, not a source of facts — never copy a row's "DEBUNKED claim"
column into code, prose, or a new inventory entry as if true; the "truth"
column only points at the current `inventory.yaml` id, it never restates the
value. When you delete dead code or retract a claim that matches (or would
resurrect) an entry here, the tombstone comment or retraction note cites
`docs/research/debunked-claims.md § D<n>` (or `§ <era name>` for an era row) —
never restate the debunked content inline. Adding a new entry goes through the
normal inventory retraction flow above; this register only indexes it.

### Where this rule does NOT apply

- Refactors that don't change wire understanding or entity sources.
- File renames, comment edits, formatting changes.
- Test additions.
- Changes inside `coordinator.py` (too broad — gating it would create
  noise; the rule applies to the entity *definitions* in the platform
  files, not to the orchestrator).

If you're unsure whether the rule applies, default to recording. A stray
`presumed` entry is recoverable; a missed verification is not.

### Convenience shortcuts

- `/verify-fact <surface-key> claim="..." evidence="..." [status=...]` —
  same shape, less typing. Use when there's a single discrete fact.
- `/retract <surface-key> retracts="..." reason="..."` — shortcut for
  the retraction case.

These slash commands are not required; the rule is the load-bearing
part. Use Edit/Write directly when natural.

### Provenance / status taxonomy

| Status | Means |
|---|---|
| `verified` | direct evidence cited — wire capture, screenshot, or apk reference |
| `partial` | decoded with known gaps (e.g., 3 of 4 bytes understood) |
| `presumed` | hypothesis only; no evidence yet |
| `retracted` | **archive-only** — transient within a session; the durable record lives in `OLD/.../inventory-history/`, NOT inline in `inventory.yaml` |

### Why this matters

When the agent ships a finding in prose only, the next session reads it without
the structure that says how confident it is, and re-derives the original wrong
claim. Two things now prevent that: (1) the inventory entry records the
**current** fact with its provenance tag, and (2) the
`OLD/ha-dreame-a2-mower-docs/inventory-history/` archive holds every **superseded**
claim with the evidence that killed it — so a debunked claim stays addressable for
"have we seen this before?" **without** sitting in the live file where a grep would
resurrect it as truth. Current truth lives in `inventory.yaml`; dead claims live in
the archive. Never reintroduce an inline `retracted` log.

### `error_codes.py` confidence gate (durable guard)

`mower/error_codes.py` (`S2P2_EVENT_TYPES`) is CI-gated against
`inventory.yaml § state_codes` by
`tests/inventory/test_error_codes_confidence_gate.py`.

Note: `ERROR_CODE_DESCRIPTIONS` has been retired. Display strings now come
from the authoritative app catalog `mower/fault_catalog.py` /
`mower/data/fault_catalog.json` (`[apk:g2408-plugin-ext1423]`), accessed
via `describe_error(code, lang)`. The confidence gate no longer governs a
descriptions dict; it governs only `S2P2_EVENT_TYPES`.

**Rule:** a code may carry a slug in `S2P2_EVENT_TYPES` ONLY if its
`state_codes` row has `decoded: confirmed` or `decoded: partial`. A code whose
row is `decoded: hypothesized`, `decoded: unknown`, or absent must NOT appear
in `S2P2_EVENT_TYPES` — delete it. Unobserved codes that fire at runtime
surface automatically as `[PROTOCOL_NOVEL]` log entries and via the
`unknown_s2p2` activity entry, so removing a hypothesized name loses nothing
while removing the risk of the name being mistaken for a confirmed g2408 fact.

This is the durable answer to the recurring "vacuum-lineage / unvalidated names
creep into the code" failure (root causes: the s2p2=28 "blade-wear" debunk and the
s2p2=71 "standby-return" rename). If CI goes red here, it means a code was added to
`S2P2_EVENT_TYPES` without a matching confirmed/partial `state_codes` entry — fix by
adding the inventory row first, or by removing the code from `S2P2_EVENT_TYPES`.

---

## Per-map naming convention (load-bearing)

All per-map entities are namespaced under the integration's prefix. The
load-bearing rule is in `_devices.py:map_device_info`:

```python
display_name = f"{DEFAULT_NAME} {suffix}"   # "Dreame A2 Mower Map 1"
```

HA composes friendly_name and entity_id from the device's `name:` and
the entity's `_attr_name:`. With `has_entity_name=True`:

- friendly_name = `<device_name> <entity_name>` (e.g., "Dreame A2 Mower Map 1 EdgeMaster")
- entity_id = `<platform>.<slug(device_name)>_<slug(entity_name)>`
  (e.g., `switch.dreame_a2_mower_map_1_edgemaster`)

### Rules

1. **NEVER name a per-map sub-device without the integration prefix.**
   Bare `"Map 1"` / `"Map 2"` produces entity_ids like `select.map_1_*`
   that collide with other integrations' generic Map entities. The
   `f"{DEFAULT_NAME} {suffix}"` form is mandatory.

2. **NEVER set `_attr_name = f"{map_name} ..."`** on a per-map entity
   class. With `has_entity_name=True` HA already prepends the device
   name. Manually prefixing produces doubled friendly_names like
   "Dreame A2 Mower Map 1 Dreame A2 Mower Map 1 Edge walk mode" and
   doubled entity_id slugs.

   The correct form is `_attr_name = "<entity name only>"` (e.g.,
   `"Edge walk mode"`, `"EdgeMaster"`, `"Base"`).

3. **Parent-device entities** use `mower_device_info()` which sets the
   device name to `DEFAULT_NAME` ("Dreame A2 Mower"). Entity_ids are
   `<platform>.dreame_a2_mower_<key>`. Same `_attr_name` rule —
   entity-name only, no manual prefix.

4. **User-renamed maps** (the Dreame app's custom map name) flow
   through to the device name automatically — the prefix is still
   applied, so a map renamed "Front Yard" gets device name
   "Dreame A2 Mower Front Yard" and entity_ids stay namespaced.

### Why this matters

Pre-2026-05-14 the per-map device names were bare `"Map N+1"` and
entity_ids were `<platform>.map_N_<key>`. That collided with other
integrations and made the per-map / parent-device prefixes look
unrelated in the UI. We tried to fix it incrementally (per-map
sub-device split, then double-prefix bug fix) and ended up with three
parallel naming schemes in the same registry. The convention above
is the consolidated answer; tests in
`tests/integration/test_per_map_entity_names.py` and
`tests/integration/test_devices_helpers.py` pin it.

### Per-map entities are static-at-setup (by design)

Each platform's `async_setup_entry` builds per-map entities by looping
`coordinator.cloud_state.maps_by_id` **once**, so a map discovered after
setup gets no entities until the config entry is reloaded. This is
intentional for a single-user deployment (maps rarely change; reload is a
fine workaround — see `feedback_no_migration_overengineering`). Do **not**
add dynamic per-map `async_add_entities` machinery without a real need.
Note the device side *is* dynamic: `_device_sync._sync_map_subdevices`
adds/removes per-map devices on every cloud refresh, so a new map's device
appears immediately — only its entities wait for a reload.

---

## Coordinator structure (load-bearing)

The mower coordinator lives in
`custom_components/dreame_a2_mower/coordinator/` as a **package**, not a
single file. Decomposed 2026-05-15 from a 4997-LOC `coordinator.py`
monolith (see
`/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md`
and the matching plan).

**Post-P3.9 role (refactor-v2, capstone 2026-07-04):** the coordinator is now a
**thin composition root + attr hub + poll orchestrator**. The per-concern
business LOGIC has moved to the layer-4 `domain/` services (P3.9a–9e); the
mixins here are **thin delegators** that preserve the public/test surface and
dispatch to a `domain/` function taking the coordinator (`coord`) as its first
argument. `_CoreMixin` owns the god-`__init__` (the shared-state ATTR HUB — the
T2-16 shipped shape, see the architecture doc §1 and the attr-hub decision note
there) plus the transport bootstrap (`_init_cloud` / `_init_mqtt`); the ~450-LOC
first-refresh poll body dissolved into `domain/boot.py:async_first_refresh`
(`_async_update_data` is now a one-line delegator). Cite the target architecture:
`docs/superpowers/specs/2026-07-02-refactor-v2-target-architecture.md` §1.

> **Shipped-shape deviation from the spec's "single file" ideal (recorded
> 2026-07-04):** the target-architecture §1 sketched the composition root as a
> single `coordinator.py` ≤400 LOC. The SHIPPED decision keeps the **package**
> of thin-delegator mixins + `_core.py` composition root — collapsing 11
> delegator files into one buys nothing (the LOGIC already left), and the
> "don't bring back coordinator.py single file" package-contract rule below
> stands. `_core.py` lands at ~950 LOC, NOT ≤400, and that is a deliberate
> architecture decision, not a miss: it is almost entirely the god-`__init__`
> attr hub (~380 LOC of one-attr-per-line shared state, T2-16's chosen shape)
> plus the transitional @property accessors and `_init_cloud`/`_init_mqtt`. The
> per-module ≤400 cap is met by every `domain/` service; `domain/boot.py` (~530)
> is a recorded exception (poll-orchestration timer boilerplate, already split
> into ordered seam functions).

When adding a new method: the LOGIC goes in the owning `domain/` service (see
the "Domain layer" section); add a thin delegator here only to preserve an
existing public/test surface. When adding shared state, it still goes in
`_CoreMixin.__init__` (the sole owner) under the matching service section header.

**Mixin-bearing files** (each defines one `_<Concern>Mixin`; LOC as of 2026-07-04):

| File | LOC | Mixin | Concern |
|---|---|---|---|
| `__init__.py` | 78 | — (assembly) | Class assembly + public re-exports |
| `_mqtt_handlers.py` | 132 | `_MqttHandlersMixin` | **Thin delegators (P3.7)** to the `domain/` ingress/lifecycle/signals modules + the `_CFG_SINGLE_KEYS` write-key table. The routing/state-update/event_occured/MAPL LOGIC moved to `domain/` (see the "Domain layer" section); this mixin preserves the public/test surface (`coord._on_mqtt_message`, `coord.handle_property_push`, `coord._on_state_update`, `_mqtt_handlers.capture_session_type_signals`). |
| `_session.py` | 158 | `_SessionMixin` | **Thin delegators (P3.9a)** to the `domain/session/{finalize,persistence,replay}` modules. The restore/persist/finalize/replay LOGIC moved to `domain/session/` (see the "Domain layer" section); this mixin preserves the public/test surface (`coord._route_finalize`, `._run_finalize_incomplete`, `._restore_in_progress`, `._persist_in_progress`, `.render_work_log_session`, `.replay_session`, + the unbound `_SessionMixin._X` methods bound via `__get__`). |
| `_core.py` | 954 | `_CoreMixin` | **Composition root + attr hub + transport bootstrap.** `__init__` (the sole `self._foo` owner — grouped by owning-service section headers, P3.9e), the availability properties + P3.2 transitional @property accessors, `_init_cloud`, `_init_mqtt`, `_restore_device_messages`. `_async_update_data` is now a **thin delegator (P3.9e)** to `domain/boot.py:async_first_refresh` (the ~450-LOC first-refresh poll body dissolved there). The rc=5 MQTT auth-recovery pair (`_handle_mqtt_auth_error` @callback + `_async_recover_mqtt_auth`) delegates (P3.9d) to `domain/mqtt_lifecycle.py`; the `_rc5_*` guard-state attrs + `_RC5_*` constants stay owned here (attr hub). |
| `_lidar_oss.py` | 185 | `_LidarOssMixin` | **Thin delegators (P3.9c)** to `domain/lidar/service.py` (LiDAR archive accessors + s99p20 fetch + 3dmap backfill), `domain/media/gallery.py` (OSS photo/video gallery), and `domain/wifi/service.py` (WiFi body cache + render-entry selection + `_build_map_extents`). The cloud-OSS finalize assembly (`_inject_live_map_into_raw_dict` / `_do_oss_fetch[_body]`) already delegates to `domain/session/finalize.py` (P3.9a). This mixin preserves the public/test surface (`coord.lidar_archive_for`, `coord._refresh_oss_gallery`, `coord.set_wifi_render_entry`, the unbound `_LidarOssMixin._X` methods, `import coordinator._lidar_oss as L`) + re-exports `finalize_classify_raw_dict` / `merge_mow_type_fields` / `fetch_photos_from_summary` and keeps `async_call_later` / `photo_meta` importable for test monkeypatches. |
| `_writes.py` | 249 | `_WritesMixin` | **Thin delegators (P3.9b)** to the `domain/writes/{service,schedule,settings,tasks,map_edit}` modules. The write orchestration LOGIC moved VERBATIM to `domain/writes/` (see the "Domain layer" section); this mixin preserves the public/test surface (`coord.write_settings`, `coord.write_setting`, `coord.dispatch_action`, `coord.edit_map`, `coord.write_schedule`, the unbound `_WritesMixin._X` methods, `import coordinator._writes as W`). `_next_schedule_txn_id` is the ONE method kept as a real impl (not delegated) — it reads the coordinator-private lazy `_last_schedule_txn_id` via `getattr` default, which a domain module can't do without tripping `test_no_coordinator_private_getattr`. |
| `_device_sync.py` | 142 | `_DeviceSyncMixin` | **Thin delegators (P3.9d)** to `domain/device_sync.py` (map sub-device registry sync + target-area + cloud-refresh tripwire + event-entity wiring + `_fire_*` lifecycle emitters) and `domain/faults.py` (fault-delta + error-tier persistent notices + emergency-stop banner). ALL fault + device_sync method NAMES stay on `_DeviceSyncMixin` (test_fault_events binds `_DeviceSyncMixin._fire_fault_delta` etc. via `types.MethodType`) + the `_EMERGENCY_STOP_CODE` class attr is preserved. |
| `_wifi_archive.py` | 70 | `_WifiArchiveMixin` | **Thin delegators (P3.9e)** to `domain/wifi/service.py` (WiFi-heatmap archive refresh + OSS download+archive + RSSI-fingerprint map_id matcher + active-map overlay accessor — consolidating the 9c-deferred refresh alongside the body-cache/render-entry helpers that landed there in 9c). Preserves the public/test surface (`coord.refresh_wifi_archive`, `coord._periodic_archive_refresh`, `coord.active_map_wifi_overlay`, `coord._tag_wifi_archive_map_ids`, read by `camera/map.py`). The `_WIFI_MATCH_RECENT_SESSIONS` cap stays a class const here (read via `coord._WIFI_MATCH_RECENT_SESSIONS`). |
| `_rendering.py` | 75 | `_RenderingMixin` | **Thin delegators (P3.9e)** to `domain/render.py` (live-map base render + editor/clean-base variants, live position stream publish, cold-start `live_track_snapshot`, last-session-obstacle overlay). Preserves the public/test surface (`coord._render_base` etc., the unbound `_RenderingMixin._X` methods bound by `test_base_render_on_activity` / `test_live_stream_publish` / `test_obstacle_live_render`) + re-exports `LIVE_TRACK_SNAPSHOT_MAX`. |
| `_refreshers.py` | 116 | `_RefreshersMixin` | **Thin delegators (P3.9d/9e)** to the per-domain poll slices: `domain/gps.py` (`_refresh_gps`), `domain/device_info.py` (`_refresh_dock`/`net`/`remote`/`dev`/`mpos` + `apply_mpos_result`), `domain/obstacles.py` (`_refresh_aiobs` + `_fetch_pending_obstacle_photos`), `domain/notifications.py` (`_refresh_messages`). `_refresh_mapl` stays a REAL impl here (map-poll glue → `coord._apply_mapl`, no single domain home — deferred). Poll ORCHESTRATION (cadence → slice) lives in `domain/boot.py`. Re-exports `apply_mpos_result`. |
| `_notifications.py` | 78 | `_NotificationsMixin` | **Thin delegators (P3.9d)** to `domain/notifications.py` (cloud s2p2 resolver + device-message accumulate-to-200 dedup → `sensor.last_notification` feed). Keeps `_FETCH_DELAY_S` defined here (passed into the resolver so the monkeypatch target holds) + re-exports `_source_key` / `_english_text`. |
| `_cloud_state.py` | 227 | `_CloudStateMixin` | `cloud_state` apply to MowerState + map fetch / persist |

**Non-mixin helper modules** (pure functions / classes imported by the mixins above — NO `_*Mixin`, NOT in the inheritance list):

| File | LOC | Concern |
|---|---|---|
| `_property_apply.py` | shim | **P3.6 re-export shim** → `state/apply.py` (the pure apply funnel moved to the state layer). Keeps `from ._property_apply import …` working; retired P3.10. |
| `_recorder_merge.py` | 432 | Fill battery/wifi/state/charging/error sample gaps from HA recorder history at finalize |
| `_snapshot.py` | 139 | Build the session-begin firmware `settings_snapshot` from MowerState |
| `_restore_merge.py` | 123 | Restore-then-merge of `in_progress.json` payloads on boot |
| `_write_errors.py` | 78 | `raise_for_write_result` — map a `WriteResult` to `ServiceValidationError`/`HomeAssistantError` |

### Mixin pattern

Each submodule defines exactly one mixin class
(`_<ConcernName>Mixin`). `DreameA2MowerCoordinator` (in `__init__.py`)
inherits from all of them plus `DataUpdateCoordinator[MowerState]`. All
`self.foo` references work via Python's MRO.

**Only `_CoreMixin` owns `__init__`** — it's the sole site that
assigns `self._foo = ...` for shared private state. Every other mixin
is a pure method container. Don't override `__init__` in any other
mixin; don't write to a new `self._<attr>` without first adding it to
`_CoreMixin.__init__`.

> **Documented exception (P3.8; helper relocated P3.9d):**
> `domain/timers.py:schedule_self_cleaning` (moved out of `coordinator/_managed_timers.py`
> in P3.9d — its only callers are now domain services) lazily initialises
> `owner._managed_cancellers` (a set) and `owner._managed_unload_registered`
> (a bool) on first use, from OUTSIDE `_CoreMixin.__init__` — deliberately, so
> the helper also works on the bare `_WritesMixin()` / `_LidarOssMixin()` doubles
> that tests build via `object.__new__` without a full coordinator. These two
> attrs are the ONLY sanctioned exception to the "sole `__init__` owner" rule;
> the P3.9 attr-shrink audit should treat them as owned by the timer/lifecycle
> service, not seed them in `_CoreMixin.__init__`.

### Public-import preservation

`from .coordinator import DreameA2MowerCoordinator` (and
`apply_property_to_state`, `_BLOB_SLOTS`, `_SUPPRESSED_SLOTS`,
`S2P2_NOTIFICATION_MAP`, `_project_north_east`) resolve through
`coordinator/__init__.py`'s re-exports. Tests and entity platforms
keep their imports unchanged.

### Cross-mixin type hints

A mixin method may call into another mixin's method (e.g., `_apply_mapl`
in `_MqttHandlersMixin` schedules `self._render_base()` which
lives in `_RenderingMixin`). Use `TYPE_CHECKING` blocks to satisfy
static analysis:

```python
if TYPE_CHECKING:
    from ._rendering import _RenderingMixin
```

At runtime this is a no-op; the MRO dispatches.

### Don't

- Don't add a new method to `_property_apply.py` unless it's a pure
  `MowerState → MowerState` function with no side effects. Side-effect
  methods belong in one of the mixins.
- Don't bring back a `coordinator.py` single file. The package is the
  contract — and post-P3.9 that package is deliberately kept (see the
  "Shipped-shape deviation" note above): the mixins are thin delegators, so
  collapsing them into one file buys nothing while the LOGIC lives in `domain/`.
- Don't move business logic INTO a coordinator mixin. New logic goes in the
  owning `domain/` service (coord-taking function); the mixin only gets a thin
  delegator when an existing public/test surface must be preserved.
- Don't add a `Mixin` to the inheritance list without first creating
  the file and registering its mixin class. Static analyzers and
  Python's MRO both need the class defined before the inheritance
  list references it.

---

## Domain layer (load-bearing)

`custom_components/dreame_a2_mower/domain/` (layer 4) holds orchestration
services extracted from the coordinator god-object, starting with the MQTT
ingress path in P3.7 (refactor-v2, autopsy #3). Each module takes the
coordinator (`coord`) as an explicit first argument rather than being a
coordinator mixin, so the LOGIC lives at the domain layer while the
coordinator keeps a thin delegating method surface.

| Module | Concern |
|---|---|
| `domain/ingress.py` | MQTT routing: `on_mqtt_message`, `handle_property_push` (the paho→loop `_deferred` dispatch), `handle_event_occured`, `apply_mapl`. **P2.9 paho-thread purity preserved VERBATIM** — the paho thread captures only `(siid,piid,value,now)`; base-read/decode/mutate/broadcast run loop-side in `_deferred`. |
| `domain/session/lifecycle_events.py` | The `_on_state_update` lifecycle-edge detectors, decomposed VERBATIM into named seam functions (`_detect_session_transitions`, `_append_session_telemetry`, `_sync_session_view`, `_detect_non_mow_end_edge`, `_detect_dock_edges`, `_detect_self_shutdown_edge`, `_detect_s2p2_notification`, `_detect_lidar_object_name`, `_detect_dock_return_signal`) + the `on_state_update` orchestrator that calls them in the EXACT original order. Also the charging/rain/shutdown fire helpers + `capture_telemetry_sample`. |
| `domain/session/signals.py` | Session-TYPE signal capture: `capture_session_type_signals` (s2p56 multi-target ids, s2p50 op, area-ever-positive), `latch_task_op`, `handle_task_op_echo`, `seed_session_type_from_pending`. |
| `domain/session/finalize.py` | **The finalize state machine (P3.9a, autopsy #4/#10§1)** — the most corpus-validated code in the repo, moved VERBATIM. `route_finalize` / `dispatch_finalize_action` / `periodic_session_retry`; `finalize_with_latch` (single latch, P3e.4, completion-sentinel via `post_archive_reset`); `wait_for_dock_return` (P2.7 single-flight + P2.8 `_pending_finalize_task` cancel); `finalize_non_mow_immediate` / `finalize_prior_for_new_command`; `run/do_run_finalize_incomplete`; `merge_recorder_into_payload`; `provisional_session_type/is_mow/is_cloud_finalized`; `resolve_finalize_map_id`; the OSS-finalize assembly `inject_live_map_into_raw_dict` / `finalize_classify_raw_dict` / `do_oss_fetch[_body]`. Pinned by `test_finalize_interleavings/latch` + `test_pending_finalize`. |
| `domain/session/persistence.py` | **in_progress.json lifecycle (P3.9a)** — `restore_in_progress` (restore-then-merge + P2.7 restore×finalize discard guard), `persist_in_progress` (T3-12 TOCTOU `_finalize_lock` hold), `load_pending_op_from_sidecar` / `clear_pending_op`. |
| `domain/session/replay.py` | **Session replay + work-log render + picked-session derivation (P3.9a)** — `render_work_log_session` + `replay_session` (coord-taking render orchestration) + the pure derivation folded in from the DELETED root `session_card.py` (T2-13 misnomer): `build_picked_session_summary` + section helpers, `derive_render_legs` / `compute_track_distances`, `format_session_label`, `_normalise_settings_snapshot`, `_track_as_dicts`, `_compute_time_breakdown`, enum label tables. |
| `domain/writes/{service,schedule,settings,tasks,map_edit}.py` | **The write orchestration (P3.9b, autopsy #9)** — moved VERBATIM from `coordinator/_writes.py`. `service` = shared WriteResult plumbing (`_accepted` / `_chunked_kv_write_result` / `_write_result_from_schedule_exc`) + `async_trigger_firmware_update`. `schedule` = SCHD*V3 writes (`write_schedule` / `write_schedule_enabled`). `settings` = SETTINGS.* / CFG / PRE / AI_HUMAN writes + per-map General dual-writes, carrying the P2.6/P3.8 optimistic-broadcast + **per-field revert** VERBATIM. `tasks` = `dispatch_action` + the `start_*` launchers + `ensure_active_map`. `map_edit` = the `edit_map` txn driver (o=200/204/…/201 ordering) + the map-object CRUD ops + `write_patrol_point_config` (o=111 + CRUISED optimistic overlay). WriteResult end-to-end preserved; pinned by `test_write_honesty_cfg` + the per-family rejection tests. **The low-level device writers (`set_cfg`/`set_pre`/`trigger_firmware_update`) STAY in transport at `cloud_client/_writers.py`; these services orchestrate them via `coord._cloud.<writer>` — a legal domain(4)→transport(2) downward call.** |
| `domain/lidar/service.py` | **LiDAR archive + fetch (P3.9c, autopsy #10 §2)** — moved VERBATIM from `coordinator/_lidar_oss.py`. Per-map archive accessors (`lidar_archive_for` / `list_lidar_archive_entries` / `set_lidar_render_entry`), the live s99p20 object-name handler (`handle_lidar_object_name`), and the one-shot 3dmap startup backfill (`backfill_lidar_from_3dmap`). Pinned by `test_lidar_per_map` / `test_lidar_backfill` + `test_coordinator.py`'s lidar-object-name tests. |
| `domain/media/gallery.py` | **OSS photo/video gallery (P3.9c, autopsy #10 §3)** — moved VERBATIM. The hourly/boot OSS media sync (`refresh_oss_gallery`), the signed-URL gallery manifest builder (`rebuild_photo_gallery` / `sign_media_path`), the per-session photo manifest (`session_photos_manifest` / `signed_photo_thumb`), the device-message snapshot-photo linker (`link_message_snapshot_photos`), the post-finalize gallery-refresh scheduler (`schedule_post_session_gallery_refresh`), plus the module-level OSS-summary helpers the finalize service calls (`fetch_photos_from_summary` / `merge_mow_type_fields`). The 7-category `photo_category.categorize` + the camera-token double-broadcast preserved byte-for-byte. Internal cross-method calls route through the coordinator delegators (`coord._sign_media_path` / `coord._signed_photo_thumb` / `coord._rebuild_photo_gallery`) so test monkeypatches still intercept. Pinned by `test_oss_gallery_sync` / `test_photo_fetch` / `test_archive_mow_type`. |
| `domain/wifi/service.py` | **WiFi archive service (P3.9c body-cache + P3.9e refresh)** — moved VERBATIM. 9c: `get_wifi_body_cached` / `async_load_wifi_body` / `set_wifi_render_entry` (the wifi body CACHE) + `build_map_extents` (map-geometry hint). **9e consolidated the `_WifiArchiveMixin` refresh orchestration here** (the 9c deferral): `periodic_archive_refresh` / `refresh_wifi_archive` (OSS download+archive) / `download_and_archive_wifi` / `read_session_wifi_samples` / `tag_wifi_archive_map_ids` (RSSI-fingerprint map_id matcher) / `resolve_active_map_wifi_entry` / `active_map_wifi_overlay` / `schedule_active_map_wifi_load`. The pure `wifi/` support package (`archive_store` / `match` / `map_render`) STAYS separate. Pinned by `test_wifi_selected_camera` / `test_wifi_archive_select` / `test_wifi_archive_refresh` / `test_active_map_wifi_overlay` / `test_wifi_matcher_plumbing`. |
| `domain/notifications.py` | **Cloud s2p2 notification resolver + message refresh (P3.9d + P3.9e)** — moved VERBATIM from `coordinator/_notifications.py` (9d) + `coordinator/_refreshers.py` (9e). `resolve_s2p2_notification` (cloud device-messages/v2 fetch + unseen-match fire), `establish_notification_baseline`, `mark_notification_seen` (FIFO cap), `apply_device_messages` / `merge_device_messages` (accumulate-to-200 merge-by-id dedup) + the pure `_source_key` / `_english_text` helpers; **9e added `refresh_messages`** (message-record/list v1 + device-messages/v2 + share-messages poll → its device-message merge routes through `coord._merge_device_messages`, the same module's `merge_device_messages`). The resolver takes `fetch_delay_s` as a param so the `coordinator/_notifications.py:_FETCH_DELAY_S` monkeypatch target holds. Pinned by `test_notification_synthesizer` / `test_device_messages_accumulate` / `test_messages_refresh`. |
| `domain/render.py` | **Live-map render orchestration (P3.9e)** — moved VERBATIM from `coordinator/_rendering.py`. `render_base` (the ONLY server-side live-map render — background-mode/md5/marker/direction-deduped base PNG + editor/clean-base variants), `render_active_map_base`, `current_mower_position`, `compute_background_mode`, `schedule_render_base` (paho-thread-safe hop), `live_obstacle_polygons`, `begin_live_stream` / `publish_live_point` / `live_track_snapshot` (client-side trail stream + cold-start backfill), `load_last_session_obstacles`. Presentation-orchestration: reaches UP into `map_render` (layer 6) via **function-local imports only** — the layer gate excludes those (it names `coordinator/_rendering.py` as the exemplar; `domain/render.py` inherits the same accepted pattern). Pinned by `test_base_render_on_activity` / `test_live_stream_publish` / `test_obstacle_live_render` / the render golden. |
| `domain/device_info.py` | **Device-info / connectivity refresh (P3.9e)** — moved VERBATIM from `coordinator/_refreshers.py`. `refresh_dock` (CFG.DOCK position), `refresh_net` (SSID/IP/RSSI seed), `refresh_remote` (4G SIM + biz_4g_remain chain), `refresh_dev` (DEV serial/fw/ota + OTA-version), `refresh_mpos` (diagnostic routed-get) + the pure `apply_mpos_result`. Pinned by `test_phase_c_refreshers` / `test_apply_mpos_result`. |
| `domain/obstacles.py` | **Live AIOBS marker refresh (P3.9e)** — moved VERBATIM from `coordinator/_refreshers.py`. `refresh_aiobs` (mow-gated marker poll + re-render trigger) + `fetch_pending_obstacle_photos` (file-bridge photo download loop, per-marker isolated). Pinned by `test_aiobs_sensor` / `test_aiobs_photo_fetch`. |
| `domain/boot.py` | **First-refresh poll ORCHESTRATOR (P3.9e)** — moved VERBATIM from `coordinator/_core.py:_async_update_data` (the ~450-LOC first-boot body). `async_first_refresh(coord)` = the composition root's poll orchestrator, decomposed into ordered seam functions (`_restore_and_init_transports` → `_register_debounce_cancel` → `_schedule_full_state_and_baseline` → `_schedule_specialist_refreshers` → `_schedule_session_retry` → `_load_and_seed_archives` → `_schedule_persist_and_tick`). **P2.2 ConfigEntryNotReady + P2.7/P2.9 restore-before-MQTT ordering preserved byte-for-byte.** `_init_cloud`/`_init_mqtt`/`_restore_device_messages` stay on `_CoreMixin` (called via `coord._`). ~530 LOC (recorded >400 exception — timer-registration boilerplate). Pinned by `test_setup_reload_lifecycle` / `test_setup_cloud_blip` / `test_wifi_archive_refresh` (the `async_track_time_interval` monkeypatch + periodic-archive source-inspect guard target this module). |
| `domain/device_sync.py` | **Device-registry sync + lifecycle-event emission (P3.9d)** — moved VERBATIM from `coordinator/_device_sync.py`. `sync_map_subdevices`, `compute_target_area_m2`, `update_device_registry_serial`, `schedule_cloud_refresh` (debounced tripwire), `register_event_entities`, and the `_fire_*` emitters (`fire_mowing_ended` / `fire_notification` / `fire_lifecycle` / `fire_local_novel_s2p2`). Corpus-adjacent (fire on state edges). Pinned by `test_subdevice_sync` / `test_event_entity` / `test_coordinator`. |
| `domain/faults.py` | **Fault-surfacing emission glue (P3.9d)** — moved VERBATIM from `coordinator/_device_sync.py`. `fire_fault_delta` (fault_detected/cleared on snapshot.errors edges), `post_fault_notice` / `dismiss_fault_notice` / `repost_active_fault_notices` (error-tier persistent notices), `handle_emergency_stop_transition` (PIN banner) + `_EMERGENCY_STOP_CODE`. The fault tier/text/category KNOWLEDGE already lives correctly at layer 3 (`mower/fault_catalog.py` + `error_codes.py`, the P4 work); this only orchestrates surfacing. Corpus-adjacent. Pinned by `test_fault_events`. |
| `domain/gps.py` | **GPS/absolute-location refresh (P3.9d)** — moved VERBATIM from `coordinator/_refreshers.py`. `refresh_gps` (getRecords → position_lat/lon; P2.10 keep-last: None=transient-keep vs {}=clear). ONLY the GPS refresh moved; the other `_refresh_*` cycles are coordinator poll orchestration that stays until 9e. Pinned by `test_phase_c_refreshers`. |
| `domain/mqtt_lifecycle.py` | **MQTT rc=5 auth-recovery (P3.9d)** — moved VERBATIM from `coordinator/_core.py`. `handle_mqtt_auth_error` (@callback delegator) + `async_recover_mqtt_auth` (cloud re-login + credential hot-swap) with the escalating cooldown (T3-9 / P3.8). The `_rc5_*` guard-state + `_RC5_*` constants stay owned by `_CoreMixin` (read via `coord._rc5_*`) for 9e. Pinned by `test_mqtt_auth_recovery`. |
| `domain/timers.py` | **Self-cleaning delayed-timer registry (P3.8 P2-inherit; relocated here P3.9d from `coordinator/_managed_timers.py`)** — `schedule_self_cleaning`: bounded per-owner `async_call_later` registry; each timer self-removes on fire, ONE `entry.async_on_unload` hook cancels all outstanding. Callers pass their own module-local `async_call_later`. Sole callers: `domain/writes/map_edit.py:edit_map` + `domain/media/gallery.py` post-session refresh. Lazily inits `owner._managed_cancellers` / `_managed_unload_registered` (the sanctioned `_CoreMixin.__init__` exception). |

### Rules

- **Layer gate** (`tests/audit/test_layer_imports.py`, `domain`=4): domain may
  import state=3 / transport=2 / protocol=1 / foundation=0 and same-layer
  siblings; it must NOT import entities (5) or presentation (6).
- **VERBATIM-move discipline.** The ingress path is corpus-validated behaviour.
  When touching these modules, MOVE/decompose — never reimplement — and prove it
  with the corpus IDENTICAL gate (`tools/replay/corpus_replay.py --diff …`) plus
  `test_sm_thread_safety` / `test_mqtt_auth_recovery` / `test_finalize_interleavings`.
- **Delegators preserve the public/test surface.** `_mqtt_handlers.py`'s thin
  methods keep `coord.handle_property_push`, `coord._on_state_update` (+ the
  unbound `_MqttHandlersMixin._on_state_update`), and the
  `_mqtt_handlers.capture_session_type_signals` module attribute working. Tests
  that monkeypatch a moved symbol (`build_settings_snapshot_v2`,
  `apply_property_to_state`) patch it at its NEW module home.
- **`getattr(coord, "_private")` from a domain module is forbidden** by
  `test_no_coordinator_private_getattr` (it silently returns the default once
  P3.8 moves the attr off the coordinator). Add a typed transitional accessor to
  `coordinator/_core.py` (the P3.2 pattern) and read that instead — as done for
  `s2p2_resolver_tasks`, `pending_finalize_done`, `active_map_id`.
- **Property dispatch is already table-driven where the mapping encodes it.** The
  `(siid,piid)→field` decode dispatch lives in `state/apply.py:apply_property_to_state`
  (driven by `protocol/property_mapping.py:PROPERTY_MAPPING`), which ingress
  calls. The remaining per-slot ladders in ingress/lifecycle
  (`_apply_sm_mutations` slot→SM-method routing, the `_apply` session-lifecycle
  slot logic, `capture_telemetry_sample` slot→buffer selection) are BESPOKE
  side-effects NOT encoded in `property_mapping.py` — do NOT invent a new
  dispatch table for them; they stay explicit handlers.
- The FULL coordinator de-godding (thin composition root) is P3.8/P3.9. **P3.8
  landed the P2-inherit correctness debt + two structural wins** (write_setting
  per-field revert, AI-bit `async_set_updated_data` routing, rc=5 cooldown
  escalation, self-cleaning timer registry; `CloudState.from_parts`
  factory at the state layer; the `services/` package + `services/debug.py`
  isolation). The **mixin→domain-service extractions** landed across P3.9a–9d:
  9a `session/{finalize,persistence,replay}.py`; 9b `writes/`; 9c
  `media/`/`wifi/`/`lidar/`; **9d `notifications` / `device_sync` / `faults` /
  `gps` + the rc=5 pair → `mqtt_lifecycle.py` + the timer registry relocated to
  `domain/timers.py`**. The heavy coordinator mixins are now thin delegators.
  The `_CoreMixin.__init__` ~75-attr shrink + the `_async_update_data` poll-body
  dissolve remain **DEFERRED to 9e** (the thin-coordinator collapse): 9e owns the
  `__init__` shrink, so the domain-service attrs still live on `_CoreMixin` (read
  via `coord.<attr>`) until then. **OTA has no separable domain module** — the OTA
  read is glue inside `_refreshers.py:_refresh_dev` (poll-cycle, stays until 9e),
  the trigger is `domain/writes/service.py:async_trigger_firmware_update`, the
  version fetch is transport (`cloud_client/_ota.py`), and the entity is
  `update.py`; there is no `domain/ota.py`.

---

## State package (load-bearing)

The typed mower model lives in `custom_components/dreame_a2_mower/state/`
(layer 3), split out in P3.6 (refactor-v2, T2-15). `MowerState` is no
longer a 164-field flat dataclass — it is a **composition of 8 frozen,
slotted domain sub-containers**, each owned/written by one domain service:

| Module | Contents |
|---|---|
| `state/containers.py` | The 8 sub-dataclasses (`Identity`, `OtaState`, `Telemetry`, `Connectivity`, `Consumables`, `Settings`, `SessionRefs`, `Messages`) + the value enums (`State`, `ActionMode`, `ChargingStatus`). |
| `state/mower_state.py` | `MowerState` = composition of the 8 containers + `FLAT_FIELDS`. |
| `state/snapshot.py` | `StateSnapshot` + dimension enums (moved from `mower/`). |
| `state/machine.py` | `MowerStateMachine` (moved from `mower/`). |
| `state/cloud_state.py` | `CloudState` aggregate (moved from root `cloud_state.py`; composed by the refresh service, R-31). |
| `state/apply.py` | Pure `(siid,piid,value)/CFG → MowerState` apply funnel (moved from `coordinator/_property_apply.py`). |

### The container split is field-home only — the flat surface is preserved

For the duration of the P3 migration `MowerState` keeps the **entire legacy
flat interface** so no read/write site changed this phase:

- **Reads** — a delegating `@property` exists for every one of the 164 flat
  fields (`state.battery_level` → `state.telemetry.battery_level`). Entity
  descriptors and the ~59 prod `.data.<field>` sites are UNCHANGED.
- **In-place writes** — each delegate also has a **setter** that swaps the
  owning frozen container, preserving the old mutable-dataclass behaviour
  (`state.battery_level = 5` still works — 36 test + 1 prod site rely on it).
- **Construction** — `MowerState(battery_level=5, …)` (flat kwargs) routes
  each kwarg to its container via a custom `__init__(init=False)`. The 258
  test constructions are unchanged.
- **`dataclasses.replace(state, field=x)`** funnels through the same
  `__init__`, so the ~85 prod + ~35 test replace sites route to the right
  container transparently — **no call-site changes were required**. The
  preferred flat writer is `state.with_updates(**fields)`.
- **`asdict(state)` now yields the nested container shape.** Consumers that
  need the flat `{field: value}` shape use `state.to_flat_dict()` /
  `FLAT_FIELDS` — the corpus-replay digest and the diagnostics `state`
  section already do (keeps the golden digest byte-identical). Anything that
  enumerated `dataclasses.fields(MowerState)` (which now returns the 8
  CONTAINER names) must read `FLAT_FIELDS` instead — e.g. the state-machine
  audit's orphan-field derivation.

### Rules

- **Each container is the sole writer's value-object.** As domain services
  are extracted (P3.8+), a service owns exactly one container and mutates it;
  do NOT scatter writes to the same container across services.
- The old paths — `mower/state.py`, `mower/state_snapshot.py`,
  `mower/state_machine.py`, root `cloud_state.py`,
  `coordinator/_property_apply.py`, `mower/property_mapping.py` (→
  `protocol/`) — are **re-export shims**, retired in P3.10. New code imports
  from `..state` / `..state.<module>` (and `..protocol.property_mapping`).
- The `StateSnapshot` ↔ `MowerState` **decode-staging** relationship is
  PRESERVED (2026-06-15 3d-revisit ruling): pure `apply.py` writes
  `MowerState`; the SM snapshot is the persisted/entity-read behavioural SoT.
  Do NOT collapse snapshot into MowerState.
- Do NOT reintroduce a flat 164-field `MowerState`. The container composition
  is the contract.

---

## Refresher cadence (load-bearing)

Cloud polling is consolidated onto one full-state timer plus a few
fast/slow specialists. Do **not** re-add per-slot CFG/MIHIS timers — they
were removed in the 2026-05-25 refresher consolidation
(`/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/specs/2026-05-25-refresher-consolidation-design.md`).

| Timer | Interval | Why separate |
|---|---|---|
| `_refresh_cloud_state` | 2 min | Full state: cfg, mihis, mapl, settings, maps, props. Ports CFG via `cfg_to_state_updates`, MIHIS + SETTINGS, and active-map via `_apply_mapl(cs.mapl)`. |
| `_refresh_gps` | 60 s | Absolute GPS via location/getRecords → device_tracker (position_lat/lon). |
| `_refresh_dock` | 60 s | Dock position sensors (x/y/yaw/in_region). Location not set here — s2p1 is the sole location authority. |
| `_refresh_net` | 1 h | NET is not part of the full-state fetch. |
| `_refresh_remote` | 6 h | 4G SIM status (REMOTE) → SIM sensors. |
| `_refresh_messages` | 1 h | Account message-list unread (message-record/list v1). |
| `_refresh_dev` | 6 h | DEV is not part of the full-state fetch. |
| `_refresh_aiobs` | 2 min (mow-gated) | Live AIOBS obstacle markers; early-returns unless a mow session is active. View-gated analogue — never background-polls. |

> **Note:** the LOCN routed-action refresher was removed (it was unscheduled
> dead code). `position_lat`/`position_lon` are written solely by `_refresh_gps`.
> The low-level `cloud_client.fetch_locn` fetcher was deleted in P1 (zero
> integration callers — see `docs/research/debunked-claims.md` § LOCN
> endpoint era / D18); the LOCN wire target still exists (`inventory.yaml` §
> LOCN) and can be re-added trivially if a future dock-location entity needs
> it.

`CloudState` does **not** carry `dock` — it flows straight to
`MowerState` via its 60 s timer. The CFG→MowerState port lives in the pure
`coordinator/_property_apply.py:cfg_to_state_updates` helper, which never nulls
a field for an absent CFG key and never emits `pre_mowing_height_mm` /
`pre_edgemaster` (those are owned by the s6.2 push, `property_mapping.py`).

---

## Cloud client structure (load-bearing)

The cloud client lives in
`custom_components/dreame_a2_mower/cloud_client/` as a **package**, not a
single file. Decomposed 2026-05-20 from a monolithic `cloud_client.py`
(B1d split).

Each submodule owns one concern. When adding a new method, place it in
the submodule whose concern it matches:

| File | Concern |
|---|---|
| `__init__.py` | Shell `DreameA2CloudClient`: `__init__` + state, properties, MQTT accessors (`mqtt_host_port`, `mqtt_client_id`, `mqtt_credentials`, `mqtt_topic`), `_ensure_strings`, `disconnect`, mixin assembly, public re-export |
| `_helpers.py` | Shared module-level helpers: `_LOGGER`, `_http_retry`, `_random_agent_id` |
| `_auth.py` | `_AuthMixin`: login (primary + secondary-key refresh-token path) |
| `_discovery.py` | `_DiscoveryMixin`: device discovery (`get_devices`, `get_device_info`, `get_info`, `select_first_g2408`) |
| `_rpc.py` | `_RpcMixin`: transport/RPC — `send`, `request`, `action`, `routed_action`, `send_async`, `action_async`, `get_properties`, `set_property`, `set_properties`, `_api_call`, `_api_call_async`, `get_api_url` |
| `_oss.py` | `_OssMixin`: OSS signed-URL fetch (`get_interim_file_url`, `get_file_url`), WiFi heatmap listing (`list_wifi_candidates`), raw file download (`get_file`) |
| `_batch.py` | `_BatchMixin`: batch device-data primitives (`get_batch_device_datas`, `set_batch_device_datas`, `write_chunked_key`, `get_device_data`, `get_device_property`, `get_device_event`) |
| `_state_fetch.py` | `_StateFetchMixin`: periodic cloud-state family reads — `fetch_cfg`, `fetch_dev`, `fetch_mihis`, `fetch_dock`, `fetch_net`, `fetch_map`, `fetch_mapl`, `get_pre` (PRE read), plus the `fetch_full_cloud_state` orchestrator (returns decoded **parts**, NOT a `CloudState` — composition is the state layer's job, see below) + its per-family `_decode_*` module helpers |
| `_device_fetch.py` | `_DeviceFetchMixin`: live per-device telemetry — `fetch_gps`, `fetch_remote`, `fetch_4g_remain`, `fetch_mpos`, `fetch_aiobs_markers` |
| `_messages.py` | `_MessagesMixin`: cloud message stores — `fetch_device_messages`, `fetch_message_record`, `fetch_share_messages` |
| `_media.py` | `_MediaMixin`: OSS media — `list_oss_media`, `fetch_oss_quota` |
| `_ota.py` | `_OtaMixin`: `fetch_ota_version` (OTA availability check) |
| `_writers.py` | `_WritersMixin`: device WRITES — `set_cfg`, `set_pre`, `trigger_firmware_update` (all return `WriteResult`). **FINAL HOME (P3.9b decision):** these are transport-level HTTP/routed-action calls that reach the cloud-client's own internals (`self.action`, `self.request`, `self._did`/`_uid`/`_last_send_error_code`), so they STAY here in transport (layer 2). `domain/writes/` ORCHESTRATES them via `coord._cloud.set_cfg` / `.set_pre` / `.trigger_firmware_update` — a legal domain(4)→transport(2) downward call. They do NOT move into `domain/writes/` (that would force a domain→transport-internals back-edge, undoing P3.5's clean split). |
| `_fetchers.py` | **Back-compat shim** (P3.5): composes `_FetchersMixin` from the six family mixins above so pre-split test importers keep working. NO endpoints of its own; retired in P3.10. New code imports the specific family mixin. |

### Rules

- One `_<Concern>Mixin` per file; the file name mirrors the concern.
- Only the shell `__init__.py` owns `__init__` — it's the sole site that
  assigns `self._foo = ...` for shared private state. Every other mixin
  is a pure method container.
- Shared module-level helpers (logger, retry, agent-id) live in
  `_helpers.py`; mixin files import from there, not from each other.
- Domain imports use `from ..` (parent package); sibling imports use
  `from .` (this package). Local imports inside method bodies (e.g.
  `from ..protocol.cfg_action import ...`) are fine — they avoid
  circular-import problems and are already established in the codebase.
- The public `DreameA2CloudClient` is assembled and re-exported from
  `cloud_client/__init__.py`. Keep that re-export — callers do
  `from .cloud_client import DreameA2CloudClient`.
- **Transport never constructs the `CloudState` container (R-31/T2-6).**
  `fetch_full_cloud_state` returns the decoded PARTS (a dict of `CloudState`
  kwargs); the composition lives at the STATE layer via the
  `state.cloud_state.CloudState.from_parts(parts)` factory (P3.8), which
  `coordinator/_cloud_state.py:_refresh_cloud_state` calls — the refresh never
  sees the kwargs (assembly knowledge stays at the state layer). Do NOT re-import
  `..cloud_state` into any `cloud_client/*` module —
  that is an upward transport→state back-edge (it was previously hidden as a
  function-local import; the split closed it). The `tests/audit/test_layer_imports.py`
  gate pins `cloud_client` at layer 2 and `cloud_state` at layer 3.
- Do NOT reintroduce a single `cloud_client.py`. The package is the
  contract.

---

## Rendering structure (load-bearing)

Map rendering lives in `custom_components/dreame_a2_mower/map_render/` as a
**package** (B4b split, 2026-05-21, from a 1283-LOC `map_render.py`). The camera
platform is a thin entry file with domain-grouped siblings.

### map_render/ package

| File | Concern |
|---|---|
| `__init__.py` | Re-export shim — the public surface only |
| `_geometry.py` | Coord transforms (`_cloud_to_px`, `_renderer_to_px`, `_reflect_to_renderer`, `_zone_point_to_px`), `extract_projection`, palette + shared consts (`_DEFAULT_PALETTE`, `_DOCK_RADIUS_PX`, `_OBSTACLE_FILL`, `_OBSTACLE_OUTLINE`) |
| `base_map.py` | `render_base_map` (+ `_composite_polygon`) + mower-icon (`_mower_icon`, `_MOWER_ICON_*`) |
| `main_view.py` | `render_base` + pre-start previews (`_render_pre_start_*`, `STRIPE_WIDTH_MM`) |
| `work_log.py` | `render_work_log` (archived-session render) + `_render_archived_trail` + `_TRAIL_LINE_WIDTH` |
| `stripes.py` | `compute_stripe_overlay` — pre-start stripe overlay (pure pixel-space; P3a) |
| `dotted.py` | `draw_dotted_polygon` — dotted-line polygon helper (pure pixel-space; P3a) |

- `stripes.py` / `dotted.py` are **pure** (no internal import, like
  `_geometry`), folded in from the old root `_render_stripes.py` /
  `_render_dotted.py` (P3a frame untangle, 2026-06-14). `_render_dotted.py`
  (the old shim) was **deleted in P1** — zero importers (T2-7); `dotted.py` is
  the only surviving entry point. `_render_stripes.py` (the old shim) was
  **RETIRED in P3.10** — its one importer now imports `map_render.stripes`
  directly; there is no root re-export shim.
  (The former `direction.py` / `_render_direction.py` track-inference module was
  removed 2026-06-19 — the next-mow stripe angle is read from the authoritative
  cloud field `settings_mowing_direction`, not inferred from the track. See
  `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/specs/2026-06-19-next-direction-stripes-design.md`.)
- **Acyclic imports:** `{_geometry, stripes, dotted}` ← `base_map` ←
  {`main_view`, `work_log`} ← `__init__`. The leaf modules import nothing
  internal; never add a back-edge.
- A module-level constant used by functions landing in ≥2 modules lives in
  `_geometry.py` (e.g. `_OBSTACLE_FILL`/`_OBSTACLE_OUTLINE`, used by both
  `base_map` and `work_log`).
- **Public surface = `__init__.py` re-exports ONLY** the names real callers
  import (`render_base`, `render_base_map`, `render_work_log`,
  `extract_projection`, `BackgroundMode`, `background_mode_for`,
  `_DEFAULT_PALETTE`, `_OBSTACLE_FILL`, `_OBSTACLE_OUTLINE`,
  `_cloud_to_px`, `_renderer_to_px`).
  Keep `from ..map_render import …` working. No "just in case" re-exports.
- `render_work_log` calls its own module-local `_render_archived_trail`
  (moved from the deleted `trail.py` in the live-map rehaul). The live map
  no longer renders a trail server-side — the map card draws it client-side
  from the coordinator's published position stream.
- Do NOT reintroduce a single `map_render.py`. The package is the contract.

### Decode→render zone frame contract (P3 map unification / T2-17, 2026-07-04)

**ONE frame.** `parse_cloud_map` stores every zone's corners as **RAW cloud-frame
mm — verbatim from the cloud** — with `angle` / `shape_type` carried alongside.
NEITHER the per-centroid rotation NOR the midline reflection is baked into any
dataclass. This replaced the earlier three-conventions state (post-rotation
exclusion/spot points, raw mowing paths, raw-bbox decorative — the P3a half-move).

- **Decoder** (`protocol/map/`): `types.py` = dataclasses (unified `Zone(kind=…)`
  replaces `ExclusionZone`/`SpotZone`; `ExclusionZone`/`SpotZone` are back-compat
  aliases of `Zone`; `MowingZone` stays separate — different render frame + id
  space); `parse.py` = `parse_cloud_map` + collectors + `apply_session_geometry`;
  `parts.py` = `parse_cloud_maps`/`join_map_parts`; `geom.py` = rotation +
  `derive_canvas`; `shapes.py` = `DECORATIVE_SHAPE_TYPES` (wire knowledge — the
  protocol→render back-edge T2-3 is dead: `protocol/map/*` imports NOTHING from
  `map_render`). Cite `inventory.yaml` § shapeType.
- **The `points`/`points_m` twin is DEAD.** The metre-frame edit polygon is a
  DERIVATION — `zone_render_points(zone)/1000` — computed at the `editable_objects`
  boundary in `camera/map.py`. `editable_objects` output is byte-identical to the
  old stored `points_m`.
- **Render** (`map_render/`): the app's `-angle` per-centroid rotation is applied
  at DRAW time by `_geometry.zone_render_points` (decorative → raw bbox corners,
  identity), then `_zone_point_to_px` applies the midline reflection + pixel-grid
  divide. `base_map.py` / `main_view.py` rotate raw corners before projecting.
  `_geometry.build_projection(map_data) → MapProjection` is the **render-side
  Projection builder** (T2-17) that re-derives bbox / reflect / dock / canvas from
  the raw map (rotating the zones); `extract_projection` echoes MapData's canonical
  cached canvas so the card projection is byte-exact to the rendered PNG.
- **STRUCTURAL TRAP resolution:** the canvas (`bx1..by2`/`width_px`/`height_px`/
  `cloud_*_reflect`/`dock_xy`/`boundary_polygon`) is derived by the pure
  `geom.derive_canvas` (bbox expanded over the ROTATED zone corners) and cached on
  `MapData`; `build_projection` recomputes the identical values from the raw map.
  (Deviation from the literal P3-Task-3 brief, which put that derivation lazily in
  `map_render`: keeping the canvas cached on `MapData` avoids forcing the entity/
  camera/session/test layers to import `map_render` merely to learn canvas size —
  the p3a-transform-spec "minimal honest untangle" clause. The load-bearing goals
  — one raw frame in the dataclasses, no back-edge, one `Zone(kind)`, `points_m`
  derived — are all met.)
- `apply_session_geometry` stores raw cloud-frame mm (metres ×1000, angle `None`).
- Output is **pixel-identical** to the pre-move render — the golden gate
  (`tests/integration/test_map_render_golden.py`) pins it un-re-blessed; the
  Python↔JS frame parity (`tests/www/test_projection_parity.py`) pins the unified
  Zone's edit-frame ↔ render-frame lock. Don't re-bake rotation/reflection into the
  decoder; don't restore the `points_m` stored twin.

### camera package

The camera entity layer is a **package** (`camera/`, Phase 3c, 2026-06-14). The
package `__init__.py` *is* the thin HA platform entry (`async_setup_entry` + the
seven `hass.http.register_view` calls) — HA imports
`custom_components.dreame_a2_mower.camera` by name, so a sibling `camera.py`
module cannot coexist with the package; the entry lives in `camera/__init__.py`.
Entity classes live in domain-grouped modules — `camera/map.py`,
`camera/lidar.py`, `camera/wifi.py`, `camera/photos.py` — and the
`HomeAssistantView` HTTP endpoints in `camera/views.py`.

`_camera_lidar.py`, `_camera_views.py`, and `_camera_wifi.py` were **deleted in
P1** — zero importers (T2-7); import `camera.lidar`, `camera.views`, and
`camera.wifi` directly. The old flat root shims `_camera_map.py` and
`_camera_photos.py` were **RETIRED in P3.10** (all importers rewritten to the
canonical `camera.map` / `camera.photos` paths). Import from `camera.<module>`
directly; there is no root re-export shim.

### wifi/ package

The WiFi-heatmap support layer is a **package** (`wifi/`, Phase 3c, 2026-06-14):
`wifi/archive_store.py` (disk-backed archive `WifiArchiveStore` / `WifiArchiveEntry`),
`wifi/match.py` (heatmap→session fingerprint matcher), `wifi/map_render.py`
(heatmap→PNG renderer). These are NOT entity classes — no HA platform / audit /
inventory interaction.

The old root shims (`wifi_archive_store.py`, `wifi_match.py`, `wifi_map_render.py`)
were **RETIRED in P3.10** — all importers (coordinator, camera, domain, tests)
rewritten to the canonical `wifi.<module>` paths (`_rssi_to_rgb` lives on
`wifi.map_render`). Import from `wifi.<module>` directly; there are no root
re-export shims.

### entities/ package (sensor / switch / select)

The sensor / switch / select entity-class layer is a **package** (`entities/`,
Phase 3c, 2026-06-14) with per-platform subdirs:

| Module | From |
|---|---|
| `entities/sensor/{device,map,session,base}.py` | `sensor_device`, `sensor_map`, `sensor_session`, `_sensor_base` |
| `entities/switch/{global_,map,base}.py` | `switch_global`, `switch_map`, `_switch_base` |
| `entities/select/{global_,map_settings,base}.py` | `select_global`, `select_map_settings`, `_select_base` |

(`global_` avoids the `global` keyword.) The thin HA platform loaders
(`sensor.py`, `switch.py`, `select.py`) STAY at the package root — they're loaded
by HA by name — and import the classes/description tables from `entities/…`. The
intra-subpackage base import is a sibling (`from .base import …`); everything
else reaches the root package with three dots (`from ...const import …`,
`from ...wifi.archive_store import …`).

The FAT single-platform files (`number.py`, `binary_sensor.py`, `button.py`,
`time.py`, `device_tracker.py`, `lawn_mower.py`, `calendar.py`, `event.py`) ARE
the platform entry — they stay at root (out of scope; moving inline classes out
is more churn than value).

`sensor_session.py`, `_sensor_base.py`, and `_select_base.py` were **deleted in
P1** — zero importers (T2-7). The old flat root shims (`sensor_device.py`,
`sensor_map.py`, `switch_global.py`, `switch_map.py`, `_switch_base.py`,
`select_global.py`, `select_map_settings.py`) were **RETIRED in P3.10** — all
importers (tests + entry files) rewritten to the canonical
`entities.<platform>.<module>` paths. Import from `entities.<platform>.<module>`
directly (the underscore helpers `_active_fault_text` / `_mpos_value` /
`_mpos_attrs` live on `entities.sensor.device`); there are no root re-export
shims.

**Two CI lockstep targets** track these source paths and must be updated on any
further move:
- `tools/inventory/entity_inventory_audit.py` discovers entity classes by walking
  the package with `CC.rglob("*.py")` (recurses subpackages — was a root-only
  `glob` before Phase 3c). The coverage gate goes stale if a class can't be found.
- `tools/entity_source_inventory.py` `ENTITY_SOURCE_FILES` lists the entity
  source files by relative path for the state-machine audit walker
  (`state_machine_audit_discover.py` resolves them as `CCDIR / fname`). Update the
  paths here when an entity source file moves.

---

## services/ package (load-bearing)

The HA service layer is a **package** (`services/`, refactor-v2 P3.8, from a
1,134-LOC `services.py`; T2-11). HA/`__init__.py` import `services` by name, so
the package `__init__.py` *is* the service surface: registration
(`async_register_services` / `async_unregister_services` /
`async_reconcile_debug_services`), the ~30 production handlers, the `SERVICE_*`
name constants, the `@service_handler` coordinator-resolution decorator, and
`_coordinator_from_call`. The full public/test symbol surface
(`services._handle_*`, `services.SERVICE_*`, `services._coordinator_from_call`)
resolves through `__init__.py` unchanged.

| Module | Concern |
|---|---|
| `services/__init__.py` | Registration + all production handlers + `service_handler` + `SERVICE_*` constants |
| `services/debug.py` | Dev-only diagnostics: `dump_map_diagnostics`, `discover_cloud_api` + pure summariser helpers (`_group_keys_by_prefix` / `_summarise_value` / `_summarise_family`). The **experimental-gate seam** — registered ONLY when `_debug_services_enabled(entry)`. |

### Rules

- **`debug.py` bodies are plain `async def _(coordinator, call)`** — the
  `@service_handler` wrapper (which resolves the coordinator + honours a
  `services._coordinator_from_call` monkeypatch) is applied in `__init__.py`
  (`_handle_dump_map_diagnostics = service_handler(debug.dump_map_diagnostics)`).
  This keeps `debug.py` free of any import back into the package `__init__`
  (no circular import) and keeps the monkeypatch target on the package module.
- The debug/experimental GATE mechanism itself is P4; P3.8 only SEPARATED the
  tooling behind the existing `debug_services` option so the production surface
  no longer carries ~250 LOC of dev machinery.
- Being a package inside `dreame_a2_mower`, sibling imports use `..` (e.g.
  `from ..const import DOMAIN`), NOT `.` — the module→package conversion moved
  every single-dot sibling import down one level.
- Do NOT reintroduce a single `services.py`. The package is the contract.

---

## Protocol decoder naming (convention)

In `protocol/`, decoder entry points follow a name convention by INPUT SOURCE:

- `decode_*` — decodes a **device/MQTT wire payload** into a dataclass. This
  covers raw binary frames (`decode_s1p1`, `decode_s1p4`, `decode_pcd`,
  `decode_pcd_header` — all take `bytes`) and MQTT property values
  (`decode_s2p51` — takes the parsed property payload, a dict/list).
- `parse_*` — parses a **cloud JSON / batch** structure (dict/str → dataclass).
  Examples: `parse_session_summary`, `parse_schedule_batch`, `parse_settings_batch`.

When adding a new decoder, pick the prefix by source: device/MQTT wire →
`decode_*`, cloud JSON → `parse_*`. (PCD was renamed from `parse_pcd*` to
`decode_pcd*` in B2a to fit this rule.)

---

## Session replay data model (load-bearing)

### The single trail storage: `track`

Per-point `track` is the **ONLY** trail storage in the archive JSON.  On disk it is a list of **ROWS** — `[t, x_m, y_m, area_m2, heading_deg, task_state, role]` (see `_inject_live_map_into_raw_dict`).  The in-memory/derive working shape is the matching DICT `{t, x_m, y_m, area_m2, heading_deg, task_state, role}`; convert at the archive→working boundary with `live_map.state.track_row_to_dict` (or `domain/session/replay.py:_track_as_dicts`, which is row/dict tolerant).  `derive_render_legs` / `compute_track_distances` / `classify_track` all consume the DICT shape — passing raw rows to them raises `TypeError`.  Legs are a render-time derivation — never stored; call `domain/session/replay.py:derive_render_legs(track_dicts)`.

### Role classification

`role` is set inline at append time in `live_map/state.py:append_point` by the area **delta**: if the cumulative mowed-area counter GREW since the previous point (`area_m2 - prev_area > 0`) → `"mowing"`, else `"traversal"`.  (`area_m2` is cumulative, so the delta — not the absolute value — is what marks blades-down-on-new-grass.)  **Area-delta is the sole authority.**  At finalize, `domain/session/finalize.py:finalize_classify_raw_dict` → `live_map/classify.py:classify_track` only **smooths** isolated single-point role anomalies (flip a lone point to match both neighbours).

Do NOT re-add a cloud-coverage "rescue" (upgrade a traversal point to mowing because it's near the cloud `track_segments` path).  It was tried and removed 2026-05-28: on a full-lawn mow the cloud's blades-down segments blanket the whole lawn, so a cross-area traversal driving over already-mowed grass sits on the cloud path and gets falsely greened (measured: all 478 genuine traversal points on a 2613-pt mow flipped).  Only area-delta separates "mowing now" from "driving over what I mowed earlier".  `cloud_track` is still stored verbatim (reference only), not used to classify.

The same classify (smoothing) runs on the FINALIZE_INCOMPLETE path too (after `_inject_live_map_into_raw_dict`, before archive write).

### `cloud_track`

`cloud_track` is stored verbatim from the cloud session summary's `trajectory.track_segments`.  Capture continues until the mower is docked (charging state) — see `domain/session/finalize.py:wait_for_dock_return` (coord delegator `_wait_for_dock_return`) for the lifecycle.

### Removed for good

The following keys and methods were removed in the 2026-05-28 session-replay rewrite and must **not** be re-added:

- Archive keys: `_local_legs`, `_legs_meta`, `_mowing_legs`, `_traversal_legs`
- Live-map API: `LiveMapState.set_mowing()`, leg accumulator arrays

Old archives that pre-date the rewrite must be rebuilt via `tools/session/rebuild_session.py` to get a per-point `track`.

### Reference

- Spec: `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/specs/2026-05-27-session-replay-rewrite-design.md`
- Plan: `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/superpowers/plans/2026-05-28-session-replay-rewrite.md`

---

## Documentation canonicity & lifecycle (load-bearing)

In-tree `docs/` is **current truth ONLY**. This is a structural rule, not a
style preference: every grep / Explore / file read in a session is scoped to
the working tree, so anything in-tree is retrieved as equally-current "truth."
Leaving point-in-time or superseded docs in-tree is exactly what regenerates
debunked claims (the recurring failure this repo has had — see the s2p2=28
incident). The fix is *location*, not editing stale docs to agree.

### Tiers

1. **Source of truth** — `inventory.yaml`, `entity-inventory.yaml`, the
   generated `g2408-canonical.md`, `docs/research/knowledge-gaps.md`.
2. **Current reference** (in-tree) — docs that describe the *current* state and
   are maintained: `capture-procedures`,
   `cloud-map-geometry`, `cloud-write-reference`,
   `TODO.md` (the single open-work list — fold standalone `*-todo` research docs
   into it, don't keep parallel ones), `data-policy` / `events` / `lidar` /
   `multi-map` / `observability`, and this file.
3. **In-tree dated evidence / context** — the research **journal**
   (`g2408-research-journal.md`) and `wire-captures/*.md`. These STAY in-tree
   because the Tier-2 docs cite them as evidence, but they are epistemically
   **non-authoritative**: each carries a "read for context, not current truth —
   `inventory.yaml` wins" banner, and a claim being in them does NOT make it
   current. Do not treat a journal/capture line as truth without checking the
   inventory.
4. **Historical / process** — lives **OUT of the git tree** at
   `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/`, mirroring the old
   `docs/`-relative path (a moved file is at
   `OLD/ha-dreame-a2-mower-docs/<original-path-under-docs>`; git history also
   preserves it). This is: all `docs/superpowers/` (specs, plans, helpers,
   handoffs), `docs/research/historical/` (pre-restructure raw + retired
   matrices), and completed logs (`DONE.md`).

### The lifecycle rule

- **Specs & plans / handoffs** — historical the moment the work ships. Move the
  spec+plan to `OLD/…` as part of finishing the branch (the *finishing-a-
  development-branch* wrap-up). Target state: **zero `docs/superpowers/` in-tree.**
- **Completed logs / retired docs** — move to `OLD/…` once superseded.
- **Capture `FINDING-*.md` docs (often from the MITM rig / another server) —
  FOLD-then-ARCHIVE.** Fully incorporate each finding's wire facts into
  `inventory.yaml` / `entity-inventory.yaml` (and the integration), THEN move the
  doc out of the live tree (to `OLD/` or leave in the capture dir). The reason the
  findings live out-of-tree is deliberate: earlier findings got debunked by later
  ones, and stale claims resurfaced through grep/sed over in-tree history. So the
  tree must hold only current truth, never old-effort docs that will never be
  updated even after they're debunked. **Before archiving a capture's findings,
  run `tools/inventory/findings_fold_check.py`** — it flags any ACTIVE finding
  whose wire identifiers (endpoints / `o=N` / `t=KEY` / `sNpM`) are not yet in the
  inventory SoT (the getDeiviceFile/OTA drift guard: code shipped ahead of the
  SoT). It never scans `OLD/`. Mark an intentionally-unfolded finding with a
  `FOLD-CHECK: exempt` or `Status: open`/`[UNVERIFIED]` line. (CI's
  inventory-touch-gate also now watches the endpoint-defining `cloud_client/_fetchers.py`
  + `_file_bridge.py`, so a new endpoint can't ship without an inventory row.)
- **The journal & wire-captures STAY** in-tree (Tier 3) — they are cited
  evidence — but their facts must be promoted into `inventory.yaml` (the SoT),
  and they keep their non-authoritative banner. Don't grow a NEW in-tree
  narrative/history doc; append to the journal.
- **Provenance & breadcrumbs** — code comments and docs that cite a moved spec
  by its old `docs/superpowers/...` path resolve unchanged under
  `OLD/ha-dreame-a2-mower-docs/superpowers/...` (same relative path). The design
  rationale for shipped work otherwise lives in the code + this file + the
  inventory. Cite the OLD path; never copy a moved doc back in-tree.

Never resolve a documentation question by re-importing a historical doc into the
tree. If something historical is still needed, distill the *current* fact into a
Tier-1/Tier-2 doc and leave the original in `OLD/`.

## Related files

- `custom_components/dreame_a2_mower/inventory.yaml` — wire/protocol truth.
- `custom_components/dreame_a2_mower/entity-inventory.yaml` — integration entity truth.
- `docs/research/inventory/README.md` — schema reference for inventory.yaml.
- `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/` — out-of-tree
  historical/process docs (specs, plans, handoffs, pre-restructure raw, completed
  logs), mirroring the old `docs/`-relative path. Read-only archive.
- `tools/inventory/inventory_audit.py` — CI consistency check; run locally before
  shipping a fact-heavy change.
- `.github/workflows/ci.yml` — `inventory-touch-gate` job blocks PRs
  that change protocol or entity definitions without updating the
  corresponding inventory file.
