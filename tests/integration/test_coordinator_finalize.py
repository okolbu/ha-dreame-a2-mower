"""Coordinator finalize/OSS-fetch/dispatch/periodic-retry tests (domain/session/finalize).

Split out of the test_coordinator.py monolith (P3.11); tests moved verbatim.
"""
from __future__ import annotations


from custom_components.dreame_a2_mower.state import MowerState
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from tests.integration._coordinator_helpers import (
    _MINIMAL_SUMMARY_JSON,
    _make_coordinator_for_finalize_tests,
)


def test_handle_event_occured_sets_pending_fields():
    """_handle_event_occured with piid=9 sets pending_session_object_name + first_event_unix."""
    coord = _make_coordinator_for_finalize_tests()
    arguments = [{"piid": 9, "value": "d/xxx/sessions/abc123.json"}]

    import asyncio
    asyncio.run(coord._handle_event_occured(arguments))

    assert coord.data.pending_session_object_name == "d/xxx/sessions/abc123.json"
    assert coord.data.pending_session_first_event_unix is not None
    assert coord.data.pending_session_last_attempt_unix is None
    assert coord.data.pending_session_attempt_count == 0


def test_handle_event_occured_no_piid9_logs_warning():
    """_handle_event_occured with no piid=9 argument does not crash and leaves state unchanged."""
    coord = _make_coordinator_for_finalize_tests()
    arguments = [{"piid": 1, "value": "something"}]

    import asyncio
    asyncio.run(coord._handle_event_occured(arguments))

    # State unchanged — no pending_session_object_name set.
    assert coord.data.pending_session_object_name is None


def test_handle_event_occured_empty_arguments_does_not_crash():
    """_handle_event_occured with empty arguments list gracefully does nothing."""
    coord = _make_coordinator_for_finalize_tests()

    import asyncio
    asyncio.run(coord._handle_event_occured([]))

    assert coord.data.pending_session_object_name is None


def test_handle_event_occured_overwrites_existing_pending():
    """A second event_occured replaces the first pending object name."""
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="old/key.json",
    )
    arguments = [{"piid": 9, "value": "new/key.json"}]

    import asyncio
    asyncio.run(coord._handle_event_occured(arguments))

    assert coord.data.pending_session_object_name == "new/key.json"
    assert coord.data.pending_session_attempt_count == 0


def test_on_mqtt_message_event_occured_schedules_handle():
    """event_occured method with siid=4 eiid=1 calls call_soon_threadsafe."""
    coord = _make_coordinator_for_finalize_tests()

    # Track what call_soon_threadsafe is called with.
    scheduled = []
    coord.hass.loop.call_soon_threadsafe.side_effect = lambda fn: scheduled.append(fn)

    payload = {
        "method": "event_occured",
        "params": {
            "siid": 4,
            "eiid": 1,
            "arguments": [{"piid": 9, "value": "d/sessions/abc.json"}],
        },
    }
    coord._on_mqtt_message("topic", payload)

    assert len(scheduled) == 1, "call_soon_threadsafe should be called once"


def test_on_mqtt_message_event_occured_wrong_siid_ignored():
    """event_occured with siid != 4 is ignored (no call_soon_threadsafe)."""
    coord = _make_coordinator_for_finalize_tests()
    coord.hass.loop.call_soon_threadsafe.side_effect = None  # reset

    payload = {
        "method": "event_occured",
        "params": {"siid": 99, "eiid": 1, "arguments": []},
    }
    coord._on_mqtt_message("topic", payload)
    coord.hass.loop.call_soon_threadsafe.assert_not_called()


def test_on_mqtt_message_properties_changed_still_works():
    """properties_changed still dispatches to handle_property_push after refactor."""
    coord = _make_coordinator_for_finalize_tests()
    # Give coord a real data so handle_property_push can use it.
    coord.data = MowerState()
    coord.live_map.started_unix = None

    called = []
    original_hpp = DreameA2MowerCoordinator.handle_property_push

    def _spy(self, siid, piid, value):
        called.append((siid, piid, value))

    DreameA2MowerCoordinator.handle_property_push = _spy
    try:
        payload = {
            "method": "properties_changed",
            "params": [{"siid": 3, "piid": 1, "value": 85}],
        }
        coord._on_mqtt_message("topic", payload)
    finally:
        DreameA2MowerCoordinator.handle_property_push = original_hpp

    assert called == [(3, 1, 85)]


