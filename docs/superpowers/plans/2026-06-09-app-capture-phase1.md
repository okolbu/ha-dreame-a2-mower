# App-capture knowledge — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the 2026-06-08/09 app-MITM findings into the inventory/docs and ship the *fully-known* integration support — album (Patrol + AI-obstacle) photos, a routed-`get` read-probe tool, a LiDAR fetch-parity investigation, and the sendCommand/80001 reframe — while recording all partial/deferred findings for Phase 2.

**Architecture:** Photos reuse the existing OSS plumbing (`cloud_client/_oss.py` `get_interim_file_url`/`get_file`) and the `archive/lidar.py` shape; a new `archive/photos.py` + a `PhotosMixin` fetch step in `coordinator/_lidar_oss.py`'s `_do_oss_fetch`, surfaced as two camera entities. Probes are dev-box-only scripts under `tools/probes/`. Doc work updates `inventory.yaml` (the SoT) + the Tier-2 reference docs, all with CLAUDE.md epistemic tags.

**Tech Stack:** Python 3.13, Home Assistant custom integration, pytest, the vanilla stubbed-HA venv at `/data/claude/homeassistant/.venv-vanilla`.

**Spec:** `docs/superpowers/specs/2026-06-09-app-capture-knowledge-design.md`

---

## Conventions for this plan

- **Run tests with:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -v`
  (the vanilla stubbed-HA venv; system `python3` is 3.14 and broken — see
  `reference_test_env_setup`).
- **Epistemic tags (CLAUDE.md, load-bearing):** every sentence about a wire
  surface in code/docs carries `[<evidence>]`, `[UNVERIFIED]`, or
  `[UNKNOWN — to capture]`. App-MITM findings are **`partial`** (status), with
  evidence `dreame-app-implementation-guide-2026-06-09.md` — they are
  app-observed, NOT verified on our own client, so they are not `verified`.
- **Commit after every task.** Branch first (repo default branch is `main`):
  `git checkout -b feat/app-capture-phase1` before Task 1.
- **Inventory gate:** any entity add or wire-fact change must update
  `inventory.yaml`/`entity-inventory.yaml` in the same commit, or CI
  (`inventory-touch-gate`) blocks it.

---

## File structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `custom_components/dreame_a2_mower/protocol/photo_keys.py` | Create | Pure: build the OSS object key for a photo_list leaf |
| `tests/protocol/test_photo_keys.py` | Create | Unit tests for the key builder |
| `custom_components/dreame_a2_mower/archive/photos.py` | Create | On-disk photo archive (mirrors `archive/lidar.py`) |
| `tests/archive/test_photo_archive.py` | Create | Unit tests for the archive |
| `custom_components/dreame_a2_mower/const.py` | Modify | New CONF_/DEFAULT_ photo-archive option keys |
| `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py` | Modify | Fetch photos from `raw_dict["photo_list"]` during `_do_oss_fetch`; expose archive accessors |
| `custom_components/dreame_a2_mower/coordinator/_core.py` | Modify | Init photo-archive state in `__init__` |
| `custom_components/dreame_a2_mower/camera.py` + `_camera_photos.py` | Create sibling / Modify entry | Two camera entities (latest album photo, latest person-detection) |
| `tests/integration/test_photo_camera.py` | Create | Camera entity behaviour |
| `tools/probes/oss_photo_probe.py` | Create | LIVE: verify which signing endpoint resolves a media key |
| `tools/probes/read_key_probe.py` | Create | LIVE: issue routed-`get` for the new `t`-keys, log raw |
| `tools/probes/lidar_parity_probe.py` | Create | LIVE: diff our 3dmap object vs the app's captured PCD |
| `custom_components/dreame_a2_mower/inventory.yaml` | Modify | New `t`-key entries, PRE partial, photo key-layout, transport notes |
| `docs/research/app-api-surface-2026-05-25.md` | Modify | Backend B = `:13267` correction |
| `docs/research/cloud-write-reference.md` | Modify | `sendCommand` envelope + 80001 reframe |
| `docs/research/g2408-research-journal.md` | Modify | Dated 2026-06-09 entry |
| `docs/data-policy.md` | Modify | Photo privacy note |

---

## Part A — Doc reconciliation (records all known + partial findings)

### Task 1: Branch + inventory `t`-key vocabulary entries

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`

- [ ] **Step 1: Create the branch**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git checkout -b feat/app-capture-phase1
```

- [ ] **Step 2: Find where routed `t`-keys / actions are catalogued in the inventory**

Run: `grep -n "routed\|aiid.*50\|t:.*OBJ\|cfg_keys\|actions:" custom_components/dreame_a2_mower/inventory.yaml | head -40`
Expected: locates the `cfg_keys`/`actions` section to append sibling entries.

- [ ] **Step 3: Append the new read-key vocabulary as `partial` entries**

Add one entry per newly-observed routed-`get` key. Use this shape for each
(repeat for `MPOS MAPI MAPL MISTA OBS AIOBS PREI RGBPSTA SCHDTV3 REMOTE IOT MITRC`;
`DEV DOCK CFG` already exist — only add a verification line to those):

```yaml
  routed_get_mpos:
    semantic: >-
      Routed-action read key MPOS. The app issues
      action(siid:2,aiid:50) {"m":"g","t":"MPOS","d":<args>} to read live
      mower position [dreame-app-implementation-guide-2026-06-09.md]. Response
      shape is [UNKNOWN — to capture] — see tools/probes/read_key_probe.py.
    status:
      decoded: hypothesized
      last_seen: "2026-06-09"
    open_questions:
      - id: mpos-decode
        text: "Decode the MPOS routed-get response; is it a live-position fallback for when s1p4 MQTT is down? Capture via read_key_probe.py."
    verifications:
      - date: "2026-06-09"
        status: partial
        claim: "App reads live position via routed-get t=MPOS (response shape not yet decoded)"
        evidence: "dreame-app-implementation-guide-2026-06-09.md"
