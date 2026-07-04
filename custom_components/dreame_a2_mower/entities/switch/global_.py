"""Device settings switch entities, description table, and wire-value builder helpers for the Dreame A2 Mower.

This module is a helper — NOT a HA platform — so HA will not attempt to
load it as a switch platform.  It is imported by switch.py (the real
platform entry).

Contains the CFG/AI-recognition/edge-mowing/obstacle-avoidance switch classes and the SWITCHES
description table plus its wire-value builder helpers (_build_* / _field_updates_*).  Most switches
here read/write per-active-map settings via map_device_info (CFG transport); DreameA2AiHumanDetectionSwitch
is mower-scoped (parent device).  The dedicated per-map map-binding switch (DreameA2MapEdgemasterSwitch)
lives in switch_map.py instead.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..._availability import _FreshnessAvailableMixin
from ..._devices import map_unique_id, mower_device_info, mower_unique_id
from ...control_honesty import _ControlHonestyMixin, resolve_control_mode
from ...coordinator import DreameA2MowerCoordinator
from ...coordinator._write_errors import raise_for_write_result
from ...state import MowerState
from .base import (
    DreameA2SwitchEntityDescription,
    _AiRecognitionBitSwitch,
    _PerMapSettingsSwitchBase,
    PER_MAP_SETTINGS_SWITCHES,
    _AI_HUMANS_BIT,
    _AI_ANIMALS_BIT,
    _AI_OBJECTS_BIT,
)
from ...protocol import cfg_payloads as _cfgp


# ---------------------------------------------------------------------------
# Wire-value builders — settable switches
# ---------------------------------------------------------------------------

def _build_cls(state: MowerState, enabled: bool) -> int:
    """CLS wire value: single int {0, 1}."""
    return int(enabled)


def _cls_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"child_lock_enabled": enabled}


def _dnd_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"dnd_enabled": enabled}


def _wrp_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"rain_protection_enabled": enabled}


def _low_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"low_speed_at_night_enabled": enabled}


def _bat_custom_charging_field_updates(
    state: MowerState, enabled: bool
) -> dict[str, Any]:
    return {"custom_charging_enabled": enabled}


def _build_ata_lift(state: MowerState, enabled: bool) -> list:
    """ATA wire value: list(3) [lift_alarm, offmap_alarm, realtime_location].

    CFG.ATA confirmed on g2408
    (coordinator._property_apply.cfg_to_state_updates §ATA, all 3 indices
    individually verified 2026-04-27).  All 3 fields are stored in MowerState,
    so full reconstruction is safe.
    """
    return [
        int(enabled),                                        # [0] lift_alarm  (new)
        int(state.anti_theft_offmap_alarm or False),         # [1] offmap_alarm
        int(state.anti_theft_realtime_location or False),    # [2] realtime_location
    ]


def _ata_lift_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"anti_theft_lift_alarm": enabled}


def _build_ata_offmap(state: MowerState, enabled: bool) -> list:
    """ATA wire value with offmap_alarm overridden."""
    return [
        int(state.anti_theft_lift_alarm or False),           # [0] lift_alarm
        int(enabled),                                        # [1] offmap_alarm  (new)
        int(state.anti_theft_realtime_location or False),    # [2] realtime_location
    ]


def _ata_offmap_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"anti_theft_offmap_alarm": enabled}


def _build_ata_realtime(state: MowerState, enabled: bool) -> list:
    """ATA wire value with realtime_location overridden."""
    return [
        int(state.anti_theft_lift_alarm or False),           # [0] lift_alarm
        int(state.anti_theft_offmap_alarm or False),         # [1] offmap_alarm
        int(enabled),                                        # [2] realtime_location  (new)
    ]


def _ata_realtime_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"anti_theft_realtime_location": enabled}


# ---------------------------------------------------------------------------
# AMBIGUOUS_TOGGLE single-int CFG keys (FDP / STUN / AOP / PROT)
# All four toggle-confirmed 2026-04-30 (see protocol/config_s2p51.py).
# Wire shape: int {0, 1}. Trivial reconstruction.
# ---------------------------------------------------------------------------

def _build_int_toggle(_state: MowerState, enabled: bool) -> int:
    return int(enabled)


def _fdp_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"frost_protection_enabled": enabled}


def _stun_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"auto_recharge_standby_enabled": enabled}


def _aop_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"ai_obstacle_photos_enabled": enabled}


# ---------------------------------------------------------------------------
# MSG_ALERT — Notification Preferences (4-bool list)
# Slots [anomaly, error, task, consumables_messages] confirmed 2026-04-30.
# All four MowerState fields stored, so full reconstruction is safe.
# ---------------------------------------------------------------------------

def _build_msg_alert_with(
    state: MowerState, idx: int, enabled: bool
) -> list[int]:
    """Reconstruct CFG.MSG_ALERT with element ``idx`` overridden to ``enabled``."""
    current = (
        state.msg_alert_anomaly,
        state.msg_alert_error,
        state.msg_alert_task,
        state.msg_alert_consumables,
    )
    return [
        int(enabled if i == idx else bool(current[i] or False))
        for i in range(4)
    ]


def _build_msg_alert_anomaly(state: MowerState, enabled: bool) -> list[int]:
    return _build_msg_alert_with(state, 0, enabled)


def _build_msg_alert_error(state: MowerState, enabled: bool) -> list[int]:
    return _build_msg_alert_with(state, 1, enabled)


def _build_msg_alert_task(state: MowerState, enabled: bool) -> list[int]:
    return _build_msg_alert_with(state, 2, enabled)


def _build_msg_alert_consumables(state: MowerState, enabled: bool) -> list[int]:
    return _build_msg_alert_with(state, 3, enabled)


def _msg_alert_anomaly_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"msg_alert_anomaly": enabled}


def _msg_alert_error_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"msg_alert_error": enabled}


def _msg_alert_task_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"msg_alert_task": enabled}


def _msg_alert_consumables_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"msg_alert_consumables": enabled}


# ---------------------------------------------------------------------------
# VOICE — Voice Prompt Modes (4-bool list)
# Slots [regular_notification, work_status, special_status, error_status]
# confirmed 2026-04-30. Full reconstruction safe.
# ---------------------------------------------------------------------------

def _build_voice_with(
    state: MowerState, idx: int, enabled: bool
) -> list[int]:
    current = (
        state.voice_regular_notification,
        state.voice_work_status,
        state.voice_special_status,
        state.voice_error_status,
    )
    return [
        int(enabled if i == idx else bool(current[i] or False))
        for i in range(4)
    ]


def _build_voice_regular(state: MowerState, enabled: bool) -> list[int]:
    return _build_voice_with(state, 0, enabled)


def _build_voice_work(state: MowerState, enabled: bool) -> list[int]:
    return _build_voice_with(state, 1, enabled)


def _build_voice_special(state: MowerState, enabled: bool) -> list[int]:
    return _build_voice_with(state, 2, enabled)


def _build_voice_error(state: MowerState, enabled: bool) -> list[int]:
    return _build_voice_with(state, 3, enabled)


def _voice_regular_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"voice_regular_notification": enabled}


def _voice_work_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"voice_work_status": enabled}


def _voice_special_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"voice_special_status": enabled}


def _voice_error_field_updates(state: MowerState, enabled: bool) -> dict[str, Any]:
    return {"voice_error_status": enabled}


# ---------------------------------------------------------------------------
# Entity descriptors
# ---------------------------------------------------------------------------

SWITCHES: tuple[DreameA2SwitchEntityDescription, ...] = (
    # ------------------------------------------------------------------
    # Settable: CLS — child lock
    # Wire shape: single int {0, 1}. Trivially reconstructible.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="child_lock",
        name="Child lock",
        icon="mdi:lock",
        value_fn=lambda s: s.child_lock_enabled,
        cfg_key="CLS",
        build_value_fn=_build_cls,
        field_updates_fn=_cls_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: DND — do-not-disturb
    # Wire shape: list(3) [enabled, start_min, end_min].
    # All 3 fields stored in MowerState (dnd_enabled, dnd_start_min,
    # dnd_end_min).  Safe to reconstruct.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="dnd",
        name="Do not disturb",
        icon="mdi:sleep",
        value_fn=lambda s: s.dnd_enabled,
        cfg_key="DND",
        build_from_cfg_fn=lambda raw, on: _cfgp.build_dnd(raw, value=on),
        field_updates_fn=_dnd_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: WRP — rain protection
    # Wire shape: list(2) [enabled, resume_hours].
    # Both fields stored in MowerState.  Safe to reconstruct.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="rain_protection",
        name="Rain protection",
        icon="mdi:weather-rainy",
        value_fn=lambda s: s.rain_protection_enabled,
        cfg_key="WRP",
        build_from_cfg_fn=lambda raw, on: _cfgp.build_wrp(raw, value=on),
        field_updates_fn=_wrp_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: LOW — low speed at night
    # Wire shape: list(3) [enabled, start_min, end_min].
    # All 3 fields stored in MowerState.  Safe to reconstruct.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="low_speed_at_night",
        name="Low speed at night",
        icon="mdi:weather-night",
        value_fn=lambda s: s.low_speed_at_night_enabled,
        cfg_key="LOW",
        build_from_cfg_fn=lambda raw, on: _cfgp.build_low(raw, value=on),
        field_updates_fn=_low_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: BAT[3] — custom charging period
    # Wire shape: list(6) [recharge_pct, resume_pct, unknown_flag(=1),
    #             custom_charging, start_min, end_min].
    # All 6 fields stored in MowerState.  unknown_flag hard-coded to 1
    # (only observed value — same decision as F4.6.1 number.py).
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="custom_charging_period",
        name="Custom charging period",
        icon="mdi:battery-clock",
        value_fn=lambda s: s.custom_charging_enabled,
        cfg_key="BAT",
        build_from_cfg_fn=lambda raw, on: _cfgp.build_bat_charging(raw, enabled=on),
        field_updates_fn=_bat_custom_charging_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: ATA[0] — lift alarm
    # Wire shape: list(3) [lift_alarm, offmap_alarm, realtime_location].
    # All 3 fields stored in MowerState.  Safe to reconstruct.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="anti_theft_lift_alarm",
        name="Anti-theft lift alarm",
        icon="mdi:alarm-light",
        value_fn=lambda s: s.anti_theft_lift_alarm,
        cfg_key="ATA",
        build_value_fn=_build_ata_lift,
        field_updates_fn=_ata_lift_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: ATA[1] — off-map alarm
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="anti_theft_offmap_alarm",
        name="Anti-theft off-map alarm",
        icon="mdi:map-marker-alert",
        value_fn=lambda s: s.anti_theft_offmap_alarm,
        cfg_key="ATA",
        build_value_fn=_build_ata_offmap,
        field_updates_fn=_ata_offmap_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: ATA[2] — realtime location
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="anti_theft_realtime_location",
        name="Anti-theft realtime location",
        icon="mdi:crosshairs-gps",
        value_fn=lambda s: s.anti_theft_realtime_location,
        cfg_key="ATA",
        build_value_fn=_build_ata_realtime,
        field_updates_fn=_ata_realtime_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: AMBIGUOUS_TOGGLE single-int CFG keys (a62)
    # All four toggle-confirmed 2026-04-30. CFG int {0, 1}, trivial build.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="frost_protection",
        name="Frost protection",
        icon="mdi:snowflake-alert",
        value_fn=lambda s: s.frost_protection_enabled,
        cfg_key="FDP",
        build_value_fn=_build_int_toggle,
        field_updates_fn=_fdp_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="auto_recharge_standby",
        name="Auto recharge after extended standby",
        icon="mdi:battery-clock",
        value_fn=lambda s: s.auto_recharge_standby_enabled,
        cfg_key="STUN",
        build_value_fn=_build_int_toggle,
        field_updates_fn=_stun_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="ai_obstacle_photos",
        name="AI obstacle photos",
        icon="mdi:camera-iris",
        value_fn=lambda s: s.ai_obstacle_photos_enabled,
        cfg_key="AOP",
        build_value_fn=_build_int_toggle,
        field_updates_fn=_aop_field_updates,
    ),
    # ------------------------------------------------------------------
    # Settable: MSG_ALERT — Notification Preferences (a62)
    # Four switches sharing CFG.MSG_ALERT 4-bool list. Slots
    # [anomaly, error, task, consumables_messages] toggle-confirmed
    # 2026-04-30. Full reconstruction safe (all 4 in MowerState).
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="msg_alert_anomaly",
        # v2 rename (P4.5, track-5 T5-11): drop the "Notification:" colon prefix.
        # object_id: switch.dreame_a2_mower_anomaly_notifications.
        name="Anomaly notifications",
        icon="mdi:alert-octagon",
        value_fn=lambda s: s.msg_alert_anomaly,
        cfg_key="MSG_ALERT",
        build_value_fn=_build_msg_alert_anomaly,
        field_updates_fn=_msg_alert_anomaly_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="msg_alert_error",
        name="Error notifications",
        icon="mdi:alert-circle",
        value_fn=lambda s: s.msg_alert_error,
        cfg_key="MSG_ALERT",
        build_value_fn=_build_msg_alert_error,
        field_updates_fn=_msg_alert_error_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="msg_alert_task",
        name="Task notifications",
        icon="mdi:clipboard-text",
        value_fn=lambda s: s.msg_alert_task,
        cfg_key="MSG_ALERT",
        build_value_fn=_build_msg_alert_task,
        field_updates_fn=_msg_alert_task_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="msg_alert_consumables",
        name="Consumables notifications",
        icon="mdi:tools",
        value_fn=lambda s: s.msg_alert_consumables,
        cfg_key="MSG_ALERT",
        build_value_fn=_build_msg_alert_consumables,
        field_updates_fn=_msg_alert_consumables_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable: VOICE — Voice Prompt Modes (a62)
    # Four switches sharing CFG.VOICE 4-bool list. Slots
    # [regular_notification, work_status, special_status, error_status]
    # toggle-confirmed 2026-04-30. Full reconstruction safe.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="voice_regular_notification",
        # v2 rename (P4.5, track-5 T5-11): drop the "Voice:" colon prefix.
        # object_id: switch.dreame_a2_mower_voice_prompt_regular_notification.
        name="Voice prompt — Regular notification",
        icon="mdi:bullhorn",
        value_fn=lambda s: s.voice_regular_notification,
        cfg_key="VOICE",
        build_value_fn=_build_voice_regular,
        field_updates_fn=_voice_regular_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="voice_work_status",
        name="Voice prompt — Work status",
        icon="mdi:bullhorn-variant",
        value_fn=lambda s: s.voice_work_status,
        cfg_key="VOICE",
        build_value_fn=_build_voice_work,
        field_updates_fn=_voice_work_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="voice_special_status",
        name="Voice prompt — Special status",
        icon="mdi:bullhorn-variant-outline",
        value_fn=lambda s: s.voice_special_status,
        cfg_key="VOICE",
        build_value_fn=_build_voice_special,
        field_updates_fn=_voice_special_field_updates,
    ),
    DreameA2SwitchEntityDescription(
        key="voice_error_status",
        name="Voice prompt — Error status",
        icon="mdi:alert-octagon-outline",
        value_fn=lambda s: s.voice_error_status,
        cfg_key="VOICE",
        build_value_fn=_build_voice_error,
        field_updates_fn=_voice_error_field_updates,
    ),

    # ------------------------------------------------------------------
    # Settable (Phase A1): LIT[0] — LED period (main enable); RMW via cfg_payloads.build_lit
    #
    # CFG.LIT = list(8) [enabled, start_min, end_min, standby, working,
    #                    charging, error, unknown_trailing_toggle].
    # build_lit reads the raw 8-element list from CFG and patches only
    # the target index, preserving undecoded slots — no reconstruction needed.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="led_period",
        name="LED period",
        icon="mdi:led-on",
        value_fn=lambda s: s.led_period_enabled,
        cfg_key="LIT",
        build_from_cfg_fn=lambda raw, on: _cfgp.build_lit(raw, value=on),
        field_updates_fn=lambda s, on: {"led_period_enabled": on},
    ),

    # ------------------------------------------------------------------
    # Settable (Phase A1): LIT[3] — LED in standby; RMW via cfg_payloads.build_lit
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="led_in_standby",
        name="LED in standby",
        icon="mdi:led-outline",
        value_fn=lambda s: s.led_in_standby,
        cfg_key="LIT",
        build_from_cfg_fn=lambda raw, on: _cfgp.build_lit(raw, standby=on),
        field_updates_fn=lambda s, on: {"led_in_standby": on},
    ),

    # ------------------------------------------------------------------
    # Settable (Phase A1): LIT[4] — LED while working; RMW via cfg_payloads.build_lit
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="led_in_working",
        name="LED while working",
        icon="mdi:led-outline",
        value_fn=lambda s: s.led_in_working,
        cfg_key="LIT",
        build_from_cfg_fn=lambda raw, on: _cfgp.build_lit(raw, working=on),
        field_updates_fn=lambda s, on: {"led_in_working": on},
    ),

    # ------------------------------------------------------------------
    # Settable (Phase A1): LIT[5] — LED while charging; RMW via cfg_payloads.build_lit
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="led_in_charging",
        name="LED while charging",
        icon="mdi:led-outline",
        value_fn=lambda s: s.led_in_charging,
        cfg_key="LIT",
        build_from_cfg_fn=lambda raw, on: _cfgp.build_lit(raw, charging=on),
        field_updates_fn=lambda s, on: {"led_in_charging": on},
    ),

    # ------------------------------------------------------------------
    # Settable (Phase A1): LIT[6] — LED on error; RMW via cfg_payloads.build_lit
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="led_in_error",
        name="LED on error",
        icon="mdi:led-alert",
        value_fn=lambda s: s.led_in_error,
        cfg_key="LIT",
        build_from_cfg_fn=lambda raw, on: _cfgp.build_lit(raw, error=on),
        field_updates_fn=lambda s, on: {"led_in_error": on},
    ),

    # ------------------------------------------------------------------
    # Settable (Phase A1): REC[0] — human presence alert enabled; RMW via cfg_payloads.build_rec
    #
    # CFG.REC = list(9) [enabled, sensitivity, standby, mowing, recharge,
    #                    patrol, alert, photo_consent, push_min].
    # build_rec reads the raw 9-element list from CFG and patches only
    # the target index, preserving undecoded slots — no reconstruction needed.
    # ------------------------------------------------------------------
    DreameA2SwitchEntityDescription(
        key="human_presence_alert",
        name="Human presence alert",
        icon="mdi:motion-sensor",
        value_fn=lambda s: s.human_presence_alert_enabled,
        cfg_key="REC",
        build_from_cfg_fn=lambda raw, on: _cfgp.build_rec(raw, value=on),
        field_updates_fn=lambda s, on: {"human_presence_alert_enabled": on},
    ),

    # NOTE — parent-level `edgemaster` removed 2026-05-15. It was a
    # read-only mirror of the LAST ACTIVE MAP's s6.2[2] value, which
    # is misleading on a multi-map device. Replaced by per-map
    # ``DreameA2MapEdgemasterSwitch`` (read-only, reads from PRE
    # shadow per map). Symmetric to the mowing-efficiency removal.
)


# ---------------------------------------------------------------------------
# SETTINGS-driven switch entities (Task 8)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-map SETTINGS switches — thin subclasses over _PerMapSettingsSwitchBase.
#
# All shared logic (is_on / available / async_turn_on|off / __init__ wiring)
# lives in the base; each subclass only binds its _SPEC row from
# PER_MAP_SETTINGS_SWITCHES. unique_ids, entity_ids, names, and control_modes
# are byte-identical to the pre-consolidation per-switch classes.
# ---------------------------------------------------------------------------

_PER_MAP_SETTINGS_SPECS = {s.key: s for s in PER_MAP_SETTINGS_SWITCHES}


class DreameA2EdgeMowingAutoSwitch(_PerMapSettingsSwitchBase):
    """Edge mowing auto — per-map SETTINGS switch."""

    _SPEC = _PER_MAP_SETTINGS_SPECS["settings_edge_mowing_auto"]


class DreameA2EdgeMowingSafeSwitch(_PerMapSettingsSwitchBase):
    """Edge mowing safe — per-map SETTINGS switch."""

    _SPEC = _PER_MAP_SETTINGS_SPECS["settings_edge_mowing_safe"]


class DreameA2EdgeMowingObstacleAvoidanceSwitch(_PerMapSettingsSwitchBase):
    """Edge mowing obstacle avoidance — per-map SETTINGS switch."""

    _SPEC = _PER_MAP_SETTINGS_SPECS["settings_edge_mowing_obstacle_avoidance"]


class DreameA2ObstacleAvoidanceEnabledSwitch(_PerMapSettingsSwitchBase):
    """Obstacle avoidance enabled — per-map SETTINGS switch."""

    _SPEC = _PER_MAP_SETTINGS_SPECS["settings_obstacle_avoidance_enabled"]


class DreameA2AiHumanDetectionSwitch(
    _FreshnessAvailableMixin,
    _ControlHonestyMixin,
    CoordinatorEntity[DreameA2MowerCoordinator],
    SwitchEntity,
):
    """AI human detection — reads from cloud_state.ai_human_enabled."""

    _attr_has_entity_name = True
    _availability_source = "cloud"
    _attr_translation_key = "cloud_state_ai_human_enabled"
    _attr_name = "Capture Photos AI Obstacles"
    _attr_should_poll = False
    # R-50 / T5-4: writable AI-obstacle-photo control → CONFIG.
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "cloud_state_ai_human_enabled")
        self._attr_device_info = mower_device_info(coordinator)
        self._control_mode = resolve_control_mode(platform="switch", key="cloud_state_ai_human_enabled")

    @property
    def is_on(self) -> bool | None:
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return None
        return cs.ai_human_enabled

    @property
    def available(self) -> bool:
        if self.is_on is None:
            return False
        return super().available

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.read_only:
            return await self._reject_readonly_write()
        coord = self.coordinator
        cs = getattr(coord, "cloud_state", None)
        old_value = cs.ai_human_enabled if cs is not None else None
        result = await coord.write_ai_human_enabled(True)
        if result.accepted:
            self.async_write_ha_state()
            return
        await self.hass.services.async_call(
            "persistent_notification", "create",
            service_data={
                "title": "Dreame A2 Mower: setting write rejected",
                "message": (
                    "The cloud rejected the AI Human Detection toggle. "
                    f"Previous value: {old_value!r}."
                ),
                "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
            },
            blocking=False,
        )
        self.async_write_ha_state()
        # P2 Task 5: raise so the UI action shows the honest cloud verdict.
        raise_for_write_result(result, "Set AI Human Detection", context="entity")

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.read_only:
            return await self._reject_readonly_write()
        coord = self.coordinator
        cs = getattr(coord, "cloud_state", None)
        old_value = cs.ai_human_enabled if cs is not None else None
        result = await coord.write_ai_human_enabled(False)
        if result.accepted:
            self.async_write_ha_state()
            return
        await self.hass.services.async_call(
            "persistent_notification", "create",
            service_data={
                "title": "Dreame A2 Mower: setting write rejected",
                "message": (
                    "The cloud rejected the AI Human Detection toggle. "
                    f"Previous value: {old_value!r}."
                ),
                "notification_id": f"dreame_a2_write_fail_{self.entity_id}",
            },
            blocking=False,
        )
        self.async_write_ha_state()
        # P2 Task 5: raise so the UI action shows the honest cloud verdict.
        raise_for_write_result(result, "Set AI Human Detection", context="entity")


# ---------------------------------------------------------------------------
# WiFi-heatmap render-orientation toggles (R-15 / P5.1)
#
# Integration-owned LOCAL render preferences that REPLACE the old
# dashboard-installed helpers input_boolean.dreame_a2_mower_wifi_flip_x/y.
# They store an on/off bool on the coordinator (coord.wifi_flip_x /
# coord.wifi_flip_y) that camera/wifi.py reads at render time — NO wire
# write. Eliminating the backend's dependency on external helper entities is
# what lets the P5 dashboard strategy ship helper-free.
# ---------------------------------------------------------------------------

class _WifiHeatmapFlipSwitchBase(
    _ControlHonestyMixin,
    CoordinatorEntity[DreameA2MowerCoordinator],
    RestoreEntity,
    SwitchEntity,
):
    """Base for the two WiFi-heatmap render-orientation flip switches.

    Each subclass binds ``_AXIS`` (``"x"`` or ``"y"``) plus its name/icon.
    The authoritative on/off state is the coordinator attr
    ``coord.wifi_flip_<axis>`` (set here, read by camera/wifi.py). This is a
    local render preference (``control_mode`` = INTEGRATION_LOCAL): toggling
    performs NO cloud/device write. ``RestoreEntity`` persists the toggle
    across HA restarts. Toggling broadcasts a coordinator update so each WiFi
    camera rotates its ``access_token`` (the cameras fold the flip bools into
    their ``_handle_coordinator_update`` key), which busts the browser's
    cached image and re-fetches the re-oriented PNG.
    """

    _AXIS: str = ""
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        leaf = f"wifi_heatmap_flip_{self._AXIS}"
        self._attr_unique_id = mower_unique_id(coordinator, leaf)
        self._attr_device_info = mower_device_info(coordinator)
        self._control_mode = resolve_control_mode(platform="switch", key=leaf)

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator, f"wifi_flip_{self._AXIS}", False))

    async def async_added_to_hass(self) -> None:
        """Restore the last flip preference across HA restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            setattr(
                self.coordinator,
                f"wifi_flip_{self._AXIS}",
                last_state.state == "on",
            )

    async def _set(self, value: bool) -> None:
        """Store the flip pref and re-render every WiFi camera in-band.

        Writes the coordinator attr, then broadcasts a coordinator update so
        each WiFi camera's ``_handle_coordinator_update`` observes the flip
        change (it is folded into the camera's dedup key) and rotates its
        ``access_token``. See ``feedback_camera_image_refresh_pattern``.
        """
        setattr(self.coordinator, f"wifi_flip_{self._AXIS}", value)
        self.async_write_ha_state()
        update_listeners = getattr(
            self.coordinator, "async_update_listeners", None
        )
        if callable(update_listeners):
            update_listeners()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class DreameA2WifiHeatmapFlipXSwitch(_WifiHeatmapFlipSwitchBase):
    """WiFi heatmap horizontal-flip toggle (object_id: …_wifi_heatmap_flip_x)."""

    _AXIS = "x"
    _attr_name = "WiFi heatmap flip X"
    _attr_icon = "mdi:flip-horizontal"


