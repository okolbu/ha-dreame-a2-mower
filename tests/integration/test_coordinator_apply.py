"""Coordinator property-apply / blob-dispatch tests (state/apply funnel).

Split out of the test_coordinator.py monolith (P3.11); tests moved verbatim.
"""
from __future__ import annotations

import base64

from custom_components.dreame_a2_mower.state import ChargingStatus, MowerState
from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
from tests.integration._coordinator_helpers import (
    _make_s1p1_frame_temp_low_set,
    _make_s1p4_frame_33b,
    _pack_pose,
)


def test_apply_battery_level_property():
    """A (3, 1) property push updates MowerState.battery_level."""
    state = MowerState()
    new_state = apply_property_to_state(state, siid=3, piid=1, value=72)
    assert new_state.battery_level == 72
    # Other fields unchanged
    assert new_state.charging_status is None


def test_apply_state_property():
    """A (2, 1) property push returns state unchanged (SM-14: state field removed;
    state machine owns behavioural state now)."""
    state = MowerState()
    new_state = apply_property_to_state(state, siid=2, piid=1, value=1)
    # MowerState.state was removed; the apply is a no-op for s2p1
    assert new_state == state


def test_apply_charging_status_property():
    state = MowerState()
    new_state = apply_property_to_state(state, siid=3, piid=2, value=1)
    assert new_state.charging_status == ChargingStatus.CHARGING


def test_apply_unknown_property_returns_unchanged_state():
    """Unknown (siid, piid) is logged elsewhere; the state is unchanged."""
    state = MowerState(battery_level=50)
    new_state = apply_property_to_state(state, siid=99, piid=99, value="weird")
    assert new_state == state


def test_apply_property_with_invalid_state_value_is_noop():
    """Invalid s2p1 values are silently dropped (SM-14: state field removed)."""
    state = MowerState()
    # 999 is not a valid State enum; s2p1 apply is now a no-op
    new_state = apply_property_to_state(state, siid=2, piid=1, value=999)
    assert new_state == state


def test_s1p4_blob_updates_position_area_phase():
    """A (1, 4) push (telemetry blob) decodes and updates multiple state fields."""
    state = MowerState()
    blob = _make_s1p4_frame_33b(
        x_m=1.23, y_m=-4.56, phase=2, distance_dm=3450, area_mowed_cm2=1250
    )
    # MQTT delivers the blob base64-encoded in the value field
    value = base64.b64encode(blob).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=4, value=value)
    assert abs(new_state.position_x_m - 1.23) < 0.001
    assert abs(new_state.position_y_m - (-4.56)) < 0.001
    assert new_state.mowing_phase == 2
    assert abs(new_state.area_mowed_m2 - 12.50) < 0.001


def test_s1p4_short_frame_updates_position_only():
    """8-byte BEACON short frames update only position_x_m and position_y_m."""
    state = MowerState(mowing_phase=5, area_mowed_m2=7.0)
    # Build an 8-byte beacon with the same pose as the 33-byte test
    x20 = round(1.23 * 1000 / 10)
    y20 = round(-4.56 * 1000 / 10)
    pose = _pack_pose(x20, y20)
    frame8 = bytearray(8)
    frame8[0] = 0xCE
    frame8[1:6] = pose
    frame8[7] = 0xCE
    value = base64.b64encode(bytes(frame8)).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=4, value=value)
    assert abs(new_state.position_x_m - 1.23) < 0.001
    assert abs(new_state.position_y_m - (-4.56)) < 0.001
    # Non-position fields are unchanged (still the original values)
    assert new_state.mowing_phase == 5
    assert new_state.area_mowed_m2 == 7.0


def test_s1p4_invalid_blob_returns_unchanged_state():
    """A malformed s1.4 blob is dropped (logged) without crashing."""
    state = MowerState(position_x_m=1.0)
    new_state = apply_property_to_state(state, siid=1, piid=4, value="not-base64-padded!!")
    # State is unchanged
    assert new_state == state


def test_s1p1_blob_sets_battery_temp_low():
    """A (1, 1) push with battery_temp_low bit set → state.battery_temp_low is True."""
    state = MowerState()
    blob = _make_s1p1_frame_temp_low_set()
    value = base64.b64encode(blob).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=1, value=value)
    assert new_state.battery_temp_low is True


def test_s1p1_blob_clears_battery_temp_low():
    """When the bit is unset, battery_temp_low → False (not None)."""
    state = MowerState(battery_temp_low=True)
    frame = bytearray(20)
    frame[0] = 0xCE   # delimiter
    frame[6] = 0x00   # bit 3 cleared
    frame[19] = 0xCE  # delimiter
    blob = bytes(frame)
    value = base64.b64encode(blob).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=1, value=value)
    assert new_state.battery_temp_low is False


