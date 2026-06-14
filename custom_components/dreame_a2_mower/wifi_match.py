"""Re-export shim — WiFi fingerprint matcher relocated to ``wifi/match.py``.

Packaged under ``wifi/`` (Phase 3c, 2026-06-14). Preserves the old import path;
new code should import from ``.wifi.match`` directly.
"""
from __future__ import annotations

from .wifi.match import (  # noqa: F401
    MatchScore,
    NO_DATA_SENTINEL,
    WifiSample,
    match_heatmap_to_session,
    score_candidates,
)

__all__ = [
    "MatchScore",
    "NO_DATA_SENTINEL",
    "WifiSample",
    "match_heatmap_to_session",
    "score_candidates",
]
