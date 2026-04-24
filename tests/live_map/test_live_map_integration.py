"""Integration test — reconstruct a real session from the probe log.

Uses the 2026-04-17 probe log's Y-axis session (session index 4:
22:14-23:09) to validate that LiveMapState produces a reasonable
path when driven by real telemetry.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from live_map import LiveMapState
from protocol.replay import iter_probe_log
from protocol.telemetry import decode_s1p4

PROBE_LOG = Path("/data/claude/homeassistant/probe_log_20260417_095500.jsonl")


def _parse(ts: str) -> datetime.datetime:
    return datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def _sessions_from_probe_log(path: Path) -> list[list]:
    """Group probe-log telemetry events into sessions by >3-minute gaps."""
    telem = []
    for ev in iter_probe_log(path):
        if (ev.siid, ev.piid) != (1, 4):
            continue
        if not isinstance(ev.value, list) or len(ev.value) != 33:
            continue
        telem.append(ev)

    sessions: list[list] = []
    current: list = []
    for ev in telem:
        t = _parse(ev.timestamp)
        if current and (t - _parse(current[-1].timestamp)).total_seconds() > 180:
            sessions.append(current)
            current = []
        current.append(ev)
    if current:
        sessions.append(current)
    return sessions


@pytest.mark.skipif(not PROBE_LOG.exists(), reason="probe log fixture missing")
def test_y_axis_session_reconstructs_with_calibrated_points():
    sessions = _sessions_from_probe_log(PROBE_LOG)
    assert len(sessions) >= 5, (
        f"expected at least 5 sessions in the probe log, got {len(sessions)}"
    )

    # Session 4 = 2026-04-17 22:14-23:09 Y-axis mow (per memory).
    y_axis_session = sessions[4]
    assert len(y_axis_session) > 400, (
        f"Y-axis session should have >400 frames, got {len(y_axis_session)}"
    )

    s = LiveMapState()
    s.start_session(y_axis_session[0].timestamp)

    x_factor = 1.0
    y_factor = 1.0  # was 0.625 before alpha.98 — compensated for the old
                   # 16× Y decode scaling; no longer needed.

    for ev in y_axis_session:
        telem = decode_s1p4(bytes(ev.value))
        x_m = (telem.x_mm / 1000.0) * x_factor
        y_m = (telem.y_mm / 1000.0) * y_factor
        s.append_point(x_m, y_m)

    # Plan C recorded X span ~5m and Y calibrated span ~20m for this session.
    xs = [p[0] for p in s.path]
    ys = [p[1] for p in s.path]
    x_span = max(xs) - min(xs)
    y_span = max(ys) - min(ys)

    assert 3.0 < x_span < 7.0, f"X span {x_span:.2f} m outside expected 3-7 m window"
    assert 14.0 < y_span < 30.0, f"Y span {y_span:.2f} m outside expected 14-30 m window"

    # After dedupe, path should be 200-700 points (mower frames deduped at 0.2 m).
    assert 200 < len(s.path) < 700, f"path length {len(s.path)} outside 200-700"
