"""AIOBS refresher gating + sensor. Uses the repo's HA-stub conftest."""
import asyncio
import types

from custom_components.dreame_a2_mower.protocol.obstacle_markers import ObstacleMarker

_MARK = ObstacleMarker(
    id="1781714586.078000_0", filename="1781714586.078000_0",
    polygon_m=((-6.627, 4.113),), confidence=78, obstacle_class=5,
    flag=0, detection_epoch=1781714586.078,
)


def _make_coord(tmp_path, *, mow_session, markers):
    """Build a minimal object carrying just the _refresh_aiobs collaborators."""
    from custom_components.dreame_a2_mower.archive.obstacle_markers_log import (
        ObstacleMarkerLog,
    )
    from custom_components.dreame_a2_mower.coordinator._refreshers import (
        _RefreshersMixin,
    )

    class _Coord(_RefreshersMixin):
        def __init__(self):
            self._obstacle_markers = []
            self._obstacle_marker_log = ObstacleMarkerLog(tmp_path)
            self._obstacle_marker_log.load()
            self._cloud = types.SimpleNamespace(
                fetch_aiobs_markers=lambda: list(markers)
            )
            snap = types.SimpleNamespace(mow_session=mow_session)
            self.state_machine = types.SimpleNamespace(snapshot=lambda: snap)

    return _Coord()


def test_refresh_aiobs_noops_when_idle(tmp_path):
    coord = _make_coord(tmp_path, mow_session="IDLE", markers=[_MARK])
    asyncio.run(coord._refresh_aiobs())
    assert coord._obstacle_markers == []           # not polled while idle
    assert coord._obstacle_marker_log.all() == []


def test_refresh_aiobs_collects_and_logs_when_in_session(tmp_path):
    coord = _make_coord(tmp_path, mow_session="IN_SESSION", markers=[_MARK])
    asyncio.run(coord._refresh_aiobs())
    assert [m.id for m in coord._obstacle_markers] == [_MARK.id]
    assert [r.id for r in coord._obstacle_marker_log.all()] == [_MARK.id]


def test_marker_sensor_value_and_attrs(tmp_path):
    coord = _make_coord(tmp_path, mow_session="IN_SESSION", markers=[_MARK])
    asyncio.run(coord._refresh_aiobs())

    from custom_components.dreame_a2_mower.entities.sensor.device import (
        _obstacle_marker_value,
        _obstacle_marker_attrs,
    )
    assert _obstacle_marker_value(coord) == 1
    attrs = _obstacle_marker_attrs(coord)
    assert attrs["markers"][0]["id"] == _MARK.id
    assert attrs["markers"][0]["confidence"] == 78
    assert attrs["markers"][0]["image_status"] == "pending"
    assert attrs["archived_count"] == 1
