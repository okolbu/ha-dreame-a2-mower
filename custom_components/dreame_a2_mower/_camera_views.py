"""Re-export shim — camera HTTP views relocated to ``camera/views.py``.

Packaged under ``camera/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.camera.views`` directly.
"""
from __future__ import annotations

from .camera.views import (  # noqa: F401
    LidarPcdDownloadView,
    LidarSelectedPcdView,
    MapImageView,
    PhotoFileView,
    VideoFileView,
    VideoThumbView,
    WorkLogImageView,
)

__all__ = [
    "LidarPcdDownloadView",
    "LidarSelectedPcdView",
    "MapImageView",
    "PhotoFileView",
    "VideoFileView",
    "VideoThumbView",
    "WorkLogImageView",
]
