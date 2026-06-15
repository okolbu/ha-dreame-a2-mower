# Messages "Info" dashboard tab — design

**Date:** 2026-06-15
**Status:** approved design (pre-implementation)
**Topic:** surface the device / service / sharing message lists from the Dreame
message center on a new dashboard "Info" tab, backed by three read-only sensors.

## Goal

The Dreame app's message center has several tabs; the integration currently
surfaces only unread *counts* (`sensor.service_messages_unread` with
`system_messages_unread` + `latest_message` attrs). This feature surfaces the
actual message *lists* for three tabs — **Device**, **Service**, **Sharing** —
as read-only HA sensors, and renders them on a new dashboard "Info" view as one
markdown card per list.

Out of scope (deliberate): the **System** tab (Dreame-wide marketing, e.g. the
"SOMMERSALG" summer-sale system messages) — we don't want Dreame-wide
announcements in the integration. Its unread count stays available via the
existing `system_messages_unread` attribute. Also out of scope: mark-read
actions (read-only for now) and a custom Lovelace card (markdown is sufficient).

## Background (already in place)

- `fetch_message_record` (`cloud_client/_fetchers.py`) already GETs the v1 list
  `/dreame-message-push/v1/message-record/list?version=v1` and parses
  `serviceMsg` / `systemMsg`, but returns only `{service_unread, system_unread,
  latest}` — it **discards** `serviceMsg.msgRecord` (the list we now want).
  [verified — current code]
- `fetch_device_messages` (`cloud_client/_fetchers.py`) already GETs
  `/dreame-messaging/user/device-messages/v2?did=…&pageNum=1&pageSize=N` (latest
  10) and feeds `sensor.last_notification` + the notification event via
  `coordinator/_notifications.py`. The full list is not surfaced. [verified —
  current code]
- The message-center endpoint surface is documented in `inventory.yaml`
  § `message_record_and_messaging_endpoints` `[app-mitm:2026-06-09-settings-sweep]`:
  service records carry `multiLangDisplay` = `"{zh/en:{name,content,link}}"`;
  sharing is `GET /dreame-messaging/user/share-messages?limit&offset&version=v1`.
- The read-only list pattern already exists: the `patrol_points` sensor
  (`entities/sensor/map.py`) has `state = count` and an `items` attribute list.
- `_unrecorded_attributes = frozenset({"*"})` is already used on big-attribute
  sensors (`entities/sensor/device.py`).
- The options flow already carries a family of `CONF_*_ARCHIVE_KEEP` integer
  caps (lidar / photo / video / session / wifi).
- The live dashboard is YAML-mode at `/config/dashboards/mower/dashboard.yaml`
  on the HA host and is deployed via SCP (not version-controlled in this repo).

## Architecture

```
cloud (v1 message-record/list, device-messages/v2, share-messages)
   │  (existing 1 h _refresh_messages cycle)
   ▼
cloud_client/_fetchers.py
   fetch_message_record()   → service list (+ existing counts)
   fetch_device_messages()  → device list  (page size = cap)
   fetch_share_messages()   → sharing list (NEW)
   ▼
protocol/message_record.py  (NEW, pure)
   normalize_*()            → list[Message] {id,title,date,body,link,unread}
   ▼
coordinator/_refreshers.py:_refresh_messages
   trims each list to CONF_MESSAGES_KEEP, writes 3 new MowerState fields
   ▼
entities/sensor/device.py   3 read-only DreameA2Sensor descriptors
   sensor.dreame_a2_mower_device_messages   (state=unread, items=list)
   sensor.dreame_a2_mower_service_messages
   sensor.dreame_a2_mower_shared_messages
   ▼
dashboard "Info" view — one markdown card per sensor (SCP deploy)
```

## Components

### 1. `protocol/message_record.py` (new, pure)

A side-effect-free module that normalizes each upstream record into a single
shape:

```python
@dataclass(frozen=True)
class Message:
    id: str
    title: str
    date: str | None     # ISO-8601 string, or None
    body: str | None     # short content snippet
    link: str | None     # tap-through URL, or None
    unread: bool
```

- `normalize_service(records: list[dict]) -> list[Message]` — `title =
  multiLangDisplay.en.name` (fallback first lang), `body = .content`, `link =
  .link`; `date` from the record's timestamp field; `unread` from its read flag.
  [service shape verified — inventory § message_record_and_messaging_endpoints]
- `normalize_device(records: list[dict]) -> list[Message]` — map from the
  already-parsed device-message dicts (title/text/time). The raw `source`
  `{siid,piid,value}` is **not** carried into the card (Standard depth). [device
  shape verified — current fetch_device_messages]
- `normalize_share(records: list[dict]) -> list[Message]` — defensive map.
  ⚠️ **The exact share-messages record field names are not yet captured**
  `[UNKNOWN — to capture]`. The implementation plan MUST include a one-shot live
  capture of `GET /dreame-messaging/user/share-messages?version=v1` to confirm
  the field names before this parser is finalized; until then it is written
  defensively (best-effort key probing) and covered by a fixture once captured.

All lists are returned newest-first. Trimming to the cap happens in the
refresher, not here (the module is cap-agnostic).

### 2. Fetchers (`cloud_client/_fetchers.py`)

- **Extend `fetch_message_record`** to additionally return
  `service_records = serviceMsg.msgRecord` (raw list) alongside the existing
  `{service_unread, system_unread, latest}`. No new HTTP call. Back-compatible
  (additive key).
- **Extend `fetch_device_messages`** usage in `_refresh_messages` to request
  `pageSize = cap` (the function already takes a page-size arg).
