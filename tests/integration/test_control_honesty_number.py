"""Integration tests for control-honesty markers on the number platform.

Verifies:
- Per-map settings number (DreameA2PerMapMowingHeightNumber) is now
  device_writable (Task 10): read_only=False, no padlock icon, and
  async_set_native_value DOES call _settings_optimistic_write.
- The "volume" DreameA2Number is read_only=False and async_set_native_value
  DOES call coordinator.write_setting.
- human_presence_alert_sensitivity is now read_only=False (device_writable, Task 8).
- DreameA2TrailRenderWidthNumber is read_only=False and
  extra_state_attributes["control_mode"] == "integration_local";
  a set still executes normally (not snapped back).
"""
from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.number import (

    DreameA2Number,
    DreameA2PerMapMowingHeightNumber,
    DreameA2TrailRenderWidthNumber,
    NUMBERS,
)

from custom_components.dreame_a2_mower.cloud_client import WriteResult as _WR

# P2 Task 5: the coordinator write families return WriteResult, not bool.
_WR_ACCEPTED = _WR(delivered=True, accepted=True, code=0)
_WR_REJECTED = _WR(delivered=True, accepted=False, code=-3, msg="not supported")


_MAP_ID = 0


def _make_mower_coord(**state_kwargs):
    """Minimal coordinator stub for mower-scoped number entities."""
    coord = MagicMock()
    coord.entry.entry_id = "test_entry"
    state = dataclasses.replace(MowerState(), **state_kwargs)
    coord.data = state
    return coord


def _make_map_coord(*, settings_by_map=None):
    """Minimal coordinator stub for per-map number entities."""
    coord = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MowerState()
    cs = MagicMock()
    cs.maps_by_id = {_MAP_ID: MagicMock(name="Front")}
    cs.settings.by_map_id_canonical = settings_by_map or {_MAP_ID: {"mowingHeight": 5}}
    coord.cloud_state = cs
    return coord


def _number_desc(key: str):
    """Find a number descriptor by key."""
    for d in NUMBERS:
        if d.key == key:
            return d
    raise KeyError(key)


# ---------------------------------------------------------------------------
# Per-map settings number: DreameA2PerMapMowingHeightNumber (device_writable since Task 10)
# ---------------------------------------------------------------------------

def test_per_map_mowing_height_is_not_read_only():
    coord = _make_map_coord()
    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=_MAP_ID)
    assert ent.read_only is False


def test_per_map_mowing_height_has_no_padlock_icon():
    coord = _make_map_coord()
    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=_MAP_ID)
    assert ent.icon != "mdi:lock-outline"


def test_per_map_mowing_height_extra_attrs_mark_writable():
    coord = _make_map_coord()
    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=_MAP_ID)
    attrs = ent.extra_state_attributes
    assert attrs["read_only"] is False
    assert attrs["control_mode"] == "device_writable"


def test_per_map_mowing_height_set_value_calls_pre_settings_write():
    """async_set_native_value on the now-writable per-map number MUST call
    _pre_settings_optimistic_write (PRE dual-write path)."""
    coord = _make_map_coord()
    coord.write_map_general_setting = AsyncMock(return_value=_WR_ACCEPTED)
    ent = DreameA2PerMapMowingHeightNumber(coord, map_id=_MAP_ID)
    ent.async_write_ha_state = MagicMock()

    with patch(
        "custom_components.dreame_a2_mower.number._pre_settings_optimistic_write",
        new_callable=AsyncMock,
    ) as mock_opt_write:
        asyncio.run(ent.async_set_native_value(4.0))

    mock_opt_write.assert_called_once()


# ---------------------------------------------------------------------------
# DreameA2Number: volume (writable)
# ---------------------------------------------------------------------------

def test_volume_number_is_not_read_only():
    coord = _make_mower_coord(volume_pct=50)
    ent = DreameA2Number(coord, _number_desc("volume"))
    assert ent.read_only is False


def test_volume_number_extra_attrs_control_mode():
    coord = _make_mower_coord(volume_pct=50)
    ent = DreameA2Number(coord, _number_desc("volume"))
    attrs = ent.extra_state_attributes
    assert attrs["control_mode"] == "device_writable"
    assert attrs["read_only"] is False


def test_volume_number_set_value_calls_write_setting():
    """async_set_native_value on the volume number MUST call coordinator.write_setting."""
    coord = _make_mower_coord(volume_pct=50)
    coord.write_setting = AsyncMock(return_value=_WR_ACCEPTED)
    ent = DreameA2Number(coord, _number_desc("volume"))
    ent.async_write_ha_state = MagicMock()

    asyncio.run(ent.async_set_native_value(75.0))

    coord.write_setting.assert_called_once()


# ---------------------------------------------------------------------------
# DreameA2Number: human_presence_alert_sensitivity (device_writable, Task 8)
# ---------------------------------------------------------------------------

def test_human_presence_alert_sensitivity_is_not_read_only():
    coord = _make_mower_coord(human_presence_alert_sensitivity=1)
    ent = DreameA2Number(coord, _number_desc("human_presence_alert_sensitivity"))
    assert ent.read_only is False


def test_human_presence_alert_sensitivity_has_no_padlock_icon():
    coord = _make_mower_coord(human_presence_alert_sensitivity=1)
    ent = DreameA2Number(coord, _number_desc("human_presence_alert_sensitivity"))
    assert ent.icon != "mdi:lock-outline"


def test_human_presence_alert_sensitivity_extra_attrs_mark_writable():
    coord = _make_mower_coord(human_presence_alert_sensitivity=1)
    ent = DreameA2Number(coord, _number_desc("human_presence_alert_sensitivity"))
    attrs = ent.extra_state_attributes
    assert attrs["read_only"] is False
    assert attrs["control_mode"] == "device_writable"


# ---------------------------------------------------------------------------
# DreameA2TrailRenderWidthNumber: integration_local, no write guard
# ---------------------------------------------------------------------------

def test_trail_render_width_is_not_read_only():
    coord = _make_mower_coord(trail_render_width=24)
    ent = DreameA2TrailRenderWidthNumber(coord)
    assert ent.read_only is False


def test_trail_render_width_extra_attrs_control_mode():
    coord = _make_mower_coord(trail_render_width=24)
    ent = DreameA2TrailRenderWidthNumber(coord)
    attrs = ent.extra_state_attributes
    assert attrs["control_mode"] == "integration_local"
    assert attrs["read_only"] is False


def test_trail_render_width_set_value_not_snapped_back():
    """DreameA2TrailRenderWidthNumber.async_set_native_value must proceed
    normally — it must NOT call async_write_ha_state as a snap-back without
    actually updating the state."""
    coord = _make_mower_coord(trail_render_width=24)
    coord._render_base = AsyncMock()
    coord.render_base = coord._render_base
    coord._picked_session_summary = None
    coord.picked_session_summary = None
    ent = DreameA2TrailRenderWidthNumber(coord)

    captured: list[MowerState] = []

    def _capture(new_state):
        captured.append(new_state)

    coord.async_set_updated_data.side_effect = _capture

    asyncio.run(ent.async_set_native_value(10.0))

    # Must have updated the mower state (not snapped back)
    assert len(captured) == 1
    assert captured[0].trail_render_width == 10