```

Per-key `open_questions.id` values (referenced by Spec B / the playbook):
`mpos-decode`, `mapi-decode`, `mapl-decode`, `mista-decode`, `obs-decode`,
`aiobs-photo-index`, `prei-decode`, `rgbpsta-decode`, `schdtv3-shape`,
`remote-decode`, `iot-decode`, `mitrc-decode`.

- [ ] **Step 4: Validate the inventory schema**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only`
Expected: PASS (no schema errors). If `decoded: hypothesized` is rejected, check the allowed vocab in `tools/inventory/inventory_gen.py` and match it.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml
git commit -m "docs(inventory): add routed-get t-key vocabulary from app capture (partial)"
```

---

### Task 2: Inventory — PRE 19-element partial + photo key-layout correction

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`

- [ ] **Step 1: Locate the PRE entry**

Run: `grep -n "PRE\|pre_mowing\|pre_edgemaster\|edgemaster" custom_components/dreame_a2_mower/inventory.yaml | head`
Expected: finds the existing PRE / `s6p2` entries (PRE write currently recorded as `r=-3`).

- [ ] **Step 2: Append the app-observed PRE write as `partial` with open_questions**

```yaml
    verifications:
      - date: "2026-06-09"
        status: partial
        claim: >-
          App writes PRE via action(siid:2,aiid:50) {"m":"s","t":"PRE","d":[...]}
          with a 19-element array, ON-state captured
          d=[0,0,0,0,55,1,8,1,0,1,1,2,1,20,10,7,1,2,0]; d[4]=55 = mowing height
          5.5cm. Returned code:0 app-side.
        evidence: "dreame-app-implementation-guide-2026-06-09.md"
    open_questions:
      - id: pre-layout
        text: >-
          Reconcile the app's 19-element PRE array (height at index 4) vs the
          integration's 10-element builder (height at index 2). Capture a 2nd PRE
          SET to map every index.
      - id: pre-edgemaster-bit
        text: >-
          Locate the EdgeMaster bit by diffing an OFF vs ON PRE write (only ON
          captured). Then confirm m:s t:PRE returns code:0 on OUR client (our
          recorded r=-3 may have been a different path/payload).
```

- [ ] **Step 3: Locate the photo entries**

Run: `grep -n "ai_obstacle\|photo_list\|summary_photo\|s2p55" custom_components/dreame_a2_mower/inventory.yaml | head`
Expected: finds `summary_photo_list` / `s2p55` entries currently stating photos are unreachable.

- [ ] **Step 4: Correct the photo entries (reachable; key layout) — `partial`**

Append to the `summary_photo_list` entry:

```yaml
    verifications:
      - date: "2026-06-09"
        status: partial
        claim: >-
          Photos ARE reachable. Album (Patrol + AI-obstacle) photos live in
          dreame-eu.oss-eu-central-1 at
          oss/media/000000/oss/<uid>/<did>/ali_dreame/<unix_ts>[_person].jpg;
          the .0550.json summary's photo_list[] leaves map 1:1 to <ts>.jpg.
          _person.jpg = person/guard detection variant.
        evidence: "dreame-app-implementation-guide-2026-06-09.md"
      - date: "2026-06-09"
        status: retracted
        claim: "Album photos are reachable via the dreame-eu OSS bucket"
        retracts: "photos exist app-side only and the integration cannot reach them"
        reason: "App capture shows photos in the SAME OSS bucket the integration already fetches LiDAR PCD from."
    open_questions:
      - id: transient-obstacle-photo-api
        text: >-
          The transient session-obstacle photos (live-map clickable icons that
          die after the session) use a different, uncaptured API — no real mow
          ran. Capture during a real obstacle-hitting mow (Spec B §4.4).
      - id: aiobs-photo-index
        text: >-
          The pre-signed photo-index call (returns the album URL set) was not on
          HTTPS; likely a sendCommand t=AIOBS read or MQTT event. Not needed for
          Phase 1 (photo_list suffices) but pin it for a durable list path.
```

> NOTE: before writing the `retracts:` line, grep the entry's `semantic:` prose
> for the old "unreachable" wording and reword it in the same edit (CLAUDE.md
> requires the retracted claim text to match a real prior claim).

- [ ] **Step 5: Validate + commit**

```bash
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
git add custom_components/dreame_a2_mower/inventory.yaml
git commit -m "docs(inventory): PRE 19-elem partial + photos-reachable correction (app capture)"
```

---

### Task 3: Reference docs — backend B identity, sendCommand envelope, journal, privacy

**Files:**
- Modify: `docs/research/app-api-surface-2026-05-25.md`
- Modify: `docs/research/cloud-write-reference.md`
- Modify: `docs/research/g2408-research-journal.md`
- Modify: `docs/data-policy.md`

- [ ] **Step 1: Correct backend B in `app-api-surface-2026-05-25.md`**

Find the A/B/C table (`grep -n "app.dreame.tech\|Backend B\|backend B" docs/research/app-api-surface-2026-05-25.md`). Add a dated correction block right under the table:

```markdown
> **Correction 2026-06-09 [dreame-app-implementation-guide-2026-06-09.md]:**
> Backend B is `eu.iot.dreame.tech:13267` (HTTP-over-TLS), NOT `app.dreame.tech`.
> Backends A and B share that host:port; `POST …/dreame-iot-com-10000/device/
> sendCommand` is the shared control relay and returns `code:0` while the mower
> is online — the `80001` is asleep/slow-prop-specific, not RPC-inherent. The
> auth bridge is `:13267/dreame-smarthome/aliIot/getAuthCodeV3` →
> `api.link.aliyun.com/living/account/region/get` → Aliyun Link session. The
> "app does not use backend A" claim is superseded.
```

- [ ] **Step 2: Add the live `sendCommand` envelope to `cloud-write-reference.md`**

Append a section + bump the "last-verified" date at the top to `2026-06-09`:

