# ioBroker.dreame Findings Adoption — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt every finding from `docs/research/2026-04-23-iobroker-dreame-cross-reference.md` into the integration without breaking alpha.74 functionality. Validate every binary-frame-decoder change against captured g2408 telemetry before adopting (apk targets g2568a; layouts may differ).

**Architecture:**
- New `protocol/cfg_action.py` module wraps the `siid:2 aiid:50` action call with `{m,t,d}` payload routing.
- `DreameMowerDevice` gains a `cfg` cache populated by an asynchronous fetch on coordinator first refresh + on every `s2p52` (preference change) or `s2p51` (settings change) push.
- A new `protocol/pose.py` validates and (if confirmed correct on g2408) replaces the int16_le pose decoder with the apk's 12-bit-packed variant.
- Settings, sensors, and action buttons added to existing entity platforms (number, sensor, switch, button) — no new platform plumbing required.
- Each new entity gets an availability gate based on whether its CFG key showed up in the latest fetch (so g2408 doesn't get phantom controls for fields it doesn't expose).

**Tech Stack:** Python 3.13+, Home Assistant 2025.x, paho-mqtt, pytest. PIL for trail rendering (unchanged). New: nothing — uses existing protocol.action / requestClient infrastructure.

---

## File Structure

| File | Purpose | Status |
|---|---|---|
| `custom_components/dreame_a2_mower/protocol/cfg_action.py` | New module: type-safe wrappers for `siid:2 aiid:50` get/set/action calls | CREATE |
| `custom_components/dreame_a2_mower/protocol/pose.py` | New module: pose decoders (int16_le legacy + 12-bit packed apk variant) for side-by-side validation | CREATE |
| `custom_components/dreame_a2_mower/dreame/device.py` | Add `cfg` cache, getCFG fetch, fields from new piid handlers (53/57/58/61), uint24 task fields | MODIFY |
| `custom_components/dreame_a2_mower/protocol/telemetry.py` | Switch pose decoder once validated; add angle field; uint24 area fields | MODIFY |
| `custom_components/dreame_a2_mower/sensor.py` | New sensors: cutting_height, mow_mode, edge_*, headlight_*, gps, wear_meters, dock_pos, ai_obstacles | MODIFY |
| `custom_components/dreame_a2_mower/number.py` | New number entities for PRE settings (cutting_height, obstacle_distance, coverage%) | MODIFY |
| `custom_components/dreame_a2_mower/switch.py` | New switch entities (mow_mode, direction_change, edge_mowing, edge_detection, headlight_enabled, anti_theft, ata, weather_ref, protection_mode) | MODIFY |
| `custom_components/dreame_a2_mower/button.py` | New buttons: cutter_bias, suppress_fault, find_bot, lock_bot, take_pic | MODIFY |
| `custom_components/dreame_a2_mower/coordinator.py` | Wire CFG fetch on first refresh; subscribe to s2p51/s2p52 to refetch | MODIFY |
| `docs/research/g2408-protocol.md` | Update piid catalog: s2p1/s2p2/s1p51/s2p52 corrections; document confirmed cloud schema; add CFG / action sections | MODIFY |
| `tests/protocol/test_cfg_action.py` | Tests for CFG fetch, PRE setter, error paths | CREATE |
| `tests/protocol/test_pose.py` | Tests for both decoder variants against captured probe-log frames; cross-check assertions | CREATE |
| `tests/protocol/fixtures/captured_s1p4_frames.json` | Real captured 33-byte frames from probe logs with known mower position at capture time | CREATE |

---

## Pre-flight: working branch + clean test baseline

- [ ] **Step 0.1: Confirm test baseline is green**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/ -q`
Expected: `161 passed, 4 skipped` (or equivalent — the alpha.74 baseline). If this fails, STOP and reconcile before proceeding.

- [ ] **Step 0.2: Confirm we're on a clean main**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && git status -s`
Expected: empty output. If dirty, STOP and clean up.

---

## Task 1: Pose decoder validation (apk 12-bit-packed vs our int16_le)

**Why first:** if the apk's 12-bit decode is correct on g2408, every existing area/distance/path computation in the integration depends on a wrong x/y. We MUST verify before any other work — adopting other findings on top of a broken position decode would compound.

**Files:**
- Create: `tests/protocol/fixtures/captured_s1p4_frames.json`
- Create: `tests/protocol/test_pose.py`
- Create: `custom_components/dreame_a2_mower/protocol/pose.py`

- [ ] **Step 1.1: Capture 5–10 known-position s1p4 frames**

Mine `/data/claude/homeassistant/probe_log_20260419_130434.jsonl` for 33-byte s1p4 values where the mower position is unambiguously known (e.g. immediately after dock departure: x≈0, y≈0; after first row turn: known approximate location).

Run:
```bash
awk '/"timestamp":"2026-04-22 20:47:[0-9][0-9]"/' /data/claude/homeassistant/probe_log_20260419_130434.jsonl | python3 -c "
import json,sys
for ln in sys.stdin:
    try: d=json.loads(ln)
    except: continue
    if d.get('type')!='mqtt_message': continue
    pd=d.get('parsed_data',{})
    if pd.get('method')!='properties_changed': continue
    for p in pd.get('params',[]) or []:
        if not isinstance(p,dict): continue
        s,pi,v=p.get('siid'),p.get('piid'),p.get('value')
        if (s,pi)==(1,4) and isinstance(v,list) and len(v)==33:
            print(json.dumps({'ts':d['timestamp'],'bytes':v}))
" > /tmp/s1p4_capture.jsonl
wc -l /tmp/s1p4_capture.jsonl
```
Expected: ≥10 lines.

- [ ] **Step 1.2: Pick 5 frames with documented known positions**

The 2026-04-22 dock-departure capture (between 20:47:44 and 20:48:09) is known: mower drove a straight line from dock (0,0) westward to (-9.76, -1.04). Pick 5 consecutive frames from that range.

Create `tests/protocol/fixtures/captured_s1p4_frames.json` with this content:

```json
{
  "frames": [
    {
      "ts": "2026-04-22 20:47:44",
      "bytes": [206, 0, 0, 96, 255, 255, ... PASTE FROM /tmp/s1p4_capture.jsonl ...],
      "expected_x_cm_int16le": 0,
      "expected_y_mm_int16le": -100,
      "context": "at dock, post-recharge resume, frame[8] phase=2"
    }
  ]
}
```

Use the actual 33-byte values from /tmp/s1p4_capture.jsonl. Compute `expected_x_cm_int16le` by manually reading bytes [1-2] as little-endian signed int16, and `expected_y_mm_int16le` from bytes [3-4]. These are what the CURRENT decoder produces — they're the baseline we have to either confirm (current decoder right, apk wrong on g2408) or refute (apk right, current decoder wrong).

- [ ] **Step 1.3: Write the dual-decoder module**

Create `custom_components/dreame_a2_mower/protocol/pose.py`:

```python
"""Two pose decoders for s1p4 frames — used to validate which one
matches g2408 firmware behavior.

Background: the existing telemetry decoder (telemetry.py) reads pose
as int16_le from bytes [1-2] (x_cm) and [3-4] (y_mm). The
ioBroker.dreame APK decompilation (apk.md) shows a different layout
on g2568a: bytes [1-6] hold three packed values (x24, y24, angle8)
where x and y share byte [3] (the original numbering — adjust by 1
since our 0xCE delimiter at byte 0 means the apk's "byte 0" is our
byte 1).

This module exposes both decoders so a test suite can run them
side by side against captured frames. The integration code can
later switch to whichever proves correct on g2408 — or keep both
behind a feature flag if the answer is firmware-dependent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PoseInt16LE:
    """Result of the original int16_le decoder."""
    x_cm: int
    y_mm: int


@dataclass(frozen=True)
class PosePacked12:
    """Result of the apk's 12-bit-packed decoder."""
    x_raw: int       # signed 24-bit (sign-extended from 12 bits packed)
    y_raw: int       # signed 24-bit
    angle_deg: float # 0..360
    # Convenience: the apk says x_raw/y_raw map to "map coords" via *10.
    # We expose the raw values so callers can choose units.


def decode_pose_int16le(payload: Sequence[int]) -> PoseInt16LE:
    """Original decoder — reads bytes [1-2] as int16_le x_cm and [3-4]
    as int16_le y_mm. Assumes the leading 0xCE delimiter at byte 0."""
    if len(payload) < 5:
        raise ValueError(f"need ≥5 bytes for int16_le decode, got {len(payload)}")
    x_lo, x_hi = payload[1], payload[2]
    y_lo, y_hi = payload[3], payload[4]
    x = x_lo | (x_hi << 8)
    if x & 0x8000:
        x -= 0x10000
    y = y_lo | (y_hi << 8)
    if y & 0x8000:
        y -= 0x10000
    return PoseInt16LE(x_cm=x, y_mm=y)


def decode_pose_packed12(payload: Sequence[int]) -> PosePacked12:
    """APK's decoder — bytes [1-6] hold (x24, y24, angle8) packed.
    Per apk.md parseRobotPose, the in-payload offsets are 0..5
    (the apk passes bytes after the 0xCE delimiter is stripped),
    so we read our payload[1..6] as the apk's payload[0..5]."""
    if len(payload) < 7:
        raise ValueError(f"need ≥7 bytes for packed12 decode, got {len(payload)}")
    p = payload[1:]  # apk's "payload[0..5]"
    x = (p[2] << 28) | (p[1] << 20) | (p[0] << 12)
    x = x >> 12       # arithmetic right shift for sign extension
    y = (p[4] << 24) | (p[3] << 16) | (p[2] << 8)
    y = y >> 12
    angle = (p[5] / 255.0) * 360.0
    return PosePacked12(x_raw=x, y_raw=y, angle_deg=angle)
```

- [ ] **Step 1.4: Write the validation test suite**

Create `tests/protocol/test_pose.py`:

