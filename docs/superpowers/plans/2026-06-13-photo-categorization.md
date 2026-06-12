# Photo Categorization + Gallery Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the buggy 3-way photo categorization with a principled
7-category COM-derived scheme (video, ai_human, ai_animal, ai_object, patrol,
obstacle, manual), store the full per-detection list for a future bbox overlay,
and surface category filters in the gallery card.

**Architecture:** A pure `protocol/photo_category.py:categorize()` is the single
source of truth, called from both ingest paths (the OSS-gallery sync and the
session-end fetch). `ArchivedPhoto` stores `category` + a `detections` list. The
gallery manifest carries those through to the client card, which filters
client-side. Animal/object vocab + the obstacle/manual split are provisional
(documented), refined when a live session produces those events.

**Tech Stack:** Python 3.13 (Home Assistant custom integration), pytest, vanilla
JS web component. Test runner: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest`.

---

### Task 1: Pure categorizer module

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/photo_category.py`
- Test: `tests/protocol/test_photo_category.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/protocol/test_photo_category.py
from custom_components.dreame_a2_mower.protocol.photo_category import (
    categorize, primary_detection, HUMAN_CLASSES, ANIMAL_CLASSES,
)


def _com(o=None, dets=None):
    return {"o": o, "detections": dets or [], "s": None, "sub": None}


def test_video_by_type():
    assert categorize(name="x.jpg", record={"type": "thumb"}, com=None) == "video"


def test_video_by_videopath():
    assert categorize(name="x.jpg", record={"videoPath": "a.mp4"}, com=_com()) == "video"


def test_ai_human_from_detection():
    com = _com(o=101, dets=[{"cls": "person", "conf": 0.7}])
    assert categorize(name="1_person.jpg", record={"type": "jpg"}, com=com) == "ai_human"


def test_ai_human_during_patrol_still_ai():
    # detection takes priority over o=107 patrol activity
    com = _com(o=107, dets=[{"cls": "person", "conf": 0.8}])
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=com) == "ai_human"


def test_ai_animal_known_class():
    com = _com(o=100, dets=[{"cls": "hedgehog", "conf": 0.95}])
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=com) == "ai_animal"


def test_ai_object_unknown_class_falls_through():
    com = _com(o=100, dets=[{"cls": "wheelbarrow", "conf": 0.6}])
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=com) == "ai_object"


def test_patrol_o107_empty_detections():
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=_com(o=107)) == "patrol"


def test_obstacle_mow_mode_empty_detections():
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=_com(o=100)) == "obstacle"


def test_manual_no_com():
    assert categorize(name="1.jpg", record={"type": "jpg"}, com=None) == "manual"


def test_person_filename_fallback_when_no_detection():
    assert categorize(name="1_person.jpg", record={"type": "jpg"}, com=_com(o=101)) == "ai_human"


def test_primary_detection_is_highest_conf():
    dets = [{"cls": "a", "conf": 0.4}, {"cls": "b", "conf": 0.9}]
    assert primary_detection(dets)["cls"] == "b"


def test_vocab_membership():
    assert "person" in HUMAN_CLASSES
    assert "hedgehog" in ANIMAL_CLASSES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_photo_category.py -q`
Expected: FAIL — `ModuleNotFoundError: ... photo_category`.

- [ ] **Step 3: Write minimal implementation**

