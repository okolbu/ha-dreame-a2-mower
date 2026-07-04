"""P2 Task 5 (R-35): write honesty end-to-end for the CFG / PRE / SETTINGS /
schedule / map-edit families.

For EACH family this file proves BOTH directions of the seam:

  - device/cloud REJECTION → the entity handler raises HomeAssistantError
    (entity context) or the service handler raises ServiceValidationError
    (service context, delivered-but-rejected) / retryable HomeAssistantError
    (not delivered);
  - ACCEPTANCE → no raise AND the positive post-condition holds (write
    dispatched with the right payload / optimistic state applied).

Rejection shapes are the real wire verdicts, not invented ones:

  - CFG/PRE routed-action writes: ``out[0].r = -3`` — the device's "no setter
    for THIS key at THIS address" verdict (see ``inventory.yaml``
    § READ/WRITE SURFACES note 1; the s2.50 setter envelope is § CFG).
  - SETTINGS/AI_HUMAN chunked-KV writes: the CLOUD's non-zero result code on
    iotuserdata setDeviceData (§ READ/WRITE SURFACES item 3 — this transport
    carries no per-write device verdict; the cloud record IS the store).
  - Schedule (SCHD*V3, § SCHDIV3/SCHDDV3/SCHDSV3): a failing leg raises
    CfgActionError through ``_unwrap``; with a device code → rejected,
    without → not-delivered.
  - Map-edit (o=200/204/…/201 transaction, § o204/§ o201/§ o215): the first
    not-accepted leg's WriteResult is the transaction verdict.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.dreame_a2_mower import services
from custom_components.dreame_a2_mower.cloud_client import WriteResult
from custom_components.dreame_a2_mower.control_honesty import ControlMode
from custom_components.dreame_a2_mower.state import MowerState

# The honest verdict shapes (mirrors what the real transports return).
_ACCEPTED = WriteResult(delivered=True, accepted=True, code=0)
# r=-3: device rejection on the routed-action setter surface.
_REJECTED_R3 = WriteResult(delivered=True, accepted=False, code=-3, msg="not supported")
# Cloud-KV rejection (non-zero cloud result code on setDeviceData).
_REJECTED_KV = WriteResult(delivered=True, accepted=False, code=10007, msg="rejected")
_NOT_DELIVERED = WriteResult.not_delivered("mower asleep (80001)")


# ---------------------------------------------------------------------------
# Family 1: CFG switch — FULL chain (entity → real coordinator.write_setting →
# real cloud_client.set_cfg parsing the raw r=-3 envelope).
# ---------------------------------------------------------------------------

def _real_chain_coordinator(action_response):
    """Real DreameA2MowerCoordinator + real DreameA2CloudClient, with only the
    HTTP boundary (client.action) mocked — the WriteResult is produced by the
    REAL set_cfg envelope parse, not a hand-built stub."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    client = object.__new__(DreameA2CloudClient)
    client.action = MagicMock(return_value=action_response)

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.logger = MagicMock()
    coord._cloud = client

    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor
    coord.hass = hass

    def _set_updated(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set_updated
    return coord


def _cfg_switch(coord):
    from custom_components.dreame_a2_mower.entities.switch.base import (
        DreameA2Switch,
        DreameA2SwitchEntityDescription,
    )

    desc = DreameA2SwitchEntityDescription(
        key="child_lock",
        name="Child lock",
        cfg_key="CLS",
        value_fn=lambda s: s.child_lock_enabled,
        field_updates_fn=lambda s, enabled: {"child_lock_enabled": enabled},
    )
    ent = object.__new__(DreameA2Switch)
    ent.coordinator = coord
    ent.entity_description = desc
    ent._control_mode = ControlMode.DEVICE_WRITABLE
    ent.async_write_ha_state = lambda: None
    return ent


def test_cfg_switch_device_rejection_raises_and_reverts():
    """r=-3 wire envelope → HomeAssistantError from the switch handler AND the
    optimistic field is reverted. The envelope is parsed by the REAL set_cfg."""
    coord = _real_chain_coordinator(
        {"code": 0, "out": [{"r": -3, "msg": "not supported"}]}
    )
    ent = _cfg_switch(coord)
    assert coord.data.child_lock_enabled is None
    with pytest.raises(HomeAssistantError) as exc:
        asyncio.run(ent.async_turn_on())
    # Entity context: plain HomeAssistantError, NOT the service-only class.
    assert not isinstance(exc.value, ServiceValidationError)
    # The device's own code is in the user-facing message.
    assert "-3" in str(exc.value)
    # Optimistic update reverted by write_setting.
    assert coord.data.child_lock_enabled is None


def test_cfg_switch_not_delivered_raises_retryable():
    """action() → None (80001/asleep) → retryable HomeAssistantError."""
    coord = _real_chain_coordinator(None)
    ent = _cfg_switch(coord)
    with pytest.raises(HomeAssistantError) as exc:
        asyncio.run(ent.async_turn_on())
    assert not isinstance(exc.value, ServiceValidationError)
    assert "Try again" in str(exc.value)
    assert coord.data.child_lock_enabled is None


def test_cfg_switch_accepted_applies_state():
    """r=0 → no raise; the optimistic field STAYS applied and the wire payload
    is the wrapped {value: 1} CLS setter."""
    coord = _real_chain_coordinator({"code": 0, "out": [{"r": 0}]})
    ent = _cfg_switch(coord)
    asyncio.run(ent.async_turn_on())  # must not raise
    assert coord.data.child_lock_enabled is True
    payload = coord._cloud.action.call_args.kwargs["parameters"][0]
    assert payload == {"m": "s", "t": "CLS", "d": {"value": 1}}


# ---------------------------------------------------------------------------
# Family 2: CFG time entity (write_setting seam, coordinator mocked with the
# honest WriteResult shapes).
# ---------------------------------------------------------------------------

def _cfg_time(write_result):
    from datetime import time as dt_time

    from custom_components.dreame_a2_mower.time import (
        DreameA2Time,
        DreameA2TimeEntityDescription,
    )

    desc = DreameA2TimeEntityDescription(
        key="dnd_start",
        name="DND start",
        cfg_key="DND",
        minutes_fn=lambda s: 1260,
        build_from_cfg_fn=lambda raw, m: [raw[0], m, raw[2]],
    )
    coord = MagicMock()
    coord.data = MowerState()
    coord.cloud_state = SimpleNamespace(cfg={"DND": [1, 1260, 420]})
    coord.write_setting = AsyncMock(return_value=write_result)
    ent = object.__new__(DreameA2Time)
    ent.coordinator = coord
    ent.entity_description = desc
    ent._control_mode = ControlMode.DEVICE_WRITABLE
    ent.async_write_ha_state = lambda: None
    return ent, coord, dt_time(22, 30)


@pytest.mark.asyncio
async def test_cfg_time_rejection_raises():
    ent, _coord, value = _cfg_time(_REJECTED_R3)
    with pytest.raises(HomeAssistantError) as exc:
        await ent.async_set_value(value)
    assert not isinstance(exc.value, ServiceValidationError)


@pytest.mark.asyncio
async def test_cfg_time_accepted_writes_rmw_payload():
    ent, coord, value = _cfg_time(_ACCEPTED)
    await ent.async_set_value(value)  # must not raise
    coord.write_setting.assert_awaited_once()
    args, _ = coord.write_setting.call_args
    # RMW payload: enabled + end minutes preserved from the cfg base.
    assert args[0] == "DND"
    assert args[1] == [1, 22 * 60 + 30, 420]


def _wire_broadcast(coord):
    """Give a MagicMock coordinator REAL async_set_updated_data semantics —
    assign ``.data`` and record the broadcast — mirroring the (verified)
    real-HA behaviour the stub now implements. P3 Task 1: the production
    helpers no longer carry a MagicMock-compat direct ``coord.data =``
    assign, so the broadcast IS the only state-application path; tests
    assert through it (and gain optimistic→revert sequence visibility)."""
    published: list = []

    def _set(new_state):
        coord.data = new_state
        published.append(new_state)

    coord.async_set_updated_data = MagicMock(side_effect=_set)
    return published


# ---------------------------------------------------------------------------
# Family 3: PRE number (per-map mowing height → write_map_general_setting,
# the PRE dual-write). Rejection = device r=-3 on the PRE array setter.
# ---------------------------------------------------------------------------

def _pre_number(write_result):
    from custom_components.dreame_a2_mower.number import (
        DreameA2PerMapMowingHeightNumber,
    )

    coord = MagicMock()
    coord.data = MowerState(settings_mowing_height=5)
    coord.write_map_general_setting = AsyncMock(return_value=write_result)
    coord._published = _wire_broadcast(coord)
    ent = object.__new__(DreameA2PerMapMowingHeightNumber)
    ent.coordinator = coord
    ent._map_id = 0
    ent._control_mode = ControlMode.DEVICE_WRITABLE
    ent.async_write_ha_state = MagicMock()
    ent.entity_id = "number.map_1_mowing_height"
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    ent.hass = hass
    return ent, coord


@pytest.mark.asyncio
async def test_pre_number_rejection_raises_reverts_and_notifies():
    ent, coord = _pre_number(_REJECTED_R3)
    with pytest.raises(HomeAssistantError) as exc:
        await ent.async_set_native_value(7.0)
    assert not isinstance(exc.value, ServiceValidationError)
    # Optimistic value reverted — and both hops were BROADCAST (listener
    # path), which since P3 Task 1 is the only state-application path.
    assert coord.data.settings_mowing_height == 5
    assert [s.settings_mowing_height for s in coord._published] == [7.0, 5]
    # …and the pre-existing persistent-notification UX is preserved.
    ent.hass.services.async_call.assert_awaited()


@pytest.mark.asyncio
async def test_pre_number_accepted_applies_optimistic_value():
    ent, coord = _pre_number(_ACCEPTED)
    await ent.async_set_native_value(7.0)  # must not raise
    # Applied AND broadcast exactly once via the listener path.
    assert coord.data.settings_mowing_height == 7.0
    assert [s.settings_mowing_height for s in coord._published] == [7.0]
    coord.write_map_general_setting.assert_awaited_once_with(
        map_id=0, pre_index=4, pre_value=70,
        settings_field="mowingHeight", settings_value=7.0,
    )
    ent.hass.services.async_call.assert_not_awaited()  # no failure notification


# ---------------------------------------------------------------------------
# Family 4: SETTINGS number (per-map cutter position → write_settings, the
# chunked-KV transport). Rejection = the CLOUD's non-zero result code.
# ---------------------------------------------------------------------------

def _settings_number(write_result):
    from custom_components.dreame_a2_mower.number import (
        DreameA2PerMapCutterPositionNumber,
    )

    coord = MagicMock()
    coord.data = MowerState(settings_cutter_position=1)
    coord.write_settings = AsyncMock(return_value=write_result)
    coord._published = _wire_broadcast(coord)
    ent = object.__new__(DreameA2PerMapCutterPositionNumber)
    ent.coordinator = coord
    ent._map_id = 0
    ent._control_mode = ControlMode.DEVICE_WRITABLE
    ent.async_write_ha_state = MagicMock()
    ent.entity_id = "number.map_1_cutter_position"
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    ent.hass = hass
    return ent, coord


@pytest.mark.asyncio
async def test_settings_number_cloud_rejection_raises_and_reverts():
    ent, coord = _settings_number(_REJECTED_KV)
    with pytest.raises(HomeAssistantError):
        await ent.async_set_native_value(2.0)
    assert coord.data.settings_cutter_position == 1  # reverted
    # Optimistic→revert both broadcast via the listener path.
    assert [s.settings_cutter_position for s in coord._published] == [2, 1]
    ent.hass.services.async_call.assert_awaited()  # notification preserved


@pytest.mark.asyncio
async def test_settings_number_accepted_applies_value():
    ent, coord = _settings_number(_ACCEPTED)
    await ent.async_set_native_value(2.0)  # must not raise
    assert coord.data.settings_cutter_position == 2
    assert [s.settings_cutter_position for s in coord._published] == [2]
    coord.write_settings.assert_awaited_once()
    _, kwargs = coord.write_settings.call_args
    assert kwargs == {"map_id": 0, "field": "cutterPosition", "value": 2}


# ---------------------------------------------------------------------------
# Family 5: settings select (per-map mowing direction — PRE dual-write via
# pre_settings_optimistic_write; T7-23 named this surface untested).
# ---------------------------------------------------------------------------

def _direction_select(write_result):
    from custom_components.dreame_a2_mower.entities.select.map_settings import (
        DreameA2PerMapMowingDirectionSelect,
    )

    coord = MagicMock()
    coord.data = MowerState(settings_mowing_direction=0)
    coord.write_map_general_setting = AsyncMock(return_value=write_result)
    coord._published = _wire_broadcast(coord)
    # P2 Task 6 (T3-4): an accepted write now awaits coordinator._render_base()
    # to refresh the stripe preview — plain MagicMock attributes aren't
    # awaitable, so this must be an AsyncMock (mirrors the established
    # test_action_mode_select.py._make_coord convention). Inert on the
    # rejection test below since the raise happens before this is reached.
    coord._render_base = AsyncMock()
    coord.render_base = coord._render_base
    ent = object.__new__(DreameA2PerMapMowingDirectionSelect)
    ent.coordinator = coord
    ent._map_id = 0
    ent._control_mode = ControlMode.DEVICE_WRITABLE
    ent.async_write_ha_state = MagicMock()
    ent.entity_id = "select.map_1_mowing_direction"
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    ent.hass = hass
    return ent, coord


@pytest.mark.asyncio
async def test_direction_select_rejection_raises_and_reverts():
    ent, coord = _direction_select(_REJECTED_R3)
    with pytest.raises(HomeAssistantError) as exc:
        await ent.async_select_option("90°")
    assert not isinstance(exc.value, ServiceValidationError)
    assert coord.data.settings_mowing_direction == 0  # reverted
    # Optimistic→revert both broadcast via the listener path.
    assert [s.settings_mowing_direction for s in coord._published] == [90, 0]


@pytest.mark.asyncio
async def test_direction_select_accepted_applies_option():
    ent, coord = _direction_select(_ACCEPTED)
    await ent.async_select_option("90°")  # must not raise
    assert coord.data.settings_mowing_direction == 90
    assert [s.settings_mowing_direction for s in coord._published] == [90]
    coord.write_map_general_setting.assert_awaited_once_with(
        map_id=0, pre_index=6, pre_value=90,
        settings_field="mowingDirection", settings_value=90,
    )


# ---------------------------------------------------------------------------
# Family 6: schedule services (SCHD*V3 device-plane transport).
# ---------------------------------------------------------------------------

def _schedule_coord(monkeypatch, write_schedule=None, write_schedule_enabled=None):
    from custom_components.dreame_a2_mower.state.cloud_state import (
        ScheduleData,
        ScheduleSlot,
    )

    slot = ScheduleSlot(slot_id=0, name="Spr", raw_blob_b64="", plans=(), mode=1)
    coord = SimpleNamespace(
        cloud_state=SimpleNamespace(schedule=ScheduleData(version=3, slots=(slot,))),
        write_schedule=write_schedule or AsyncMock(return_value=_ACCEPTED),
        write_schedule_enabled=write_schedule_enabled
        or AsyncMock(return_value=_ACCEPTED),
    )
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    return coord


_PLANS_CALL_DATA = {
    "slot_id": 0,
    "plans": [{"time_min": 600, "weekday_mask": 127, "action_type": 0}],
}


@pytest.mark.asyncio
async def test_set_schedule_plans_rejection_raises_service_validation(monkeypatch):
    """Device-rejected SCHD*V3 leg (CfgActionError with r-code) →
    ServiceValidationError carrying the code."""
    _schedule_coord(
        monkeypatch, write_schedule=AsyncMock(return_value=_REJECTED_R3)
    )
    call = SimpleNamespace(hass=SimpleNamespace(), data=dict(_PLANS_CALL_DATA))
    with pytest.raises(ServiceValidationError) as exc:
        await services._handle_set_schedule_plans(call)
    assert "-3" in str(exc.value)


@pytest.mark.asyncio
async def test_set_schedule_plans_not_delivered_raises_retryable(monkeypatch):
    """Transport drop (no device verdict) → retryable HomeAssistantError, NOT
    ServiceValidationError."""
    _schedule_coord(
        monkeypatch, write_schedule=AsyncMock(return_value=_NOT_DELIVERED)
    )
    call = SimpleNamespace(hass=SimpleNamespace(), data=dict(_PLANS_CALL_DATA))
    with pytest.raises(HomeAssistantError) as exc:
        await services._handle_set_schedule_plans(call)
    assert not isinstance(exc.value, ServiceValidationError)


@pytest.mark.asyncio
async def test_set_schedule_plans_accepted_writes_slot(monkeypatch):
    coord = _schedule_coord(monkeypatch)
    call = SimpleNamespace(hass=SimpleNamespace(), data=dict(_PLANS_CALL_DATA))
    await services._handle_set_schedule_plans(call)  # must not raise
    coord.write_schedule.assert_awaited_once()
    (new_slots,), _ = coord.write_schedule.call_args
    assert [s.slot_id for s in new_slots] == [0]
    assert len(new_slots[0].plans) == 1
    assert new_slots[0].plans[0].time_min == 600
    assert new_slots[0].mode == 1  # active flag round-tripped, not zeroed


@pytest.mark.asyncio
async def test_set_schedule_enabled_rejection_raises(monkeypatch):
    _schedule_coord(
        monkeypatch, write_schedule_enabled=AsyncMock(return_value=_REJECTED_R3)
    )
    call = SimpleNamespace(
        hass=SimpleNamespace(), data={"slot_id": 0, "enabled": True}
    )
    with pytest.raises(ServiceValidationError):
        await services._handle_set_schedule_enabled(call)


@pytest.mark.asyncio
async def test_set_schedule_enabled_accepted_forwards_args(monkeypatch):
    coord = _schedule_coord(monkeypatch)
    call = SimpleNamespace(
        hass=SimpleNamespace(), data={"slot_id": 1, "enabled": False}
    )
    await services._handle_set_schedule_enabled(call)  # must not raise
    coord.write_schedule_enabled.assert_awaited_once_with(
        slot_id=1, enabled=False
    )


# ---------------------------------------------------------------------------
# Family 7: map-edit services (o=200/204/…/201 transaction; T7-23 named
# rename/delete/create rejection surfacing untested).
# ---------------------------------------------------------------------------

def _map_edit_coord(monkeypatch, **methods):
    coord = SimpleNamespace(**methods)
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    return coord


_NO_GO_DATA = {
    "map_id": 0,
    "shape": "polygon",
    "points": [[0, 0], [1, 0], [1, 1]],
    "radius": 0.0,
    "object_id": -1,
}


@pytest.mark.asyncio
async def test_create_no_go_rejection_raises_service_validation(monkeypatch):
    """A device-rejected map-edit leg (r=-3, e.g. bad region/geometry per
    inventory § o215) surfaces as ServiceValidationError with the code."""
    _map_edit_coord(monkeypatch, create_no_go=AsyncMock(return_value=_REJECTED_R3))
    call = SimpleNamespace(hass=SimpleNamespace(), data=dict(_NO_GO_DATA))
    with pytest.raises(ServiceValidationError) as exc:
        await services._handle_create_no_go_zone(call)
    assert "-3" in str(exc.value)


@pytest.mark.asyncio
async def test_create_no_go_not_delivered_raises_retryable(monkeypatch):
    _map_edit_coord(
        monkeypatch, create_no_go=AsyncMock(return_value=_NOT_DELIVERED)
    )
    call = SimpleNamespace(hass=SimpleNamespace(), data=dict(_NO_GO_DATA))
    with pytest.raises(HomeAssistantError) as exc:
        await services._handle_create_no_go_zone(call)
    assert not isinstance(exc.value, ServiceValidationError)


@pytest.mark.asyncio
async def test_create_no_go_accepted_forwards_geometry(monkeypatch):
    coord = _map_edit_coord(
        monkeypatch, create_no_go=AsyncMock(return_value=_ACCEPTED)
    )
    call = SimpleNamespace(hass=SimpleNamespace(), data=dict(_NO_GO_DATA))
    await services._handle_create_no_go_zone(call)  # must not raise
    coord.create_no_go.assert_awaited_once_with(
        0, "polygon", [[0, 0], [1, 0], [1, 1]], 0.0, object_id=-1
    )


@pytest.mark.asyncio
async def test_rename_zone_rejection_raises(monkeypatch):
    _map_edit_coord(monkeypatch, rename_zone=AsyncMock(return_value=_REJECTED_R3))
    call = SimpleNamespace(
        hass=SimpleNamespace(), data={"map_id": 0, "zone": 1, "name": "Lawn"}
    )
    with pytest.raises(ServiceValidationError):
        await services._handle_rename_zone(call)


@pytest.mark.asyncio
async def test_delete_map_object_rejection_raises(monkeypatch):
    _map_edit_coord(
        monkeypatch, delete_map_object=AsyncMock(return_value=_REJECTED_R3)
    )
    call = SimpleNamespace(
        hass=SimpleNamespace(),
        data={"map_id": 0, "object_id": 7, "category": 1},
    )
    with pytest.raises(ServiceValidationError):
        await services._handle_delete_map_object(call)
