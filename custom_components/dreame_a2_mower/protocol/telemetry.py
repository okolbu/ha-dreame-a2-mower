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
    MOWING = 0
    TRANSIT = 1
    PHASE_2 = 2
    RETURNING = 3
    ZONE_4 = 4
    ZONE_5 = 5
    ZONE_6 = 6
    ZONE_7 = 7
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
    phase_raw = data[8]
    phase = Phase(phase_raw) if phase_raw in Phase._value2member_map_ else Phase.UNKNOWN
    distance_deci = struct.unpack_from("<H", data, 24)[0]
    total_area_cent = struct.unpack_from("<H", data, 26)[0]
    area_mowed_cent = struct.unpack_from("<H", data, 29)[0]
    return MowingTelemetry(
        x_cm=x_cm,
        y_mm=y_mm,
        sequence=seq,
        phase=phase,
        phase_raw=phase_raw,
        distance_m=distance_deci / 10.0,
        total_area_m2=total_area_cent / 100.0,
        area_mowed_m2=area_mowed_cent / 100.0,
    )