```markdown
## device/sendCommand — app-observed control path (2026-06-09, partial)

`POST eu.iot.dreame.tech:13267/dreame-iot-com-10000/device/sendCommand`
[dreame-app-implementation-guide-2026-06-09.md] — app-observed, not yet
re-verified on our client.

Outer: `{"id":N,"did":did,"data":{...},"sign":hmac,"timestamp":ms}`
Inner: `{"id":N,"did":did,"method":"action|get_properties|set_properties",
"from":"android","params":...}`. `action(siid:2,aiid:50)` multiplexes:
`{"m":"g","t":KEY,"d":args}` (read), `{"m":"s","t":KEY,"d":value}` (CFG write),
`{"m":"a","p":P,"o":opcode,"d":args}` (routed action). Spot mow live-confirmed:
`{"m":"a","p":0,"o":103,"d":{"area":[1]}}` → code:0.

**80001 reframe:** returns `code:0` online; the 80001 we attributed to the RPC
path is asleep/slow-prop-specific. See tools/probes/read_key_probe.py and the
sendCommand verification (Task 11).
```

- [ ] **Step 3: Add the dated journal entry**

Append to `docs/research/g2408-research-journal.md` (keep its non-authoritative banner intact) a `## 2026-06-09 — app-MITM capture reconciliation` entry summarising: photos reachable, backend B = `:13267`, spot `o=103` corroboration, the `t`-key vocab, the PRE 19-elem partial, and a pointer to `docs/superpowers/specs/2026-06-09-app-capture-playbook-design.md` for the deferred captures.

- [ ] **Step 4: Add the photo privacy note to `data-policy.md`**

Append:

```markdown
## Camera / album photos (2026-06-09)

The mower has a camera (`feature: video_tx`). Album photos (Patrol + AI-obstacle,
including `_person` person-detection shots) are fetched to a LOCAL on-disk
archive (`archive/photos.py`) and never committed. They contain images of the
property and people — treat the bucket paths and any saved frames as sensitive.
```

- [ ] **Step 5: Commit**

```bash
git add docs/research/app-api-surface-2026-05-25.md docs/research/cloud-write-reference.md docs/research/g2408-research-journal.md docs/data-policy.md
git commit -m "docs(research): backend-B identity, sendCommand envelope, journal + photo privacy"
```

---

## Part B — Album photos feature

### Task 4: Photo OSS key builder (pure)

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/photo_keys.py`
- Test: `tests/protocol/test_photo_keys.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/protocol/test_photo_keys.py
from custom_components.dreame_a2_mower.protocol.photo_keys import (
    build_photo_object_key,
    is_person_photo,
)


def test_build_photo_object_key():
    # [dreame-app-implementation-guide-2026-06-09.md] key layout:
    # oss/media/000000/oss/<uid>/<did>/ali_dreame/<name>
    key = build_photo_object_key(uid="BM169439", did="-112293549", name="1780512275.jpg")
    assert key == "oss/media/000000/oss/BM169439/-112293549/ali_dreame/1780512275.jpg"


def test_build_photo_object_key_person_variant():
    key = build_photo_object_key(uid="BM169439", did="-112293549", name="1780512275_person.jpg")
    assert key.endswith("/ali_dreame/1780512275_person.jpg")


def test_is_person_photo():
    assert is_person_photo("1780512275_person.jpg") is True
    assert is_person_photo("1780512275.jpg") is False
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_photo_keys.py -v`
Expected: FAIL — `ModuleNotFoundError: ...photo_keys`.

- [ ] **Step 3: Write the implementation**

```python
# custom_components/dreame_a2_mower/protocol/photo_keys.py
"""Build OSS object keys for album (Patrol + AI-obstacle) photos.

[dreame-app-implementation-guide-2026-06-09.md] Photos live in the
dreame-eu.oss-eu-central-1 bucket at
``oss/media/000000/oss/<uid>/<did>/ali_dreame/<name>``, where ``<name>`` is a
``photo_list`` leaf from the session-summary ``.0550.json`` (a bare
``<unix_ts>.jpg`` or a ``<unix_ts>_person.jpg`` person-detection variant).

This module is pure (no HA, no network) and unit-testable in isolation. Whether
``get_interim_file_url`` or ``get_file_url`` signs this key is verified live by
``tools/probes/oss_photo_probe.py`` before the feature uses it.
"""
from __future__ import annotations

_PHOTO_KEY_PREFIX = "oss/media/000000/oss"
_PHOTO_KEY_SUBDIR = "ali_dreame"


def build_photo_object_key(*, uid: str, did: str, name: str) -> str:
    """Return the OSS object key for one photo_list leaf."""
    return f"{_PHOTO_KEY_PREFIX}/{uid}/{did}/{_PHOTO_KEY_SUBDIR}/{name}"


def is_person_photo(name: str) -> bool:
    """True when the leaf is a person/guard-detection variant (`_person.jpg`)."""
    return name.lower().endswith("_person.jpg")
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_photo_keys.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/photo_keys.py tests/protocol/test_photo_keys.py
git commit -m "feat(photos): pure OSS key builder for album photos"
```

---

### Task 5: PhotoArchive (on-disk, mirrors LidarArchive)

**Files:**
- Create: `custom_components/dreame_a2_mower/archive/photos.py`
- Test: `tests/archive/test_photo_archive.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/archive/test_photo_archive.py
from custom_components.dreame_a2_mower.archive.photos import PhotoArchive

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # ffd8 magic + filler


def test_archive_and_latest(tmp_path):
    arc = PhotoArchive(tmp_path)
    entry = arc.archive(name="1780512275.jpg", unix_ts=1780512275, data=JPEG, is_person=False)
    assert entry is not None
    assert entry.is_person is False
    assert arc.count == 1
    assert arc.latest().name == "1780512275.jpg"


def test_archive_dedup_by_md5(tmp_path):
    arc = PhotoArchive(tmp_path)
    arc.archive(name="a.jpg", unix_ts=1, data=JPEG, is_person=False)
    assert arc.archive(name="a.jpg", unix_ts=1, data=JPEG, is_person=False) is None
    assert arc.count == 1


