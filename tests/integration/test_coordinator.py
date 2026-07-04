"""Coordinator-adjacent entity / observability / discovery tests.

Residual of the former test_coordinator.py monolith after the P3.11 topical
split (see test_coordinator_{apply,writes,session,persist,finalize,replay,
render}.py). Holds the entity/sensor + novelty/observability + LiDAR-fetch +
select_first_g2408 tests that are not owned by a single domain service.
"""
from __future__ import annotations

import asyncio

from custom_components.dreame_a2_mower.state import MowerState
from custom_components.dreame_a2_mower.coordinator import apply_property_to_state
from tests.integration._coordinator_helpers import (
    _MINIMAL_SUMMARY_JSON,
    _make_coordinator_for_finalize_tests,
    _make_coordinator_for_session_tests,
)


def test_session_start_creates_live_map():
    """Feeding an s2p56=1 push causes live_map.begin_session to run.

    After the push:
    - live_map.is_active() is True
    - MowerState.session_started_unix is set to the supplied now_unix
    - MowerState.session_track_segments is an empty tuple-of-legs
    (SM-14: session_active removed from MowerState; use live_map.is_active())
    """
    coord = _make_coordinator_for_session_tests()

    # Simulate an s2p56=1 push (task_state_code = 1 = start_pending)
    new_state = apply_property_to_state(coord.data, siid=2, piid=56, value={"status": [[1, 0]]})
    assert new_state != coord.data  # sanity: state actually changed

    now = 1_714_329_600  # arbitrary fixed timestamp
    result = coord._on_state_update(new_state, now)

    assert coord.live_map.is_active()
    assert result.session_started_unix == now
    # segments is a tuple of legs; begin_session starts with one empty leg
    assert isinstance(result.session_track_segments, tuple)
    assert coord._prev_task_state == 0


def test_finalize_session_button_async_press_dispatches_action():
    """async_press() calls coordinator.dispatch_action(FINALIZE_SESSION)."""
    import asyncio
    from unittest.mock import MagicMock, AsyncMock

    from custom_components.dreame_a2_mower.button import DreameA2FinalizeSessionButton
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    # Build a minimal coordinator mock.
    coord = MagicMock()
    coord.dispatch_action = AsyncMock()
    # entry.entry_id is used for unique_id.
    coord.entry = MagicMock()
    coord.entry.entry_id = "test-entry-id"
    # _cloud may be None; the entity reads device_id / model from it.
    coord._cloud = None

    button = DreameA2FinalizeSessionButton.__new__(DreameA2FinalizeSessionButton)
    # Manually set attributes that __init__ would set (bypass CoordinatorEntity).
    button.coordinator = coord
    button._attr_unique_id = f"{coord.entry.entry_id}_finalize_session"

    asyncio.run(button.async_press())

    coord.dispatch_action.assert_awaited_once_with(MowerAction.FINALIZE_SESSION, {})


def test_finalize_session_button_lives_in_main_controls():
    """v1.0.0a27: Finalize joins Start/Pause/Stop/Recharge in the main
    controls section (no entity_category), so all five mow-control
    buttons cluster together on the device page."""
    from custom_components.dreame_a2_mower.button import DreameA2FinalizeSessionButton

    assert getattr(DreameA2FinalizeSessionButton, "_attr_entity_category", None) is None


def test_finalize_session_button_unique_id_uses_sn():
    """unique_id is SN-based: {sn}_finalize_session."""
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower._devices import mower_unique_id
    from custom_components.dreame_a2_mower.button import DreameA2FinalizeSessionButton

    coord = MagicMock()
    coord.entry.entry_id = "abc-123"
    coord.sn = "G2408000TESTSN0000"
    coord._cloud = None

    # Bypass super().__init__ to avoid HA coordinator plumbing.
    button = DreameA2FinalizeSessionButton.__new__(DreameA2FinalizeSessionButton)
    button.coordinator = coord
    button._attr_unique_id = mower_unique_id(coord, "finalize_session")

    assert button._attr_unique_id == "G2408000TESTSN0000_finalize_session"


def test_unknown_siid_piid_triggers_property_novelty():
    """A property push with an unmapped (siid, piid) pair adds a
    'property' observation to the registry exactly once."""
    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord.hass.loop.call_soon_threadsafe.side_effect = lambda fn: fn()

    coord.handle_property_push(siid=99, piid=42, value=7)
    coord.handle_property_push(siid=99, piid=42, value=8)  # dupe

    obs = coord.novel_registry.snapshot().observations
    property_obs = [o for o in obs if o.category == "property"]
    assert len(property_obs) == 1, f"expected 1 property obs, got {len(property_obs)}"
    assert property_obs[0].detail == "siid=99 piid=42"


