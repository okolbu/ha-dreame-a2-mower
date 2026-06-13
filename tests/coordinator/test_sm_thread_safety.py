"""Phase 1.3 — state-machine thread safety.

MQTT property pushes arrive on paho's network thread. The paho thread must do
ONLY pure decode; ALL mutation of shared state (state_machine snapshot,
novel_registry, live_map wifi buffer) must be deferred onto the HA event loop
via call_soon_threadsafe.

These spy tests capture the scheduled hop callback(s) instead of running them
(mirroring tests/coordinator/test_render_thread_safety.py), assert NOTHING
mutated immediately after the paho-thread call, then invoke the captured
callback(s) and assert the mutation landed on the loop.
"""
from __future__ import annotations

import base64
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker,
    NovelObservationRegistry,
)


def _make_coord(*, capture: list):
    """Coordinator stub whose loop.call_soon_threadsafe CAPTURES the callback
    (paho-thread simulation) instead of running it.
    """
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord.state_machine = MowerStateMachine()
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._prev_task_state = None
    coord._real_task_state_observed = False
    coord._prev_in_dock = None
    coord._prev_error_code = None
    coord._prev_charging_status = None
    coord._rain_delay_started_at = None
    coord._pending_task_op = None
    coord._pending_saw_patrol_start = False
    coord._pending_finalize_done = None
    coord._live_map_dirty = False
    coord._live_trail_dirty = False
    coord._last_live_render_unix = 0.0
    coord._last_lidar_object_name = None
    coord._prev_s2p56_empty = None
    coord.entry = MagicMock()
    coord.entry.options = {}
    coord._active_map_id = None
    coord.cloud_state = MagicMock()
    coord.cloud_state.maps_by_id = {}
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._lifecycle_event = None
    coord._notification_event = None
    coord._last_notification = None

    coord.async_set_updated_data = lambda s: setattr(coord, "data", s)
    coord._handle_emergency_stop_transition = lambda *a, **k: None
    coord._compute_target_area_m2 = lambda s: None
    coord._begin_live_stream = lambda: None
    coord._publish_live_point = lambda **k: None
    coord._provisional_session_is_cloud_finalized = lambda: False
    coord._fire_lifecycle = lambda *a, **k: None
    coord._schedule_render_base = lambda: None

    hass = MagicMock()
    hass.loop.call_soon_threadsafe = lambda cb, *a: capture.append(cb)
    coord.hass = hass
    return coord


# ---------------------------------------------------------------------------
# handle_property_push — no mutation on the calling (paho) thread
# ---------------------------------------------------------------------------


def test_hpp_unmapped_slot_no_paho_thread_mutation():
    """An unmapped slot (novel 'property') must NOT touch novel_registry on the
    calling thread — recording is deferred to the captured loop callback."""
    captured: list = []
    coord = _make_coord(capture=captured)

    coord.handle_property_push(siid=99, piid=42, value=7)

    # NOTHING recorded on the paho thread.
    assert coord.novel_registry.snapshot().count == 0, (
        "novel_registry mutated on the calling (paho) thread"
    )
    assert len(captured) >= 1, "a loop callback must have been scheduled"

    # Run the captured callback(s) — NOW the mutation lands.
    for cb in captured:
        cb()
    property_obs = [
        o for o in coord.novel_registry.snapshot().observations
        if o.category == "property"
    ]
    assert len(property_obs) == 1
    assert property_obs[0].detail == "siid=99 piid=42"


def test_hpp_mapped_novel_value_no_paho_thread_mutation():
    """A mapped slot with a novel value records a 'value' obs — deferred."""
    captured: list = []
    coord = _make_coord(capture=captured)

    coord.handle_property_push(siid=2, piid=2, value=999)

    assert coord.novel_registry.snapshot().count == 0
    for cb in captured:
        cb()
    value_obs = [
        o for o in coord.novel_registry.snapshot().observations
        if o.category == "value"
    ]
    assert len(value_obs) == 1
    assert "value=999" in value_obs[0].detail


