"""Round-trip + missing-key tolerance for state.last_known.LastKnown.

Task 12a (P6.7 offline last-known persistence). LastKnown is a SEPARATE
structure from MowerState/StateSnapshot (adding a field to those would break the
corpus golden digest), persisted via its own Store. This pins its pure
to_dict/from_dict contract.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.state.last_known import LastKnown, _STATE_FIELDS
from custom_components.dreame_a2_mower.state import FLAT_FIELDS, MowerState


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


def test_state_fields_are_all_real_mower_state_fields():
    """Guard: every _STATE_FIELDS name must be a real MowerState flat field.

    A misspelled or stale name in _STATE_FIELDS makes ``getattr(state, name,
    None)`` silently return None in ``LastKnown.from_state`` -- the setting
    never persists and no existing test catches it (the CFG-coverage test
    below uses a fake state with every attr preset, so a typo there would
    just set an attr that's never read back). Comparing against the
    authoritative FLAT_FIELDS tuple catches that class of typo loudly.
    """
    stray = set(_STATE_FIELDS) - set(FLAT_FIELDS)
    assert not stray, f"_STATE_FIELDS names not in MowerState.FLAT_FIELDS: {stray}"


def test_last_known_captures_all_cfg_settings():
    """Every CFG-backed device-wide setting round-trips through LastKnown."""
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
        "pre_zone_id": 3, "pre_mowing_efficiency": 1,
        "photo_consent": True,
        "weather_forecast_reference": 1,
        "timezone": "Europe/Oslo",
        "cfg_version": 42,
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


# --- the save must MERGE, not overwrite --------------------------------------
#
# LastKnown.from_state takes `getattr(state, name, None)` for every field —
# including None — and the Store save is a whole-blob overwrite. So the moment
# the mower goes offline, a cloud fetch that SUCCEEDS but carries no device data
# (cloud up, mower absent) rebuilds the blob from an empty MowerState and writes
# nulls over a perfectly good last-known.
#
# That defeats the entire point of the layer: it captures values while online,
# then erases them at exactly the moment they are needed. The guard on the
# caller ("only save after a successful fetch") does NOT cover
# succeeded-but-empty.
#
# Observed live 2026-07-16: the store held saved_unix=<today> with 72/73 fields
# null after ~12 days offline. Nothing was lost only because nothing had been
# captured yet. The restore side already has this protection
# (non_none_state_updates); the save side did not.


def test_merged_with_keeps_previous_value_when_the_new_one_is_none():
    from custom_components.dreame_a2_mower.state.last_known import LastKnown

    prev = LastKnown.from_dict({"blades_life_pct": 88, "wifi_ssid": "garden", "saved_unix": 1.0})
    # The mower is away: MowerState carries nothing.
    fresh = LastKnown.from_dict({"saved_unix": 2.0})

    merged = fresh.merged_with(prev)
    assert merged.blades_life_pct == 88, "a null fetch wiped the last-known value"
    assert merged.wifi_ssid == "garden"
    # The save time must be the NEW one — it records when we last looked.
    assert merged.saved_unix == 2.0


def test_merged_with_prefers_a_fresh_value_over_the_previous_one():
    from custom_components.dreame_a2_mower.state.last_known import LastKnown

    prev = LastKnown.from_dict({"blades_life_pct": 88, "saved_unix": 1.0})
    fresh = LastKnown.from_dict({"blades_life_pct": 41, "saved_unix": 2.0})
    assert fresh.merged_with(prev).blades_life_pct == 41


def test_merged_with_keeps_a_falsy_fresh_value():
    """0 / False / "" are REAL readings, not absences. A truthiness test here
    would resurrect a stale 88% blade life the moment the blades read 0."""
    from custom_components.dreame_a2_mower.state.last_known import LastKnown

    prev = LastKnown.from_dict({"blades_life_pct": 88, "dnd_enabled": True, "wifi_ssid": "garden"})
    fresh = LastKnown.from_dict({"blades_life_pct": 0, "dnd_enabled": False, "wifi_ssid": ""})
    merged = fresh.merged_with(prev)
    assert merged.blades_life_pct == 0
    assert merged.dnd_enabled is False
    assert merged.wifi_ssid == ""


def test_merged_with_no_previous_blob_is_a_noop():
    from custom_components.dreame_a2_mower.state.last_known import LastKnown

    fresh = LastKnown.from_dict({"blades_life_pct": 41, "saved_unix": 2.0})
    assert fresh.merged_with(None).blades_life_pct == 41


def test_merged_with_carries_active_map_id_across_a_null_fetch():
    """active_map_id is what lets the Overview live-map render offline — losing
    it to a null save is the whole reason the base map early-returns."""
    from custom_components.dreame_a2_mower.state.last_known import LastKnown

    prev = LastKnown.from_dict({"active_map_id": 3, "saved_unix": 1.0})
    fresh = LastKnown.from_dict({"saved_unix": 2.0})
    assert fresh.merged_with(prev).active_map_id == 3


def test_save_last_known_does_not_null_out_a_good_blob_when_the_mower_is_absent():
    """The regression this whole merge exists for, through the real save path.

    Sequence: mower online → values captured → mower leaves → the cloud fetch
    still SUCCEEDS (cloud is up) but carries no device data, so the refreshers
    call _save_last_known against an empty MowerState. Before the merge, that
    save wrote nulls over everything — erasing last-known at the exact moment
    the dashboard needed it.
    """
    from custom_components.dreame_a2_mower.coordinator._core import _CoreMixin
    from custom_components.dreame_a2_mower.state import MowerState
    from custom_components.dreame_a2_mower.state.last_known import LastKnown

    saved = []

    class _Store:
        def async_delay_save(self, fn, delay):
            saved.append(fn())

    c = object.__new__(_CoreMixin)
    c._last_known_store = _Store()
    c._active_map_id = 2
    c._last_known_saved_unix = None
    # As if the mower had been online: a good blob is already held.
    c._last_known_blob = LastKnown.from_dict(
        {"blades_life_pct": 88, "wifi_ssid": "garden", "active_map_id": 2, "saved_unix": 1.0}
    )
    # ...and now it's gone: MowerState carries nothing.
    c.data = MowerState()

    c._save_last_known()

    blob = saved[0]
    assert blob["blades_life_pct"] == 88, "an absent mower nulled out the last-known blob"
    assert blob["wifi_ssid"] == "garden"
    assert blob["active_map_id"] == 2
    assert blob["saved_unix"] != 1.0, "saved_unix should record when we last looked"


def test_save_last_known_captures_fresh_values_over_the_previous_blob():
    """The merge must not make the blob write-once — a real reading still wins."""
    from custom_components.dreame_a2_mower.coordinator._core import _CoreMixin
    from custom_components.dreame_a2_mower.state import MowerState
    from custom_components.dreame_a2_mower.state.last_known import LastKnown

    saved = []

    class _Store:
        def async_delay_save(self, fn, delay):
            saved.append(fn())

    c = object.__new__(_CoreMixin)
    c._last_known_store = _Store()
    c._active_map_id = 1
    c._last_known_saved_unix = None
    c._last_known_blob = LastKnown.from_dict({"blades_life_pct": 88, "saved_unix": 1.0})
    c.data = MowerState(blades_life_pct=41)

    c._save_last_known()
    assert saved[0]["blades_life_pct"] == 41
    # And the merged result becomes the base for the next save.
    assert c._last_known_blob.blades_life_pct == 41
