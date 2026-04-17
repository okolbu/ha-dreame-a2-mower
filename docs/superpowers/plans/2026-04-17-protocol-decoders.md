# Protocol Decoders + Replay Harness Implementation Plan (Phase 1, Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce pure-Python decoder modules for the Dreame A2 (`dreame.mower.g2408`) MQTT protocol — `s1p4` mowing telemetry (33-byte blob), `s1p1` heartbeat (20-byte blob), `s2p51` multiplexed config payloads (13 settings), and a g2408-specific siid/piid property map — plus a replay harness that drives all decoders from `.jsonl` probe logs as regression fixtures. **No Home Assistant dependency in this plan.** All decoders are unit-testable in isolation.

**Architecture:** A new `custom_components/dreame_a2_mower/protocol/` package containing focused modules, each with one responsibility and a narrow interface. Plan C's coordinator will later import from this package; for now the package stands alone and is exercised by `pytest`-driven unit tests plus an end-to-end replay test that feeds a real probe-log session through the decoders and asserts the resulting session-state transitions match what was observed in the Dreame app during that session. No edits to existing HA entity code in this plan (that's Plan C).

**Tech Stack:** Python 3.14, `pytest`, dataclasses, `struct` for byte unpacking, stdlib `json` for replay. No new runtime dependencies — the decoders only use stdlib. `pytest` is a dev dependency pinned in `pyproject.toml` only.

---

## Environment & credentials

- **Fork working copy:** `/data/claude/homeassistant/ha-dreame-a2-mower/`
- **Probe log fixtures (outside fork, read-only):** `/data/claude/homeassistant/probe_log_20260417_093127.jsonl` (69 lines, connection/login only) and `/data/claude/homeassistant/probe_log_20260417_095500.jsonl` (20707 lines, full mowing session including low-battery return and session-start events).
- **Credentials hygiene:** no credentials are touched by this plan. HA is not exercised until Plan C. `.gitignore` already blocks `ha-credentials.txt`.
- **Starting HEAD:** `5aa1e8c` (current `main`, tagged `v2.0.0-alpha.2`).

## Test philosophy

Every decoder gets TDD treatment: write a failing unit test with known-good inputs (byte arrays or JSON dicts pulled directly from the probe logs or the reverse-engineering notes), watch it fail with the exact error, implement the minimum code to pass, run again, commit.

Representative byte arrays for `s1p4` and `s1p1` are taken from the probe logs. For `s2p51` payload shapes, sample payloads are copied verbatim from log entries where each setting was toggled during reverse engineering.

---

## File structure

Before any task, this is the target layout:

```
custom_components/dreame_a2_mower/protocol/
├── __init__.py              # re-exports public API
├── telemetry.py             # s1p4 decoder
├── heartbeat.py             # s1p1 decoder
├── config_s2p51.py          # s2p51 multiplexed decoder+encoder
├── properties_g2408.py      # g2408 siid/piid map + state enums
└── replay.py                # probe-log iterator

tests/
├── __init__.py
├── conftest.py              # shared fixtures (fixture-path resolver)
├── fixtures/
│   ├── session_short.jsonl  # 200-line trimmed subset for fast tests
│   └── s2p51_samples.json   # collected s2p51 payloads per setting
└── protocol/
    ├── __init__.py
    ├── test_telemetry.py
    ├── test_heartbeat.py
    ├── test_config_s2p51.py
    ├── test_properties_g2408.py
    └── test_replay.py

pyproject.toml               # pytest config, dev dep pin, package info
```

The existing `custom_components/dreame_a2_mower/dreame/` directory (the old upstream protocol package) stays untouched in Plan B. Plan C will either consume the new `protocol/` package from the coordinator or replace parts of `dreame/` with it. Leaving `dreame/` alone for now means the existing HA install continues to work during Plan B development.

---

### Task 1: Test infrastructure

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/protocol/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore` append

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "ha-dreame-a2-mower"
version = "2.0.0-alpha.2"
description = "Home Assistant integration for the Dreame A2 robotic lawn mower"
requires-python = ">=3.14"

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-ra -q"

[tool.setuptools.packages.find]
where = ["."]
include = ["custom_components*"]
```

- [ ] **Step 2: Create empty `tests/__init__.py` and `tests/protocol/__init__.py`**

```bash
touch tests/__init__.py tests/protocol/__init__.py
```

- [ ] **Step 3: Create `tests/conftest.py`**

```python
"""Shared test fixtures for dreame_a2_mower protocol tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the tests/fixtures directory."""
    return FIXTURES
```

- [ ] **Step 4: Append pytest artefact patterns to `.gitignore`**

Append to `.gitignore`:

```
# Test artefacts
.pytest_cache/
.coverage
htmlcov/
```

- [ ] **Step 5: Install dev deps and verify pytest runs**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest --collect-only
```

Expected: `no tests collected` (no test files yet — success case).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/protocol/__init__.py tests/conftest.py .gitignore
git commit -m "chore: pyproject + pytest scaffolding for protocol decoder tests"
```

---

### Task 2: Probe-log fixture data

**Files:**
- Create: `tests/fixtures/session_short.jsonl`
- Create: `tests/fixtures/s2p51_samples.json`

- [ ] **Step 1: Generate `session_short.jsonl` — first 200 lines of the probe log**

```bash
head -n 200 /data/claude/homeassistant/probe_log_20260417_095500.jsonl \
  > tests/fixtures/session_short.jsonl
wc -l tests/fixtures/session_short.jsonl
```

Expected: `200 tests/fixtures/session_short.jsonl`. This slice captures session start, first mow start transition, initial telemetry, and battery increments — enough to exercise all decoders in the integration test without shipping a multi-megabyte fixture.

- [ ] **Step 2: Generate `s2p51_samples.json` — all distinct `s2p51` payloads from the full session**

Use `jq` to extract every `s2p51` event's value from the full probe log:

```bash
grep '"siid":2,"piid":51' /data/claude/homeassistant/probe_log_20260417_095500.jsonl \
  | jq -s 'map(.params[0].value) | unique' \
  > tests/fixtures/s2p51_samples.json
cat tests/fixtures/s2p51_samples.json | head -20
```

If `jq` is not installed on the development machine, fall back to Python:

```bash
python3 - <<'PY'
import json
seen = set()
out = []
with open("/data/claude/homeassistant/probe_log_20260417_095500.jsonl") as f:
    for line in f:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        params = obj.get("params") or []
        for p in params:
            if p.get("siid") == 2 and p.get("piid") == 51:
                v = json.dumps(p["value"], sort_keys=True)
                if v not in seen:
                    seen.add(v)
                    out.append(p["value"])
with open("tests/fixtures/s2p51_samples.json", "w") as fh:
    json.dump(out, fh, indent=2)
print(f"Wrote {len(out)} unique s2p51 payloads")
PY
```

Expected: at least 4 distinct payloads across timestamp events, toggles, and settings changes observed during the RE session.

