"""Coordinator in_progress.json persist + restore tests (domain/session/persistence).

Split out of the test_coordinator.py monolith (P3.11); tests moved verbatim.
"""
from __future__ import annotations


from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
from tests.integration._coordinator_helpers import (
    _make_coordinator_for_persist_tests,
)


def test_persist_in_progress_includes_settings_snapshot():
    """_persist_in_progress writes settings_snapshot into the JSON payload."""
    import asyncio

    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=1_700_000_000,
        live_map_dirty=True,
    )
    coord.live_map.settings_snapshot = {"settings_edgemaster": True}

    asyncio.run(coord._persist_in_progress())

    coord.session_archive.write_in_progress.assert_called_once()
    written_payload = coord.session_archive.write_in_progress.call_args[0][0]
    assert written_payload["settings_snapshot"] == {"settings_edgemaster": True}


def test_restore_in_progress_rehydrates_settings_snapshot():
    """_restore_in_progress populates live_map.settings_snapshot from disk."""
    import asyncio

    disk_payload = {
        "session_start_ts": 1_700_000_000,
        "track": [],
        "wifi_samples": [],
        "battery_samples": [],
        "charging_status_samples": [],
        "state_samples": [],
        "error_samples": [],
        "charge_at_start": 87,
        "settings_snapshot": {"settings_edgemaster": True, "settings_mowing_height_mm": 30},
        "area_mowed_m2": 0,
        "map_area_m2": 0,
    }
    coord = _make_coordinator_for_persist_tests(read_in_progress_return=disk_payload)

    asyncio.run(coord._restore_in_progress())

    assert coord.live_map.settings_snapshot == {
        "settings_edgemaster": True,
        "settings_mowing_height_mm": 30,
    }


def test_restore_in_progress_missing_settings_snapshot_legacy():
    """Legacy in_progress.json without settings_snapshot → field stays None."""
    import asyncio

    disk_payload = {
        "session_start_ts": 1_700_000_000,
        "track": [],
    }
    coord = _make_coordinator_for_persist_tests(read_in_progress_return=disk_payload)

    asyncio.run(coord._restore_in_progress())

    assert coord.live_map.settings_snapshot is None


def test_restore_in_progress_populates_live_map_from_disk():
    """On HA boot with a valid in_progress.json, live_map is repopulated.

    After _restore_in_progress:
    - live_map.started_unix matches session_start_ts from disk
    - live_map.track contains the restored points
    - live_map.is_active() is True (SM-14: session_active removed from MowerState)
    - MowerState.session_track_segments reflects the track as a single flat
      segment (track-model invariant)
    """
    import asyncio

    # Track rows: [t, x, y, area, heading, task_state, role].
    disk_payload = {
        "session_start_ts": 1_714_329_600,
        "track": [
            [1_714_329_601, 1.0, 2.0, 0.0, None, 0, "mowing"],
            [1_714_329_602, 3.0, 4.0, 0.5, None, 0, "mowing"],
            [1_714_329_603, 5.0, 6.0, 1.0, None, 0, "mowing"],
        ],
        "area_mowed_m2": 42.0,
        "map_area_m2": 0,
        "last_update_ts": 1_714_329_700,
    }
    coord = _make_coordinator_for_persist_tests(read_in_progress_return=disk_payload)

    asyncio.run(coord._restore_in_progress())

    assert coord.live_map.started_unix == 1_714_329_600
    assert coord.live_map.total_points() == 3
    assert [(p.x_m, p.y_m) for p in coord.live_map.track] == [
        (1.0, 2.0), (3.0, 4.0), (5.0, 6.0),
    ]

    assert coord.live_map.is_active()  # SM-14: use live_map, not session_active
    assert coord.data.session_started_unix == 1_714_329_600
    # Track model: producers emit ONE flat segment holding every point.
    assert isinstance(coord.data.session_track_segments, tuple)
    assert len(coord.data.session_track_segments) == 1
    assert coord.data.session_track_segments[0] == (
        (1.0, 2.0), (3.0, 4.0), (5.0, 6.0),
    )


def test_restore_in_progress_no_file_leaves_state_unchanged():
    """When read_in_progress returns None, live_map stays idle and MowerState unchanged."""
    import asyncio

    coord = _make_coordinator_for_persist_tests(read_in_progress_return=None)
    original_state = coord.data

    asyncio.run(coord._restore_in_progress())

    assert not coord.live_map.is_active()
    # MowerState unchanged — async_set_updated_data not called.
    assert coord.data is original_state


