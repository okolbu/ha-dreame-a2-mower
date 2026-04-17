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