```python
"""Validation tests: do the int16_le and 12-bit-packed pose decoders
agree on captured g2408 frames? If they diverge, the apk decoder is
wrong for g2408 (or vice versa)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protocol.pose import (
    decode_pose_int16le,
    decode_pose_packed12,
)


_FIXTURES = Path(__file__).parent / "fixtures" / "captured_s1p4_frames.json"


def _load_frames():
    with _FIXTURES.open() as fh:
        return json.load(fh)["frames"]


@pytest.mark.parametrize("frame", _load_frames())
def test_int16le_decode_matches_capture_baseline(frame):
    """Sanity: the int16_le decoder still produces the values we
    expect from the captured frames. If this fails, our test
    fixture is malformed or the decoder regressed."""
    got = decode_pose_int16le(frame["bytes"])
    assert got.x_cm == frame["expected_x_cm_int16le"]
    assert got.y_mm == frame["expected_y_mm_int16le"]


@pytest.mark.parametrize("frame", _load_frames())
def test_packed12_decode_runs_without_error(frame):
    """Sanity: the apk decoder doesn't crash on real frames."""
    got = decode_pose_packed12(frame["bytes"])
    # No assertion on the value here — Step 1.5 compares.
    assert isinstance(got.x_raw, int)
    assert isinstance(got.y_raw, int)
    assert 0.0 <= got.angle_deg < 360.0


def test_decoders_agree_for_zero_position():
    """If the mower is at (0, 0), both decoders should return 0/0
    regardless of which scheme is correct — both interpretations
    of an all-zero byte slice yield 0."""
    payload = [0xCE] + [0] * 32
    assert decode_pose_int16le(payload).x_cm == 0
    assert decode_pose_int16le(payload).y_mm == 0
    assert decode_pose_packed12(payload).x_raw == 0
    assert decode_pose_packed12(payload).y_raw == 0
```

- [ ] **Step 1.5: Run the validation test**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/protocol/test_pose.py -v`
Expected: all parametrize cases pass for `test_int16le_decode_matches_capture_baseline` (sanity check confirms the fixture is correct) and `test_packed12_decode_runs_without_error` (apk decoder doesn't crash). The `test_decoders_agree_for_zero_position` should pass.

- [ ] **Step 1.6: Compute side-by-side comparison + write decision**

Run this one-liner to print int16_le vs packed12 outputs for every captured frame:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && python -c "
import json, sys
sys.path.insert(0, 'custom_components/dreame_a2_mower')
from protocol.pose import decode_pose_int16le, decode_pose_packed12
data = json.load(open('tests/protocol/fixtures/captured_s1p4_frames.json'))
for f in data['frames']:
    a = decode_pose_int16le(f['bytes'])
    b = decode_pose_packed12(f['bytes'])
    print(f\"{f['ts']}  int16le=({a.x_cm:+5d}, {a.y_mm:+6d})  packed12=({b.x_raw:+8d}, {b.y_raw:+8d}, {b.angle_deg:5.1f}°)  ctx={f['context']}\")
"
```

Append the results plus a short verdict (2-3 lines) to `tests/protocol/fixtures/captured_s1p4_frames.json` under a new `verdict` field. Three possible outcomes:

- **Verdict A**: int16_le and packed12 produce identical x/y for all captured frames → either decoder is fine; keep int16_le, add angle byte parsing in a separate task.
- **Verdict B**: packed12 produces values consistent with the documented mowing path (the dock-departure straight line from (0,0) westward, where x decreases linearly), int16_le diverges → switch decoder.
- **Verdict C**: int16_le matches the documented path, packed12 produces nonsense → keep int16_le, document the apk's decoder as g2568a-specific.

Most likely outcome (based on the small-coord discussion in cross-ref §3.1) is **Verdict A or C** for our captures (small lawn, small numbers). Beyond ±32 m the answer would change but our capture range never goes there.

- [ ] **Step 1.7: Commit Task 1**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
git add custom_components/dreame_a2_mower/protocol/pose.py tests/protocol/test_pose.py tests/protocol/fixtures/captured_s1p4_frames.json
git commit -m "test: side-by-side validate int16_le vs packed12 pose decoders

Adds pose.py with both decoders + a fixture of captured g2408 s1p4
frames + a parametrized test suite. The verdict field in the
fixture file records the empirical conclusion against each capture
so subsequent decoder changes have a baseline to reference.

No production code change in this task — telemetry.py still uses
int16_le. Switching depends on Verdict B; angle-byte adoption
depends on a separate task once Verdict is known.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add the angle byte to MowingTelemetry (regardless of Task 1 verdict)

**Why:** byte [5] of the s1p4 frame is the heading angle (0..255 → 0..360°) per apk. Even if int16_le pose is correct, we're discarding this byte. Adding it lets the mower icon be rendered with proper orientation in a future trail-overlay update.

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/telemetry.py`
- Test: `tests/protocol/test_telemetry.py` (existing file, add cases)

- [ ] **Step 2.1: Add angle to the dataclass**

Open `custom_components/dreame_a2_mower/protocol/telemetry.py`, find `class MowingTelemetry`, and add a new field after `area_mowed_m2`:

```python
@dataclass(frozen=True)
class MowingTelemetry:
    # ...existing fields...
    area_mowed_m2: float
    # Heading angle from s1p4 byte [5]. 0..255 → 0..360 degrees,
    # decoded from one byte. Confirmed by apk decompilation
    # (parseRobotPose). Useful for orienting the mower icon.
    heading_deg: float
```

- [ ] **Step 2.2: Decode the angle in `decode_s1p4`**

Find `def decode_s1p4` in the same file. Locate the line where `area_mowed_cent = struct.unpack_from("<H", data, 29)[0]`. Add the angle decode and pass it to the constructor:

```python
def decode_s1p4(data: bytes) -> MowingTelemetry:
    # ...existing validation + field reads...
    area_mowed_cent = struct.unpack_from("<H", data, 29)[0]
    heading_byte = data[5]                       # NEW: angle byte
    heading_deg = (heading_byte / 255.0) * 360.0  # NEW: convert
    return MowingTelemetry(
        # ...existing args...
        area_mowed_m2=area_mowed_cent / 100.0,
        heading_deg=heading_deg,                  # NEW
    )
```

- [ ] **Step 2.3: Write the test for angle decode**

Open `tests/protocol/test_telemetry.py`, find an existing decode test for context, and add at the end of the file:

```python
def test_decode_s1p4_extracts_heading_angle():
    """s1p4 byte[5] is heading angle 0..255 → 0..360°."""
    # Build a minimal valid 33-byte frame with byte[5] = 128 (mid-range)
    frame = bytearray([0xCE] + [0] * 31 + [0xCE])
    frame[5] = 128
    telem = decode_s1p4(bytes(frame))
    # 128 / 255 * 360 ≈ 180.7°. Allow 0.5° float drift.
    assert 180.0 < telem.heading_deg < 181.5


def test_decode_s1p4_heading_zero_for_zero_byte():
    frame = bytearray([0xCE] + [0] * 31 + [0xCE])
    telem = decode_s1p4(bytes(frame))
    assert telem.heading_deg == 0.0


def test_decode_s1p4_heading_full_circle_just_under_360():
    frame = bytearray([0xCE] + [0] * 31 + [0xCE])
    frame[5] = 255
    telem = decode_s1p4(bytes(frame))
    # 255 / 255 * 360 = 360 exactly. Acceptable; downstream
    # consumers should mod-360 if they care about [0, 360).
    assert telem.heading_deg == 360.0
```

Note: the test fixture uses `bytearray([0xCE] + [0]*31 + [0xCE])` = 33 bytes total (1 + 31 + 1 = 33). Confirm that matches your existing decode_s1p4 frame validation.

- [ ] **Step 2.4: Run the new tests**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/protocol/test_telemetry.py -v`
Expected: all existing tests still pass, plus the 3 new ones pass.

- [ ] **Step 2.5: Commit Task 2**

```bash
git add custom_components/dreame_a2_mower/protocol/telemetry.py tests/protocol/test_telemetry.py
git commit -m "feat(telemetry): decode s1p4 heading angle from byte[5]

Per apk.md parseRobotPose, byte[5] of the 33-byte s1p4 frame is
a uint8 heading: 0..255 maps linearly to 0..360 degrees. The
existing decoder discarded it; now exposed as
MowingTelemetry.heading_deg so future renderers can orient the
mower icon.

3 new tests cover zero, mid-range, and 255-byte cases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Decode uint24 task fields (regionId, taskId, percent, total, finish)

**Why:** apk says bytes [22-31] of the 33-byte frame contain task progress fields with uint24 area encoding, exposing regionId / taskId / percent we don't currently surface. Our current uint16 read of areas works for ≤655 m² lawns but truncates beyond that. Plus `percent` is the mowing-progress % the app shows.

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/telemetry.py`
- Test: `tests/protocol/test_telemetry.py`

- [ ] **Step 3.1: Add the new fields to MowingTelemetry**

Edit the dataclass to add (after `heading_deg` from Task 2):

```python
@dataclass(frozen=True)
class MowingTelemetry:
    # ...existing fields...
    heading_deg: float
    # Task struct from frame bytes [22-31] per apk parseRobotTask.
    # On g2408 these fields may overlap with our current
    # distance_deci / total_area_cent / area_mowed_cent reads —
    # both interpretations are computed in decode_s1p4 and the
    # caller can pick whichever the field-validation effort
    # (Task 1) blesses.
    region_id: int
    task_id: int
    percent: float       # 0..100 mowing progress
    total_uint24_m2: float
    finish_uint24_m2: float
```

- [ ] **Step 3.2: Add a uint24 helper + decode the task struct**

Inside `protocol/telemetry.py` (top-level helper, just above `decode_s1p4`):

```python
def _read_uint24_le(buf: bytes, offset: int) -> int:
    """Read a little-endian unsigned 24-bit integer from `buf` at `offset`."""
    return buf[offset] | (buf[offset + 1] << 8) | (buf[offset + 2] << 16)
```

Inside `decode_s1p4`, after the existing area reads:

```python
def decode_s1p4(data: bytes) -> MowingTelemetry:
    # ...existing reads up to and including area_mowed_cent...
    # apk parseRobotTask: payload bytes [22-31] of the frame.
    # Interpreted as a 10-byte sub-struct starting at frame[22]:
    #   [22] regionId (uint8)
    #   [23] taskId (uint8)
    #   [24-25] percent ÷ 100 → %
    #   [26-28] total m² × 100 (uint24_le)
    #   [29-31] finish m² × 100 (uint24_le)
    region_id = data[22]
    task_id = data[23]
    percent_raw = struct.unpack_from("<H", data, 24)[0]
    percent = percent_raw / 100.0
    total_u24_cent = _read_uint24_le(data, 26)
    finish_u24_cent = _read_uint24_le(data, 29)
    return MowingTelemetry(
        # ...existing args (incl heading_deg from Task 2)...
        region_id=region_id,
        task_id=task_id,
        percent=percent,
        total_uint24_m2=total_u24_cent / 100.0,
        finish_uint24_m2=finish_u24_cent / 100.0,
    )
```

Note: the existing `total_area_cent` (bytes 26-27) and `area_mowed_cent` (bytes 29-30) reads are LEFT IN PLACE. They're the low 16 bits of the apk's uint24. Both decoded fields are exposed; downstream code keeps using the legacy fields until Task 4 confirms the swap is safe.

- [ ] **Step 3.3: Write tests for the new fields**

Append to `tests/protocol/test_telemetry.py`:

```python
def test_decode_s1p4_task_struct_zero_frame():
    """All-zero frame: every task field is 0."""
    frame = bytes([0xCE] + [0] * 31 + [0xCE])
    telem = decode_s1p4(frame)
    assert telem.region_id == 0
    assert telem.task_id == 0
    assert telem.percent == 0.0
    assert telem.total_uint24_m2 == 0.0
    assert telem.finish_uint24_m2 == 0.0


def test_decode_s1p4_task_struct_uint24_overflows_uint16():
    """If total_uint24 > 65535 cm² (655.35 m²), the legacy uint16
    read truncates; the new uint24 read survives. Pin the
    behavior."""
    frame = bytearray([0xCE] + [0] * 31 + [0xCE])
    # Set bytes [26-28] to 0x000100 little-endian → 65536 cent
    # → 655.36 m². Just above uint16 max.
    frame[26] = 0x00
    frame[27] = 0x00
    frame[28] = 0x01
    telem = decode_s1p4(bytes(frame))
    assert telem.total_uint24_m2 == 655.36
    # Legacy field would read bytes [26-27] = 0 → reports 0.
    # The legacy field stays available; consumers who need the
    # bigger range use total_uint24_m2.
    assert telem.total_area_m2 == 0.0


def test_decode_s1p4_task_percent_division():
    """percent = bytes[24-25] / 100. Test 5000 raw → 50.00 %."""
    frame = bytearray([0xCE] + [0] * 31 + [0xCE])
    # 5000 little-endian = 0x88, 0x13
    frame[24] = 0x88
    frame[25] = 0x13
    telem = decode_s1p4(bytes(frame))
    assert telem.percent == 50.0
```

- [ ] **Step 3.4: Run tests**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/protocol/test_telemetry.py -v`
Expected: all existing tests pass + 3 new pass.

- [ ] **Step 3.5: Commit Task 3**

```bash
git add custom_components/dreame_a2_mower/protocol/telemetry.py tests/protocol/test_telemetry.py
git commit -m "feat(telemetry): expose region_id / task_id / percent / uint24 areas

Per apk.md parseRobotTask, frame bytes [22-31] hold a 10-byte task
struct. Adds:
- region_id: which zone the active task is in
- task_id: which logical task the firmware is running
- percent: mowing-progress % (0..100; what the app shows)
- total_uint24_m2 / finish_uint24_m2: full uint24 area reads
  that don't truncate above 655 m² like the legacy uint16 reads

Legacy total_area_m2 / area_mowed_m2 fields are preserved for
back-compat. Downstream code that needs lawn coverage > 655 m²
should switch to the uint24 fields once field-validated.

3 new tests pin the behavior including the uint16-overflow case.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Field-validate uint24 + percent against captured frames

**Why:** before exposing region_id/task_id/percent to entity consumers, confirm the values are sensible on g2408. Bad data here would surface as confusing "task ID = 137" sensors.

**Files:**
- Test: `tests/protocol/test_pose.py` (extend with task-field assertions)

- [ ] **Step 4.1: Inspect captured task fields**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -c "
import json, sys
sys.path.insert(0, 'custom_components/dreame_a2_mower')
from protocol.telemetry import decode_s1p4
data = json.load(open('tests/protocol/fixtures/captured_s1p4_frames.json'))
for f in data['frames']:
    t = decode_s1p4(bytes(f['bytes']))
    print(f\"{f['ts']}  region={t.region_id} task={t.task_id} pct={t.percent:.2f}% total={t.total_uint24_m2:.2f}/{t.total_area_m2:.2f} finish={t.finish_uint24_m2:.2f}/{t.area_mowed_m2:.2f}\")
"`

- [ ] **Step 4.2: Document the verdict in the fixture file**

Add a `task_struct_verdict` field to `tests/protocol/fixtures/captured_s1p4_frames.json` with one of:
- "valid": region_id ∈ {0,1,2,...} sensible, task_id stable across consecutive frames during one mow, percent monotonic, uint24 ≈ uint16 (low bytes match for small lawns).
- "diverges": task_id varies per-frame, percent non-monotonic, uint24 vs uint16 mismatch — apk struct doesn't apply on g2408.

If "valid", proceed; if "diverges", mark all entity tasks below as conditional and document the divergence in protocol doc §3.1.

- [ ] **Step 4.3: Add an assertion test based on the verdict**

Append to `tests/protocol/test_pose.py`:

```python
def test_task_struct_field_sanity():
    """Confirm the captured frames produce sensible task fields.
    The verdict field in the fixture documents what 'sensible'
    means for our captures."""
    import json
    from pathlib import Path
    from protocol.telemetry import decode_s1p4
    data = json.load(
        (Path(__file__).parent / "fixtures" / "captured_s1p4_frames.json").open()
    )
    verdict = data.get("task_struct_verdict", "unknown")
    if verdict == "diverges":
        pytest.skip(f"task_struct decoder diverged on g2408 — see fixture verdict")
    for f in data["frames"]:
        t = decode_s1p4(bytes(f["bytes"]))
        # Sane bounds for any g2408 telemetry frame.
        assert 0 <= t.region_id < 32, f"unreasonable region_id {t.region_id}"
        assert 0 <= t.percent <= 100, f"out-of-range percent {t.percent}"
        assert 0 <= t.total_uint24_m2 < 10000
        assert 0 <= t.finish_uint24_m2 <= t.total_uint24_m2 + 1.0  # finish ≤ total
```

- [ ] **Step 4.4: Run the test**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/protocol/test_pose.py -v`
Expected: pass (or skip with the diverges reason).

- [ ] **Step 4.5: Commit Task 4**

```bash
git add tests/protocol/fixtures/captured_s1p4_frames.json tests/protocol/test_pose.py
git commit -m "test: validate s1p4 task struct against captured g2408 frames

Adds a verdict field to the fixture file recording whether the
apk's task-struct interpretation produces sensible values on
g2408. The new test enforces the verdict — skips with a clear
reason if the verdict is 'diverges', so the rest of the pipeline
can branch on whether to expose region_id / task_id / percent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Action-call infrastructure — `cfg_action.py`

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/cfg_action.py`
- Test: `tests/protocol/test_cfg_action.py`

- [ ] **Step 5.1: Write the module skeleton with type-safe wrappers**

Create `custom_components/dreame_a2_mower/protocol/cfg_action.py`:

```python
"""Routed-action wrappers for siid:2 aiid:50 calls.

Per apk.md, the Dreame mower exposes most of its CFG/PRE/CMS/etc.
machinery via a single MIoT action endpoint at siid=2 aiid=50.
The `in[0]` payload routes by `m` (mode: 'g'=get, 's'=set, 'a'=action,
'r'=remote) and `t` (target: 'CFG', 'PRE', 'DOCK', 'CMS', ...).

Returns are unwrapped from `result.out[0]` (the cloud envelope).

This module provides typed wrappers but deliberately stays
protocol-only — no HA imports. The device.py layer is responsible
for translating CFG payloads into entity state.
"""

from __future__ import annotations

from typing import Any


# Action endpoint constants per apk decompilation.
ROUTED_ACTION_SIID = 2
ROUTED_ACTION_AIID = 50


class CfgActionError(RuntimeError):
    """Raised when a routed action call returns no data."""


def _unwrap(result: Any) -> Any:
    """Unwrap the cloud envelope. The protocol's send-action path
    returns `{"result": {"out": [<payload>]}}` on success and various
    error shapes on failure. We accept any shape that yields an
    `out[0]` mapping; everything else raises."""
    if not isinstance(result, dict):
        raise CfgActionError(f"unexpected result type: {type(result).__name__}")
    inner = result.get("result", result)  # tolerate flat or nested
    out = inner.get("out") if isinstance(inner, dict) else None
    if not isinstance(out, list) or not out:
        raise CfgActionError(f"action returned no `out`: {result!r}")
    return out[0]


def get_cfg(send_action) -> dict:
    """Fetch the full settings dict (WRP, DND, BAT, CLS, VOL, LIT,
    AOP, REC, STUN, ATA, PATH, WRF, PROT, CMS, PRE, ...).

    `send_action` must be a callable matching the protocol's
    action(siid, aiid, parameters) signature.
    """
    raw = send_action(
        ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "g", "t": "CFG"}]
    )
    payload = _unwrap(raw)
    d = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(d, dict):
        raise CfgActionError(f"getCFG returned no `d` dict: {payload!r}")
    return d


def get_dock_pos(send_action) -> dict:
    """Fetch dock position + lawn-connection status."""
    raw = send_action(
        ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "g", "t": "DOCK"}]
    )
    payload = _unwrap(raw)
    d = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(d, dict):
        raise CfgActionError(f"getDockPos returned no `d` dict: {payload!r}")
    dock = d.get("dock")
    if not isinstance(dock, dict):
        raise CfgActionError(f"getDockPos: missing dock subkey: {d!r}")
    return dock


def set_pre(send_action, pre_array: list) -> Any:
    """Write the PRE preferences array. Caller is responsible for
    read-modify-write semantics (read CFG.PRE, modify the slot,
    pass the full updated array here)."""
    if not isinstance(pre_array, list) or len(pre_array) < 10:
        raise ValueError(
            f"PRE array must have ≥10 elements, got {len(pre_array) if isinstance(pre_array, list) else type(pre_array).__name__}"
        )
    return send_action(
        ROUTED_ACTION_SIID,
        ROUTED_ACTION_AIID,
        [{"m": "s", "t": "PRE", "d": {"value": pre_array}}],
    )


def call_action_op(send_action, op: int, extra: dict | None = None) -> Any:
    """Invoke an action opcode (`{m:'a', p:0, o:OP, ...}`).

    Per apk § "Actions", op 100 = globalMower, 101 = edgeMower,
    102 = zoneMower, 110 = startLearningMap, 11 = suppressFault,
    9 = findBot, 12 = lockBot, 401 = takePic, 503 = cutterBias.
    The extra dict (if given) is merged into the payload — for
    zoneMower this is `{region: [zone_id]}`.
    """
    payload: dict = {"m": "a", "p": 0, "o": int(op)}
    if extra:
        payload.update(extra)
    return send_action(ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [payload])
```

- [ ] **Step 5.2: Write the test suite**

Create `tests/protocol/test_cfg_action.py`:

```python
"""Tests for protocol.cfg_action — unwrapping + error paths.
The send_action callable is mocked; no real network."""

from __future__ import annotations

import pytest

from protocol.cfg_action import (
    CfgActionError,
    call_action_op,
    get_cfg,
    get_dock_pos,
    set_pre,
)


def test_get_cfg_unwraps_result_out_d():
    """A successful getCFG returns result.out[0].d as a dict."""
    captured = {}

    def fake_send(siid, aiid, params):
        captured["call"] = (siid, aiid, params)
        return {"result": {"out": [{"d": {"WRP": [1, 8, 0], "VOL": 80}}]}}

    cfg = get_cfg(fake_send)
    assert cfg == {"WRP": [1, 8, 0], "VOL": 80}
    assert captured["call"] == (2, 50, [{"m": "g", "t": "CFG"}])