```python
# custom_components/dreame_a2_mower/protocol/photo_category.py
"""Categorize an archived photo/video from its OSS record + parsed JPEG COM.

Single source of truth for the gallery taxonomy. Derived from the 2026-06-12
live OSS probe: the server `category` field is always 0 (useless) and the COM
`o` is the *activity* during capture (107=patrol, 100-103=mow), NOT the photo
type. AI detection = a non-empty COM `detections` list; `cls` names the object.
Manual live-view snapshots have no COM.

Categories: video, ai_human, ai_animal, ai_object, patrol, obstacle, manual.

PROVISIONAL (refined once a live session produces these events):
  - ANIMAL_CLASSES is a best-guess set; any unknown `cls` falls through to
    ai_object with its raw label preserved on the item (no silent loss).
  - obstacle (o in mow modes + empty detections) vs manual (no COM) may overlap
    if normal-obstacle photos turn out to lack a COM.
"""
from __future__ import annotations

from typing import Any

HUMAN_CLASSES: frozenset[str] = frozenset({"person", "human"})

# Best-guess animal labels. Unknown labels -> ai_object (raw label kept).
ANIMAL_CLASSES: frozenset[str] = frozenset({
    "animal", "cat", "dog", "hedgehog", "bird", "rabbit", "fox", "squirrel",
    "mouse", "rat", "deer", "cow", "sheep", "horse", "goat", "pig", "chicken",
    "duck", "tortoise", "turtle", "frog", "snake", "lizard",
})

_MOW_MODES = frozenset({100, 101, 102, 103})


def primary_detection(detections: list[dict] | None) -> dict:
    """Return the highest-confidence detection (or {} if none)."""
    if not detections:
        return {}
    return max(detections, key=lambda d: (d or {}).get("conf") or 0.0)


def categorize(*, name: str | None, record: dict[str, Any], com: dict | None) -> str:
    """Return the gallery category for one media item.

    `name`   = OSS leaf filename (e.g. "1780952775_person.jpg").
    `record` = the userDidOssList record (`type`, `videoPath`, ...).
    `com`    = parsed JPEG COM (`{o, detections, s, sub}`) or None.
    """
    if (record or {}).get("type") == "thumb" or (record or {}).get("videoPath"):
        return "video"

    dets = (com or {}).get("detections") or []
    if dets:
        cls = primary_detection(dets).get("cls")
        if cls in HUMAN_CLASSES:
            return "ai_human"
        if cls in ANIMAL_CLASSES:
            return "ai_animal"
        return "ai_object"

    # No AI detection.
    if name and name.lower().endswith("_person.jpg"):
        return "ai_human"  # app-named human capture (COM detection may be absent)
    o = (com or {}).get("o")
    if o == 107:
        return "patrol"
    if o in _MOW_MODES:
        return "obstacle"
    if com is None:
        return "manual"
    return "obstacle"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_photo_category.py -q`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/photo_category.py tests/protocol/test_photo_category.py
git commit -m "feat(photos): pure photo categorizer (7-category COM-derived)"
```

---

### Task 2: ArchivedPhoto stores a detections list

**Files:**
- Modify: `custom_components/dreame_a2_mower/archive/photos.py` (the `ArchivedPhoto` dataclass + `PhotoArchive.archive`)
- Test: `tests/integration/test_oss_sensors.py` already builds archives; add a dedicated test file `tests/archive/test_photos_detections.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/archive/test_photos_detections.py
from custom_components.dreame_a2_mower.archive.photos import ArchivedPhoto, PhotoArchive


def test_archive_stores_detections_list(tmp_path):
    a = PhotoArchive(tmp_path)
    dets = [{"cls": "person", "conf": 0.7, "x": 1, "y": 2, "w": 3, "h": 4}]
    rec = a.archive(name="1_person.jpg", unix_ts=10, data=b"\xff\xd8\xff\xd9",
                    is_person=True, category="ai_human", detections=dets)
    assert rec is not None
    assert rec.detections == dets
    assert rec.category == "ai_human"


def test_from_dict_migrates_legacy_single_detection():
    # Old index rows had `detection` (singular) + coarse category.
    legacy = {"filename": "f.jpg", "name": "1_person.jpg", "unix_ts": 1,
              "size_bytes": 1, "md5": "m", "is_person": True,
              "category": "person", "detection": {"cls": "person", "conf": 0.7}}
    p = ArchivedPhoto.from_dict(legacy)
    assert p.detections == [{"cls": "person", "conf": 0.7}]
    assert p.category == "ai_human"  # 'person' migrated to 'ai_human'


def test_from_dict_legacy_no_detection():
    legacy = {"filename": "f.jpg", "name": "1.jpg", "unix_ts": 1, "size_bytes": 1,
              "md5": "m", "is_person": False, "category": "obstacle"}
    p = ArchivedPhoto.from_dict(legacy)
    assert p.detections == []
    assert p.category == "obstacle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/archive/test_photos_detections.py -q`
Expected: FAIL — `archive()` has no `detections` kwarg / `ArchivedPhoto` has no `detections`.

- [ ] **Step 3: Write minimal implementation**

In `archive/photos.py`, change the dataclass field `detection: dict | None = None`
to `detections: list[dict] | None = None`, and update `to_dict`/`from_dict`/`archive`:

```python
# In ArchivedPhoto: replace the `detection` field
    detections: list[dict] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "name": self.name,
            "unix_ts": self.unix_ts,
            "size_bytes": self.size_bytes,
            "md5": self.md5,
            "is_person": self.is_person,
            "category": self.category,
            "detections": self.detections,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArchivedPhoto":
        is_person = bool(d.get("is_person", False))
        # Migrate legacy single `detection` -> `detections` list.
        dets = d.get("detections")
        if dets is None:
            single = d.get("detection")
            dets = [single] if isinstance(single, dict) else []
        raw_cat = d.get("category")
        category = raw_cat if raw_cat else ("ai_human" if is_person else "obstacle")
        if category == "person":  # legacy coarse label
            category = "ai_human"
        return cls(
            filename=str(d.get("filename", "")),
            name=str(d.get("name", "")),
            unix_ts=int(d.get("unix_ts", 0)),
            size_bytes=int(d.get("size_bytes", 0)),
            md5=str(d.get("md5", "")),
            is_person=is_person,
            category=category,
            detections=dets,
        )
```

