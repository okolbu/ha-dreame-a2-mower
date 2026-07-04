"""Pin the P4.5 v2 entity RENAMES (track-5 T5-11 / R-64).

The v2 refactor intentionally broke a set of entity_ids by changing their
descriptor *names* (HA derives ``object_id`` from the name slug when
``has_entity_name=True``; the descriptor *key* only drives ``unique_id``).
This test pins BOTH sides of every rename:

  * the descriptor ``name`` (what we control), and
  * the resulting name-derived ``object_id`` (what HA generates).

If a future edit reverts a name or drifts an object_id off the v2 canonical
surface, this fails loudly — the rename surface has no other schema pin
(``test_card_contract`` pins attribute shapes, ``test_per_map_entity_names``
pins per-map entities, neither of which are the renamed parent-device set).

``unique_id`` is NOT changed by any rename — the registry keeps entity
identity (recorder history survives); only ``object_id`` moves. New live
object_ids are swept in P4.7 (the old ids become registry orphans).
"""
from __future__ import annotations

import re

DEVICE_NAME = "Dreame A2 Mower"


def _object_id(entity_name: str) -> str:
    """HA-equivalent object_id for a has_entity_name parent-device entity.

    Mirrors homeassistant.util.slugify over ``f"{device_name} {entity_name}"``
    (lowercase; every non-[a-z0-9] run → single "_"; strip). ASCII + the
    em-dash / "+" cases used below all reduce the same way HA does.
    """
    raw = f"{DEVICE_NAME} {entity_name}".lower()
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_")


def _desc_by_key(table, key):
    for d in table:
        if d.key == key:
            return d
    raise AssertionError(f"descriptor key {key!r} not found in table")


# (descriptor-name, expected v2 object_id) — the canonical v2 surface.
_EXPECTED = {
    # cameras
    "camera_live_map": ("Live map", "dreame_a2_mower_live_map"),
    "camera_session_replay": ("Session replay", "dreame_a2_mower_session_replay"),
    "camera_obstacle": (
        "Latest obstacle capture", "dreame_a2_mower_latest_obstacle_capture",
    ),
    # select
    "select_session_replay": ("Session replay", "dreame_a2_mower_session_replay"),
    "select_lcd": ("LCD language", "dreame_a2_mower_lcd_language"),
    # switch — msg_alert
    "msg_alert_anomaly": ("Anomaly notifications", "dreame_a2_mower_anomaly_notifications"),
    "msg_alert_error": ("Error notifications", "dreame_a2_mower_error_notifications"),
    "msg_alert_task": ("Task notifications", "dreame_a2_mower_task_notifications"),
    "msg_alert_consumables": (
        "Consumables notifications", "dreame_a2_mower_consumables_notifications",
    ),
    # switch — voice
    "voice_regular_notification": (
        "Voice prompt — Regular notification",
        "dreame_a2_mower_voice_prompt_regular_notification",
    ),
    "voice_work_status": (
        "Voice prompt — Work status", "dreame_a2_mower_voice_prompt_work_status",
    ),
    "voice_special_status": (
        "Voice prompt — Special status", "dreame_a2_mower_voice_prompt_special_status",
    ),
    "voice_error_status": (
        "Voice prompt — Error status", "dreame_a2_mower_voice_prompt_error_status",
    ),
    # binary_sensor — human presence (4 scenario ids UNCHANGED; only display name)
    "hp_standby": (
        "Human presence scenario — standby",
        "dreame_a2_mower_human_presence_scenario_standby",
    ),
    "hp_mowing": (
        "Human presence scenario — mowing",
        "dreame_a2_mower_human_presence_scenario_mowing",
    ),
    "hp_recharge": (
        "Human presence scenario — recharge",
        "dreame_a2_mower_human_presence_scenario_recharge",
    ),
    "hp_patrol": (
        "Human presence scenario — patrol",
        "dreame_a2_mower_human_presence_scenario_patrol",
    ),
    "hp_voice": (
        "Human presence voice and push alert",
        "dreame_a2_mower_human_presence_voice_and_push_alert",
    ),
    # sensor
    "latest_video": ("Latest video duration", "dreame_a2_mower_latest_video_duration"),
}


def _check(tag: str, name: str) -> None:
    exp_name, exp_oid = _EXPECTED[tag]
    assert name == exp_name, f"{tag}: name {name!r} != v2 {exp_name!r}"
    assert _object_id(name) == exp_oid, (
        f"{tag}: object_id {_object_id(name)!r} != v2 {exp_oid!r}"
    )


def test_object_id_slug_helper_sanity():
    # Guard the helper itself: colon and "+" both collapse to a single "_".
    assert _object_id("Notification: Anomaly messages") == (
        "dreame_a2_mower_notification_anomaly_messages"
    )
    assert _object_id("Human presence voice + push alert") == (
        "dreame_a2_mower_human_presence_voice_push_alert"
    )


def test_camera_renames():
    from custom_components.dreame_a2_mower.camera.map import (
        DreameA2MapCamera, DreameA2WorkLogCamera,
    )
    from custom_components.dreame_a2_mower.camera.photos import (
        DreameA2ObstaclePhotoCamera,
    )

    _check("camera_live_map", DreameA2MapCamera._attr_name)
    _check("camera_session_replay", DreameA2WorkLogCamera._attr_name)
    _check("camera_obstacle", DreameA2ObstaclePhotoCamera._attr_name)


def test_select_renames():
    from custom_components.dreame_a2_mower.entities.select.global_ import (
        DreameA2WorkLogSelect, SETTING_SELECTS,
    )

    _check("select_session_replay", DreameA2WorkLogSelect._attr_name)
    _check("select_lcd", _desc_by_key(SETTING_SELECTS, "lcd_language").name)


def test_switch_renames():
    from custom_components.dreame_a2_mower.entities.switch.global_ import SWITCHES

    for tag, key in (
        ("msg_alert_anomaly", "msg_alert_anomaly"),
        ("msg_alert_error", "msg_alert_error"),
        ("msg_alert_task", "msg_alert_task"),
        ("msg_alert_consumables", "msg_alert_consumables"),
        ("voice_regular_notification", "voice_regular_notification"),
        ("voice_work_status", "voice_work_status"),
        ("voice_special_status", "voice_special_status"),
        ("voice_error_status", "voice_error_status"),
    ):
        _check(tag, _desc_by_key(SWITCHES, key).name)


def test_binary_sensor_human_presence_renames():
    from custom_components.dreame_a2_mower.binary_sensor import BINARY_SENSORS

    for tag, key in (
        ("hp_standby", "human_presence_scenario_standby"),
        ("hp_mowing", "human_presence_scenario_mowing"),
        ("hp_recharge", "human_presence_scenario_recharge"),
        ("hp_patrol", "human_presence_scenario_patrol"),
        ("hp_voice", "human_presence_alert_voice"),
    ):
        _check(tag, _desc_by_key(BINARY_SENSORS, key).name)


def test_sensor_latest_video_rename():
    from custom_components.dreame_a2_mower.entities.sensor.device import (
        DIAGNOSTIC_SENSORS,
    )

    _check("latest_video", _desc_by_key(DIAGNOSTIC_SENSORS, "latest_video").name)
