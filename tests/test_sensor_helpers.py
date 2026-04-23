"""Unit tests for sensor.py's CFG helper functions (_format_time_window,
_wear_health). These helpers are module-level pure functions, so they
can be tested without a HA harness by importing directly."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_sensor_module():
    """Load sensor.py in isolation. Avoids the HA-dependent import chain
    that the rest of the module triggers at top-level."""
    # sensor.py pulls in homeassistant at import time; work around that
    # by loading only the helper definitions via exec on a sliced source.
    src = Path(
        "custom_components/dreame_a2_mower/sensor.py"
    ).read_text()
    current = []
    capture = False
    for line in src.splitlines():
        if line.startswith("def _format_time_window"):
            capture = True
        if capture:
            # Stop at any import or class/tuple declaration that
            # isn't part of our two helpers. Our two helpers are
            # consecutive top-level defs with no imports between them.
            if line.startswith("from ") or line.startswith("import ") \
                    or line.startswith("SENSORS") or line.startswith("class ") \
                    or line.startswith("@"):
                break
            current.append(line)
    ns: dict = {}
    exec("\n".join(current), ns)
    return ns


_H = _load_sensor_module()


def test_format_time_window_happy_path():
    # 8:00 (480 min) to 18:30 (1110 min)
    assert _H["_format_time_window"]([0, 480, 1110, 0, 0, 0, 0]) == "08:00-18:30"


def test_format_time_window_none_on_short_list():
    assert _H["_format_time_window"]([0, 480]) is None


def test_format_time_window_none_on_non_list():
    assert _H["_format_time_window"](None) is None
    assert _H["_format_time_window"]("not a list") is None


def test_format_time_window_none_on_non_int_values():
    assert _H["_format_time_window"]([0, "480", 1110]) is None


def test_wear_health_full_life():
    # 0 minutes used → 100% remaining
    assert _H["_wear_health"]([0, 0, 0], 0, 6000) == 100


def test_wear_health_half_life():
    # 3000 / 6000 → 50% remaining
    assert _H["_wear_health"]([3000, 0, 0], 0, 6000) == 50


def test_wear_health_clamps_to_zero():
    # Over-the-max minutes shouldn't go negative
    assert _H["_wear_health"]([10000, 0, 0], 0, 6000) == 0


def test_wear_health_none_on_bad_input():
    assert _H["_wear_health"](None, 0, 6000) is None
    assert _H["_wear_health"]([0, 0], 5, 6000) is None  # idx out of range
    assert _H["_wear_health"]([None, 0, 0], 0, 6000) is None
