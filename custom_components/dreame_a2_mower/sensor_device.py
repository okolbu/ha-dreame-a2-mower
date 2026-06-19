"""Re-export shim — device-sensor entities relocated to
``entities/sensor/device.py``.

The entity layer was packaged under ``entities/`` (Phase 3c, 2026-06-14). This
re-export preserves the old import path (``from .sensor_device import …`` and
``from . import sensor_device``) for the deep test imports. New code should
import from ``.entities.sensor.device`` directly.

Explicit re-export of the underscore helpers (``_active_fault_text``,
``_error_attrs``, ``_mpos_value``, ``_mpos_attrs``): ``import *`` would not
carry them, and the test suite imports them by name.
"""
from __future__ import annotations

from .entities.sensor.device import *  # noqa: F401,F403
from .entities.sensor.device import (  # noqa: F401
    _active_fault_text,
    _error_attrs,
    _mpos_attrs,
    _mpos_value,
    _obstacle_marker_value,
)
