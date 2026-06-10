# Phase D — OSS media archive (photos + video) (design)

**Date:** 2026-06-10
**Status:** design, awaiting user review → writing-plans
**Phase:** D of the app-integration roadmap (`docs/research/app-integration-roadmap.md`).
**Predecessors:** Phase 0, A1, A2, B, C. (Album/person *latest-photo* cameras already shipped v1.0.24a7, sourced per-session.)

## Context

The app's "Archive" page has two tabs (Photos / Videos) over the **same OSS
bucket** (`dreame-eu…/oss/media/000000/oss/<uid>/<did>/ali_dreame/<ts>[_person].jpg`),
filtered by `userDidOssList` `type`: `"jpg"` (photos) vs `"thumb"` (videos). The
integration currently archives photos only from the **session summary**
(`photo_list`) and shows latest album/person cameras. The canonical gallery
(`userDidOssList`), embedded-JPEG metadata, video (mp4), and quota are not done.

Captured shapes (2026-06-09):
- `POST iotoss/userDidOssList` body `{did, type:"jpg"|"thumb", sign, timestamp}` (signed), paged `?current&size=12`.
- Photo record: `{id, type:"jpg", category, filepath:<signed OSS jpg URL>, fileSize, uploadTime, key, ext, videoPath:""}`.
- Video record (`type:"thumb"`): `{id, type:"thumb", filepath:<signed thumb-jpg URL>, ext:"{\"duration\":18}", videoPath:<signed mp4 URL>, …}`.
- `POST iotoss/checkDevOssStorage` → `{data:{total:"209715200"(200MB), used:"<bytes>"}}`.
- Embedded JPEG COM marker (`FFFE`) = base64 JSON `{d:[{c,f,x,y,w,h}], o, s, sub}` (o=107 patrol, o=100 mow/obstacle).

**Three photo types (user-confirmed):** (1) AI-obstacle, (2) patrol — both in the
app archive; (3) drive-around obstacle photos, viewed by clicking live-map
obstacle icons mid-session (icon→photo link unreachable after session end). Type-3
is NOT wire-captured, BUT its bytes are in the same OSS bucket → archived via
`userDidOssList`; only the icon→photo association is missing (TODO/probe).

**Honesty basis:** the 2026-06-09 capture is the wire verification.

## Goal & scope

**Goal:** archive OSS media (photos + videos) via the canonical `userDidOssList`,
categorize photos via COM metadata, surface them minimally in HA, expose quota,
and cap disk per type.

**In scope:**
1. **Photos** — `userDidOssList type:"jpg"` = canonical archive source (absorbs the
   per-session `photo_list` fetch as the authority). Categorize: person/patrol/obstacle.
2. **COM metadata** parse (class/confidence/bbox + `o`/`s`/`sub`).
3. **Video** — `userDidOssList type:"thumb"` → archive thumb (jpg) + mp4 (`videoPath`) + duration.
4. **Quota sensor** — `checkDevOssStorage`.
5. **Per-type retention cap** — keep ≤ N per {obstacle, patrol, person, video} + max-mb backstop.

**Out of scope / TODO:** type-3 map-icon→photo association wire (live-session
probe). mp4 `media_source` registration (optional follow-up — only if trivial).

## §1 Architecture

**`cloud_client/`:**
- `list_oss_media(media_type: str, *, current=1, size=12) -> list[dict] | None` —
  POST `iotoss/userDidOssList` with the signed body `{did, type, sign, timestamp}`,
  returns records. `media_type` ∈ `{"jpg","thumb"}`. Pages until a short page.
  Reuses the existing request signer (`_photo_sign_fn` / sendCommand signing).
- `fetch_oss_quota() -> dict | None` — POST `iotoss/checkDevOssStorage` →
  `{total:int, used:int}`.
- Existing `get_file(signed_url) -> bytes` fetches OSS bytes (already used).

**`protocol/photo_meta.py` (new):** pure `parse_jpeg_com(data: bytes) -> dict | None`
— scan for the `FFFE` COM marker, base64-decode the JSON payload, return
`{detections:[{cls,conf,x,y,w,h}], o, s, sub}` (None if absent/malformed).

**`archive/`:**
- `PhotoArchive` reworked: canonical source = `userDidOssList`. `ArchivedPhoto`
  gains `category: str` ("person"|"patrol"|"obstacle") and `detection: dict|None`
  (top class/conf). Per-type retention.
- `VideoArchive` (new, mirrors PhotoArchive): stores thumb jpg + mp4 + `duration`;
  index keyed by record `id`/`key`; per-type-N retention; prunes thumb+mp4 together.

**`coordinator/`:**
- `_refresh_oss_gallery` (1h periodic + immediate kick on session-end): list `jpg`
  + `thumb`, diff vs archive by record `id`, fetch+archive new (parse COM for
  photos), enforce caps. Absorbs `fetch_photos_from_summary` as the authority
  (keep a session-end trigger that calls the gallery sync).

