"""SETTINGS.* batch decoder + read-modify-write helper.

Structure (g2408, re-derived 2026-06-19 from a live 2-map device —
``[probe:settings_dump@2026-06-19]``):

    [
      # raw[0] = MAP 0
      {"mode": 0, "settings": {"0": {<general/map-level>}, "1": {<zone1>}}},
      # raw[1] = MAP 1
      {"mode": 0, "settings": {"0": {<general>}, "1": {<zone1>}, "2": {<zone2>}}},
    ]

**The top-level index IS the map index**, and within each map the inner
``settings`` dict is keyed by ZONE index, where ``"0"`` is the map's
**general (map-level)** settings — the slot that direction / height /
AI / obstacle etc. read and write (those fields are per-map). Inner
``"1"+`` are per-zone slots: present on multi-zone maps (their count is
``#zones``), currently default/unused for the per-map fields. So a map
with N zones has ``1 + N`` inner keys.

``by_map_id_canonical`` maps ``map_index -> that map's general ("0")
settings dict``.

**Supersedes** the earlier "entry 0 = user-saved / entry 1 =
firmware-applied mirror, inner key = map id" reading (2026-05-09). That
held on a single-map device where the lone map's two-entry shape looked
like user-vs-mirror; on a 2-map device it is decisively wrong — entry 1's
``"0"`` carries map 2's OWN value (e.g. 118), not a stale mirror of map 1's
(26), and the inner-key counts differ per map (2 vs 3) = ``1 + #zones``.
Archived to ``OLD/.../inventory-history/cfg_individual.md``.

Cloud-side propagation note: writes via setDeviceData take ~5 minutes
to be reflected in a follow-up `get_batch_device_datas` read. The
integration's polling cadence should account for that lag.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SettingsRoot:
    """Per-map mowing-behaviour settings.

    Preserves the dual-level structure observed on g2408 fw 4.3.6_0550
    (two top-level entries, both `mode: 0`, each keyed by the same map
    ids but holding DIFFERENT values). Roles confirmed 2026-05-09 via
    controlled diffs of a cloud `getDeviceData` batch around app saves:
    entry 0 holds user-saved settings (what the app and HA both read
    and write; `version` increments on each save), entry 1 is a
    firmware-applied mirror that lags arbitrarily and stays at
    `version: 0` until the device pushes its applied state back.

    `by_map_id_canonical` reflects entry 0; writes propagate to every
    entry to keep them mutually consistent until the firmware updates
    entry 1 on its own schedule.

    Moved here from root `cloud_state.py` (R-29a/T2-4): this is the
    decoder's own output type, not a state-layer container. `cloud_state.py`
    re-exports it for the existing importers.
    """

    raw: list[dict[str, Any]]
    by_map_id_canonical: dict[int, dict[str, Any]]


def parse_settings_batch(raw: list[dict[str, Any]]) -> SettingsRoot:
    """Parse a SETTINGS.* JSON-decoded payload into a SettingsRoot.

    Top-level index = map index; each map's general (map-level) settings
    live in its inner ``"0"`` (zone-0) slot. ``by_map_id_canonical`` maps
    ``map_index -> raw[map_index].settings["0"]`` (see module docstring for
    the full structure + the 2026-06-19 supersession).
    """
    by_map_id_canonical: dict[int, dict[str, Any]] = {}
    if isinstance(raw, list):
        for map_idx, entry in enumerate(raw):
            if not isinstance(entry, dict):
                continue
            settings_dict = entry.get("settings")
            if not isinstance(settings_dict, dict):
                continue
            general = settings_dict.get("0")
            if isinstance(general, dict):
                by_map_id_canonical[map_idx] = general
    return SettingsRoot(
        raw=raw if isinstance(raw, list) else [],
        by_map_id_canonical=by_map_id_canonical,
    )


def write_setting(
    raw: list[dict[str, Any]],
    *,
    map_id: int,
    field: str,
    value: Any,
) -> list[dict[str, Any]]:
    """Read-modify-write: set `field` on map `map_id`'s general settings
    slot — ``raw[map_id].settings["0"]``. Input is NOT mutated; returns a
    new list.

    Under the map-indexed model (2026-06-19, see module docstring) each
    top-level entry IS a distinct map, so we write ONLY that map's general
    ("0") slot. The pre-2026-06-19 behaviour wrote the field into every
    top-level entry's same-key sub-dict — which, now that the top level is
    per-map, would clobber OTHER maps' settings.

    Raises KeyError if `map_id` has no top-level entry, or that entry has no
    general ("0") settings slot.
    """
    new_raw = copy.deepcopy(raw)
    if not new_raw:
        raise KeyError(f"SETTINGS list empty; cannot set {field}")
    if not isinstance(map_id, int) or map_id < 0 or map_id >= len(new_raw):
        raise KeyError(str(map_id))
    entry = new_raw[map_id]
    sd = entry.get("settings") if isinstance(entry, dict) else None
    general = sd.get("0") if isinstance(sd, dict) else None
    if not isinstance(general, dict):
        raise KeyError(f"map {map_id} has no general ('0') settings slot")
    general[field] = value
    return new_raw
