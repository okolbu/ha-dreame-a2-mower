"""AIOBS marker parser — golden from
[cloud/captures/mitm_session_20260619/miio-13267.jsonl@2026-06-17_19:50:15]."""
import math

from custom_components.dreame_a2_mower.protocol import cfg_action
from custom_components.dreame_a2_mower.protocol.obstacle_markers import (
    ObstacleMarker,
    parse_aiobs_markers,
)

# The exact `d` dict captured inline in the AIOBS read response.
_GOLDEN_D = {
    "idx": 0,
    "obs": [
        [
            [-6627, -6777, -6827, -6827, -6627],   # X verts, cloud-map mm
            [4113, 4163, 4163, 4063, 4063],        # Y verts, cloud-map mm
            78,                                     # confidence ≈ f*100
            5,                                      # class == JPEG-COM "s"
            "1781714586.078000_0",                  # filename base
            0,                                      # flag [UNVERIFIED]
            "1781714586.078000_0",                  # id
        ]
    ],
}


def test_parses_single_marker_geometry_and_fields():
    markers = parse_aiobs_markers(_GOLDEN_D)
    assert len(markers) == 1
    m = markers[0]
    assert m.id == "1781714586.078000_0"
    assert m.filename == "1781714586.078000_0"
    assert m.confidence == 78
    assert m.obstacle_class == 5
    assert m.flag == 0
    # mm → metres, paired (x, y), reflection NOT applied here.
    assert m.polygon_m[0] == (-6.627, 4.113)
    assert len(m.polygon_m) == 5
    # detection epoch parsed from the filename base "<epoch.frac>_<idx>".
    assert math.isclose(m.detection_epoch, 1781714586.078, rel_tol=0, abs_tol=1e-3)


def test_empty_or_missing_obs_returns_empty_list():
    assert parse_aiobs_markers(None) == []
    assert parse_aiobs_markers({"idx": 0}) == []
    assert parse_aiobs_markers({"idx": 0, "obs": []}) == []


def test_degenerate_polygon_is_kept_but_flagged_short():
    # Fewer than 3 verts — parser keeps the record (metadata matters) but the
    # polygon is short; render-side drops <3-point polygons (Task 7).
    d = {"obs": [[[1000], [2000], 50, 5, "1.0_0", 0, "1.0_0"]]}
    markers = parse_aiobs_markers(d)
    assert len(markers) == 1
    assert markers[0].polygon_m == ((1.0, 2.0),)


def test_get_aiobs_markers_sends_idx_payload_and_unwraps():
    calls = []

    def fake_send(siid, aiid, params):
        calls.append((siid, aiid, params))
        # Mirror the wire `out` envelope cfg_action._unwrap expects.
        return {"result": {"out": [{"m": "r", "r": 0, "d": {"idx": 0, "obs": []}}]}}

    d = cfg_action.get_aiobs_markers(fake_send, idx=0)
    assert calls == [(2, 50, [{"m": "g", "t": "AIOBS", "d": {"idx": 0}}])]
    assert d == {"idx": 0, "obs": []}
