# P2 entity audit table

**Date**: 2026-04-27
**Plan**: docs/superpowers/plans/2026-04-27-pre-launch-p2-entity-audit.md
**Source-of-truth**: docs/research/g2408-protocol.md §2.1

## Disposition rules

| §2.1 status | Classification |
|---|---|
| Confirmed | PRODUCTION / OBSERVABILITY |
| Partial | OBSERVABILITY |
| TBD on g2408 | EXPERIMENTAL (disabled by default) |
| enum-only / none | DELETE |

## Section 1.1 — binary_sensor.py + camera.py + lawn_mower.py + device_tracker.py

> **Row count**: 12 total (5 binary_sensor + 5 camera + 1 lawn_mower + 1 device_tracker).
> The spec estimated ~16; actual descriptor count is lower: binary_sensor.py has 5 descriptors (not 8) and camera.py has 5 distinct entity types (not 7).

| File | Class/key | Computed entity_id | Underlying property/action | §2.1 citation | Classification | Proposed entity_id | Proposed entity_category | Proposed enabled_by_default | Reason / notes |
|---|---|---|---|---|---|---|---|---|---|
| binary_sensor.py | `obstacle_detected` | `binary_sensor.dreame_a2_mower_obstacle_detected` | `property_key=DreameMowerProperty.OBSTACLE_FLAG` → s1.53 bool | s1.53 (confirmed) | PRODUCTION | — | `None` | `True` | Directly actionable: user should see obstacle/person alerts on dashboard. s1p53 is confirmed in §2.1; has auto-clear 30 s guard for latch-without-clear behaviour (binary_sensor.py:27). |
| binary_sensor.py | `mowing_session_active` | `binary_sensor.dreame_a2_mower_mowing_session_active` | `value_fn` → `device.status.started` (from s2.56 task-state) OR `device.has_active_in_progress` (disk-restored flag) | s2.56 (confirmed) | PRODUCTION | — | `None` | `True` | Orthogonal to lawn_mower state: stays True through pause/charge mid-session; the only entity that signals "session is still running" while the mower is physically docked for recharge. Feeds useful automations ("notify when mowing finishes"). |
| binary_sensor.py | `battery_temp_low` | `binary_sensor.dreame_a2_mower_battery_temp_low` | `value_fn` → `device.battery_temp_low` → s1.1 heartbeat byte[6]&0x08 | s1.1 (confirmed, HEARTBEAT byte[6] bit) | PRODUCTION | — | `None` | `True` | User-actionable: mower refuses to charge when asserted; coordinator also fires a persistent notification (coordinator.py:390). Sourced from confirmed heartbeat decode (§4.4). |
| binary_sensor.py | `positioning_failed` | `binary_sensor.dreame_a2_mower_positioning_failed` | `value_fn` → `device.positioning_failed` → s2.2 code 71 | s2.2 / s2.56 (confirmed — s2p2 secondary phase channel; code 71 = positioning failed) | PRODUCTION | — | `None` | `True` | User-actionable: while True every cloud-issued Start/Dock/Return fails until SLAM relocation recovers. Enables automation "alert when mower is lost". s2p2 phase channel is confirmed on g2408 (device.py:354). |
| binary_sensor.py | `rain_protection_active` | `binary_sensor.dreame_a2_mower_rain_protection_active` | `value_fn` → `device.rain_protection_active` → s2.2 code 56 | s2.2 / s2.56 (confirmed — s2p2 secondary phase channel; code 56 = BAD_WEATHER / rain) | PRODUCTION | — | `None` | `True` | User-actionable: mower parked at dock due to rain; useful dashboard indicator and automation trigger. Same confirmed s2p2 channel as positioning_failed, different code. §2.1 §ERROR code 56 = BAD_WEATHER. |
| camera.py | `map` (key="map") | `camera.<device_name>_map` | `DreameMowerMapType.FLOOR_MAP` — renders live map PNG from MAP_DATA (s6.1) + live trail overlay from s1.4 telemetry | s6.1 (confirmed, MAP_DATA), s1.4 (confirmed, MOWING_TELEMETRY) | PRODUCTION | — | N/A | `True` | Primary user-facing map entity; confirmed data sources. No rename: name already set dynamically to "Live Map". |
| camera.py | `map_data` (key="map_data") | `camera.<device_name>_map_data` | `DreameMowerMapType.JSON_MAP_DATA` — serves gzip-JSON dump of parsed map state for dev/custom-card use | s6.1 (confirmed) | OBSERVABILITY | — | `EntityCategory.CONFIG` | `False` | Dev/integration-builder tool: exposes raw parsed map JSON for custom Lovelace cards or debugging. Not a user dashboard item. Already `entity_registry_enabled_default=False` (camera.py:108). |
| camera.py | `saved_map` (key="saved_map", dynamic per map index) | `camera.<device_name>_map_<N>` | Static base-map PNG per stored map; uses same `DreameMowerMapRenderer` on stored `MapData` | s6.1 (confirmed) | PRODUCTION | — | `EntityCategory.CONFIG` | `True` | User needs to select and view stored maps; each created dynamically in `async_update_map_cameras` (camera.py:397). CONFIG category appropriate — infrastructure, not live state. |
| camera.py | `wifi_map` (key="wifi_map", dynamic per map index) | `camera.<device_name>_wifi_map_<N>` | WiFi heatmap overlay PNG per stored map; gated by `capability.wifi_map && !low_resolution` | s6.3 (confirmed, WiFi signal on g2408) | OBSERVABILITY | — | `EntityCategory.CONFIG` | `False` | Nice-to-have overlay for finding WiFi dead spots, not a dashboard primary. Already `entity_registry_enabled_default=False` (camera.py:419). On g2408 s6.3 carries WiFi [cloud_connected, rssi_dbm] — the wifi_map itself may not be populated; treat as OBSERVABILITY until confirmed working. |
| camera.py | `DreameMowerLidarTopDownCamera` | `camera.<device_name>_lidar_top_down` (unique_id: `<mac>_lidar_topdown`) | Renders top-down PNG from LiDAR PCD archive (99.20 OSS key, local cache) | 99.20 (confirmed, LiDAR PCD trigger) | OBSERVABILITY | — | N/A | `True` | Protocol-debugging / power-user feature: visualises the LiDAR point cloud. Not a primary mowing-state indicator. Enabled by default because it's the only 3D scan view and users asked for it; but not PRODUCTION because it's a dev/exploration tool. |
| lawn_mower.py | `DreameMower` | `lawn_mower.<device_name>` (unique_id: `<mac>_dreame_a2_mower`) | Wraps s2.1 STATUS enum → `LawnMowerActivity`; s3.1 BATTERY_LEVEL; s3.2 CHARGING_STATUS; actions via device.start/pause/dock | s2.1 (confirmed), s3.1 (confirmed), s3.2 (confirmed) | PRODUCTION | — | `None` | `True` | The mandatory primary entity for any lawn_mower platform integration. All three underlying properties are confirmed in §2.1. State mapping covers the full DreameMowerState enum (lawn_mower.py:114). |
| device_tracker.py | `DreameMowerGpsTracker` | `device_tracker.<device_name>_gps` (unique_id: `<mac>_gps`) | Reads `device.gps_latitude` / `device.gps_longitude` from `_locn` cache populated by `getCFG t:'LOCN'` | LOCN (confirmed, WGS84 {pos:[lon,lat]}) | PRODUCTION | — | `None` | `True` | Anti-theft / location tracking. LOCN is confirmed in §2.1 CFG catalog. Entity goes unavailable when gps_latitude is None (device_tracker.py:81), handling the CFG.ATA[2] anti-theft-disabled case cleanly. |
