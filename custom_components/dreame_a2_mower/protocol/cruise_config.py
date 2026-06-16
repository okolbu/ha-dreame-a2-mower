"""Parse the CRUISE.0 device-data key into per-map per-point patrol config.

CRUISE.0 (sibling of MAP.* in the getDeviceData response) is a JSON-string
per-map outer array:
  [{version, settings:{<point_id>:{num:<cycles>, ap:<auto_capture bool>}}}, …]
element[i] = map index i; an unused map carries {version:-1, settings:{}}.
There is NO m:g getter on t:CRUISED (returns r=-3) — CRUISE.0 is the only read
path. See inventory.yaml § CRUISED. WRITE is the CRUISED CFG key.
"""
from __future__ import annotations

import json
from typing import Any

from ..const import LOGGER


def parse_cruise_config(raw: Any) -> dict[int, dict[int, dict[str, Any]]]:
    """Return ``{map_idx: {point_id: {"cycles": int, "auto_capture": bool}}}``.

    Tolerant: never raises. Non-JSON / wrong shape → ``{}``; ``version:-1`` or
    empty ``settings`` contribute nothing; entries missing ``num`` are skipped;
    non-integer settings keys (the un-disambiguated ``"1,0"`` comma-key) are
    skipped + debug-logged.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    if not isinstance(raw, list):
        return {}
    out: dict[int, dict[int, dict[str, Any]]] = {}
    for map_idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        settings = entry.get("settings")
        if not isinstance(settings, dict):
            continue
        per_point: dict[int, dict[str, Any]] = {}
        for key, val in settings.items():
            try:
                pid = int(key)
            except (TypeError, ValueError):
                LOGGER.debug("parse_cruise_config: skipping non-int point key %r", key)
                continue
            if not isinstance(val, dict) or "num" not in val:
                continue
            try:
                cycles = int(val["num"])
            except (TypeError, ValueError):
                continue
            per_point[pid] = {"cycles": cycles, "auto_capture": bool(val.get("ap"))}
        if per_point:
            out[map_idx] = per_point
    return out