def test_latest_person(tmp_path):
    arc = PhotoArchive(tmp_path)
    arc.archive(name="1.jpg", unix_ts=1, data=JPEG, is_person=False)
    arc.archive(name="2_person.jpg", unix_ts=2, data=JPEG + b"x", is_person=True)
    assert arc.latest_person().name == "2_person.jpg"
    assert arc.latest().name == "2_person.jpg"  # latest overall
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/archive/test_photo_archive.py -v`
Expected: FAIL — `ModuleNotFoundError: ...archive.photos`.

- [ ] **Step 3: Write the implementation**

Mirror `archive/lidar.py` (read it first: same `index.json` v1 pattern,
`_save_index`/`load_index`, `_enforce_retention`/`_enforce_size_cap`). The
deltas: the dataclass field set is `(filename, name, unix_ts, size_bytes, md5,
is_person)`; files are written as `<date>_<ts>_<md5[:8]>.jpg`; add
`latest_person()`; the archive is NOT per-map (drop the `map_id` ctor arg and
the `<root>/<map_id>/` namespacing — photos aren't map-scoped).

```python
# custom_components/dreame_a2_mower/archive/photos.py
"""On-disk archive of album (Patrol + AI-obstacle) photos.

[dreame-app-implementation-guide-2026-06-09.md] Photos are fetched from the
dreame-eu OSS bucket (see protocol/photo_keys.py) and persisted here verbatim.
Content-addressed by md5; re-fetching the same image is a no-op. Mirrors
archive/lidar.py but is NOT map-scoped and tracks a person-detection flag.

Privacy: these JPEGs contain images of the property and people. Local only;
never committed (see docs/data-policy.md).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

INDEX_NAME = "index.json"
INDEX_VERSION = 1


@dataclass(frozen=True)
class ArchivedPhoto:
    filename: str
    name: str          # original photo_list leaf, e.g. "1780512275_person.jpg"
    unix_ts: int
    size_bytes: int
    md5: str
    is_person: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename, "name": self.name,
            "unix_ts": self.unix_ts, "size_bytes": self.size_bytes,
            "md5": self.md5, "is_person": self.is_person,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArchivedPhoto":
        return cls(
            filename=str(d.get("filename", "")),
            name=str(d.get("name", "")),
            unix_ts=int(d.get("unix_ts", 0)),
            size_bytes=int(d.get("size_bytes", 0)),
            md5=str(d.get("md5", "")),
            is_person=bool(d.get("is_person", False)),
        )


def _format_date(unix_ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=UTC).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return "unknown-date"


class PhotoArchive:
    def __init__(self, root: Path, retention: int = 0, max_bytes: int = 0) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index: list[ArchivedPhoto] = []
        self._retention = int(retention) if retention else 0
        self._max_bytes = int(max_bytes) if max_bytes else 0
        self._index_loaded = False

    def _index_path(self) -> Path:
        return self._root / INDEX_NAME

    def load_index(self) -> None:
        if self._index_loaded:
            return
        path = self._index_path()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                rows = data.get("photos", []) if isinstance(data, dict) else []
                self._index = [ArchivedPhoto.from_dict(r) for r in rows if isinstance(r, dict)]
            except (OSError, ValueError, TypeError) as ex:
                _LOGGER.warning("PhotoArchive: index load failed (%s); fresh", ex)
                self._index = []
        self._index_loaded = True

    def _save_index(self) -> None:
        path = self._index_path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(
            {"version": INDEX_VERSION, "photos": [p.to_dict() for p in self._index]},
            indent=2, sort_keys=True,
        ))
        tmp.replace(path)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def count(self) -> int:
        self.load_index()
        return len(self._index)

    def has(self, md5: str) -> bool:
        self.load_index()
        return any(p.md5 == md5 for p in self._index)

    def latest(self) -> ArchivedPhoto | None:
        self.load_index()
        return max(self._index, key=lambda p: p.unix_ts) if self._index else None

    def latest_person(self) -> ArchivedPhoto | None:
        self.load_index()
        persons = [p for p in self._index if p.is_person]
        return max(persons, key=lambda p: p.unix_ts) if persons else None

    def list_photos(self) -> list[ArchivedPhoto]:
        self.load_index()
        return sorted(self._index, key=lambda p: p.unix_ts, reverse=True)

    def read_bytes(self, filename: str) -> bytes | None:
        path = self._root / filename
        try:
            return path.read_bytes()
        except OSError:
            return None

    def archive(self, *, name: str, unix_ts: int, data: bytes, is_person: bool) -> ArchivedPhoto | None:
        if not data:
            return None
        md5 = hashlib.md5(data).hexdigest()
        if self.has(md5):
            return None
        stem = f"{_format_date(unix_ts)}_{int(unix_ts)}_{md5[:8]}.jpg"
        path = self._root / stem
        tmp = path.with_suffix(".jpg.tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError as ex:
            _LOGGER.warning("PhotoArchive: write failed (%s): %s", ex, path)
            return None
        photo = ArchivedPhoto(stem, name, int(unix_ts), len(data), md5, bool(is_person))
        self._index.append(photo)
        self._save_index()
        self._enforce_retention()
        self._enforce_size_cap()
        return photo

    def _enforce_retention(self) -> None:
        keep = self._retention
        if not keep or keep <= 0 or len(self._index) <= keep:
            return
        sorted_idx = sorted(self._index, key=lambda p: p.unix_ts)
        for photo in sorted_idx[: len(sorted_idx) - keep]:
            (self._root / photo.filename).unlink(missing_ok=True)
        kept = {p.filename for p in sorted_idx[len(sorted_idx) - keep :]}
        self._index = [p for p in self._index if p.filename in kept]
        self._save_index()

    def _enforce_size_cap(self) -> None:
        cap = self._max_bytes
        if not cap or cap <= 0:
            return
        sorted_idx = sorted(self._index, key=lambda p: p.unix_ts)
        total = sum(p.size_bytes for p in sorted_idx)
        while sorted_idx and total > cap:
            photo = sorted_idx.pop(0)
            (self._root / photo.filename).unlink(missing_ok=True)
            total -= photo.size_bytes
        kept = {p.filename for p in sorted_idx}
        if len(kept) != len(self._index):
            self._index = [p for p in self._index if p.filename in kept]
            self._save_index()
```

- [ ] **Step 4: Run the tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/archive/test_photo_archive.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/archive/photos.py tests/archive/test_photo_archive.py
git commit -m "feat(photos): on-disk PhotoArchive mirroring LidarArchive"
```

---

### Task 6: LIVE — verify the OSS signing endpoint for a media key

**Files:**
- Create: `tools/probes/oss_photo_probe.py`

This resolves the one `[UNVERIFIED]` in the photo path: whether
`get_interim_file_url` (key-only) or `get_file_url` (uid+filename) signs the
media key. It runs against the live cloud; it is read-only.

- [ ] **Step 1: Read an existing probe for the connect/auth boilerplate**

Run: `sed -n '1,60p' tools/probes/probe_pre_write.py`
Expected: shows how a probe constructs `DreameA2CloudClient`, logs in, and selects the g2408 (reuse this verbatim — do not invent auth).

- [ ] **Step 2: Write the probe**

```python
# tools/probes/oss_photo_probe.py
"""LIVE read-only probe: verify which OSS signing endpoint resolves a photo key.

