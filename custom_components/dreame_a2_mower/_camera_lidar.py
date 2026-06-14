"""Re-export shim — LiDAR camera entities relocated to ``camera/lidar.py``.

Packaged under ``camera/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.camera.lidar`` directly.
"""
from __future__ import annotations

from .camera.lidar import (  # noqa: F401
    DreameA2LidarSelectedCamera,
    DreameA2LidarTopDownCamera,
    DreameA2LidarTopDownFullCamera,
)

__all__ = [
    "DreameA2LidarSelectedCamera",
    "DreameA2LidarTopDownCamera",
    "DreameA2LidarTopDownFullCamera",
]
