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
