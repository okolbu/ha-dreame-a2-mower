"""FAILING repro (TDD red): a rain-paused MOW mis-classifies as
maintenance_run after an HA reboot.

Incident (2026-05-31): a scheduled all-area MOW (147.5/371 m² mowed) hit
rain protection (s2p2=56), returned to dock, and was charging. HA was
REBOOTED in this state. After reboot the session was archived with
session_type=maintenance_run and area 0.0 — both prematurely finalized
AND mis-classified, despite a 1927-row track ending at area_m2=147.47.

This file pins defect #1's USER-VISIBLE consequence: the finalize-time
classifier (the SAME logic _inject_live_map_into_raw_dict runs) must
classify a restored rain-paused mow as "mow", not "maintenance_run".

Why it fails today: classify_session_type's mow signals are
  (a) saw_mow_start  — derived at finalize from error_samples (50/53), AND
  (b) area_ever_positive — a LiveMapState field.
On reboot, dump_to_payload/hydrate_from_payload DROP area_ever_positive
(it resets to False). For a SCHEDULED all-area mow, last_task_op is None
(the op never echoes) and the start code 53 fires in the same second the
session begins — it is NOT guaranteed to be in the persisted error_samples
window. When the persisted error_samples hold only the later rain code 56
(no 50/53), saw_mow_start=False AND area_ever_positive=False, so the
classifier falls through to its maintenance_run default — even though the
restored track plainly shows 147 m² of cut grass.

The faithful durable assertion: a restored session whose TRACK shows a
positive mowed area must classify as "mow". Today it does not, because
the only durable mow-evidence (area_ever_positive) is not persisted and
the track's own area is never consulted by the classifier.

EXPECTED TO FAIL until area_ever_positive is persisted (or the classifier
derives mow-evidence from the restored track's area).
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.classify import (
    classify_session_type,
)
from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def _restore_live_map_after_reboot() -> LiveMapState:
    """Reproduce the post-reboot LiveMapState for the rain incident.

    A scheduled all-area mow: area grew to 147.47 m², op never echoed
    (last_task_op stays None), and the persisted error_samples hold only
    the rain code 56 (the scheduled-start code 53 fired in the same
    second the session began, before the first in_progress.json persist
    tick — the realistic disk state for a long-running scheduled mow).
    """
    pre_reboot = LiveMapState()
    pre_reboot.begin_session(started_unix=1000)
    pre_reboot.append_point(t=1001.0, x_m=0.0, y_m=0.0, area_m2=0.0, heading_deg=0.0)
    # Cumulative mowed-area counter climbs to 147.47 m² over the run.
    pre_reboot.append_point(t=2000.0, x_m=12.0, y_m=8.0, area_m2=147.47, heading_deg=90.0)
    # In-memory mow evidence that the run accumulated:
    pre_reboot.area_ever_positive = True          # latched when area first grew
    pre_reboot.last_task_op = None                # scheduled mow: op never echoes
    pre_reboot.error_samples = [(1500, 56)]       # rain only; no 50/53 on disk

    # --- reboot: persist to in_progress.json, then restore into a fresh state
    payload = pre_reboot.dump_to_payload()
    restored = LiveMapState()
    restored.hydrate_from_payload(payload)
    return restored


def _classify_like_finalizer(lm: LiveMapState) -> tuple[str, str | None]:
    """Mirror coordinator/_lidar_oss.py:_inject_live_map_into_raw_dict's
    classification block exactly, so this test exercises the real
    finalize-time decision inputs."""
    codes = [code for _, code in (lm.error_samples or [])]
    saw_mow_start = any(c in (50, 53) for c in codes)
    saw_patrol_start = 51 in codes
    end_codes = [c for c in codes if c in (75, 76)]
    last_point_end_code = end_codes[-1] if end_codes else None
    return classify_session_type(
        last_task_op=lm.last_task_op,
        saw_mow_start=saw_mow_start,
        area_ever_positive=lm.area_ever_positive,
        last_point_end_code=last_point_end_code,
        saw_patrol_start=saw_patrol_start,
    )


def test_restored_rain_paused_mow_classifies_as_mow():
    """A rain-paused all-area mow that survived a reboot must finalize as
    a MOW, never as maintenance_run.

    This is the user-visible bug: the restored track shows 147 m² mowed,
    but the classifier (using post-restore inputs) returns maintenance_run.
    """
    restored = _restore_live_map_after_reboot()

    # Sanity: the durable trail evidence is intact — the track ends at 147 m².
    assert restored.track, "precondition: restored track should be non-empty"
    assert restored.track[-1].area_m2 == 147.47

    session_type, _ = _classify_like_finalizer(restored)

    assert session_type == "mow", (
        "A restored rain-paused mow (track shows 147.47 m² cut) must classify "
        f"as 'mow', got {session_type!r}. Post-restore classifier inputs: "
        f"last_task_op={restored.last_task_op!r}, "
        f"area_ever_positive={restored.area_ever_positive!r}, "
        f"error_samples={restored.error_samples!r} "
        "(area_ever_positive was dropped by the in_progress round-trip and the "
        "track's own positive area is never consulted, so it falls through to "
        "the maintenance_run default)."
    )


def test_area_ever_positive_durable_across_reboot():
    """Direct pin on the durable mow-evidence signal: area_ever_positive,
    once latched True during a mow, must survive a reboot.

    This is the single field whose loss flips the classification when no
    50/53 start code is in the persisted error_samples window."""
    restored = _restore_live_map_after_reboot()
    assert restored.area_ever_positive is True, (
        "area_ever_positive must survive the in_progress.json round-trip — "
        "it is the reboot-durable mow-evidence signal a scheduled all-area "
        "mow relies on (last_task_op is None and the 53 start-code may not be "
        "in the persisted error_samples window)."
    )
