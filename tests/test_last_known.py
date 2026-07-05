"""Round-trip + missing-key tolerance for state.last_known.LastKnown.

Task 12a (P6.7 offline last-known persistence). LastKnown is a SEPARATE
structure from MowerState/StateSnapshot (adding a field to those would break the
corpus golden digest), persisted via its own Store. This pins its pure
to_dict/from_dict contract.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.state.last_known import LastKnown
from custom_components.dreame_a2_mower.state import MowerState


def _full_blob() -> LastKnown:
    return LastKnown(
        blades_life_pct=88.0,
        cleaning_brush_life_pct=42.0,
        robot_maintenance_life_pct=71.0,
        total_mowed_area_m2=1234.5,
        total_mowing_time_min=9876,
        mowing_count=321,
        sim_card_id="ICCID-XYZ",
        sim_left_days=895,
        sim_active_time="2024-01-01",
        sim_expired_time="2028-11-19T16:00:00Z",
        sim_data_remaining_mb=1683.05,
        sim_out_of_warranty=False,
        dock_x_mm=1500,
        dock_y_mm=-2200,
        dock_yaw=90,
        dock_in_lawn_region=True,
        firmware_version="4.3.6_0625",
        rain_protection_enabled=True,
        rain_protection_resume_hours=3,
        frost_protection_enabled=False,
        dnd_enabled=True,
        dnd_start_min=1320,
        dnd_end_min=420,
        custom_charging_enabled=False,
        charging_start_min=60,
        charging_end_min=360,
        wifi_ssid="MyLawnNet",
        wifi_ip="192.168.1.42",
        active_map_id=7,
        saved_unix=1_700_000_000.0,
    )


def test_round_trip_identity():
    blob = _full_blob()
    assert LastKnown.from_dict(blob.to_dict()) == blob


def test_to_dict_is_plain_jsonable():
    d = _full_blob().to_dict()
    assert isinstance(d, dict)
    # every value is a JSON-native scalar or None
    for v in d.values():
        assert v is None or isinstance(v, (str, int, float, bool))


def test_from_dict_tolerates_missing_keys():
    # Forward/back compat: an older/newer blob missing keys -> those fields None.
    blob = LastKnown.from_dict({"active_map_id": 3, "blades_life_pct": 50.0})
    assert blob.active_map_id == 3
    assert blob.blades_life_pct == 50.0
    assert blob.wifi_ssid is None
    assert blob.sim_card_id is None
    assert blob.saved_unix is None


def test_from_dict_ignores_unknown_keys():
    blob = LastKnown.from_dict({"active_map_id": 1, "some_future_field": "x"})
    assert blob.active_map_id == 1


def test_empty_dict_gives_all_none():
    blob = LastKnown.from_dict({})
    assert blob == LastKnown()
    assert blob.active_map_id is None


def test_from_state_reads_mower_state_fields():
    state = MowerState(
        blades_life_pct=88.0,
        dock_x_mm=1500,
        wifi_ssid="MyLawnNet",
        rain_protection_enabled=True,
    )
    blob = LastKnown.from_state(state, active_map_id=5, saved_unix=123.0)
    assert blob.blades_life_pct == 88.0
    assert blob.dock_x_mm == 1500
    assert blob.wifi_ssid == "MyLawnNet"
    assert blob.rain_protection_enabled is True
    assert blob.active_map_id == 5
    assert blob.saved_unix == 123.0


def test_non_none_state_updates_excludes_meta_and_none():
    blob = LastKnown.from_dict(
        {"blades_life_pct": 50.0, "active_map_id": 9, "saved_unix": 1.0}
    )
    updates = blob.non_none_state_updates()
    assert updates == {"blades_life_pct": 50.0}
    # meta fields never leak into MowerState updates
    assert "active_map_id" not in updates
    assert "saved_unix" not in updates
    # seeding a real MowerState with the updates works
    seeded = MowerState().with_updates(**updates)
    assert seeded.blades_life_pct == 50.0


def test_last_known_captures_all_cfg_settings():
    """Every CFG-backed device-wide setting round-trips through LastKnown."""
    from custom_components.dreame_a2_mower.state.last_known import LastKnown, _STATE_FIELDS

    cfg_fields = {
        "child_lock_enabled": True, "volume_pct": 60,
        "language_text_idx": 1, "language_voice_idx": 2, "language_code": "text=1,voice=2",
        "low_speed_at_night_enabled": True, "low_speed_at_night_start_min": 1320, "low_speed_at_night_end_min": 360,
        "auto_recharge_battery_pct": 15, "resume_battery_pct": 80,
        "led_period_enabled": True, "led_in_standby": True, "led_in_working": False,
        "led_in_charging": True, "led_in_error": True,
        "anti_theft_lift_alarm": True, "anti_theft_offmap_alarm": False, "anti_theft_realtime_location": True,
        "human_presence_alert_enabled": True, "human_presence_alert_sensitivity": 2,
        "human_presence_scenario_standby": True, "human_presence_scenario_mowing": False,
        "human_presence_scenario_recharge": True, "human_presence_scenario_patrol": False,
        "human_presence_alert_voice": True, "human_presence_alert_push_interval_min": 30,
        "msg_alert_anomaly": True, "msg_alert_error": True, "msg_alert_task": False, "msg_alert_consumables": True,
        "voice_regular_notification": True, "voice_work_status": False,
        "voice_special_status": True, "voice_error_status": True,
        "auto_recharge_standby_enabled": True, "ai_obstacle_photos_enabled": False, "navigation_path_smart": True,
    }
    # Every field is a declared _STATE_FIELDS entry.
    for name in cfg_fields:
        assert name in _STATE_FIELDS, f"{name} missing from _STATE_FIELDS"

    class _FakeState:
        pass
    st = _FakeState()
    for k, v in cfg_fields.items():
        setattr(st, k, v)

    lk = LastKnown.from_state(st, active_map_id=0, saved_unix=123.0)
    round_tripped = LastKnown.from_dict(lk.to_dict())
    updates = round_tripped.non_none_state_updates()
    for k, v in cfg_fields.items():
        assert getattr(round_tripped, k) == v, f"{k} lost in round-trip"
        assert updates[k] == v, f"{k} not seeded via non_none_state_updates"
