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
