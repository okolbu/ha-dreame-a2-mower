from types import SimpleNamespace
from custom_components.dreame_a2_mower.session_card import format_session_label


def _entry(**kw):
    base = dict(start_ts=1717081740, end_ts=1717083000, map_id=1,
                area_mowed_m2=0.0, duration_min=21, local_trail_complete=True)
    base.update(kw); return SimpleNamespace(**base)


def test_mode_and_start_mode_labels_match_decoded_mapping():
    """MODE_LABELS / START_MODE_LABELS must match the verified decode
    (inventory § summary_mode): 100 all-areas / 101 edge / 102 zone / 103 spot /
    107 point-patrol / 108 edge-patrol; start_mode 1=scheduled / 0=manual. (Old
    code had 102='All areas' and reversed start_mode — guesswork.)"""
    from custom_components.dreame_a2_mower.session_card import (
        MODE_LABELS, START_MODE_LABELS,
    )
    assert MODE_LABELS[100] == "All areas"
    assert MODE_LABELS[101] == "Edge"
    assert MODE_LABELS[102] == "Zone"
    assert MODE_LABELS[103] == "Spot"
    assert MODE_LABELS[107] == "Point Patrol"
    assert MODE_LABELS[108] == "Edge Patrol"
    assert START_MODE_LABELS[1] == "Scheduled"
    assert START_MODE_LABELS[0].startswith("Manual")


def test_mow_label_unchanged():
    lbl = format_session_label(_entry(session_type="mow", area_mowed_m2=42.0))
    assert lbl.startswith("[Mowing] [Map 2]")


def test_maintenance_run_label():
    lbl = format_session_label(_entry(session_type="maintenance_run", outcome="could_not_reach"))
    assert lbl.startswith("[To Point] [Map 2]")
    assert "(blocked)" in lbl


def test_manual_drive_label():
    lbl = format_session_label(_entry(session_type="manual_drive"))
    assert lbl.startswith("[Manual] [Map 2]")


def test_back_compat_no_session_type_is_mow():
    lbl = format_session_label(_entry(area_mowed_m2=12.0))  # no session_type attr at all
    assert lbl.startswith("[Mowing] [Map 2]")


def test_patrol_label():
    lbl = format_session_label(_entry(session_type="patrol"))
    assert lbl.startswith("[Patrol] [Map 2]")
    # blades-up: no area/coverage in the label
    assert "m²" not in lbl


def test_patrol_point_label_has_point_subtype_and_duration():
    """mode=107 (Point Patrol) postfixes '— Point / Dmin', keeping [Patrol] as the
    primary tag. Patrol picker entries carry no m², so the subtype + actual run
    time stand in for the mow branch's 'm² / Dmin'."""
    lbl = format_session_label(_entry(session_type="patrol", mode=107, duration_min=11))
    assert lbl.startswith("[Patrol] [Map 2]")
    assert "— Point / 11min" in lbl
    assert "Edge" not in lbl
    assert "m²" not in lbl


def test_patrol_edge_label_has_edge_subtype_and_duration():
    """mode=108 (Edge Patrol) postfixes '— Edge / Dmin'."""
    lbl = format_session_label(_entry(session_type="patrol", mode=108, duration_min=7))
    assert lbl.startswith("[Patrol] [Map 2]")
    assert "— Edge / 7min" in lbl
    assert "Point" not in lbl


def test_patrol_unknown_mode_shows_duration_only():
    """Patrol with no recorded mode (non-echoed saw_patrol_start, or a legacy
    entry) → no subtype word, but the run time is still postfixed when present."""
    lbl = format_session_label(_entry(session_type="patrol", duration_min=9))
    assert lbl.startswith("[Patrol] [Map 2]")
    assert "Point" not in lbl and "Edge" not in lbl
    assert "— 9min" in lbl


def test_patrol_no_mode_no_duration_is_bare():
    """Neither subtype nor duration → the original bare [Patrol] label."""
    lbl = format_session_label(_entry(session_type="patrol", duration_min=0))
    assert lbl.startswith("[Patrol] [Map 2]")
    assert "—" not in lbl
    assert "min" not in lbl
