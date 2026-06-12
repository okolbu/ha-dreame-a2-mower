# Photo/video gallery — dashboard tab + boot backfill

Surfaces the existing OSS photo/video archive (backend shipped: `archive/photos.py`,
`archive/videos.py`, `_refresh_oss_gallery`) as a **thumbnail-gallery dashboard tab**
(grid of thumbnails, click → large pop-out / lightbox, per-type filter, date +
AI-detection overlays), and makes the boot sync a **full backfill**.

## Part B — boot backfill (small)
`_refresh_oss_gallery` already runs hourly + once at boot (`_core.py:578`), and
`list_oss_media(media_type, size=12, max_pages=20)` pages until a short page (end)
OR `max_pages`. So the hourly/boot fetch only grabs the most-recent ≈240 items; a
fresh install with a longer cloud history loses the older tail.
- Add a `max_pages` parameter to `_refresh_oss_gallery(self, max_pages=20)` and pass
  it into both `list_oss_media(..., max_pages=max_pages)` calls.
- In `_core.py`, the **boot** call becomes a full backfill:
  `await self._refresh_oss_gallery(max_pages=400)` (pages to natural exhaustion —
  `list_oss_media` already stops at the first short page). The hourly periodic call
  stays at the default (recent items; the archive dedups by name/id so nothing is
  re-downloaded anyway, but a smaller hourly cap keeps it cheap).

## Part A — gallery (the dashboard tab)

### A1. HTTP views (serve archived media by id) — `_camera_views.py`, registered in `camera.py`
Add three auth-gated views (registered in the existing `_views_registered` block in
`camera.py::async_setup_entry`). Look the coordinator up per-request from
`hass.data[DOMAIN]` (mirror `MapImageView`). **Path-traversal guard:** only serve a
name/id that is PRESENT in the archive index — reject anything else with 404 (never
`open()` an arbitrary path).
- `class PhotoFileView` — `url = "/api/dreame_a2_mower/photo/{name}"`, `requires_auth = True`.
  Serve `coordinator.photo_archive.read_bytes(name)` as `image/jpeg` IF `name` is in
  `photo_archive.list_photos()` filenames; else 404.
- `class VideoThumbView` — `url = "/api/dreame_a2_mower/video_thumb/{vid}"`,
  `requires_auth = True`. Serve the thumb (`{video_archive.root}/{vid}.jpg`, via a
  `read`-by-id helper) as `image/jpeg` IF `vid` is in the index; else 404.
- `class VideoFileView` — `url = "/api/dreame_a2_mower/video/{vid}"`,
  `requires_auth = True`. Serve the mp4 (`{vid}.mp4`) as `video/mp4` IF in index; else 404.
Use `requires_auth=True` (NOT public like `map.png`) — photos can show people; access
is via SIGNED URLs (below), so `<img src>` works without an auth header but the paths
aren't world-readable. Emit `Cache-Control: private, max-age=3600` (archived media is
immutable per id).

### A2. Gallery manifest (built with signed URLs) — coordinator + a sensor
- In `_refresh_oss_gallery`, AFTER archiving, build a manifest list and store it on
  the coordinator (`self._photo_gallery`, init `[]` in `_CoreMixin.__init__`). Each
  item (newest-first by ts):
  ```
  { "type": "photo"|"video", "id": <filename|video_id>, "ts": <int>,
    "date": "<YYYY-MM-DD HH:MM>",            # local-naive from unix_ts
    "category": <photo category | "video">,  # obstacle|patrol|person for photos
    "detection": {"cls": <str>, "conf": <float 0..1>} | null,   # photos only
    "duration": <int seconds>,               # videos only (else omit/0)
    "url": <signed full-media URL>, "thumb_url": <signed thumb URL> }
  ```
  - photos: `url` = `thumb_url` = signed `/api/dreame_a2_mower/photo/<filename>` (the
    crops are small; the card CSS-scales the thumbnail and shows the same image in the
    lightbox).
  - videos: `thumb_url` = signed `/video_thumb/<id>`, `url` = signed `/video/<id>`.
  - Sign via `self.hass.http.async_sign_path(path, timedelta(days=7))` (callback, safe
    from async). 7-day window, rebuilt hourly → always fresh.
  - Source: `photo_archive.list_photos()` (filename, unix_ts, category, detection
    {cls,conf}) + `video_archive` entries (video_id, unix_ts, duration). Sort by ts desc.
