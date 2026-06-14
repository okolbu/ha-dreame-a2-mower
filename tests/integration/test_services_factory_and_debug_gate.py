"""P2 sub-task 2.5: service-handler factory + debug-service gating.

These tests pin the refactor's invariants:
  * the @service_handler-wrapped handlers resolve the coordinator via
    ``_coordinator_from_call`` and short-circuit (no body run) when it's None,
    exactly as the old inline preamble did;
  * the two debug services are NOT registered when the debug option is OFF
    (the default) and ARE registered when it's ON.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dreame_a2_mower import services
from custom_components.dreame_a2_mower.const import (
    CONF_DEBUG_SERVICES,
    DOMAIN,
)


# ---------------------------------------------------------------------------
# Factory: coordinator resolution + None short-circuit
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "handler_name, data",
    [
        ("_handle_refresh_cloud_state", {}),
        ("_handle_rename_zone", {"map_id": 0, "zone": 1, "name": "x"}),
        ("_handle_mow_zone", {"zone_ids": [1]}),
    ],
)
async def test_handler_short_circuits_when_no_coordinator(monkeypatch, handler_name, data):
    """When _coordinator_from_call returns None the handler must no-op:
    the body never runs (no coordinator method touched, no raise)."""
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: None)
    handler = getattr(services, handler_name)
    call = SimpleNamespace(hass=SimpleNamespace(), data=data)
    # Must return cleanly without raising.
    assert await handler(call) is None


async def test_handler_resolves_and_passes_coordinator(monkeypatch):
    """A wrapped handler runs its body with the resolved coordinator."""
    coord = SimpleNamespace(
        rename_zone=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(hass=SimpleNamespace(), data={"map_id": 2, "zone": 5, "name": "Lawn"})
    await services._handle_rename_zone(call)
    coord.rename_zone.assert_awaited_once_with(2, 5, "Lawn")


async def test_refresh_cloud_state_runs_body(monkeypatch):
    """refresh_cloud_state forwards to coordinator._refresh_cloud_state."""
    coord = SimpleNamespace(_refresh_cloud_state=AsyncMock())
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(hass=SimpleNamespace(), data={})
    await services._handle_refresh_cloud_state(call)
    coord._refresh_cloud_state.assert_awaited_once()


async def test_map_edit_helper_swallows_value_error(monkeypatch):
    """The shared map-edit helper logs + swallows ValueError (no raise)."""
    coord = SimpleNamespace(merge_zones=AsyncMock(side_effect=ValueError("bad")))
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(hass=SimpleNamespace(), data={"map_id": 0, "zones": [1, 2]})
    # Must NOT raise.
    await services._handle_merge_zones(call)


# ---------------------------------------------------------------------------
# Debug-service gating
# ---------------------------------------------------------------------------
def _registered_service_names(hass):
    return {
        call_args.args[1]
        for call_args in hass.services.async_register.call_args_list
    }


def _hass_stub():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    return hass


async def test_debug_services_not_registered_by_default():
    """No entry / option OFF → the two debug services are NOT registered."""
    hass = _hass_stub()
    await services.async_register_services(hass)
    names = _registered_service_names(hass)
    assert services.SERVICE_DUMP_MAP_DIAGNOSTICS not in names
    assert services.SERVICE_DISCOVER_CLOUD_API not in names
    # A normal (non-debug) service is still registered.
    assert services.SERVICE_MOW_ZONE in names


async def test_debug_services_not_registered_when_option_off():
    """Explicit debug_services=False entry → still not registered."""
    hass = _hass_stub()
    entry = SimpleNamespace(options={CONF_DEBUG_SERVICES: False})
    await services.async_register_services(hass, entry)
    names = _registered_service_names(hass)
    assert services.SERVICE_DUMP_MAP_DIAGNOSTICS not in names
    assert services.SERVICE_DISCOVER_CLOUD_API not in names


async def test_debug_services_registered_when_option_on():
    """debug_services=True entry → both debug services registered."""
    hass = _hass_stub()
    entry = SimpleNamespace(options={CONF_DEBUG_SERVICES: True})
    await services.async_register_services(hass, entry)
    names = _registered_service_names(hass)
    assert services.SERVICE_DUMP_MAP_DIAGNOSTICS in names
    assert services.SERVICE_DISCOVER_CLOUD_API in names


async def test_reconcile_adds_and_removes_debug_services():
    """async_reconcile_debug_services adds when ON, removes when OFF."""
    # ON: not yet registered → registers both.
    hass = _hass_stub()
    hass.services.has_service.return_value = False
    entry_on = SimpleNamespace(options={CONF_DEBUG_SERVICES: True})
    services.async_reconcile_debug_services(hass, entry_on)
    names = _registered_service_names(hass)
    assert services.SERVICE_DUMP_MAP_DIAGNOSTICS in names
    assert services.SERVICE_DISCOVER_CLOUD_API in names

    # OFF: removes both.
    hass2 = _hass_stub()
    entry_off = SimpleNamespace(options={CONF_DEBUG_SERVICES: False})
    services.async_reconcile_debug_services(hass2, entry_off)
    removed = {ca.args[1] for ca in hass2.services.async_remove.call_args_list}
    assert services.SERVICE_DUMP_MAP_DIAGNOSTICS in removed
    assert services.SERVICE_DISCOVER_CLOUD_API in removed


async def test_unregister_handles_absent_debug_services():
    """async_unregister_services removes every service including the gated-OFF
    debug ones (async_remove is a no-op when absent)."""
    hass = _hass_stub()
    services.async_unregister_services(hass)
    removed = {ca.args[1] for ca in hass.services.async_remove.call_args_list}
    # All declared services attempted, incl. the two debug ones.
    assert services.SERVICE_DUMP_MAP_DIAGNOSTICS in removed
    assert services.SERVICE_DISCOVER_CLOUD_API in removed
    assert services.SERVICE_MOW_ZONE in removed
