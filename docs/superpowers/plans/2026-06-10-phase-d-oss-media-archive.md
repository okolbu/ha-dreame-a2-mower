# Phase D — OSS media archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Archive the device's OSS media (photos + videos) via the canonical `userDidOssList` gallery, categorize photos by embedded COM metadata, expose them minimally in HA, add a storage-quota sensor, and cap disk per type.

**Architecture:** New cloud fetchers (`list_oss_media`, `fetch_oss_quota`) + a pure JPEG-COM metadata parser feed a reworked `PhotoArchive` (canonical source, per-category retention, category+detection on `ArchivedPhoto`) and a new `VideoArchive`. A periodic `_refresh_oss_gallery` syncs new items; sensors/cameras surface them.

**Tech Stack:** Python, vanilla pytest venv (`/data/claude/homeassistant/.venv-vanilla/bin/python`), inventory + state-machine-audit validators.

**Spec:** `docs/superpowers/specs/2026-06-10-phase-d-oss-media-archive-design.md`

**Captured shapes (2026-06-09):**
- `POST /dreame-user-iot/iotoss/userDidOssList?current=1&size=12` body `{did, type:"jpg"|"thumb", sign, timestamp}`.
- Photo record: `{id, type:"jpg", category, filepath:<signed jpg URL>, fileSize, uploadTime, key, ext, videoPath:""}`.
- Video record (`type:"thumb"`): `{id, type:"thumb", filepath:<signed thumb-jpg URL>, ext:"{\"duration\":18}", videoPath:<signed mp4 URL>, fileSize, uploadTime, key}`.
- `POST /dreame-user-iot/iotoss/checkDevOssStorage` → `{data:{total:"209715200", used:"<bytes>"}}`.
- COM metadata: JPEG `FFFE` marker → base64 JSON `{d:[{c,f,x,y,w,h}], o, s, sub}` (o=107 patrol / o=100 mow-obstacle).

**Existing code to reuse:**
- `cloud_client/_fetchers.py:fetch_device_messages` — the dreame-auth HTTP pattern (`self._session`, headers from strings, `get_api_url()`, `_key_expire`→login() guard). The two new POSTs MIRROR this (JWT-header auth).
- `cloud_client/_oss.py:get_file(url)` — fetch bytes from a signed OSS URL.
- `archive/photos.py` — `PhotoArchive(root, retention, max_bytes)`, `add(...)`, `_enforce_retention`, `_enforce_size_cap`, `load_index`, `count`, `has(md5)`, `latest`; `ArchivedPhoto(filename,name,unix_ts,size_bytes,md5,is_person)`.
- `coordinator/_lidar_oss.py:fetch_photos_from_summary` (per-session source — becomes a trigger into the gallery sync); `coordinator/_core.py:238` `_photo_sign_fn`.
- `const.py`: `CONF_PHOTO_ARCHIVE_KEEP`/`MAX_MB`, `DEFAULT_PHOTO_ARCHIVE_KEEP=200`/`MAX_MB=50`.