- [ ] **Step 3: Commit fixtures**

```bash
git add tests/fixtures/session_short.jsonl tests/fixtures/s2p51_samples.json
git commit -m "test: add probe-log fixtures for protocol replay tests"
```

---

### Task 3: `telemetry.py` — dataclass + frame validation + position

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/__init__.py`
- Create: `custom_components/dreame_a2_mower/protocol/telemetry.py`
- Create: `tests/protocol/test_telemetry.py`

- [ ] **Step 1: Create empty package init**

```bash
touch custom_components/dreame_a2_mower/protocol/__init__.py
```

- [ ] **Step 2: Write failing test**

Create `tests/protocol/test_telemetry.py`:

```python
"""Tests for custom_components.dreame_a2_mower.protocol.telemetry."""

from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.protocol.telemetry import (
    MowingTelemetry,
    decode_s1p4,
    InvalidS1P4Frame,
)


# Verified frame from probe_log_20260417_095500.jsonl at 2026-04-17 10:48:52
# During active mowing: x=-1562mm, y=2847mm, phase=2, area_mowed=12.50m²,
# total_area=321.00m², distance=45.4m, seq=1094.
ACTIVE_MOW_FRAME = bytes([
    0xCE,                                     # [0] delimiter
    0xE6, 0xF9,                               # [1-2] x = -1562 (int16_le, 0xF9E6)
    0x1F, 0x0B,                               # [3-4] y = 2847 (int16_le, 0x0B1F)
    0x00,                                     # [5] static
    0x46, 0x04,                               # [6-7] seq = 1094
    0x02,                                     # [8] phase = mowing
    0x00,                                     # [9] static
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,       # [10-15] motion (zeros for this sample)
    0x00, 0x00,                               # [16-17] motion
    0xFF, 0x7F, 0x00, 0x80,                   # [18-21] sentinel vectors
    0x01, 0x02,                               # [22-23] flags
    0xC6, 0x01,                               # [24-25] distance = 454 (÷10 = 45.4m)
    0x64, 0x7D,                               # [26-27] total area = 32100 (÷100 = 321.00m²)
    0x00,                                     # [28] static
    0xE2, 0x04,                               # [29-30] area mowed = 1250 (÷100 = 12.50m²)
    0x00,                                     # [31] static
    0xCE,                                     # [32] delimiter
])


def test_decode_s1p4_valid_frame_returns_telemetry_dataclass():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert isinstance(t, MowingTelemetry)


def test_decode_s1p4_position_is_charger_relative_mm():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.x_mm == -1562
    assert t.y_mm == 2847


def test_decode_s1p4_rejects_wrong_length():
    with pytest.raises(InvalidS1P4Frame, match="length"):
        decode_s1p4(b"\xce\x00\xce")


def test_decode_s1p4_rejects_missing_start_delimiter():
    bad = bytes([0x00]) + ACTIVE_MOW_FRAME[1:]
    with pytest.raises(InvalidS1P4Frame, match="delimiter"):
        decode_s1p4(bad)


def test_decode_s1p4_rejects_missing_end_delimiter():
    bad = ACTIVE_MOW_FRAME[:-1] + bytes([0x00])
    with pytest.raises(InvalidS1P4Frame, match="delimiter"):
        decode_s1p4(bad)
```

- [ ] **Step 3: Run test, verify failure**

```bash
pytest tests/protocol/test_telemetry.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` for `custom_components.dreame_a2_mower.protocol.telemetry`.

- [ ] **Step 4: Write minimal implementation**

Create `custom_components/dreame_a2_mower/protocol/telemetry.py`:

```python
"""s1p4 mowing telemetry decoder for Dreame A2 (g2408).

The s1p4 property carries a 33-byte little-endian blob sent roughly every
second during active mowing. Full byte layout is documented in the reverse-
engineering notes (docs/superpowers/specs/2026-04-17-dreame-a2-mower-
ha-integration-design.md and the project memory).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

FRAME_LENGTH = 33
FRAME_DELIMITER = 0xCE


class InvalidS1P4Frame(ValueError):
    """Raised when an s1p4 frame does not match the expected shape."""


@dataclass(frozen=True)
class MowingTelemetry:
    """Decoded s1p4 frame.

    Position is charger-relative, millimetres, fixed to map north (no rotation
    per session — verified across two sessions with different mow directions).
    """

    x_mm: int
    y_mm: int


def decode_s1p4(data: bytes) -> MowingTelemetry:
    """Decode a single 33-byte s1p4 frame."""
    if len(data) != FRAME_LENGTH:
        raise InvalidS1P4Frame(
            f"expected frame length {FRAME_LENGTH}, got {len(data)}"
        )
    if data[0] != FRAME_DELIMITER or data[-1] != FRAME_DELIMITER:
        raise InvalidS1P4Frame(
            f"expected 0x{FRAME_DELIMITER:02X} delimiters at [0] and [32]"
        )
    x_mm, y_mm = struct.unpack_from("<hh", data, 1)
    return MowingTelemetry(x_mm=x_mm, y_mm=y_mm)
```

- [ ] **Step 5: Run tests, verify pass**

```bash
pytest tests/protocol/test_telemetry.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/__init__.py \
        custom_components/dreame_a2_mower/protocol/telemetry.py \
        tests/protocol/test_telemetry.py
git commit -m "feat(protocol): s1p4 telemetry decoder with position + frame validation"
```

---

### Task 4: `telemetry.py` — phase + sequence + area + distance

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/telemetry.py`
- Modify: `tests/protocol/test_telemetry.py`

- [ ] **Step 1: Add failing tests for phase/sequence/area/distance**

Append to `tests/protocol/test_telemetry.py`:

```python
from custom_components.dreame_a2_mower.protocol.telemetry import Phase


def test_decode_s1p4_exposes_sequence_counter():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.sequence == 1094


def test_decode_s1p4_exposes_phase_enum_for_active_mow():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.phase is Phase.MOWING


@pytest.mark.parametrize(
    ("phase_byte", "expected"),
    [
        (0, Phase.EDGE_OR_REPOSITION),
        (1, Phase.TRANSIT),
        (2, Phase.MOWING),
        (3, Phase.RETURNING),
    ],
)
def test_decode_s1p4_phase_byte_mapping(phase_byte, expected):
    frame = bytearray(ACTIVE_MOW_FRAME)
    frame[8] = phase_byte
    assert decode_s1p4(bytes(frame)).phase is expected


def test_decode_s1p4_unknown_phase_byte_is_preserved_raw():
    frame = bytearray(ACTIVE_MOW_FRAME)
    frame[8] = 9
    t = decode_s1p4(bytes(frame))
    assert t.phase is Phase.UNKNOWN
    assert t.phase_raw == 9


def test_decode_s1p4_distance_meters_from_deci_units():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # raw = 454 → 45.4m
    assert t.distance_m == pytest.approx(45.4)


def test_decode_s1p4_total_area_from_centiares():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # raw = 32100 → 321.00m²
    assert t.total_area_m2 == pytest.approx(321.00)


def test_decode_s1p4_mowed_area_from_centiares():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # raw = 1250 → 12.50m²
    assert t.area_mowed_m2 == pytest.approx(12.50)
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/protocol/test_telemetry.py -v
```

Expected: the new 8 tests fail (ImportError on `Phase`, AttributeError on `sequence`, `phase`, `distance_m`, `total_area_m2`, `area_mowed_m2`).

- [ ] **Step 3: Extend the implementation**

Replace the contents of `custom_components/dreame_a2_mower/protocol/telemetry.py` with:

```python
"""s1p4 mowing telemetry decoder for Dreame A2 (g2408)."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