[dreame-app-implementation-guide-2026-06-09.md] Photos sit at
oss/media/000000/oss/<uid>/<did>/ali_dreame/<name>. The capture used a
pre-signed URL we cannot replay (Expires-limited), so we must sign the key
ourselves. This probe tries get_interim_file_url(key) and get_file_url(key)
against a real photo_list leaf and reports which returns a 200-downloadable URL.

Dev-box only. Pretty-prints inline with timestamps (feedback_inline_logging).
Usage:
  /data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/oss_photo_probe.py <photo_name.jpg>
where <photo_name.jpg> is a leaf from a recent session summary's photo_list.
"""
from __future__ import annotations

import sys
from datetime import datetime

# Reuse the connect/login boilerplate from probe_pre_write.py (copy its
# _connect() helper here; do NOT re-derive auth). The helper returns a
# logged-in DreameA2CloudClient selected onto the g2408.
from _probe_common import connect  # see Step 3


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main(name: str) -> None:
    from custom_components.dreame_a2_mower.protocol.photo_keys import (
        build_photo_object_key, is_person_photo,
    )
    cloud = connect()
    key = build_photo_object_key(uid=str(cloud._uid), did=str(cloud._did), name=name)
    print(f"[{_ts()}] photo key = {key}  (person={is_person_photo(name)})")

    for label, fn in (("get_interim_file_url", cloud.get_interim_file_url),
                      ("get_file_url", cloud.get_file_url)):
        try:
            url = fn(key)
        except Exception as ex:  # noqa: BLE001
            print(f"[{_ts()}] {label}: raised {ex!r}")
            continue
        print(f"[{_ts()}] {label}: url={str(url)[:120]!r}")
        if url:
            body = cloud.get_file(url)
            ok = bool(body) and body[:2] == b"\xff\xd8"
            print(f"[{_ts()}] {label}: downloaded {len(body or b'')} bytes, jpeg={ok}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    main(sys.argv[1])
```

- [ ] **Step 3: Extract the shared connect helper**

If `tools/probes/` has no `_probe_common.py`, create it by lifting the
login/select boilerplate out of `probe_pre_write.py` into
`connect() -> DreameA2CloudClient`. Otherwise import the existing one. Run:
`ls tools/probes/_probe_common.py 2>/dev/null && echo exists || echo create-it`

- [ ] **Step 4: Run the probe live and record the winning endpoint**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/oss_photo_probe.py <a-recent-photo_list-leaf>.jpg`
Expected: one of the two endpoints prints `jpeg=True` with a non-zero byte count. **Record which one** — Task 7 uses it. If BOTH fail, STOP and report: the key layout or signing assumption is wrong; move the photo feature to Phase 2 and add a Spec B capture item.

- [ ] **Step 5: Record the result in the inventory + commit**

Append a `verification` to the `summary_photo_list` entry:
```yaml
      - date: "2026-06-09"
        status: verified
        claim: "Photo key <key> resolves to a downloadable JPEG via <winning endpoint>"
        evidence: "tools/probes/oss_photo_probe.py live run 2026-06-09"
```
```bash
git add tools/probes/oss_photo_probe.py tools/probes/_probe_common.py custom_components/dreame_a2_mower/inventory.yaml
git commit -m "feat(probes): verify OSS signing endpoint for photo keys (live)"
```

---

### Task 7: Coordinator — fetch album photos during `_do_oss_fetch`

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py`
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py`
- Modify: `custom_components/dreame_a2_mower/coordinator/_lidar_oss.py`
- Test: `tests/integration/test_photo_fetch.py`

- [ ] **Step 1: Add option consts**

In `const.py`, mirror the lidar archive consts:
```python
CONF_PHOTO_ARCHIVE_KEEP = "photo_archive_keep"
CONF_PHOTO_ARCHIVE_MAX_MB = "photo_archive_max_mb"
DEFAULT_PHOTO_ARCHIVE_KEEP = 200
DEFAULT_PHOTO_ARCHIVE_MAX_MB = 50
```

- [ ] **Step 2: Init the archive in `_core.py.__init__`**

Where `self.lidar_archives` / `self._lidar_archive_root` are set, add:
```python
from ..archive.photos import PhotoArchive
self._photo_archive = PhotoArchive(
    self._archive_root_base / "photos",   # reuse the same base dir the lidar archive uses
    retention=entry.options.get(CONF_PHOTO_ARCHIVE_KEEP, DEFAULT_PHOTO_ARCHIVE_KEEP),
    max_bytes=entry.options.get(CONF_PHOTO_ARCHIVE_MAX_MB, DEFAULT_PHOTO_ARCHIVE_MAX_MB) * 1024 * 1024,
)
```
> Read the existing `_core.py` to use the actual archive-root attribute name
> (grep `_lidar_archive_root`/`archive_root`); match it — do not invent a path.

- [ ] **Step 3: Write the failing test**

```python
# tests/integration/test_photo_fetch.py
import asyncio
from custom_components.dreame_a2_mower.coordinator._lidar_oss import fetch_photos_from_summary


class _FakeCloud:
    _uid = "BM169439"
    _did = "-112293549"
    def get_interim_file_url(self, key): return f"https://signed/{key}"
    def get_file(self, url): return b"\xff\xd8\xff" + b"0" * 50


def test_fetch_photos_from_summary(tmp_path):
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive
    arc = PhotoArchive(tmp_path)
    raw = {"photo_list": ["1780512275.jpg", "1780512300_person.jpg"]}
    n = asyncio.run(fetch_photos_from_summary(
        _FakeCloud(), arc, raw, sign=lambda c, k: c.get_interim_file_url(k),
    ))
    assert n == 2
    assert arc.count == 2
    assert arc.latest_person().name == "1780512300_person.jpg"
```

- [ ] **Step 4: Run it to confirm it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_photo_fetch.py -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_photos_from_summary'`.

- [ ] **Step 5: Add `fetch_photos_from_summary` as a module-level helper in `_lidar_oss.py`**

```python
# add near merge_mow_type_fields / finalize_classify_raw_dict (module-level, HA-free)
async def fetch_photos_from_summary(cloud, archive, raw_dict, *, sign) -> int:
    """Fetch every photo_list leaf into the PhotoArchive. Returns count added.

    [dreame-app-implementation-guide-2026-06-09.md] photo_list entries are
    <ts>[_person].jpg leaves; the OSS key is built via protocol/photo_keys.
    `sign(cloud, key)` is the signing endpoint confirmed live in Task 6
    (get_interim_file_url or get_file_url) — injected so this stays testable.
    Synchronous cloud I/O is fine here; callers run it in an executor job.
    """
    from ..protocol.photo_keys import build_photo_object_key, is_person_photo
    names = raw_dict.get("photo_list") or []
    if not isinstance(names, list):
        return 0
    added = 0
    for name in names:
        if not isinstance(name, str) or not name:
            continue
        ts = _photo_ts_from_name(name)
        key = build_photo_object_key(uid=str(cloud._uid), did=str(cloud._did), name=name)
        url = sign(cloud, key)
        if not url:
            continue
        body = cloud.get_file(url)
        if not body:
            continue
        entry = archive.archive(name=name, unix_ts=ts, data=body, is_person=is_person_photo(name))
        if entry is not None:
            added += 1
    return added


def _photo_ts_from_name(name: str) -> int:
    import re
    m = re.match(r"(\d{9,11})", name)
    return int(m.group(1)) if m else 0
```

- [ ] **Step 6: Wire it into `_do_oss_fetch`**

After `self._inject_live_map_into_raw_dict(raw_dict)` (around line 582) and
before/after archiving, add an executor-run call guarded so a failure never
breaks the session finalize (match the LiDAR `try/except…WARNING` style):
```python
# Album photos (Patrol + AI-obstacle). [dreame-app-implementation-guide-2026-06-09.md]
try:
    sign = self._photo_sign_fn  # set in _core.py to the Task-6-confirmed endpoint
    n = await self.hass.async_add_executor_job(
        lambda: asyncio.run(fetch_photos_from_summary(self._cloud, self._photo_archive, raw_dict, sign=sign))
    )
    if n:
        LOGGER.info("[PHOTOS] archived %d album photo(s); total=%d", n, self._photo_archive.count)
except Exception as ex:  # noqa: BLE001 — photos never break finalize
    LOGGER.warning("[PHOTOS] fetch failed: %s", ex)
```
> `asyncio` is already imported in `_lidar_oss.py` (line 7). Define
> `self._photo_sign_fn` in `_core.py` as a module-level `def` wrapper around the
> Task-6-confirmed endpoint (e.g. `lambda c, k: c.get_interim_file_url(k)`).

- [ ] **Step 7: Run the test**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_photo_fetch.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add custom_components/dreame_a2_mower/const.py custom_components/dreame_a2_mower/coordinator/_core.py custom_components/dreame_a2_mower/coordinator/_lidar_oss.py tests/integration/test_photo_fetch.py
git commit -m "feat(photos): fetch album photos from photo_list during OSS finalize"
```

---

### Task 8: Camera entities (latest album photo, latest person-detection)

**Files:**
- Read: `custom_components/dreame_a2_mower/_camera_lidar.py` (pattern)
- Create: `custom_components/dreame_a2_mower/_camera_photos.py`
- Modify: `custom_components/dreame_a2_mower/camera.py` (import + add to setup)
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml` (two new entities)
- Test: `tests/integration/test_photo_camera.py`

- [ ] **Step 1: Read the existing camera-entity + view pattern**

Run: `sed -n '1,140p' custom_components/dreame_a2_mower/_camera_lidar.py`
Expected: shows the `Camera` subclass shape, `async_camera_image`, the
`coordinator` accessor, and the access_token-rotation refresh pattern
(`feedback_camera_image_refresh_pattern`). Mirror it.

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/test_photo_camera.py
from custom_components.dreame_a2_mower._camera_photos import (
    DreameAlbumPhotoCamera, DreamePersonPhotoCamera,
)


class _Coord:
    def __init__(self, archive): self._photo_archive = archive
    @property
    def photo_archive(self): return self._photo_archive


def test_album_camera_returns_latest_bytes(tmp_path):
    from custom_components.dreame_a2_mower.archive.photos import PhotoArchive
    arc = PhotoArchive(tmp_path)
    arc.archive(name="1.jpg", unix_ts=1, data=b"\xff\xd8A" + b"0" * 20, is_person=False)
    arc.archive(name="2_person.jpg", unix_ts=2, data=b"\xff\xd8B" + b"0" * 20, is_person=True)
    cam = DreameAlbumPhotoCamera(_Coord(arc), entry_id="e1")
    assert cam._latest_bytes()[:3] == b"\xff\xd8B"          # newest overall
    person = DreamePersonPhotoCamera(_Coord(arc), entry_id="e1")
    assert person._latest_bytes()[:3] == b"\xff\xd8B"        # newest person
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_photo_camera.py -v`
Expected: FAIL — module/class not found.

- [ ] **Step 4: Add a `photo_archive` property on the coordinator**

In `coordinator/_lidar_oss.py` (or wherever the lidar archive accessor lives),
add:
```python
@property
def photo_archive(self):
    return self._photo_archive
```

- [ ] **Step 5: Implement the two camera classes**

Mirror `_camera_lidar.py` exactly for device_info, unique_id, availability, and
the token-rotation refresh. The two classes differ only in which archive method
they read:
```python
# custom_components/dreame_a2_mower/_camera_photos.py
"""Camera entities for album (Patrol + AI-obstacle) photos.

