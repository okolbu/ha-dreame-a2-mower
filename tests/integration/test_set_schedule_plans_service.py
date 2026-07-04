"""Tests for the set_schedule_plans and set_schedule_enabled services."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.dreame_a2_mower import services
from custom_components.dreame_a2_mower.state.cloud_state import (

    ScheduleData,
    ScheduleSlot,
)

from custom_components.dreame_a2_mower.cloud_client import WriteResult as _WR

# P2 Task 5: the coordinator write families return WriteResult, not bool.
_WR_ACCEPTED = _WR(delivered=True, accepted=True, code=0)
_WR_REJECTED = _WR(delivered=True, accepted=False, code=-3, msg="not supported")



@pytest.mark.asyncio
async def test_set_schedule_enabled_blocks_during_active_task(monkeypatch):
    """Handler must raise ServiceValidationError and NOT call write_schedule_enabled
    when a mow session is currently IN_SESSION."""
    from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession
    from homeassistant.exceptions import ServiceValidationError

    coordinator = SimpleNamespace(
        state_machine=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(mow_session=MowSession.IN_SESSION)
        ),
        write_schedule_enabled=AsyncMock(return_value=_WR_ACCEPTED),
    )
    monkeypatch.setattr(
        services, "_coordinator_from_call", lambda hass, call: coordinator
    )
    call = SimpleNamespace(
        hass=SimpleNamespace(),
        data={"slot_id": 0, "enabled": False},
    )
    with pytest.raises(ServiceValidationError):
        await services._handle_set_schedule_enabled(call)
    coordinator.write_schedule_enabled.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_schedule_enabled_dispatches_when_idle(monkeypatch):
    """Handler must call write_schedule_enabled with the correct kwargs when
    the mower is BETWEEN_SESSIONS (no active task)."""
    from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession

    coordinator = SimpleNamespace(
        state_machine=SimpleNamespace(
            snapshot=lambda: SimpleNamespace(mow_session=MowSession.BETWEEN_SESSIONS)
        ),
        write_schedule_enabled=AsyncMock(return_value=_WR_ACCEPTED),
    )
    monkeypatch.setattr(
        services, "_coordinator_from_call", lambda hass, call: coordinator
    )
    call = SimpleNamespace(
        hass=SimpleNamespace(),
        data={"slot_id": 1, "enabled": True},
    )
    await services._handle_set_schedule_enabled(call)
    coordinator.write_schedule_enabled.assert_awaited_once_with(slot_id=1, enabled=True)


@pytest.mark.asyncio
async def test_set_schedule_plans_calls_write_schedule(monkeypatch):
    existing = ScheduleSlot(slot_id=0, name="Spr", raw_blob_b64="", plans=(), mode=1)
    coord = SimpleNamespace(
        cloud_state=SimpleNamespace(
            schedule=ScheduleData(version=1, slots=(existing,))
        ),
        write_schedule=AsyncMock(return_value=_WR_ACCEPTED),
    )
    monkeypatch.setattr(
        services, "_coordinator_from_call", lambda hass, call: coord
    )
    call = SimpleNamespace(
        hass=SimpleNamespace(),
        data={
            "slot_id": 0,
            "plans": [{"time_min": 780, "weekday_mask": 4, "action_type": 0}],
        },
    )
    await services._handle_set_schedule_plans(call)
    coord.write_schedule.assert_awaited_once()
    (slots_arg,), _ = coord.write_schedule.await_args
    assert any(s.slot_id == 0 and len(s.plans) == 1 for s in slots_arg)