- **Add `fetch_share_messages(limit, offset=0) -> list | None`** —
  `GET /dreame-messaging/user/share-messages?version=v1&limit=<cap>&offset=0`,
  same header/retry/error pattern as the sibling fetchers; returns the raw
  record list or `None` on failure.

### 3. Refresher (`coordinator/_refreshers.py:_refresh_messages`)

Within the existing 1 h cycle, after the count update:
1. Read the cap = `entry.options.get(CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP)`.
2. Call the three fetchers; normalize via `message_record`; trim each to the cap.
3. `dataclasses.replace(self.data, device_messages=…, service_messages=…,
   shared_messages=…)` (plus the existing count fields) and
   `async_set_updated_data` if changed.
A `None`/failed fetch leaves that list at its previous value (others proceed).

### 4. State (`mower/state.py`)

Three new fields on `MowerState`, each `list` of message dicts (serialized form
of `Message`), defaulting to empty list/`None`:
`device_messages`, `service_messages`, `shared_messages`.

### 5. Sensors (`entities/sensor/device.py`)

Three `DreameA2Sensor` descriptors on the **parent** device, mirroring the
`patrol_points` pattern:

| entity_id | state | `items` attr |
|---|---|---|
| `sensor.dreame_a2_mower_device_messages` | unread count | device list |
| `sensor.dreame_a2_mower_service_messages` | unread count | service list |
| `sensor.dreame_a2_mower_shared_messages` | unread count | sharing list |

- **state = unread count**, falling back to total count where a source lacks a
  read flag.
- `items` = the capped, normalized list (`[{id,title,date,body,link,unread}]`).
- `_unrecorded_attributes = frozenset({"*"})` (lists can be long; keep them out
  of the recorder — same precedent as the photo-gallery sensors).
- `entity_category = DIAGNOSTIC`.

The existing `service_messages_unread` / `system_messages_unread` /
`latest_message` count surface is unchanged.

### 6. Config — the cap

- New const `CONF_MESSAGES_KEEP = "messages_keep"` + `DEFAULT_MESSAGES_KEEP = 100`
  in `const.py`.
- New integer field in the options flow (`config_flow.py`) next to the existing
  `CONF_*_ARCHIVE_KEEP` fields.
- Applied identically to all three lists (fetch page size + post-fetch trim).
- Rationale for a generous default: message records are tiny (a URL or 1–2
  sentences), so keeping ~100 per list costs little. [user direction 2026-06-15]

### 7. Dashboard — the "Info" view

A new view appended to `/config/dashboards/mower/dashboard.yaml`:
- `title: Info`, `icon: mdi:message-text`, `path: info`.
- Three **markdown cards** (Device / Service / Sharing). Each card's Jinja loops
  `state_attr('sensor.dreame_a2_mower_<x>_messages','items')` and renders per
  row: `●` (unread) / `○` (read) · **title** · date · body snippet ·
  `[link](url)` when present. Card title shows the unread count
  (`{{ states('sensor…') }}`). Empty list → "No messages".
- Deployed via the standard SCP procedure (backup first, browser-reload, no HA
  restart). Not version-controlled in this repo.

## Error handling

- Each fetcher returns `None` (HTTP error / parse failure) following the
  existing pattern; the refresher skips updating that one list, leaving its last
  value; the other two proceed independently.
- Normalizers tolerate missing keys (defensive `.get`), never raise; a record
  that can't be normalized is skipped (logged at DEBUG), not fatal.
- An empty or missing list renders an empty card, never an error card.
- No exception from this feature reaches the `DataUpdateCoordinator` loop.

## Testing

- `tests/protocol/test_message_record.py` — `normalize_service` /
  `normalize_device` / `normalize_share` against captured fixtures: correct
  field mapping, newest-first ordering, unread counting, robustness to missing
  keys.
- `tests/.../test_fetch_share_messages` — once the share-messages shape is
  captured (parser + a recorded fixture).
- Sensor wiring test — state = unread count, `items` shape, `_unrecorded_attributes`.
- `CONF_MESSAGES_KEEP` options-flow test (default 100; cap trims each list).
- `entity-inventory.yaml` rows for the 3 sensors + matching
  `tools/state_machine/state_machine_audit_expectations.yaml` rows (idle +
  reboot yellows) so `tests/audit` stays green (recurring gotcha).

## Done when

1. The three fetchers return their lists; `protocol/message_record.py` normalizes
   them; `_refresh_messages` trims to `CONF_MESSAGES_KEEP` and writes the three
   `MowerState` fields.
2. The three read-only sensors expose state = unread count + `items` list.
3. `CONF_MESSAGES_KEEP` is configurable via the options flow (default 100).
4. The dashboard "Info" view renders the three markdown cards on the live
   dashboard (Device / Service / Sharing).
5. The share-messages record shape is confirmed by a live capture and its parser
   + fixture finalized (the one `[UNKNOWN — to capture]` in this design).
6. Full test suite green; `entity-inventory.yaml` + audit expectations updated;
   `inventory.yaml` § message_record_and_messaging_endpoints gets a verification
   noting the list surfaces now wired (+ the share-messages shape once captured).
7. The "Probe `message-record/list` for the System/Sharing/Service/Activity
   tabs" item in `docs/TODO.md` is moved to `OLD/.../DONE.md`.

## Open question carried into the plan

- **share-messages record shape** `[UNKNOWN — to capture]` — confirm field names
  (title / date / body / link / read-flag) via a live `GET …/share-messages`
  before finalizing `normalize_share`. This is the only unverified wire surface;
  service + device are known.