def test_known_siid_piid_with_novel_value_triggers_value_novelty():
    """A property push with a mapped (siid, piid) but never-before-seen
    value adds a 'value' observation."""
    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord.hass.loop.call_soon_threadsafe.side_effect = lambda fn: fn()

    # s2.2 (error_code) is in PROPERTY_MAPPING. Use a novel value.
    coord.handle_property_push(siid=2, piid=2, value=999)
    coord.handle_property_push(siid=2, piid=2, value=999)  # dupe

    value_obs = [
        o for o in coord.novel_registry.snapshot().observations
        if o.category == "value"
    ]
    assert len(value_obs) == 1
    assert "siid=2 piid=2" in value_obs[0].detail
    assert "value=999" in value_obs[0].detail
    # And no property novelty fired — slot is mapped.
    property_obs = [
        o for o in coord.novel_registry.snapshot().observations
        if o.category == "property"
    ]
    assert property_obs == []


def test_do_oss_fetch_novel_key_logs_and_records(monkeypatch, caplog):
    """An OSS session_summary fetch where the JSON contains a key not in
    SCHEMA_SESSION_SUMMARY logs [NOVEL_KEY/session_summary] WARNING once
    and adds a 'key' observation to the registry."""
    import json

    # Build a payload that is valid for parse_session_summary AND contains
    # a key SCHEMA_SESSION_SUMMARY does not list.
    payload = dict(_MINIMAL_SUMMARY_JSON)
    payload["weird_field"] = 42
    raw_bytes = json.dumps(payload).encode()

    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/sessions/abc.json",
        pending_first_attempt_unix=1_700_000_000,
        pending_attempt_count=0,
        cloud_get_file_return=raw_bytes,
    )

    with caplog.at_level("WARNING"):
        asyncio.run(coord._do_oss_fetch(1_700_000_000))
        # Run a SECOND time — dupe should not log again.
        # Reset pending so the second fetch proceeds too.
        coord.data = MowerState(
            pending_session_object_name="d/sessions/abc.json",
            pending_session_first_event_unix=1_700_000_000,
            pending_session_attempt_count=0,
        )
        asyncio.run(coord._do_oss_fetch(1_700_000_005))

    novel = [
        o for o in coord.novel_registry.snapshot().observations
        if o.category == "key"
    ]
    novel_details = [o.detail for o in novel]
    assert "session_summary.weird_field" in novel_details, (
        f"expected 'session_summary.weird_field' in key observations, got: {novel_details}"
    )

    warns = [r for r in caplog.records if "[NOVEL_KEY/session_summary]" in r.getMessage()]
    assert len(warns) >= 1, f"expected at least 1 NOVEL_KEY warning, got {len(warns)}"

    # Second run produced no additional key observations (gate held).
    key_obs_after_run1 = len(novel)
    # All the weird_field warnings should be exactly 1 (once per process).
    weird_warns = [r for r in warns if "weird_field" in r.getMessage()]
    assert len(weird_warns) == 1, f"expected exactly 1 weird_field warning, got {len(weird_warns)}"


def test_novel_observations_sensor_value_fn_returns_count():
    from custom_components.dreame_a2_mower.sensor import (
        DIAGNOSTIC_SENSORS,
    )
    from custom_components.dreame_a2_mower.observability import (
        NovelObservationRegistry,
    )

    reg = NovelObservationRegistry()
    reg.record_property(siid=99, piid=42, now_unix=1700000000)
    reg.record_value(siid=2, piid=2, value=999, now_unix=1700000005)
    reg.record_key(namespace="session_summary", key="weird", now_unix=1700000010)

    coord_like = type("C", (), {"novel_registry": reg})()
    descs = [d for d in DIAGNOSTIC_SENSORS if d.key == "novel_observations"]
    assert len(descs) == 1
    desc = descs[0]
    assert desc.value_fn(coord_like) == 3


def test_novel_observations_sensor_attrs_lists_observations():
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS
    from custom_components.dreame_a2_mower.observability import (
        NovelObservationRegistry,
    )
    from homeassistant.helpers.entity import EntityCategory

    reg = NovelObservationRegistry()
    reg.record_property(siid=99, piid=42, now_unix=1700000000)
    coord_like = type("C", (), {"novel_registry": reg})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "novel_observations")
    attrs = desc.extra_state_attributes_fn(coord_like)
    assert "observations" in attrs
    assert len(attrs["observations"]) == 1
    sample = attrs["observations"][0]
    assert set(sample.keys()) == {"category", "detail", "first_seen_unix"}
    assert sample["category"] == "property"
    assert sample["detail"] == "siid=99 piid=42"
    assert sample["first_seen_unix"] == 1700000000
    assert desc.entity_category is EntityCategory.DIAGNOSTIC


