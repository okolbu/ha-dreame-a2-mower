"""Shared coordinator-test fixtures/factories.

Extracted verbatim from the former test_coordinator.py monolith (P3.11) so the
topically-split test files (test_coordinator_{apply,writes,session,persist,
finalize,replay,render}.py + the residual test_coordinator.py entity tests)
share one copy of the coordinator stub factories and frame builders.
"""
from __future__ import annotations

import asyncio
import struct

from unittest.mock import MagicMock
from custom_components.dreame_a2_mower.state import MowerState
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator


def _pack_pose(x20: int, y20: int) -> bytes:
    """Pack (x20, y20) into 5 bytes using the apk's 20-bit signed format.

    The decoder uses _decode_pose which reverses this operation:
      x: 20-bit signed stored in b0[7:0], b1[7:0], b2[3:0]
      y: 20-bit signed stored in b2[7:4], b3[7:0], b4[7:0]
    Raw values are in map-scale millimetres (= actual_mm / 10 × 10).
    """
    if x20 < 0:
        x20 += 0x100000
    if y20 < 0:
        y20 += 0x100000
    b0 = x20 & 0xFF
    b1 = (x20 >> 8) & 0xFF
    b2 = ((y20 & 0x0F) << 4) | ((x20 >> 16) & 0x0F)
    b3 = (y20 >> 4) & 0xFF
    b4 = (y20 >> 12) & 0xFF
    return bytes([b0, b1, b2, b3, b4])


def _make_s1p4_frame_33b(
    x_m: float = 1.23,
    y_m: float = -4.56,
    phase: int = 2,
    distance_dm: int = 3450,
    area_mowed_cm2: int = 1250,
) -> bytes:
    """Construct a valid 33-byte s1.4 telemetry frame.

    Uses the apk's 20-bit signed packed pose encoding at bytes [1-5].
    Position arguments are in metres; the encoder converts to raw units
    (x20 = round(x_m * 1000 / 10), y20 = round(y_m * 1000 / 10)).

    distance_dm:    distance in decimetres (distance_m = distance_dm / 10)
    area_mowed_cm2: area in cm² (area_mowed_m2 = area_mowed_cm2 / 100)
    """
    # x20 and y20 are in map-scale millimetres divided by 10 (× 10 factor)
    x20 = round(x_m * 1000 / 10)   # x_mm / 10
    y20 = round(y_m * 1000 / 10)   # y_mm / 10
    pose = _pack_pose(x20, y20)

    frame = bytearray(33)
    frame[0] = 0xCE                                   # delimiter
    frame[1:6] = pose                                 # bytes 1-5: pose
    frame[6] = 0                                      # heading byte
    frame[7] = 0                                      # trace_start_index[0]
    frame[8] = phase                                  # phase byte
    # bytes 9-21: zeros (motion vectors, trace_start, etc.)
    frame[22] = 0                                     # region_id
    frame[23] = 0                                     # task_id
    struct.pack_into("<H", frame, 24, distance_dm)    # bytes 24-25: distance
    struct.pack_into("<H", frame, 26, 50000)          # bytes 26-27: total_area (filler)
    frame[28] = 0
    struct.pack_into("<H", frame, 29, area_mowed_cm2) # bytes 29-30: area_mowed
    frame[31] = 0
    frame[32] = 0xCE                                  # delimiter
    return bytes(frame)


def _make_s1p1_frame_temp_low_set() -> bytes:
    """20-byte heartbeat with battery_temp_low bit asserted at byte[6] bit 3."""
    frame = bytearray(20)
    frame[0] = 0xCE   # delimiter
    frame[6] = 0x08   # bit 3 = battery_temp_low
    frame[19] = 0xCE  # delimiter
    return bytes(frame)