def test_hpp_s2p56_no_sm_or_livemap_mutation_on_paho_thread():
    """An s2p56 push that begins a session must not mutate state_machine OR
    live_map on the calling thread; both land only when the hop runs."""
    captured: list = []
    coord = _make_coord(capture=captured)

    before_snap = coord.state_machine.snapshot()
    assert not coord.live_map.is_active()

    coord.handle_property_push(siid=2, piid=56, value={"status": [[1, 0]]})

    # Paho thread: SM snapshot and live_map both UNCHANGED.
    assert coord.state_machine.snapshot() == before_snap, (
        "state_machine mutated on the calling (paho) thread"
    )
    assert not coord.live_map.is_active(), (
        "live_map mutated on the calling (paho) thread"
    )

    for cb in captured:
        cb()

    # Loop: the session began (live_map active via _on_state_update).
    assert coord.live_map.is_active()


# ---------------------------------------------------------------------------
# TRAP #1 — novel recording survives the unchanged-state early return
# ---------------------------------------------------------------------------


def test_trap1_unchanged_state_push_still_records_novel_after_hop():
    """s2p1 maps to 'state' which apply_property_to_state drops, so
    new_state == self.data (the common no-op case). Novel recording for an
    unmapped no-op slot MUST still happen (deferred to the loop)."""
    captured: list = []
    coord = _make_coord(capture=captured)

    # Unmapped slot whose apply is a no-op: new_state == self.data.
    coord.handle_property_push(siid=99, piid=99, value=123)

    # Paho thread: nothing recorded.
    assert coord.novel_registry.snapshot().count == 0
    # A hop was scheduled even though state is unchanged.
    assert len(captured) >= 1, (
        "TRAP #1: a loop callback must be scheduled even on a no-op-state push "
        "so novel recording is not lost"
    )

    for cb in captured:
        cb()

    property_obs = [
        o for o in coord.novel_registry.snapshot().observations
        if o.category == "property"
    ]
    assert len(property_obs) == 1, (
        "TRAP #1: novel recording lost on an unchanged-state push"
    )
    assert property_obs[0].detail == "siid=99 piid=99"


def test_trap1_s2p1_records_nothing_changes_but_sm_unaffected_by_hpp():
    """s2p1 (key 2,1) is a no-op for MowerState (field 'state' dropped). hpp
    must not early-return in a way that loses the hop, and must not mutate the
    SM on the paho thread (the SM is driven by the dispatcher, not hpp)."""
    captured: list = []
    coord = _make_coord(capture=captured)
    before_snap = coord.state_machine.snapshot()

    coord.handle_property_push(siid=2, piid=1, value=6)

    assert coord.state_machine.snapshot() == before_snap
    # No crash; run any scheduled callbacks.
    for cb in captured:
        cb()


# ---------------------------------------------------------------------------
# _on_mqtt_message dispatcher — paho-thread purity
# ---------------------------------------------------------------------------


