"""Tests for coordinator-level write helpers + mutex."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.state import MowerState
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from tests.integration._coordinator_helpers import (
    _make_coordinator_for_finalize_tests,
    _make_coordinator_with_cloud,
    _make_dispatch_coord_with_map,
)


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
    from custom_components.dreame_a2_mower.state.cloud_state import (
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
    assert ok.accepted is True
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
    result = asyncio.run(coord.write_settings(map_id=0, field="mowingHeight", value=7))
    # Cloud KV rejection → delivered-but-not-accepted, carrying the cloud code.
    assert result.accepted is False
    assert result.delivered is True and result.code == 10007


def test_write_settings_unknown_map_id_returns_false():
    coord = _make_coord_for_settings_write()
    result = asyncio.run(coord.write_settings(map_id=99, field="mowingHeight", value=7))
    # Local precondition abort (nothing sent) → not delivered.
    assert result.accepted is False and result.delivered is False
    coord._cloud.write_chunked_key.assert_not_called()


def test_write_schedule_uses_device_plane_not_kv():
    """write_schedule routes through the SCHD*V3 routed-action transport
    (siid:2/aiid:50 via _cloud.action), NOT the device-ignored SCHEDULE.* KV.

    The KV write_chunked_key path was retired 2026-06-10 (the device ignores
    the SCHEDULE.* cache mirror; see dreame-app-schedule-write-2026-06-10.md).
    """
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.state.cloud_state import (
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
    assert ok.accepted is True
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


# ---------------------------------------------------------------------------
# write_setting + dispatch(edge-mow) tests — moved verbatim from the
# test_coordinator.py monolith (P3.11 split).
# ---------------------------------------------------------------------------


def test_write_setting_cls_success():
    """write_setting('CLS', True) calls cloud.set_cfg and returns accepted."""
    coord = _make_coordinator_with_cloud(set_cfg_return=True)
    result = asyncio.run(coord.write_setting("CLS", True))
    assert result.accepted is True
    coord._cloud.set_cfg.assert_called_once_with("CLS", True)


def test_write_setting_vol_success():
    """write_setting('VOL', 80) calls cloud.set_cfg('VOL', 80)."""
    coord = _make_coordinator_with_cloud(set_cfg_return=True)
    result = asyncio.run(coord.write_setting("VOL", 80))
    assert result.accepted is True
    coord._cloud.set_cfg.assert_called_once_with("VOL", 80)


def test_write_setting_dnd_full_array():
    """write_setting('DND', [1, 1320, 420]) calls set_cfg with the full list."""
    coord = _make_coordinator_with_cloud(set_cfg_return=True)
    dnd_value = [1, 1320, 420]
    result = asyncio.run(coord.write_setting("DND", dnd_value))
    assert result.accepted is True
    coord._cloud.set_cfg.assert_called_once_with("DND", dnd_value)


def test_write_setting_pre_uses_set_pre():
    """write_setting('PRE', [...]) delegates to cloud.set_pre, not set_cfg."""
    coord = _make_coordinator_with_cloud(set_pre_return=True)
    pre_array = [0, 1, 50, 0, 0, 0, 0, 0, True, False]
    result = asyncio.run(coord.write_setting("PRE", pre_array))
    assert result.accepted is True
    coord._cloud.set_pre.assert_called_once_with(pre_array)
    coord._cloud.set_cfg.assert_not_called()


def test_write_setting_unknown_key_returns_false():
    """write_setting with an unrecognised cfg_key returns False without calling cloud."""
    coord = _make_coordinator_with_cloud()
    result = asyncio.run(coord.write_setting("BOGUS", 42))
    assert result.accepted is False and result.delivered is False
    coord._cloud.set_cfg.assert_not_called()
    coord._cloud.set_pre.assert_not_called()


def test_write_setting_no_cloud_returns_false():
    """write_setting returns False immediately when cloud client is not ready."""
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.logger = MagicMock()
    coord.hass = MagicMock()
    coord.async_set_updated_data = MagicMock()
    # No _cloud attribute — simulates pre-init state.
    result = asyncio.run(coord.write_setting("CLS", True))
    assert result.accepted is False and result.delivered is False


def test_write_setting_optimistic_update_applied_on_success():
    """field_updates are applied to MowerState before the cloud call."""
    coord = _make_coordinator_with_cloud(set_cfg_return=True)
    assert coord.data.child_lock_enabled is None

    result = asyncio.run(
        coord.write_setting("CLS", True, field_updates={"child_lock_enabled": True})
    )
    assert result.accepted is True
    assert coord.data.child_lock_enabled is True


def test_write_setting_optimistic_update_reverted_on_failure():
    """field_updates are reverted when the device rejects the write."""
    coord = _make_coordinator_with_cloud(set_cfg_return=False)
    assert coord.data.child_lock_enabled is None

    result = asyncio.run(
        coord.write_setting("CLS", True, field_updates={"child_lock_enabled": True})
    )
    # The device's rejection code survives to the caller (surfacing layer).
    assert result.accepted is False and result.code == -3
    # State reverted — child_lock_enabled should be back to None.
    assert coord.data.child_lock_enabled is None


def test_write_setting_revert_preserves_concurrent_update():
    """Per-field revert: a concurrent update to another field survives a rejected
    write's revert (the old whole-snapshot revert clobbered it — P2 inherit)."""
    import dataclasses
    coord = _make_coordinator_with_cloud(set_cfg_return=False)
    assert coord.data.child_lock_enabled is None
    assert coord.data.battery_level is None

    def _set_cfg(cfg_key, value):
        # Simulate an MQTT push landing between the optimistic apply and the
        # cloud rejection: it updates a DIFFERENT field concurrently.
        coord.data = dataclasses.replace(coord.data, battery_level=42)
        from custom_components.dreame_a2_mower.cloud_client import WriteResult
        return WriteResult(delivered=True, accepted=False, code=-3, msg="rejected")

    coord._cloud.set_cfg.side_effect = _set_cfg

    result = asyncio.run(
        coord.write_setting("CLS", True, field_updates={"child_lock_enabled": True})
    )
    assert result.accepted is False
    # The optimistically-set field reverted.
    assert coord.data.child_lock_enabled is None
    # The concurrent update to a DIFFERENT field is NOT clobbered.
    assert coord.data.battery_level == 42