def test_do_oss_fetch_success_clears_pending_and_updates_state():
    """Successful OSS fetch archives session and clears pending_session_* fields."""
    import asyncio
    import json

    raw_bytes = json.dumps(_MINIMAL_SUMMARY_JSON).encode()

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
        pending_first_attempt_unix=1_700_000_000,
        pending_attempt_count=0,
        cloud_get_file_return=raw_bytes,
    )
    coord.session_archive.count = 1  # simulate first archive

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    # Pending fields cleared.
    assert coord.data.pending_session_object_name is None
    assert coord.data.pending_session_first_event_unix is None
    assert coord.data.pending_session_last_attempt_unix is None
    assert coord.data.pending_session_attempt_count is None

    # latest_session_* fields populated. (latest_session_md5 was pruned
    # in F10 — see docs/research/state-machines/orphan-fields.md.)
    assert coord.data.latest_session_area_m2 == 120.5
    assert coord.data.latest_session_duration_min == 60

    # live_map reset.
    assert not coord.live_map.is_active()


def test_do_oss_fetch_no_cloud_returns_early():
    """_do_oss_fetch with no cloud client does nothing (early boot guard)."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
    )
    del coord._cloud  # simulate early boot

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    # State unchanged — no cloud client.
    assert coord.data.pending_session_object_name == "d/sessions/test.json"


def test_do_oss_fetch_no_object_name_returns_early():
    """_do_oss_fetch with no pending object name does nothing."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name=None,
    )

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    coord._cloud.get_interim_file_url.assert_not_called()


def test_do_oss_fetch_signed_url_none_does_not_archive():
    """If get_interim_file_url returns None, fetch is aborted (no archive)."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
        cloud_get_interim_file_url_return=None,
    )

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    # Attempt count incremented (fetch was attempted).
    assert coord.data.pending_session_attempt_count == 1
    # Archive not called.
    coord.session_archive.archive.assert_not_called()
    # Pending object name still set (not cleared on failure).
    assert coord.data.pending_session_object_name == "d/sessions/test.json"


def test_do_oss_fetch_raw_bytes_none_does_not_archive():
    """If get_file returns None, fetch aborted (no archive)."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
        cloud_get_file_return=None,
    )

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    coord.session_archive.archive.assert_not_called()
    assert coord.data.pending_session_object_name == "d/sessions/test.json"


def test_do_oss_fetch_invalid_json_does_not_archive():
    """If raw bytes are not valid JSON, fetch aborted (no archive)."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
        cloud_get_file_return=b"this is not json {{{",
    )

    asyncio.run(coord._do_oss_fetch(now_unix=1_700_003_700))

    coord.session_archive.archive.assert_not_called()


def test_run_finalize_incomplete_clears_pending_and_ends_session():
    """_run_finalize_incomplete archives an incomplete entry, clears pending state."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/old.json",
        pending_first_attempt_unix=1_700_000_000,
        pending_attempt_count=11,
        session_active=True,
        session_started_unix=1_700_000_000,
        area_mowed_m2=50.0,
    )
    coord.live_map.begin_session(1_700_000_000)
    coord.session_archive.count = 1

    asyncio.run(coord._run_finalize_incomplete(now_unix=1_700_003_700))

    # Pending fields cleared.
    assert coord.data.pending_session_object_name is None
    assert coord.data.pending_session_first_event_unix is None
    assert coord.data.pending_session_last_attempt_unix is None
    assert coord.data.pending_session_attempt_count is None

    # Session ended.
    assert not coord.live_map.is_active()

    # Archive was called.
    coord.session_archive.archive.assert_called_once()


def test_run_finalize_incomplete_no_live_session_still_clears_pending():
    """Even with no live_map session, _run_finalize_incomplete clears pending."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/old.json",
        pending_attempt_count=12,
    )
    # live_map not started — started_unix is None.
    coord.session_archive.count = 0

    asyncio.run(coord._run_finalize_incomplete(now_unix=1_700_003_700))

    assert coord.data.pending_session_object_name is None


def test_dispatch_action_finalize_session_calls_run_finalize_incomplete():
    """dispatch_action(FINALIZE_SESSION) runs the finalize-incomplete path."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/stuck.json",
        pending_first_attempt_unix=1_700_000_000,
        pending_attempt_count=5,
        session_active=True,
        session_started_unix=1_700_000_000,
        area_mowed_m2=30.0,
    )
    coord.live_map.begin_session(1_700_000_000)
    coord.session_archive.count = 2

    from custom_components.dreame_a2_mower.mower.actions import MowerAction
    asyncio.run(coord.dispatch_action(MowerAction.FINALIZE_SESSION, {}))

    # Pending fields cleared.
    assert coord.data.pending_session_object_name is None
    assert coord.data.pending_session_first_event_unix is None
    assert coord.data.pending_session_last_attempt_unix is None
    assert coord.data.pending_session_attempt_count is None

    # Session ended.
    assert not coord.live_map.is_active()

    # Archive was called with the incomplete sentinel.
    coord.session_archive.archive.assert_called_once()


