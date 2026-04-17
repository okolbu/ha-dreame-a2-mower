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