class DreameA2WifiHeatmapFlipYSwitch(_WifiHeatmapFlipSwitchBase):
    """WiFi heatmap vertical-flip toggle (object_id: …_wifi_heatmap_flip_y)."""

    _AXIS = "y"
    _attr_name = "WiFi heatmap flip Y"
    _attr_icon = "mdi:flip-vertical"


class DreameA2AiRecognitionHumansSwitch(_AiRecognitionBitSwitch):
    """AI Obstacle Recognition: Humans (bit 0) — per-map."""

    _BIT = _AI_HUMANS_BIT
    _HONESTY_LEAF = "ai_recognition_humans"
    _attr_translation_key = "ai_recognition_humans"

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator, map_id=map_id)
        self._attr_unique_id = map_unique_id(coordinator, map_id, "ai_recognition_humans")
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "AI Obstacle Recognition: Humans"


class DreameA2AiRecognitionAnimalsSwitch(_AiRecognitionBitSwitch):
    """AI Obstacle Recognition: Animals (bit 1) — per-map."""

    _BIT = _AI_ANIMALS_BIT
    _HONESTY_LEAF = "ai_recognition_animals"
    _attr_translation_key = "ai_recognition_animals"

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator, map_id=map_id)
        self._attr_unique_id = map_unique_id(coordinator, map_id, "ai_recognition_animals")
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "AI Obstacle Recognition: Animals"


class DreameA2AiRecognitionObjectsSwitch(_AiRecognitionBitSwitch):
    """AI Obstacle Recognition: Objects (bit 2) — per-map."""

    _BIT = _AI_OBJECTS_BIT
    _HONESTY_LEAF = "ai_recognition_objects"
    _attr_translation_key = "ai_recognition_objects"

    def __init__(self, coordinator: DreameA2MowerCoordinator, *, map_id: int) -> None:
        super().__init__(coordinator, map_id=map_id)
        self._attr_unique_id = map_unique_id(coordinator, map_id, "ai_recognition_objects")
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "AI Obstacle Recognition: Objects"
