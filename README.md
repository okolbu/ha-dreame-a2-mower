# Dreame A2 Mower — Home Assistant Integration

Home Assistant integration for the **Dreame A2 robotic lawn mower** (model `dreame.mower.g2408`).

> **⚠️ Status: Alpha, actively reverse-engineered**
>
> This integration is being built from detailed MQTT protocol analysis of a live A2 mower. Settings decoding, telemetry, and live map overlay are being added phase-by-phase. Expect breaking changes on minor version bumps.

## Scope

- **Supported:** Dreame A2 (`dreame.mower.g2408`) only.
- **Not supported:** Any other Dreame mower, any Dreame vacuum, MOVA, Mi branded devices.

If you own another model, use the [upstream project](https://github.com/nicolasglg/dreame-mova-mower) this fork is based on. This fork deliberately strips non-A2 code paths to keep the integration focused.

## Attribution

Forked from [nicolasglg/dreame-mova-mower](https://github.com/nicolasglg/dreame-mova-mower) which is itself derived from the Dreame vacuum HA integration community work. License (MIT) preserved. Upstream contributions are gratefully acknowledged; this fork diverges because the A2 mower uses materially different siid/piid assignments and transport semantics that the upstream project explicitly does not target.

## Installation (HACS)

1. In HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/okolbu/ha-dreame-a2-mower` with category **Integration**.
3. Install **Dreame A2 Mower**.
4. Restart Home Assistant.
5. Settings → Devices & Services → Add Integration → "Dreame A2 Mower".

## Settings invisible to Home Assistant (Bluetooth-only)

A subset of the Dreame app's configuration flows over **Bluetooth directly from the phone to the mower**, bypassing the cloud entirely. Those settings never appear on MQTT and can't be read or written from HA. You have to adjust them in the app with Bluetooth reach of the mower.

Confirmed BT-only on the Dreame A2 (`dreame.mower.g2408`):

- Mowing Direction (angle slider)
- Mowing Height (cutting-blade height slider)
- Mowing Efficiency
- Edge Mowing / Safe Edge Mowing / EdgeMaster
- Start from Stop Point
- Obstacle Avoidance Distance / Height
- Pathway Obstacle Avoidance
- Obstacle Avoidance on Edges
- LiDAR / AI Recognition detail toggles
- Robot Voice / Volume

If a toggle you expect to see in HA is missing, check whether it's in the list above — it's almost certainly BT-only. Cloud-visible settings (DnD, Rain Protection, Frost Protection, Child Lock, Anti-Theft, Charging Config, Low-Speed Nighttime, LED schedule, AI Obstacle Photos, Human Presence Detection) are handled through `s2p51` MQTT multiplexed writes and exposed as HA switches / numbers / selects.

See `docs/research/g2408-protocol.md` §6.1 for the full reverse-engineering notes.

## Removing orphaned `dreame_*` entities from an earlier install

If you previously installed the upstream **Dreame Vacuum / Mover** integration before switching to this one, HA's entity registry retains the old `lawn_mower.dreame_mower_*`, `sensor.dreame_mower_*`, `camera.dreame_mower_*`, etc. They persist as greyed-out "Unavailable" rows and clutter dashboards.

**To clean them up:**

1. **Settings → Devices & Services**, find the old Dreame integration, click ⋮ → **Delete**. This removes the config entry but may leave the device/entities in the registry.
2. **Settings → Devices & Services → Entities tab**. Filter by `dreame_` (or whatever prefix the old entity IDs used). For each row showing **Not available** or **Disabled by integration**, click into it and hit **Delete entity**.
3. Repeat for the **Devices** tab — old Dreame devices with no associated integration can be removed.
4. Refresh the browser. The new `dreame_a2_mower.*` entities remain.

YAML dashboards referencing the old entity IDs will need to be updated to the new `lawn_mower.dreame_a2_mower`, `camera.dreame_a2_mower_map`, etc. The new integration deliberately uses the `dreame_a2_mower` domain prefix to avoid colliding.

## Interactive 3D LiDAR card (alpha)

A minimal pure-WebGL Lovelace card ships with the integration — no
Three.js or other external dependencies, single JS file served from
the integration itself. Consumes the `.pcd` from
`/api/dreame_a2_mower/lidar/latest.pcd` and shows an orbitable 3D
point cloud. Drag to rotate, wheel to zoom.

**Enable it:**

1. **Settings → Dashboards → Resources → Add Resource**
   - URL: `/dreame_a2_mower/dreame-a2-lidar-card.js`
   - Resource type: **JavaScript Module**
2. Force-reload the browser (cache busts on the file path).
3. Add the card either via the UI picker ("Dreame A2 LiDAR Card") or in YAML:
   ```yaml
   type: custom:dreame-a2-lidar-card
   # Optional:
   # point_size: 3
   # background: '#111'
   ```

Status: **alpha**. Mouse only for now — no touch gestures,
no auto-refresh on new scan, no screenshot export. Performance tested
at 145 000 points on desktop integrated GPU (60 fps). Raspberry Pi-
class hardware caps `gl_PointSize` to stay fill-rate-friendly.

## Map card configuration

The integration exposes the active mowing session's position, path trail, and detected obstacles as attributes on the `camera.dreame_a2_map` entity. Use [lovelace-xiaomi-vacuum-map-card](https://github.com/PiotrMachowski/lovelace-xiaomi-vacuum-map-card) or a similar Lovelace map card to render them on top of the base map image.

Published attributes:

- `position` — `[x_m, y_m]` current calibrated mower position (charger is origin)
- `path` — list of `[x_m, y_m]` points for the current session (deduped at 0.2 m)
- `obstacles` — list of `[x_m, y_m]` obstacle markers (deduped at 0.5 m)
- `charger_position` — always `[0.0, 0.0]`
- `session_id` / `session_start` — increments / ISO timestamp on each mow session
- `calibration` — active `x_factor` and `y_factor` from Options Flow

Calibration factors are editable per-installation via **Settings → Devices & Services → Dreame A2 Mower → Configure** (defaults: X=1.0, Y=0.625 per current firmware's wheel-encoder constant).

Example card configuration:

```yaml
type: custom:xiaomi-vacuum-map-card
map_source:
  camera: camera.dreame_a2_map
calibration_source:
  camera: true
map_locked: true
entities:
  - path: path
    icon: mdi:robot-mower
```

You will need to add `calibration_points` specific to your lawn by dragging three points on the card's setup UI — the integration cannot infer them.

### Dev tool: seed the map from a probe log

Service `dreame_a2_mower.import_path_from_probe_log` replays a past session from a probe-log JSONL file onto the map attributes. Useful for validating card configuration without waiting for a live run:

```yaml
service: dreame_a2_mower.import_path_from_probe_log
data:
  file: /config/probe_log_sample.jsonl
  session_index: 4    # optional; default picks the most recent session
```

## Development

See [`docs/superpowers/specs/`](docs/superpowers/specs/) for design documents and [`docs/superpowers/plans/`](docs/superpowers/plans/) for implementation plans.

Protocol research:

- [`docs/research/g2408-protocol.md`](docs/research/g2408-protocol.md) — full MQTT property catalog, `s1p4` frame layout, state machine, `s2p51` config-write map, and the map-push / OSS fetch flow.
- [`docs/research/2026-04-17-g2408-property-divergences.md`](docs/research/2026-04-17-g2408-property-divergences.md) — g2408 siid/piid differences vs upstream `dreame-mova-mower`.

## License

MIT — see [LICENSE](LICENSE).