In `PhotoArchive.archive`, change the signature `detection: dict | None = None`
to `detections: list[dict] | None = None` and pass it into the `ArchivedPhoto(...)`
constructor as `detections=detections`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/archive/test_photos_detections.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/archive/photos.py tests/archive/test_photos_detections.py
git commit -m "feat(photos): ArchivedPhoto stores detections list + legacy migration"
```

---

### Task 3: Wire the categorizer into both ingest paths

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py`
  - `_refresh_oss_gallery` photo loop (the inline if/elif categorization)
  - `fetch_photos_from_summary` (module-level fn — session-end path, currently no COM parse)
- Test: `tests/integration/test_oss_gallery_sync.py` (existing)

- [ ] **Step 1: Write the failing test** — add to `tests/integration/test_oss_gallery_sync.py`:

```python
@pytest.mark.asyncio
async def test_sync_categorizes_via_categorizer(tmp_path):
    # A person photo (COM person detection) -> ai_human; a no-COM photo -> manual.
    # _coord_real_archives is the existing helper in this file.
    photos = [
        {"id": "p1", "filepath": "https://fake/1_person.jpg", "type": "jpg",
         "uploadTime": "2026-06-08 21:07:08", "videoPath": ""},
    ]
    c = _coord_real_archives(tmp_path, photos, [], {"total": 100, "used": 1})
    # get_file returns a JPEG with a COM person detection — stub photo_meta.
    import custom_components.dreame_a2_mower.coordinator._lidar_oss as L
    orig = L.photo_meta.parse_jpeg_com
    L.photo_meta.parse_jpeg_com = lambda data: {"o": 101, "detections": [{"cls": "person", "conf": 0.7, "x": 1, "y": 2, "w": 3, "h": 4}], "s": None, "sub": None}
    try:
        await c._refresh_oss_gallery()
    finally:
        L.photo_meta.parse_jpeg_com = orig
    cats = [p.category for p in c._photo_archive.list_photos()]
    assert "ai_human" in cats
    assert c._photo_archive.list_photos()[0].detections[0]["cls"] == "person"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_oss_gallery_sync.py::test_sync_categorizes_via_categorizer -q`
Expected: FAIL — category is "person"/"obstacle" (old inline logic), not "ai_human".

- [ ] **Step 3: Write minimal implementation**

In `_lidar_oss.py`, add ONE module-level import near the other `from ..protocol`
imports (used by both the method and the module-level `fetch_photos_from_summary`):

```python
from ..protocol.photo_category import categorize
```

Replace the inline categorization block in `_refresh_oss_gallery` (the
`is_person = ...; meta = ...; if is_person: ... else: category = "obstacle"`
section and the `detection = ...` line) with:

```python
            meta = photo_meta.parse_jpeg_com(data)
            is_person = name.lower().endswith("_person.jpg")
            category = categorize(name=name, record=rec, com=meta)
            detections = (meta or {}).get("detections") or []
            await self.hass.async_add_executor_job(
                lambda d=data, n=name, t=_ts(rec), ip=is_person, c=category, det=detections:
                self._photo_archive.archive(name=n, unix_ts=t, data=d, is_person=ip, category=c, detections=det))
```

In `fetch_photos_from_summary` (module-level), parse the COM and categorize so the
session-end path no longer defaults everything to "obstacle". Replace the archive
call (it uses the same module-level `categorize`):

```python
        from ..protocol.photo_meta import parse_jpeg_com
        meta = parse_jpeg_com(body)
        category = categorize(name=name, record={"type": "jpg"}, com=meta)
        detections = (meta or {}).get("detections") or []
        entry = archive.archive(
            name=name, unix_ts=ts, data=body, is_person=is_person_photo(name),
            category=category, detections=detections,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_oss_gallery_sync.py -q`
Expected: PASS (all, including the new test).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_lidar_oss.py tests/integration/test_oss_gallery_sync.py
git commit -m "feat(photos): categorize via photo_category in both ingest paths"
```

---

### Task 4: Manifest emits detections + rich category

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py` (`_rebuild_photo_gallery`)
- Test: `tests/integration/test_oss_gallery_sync.py::test_gallery_manifest_shape_and_sort` (extend assertions)