def test_restore_in_progress_skips_if_live_map_already_active():
    """If MQTT arrived first and live_map is already active, restore is skipped."""
    import asyncio

    from custom_components.dreame_a2_mower.live_map.state import TrackPoint

    disk_payload = {
        "session_start_ts": 1_000_000,
        "track": [[1_000_001, 0.0, 0.0, 0.0, None, 0, "mowing"]],
        "area_mowed_m2": 0.0,
        "map_area_m2": 0,
    }
    # Pre-start a session in live_map (simulates MQTT arriving before restore).
    mqtt_point = TrackPoint(
        t=2_000_001, x_m=9.0, y_m=9.0, area_m2=0.0,
        heading_deg=None, task_state=0, role="mowing",
    )
    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=2_000_000,  # a *different* (newer) session
        live_map_track=[mqtt_point],
        read_in_progress_return=disk_payload,
    )

    asyncio.run(coord._restore_in_progress())

    # live_map should still have the MQTT-driven session, not the disk one.
    assert coord.live_map.started_unix == 2_000_000
    assert [(p.x_m, p.y_m) for p in coord.live_map.track] == [(9.0, 9.0)]
    # async_set_updated_data should NOT have been called (state unchanged).
    # SM-14: session_active removed from MowerState; verify live_map not changed.
    assert not coord.live_map.is_active() or coord.live_map.started_unix == 2_000_000


def test_restore_in_progress_zero_start_ts_discards():
    """An in-progress entry with session_start_ts=0 is treated as invalid."""
    import asyncio

    disk_payload = {"session_start_ts": 0, "track": [], "area_mowed_m2": 0.0}
    coord = _make_coordinator_for_persist_tests(read_in_progress_return=disk_payload)

    asyncio.run(coord._restore_in_progress())

    assert not coord.live_map.is_active()


def test_restore_in_progress_empty_track_starts_active():
    """An in-progress entry with an empty track still sets live_map active."""
    import asyncio

    disk_payload = {"session_start_ts": 1_714_329_600, "track": [], "area_mowed_m2": 0.0}
    coord = _make_coordinator_for_persist_tests(read_in_progress_return=disk_payload)

    asyncio.run(coord._restore_in_progress())

    assert coord.live_map.is_active()
    # An empty track on disk still yields an active session ready for
    # incoming telemetry; no points captured yet.
    assert coord.live_map.track == []
    assert coord.live_map.total_points() == 0


def test_restore_then_mqtt_first_push_preserves_track():
    """Mid-mow restart: the first MQTT s2p56 push after restore must NOT
    clobber the disk-restored track by calling begin_session(now_unix).

    Reproduces the trail-loss-on-restart bug:
    1. HA restarts mid-mow; in_progress.json has the session.
    2. _restore_in_progress runs early (before MQTT can push), populating
       live_map.track and started_unix from disk.
    3. MQTT first push lands carrying task_state_code=0 (running).
       _prev_task_state is None at boot, so without the guard
       _on_state_update would treat None→0 as a fresh begin_session and
       wipe the just-restored track.

    With the fix in place: live_map.track survives, started_unix stays at
    the original (firmware-issued) session start, and _prev_task_state
    advances to 0 so the finalize gate works correctly on subsequent ticks.
    """
    import asyncio

    from custom_components.dreame_a2_mower.observability import (
        FreshnessTracker,
        NovelObservationRegistry,
    )

    # Track rows: [t, x, y, area, heading, task_state, role].
    disk_payload = {
        "session_start_ts": 1_714_329_600,
        "track": [
            [1_714_329_601, 1.0, 2.0, 0.0, None, 0, "mowing"],
            [1_714_329_602, 3.0, 4.0, 0.5, None, 0, "mowing"],
            [1_714_329_603, 5.0, 6.0, 1.0, None, 0, "mowing"],
        ],
        "area_mowed_m2": 42.0,
        "map_area_m2": 0,
        "last_update_ts": 1_714_329_700,
    }
    coord = _make_coordinator_for_persist_tests(read_in_progress_return=disk_payload)
    # _on_state_update needs these in addition to the persist-test stub.
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._prev_error_code = None
    coord._last_notification = None
    coord._lifecycle_event = None
    coord._notification_event = None

    # Step 1: restore from disk (runs before MQTT in the fixed ordering).
    asyncio.run(coord._restore_in_progress())
    assert coord.live_map.is_active()
    assert coord.live_map.started_unix == 1_714_329_600
    assert coord.live_map.total_points() == 3

    # Step 2: simulate the first MQTT s2p56 push that would normally land
    # AFTER restore. task_state_code=0 (running). prev_task_state is None
    # at boot. Without the guard, _on_state_update would call
    # begin_session(now) here and clobber the track.
    now_after_restart = 1_714_330_000  # ~7 minutes after disk start_ts
    new_state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 0]]}
    )
    result = coord._on_state_update(new_state, now_after_restart)

    # Track preserved.
    assert coord.live_map.total_points() == 3, (
        "First MQTT push after restore wiped the disk-restored track "
        "(begin_session was called when it shouldn't have been)"
    )
    assert [(p.x_m, p.y_m) for p in coord.live_map.track] == [
        (1.0, 2.0), (3.0, 4.0), (5.0, 6.0),
    ]

    # started_unix kept at the disk (firmware-original) value, NOT the
    # current restart time.
    assert coord.live_map.started_unix == 1_714_329_600
    assert result.session_started_unix == 1_714_329_600

    # _prev_task_state advanced so the finalize gate's session-end
    # detection (prev ∈ {0,4} → new ∈ {2,None}) fires correctly on the
    # next tick if the mower has actually gone idle.
    assert coord._prev_task_state == 0


