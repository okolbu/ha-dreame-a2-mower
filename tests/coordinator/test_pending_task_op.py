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
    c._pending_saw_patrol_start = False
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


def test_handle_task_op_echo_all_corpus_shapes(tmp_path):
    # The three s2p50 echo shapes seen in probe_log_20260520, plus the SEND
    # form (op at top + d=payload) the old `value.get("d") or value` form missed.
    cases = [
        {"d": {"error": 0, "exe": True, "o": 107, "status": True}, "t": "TASK"},  # wrapped
        {"error": 0, "estimate_time": 155, "exe": True, "o": 107, "status": True, "time": 1},  # unwrapped
        {"exe": False, "o": 107, "status": False},  # reject echo
        {"m": "a", "o": 107, "d": {"point": [3, 4]}},  # SEND (op top + d payload)
    ]
    for value in cases:
        c = _coord(tmp_path)
        c._handle_task_op_echo(value)
        assert c._pending_task_op == 107, f"missed op in {value!r}"


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


from custom_components.dreame_a2_mower.state import MowerState


class _NullFreshness:
    def record(self, *a, **k): pass


def _coord_for_state_update(tmp_path):
    from unittest.mock import MagicMock
    c = _coord(tmp_path)
    c.data = MowerState()
    c._prev_task_state = None
    c._real_task_state_observed = True
    c._begin_live_stream = lambda: None
    c._fire_lifecycle = lambda *a, **k: None
    # cloud_state + _active_map_id read by _compute_target_area_m2.
    c.cloud_state = None
    c._active_map_id = None
    # Dock / charging / error-code trackers.
    c._prev_in_dock = None
    c._prev_charging_status = None
    c._prev_error_code = None
    c._rain_delay_started_at = None
    c._pending_finalize_done = None
    # Freshness tracker stub.
    c.freshness = _NullFreshness()
    # _provisional_session_is_cloud_finalized drives finalize gate.
    c._provisional_session_is_cloud_finalized = lambda: False
    # _refresh_mapl / _render_base / _handle_lidar_object_name are awaitable;
    # hass.async_create_task receives the coroutine but our lambda discards it
    # (never awaited). Define them as sync stubs returning None so the call
    # `self._refresh_mapl()` constructs something without raising.
    async def _noop_coro(*a, **k): pass
    c._refresh_mapl = _noop_coro
    c._render_base = _noop_coro
    c._handle_lidar_object_name = _noop_coro
    hass = MagicMock()
    hass.async_create_task = lambda *a, **k: None
    c.hass = hass
    # build_settings_snapshot_v2 reads many attrs; stub the symbol the module uses.
    # The begin-session snapshot call lives in domain/session/lifecycle_events.py
    # (P3.7 ingress split), so patch the symbol there.
    import custom_components.dreame_a2_mower.domain.session.lifecycle_events as mh
    c.__class__._orig_bss = getattr(mh, "build_settings_snapshot_v2")
    mh.build_settings_snapshot_v2 = lambda *a, **k: None
    return c, mh


def test_begin_session_seeds_pending_op(tmp_path):
    c, mh = _coord_for_state_update(tmp_path)
    try:
        c._latch_task_op(107)                  # echo arrived BEFORE session
        assert not c.live_map.is_active()
        s = MowerState()
        s.task_state_code = 0                  # idle -> running triggers begin
        c._on_state_update(s, now_unix=2000)
        assert c.live_map.is_active()
        assert c.live_map.last_task_op == 107  # SEEDED at birth
    finally:
        mh.build_settings_snapshot_v2 = c.__class__._orig_bss


def test_begin_session_seeds_non_patrol_op(tmp_path):
    c, mh = _coord_for_state_update(tmp_path)
    try:
        c._latch_task_op(109)                  # cruise-to-point, not patrol
        s = MowerState()
        s.task_state_code = 0
        c._on_state_update(s, now_unix=2000)
        assert c.live_map.last_task_op == 109
    finally:
        mh.build_settings_snapshot_v2 = c.__class__._orig_bss