def test_dispatcher_s1p1_heartbeat_deferred():
    """s1p1 heartbeat must not call state_machine.handle_heartbeat OR append a
    wifi sample on the paho thread; both update only when the hop runs.

    The wifi-buffer purity assertion is regression safety for the one live_map
    mutation that moved into _apply_heartbeat (P1.3): the append must NOT run on
    paho's thread. We arm the append gate (active live_map + a known position +
    the frame's always-present wifi_rssi_dbm) so the sample genuinely *would*
    land, then pin that it lands only after the hop.
    """
    captured: list = []
    coord = _make_coord(capture=captured)

    # Arm the wifi-sample gate in _apply_heartbeat: needs an active live_map
    # and a non-None position; the decoded heartbeat always carries an rssi.
    coord.live_map.begin_session(started_unix=1000)
    coord.data.position_x_m = 1.0
    coord.data.position_y_m = 2.0
    assert coord.live_map.wifi_samples == []

    before = coord.state_machine.snapshot().last_heartbeat_unix
    wifi_before = len(coord.live_map.wifi_samples)

    # A valid 20-byte s1p1 heartbeat frame: 0xCE delimiters at [0] and [19].
    frame = bytearray(20)
    frame[0] = 0xCE
    frame[19] = 0xCE
    blob = base64.b64encode(bytes(frame)).decode("ascii")
    payload = {
        "method": "properties_changed",
        "params": [{"siid": 1, "piid": 1, "value": blob}],
    }
    coord._on_mqtt_message("topic", payload)

    # Paho thread: heartbeat NOT applied.
    assert coord.state_machine.snapshot().last_heartbeat_unix == before, (
        "handle_heartbeat ran on the calling (paho) thread"
    )
    # Paho thread: wifi-sample buffer UNCHANGED (append did not run here).
    assert len(coord.live_map.wifi_samples) == wifi_before, (
        "append_wifi_sample ran on the calling (paho) thread"
    )
    assert len(captured) >= 1

    for cb in captured:
        cb()

    # Loop: heartbeat applied (last_heartbeat_unix now set).
    assert coord.state_machine.snapshot().last_heartbeat_unix is not None
    assert coord.state_machine.snapshot().last_heartbeat_unix != before
    # Loop: the wifi sample DID land once the hop ran.
    assert len(coord.live_map.wifi_samples) == wifi_before + 1, (
        "wifi sample did not land on the event loop"
    )


def test_dispatcher_s2p2_handle_mqtt_property_deferred():
    """s2p2 fault push: state_machine.handle_mqtt_property must not run on the
    paho thread. The SM raw_s2p2 updates only when the hop runs."""
    captured: list = []
    coord = _make_coord(capture=captured)

    before = coord.state_machine.snapshot().raw_s2p2

    payload = {
        "method": "properties_changed",
        "params": [{"siid": 2, "piid": 2, "value": 50}],
    }
    coord._on_mqtt_message("topic", payload)

    assert coord.state_machine.snapshot().raw_s2p2 == before, (
        "handle_mqtt_property ran on the calling (paho) thread"
    )
    assert len(captured) >= 1

    for cb in captured:
        cb()

    assert coord.state_machine.snapshot().raw_s2p2 == 50


# ---------------------------------------------------------------------------
# Run-inline compatibility — the existing lambda fn: fn() mock still works
# ---------------------------------------------------------------------------


def test_run_inline_mock_applies_everything():
    """With call_soon_threadsafe = lambda fn: fn(), the deferred callbacks run
    synchronously (the existing test convention). End-to-end mutation lands."""
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord.state_machine = MowerStateMachine()
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._prev_task_state = None
    coord._real_task_state_observed = False
    coord._prev_in_dock = None
    coord._prev_error_code = None
    coord._prev_charging_status = None
    coord._rain_delay_started_at = None
    coord._pending_task_op = None
    coord._pending_saw_patrol_start = False
    coord._pending_finalize_done = None
    coord._live_map_dirty = False
    coord._live_trail_dirty = False
    coord._last_live_render_unix = 0.0
    coord._last_lidar_object_name = None
    coord._prev_s2p56_empty = None
    coord.entry = MagicMock()
    coord.entry.options = {}
    coord._active_map_id = None
    coord.cloud_state = MagicMock()
    coord.cloud_state.maps_by_id = {}
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._lifecycle_event = None
    coord._notification_event = None
    coord._last_notification = None

    hass = MagicMock()
    hass.loop.call_soon_threadsafe.side_effect = lambda fn: fn()
    coord.async_set_updated_data = lambda s: setattr(coord, "data", s)
    coord.hass = hass

    coord.handle_property_push(siid=99, piid=42, value=7)
    obs = [
        o for o in coord.novel_registry.snapshot().observations
        if o.category == "property"
    ]
    assert len(obs) == 1
