# Refactor v2 — Target Architecture (Act II)

**Status:** APPROVED by user 2026-07-02 (Act II deliverable of the full-refactor-v2 program).
**Inputs:** spec (`2026-07-02-full-refactor-v2-design.md` § Act II principles) +
`findings/findings-register.md` (R-ids) + track files (T-ids). Coverage appendix at end.

## 1. Layer model

Six layers, imports point strictly downward. A module may import same-layer siblings
and anything below; never above.

```
6  presentation   render/, camera/, live_map render, dashboard/ (strategy+cards), diagnostics view
5  entities       descriptor-driven platforms (sensor/select/switch/…), lawn_mower, services (HA API)
4  domain         session/, writes/, media/, wifi/, lidar/, notifications/, ota, device_sync, ingress
3  state          MowerState (split containers), StateSnapshot, MowerStateMachine, CloudState, apply
2  transport      mqtt, cloud RPC/OSS/file-bridge, fetch families (return protocol types, not state)
1  protocol       pure decode/encode; zero HA imports; zero upward imports
0  foundation     const.py (leaf), observability/, inventory loader
```

The coordinator survives as a **thin composition root** (single file, target ≤400 LOC):
constructs transports + services, owns the spine (`data` [MowerState], `cloud_state`,
`state_machine`, `live_map`), and composes `_async_update_data` from per-service refresh
slices. Everything else the 9,804-LOC coordinator package does today (R-8/T2-1) moves
into layer-4 services that own their attrs — this is how the attr-bundling verdict
(T2-16) is realized: the god-object is removed, not decorated.

## 2. Target package tree

