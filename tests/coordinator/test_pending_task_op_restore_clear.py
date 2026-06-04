"""Pending op survives a boot via sidecar; cleared on finalize."""
from __future__ import annotations

from custom_components.dreame_a2_mower.archive.session import SessionArchive
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_load_pending_op_from_sidecar(tmp_path):
    arc = SessionArchive(tmp_path)
    arc.write_pending_op(108)
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = arc
    c.live_map = LiveMapState()
    c._pending_task_op = None
    c._load_pending_op_from_sidecar()
    assert c._pending_task_op == 108


def test_clear_pending_op_removes_sidecar(tmp_path):
    arc = SessionArchive(tmp_path)
    arc.write_pending_op(107)
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = arc
    c._pending_task_op = 107
    c._clear_pending_op()
    assert c._pending_task_op is None
    assert arc.read_pending_op() is None


def test_clear_is_idempotent_when_no_sidecar(tmp_path):
    arc = SessionArchive(tmp_path)
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = arc
    c._pending_task_op = None
    c._clear_pending_op()                 # must not raise when nothing to clear
    assert c._pending_task_op is None
    assert arc.read_pending_op() is None