def _make_coordinator_with_cloud(set_cfg_return=True, set_pre_return=True):
    """Return a minimal DreameA2MowerCoordinator stub with a mock cloud client.

    The coordinator is not fully initialised (no hass, no MQTT).  Tests call
    the async write_setting coroutine via ``asyncio.run()`` to avoid needing
    pytest-asyncio.  The hass.async_add_executor_job side-effect runs the
    blocking callable synchronously so no real thread pool is needed.

    ``set_cfg_return`` / ``set_pre_return`` accept the legacy bool flags and
    map them to the honest WriteResult the real transport returns (P2 Task 5):
    True → accepted, False → delivered-but-rejected r=-3.
    """
    from custom_components.dreame_a2_mower.cloud_client import WriteResult

    def _as_result(flag):
        if isinstance(flag, WriteResult):
            return flag
        if flag:
            return WriteResult(delivered=True, accepted=True, code=0)
        return WriteResult(delivered=True, accepted=False, code=-3, msg="not supported")

    coord = object.__new__(DreameA2MowerCoordinator)
    # Minimal attributes required by write_setting
    coord.data = MowerState()
    coord.logger = MagicMock()

    cloud = MagicMock()
    cloud.set_cfg.return_value = _as_result(set_cfg_return)
    cloud.set_pre.return_value = _as_result(set_pre_return)
    coord._cloud = cloud

    # hass mock: async_add_executor_job runs the callable synchronously in
    # the test (no actual thread pool needed).
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor
    coord.hass = hass

    # async_set_updated_data updates coord.data (mirrors real coordinator).
    def _set_updated(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set_updated
    return coord


def _make_coordinator_for_session_tests():
    """Return a minimal DreameA2MowerCoordinator stub with live_map initialised.

    Uses object.__new__ (like the write_setting tests above) to avoid the
    full HA initialisation path; sets the minimal attributes that
    _on_state_update requires.
    """
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState

    from custom_components.dreame_a2_mower.observability import FreshnessTracker, NovelObservationRegistry

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._real_task_state_observed = False
    coord._prev_in_dock = None
    coord._pending_task_op = None
    coord._pending_saw_patrol_start = False
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    # v1.0.0a18: live-trail re-render needs these in __init__-bypassing fixtures.
    coord._live_map_dirty = False
    coord.cloud_state = MagicMock()
    coord.cloud_state.maps_by_id = {}
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = None
    # Task 3: event dispatcher refs (None = race-safe drop until event.py wires up).
    coord._lifecycle_event = None
    coord._notification_event = None
    # F13: s2p2 notification synthesizer state.
    coord._prev_error_code = None
    coord._last_notification = None
    # Single finalize latch (P3e.4) — owned by _CoreMixin.__init__; seed it
    # here since the fixture builds via __new__.
    coord._finalize_lock = asyncio.Lock()
    coord._finalizing_start_ts = None
    return coord


def _make_coordinator_for_finalize_tests(
    pending_object_name: str | None = None,
    pending_first_attempt_unix: int | None = None,
    pending_attempt_count: int | None = None,
    task_state_code: int | None = None,
    session_active: bool | None = None,  # ignored (SM-14: removed from MowerState)
    area_mowed_m2: float | None = None,
    session_started_unix: int | None = None,
    cloud_get_interim_file_url_return: str | None = "https://oss.example.com/signed",
    cloud_get_file_return: bytes | None = None,
):
    """Build a coordinator stub suitable for testing finalize/OSS-fetch methods.

    Wires a mock cloud client, a mock session_archive, and a mock hass
    (async_add_executor_job runs callables synchronously in tests).
    live_map is initialised so end_session() is callable.
    """
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.archive.session import SessionArchive

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(
        pending_session_object_name=pending_object_name,
        pending_session_first_event_unix=pending_first_attempt_unix,
        pending_session_last_attempt_unix=pending_first_attempt_unix,
        pending_session_attempt_count=pending_attempt_count,
        task_state_code=task_state_code,
        # session_active removed from MowerState (SM-14); ignored here
        area_mowed_m2=area_mowed_m2,
        session_started_unix=session_started_unix,
    )
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._real_task_state_observed = False
    coord._prev_in_dock = None
    from custom_components.dreame_a2_mower.observability import FreshnessTracker, NovelObservationRegistry
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()

    # Mock cloud client.
    cloud = MagicMock()
    cloud.get_interim_file_url.return_value = cloud_get_interim_file_url_return
    cloud.get_file.return_value = cloud_get_file_return
    coord._cloud = cloud

    # Mock session_archive with a minimal real-ish count behaviour.
    archive = MagicMock(spec=SessionArchive)
    archive.count = 0
    coord.session_archive = archive

    # T13: lidar_archive_for(map_id) is the per-map accessor; the flat
    # lidar_archive property was removed. Tests that need a real archive
    # set coord.lidar_archives[map_id] directly (see test_lidar_object_name_*).
    coord.lidar_archives = {}
    coord._last_lidar_object_name = None
    coord.cloud_state = MagicMock()
    coord.cloud_state.maps_by_id = {}
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = None
    # Last-session obstacles overlay cache; invalidated by _do_oss_fetch
    # on session finalize so the next Main-view render picks up the
    # freshly-archived session's obstacles.
    coord._last_session_obstacles_by_map = {}

    # Mock hass.
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor

    # async_set_updated_data updates coord.data.
    def _set_updated(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set_updated
    coord.hass = hass

    # Lifecycle/alert event entities — None until wired; _fire_lifecycle
    # race-skips with DEBUG log when not yet registered (same as production).
    coord._lifecycle_event = None
    coord._notification_event = None
    # F13: s2p2 notification synthesizer state.
    coord._prev_error_code = None
    coord._last_notification = None

    # T8 (session-data-completeness) + Task 12 (capture-until-docked):
    # _dispatch_finalize_action now waits up to 10 min for charging_status=1
    # (physical dock) before writing the archive. The finalize tests don't
    # simulate MQTT, so the wait would block for 600s per test. Skip it.
    async def _instant_wait(*args, **kwargs):
        return "test_skip"
    coord._wait_for_dock_return = _instant_wait
    coord._pending_finalize_done = None
    coord._pending_finalize_done_reason = None

    # Single finalize latch (P3e.4) — owned by _CoreMixin.__init__; seed it
    # here since the fixture builds via __new__.
    coord._finalize_lock = asyncio.Lock()
    coord._finalizing_start_ts = None

    return coord


_MINIMAL_SUMMARY_JSON = {
    "start": 1_700_000_000,
    "end": 1_700_003_600,
    "time": 60,
    "mode": 0,
    "result": 0,
    "stop_reason": 0,
    "start_mode": 0,
    "pre_type": 0,
    "md5": "abc123",
    "areas": 120.5,
    "map_area": 5000,
    "dock": None,
    "pref": [],
    "region_status": [],
    "faults": [],
    "spot": [],
    "ai_obstacle": [],
    "obstacle": [],
    "map": [],
    "trajectory": [],
}


def _make_coordinator_for_persist_tests(
    live_map_track: list | None = None,
    live_map_started_unix: int | None = None,
    live_map_dirty: bool = False,
    area_mowed_m2: float | None = None,
    write_in_progress_side_effect=None,
    read_in_progress_return=None,
):
    """Build a minimal coordinator stub suitable for restore/persist tests.

    Uses a real SessionArchive mock (not spec-locked) so read_in_progress
    and write_in_progress can be configured independently.

    ``live_map_track`` is a list of TrackPoint (the track model's single
    source of truth). Defaults to an empty track when a session is started.
    """
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.archive.session import SessionArchive

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(area_mowed_m2=area_mowed_m2)
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._real_task_state_observed = False
    coord._prev_in_dock = None
    coord._live_map_dirty = live_map_dirty
    coord.cloud_state = MagicMock()
    coord.cloud_state.maps_by_id = {}
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = None
    # T3-12: _persist_in_progress now acquires _finalize_lock (owned by
    # _CoreMixin.__init__; seeded manually here since the fixture uses __new__).
    coord._finalize_lock = asyncio.Lock()

    if live_map_started_unix is not None:
        coord.live_map.started_unix = live_map_started_unix
        coord.live_map.track = list(live_map_track) if live_map_track is not None else []

    # Mock session_archive.
    archive = MagicMock(spec=SessionArchive)
    archive.read_in_progress.return_value = read_in_progress_return
    if write_in_progress_side_effect is not None:
        archive.write_in_progress.side_effect = write_in_progress_side_effect
    coord.session_archive = archive

    # Mock hass.
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor

    def _set_updated(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set_updated
    coord.hass = hass

    return coord


def _make_coordinator_for_replay_tests(
    sessions: list | None = None,
    load_return: dict | None = None,
    fetch_map_return=None,
    last_map_md5: str | None = "old-md5",
):
    """Minimal coordinator stub for replay_session tests.

    ``sessions`` is the list returned by session_archive.list_sessions().
    ``load_return`` is what session_archive.load() returns for any entry.
    ``fetch_map_return`` is what cloud.fetch_map() returns.
    """
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.archive.session import SessionArchive
    from tests.integration.conftest import make_empty_cloud_state

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._live_map_dirty = False
    coord.cloud_state = make_empty_cloud_state()
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = None
    coord._base_png = None
    coord._work_log_png = None
    if last_map_md5 is not None:
        coord._last_map_md5_by_id[0] = last_map_md5

    # Mock archive.
    archive = MagicMock(spec=SessionArchive)
    archive.list_sessions.return_value = sessions if sessions is not None else []
    archive.load.return_value = load_return
    coord.session_archive = archive

    # Mock cloud.
    cloud = MagicMock()
    cloud.fetch_map.return_value = fetch_map_return
    coord._cloud = cloud

    # Mock hass.
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor

    def _set_updated(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set_updated
    coord.hass = hass

    return coord


_REPLAY_SUMMARY_JSON = {
    "start": 1_700_000_000,
    "end": 1_700_003_600,
    "time": 60,
    "mode": 0,
    "result": 0,
    "stop_reason": 0,
    "start_mode": 0,
    "pre_type": 0,
    "md5": "replay-md5",
    "areas": 80.0,
    "map_area": 4000,
    "dock": None,
    "pref": [],
    "region_status": [],
    "faults": [],
    "spot": [],
    "ai_obstacle": [],
    "obstacle": [],
    "trajectory": [],
    "map": [
        {
            "id": 0,
            "type": 0,  # BoundaryLayer
            "name": "Main Lawn",
            "area": 80.0,
            "etime": 0,
            "time": 60,
            "data": [
                [0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0],
            ],
            "track": [
                [100, 100], [200, 200], [300, 300],
            ],
        }
    ],
}


_REPLAY_SUMMARY_WITH_OBSTACLES_JSON = {
    "start": 1_700_000_000,
    "end": 1_700_003_600,
    "time": 60,
    "mode": 0,
    "result": 0,
    "stop_reason": 0,
    "start_mode": 0,
    "pre_type": 0,
    "md5": "obs-md5",
    "areas": 80.0,
    "map_area": 4000,
    "dock": None,
    "pref": [],
    "region_status": [],
    "faults": [],
    "spot": [],
    "ai_obstacle": [],
    "trajectory": [],
    "obstacle": [
        {"id": 1, "type": 0, "data": [[-110, 1163], [-145, 1173], [-190, 1228], [-195, 1298], [-150, 1358], [-80, 1363], [-10, 1318], [9, 1248], [-35, 1188]]},
        {"id": 2, "type": 0, "data": [[200, 300], [250, 310], [260, 360], [210, 380], [170, 350], [175, 305]]},
        {"id": 3, "type": 0, "data": [[500, 600], [550, 610], [560, 660], [510, 680], [470, 650], [475, 605]]},
        {"id": 4, "type": 0, "data": [[100, 100], [150, 110], [160, 160], [110, 180], [70, 150], [75, 105]]},
        {"id": 5, "type": 0, "data": [[-300, 400], [-250, 410], [-240, 460], [-290, 480], [-330, 450], [-325, 405]]},
        {"id": 6, "type": 0, "data": [[700, 200], [750, 210], [760, 260], [710, 280], [670, 250], [675, 205]]},
        {"id": 7, "type": 0, "data": [[-500, -200], [-450, -190], [-440, -140], [-490, -120], [-530, -150], [-525, -195]]},
    ],
    "map": [
        {
            "id": 0,
            "type": 0,  # BoundaryLayer
            "name": "Main Lawn",
            "area": 80.0,
            "etime": 0,
            "time": 60,
            "data": [
                [0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0],
            ],
            "track": [
                [100, 100], [200, 200], [300, 300],
            ],
        }
    ],
}


def _make_dispatch_coord_with_map(available_contour_ids):
    """Coordinator stub with cloud_state.maps_by_id populated for dispatch tests."""
    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord._active_map_id = 0
    mock_map = MagicMock()
    mock_map.available_contour_ids = tuple(available_contour_ids)
    coord.cloud_state.maps_by_id = {0: mock_map}
    # routed_action returns synchronously via the mocked async_add_executor_job
    coord._cloud.routed_action = MagicMock()
    return coord


def _empty_cloud_state_parts():
    """The decoded PARTS dict that ``fetch_full_cloud_state`` returns post-P3.5.

    The coordinator composes ``CloudState(**parts)`` in ``_refresh_cloud_state``
    (the CloudState construction moved OUT of transport — R-31/T2-6), so these
    tests mock the transport call to return parts rather than a CloudState.
    """
    import dataclasses

    from custom_components.dreame_a2_mower.state.cloud_state import (
        CloudState,
        ScheduleData,
        SettingsRoot,
    )

    cs = CloudState(
        cfg={},
        maps_by_id={},
        mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map={},
        ota_status=None,
        task_id=0,
        props={},
        mapl=None,
        mihis={},
        fetched_at_unix=0,
    )
    return {f.name: getattr(cs, f.name) for f in dataclasses.fields(cs)}


def _make_coordinator_for_render_tests(last_map_md5: str | None = None):
    """Minimal coordinator stub exercising _render_maps_from_cloud_state."""
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.protocol.map import parse_cloud_map
    from tests.integration.test_map_decoder import _MINIMAL_MAP
    import copy

    coord = object.__new__(DreameA2MowerCoordinator)
    md = parse_cloud_map(copy.deepcopy(_MINIMAL_MAP))
    assert md is not None
    coord.cloud_state = MagicMock()
    coord.cloud_state.maps_by_id = {0: md}
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    if last_map_md5 is not None:
        coord._last_map_md5_by_id[0] = last_map_md5

    hass = MagicMock()

    async def _exec(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _exec
    coord.hass = hass
    return coord, md