**⚠ TOP RISK — request signing:** the captured `userDidOssList`/`checkDevOssStorage` bodies carry `sign`+`timestamp` (the app's scheme). The integration authenticates miio HTTP via dreame-auth JWT headers (no body sign) and that works for the sibling `device-messages` endpoint. **Implement header-auth (no body sign) first.** If the live server rejects the iotoss POSTs without a body `sign`, that's a documented follow-up (RE the sign algorithm) — surface it, don't guess. Tests validate the RESPONSE parsing regardless.

**Conventions:** Python = the venv path above. Stage by explicit path (never `git add -A`). Co-Authored-By trailer for Claude Opus 4.8. **Tests use FAKE OSS URLs + a synthetic COM JPEG — never commit real photo/video bytes or real signed URLs.** Branch is `phase-d-oss-media-archive`.

---

### Task 1: Cloud fetchers — list_oss_media + fetch_oss_quota

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py`
- Test: `tests/integration/test_oss_gallery_fetchers.py` (create)

- [ ] **Step 1: Read** `fetch_device_messages` (~L539) for the exact dreame-auth header/session block to copy.

- [ ] **Step 2: Write the failing test** (`tests/integration/test_oss_gallery_fetchers.py`):
```python
from types import SimpleNamespace
from unittest.mock import MagicMock
from custom_components.dreame_a2_mower.cloud_client import _fetchers


def _client(json_body):
    c = _fetchers._FetchersMixin()
    resp = SimpleNamespace(status_code=200, json=lambda: json_body, text="")
    c._session = SimpleNamespace(post=MagicMock(return_value=resp), get=MagicMock(return_value=resp))
    c.get_api_url = lambda: "https://eu.iot.dreame.tech"
    c._ensure_strings = lambda: None
    c.strings = ["" for _ in range(60)]
    c.did = 123
    return c


def test_list_oss_media_jpg_records():
    body = {"code": 0, "success": True, "data": {"records": [
        {"id": "1", "type": "jpg", "filepath": "https://fake/oss/a.jpg", "uploadTime": "2026-06-08 21:07:08", "videoPath": "", "ext": "0", "fileSize": 100, "key": "0"},
    ]}}
    c = _client(body)
    recs = c.list_oss_media("jpg")
    assert recs and recs[0]["id"] == "1" and recs[0]["filepath"] == "https://fake/oss/a.jpg"


def test_list_oss_media_thumb_records():
    body = {"code": 0, "success": True, "data": {"records": [
        {"id": "9", "type": "thumb", "filepath": "https://fake/oss/t.jpg", "videoPath": "https://fake/oss/v.mp4", "ext": "{\"duration\":18}", "uploadTime": "2026-06-09 18:42:13", "fileSize": 100, "key": "k"},
    ]}}
    recs = _client(body).list_oss_media("thumb")
    assert recs[0]["videoPath"] == "https://fake/oss/v.mp4"


def test_fetch_oss_quota():
    c = _client({"code": 0, "success": True, "data": {"total": "209715200", "used": "45898604"}})
    q = c.fetch_oss_quota()
    assert q == {"total": 209715200, "used": 45898604}
```
(`data.records` may be `records` at top level in some firmwares — the impl tolerates both, like message-record did.)

- [ ] **Step 3: Run, expect fail.**
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_oss_gallery_fetchers.py -q`

- [ ] **Step 4: Implement** in `_FetchersMixin` (copy `fetch_device_messages`' real header block where `<headers>` appears; include the `_key_expire`→login guard):
```python
    def list_oss_media(self, media_type: str, *, size: int = 12, max_pages: int = 20) -> list | None:
        """List OSS media via iotoss/userDidOssList. media_type 'jpg' (photos) or
        'thumb' (videos). Returns all records (paged) or None on failure.
        Records carry server-signed `filepath` (+ `videoPath` for thumb)."""
        import time
        if getattr(self, "_key_expire", None) and time.time() > self._key_expire:
            self.login()
        out: list = []
        for page in range(1, max_pages + 1):
            try:
                url = f"{self.get_api_url()}/dreame-user-iot/iotoss/userDidOssList?current={page}&size={size}"
                resp = self._session.post(url, headers=<headers like fetch_device_messages>,
                                          json={"did": str(self.did), "type": media_type}, timeout=10)
                if resp.status_code != 200:
                    return out or None
                body = resp.json()
            except Exception as ex:  # pragma: no cover
                _LOGGER.warning("list_oss_media(%s): %s", media_type, ex)
                return out or None
            recs = ((body or {}).get("data") or {}).get("records")
            if recs is None:
                recs = (body or {}).get("records")
            if not recs:
                break
            out.extend(recs)
            if len(recs) < size:
                break
        return out or None

    def fetch_oss_quota(self) -> dict | None:
        """OSS storage quota via iotoss/checkDevOssStorage → {total, used} (bytes)."""
        import time
        if getattr(self, "_key_expire", None) and time.time() > self._key_expire:
            self.login()
        try:
            url = f"{self.get_api_url()}/dreame-user-iot/iotoss/checkDevOssStorage"
            resp = self._session.post(url, headers=<headers like fetch_device_messages>,
                                      json={"did": str(self.did)}, timeout=10)
            if resp.status_code != 200:
                return None
            data = (resp.json() or {}).get("data") or {}
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_oss_quota: %s", ex)
            return None
        try:
            return {"total": int(data["total"]), "used": int(data["used"])}
        except (KeyError, TypeError, ValueError):
            return None
```

- [ ] **Step 5: Run, expect pass.** Then `… -m pytest tests/ -k "fetch or cloud_client or oss" -q` (regression).

- [ ] **Step 6: Commit**
```bash
git add custom_components/dreame_a2_mower/cloud_client/_fetchers.py tests/integration/test_oss_gallery_fetchers.py
git commit -m "feat(d): list_oss_media + fetch_oss_quota cloud fetchers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: JPEG COM metadata parser

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/photo_meta.py`
- Test: `tests/protocol/test_photo_meta.py` (create)

- [ ] **Step 1: Write the failing test** (`tests/protocol/test_photo_meta.py`) — builds a SYNTHETIC JPEG with an FFFE COM marker:
```python
import base64, json, struct
from custom_components.dreame_a2_mower.protocol import photo_meta


def _jpeg_with_com(meta: dict) -> bytes:
    payload = base64.b64encode(json.dumps(meta).encode()).decode().encode()
    seg = payload + b"\x00"  # COM data
    length = len(seg) + 2
    return b"\xff\xd8" + b"\xff\xfe" + struct.pack(">H", length) + seg + b"\xff\xd9"


def test_parse_jpeg_com_extracts_detections_and_opcode():
    meta = {"d": [{"c": "person", "f": 0.81, "x": 1, "y": 2, "w": 3, "h": 4}], "o": 107, "s": 5, "sub": 35}
    out = photo_meta.parse_jpeg_com(_jpeg_with_com(meta))
    assert out["o"] == 107 and out["s"] == 5 and out["sub"] == 35
    assert out["detections"][0]["cls"] == "person"
    assert abs(out["detections"][0]["conf"] - 0.81) < 1e-6
    assert out["detections"][0]["x"] == 1 and out["detections"][0]["w"] == 3


def test_parse_jpeg_com_none_when_absent():
    assert photo_meta.parse_jpeg_com(b"\xff\xd8\xff\xd9") is None
    assert photo_meta.parse_jpeg_com(b"not a jpeg") is None
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement** `protocol/photo_meta.py`:
```python
"""Parse the Dreame embedded-JPEG COM (FFFE) metadata block.

The app stores AI-detection metadata in the JPEG COM marker as base64 JSON:
  {"d":[{"c":<class>,"f":<conf 0-1>,"x","y","w","h"}], "o":<opcode>, "s", "sub"}
o=107 patrol, o=100 mow/obstacle. Returns a normalized dict or None.
"""
from __future__ import annotations

import base64
import json
import struct
from typing import Any

_SOI = b"\xff\xd8"
_COM = b"\xff\xfe"


def parse_jpeg_com(data: Any) -> dict | None:
    """Return {detections:[{cls,conf,x,y,w,h}], o, s, sub} from the JPEG's COM
    marker, or None if absent/malformed."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 4 or data[:2] != _SOI:
        return None
    i = 2
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            break
        marker = data[i:i + 2]
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker == _COM:
            seg = data[i + 4:i + 2 + seg_len]
            try:
                raw = base64.b64decode(seg.split(b"\x00", 1)[0])
                meta = json.loads(raw)
            except (ValueError, TypeError):
                return None
            dets = []
            for d in meta.get("d") or []:
                if isinstance(d, dict):
                    dets.append({"cls": d.get("c"), "conf": d.get("f"),
                                 "x": d.get("x"), "y": d.get("y"),
                                 "w": d.get("w"), "h": d.get("h")})
            return {"detections": dets, "o": meta.get("o"),
                    "s": meta.get("s"), "sub": meta.get("sub")}
        # SOS (FFDA) → start of scan; no COM before image data
        if marker == b"\xff\xda":
            break
        i += 2 + seg_len
    return None
```

- [ ] **Step 4: Run, expect pass. Step 5: Commit**
```bash
git add custom_components/dreame_a2_mower/protocol/photo_meta.py tests/protocol/test_photo_meta.py
git commit -m "feat(d): JPEG COM metadata parser (detections + activity opcode)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: PhotoArchive — category + detection + per-category retention

**Files:**
- Modify: `custom_components/dreame_a2_mower/archive/photos.py`
- Modify: `custom_components/dreame_a2_mower/const.py` (defaults; no new conf key needed for photos)
- Test: `tests/protocol/test_photo_archive_category.py` (create)

- [ ] **Step 1: Read** `archive/photos.py` fully (`ArchivedPhoto`, `PhotoArchive.add`, `_enforce_retention`).

- [ ] **Step 2: Write the failing test** (`tests/protocol/test_photo_archive_category.py`):
```python
from pathlib import Path
from custom_components.dreame_a2_mower.archive.photos import PhotoArchive, ArchivedPhoto


def test_archived_photo_has_category_and_detection_roundtrip():
    p = ArchivedPhoto(filename="f", name="n", unix_ts=1, size_bytes=2, md5="m",
                      is_person=False, category="patrol", detection={"cls": "person", "conf": 0.8})
    d = p.to_dict()
    assert d["category"] == "patrol" and d["detection"]["cls"] == "person"
    assert ArchivedPhoto.from_dict(d).category == "patrol"


def test_from_dict_defaults_category_for_legacy_entries():
    legacy = {"filename": "f", "name": "n", "unix_ts": 1, "size_bytes": 2, "md5": "m", "is_person": True}
    p = ArchivedPhoto.from_dict(legacy)
    assert p.category == "person"  # is_person → person; else obstacle
    assert p.detection is None


def test_per_category_retention(tmp_path: Path):
    arch = PhotoArchive(tmp_path)
    arch.set_per_category_retention(2)
    for i in range(4):
        arch.add(b"\xff\xd8\xff\xd9", name=f"ob{i}", unix_ts=i, is_person=False, category="obstacle")
    for i in range(3):
        arch.add(b"\xff\xd8\xff\xd9", name=f"pa{i}", unix_ts=100 + i, is_person=False, category="patrol")
    assert arch.count_by_category("obstacle") == 2
    assert arch.count_by_category("patrol") == 2
```

- [ ] **Step 3: Run, expect fail. Step 4: Implement** in `archive/photos.py`:
- Add `category: str = "obstacle"` and `detection: dict | None = None` to `ArchivedPhoto` (dataclass fields + `to_dict` + `from_dict`). In `from_dict`, default category: if `d.get("category")` present use it; elif `is_person` → `"person"`; else `"obstacle"`.
- Extend `PhotoArchive.add(...)` signature with `category: str = "obstacle"`, `detection: dict | None = None`; store them on the `ArchivedPhoto`.
- Add `set_per_category_retention(self, keep: int)` (store `self._per_cat`), `count_by_category(self, cat)`, and a `_enforce_per_category_retention()` that, per category, keeps the `keep` newest (by unix_ts) and deletes file+index entry for the rest. Call it from `add` after the existing `_enforce_retention`/`_enforce_size_cap`.
- (Keep the existing global retention/max_bytes as a backstop.)

- [ ] **Step 5: Run, expect pass + photo-archive regression** (`… -m pytest tests/ -k "photo" -q`). Update any existing PhotoArchive test that constructs `ArchivedPhoto` without the new fields (defaults make them optional, so likely none).

- [ ] **Step 6: Commit**
```bash
git add custom_components/dreame_a2_mower/archive/photos.py custom_components/dreame_a2_mower/const.py tests/protocol/test_photo_archive_category.py
git commit -m "feat(d): PhotoArchive category + detection + per-category retention

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: VideoArchive

**Files:**
- Create: `custom_components/dreame_a2_mower/archive/videos.py`
- Modify: `custom_components/dreame_a2_mower/const.py` (`CONF_VIDEO_ARCHIVE_KEEP`/`MAX_MB` + defaults)
- Test: `tests/protocol/test_video_archive.py` (create)

- [ ] **Step 1: Write the failing test** (`tests/protocol/test_video_archive.py`):
```python
from pathlib import Path
from custom_components.dreame_a2_mower.archive.videos import VideoArchive, ArchivedVideo


def test_add_video_stores_thumb_and_mp4(tmp_path: Path):
    arch = VideoArchive(tmp_path, retention=10)
    v = arch.add(video_id="9", mp4=b"MP4DATA", thumb=b"\xff\xd8\xff\xd9", unix_ts=5, duration=18)
    assert v is not None and v.duration == 18
    assert (tmp_path / v.mp4_filename).read_bytes() == b"MP4DATA"
    assert (tmp_path / v.thumb_filename).exists()
    assert arch.has("9")


def test_retention_prunes_mp4_and_thumb_together(tmp_path: Path):
    arch = VideoArchive(tmp_path, retention=2)
    for i in range(4):
        arch.add(video_id=str(i), mp4=b"M", thumb=b"\xff\xd8\xff\xd9", unix_ts=i, duration=1)
    assert arch.count == 2
    # only the 2 newest remain on disk
    remaining = {p.name for p in tmp_path.glob("*.mp4")}
    assert len(remaining) == 2
```

- [ ] **Step 2: Run, expect fail. Step 3: Implement** `archive/videos.py` mirroring `PhotoArchive` (load_index/_save_index/has(video_id)/count/latest; `ArchivedVideo(video_id, mp4_filename, thumb_filename, unix_ts, duration, size_bytes)` with to_dict/from_dict). `add(video_id, mp4, thumb, unix_ts, duration)` writes `<video_id>.mp4` + `<video_id>.jpg`, appends index, enforces `retention` (keep N newest, delete BOTH files), enforces `max_bytes`. `has(video_id)` dedups. (Copy PhotoArchive's structure; videos prune mp4+thumb atomically.)
- Add `CONF_VIDEO_ARCHIVE_KEEP`/`CONF_VIDEO_ARCHIVE_MAX_MB` + `DEFAULT_VIDEO_ARCHIVE_KEEP = 10`, `DEFAULT_VIDEO_ARCHIVE_MAX_MB = 100` to `const.py`.

- [ ] **Step 4: Run, expect pass. Step 5: Commit**
```bash
git add custom_components/dreame_a2_mower/archive/videos.py custom_components/dreame_a2_mower/const.py tests/protocol/test_video_archive.py
git commit -m "feat(d): VideoArchive (thumb+mp4+duration, paired retention)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Coordinator gallery sync (`_refresh_oss_gallery`)

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py` (or wherever the photo archive helpers live)
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` (instantiate VideoArchive + register the refresher)
- Test: `tests/integration/test_oss_gallery_sync.py` (create)

- [ ] **Step 1: Read** `coordinator/_core.py` ~L226-240 (PhotoArchive instantiation + `_photo_sign_fn`) and the refresher-registration block (~L505-555 pattern from Phase C). Read `coordinator/_lidar_oss.py:fetch_photos_from_summary` + `photo_archive` property.

- [ ] **Step 2: Write the failing test** (`tests/integration/test_oss_gallery_sync.py`) — stub cloud + archives, assert new items archived + categorized:
```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from custom_components.dreame_a2_mower.coordinator._lidar_oss import _LidarOssMixin


def _coord(photos, videos, quota):
    c = _LidarOssMixin()
    c._cloud = SimpleNamespace(
        list_oss_media=MagicMock(side_effect=lambda t, **k: photos if t == "jpg" else videos),
        fetch_oss_quota=MagicMock(return_value=quota),
        get_file=MagicMock(return_value=b"\xff\xd8\xff\xd9"),
    )
    c._photo_archive = MagicMock(has=MagicMock(return_value=False), count_by_category=MagicMock(return_value=0))
    c._video_archive = MagicMock(has=MagicMock(return_value=False), count=0)
    c.data = SimpleNamespace()
    async def _exec(fn, *a): return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    c.async_set_updated_data = lambda s: setattr(c, "data", s)
    return c


@pytest.mark.asyncio
async def test_gallery_sync_archives_new_photo_and_video():
    photos = [{"id": "p1", "filepath": "https://fake/a_person.jpg", "uploadTime": "2026-06-08 21:07:08", "videoPath": ""}]
    videos = [{"id": "v1", "filepath": "https://fake/t.jpg", "videoPath": "https://fake/v.mp4", "ext": "{\"duration\":18}", "uploadTime": "2026-06-09 18:42:13"}]
    c = _coord(photos, videos, {"total": 209715200, "used": 1000})
    await c._refresh_oss_gallery()
    c._photo_archive.add.assert_called()   # at least one photo archived
    c._video_archive.add.assert_called()   # at least one video archived
    assert c.data.oss_storage_used == 1000 and c.data.oss_storage_total == 209715200
```
(Adapt the mixin name/attrs to the real `_lidar_oss.py` class. Add MowerState fields `oss_storage_used`/`oss_storage_total` in this task too — small dataclass addition.)

- [ ] **Step 3: Implement `_refresh_oss_gallery`** in `_lidar_oss.py`:
  - `list_oss_media("jpg")` → for each record not `_photo_archive.has(...)` (dedup by record `id` — add an `has_id`/use name): fetch bytes via `get_file(filepath)`, parse COM via `photo_meta.parse_jpeg_com`, categorize (name endswith `_person.jpg` → person; elif meta o==107 → patrol; else obstacle), `detection` = first meta detection; `_photo_archive.add(bytes, name=<leaf>, unix_ts=<from uploadTime or name>, is_person=, category=, detection=)`.
  - `list_oss_media("thumb")` → for each not `_video_archive.has(id)`: fetch thumb bytes (`get_file(filepath)`) + mp4 bytes (`get_file(videoPath)`), parse duration from `ext` (`json.loads(ext).get("duration")`), `_video_archive.add(video_id=id, mp4=, thumb=, unix_ts=, duration=)`.
  - `fetch_oss_quota()` → set MowerState `oss_storage_used`/`oss_storage_total`.
  - Dedup: PhotoArchive currently dedups by md5 (`has(md5)`); for the gallery, prefer dedup by the OSS record `id` or the object name (stable). Add an `has_name(name)` to PhotoArchive (Task 3) if md5-only is insufficient — or compute md5 of fetched bytes and use `has(md5)`. Pick the simplest correct dedup and note it.
  - Run blocking I/O via `hass.async_add_executor_job`.
- **Step 4: `_core.py`** — instantiate `self._video_archive = VideoArchive(<config>/videos, retention=DEFAULT_VIDEO_ARCHIVE_KEEP, max_bytes=...)`; set photo per-category retention via `set_per_category_retention`; register `_refresh_oss_gallery` on a 1h `async_track_time_interval` + initial await (Phase C pattern). Keep `fetch_photos_from_summary`'s session-end call but have it (or a small wrapper) trigger `_refresh_oss_gallery` (so session-end still kicks an immediate sync) — OR leave the per-session fetch as-is and let the 1h sync be canonical; choose the cleaner integration and note it.

- [ ] **Step 5: Run + regression** (`… -m pytest tests/integration/test_oss_gallery_sync.py tests/ -k "oss or photo or lidar or coordinator" -q`).

- [ ] **Step 6: Commit**
```bash
git add custom_components/dreame_a2_mower/coordinator/_lidar_oss.py custom_components/dreame_a2_mower/coordinator/_core.py custom_components/dreame_a2_mower/mower/state.py tests/integration/test_oss_gallery_sync.py
git commit -m "feat(d): _refresh_oss_gallery canonical sync (photos+videos+quota)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Sensors — quota + per-type counts + latest-video

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor_device.py` (or a sensor file reading archives)
- Test: `tests/integration/test_oss_sensors.py` (create)

- [ ] **Step 1: Read** how existing sensors that read archives/coordinator (not MowerState) are built (e.g. wifi_rssi reads `coord.state_machine`; some sensors take a coordinator). Determine the pattern for a sensor whose value comes from `coordinator._photo_archive`/`_video_archive` or MowerState `oss_storage_*`.

- [ ] **Step 2: Add sensors** (mirror the closest existing pattern):
  - `oss_storage_used` (MB, from `s.oss_storage_used`), `oss_storage_total` (MB), `oss_storage_pct` (used/total*100).
  - `photos_obstacle` / `photos_patrol` / `photos_person` → `coordinator._photo_archive.count_by_category(<cat>)`.
  - `videos` → `coordinator._video_archive.count`.
  - `latest_video` → latest `ArchivedVideo` duration as state, with mp4 path as an attribute.
  All `EntityCategory.DIAGNOSTIC`.

- [ ] **Step 3: Test** (`tests/integration/test_oss_sensors.py`): construct each descriptor/entity with a stub coordinator/state and assert the value (quota pct math; counts read the archive; latest_video reads the archive). Use the `value_fn` or entity pattern the file uses.

- [ ] **Step 4: Run + commit**
```bash
git add custom_components/dreame_a2_mower/sensor_device.py tests/integration/test_oss_sensors.py
git commit -m "feat(d): OSS quota + per-type count + latest-video sensors

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Cameras — latest-video thumb + metadata attributes

**Files:**
- Modify: `custom_components/dreame_a2_mower/_camera_photos.py`
- Modify: `custom_components/dreame_a2_mower/camera.py` (register the new camera)
- Test: `tests/integration/test_oss_camera.py` (create)

- [ ] **Step 1: Read** `_camera_photos.py` (`_BasePhotoCamera`, `DreameA2AlbumPhotoCamera`, `DreameA2PersonPhotoCamera`).

- [ ] **Step 2: Add** `DreameA2LatestVideoThumbCamera(_BasePhotoCamera-like)` whose `async_camera_image` returns the latest `ArchivedVideo`'s thumb bytes from `coordinator._video_archive` (mirror `_latest_bytes`). Register it in `camera.py`'s `async_setup_entry`.

- [ ] **Step 3: Add metadata attributes** to the album/person cameras: an `extra_state_attributes` returning the latest photo's `category` + `detection` (cls/conf) from its `ArchivedPhoto` (the cameras already resolve `_latest_entry()`).

- [ ] **Step 4: Test** (`tests/integration/test_oss_camera.py`): stub coordinator with a `_video_archive` returning a latest video with thumb bytes → camera image returns them; album camera `extra_state_attributes` exposes category/detection. Use `object.__new__` construction if needed.

- [ ] **Step 5: Run + commit**
```bash
git add custom_components/dreame_a2_mower/_camera_photos.py custom_components/dreame_a2_mower/camera.py tests/integration/test_oss_camera.py
git commit -m "feat(d): latest-video thumb camera + photo detection attributes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Inventory + entity-inventory + audit + TODO

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify: `tools/state_machine/state_machine_audit_expectations.yaml` + `state_machine_audit_checks.py` (if new orphan fields)
- Modify: `docs/research/knowledge-gaps.md`

- [ ] **Step 1: inventory.yaml** — userDidOssList / checkDevOssStorage / embedded-JPEG-metadata / video are already `verified` (Phase 0). Append `status: verified` verifications (date 2026-06-10, evidence `app-mitm:2026-06-09-settings-sweep`) that they're now **wired + surfaced** (canonical gallery sync, COM parse, video archive, quota sensor). Note the per-session `photo_list` fetch is now subordinate. Bump `last_seen`.

- [ ] **Step 2: entity-inventory.yaml** — add entries for the new sensors (quota×3, counts×3, videos, latest_video) + the latest-video camera; update the album/person camera source to canonical userDidOssList. `last_verified: "2026-06-10"`.

- [ ] **Step 3: state-machine audit** — new MowerState fields `oss_storage_used`/`oss_storage_total` are sensor-surfaced (add expectations.yaml rows for the quota sensors). Any archive-backed sensor reads the coordinator (not MowerState) so no orphan-field issue, but VERIFY: run the audit and fix any new orphan (register sensor-surfaced state fields in expectations; archive-read sensors need no MowerState field). Mirror the Phase C fix.

- [ ] **Step 4: knowledge-gaps.md TODO** — add `[UNKNOWN — to capture]`: type-3 map-icon→photo association wire (live-session probe: click an obstacle icon mid-session, capture the request); bytes already archived via userDidOssList. Also note the **request-signing open question** (whether iotoss POSTs need the body `sign` or accept JWT-header auth — to confirm live) and mp4 `media_source` registration as a follow-up.

- [ ] **Step 5: Validate**
```
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/audit_outstanding_retractions.py
/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/ tests/audit/ -q
```
Expected: validator ok; entity audit 0 missing; retraction audit clean; inventory + audit tests green.

- [ ] **Step 6: Commit**
```bash
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml tools/state_machine/ docs/research/knowledge-gaps.md
git commit -m "inventory(d): record OSS media archive wired+surfaced; audit + TODO (type-3, signing, media_source)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Full suite + final verification

**Files:** none (verification only)

- [ ] **Step 1: Full suite** — `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q` → 0 failures, 4 skipped; passed count ≥ baseline + new D tests.
- [ ] **Step 2: Inventory + audit gates** — `inventory_gen.py --validate-only`; `inventory_audit.py --consistency`; `entity_inventory_audit.py`; `audit_outstanding_retractions.py`; `tests/audit/` — all clean.
- [ ] **Step 3: Sensitive-data sweep** — `grep -rnE "59\.94|10\.75|8933|oss-eu-central" tests/` → no real GPS/ICCID/real-signed-URL in any test/fixture (FAKE only).
- [ ] **Step 4: Report** — new entities (sensors/cameras), that userDidOssList is the canonical source, the signing approach used (header-auth) + the live-confirm caveat, photo/video retention caps, pass/skip counts, scope (`.py` changes confined to cloud_client/_fetchers, protocol/photo_meta, archive/photos+videos, coordinator/_lidar_oss+_core, mower/state, sensor_device, _camera_photos, camera).