**Entities:**
- Keep existing latest-album + latest-person cameras (now from the canonical
  archive; add detected-class/confidence attributes).
- Add: latest-video thumb camera; quota sensor (`oss_storage_used`/`_total`/`_pct`);
  per-type count sensors (`photos_obstacle`/`photos_patrol`/`photos_person`/`videos`);
  latest-video sensor (duration + local mp4 path; signed-URL attribute).

## §2 Categorization

Per photo, in order:
1. name ends `_person.jpg` → **person**.
2. else COM `o == 107` → **patrol**.
3. else (`o == 100` / other / no COM) → **obstacle** (includes type-3 bytes).

`detection` = the first/top `d[]` entry's `c` (class) + `f` (confidence), kept for
camera attributes; bbox retained.

## §3 Presentation (minimal — revisit after wiring)

- Cameras: latest-album, latest-person (existing, metadata-enriched), latest-video-thumb (new).
- Sensors: quota (used/total/pct); per-type counts; latest-video (duration + mp4 path).
- NO per-type *latest* cameras (decided minimal; revisit once live).
- mp4: archived to disk; sensor exposes path/duration (+ signed URL attr). HA can't
  inline-play mp4 in a camera; `media_source` registration is an optional follow-up.

## §4 Retention (per-type disk cap)

- Per-category keep-count N: keep ≤ N most-recent of {obstacle, patrol, person}
  (photos) and ≤ Nv videos, plus the existing global `max-mb` backstop.
- Config: extend `CONF_PHOTO_ARCHIVE_KEEP`/`MAX_MB`; add `CONF_VIDEO_ARCHIVE_KEEP`
  /`MAX_MB`. Defaults: ~50/photo-type, ~10 videos (videos are large), with max-mb
  ceilings.
- Enforced on each gallery sync: after archiving, prune oldest-per-category beyond
  N and prune to fit max-mb; delete file + index entry (videos: mp4 + thumb together).

## §5 Testing (TDD)

- `list_oss_media`: request body shape (`{did,type,sign,timestamp}`) + parse jpg
  and thumb records (signed `filepath`/`videoPath`, `ext.duration`); paging.
- `parse_jpeg_com`: a **synthetic** JPEG with an `FFFE` COM marker carrying the
  base64 JSON → correct detections/o/s/sub; None when absent.
- Categorization: person (`_person.jpg`), patrol (`o=107`), obstacle (`o=100`/none).
- `PhotoArchive` per-type prune (keep N per category); `VideoArchive` add +
  paired thumb/mp4 prune; max-mb backstop.
- Quota sensor parse (used/total/pct).
- `_refresh_oss_gallery` diffs new-vs-existing by `id`; archives only new.
- **Fixtures use FAKE OSS URLs + a synthetic COM JPEG — never commit real photo/
  video bytes or real signed URLs** (the capture's are real, in the private dir).

## §6 Fact-discipline

- `inventory.yaml`: userDidOssList / checkDevOssStorage / COM-metadata / video are
  already `verified` (Phase 0) — append "now wired + surfaced" (date 2026-06-10,
  evidence `app-mitm:2026-06-09-settings-sweep`). Note the per-session
  `photo_list` fetch is now subordinate to the canonical gallery sync.
- `entity-inventory.yaml`: add the new sensors/camera; update the album/person
  camera source (now canonical userDidOssList).
- **state-machine audit**: register any new archive-surfaced MowerState/coordinator
  fields (the Phase C orphan-field gotcha — add to `_KNOWN_ATTRIBUTE_SURFACED_FIELDS`
  / expectations.yaml so `tests/audit` stays green).
- **TODO** (`knowledge-gaps.md`): type-3 map-icon→photo association wire — uncaptured;
  a live-session app-MITM probe (click an obstacle icon mid-session, capture the
  request). The bytes are already archived via userDidOssList; only the linkage is open.

## §7 Risks & edge cases

- **Sensitive data** — fake URLs + synthetic JPEG only in tests; the real capture
  (photos/, signed URLs) stays private.
- **Signing** — userDidOssList needs a signed body; reuse the existing signer; if
  the signer differs from sendCommand's, confirm during build (the capture's
  `sign` is over `{did,type,timestamp}`).
- **Signed-URL expiry** — `filepath`/`videoPath` URLs expire (`Expires=`); fetch
  bytes promptly during the sync; don't persist the URL as a long-lived reference.
- **Dedup** — diff by record `id` (stable) so re-syncs don't re-download; the
  per-session fetch and gallery sync must not double-archive (key on `id`/name).
- **Video size** — small `Nv` + max-mb; prune mp4+thumb atomically.
- **Type-3 linkage** — bytes archived, icon→photo association deferred (TODO).

## Out-of-scope follow-ups (TODO)

- Type-3 map-icon→photo association (probe).
- mp4 `media_source` registration for in-HA playback.
- Manual photo/video upload (`addOssNew`/`ossUploaded`) — that's a *capture/upload*
  flow tied to live-view (Phase G), not archival.