Names in **bold** are new/moved; unmarked = stays. Every module ≤400 LOC (spec cap);
recorded exceptions: `state/machine.py` (cohesive SM, T2 autopsy #11).

```
custom_components/dreame_a2_mower/
├─ const.py                      # leaf again: R-30 inversion (event consts live here;
│                                #   mower.error_codes imports const, not vice versa)
├─ config_flow.py                # + validation/reauth/region/device-select (R-2, R-43/44)
├─ diagnostics.py                # redact-by-allowlist rewrite (R-3)
├─ __init__.py                   # setup/unload; all timers/tasks cancelled (R-40)
├─ protocol/
│  ├─ heartbeat.py telemetry.py config_s2p51.py session_summary.py message_record.py
│  ├─ mode_enum.py cfg_action.py api_log.py photo_category.py
│  ├─ **property_mapping.py**    # from mower/ — wire knowledge
│  ├─ **settings.py m_path.py schedule.py**  # now own their output dataclasses (R-29/T2-4)
│  └─ **map/** types.py parse.py parts.py geom.py **shapes.py**
│                                # map_decoder split (T2 autopsy #8); ONE frame convention:
│                                #   all geometry raw cloud-mm + angle/shape_type verbatim;
│                                #   shapes.py owns DECORATIVE_SHAPE_TYPES (kills R-10/T2-3);
│                                #   one Zone(kind=…) replaces ExclusionZone/SpotZone/… (T2-17)
├─ transport/
│  ├─ **mqtt.py**                # mqtt_client.py moved; rc=5 auth callback WIRED (R-41)
│  └─ **cloud/** rpc.py oss.py file_bridge.py helpers.py
│     ├─ **fetch_state.py fetch_device.py fetch_messages.py fetch_media.py fetch_ota.py**
│     │                          # _fetchers split (T2 autopsy #2); return protocol types;
│     │                          #   CloudState is NOT built here (R-29)
│     └─ (set_cfg/set_pre/trigger_firmware_update move UP to domain/writes — R-31/T2-6)
├─ state/
│  ├─ **containers.py**          # the MowerState split (T2-15 verdict): frozen sub-dataclasses
│  │                             #   Identity, Settings, Telemetry, Consumables, Connectivity,
│  │                             #   SessionRefs, OtaState, Messages — seams = wire-source
│  │                             #   domains already visible in property_mapping/cfg_to_state
│  ├─ **mower_state.py**         # MowerState = composition of containers; one name per fact
│  ├─ **snapshot.py machine.py** # StateSnapshot + MowerStateMachine (from mower/) — the SM
│  │                             #   snapshot remains the behavioral SoT; the decode-staging
│  │                             #   relationship is PRESERVED (2026-06-15 3d-revisit ruling
│  │                             #   stands; no ingestion-funnel rejudging)
│  ├─ **cloud_state.py**         # CloudState composed here by domain, not transport
│  └─ **apply.py**               # pure property/CFG→state application (from coordinator/
│                                #   _property_apply.py, header purged — R-9/T2-2)
├─ domain/
│  ├─ **ingress.py**             # MQTT funnel: thin routing (paho thread = pure decode only,
│  │                             #   preserved from P1.3) → loop-side apply → SM → services;
│  │                             #   base-state read moves loop-side (R-39/T3-7)
│  ├─ **session/** finalize.py persistence.py replay.py lifecycle_events.py signals.py
│  │                             # from _session/_mqtt_handlers/_lidar_oss §1 (autopsies #3/#4/#10);
│  │                             #   finalize keeps the latch + corpus-validated ordering VERBATIM;
│  │                             #   dock-wait single-flight (R-38); interleaving tests first (R-17)
│  ├─ **writes/** service.py schedule.py settings.py tasks.py map_edit.py
│  │                             # THE one write path (spec): every mutator returns WriteResult;
│  │                             #   absorbs set_cfg/set_pre/OTA-trigger + _writes.py families;
│  │                             #   bool returns eliminated (R-35/T2-6); optimistic overlays go
│  │                             #   through async_set_updated_data (R-37)
│  ├─ **media/** gallery.py      # photo/video gallery + OSS session assembly (autopsy #10)
│  ├─ **wifi/** service.py       # wifi archive refresh + body cache (consolidated)
│  ├─ **lidar/** service.py      # lidar archive + 3dmap backfill
│  ├─ **notifications.py faults.py ota.py device_sync.py gps.py**
│  │                             # gps: transient-failure keeps last fix (R-42)
│  └─ archive/                   # session/photos/videos/lidar disk stores (already clean leaves)
├─ **coordinator.py**            # the thin composition root described in §1
├─ live_map/                     # trail state (state-ish leaf, stays)
├─ entities/                     # layer 5 — see §4
├─ camera/ render/               # layer 6; render/ = map_render (acyclic, keeps structure)
│                                #   + Projection builder owning bbox/reflect derivation (T2-17)
├─ **dashboard/**                # layer 6 — see §5; www/ cards live here
└─ services/                     # HA services API: registration + per-domain handler modules
   └─ **debug.py**               # dump/discover tooling behind the experimental gate (R-52)
```

Deletions (no successor): 21 root shims (7 now, 10 with contract-test rewrite, 4 after
the 19 prod import fixes — R-34/T2-7/8), `fetch_wifi_map`+`REQUEST_WIFI_MAP`+`fetch_locn`
(R-22/23/61), single-map fallback (R-24), op=10/12 buttons+services (R-28),
`session_card.py` (contents → domain/session/replay.py — fixes the misnomer T2-13 and
publishes `error_samples` per R-7).

## 3. State design (one container per fact)

- `MowerState` becomes a composition of 8 frozen sub-containers split along wire-source
  seams (T2-15). Each **domain service is the sole writer of its container**; the apply
  funnel (`state/apply.py` + ingress) does grouped per-slot applies exactly as
  `_apply_s1p4/_apply_s2p51/…` already do. No cross-domain two-level `replace` at call
  sites — that was the old counter-evidence, and it dissolves structurally.
- `StateSnapshot`/`MowerStateMachine` unchanged in role (behavioral SoT; freshness map).
  battery/wifi/position staging fields stay per the 2026-06-15 ruling — the corpus-replay
  harness pins their equivalence through the split.
- `CloudState` remains the frozen cloud aggregate, built by a layer-4 refresh service
  from transport-returned protocol types.
- Archive/persistence formats may change with the container split (user ruling: allowed,
  feature-complete); `rebuild_session.py` + raw corpus is the backstop; deploy-order rule
  from the index-backfill lesson applies.

## 4. Entity layer

- **Descriptor-first:** platforms are tables + a small number of generic classes; track-5's
  verdict table (the draft v2 canonical entity table in `findings/track-5-entity-surface.md`)
  is adopted as amended by synthesis: ~118 keep (35 with metadata fixes: entity_category,
  device_class/unit, state_class — R-50), 14 renames, 4 demotes, 13 experimental-gated,
  10 entity + 6 service deletions. Bespoke sensor classes in `entities/sensor/device.py`
  are first converted to descriptors where track 5 says so, THEN the file splits
  (autopsy #1 order).
- **Descriptor schema gains:** `experimental: Tier|None` (see §6), `availability_source`
  (exists), `control_mode` (exists). Value/attr derivation helpers move to the owning
  domain service — entities read services, never `getattr(coordinator, "_private")`
  (the 37 string-getattr sites are burned down as the P3 pre-step per T2-16).
- **Naming:** entity_id derives from the name slug (known gotcha) — the rename set is
  applied in one P4 pass with a live-registry cleanup script; the `floor_0_outside_`
  recurrence class (R-11) is root-caused (device-name prefix timing) before any rename lands.
- **services.yaml** surface per track-5 verdicts; handlers become thin calls into
  domain/writes with `raise_for_write_result` everywhere (R-35).

## 5. Dashboard & cards (shippable product)

- **One Lovelace resource:** `dashboard/strategy.js` — an ES module that (a) imports and
  registers every bundled card (collapses 7 manual resource entries; fresh-install works
  — T6 feasibility), (b) defines the `dreame-a2-mower` **dashboard strategy** generating
  views from the entity registry via stable `unique_id` suffix grouping (kills the
  dead-entity-ref class: R-11/12/13/14).
- **Generator inputs:** entity registry + a small machine-readable card-grouping manifest
  (owned by `dashboard/`, CI-checked against entity-inventory) + CONTROL_MODES.
  Per-map views appear per registered map device. Developer-only content is gated behind
  the experimental option (R-55).
- **Degrade paths (user-approved OQ-4):** plotly session charts render only if
  plotly-graph-card is installed (registry probe), calendar view falls back to the native
  calendar card.
- **Helpers eliminated:** backend stops reading dashboard-installed `input_boolean`s
  (R-15/T6-18) — those toggles become integration switches/options.
- **Card hygiene pass (R-54):** shared core module for banner/registration/lightbox,
  guarded `customElements.define`, `schema_version` on all card-consumed attrs, no
  hardcoded entity_ids (cards take entity via config from the strategy), CARD_VERSION
  sync fixed in release.sh (R-53).
- The SCP-deployed YAML and its .baks retire (R-48); the live instance switches to the
  strategy dashboard in P5.

## 6. Experimental gate

One config-entry option `experimental_features` (default off), replacing `debug_services`
(R-52). Mechanism: descriptor `experimental` tier → entities not created when off;
gated services raise. Population (track-5 T5-9, tiers per spec § Experimental gate):
Tier-speculative: MPOS pair, 5 raw slot probes, novel_observations,
api_endpoints_supported, create_patrol_point service. Tier-wire-verified-client-unexercised:
OTA install action (promotion path: byte-diff vs the app OTA MITM transcript, then next
firmware), active-map select. Tier-fail-closed: obstacle-photo camera (Track B signer).
Correction adopted: patrol o=223 points are CONFIRMED (inventory) — NOT gated;
the spec's example line is amended when this doc is committed.

## 7. Contract tests (rewritten to the new surface, P0-style)

1. Corpus-replay goldens (exists; excerpt set expanding per OQ-3).
2. Camera map attrs `schema_version: 2` — projection, point_seq, track_snapshot cap.
3. Replay/picked-session attrs — **including `error_samples`** (R-7) and the shapes
   track-7 found unpinned (calibration_points, last_known_point — R-59).
4. Map-editor `editable_objects` (single-frame geometry per §2 protocol/map).
5. WriteResult surfacing: every service/entity write path raises on rejection (R-35).
6. Strategy output: generated dashboard references only registry-present entities.
7. Python↔JS frame parity (exists) extended to the unified Zone types.
8. Property↔fake shape census as a permanent gate (T7-2) + coordinator built via the
   real `__init__` factory in tests (R-16).

## 8. Register coverage appendix

HIGH: R-1 done (tree+history). R-2/R-3 → config_flow/diagnostics rewrites (§2, P6).
R-4 → transport/mqtt + ingress fix + T7-2 gate (P2). R-5 → coordinator.py first-refresh
contract + 0-map tests (P2). R-6 → entity fix/delete per track-5 (P2). R-7 → session/replay
publishes error_samples + contract #3 (P2). R-8 → §1/§2 service extraction (P3).
R-9 → pyflakes purge + F401 CI gate (P1). R-10 → protocol/map/shapes.py (P3).
R-11 → §4 naming root-cause + registry cleanup (P4). R-12 → track-5 verdict (P4).
R-13/14/15 → §5 strategy + backend helper removal (P5). R-16 → test factory (P3 pre-step).
R-17/18 → session interleaving + lifecycle tests (P2, before P3 touches session).
R-19/20 done (archived doc).
MED (structural): R-29→§2 protocol; R-30→const inversion; R-31→§2 transport/writes;
R-32→autopsy splits (§2); R-33 adopted (§2/§3); R-34→shim schedule (§2 deletions);
R-56→R-16 factory + lint gates.
MED (correctness): R-35/36/37/38/39/40/41/42 → §2 annotations (P2). R-53 → release.sh (P2).
MED (surface/docs): R-21..R-28, R-47, R-49..R-52, R-46 → P1/P4 batches per register.
R-43/44/45, R-60 → P6. R-48, R-54, R-55 → P5. R-57/58/59 → P1/P2/P0-followup.
LOW batches R-61..R-67 ride their phase hosts. OPEN: R-45 regions (EU-verified labeling,
user-approved OQ-2).

## 9. Phase mapping (feeds the Act III per-phase plans)

- **P1 dead-code/docs purge:** R-9 imports, 7 dead shims, R-21..R-27, R-47, R-57, R-61,
  R-62 junk; debunked-register v1 lands in gated docs; § s6.2 wire-shape fold into inventory.
- **P2 correctness:** R-4..R-7, R-17/18 (tests-first), R-35..R-42, R-53, R-58, R-63, R-66.
- **P3 structure:** test factory + getattr burn-down → protocol/map unification (T2-17) →
  transport split → state containers (T2-15) → domain-service extraction (T2-1 dissolution)
  → shim retirement + 59 test-file import rewrite. Corpus-replay `--diff` green at every step.
- **P4 entity surface:** track-5 table (renames/deletes/demotes/metadata), experimental
  gate, translation rebuild (R-46), registry cleanup, contract tests #2-#5.
- **P5 dashboard:** strategy + card hygiene + helper elimination + live cutover.
- **P6 release:** config_flow validation/reauth/device-select, diagnostics redaction,
  model gate, region labeling, HACS hygiene (R-60), README, v2.0.0.