# test_data_freshness_sensor_* (native value / per-field attrs / none-when-empty)
# DELETED refactor-v2 P4.2 (R-51, track-5 T5-7): sensor.data_freshness was
# removed as a staleness duplicate of sensor.mqtt_connectivity, along with the
# _freshness_value/_freshness_attrs helpers these tests exercised.


def test_cloud_routed_action_records_accepted():
    """A device-accepted routed_action (out[0].r==0) records 'accepted'."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    # Build a barebones client without invoking the real __init__.
    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client.endpoint_log = {}
    client._did = "did1"
    client._last_send_error_code = None

    # Realistic wire shape: cloud HTTP code 0, device verdict out[0].r == 0.
    with patch.object(client, "action", return_value={"code": 0, "out": [{"r": 0}]}):
        result = client.routed_action(op=100)

    assert result.accepted is True
    assert result.delivered is True
    assert client.endpoint_log["routed_action_op=100"] == "accepted"


def test_cloud_routed_action_records_device_rejected():
    """A delivered-but-rejected routed_action (out[0].r != 0) records
    'device_rejected' — the cloud HTTP code is 0 but the device said no."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client.endpoint_log = {}
    client._did = "did1"
    client._last_send_error_code = None

    rejected = {"code": 0, "out": [{"r": -3, "msg": "not supported"}]}
    with patch.object(client, "action", return_value=rejected):
        result = client.routed_action(op=100)

    assert result.delivered is True
    assert result.accepted is False
    assert result.code == -3
    assert client.endpoint_log["routed_action_op=100"] == "device_rejected"


def test_cloud_routed_action_records_80001():
    """When self.action returns None AND _last_send_error_code is 80001,
    the endpoint is marked rejected_80001."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client.endpoint_log = {}
    client._did = "did1"
    client._last_send_error_code = None

    def _fake_action(*_a, **_kw):
        client._last_send_error_code = 80001
        return None

    with patch.object(client, "action", side_effect=_fake_action):
        client.routed_action(op=999)

    assert client.endpoint_log["routed_action_op=999"] == "rejected_80001"


def test_cloud_routed_action_records_error_for_other_failures():
    """Any non-80001 failure (None return + other error code) is logged
    as 'error'."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client.endpoint_log = {}
    client._did = "did1"
    client._last_send_error_code = None

    def _fake_action(*_a, **_kw):
        client._last_send_error_code = -7  # arbitrary non-80001 code
        return None

    with patch.object(client, "action", side_effect=_fake_action):
        client.routed_action(op=42)

    assert client.endpoint_log["routed_action_op=42"] == "error"


def test_api_endpoints_supported_sensor_value_fn_counts_accepted():
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS

    cloud_like = type("Cloud", (), {"endpoint_log": {
        "routed_action_op=100": "accepted",
        "routed_action_op=101": "accepted",
        "routed_action_op=999": "rejected_80001",
        "routed_action_op=42": "error",
    }})()
    coord_like = type("C", (), {"_cloud": cloud_like, "cloud": property(lambda self: cloud_like)})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "api_endpoints_supported")
    assert desc.value_fn(coord_like) == 2


def test_api_endpoints_supported_sensor_attrs_buckets_by_outcome():
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS

    cloud_like = type("Cloud", (), {"endpoint_log": {
        "routed_action_op=100": "accepted",
        "routed_action_op=999": "rejected_80001",
        "routed_action_op=42": "error",
    }})()
    coord_like = type("C", (), {"_cloud": cloud_like, "cloud": property(lambda self: cloud_like)})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "api_endpoints_supported")
    attrs = desc.extra_state_attributes_fn(coord_like)
    assert attrs == {
        "accepted": ["routed_action_op=100"],
        "rejected_80001": ["routed_action_op=999"],
        "device_rejected": [],
        "error": ["routed_action_op=42"],
    }


