"""Task 6: the set_schedule_plans service still reaches coordinator.write_schedule."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.dreame_a2_mower import services
from custom_components.dreame_a2_mower.cloud_state import (
    ScheduleData,
    ScheduleSlot,
)


@pytest.mark.asyncio
async def test_set_schedule_plans_calls_write_schedule(monkeypatch):
    existing = ScheduleSlot(slot_id=0, name="Spr", raw_blob_b64="", plans=(), mode=1)
    coord = SimpleNamespace(
        cloud_state=SimpleNamespace(
            schedule=ScheduleData(version=1, slots=(existing,))
        ),
        write_schedule=AsyncMock(return_value=True),
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
