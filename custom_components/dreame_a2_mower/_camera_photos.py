"""Re-export shim — photo/video camera entities relocated to ``camera/photos.py``.

Packaged under ``camera/`` (Phase 3c, 2026-06-14). Preserves the old import
path; new code should import from ``.camera.photos`` directly.
"""
from __future__ import annotations

from .camera.photos import (  # noqa: F401
    DreameA2AlbumPhotoCamera,
    DreameA2LatestVideoThumbCamera,
    DreameA2PersonPhotoCamera,
    _photo_detection_attrs,
)

__all__ = [
    "DreameA2AlbumPhotoCamera",
    "DreameA2LatestVideoThumbCamera",
    "DreameA2PersonPhotoCamera",
    "_photo_detection_attrs",
]
