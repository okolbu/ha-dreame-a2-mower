"""Multi-map fan-out + batch-join helpers for the cloud map decoder."""

from __future__ import annotations

import json
import logging
from typing import Any

from .parse import parse_cloud_map
from .types import MapData

_LOGGER = logging.getLogger(__name__)


def parse_cloud_maps(by_id: dict[int, dict[str, Any]]) -> dict[int, MapData]:
    """Parse a multi-map cloud response into MapData entries by map_id.

    ``by_id`` is the splitter output from ``cloud_client.fetch_map`` —
    a dict keyed by map index, where each value is the raw cloud
    response dict for that map.

    Entries that fail :func:`parse_cloud_map` are silently dropped; partial
    results beat raising on a single bad map.
    """
    result: dict[int, MapData] = {}
    for map_id, raw in by_id.items():
        if not isinstance(raw, dict):
            continue
        decoded = parse_cloud_map(raw)
        if decoded is None:
            continue
        result[int(map_id)] = decoded
    return result


# ---------------------------------------------------------------------------
# Batch-join helper
# ---------------------------------------------------------------------------


def join_map_parts(batch_response: dict[str, Any], *, prefix: str = "MAP") -> dict[str, Any] | None:
    """Join the 28 cloud batch keys (``MAP.0`` … ``MAP.27``) and JSON-decode.

    Handles the wrapped-list form ``[json_string, ...]`` that some firmware
    versions emit.  Returns ``None`` when no valid map dict can be extracted.

    This is the outer shell around :func:`parse_cloud_map`; the coordinator
    calls ``parse_cloud_map(join_map_parts(batch))`` to obtain a
    :class:`MapData`.
    """
    if not batch_response:
        return None

    # 128 chunks: wide enough for any plausible future expansion; cloud returns
    # empty strings for keys it doesn't have, so over-requesting is cheap.
    parts = [batch_response.get(f"{prefix}.{i}", "") or "" for i in range(128)]
    raw = "".join(parts)
    if not raw:
        return None

    try:
        decoder = json.JSONDecoder()
        parsed, _ = decoder.raw_decode(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        _LOGGER.debug("join_map_parts: JSON decode failed: %s", exc)
        return None

    if isinstance(parsed, list):
        # Wrapped form: try each element.
        for item in parsed:
            if isinstance(item, str):
                try:
                    candidate = json.loads(item)
                    if isinstance(candidate, dict) and (
                        "boundary" in candidate or "mowingAreas" in candidate
                    ):
                        return candidate
                except (json.JSONDecodeError, ValueError):
                    continue
            elif isinstance(item, dict) and (
                "boundary" in item or "mowingAreas" in item
            ):
                return item
        _LOGGER.debug("join_map_parts: list form but no usable map entry")
        return None

    if isinstance(parsed, dict):
        return parsed

    return None
