"""Card-contract snapshot: pin the attribute shapes the JS cards consume.

The bundled Lovelace cards under ``custom_components/dreame_a2_mower/www/``
read entity/camera attributes by key and by positional-array index. Those
backend↔card contracts have **no schema version** — a backend attr-shape
change breaks a card silently (browser-side only; nothing in the HA server
log). This test snapshots the SHAPE (key sets + element layout) of each
card-consumed attribute so such a change fails loudly here.

Strength of the pins:
- **Nested element dicts** (map_projection, wifi_overlay, a legs_timeline
  leg, a schedule slot/plan, an editable/deletable/renamable object) are
  pinned to an EXACT key set — these are the tight card contracts; a
  field add/rename/remove must update the consuming card AND this test in
  lockstep.
- **Positional arrays** (latest_point, track_snapshot rows, state_samples
  rows) are pinned by length — the cards index them positionally.
- **Top-level entity-attribute dicts** carry many diagnostic keys that
  grow purely-additively (safe); for those we assert only that the
  card-consumed keys are PRESENT, not that the full set is frozen.

Consumers (grep the key in www/ to confirm):
  camera map        → dreame-mower-map-card.js, dreame-map-editor-card.js
  picked_session    → dreame-mower-replay-card.js
  schedule_count    → dreame-a2-schedule-card.js
  segment_count     → (backend rename/delete services; not a card)

Construction mirrors the proven lightweight patterns in
test_map_camera_attributes.py / test_picked_session.py /
test_map_edit_sensor_attrs.py / test_cloud_state_sensors.py /
test_active_map_wifi_overlay.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

FIXTURE = Path("tests/protocol/data/sessions/short.json")


# ---------------------------------------------------------------------------
# Camera "map" — dreame-mower-map-card.js + dreame-map-editor-card.js
# ---------------------------------------------------------------------------

def _make_map_camera():
    from custom_components.dreame_a2_mower.camera import DreameA2MapCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
    from custom_components.dreame_a2_mower.protocol.map import (
        ExclusionZone,
        SpotZone,
        MaintenancePoint,
        PatrolPoint,
    )

    md = SimpleNamespace(
        name="Main Lawn", bx1=0.0, by1=0.0, bx2=20000.0, by2=21000.0,
        pixel_size_mm=50.0, width_px=400, height_px=420, nav_paths=(),
        exclusion_zones=(
            ExclusionZone(points=((0.0, 0.0), (1.0, 1.0)), subtype=None, obj_id=101),
            ExclusionZone(points=((2.0, 2.0),), subtype="ignore", obj_id=102),
        ),
        spot_zones=(
            # points_m is derived (points/1000); kept raw here as placeholders.
            SpotZone(
                kind="spot", obj_id=201, name="Spot A",
                points=((1000.0, 1000.0), (3000.0, 1000.0), (3000.0, 3000.0), (1000.0, 3000.0)),
                area_m2=4.0,
            ),
        ),
        maintenance_points=(
            MaintenancePoint(point_id=301, x_mm=2500.0, y_mm=-1300.0),
        ),
        patrol_points=(
            PatrolPoint(point_id=401, x_mm=7000.0, y_mm=2000.0),
        ),
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._base_png = b"\x89PNGbase"
    coord._editor_base_png = None
    coord._base_png_mode = SimpleNamespace(value="green")
    coord._live_point_seq = 7
    coord._latest_point = [1.0, 2.0, 90.0, 1234.0]
    coord._track_snapshot_cache = None
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState, TrackPoint
    coord.live_map = LiveMapState(track=[
        TrackPoint(t=1230.0, x_m=0.0, y_m=0.0, area_m2=0.0,
                   heading_deg=None, task_state=0, role="mowing"),
        TrackPoint(t=1234.0, x_m=1.0, y_m=2.0, area_m2=1.0,
                   heading_deg=90.0, task_state=0, role="mowing"),
    ])
    coord.cloud_state = SimpleNamespace(
        maps_by_id={0: md}, forbidden_node_types_by_map={},
        settings=SimpleNamespace(raw=[]),
        cruise_config_by_map={0: {401: {"cycles": 2, "auto_capture": True}}},
    )
    coord._active_map_id = 0
    coord.state_machine = MowerStateMachine()
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "e"
    coord.data = MagicMock()
    coord.data.hardware_serial = None
    return DreameA2MapCamera(coord)


def test_camera_map_card_consumed_keys_present():
    attrs = _make_map_camera().extra_state_attributes
    # Live-stream + projection keys the map card reads.
    for key in (
        "map_projection", "point_seq", "latest_point", "track_snapshot",
        "last_known_point", "background_mode", "available_map_ids",
        "editable_objects", "schema_version",
    ):
        assert key in attrs, f"camera map dropped card-consumed attr {key!r}"


def test_camera_map_schema_version_pinned():
    """The camera 'map' attribute contract carries an integer schema_version.

    Bumping the SHAPE of any card-consumed attr (map_projection,
    latest_point/track_snapshot layout, editable_objects element keys) must be
    accompanied by a bump of MAP_ATTR_SCHEMA_VERSION so a card can detect a
    backend it doesn't understand. This pins the current value.
    """
    from custom_components.dreame_a2_mower.camera.map import (
        MAP_ATTR_SCHEMA_VERSION,
    )

    attrs = _make_map_camera().extra_state_attributes
    assert attrs["schema_version"] == MAP_ATTR_SCHEMA_VERSION
    assert isinstance(attrs["schema_version"], int)
    assert MAP_ATTR_SCHEMA_VERSION == 5


def test_camera_map_projection_exact_shape():
    proj = _make_map_camera().extra_state_attributes["map_projection"]
    assert set(proj) == {
        "bx1_mm", "by1_mm", "bx2_mm", "by2_mm",
        "pixel_size_mm", "width_px", "height_px",
    }


def test_camera_positional_arrays_layout():
    attrs = _make_map_camera().extra_state_attributes
    # map card indexes latest_point[0..3] = x, y, heading, area.
    assert isinstance(attrs["latest_point"], list) and len(attrs["latest_point"]) == 4
    # track_snapshot is a list of same-layout rows.
    assert isinstance(attrs["track_snapshot"], list)
    for row in attrs["track_snapshot"]:
        assert len(row) == 4
    assert isinstance(attrs["point_seq"], int)


def test_camera_editable_objects_exact_element_shape():
    objs = _make_map_camera().extra_state_attributes["editable_objects"]
    assert objs, "expected at least one editable object from the fixture map"
    # Two element shapes: polygon objects (no-go/ignore/spot) carry points_m;
    # single-point objects (maintenance o=224) carry point_m;
    # patrol objects (o=223) carry point_m + cycles + auto_capture.
    poly_keys = {"id", "op", "type", "kind", "shape_type", "points_m", "radius"}
    maint_keys = {"id", "op", "type", "kind", "point_m"}
    patrol_keys = {"id", "op", "type", "kind", "point_m", "cycles", "auto_capture"}
    kinds = set()
    for o in objs:
        kinds.add(o["kind"])
        if o["kind"] == "maintenance":
            assert set(o) == maint_keys
            assert o["op"] == 224 and o["type"] == 3
        elif o["kind"] == "patrol":
            assert set(o) == patrol_keys
            # DISTINCT opcode from maintenance; delete type 2.
            assert o["op"] == 223 and o["type"] == 2
        else:
            assert set(o) == poly_keys
            if o["kind"] == "spot":
                assert o["op"] == 214 and o["type"] == 1
    # The fixture surfaces all old + new point kinds.
    assert {"spot", "maintenance", "patrol"} <= kinds


def test_camera_wifi_overlay_exact_shape(tmp_path):
    # wifi_overlay only appears once a heatmap for the active map is cached;
    # build that state via WifiArchiveStore (mirrors test_active_map_wifi_overlay).
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.wifi.archive_store import WifiArchiveStore

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._wifi_archive_store = WifiArchiveStore(tmp_path / "wifi_archive")
    coord._wifi_archive_index = []
    coord._wifi_body_cache = {}
    coord._active_map_id = None
    body = {
        "data": [-55] * 6, "width": 2, "height": 3, "resolution": 2,
        "startX": 100, "startY": 300,
    }
    store = coord._wifi_archive_store
    store.archive("hm1", body, first_seen_unix=1000)
    store.set_map_id("hm1", 0)
    coord._wifi_archive_index = store.load_index()
    coord._active_map_id = 0
    coord._wifi_body_cache["hm1"] = body
    overlay = coord.active_map_wifi_overlay
    assert overlay is not None
    assert set(overlay) == {
        "data", "width", "height", "resolution_m", "start_x_m", "start_y_m",
    }


# ---------------------------------------------------------------------------
# Sensor "picked_session" — dreame-mower-replay-card.js
# ---------------------------------------------------------------------------

def _build_picked_summary(*, with_track: bool):
    from custom_components.dreame_a2_mower.domain.session.replay import (
        build_picked_session_summary, format_session_label,
    )
    from custom_components.dreame_a2_mower.protocol.session_summary import (
        parse_session_summary,
    )
    raw = json.loads(FIXTURE.read_text())
    if with_track:
        # on-disk track row: [t, x_m, y_m, area_m2, heading_deg, task_state, role]
        raw["track"] = [
            [1000, 0.0, 0.0, 0.0, 0.0, 1, "mowing"],
            [1001, 1.0, 0.0, 1.0, 0.0, 1, "mowing"],
            [1002, 2.0, 0.0, 1.0, 0.0, 1, "traversal"],
            [1003, 3.0, 0.0, 1.0, 0.0, 1, "traversal"],
        ]
    entry = SimpleNamespace(
        md5=raw["md5"], filename="short.json", map_id=0,
        end_ts=raw["end"], start_ts=raw["start"], duration_min=raw["time"],
        area_mowed_m2=raw["areas"], local_trail_complete=True, still_running=False,
    )
    return build_picked_session_summary(
        raw_dict=raw, summary=parse_session_summary(raw),
        entry=entry, picker_label=format_session_label(entry),
    )


def test_picked_session_card_consumed_keys_present():
    out = _build_picked_summary(with_track=False)
    for key in (
        "legs_timeline", "track_first_ts", "track_last_ts", "state_samples",
        "error_samples",
        "base_map_image_url", "base_map_image_url_no_trail", "map_projection",
    ):
        assert key in out, f"picked_session dropped card-consumed attr {key!r}"


def test_picked_session_legs_timeline_exact_element_shape():
    out = _build_picked_summary(with_track=True)
    legs = out["legs_timeline"]
    assert legs, "expected legs from the injected track"
    for leg in legs:
        assert set(leg) == {"role", "start_ts", "end_ts", "pts"}
        assert isinstance(leg["start_ts"], int)
        assert isinstance(leg["end_ts"], int)
        for pt in leg["pts"]:
            assert len(pt) == 2  # [x_m, y_m] — replay card indexes pt[0], pt[1]


def test_picked_session_state_samples_layout():
    out = _build_picked_summary(with_track=True)
    samples = out["state_samples"]
    assert isinstance(samples, list)
    for s in samples:
        assert len(s) == 2  # [unix_ts, state_code]


def test_picked_session_error_samples_layout():
    # Card's rain-delay overlay (dreame-mower-replay-card.js: `a.error_samples`,
    # code===56 windows) indexes rows positionally — same [unix_ts, code]
    # shape as state_samples.
    out = _build_picked_summary(with_track=True)
    samples = out["error_samples"]
    assert isinstance(samples, list)
    for s in samples:
        assert len(s) == 2  # [unix_ts, error_code]


# ---------------------------------------------------------------------------
# Sensor "segment_count" — backend rename/delete services (not a card)
# ---------------------------------------------------------------------------

def test_segment_count_rename_delete_element_shapes():
    from custom_components.dreame_a2_mower.entities.sensor.map import (
        DreameA2MapSegmentCountSensor,
    )
    from custom_components.dreame_a2_mower.protocol.map import ExclusionZone, MowingZone

    m = MagicMock()
    m.mowing_zones = (
        MowingZone(zone_id=1, name="Zone1", path=((0.0, 0.0),), area_m2=5.0),
    )
    m.exclusion_zones = (
        ExclusionZone(points=((0.0, 0.0),), subtype=None, obj_id=101),
        ExclusionZone(points=((1.0, 1.0),), subtype="ignore", obj_id=102),
    )
    coord = MagicMock()
    coord.entry.entry_id = "f"
    coord.cloud_state.maps_by_id = {0: m}
    attrs = DreameA2MapSegmentCountSensor(coord, map_id=0).extra_state_attributes
    assert {"renamable_zones", "deletable_objects"} <= set(attrs)
    for z in attrs["renamable_zones"]:
        assert set(z) == {"region", "name"}
    for o in attrs["deletable_objects"]:
        assert set(o) == {"id", "category", "label"}


# ---------------------------------------------------------------------------
# Sensor "schedule_count" — dreame-a2-schedule-card.js
# ---------------------------------------------------------------------------

def test_schedule_count_slot_and_plan_element_shapes():
    from custom_components.dreame_a2_mower.cloud_state import (
        CloudState, ScheduleData, SchedulePlan, ScheduleSlot, SettingsRoot,
    )
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.mower.state import MowerState
    from custom_components.dreame_a2_mower.observability import (
        FreshnessTracker, NovelObservationRegistry,
    )
    from custom_components.dreame_a2_mower.sensor import DreameA2ScheduleCountSensor

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._active_map_id = 0
    coord.entry = MagicMock()
    coord.entry.entry_id = "e"
    sched = ScheduleData(
        version=657,
        slots=(
            ScheduleSlot(
                slot_id=0, name="Spring", raw_blob_b64="x",
                plans=(SchedulePlan(time_min=478, weekday_mask=5, action_type=0),),
            ),
        ),
    )
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=sched, ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={}, mapl=None, mihis={}, fetched_at_unix=0,
    )
    attrs = DreameA2ScheduleCountSensor(coord).extra_state_attributes
    assert {"slots", "version"} <= set(attrs)
    for slot in attrs["slots"]:
        assert set(slot) == {"slot_id", "name", "enabled", "plans"}
        for plan in slot["plans"]:
            assert set(plan) == {"time", "days", "action", "zone_id"}
