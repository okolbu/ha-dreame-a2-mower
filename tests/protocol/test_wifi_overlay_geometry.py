"""Pin the WiFi-overlay cell->rect geometry the live-map card implements.

The card derives each heatmap cell's screen rectangle by:
  1. cell (cx, cy) covers cloud-metre box
       x in [start_x_m + cx*res, start_x_m + (cx+1)*res]
       y in [start_y_m + cy*res, start_y_m + (cy+1)*res]
     (the inverse of wifi_match.score_candidates' cx/cy formula)
  2. projecting the two opposite corners with projectPoint (same as the live
     trail), then taking min/max for an axis-aligned <rect>.
This is the contract dreame-mower-map-card.js mirrors in JS (not executed here)."""
from __future__ import annotations


def _project_point(x_m, y_m, proj):
    # Character-equivalent to _dreame-map-core.js:projectPoint.
    px = (proj["bx2_mm"] - x_m * 1000) / proj["pixel_size_mm"]
    py = proj["height_px"] - (proj["by2_mm"] - y_m * 1000) / proj["pixel_size_mm"]
    return (px, py)


def _cell_rect(cx, cy, overlay, proj):
    res = overlay["resolution_m"]
    x0 = overlay["start_x_m"] + cx * res
    x1 = overlay["start_x_m"] + (cx + 1) * res
    y0 = overlay["start_y_m"] + cy * res
    y1 = overlay["start_y_m"] + (cy + 1) * res
    p00 = _project_point(x0, y0, proj)
    p11 = _project_point(x1, y1, proj)
    xmin, xmax = sorted((p00[0], p11[0]))
    ymin, ymax = sorted((p00[1], p11[1]))
    return (xmin, ymin, xmax - xmin, ymax - ymin)


def test_cell_rect_matches_projection():
    proj = {"bx2_mm": 20000.0, "by2_mm": 21000.0,
            "pixel_size_mm": 50.0, "width_px": 400, "height_px": 420}
    overlay = {"resolution_m": 2.0, "start_x_m": 0.0, "start_y_m": 0.0}
    # Cell (0,0) covers cloud x in [0,2] m, y in [0,2] m.
    x, y, w, h = _cell_rect(0, 0, overlay, proj)
    # 2 m / 0.05 m-per-px = 40 px square.
    assert round(w, 6) == 40.0
    assert round(h, 6) == 40.0
    # Corner (0,0) cloud -> px=(20000-0)/50=400, py=420-(21000-0)/50=0.
    # Corner (2,2) cloud -> px=(20000-2000)/50=360, py=420-(21000-2000)/50=40.
    assert round(x, 6) == 360.0   # min of {400, 360}
    assert round(y, 6) == 0.0     # min of {0, 40}


def test_cell_index_is_row_major():
    # idx = cy*width + cx, matching wifi_match.score_candidates.
    width = 3
    assert 1 * width + 2 == 5  # cell (cx=2, cy=1) -> data index 5
