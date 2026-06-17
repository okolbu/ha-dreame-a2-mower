"""Wire-send trace helper: gated, append-only JSONL, never raises.

The trace is a debugging instrument for diffing our on-wire action payloads
against the app↔mower MITM captures. It must (a) do nothing without the
sentinel, (b) append one JSON line per record when enabled, and (c) never let
a tracing failure propagate into a real device write.
"""
import json

import custom_components.dreame_a2_mower.cloud_client._helpers as helpers


def _point_paths(tmp_path, monkeypatch):
    sentinel = tmp_path / "trace.enabled"
    out = tmp_path / "trace.jsonl"
    monkeypatch.setattr(helpers, "_WIRE_TRACE_SENTINEL", str(sentinel))
    monkeypatch.setattr(helpers, "_WIRE_TRACE_PATH", str(out))
    return sentinel, out


def test_no_op_without_sentinel(tmp_path, monkeypatch):
    _sentinel, out = _point_paths(tmp_path, monkeypatch)
    assert helpers.wire_trace_enabled() is False
    helpers.wire_trace({"siid": 2, "aiid": 50, "in": [{"o": 111}]})
    assert not out.exists()


def test_appends_jsonl_when_enabled(tmp_path, monkeypatch):
    sentinel, out = _point_paths(tmp_path, monkeypatch)
    sentinel.write_text("")  # operator dropped the sentinel
    assert helpers.wire_trace_enabled() is True

    helpers.wire_trace({"siid": 2, "aiid": 50, "in": [{"m": "a", "o": 111, "point": [3, 3]}]})
    helpers.wire_trace({"siid": 2, "aiid": 50, "in": [{"m": "s", "t": "CRUISED"}]})

    lines = out.read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["in"][0]["o"] == 111 and first["in"][0]["point"] == [3, 3]
    assert json.loads(lines[1])["in"][0]["t"] == "CRUISED"


def test_non_json_value_does_not_break_line(tmp_path, monkeypatch):
    sentinel, out = _point_paths(tmp_path, monkeypatch)
    sentinel.write_text("")
    # A result carrying a non-JSON object (e.g. an exception) must still produce
    # a parseable line via default=repr, not raise.
    helpers.wire_trace({"siid": 2, "aiid": 50, "result": ValueError("boom")})
    line = json.loads(out.read_text().splitlines()[0])
    assert "boom" in line["result"]


def test_never_raises_on_unwritable_path(tmp_path, monkeypatch):
    sentinel = tmp_path / "trace.enabled"
    sentinel.write_text("")
    monkeypatch.setattr(helpers, "_WIRE_TRACE_SENTINEL", str(sentinel))
    # Point the output at a path whose parent is a file, so open() fails.
    bad = tmp_path / "afile"
    bad.write_text("x")
    monkeypatch.setattr(helpers, "_WIRE_TRACE_PATH", str(bad / "nested.jsonl"))
    # Must swallow the OSError rather than propagate into the caller's write.
    helpers.wire_trace({"siid": 2, "aiid": 50})
