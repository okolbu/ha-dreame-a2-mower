"""Coordinator writes-service tests: write_setting + dispatch(edge-mow).

Split out of the test_coordinator.py monolith (P3.11); tests moved verbatim.
"""
from __future__ import annotations

import asyncio

from unittest.mock import MagicMock
from custom_components.dreame_a2_mower.state import MowerState
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from tests.integration._coordinator_helpers import (
    _make_coordinator_for_finalize_tests,
    _make_coordinator_with_cloud,
    _make_dispatch_coord_with_map,
)


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
