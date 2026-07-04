"""Coordinator session-lifecycle tests: start/telemetry/snapshot/dirty/inject.

Split out of the test_coordinator.py monolith (P3.11); tests moved verbatim.
"""
from __future__ import annotations

import base64

from custom_components.dreame_a2_mower.state import MowerState
from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
from tests.integration._coordinator_helpers import (
    _make_coordinator_for_session_tests,
    _make_s1p4_frame_33b,
)


def test_resume_after_recharge_splits_track_on_pen_up_gap():
    """4 → 0 (recharge resume) no longer calls begin_leg(); the pause→resume
    time gap is a pen-up boundary that derive_render_legs() splits on.

    Setup:
    1. Start a session (task_state=1 → begin_session).
    2. Append a point before the pause.
    3. Feed task_state=4 (resume_pending).
    4. Feed task_state=0 (running again).
    5. Append a point well after the gap.
    6. Verify the resume left the session active and the derived render
       legs split into two on the pen-up boundary.
    """
    from custom_components.dreame_a2_mower.domain.session.replay import derive_render_legs

    coord = _make_coordinator_for_session_tests()
    now = 1_714_329_600

    # Step 1: start session
    state_ts1 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    coord.data = coord._on_state_update(state_ts1, now)

    # Step 2: two mowing points before the pause (a leg needs >= 2 pts).
    coord.live_map.append_point(t=now + 10, x_m=0.0, y_m=0.0, area_m2=0.0, heading_deg=0.0)
    coord.live_map.append_point(t=now + 11, x_m=1.0, y_m=0.0, area_m2=0.5, heading_deg=0.0)

    # Step 3: feed task_state=4 (resume_pending — going to charge station)
    state_ts4 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 4]]})
    coord.data = coord._on_state_update(state_ts4, now + 100)
    assert coord._prev_task_state == 4

    # Step 4: feed task_state=0 (running again)
    state_ts2 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    result = coord._on_state_update(state_ts2, now + 200)

    # Step 5: two more points well after the gap (> pen-up threshold).
    coord.live_map.append_point(t=now + 300, x_m=2.0, y_m=0.0, area_m2=1.0, heading_deg=0.0)
    coord.live_map.append_point(t=now + 301, x_m=3.0, y_m=0.0, area_m2=1.5, heading_deg=0.0)

    # Step 6: session stayed active; the pen-up gap splits the track into
    # two render legs (no shared boundary point across the gap).
    assert coord.live_map.is_active()  # SM-14: session_active removed; use live_map
    assert coord._prev_task_state == 0  # status[0][1]=0 → running (v1.0.0a18 semantics)
    legs = derive_render_legs([p.as_dict() for p in coord.live_map.track])
    assert len(legs) == 2


def test_telemetry_appends_with_real_state_machine_set():
    """Regression: capture must work with a REAL state_machine set.

    Historical context: the 2026-05-18 trail-split commit read
    ``sm.snapshot.current_activity`` (attribute on a method) in
    _on_state_update's append-point gate, which raised AttributeError on
    every s1p4 push once the coordinator had a real ``state_machine`` set
    (production always does). HA's call_soon_threadsafe loop swallowed the
    exception, so the trail silently stayed empty for every session.

    The track-model rewrite (Task 9) dropped the per-point activity
    classification entirely (role is now derived from the area delta in
    append_point), so the crash class is gone. This test keeps a REAL
    MowerStateMachine on the coord as a guard that the append path runs
    cleanly to the track when a state_machine is present.
    """
    from custom_components.dreame_a2_mower.state.machine import MowerStateMachine

    coord = _make_coordinator_for_session_tests()
    coord.state_machine = MowerStateMachine()  # mimic _CoreMixin.__init__
    now = 1_714_329_600

    state_ts1 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    coord.data = coord._on_state_update(state_ts1, now)
    assert coord.live_map.is_active()

    blob = _make_s1p4_frame_33b(x_m=3.5, y_m=7.2)
    value = base64.b64encode(blob).decode("ascii")
    state_with_pos = apply_property_to_state(coord.data, siid=1, piid=4, value=value)
    coord._on_state_update(state_with_pos, now + 30)

    # The point must reach the track — pre-fix this was 0 because of the
    # AttributeError on the snapshot attribute access (vs method call).
    assert coord.live_map.total_points() == 1
    assert len(coord.live_map.track) == 1


