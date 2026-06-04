"""HA service layer for start_point_patrol and start_edge_patrol.

Tests mirror the _handle_mow_spot idiom:
  - coordinator retrieved via _coordinator_from_call → call.hass.data[DOMAIN]
  - hass.services.async_call dispatches into the registered handler
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.dreame_a2_mower.const import DOMAIN


def _make_hass_with_coordinator():
    """Return a minimal hass stub with a coordinator wired into hass.data."""
    coord = MagicMock()
    coord.start_point_patrol = AsyncMock()
    coord.start_edge_patrol = AsyncMock()

    # _coordinator_from_call does:
    #   coordinators = hass.data.get(DOMAIN, {})
    #   return next(iter(coordinators.values()))
    hass = MagicMock()
    hass.data = {DOMAIN: {"entry_id": coord}}
    return hass, coord


async def test_start_point_patrol_service_calls_coordinator():
    """Calling start_point_patrol service dispatches coordinator.start_point_patrol."""
    from custom_components.dreame_a2_mower.services import (
        async_register_services,
        SERVICE_START_POINT_PATROL,
        SCHEMA_START_POINT_PATROL,
    )
    import homeassistant.core as ha_core

    hass, coord = _make_hass_with_coordinator()
    await async_register_services(hass)

    # Build a ServiceCall like the stub in conftest.py
    call = ha_core.ServiceCall(
        hass, DOMAIN, SERVICE_START_POINT_PATROL,
        data={"map_id": 0, "point_ids": [3, 4]},
    )

    # Find and invoke the registered handler directly
    registered = hass.services.async_register.call_args_list
    handler = None
    for call_args in registered:
        args, kwargs = call_args
        if args[1] == SERVICE_START_POINT_PATROL:
            handler = args[2]
            break
    assert handler is not None, "start_point_patrol handler was not registered"

    await handler(call)

    coord.start_point_patrol.assert_awaited_once_with(map_id=0, point_ids=[3, 4])


async def test_start_edge_patrol_service_calls_coordinator():
    """Calling start_edge_patrol service dispatches coordinator.start_edge_patrol."""
    from custom_components.dreame_a2_mower.services import (
        async_register_services,
        SERVICE_START_EDGE_PATROL,
        SCHEMA_START_EDGE_PATROL,
    )
    import homeassistant.core as ha_core

    hass, coord = _make_hass_with_coordinator()
    await async_register_services(hass)

    call = ha_core.ServiceCall(
        hass, DOMAIN, SERVICE_START_EDGE_PATROL,
        data={"map_id": 0, "contour_ids": [[1, 0]]},
    )

    registered = hass.services.async_register.call_args_list
    handler = None
    for call_args in registered:
        args, kwargs = call_args
        if args[1] == SERVICE_START_EDGE_PATROL:
            handler = args[2]
            break
    assert handler is not None, "start_edge_patrol handler was not registered"

    await handler(call)

    coord.start_edge_patrol.assert_awaited_once_with(map_id=0, contour_ids=[[1, 0]])


async def test_start_point_patrol_defaults_map_id_to_zero_when_absent():
    """map_id defaults to 0 (fallback) when omitted from the call."""
    from custom_components.dreame_a2_mower.services import (
        async_register_services,
        SERVICE_START_POINT_PATROL,
    )
    import homeassistant.core as ha_core

    hass, coord = _make_hass_with_coordinator()
    # No _active_map_id attribute on the MagicMock → getattr returns MagicMock falsy
    # We set it explicitly to None to test the fallback path.
    coord._active_map_id = None
    await async_register_services(hass)

    call = ha_core.ServiceCall(
        hass, DOMAIN, SERVICE_START_POINT_PATROL,
        data={"point_ids": [5]},
    )

    registered = hass.services.async_register.call_args_list
    handler = None
    for call_args in registered:
        args, kwargs = call_args
        if args[1] == SERVICE_START_POINT_PATROL:
            handler = args[2]
            break

    await handler(call)

    # map_id should default to 0
    coord.start_point_patrol.assert_awaited_once_with(map_id=0, point_ids=[5])


async def test_start_edge_patrol_defaults_map_id_to_zero_when_absent():
    """map_id defaults to 0 (fallback) when omitted from the call."""
    from custom_components.dreame_a2_mower.services import (
        async_register_services,
        SERVICE_START_EDGE_PATROL,
    )
    import homeassistant.core as ha_core

    hass, coord = _make_hass_with_coordinator()
    coord._active_map_id = None
    await async_register_services(hass)

    call = ha_core.ServiceCall(
        hass, DOMAIN, SERVICE_START_EDGE_PATROL,
        data={"contour_ids": [[2, 1]]},
    )

    registered = hass.services.async_register.call_args_list
    handler = None
    for call_args in registered:
        args, kwargs = call_args
        if args[1] == SERVICE_START_EDGE_PATROL:
            handler = args[2]
            break

    await handler(call)

    coord.start_edge_patrol.assert_awaited_once_with(map_id=0, contour_ids=[[2, 1]])
