"""LastKnown — offline last-known read-only snapshot (layer 3, Task 12a / P6.7).

A SEPARATE, self-contained value object holding the read-only device values the
integration should keep showing while the mower/cloud is offline (including
across an HA restart). It is deliberately NOT part of ``MowerState`` /
``StateSnapshot`` / any of the eight state containers: adding a field to those
would change ``MowerState.to_flat_dict()`` / ``FLAT_FIELDS`` /
``dataclasses.asdict(snapshot())`` and break the corpus-replay golden digest
(``tools/replay/corpus_replay.py``) even though decode semantics are unchanged.
So this lives here with its own ``to_dict`` / ``from_dict`` and is persisted via
its own ``homeassistant.helpers.storage.Store`` (see ``coordinator/_core.py``
``_restore_last_known`` / ``_save_last_known`` and ``domain/boot.py``).

Pure module: it imports nothing from coordinator/entities. ``from_state`` reads
the flat MowerState fields by name via ``getattr`` (duck-typed — no MowerState
import needed), so this stays a layer-3 leaf.

The ``12b`` follow-up (entity availability/staleness) consumes ``saved_unix``.
"""
from __future__ import annotations

from dataclasses import dataclass, fields as _dc_fields
from typing import Any

# Debounce window for the last-known Store write (seconds). Matches the
# device-messages store cadence — a refresh burst coalesces into one disk write.
LAST_KNOWN_SAVE_DELAY_S = 5

# MowerState flat field names this blob mirrors 1:1. These are read off
# ``coord.data`` at save time and seeded back onto it at restore time. Each name
# MUST be a real MowerState flat field (see ``state/containers.py``). The two
# meta fields (``active_map_id`` / ``saved_unix``) are NOT MowerState fields and
# are handled separately — they never seed MowerState.
_STATE_FIELDS: tuple[str, ...] = (
    # consumables + lifetime totals (MIHIS)
    "blades_life_pct",
    "cleaning_brush_life_pct",
    "robot_maintenance_life_pct",
    "total_mowed_area_m2",
    "total_mowing_time_min",
    "mowing_count",
    # 4G SIM
    "sim_card_id",
    "sim_left_days",
    "sim_active_time",
    "sim_expired_time",
    "sim_data_remaining_mb",
    "sim_out_of_warranty",
    # dock pose
    "dock_x_mm",
    "dock_y_mm",
    "dock_yaw",
    "dock_in_lawn_region",
    # firmware
    "firmware_version",
    # device-wide read-only time-window / protection settings (NOT per-map)
    "rain_protection_enabled",
    "rain_protection_resume_hours",
    "frost_protection_enabled",
    "dnd_enabled",
    "dnd_start_min",
    "dnd_end_min",
    "custom_charging_enabled",
    "charging_start_min",
    "charging_end_min",
    # WiFi identity
    "wifi_ssid",
    "wifi_ip",
)


@dataclass(frozen=True, slots=True)
class LastKnown:
    """Frozen last-known read-only values + active map + save timestamp."""

    # --- mirrored MowerState fields (keep in sync with _STATE_FIELDS) ---
    blades_life_pct: float | None = None
    cleaning_brush_life_pct: float | None = None
    robot_maintenance_life_pct: float | None = None
    total_mowed_area_m2: float | None = None
    total_mowing_time_min: int | None = None
    mowing_count: int | None = None
    sim_card_id: str | None = None
    sim_left_days: int | None = None
    sim_active_time: str | None = None
    sim_expired_time: str | None = None
    sim_data_remaining_mb: float | None = None
    sim_out_of_warranty: bool | None = None
    dock_x_mm: int | None = None
    dock_y_mm: int | None = None
    dock_yaw: int | None = None
    dock_in_lawn_region: bool | None = None
    firmware_version: str | None = None
    rain_protection_enabled: bool | None = None
    rain_protection_resume_hours: int | None = None
    frost_protection_enabled: bool | None = None
    dnd_enabled: bool | None = None
    dnd_start_min: int | None = None
    dnd_end_min: int | None = None
    custom_charging_enabled: bool | None = None
    charging_start_min: int | None = None
    charging_end_min: int | None = None
    wifi_ssid: str | None = None
    wifi_ip: str | None = None
    # --- meta (not MowerState fields) ---
    active_map_id: int | None = None
    saved_unix: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-native dict for the Store (all values scalar or None)."""
        return {f.name: getattr(self, f.name) for f in _dc_fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "LastKnown":
        """Build from a stored dict, tolerating missing/extra keys (compat).

        Missing keys default to ``None``; unknown keys are ignored so a blob
        written by a newer/older version restores cleanly.
        """
        data = data or {}
        names = {f.name for f in _dc_fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    @classmethod
    def from_state(
        cls, state: Any, active_map_id: int | None, saved_unix: float | None
    ) -> "LastKnown":
        """Snapshot the mirrored fields off a MowerState (duck-typed)."""
        kw: dict[str, Any] = {n: getattr(state, n, None) for n in _STATE_FIELDS}
        kw["active_map_id"] = active_map_id
        kw["saved_unix"] = saved_unix
        return cls(**kw)

    def non_none_state_updates(self) -> dict[str, Any]:
        """The mirrored fields that are set, as ``MowerState.with_updates`` kwargs.

        Excludes the meta fields (``active_map_id`` / ``saved_unix``) and any
        field still ``None`` — so a restore never clobbers a real value with a
        blank and never passes a non-MowerState key into ``with_updates``.
        """
        out: dict[str, Any] = {}
        for name in _STATE_FIELDS:
            val = getattr(self, name)
            if val is not None:
                out[name] = val
        return out
