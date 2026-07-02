"""Tests for the corpus-replay golden harness (refactor-v2 P0)."""
from __future__ import annotations

import json
from pathlib import Path

from tools.replay.corpus_replay import digest_diff, iter_pushes, replay

_LINES = [
    # non-mqtt lines must be skipped
    {"type": "session_start", "timestamp": "2026-04-17 09:31:27", "device": {"did": "-1"}},
    {"type": "api_probe", "timestamp": "2026-04-17 09:31:35"},
    # battery scalar (s3p1) — mapped in PROPERTY_MAPPING and in the SM
    {
        "type": "mqtt_message",
        "timestamp": "2026-04-17 09:31:55",
        "params": [{"did": "-1", "siid": 3, "piid": 1, "value": 62}],
    },
    # two params in one message
    {
        "type": "mqtt_message",
        "timestamp": "2026-04-17 09:32:00",
        "params": [
            {"did": "-1", "siid": 3, "piid": 1, "value": 63},
            {"did": "-1", "siid": 3, "piid": 2, "value": 1},
        ],
    },
]


def _write_jsonl(path: Path, rows) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def test_iter_pushes_yields_only_property_params(tmp_path):
    log = _write_jsonl(tmp_path / "probe.jsonl", _LINES)
    pushes = list(iter_pushes(log))
    assert [(s, p, v) for _, s, p, v in pushes] == [(3, 1, 62), (3, 1, 63), (3, 2, 1)]
    # timestamps are unix ints and non-decreasing
    ts = [t for t, *_ in pushes]
    assert all(isinstance(t, int) for t in ts) and ts == sorted(ts)


def test_replay_digest_shape_and_determinism(tmp_path):
    log = _write_jsonl(tmp_path / "probe.jsonl", _LINES)
    d1 = replay([log])
    d2 = replay([log])
    assert d1 == d2  # byte-determinism
    assert d1["schema"] == 1
    assert d1["push_count"] == 3
    assert d1["per_slot"]["s3p1"]["count"] == 2
    assert d1["final_mower_state"]["battery_level"] == 63
    assert d1["final_snapshot"]["battery_percent"] == 63
    assert isinstance(d1["rolling_sha256"], str) and len(d1["rolling_sha256"]) == 64


def test_replay_survives_malformed_and_unknown_lines(tmp_path):
    rows = list(_LINES) + [
        {"type": "mqtt_message", "timestamp": "2026-04-17 09:33:00",
         "params": [{"did": "-1", "siid": 99, "piid": 99, "value": {"x": 1}}]},
    ]
    log = _write_jsonl(tmp_path / "probe.jsonl", rows)
    log.write_text(log.read_text() + "not json at all\n")
    d = replay([log])  # must not raise
    assert d["push_count"] == 4
    assert d["per_slot"]["s99p99"]["count"] == 1


def test_digest_diff_reports_and_clears(tmp_path):
    log = _write_jsonl(tmp_path / "probe.jsonl", _LINES)
    a = replay([log])
    assert digest_diff(a, replay([log])) == []
    b = json.loads(json.dumps(a))
    b["final_mower_state"]["battery_level"] = 1
    b["rolling_sha256"] = "0" * 64
    problems = digest_diff(a, b)
    assert any("battery_level" in p for p in problems)
    assert any("rolling_sha256" in p for p in problems)