- Add `sensor.dreame_a2_mower_photo_gallery` (`sensor_device.py`): state = total item
  count; `extra_state_attributes = {"items": coordinator._photo_gallery}`;
  `_unrecorded_attributes = {"*"}` (the list can be large — keep it out of the
  recorder, like `picked_session`). disabled-by-default? NO — needed by the card.
  Translation/name "Photo gallery".

### A3. Gallery card — `www/dreame-a2-photo-gallery-card.js` (bundled, vanilla element)
Config: `{ type: "custom:dreame-a2-photo-gallery-card", entity: "sensor.dreame_a2_mower_photo_gallery" }`.
- Reads `hass.states[entity].attributes.items`.
- **Filter tabs** across the top: `All` + one per distinct category present
  (Obstacle / Patrol / Person) + `Videos` (type==video). Clicking filters the grid.
- **Thumbnail grid** (responsive CSS grid, ~auto-fill minmax(120px,1fr)): one
  `<img loading="lazy" src=thumb_url>` per item, object-fit cover, fixed aspect cell.
  Overlay on each cell: bottom caption = `date` + (if `detection`) `cls conf%` (e.g.
  "human 80%"); video cells show a ▶ badge + `duration` (m:ss). Category dot/colour
  optional.
- **Lightbox / pop-out**: clicking a cell opens a fixed full-screen dimmed overlay
  centred on the large media — `<img src=url>` for photos, `<video src=url controls
  autoplay>` for videos — with the caption (date + detection) shown. Close on
  click-outside, an X button, or Esc. (Pure DOM; no deps.)
- Empty state: "No photos archived yet." Register with the `customElements.get`
  guard + `window.customCards.push` like the other bundled cards. `node --check` clean.

### A4. Dashboard tab — `dashboards/mower/dashboard.yaml`
Add a **Photos** view (panel, `mdi:image-multiple`), placed near the existing
"Photo Privacy" tab. Tab-header anchor `_tab_header_photos`. Cards:
- a small `entities`/`glance` header: `sensor.dreame_a2_mower_photos_obstacle`,
  `_photos_patrol`, `_photos_person`, `_videos`, `_oss_storage_pct` (+ used/total).
- the gallery card on `sensor.dreame_a2_mower_photo_gallery`.
(Leave the existing "Photo Privacy" tab as-is — it's the capture-consent tab.)
Resource: the new card needs a Lovelace resource entry
`/dreame_a2_mower/dreame-a2-photo-gallery-card.js` in the host `lovelace.yaml`
(yaml resource mode) — a deploy step (SSH-edit + HA restart), like the map-editor card.

## Tests
- pytest: `PhotoFileView`/`VideoThumbView`/`VideoFileView` return bytes for an
  in-index id and 404 for an unknown/traversal id (use a small temp archive +
  the per-request coordinator lookup); the gallery manifest builds the right item
  shape (photo + video) with signed-ish URLs (assert the path prefix); the backfill
  `max_pages` param is threaded into `list_oss_media` (mock the cloud, assert the
  arg). Keep the full suite green; new sensor → add a row to the state-machine-audit
  expectations if the audit test requires it (check against main; 2 yellows/sensor).
- node: `node --check www/dreame-a2-photo-gallery-card.js`; a tiny node harness that
  imports nothing (the card is a single element) — `node --check` suffices.

## Release / deploy
`release.sh` bump; SCP the new card + the changed Python to the host; add the
resource to `lovelace.yaml`; **HA restart** (Python changed + new resource); SCP the
dashboard.yaml; hard-refresh.