- [ ] **Step 1: Write the failing test** — extend the existing manifest test with:

```python
    # (append inside test_gallery_manifest_shape_and_sort, after the existing asserts)
    assert "detections" in photo  # full detection list present on photo items
    assert isinstance(photo["detections"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_oss_gallery_sync.py::test_gallery_manifest_shape_and_sort -q`
Expected: FAIL — `KeyError: 'detections'`.

- [ ] **Step 3: Write minimal implementation**

In `_rebuild_photo_gallery`, in the photo-item dict, replace the
`"detection": p.detection,` line with:

```python
                    "detections": p.detections or [],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_oss_gallery_sync.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_lidar_oss.py tests/integration/test_oss_gallery_sync.py
git commit -m "feat(photos): gallery manifest carries full detections list"
```

---

### Task 5: Fix the human count sensor (person -> ai_human)

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor_device.py` (the `photos_person` descriptor `value_fn`)
- Test: `tests/integration/test_oss_sensors.py`

- [ ] **Step 1: Write the failing test** — add to `tests/integration/test_oss_sensors.py`:

```python
def test_person_count_uses_ai_human_category():
    coord = _coord_with_photos([  # existing helper builds a coord w/ archive
        {"category": "ai_human"}, {"category": "ai_human"}, {"category": "obstacle"},
    ])
    assert _find("photos_person").value_fn(coord) == 2
```

(If `_coord_with_photos` does not exist, use the file's existing archive-building
helper — match its current pattern for `test_photos_person_count`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_oss_sensors.py::test_person_count_uses_ai_human_category -q`
Expected: FAIL — counts 0 (value_fn still queries `'person'`).

- [ ] **Step 3: Write minimal implementation**

In `sensor_device.py`, the `photos_person` descriptor: change
`value_fn=lambda coord: coord._photo_archive.count_by_category("person")` to
`count_by_category("ai_human")`. Leave `photos_obstacle` / `photos_patrol` as-is
(those category names are unchanged).

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_oss_sensors.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor_device.py tests/integration/test_oss_sensors.py
git commit -m "fix(photos): human count sensor reads ai_human category"
```

---

### Task 6: Gallery card — new filter labels + detections caption

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-a2-photo-gallery-card.js`
- Test: node render-harness (manual, per `feedback_frontend_card_verification`)

- [ ] **Step 1: Update CATEGORY_LABELS + order**

Replace the `CATEGORY_LABELS` const (lines ~20-24) with:

```javascript
const CATEGORY_LABELS = {
  ai_human: "AI · Human",
  ai_animal: "AI · Animal",
  ai_object: "AI · Object",
  obstacle: "Obstacle",
  patrol: "Patrol",
  manual: "Manual",
};
```

In `_categories()`, change the `order` array to:

```javascript
    const order = ["ai_human", "ai_animal", "ai_object", "obstacle", "patrol", "manual"];
```

- [ ] **Step 2: Update the caption to use detections[0]**

In `_captionText`, replace the `else if (item.detection && item.detection.cls != null)`
branch with:

```javascript
    } else if (Array.isArray(item.detections) && item.detections.length) {
      const d = item.detections[0];
      if (d && d.cls != null) {
        const conf = Math.round((d.conf || 0) * 100);
        txt += " · " + d.cls + " " + conf + "%";
      }
    }
```

- [ ] **Step 3: Verify with a node render-harness**

Create a throwaway `/tmp/card_harness.mjs` that stubs `HTMLElement`/`customElements`/
`document` enough to instantiate the card, sets `hass` with a fake gallery sensor
whose `items` cover every category + a video, and asserts `_categories()` returns
the new order subset and `_filtered()` returns the right subset per filter. Run:

`node /tmp/card_harness.mjs`
Expected: prints the category list `[ai_human, ai_animal, ai_object, obstacle, patrol, manual]` (those present) and the per-filter counts; no exceptions. (`node --check` only catches syntax — execute the render fn.)

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-a2-photo-gallery-card.js
git commit -m "feat(photos): gallery card 7-category filters + detections caption"
```

---

### Task 7: Record the wire findings (fact-discipline)

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (photo/OSS entry)
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml` (photo count sensors)
- Modify: `docs/research/knowledge-gaps.md` (animal/object vocab + obstacle/manual split open questions)

- [ ] **Step 1: Add a verification to the OSS/photo inventory entry**

Append a `2026-06-12` verification (status `verified`, evidence
`app-mitm:2026-06-12-ossprobe`) capturing: userDidOssList `category` is always 0
(server does not categorize) and has no `source` field; COM `o` is the capture
activity (107 patrol / 100-103 mow), not the photo type; AI detection = non-empty
COM detections; manual captures have no COM. (Find the existing photo/userDidOssList
entry; if none, add one under the api_endpoint section.)

