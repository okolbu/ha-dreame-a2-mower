# Phase C — New read sources (design)

**Date:** 2026-06-10
**Status:** design, awaiting user review → writing-plans
**Phase:** C of the app-integration roadmap (`docs/research/app-integration-roadmap.md`).
**Predecessors:** Phase 0 (knowledge capture), A1 (CFG writable), A2 (PRE writable), B (core-control).

## Context

Phase C surfaces read-only sources the 2026-06-09 capture revealed. Exploration
found most of the roadmap's "new reads" are already built:
- **NET wifi = done** — `_refresh_net` (1h) populates `wifi_ssid`/`wifi_ip`/
  `wifi_rssi_dbm`; sensors exist.
- **MAP.* decoded-cache = done** — `fetch_map` already reads the decoded JSON
  (`mapIndex` segments), not the binary blob.
- **device fault/event messages = done** — `fetch_device_messages` (v2) → `event.py`.

The genuinely-new pieces (this phase): absolute GPS via `location/getRecords`,
4G-SIM status via `REMOTE`, the System/Service/Activity message list via
`message-record/list` v1, and a `wifi_ip` sensor.

All read-only — **no control_mode / writability concerns.** Honesty basis: the
2026-06-09 capture is the wire verification (consistent with A1/A2/B).

## Goal & scope

**Goal:** make the mower's real location, 4G-SIM status, account message list, and
wifi IP visible in HA.

**In scope (4 read sources):**
1. **GPS absolute** (`location/getRecords`) → feeds the existing device_tracker.
2. **REMOTE / 4G-SIM** → 4 diagnostic sensors.
3. **message-record v1** → one unread-count sensor (minimal).
4. **wifi_ip** → one diagnostic sensor (state already populated).