FRAME_LENGTH = 33
FRAME_DELIMITER = 0xCE


class InvalidS1P4Frame(ValueError):
    """Raised when an s1p4 frame does not match the expected shape."""


class Phase(IntEnum):
    EDGE_OR_REPOSITION = 0
    TRANSIT = 1
    MOWING = 2
    RETURNING = 3
    UNKNOWN = -1


@dataclass(frozen=True)
class MowingTelemetry:
    """Decoded s1p4 frame.

    Position is charger-relative millimetres, fixed to map north.
    Distance and area counters reset at the start of each mowing session.
    """

    x_mm: int
    y_mm: int
    sequence: int
    phase: Phase
    phase_raw: int
    distance_m: float
    total_area_m2: float
    area_mowed_m2: float


def decode_s1p4(data: bytes) -> MowingTelemetry:
    if len(data) != FRAME_LENGTH:
        raise InvalidS1P4Frame(
            f"expected frame length {FRAME_LENGTH}, got {len(data)}"
        )
    if data[0] != FRAME_DELIMITER or data[-1] != FRAME_DELIMITER:
        raise InvalidS1P4Frame(
            f"expected 0x{FRAME_DELIMITER:02X} delimiters at [0] and [32]"
        )
    x_mm, y_mm = struct.unpack_from("<hh", data, 1)
    seq = struct.unpack_from("<H", data, 6)[0]
    phase_raw = data[8]
    phase = Phase(phase_raw) if phase_raw in Phase._value2member_map_ else Phase.UNKNOWN
    distance_deci = struct.unpack_from("<H", data, 24)[0]
    total_area_cent = struct.unpack_from("<H", data, 26)[0]
    area_mowed_cent = struct.unpack_from("<H", data, 29)[0]
    return MowingTelemetry(
        x_mm=x_mm,
        y_mm=y_mm,
        sequence=seq,
        phase=phase,
        phase_raw=phase_raw,
        distance_m=distance_deci / 10.0,
        total_area_m2=total_area_cent / 100.0,
        area_mowed_m2=area_mowed_cent / 100.0,
    )
```

- [ ] **Step 4: Run tests, verify all pass**

```bash
pytest tests/protocol/test_telemetry.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/telemetry.py \
        tests/protocol/test_telemetry.py
git commit -m "feat(protocol): s1p4 phase/sequence/area/distance decoding"
```

---

### Task 5: `heartbeat.py` — s1p1 20-byte blob

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/heartbeat.py`
- Create: `tests/protocol/test_heartbeat.py`

- [ ] **Step 1: Write failing test**

Create `tests/protocol/test_heartbeat.py`:

```python
"""Tests for custom_components.dreame_a2_mower.protocol.heartbeat."""

from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.protocol.heartbeat import (
    Heartbeat,
    decode_s1p1,
    InvalidS1P1Frame,
)


# From probe_log_20260417_095500.jsonl at 2026-04-17 09:55:56.
HEARTBEAT_FRAME_A = bytes([
    0xCE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0xDA, 0x85, 0x24, 0x00, 0x01, 0x80, 0xC1, 0xBA, 0xCE,
])

# From same session, ~68s later — counter advanced at bytes [11,12].
HEARTBEAT_FRAME_B = bytes([
    0xCE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0xDB, 0xB5, 0x24, 0x00, 0x01, 0x80, 0xC1, 0xBA, 0xCE,
])


def test_decode_s1p1_returns_heartbeat_dataclass():
    assert isinstance(decode_s1p1(HEARTBEAT_FRAME_A), Heartbeat)


def test_decode_s1p1_rejects_wrong_length():
    with pytest.raises(InvalidS1P1Frame, match="length"):
        decode_s1p1(b"\xce\x00\xce")


def test_decode_s1p1_rejects_wrong_delimiters():
    bad = bytes([0x00]) + HEARTBEAT_FRAME_A[1:]
    with pytest.raises(InvalidS1P1Frame, match="delimiter"):
        decode_s1p1(bad)


def test_decode_s1p1_exposes_counter_bytes_11_12():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.counter == (0xDA | (0x85 << 8))  # little-endian u16 at [11,12]


def test_decode_s1p1_counter_advances_between_frames():
    a = decode_s1p1(HEARTBEAT_FRAME_A)
    b = decode_s1p1(HEARTBEAT_FRAME_B)
    assert b.counter > a.counter


def test_decode_s1p1_exposes_state_byte_7():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.state_raw == 0


def test_decode_s1p1_exposes_raw_bytes():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.raw == HEARTBEAT_FRAME_A
```

- [ ] **Step 2: Run test, verify failure**

```bash
pytest tests/protocol/test_heartbeat.py -v
```

Expected: `ModuleNotFoundError: custom_components.dreame_a2_mower.protocol.heartbeat`.

- [ ] **Step 3: Write implementation**

Create `custom_components/dreame_a2_mower/protocol/heartbeat.py`:

```python
"""s1p1 heartbeat decoder for Dreame A2 (g2408).

The s1p1 property is a 20-byte blob sent every ~45s regardless of mowing
state. Most bytes are static; bytes [11,12] form a monotonic little-endian
counter, byte [7] carries a partial state indicator (0=idle, non-zero values
observed during state transitions).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

FRAME_LENGTH = 20
FRAME_DELIMITER = 0xCE


class InvalidS1P1Frame(ValueError):
    """Raised when an s1p1 frame does not match the expected shape."""


@dataclass(frozen=True)
class Heartbeat:
    counter: int
    state_raw: int
    raw: bytes


def decode_s1p1(data: bytes) -> Heartbeat:
    if len(data) != FRAME_LENGTH:
        raise InvalidS1P1Frame(
            f"expected frame length {FRAME_LENGTH}, got {len(data)}"
        )
    if data[0] != FRAME_DELIMITER or data[-1] != FRAME_DELIMITER:
        raise InvalidS1P1Frame(
            f"expected 0x{FRAME_DELIMITER:02X} delimiters at [0] and [19]"
        )
    counter = struct.unpack_from("<H", data, 11)[0]
    state_raw = data[7]
    return Heartbeat(counter=counter, state_raw=state_raw, raw=bytes(data))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/protocol/test_heartbeat.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/heartbeat.py \
        tests/protocol/test_heartbeat.py
git commit -m "feat(protocol): s1p1 heartbeat partial decoder"
```