[dreame-app-implementation-guide-2026-06-09.md] Two entities: the latest album
photo overall, and the latest person/guard-detection (`_person.jpg`) photo. The
app only distinguishes type on the photo itself, not in the list, so `_person`
is the only reliable discriminator we expose.

Follows the access_token-rotation refresh pattern from _camera_lidar.py
(feedback_camera_image_refresh_pattern): on new data, broadcast → await render →
broadcast again so the browser re-fetches instead of serving a cached frame.
"""
from __future__ import annotations

from homeassistant.components.camera import Camera

from ._devices import mower_device_info
from .const import DOMAIN


class _BasePhotoCamera(Camera):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__()
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_device_info = mower_device_info(entry_id)

    def _latest_bytes(self) -> bytes | None:  # overridden
        raise NotImplementedError

    async def async_camera_image(self, width=None, height=None) -> bytes | None:
        return await self.coordinator.hass.async_add_executor_job(self._latest_bytes)

    @property
    def available(self) -> bool:
        return self._latest_bytes() is not None


class DreameAlbumPhotoCamera(_BasePhotoCamera):
    _attr_name = "Latest photo"
    _attr_unique_id = None

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_album_photo"

    def _latest_bytes(self) -> bytes | None:
        e = self.coordinator.photo_archive.latest()
        return self.coordinator.photo_archive.read_bytes(e.filename) if e else None


class DreamePersonPhotoCamera(_BasePhotoCamera):
    _attr_name = "Latest person detection"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_person_photo"

    def _latest_bytes(self) -> bytes | None:
        e = self.coordinator.photo_archive.latest_person()
        return self.coordinator.photo_archive.read_bytes(e.filename) if e else None
```
> Verify `mower_device_info`'s real signature in `_devices.py` and match it
> (it may take the coordinator/entry differently). Follow the per-map naming
> rule: these are parent-device entities (`DEFAULT_NAME`), `_attr_name` is the
> entity name only.

- [ ] **Step 6: Register in `camera.py async_setup_entry`**

Add `DreameAlbumPhotoCamera(coordinator, entry.entry_id)` and
`DreamePersonPhotoCamera(...)` to the entity list passed to `async_add_entities`.

- [ ] **Step 7: Add both entities to `entity-inventory.yaml`** (read source = PhotoArchive; control = read-only) so the inventory-touch-gate passes.

- [ ] **Step 8: Run the test + the camera regression subset**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_photo_camera.py tests/integration/test_per_map_entity_names.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add custom_components/dreame_a2_mower/_camera_photos.py custom_components/dreame_a2_mower/camera.py custom_components/dreame_a2_mower/coordinator/_lidar_oss.py custom_components/dreame_a2_mower/entity-inventory.yaml tests/integration/test_photo_camera.py
git commit -m "feat(photos): album + person-detection camera entities"
```

---

## Part C — Read-key probe tool

### Task 9: `tools/probes/read_key_probe.py`

**Files:**
- Create: `tools/probes/read_key_probe.py`

- [ ] **Step 1: Write the probe**

```python
# tools/probes/read_key_probe.py
"""LIVE read-only probe: issue routed-get for the app's t-key vocabulary.