def test_telemetry_during_active_session_appends_to_track():
    """s1p4 telemetry arriving during an active session appends a TrackPoint.

    Setup:
    1. Start session (task_state=1).
    2. Feed a valid s1p4 blob carrying a new position.
    3. Verify live_map.total_points() == 1 and the point is in MowerState.
    """
    coord = _make_coordinator_for_session_tests()
    now = 1_714_329_600

    # Step 1: start session
    state_ts1 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    coord.data = coord._on_state_update(state_ts1, now)

    # Step 2: build a 33-byte s1p4 frame with a known position and push it
    blob = _make_s1p4_frame_33b(x_m=3.5, y_m=7.2)
    value = base64.b64encode(blob).decode("ascii")
    state_with_pos = apply_property_to_state(coord.data, siid=1, piid=4, value=value)
    assert state_with_pos != coord.data  # position actually changed

    result = coord._on_state_update(state_with_pos, now + 30)

    # Step 3: position was appended to the track
    assert coord.live_map.total_points() == 1
    assert len(coord.live_map.track) == 1
    pt = coord.live_map.track[0]
    assert abs(pt.x_m - 3.5) < 0.01
    assert abs(pt.y_m - 7.2) < 0.01

    # MowerState.session_track_segments reflects the captured points (one
    # flat segment of (x_m, y_m) pairs — the per-leg split is at render time).
    assert result.session_track_segments is not None
    assert len(result.session_track_segments) == 1
    assert len(result.session_track_segments[0]) == 1
    assert abs(result.session_track_segments[0][0][0] - 3.5) < 0.01


def test_on_state_update_captures_settings_snapshot_at_session_begin():
    """When task_state_code transitions idle → running, the coordinator
    builds a v2 settings_snapshot; per_map subsection matches
    cloud_state.settings.by_map_id_canonical[active_map_id]."""
    from unittest.mock import MagicMock

    per_map_settings = {
        "settings_edgemaster": True,
        "settings_mowing_height_mm": 30,
        "settings_obstacle_avoidance_ai": False,
    }

    coord = _make_coordinator_for_session_tests()
    coord._active_map_id = 0

    # Build a mock cloud_state whose settings.by_map_id_canonical[0] returns
    # our dict — avoids constructing the full frozen CloudState dataclass.
    mock_settings = MagicMock()
    mock_settings.by_map_id_canonical = {0: per_map_settings}
    mock_cloud_state = MagicMock()
    mock_cloud_state.settings = mock_settings
    coord.cloud_state = mock_cloud_state

    coord._prev_task_state = None  # idle
    coord.data = MowerState(battery_level=87)

    # task_state_code=0 → running; prev=None → triggers begin_session
    new_state = MowerState(task_state_code=0, battery_level=87)

    coord._on_state_update(new_state, now_unix=1_700_000_000)

    # v2 snapshot: per_map subsection carries the cloud settings; version=2
    snap = coord.live_map.settings_snapshot
    assert snap["version"] == 2
    assert snap["per_map"] == per_map_settings


def test_on_state_update_settings_snapshot_none_when_cloud_state_missing():
    """When cloud_state is None the v2 snapshot has per_map=None (other sections present)."""
    coord = _make_coordinator_for_session_tests()
    coord._active_map_id = 0
    coord.cloud_state = None
    coord._prev_task_state = None
    coord.data = MowerState()

    new_state = MowerState(task_state_code=0)

    coord._on_state_update(new_state, now_unix=1_700_000_000)

    # v2 snapshot is always a dict; per_map is None when cloud_state is missing
    snap = coord.live_map.settings_snapshot
    assert snap["version"] == 2
    assert snap["per_map"] is None