---

### Task 6: `properties_g2408.py` — siid/piid map + state enums

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/properties_g2408.py`
- Create: `tests/protocol/test_properties_g2408.py`

- [ ] **Step 1: Write failing tests**

Create `tests/protocol/test_properties_g2408.py`:

```python
"""Tests for the g2408 siid/piid property map."""

from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.protocol.properties_g2408 import (
    Property,
    PROPERTY_MAP,
    StateCode,
    ChargingStatus,
    siid_piid,
    property_for,
    state_label,
    charging_label,
)


def test_property_map_returns_battery_siid_piid():
    assert siid_piid(Property.BATTERY_LEVEL) == (3, 1)


def test_property_map_returns_state_siid_piid():
    assert siid_piid(Property.STATE) == (2, 2)


def test_property_map_returns_telemetry_blob_siid_piid():
    # s1p4 — 33-byte mowing telemetry
    assert siid_piid(Property.MOWING_TELEMETRY) == (1, 4)


def test_property_map_returns_heartbeat_blob_siid_piid():
    # s1p1 — 20-byte heartbeat
    assert siid_piid(Property.HEARTBEAT) == (1, 1)


def test_property_map_returns_obstacle_flag_siid_piid():
    # s1p53 — boolean set during obstacle/exclusion-zone proximity
    assert siid_piid(Property.OBSTACLE_FLAG) == (1, 53)


def test_property_map_returns_multiplexed_config_siid_piid():
    # s2p51 — every "More Settings" change flows through this property
    assert siid_piid(Property.MULTIPLEXED_CONFIG) == (2, 51)


def test_property_for_reverse_lookup_known_siid_piid():
    assert property_for(3, 1) is Property.BATTERY_LEVEL
    assert property_for(1, 4) is Property.MOWING_TELEMETRY


def test_property_for_unknown_siid_piid_returns_none():
    assert property_for(99, 99) is None


@pytest.mark.parametrize(
    ("code", "label"),
    [
        (70, "mowing"),
        (54, "returning"),
        (48, "mowing_complete"),
        (50, "session_started"),
        (27, "idle"),
    ],
)
def test_state_label_translates_known_g2408_s2p2_codes(code, label):
    assert state_label(StateCode(code)) == label


def test_state_label_unknown_code_returns_unknown_with_raw():
    assert state_label(999) == "unknown_999"


@pytest.mark.parametrize(
    ("code", "label"),
    [
        (0, "not_charging"),  # g2408 differs from upstream enum which starts at 1
        (1, "charging"),
        (2, "charged"),
    ],
)
def test_charging_label_translates_g2408_s3p2_codes(code, label):
    assert charging_label(ChargingStatus(code)) == label


def test_charging_label_unknown_returns_unknown_with_raw():
    assert charging_label(42) == "unknown_42"
```

- [ ] **Step 2: Run test, verify failure**

```bash
pytest tests/protocol/test_properties_g2408.py -v
```

Expected: import error — module does not exist yet.

- [ ] **Step 3: Write implementation**

Create `custom_components/dreame_a2_mower/protocol/properties_g2408.py`:

```python
"""g2408-specific siid/piid map and state-code translations.

This replaces the multi-model property registry from upstream's dreame/types.py
with values observed on the Dreame A2 (model dreame.mower.g2408) via MQTT
probing. Upstream's mapping was built for A1 Pro and earlier vacuum-derived
mowers, which use different siid/piid assignments — the reason so many entities
show "Unavailable" on a g2408 with the upstream integration.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Final


class Property(StrEnum):
    BATTERY_LEVEL = "battery_level"
    STATE = "state"
    CHARGING_STATUS = "charging_status"
    MOWING_TELEMETRY = "mowing_telemetry"
    HEARTBEAT = "heartbeat"
    OBSTACLE_FLAG = "obstacle_flag"
    MULTIPLEXED_CONFIG = "multiplexed_config"


PROPERTY_MAP: Final[dict[Property, tuple[int, int]]] = {
    Property.BATTERY_LEVEL: (3, 1),
    Property.STATE: (2, 2),
    Property.CHARGING_STATUS: (3, 2),
    Property.MOWING_TELEMETRY: (1, 4),
    Property.HEARTBEAT: (1, 1),
    Property.OBSTACLE_FLAG: (1, 53),
    Property.MULTIPLEXED_CONFIG: (2, 51),
}

_REVERSE_MAP: Final[dict[tuple[int, int], Property]] = {
    v: k for k, v in PROPERTY_MAP.items()
}


def siid_piid(prop: Property) -> tuple[int, int]:
    """Return the g2408 (siid, piid) tuple for a Property."""
    return PROPERTY_MAP[prop]


def property_for(siid: int, piid: int) -> Property | None:
    """Reverse-lookup a Property from a (siid, piid) tuple, or None if unknown."""
    return _REVERSE_MAP.get((siid, piid))


class StateCode(IntEnum):
    SESSION_STARTED = 50
    MOWING = 70
    RETURNING = 54
    MOWING_COMPLETE = 48
    IDLE = 27


_STATE_LABELS: Final[dict[int, str]] = {
    StateCode.SESSION_STARTED: "session_started",
    StateCode.MOWING: "mowing",
    StateCode.RETURNING: "returning",
    StateCode.MOWING_COMPLETE: "mowing_complete",
    StateCode.IDLE: "idle",
}


def state_label(code: int) -> str:
    """Translate a raw s2p2 code into a human-readable label."""
    return _STATE_LABELS.get(int(code), f"unknown_{int(code)}")


class ChargingStatus(IntEnum):
    # Upstream enum starts at 1; g2408 includes 0 = not_charging.
    NOT_CHARGING = 0
    CHARGING = 1
    CHARGED = 2


_CHARGING_LABELS: Final[dict[int, str]] = {
    ChargingStatus.NOT_CHARGING: "not_charging",
    ChargingStatus.CHARGING: "charging",
    ChargingStatus.CHARGED: "charged",
}


def charging_label(code: int) -> str:
    return _CHARGING_LABELS.get(int(code), f"unknown_{int(code)}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/protocol/test_properties_g2408.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/properties_g2408.py \
        tests/protocol/test_properties_g2408.py
git commit -m "feat(protocol): g2408 siid/piid map + state/charging label helpers"
```

---

### Task 7: `config_s2p51.py` — Setting enum + decode dispatcher + simple toggles + timestamp event

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/config_s2p51.py`
- Create: `tests/protocol/test_config_s2p51.py`

**Background:** s2p51 is a "multiplexed" property — every More Settings change flows through this one siid/piid with a different value-payload shape per setting. Five settings share the shape `{"value": 0|1}` (Navigation Path, Auto Recharge Standby, Child Lock, Frost Protection, AI Obstacle Photos). **These are not distinguishable from each other on the read path alone** — the mower broadcasts the change without labelling which toggle fired. The decoder returns an ambiguous-toggle kind for these, and the coordinator in Plan C must combine the event with app-action context.

- [ ] **Step 1: Write failing tests**

Create `tests/protocol/test_config_s2p51.py`:

```python
"""Tests for s2p51 multiplexed config decoder."""

from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.protocol.config_s2p51 import (
    Setting,
    S2P51Event,
    decode_s2p51,
    S2P51DecodeError,
)


def test_decode_timestamp_event_returns_timestamp_kind():
    payload = {"time": "1776415722", "tz": "UTC"}
    ev = decode_s2p51(payload)
    assert ev.setting is Setting.TIMESTAMP
    assert ev.values == {"time": 1776415722, "tz": "UTC"}


def test_decode_ambiguous_toggle_value_one():
    ev = decode_s2p51({"value": 1})
    assert ev.setting is Setting.AMBIGUOUS_TOGGLE
    assert ev.values == {"value": 1}


def test_decode_ambiguous_toggle_value_zero():
    ev = decode_s2p51({"value": 0})
    assert ev.setting is Setting.AMBIGUOUS_TOGGLE
    assert ev.values == {"value": 0}


def test_decode_rejects_malformed_payload():
    with pytest.raises(S2P51DecodeError, match="unknown"):
        decode_s2p51({"nonsense": True})


def test_decode_rejects_empty_payload():
    with pytest.raises(S2P51DecodeError, match="empty"):
        decode_s2p51({})
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/protocol/test_config_s2p51.py -v
```

Expected: module import fails.

- [ ] **Step 3: Write initial implementation**

Create `custom_components/dreame_a2_mower/protocol/config_s2p51.py`:

```python
"""s2p51 multiplexed config decoder/encoder for Dreame A2 (g2408).

