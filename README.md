# Dreame A2 Mower — Home Assistant Integration

Home Assistant integration for the **Dreame A2 robotic lawn mower** (model `dreame.mower.g2408`).

> **⚠️ Status: Alpha, actively reverse-engineered**
>
> This integration is being built from detailed MQTT protocol analysis of a live A2 mower. Settings decoding, telemetry, live map overlay and interactive 3D LiDAR viewing are in place. Expect breaking changes on minor version bumps.

## Scope

- **Supported:** Dreame A2 (`dreame.mower.g2408`) only.
- **Not supported:** Any other Dreame mower, any Dreame vacuum, MOVA, Mi-branded devices.

If you own another model, use the [upstream project](https://github.com/nicolasglg/dreame-mova-mower) this fork is based on.

## What you get

*Screenshots to follow.*

- **Live mower telemetry** — state, battery, charging status, current mowing zone, session area mowed, session distance, calibrated position (X, Y, or North/East compass projection), rain-protection state, obstacle detection.
- **Live 2D map** built directly from the cloud's `MAP.*` data — lawn boundary, exclusion zones tilted at their correct angle, dock icon placed at the physical charging station. Updates in place; md5-gated so it doesn't flicker on every state transition.
- **Live mowing trail** rendered into the camera PNG server-side. Works with any Lovelace card that shows the camera image. Configurable colour palette that matches the Dreame app (grass green, dark-grey trail, blue obstacles, red exclusion overlay).
- **Session summary archive** — every completed mow run's summary JSON (lawn polygon, mow path, obstacles, areas) persists to `<config>/dreame_a2_mower/sessions/`.
- **Session replay service** — `dreame_a2_mower.replay_session` pushes any archived run back into the camera for playback.
- **LiDAR scan archive** — every time you tap "Download LiDAR map" in the Dreame app, the mower uploads a standard `.pcd` point cloud; the integration fetches and stores it to `<config>/dreame_a2_mower/lidar/` and serves it at `/api/dreame_a2_mower/lidar/latest.pcd`.
- **Interactive 3D LiDAR card** — pure-WebGL Lovelace card (no Three.js, single JS file) that renders the point cloud with orbit controls, splat-size / softness controls, and an optional 2D-lawn-map underlay at ground level for context.
- **Archived session / LiDAR counters** exposed as diagnostic sensors so you know when a new run has been captured.
- **Rain-protection detection** — when the mower's LiDAR detects water and aborts a session, HA sees `s2p2 = 56` and tracks it.
- **Observability tooling** — an unknown-field MQTT watchdog logs any novel `(siid, piid)` pair the mower emits (new firmware features surface immediately). Optional raw-MQTT JSONL archive writes every payload to disk for offline analysis.

## Installation (HACS)

1. In HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/okolbu/ha-dreame-a2-mower` with category **Integration**.
3. Install **Dreame A2 Mower**.
4. Restart Home Assistant.
5. Settings → Devices & Services → Add Integration → "Dreame A2 Mower".

## Starter dashboard (optional but recommended)

This integration ships a ready-made Lovelace dashboard at
[`dashboards/mower.yaml`](dashboards/mower.yaml) with the map,
replay-session picker, 3D LiDAR card, problem-indicator panel, and
live telemetry already arranged. Home Assistant doesn't auto-install
integration dashboards (by design — it's your config), but a copy-
paste takes 2 minutes:

1. Drop `dashboards/mower.yaml` into `<ha_config>/dashboards/dreame_a2_mower/dashboard.yaml`.
2. Register it in `configuration.yaml` under `lovelace.dashboards`.
3. Restart HA — the **Mower** entry appears in the sidebar.

Full walkthrough: [`docs/dashboard-setup.md`](docs/dashboard-setup.md).

Otherwise the individual cards below can be mixed into your own
dashboard.

## The 2D base map — `camera.dreame_a2_mower_map`

After setup, a camera entity is created that serves the lawn map with the mower trail overlaid. Behind the scenes the integration:

- Pulls the map JSON from the Dreame cloud (`MAP.0`–`MAP.27` in `getDeviceData`). On g2408 the cloud's routed-action endpoint for CFG/PRE/DOCK/action opcodes ALSO works via `sendCommand` — see [`docs/research/g2408-protocol.md`](docs/research/g2408-protocol.md) §6.2 for the URL-construction gotcha (`-10000` iotComPrefix suffix + HTTPS) needed to avoid a 404.
- Projects the lawn polygon, exclusion zones (rotated by their stored `angle` field), and dock icon onto a rendered PNG. All the coordinate-frame gotchas are in [`docs/research/cloud-map-geometry.md`](docs/research/cloud-map-geometry.md).
- Composites the live mowing trail on top — one red segment per `s1p4` tick, with a pen-up filter at >5 m jumps so dock visits / telemetry drops don't draw ghost lines across the lawn.
- Serves PNG as the camera's `entity_picture`, with extra attributes for card calibration.

You can just drop `camera.dreame_a2_mower_map` into any picture-entity card and it renders. For interactive features (zones, go-to points) use a map card:

```yaml
type: custom:xiaomi-vacuum-map-card
entity: lawn_mower.dreame_a2_mower
vacuum_platform: default
map_source:
  camera: camera.dreame_a2_mower_map
calibration_source:
  camera: true
map_locked: true
two_finger_pan: true
map_modes:
  - name: Live position
    selection_type: MANUAL_PATH
    icon: mdi:robot-mower
    coordinates_rounding: false
    repeats_type: NONE
    max_repeats: 1
    predefined_selections: []
    service_call_schema:
      service: homeassistant.noop
```

Known map-card compatibility: **`lovelace-xiaomi-vacuum-map-card` works well**. `dreame-vacuum-map-card` expects entity=vacuum and auto-derives the camera by appending `_map` — ends up with `camera.dreame_a2_mower_map_map` (a non-existent entity). Stick to xiaomi unless you already know what you're doing.

## Map & LiDAR freshness — when does the integration re-pull?

The short version: **the base map is kept fresh automatically; the LiDAR scan is not — you have to trigger it from the app**.

### Base map (`camera.dreame_a2_mower_map`)

The mower does not push a "your cached map is stale" signal on every edit. To keep the HA camera in sync with app-side zone/exclusion/no-go changes, the integration re-pulls the cloud `MAP.*` dataset at seven different trigger points:

| When | Why |
|---|---|
| HA startup / integration setup | First load |
| **Every 6 hours** (periodic timer) | Catches edits made while HA was offline or from another phone, even if you don't mow for days |
| Session start (scheduled or manual) | In case you edited zones since the last run |
| BUILDING complete (after *Expand Lawn* / *Add Zone*) | Firmware just committed a new polygon |
| Dock departure | Belt-and-braces catch |
| Zone / exclusion edit from the Dreame app (while HA is running) | MQTT confirm `s2p50 o=215` detected in real time |
| Auto-recharge leg start (mid-session) | Firmware's own "map may be newer" signal |

Each refresh is a single ~100-200 KB cloud HTTP call. The server payload carries an `md5sum`; if it matches what's already cached, the camera is untouched (no logbook entry, no Lovelace reload). You can see the polls happening by enabling DEBUG on `custom_components.dreame_a2_mower.dreame.device` and grepping for `[MAP_POLL]`.

**No lightweight probe is possible:** the `md5sum` lives *inside* the 28 zlib+base64-compressed cloud chunks, so a full fetch IS the cheapest freshness check the Dreame platform exposes. Hence the deduplication at the md5 layer instead of a HEAD-style probe.

### LiDAR point cloud (`/api/dreame_a2_mower/lidar/latest.pcd`, `camera.*_lidar_top_down`, 3D card)

**The integration can only download a fresh LiDAR scan when you tap *Download LiDAR map* in the Dreame app.** This is a platform limitation, not a missing feature on our end — there is no passive endpoint that tells HA whether the on-mower scan has changed, and the mower only emits the `s99p20` OSS object key when the app view is opened *and* the scan has actually updated since last time.

Practical consequences:

- First install: until you've opened the LiDAR view in the app once, the integration has no PCD to show. The 3D card will say "no data" and the top-down camera will be blank.
- Between mowing sessions, the on-mower scan evolves as the LiDAR spins up on every run. To bring that into HA, tap the app's LiDAR view and wait ~30 s for the upload (you'll see the `s2p54` progress ticking in the HA log if DEBUG is on).
- Re-opening the LiDAR view with no scan change is a no-op — the mower deduplicates server-side. The existing cached PCD stays.
- If you want HA to always have a recent scan, open the app's LiDAR view once after each significant mow. There's no automation-side way to trigger this.

`camera.dreame_a2_mower_map_lidar_top_down` and the WebGL card re-render immediately when a new PCD lands. Old scans stay in `<config>/dreame_a2_mower/lidar/` indefinitely (content-addressed by md5) in case you want to compare across time.

## Interactive 3D LiDAR card

A pure-WebGL Lovelace card ships bundled with the integration (no Three.js, no HACS frontend plugin — served directly from the integration's own static path). Consumes the `.pcd` from `/api/dreame_a2_mower/lidar/latest.pcd` and shows an orbitable 3D point cloud.

**Enable it:**

1. **Settings → Dashboards → Resources → Add Resource**
   - URL: `/dreame_a2_mower/dreame-a2-lidar-card.js`
   - Resource type: **JavaScript Module**
2. Hard-refresh the browser (`Shift+F5`) — first installs trip on browser cache otherwise.
3. Add via the UI picker ("Dreame A2 LiDAR Card") or YAML:
   ```yaml
   type: custom:dreame-a2-lidar-card
   # All optional (all also exposed as live controls inside the card):
   # point_size: 2.5          splat size in px (live slider 1–40)
   # soft_edge: 1.0           0 = hard-edged circles, 1 = soft alpha falloff
   # show_map: false          draw 2D lawn underlay at Z=0
   # map_z: -1.0              underlay Z offset in metres (auto-defaults to bbox-min-Z)
   # map_flip_x: true         flip UV horizontally — needed on g2408 firmware
   # map_flip_y: true         flip UV vertically — needed on g2408 firmware
   # map_desat: 1.0           desaturation 0-1 (1 = monochrome underlay)
   # background: '#111'       card background colour
   ```

**Controls in the card:**

- **Drag** = orbit
- **Mouse wheel** = zoom
- **Splat slider** (1–40 px) — point size. At small sizes you see individual dots; at large sizes they blend into a pseudo-surface.
- **Soft splats** toggle — enables alpha falloff at splat edges so large overlapping splats read as a continuous surface. On by default.
- **Map underlay** toggle — draws the `camera.dreame_a2_mower_map` PNG as a textured ground plane at Z = `map_z` metres, under the point cloud. Lets you see the mown-area boundary behind the 3D dots.
  - **Z slider** — adjust the ground-plane altitude. Defaults to the point cloud's bbox-min-Z, which lands close for flat lawns; tune for slopes.
  - **Flip X / Flip Y** — orientation match between PCD and base map's coord frame. Both ON is the correct default on g2408.

**Performance:** 145 000-point scans render at 60 fps on integrated GPUs. Mobile / Pi-class hardware caps `gl_PointSize` at 48 to stay fill-rate-friendly. See [`docs/research/webgl-lidar-card-feasibility.md`](docs/research/webgl-lidar-card-feasibility.md) for the architecture notes.

**Feature status:** alpha. Mouse only (no touch gestures yet); no auto-refresh when a new scan lands (reload the card).

## Session replay

Every completed mow run is archived as a JSON summary under `<config>/dreame_a2_mower/sessions/`. Exposed count at `sensor.dreame_a2_mower_archived_mowing_sessions` with metadata for each run in the attributes.

Use the **Replay Session** picker on the Mower dashboard, or call the service directly:

```yaml
service: dreame_a2_mower.replay_session
data:
  file: latest           # auto-track newest run (= picker "Latest")
  # file: blank          # empty canvas (= picker "Blank")
  # Or an absolute path to a specific summary JSON (pinned — = picker "<date>"):
  # file: /config/dreame_a2_mower/sessions/2026-04-18_1776541055_0a68d124.json
```

The picker has three option types:

- **Latest** — auto-tracks the current run, or the newest archive when no run is active. A new run starting clears the map and begins drawing live.
- **Blank** — empty canvas; not affected by mower activity (for screenshots).
- **`<date>`** — pins the map to one archived session. Frozen until you pick something else.

The pinned overlay carries the historical lawn polygon, completed track (segment-aware — no ghost lines across pen-up gaps), obstacle polygons, and dock position. Map cards that read these attributes redraw with the frozen session overlaid. The live camera PNG also recomposites the trail directly.

## LiDAR scans

> LiDAR downloads only happen when **you tap *Download LiDAR map* in the Dreame app** — see the "Map & LiDAR freshness" section above for the full explanation of why this is a user-driven flow.

When you do tap, the mower uploads a PCD point cloud to Alibaba OSS and announces the object key via MQTT on `s99p20`. The integration detects this, fetches the binary, and stores it at `<config>/dreame_a2_mower/lidar/<YYYY-MM-DD>_<ts>_<md5>.pcd`.

Exposed surfaces:

- **`sensor.dreame_a2_mower_archived_lidar_scans`** — count of archived scans with metadata of the most recent in attributes.
- **`camera.dreame_a2_mower_lidar_top_down`** — server-side-rendered PNG top-down view with 45° oblique tilt (uses the firmware's baked-in height-gradient RGB, so the result matches the Dreame app's 3D view).
- **`GET /api/dreame_a2_mower/lidar/latest.pcd`** — auth-gated HTTP endpoint serving the raw `.pcd` for loading into desktop tools (CloudCompare / Open3D / MeshLab).
- **`custom:dreame-a2-lidar-card`** — the interactive WebGL card described above.

## Sensors (highlights)

- `sensor.dreame_a2_mower_state` — mower state (mowing / charging / docked / returning / error / …)
- `sensor.dreame_a2_mower_battery_level`, `sensor.dreame_a2_mower_charging_status`
- `sensor.dreame_a2_mower_mowing_position_x` / `_y` — calibrated live position, charger-relative metres. Raw Y has a 0.000625 correction factor for the g2408's wheel-encoder calibration; raw X is cm, calibrated to m.
- `sensor.dreame_a2_mower_mowing_position_north` / `_east` — compass-projected position when you set the **Station Direction** config number (degrees compass).
- `sensor.dreame_a2_mower_mowing_phase` — current mowing zone (resolves to the zone name when available, otherwise 1-indexed).
- `sensor.dreame_a2_mower_session_area_mowed` / `_session_distance` — live counters.
- `binary_sensor.dreame_a2_mower_obstacle_detected` — latches True on s1p53 obstacle events (LiDAR water detection, real obstacles, human presence).
- `binary_sensor.dreame_a2_mower_mowing_session_active` — True while a session is live, INCLUDING rain-paused periods (reads `s2p56` which the g2408 uses instead of the upstream `TASK_STATUS`).
- `sensor.dreame_a2_mower_error` — friendly error-code name (reads "No error" when everything is fine rather than "Unavailable").

## Configuration (options flow)

Settings → Devices & Services → Dreame A2 Mower → Configure:

- **Color scheme** + **Map objects** — base-map renderer options.
- **Live map X / Y calibration factors** — Y defaults to 0.625 (the g2408's wheel-encoder calibration constant; see [`docs/research/g2408-protocol.md`](docs/research/g2408-protocol.md) §3.1). Adjust if tape-measured distances don't match the rendered map.
- **Station Direction (° compass)** — the physical compass direction the charging station faces (0 = N, 90 = E, 180 = S, 270 = W). Projects the mower's X/Y into world North/East via the compass sensors. Also reachable as a regular number entity in the device Configuration card.
- **Raw MQTT archive** — off by default. When on, writes every MQTT payload to a daily-rotating JSONL file under `<config>/dreame_a2_mower/mqtt_archive/` for reverse engineering.

## Settings reachable from HA (cloud-visible)

Most of the Dreame app's settings flow through the cloud and are readable by HA. The integration fetches a 24-key `CFG` dict via the routed `getCFG` action (`siid:2 aiid:50 m:'g' t:'CFG'`) on every connect and whenever the firmware pushes `s2p51`/`s2p52` (settings-changed triggers).

Confirmed cloud-visible and exposed as HA entities (CFG-derived unless noted):

- **Navigation Path** (Direct/Smart, CFG.PROT) — confirmed via toggle correlation
- **Frost Protection** (on/off, CFG.FDP)
- **Rain Protection** (CFG.WRP `[enabled, resume_hours]` — resume_hours 0 = "Don't Mow After Rain")
- **Low-Speed Nighttime** (CFG.LOW `[enabled, start_min, end_min]`)
- **Auto-Recharge after Extended Standby** (CFG.STUN — fires auto-return ~1h after idle)
- **AI Obstacle Photos** (capture switch, CFG.AOP)
- **Lights schedule** (CFG.LIT 8-element, `[enabled, start_min, end_min, standby, working, charging, error, ?]`)
- **Anti-Theft Alarm** (CFG.ATA `[lift_alarm, offmap_alarm, realtime_location]`)
- **Do Not Disturb** (CFG.DND `[enabled, start_min, end_min]`)
- **Child Lock** (CFG.CLS)
- **Human Presence Alert** (CFG.REC 9-element, sensitivity + scenarios + photo consent + push interval)
- **Language** (CFG.LANG `[text_idx, voice_idx]`)
- **Voice volume** (0–100, CFG.VOL)
- **Voice prompt modes** (CFG.VOICE 4-element `[regular, work, special, error]`)
- **Charging config** (CFG.BAT 6-element `[recharge_pct, resume_pct, ?, custom_charging, start_min, end_min]`)
- **Notification preferences** (CFG.MSG_ALERT 4-element — `[0]=Anomaly Messages`, `[2]=Task Messages` confirmed; `[1]` and `[3]` are the other two app rows)
- **Mowing Height** (3-7 cm, `s6p2[0]` in mm)
- **Mowing Efficiency** (Standard/Efficient, `s6p2[1]`)
- **EdgeMaster** (`s6p2[2]` bool)
- **Mowing zones** (cloud `MAP.* mowingAreas`)
- **Designated Ignore Obstacle zones** (cloud `MAP.* notObsAreas` — green on map)
- **Classic exclusion zones** (cloud `MAP.* forbiddenAreas` — red on map)
- **Spots** for spot-mow (cloud `MAP.* spotAreas` — opt-in grey overlay via `switch.show_spot_zones`)
- **CFG version counter** (CFG.VER monotonic — useful as a tripwire)
- **Wear meters** (CFG.CMS `[blade, brush, robot, aux]`)
- **Timezone** (CFG.TIME IANA string)

Five CFG keys still mystery as of 2026-04-27: **`BP`, `DLS`, `PATH`, `PRE`** (g2408 only returns 2 elements where apk says 9), plus the unknown trailing fields on a few of the lists above. The `cfg_keys_raw` diagnostic sensor + dashboard MAP card make further toggle-research one click each.

### Cloud-write-invisible-on-MQTT (still un-readable on g2408)

These settings travel through cloud-write paths the integration hasn't reverse-engineered (`s6p2` tripwire fires but no readable side effect; the apk likely has dedicated `setX` endpoints we haven't enumerated):

- Mowing Direction (angle slider, incl. Crisscross / Chequerboard sub-options)
- Automatic Edge Mowing / Safe Edge Mowing
- Obstacle Avoidance on Edges
- LiDAR Obstacle Recognition (incl. Obstacle Avoidance Height sub-band)
- AI Obstacle Recognition: Humans / Animals / Objects (3 individual toggles)
- Obstacle Avoidance Distance (10/15/20 cm bands)
- Pathway Obstacle Avoidance (toggle + map-draw component)
- Stop Point Term, Start from Stop Point

These were originally labelled "Bluetooth-only" but the 2026-04-27 cloud-only Edge Mow start proved the mower is reachable via cloud HTTP without any BT hop. The settings ARE going through the cloud — just via `setX` targets we haven't identified. SSL-decrypt of the Dreame app's HTTPS traffic would surface the `t:` values in one session.

## Write commands

The routed-action endpoint (`siid:2 aiid:50`) works on g2408 once the URL-construction race is handled — see [`docs/research/g2408-protocol.md`](docs/research/g2408-protocol.md) §6.2. This enables:

- **`setPRE`** — wraps the mowing-prefs write (caveat: g2408's PRE is only 2 elements vs apk's 9, so most slots aren't reachable).
- **Action opcodes** — `start_mowing` (op 100 = all-area), `start_edge_mowing` (op 101), `find_bot` (op 9), `lock_bot` (op 12), `suppress_fault` (op 11), `cutter_bias` (op 503), `start_learning_map` (op 110 = manual perimeter walk), `pause`, `stop`, `recharge`. Plus the new multi-select **`Start Selected Zone Mow`** (op 102) and **`Start Selected Spot Mow`** (op 103) — pick zones/spots via per-entry "(mow next)" switches, then press the start button.
- **`getDockPos`** — dock position readback (currently a diagnostic sensor, may drive a future auto-calibration path).
- **`getOBS` / `getAIOBS`** — wrappers exist; on g2408 these return `r=-3` (no-data / not-supported), so the actual obstacle settings probably live in a different cloud surface.

Take Picture (op 401) was removed in alpha.164: the firmware accepts the routed-action but doesn't actually capture or upload — the Dreame app uses a separate cloud media-upload endpoint we haven't reverse-engineered.

Caveats:

- **Cloud relay `80001` errors are transient** on g2408 (the Dreame cloud can't always wake the mower for a command even when it's online via MQTT). Retries are built in; persistent failure surfaces as the entity showing "Unavailable" until the next successful refetch.
- `lawn_mower.dreame_a2_mower.start` / `.pause` / `.dock` service calls inherited from upstream still use the old un-prefixed URL and may fail — they predate the alpha.78 fix. Tracked in `TODO.md`.

Up-to-date protocol research: [`docs/research/g2408-protocol.md`](docs/research/g2408-protocol.md).

## Reporting new firmware behaviour (`[PROTOCOL_NOVEL]` warnings)

The integration was built by reverse-engineering the MQTT traffic of one
g2408 firmware build. When Dreame ships a firmware update — or when your
specific lawn / schedule / dock hardware triggers a protocol path we haven't
seen — the integration will log a one-shot WARNING so the new data doesn't
just vanish. You can help the project by opening an issue when any of these
appear in `home-assistant.log`:

```
[PROTOCOL_NOVEL] MQTT message with unfamiliar method=…
[PROTOCOL_NOVEL] properties_changed carried an unmapped siid=… piid=… value=…
[PROTOCOL_NOVEL] event_occured siid=… eiid=… with piids=…
[PROTOCOL_NOVEL] s2p2 carried unknown value=…
[PROTOCOL_NOVEL] s1p4 short frame len=… Raw=[…]
```

Each novel shape logs exactly **once** for the lifetime of the HA process
(deduped in-memory) — so these are safe to leave enabled and won't flood
the log. If you see one, please:

1. Copy the **full WARNING line verbatim** (the raw bytes / piid list are
   the data we need).
2. Note what you were doing at the time (mowing, docking, opening the
   LiDAR view in the app, changing a setting, etc.).
3. Open an issue at <https://github.com/okolbu/ha-dreame-a2-mower/issues>
   tagged `protocol` — we'll extend the decoder in the next release.

Integration-generated WARNINGs that are **not** actionable bugs:

- `[EVENT] session-summary fetch deferred (no cloud login yet) …` — routine
  at HA startup; the coordinator retries on the next update tick (see
  v2.0.0-alpha.6 changelog).
- `Discarding malformed g2408 blob (did=…)` — a single corrupted MQTT push;
  the blob decoder dropped it and the prior good value is retained.

If you see repeated (not one-shot) WARNINGs from this integration, that's
worth an issue too.

## Removing orphaned `dreame_*` entities from an earlier install

If you previously installed the upstream **Dreame Vacuum / Mover** integration before switching, HA's entity registry retains the old `*.dreame_*` entities. To clean up:

1. **Settings → Devices & Services**, find the old Dreame integration, click ⋮ → **Delete**.
2. **Settings → Devices & Services → Entities**. Filter by the old prefix, click into each **Not available** row → **Delete entity**.
3. Repeat for **Devices**.
4. Refresh. The new `dreame_a2_mower.*` entities remain.

Dashboards referencing old IDs need updating to the `dreame_a2_mower.*` prefix — this fork uses the new domain to avoid colliding.

## Development

Design documents: [`docs/superpowers/specs/`](docs/superpowers/specs/). Implementation plans: [`docs/superpowers/plans/`](docs/superpowers/plans/).

Protocol research:

- [`docs/research/g2408-protocol.md`](docs/research/g2408-protocol.md) — full MQTT property catalogue, `s1p4` frame layout, state machine, `s2p51` config-write map, map-push flow.
- [`docs/research/cloud-map-geometry.md`](docs/research/cloud-map-geometry.md) — coordinate-frame math behind the 2D base map.
- [`docs/research/webgl-lidar-card-feasibility.md`](docs/research/webgl-lidar-card-feasibility.md) — design notes for the interactive 3D card.
- [`docs/research/2026-04-17-g2408-property-divergences.md`](docs/research/2026-04-17-g2408-property-divergences.md) — g2408 siid/piid differences vs upstream `dreame-mova-mower`.

### Dev tool: seed the map from a probe log

```yaml
service: dreame_a2_mower.import_path_from_probe_log
data:
  file: /config/probe_log_sample.jsonl
  session_index: 4    # optional; default picks the most recent session
```

Replays a past session from a probe-log JSONL file onto the map attributes — validates card configuration without waiting for a live run.

## Attribution

Forked from [nicolasglg/dreame-mova-mower](https://github.com/nicolasglg/dreame-mova-mower) which is itself derived from the Dreame vacuum HA integration community work. License (MIT) preserved. Upstream contributions are gratefully acknowledged; this fork diverges because the A2 mower uses materially different `siid/piid` assignments and transport semantics that upstream explicitly does not target.

## License

MIT — see [LICENSE](LICENSE).