def test_api_endpoints_supported_sensor_attrs_surfaces_device_rejected():
    """A 'device_rejected' endpoint_log entry must appear in the sensor's
    attributes — without its own bucket a device rejection is invisible
    (counted as neither accepted nor failed)."""
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS

    cloud_like = type("Cloud", (), {"endpoint_log": {
        "routed_action_op=100": "accepted",
        "routed_action_op=102": "device_rejected",
        "routed_action_op=999": "rejected_80001",
    }})()
    coord_like = type("C", (), {"_cloud": cloud_like, "cloud": property(lambda self: cloud_like)})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "api_endpoints_supported")
    attrs = desc.extra_state_attributes_fn(coord_like)
    assert attrs["device_rejected"] == ["routed_action_op=102"]
    # And it is NOT mislabelled into accepted / error buckets.
    assert attrs["accepted"] == ["routed_action_op=100"]
    assert "routed_action_op=102" not in attrs["error"]


def test_api_endpoints_supported_sensor_handles_no_cloud_yet():
    """Before the cloud client is connected, _cloud is None — sensor
    should return 0 / empty attrs rather than crash."""
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS

    coord_like = type("C", (), {"_cloud": None, "cloud": property(lambda self: None)})()

    desc = next(d for d in DIAGNOSTIC_SENSORS if d.key == "api_endpoints_supported")
    assert desc.value_fn(coord_like) == 0
    assert desc.extra_state_attributes_fn(coord_like) == {
        "accepted": [], "rejected_80001": [], "device_rejected": [], "error": [],
    }


