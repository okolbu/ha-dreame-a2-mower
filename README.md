# Dreame A2 Mower — Home Assistant Integration

A Home Assistant integration for the **Dreame A2** robotic lawn mower
(model `dreame.mower.g2408`). Written from scratch for the A2 — **not a
fork** of any upstream vacuum or mower project.

## Status

🟢 **Approaching a v2.0.0 public release.** Feature-complete for a single
`dreame.mower.g2408` on one Dreame cloud account, and in daily use against
a live mower. Distributed as a HACS custom repository (see Installation)
while protocol coverage and live validation continue — check the
[Releases page](https://github.com/okolbu/ha-dreame-a2-mower/releases) for
the current published version. Built greenfield for the A2 — the original
F1–F7 phase rollout plans are maintainer-internal history (not distributed
with this repo); since then the coordinator, cloud client, entity
platforms, and map renderer have each been decomposed into focused
packages and multi-map support was added.

### Region status

Developed and verified against the **EU** Dreame cloud region
(`country: eu` in the config flow). The other regions the cloud API
accepts — `us`, `cn`, `ru`, `i2`, `sg`, `de` — are **best-effort**: the
same login / device-discovery / cloud-RPC code path runs against them,
but none of it has been exercised against those regions' actual cloud
endpoints, and there's no region gating in the code to stop you trying.
If you're on a non-EU account, please
[open an issue](https://github.com/okolbu/ha-dreame-a2-mower/issues) and
report whether it worked — that's how this list grows.

## Features

### Live state
- **Lawn mower entity** with `start_mowing` / `pause` / `dock` actions.
- **Live map camera** rendered server-side from the cloud's map JSON
  + s1.4 telemetry trail. Lawn boundary, mowing zones (translucent,
  per-zone stripe colours so adjacent zones are distinguishable),
  exclusion / no-obstacle / spot zones, dock pin, GPS-anchored.
- **Battery, charging status, error code, obstacle flag, rain
  protection, positioning failed, battery temp low** as native HA
  entities.
- **Localized fault text** — the error-code sensor resolves its active
  fault to human-readable text in your HA language, sourced from the
  Dreame app's own fault catalog (`mower/data/fault_catalog.json`,
  `[apk:g2408-plugin-ext1423]`). Extra attributes carry `error_detail`
  (localized), `fault_names`, and `fault_categories`; the s1.1
  heartbeat flag sensors carry the same catalog `fault_text` / `tier` /
  `detail` attributes.
- **Position** as `device_tracker` — absolute GPS lat/lon read from the
  cloud `location/getRecords` history (`_refresh_gps`, 60 s) — plus
  `sensor.position_x_m` / `_y_m` / `_north_m` / `_east_m` derived
  from s1.4 + station-bearing rotation, and an `MPOS` diagnostic sensor
  (`{x, y, yaw}`, raw/untransformed) with an on-demand Refresh MPOS button.

### Control surface
- `action_mode` select (`all_areas` / `edge` / `zone` / `spot`).
- **Resume** and **Cancel dock return** buttons (in addition to the
  mower entity's `start_mowing` / `pause` / `dock`).
- Services: `set_active_selection`, `mow_zone`, `mow_edge`, `mow_spot`,
  `suppress_fault`, `set_schedule_plans`, `set_schedule_enabled`,
  `replay_session`, `show_lidar_fullscreen`, `start_point_patrol`,
  `start_edge_patrol`, `set_patrol_point_config`. (Parameterless 1:1
  button/switch duplicates — `recharge`, `find_bot`, `set_child_lock`,
  `finalize_session`, `refresh_cloud_state` — plus the one-time
  migration helper `move_lidar_scan` were removed; press the
  corresponding button/switch entity instead.)
- All routed through the cloud RPC `s2.50 aiid=50` envelope (the only
  command path that works on g2408 — direct `action()` returns 80001).

### Firmware updates
- **Device-firmware `update` entity** ("Mower firmware") — surfaces the
  installed vs latest firmware version and an Install button. The install
  path is build-correct but `[UNVERIFIED]` against a real pending update
  (the device was already on the latest build when the entity shipped);
  it stays available for the next firmware drop.
- **`sensor.dreame_a2_mower_ota_state`** /
  **`sensor.dreame_a2_mower_ota_progress`** — live OTA status + percent
  during an update (diagnostic).
- **Update Station Location** button (routed `o=19`) re-syncs the charging
  station's stored position.

### AI obstacle capture

When the mower's AI obstacle recognition flags something mid-mow, the
integration captures it on two independent tracks:

- **Track A — live markers (shipped, render-verified).** A mow-gated
  poller (`_refresh_aiobs`, every 2 min while a session is active) fetches
  the cloud's live AIOBS obstacle-marker list, writes a durable
  marker-metadata log, and paints the markers as translucent blue polygons
  on the live map during the mow. A diagnostic
  **`sensor.dreame_a2_mower_obstacle_markers`** exposes the current count
  plus per-marker metadata (confidence, class, detection epoch). The
  marker class/confidence are the AI's own guess — **not** a reliable
  person signal.
- **Track B — obstacle photos (shipped fail-closed, signer `[UNVERIFIED]`).**
  When a marker has an associated photo, the coordinator attempts to
  download it via the cloud `getDeiviceFile` bridge and archives it as an
  ephemeral obstacle photo;
  **`camera.dreame_a2_mower_obstacle_photo`** serves the most recent one.
  The request signer was reconstructed from the native library but does
  **not** yet reproduce a golden signature, so the download **fails
  closed** — the camera stays empty until the backend returns a photo, at
  which point the path self-verifies. Capture retries while a marker is
  live so a transient `backend_unavailable` doesn't drop the photo.

### Schedule editing
- Edit mowing schedules from HA — the bundled
  **schedule card** (`dreame-a2-schedule-card.js`) drives the
  `set_schedule_plans` service, which writes the schedule back to the
  mower over the chunked `SCHD*V3` transport (decoded + byte-verified).
- **Enable / disable the active schedule season** via the
  `set_schedule_enabled` service (`slot_id` + `enabled`). The two slots are
  the mutually-exclusive seasons the app exposes — slot 0 = *Spr & Sum*,
  slot 1 = *Aut & Win* — so enabling one disables the other; disabling the
  active one leaves no schedule running. The per-slot enabled state is
  exposed on the `schedule_count` sensor's attributes. Blocked while a task
  is active.

### Map editor
- Draw and manage map objects from HA via services:
  `create_no_go_zone`, `create_ignore_obstacle`, `create_mow_shape`,
  `rename_zone`, `delete_map_object`, `split_zone`, `merge_zones` —
  all routed as map-edit transactions (`o=200` select → `o=204` begin →
  mutations → `o=201` commit). A bundled map-editor card
  (`dreame-map-editor-card.js`) surfaces them on the dashboard.
- Place and move named points: `create_spot` (spot-mow area, `o=214`),
  `create_maintenance_point` (`o=224`), and `create_patrol_point`
  (cruise point, `o=223`). `set_patrol_point_config` sets a patrol
  point's cycle count + auto-capture (live-verified write).

### Photo & video gallery
- **`sensor.dreame_a2_mower_photo_gallery`** — categorized cloud media
  (person / patrol / obstacle / album), synced hourly from the Dreame
  OSS bucket. State is the total item count; the `items` attribute
  carries the newest-first photo + video list (each with a signed media
  URL) for the bundled gallery card. Surfaced on the dashboard's
  Photos view.
- Per-type "latest" camera entities for picture cards:
  `camera.dreame_a2_mower_latest_photo`,
  `…_latest_person_detection`, `…_obstacle_photo` (the live AI-obstacle
  capture — see *AI obstacle capture*), and `…_latest_video` (video
  thumbnail).
- Per-type count sensors (`obstacle_photos`, `patrol_photos`,
  `person_photos`, `videos`) plus OSS storage-used % feed the Photos-view
  glance.
- The `show_photo_privacy_policy` service surfaces the Dreame AI photo-capture
  privacy policy as a persistent notification (the consent text behind the
  cloud's people/obstacle imagery).

### Settings (cloud + s2.51)
- Switches: rain protection, DnD, low-speed-at-night, custom charging
  window, child lock, anti-theft (lift / off-map / realtime location),
  LED behaviour (standby / working / charging / error).
- Numbers: volume, auto-recharge battery %, resume battery %.
- Times: DnD start/end, low-speed start/end, charging start/end.
- Selects: mowing efficiency, rain-protection resume hours.

### Known sync nuances

A subset of g2408 settings is on the Dreame app's "Mowing settings" page
(the one with the explicit Save button). All of these settings DO
propagate through the cloud — verified by toggling in one app instance
and observing the change in a second app instance on a different
device, with zero Bluetooth involvement. And because the integration issues
the **same Save path the Dreame app uses** and changes round-trip to the app
(confirmed with a live *AI Obstacle Recognition: Animals* toggle — changed in
HA, reflected in the app), an HA-initiated change is what the mower operates
under, the same as an app-initiated one: the app is the vendor control surface,
so a setting it reflects is the setting the mower runs on.

- AI Obstacle Recognition: Humans / Animals / Objects
- Mowing Direction
- Edge Mowing: Auto / Safe / Obstacle Avoidance
- LiDAR Obstacle Recognition + Obstacle Avoidance Distance / Height
- Mowing Height

(The Mowing-settings page also exposes value-tied fields — Mowing
Pattern, Edge Walk Mode, Obstacle-Avoidance Sensitivity, Cutter
Position, Cutter Height, Edge Passes — that have **no toggle in the
g2408 app** as of 2.5.8.1: they are wire-present but UI-less on this
model, so the integration does not surface them as user settings.)

For the settings above, the safe pattern today is: **toggle them in the
Dreame app**. HA picks up the change automatically within ≤2 min (cloud
poll cadence; some changes also fire MQTT and surface within seconds).
Force an immediate sync via
**`button.dreame_a2_mower_refresh_from_cloud`** if you don't want to wait.

If you toggle one of these in HA the cloud accepts the write and other
app instances pick it up on cold-start: the integration issues the same
Save path the Dreame app uses — the confirmed PRE bare-array
`action s2.a50 {m:s, t:PRE, d:[…]}`, dual-written to the SETTINGS cloud
record `[app-mitm:2026-06-09]`. One minor caveat: the original Dreame app
session may keep showing the pre-write value until its UI cache refreshes —
other app instances pick it up cleanly on cold-start.

Full per-entity reference — read source and verification status for every
switch / select / number / sensor / button / service — in
[`entity-inventory.yaml`](custom_components/dreame_a2_mower/entity-inventory.yaml);
the cloud write paths are in
[`docs/research/cloud-write-reference.md`](docs/research/cloud-write-reference.md).

### Multi-map

The integration tracks every cloud-side map and exposes each as a per-map
**sub-device** (SN-keyed, namespaced under the integration prefix). The
active map drives the live camera + the zone / spot / edge / direction /
efficiency selectors; each map also gets its own static map camera, LiDAR
camera, WiFi-heatmap camera, and metadata sensors (area, segment count,
spots, exclusion / no-obstacle zones, maintenance points, and per-map
session totals). The replay picker spans all maps. See `docs/multi-map.md`.

### Session lifecycle
- **Live trail** drawn over the base map during a mow; pen-up filter
  splits legs at >5 m jumps; <20 cm segments deduped.
- **In-progress persistence** survives HA restarts.
- **Finalize gate** with bounded retry (30-min max-age, 10 attempts,
  60 s interval) — no more sessions stuck "fetching summary" forever.
- **Manual finalize button + service** as escape hatch.
- **Session archive** at `<config>/dreame_a2_mower/sessions/`,
  content-addressed by md5; replay-session select on the dashboard
  drives the live map back to any archived session.

### LiDAR
- **Top-down camera** (512² thumbnail + 1024² full-resolution popout)
  rendered from archived PCD blobs.
- **WebGL Lovelace card** at `/dreame_a2_mower/dreame-a2-lidar-card.js`
  for an interactive 3D view (orbit / zoom / splat-size slider, optional
  base-map underlay).
- **PCD archive** with retention caps (count + total MB) configurable
  in the options flow.
- HTTP endpoint `/api/dreame_a2_mower/lidar/latest.pcd` (auth-gated)
  serves the most recent archived blob for desktop tools (Open3D,
  CloudCompare, MeshLab).
- **Per-map LiDAR cameras** — a top-down camera per known map.

### WiFi heatmap

- **WiFi-signal heatmap cameras** rendered from archived WiFi-strength
  samples laid over the map: a picker-driven WiFi camera (follows the
  WiFi-archive select) plus a per-map WiFi camera for each known map.
- **WiFi archive select** chooses which captured heatmap to display;
  `switch.dreame_a2_mower_wifi_heatmap_flip_x` / `_flip_y` correct the
  overlay orientation when a map needs it (integration-owned; no external
  helper needed).

### Observability
- **`sensor.dreame_a2_mower_novel_observations`** — count + attribute
  list of unfamiliar protocol shapes seen this process.
- **`sensor.dreame_a2_mower_api_endpoints_supported`** (default-disabled)
  — passive cloud-RPC accept/reject log.
- Raw diagnostic sensors for unmapped slots so values surface during
  ongoing protocol-RE work.
- **`download_diagnostics`** dumps state, capabilities, novel-token
  list, freshness, endpoint log, and recent NOVEL log lines through an
  **allowlist** (default-deny) — only fields known to be safe for a bug
  report are included; secrets, GPS coordinates, WiFi SSID/IP, the
  device serial, and cloud/MQTT identifiers (did/uid/host) are omitted
  or replaced with a `**REDACTED**` marker. See *Reporting bugs* below.

### Events and notifications

Mowing start/pause/resume/end and dock arrive/depart fire as HA event
entities (`event.dreame_a2_mower_lifecycle`). Each event carries a
payload with the action mode, area mowed, etc. — wire them to push
notifications, Logbook, automations, or your own dashboards. The
integration also ships a **device-trigger** platform, so the HA
automation editor offers per-event triggers ("Mowing started",
"Human detected", "Arrived at maintenance point", ...) directly off
the mower device. See `docs/events.md` for the full event reference
and recipes. The follow-up alert tier (emergency_stop, lifted,
stuck, ...) lands in a later release.

The integration also mirrors the Dreame app's notification inbox:
**`sensor.dreame_a2_mower_device_messages`** accumulates device messages
(state = total retained count, capped at 200; `items` attribute carries
the merged-by-id, newest-first list), fed from the cloud
`device-messages` list. Companion `last_notification` and per-scope
(device / service / shared) message-list sensors surface the same feed.

### Dashboard strategy

The integration ships a registered Lovelace **dashboard strategy**
(`custom:dreame-a2-mower`) that generates the whole dashboard from your
live entity/device registry — no YAML to copy or edit, and it can't drift
out of sync with the entities you actually have. See "Dashboard" under
Installation.

## Architecture

Three-layer stack with strict layering:

| Layer | Path | HA imports? | Responsibility |
|---|---|---|---|
| 1 | `custom_components/dreame_a2_mower/protocol/` | ❌ | Pure-Python wire codecs (s1.1 / s1.4 / s2.51 / session_summary / PCD / cloud-map geometry / TASK envelope). Unit-testable in a vanilla pytest venv. |
| 2 | `custom_components/dreame_a2_mower/{mower,observability,archive,live_map}/` | ❌ | Typed domain layer — `MowerState` dataclass, capabilities, property mapping, novel-observation registry, archives, live-map session state machine. |
| 3 | `custom_components/dreame_a2_mower/*.py` | ✅ | HA glue — config flow, coordinator, all platforms, services, diagnostics. |

The layering invariant (`grep` runs on every CI run) prevents
upstream creep: layer-1 and layer-2 must never import `homeassistant.*`.

## Installation

Currently distributed as a HACS custom repository.

1. HACS → Integrations → ⋮ → **Custom repositories**.
2. Add `https://github.com/okolbu/ha-dreame-a2-mower` with category
   **Integration**. Enable "show beta" if you want pre-release tags.
3. Install **Dreame A2 Mower** from HACS, restart HA.
4. Settings → Devices & Services → **Add Integration** → "Dreame A2
   Mower". Enter your Dreame cloud username, password, and cloud region
   (see *Region status* above). Setup **validates the credentials
   against the Dreame cloud on submit** — a wrong username/password or a
   connection problem shows an inline error right there instead of
   leaving you with a broken config entry. On success it **auto-detects
   your account's mowers and pins the first `dreame.mower.g2408`** it
   finds (a warning is logged if the account has more than one — see
   *Single-mower support* under Limitations); an account with no
   supported mower is rejected with a clear "no supported device"
   message rather than silently creating an unusable entry. If the
   Dreame cloud password changes later, HA surfaces a **reauthenticate**
   prompt on the integration instead of failing silently — enter the new
   password and existing entities carry on unchanged.
5. Configure → **Options** → set retention caps (LiDAR archive size
   defaults to 200 MB; PCDs run 2-3 MB each) and, optionally, turn on
   **experimental features** (see below; off by default, safe to leave
   off).

### Experimental features

The options flow has an **"Enable experimental features"** toggle,
**off by default**. Leave it off unless you have a specific reason to
change it — it gates two things:

- Entities that are wire-verified-but-unexercised, have unverified
  frame/units, or are fail-closed pending a backend response stay
  uncreated while it's off; turning it on creates them (still disabled
  by default in the entity registry, so you opt in per-entity from
  there).
- Two developer-only diagnostic services, `dump_map_diagnostics` and
  `discover_cloud_api`, are registered only while it's on — they're
  protocol reverse-engineering tools for maintainers, not needed for
  normal use.

Reload the integration after changing the option. Nothing in the
supported feature set — lawn mower control, live map, schedule editing,
settings, photo/video gallery, and the rest of this README — depends on
it.

### Dashboard

The integration ships everything a dashboard needs — 7 custom cards plus
a **dashboard strategy** that generates the whole thing from your live
entity/device registry — under **one** Lovelace resource:

1. Settings → Dashboards → Resources → **Add Resource**.
   - URL: `/dreame_a2_mower/dreame-a2-strategy.js`
   - Type: `JavaScript Module`

   (This one resource is enough — the strategy dynamically `import()`s
   all 7 bundled cards itself; you do not register them individually.
   They are served from the same static path,
   `/dreame_a2_mower/<file>.js` — see `__init__.py`'s
   `async_register_static_paths` call.)
2. Create a new dashboard (Settings → Dashboards → **Add Dashboard** →
   "New dashboard from scratch"), then edit it in YAML mode (⋮ → Edit
   Dashboard → ⋮ → Edit in YAML) and replace the content with:
   ```yaml
   strategy:
     type: custom:dreame-a2-mower
   ```
3. Save. The strategy reads the entity/device registry at render time
   and builds one view per discovered map plus Overview, Schedule,
   Sessions & History, Settings, Diagnostics & Tools, Photos, and
   Messages — it scales automatically to however many maps your mower
   has (no hardcoded map count) and never drifts out of sync with your
   actual entities, because it isn't a static file you copy and edit.
   Optional strategy config keys: `plotly: true` forces the Plotly
   session charts on (auto-detected by default; falls back to native
   `history-graph` if the `plotly-graph-card` HACS card isn't
   installed).

The sections below cover using individual bundled cards **standalone**,
outside the strategy (e.g. dropping the live map into a dashboard you're
building by hand) — not needed if you're using the strategy above.

#### WebGL LiDAR card

To use the WebGL LiDAR view on its own:

1. Settings → Dashboards → Resources → **Add Resource**.
2. URL: `/dreame_a2_mower/dreame-a2-lidar-card.js`, type
   `JavaScript Module`.
3. Add `type: custom:dreame-a2-lidar-card` to a card.

#### Animated live map

The live map is drawn by the bundled custom card
`custom:dreame-mower-map-card` (the strategy's Overview view uses it for
the hero live map). It renders the base PNG as an SVG backdrop and then,
reading the position stream the integration publishes on
`camera.dreame_a2_mower_map` (`map_projection`, `point_seq`,
`latest_point`, `track_snapshot`), accumulates the mowing trail
client-side and glides a directional mower icon between the ~5 s position
pushes. No more waiting on `<hui-image>`'s 10 s camera poll.

To use it standalone, register it as a Lovelace resource (Settings →
Dashboards → Resources → Add):

- URL: `/dreame_a2_mower/dreame-mower-map-card.js`
- Type: `JavaScript Module`

Then use:

```yaml
- type: custom:dreame-mower-map-card
  entity: camera.dreame_a2_mower_map
```

The card imports `/dreame_a2_mower/_dreame-map-core.js` (shared
projection / icon-rotation math) as an ES module — it is pulled in
automatically, so it needs **no** separate resource entry. Do not
register either file via `add_extra_js_url`; that proved unreliable on
YAML-mode dashboards (the card rendered a red "Configuration error"
because it never landed in the dashboard's element registry).

#### Animated session replay

The Sessions & History view includes an animated replay
(`custom:dreame-mower-replay-card`) that draws the mower's trail over
the base map at ≤30s total, with proportional freezes during charging /
stuck / faulted intervals — the strategy renders it directly for the
picked session, no toggle needed.

To use it standalone, register it as a Lovelace resource (Settings →
Dashboards → Resources → Add):

- URL: `/dreame_a2_mower/dreame-mower-replay-card.js`
- Type: JavaScript Module

Then use `type: custom:dreame-mower-replay-card` with `entity:` set to
the session-replay camera (`camera.dreame_a2_mower_session_replay`). The
JS ships with the integration — no separate HACS install needed.

### Activity logbook (optional dedup)

The Mower tab includes an activity logbook card that surfaces the
integration's two `event` entities — lifecycle (mowing started /
paused / resumed / ended, dock arrived / departed) and alert (the
s2p2 notification codes that mirror the Dreame app's push
notifications).

Each event currently shows TWICE: once as the EventEntity state
change with a generic "detected an event" message (HA's logbook
component bypasses custom describers for entity state changes),
and once as a custom HA bus event with the formatted human message.

To suppress the duplicates, add to your `configuration.yaml`:

```yaml
logbook:
  exclude:
    entities:
      - event.dreame_a2_mower_lifecycle
      - event.dreame_a2_mower_alert
```

The entities stay live (template/automation triggers still work) —
only the duplicate generic logbook lines are filtered.

## Cutting over from the legacy

If you ran the legacy `okolbu/ha-dreame-a2-mower-legacy` integration: see
**`docs/cutover.md`** for the full runbook. Greenfield uses the same
on-disk archive paths (`/config/dreame_a2_mower/{sessions,lidar}/`)
so historical session and LiDAR data carry over without migration.

## Documentation

- The original greenfield design spec (48-item behavioral parity checklist)
  and F1–F7 phase-by-phase implementation plans are maintainer-internal
  history and are not distributed with this repo.
- **`custom_components/dreame_a2_mower/entity-inventory.yaml`** — the
  authoritative per-entity inventory: read source + verification status
  for every entity and service. Use it to diagnose "I toggled X in HA
  but the app didn't see it".
- **`docs/research/cloud-write-reference.md`** — canonical reference
  for the chunked-batch (SETTINGS / SCHEDULE / AI_HUMAN) and
  routed-action (CFG) cloud surfaces, including the dual-entry
  semantic and propagation lag.
- **`docs/research/inventory/generated/g2408-canonical.md`** — wire SoT
  for MQTT property mappings, cloud-map coordinate frame, blob layouts,
  session-event schema, generated from
  `custom_components/dreame_a2_mower/inventory.yaml`. (The prior
  architecture-overview doc, `g2408-protocol.md`, is ARCHIVED to
  maintainer-internal history — it carried debunked claims; do not
  resurrect it as a source.)
- **`docs/research/cloud-map-geometry.md`** — pixel ↔ cloud-frame mm
  transforms, midline reflections, lawn-polygon decoding.
- **`docs/observability.md`** — diagnostic sensors, NOVEL log prefixes,
  `download_diagnostics` schema.
- **`docs/lidar.md`** — user-facing LiDAR guide.
- **`docs/cutover.md`** — legacy → greenfield runbook.
- **`docs/data-policy.md`** — per-field persistent / volatile /
  computed split.
- **`docs/events.md`** — event reference + automation recipes for the
  lifecycle event entity.
- **`docs/multi-map.md`** — multi-map support: active-map detection,
  per-map cameras, replay picker, current limitations.

## Limitations

### Single-mower support

This integration supports **one `dreame.mower.g2408` per Dreame cloud
account.** The config flow auto-detects your account's mowers and pins
the first g2408 it finds (see Installation); if the account has more
than one, only that one is set up and a warning is logged. The internal
architecture (SN-keyed identifiers, sub-devices via `via_device`) allows
for multiple mowers under separate config entries, but that path is
untested — if you have two A2/g2408 mowers, expect rough edges with a
second config entry; please file an issue.

### Time-window entities are read-only

The mowing schedule itself is editable from HA (the `set_schedule_plans`
service + the bundled schedule card). The per-setting time windows shown
as `time.*` entities — DnD, low-speed-at-night, and charging start/end —
are surfaced read-only; change those in the Dreame app and HA picks them
up on the next cloud sync.

### New maps need a reload

A newly-added map's *device* appears on the next cloud refresh, but its
*entities* are created only at integration setup. After creating a new map
in the Dreame app, reload the integration (Settings → Devices & Services →
Dreame A2 Mower → ⋮ → Reload) to surface its per-map entities. Rare in
practice — most users keep a stable set of maps.

## Reporting bugs

1. Open a [GitHub issue](https://github.com/okolbu/ha-dreame-a2-mower/issues)
   using the **Bug report** template.
2. Run `download_diagnostics` (Settings → Devices & Services → Dreame A2
   Mower → ⋮ → Download Diagnostics) and attach the resulting JSON file.
   It's built from an **allowlist**, not a denylist — only fields known
   to be safe are included in the first place — so it's safe to attach
   to a public issue. It contains:
   - `state` — an allowlisted subset of the `MowerState` snapshot;
     GPS, exact map/dock coordinates, and other sensitive fields are
     excluded outright, not merely redacted.
   - `cloud_state` / `mqtt_state` — connection status only; `did` /
     `uid` / `host` and the MQTT topic strings (which embed the device
     serial) are never included.
   - `config_entry` — only `country` and `model`; username, password,
     token, device id, serial, MAC, and host are replaced with a
     `**REDACTED**` marker if present.
   - `novel_observations`, `freshness`, `endpoint_log`,
     `recent_novel_log_lines` — protocol reverse-engineering diagnostics
     (unrecognized wire shapes, per-field staleness, cloud-RPC
     accept/reject outcomes, recent `[NOVEL/*]` warnings).
3. Include the integration version (HACS → Dreame A2 Mower) and your
   Home Assistant version (Settings → About).
4. **Do not paste raw Dreame cloud credentials, tokens, or MQTT
   connection strings into the issue.** The diagnostics download is
   built to be safe to attach; ad-hoc log excerpts are not guaranteed to
   be, so prefer the diagnostics file over pasting raw logs.

## License

MIT — see `LICENSE`.