def test_dispatch_action_finalize_session_no_active_session_noop_cleanly():
    """dispatch_action(FINALIZE_SESSION) with no active session clears state cleanly."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests()
    # No live session, no pending — just verify no crash.
    coord.session_archive.count = 0

    from custom_components.dreame_a2_mower.mower.actions import MowerAction
    asyncio.run(coord.dispatch_action(MowerAction.FINALIZE_SESSION, {}))

    # Pending still None — nothing to clear.
    assert coord.data.pending_session_object_name is None
    # Archive still called (archives an empty/zero session).
    coord.session_archive.archive.assert_called_once()


def test_dispatch_action_local_only_returns_accepted_writeresult():
    """FINALIZE_SESSION (local-only) returns an accepted WriteResult."""
    import asyncio
    from custom_components.dreame_a2_mower.cloud_client import WriteResult
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _make_coordinator_for_finalize_tests()
    coord.session_archive.count = 0
    result = asyncio.run(coord.dispatch_action(MowerAction.FINALIZE_SESSION, {}))
    assert isinstance(result, WriteResult)
    assert result.accepted is True


def test_dispatch_action_unknown_returns_not_delivered():
    """An action not in ACTION_TABLE → not-delivered, not-accepted WriteResult."""
    import asyncio
    from custom_components.dreame_a2_mower.cloud_client import WriteResult

    coord = _make_coordinator_for_finalize_tests()

    class _Bogus:
        name = "BOGUS"

    result = asyncio.run(coord.dispatch_action(_Bogus()))
    assert isinstance(result, WriteResult)
    assert result.delivered is False
    assert result.accepted is False


def test_dispatch_action_propagates_routed_writeresult():
    """A cloud-path action propagates routed_action's WriteResult verbatim —
    a device rejection (accepted=False) flows through to the caller."""
    import asyncio
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.cloud_client import WriteResult
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord._active_map_id = 0
    rejected = WriteResult(delivered=True, accepted=False, code=-3, msg="no")
    coord._cloud.routed_action = MagicMock(return_value=rejected)

    result = asyncio.run(coord.dispatch_action(MowerAction.START_MOWING, {}))
    assert result is rejected
    assert result.accepted is False


def test_dispatch_action_cloud_not_ready_returns_not_delivered():
    """No cloud client → not-delivered WriteResult, non-raising."""
    import asyncio
    from custom_components.dreame_a2_mower.cloud_client import WriteResult
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord._cloud = None
    result = asyncio.run(coord.dispatch_action(MowerAction.START_MOWING, {}))
    assert isinstance(result, WriteResult)
    assert result.delivered is False
    assert result.accepted is False
    assert result.code is None


def test_dispatch_action_cfg_toggle_accepted_returns_accepted_writeresult():
    """cfg_toggle_field path (LOCK_BOT_TOGGLE → CLS): write_setting's accepted
    WriteResult is propagated verbatim (P2 Task 5 — no more synthetic wrap)."""
    import asyncio
    from unittest.mock import AsyncMock
    from custom_components.dreame_a2_mower.cloud_client import WriteResult
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState(child_lock_enabled=False)
    # Stub write_setting so we exercise dispatch_action's propagation, not the
    # CFG transport (covered elsewhere).
    accepted = WriteResult(delivered=True, accepted=True, code=0)
    coord.write_setting = AsyncMock(return_value=accepted)

    result = asyncio.run(coord.dispatch_action(MowerAction.LOCK_BOT_TOGGLE, {}))
    assert result is accepted  # verbatim propagation, not a re-wrap
    # CLS wire value is the toggled int (was False → 1).
    coord.write_setting.assert_awaited_once()
    args, kwargs = coord.write_setting.await_args
    assert args[0] == "CLS"
    assert args[1] == 1


def test_dispatch_action_cfg_toggle_rejected_propagates_device_code():
    """cfg_toggle_field path: a device-rejected write_setting WriteResult is
    propagated verbatim — the real out[0].r code (e.g. -3) now reaches the
    caller instead of the old synthetic code=None wrapper (P2 Task 5)."""
    import asyncio
    from unittest.mock import AsyncMock
    from custom_components.dreame_a2_mower.cloud_client import WriteResult
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState(child_lock_enabled=True)
    rejected = WriteResult(delivered=True, accepted=False, code=-3, msg="not supported")
    coord.write_setting = AsyncMock(return_value=rejected)

    result = asyncio.run(coord.dispatch_action(MowerAction.LOCK_BOT_TOGGLE, {}))
    assert result is rejected
    assert result.code == -3


def test_dispatch_action_direct_siid_aiid_delivered_when_action_returns():
    """An action entry with siid/aiid but no routed_o/local_only/cfg_toggle_field
    falls back to a direct action(siid, aiid) call; a non-None device result →
    delivered + accepted, code=None.

    ACTION_TABLE currently has no such entry — every cloud action carries a
    routed_o (the working path on g2408) — so this generic fallback branch in
    dispatch_action would otherwise be untested (it lost its only coverage,
    REQUEST_WIFI_MAP, when that dead action was deleted). We locally construct
    a fake ActionEntry and patch.dict it onto an existing MowerAction member
    for just this test — no new MowerAction member or permanent ACTION_TABLE
    row is added; FIND_BOT is reused purely as a dict key.
    """
    import asyncio
    from unittest.mock import MagicMock, patch
    from custom_components.dreame_a2_mower.cloud_client import WriteResult
    from custom_components.dreame_a2_mower.mower.actions import ACTION_TABLE, MowerAction

    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord._cloud.action = MagicMock(return_value={"code": 0})

    fake_entry = {"siid": 6, "aiid": 4}  # no routed_o / local_only / cfg_toggle_field
    with patch.dict(ACTION_TABLE, {MowerAction.FIND_BOT: fake_entry}):
        result = asyncio.run(coord.dispatch_action(MowerAction.FIND_BOT, {}))

    assert isinstance(result, WriteResult)
    assert result.delivered is True
    assert result.accepted is True
    assert result.code is None
    coord._cloud.action.assert_called_once_with(6, 4)


def test_dispatch_action_direct_siid_aiid_not_delivered_when_action_none():
    """Direct siid/aiid fallback path: action() returns None → not-delivered."""
    import asyncio
    from unittest.mock import MagicMock, patch
    from custom_components.dreame_a2_mower.cloud_client import WriteResult
    from custom_components.dreame_a2_mower.mower.actions import ACTION_TABLE, MowerAction

    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord._cloud.action = MagicMock(return_value=None)

    fake_entry = {"siid": 6, "aiid": 4}
    with patch.dict(ACTION_TABLE, {MowerAction.FIND_BOT: fake_entry}):
        result = asyncio.run(coord.dispatch_action(MowerAction.FIND_BOT, {}))

    assert isinstance(result, WriteResult)
    assert result.delivered is False
    assert result.accepted is False
    assert result.code is None


def test_dispatch_action_payload_error_returns_not_delivered():
    """A payload_fn that raises ValueError → not-delivered WriteResult,
    non-raising, code=None, and no cloud call is made."""
    import asyncio
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.cloud_client import WriteResult
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord._active_map_id = 0
    coord._cloud.routed_action = MagicMock()
    # START_ZONE_MOW's payload_fn requires a "zones" list; omitting it raises
    # ValueError inside dispatch_action's payload-build step.
    result = asyncio.run(coord.dispatch_action(MowerAction.START_ZONE_MOW, {}))
    assert isinstance(result, WriteResult)
    assert result.delivered is False
    assert result.accepted is False
    assert result.code is None
    assert "payload error" in result.msg
    coord._cloud.routed_action.assert_not_called()


def test_dispatch_action_cfg_toggle_missing_cfg_key_returns_not_delivered():
    """cfg_toggle_field set but cfg_key missing in the entry → not-delivered
    WriteResult, code=None, and write_setting is never called."""
    import asyncio
    from unittest.mock import AsyncMock, patch
    from custom_components.dreame_a2_mower.cloud_client import WriteResult
    from custom_components.dreame_a2_mower.mower.actions import (
        ACTION_TABLE,
        MowerAction,
    )

    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord.write_setting = AsyncMock(return_value=True)

    # Patch the entry to drop cfg_key while keeping cfg_toggle_field.
    broken_entry = {"cfg_toggle_field": "child_lock_enabled"}  # no cfg_key
    with patch.dict(ACTION_TABLE, {MowerAction.LOCK_BOT_TOGGLE: broken_entry}):
        result = asyncio.run(
            coord.dispatch_action(MowerAction.LOCK_BOT_TOGGLE, {})
        )
    assert isinstance(result, WriteResult)
    assert result.delivered is False
    assert result.accepted is False
    assert result.code is None
    coord.write_setting.assert_not_awaited()


def test_periodic_session_retry_noop_when_no_pending():
    """_periodic_session_retry does nothing when no pending object and session idle."""
    import asyncio

    coord = _make_coordinator_for_finalize_tests()
    # No pending, no task_state — decide() should return NOOP.

    asyncio.run(coord._periodic_session_retry())

    coord._cloud.get_interim_file_url.assert_not_called()
    coord.session_archive.archive.assert_not_called()


def test_periodic_session_retry_fires_oss_fetch_when_pending_ready():
    """When pending object name is set and retry window has elapsed, fetch fires."""
    import asyncio
    import json

    raw_bytes = json.dumps(_MINIMAL_SUMMARY_JSON).encode()

    # Set first_attempt_unix far in the past so decide() returns AWAIT_OSS_FETCH.
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/test.json",
        pending_first_attempt_unix=1_700_000_000,   # far past
        pending_attempt_count=0,
        cloud_get_file_return=raw_bytes,
    )
    coord.session_archive.count = 1

    asyncio.run(coord._periodic_session_retry())

    # Pending should be cleared after successful fetch.
    assert coord.data.pending_session_object_name is None


def test_periodic_session_retry_boot_stale_skips_finalize_incomplete():
    """Regression: 2026-05-15 rain-stop incident.

    After `_restore_in_progress` seeds `_prev_task_state=0` to support
    the "mower finished while HA was off" path, the first retry tick
    fires BEFORE any fresh task_state push arrives via MQTT — so
    MowerState.task_state_code is still default None. The naive gate
    matched (prev=0 in (0,4), new=None in (2,None)) → FINALIZE_INCOMPLETE,
    writing a phantom (incomplete) 0 m² session for a still-active mow.
    Boot-stale guard skips this case until a real task_state has been
    seen.
    """
    import asyncio

    coord = _make_coordinator_for_finalize_tests()
    # Simulate post-restart state: prev seeded to 0 by _restore_in_progress,
    # MowerState.task_state_code default None, no MQTT push observed yet.
    coord._prev_task_state = 0
    coord._real_task_state_observed = False
    coord.live_map.begin_session(1700000000)

    asyncio.run(coord._periodic_session_retry())

    # Phantom must NOT be archived.
    coord.session_archive.archive.assert_not_called()


def test_periodic_session_retry_finalizes_after_real_task_state_seen():
    """After a real MQTT task_state push has been observed, the boot-stale
    guard releases — the gate fires as normal if conditions match.
    """
    import asyncio

    coord = _make_coordinator_for_finalize_tests()
    # Seeded prev, but now we've also observed a real task_state.
    coord._prev_task_state = 0
    coord._real_task_state_observed = True
    coord.live_map.begin_session(1700000000)

    asyncio.run(coord._periodic_session_retry())

    # decide() returns FINALIZE_INCOMPLETE (session_just_ended branch),
    # which dispatches to _run_finalize_incomplete and writes the
    # (incomplete) archive.
    coord.session_archive.archive.assert_called_once()


def test_periodic_session_retry_finalize_incomplete_when_max_age_expired():
    """When max-age expired, _periodic_session_retry calls _run_finalize_incomplete."""
    import asyncio
    import time as _time
    from custom_components.dreame_a2_mower.live_map.finalize import MAX_AGE_SECONDS

    # first_attempt so old it's past MAX_AGE_SECONDS
    first_attempt = int(_time.time()) - MAX_AGE_SECONDS - 3600

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/expired.json",
        pending_first_attempt_unix=first_attempt,
        pending_attempt_count=0,
    )
    coord.live_map.begin_session(first_attempt)
    coord.session_archive.count = 1

    asyncio.run(coord._periodic_session_retry())

    # decide() returns FINALIZE_INCOMPLETE → _run_finalize_incomplete ran.
    assert coord.data.pending_session_object_name is None
    coord.session_archive.archive.assert_called_once()