def test_write_setting_no_revert_when_field_concurrently_overwritten():
    """If a concurrent writer overwrote the SAME field, revert leaves it alone."""
    import dataclasses
    coord = _make_coordinator_with_cloud(set_cfg_return=False)

    def _set_cfg(cfg_key, value):
        # Concurrent writer sets our own field to a third value.
        coord.data = dataclasses.replace(coord.data, child_lock_enabled=False)
        from custom_components.dreame_a2_mower.cloud_client import WriteResult
        return WriteResult(delivered=True, accepted=False, code=-3, msg="rejected")

    coord._cloud.set_cfg.side_effect = _set_cfg

    result = asyncio.run(
        coord.write_setting("CLS", True, field_updates={"child_lock_enabled": True})
    )
    assert result.accepted is False
    # Our optimistic value (True) was overwritten to False by the concurrent
    # writer; per-field revert must NOT stomp that back to the prior None.
    assert coord.data.child_lock_enabled is False


def test_write_setting_all_cfg_keys_accepted():
    """All documented CFG keys are accepted (no unknown-key warning)."""
    known_keys = ["CLS", "VOL", "LANG", "DND", "WRP", "LOW", "BAT", "LIT", "ATA", "REC"]
    for key in known_keys:
        coord = _make_coordinator_with_cloud(set_cfg_return=True)
        result = asyncio.run(coord.write_setting(key, "dummy_value"))
        assert result.accepted is True, f"Expected accepted for key {key!r}"


def test_write_setting_pre_non_list_returns_false():
    """write_setting('PRE', non-list) returns False without calling set_pre."""
    coord = _make_coordinator_with_cloud()
    result = asyncio.run(coord.write_setting("PRE", {"not": "a list"}))
    assert result.accepted is False and result.delivered is False
    coord._cloud.set_pre.assert_not_called()


def test_dispatch_edge_mow_defaults_to_all_outer_perimeters_single_zone():
    """One zone with [(1, 0), (1, 1)] → only [1, 0] is sent (sub-zone seam skipped)."""
    import asyncio
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _make_dispatch_coord_with_map([(1, 0), (1, 1)])
    asyncio.run(coord.dispatch_action(MowerAction.START_EDGE_MOW, {}))

    coord._cloud.routed_action.assert_called_once()
    op, extra = coord._cloud.routed_action.call_args.args
    assert op == 101
    assert extra == {"edge": [[1, 0]]}


def test_dispatch_edge_mow_defaults_to_all_outer_perimeters_multi_zone():
    """Multi-zone lawn → every zone's [N, 0] outer contour is sent."""
    import asyncio
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _make_dispatch_coord_with_map(
        [(1, 0), (1, 1), (2, 0), (3, 0), (3, 1)]
    )
    asyncio.run(coord.dispatch_action(MowerAction.START_EDGE_MOW, {}))

    coord._cloud.routed_action.assert_called_once()
    op, extra = coord._cloud.routed_action.call_args.args
    assert op == 101
    # Outer-perimeter contours only — seams (1,1) and (3,1) excluded.
    assert extra == {"edge": [[1, 0], [2, 0], [3, 0]]}


def test_dispatch_edge_mow_explicit_contours_passed_through():
    """User-specified contour_ids bypass the default-all-outer logic."""
    import asyncio
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _make_dispatch_coord_with_map([(1, 0), (2, 0), (3, 0)])
    asyncio.run(
        coord.dispatch_action(
            MowerAction.START_EDGE_MOW, {"contour_ids": [[2, 0]]}
        )
    )

    coord._cloud.routed_action.assert_called_once()
    op, extra = coord._cloud.routed_action.call_args.args
    assert op == 101
    assert extra == {"edge": [[2, 0]]}


def test_dispatch_edge_mow_no_map_data_falls_back_to_safe_default():
    """When cloud_state.maps_by_id has no active map, falls back to [[1, 0]] safety net."""
    import asyncio
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord._cloud.routed_action = MagicMock()

    asyncio.run(coord.dispatch_action(MowerAction.START_EDGE_MOW, {}))

    coord._cloud.routed_action.assert_called_once()
    op, extra = coord._cloud.routed_action.call_args.args
    assert op == 101
    assert extra == {"edge": [[1, 0]]}
