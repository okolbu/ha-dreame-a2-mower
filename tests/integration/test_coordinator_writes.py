"""Tests for coordinator-level write helpers + mutex."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock


def test_coordinator_init_declares_chunked_write_lock():
    """Regex check that __init__ creates self._chunked_write_lock as Lock()."""
    # Refactor 2026-05-15: coordinator.py was split into coordinator/
    # package + _coordinator_legacy.py. The class body still lives in
    # the legacy file until task 12 of the decomposition completes.
    src = Path("custom_components/dreame_a2_mower/coordinator/_core.py").read_text()
    assert re.search(
        r"self\._chunked_write_lock\s*:\s*asyncio\.Lock\s*=\s*asyncio\.Lock\(\)",
        src,
    ), "coordinator.__init__ should declare self._chunked_write_lock"


def _make_coord_for_settings_write():
    """Build a coordinator stub with cloud_state.settings populated."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState, ScheduleData, SettingsRoot,
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._chunked_write_lock = asyncio.Lock()
    coord._cloud = MagicMock()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(True, {"code": 0, "success": True})
    )
    coord.hass = MagicMock()
    # Make hass.async_add_executor_job actually call the function inline.
    async def _run(fn, *a, **k):
        return fn(*a, **k)
    coord.hass.async_add_executor_job = lambda fn, *a: _run(fn, *a)
    raw = [
        {"mode": 0, "settings": {
            "0": {"mowingHeight": 5, "cutterPosition": 1},
            "1": {"mowingHeight": 6, "cutterPosition": 2},
        }},
        {"mode": 0, "settings": {
            "0": {"mowingHeight": 5, "cutterPosition": 1},
            "1": {"mowingHeight": 6, "cutterPosition": 2},
        }},
    ]
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=raw,
            by_map_id_canonical={
                0: raw[0]["settings"]["0"],
                1: raw[1]["settings"]["0"],
            },
        ),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={},
        mapl=None, mihis={}, fetched_at_unix=0,
    )
    async def _noop_refresh():
        return None
    coord._refresh_cloud_state = MagicMock(side_effect=lambda: _noop_refresh())
    return coord


def test_write_settings_targets_only_the_target_maps_general_slot():
    """write_settings RMWs ONLY the target map's general ('0') slot — top-level
    index is per-map (2026-06-19), so writing map 0 must NOT touch map 1's
    entry. Writing every entry (the old behaviour) clobbered other maps."""
    coord = _make_coord_for_settings_write()
    ok = asyncio.run(coord.write_settings(map_id=0, field="mowingHeight", value=7))
    assert ok is True
    args, _ = coord._cloud.write_chunked_key.call_args
    key_prefix, value = args[0], args[1]
    assert key_prefix == "SETTINGS"
    import json
    parsed = json.loads(value)
    # Target map (entry 0) general slot mutated.
    assert parsed[0]["settings"]["0"]["mowingHeight"] == 7
    # The OTHER map (entry 1) is untouched.
    assert parsed[1]["settings"]["0"]["mowingHeight"] == 5
    # Target map's own per-zone slot untouched.
    assert parsed[0]["settings"]["1"]["mowingHeight"] == 6


def test_write_settings_returns_false_on_cloud_rejection():
    coord = _make_coord_for_settings_write()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(False, {"code": 10007, "msg": "rejected"})
    )
    ok = asyncio.run(coord.write_settings(map_id=0, field="mowingHeight", value=7))
    assert ok is False


def test_write_settings_unknown_map_id_returns_false():
    coord = _make_coord_for_settings_write()
    ok = asyncio.run(coord.write_settings(map_id=99, field="mowingHeight", value=7))
    assert ok is False
    coord._cloud.write_chunked_key.assert_not_called()