def test_persist_in_progress_writes_when_dirty():
    """_persist_in_progress calls write_in_progress when active and dirty."""
    import asyncio

    from custom_components.dreame_a2_mower.live_map.state import TrackPoint

    track = [
        TrackPoint(t=1_714_329_601, x_m=1.0, y_m=2.0, area_m2=0.0,
                   heading_deg=None, task_state=0, role="mowing"),
        TrackPoint(t=1_714_329_602, x_m=3.0, y_m=4.0, area_m2=0.5,
                   heading_deg=None, task_state=0, role="mowing"),
    ]
    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=1_714_329_600,
        live_map_track=track,
        live_map_dirty=True,
        area_mowed_m2=25.0,
    )

    asyncio.run(coord._persist_in_progress())

    coord.session_archive.write_in_progress.assert_called_once()
    written_payload = coord.session_archive.write_in_progress.call_args[0][0]
    assert written_payload["session_start_ts"] == 1_714_329_600
    assert written_payload["area_mowed_m2"] == 25.0
    # track serialised by dump_to_payload() as 7-element rows
    # [t, x, y, area, heading, task_state, role].
    assert written_payload["track"] == [
        [1_714_329_601, 1.0, 2.0, 0.0, None, 0, "mowing"],
        [1_714_329_602, 3.0, 4.0, 0.5, None, 0, "mowing"],
    ]
    # Dirty flag cleared after successful write.
    assert coord._live_map_dirty is False


def test_persist_in_progress_skips_when_not_dirty():
    """_persist_in_progress does NOT write when dirty flag is False."""
    import asyncio

    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=1_714_329_600,
        live_map_dirty=False,
    )

    asyncio.run(coord._persist_in_progress())

    coord.session_archive.write_in_progress.assert_not_called()
    # Dirty flag stays False.
    assert coord._live_map_dirty is False


def test_persist_in_progress_skips_when_session_not_active():
    """_persist_in_progress is a no-op when live_map.is_active() is False."""
    import asyncio

    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=None,  # not active
        live_map_dirty=True,
    )

    asyncio.run(coord._persist_in_progress())

    coord.session_archive.write_in_progress.assert_not_called()


def test_persist_in_progress_blocked_by_finalize_lock_does_not_resurrect_file():
    """T3-12 (TOCTOU): a persist tick racing a finalize's archive-write
    critical section must not resurrect in_progress.json after the finalize
    has archived + ended the session. _persist_in_progress now acquires
    _finalize_lock — the SAME lock _finalize_with_latch holds — so it either
    runs to completion before the finalize's critical section starts, or
    blocks until that section (which calls live_map.end_session()) releases
    the lock, at which point the re-checked is_active() guard correctly
    no-ops instead of writing a phantom "still running" file."""
    import asyncio

    from custom_components.dreame_a2_mower.live_map.state import TrackPoint

    track = [
        TrackPoint(t=1_714_329_601, x_m=1.0, y_m=2.0, area_m2=0.0,
                   heading_deg=None, task_state=0, role="mowing"),
    ]
    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=1_714_329_600,
        live_map_track=track,
        live_map_dirty=True,
    )

    async def _run():
        # Simulate finalize's critical section (_finalize_with_latch's body,
        # e.g. _post_archive_reset): acquire the lock, do some archive I/O,
        # THEN end_session() — all before releasing.
        async def _fake_finalize_critical_section():
            async with coord._finalize_lock:
                await asyncio.sleep(0.02)
                coord.live_map.end_session()

        finalize_task = asyncio.create_task(_fake_finalize_critical_section())
        await asyncio.sleep(0)  # let the fake finalize grab the lock first
        await coord._persist_in_progress()
        await finalize_task

    asyncio.run(_run())

    # Persist blocked on the lock; by the time it acquired it the session
    # was already ended, so it must NOT have resurrected the file.
    coord.session_archive.write_in_progress.assert_not_called()


def test_persist_in_progress_does_not_clear_dirty_on_exception():
    """When write_in_progress raises, dirty flag remains True for next retry."""
    import asyncio

    coord = _make_coordinator_for_persist_tests(
        live_map_started_unix=1_714_329_600,
        live_map_dirty=True,
        write_in_progress_side_effect=OSError("disk full"),
    )

    asyncio.run(coord._persist_in_progress())

    # Write was attempted.
    coord.session_archive.write_in_progress.assert_called_once()
    # But dirty flag was NOT cleared (so next tick retries).
    assert coord._live_map_dirty is True
