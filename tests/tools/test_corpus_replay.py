"""Tests for the corpus-replay golden harness (refactor-v2 P0)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.replay.corpus_replay import digest_diff, iter_pushes, main, replay

_REPO = Path(__file__).resolve().parents[2]

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


def test_sm_error_is_folded_into_rolling_hash(tmp_path):
    """A malformed s1p1 frame must not abort replay AND must leave a mark.

    A truncated s1p1 blob is dropped safely by pipeline 1
    (_apply_s1p1_heartbeat catches) but raises InvalidS1P1Frame in the
    harness's direct decode_s1p1 call for the SM pipeline — that crash is
    a finding, folded into the rolling hash as an SM_ERROR entry.
    """
    clean = _write_jsonl(tmp_path / "probe_log_clean.jsonl", _LINES)
    d_clean = replay([clean])

    bad_rows = list(_LINES) + [
        # 3-byte s1p1 blob: decode_s1p1 requires FRAME_LENGTH=20 → raises
        {"type": "mqtt_message", "timestamp": "2026-04-17 09:34:00",
         "params": [{"did": "-1", "siid": 1, "piid": 1, "value": [206, 0, 206]}]},
    ]
    bad = _write_jsonl(tmp_path / "probe_log_bad.jsonl", bad_rows)
    d_bad = replay([bad])  # must not raise

    assert d_bad["push_count"] == d_clean["push_count"] + 1
    assert d_bad["per_slot"]["s1p1"]["count"] == 1
    # SM_ERROR was chained into the rolling hash: same corpus + bad frame
    # hashes differently even though neither state pipeline changed state.
    assert d_bad["rolling_sha256"] != d_clean["rolling_sha256"]
    # ...and the final states themselves are untouched by the bad frame.
    assert d_bad["final_mower_state"] == d_clean["final_mower_state"]
    assert d_bad["final_snapshot"] == d_clean["final_snapshot"]


def test_main_exit_code_2_when_no_logs_match(tmp_path, capsys):
    assert main(["--corpus-dir", str(tmp_path)]) == 2
    assert "no logs match" in capsys.readouterr().err


def test_main_exit_code_0_on_identical_diff(tmp_path, capsys):
    _write_jsonl(tmp_path / "probe_log_a.jsonl", _LINES)
    golden = tmp_path / "golden.json"
    assert main(["--corpus-dir", str(tmp_path), "--out", str(golden)]) == 0
    assert golden.exists()
    assert main(["--corpus-dir", str(tmp_path), "--diff", str(golden)]) == 0
    assert "IDENTICAL" in capsys.readouterr().out


def test_main_exit_code_1_on_mismatched_diff(tmp_path, capsys):
    _write_jsonl(tmp_path / "probe_log_a.jsonl", _LINES)
    golden = tmp_path / "golden.json"
    assert main(["--corpus-dir", str(tmp_path), "--out", str(golden)]) == 0
    tampered = json.loads(golden.read_text())
    tampered["rolling_sha256"] = "0" * 64
    golden.write_text(json.dumps(tampered))
    assert main(["--corpus-dir", str(tmp_path), "--diff", str(golden)]) == 1
    out = capsys.readouterr().out
    assert "MISMATCH" in out and "rolling_sha256" in out


def test_main_partial_extract_flags_error(tmp_path):
    """A lone --extract-* flag must argparse-error (exit 2), not silently
    fall through to a normal replay run."""
    import pytest

    with pytest.raises(SystemExit) as ei:
        main(["--corpus-dir", str(tmp_path), "--extract-start", "x"])
    assert ei.value.code == 2


def test_cli_standalone_without_pytest_conftest(tmp_path):
    """`python -m tools.replay.corpus_replay` must work in a bare venv.

    Regression guard for the ModuleNotFoundError('homeassistant') CLI
    break: a subprocess has no pytest-injected HA stub, so this proves
    the harness's own _ensure_ha_stubs bootstrap carries it.
    """
    _write_jsonl(tmp_path / "probe_log_a.jsonl", _LINES)
    out = tmp_path / "golden.json"
    result = subprocess.run(
        [sys.executable, "-m", "tools.replay.corpus_replay",
         "--corpus-dir", str(tmp_path), "--out", str(out)],
        cwd=_REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    digest = json.loads(out.read_text())
    assert digest["schema"] == 1
    assert digest["push_count"] == 3
