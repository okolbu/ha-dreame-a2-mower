"""Regression: a dock-started patrol is typed `patrol` and not finalized on
the first point arrival.

Reproduces the 2026-06-04 bug: s2p50 op echo + s2p2=51 arrive before
begin_session, are lost, so classify falls through to maintenance_run and the
s2p2=75 gate finalizes early. With the pending-op latch, begin_session seeds
last_task_op=107 so the session is cloud-finalized (patrol) and the early gate
is skipped.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.session import SessionArchive
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState


class _NullFreshness:
    def record(self, *a, **k): pass


def _coord(tmp_path, monkeypatch):
    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.session_archive = SessionArchive(tmp_path)
    c.live_map = LiveMapState()
    c.data = MowerState()
    c._pending_task_op = None
    c._pending_saw_patrol_start = False

    # Task-state transition tracking.
    c._prev_task_state = None
    c._real_task_state_observed = True

    # Cloud state + active-map (read by _compute_target_area_m2).
    c.cloud_state = None
    c._active_map_id = None

    # Dock / charging / error-code edge trackers.
    c._prev_in_dock = None
    c._prev_charging_status = None
    c._prev_error_code = None

    # Rain-delay and pending-finalize sentinels.
    c._rain_delay_started_at = None
    c._pending_finalize_done = None

    # Freshness tracker stub (records timing metadata; pure side-effect).
    c.freshness = _NullFreshness()

    # Session lifecycle callbacks — sync stubs; the real impls schedule HA
    # tasks which we don't need for this unit test.
    c._begin_live_stream = lambda: None
    c._fire_lifecycle = lambda *a, **k: None

    # Async methods that _on_state_update schedules via hass.async_create_task.
    # Defined as coroutine functions so the `self._foo()` call constructs a
    # coroutine object without raising; async_create_task then discards it.
    async def _noop_coro(*a, **k): pass
    c._refresh_mapl = _noop_coro
    c._render_base = _noop_coro
    c._handle_lidar_object_name = _noop_coro

    # HA event loop handle — async_create_task is called but we discard the
    # coroutine; hass.async_create_task just returns None.
    hass = MagicMock()
    hass.async_create_task = lambda *a, **k: None
    c.hass = hass

    # build_settings_snapshot_v2 reads many coordinator attrs; monkeypatch the
    # symbol used by the module so the session-start path is a no-op.
    import custom_components.dreame_a2_mower.coordinator._mqtt_handlers as mh
    monkeypatch.setattr(mh, "build_settings_snapshot_v2", lambda *a, **k: None)

    # Do NOT stub _provisional_session_type or _provisional_session_is_cloud_finalized
    # — the test verifies the real implementations.
    return c


def test_dock_started_point_patrol_typed_patrol_not_finalized(tmp_path, monkeypatch):
    """Full dock-start race: op echo before begin_session; session is
    typed patrol (cloud-finalized); early-finalize gate skips.
    """
    c = _coord(tmp_path, monkeypatch)

    # ── 1. Op echo arrives while no session is active (dock-start race). ──
    c._handle_task_op_echo({"d": {"o": 107}})
    assert not c.live_map.is_active(),      "No session should be active yet"
    assert c.live_map.last_task_op is None, "echo must not seed live_map while inactive"
    assert c._pending_task_op == 107,       "echo must be latched in _pending_task_op"

    # ── 2. First MQTT push: idle → running triggers begin_session + seed. ──
    s = MowerState()
    s.task_state_code = 0          # None→0: fires begin_session
    c._on_state_update(s, now_unix=2000)

    assert c.live_map.is_active(),             "Session must be active after begin"
    assert c.live_map.last_task_op == 107,     "Pending op must be seeded into live_map"

    # ── 3. Provisional type resolves to patrol (cloud-finalized). ──
    assert c._provisional_session_type() == "patrol", (
        "With last_task_op=107, session must classify as patrol"
    )
    assert c._provisional_session_is_cloud_finalized() is True, (
        "Patrol is cloud-finalized — early gate must be skipped"
    )

    # ── 4. s2p2=75 (arrived-at-point) early-finalize gate guard skips. ──
    # The guard is: if is_active AND NOT cloud_finalized → finalize early.
    # Append a point to simulate the first position push post-arrival.
    c.live_map.append_point(
        t=2100.0, x_m=1.0, y_m=1.0, area_m2=0.0, heading_deg=0.0
    )
    gate_would_finalize = (
        c.live_map.is_active()
        and not c._provisional_session_is_cloud_finalized()
    )
    assert not gate_would_finalize, (
        "Early-finalize gate must SKIP for a cloud-finalized (patrol) session"
    )


def test_dock_started_point_patrol_typed_patrol_via_s2p2_51(tmp_path, monkeypatch):
    """The real point-patrol case: NO op echo is captured (last_task_op stays
    None); the only type signal is s2p2=51, arriving BEFORE begin_session.
    The ungated 51-latch + seed must still type it patrol.

    Reproduces the v1.0.22a9 miss: the op-echo latch caught nothing (point
    patrols don't deliver it), and 51 was dropped by _capture_telemetry_sample's
    is_active() guard, so the session mis-typed maintenance_run ("To Point").
    """
    c = _coord(tmp_path, monkeypatch)

    # ── 1. s2p2=51 arrives while no session is active (it lands at start). ──
    c._capture_telemetry_sample((2, 2), 51, 1999)
    assert not c.live_map.is_active(),         "No session active yet"
    assert c._pending_saw_patrol_start is True, "51 must latch ungated"
    assert c.live_map.error_samples == [],      "51 must NOT enter the buffer pre-session"
    assert c.live_map.last_task_op is None,     "no op echo for a point patrol"

    # ── 2. First MQTT push fires begin_session (which would drop a buffered 51). ──
    s = MowerState()
    s.task_state_code = 0
    c._on_state_update(s, now_unix=2000)
    assert c.live_map.is_active()
    assert c.live_map.saw_patrol_start is True, "seed must stamp the durable flag"

    # ── 3. Types as patrol from the durable flag alone (no op, empty buffer). ──
    assert c.live_map.last_task_op is None
    assert [code for _, code in c.live_map.error_samples] == [], (
        "begin_session wiped the buffer — only the latched flag carries the type"
    )
    assert c._provisional_session_type() == "patrol"
    assert c._provisional_session_is_cloud_finalized() is True