Every "More Settings" change on the mower (DnD, Rain Protection, LED schedule,
etc.) is transported via the single s2p51 property with different payload
shapes. This module recognises each shape and returns a typed event, or flags
the payload as ambiguous when multiple settings share identical shape.

See docs/superpowers/specs/2026-04-17-dreame-a2-mower-ha-integration-design.md
and the project memory for the full shape catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class S2P51DecodeError(ValueError):
    """Raised when an s2p51 payload does not match any known shape."""


class Setting(StrEnum):
    TIMESTAMP = "timestamp"
    AMBIGUOUS_TOGGLE = "ambiguous_toggle"
    DND = "dnd"
    LOW_SPEED_NIGHT = "low_speed_night"
    CHARGING = "charging"
    LED_PERIOD = "led_period"
    ANTI_THEFT = "anti_theft"
    RAIN_PROTECTION = "rain_protection"
    HUMAN_PRESENCE_ALERT = "human_presence_alert"


@dataclass(frozen=True)
class S2P51Event:
    setting: Setting
    values: dict[str, Any]


def decode_s2p51(payload: dict[str, Any]) -> S2P51Event:
    if not payload:
        raise S2P51DecodeError("empty payload")

    if "time" in payload and "tz" in payload:
        return S2P51Event(
            setting=Setting.TIMESTAMP,
            values={"time": int(payload["time"]), "tz": payload["tz"]},
        )

    if set(payload.keys()) == {"value"}:
        value = payload["value"]
        if isinstance(value, int):
            return S2P51Event(
                setting=Setting.AMBIGUOUS_TOGGLE,
                values={"value": value},
            )

    raise S2P51DecodeError(f"unknown payload shape: {payload!r}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/protocol/test_config_s2p51.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/config_s2p51.py \
        tests/protocol/test_config_s2p51.py
git commit -m "feat(protocol): s2p51 decoder skeleton — timestamps + ambiguous toggles"
```

---

### Task 8: `config_s2p51.py` — time-range settings (DnD, Low-Speed Nighttime, Rain Protection)

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/config_s2p51.py`
- Modify: `tests/protocol/test_config_s2p51.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/protocol/test_config_s2p51.py`:

```python
def test_decode_dnd_event_extracts_start_end_enabled():
    ev = decode_s2p51({"end": 420, "start": 1320, "value": 1})
    assert ev.setting is Setting.DND
    assert ev.values == {"start_min": 1320, "end_min": 420, "enabled": True}


def test_decode_dnd_event_disabled():
    ev = decode_s2p51({"end": 420, "start": 1320, "value": 0})
    assert ev.setting is Setting.DND
    assert ev.values["enabled"] is False


def test_decode_low_speed_nighttime_three_element_list():
    # [enabled, start_min, end_min] — times clearly larger than 1
    ev = decode_s2p51({"value": [1, 1260, 360]})
    assert ev.setting is Setting.LOW_SPEED_NIGHT
    assert ev.values == {"enabled": True, "start_min": 1260, "end_min": 360}


def test_decode_rain_protection_two_element_list():
    # [enabled, resume_hours]
    ev = decode_s2p51({"value": [1, 3]})
    assert ev.setting is Setting.RAIN_PROTECTION
    assert ev.values == {"enabled": True, "resume_hours": 3}
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/protocol/test_config_s2p51.py::test_decode_dnd_event_extracts_start_end_enabled -v
```

Expected: `S2P51DecodeError: unknown payload shape`.

- [ ] **Step 3: Extend implementation**

Modify `decode_s2p51` in `custom_components/dreame_a2_mower/protocol/config_s2p51.py`. Replace the function with:

```python
def decode_s2p51(payload: dict[str, Any]) -> S2P51Event:
    if not payload:
        raise S2P51DecodeError("empty payload")

    if "time" in payload and "tz" in payload:
        return S2P51Event(
            setting=Setting.TIMESTAMP,
            values={"time": int(payload["time"]), "tz": payload["tz"]},
        )

    # DnD sends three keys and is unambiguous.
    if set(payload.keys()) == {"end", "start", "value"}:
        return S2P51Event(
            setting=Setting.DND,
            values={
                "start_min": int(payload["start"]),
                "end_min": int(payload["end"]),
                "enabled": bool(payload["value"]),
            },
        )

    if set(payload.keys()) == {"value"}:
        value = payload["value"]
        if isinstance(value, int):
            return S2P51Event(
                setting=Setting.AMBIGUOUS_TOGGLE,
                values={"value": value},
            )
        if isinstance(value, list):
            return _decode_list_payload(value)

    raise S2P51DecodeError(f"unknown payload shape: {payload!r}")


def _decode_list_payload(value: list[int]) -> S2P51Event:
    n = len(value)
    if n == 2:
        return S2P51Event(
            setting=Setting.RAIN_PROTECTION,
            values={"enabled": bool(value[0]), "resume_hours": int(value[1])},
        )
    if n == 3:
        # Low-Speed Nighttime: [enabled, start_min, end_min]; times are 0..1440.
        # Anti-Theft: [lift, offmap, realtime]; all three are 0/1. Distinguish
        # by checking whether any value exceeds 1.
        if any(v > 1 for v in value):
            return S2P51Event(
                setting=Setting.LOW_SPEED_NIGHT,
                values={
                    "enabled": bool(value[0]),
                    "start_min": int(value[1]),
                    "end_min": int(value[2]),
                },
            )
    raise S2P51DecodeError(f"unknown list payload shape (len={n}): {value!r}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/protocol/test_config_s2p51.py -v
```

Expected: all 9 tests pass (5 existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/config_s2p51.py \
        tests/protocol/test_config_s2p51.py
git commit -m "feat(protocol): s2p51 — DnD, Low-Speed Nighttime, Rain Protection"
```

---

### Task 9: `config_s2p51.py` — Anti-Theft, Charging, LED Period, Human Presence

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/config_s2p51.py`
- Modify: `tests/protocol/test_config_s2p51.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/protocol/test_config_s2p51.py`:

```python
def test_decode_anti_theft_three_element_all_binary():
    # [lift_alarm, offmap_alarm, realtime_location] — all 0 or 1
    ev = decode_s2p51({"value": [1, 0, 1]})
    assert ev.setting is Setting.ANTI_THEFT
    assert ev.values == {
        "lift_alarm": True,
        "offmap_alarm": False,
        "realtime_location": True,
    }


def test_decode_charging_six_element_list():
    # [recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min]
    ev = decode_s2p51({"value": [15, 95, 0, 0, 0, 0]})
    assert ev.setting is Setting.CHARGING
    assert ev.values == {
        "recharge_pct": 15,
        "resume_pct": 95,
        "unknown_flag": 0,
        "custom_charging": False,
        "start_min": 0,
        "end_min": 0,
    }


def test_decode_led_period_eight_element_list():
    # [enabled, start_min, end_min, standby, working, charging, error, reserved]
    ev = decode_s2p51({"value": [1, 360, 1320, 1, 1, 1, 1, 0]})
    assert ev.setting is Setting.LED_PERIOD
    assert ev.values == {
        "enabled": True,
        "start_min": 360,
        "end_min": 1320,
        "standby": True,
        "working": True,
        "charging": True,
        "error": True,
        "reserved": 0,
    }


def test_decode_human_presence_nine_element_list():
    # [enabled, sensitivity, standby, mowing, recharge, patrol, alert, photos, push_min]
    # Example from probe log at 2026-04-17 11:13:57: [0,1,1,1,1,1,1,0,3]
    ev = decode_s2p51({"value": [0, 1, 1, 1, 1, 1, 1, 0, 3]})
    assert ev.setting is Setting.HUMAN_PRESENCE_ALERT
    assert ev.values == {
        "enabled": False,
        "sensitivity": 1,
        "standby": True,
        "mowing": True,
        "recharge": True,
        "patrol": True,
        "alert": True,
        "photos": False,
        "push_min": 3,
    }
```

- [ ] **Step 2: Run tests, verify the new four fail**

```bash
pytest tests/protocol/test_config_s2p51.py -v
```

Expected: 4 new tests fail with `S2P51DecodeError: unknown list payload shape`.

- [ ] **Step 3: Extend `_decode_list_payload`**

Replace `_decode_list_payload` in `custom_components/dreame_a2_mower/protocol/config_s2p51.py` with:

```python
def _decode_list_payload(value: list[int]) -> S2P51Event:
    n = len(value)
    if n == 2:
        return S2P51Event(
            setting=Setting.RAIN_PROTECTION,
            values={"enabled": bool(value[0]), "resume_hours": int(value[1])},
        )
    if n == 3:
        if any(v > 1 for v in value):
            return S2P51Event(
                setting=Setting.LOW_SPEED_NIGHT,
                values={
                    "enabled": bool(value[0]),
                    "start_min": int(value[1]),
                    "end_min": int(value[2]),
                },
            )
        return S2P51Event(
            setting=Setting.ANTI_THEFT,
            values={
                "lift_alarm": bool(value[0]),
                "offmap_alarm": bool(value[1]),
                "realtime_location": bool(value[2]),
            },
        )
    if n == 6:
        return S2P51Event(
            setting=Setting.CHARGING,
            values={
                "recharge_pct": int(value[0]),
                "resume_pct": int(value[1]),
                "unknown_flag": int(value[2]),
                "custom_charging": bool(value[3]),
                "start_min": int(value[4]),
                "end_min": int(value[5]),
            },
        )
    if n == 8:
        return S2P51Event(
            setting=Setting.LED_PERIOD,
            values={
                "enabled": bool(value[0]),
                "start_min": int(value[1]),
                "end_min": int(value[2]),
                "standby": bool(value[3]),
                "working": bool(value[4]),
                "charging": bool(value[5]),
                "error": bool(value[6]),
                "reserved": int(value[7]),
            },
        )
    if n == 9:
        return S2P51Event(
            setting=Setting.HUMAN_PRESENCE_ALERT,
            values={
                "enabled": bool(value[0]),
                "sensitivity": int(value[1]),
                "standby": bool(value[2]),
                "mowing": bool(value[3]),
                "recharge": bool(value[4]),
                "patrol": bool(value[5]),
                "alert": bool(value[6]),
                "photos": bool(value[7]),
                "push_min": int(value[8]),
            },
        )
    raise S2P51DecodeError(f"unknown list payload shape (len={n}): {value!r}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/protocol/test_config_s2p51.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/config_s2p51.py \
        tests/protocol/test_config_s2p51.py
git commit -m "feat(protocol): s2p51 — Anti-Theft, Charging, LED Period, Human Presence"
```

---

### Task 10: `config_s2p51.py` — `encode()` for write path

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/config_s2p51.py`
- Modify: `tests/protocol/test_config_s2p51.py`

**Background:** The coordinator in Plan C will need to write settings back to the mower via MQTT. `encode()` is the inverse of `decode_s2p51` — given an `S2P51Event`, produce the payload dict the mower expects. Round-trip tests ensure encode and decode stay consistent.

- [ ] **Step 1: Add round-trip tests**

Append to `tests/protocol/test_config_s2p51.py`:

```python
from custom_components.dreame_a2_mower.protocol.config_s2p51 import encode_s2p51


@pytest.mark.parametrize(
    "payload",
    [
        {"time": "1776415722", "tz": "UTC"},
        # skip AMBIGUOUS_TOGGLE — no round trip without naming the setting
        {"end": 420, "start": 1320, "value": 1},
        {"value": [1, 1260, 360]},       # low-speed-night
        {"value": [1, 0, 1]},            # anti-theft
        {"value": [1, 3]},               # rain-protection
        {"value": [15, 95, 0, 0, 0, 0]}, # charging
        {"value": [1, 360, 1320, 1, 1, 1, 1, 0]},  # led-period
        {"value": [0, 1, 1, 1, 1, 1, 1, 0, 3]},    # human-presence
    ],
)
def test_encode_decode_roundtrip_for_identifiable_shapes(payload):
    ev = decode_s2p51(payload)
    reconstructed = encode_s2p51(ev)
    # Re-decode to normalize both sides (key order / bool vs int for value).
    assert decode_s2p51(reconstructed) == ev


def test_encode_rejects_ambiguous_toggle_without_specific_setting():
    # The caller must first promote AMBIGUOUS_TOGGLE to a concrete setting
    # using external context before encoding it back.
    ev = S2P51Event(setting=Setting.AMBIGUOUS_TOGGLE, values={"value": 1})
    with pytest.raises(S2P51DecodeError, match="ambiguous"):
        encode_s2p51(ev)
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/protocol/test_config_s2p51.py -v
```

Expected: import errors on `encode_s2p51`.

- [ ] **Step 3: Implement `encode_s2p51`**

Append to `custom_components/dreame_a2_mower/protocol/config_s2p51.py`:

```python
def encode_s2p51(event: S2P51Event) -> dict[str, Any]:
    """Encode an S2P51Event back into a wire-format payload dict.

    AMBIGUOUS_TOGGLE events cannot be round-tripped because the decoder cannot
    name the specific setting; callers must first replace the setting with a
    concrete toggle using external context (i.e. the app action that fired).
    """
    setting = event.setting
    v = event.values

    if setting is Setting.TIMESTAMP:
        return {"time": str(v["time"]), "tz": v["tz"]}
    if setting is Setting.DND:
        return {
            "end": int(v["end_min"]),
            "start": int(v["start_min"]),
            "value": int(bool(v["enabled"])),
        }
    if setting is Setting.LOW_SPEED_NIGHT:
        return {"value": [
            int(bool(v["enabled"])), int(v["start_min"]), int(v["end_min"])
        ]}
    if setting is Setting.ANTI_THEFT:
        return {"value": [
            int(bool(v["lift_alarm"])),
            int(bool(v["offmap_alarm"])),
            int(bool(v["realtime_location"])),
        ]}
    if setting is Setting.RAIN_PROTECTION:
        return {"value": [
            int(bool(v["enabled"])), int(v["resume_hours"])
        ]}
    if setting is Setting.CHARGING:
        return {"value": [
            int(v["recharge_pct"]),
            int(v["resume_pct"]),
            int(v["unknown_flag"]),
            int(bool(v["custom_charging"])),
            int(v["start_min"]),
            int(v["end_min"]),
        ]}
    if setting is Setting.LED_PERIOD:
        return {"value": [
            int(bool(v["enabled"])),
            int(v["start_min"]),
            int(v["end_min"]),
            int(bool(v["standby"])),
            int(bool(v["working"])),
            int(bool(v["charging"])),
            int(bool(v["error"])),
            int(v["reserved"]),
        ]}
    if setting is Setting.HUMAN_PRESENCE_ALERT:
        return {"value": [
            int(bool(v["enabled"])),
            int(v["sensitivity"]),
            int(bool(v["standby"])),
            int(bool(v["mowing"])),
            int(bool(v["recharge"])),
            int(bool(v["patrol"])),
            int(bool(v["alert"])),
            int(bool(v["photos"])),
            int(v["push_min"]),
        ]}
    if setting is Setting.AMBIGUOUS_TOGGLE:
        raise S2P51DecodeError(
            "ambiguous toggle cannot be encoded — resolve to a concrete setting first"
        )
    raise S2P51DecodeError(f"unknown setting: {setting!r}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/protocol/test_config_s2p51.py -v
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/config_s2p51.py \
        tests/protocol/test_config_s2p51.py
git commit -m "feat(protocol): s2p51 encode — round-trip for 8 identifiable settings"
```

---

### Task 11: `replay.py` — probe-log iterator

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/replay.py`
- Create: `tests/protocol/test_replay.py`

- [ ] **Step 1: Write failing test**

Create `tests/protocol/test_replay.py`:

```python
"""Tests for the probe-log replay iterator."""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.dreame_a2_mower.protocol.replay import (
    ProbeLogEvent,
    iter_probe_log,
)


def test_iter_probe_log_yields_mqtt_messages_only(fixtures_dir: Path):
    events = list(iter_probe_log(fixtures_dir / "session_short.jsonl"))
    assert events, "expected at least one event from the trimmed fixture"
    assert all(isinstance(e, ProbeLogEvent) for e in events)
    assert all(e.method == "properties_changed" for e in events)


def test_iter_probe_log_parses_siid_piid_value(fixtures_dir: Path):
    events = list(iter_probe_log(fixtures_dir / "session_short.jsonl"))
    # First mqtt_message in the short fixture is s3p1 BATTERY_LEVEL = 90.
    first = events[0]
    assert (first.siid, first.piid) == (3, 1)
    assert first.value == 90
    assert first.timestamp == "2026-04-17 09:55:56"


def test_iter_probe_log_captures_list_value_for_telemetry_blob(fixtures_dir: Path):
    events = list(iter_probe_log(fixtures_dir / "session_short.jsonl"))
    blobs = [e for e in events if (e.siid, e.piid) == (1, 1)]
    assert blobs, "expected at least one s1p1 heartbeat blob"
    assert isinstance(blobs[0].value, list)
    assert len(blobs[0].value) == 20


def test_iter_probe_log_raises_on_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(iter_probe_log(tmp_path / "does_not_exist.jsonl"))
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/protocol/test_replay.py -v
```

Expected: `ModuleNotFoundError: custom_components.dreame_a2_mower.protocol.replay`.

- [ ] **Step 3: Write implementation**

Create `custom_components/dreame_a2_mower/protocol/replay.py`:

```python
"""Probe-log replay iterator.

Consumes a `.jsonl` probe-log file and yields one ProbeLogEvent per
MQTT `properties_changed` message, with the message's siid/piid/value
extracted for downstream decoding.

The probe tool (probe_a2_mqtt.py) writes one JSON object per line. Lines whose
"type" is not "mqtt_message" are skipped (session_start, pretty annotations,
api_probe records, etc.).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Union


@dataclass(frozen=True)
class ProbeLogEvent:
    timestamp: str
    method: str
    siid: int
    piid: int
    value: Any


def iter_probe_log(path: Union[str, Path]) -> Iterator[ProbeLogEvent]:
    """Yield ProbeLogEvent for each properties_changed message in a probe log."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "mqtt_message":
                continue
            if obj.get("method") != "properties_changed":
                continue
            for param in obj.get("params") or []:
                siid = param.get("siid")
                piid = param.get("piid")
                if siid is None or piid is None:
                    continue
                yield ProbeLogEvent(
                    timestamp=obj.get("timestamp", ""),
                    method=obj["method"],
                    siid=int(siid),
                    piid=int(piid),
                    value=param.get("value"),
                )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/protocol/test_replay.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/replay.py \
        tests/protocol/test_replay.py
git commit -m "feat(protocol): probe-log replay iterator"
```

---

### Task 12: End-to-end replay test — drive all decoders from a full session fixture

**Files:**
- Modify: `tests/protocol/test_replay.py`

**Background:** This is the integration test tying all five decoder modules together. It reads the trimmed probe-log fixture, routes each event to the correct decoder based on `(siid, piid)` via the `properties_g2408` map, and asserts sensible values throughout — no crashes, expected state transitions, area/distance monotonic when mowing, etc.

- [ ] **Step 1: Add failing end-to-end test**

Append to `tests/protocol/test_replay.py`:

```python
from custom_components.dreame_a2_mower.protocol.config_s2p51 import decode_s2p51
from custom_components.dreame_a2_mower.protocol.heartbeat import decode_s1p1
from custom_components.dreame_a2_mower.protocol.properties_g2408 import (
    Property,
    property_for,
)
from custom_components.dreame_a2_mower.protocol.telemetry import decode_s1p4


def test_replay_full_session_routes_to_correct_decoder_without_errors(
    fixtures_dir: Path,
):
    """Drive every event in the short session through the decoder pipeline.

    Expectations:
      - Every known (siid, piid) routes to a decoder that accepts the payload.
      - Battery values are monotonically non-decreasing during a charging window.
      - Heartbeat counter strictly increases between consecutive heartbeats.
      - No unhandled exception from any decoder.
    """
    batteries: list[int] = []
    heartbeat_counters: list[int] = []

    for ev in iter_probe_log(fixtures_dir / "session_short.jsonl"):
        prop = property_for(ev.siid, ev.piid)

        if prop is Property.BATTERY_LEVEL:
            assert isinstance(ev.value, int)
            batteries.append(ev.value)
        elif prop is Property.HEARTBEAT:
            hb = decode_s1p1(bytes(ev.value))
            heartbeat_counters.append(hb.counter)
        elif prop is Property.MOWING_TELEMETRY:
            # Telemetry only appears while mowing; the short fixture may not
            # include it, but if present it must decode without error.
            decode_s1p4(bytes(ev.value))
        elif prop is Property.MULTIPLEXED_CONFIG:
            decode_s2p51(ev.value)
        # unknown (siid, piid) — acceptable for now; Plan C will map more.

    # The short fixture covers a charging window — battery should be non-decreasing.
    assert batteries == sorted(batteries), (
        f"battery not non-decreasing in short fixture window: {batteries}"
    )
    # Heartbeat counter must strictly increase (monotonic invariant).
    assert heartbeat_counters == sorted(set(heartbeat_counters)), (
        f"heartbeat counters not strictly increasing: {heartbeat_counters}"
    )
    assert len(batteries) > 1, "expected multiple battery readings in short fixture"
    assert len(heartbeat_counters) > 1, (
        "expected multiple heartbeats in short fixture"
    )
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/protocol/test_replay.py -v
```

Expected: the new test passes because all decoders already work. If the `session_short.jsonl` slice (200 lines) does not contain multiple heartbeats or battery readings, regenerate with more lines:

```bash
head -n 400 /data/claude/homeassistant/probe_log_20260417_095500.jsonl \
  > tests/fixtures/session_short.jsonl
```

and re-run. Commit the regenerated fixture together with the test.

- [ ] **Step 3: Run the full suite one more time**

```bash
pytest -v
```

Expected: every test across `test_telemetry.py`, `test_heartbeat.py`, `test_properties_g2408.py`, `test_config_s2p51.py`, and `test_replay.py` passes. Record the total count for the commit message.

- [ ] **Step 4: Commit**

```bash
git add tests/protocol/test_replay.py tests/fixtures/session_short.jsonl
git commit -m "test(protocol): end-to-end replay asserts decoder pipeline on real session"
```

---

### Task 13: Expose public API through package `__init__.py` + tag alpha.3

**Files:**
- Modify: `custom_components/dreame_a2_mower/protocol/__init__.py`

- [ ] **Step 1: Expose decoder API through the package**

Replace the contents of `custom_components/dreame_a2_mower/protocol/__init__.py` with:

```python
"""Pure-Python MQTT protocol decoders for the Dreame A2 (g2408) mower."""

from __future__ import annotations

from .config_s2p51 import (
    S2P51DecodeError,
    S2P51Event,
    Setting,
    decode_s2p51,
    encode_s2p51,
)
from .heartbeat import Heartbeat, InvalidS1P1Frame, decode_s1p1
from .properties_g2408 import (
    PROPERTY_MAP,
    ChargingStatus,
    Property,
    StateCode,
    charging_label,
    property_for,
    siid_piid,
    state_label,
)
from .replay import ProbeLogEvent, iter_probe_log
from .telemetry import (
    InvalidS1P4Frame,
    MowingTelemetry,
    Phase,
    decode_s1p4,
)

__all__ = [
    "PROPERTY_MAP",
    "ChargingStatus",
    "Heartbeat",
    "InvalidS1P1Frame",
    "InvalidS1P4Frame",
    "MowingTelemetry",
    "Phase",
    "ProbeLogEvent",
    "Property",
    "S2P51DecodeError",
    "S2P51Event",
    "Setting",
    "StateCode",
    "charging_label",
    "decode_s1p1",
    "decode_s1p4",
    "decode_s2p51",
    "encode_s2p51",
    "iter_probe_log",
    "property_for",
    "siid_piid",
    "state_label",
]
```

- [ ] **Step 2: Verify public imports work**

```bash
python3 -c "from custom_components.dreame_a2_mower.protocol import decode_s1p4, decode_s2p51, iter_probe_log, Property; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Full test run**

```bash
pytest -v
```

Expected: every test passes.

- [ ] **Step 4: Push and tag alpha.3**

```bash
git add custom_components/dreame_a2_mower/protocol/__init__.py
git commit -m "feat(protocol): public API via package __init__"
git push origin main
git tag -a v2.0.0-alpha.3 -m "Plan B complete — pure-Python protocol decoders + replay harness"
git push origin v2.0.0-alpha.3
```

---

## Done-definition for Plan B

- `custom_components/dreame_a2_mower/protocol/` exists with `telemetry.py`, `heartbeat.py`, `config_s2p51.py`, `properties_g2408.py`, `replay.py`, and `__init__.py`.
- 100% of decoder unit tests and the end-to-end replay test pass via `pytest`.
- The replay test drives every event in `tests/fixtures/session_short.jsonl` through the pipeline without crashes and asserts invariants (non-decreasing battery, strictly-increasing heartbeat counter).
- Tag `v2.0.0-alpha.3` points to the commit that exposes the public API.

## What Plan B deliberately does NOT do

Deferred to Plan C — do not scope-creep:

- Touching `custom_components/dreame_a2_mower/dreame/` (upstream protocol package) — stays untouched until Plan C decides whether to replace or wrap it.
- Wiring the new decoders into the coordinator or entities.
- Adding new HA sensors/entities.
- Inverting the dispatcher to MQTT-first (Plan C).
- Fixing entity state-code mapping inside the running integration (Plan C).
- Supporting write commands (start/stop mowing, dock) — encode is ready, but the command-send path is Plan C.
- Updating README/docs to describe BT-only settings (Plan C, when user-facing entities make this relevant).
