// Frame-parity harness: project a fixed set of (x_m, y_m) points through the
// REAL JS `projectPoint` from _dreame-map-core.js and emit the pixel results as
// JSON on stdout. The Python side (test_projection_parity.py) feeds the SAME
// projection inputs through map_render._geometry (_cloud_to_px + the
// height_px flip, exactly as extract_projection documents the card consumes
// them) and asserts the pixel outputs agree within a tight epsilon.
//
// This pins that the Python render frame and the JS card projection stay in
// lockstep — the regression gate for the future (deferred) transform-move.
import { projectPoint } from "../../custom_components/dreame_a2_mower/www/_dreame-map-core.js";

// Projection params (bbox corners in mm, grid, canvas size). Chosen so the
// bbox corners and several interior/exterior points exercise both axes and the
// top-bottom flip. height_px is deliberately != width_px to catch an axis swap.
const proj = {
  bx1_mm: 1000,
  by1_mm: -2000,
  bx2_mm: 21000,
  by2_mm: 19000,
  pixel_size_mm: 50,
  width_px: 400,
  height_px: 420,
};

// Input points in METRES (cloud frame). Includes the two bbox corners
// (bx2/by2 -> pixel (0, height) before/after flip; bx1/by1 -> the far corner)
// plus interior + negative-coordinate points.
const points_m = [
  [21.0, 19.0],   // (bx2, by2) corner
  [1.0, -2.0],    // (bx1, by1) corner
  [11.0, 8.5],    // interior
  [0.0, 0.0],     // origin
  [-3.25, 12.75], // negative x
  [5.5, -1.0],    // negative y
  [21.0, -2.0],   // mixed corner
  [1.0, 19.0],    // mixed corner
];

const pixels = points_m.map(([x_m, y_m]) => projectPoint(x_m, y_m, proj));

process.stdout.write(JSON.stringify({ proj, points_m, pixels }));
