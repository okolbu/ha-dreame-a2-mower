"""s1p4 mowing telemetry decoder for Dreame A2 (g2408)."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

FRAME_LENGTH = 33
FRAME_LENGTH_BEACON = 8
FRAME_LENGTH_BUILDING = 10
FRAME_DELIMITER = 0xCE


class InvalidS1P4Frame(ValueError):
    """Raised when an s1p4 frame does not match the expected shape."""


class Phase(IntEnum):
    # Byte [8] of the s1p4 frame is the mower firmware's **task-phase index**:
    # the current position in the pre-planned sub-task list for this mowing
    # job. Values advance monotonically (never revisited) and carry meaning
    # bound to the task plan itself (per-zone area-fills, then edges, …).
    # The labels below are historical placeholders from earlier incorrect
    # interpretations; keep them around only so existing references compile.
    # New code should read `phase_raw` directly. See
    # docs/research/g2408-protocol.md §"Phase byte semantics".
    #
    # Observed maximum so far: 15 (lawn with four zones + multi-pass edges).
    # Lawns with more zones or more-segmented plans will hit higher values;
    # extend this range if needed. `phase_raw` is always preserved on the
    # MowingTelemetry dataclass even when the value is outside this range.
    MOWING = 0
    TRANSIT = 1
    PHASE_2 = 2
    RETURNING = 3
    ZONE_4 = 4
    ZONE_5 = 5
    ZONE_6 = 6
    ZONE_7 = 7
    ZONE_8 = 8
    ZONE_9 = 9
    ZONE_10 = 10
    ZONE_11 = 11
    ZONE_12 = 12
    ZONE_13 = 13
    ZONE_14 = 14
    ZONE_15 = 15
    UNKNOWN = -1


@dataclass(frozen=True)
class MowingTelemetry:
    """Decoded s1p4 frame.

    Position is charger-relative, fixed to map cardinal directions
    (no per-session rotation). **X and Y use different raw scales:**
    X is centimetres, Y is millimetres. Verified live: max observed
    X=900 → 9 m matches physical 9 m; Y=6976 at the same moment is
    6.98 m (not 69.76 m — confirmed by lawn dimensions ≤ 25 m).

    Consumers should prefer the `x_m` / `y_m` metre properties to avoid
    the unit asymmetry. Distance and area counters reset at the start
    of each mowing session.
    """

    x_cm: int
    y_mm: int
    sequence: int
    phase: Phase
    phase_raw: int
    distance_m: float
    total_area_m2: float
    area_mowed_m2: float
    heading_deg: float
    # Task struct from frame bytes [22-31] per apk parseRobotTask.
    # On g2408 these fields may overlap with our current
    # distance_deci / total_area_cent / area_mowed_cent reads —
    # both interpretations are computed in decode_s1p4 and the
    # caller can pick whichever the field-validation effort
    # (Task 4) blesses.
    region_id: int
    task_id: int
    percent: float       # 0..100 mowing progress
    total_uint24_m2: float
    finish_uint24_m2: float

    @property
    def x_m(self) -> float:
        """X position in metres (charger-relative)."""
        return self.x_cm / 100.0

    @property
    def y_m(self) -> float:
        """Y position in metres (charger-relative)."""
        return self.y_mm / 1000.0


@dataclass(frozen=True)
class PositionBeacon:
    """Minimal 8-byte s1p4 beacon emitted while the mower is idle/docked
    or under remote control. Only X/Y are included — phase, session counters,
    and area/distance are not transmitted in this variant.
    """

    x_cm: int
    y_mm: int

    @property
    def x_m(self) -> float:
        return self.x_cm / 100.0

    @property
    def y_m(self) -> float:
        return self.y_mm / 1000.0


def _read_uint24_le(buf: bytes, offset: int) -> int:
    """Read a little-endian unsigned 24-bit integer from `buf` at `offset`."""
    return buf[offset] | (buf[offset + 1] << 8) | (buf[offset + 2] << 16)


def decode_s1p4_position(data: bytes) -> PositionBeacon:
    """Extract X/Y from an 8-byte beacon, a 10-byte BUILDING variant,
    or a 33-byte full frame.

    Use this when the caller only needs the current position (e.g. live
    map overlay). For phase, session, area, or distance, call decode_s1p4
    instead — it only accepts the 33-byte form.

    10-byte variants appear while the mower is in BUILDING state (map-learn /
    zone-expand). They carry the same X/Y at the same offsets as the beacon
    plus two additional bytes at offsets [6-7] (purpose not yet decoded).
    """
    if len(data) not in (FRAME_LENGTH_BEACON, FRAME_LENGTH_BUILDING, FRAME_LENGTH):
        raise InvalidS1P4Frame(
            f"expected frame length {FRAME_LENGTH_BEACON}, "
            f"{FRAME_LENGTH_BUILDING}, or {FRAME_LENGTH}, "
            f"got {len(data)}"
        )
    if data[0] != FRAME_DELIMITER or data[-1] != FRAME_DELIMITER:
        raise InvalidS1P4Frame(
            f"expected 0x{FRAME_DELIMITER:02X} delimiters at first and last byte"
        )
    x_cm, y_mm = struct.unpack_from("<hh", data, 1)
    return PositionBeacon(x_cm=x_cm, y_mm=y_mm)


def decode_s1p4(data: bytes) -> MowingTelemetry:
    if len(data) != FRAME_LENGTH:
        raise InvalidS1P4Frame(
            f"expected frame length {FRAME_LENGTH}, got {len(data)}"
        )
    if data[0] != FRAME_DELIMITER or data[-1] != FRAME_DELIMITER:
        raise InvalidS1P4Frame(
            f"expected 0x{FRAME_DELIMITER:02X} delimiters at [0] and [32]"
        )
    x_cm, y_mm = struct.unpack_from("<hh", data, 1)
    seq = struct.unpack_from("<H", data, 6)[0]
    # Heading angle (0..255 → 0..360°) per apk parseRobotPose. The apk places
    # the angle byte immediately after the pose bytes; on g2408, the pose is
    # int16_le at bytes [1-4] (see Task 1 analysis), so the apk's semantic
    # "next byte after pose" falls at byte [6] — NOT byte [5]. Empirical
    # evidence: during a westward dock-departure run (5 frames, fixtures/
    # captured_s1p4_frames.json) byte[5] is constantly 0xFF while byte[6]
    # varies 125-128 — consistent with a real heading around 176-181°
    # ("facing west"), whereas byte[5]=0xFF would decode to a constant 360°.
    #
    # Note: bytes [6-7] overlap with the `sequence` little-endian uint16 read
    # above. Whichever interpretation is correct, they can't both be — but
    # refactoring `sequence` is out of scope for this change. Task 2 just
    # exposes the heading byte; a rotating-mower capture is still needed for
    # final verification of the byte position and the 0..255 → 0..360 scale.
    heading_byte = data[6]
    heading_deg = (heading_byte / 255.0) * 360.0
    phase_raw = data[8]
    phase = Phase(phase_raw) if phase_raw in Phase._value2member_map_ else Phase.UNKNOWN
    distance_deci = struct.unpack_from("<H", data, 24)[0]
    total_area_cent = struct.unpack_from("<H", data, 26)[0]
    area_mowed_cent = struct.unpack_from("<H", data, 29)[0]
    # apk parseRobotTask: payload bytes [22-31] of the frame.
    # Interpreted as a 10-byte sub-struct starting at frame[22]:
    #   [22] regionId (uint8)
    #   [23] taskId (uint8)
    #   [24-25] percent ÷ 100 → %
    #   [26-28] total m² × 100 (uint24_le)
    #   [29-31] finish m² × 100 (uint24_le)
    # NOTE: bytes [24-25] overlap with `distance_deci` above, and bytes
    # [26-27] / [29-30] overlap with `total_area_cent` / `area_mowed_cent`.
    # The legacy reads are LEFT IN PLACE; both interpretations are exposed
    # so downstream code can pick whichever the field-validation effort
    # (Task 4) blesses. Lawns > 655 m² truncate under the uint16 reads but
    # survive under the uint24 reads.
    region_id = data[22]
    task_id = data[23]
    percent_raw = struct.unpack_from("<H", data, 24)[0]
    percent = percent_raw / 100.0
    total_u24_cent = _read_uint24_le(data, 26)
    finish_u24_cent = _read_uint24_le(data, 29)
    return MowingTelemetry(
        x_cm=x_cm,
        y_mm=y_mm,
        sequence=seq,
        phase=phase,
        phase_raw=phase_raw,
        distance_m=distance_deci / 10.0,
        total_area_m2=total_area_cent / 100.0,
        area_mowed_m2=area_mowed_cent / 100.0,
        heading_deg=heading_deg,
        region_id=region_id,
        task_id=task_id,
        percent=percent,
        total_uint24_m2=total_u24_cent / 100.0,
        finish_uint24_m2=finish_u24_cent / 100.0,
    )
