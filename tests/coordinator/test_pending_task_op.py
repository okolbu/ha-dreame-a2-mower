"""Pending task-op latch: capture every s2p50 op echo ungated, write sidecar."""
from __future__ import annotations

from custom_components.dreame_a2_mower.archive.session import SessionArchive
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def _coord(tmp_path):
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = SessionArchive(tmp_path)
    c.live_map = LiveMapState()
    c._pending_task_op = None
    return c


def test_latch_sets_attr_and_sidecar_ungated_by_active(tmp_path):
    c = _coord(tmp_path)
    assert not c.live_map.is_active()          # no session yet
    c._latch_task_op(107)
    assert c._pending_task_op == 107
    assert c.session_archive.read_pending_op() == 107


def test_latch_last_wins_no_window(tmp_path):
    c = _coord(tmp_path)
    c._latch_task_op(108)
    c._latch_task_op(102)
    assert c._pending_task_op == 102
    assert c.session_archive.read_pending_op() == 102


def test_handle_task_op_echo_parses_d_o(tmp_path):
    c = _coord(tmp_path)
    c._handle_task_op_echo({"d": {"o": 107}})
    assert c._pending_task_op == 107


def test_handle_task_op_echo_parses_flat_o(tmp_path):
    c = _coord(tmp_path)
    c._handle_task_op_echo({"o": 108})
    assert c._pending_task_op == 108


def test_handle_task_op_echo_ignores_missing_op(tmp_path):
    c = _coord(tmp_path)
    c._handle_task_op_echo({"d": {}})
    assert c._pending_task_op is None
    assert c.session_archive.read_pending_op() is None


def test_handle_task_op_echo_when_active_sets_last_task_op(tmp_path):
    c = _coord(tmp_path)
    c.live_map.begin_session(1000)             # active mid-session
    c._handle_task_op_echo({"d": {"o": 102}})
    assert c.live_map.last_task_op == 102       # immediate set for live session
    assert c._pending_task_op == 102
