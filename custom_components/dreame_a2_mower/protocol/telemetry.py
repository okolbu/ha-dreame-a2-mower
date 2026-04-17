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
