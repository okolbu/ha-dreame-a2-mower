from custom_components.dreame_a2_mower.archive.obstacle_markers_log import (
    ObstacleMarkerLog,
)
from custom_components.dreame_a2_mower.protocol.obstacle_markers import ObstacleMarker

_M = ObstacleMarker(
    id="1781714586.078000_0",
    filename="1781714586.078000_0",
    polygon_m=((-6.627, 4.113), (-6.777, 4.163)),
    confidence=78,
    obstacle_class=5,
    flag=0,
    detection_epoch=1781714586.078,
)


def test_note_is_idempotent_by_id(tmp_path):
    log = ObstacleMarkerLog(tmp_path)
    log.load()
    assert log.note(_M) is True
    assert log.note(_M) is False           # second insert dedups
    assert len(log.all()) == 1
    rec = log.all()[0]
    assert rec.image_status == "pending"   # default on first note
    assert rec.detection_epoch == 1781714586.078


def test_status_transition_and_pending_filter(tmp_path):
    log = ObstacleMarkerLog(tmp_path)
    log.load()
    log.note(_M)
    assert [r.id for r in log.pending()] == [_M.id]
    log.set_status(_M.id, "ready", image_md5="abc123")
    assert log.pending() == []
    assert log.all()[0].image_md5 == "abc123"


def test_survives_reload_from_disk(tmp_path):
    log = ObstacleMarkerLog(tmp_path)
    log.load()
    log.note(_M)
    reloaded = ObstacleMarkerLog(tmp_path)
    reloaded.load()
    assert len(reloaded.all()) == 1
    assert reloaded.all()[0].filename == _M.filename


def test_load_tolerates_non_list_json(tmp_path):
    (tmp_path / "markers.json").write_text("{}")   # object, not a list
    log = ObstacleMarkerLog(tmp_path)
    log.load()                                       # must not raise
    assert log.all() == []


def test_set_status_rejects_invalid(tmp_path):
    import pytest
    log = ObstacleMarkerLog(tmp_path)
    log.load()
    log.note(_M)
    with pytest.raises(ValueError):
        log.set_status(_M.id, "bogus")
