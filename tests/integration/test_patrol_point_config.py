import pytest

from custom_components.dreame_a2_mower.cloud_client import WriteResult

_ACCEPTED = WriteResult(delivered=True, accepted=True, code=0)
_REJECTED = WriteResult(delivered=True, accepted=False, code=-3, msg="not supported")
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.dreame_a2_mower.cloud_state import CloudState


def _bare_cloud_state(**over):
    base = dict(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={}, settings=None,
        schedule=None, ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={}, mapl=None, mihis={},
        fetched_at_unix=0,
    )
    base.update(over)
    return CloudState(**base)


def test_cloud_state_has_cruise_config_default_empty():
    cs = _bare_cloud_state()
    assert cs.cruise_config_by_map == {}


def test_cloud_state_carries_cruise_config():
    cs = _bare_cloud_state(cruise_config_by_map={0: {3: {"cycles": 2, "auto_capture": True}}})
    assert cs.cruise_config_by_map[0][3]["cycles"] == 2


def _patrol_sensor(map_id, points, cruise_cfg):
    from custom_components.dreame_a2_mower.entities.sensor.map import DreameA2PatrolPointsSensor
    sensor = DreameA2PatrolPointsSensor.__new__(DreameA2PatrolPointsSensor)
    md = SimpleNamespace(patrol_points=points)
    sensor._map = lambda: md
    sensor.coordinator = SimpleNamespace(
        cloud_state=_bare_cloud_state(cruise_config_by_map=cruise_cfg)
    )
    sensor._map_id = map_id
    return sensor


def test_patrol_sensor_fills_cycles_and_auto_capture():
    pts = [SimpleNamespace(point_id=3, x_mm=-3050, y_mm=-5480)]
    s = _patrol_sensor(0, pts, {0: {3: {"cycles": 3, "auto_capture": True}}})
    item = s.extra_state_attributes["items"][0]
    assert item["cycles"] == 3 and item["auto_capture"] is True


def test_patrol_sensor_defaults_when_no_config():
    pts = [SimpleNamespace(point_id=4, x_mm=0, y_mm=0)]
    s = _patrol_sensor(0, pts, {})
    item = s.extra_state_attributes["items"][0]
    assert item["cycles"] == 1 and item["auto_capture"] is False


def test_editable_objects_patrol_carries_cycles_auto():
    from custom_components.dreame_a2_mower.camera.map import DreameA2MapCamera
    cam = DreameA2MapCamera.__new__(DreameA2MapCamera)
    md = SimpleNamespace(
        patrol_points=[SimpleNamespace(point_id=3, x_mm=-3050, y_mm=-5480)],
        exclusion_zones=(),
        spot_zones=(),
        maintenance_points=(),
    )
    cam.coordinator = SimpleNamespace(
        _active_map_id=0,
        cloud_state=_bare_cloud_state(
            maps_by_id={0: md},
            cruise_config_by_map={0: {3: {"cycles": 2, "auto_capture": True}}},
        ),
    )
    objs = cam._editable_objects_from_map(md)
    patrol = [o for o in objs if o.get("kind") == "patrol"][0]
    assert patrol["cycles"] == 2 and patrol["auto_capture"] is True


@pytest.mark.asyncio
async def test_write_patrol_point_config_builds_cruised():
    from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin
    c = _WritesMixin.__new__(_WritesMixin)
    # Dual-write: leg 1 = routed o=111 (device-applied cycles), leg 2 = CRUISED
    # (cloud CRUISE.0 record incl. auto_capture). CRUISED alone does not stick.
    c._cloud = SimpleNamespace(
        routed_action=MagicMock(return_value=_ACCEPTED),
        set_cfg=MagicMock(return_value=_ACCEPTED),
    )
    # Optimistic-overlay state normally set in _CoreMixin.__init__ (the bare
    # __new__ instance skips it): the write records the just-written value here
    # so the laggy CRUISE.0 poll can't revert the UI.
    c._pending_cruise_writes = {}
    c.cloud_state = SimpleNamespace(cruise_config_by_map={})
    # Frontend push: entities read cloud_state lazily, so the write must notify
    # listeners or the optimistic value lags until the next poll.
    c.async_update_listeners = MagicMock()
    async def _exec(fn, *a): return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    ok = await c.write_patrol_point_config(
        map_id=0, point_id=3, cycles=3, auto_capture=True
    )
    assert ok.accepted is True
    c.async_update_listeners.assert_called_once()
    # Leg 1: o=111 carries [point_id, cycles] only.
    c._cloud.routed_action.assert_called_once_with(111, {"point": [3, 3]})
    # Leg 2: CRUISED carries [-1, point_id, auto(0/1), cycles].
    c._cloud.set_cfg.assert_called_once_with(
        "CRUISED", {"idx": 0, "value": [-1, 3, 1, 3]}
    )