def test_write_schedule_uses_device_plane_not_kv():
    """write_schedule routes through the SCHD*V3 routed-action transport
    (siid:2/aiid:50 via _cloud.action), NOT the device-ignored SCHEDULE.* KV.

    The KV write_chunked_key path was retired 2026-06-10 (the device ignores
    the SCHEDULE.* cache mirror; see dreame-app-schedule-write-2026-06-10.md).
    """
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState, ScheduleData, ScheduleSlot, SettingsRoot,
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._chunked_write_lock = asyncio.Lock()
    coord._cloud = MagicMock()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(True, {"code": 0, "success": True})
    )
    # _cloud.action is the routed-action callable; return a success envelope
    # for every leg (read probe + write legs).
    coord._cloud.action = MagicMock(
        return_value={"result": {"out": [{"m": "r", "r": 0, "d": {}}]}}
    )
    coord.hass = MagicMock()
    async def _run(fn, *a, **k):
        return fn(*a, **k)
    coord.hass.async_add_executor_job = lambda fn, *a: _run(fn, *a)
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=10, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={},
        mapl=None, mihis={}, fetched_at_unix=0,
    )
    # Stub _refresh_cloud_state with a coroutine factory (Py 3.14 compat).
    async def _stub_refresh():
        return None
    coord._refresh_cloud_state = MagicMock(side_effect=_stub_refresh)
    new_slots = (ScheduleSlot(slot_id=0, name="A", raw_blob_b64="", plans=()),)
    ok = asyncio.run(coord.write_schedule(new_slots))
    assert ok is True
    # KV path retired — never touched.
    coord._cloud.write_chunked_key.assert_not_called()
    # Routed-action transport used: a m:'g' SCHDIV3 live-read probe + the
    # write legs. The read is the chunked GET (SCHDIV3 header), not the retired
    # SCHDTV3 scalar.
    legs = [(c.args[2][0].get("m"), c.args[2][0]["t"]) for c in coord._cloud.action.call_args_list]
    ts = [t for _, t in legs]
    assert ("g", "SCHDIV3") in legs   # read-modify-write base (live-read header)
    assert ("s", "SCHDIV3") in legs   # write row header
    assert "SCHDSV3" in ts            # row state (version bump)
    assert "SCHDTV3" not in ts        # retired read probe


def test_write_ai_human_enabled_uses_write_chunked_key():
    """write_ai_human_enabled routes through write_chunked_key (not set_batch_device_datas)
    to pick up chunking + lock."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._chunked_write_lock = asyncio.Lock()
    coord._cloud = MagicMock()
    coord._cloud.write_chunked_key = MagicMock(
        return_value=(True, {"code": 0, "success": True})
    )
    coord.hass = MagicMock()
    async def _run(fn, *a, **k):
        return fn(*a, **k)
    coord.hass.async_add_executor_job = lambda fn, *a: _run(fn, *a)
    async def _stub_refresh():
        return None
    coord._refresh_cloud_state = MagicMock(side_effect=_stub_refresh)
    asyncio.run(coord.write_ai_human_enabled(True))
    coord._cloud.write_chunked_key.assert_called_once_with("AI_HUMAN", '"true"')


def _make_coord_for_firmware_update():
    """Build a minimal coordinator stub for async_trigger_firmware_update tests."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._cloud = MagicMock()
    coord.hass = MagicMock()
    async def _run(fn, *a, **k):
        return fn(*a, **k)
    coord.hass.async_add_executor_job = lambda fn, *a: _run(fn, *a)
    return coord


def test_trigger_firmware_update_returns_device_decision():
    """async_trigger_firmware_update returns the device's bool decision."""
    coord = _make_coord_for_firmware_update()

    coord._cloud.trigger_firmware_update = MagicMock(return_value=True)
    assert asyncio.run(coord.async_trigger_firmware_update()) is True

    coord._cloud.trigger_firmware_update = MagicMock(return_value=False)
    assert asyncio.run(coord.async_trigger_firmware_update()) is False


def test_trigger_firmware_update_no_cloud_returns_false():
    """async_trigger_firmware_update returns False without raising when _cloud absent."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.hass = MagicMock()
    # _cloud intentionally absent
    assert asyncio.run(coord.async_trigger_firmware_update()) is False
