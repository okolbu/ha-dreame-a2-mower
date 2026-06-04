"""Single source of truth for control-honesty: which control entities reach
the g2408 firmware and which are read-only-until-a-write-path-is-found.

Pure Python (NO homeassistant import) so the CI sync test can load it in the
vanilla stubbed-HA venv. The mixin lives here too but only references HA via
duck-typing at call time, never at import.

CONTROL_MODES is keyed by the SAME entity-id templates as entity-inventory.yaml
rows (`<platform>.dreame_a2_mower_<leaf>`), with two generic <key> rows carrying
a per-leaf sub-map. Keep both in sync — tests/inventory/test_control_mode_code_sync
enforces it. See docs/research/control-honesty-audit-2026-06-03.md.
"""
from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any


class ControlMode(StrEnum):
    DEVICE_WRITABLE = "device_writable"
    DEVICE_WRITE_UNPROVEN = "device_write_unproven"
    INTEGRATION_LOCAL = "integration_local"
    READ_ONLY_PENDING = "read_only_pending"
    READ_ONLY_CONFIRMED = "read_only_confirmed"
    READ_ONLY_NOOP = "read_only_noop"


READ_ONLY_MODES = frozenset({
    ControlMode.READ_ONLY_PENDING,
    ControlMode.READ_ONLY_CONFIRMED,
    ControlMode.READ_ONLY_NOOP,
})

_W = ControlMode.DEVICE_WRITABLE
_U = ControlMode.DEVICE_WRITE_UNPROVEN
_L = ControlMode.INTEGRATION_LOCAL
_P = ControlMode.READ_ONLY_PENDING
_C = ControlMode.READ_ONLY_CONFIRMED
_N = ControlMode.READ_ONLY_NOOP

CONTROL_MODES: dict[str, ControlMode | dict[str, ControlMode]] = {
    # number
    "number.dreame_a2_mower_human_presence_alert_sensitivity": _N,
    "number.dreame_a2_mower_trail_render_width": _L,
    "number.dreame_a2_mower_station_bearing_deg": _L,
    "number.dreame_a2_mower_map_N_settings_mowing_height": _C,
    "number.dreame_a2_mower_map_N_settings_cutter_position": _C,
    "number.dreame_a2_mower_map_N_settings_cutter_position_height": _C,
    "number.dreame_a2_mower_map_N_settings_edge_mowing_num": _C,
    "number.dreame_a2_mower_map_N_settings_obstacle_avoidance_height": _C,
    "number.dreame_a2_mower_map_N_settings_obstacle_avoidance_distance": _C,
    "number.dreame_a2_mower_map_N_settings_obstacle_avoidance_sensitivity": _C,
    "number.dreame_a2_mower_<key>": {
        "volume": _W,
        "auto_recharge_battery_pct": _C,
        "resume_battery_pct": _C,
    },
    # select
    "select.dreame_a2_mower_navigation_path": _W,
    "select.dreame_a2_mower_rain_protection_resume_hours": _P,
    "select.dreame_a2_mower_lcd_language": _P,
    "select.dreame_a2_mower_voice_language": _P,
    "select.dreame_a2_mower_work_log": _L,
    "select.dreame_a2_mower_lidar_archive": _L,
    "select.dreame_a2_mower_active_map": _U,
    "select.dreame_a2_mower_action_mode": _L,
    "select.dreame_a2_mower_wifi_archive": _L,
    "select.dreame_a2_mower_map_N_edge_target": _L,
    "select.dreame_a2_mower_map_N_mowing_mode": _L,
    "select.dreame_a2_mower_map_N_settings_mowing_direction": _C,
    "select.dreame_a2_mower_map_N_settings_mowing_direction_mode": _C,
    "select.dreame_a2_mower_map_N_edge_walk_mode": _C,
    "select.dreame_a2_mower_map_N_maintenance_point": _L,
    "select.dreame_a2_mower_map_N_mowing_efficiency": _N,
    "select.dreame_a2_mower_map_N_zone_target": _L,
    "select.dreame_a2_mower_map_N_spot_target": _L,
    # switch
    "switch.dreame_a2_mower_map_N_edgemaster": _N,
    "switch.dreame_a2_mower_map_N_automatic_edge_mowing": _C,
    "switch.dreame_a2_mower_map_N_safe_edge_mowing": _C,
    "switch.dreame_a2_mower_map_N_obstacle_avoidance_on_edges": _C,
    "switch.dreame_a2_mower_map_N_lidar_obstacle_recognition": _C,
    "switch.dreame_a2_mower_cloud_state_ai_human_enabled": _P,
    "switch.dreame_a2_mower_map_N_ai_recognition_humans": _C,
    "switch.dreame_a2_mower_map_N_ai_recognition_animals": _C,
    "switch.dreame_a2_mower_map_N_ai_recognition_objects": _C,
    "switch.dreame_a2_mower_<key>": {
        "child_lock": _W, "anti_theft_lift_alarm": _W, "anti_theft_offmap_alarm": _W,
        "anti_theft_realtime_location": _W, "frost_protection": _W, "auto_recharge_standby": _W,
        "ai_obstacle_photos": _W, "msg_alert_anomaly": _W, "msg_alert_error": _W,
        "msg_alert_task": _W, "msg_alert_consumables": _W, "voice_regular_notification": _W,
        "voice_work_status": _W, "voice_special_status": _W, "voice_error_status": _W,
        "dnd": _C, "low_speed_at_night": _C, "custom_charging_period": _C,
        "rain_protection": _P,
        "led_period": _N, "led_in_standby": _N, "led_in_working": _N,
        "led_in_charging": _N, "led_in_error": _N, "human_presence_alert": _N,
    },
    # time
    "time.dreame_a2_mower_<key>": _N,
    # lawn_mower / button (dict-only; no entity wiring)
    "lawn_mower.dreame_a2_mower": _W,
    "button.dreame_a2_mower_map_N_head_to_point": _W,
    "button.dreame_a2_mower_refresh_cloud_state": _L,
    "button.dreame_a2_mower_refresh_wifi_heatmaps": _L,
    "button.dreame_a2_mower_finalize_session": _L,
    "button.dreame_a2_mower_start_mowing": _W,
    "button.dreame_a2_mower_pause_mowing": _U,
    "button.dreame_a2_mower_stop_mowing": _U,
    "button.dreame_a2_mower_recharge": _U,
    "button.dreame_a2_mower_find_bot": _W,
    "button.dreame_a2_mower_lock_bot": _U,
    "button.dreame_a2_mower_generate_3dmap": _U,
}


