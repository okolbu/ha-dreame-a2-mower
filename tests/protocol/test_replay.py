"""Tests for the probe-log replay iterator."""

from __future__ import annotations

from pathlib import Path

import pytest

from protocol.replay import (
    ProbeLogEvent,
    iter_probe_log,
)


def test_iter_probe_log_yields_mqtt_messages_only(fixtures_dir: Path):
    events = list(iter_probe_log(fixtures_dir / "session_short.jsonl"))
    assert events, "expected at least one event from the trimmed fixture"
    assert all(isinstance(e, ProbeLogEvent) for e in events)
    assert all(e.method == "properties_changed" for e in events)


def test_iter_probe_log_parses_siid_piid_value(fixtures_dir: Path):
    events = list(iter_probe_log(fixtures_dir / "session_short.jsonl"))
    # First mqtt_message in the short fixture is s3p1 BATTERY_LEVEL = 90.
    first = events[0]
    assert (first.siid, first.piid) == (3, 1)
    assert first.value == 90
    assert first.timestamp == "2026-04-17 09:55:56"


def test_iter_probe_log_captures_list_value_for_telemetry_blob(fixtures_dir: Path):
    events = list(iter_probe_log(fixtures_dir / "session_short.jsonl"))
    blobs = [e for e in events if (e.siid, e.piid) == (1, 1)]
    assert blobs, "expected at least one s1p1 heartbeat blob"
    assert isinstance(blobs[0].value, list)
    assert len(blobs[0].value) == 20


def test_iter_probe_log_raises_on_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(iter_probe_log(tmp_path / "does_not_exist.jsonl"))