[dreame-app-implementation-guide-2026-06-09.md] The app reads via
action(siid:2,aiid:50) {"m":"g","t":<KEY>,"d":<args>}. This issues that for each
key and pretty-prints the raw response inline with timestamps
(feedback_inline_logging), so the responses can be decoded into Phase 2 entities
without the Mac MITM rig. Read-only; dev-box only.

Usage: /data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/read_key_probe.py
"""
from __future__ import annotations

import json
from datetime import datetime

from _probe_common import connect

KEYS = [
    ("MPOS", None), ("PREI", None), ("PRE", None), ("AIOBS", None),
    ("RGBPSTA", None), ("MITRC", {"idx": 0, "size": 20}), ("SCHDTV3", None),
    ("MAPI", None), ("MAPL", None), ("MISTA", None), ("OBS", None),
]


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main() -> None:
    cloud = connect()
    for key, d in KEYS:
        try:
            resp = cloud.action(siid=2, aiid=50, parameters=[{"m": "g", "t": key, "d": d}])
        except Exception as ex:  # noqa: BLE001
            print(f"[{_ts()}] t={key}: raised {ex!r}")
            continue
        print(f"[{_ts()}] t={key}  d={d} →")
        print(json.dumps(resp, indent=2, default=str)[:2000])
        print("-" * 60)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it live; paste the raw outputs into the inventory open_questions**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/read_key_probe.py`
Expected: each key prints either a `code:0` body (record the shape against its `*-decode` open_question) or an error (record that too — `r=-1/-3` likely means idle-only, cf. MISTA). For any key that returns a decodable body, add a `partial` verification to its inventory entry citing this run.

- [ ] **Step 3: Commit**

```bash
git add tools/probes/read_key_probe.py custom_components/dreame_a2_mower/inventory.yaml
git commit -m "feat(probes): routed-get read-key probe + decode material for Phase 2"
```

---

## Part D — LiDAR fetch-parity investigation

### Task 10: `tools/probes/lidar_parity_probe.py`

**Files:**
- Create: `tools/probes/lidar_parity_probe.py`

- [ ] **Step 1: Write the probe**

The app renders a newer/denser scan than the integration. Diff our
`list_3dmap_objects()` result (object name + the PCD point count we'd fetch)
against the app's captured sample (`<did>_154157120.0550.bin`, 153,261 points,
`2026/04/20` — `[dreame-app-implementation-guide-2026-06-09.md]`).

```python
# tools/probes/lidar_parity_probe.py
"""LIVE read-only probe: is our 3dmap object the same one the app renders?