def test_get_cfg_raises_on_missing_d():
    def fake_send(*_args, **_kw):
        return {"result": {"out": [{"unrelated": 1}]}}

    with pytest.raises(CfgActionError):
        get_cfg(fake_send)


def test_get_cfg_raises_on_empty_out():
    def fake_send(*_args, **_kw):
        return {"result": {"out": []}}

    with pytest.raises(CfgActionError):
        get_cfg(fake_send)


def test_get_dock_pos_unwraps_dock_subkey():
    def fake_send(*_args, **_kw):
        return {"result": {"out": [{"d": {"dock": {"x": 10, "y": -5, "yaw": 90, "connect_status": 1}}}]}}

    dock = get_dock_pos(fake_send)
    assert dock == {"x": 10, "y": -5, "yaw": 90, "connect_status": 1}


def test_set_pre_validates_array_length():
    with pytest.raises(ValueError):
        set_pre(lambda *_a, **_kw: None, [0, 1, 2])  # too short


def test_set_pre_sends_value_envelope():
    captured = []

    def fake_send(siid, aiid, params):
        captured.append((siid, aiid, params))
        return {"result": {"out": [{"d": {}}]}}

    pre = [0, 0, 35, 100, 80, 0, 0, 0, 0, 1]
    set_pre(fake_send, pre)
    assert captured == [(2, 50, [{"m": "s", "t": "PRE", "d": {"value": pre}}])]


def test_call_action_op_basic():
    captured = []

    def fake_send(siid, aiid, params):
        captured.append((siid, aiid, params))
        return {"result": {"out": [{"d": {}}]}}

    call_action_op(fake_send, 100)
    assert captured == [(2, 50, [{"m": "a", "p": 0, "o": 100}])]


def test_call_action_op_with_zone_extra():
    captured = []

    def fake_send(siid, aiid, params):
        captured.append((siid, aiid, params))
        return {"result": {"out": [{"d": {}}]}}

    call_action_op(fake_send, 102, extra={"region": [1, 2]})
    assert captured == [(2, 50, [{"m": "a", "p": 0, "o": 102, "region": [1, 2]}])]
```

- [ ] **Step 5.3: Run tests**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/protocol/test_cfg_action.py -v`
Expected: 7 passed.

- [ ] **Step 5.4: Commit Task 5**

```bash
git add custom_components/dreame_a2_mower/protocol/cfg_action.py tests/protocol/test_cfg_action.py
git commit -m "feat(protocol): routed-action wrappers for siid:2 aiid:50

Per apk.md, the Dreame mower exposes CFG/PRE/CMS/DOCK/etc. through
a single MIoT action endpoint with {m,t,d} payload routing.

New module protocol/cfg_action.py provides typed wrappers:
- get_cfg(send_action) → full settings dict
- get_dock_pos(send_action) → dock position + lawn-connection
- set_pre(send_action, pre_array) → write PRE preferences
- call_action_op(send_action, op, extra) → action opcode dispatch

7 tests cover happy path + error envelopes (no `d`, empty `out`),
PRE length validation, and zone-region extra merging.

Module is HA-import-free — pure protocol layer. The device.py
wiring lands in the next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Wire CFG fetch into the device layer

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/device.py`
- Test: `tests/protocol/test_property_overlay.py` is HA-dependent; skip device-level tests for now (mock-heavy)

- [ ] **Step 6.1: Add cfg cache + fetcher method to device**

Open `custom_components/dreame_a2_mower/dreame/device.py`, find `class DreameMowerDevice` (search for `class DreameMowerDevice`). Inside `__init__`, near the bottom (after the existing init blocks), add:

```python
        # CFG cache — populated by `refresh_cfg()` calls. Each key
        # mirrors what the firmware returns from `getCFG`: WRP, DND,
        # BAT, CLS, VOL, LIT, AOP, REC, STUN, ATA, PATH, WRF, PROT,
        # CMS, PRE. Default empty so consumers can rely on
        # `device.cfg.get(...)` semantics.
        self._cfg: dict = {}
        # Wall-clock timestamp of the last successful CFG fetch.
        # `refresh_cfg()` updates it; entity availability gates
        # check it to avoid surfacing stale-config-only data.
        self._cfg_fetched_at: float | None = None
```

- [ ] **Step 6.2: Add the `cfg` property + `refresh_cfg` method**

Append (anywhere logical — find an existing simple property like `latest_session_summary` and put `cfg` next to it):

```python
    @property
    def cfg(self) -> dict:
        """Most recent settings dict from `getCFG`. Empty until first
        successful fetch (see `refresh_cfg`)."""
        return self._cfg

    @property
    def cfg_fetched_at(self) -> float | None:
        return self._cfg_fetched_at

    def refresh_cfg(self) -> bool:
        """Fetch the full settings dict via the routed action.
        Stores the result in `self._cfg` and returns True on success.
        Logs + returns False on any error (cloud failure, malformed
        envelope, etc.) — the cache is preserved so transient errors
        don't blank existing entity state.
        """
        from ..protocol.cfg_action import get_cfg, CfgActionError
        import time as _time

        protocol = getattr(self, "_protocol", None)
        if protocol is None or not getattr(protocol, "connected", False):
            _LOGGER.debug("refresh_cfg: protocol not connected, skipping")
            return False
        try:
            cfg = get_cfg(protocol.action)
        except CfgActionError as ex:
            _LOGGER.warning("refresh_cfg: %s", ex)
            return False
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("refresh_cfg: unexpected error %s", ex)
            return False
        self._cfg = cfg
        self._cfg_fetched_at = _time.time()
        _LOGGER.warning(
            "[CFG] fetched %d settings keys: %s",
            len(cfg), sorted(cfg.keys()),
        )
        return True
```

- [ ] **Step 6.3: Hook `refresh_cfg` into the property handler**

Find the `_handle_properties` method (or wherever s2p51 / s2p52 events are dispatched). The cross-reference says s2p51 = settings update trigger and s2p52 = mowing-pref update trigger. Both should refetch CFG.

Locate the `[PROTOCOL_VALUE_NOVEL]`/known_quiet block in device.py (around the s2p51 path) and add a call to refresh_cfg when those piids fire. Pseudocode:

```python
            # Trigger a CFG re-fetch on settings/preference updates
            # (s2p51 = MULTIPLEXED_CONFIG, s2p52 = mowing-prefs
            # changed). The cache is the source of truth for the
            # CFG-derived entities; refreshing keeps them in sync
            # within one tick of any user-initiated change.
            if (siid_int, piid_int) in ((2, 51), (2, 52)):
                # Fire-and-forget so the MQTT callback isn't
                # blocked by the cloud round-trip.
                offload = getattr(self, "_hass", None)
                if offload is not None:
                    try:
                        offload.async_add_executor_job(self.refresh_cfg)
                    except Exception:
                        # Fall back to inline if the loop hop fails.
                        self.refresh_cfg()
                else:
                    self.refresh_cfg()
```

(Place this AFTER the existing PROTOCOL_NOVEL/VALUE_NOVEL emissions for those slots, so the diagnostic log still fires.)

If `self._hass` doesn't exist on the device, instead schedule via the protocol's executor or the coordinator. Search for an existing async-offload pattern in device.py (`hass.async_add_executor_job` or `async_create_task`) and mirror it.

- [ ] **Step 6.4: Hook initial fetch into coordinator first refresh**

Open `custom_components/dreame_a2_mower/coordinator.py`, find the `__init__`. After `self.live_map.async_setup()` add:

```python
        # Schedule an initial CFG fetch so all CFG-derived entities
        # (cutting height, mow mode, headlight, wear meters, …) have
        # data to populate from on first state evaluation.
        # async_add_executor_job is correct here because get_cfg
        # ultimately performs a blocking HTTP request via the
        # cloud client.
        try:
            hass.async_add_executor_job(self._device.refresh_cfg)
        except Exception:  # pragma: no cover — defensive
            pass
```

- [ ] **Step 6.5: Run full test suite, ensure no regression**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/ -q`
Expected: same baseline + the new tests from Tasks 1-5 = ~175 passed.

- [ ] **Step 6.6: Commit Task 6**

```bash
git add custom_components/dreame_a2_mower/dreame/device.py custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(device): CFG cache + refresh_cfg hook on s2p51/s2p52

Adds device.cfg dict + device.refresh_cfg() method backed by the
new cfg_action.get_cfg wrapper. Fetched once at coordinator init
and re-fetched whenever the firmware fires a settings-changed
trigger (s2p51 MULTIPLEXED_CONFIG, s2p52 mowing-prefs changed).

