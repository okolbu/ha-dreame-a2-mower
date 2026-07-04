"""s2p2=51 (patrol-start) latch — a POINT patrol's only type signal.

A point patrol emits no captured s2p50 op echo; its only type clue is
s2p2=51, which arrives AT session start (before begin_session) and is dropped
by _capture_telemetry_sample's is_active() guard. The latch records it ungated
and seeds live_map.saw_patrol_start at begin so classify types it as patrol.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.session import SessionArchive
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.state import MowerState


def _coord(tmp_path):
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = SessionArchive(tmp_path)
    c.live_map = LiveMapState()
    c._pending_task_op = None
    c._pending_saw_patrol_start = False
    c._live_map_dirty = False
    return c


def test_s2p2_51_latches_ungated_when_inactive(tmp_path):
    c = _coord(tmp_path)
    assert not c.live_map.is_active()
    c._capture_telemetry_sample((2, 2), 51, 1000)
    assert c._pending_saw_patrol_start is True
    # inactive -> not stamped on lm yet, and not appended to error_samples
    assert c.live_map.saw_patrol_start is False
    assert c.live_map.error_samples == []


def test_s2p2_51_in_session_sets_lm_flag_and_buffer(tmp_path):
    c = _coord(tmp_path)
    c.live_map.begin_session(1000)
    c._capture_telemetry_sample((2, 2), 51, 1001)
    assert c.live_map.saw_patrol_start is True
    assert [code for _, code in c.live_map.error_samples] == [51]


def test_other_s2p2_codes_do_not_latch(tmp_path):
    c = _coord(tmp_path)
    c._capture_telemetry_sample((2, 2), 75, 1000)
    assert c._pending_saw_patrol_start is False


def test_seed_stamps_saw_patrol_start(tmp_path):
    c = _coord(tmp_path)
    c._pending_saw_patrol_start = True
    c.live_map.begin_session(2000)          # nulls saw_patrol_start
    assert c.live_map.saw_patrol_start is False
    c._seed_session_type_from_pending()
    assert c.live_map.saw_patrol_start is True


def test_provisional_type_is_patrol_from_latched_flag(tmp_path):
    # No op, empty error_samples (51 was dropped pre-session) — only the
    # durable lm flag carries the patrol type.
    c = _coord(tmp_path)
    c.live_map.begin_session(2000)
    c.live_map.saw_patrol_start = True
    assert c.live_map.last_task_op is None
    assert c.live_map.error_samples == []
    assert c._provisional_session_type() == "patrol"
    assert c._provisional_session_is_cloud_finalized() is True
