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
    # Phase-byte semantics learned from live observation — note earlier RE
    # notes labelled 0 as "edge_or_reposition" and 2 as "active mowing", but
    # a g2408 doing a plain straight-pass mow was observed at byte value 0
    # during active cutting, so 0 is the main mow phase. Value 2 has not
    # been confirmed in isolation; kept as PHASE_2 until verified.
    MOWING = 0
    TRANSIT = 1
    PHASE_2 = 2
    RETURNING = 3
    UNKNOWN = -1


@dataclass(frozen=True)
class MowingTelemetry:
    """Decoded s1p4 frame.

    Position is charger-relative millimetres, fixed to map cardinal
    directions (no per-session rotation). Verified on a 378m² lawn —
    values like Y=5855 correspond to 5.85m from the charger, which
    matches live observations. An earlier attempt interpreted these as
    centimetres but that contradicted the growth rate across passes.

    x_mm / y_mm are the raw integer fields; x_m / y_m are derived
    metre-scale properties for display convenience.
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

    @property
    def x_m(self) -> float:
        """X position in metres (charger-relative)."""
        return self.x_mm / 1000.0

    @property
    def y_m(self) -> float:
        """Y position in metres (charger-relative)."""
        return self.y_mm / 1000.0


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