**Out of scope:** MAP.* (done), NET wifi ssid/rssi (done), device-messages/v2
(done), LOCN dock-origin projection (unimplemented; conceptually a future "dock
location" entity — not built).

## §1 GPS: getRecords → device_tracker (retire the LOCN position write)

Today `position_lat/lon` is written ONLY by `_refresh_locn` (LOCN routed-action,
`pos:[lon,lat]`) and read ONLY by the device_tracker. LOCN returns the `[-1,-1]`
sentinel (dock-origin unconfigured) on this device, so the tracker is **always
empty**. `location/getRecords` returns absolute WGS84 (~4m, via the 4G SIM, no
dock-origin needed).

- New `cloud_client.fetch_gps()` → `POST dreame-mower-service-app/location/
  getRecords` → parse `locationRecords.records[]`, take the **newest by
  `updateTime`**, return `{lat: float, lon: float, update_time: str,
  card4g: str}` (gpsLat/gpsLong are decimal-degree STRINGS → float). None on
  empty/failure.
- New `coordinator._refresh_gps` (60s) populates `position_lat/lon` from
  getRecords → the existing device_tracker shows the mower's absolute location.
  Also store `gps_update_time` / `gps_card4g` for device_tracker attributes.
- **Retire `_refresh_locn`'s `position_lat/lon` write** — remove `_refresh_locn`
  from the refresher timer set (it only ever wrote the sentinel→None here).
  `fetch_locn` stays in the cloud client (unused) for a future dock-location
  entity; do not delete it.
- ATA[2] (Real-Time Location) gates getRecords — if off (writable via the A1
  `anti_theft_realtime_location` switch), no records → position `None` (graceful).
- Update the device_tracker docstring: source is now getRecords (absolute), not
  LOCN.

## §2 REMOTE / 4G-SIM

- New `cloud_client.fetch_remote()` → routed `m:g t:"REMOTE"` →
  `{activeTime, cardId(ICCID), expiredTime, leftDays}`. None on failure.
- New `coordinator._refresh_remote` (6h — SIM data changes rarely).
- New `MowerState` fields: `sim_active_time`, `sim_card_id`, `sim_expired_time`,
  `sim_left_days`.
- 4 diagnostic sensors (`sensor_device.py`): `sim_card_id` (ICCID),
  `sim_active_time`, `sim_expired_time`, `sim_left_days` (the headline —
  SIM-expiry countdown, unit "days"). `cardId` == getRecords `card4g` (same SIM).

## §3 message-record v1 (minimal)

- New `cloud_client.fetch_message_record()` → `GET /dreame-message-push/v1/
  message-record/list?version=v1` → System+Service+Activity (incl. marketing).
  Parse the unread count (or `message-record/homestat` for `serviceMsgUnread`)
  and the latest message's title/link.
- Folded into a slow refresh (1h). New `MowerState` fields:
  `service_messages_unread` (int) + `latest_service_message` (str, for an
  attribute).
- One diagnostic sensor `service_messages_unread` with the latest message
  title/link in attributes. Low value — kept deliberately minimal; the useful
  fault/event surface is already `device-messages/v2`.

## §4 wifi_ip

- `wifi_ip` already exists in `MowerState` (populated by `_refresh_net`). Add one
  diagnostic sensor reading `s.wifi_ip`. No fetch/refresh change.

## §5 Architecture (all read-only)

- `cloud_client/_fetchers.py`: add `fetch_gps`, `fetch_remote`,
  `fetch_message_record`. `fetch_locn` retained (unused).
- `coordinator/_refreshers.py`: add `_refresh_gps` (60s) + `_refresh_remote`
  (6h); fold message-record into a slow refresh (1h); **remove `_refresh_locn`
  from the timer registration**.
- `mower/state.py`: add `sim_active_time`, `sim_card_id`, `sim_expired_time`,
  `sim_left_days`, `service_messages_unread`, `latest_service_message`,
  `gps_update_time`, `gps_card4g`.
- `sensor_device.py`: 4 SIM sensors + `wifi_ip` + `service_messages_unread`.
- `device_tracker.py`: now fed by getRecords (docstring + attributes updated);
  no structural change to the entity.

## §6 Testing (TDD)

- **Fetcher parse tests** against the captured response shapes: getRecords
  (`locationRecords.records[]`, newest-by-updateTime, string→float), REMOTE
  (`{activeTime,cardId,expiredTime,leftDays}`), message-record/list v1 (unread +
  latest). **Use FAKE lat/long + a FAKE ICCID in fixtures** — the captured GPS is
  the user's home and `cardId` is the real SIM (sensitive); never commit real
  values.
- **Refresher tests**: `_refresh_gps` populates `position_lat/lon` from the newest
  record and `None` on empty/ATA-off; `_refresh_remote` populates the 4 SIM
  fields; message-record refresh populates the unread count.
- **Sensor/device_tracker tests**: the 4 SIM + wifi_ip + service_messages_unread
  sensors read their state fields; the device_tracker reports the getRecords
  position + attributes.
- **Retirement test**: `_refresh_locn` is no longer in the timer set; any test
  asserting it ran or that the tracker reads LOCN is updated.
- Full suite green.

## §7 Fact-discipline

- `inventory.yaml`: getRecords / REMOTE / message-record-v1 are already `verified`
  (Phase 0) — append verifications that they're now **wired + surfaced** in the
  integration (date 2026-06-10, evidence `app-mitm:2026-06-09-settings-sweep`).
- `entity-inventory.yaml`: add entries for the new sensors (4 SIM, `wifi_ip`,
  `service_messages_unread`); **update the device_tracker entry's source from
  LOCN → getRecords** (the prior "reads LOCN" claim is now stale → correct it;
  retract verbatim if a claim is literally false). Record the `_refresh_locn`
  retirement.

## §8 Risks & edge cases

- **Sensitive data** — test fixtures use fake GPS/ICCID only.
- **getRecords is history** — take the newest by `updateTime`; stale when docked
  (device reports while mowing) — acceptable (tracker shows last-known).
- **ATA[2] gating** — off → no records → `None`; documented (enable via A1 switch).
- **Retiring `_refresh_locn`** — update tests; `fetch_locn` kept for a future
  dock-location entity.
- **message-record low value** — minimal surface (one sensor); don't over-build.

## Out-of-scope follow-ups (TODO, not built here)

- Dock-location entity from LOCN/dock-origin (needs dock-origin configuration —
  unimplemented).
- Richer message-center surface (per-tab lists, mark-read) if ever wanted.
