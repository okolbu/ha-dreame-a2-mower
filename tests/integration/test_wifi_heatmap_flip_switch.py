"""Tests for the WiFi-heatmap flip switches (R-15 / P5.1).

These integration-owned switches REPLACE the old dashboard-installed helpers
input_boolean.dreame_a2_mower_wifi_flip_x/y that the backend used to read
directly. They are LOCAL render preferences: toggling stores a bool on the
coordinator (coord.wifi_flip_x / coord.wifi_flip_y) that camera/wifi.py reads
at render time — NO cloud/device write — and broadcasts a coordinator update
so the wifi cameras re-render.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.dreame_a2_mower.control_honesty import ControlMode
from custom_components.dreame_a2_mower.entities.switch.global_ import (
    DreameA2WifiHeatmapFlipXSwitch,
    DreameA2WifiHeatmapFlipYSwitch,
)


def _make_coord(flip_x: bool = False, flip_y: bool = False) -> MagicMock:
    coord = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data.hardware_serial = None  # mower_unique_id falls back to entry_id
    coord.wifi_flip_x = flip_x
    coord.wifi_flip_y = flip_y
    return coord


def _make_switch(cls, coord):
    ent = cls(coord)
    ent.hass = MagicMock()
    # async_write_ha_state touches HA internals not present on a bare entity.
    ent.async_write_ha_state = MagicMock()
    return ent


class TestFlipSwitchMetadata:
    def test_axes_and_object_id_suffix(self):
        assert DreameA2WifiHeatmapFlipXSwitch._AXIS == "x"
        assert DreameA2WifiHeatmapFlipYSwitch._AXIS == "y"
        # entity_id is derived from the name slug.
        assert DreameA2WifiHeatmapFlipXSwitch._attr_name == "WiFi heatmap flip X"
        assert DreameA2WifiHeatmapFlipYSwitch._attr_name == "WiFi heatmap flip Y"

    def test_config_category_and_has_entity_name(self):
        from homeassistant.helpers.entity import EntityCategory
        assert DreameA2WifiHeatmapFlipXSwitch._attr_entity_category == EntityCategory.CONFIG
        assert DreameA2WifiHeatmapFlipXSwitch._attr_has_entity_name is True

    def test_control_mode_is_local(self):
        coord = _make_coord()
        ent = _make_switch(DreameA2WifiHeatmapFlipXSwitch, coord)
        # Local render preference — operable (not read-only) but not a wire write.
        assert ent.control_mode == ControlMode.INTEGRATION_LOCAL
        assert ent.read_only is False


class TestFlipSwitchReads:
    def test_is_on_reflects_coordinator_attr(self):
        ent_on = _make_switch(DreameA2WifiHeatmapFlipXSwitch, _make_coord(flip_x=True))
        ent_off = _make_switch(DreameA2WifiHeatmapFlipXSwitch, _make_coord(flip_x=False))
        assert ent_on.is_on is True
        assert ent_off.is_on is False

    def test_y_switch_reads_its_own_axis(self):
        coord = _make_coord(flip_x=True, flip_y=False)
        ent_y = _make_switch(DreameA2WifiHeatmapFlipYSwitch, coord)
        assert ent_y.is_on is False  # reads wifi_flip_y, not wifi_flip_x


class TestFlipSwitchWrites:
    @pytest.mark.asyncio
    async def test_turn_on_sets_attr_and_broadcasts(self):
        coord = _make_coord(flip_x=False)
        ent = _make_switch(DreameA2WifiHeatmapFlipXSwitch, coord)
        await ent.async_turn_on()
        assert coord.wifi_flip_x is True
        # Re-render trigger: a coordinator broadcast rotates the wifi cameras'
        # access_token (flip folded into their _handle_coordinator_update key).
        coord.async_update_listeners.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_off_sets_attr(self):
        coord = _make_coord(flip_y=True)
        ent = _make_switch(DreameA2WifiHeatmapFlipYSwitch, coord)
        await ent.async_turn_off()
        assert coord.wifi_flip_y is False
        coord.async_update_listeners.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_cloud_or_device_write(self):
        """Local render pref — must NOT issue any cloud/device write."""
        coord = _make_coord(flip_x=False)
        ent = _make_switch(DreameA2WifiHeatmapFlipXSwitch, coord)
        await ent.async_turn_on()
        # None of the coordinator write surfaces may be touched.
        coord.write_setting.assert_not_called()
        coord.write_settings.assert_not_called()
        coord.dispatch_action.assert_not_called()
        coord.write_ai_human_enabled.assert_not_called()
        assert not coord._cloud.method_calls


class TestFlipSwitchRestore:
    @pytest.mark.asyncio
    async def test_restore_on_from_last_state(self):
        coord = _make_coord(flip_x=False)
        ent = _make_switch(DreameA2WifiHeatmapFlipXSwitch, coord)
        restored = SimpleNamespace(state="on")
        with patch.object(
            ent, "async_get_last_state", AsyncMock(return_value=restored)
        ):
            await ent.async_added_to_hass()
        assert coord.wifi_flip_x is True

    @pytest.mark.asyncio
    async def test_restore_off_from_last_state(self):
        coord = _make_coord(flip_x=True)
        ent = _make_switch(DreameA2WifiHeatmapFlipXSwitch, coord)
        restored = SimpleNamespace(state="off")
        with patch.object(
            ent, "async_get_last_state", AsyncMock(return_value=restored)
        ):
            await ent.async_added_to_hass()
        assert coord.wifi_flip_x is False

    @pytest.mark.asyncio
    async def test_restore_ignores_unknown(self):
        coord = _make_coord(flip_x=True)
        ent = _make_switch(DreameA2WifiHeatmapFlipXSwitch, coord)
        restored = SimpleNamespace(state="unknown")
        with patch.object(
            ent, "async_get_last_state", AsyncMock(return_value=restored)
        ):
            await ent.async_added_to_hass()
        # Untouched — the pre-restore coordinator value stands.
        assert coord.wifi_flip_x is True

    @pytest.mark.asyncio
    async def test_restore_no_last_state(self):
        coord = _make_coord(flip_x=False)
        ent = _make_switch(DreameA2WifiHeatmapFlipXSwitch, coord)
        with patch.object(
            ent, "async_get_last_state", AsyncMock(return_value=None)
        ):
            await ent.async_added_to_hass()
        assert coord.wifi_flip_x is False


class TestFlipDrivesRender:
    @pytest.mark.asyncio
    async def test_camera_render_honours_flip_from_coordinator(self):
        """End-to-end: the switch's coord attr is what the camera passes to
        the renderer — proving the toggle flips the render orientation."""
        from custom_components.dreame_a2_mower.camera import (
            DreameA2WifiSelectedCamera,
        )

        body = {"data": [-50] * 16, "width": 4, "height": 4,
                "resolution": 2, "startX": 0, "startY": 0}
        coord = _make_coord(flip_x=False, flip_y=False)
        coord._wifi_render_entry = (None, "wifimap_1700000001.json")
        coord._get_wifi_body_cached = MagicMock(return_value=body)
        cam = DreameA2WifiSelectedCamera(coord)
        cam.hass = MagicMock()
        cam.hass.async_add_executor_job = AsyncMock(
            side_effect=lambda fn, *a, **kw: fn(*a, **kw)
        )

        # Flip the switch on via the switch entity, then render.
        flip_switch = _make_switch(DreameA2WifiHeatmapFlipXSwitch, coord)
        await flip_switch.async_turn_on()

        with patch(
            "custom_components.dreame_a2_mower.wifi.map_render.render_wifi_map_png"
        ) as mock_r:
            mock_r.return_value = b"\x89PNG"
            await cam.async_camera_image()
        assert mock_r.call_args.kwargs.get("flip_x") is True
        assert mock_r.call_args.kwargs.get("flip_y") is False
