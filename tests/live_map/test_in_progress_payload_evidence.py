"""FAILING repro (TDD red): mow-evidence fields are dropped by the
in_progress.json persistence round-trip.

Incident (2026-05-31): a scheduled all-area MOW (147.5/371 m² mowed) hit
rain protection, returned to dock, and was charging (paused for rain).
HA was REBOOTED in this state. After reboot the session was archived as
session_type=maintenance_run with area 0.0 — prematurely finalized AND
mis-classified.

Root-cause defect #1 (this file): live_map/state.py:dump_to_payload
persists track + samples + charge_at_start + settings_snapshot, but NOT
the mow-evidence fields `area_ever_positive`, `last_task_op`, `target_ids`.
hydrate_from_payload therefore cannot restore them; after reboot they
reset to their dataclass defaults (False / None / []). The finalize-time
classifier (_inject_live_map_into_raw_dict → classify_session_type) reads
those reset values, contributing to the maintenance_run mis-classification.

These tests assert the DESIRED round-trip behaviour and are EXPECTED TO
FAIL until dump_to_payload/hydrate_from_payload carry the three fields.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def _build_session_with_evidence() -> LiveMapState:
    """An active session that has accumulated positive mow-evidence:
    area grew (area_ever_positive latches True), a TASK op was seen, and
    a target id was visited."""
    lm = LiveMapState()
    lm.begin_session(started_unix=1000)
    # Two points with a growing area counter → area_ever_positive becomes
    # True and the second point's role is "mowing".
    lm.append_point(t=1001.0, x_m=0.0, y_m=0.0, area_m2=0.0, heading_deg=0.0)
    lm.append_point(t=1002.0, x_m=1.0, y_m=1.0, area_m2=5.0, heading_deg=45.0)
    # Mow-evidence signals captured during the run (mirrors
    # capture_session_type_signals side effects).
    lm.area_ever_positive = True
    lm.last_task_op = 100
    lm.target_ids = [3]
    return lm


def test_area_ever_positive_survives_round_trip():
    lm = _build_session_with_evidence()
    assert lm.area_ever_positive is True  # precondition

    payload = lm.dump_to_payload()
    fresh = LiveMapState()
    fresh.hydrate_from_payload(payload)

    assert fresh.area_ever_positive is True, (
        "area_ever_positive was lost across the in_progress.json round-trip "
        f"(payload key present? {'area_ever_positive' in payload})"
    )


def test_last_task_op_survives_round_trip():
    lm = _build_session_with_evidence()
    assert lm.last_task_op == 100  # precondition

    payload = lm.dump_to_payload()
    fresh = LiveMapState()
    fresh.hydrate_from_payload(payload)

    assert fresh.last_task_op == 100, (
        "last_task_op was lost across the in_progress.json round-trip "
        f"(payload key present? {'last_task_op' in payload}); "
        f"got {fresh.last_task_op!r}"
    )


def test_target_ids_survives_round_trip():
    lm = _build_session_with_evidence()
    assert lm.target_ids == [3]  # precondition

    payload = lm.dump_to_payload()
    fresh = LiveMapState()
    fresh.hydrate_from_payload(payload)

    assert fresh.target_ids == [3], (
        "target_ids was lost across the in_progress.json round-trip "
        f"(payload key present? {'target_ids' in payload}); "
        f"got {fresh.target_ids!r}"
    )
