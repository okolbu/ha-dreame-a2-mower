from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_begin_session_resets_type_tracking_fields():
    lm = LiveMapState()
    lm.target_ids = [9]
    lm.last_task_op = 103
    lm.area_ever_positive = True
    lm.saw_patrol_start = True
    lm.begin_session(1000)
    assert lm.target_ids == []
    assert lm.last_task_op is None
    assert lm.area_ever_positive is False
    assert lm.saw_patrol_start is False


def test_saw_patrol_start_dump_restore_roundtrip():
    lm = LiveMapState()
    lm.begin_session(1000)
    lm.saw_patrol_start = True
    payload = lm.dump_to_payload()
    assert payload["saw_patrol_start"] is True
    lm2 = LiveMapState()
    lm2.hydrate_from_payload(payload)
    assert lm2.saw_patrol_start is True


def test_saw_patrol_start_recovered_from_error_samples_on_restore():
    # Old payload lacking the key but with a 51 in error_samples still recovers.
    lm = LiveMapState()
    lm.hydrate_from_payload({"session_start_ts": 1000, "error_samples": [[1000, 51]]})
    assert lm.saw_patrol_start is True