def test_on_state_update_sets_dirty_flag_on_new_point():
    """_on_state_update sets _live_map_dirty when a new point is appended."""
    import base64

    coord = _make_coordinator_for_session_tests()
    coord._live_map_dirty = False

    # Start a session.
    now = 1_714_329_600
    state_ts1 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    coord.data = coord._on_state_update(state_ts1, now)

    # Feed a telemetry blob carrying a new position.
    blob = _make_s1p4_frame_33b(x_m=2.0, y_m=3.0)
    value = base64.b64encode(blob).decode("ascii")
    state_with_pos = apply_property_to_state(coord.data, siid=1, piid=4, value=value)
    assert state_with_pos != coord.data  # position actually changed

    coord._on_state_update(state_with_pos, now + 30)

    # A point was added — dirty flag should be set.
    assert coord._live_map_dirty is True


def test_on_state_update_does_not_set_dirty_when_point_deduped():
    """_live_map_dirty is not set when append_point dedupes (no new point added)."""
    import base64

    coord = _make_coordinator_for_session_tests()
    coord._live_map_dirty = False

    now = 1_714_329_600
    # Start session + add one real point.
    state_ts1 = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    coord.data = coord._on_state_update(state_ts1, now)

    blob = _make_s1p4_frame_33b(x_m=2.0, y_m=3.0)
    value = base64.b64encode(blob).decode("ascii")
    state_pos = apply_property_to_state(coord.data, siid=1, piid=4, value=value)
    coord.data = coord._on_state_update(state_pos, now + 10)
    # Reset dirty after first real point.
    coord._live_map_dirty = False

    # Send the same (almost identical) position — dedup kicks in. The track
    # model dedups only when close in space (< 20cm) AND close in time
    # (< 0.5s), so reuse the same timestamp (now + 10) for the follow-up.
    blob2 = _make_s1p4_frame_33b(x_m=2.01, y_m=3.01)  # 14cm from first point
    value2 = base64.b64encode(blob2).decode("ascii")
    state_pos2 = apply_property_to_state(coord.data, siid=1, piid=4, value=value2)
    # state_pos2 differs from coord.data (position changed slightly) so
    # _on_state_update's "something changed" guard passes, but append_point
    # dedup should skip the point (same tick, within 20cm).
    coord._on_state_update(state_pos2, now + 10)

    # Dirty should NOT be set — the dedup ate the point.
    assert coord._live_map_dirty is False


def test_inject_live_map_settings_snapshot():
    coord = _make_coordinator_for_session_tests()
    coord.live_map.begin_session(1700000000)
    coord.live_map.settings_snapshot = {"settings_edgemaster": True}
    coord.live_map.charge_at_start = 87
    raw = {}
    coord._inject_live_map_into_raw_dict(raw)
    assert raw["settings_snapshot"] == {"settings_edgemaster": True}
    assert raw["charge_at_start"] == 87


def test_inject_live_map_settings_snapshot_none_skipped():
    coord = _make_coordinator_for_session_tests()
    coord.live_map.begin_session(1700000000)
    coord.live_map.settings_snapshot = None
    raw = {}
    coord._inject_live_map_into_raw_dict(raw)
    assert "settings_snapshot" not in raw


def test_inject_live_map_charge_at_start_none_skipped():
    coord = _make_coordinator_for_session_tests()
    coord.live_map.begin_session(1700000000)
    coord.live_map.charge_at_start = None
    raw = {}
    coord._inject_live_map_into_raw_dict(raw)
    assert "charge_at_start" not in raw


def test_inject_live_map_battery_samples_passthrough():
    coord = _make_coordinator_for_session_tests()
    coord.live_map.begin_session(1700000000)
    coord.live_map.battery_samples = [(1700000000, 87), (1700000060, 86)]
    raw = {}
    coord._inject_live_map_into_raw_dict(raw)
    assert raw["battery_samples"] == [[1700000000, 87], [1700000060, 86]]