@pytest.mark.asyncio
async def test_write_patrol_point_config_rejects_bad_cycles():
    from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin
    c = _WritesMixin.__new__(_WritesMixin)
    with pytest.raises(ValueError):
        await c.write_patrol_point_config(map_id=0, point_id=3, cycles=4, auto_capture=False)


@pytest.mark.asyncio
async def test_set_patrol_point_config_handler_calls_coordinator(monkeypatch):
    """The @service_handler-decorated handler resolves the coordinator via
    _coordinator_from_call (monkeypatched here) and forwards kwargs correctly."""
    from custom_components.dreame_a2_mower import services as svc

    coord = SimpleNamespace(
        write_patrol_point_config=AsyncMock(return_value=_ACCEPTED),
        _active_map_id=0,
        active_map_id=0,
    )
    monkeypatch.setattr(svc, "_coordinator_from_call", lambda hass, call: coord)

    # The decorated handler takes (call) — coordinator is resolved internally.
    call = SimpleNamespace(
        hass=SimpleNamespace(),
        data={"point_id": 3, "cycles": 2, "auto_capture": True},
    )
    await svc._handle_set_patrol_point_config(call)

    coord.write_patrol_point_config.assert_awaited_once_with(
        map_id=0, point_id=3, cycles=2, auto_capture=True
    )


@pytest.mark.asyncio
async def test_set_patrol_point_config_handler_uses_explicit_map_id(monkeypatch):
    """When map_id is supplied explicitly it takes precedence over _active_map_id."""
    from custom_components.dreame_a2_mower import services as svc

    coord = SimpleNamespace(
        write_patrol_point_config=AsyncMock(return_value=_ACCEPTED),
        _active_map_id=0,
        active_map_id=0,
    )
    monkeypatch.setattr(svc, "_coordinator_from_call", lambda hass, call: coord)

    call = SimpleNamespace(
        hass=SimpleNamespace(),
        data={"map_id": 2, "point_id": 5, "cycles": 3, "auto_capture": False},
    )
    await svc._handle_set_patrol_point_config(call)

    coord.write_patrol_point_config.assert_awaited_once_with(
        map_id=2, point_id=5, cycles=3, auto_capture=False
    )


@pytest.mark.asyncio
async def test_set_patrol_point_config_handler_raises_on_device_rejection(monkeypatch):
    """A device-rejected WriteResult from write_patrol_point_config raises ServiceValidationError."""
    from homeassistant.exceptions import ServiceValidationError
    from custom_components.dreame_a2_mower import services as svc

    coord = SimpleNamespace(
        write_patrol_point_config=AsyncMock(return_value=_REJECTED),
        _active_map_id=0,
        active_map_id=0,
    )
    monkeypatch.setattr(svc, "_coordinator_from_call", lambda hass, call: coord)

    call = SimpleNamespace(
        hass=SimpleNamespace(),
        data={"point_id": 3, "cycles": 1, "auto_capture": False},
    )
    with pytest.raises(ServiceValidationError):
        await svc._handle_set_patrol_point_config(call)


@pytest.mark.asyncio
async def test_set_patrol_point_config_handler_raises_on_bad_cycles(monkeypatch):
    """ValueError from write_patrol_point_config is re-raised as ServiceValidationError."""
    from homeassistant.exceptions import ServiceValidationError
    from custom_components.dreame_a2_mower import services as svc

    coord = SimpleNamespace(
        write_patrol_point_config=AsyncMock(side_effect=ValueError("cycles must be 1, 2 or 3")),
        _active_map_id=0,
        active_map_id=0,
    )
    monkeypatch.setattr(svc, "_coordinator_from_call", lambda hass, call: coord)

    call = SimpleNamespace(
        hass=SimpleNamespace(),
        data={"point_id": 3, "cycles": 5, "auto_capture": False},
    )
    with pytest.raises(ServiceValidationError):
        await svc._handle_set_patrol_point_config(call)