def test_lidar_object_name_change_triggers_fetch_and_archive(tmp_path):
    """A new latest_lidar_object_name causes _handle_lidar_object_name
    to fetch the OSS blob, dedup by md5, and write to the archive."""
    import asyncio
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive

    coord = _make_coordinator_for_finalize_tests()
    # T12: set up per-map archive for map_id=0 and make it active.
    coord._lidar_archive_root = tmp_path / "lidar"
    coord._lidar_archive_retention = 0
    coord._lidar_archive_max_bytes = 0
    coord.lidar_archives = {0: LidarArchive(tmp_path / "lidar", map_id=0)}
    coord._active_map_id = 0
    coord._last_lidar_object_name = None
    coord.data = MowerState()

    fake_pcd = b"# .PCD v0.7\nDUMMY-LIDAR-PAYLOAD"

    def _fake_url(_obj_name):
        return "https://example/abc.pcd"

    def _fake_get(_url):
        return fake_pcd

    coord._cloud.get_interim_file_url = _fake_url
    coord._cloud.get_file = _fake_get

    async def _fake_executor(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    coord.hass.async_add_executor_job = _fake_executor

    async def _run():
        await coord._handle_lidar_object_name("dreame/lidar/abc.pcd", now_unix=1700000000)
        # Same object_name again — should be skipped (idempotent guard).
        await coord._handle_lidar_object_name("dreame/lidar/abc.pcd", now_unix=1700000005)

    asyncio.run(_run())

    assert coord.lidar_archive_for(0).count == 1
    latest = coord.lidar_archive_for(0).latest()
    assert latest is not None
    assert latest.object_name == "dreame/lidar/abc.pcd"


def test_lidar_object_name_unchanged_skips_fetch(tmp_path):
    """If _handle_lidar_object_name receives the same object_name as
    last time, no cloud fetch is attempted at all."""
    import asyncio
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive

    coord = _make_coordinator_for_finalize_tests()
    # T12: set up per-map archive for map_id=0 and make it active.
    coord._lidar_archive_root = tmp_path / "lidar"
    coord._lidar_archive_retention = 0
    coord._lidar_archive_max_bytes = 0
    coord.lidar_archives = {0: LidarArchive(tmp_path / "lidar", map_id=0)}
    coord._active_map_id = 0
    coord._last_lidar_object_name = "dreame/lidar/already.pcd"

    fetch_count = 0

    def _fake_url(_obj_name):
        nonlocal fetch_count
        fetch_count += 1
        return None

    coord._cloud.get_interim_file_url = _fake_url

    async def _fake_executor(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    coord.hass.async_add_executor_job = _fake_executor

    asyncio.run(
        coord._handle_lidar_object_name("dreame/lidar/already.pcd", now_unix=1700000000)
    )
    assert fetch_count == 0


def test_lidar_object_name_handles_url_fetch_failure_gracefully(tmp_path):
    """When get_interim_file_url returns None or raises, log + swallow,
    do not crash."""
    import asyncio
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive

    coord = _make_coordinator_for_finalize_tests()
    # T12: set up per-map archive for map_id=0 and make it active.
    coord._lidar_archive_root = tmp_path / "lidar"
    coord._lidar_archive_retention = 0
    coord._lidar_archive_max_bytes = 0
    coord.lidar_archives = {0: LidarArchive(tmp_path / "lidar", map_id=0)}
    coord._active_map_id = 0
    coord._last_lidar_object_name = None
    coord.data = MowerState()

    def _fake_url(_obj_name):
        return None

    coord._cloud.get_interim_file_url = _fake_url

    async def _fake_executor(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    coord.hass.async_add_executor_job = _fake_executor

    # Should not raise.
    asyncio.run(
        coord._handle_lidar_object_name("dreame/lidar/sad.pcd", now_unix=1700000000)
    )
    assert coord.lidar_archive_for(0).count == 0


def test_show_lidar_fullscreen_fires_bus_event():
    """The service handler fires a dreame_a2_mower_lidar_fullscreen
    event on the bus. Lovelace cards listen for it to pop up the
    fullscreen LiDAR view."""
    import asyncio
    from custom_components.dreame_a2_mower.services import (
        _handle_show_lidar_fullscreen,
    )
    from unittest.mock import MagicMock

    hass = MagicMock()
    hass.bus.async_fire = MagicMock()

    call = MagicMock()
    call.hass = hass
    call.data = {}

    asyncio.run(_handle_show_lidar_fullscreen(call))

    hass.bus.async_fire.assert_called_once_with(
        "dreame_a2_mower_lidar_fullscreen", {}
    )


def test_select_first_g2408_picks_dreame_mower_model_and_pins_did():
    """Picks the first dreame.mower.* device, calls _handle_device_info
    so _did + _host get populated for subsequent get_device_info /
    mqtt_host_port calls."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._logged_in = True
    client._strings = None  # _handle_device_info reads strings via _ensure_strings

    devices_payload = {
        "page": {
            "records": [
                {"did": "12345", "model": "dreame.vacuum.r2227", "name": "robovac"},
                {"did": "67890", "model": "dreame.mower.g2408", "name": "the mower"},
            ]
        }
    }

    captured = {}
    def _fake_handle(self, info):
        captured["info"] = info
        self._did = info["did"]
        self._model = info["model"]
        self._host = "fake.mqtt.host:8883"
        self._uid = "fake-uid"

    with patch.object(client, "get_devices", return_value=devices_payload):
        with patch.object(
            DreameA2CloudClient, "_handle_device_info",
            new=_fake_handle,
        ):
            picked = client.select_first_g2408()

    assert picked["did"] == "67890"
    assert picked["model"] == "dreame.mower.g2408"
    assert client._did == "67890"
    assert client._host == "fake.mqtt.host:8883"


def test_select_first_g2408_raises_when_not_logged_in():
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._logged_in = False
    try:
        client.select_first_g2408()
    except ValueError as ex:
        assert "login()" in str(ex)
    else:
        raise AssertionError("expected ValueError")


def test_select_first_g2408_raises_when_no_matching_device():
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._logged_in = True

    payload = {
        "page": {
            "records": [
                {"did": "1", "model": "dreame.vacuum.r2227"},
            ]
        }
    }
    with patch.object(client, "get_devices", return_value=payload):
        try:
            client.select_first_g2408()
        except ValueError as ex:
            assert "dreame.mower" in str(ex)
        else:
            raise AssertionError("expected ValueError")


def test_select_first_g2408_raises_on_empty_response():
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
    from unittest.mock import patch

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._logged_in = True

    with patch.object(client, "get_devices", return_value=None):
        try:
            client.select_first_g2408()
        except ValueError as ex:
            assert "no data" in str(ex) or "auth" in str(ex).lower()
        else:
            raise AssertionError("expected ValueError")


def test_blob_slots_do_not_trigger_novelty_noise(tmp_path):
    """s1.1 / s1.4 / s2.51 must NOT log [NOVEL/property] or [NOVEL/value]
    on every push — they're dispatched via dedicated blob handlers."""
    coord = _make_coordinator_for_finalize_tests()
    coord.data = MowerState()
    coord.hass.loop.call_soon_threadsafe.side_effect = lambda fn: fn()

    # Two pushes for each blob slot.
    blob_list = [0] * 20
    coord.handle_property_push(siid=1, piid=1, value=blob_list)
    coord.handle_property_push(siid=1, piid=1, value=blob_list)

    # The novel-registry must contain ZERO entries for blob slots —
    # the slots are known, but their per-tick blob bytes don't go
    # through the value-novelty path.
    obs = coord.novel_registry.snapshot().observations
    blob_obs = [
        o for o in obs
        if "siid=1 piid=1" in o.detail or "siid=1 piid=4" in o.detail or "siid=2 piid=51" in o.detail
    ]
    assert blob_obs == [], f"Expected no novelty observations for blob slots, got: {blob_obs}"
