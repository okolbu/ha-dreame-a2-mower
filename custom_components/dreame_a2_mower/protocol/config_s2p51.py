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