[dreame-app-implementation-guide-2026-06-09.md] reports the app fetches a
153,261-point PCD dated 2026/04/20. This lists our OBJ objects, fetches the
newest, decodes the PCD header (protocol/pcd.py), and prints name/date/point
count so we can tell whether OBJ-list hands us a stale/sparser object or the
dense scan is on a surface we don't reach (op10_3dmap_negative).
"""
from __future__ import annotations

from datetime import datetime

from _probe_common import connect


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def main() -> None:
    from custom_components.dreame_a2_mower.protocol.pcd import decode_pcd_header
    cloud = connect()
    names = cloud.list_3dmap_objects()
    print(f"[{_ts()}] list_3dmap_objects → {names!r}")
    if not names:
        print("No 3dmap objects from OBJ-list (None=80001/failure, []=empty).")
        return
    for name in names[:3]:
        url = cloud.get_interim_file_url(name)
        body = cloud.get_file(url) if url else None
        if not body:
            print(f"[{_ts()}] {name}: no body")
            continue
        try:
            hdr = decode_pcd_header(body)
            pts = getattr(hdr, "points", "?")
        except Exception as ex:  # noqa: BLE001
            pts = f"header-decode-failed: {ex!r}"
        print(f"[{_ts()}] {name}: {len(body)} bytes, points={pts}")
    print("App reference: <did>_154157120.0550.bin, 153261 points, 2026/04/20.")
```
> Confirm the real header decoder name/signature in `protocol/pcd.py`
> (the convention is `decode_pcd_header`); match it.

- [ ] **Step 2: Run it live and record the finding**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/lidar_parity_probe.py`
Expected: prints our object name(s) + point count. **Compare to 153,261 / 2026/04/20.** Record one of:
- *Parity confirmed* (same object, similar density) → add a `verified` line to the `s99p20` inventory entry; close the question.
- *We get a stale/sparser object* → file a Phase 2 code fix (OBJ-list recency selection) + add an `open_questions` id `lidar-stale-object`.
- *Dense scan not in OBJ-list* → add `open_questions` id `lidar-dense-source` and the matching Spec B §4.8 capture item.

- [ ] **Step 3: Commit**

```bash
git add tools/probes/lidar_parity_probe.py custom_components/dreame_a2_mower/inventory.yaml
git commit -m "feat(probes): LiDAR fetch-parity probe + finding (app vs integration scan)"
```

---

## Part E — sendCommand / 80001 verification

### Task 11: Verify our RPC path matches the app's `device/sendCommand`

**Files:**
- Read: `custom_components/dreame_a2_mower/cloud_client/_rpc.py`
- Modify: `docs/research/cloud-write-reference.md`

- [ ] **Step 1: Confirm the endpoint + envelope our client uses**

Run: `grep -n "sendCommand\|get_api_url\|def action\|def send\|from\": \|method" custom_components/dreame_a2_mower/cloud_client/_rpc.py | head -40`
Expected: shows whether `_rpc.py` POSTs to `…/device/sendCommand` with `{did,id,data:{method,params,from}}` (the app's shape).

- [ ] **Step 2: Run a `get_properties` + a routed-`get` live and observe the result code**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/probes/read_key_probe.py 2>&1 | grep -i "code\|80001\|raised" | head`
Expected: classify when `code:0` vs `80001` actually occurs (online vs asleep/slow-prop). This is observation, not a code change.

- [ ] **Step 3: Record the reframe in `cloud-write-reference.md`**

Under the section added in Task 3 Step 2, append the observed reality:
```markdown
**Verified 2026-06-09 (our client):** read_key_probe.py returned <code:0 / 80001>
for routed-gets while the mower was <online/asleep>. The 80001 correlates with
<asleep / slow-prop>, matching the app-observed reframe. Our _rpc.py path
<does/does not> already target device/sendCommand.
```
Fill the angle-brackets from the Step 2 observation. If `_rpc.py` already
targets `sendCommand` (likely), state that no code change is needed; if it uses
a different endpoint that 80001s more, file a Phase 2 `open_questions`.

- [ ] **Step 4: Commit**

```bash
git add docs/research/cloud-write-reference.md
git commit -m "docs(research): verify sendCommand path + 80001 reframe on our client"
```

---

## Final verification

- [ ] **Run the full affected test surface**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_photo_keys.py tests/archive/test_photo_archive.py tests/integration/test_photo_fetch.py tests/integration/test_photo_camera.py tests/inventory -v`
Expected: all PASS; inventory schema + touch gates green.

- [ ] **Run the inventory audit**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_audit.py`
Expected: no errors.

- [ ] **Update memories** (per CLAUDE.md / brainstorming close-out): `project_g2408_ai_photo_probe` → resolved (album path shipped); backend-B identity; the LiDAR parity finding; note Phase 2 + Spec B as the next step.

- [ ] **Release** (per `feedback_tag_after_push` / `release.sh`): bump alpha, push, `gh release create … --prerelease`, refresh HACS. Mind the digit-boundary version-ladder trap (`feedback_hacs_version_ladder`).

---

## Spec coverage self-check

| Spec A §3 item | Task(s) |
|---|---|
| §3.1 doc reconciliation (incl. all partial/deferred) | 1, 2, 3 |
| §3.2 album photos (key, archive, fetch, cameras, privacy) | 4, 5, 6, 7, 8, 3(privacy) |
| §3.3 read-probe tool | 9 |
| §3.4 LiDAR fetch-parity | 10 |
| §3.5 sendCommand/80001 verify | 11 |
| Phase 2 partials documented now | 1, 2 (`open_questions` + `partial`) |