_LOGGER = logging.getLogger(__name__)
_PADLOCK_ICON = "mdi:lock-outline"


class _ControlHonestyMixin:
    """Adds the honesty verdict to a control entity.

    Subclasses MUST set ``self._control_mode`` (a ControlMode) in __init__,
    typically via ``resolve_control_mode(...)``. When the mode is read-only the
    mixin shows a padlock, marks the entity via extra-state-attributes, and the
    write handler is expected to call ``_reject_readonly_write`` instead of
    writing. Operable modes are pass-through.
    """

    _control_mode: ControlMode = ControlMode.INTEGRATION_LOCAL

    @property
    def control_mode(self) -> ControlMode:
        return self._control_mode

    @property
    def read_only(self) -> bool:
        return self._control_mode in READ_ONLY_MODES

    @property
    def icon(self) -> str | None:
        if self.read_only:
            return _PADLOCK_ICON
        attr = getattr(self, "_attr_icon", None)
        if attr is not None:
            return attr
        desc = getattr(self, "entity_description", None)
        return getattr(desc, "icon", None) if desc is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        base: dict[str, Any] = {}
        parent = super()
        parent_attrs = getattr(parent, "extra_state_attributes", None)
        if isinstance(parent_attrs, dict):
            base.update(parent_attrs)
        base["control_mode"] = str(self._control_mode)
        base["read_only"] = self.read_only
        return base

    async def _reject_readonly_write(self) -> None:
        _LOGGER.info(
            "%s: write ignored — no device write path yet (control_mode=%s)",
            getattr(self, "entity_id", type(self).__name__), self._control_mode,
        )
        self.async_write_ha_state()  # re-publish unchanged state → UI snaps back


def resolve_control_mode(*, platform: str, key: str) -> ControlMode:
    """Resolve an entity's ControlMode from its platform + entity-key leaf.

    `key` is the inventory leaf: descriptor `.key` for parent entities,
    `map_N_<KEY>` for per-map entities. Tries the direct 1:1 id first, then
    falls back to the generic `<key>` sub-map keyed by the same leaf.
    """
    direct = f"{platform}.dreame_a2_mower_{key}"
    val = CONTROL_MODES.get(direct)
    if isinstance(val, ControlMode):
        return val
    generic = CONTROL_MODES.get(f"{platform}.dreame_a2_mower_<key>")
    if isinstance(generic, dict) and key in generic:
        return generic[key]
    raise KeyError(f"no control_mode for {platform}.* key={key!r}")