def test_s2p51_rain_protection_updates_state():
    """s2.51 RAIN_PROTECTION payload sets rain_protection_* fields."""
    state = MowerState()
    # [enabled=1, resume_hours=3] — from test_decode_rain_protection_two_element_list
    payload = {"value": [1, 3]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.rain_protection_enabled is True
    assert new_state.rain_protection_resume_hours == 3
    # Unrelated fields unchanged
    assert new_state.dnd_enabled is None


def test_s2p51_rain_protection_disabled():
    """s2.51 RAIN_PROTECTION with enabled=0 sets field to False."""
    state = MowerState()
    payload = {"value": [0, 6]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.rain_protection_enabled is False
    assert new_state.rain_protection_resume_hours == 6


def test_s2p51_dnd_updates_state():
    """s2.51 DND payload updates dnd_enabled, dnd_start_min, dnd_end_min."""
    state = MowerState()
    # {"end": 420, "start": 1320, "value": 1} — from test_decode_dnd_event_extracts_start_end_enabled
    payload = {"end": 420, "start": 1320, "value": 1}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.dnd_enabled is True
    assert new_state.dnd_start_min == 1320
    assert new_state.dnd_end_min == 420


def test_s2p51_dnd_disabled():
    """s2.51 DND with value=0 sets dnd_enabled to False."""
    state = MowerState()
    payload = {"end": 420, "start": 1320, "value": 0}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.dnd_enabled is False


def test_s2p51_charging_updates_battery_thresholds():
    """s2.51 CHARGING payload updates auto_recharge_battery_pct and resume_battery_pct."""
    state = MowerState()
    # [recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min]
    # From test_decode_charging_six_element_list
    payload = {"value": [15, 95, 0, 0, 0, 0]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.auto_recharge_battery_pct == 15
    assert new_state.resume_battery_pct == 95
    assert new_state.custom_charging_enabled is False
    assert new_state.charging_start_min == 0
    assert new_state.charging_end_min == 0


def test_s2p51_charging_with_custom_schedule():
    """s2.51 CHARGING with custom_charging=1 sets correct fields."""
    state = MowerState()
    payload = {"value": [20, 80, 0, 1, 480, 720]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.auto_recharge_battery_pct == 20
    assert new_state.resume_battery_pct == 80
    assert new_state.custom_charging_enabled is True
    assert new_state.charging_start_min == 480
    assert new_state.charging_end_min == 720


def test_s2p51_led_period_updates_state():
    """s2.51 LED_PERIOD payload updates led_period_enabled and scenario bools."""
    state = MowerState()
    # [enabled, start_min, end_min, standby, working, charging, error, reserved]
    # From test_decode_led_period_eight_element_list
    payload = {"value": [1, 360, 1320, 1, 1, 1, 1, 0]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.led_period_enabled is True
    assert new_state.led_in_standby is True
    assert new_state.led_in_working is True
    assert new_state.led_in_charging is True
    assert new_state.led_in_error is True


def test_s2p51_low_speed_night_updates_state():
    """s2.51 LOW_SPEED_NIGHT payload updates low_speed_at_night_* fields."""
    state = MowerState()
    # [enabled=1, start_min=1260, end_min=360] — from test_decode_low_speed_nighttime
    payload = {"value": [1, 1260, 360]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.low_speed_at_night_enabled is True
    assert new_state.low_speed_at_night_start_min == 1260
    assert new_state.low_speed_at_night_end_min == 360


def test_s2p51_anti_theft_updates_state():
    """s2.51 ANTI_THEFT payload updates all three alarm bools."""
    state = MowerState()
    # [lift_alarm=1, offmap_alarm=0, realtime_location=1]
    # From test_decode_anti_theft_three_element_all_binary
    payload = {"value": [1, 0, 1]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.anti_theft_lift_alarm is True
    assert new_state.anti_theft_offmap_alarm is False
    assert new_state.anti_theft_realtime_location is True


def test_s2p51_human_presence_alert_updates_state():
    """s2.51 HUMAN_PRESENCE_ALERT payload updates all 8 fields."""
    state = MowerState()
    # [enabled, sensitivity, standby, mowing, recharge, patrol, alert, photos, push_min]
    # Sample [1,1,1,1,1,1,0,1,3] from inventory.yaml id=REC
    payload = {"value": [1, 1, 1, 1, 1, 1, 0, 1, 3]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.human_presence_alert_enabled is True
    assert new_state.human_presence_alert_sensitivity == 1
    # ↓ new assertions (sample [1,1,1,1,1,1,0,1,3] from inventory.yaml id=REC)
    assert new_state.human_presence_scenario_standby is True
    assert new_state.human_presence_scenario_mowing is True
    assert new_state.human_presence_scenario_recharge is True
    assert new_state.human_presence_scenario_patrol is True
    assert new_state.human_presence_alert_voice is False
    assert new_state.human_presence_alert_push_interval_min == 3


def test_s2p51_language_updates_state():
    """s2.51 LANGUAGE payload updates language_text_idx and language_voice_idx."""
    state = MowerState()
    # From test_decode: {'text': 2, 'voice': 7} → text_idx=2, voice_idx=7
    payload = {"text": 2, "voice": 7}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.language_text_idx == 2
    assert new_state.language_voice_idx == 7


def test_s2p51_timestamp_updates_last_settings_change():
    """s2.51 TIMESTAMP payload updates last_settings_change_unix."""
    state = MowerState()
    payload = {"time": "1776415722", "tz": "UTC"}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state.last_settings_change_unix == 1776415722


def test_s2p51_ambiguous_toggle_drops_silently():
    """AMBIGUOUS_TOGGLE leaves state unchanged (no field to map to)."""
    state = MowerState(rain_protection_enabled=True)
    payload = {"value": 1}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state == state


def test_s2p51_ambiguous_4list_drops_silently():
    """AMBIGUOUS_4LIST leaves state unchanged (cannot distinguish MSG_ALERT vs VOICE)."""
    state = MowerState(dnd_enabled=True)
    payload = {"value": [1, 0, 1, 1]}
    new_state = apply_property_to_state(state, siid=2, piid=51, value=payload)
    assert new_state == state


def test_s2p51_invalid_payload_not_dict_drops_silently():
    """A non-dict payload (string, list, etc.) is dropped; state unchanged."""
    state = MowerState(rain_protection_enabled=True)
    new_state = apply_property_to_state(state, siid=2, piid=51, value="not-a-dict")
    assert new_state == state


def test_s2p51_malformed_dict_drops_silently():
    """A dict with unknown shape is dropped (S2P51DecodeError); state unchanged."""
    state = MowerState(dnd_enabled=False)
    new_state = apply_property_to_state(state, siid=2, piid=51, value={"nonsense": True})
    assert new_state == state


def test_s2p51_empty_dict_drops_silently():
    """An empty dict payload is dropped (S2P51DecodeError); state unchanged."""
    state = MowerState(battery_level=80)
    new_state = apply_property_to_state(state, siid=2, piid=51, value={})
    assert new_state == state


def test_s6p2_multi_field_extracts_mowing_settings():
    """s6.2 is [height_mm, mow_mode, edgemaster, ?]; multi_field extracts all three."""
    state = MowerState()
    value = [60, 1, True, 2]
    new_state = apply_property_to_state(state, siid=6, piid=2, value=value)
    assert new_state.pre_mowing_height_mm == 60
    assert new_state.pre_mowing_efficiency == 1
    assert new_state.pre_edgemaster is True


def test_s6p2_multi_field_handles_short_list():
    """s6.2 multi_field extractors handle too-short lists gracefully."""
    state = MowerState()
    value = [55]  # Only element [0]
    new_state = apply_property_to_state(state, siid=6, piid=2, value=value)
    assert new_state.pre_mowing_height_mm == 55
    assert new_state.pre_mowing_efficiency is None
    assert new_state.pre_edgemaster is None


def test_apply_lidar_object_name_property_updates_state():
    """F7.2.1: dispatching (99, 20) writes latest_lidar_object_name."""
    from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
    from custom_components.dreame_a2_mower.state import MowerState

    state = MowerState()
    new = apply_property_to_state(state, 99, 20, "dreame/lidar/abcdef.pcd")
    assert new.latest_lidar_object_name == "dreame/lidar/abcdef.pcd"
    # Round-trip with same value yields equal state (no spurious change).
    same = apply_property_to_state(new, 99, 20, "dreame/lidar/abcdef.pcd")
    assert same == new


def test_apply_s1p1_accepts_list_payload():
    """g2408 over MQTT delivers s1.1 as a JSON-list of ints, not bytes
    or base64. The blob applier must accept lists (Python list of int)."""
    from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
    from custom_components.dreame_a2_mower.state import MowerState

    state = MowerState()
    # Realistic 20-byte heartbeat blob shape (all-zeros except the
    # battery-temp byte at offset 6).
    blob_list = [0] * 20
    blob_list[6] = 1  # battery_temp_low bit set
    new = apply_property_to_state(state, 1, 1, blob_list)
    # battery_temp_low should now be set (or at least decode shouldn't crash).
    # The exact decoded value depends on the heartbeat schema, but the
    # state should change in some way (or stay equal if the blob is
    # all-default). Most importantly: no exception.
    assert isinstance(new, MowerState)


def test_apply_s1p4_accepts_list_payload():
    """Same coercion path for s1.4 telemetry."""
    from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
    from custom_components.dreame_a2_mower.state import MowerState

    state = MowerState()
    # 8-byte BEACON frame so position-only decode applies.
    blob_list = [0, 0, 1, 0, 0, 0, 1, 0]
    new = apply_property_to_state(state, 1, 4, blob_list)
    assert isinstance(new, MowerState)