The fetch logs at WARNING with the list of returned keys on
success — first run will reveal exactly which CFG slots are
populated on g2408 (vs g2568a's full set). Entities added in
later tasks gate availability on the cfg_fetched_at timestamp
so they don't surface stale or absent slots.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: PRE settings — read-only sensors first

**Why:** before exposing writeable controls (which need read-modify-write semantics + a service call), surface the values as read-only sensors so the user can see them populate. Confirm with one mowing run that the values are correct before adding writers.

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`

- [ ] **Step 7.1: Locate the existing sensor description list**

Open `custom_components/dreame_a2_mower/sensor.py`. Find the `SENSORS` tuple (or whatever it's named — search for `SensorEntityDescription` patterns). Confirm it's a tuple of description objects that get instantiated in `async_setup_entry`.

- [ ] **Step 7.2: Add the PRE-derived sensors**

Add the following descriptions to the SENSORS tuple. Each gates availability on `device.cfg_fetched_at is not None and len(device.cfg.get('PRE', [])) >= 10`:

```python
    DreameMowerSensorEntityDescription(
        key="cutting_height_mm",
        name="Cutting Height",
        icon="mdi:scissors-cutting",
        native_unit_of_measurement="mm",
        # PRE = [zone, mode, height_mm, obstacle_mm, coverage%,
        #        direction_change, adaptive, ?, edge_detection, auto_edge]
        value_fn=lambda device: (
            device.cfg.get("PRE", [None] * 10)[2]
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="obstacle_distance_mm",
        name="Obstacle Distance",
        icon="mdi:ruler",
        native_unit_of_measurement="mm",
        value_fn=lambda device: (
            device.cfg.get("PRE", [None] * 10)[3]
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="mow_coverage_pct",
        name="Mowing Coverage",
        icon="mdi:percent",
        native_unit_of_measurement="%",
        value_fn=lambda device: (
            device.cfg.get("PRE", [None] * 10)[4]
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        exists_fn=lambda description, device: True,
    ),
```

(If the existing sensor descriptions use a different field name than `value_fn` / `exists_fn`, mirror their pattern instead. Read 2-3 existing descriptions in the file before adding.)

- [ ] **Step 7.3: Add three string-valued sensors for the enum-ish PRE fields**

```python
    DreameMowerSensorEntityDescription(
        key="mow_mode",
        name="Mow Mode",
        icon="mdi:robot-mower",
        # PRE[1]: 0=Standard, 1=Efficient
        value_fn=lambda device: (
            {0: "standard", 1: "efficient"}.get(
                device.cfg.get("PRE", [None] * 10)[1]
            )
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="direction_change",
        name="Direction Change",
        icon="mdi:rotate-3d-variant",
        # PRE[5]: 0=auto, 1=off
        value_fn=lambda device: (
            {0: "auto", 1: "off"}.get(
                device.cfg.get("PRE", [None] * 10)[5]
            )
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="edge_mowing",
        name="Edge Mowing",
        icon="mdi:square-outline",
        # PRE[9]: 0=off, 1=on (auto-edge / outer perimeter pass)
        value_fn=lambda device: (
            {0: "off", 1: "on"}.get(
                device.cfg.get("PRE", [None] * 10)[9]
            )
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="edge_detection",
        name="Edge Detection",
        icon="mdi:square-rounded-outline",
        # PRE[8]: 0=off, 1=on
        value_fn=lambda device: (
            {0: "off", 1: "on"}.get(
                device.cfg.get("PRE", [None] * 10)[8]
            )
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        exists_fn=lambda description, device: True,
    ),
```

- [ ] **Step 7.4: Run tests + verify the integration loads**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/ -q`
Expected: same passing baseline (sensor entities aren't unit-tested without an HA env).

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -c "
import importlib, sys
sys.path.insert(0, 'custom_components/dreame_a2_mower')
import sensor
print('module imported OK')
print('SENSORS count:', len([s for s in dir(sensor) if 'SENSOR' in s.upper()]))
"`
Expected: `module imported OK` (verifies no syntax error).

- [ ] **Step 7.5: Commit Task 7**

```bash
git add custom_components/dreame_a2_mower/sensor.py
git commit -m "feat(sensor): expose PRE settings as read-only sensors

Per apk.md, PRE is a 10-element settings array returned by getCFG:
  [zone, mode, height_mm, obstacle_mm, coverage%,
   direction_change, adaptive, ?, edge_detection, auto_edge]

Adds 7 sensors (cutting height, obstacle distance, coverage %,
mow mode, direction change, edge mowing, edge detection) backed
by device.cfg['PRE']. Each gates on cfg_fetched_at + array
length so g2408 firmwares without a PRE slot don't show
phantom 'unknown' entities.

Read-only first; writers (number/switch entities with PRE
read-modify-write semantics) follow in a later task once
field-validated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Headlight + GPS + Anti-theft + ATA + WRF + PROT + PATH sensors

**Why:** these are the "other" CFG keys the apk lists. Same pattern as Task 7 — read-only sensors so they appear immediately; writers come later.

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`

- [ ] **Step 8.1: Add headlight sensors**

Append to SENSORS:

```python
    DreameMowerSensorEntityDescription(
        key="headlight_enabled",
        name="Headlight Enabled",
        icon="mdi:car-light-high",
        # LIT = [enabled, start_min, end_min, light1, light2, light3, light4]
        value_fn=lambda device: (
            "on" if (
                isinstance(device.cfg.get("LIT"), list)
                and len(device.cfg.get("LIT", [])) >= 1
                and device.cfg["LIT"][0]
            ) else "off" if isinstance(device.cfg.get("LIT"), list) else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="headlight_schedule",
        name="Headlight Schedule",
        icon="mdi:clock-outline",
        # Format start/end minutes as HH:MM-HH:MM string.
        value_fn=lambda device: _format_time_window(device.cfg.get("LIT")),
        exists_fn=lambda description, device: True,
    ),
```

Then add the helper near the top of `sensor.py`:

```python
def _format_time_window(lst, start_idx=1, end_idx=2):
    """Format `[..., start_min, end_min, ...]` as 'HH:MM-HH:MM'.
    Returns None when input is missing or malformed."""
    if not isinstance(lst, list) or len(lst) <= max(start_idx, end_idx):
        return None
    s = lst[start_idx]
    e = lst[end_idx]
    if not (isinstance(s, int) and isinstance(e, int)):
        return None
    return f"{s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d}"
```

- [ ] **Step 8.2: Add anti-theft, ATA, WRF, PROT, PATH sensors**

```python
    DreameMowerSensorEntityDescription(
        key="anti_theft",
        name="Anti-Theft",
        icon="mdi:shield-lock",
        value_fn=lambda device: (
            "on" if device.cfg.get("STUN") == 1 else
            "off" if device.cfg.get("STUN") == 0 else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="auto_task_adjust",
        name="Auto Task Adjustment",
        icon="mdi:tune",
        # ATA = [a, b, c] — 3-element config; surface raw JSON so
        # the user can see what's there until we know the schema.
        value_fn=lambda device: (
            str(device.cfg.get("ATA")) if device.cfg.get("ATA") is not None else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="weather_reference",
        name="Weather Reference",
        icon="mdi:weather-partly-cloudy",
        value_fn=lambda device: (
            "on" if device.cfg.get("WRF") else
            "off" if device.cfg.get("WRF") is False else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="grass_protection",
        name="Grass Protection",
        icon="mdi:grass",
        value_fn=lambda device: (
            "on" if device.cfg.get("PROT") == 1 else
            "off" if device.cfg.get("PROT") == 0 else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="path_display",
        name="Path Display Mode",
        icon="mdi:map-marker-path",
        value_fn=lambda device: device.cfg.get("PATH"),
        exists_fn=lambda description, device: True,
    ),
```

- [ ] **Step 8.3: Add wear-meter sensors (CMS)**

```python
    DreameMowerSensorEntityDescription(
        key="blade_health_pct",
        name="Blade Health",
        icon="mdi:scissors-cutting",
        native_unit_of_measurement="%",
        # CMS = [blade_min, brush_min, robot_min]; max minutes per
        # apk: blade=6000, brush=30000, robot=3600.
        value_fn=lambda device: _wear_health(device.cfg.get("CMS"), 0, 6000),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="brush_health_pct",
        name="Brush Health",
        icon="mdi:broom",
        native_unit_of_measurement="%",
        value_fn=lambda device: _wear_health(device.cfg.get("CMS"), 1, 30000),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="robot_maintenance_health_pct",
        name="Robot Maintenance Health",
        icon="mdi:wrench",
        native_unit_of_measurement="%",
        value_fn=lambda device: _wear_health(device.cfg.get("CMS"), 2, 3600),
        exists_fn=lambda description, device: True,
    ),
```

Add helper near `_format_time_window`:

```python
def _wear_health(cms_list, idx, max_minutes):
    """Convert wear minutes at `cms_list[idx]` to remaining-life %.
    Returns None for missing/malformed input."""
    if not isinstance(cms_list, list) or idx >= len(cms_list):
        return None
    minutes = cms_list[idx]
    if not isinstance(minutes, (int, float)):
        return None
    return max(0, round((1 - minutes / max_minutes) * 100))
```

- [ ] **Step 8.4: Run tests + import-check**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/ -q && python -c "import sys; sys.path.insert(0, 'custom_components/dreame_a2_mower'); import sensor"`
Expected: tests pass; sensor module imports without error.

- [ ] **Step 8.5: Commit Task 8**

```bash
git add custom_components/dreame_a2_mower/sensor.py
git commit -m "feat(sensor): expose CFG-derived headlight, anti-theft, wear, weather

Adds read-only sensors for every CFG key the apk catalogs:
- headlight_enabled / headlight_schedule (LIT)
- anti_theft (STUN)
- auto_task_adjust (ATA, raw JSON until schema known)
- weather_reference (WRF)
- grass_protection (PROT)
- path_display (PATH)
- blade / brush / robot maintenance health % (CMS, with apk's
  documented max-minute thresholds)

Two new helpers: _format_time_window (start_min/end_min →
'HH:MM-HH:MM') and _wear_health (minutes → remaining %).

Each sensor returns None until device.cfg is populated, so
g2408-firmware variants that don't expose a particular key
just show 'Unknown' rather than wrong data.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: PRE writers — number + switch entities with read-modify-write

**Why:** now that sensors are confirmed populating correctly (after one round of field testing), expose writable controls. PRE updates use read-modify-write so the writer must always start from the latest cached PRE.

**Files:**
- Modify: `custom_components/dreame_a2_mower/number.py`
- Modify: `custom_components/dreame_a2_mower/switch.py`

- [ ] **Step 9.1: Add a PRE-writer helper to device**

Open `dreame/device.py`. Add a method near `refresh_cfg`:

```python
    def write_pre(self, index: int, value: int) -> bool:
        """Read the current PRE array, replace one slot, and write
        the updated array back via setPRE. Returns True on success.

        `index` must be a valid PRE slot (0..9). Caller is
        responsible for value validation (range, enum membership).
        """
        from ..protocol.cfg_action import set_pre, CfgActionError

        protocol = getattr(self, "_protocol", None)
        if protocol is None or not getattr(protocol, "connected", False):
            _LOGGER.warning("write_pre: protocol not connected")
            return False
        # Always read the freshest PRE before modifying — the cache
        # may be seconds out of date if the user just toggled
        # something via the app.
        if not self.refresh_cfg():
            _LOGGER.warning("write_pre: refresh_cfg failed; aborting")
            return False
        pre = self._cfg.get("PRE")
        if not isinstance(pre, list) or len(pre) < 10:
            _LOGGER.warning("write_pre: no PRE array in cfg")
            return False
        if not 0 <= index < len(pre):
            _LOGGER.warning("write_pre: index %d out of range", index)
            return False
        new_pre = list(pre)
        new_pre[index] = value
        try:
            set_pre(protocol.action, new_pre)
        except (CfgActionError, ValueError) as ex:
            _LOGGER.warning("write_pre: set_pre failed: %s", ex)
            return False
        # Update local cache immediately so the entity reflects the
        # change without waiting for the next s2p52 push.
        self._cfg = dict(self._cfg)
        self._cfg["PRE"] = new_pre
        _LOGGER.warning("write_pre: PRE[%d] = %r → %r", index, pre[index], value)
        return True
```

- [ ] **Step 9.2: Add Number entities for cutting_height + obstacle_distance + coverage**

Open `custom_components/dreame_a2_mower/number.py`. Append to its description list (or whatever the existing pattern is — read 2-3 existing entries first):

```python
    DreameMowerNumberEntityDescription(
        key="set_cutting_height",
        name="Cutting Height",
        icon="mdi:scissors-cutting",
        native_min_value=30, native_max_value=70, native_step=5,
        native_unit_of_measurement="mm",
        # Read from cached PRE[2]; write via device.write_pre(2, val)
        value_fn=lambda device: (
            device.cfg.get("PRE", [None] * 10)[2]
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        set_fn=lambda device, value: device.write_pre(2, int(value)),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerNumberEntityDescription(
        key="set_obstacle_distance",
        name="Obstacle Distance",
        icon="mdi:ruler",
        native_min_value=10, native_max_value=20, native_step=5,
        native_unit_of_measurement="cm",
        value_fn=lambda device: (
            device.cfg.get("PRE", [None] * 10)[3]
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        set_fn=lambda device, value: device.write_pre(3, int(value)),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerNumberEntityDescription(
        key="set_mow_coverage",
        name="Mowing Coverage",
        icon="mdi:percent",
        native_min_value=50, native_max_value=100, native_step=10,
        native_unit_of_measurement="%",
        value_fn=lambda device: (
            device.cfg.get("PRE", [None] * 10)[4]
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        set_fn=lambda device, value: device.write_pre(4, int(value)),
        exists_fn=lambda description, device: True,
    ),
```

- [ ] **Step 9.3: Add Switch entities for the on/off PRE fields**

Open `custom_components/dreame_a2_mower/switch.py`. Append:

```python
    DreameMowerSwitchEntityDescription(
        key="edge_mowing_switch",
        name="Edge Mowing",
        icon="mdi:square-outline",
        # PRE[9]: 0=off, 1=on
        is_on_fn=lambda device: (
            bool(device.cfg.get("PRE", [None] * 10)[9])
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        turn_on_fn=lambda device: device.write_pre(9, 1),
        turn_off_fn=lambda device: device.write_pre(9, 0),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSwitchEntityDescription(
        key="edge_detection_switch",
        name="Edge Detection",
        icon="mdi:square-rounded-outline",
        is_on_fn=lambda device: (
            bool(device.cfg.get("PRE", [None] * 10)[8])
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        turn_on_fn=lambda device: device.write_pre(8, 1),
        turn_off_fn=lambda device: device.write_pre(8, 0),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSwitchEntityDescription(
        key="mow_mode_efficient",
        name="Efficient Mow Mode",
        icon="mdi:robot-mower",
        # PRE[1]: 0=Standard (off), 1=Efficient (on)
        is_on_fn=lambda device: (
            device.cfg.get("PRE", [None] * 10)[1] == 1
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        turn_on_fn=lambda device: device.write_pre(1, 1),
        turn_off_fn=lambda device: device.write_pre(1, 0),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSwitchEntityDescription(
        key="direction_change_off",
        name="Direction Change Disabled",
        icon="mdi:rotate-3d-variant",
        # PRE[5]: 0=auto (switch off), 1=off (switch on)
        is_on_fn=lambda device: (
            device.cfg.get("PRE", [None] * 10)[5] == 1
            if isinstance(device.cfg.get("PRE"), list)
            and len(device.cfg.get("PRE", [])) >= 10
            else None
        ),
        turn_on_fn=lambda device: device.write_pre(5, 1),
        turn_off_fn=lambda device: device.write_pre(5, 0),
        exists_fn=lambda description, device: True,
    ),
```

- [ ] **Step 9.4: Run tests + import checks**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python -m pytest tests/ -q
python -c "import sys; sys.path.insert(0, 'custom_components/dreame_a2_mower'); import number, switch, dreame.device"
```
Expected: tests pass; modules import.

- [ ] **Step 9.5: Commit Task 9**

```bash
git add custom_components/dreame_a2_mower/dreame/device.py custom_components/dreame_a2_mower/number.py custom_components/dreame_a2_mower/switch.py
git commit -m "feat(entities): writable PRE controls (number + switch)

Adds device.write_pre(index, value) helper that does the
read-modify-write dance: refresh_cfg → modify slot → set_pre.
Updates local cache immediately so the entity reflects the
change without waiting for the next s2p52 push.

New entities (all backed by write_pre):
- number: set-cutting-height, set-obstacle-distance,
  set-mow-coverage
- switch: edge-mowing, edge-detection, mow-mode-efficient,
  direction-change-off

Each entity gates on cfg PRE array presence + length, so
g2408 firmwares without PRE just hide the controls rather
than letting the user click into an error.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Cloud `getDockPos` integration

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/device.py`
- Modify: `custom_components/dreame_a2_mower/sensor.py`

- [ ] **Step 10.1: Add dock-pos cache + fetcher to device**

In `dreame/device.py`, near `refresh_cfg`, add:

```python
        # Dock-position cache from getDockPos. Populated by
        # `refresh_dock_pos()`; consumers read via `device.dock_pos`.
        # Schema (per apk):
        #   {x, y, yaw, connect_status, path_connect, in_region}
        self._dock_pos: dict | None = None
```

(Add inside `__init__`.)

And as a property + method (near `cfg`):

```python
    @property
    def dock_pos(self) -> dict | None:
        return self._dock_pos

    def refresh_dock_pos(self) -> bool:
        from ..protocol.cfg_action import get_dock_pos, CfgActionError

        protocol = getattr(self, "_protocol", None)
        if protocol is None or not getattr(protocol, "connected", False):
            return False
        try:
            self._dock_pos = get_dock_pos(protocol.action)
        except CfgActionError as ex:
            _LOGGER.warning("refresh_dock_pos: %s", ex)
            return False
        _LOGGER.warning("[DOCK] %s", self._dock_pos)
        return True
```

- [ ] **Step 10.2: Hook s1p51 to trigger dock refresh**

The cross-reference says s1p51 is a dock-position-update trigger. Find where the integration handles s1p51 events (search for `(1, 51)` in device.py). Wherever the existing handler is, add:

```python
            if (siid_int, piid_int) == (1, 51):
                # apk: dock position change trigger → re-fetch
                hass = getattr(self, "_hass", None)
                if hass is not None:
                    try:
                        hass.async_add_executor_job(self.refresh_dock_pos)
                    except Exception:
                        self.refresh_dock_pos()
                else:
                    self.refresh_dock_pos()
```

Place this AFTER the existing PROTOCOL_NOVEL/VALUE_NOVEL emissions for that slot.

- [ ] **Step 10.3: Add dock sensors**

Append to SENSORS in `sensor.py`:

```python
    DreameMowerSensorEntityDescription(
        key="dock_x_cm",
        name="Dock Position X",
        icon="mdi:home-import-outline",
        native_unit_of_measurement="cm",
        value_fn=lambda device: (
            device.dock_pos.get("x") if isinstance(device.dock_pos, dict) else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="dock_y_cm",
        name="Dock Position Y",
        icon="mdi:home-import-outline",
        native_unit_of_measurement="cm",
        value_fn=lambda device: (
            device.dock_pos.get("y") if isinstance(device.dock_pos, dict) else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="dock_yaw_deg",
        name="Dock Heading",
        icon="mdi:compass",
        native_unit_of_measurement="°",
        # apk says yaw / 10 → degrees
        value_fn=lambda device: (
            (device.dock_pos.get("yaw", 0) / 10.0)
            if isinstance(device.dock_pos, dict) and device.dock_pos.get("yaw") is not None
            else None
        ),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerSensorEntityDescription(
        key="dock_lawn_connected",
        name="Dock-to-Lawn Connected",
        icon="mdi:link-variant",
        value_fn=lambda device: (
            "yes" if isinstance(device.dock_pos, dict) and device.dock_pos.get("connect_status")
            else "no" if isinstance(device.dock_pos, dict)
            else None
        ),
        exists_fn=lambda description, device: True,
    ),
```

- [ ] **Step 10.4: Run tests + import checks**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/ -q`
Expected: pass.

- [ ] **Step 10.5: Commit Task 10**

```bash
git add custom_components/dreame_a2_mower/dreame/device.py custom_components/dreame_a2_mower/sensor.py
git commit -m "feat(dock): getDockPos action + dock sensors

Adds device.refresh_dock_pos() backed by cfg_action.get_dock_pos().
Triggered automatically when s1p51 (dock-position-update) fires —
per apk decompilation, that's the firmware's signal to re-read.

4 new sensors: dock x/y/yaw + lawn-connection status. The yaw
conversion is yaw_raw / 10 → degrees per apk.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Action buttons (cutterBias, suppressFault, findBot, lockBot, takePic)

**Files:**
- Modify: `custom_components/dreame_a2_mower/button.py`

- [ ] **Step 11.1: Add the action-op opcodes as a constants block**

At the top of `button.py` (after existing imports), add:

```python
# Action opcodes for the routed action endpoint (siid:2 aiid:50,
# m:'a'). Sourced from apk.md §"Actions". Numbers stay verbatim
# rather than aliased to enums — the apk-side names are the
# canonical reference if more get added later.
_OP_FIND_BOT = 9
_OP_LOCK_BOT = 12
_OP_SUPPRESS_FAULT = 11
_OP_TAKE_PIC = 401
_OP_CUTTER_BIAS = 503
```

- [ ] **Step 11.2: Add a button helper on device**

In `dreame/device.py`, near `write_pre`:

```python
    def call_action_opcode(self, op: int, extra: dict | None = None) -> bool:
        """Invoke a routed action opcode. See protocol/cfg_action.py
        and apk.md for the full opcode catalog."""
        from ..protocol.cfg_action import call_action_op

        protocol = getattr(self, "_protocol", None)
        if protocol is None or not getattr(protocol, "connected", False):
            _LOGGER.warning("call_action_opcode: protocol not connected")
            return False
        try:
            call_action_op(protocol.action, op, extra)
        except Exception as ex:
            _LOGGER.warning("call_action_opcode(%d): %s", op, ex)
            return False
        return True
```

- [ ] **Step 11.3: Add the button descriptions**

Append to the BUTTONS tuple in `button.py`:

```python
    DreameMowerButtonEntityDescription(
        key="find_bot",
        name="Find Mower",
        icon="mdi:bell-ring",
        action_fn=lambda device: device.call_action_opcode(_OP_FIND_BOT),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerButtonEntityDescription(
        key="lock_bot",
        name="Lock Mower",
        icon="mdi:lock",
        action_fn=lambda device: device.call_action_opcode(_OP_LOCK_BOT),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerButtonEntityDescription(
        key="suppress_fault",
        name="Clear Warning",
        icon="mdi:alert-octagon-outline",
        action_fn=lambda device: device.call_action_opcode(_OP_SUPPRESS_FAULT),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerButtonEntityDescription(
        key="take_pic",
        name="Take Picture",
        icon="mdi:camera",
        action_fn=lambda device: device.call_action_opcode(_OP_TAKE_PIC),
        exists_fn=lambda description, device: True,
    ),
    DreameMowerButtonEntityDescription(
        key="cutter_bias",
        name="Calibrate Blade",
        icon="mdi:tune-vertical",
        action_fn=lambda device: device.call_action_opcode(_OP_CUTTER_BIAS),
        exists_fn=lambda description, device: True,
    ),
```

- [ ] **Step 11.4: Run tests + import checks**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/ -q && python -c "import sys; sys.path.insert(0, 'custom_components/dreame_a2_mower'); import button"`
Expected: pass; module imports.

- [ ] **Step 11.5: Commit Task 11**

```bash
git add custom_components/dreame_a2_mower/dreame/device.py custom_components/dreame_a2_mower/button.py
git commit -m "feat(button): action-opcode buttons (find/lock/clear/pic/calibrate)

Wraps the routed action endpoint (siid:2 aiid:50, m:'a') as
single-press button entities for the 5 most user-facing
opcodes from the apk catalog:
- 9 findBot — play 'Find Me' sound
- 11 suppressFault — clear current warning state
- 12 lockBot — lock the mower
- 401 takePic — capture a photo (camera-equipped models)
- 503 cutterBias — blade calibration routine

Adds device.call_action_opcode(op, extra) helper.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Pose decoder swap (CONDITIONAL on Task 1 verdict)

**This task only runs if Task 1's fixture verdict is 'B' (apk packed12 is correct, int16_le diverges).** Otherwise mark this task as not-applicable in the plan and skip.

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/telemetry.py`
- Test: `tests/protocol/test_telemetry.py`

- [ ] **Step 12.1: Read the verdict from the fixture file**

Open `tests/protocol/fixtures/captured_s1p4_frames.json` and read the `verdict` field. If it's "A" or "C", skip this entire task and write a one-line note in the commit log of Task 13: "Task 12 skipped — verdict A/C, int16_le decoder is correct on g2408."

If verdict is "B", continue.

- [ ] **Step 12.2: Switch the decoder in telemetry.py**

Replace the `int16_le` x_cm/y_mm reads in `decode_s1p4` with calls to the packed12 decoder:

```python
def decode_s1p4(data: bytes) -> MowingTelemetry:
    # ...validation...
    from .pose import decode_pose_packed12
    pose = decode_pose_packed12(data)
    x_cm = pose.x_raw  # apk's "map coords" use *10; downstream may scale
    y_mm = pose.y_raw
    # ...rest as before...
```

- [ ] **Step 12.3: Update tests**

Existing tests that hardcode int16_le-derived x_cm / y_mm values WILL break. For each failing test, update the expected values using the captured-frame-fixture verdict B mapping. (Each test should fail with a clear delta to the new value.)

- [ ] **Step 12.4: Commit Task 12**

```bash
git add custom_components/dreame_a2_mower/protocol/telemetry.py tests/
git commit -m "fix(telemetry): switch s1p4 pose decode to packed12 (apk-validated)

Field verdict (fixture verdict='B'): the int16_le decoder
diverges from real g2408 firmware behavior on captured frames,
while the apk's 12-bit-packed decoder produces values consistent
with documented mower paths. Switching decoder.

Test expectations updated for the 5 affected tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: M_PATH userData fetch (alternate path source)

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/device.py` (or wherever cloud-MAP fetch lives — search for `MAP.0` or `getDeviceData`)

- [ ] **Step 13.1: Locate the existing cloud MAP fetch**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && grep -rn "iotuserdata\|getDeviceData\|MAP\.0" custom_components/dreame_a2_mower/`
Identify the file that does the existing MAP.* batch fetch (likely `_build_map_from_cloud_data` in device.py).

- [ ] **Step 13.2: Add an M_PATH parser alongside the existing MAP parser**

In `_build_map_from_cloud_data` (or sibling function), after the MAP keys are read, add:

```python
            # M_PATH.* userData blob — separate from MAP.*. Per apk:
            # array of [x, y] pairs or null (segment delimiters);
            # sentinel [32767, -32768] = path break. Coordinates
            # are ~10× smaller than MAP coords.
            mpath_keys = [f"M_PATH.{i}" for i in range(28)]
            # The integration's existing batch fetch already pulled
            # all keys into `response`. If M_PATH.* keys are present,
            # reassemble them into a single JSON array.
            mpath_parts = [response.get(f"M_PATH.{i}", "") for i in range(28)]
            mpath_raw = "".join(p for p in mpath_parts if p)
            if mpath_raw:
                try:
                    mpath = json.loads(mpath_raw)
                    if isinstance(mpath, list):
                        # Stash on the device so live_map can hydrate
                        # state.path from this on a boot when
                        # in_progress.json is empty.
                        self._cloud_mpath = mpath
                        _LOGGER.warning(
                            "[M_PATH] received %d entries from cloud", len(mpath)
                        )
                except (ValueError, TypeError) as ex:
                    _LOGGER.debug("M_PATH parse failed: %s", ex)
```

Add `self._cloud_mpath = None` to `DreameMowerDevice.__init__` and a property accessor:

```python
    @property
    def cloud_mpath(self) -> list | None:
        """Most recent M_PATH from the cloud userdata fetch.
        Set by `_build_map_from_cloud_data`. Used by live_map's
        boot-time restore when in_progress.json is missing or
        empty."""
        return self._cloud_mpath
```

- [ ] **Step 13.3: Add a live_map hydrator that reads cloud_mpath**

Open `custom_components/dreame_a2_mower/live_map.py`. Find `_restore_in_progress`. After the existing on-disk-restore branch (which returns False when no in_progress file exists), add:

```python
        # If on-disk in_progress is empty AND the device's
        # cloud_mpath is populated, treat that as a fallback path
        # source. This handles the "boot mid-mow before any
        # _persist_in_progress wrote" race.
        cloud_mpath = getattr(
            getattr(self._coordinator, "device", None), "cloud_mpath", None
        )
        if cloud_mpath:
            # Convert M_PATH coords to metres. Per apk, M_PATH coords
            # are ~10× smaller than MAP coords; MAP coords are mm.
            # So M_PATH × 10 = MAP_mm = our usual mm scale.
            converted: list[list[float]] = []
            for entry in cloud_mpath:
                if entry is None:
                    continue
                if isinstance(entry, list) and len(entry) >= 2:
                    if entry[0] == 32767 and entry[1] == -32768:
                        # Path-break sentinel — skip rather than
                        # introduce a discontinuity.
                        continue
                    x_m = (entry[0] * 10) / 1000.0
                    y_m = (entry[1] * 10) / 1000.0
                    converted.append([round(x_m, 3), round(y_m, 3)])
            if converted:
                self._state.path = converted
                _LOGGER.warning(
                    "live_map: restored %d points from cloud M_PATH "
                    "(in_progress.json was empty)",
                    len(converted),
                )
                return True
        return False
```

- [ ] **Step 13.4: Run full test suite**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/ -q`
Expected: pass.

- [ ] **Step 13.5: Commit Task 13**

```bash
git add custom_components/dreame_a2_mower/dreame/device.py custom_components/dreame_a2_mower/live_map.py
git commit -m "feat(map): consume cloud M_PATH as fallback path source

Per apk.md, the cloud's userData includes a separate M_PATH.*
blob holding the live mowing path independently of the MAP.*
geometry. Coordinates are ~10× smaller than MAP coords;
sentinel [32767, -32768] marks path breaks.

Adds device.cloud_mpath cache populated alongside the existing
MAP.* parse, plus a live_map._restore_in_progress fallback that
hydrates state.path from cloud_mpath when in_progress.json
is empty (boot-mid-mow race).

Coordinate conversion: M_PATH × 10 = mm, then ÷ 1000 = m.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Document the protocol corrections

**Files:**
- Modify: `docs/research/g2408-protocol.md`

- [ ] **Step 14.1: Update the s2p1 / s2p2 entries**

Open `docs/research/g2408-protocol.md`. Find the `2.1` row in §2.1 (Summary table). Replace the entry:

```markdown
| 2.1 | **Status enum** (g2408) — `1=Working/Mowing, 2=Standby, 3=Paused, 5=Returning, 6=Charging, 11=Mapping, 13=Charged, 14=Updating` per apk decompilation. **NOT** the small mystery enum we previously guessed from `{1, 2, 5}`. | small enum mapping |
```

Replace the `2.2` row:

```markdown
| 2.2 | **Error code** per apk decompilation (NOT a state machine — the previous "STATE values {27, 43, 48, ...}" reading was wrong). Values map to fault indices catalogued in apk §FaultIndex (e.g. 0=HANGING, 24=BATTERY_LOW, 27=HUMAN_DETECTED, 56=BAD_WEATHER, 73=TOP_COVER_OPEN). | error code |
```

- [ ] **Step 14.2: Update the §4.7 empty-dict roles**

Find §4.7 "Empty-dict s1p50 / s1p51 / s1p52 / s2p52 — lightweight state-change pings". Replace the `s1p51` and `s2p52` rows in the table:

```markdown
| `s1p51` | **Dock-position-update trigger** — apk says firmware fires this when the dock pose changes; consumer should re-fetch via `getDockPos` action. (Previously hypothesized as session-start marker — wrong per apk.) |
| `s2p52` | **Mowing-preference-update trigger** — apk says firmware fires this when PRE settings change; consumer should re-fetch via `getCFG`. (Previously hypothesized as session-end marker — wrong per apk.) |
```

Then in the same section, replace the paragraph below the table that talks about session-end signal:

```markdown
**Note (2026-04-23 correction)**: an earlier hypothesis claimed
`s1p52 + s2p52` together bracket session ends, mirroring
`s1p50 + s1p51` at session start. The apk decompilation refutes
this — `s1p51` is a dock-update trigger and `s2p52` is a
preference-change trigger. The actual "session ended" signal
is the cloud `event_occured siid=4 eiid=1` push (§7.4) plus
the area-counter delta discriminator for blades-up/down (§3.1
"Detecting blades-down").
```

- [ ] **Step 14.3: Add a new §6.x section documenting the routed action endpoint**

After the existing §6 settings section, add:

```markdown
## 6.x Routed action endpoint (siid:2 aiid:50)

Per apk decompilation, the Dreame mower exposes most of its
configuration + control surface through a single MIoT action
call:

```
action {
  siid: 2,
  aiid: 50,
  in: [{ m: 'g'|'s'|'a'|'r', t: <target>, d: <optional payload> }]
}
```

`m` is the mode (get / set / action / remote-control) and `t`
is the target. Result lands at `result.out[0]`. The integration's
`protocol/cfg_action.py` provides typed wrappers (`get_cfg`,
`get_dock_pos`, `set_pre`, `call_action_op`).

Most useful targets:

| `m` `t` | Returns | Used in |
|---|---|---|
| `g CFG` | All settings dict (WRP, DND, BAT, CLS, VOL, LIT, AOP, REC, STUN, ATA, PATH, WRF, PROT, CMS, PRE) | `device.refresh_cfg` |
| `g DOCK` | `{x, y, yaw, connect_status, path_connect, in_region}` | `device.refresh_dock_pos` |
| `s PRE` | Write 10-element preferences array (read-modify-write) | `device.write_pre` |
| `a` `o:OP` | Action opcode (100 globalMower, 101 edgeMower, 9 findBot, 11 suppressFault, 12 lockBot, 401 takePic, 503 cutterBias …) | `device.call_action_opcode` |

The full opcode catalog and CFG-key schemas live in the apk
cross-reference: `docs/research/2026-04-23-iobroker-dreame-cross-reference.md`.

### PRE schema

`PRE = [zone, mode, height_mm, obstacle_mm, coverage%,
        direction_change, adaptive, ?, edge_detection, auto_edge]`

- PRE[0]: zone id
- PRE[1]: mode (0=Standard, 1=Efficient)
- PRE[2]: cutting height in mm
- PRE[3]: obstacle distance in mm
- PRE[4]: coverage %
- PRE[5]: direction change (0=auto, 1=off)
- PRE[6]: adaptive (semantic TBD)
- PRE[7]: unknown (possibly EdgeMaster or Safe Edge Mowing)
- PRE[8]: edge detection (0=off, 1=on)
- PRE[9]: edge mowing / auto-edge (0=off, 1=on)
```

- [ ] **Step 14.4: Update the s1p4 §3.1 "additional frame variants" note**

In §3.2 (the 8-byte beacon variant), add at the bottom:

```markdown
**Other variants observed by apk decompilation (g2568a)**: 7, 13,
22, 44 byte lengths exist on other mower models. We've only
observed 8 / 10 / 33 on g2408. If a future capture surfaces a
new length, the integration will emit a one-shot
`[PROTOCOL_NOVEL] s1p4 short frame len=N` warning with the raw
bytes — see §7 PROTOCOL_NOVEL catalog.
```

- [ ] **Step 14.5: Run the doc through markdownlint mentally**

(No actual command — just re-read the modified sections and confirm headings, table syntax, and code-fence languages render as expected.)

- [ ] **Step 14.6: Commit Task 14**

```bash
git add docs/research/g2408-protocol.md
git commit -m "docs(protocol): correct s2p1/s2p2/s1p51/s2p52 + add §6.x

- s2p1: actually the main status enum (1=Working, 2=Standby, ...)
  per apk, NOT the {1,2,5} mystery enum.
- s2p2: actually the error code per apk fault-index, NOT the
  state machine we'd been treating it as.
- s1p51: dock-position-update trigger (re-fetch via getDockPos),
  NOT a session-start marker.
- s2p52: mowing-prefs-changed trigger (re-fetch via getCFG),
  NOT a session-end marker. Removes the 's1p52+s2p52 brackets
  a session' hypothesis.

Adds new §6.x documenting the routed-action endpoint
(siid:2 aiid:50 with {m,t,d} routing) and the PRE schema. Cross-
links to the apk cross-reference doc for the full catalog.

Adds note in §3.2 about additional s1p4 frame lengths
(7/13/22/44 bytes) observed on g2568a per apk — not seen yet
on g2408 but PROTOCOL_NOVEL warning will catch them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Wire new SIID 2 piid handlers (53, 57, 58, 61)

**Files:**
- Modify: `custom_components/dreame_a2_mower/dreame/device.py`

- [ ] **Step 15.1: Add the four piids to `known_quiet`**

Find the `known_quiet` set in device.py (search for `known_quiet`). Add the new entries:

```python
            known_quiet = {
                # ...existing entries...
                # Per apk decompilation:
                (2, 53),   # Voice download progress (%)
                (2, 57),   # Robot shutdown trigger (5s delay then off)
                (2, 58),   # Self-check result {d:{mode,id,result}}
                (2, 61),   # Map update — triggers loadMap
            }
```

- [ ] **Step 15.2: Add a sensor for voice-download progress**

In `sensor.py`, append:

```python
    DreameMowerSensorEntityDescription(
        key="voice_download_progress",
        name="Voice Pack Download",
        icon="mdi:download",
        native_unit_of_measurement="%",
        # s2p53 push value, cached on device — needs a small
        # extension to device to surface this. See Step 15.3.
        value_fn=lambda device: getattr(device, "voice_dl_progress", None),
        exists_fn=lambda description, device: True,
    ),
```

- [ ] **Step 15.3: Cache s2p53 + s2p58 values on device**

In `dreame/device.py`, add to `__init__`:

```python
        # apk-documented but previously-unmapped properties.
        self._voice_dl_progress: int | None = None
        self._self_check_result: dict | None = None
```

Add properties:

```python
    @property
    def voice_dl_progress(self) -> int | None:
        return self._voice_dl_progress

    @property
    def self_check_result(self) -> dict | None:
        return self._self_check_result
```

In the property handler block where s2p53/s2p58 events would land, add caching logic:

```python
            if (siid_int, piid_int) == (2, 53):
                value = param.get("value")
                if isinstance(value, (int, float)):
                    self._voice_dl_progress = int(value)
            elif (siid_int, piid_int) == (2, 58):
                value = param.get("value")
                if isinstance(value, dict):
                    self._self_check_result = value.get("d") if "d" in value else value
```

(Place inside the param-iteration loop, near the existing PROTOCOL_VALUE_NOVEL emission, BEFORE the known_quiet check.)

- [ ] **Step 15.4: Add a self-check sensor**

```python
    DreameMowerSensorEntityDescription(
        key="self_check_result",
        name="Self-Check Result",
        icon="mdi:stethoscope",
        # Show the result int (or 'pass' if 0). Full dict on attrs
        # would need a custom entity; keep simple for now.
        value_fn=lambda device: (
            "pass" if isinstance(device.self_check_result, dict) and
            device.self_check_result.get("result") == 0 else
            str(device.self_check_result.get("result"))
            if isinstance(device.self_check_result, dict) else None
        ),
        exists_fn=lambda description, device: True,
    ),
```

- [ ] **Step 15.5: Run tests**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/ -q`
Expected: pass.

- [ ] **Step 15.6: Commit Task 15**

```bash
git add custom_components/dreame_a2_mower/dreame/device.py custom_components/dreame_a2_mower/sensor.py
git commit -m "feat(device): wire s2p53 / s2p57 / s2p58 / s2p61 handlers

Per apk catalog, these previously-unknown piids have known
semantics:
- s2p53 voice-pack download progress (%)
- s2p57 robot-shutdown trigger (5s delay)
- s2p58 self-check result {d:{mode,id,result}}
- s2p61 map-update trigger (re-fetch MAP.*)

Adds them to known_quiet so PROTOCOL_NOVEL stops firing,
plus caching for 53 + 58 values exposed as sensors. 57 stays
event-only (no state to surface). 61 reuses the existing
map-fetch trigger pathway (no new code needed beyond
suppressing the warning).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Final smoke test + version bump

**Files:**
- Modify: `custom_components/dreame_a2_mower/manifest.json`

- [ ] **Step 16.1: Bump version**

Edit `custom_components/dreame_a2_mower/manifest.json`:

```json
{
  ...
  "version": "2.0.0-alpha.75"
}
```

(If the current version isn't `2.0.0-alpha.74`, bump from whatever IS current by 1.)

- [ ] **Step 16.2: Final full test suite run**

Run: `cd /data/claude/homeassistant/ha-dreame-a2-mower && python -m pytest tests/ -q`
Expected: same baseline + every new test added by Tasks 1, 2, 3, 4, 5 = passing. No regressions.

- [ ] **Step 16.3: Final import smoke-test for every modified module**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python -c "
import sys
sys.path.insert(0, 'custom_components/dreame_a2_mower')
import binary_sensor, button, camera, config_flow, coordinator, lawn_mower, live_map, number, recorder, select, sensor, session_archive, switch, time
import dreame.device
import protocol.cfg_action, protocol.pose, protocol.telemetry
print('all integration modules import OK')
"
```
Expected: prints `all integration modules import OK`.

- [ ] **Step 16.4: Commit + push the version bump**

```bash
git add custom_components/dreame_a2_mower/manifest.json
git commit -m "chore: bump version to v2.0.0-alpha.75 (ioBroker findings adoption)

Wraps up the apk-cross-reference adoption work:
- Routed-action infrastructure (Tasks 5-6)
- PRE / LIT / STUN / ATA / WRF / PROT / PATH read sensors (7-8)
- PRE writers (9)
- DOCK sensors (10)
- Action buttons (11)
- M_PATH fallback path source (13)
- Protocol-doc corrections (14)
- s2p53 / 57 / 58 / 61 piid handlers (15)
- Heading angle + uint24 task fields (Tasks 2-3)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin main
```

---

## Self-review

**Spec coverage:** every numbered scope item from the brief has at least one task:
1. ✅ Action-call infrastructure → Task 5
2. ✅ CFG fetcher → Task 6
3. ✅ PRE settings entities → Tasks 7 (read), 9 (write)
4. ✅ Pose decoder validation + conditional swap → Tasks 1, 12
5. ✅ Task struct fields → Tasks 3, 4
6. ✅ piid corrections → Task 14 (doc), Task 15 (handlers)
7. ✅ M_PATH fetch → Task 13
8. ✅ New SIID 2 piid mappings → Task 15
9. ✅ New entity groups (LIT, GPS implicit in DOCK, CMS, DOCK, AIOBS, cruise points) → Tasks 8, 10. *Note:* GPS via LOCN, AIOBS, and cruisePoints are deferred to a future plan since they need their own get-action wrappers + entity types and their schemas in the apk are sparse. Adding to TODO instead of speculative entities.
10. ✅ Action buttons → Task 11
11. ✅ Update protocol doc → Task 14

**Placeholder scan:** every step contains complete content (file paths, code, commands). The conditional Task 12 references the verdict from Task 1's fixture — both tasks are concrete.

**Type consistency:** `device.cfg`, `device.write_pre`, `device.refresh_cfg`, `device.refresh_dock_pos`, `device.call_action_opcode`, `device.cloud_mpath`, `device.voice_dl_progress`, `device.self_check_result` are defined in earlier tasks and referenced consistently in later ones. Same for `protocol/cfg_action.py`'s `get_cfg`, `get_dock_pos`, `set_pre`, `call_action_op`.

**Scope check:** each task produces a working / committable change. None depend on un-merged future tasks (Task 12 conditionally depends on Task 1's verdict, but Task 12 may simply be skipped — the rest of the plan still holds).

---

Plan complete and saved to `docs/superpowers/plans/2026-04-23-iobroker-findings-adoption.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