- [ ] **Step 2: Update the photo count sensor entries in entity-inventory.yaml**

For `sensor.dreame_a2_mower_person_photos`, add a `2026-06-13` verification noting
the value_fn now counts category `ai_human` (the new 7-category scheme).

- [ ] **Step 3: Add a knowledge-gaps entry**

Append: "Photo AI-class vocabulary + obstacle-vs-manual discriminator" —
`[UNKNOWN — to capture]`: the archive currently has only `person` detections, so
`ANIMAL_CLASSES` is provisional and unknown `cls` falls through to `ai_object`;
and whether normal-obstacle photos carry a COM (o=mow+empty) or none (overlapping
`manual`) needs a live mow with a navigated physical obstacle. Capture: during a
real session with an animal/object detection + a navigated obstacle, log each new
photo's COM `o`/`cls` and the OSS record.

- [ ] **Step 4: Validate inventory + commit**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only`
Expected: `ok: inventory schema valid`. Then regenerate:
`/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py`

```bash
git add custom_components/dreame_a2_mower/inventory.yaml custom_components/dreame_a2_mower/entity-inventory.yaml docs/research/knowledge-gaps.md docs/research/inventory/generated/g2408-canonical.md
git commit -m "docs(inventory): record OSS-probe categorization findings + gaps"
```

---

### Task 8: Full suite + live deploy/verify

**Files:** none (verification)

- [ ] **Step 1: Run the full test suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q`
Expected: all pass (baseline was 2230 passed / 4 skipped + the new tests).

- [ ] **Step 2: Deploy to the live box + restart**

```bash
sshpass -p 'cex2vol' scp -o StrictHostKeyChecking=no custom_components/dreame_a2_mower/protocol/photo_category.py root@10.0.0.30:/config/custom_components/dreame_a2_mower/protocol/photo_category.py
sshpass -p 'cex2vol' scp -o StrictHostKeyChecking=no custom_components/dreame_a2_mower/archive/photos.py root@10.0.0.30:/config/custom_components/dreame_a2_mower/archive/photos.py
sshpass -p 'cex2vol' scp -o StrictHostKeyChecking=no custom_components/dreame_a2_mower/coordinator/_lidar_oss.py root@10.0.0.30:/config/custom_components/dreame_a2_mower/coordinator/_lidar_oss.py
sshpass -p 'cex2vol' scp -o StrictHostKeyChecking=no custom_components/dreame_a2_mower/sensor_device.py root@10.0.0.30:/config/custom_components/dreame_a2_mower/sensor_device.py
sshpass -p 'cex2vol' scp -o StrictHostKeyChecking=no custom_components/dreame_a2_mower/www/dreame-a2-photo-gallery-card.js root@10.0.0.30:/config/custom_components/dreame_a2_mower/www/dreame-a2-photo-gallery-card.js
sshpass -p 'cex2vol' ssh -o StrictHostKeyChecking=no root@10.0.0.30 "ha core restart"
```

- [ ] **Step 2b: Hard-refresh the dashboard** (the card JS is cached — bump is automatic via HACS, but the SCP'd file needs a browser hard-refresh; the gallery resource URL is unversioned).

- [ ] **Step 3: Verify categories on the box**

```bash
sshpass -p 'cex2vol' ssh -o StrictHostKeyChecking=no root@10.0.0.30 "jq -r '.photos[].category' /config/dreame_a2_mower/photos/index.json | sort | uniq -c"
```
Expected: counts grouped by the new categories (ai_human, patrol, obstacle, manual, …). `person` should no longer appear after a full re-sync; `ai_object`/`ai_animal` appear only once such detections exist.

- [ ] **Step 4: Version bump + HACS release** (the box runs SCP'd files until a proper release): bump `manifest.json` version (respect the HACS digit-boundary ladder, see `feedback_hacs_version_ladder`), commit, push, `gh release create` per `feedback_tag_after_push`.

---

## Notes for the implementer

- The vanilla test venv has NO real Home Assistant — `protocol/photo_category.py`
  must not import anything from `homeassistant.*`. It's pure stdlib.
- `_lidar_oss.py` is large; do NOT restructure it. Only touch the named methods.
- Do not re-add a single `coordinator.py` or otherwise refactor (see repo CLAUDE.md).
- The OSS sync re-downloads ~85 photos/boot (per-category retention prunes disk
  below the cloud count). That pre-existing inefficiency is out of scope here;
  note it but do not fix it in this plan.
