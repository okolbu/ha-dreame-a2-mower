// Dreame A2 Mower — pure map-edit geometry helpers
//
// Pure ES-module functions (NO DOM, NO globals) so they node-test under
// tests/www/geom_harness.mjs (gated by tests/www/test_map_edit_geom.py).
//
// Coordinate frames:
//   - "meters": cloud frame (the wire frame the map-edit ops consume).
//   - "pixel": screen px in the served (FLIP_TOP_BOTTOM'd) base PNG.
// projectPoint (./_dreame-map-core.js) is the SoT forward transform
// (meters -> pixel). pixelToMeters is the Task-1-LOCKED algebraic inverse.
//
// proj = { bx2_mm, by2_mm, pixel_size_mm, height_px } (width_px optional).

import { projectPoint } from "./_dreame-map-core.js";

// Pixel (screen) -> meters (cloud). Task-1-LOCKED inverse of projectPoint:
//   x_m = (bx2_mm - px*pixel_size_mm) / 1000
//   y_m = (by2_mm - (height_px - py)*pixel_size_mm) / 1000
export function pixelToMeters(px, py, proj) {
  const x_m = (proj.bx2_mm - px * proj.pixel_size_mm) / 1000;
  const y_m = (proj.by2_mm - (proj.height_px - py) * proj.pixel_size_mm) / 1000;
  return [x_m, y_m];
}

// Meters (cloud) -> pixel (screen). Thin wrapper over the SoT forward
// transform so this module cannot drift from the live-map projection.
export function metersToPixel(x_m, y_m, proj) {
  return projectPoint(x_m, y_m, proj);
}

// Two opposite drag points -> 4 axis-aligned rectangle corners, ordered
// p0, (p1x,p0y), p1, (p0x,p1y) (consistent winding for the polygon wire).
export function rectCorners(p0, p1) {
  const [x0, y0] = p0;
  const [x1, y1] = p1;
  return [
    [x0, y0],
    [x1, y0],
    [x1, y1],
    [x0, y1],
  ];
}

// Two drag points -> the 2-point bbox representation used by curved
// mow-shapes. Normalized so [0] is the min corner and [1] the max corner.
export function bboxCorners(p0, p1) {
  const [x0, y0] = p0;
  const [x1, y1] = p1;
  return [
    [Math.min(x0, x1), Math.min(y0, y1)],
    [Math.max(x0, x1), Math.max(y0, y1)],
  ];
}

// Rotate a polygon's corners about their centroid by `deg` degrees.
// Preserves edge lengths (rigid rotation). Returns a new array of [x,y].
export function rotatePointsAroundCentroid(points, deg) {
  const n = points.length;
  if (n === 0) return [];
  let cx = 0;
  let cy = 0;
  for (const [x, y] of points) {
    cx += x;
    cy += y;
  }
  cx /= n;
  cy /= n;
  const rad = (deg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  return points.map(([x, y]) => {
    const dx = x - cx;
    const dy = y - cy;
    return [cx + dx * cos - dy * sin, cy + dx * sin + dy * cos];
  });
}

// Uniformly scale `corners` (keep aspect ratio) when corner `handleIdx` is
// dragged to `newPos`. The scaling is anchored at the centroid; the scale
// factor is the ratio of the new handle distance to the old handle distance
// from the centroid. Returns a new array of [x,y].
export function resizeUniform(corners, handleIdx, newPos) {
  const n = corners.length;
  if (n === 0) return [];
  let cx = 0;
  let cy = 0;
  for (const [x, y] of corners) {
    cx += x;
    cy += y;
  }
  cx /= n;
  cy /= n;
  const [hx, hy] = corners[handleIdx];
  const oldR = Math.hypot(hx - cx, hy - cy);
  if (oldR === 0) return corners.map(([x, y]) => [x, y]);
  const newR = Math.hypot(newPos[0] - cx, newPos[1] - cy);
  const s = newR / oldR;
  return corners.map(([x, y]) => [cx + (x - cx) * s, cy + (y - cy) * s]);
}

// Center + a point on the rim -> { center, radius }. radius = |edge - center|.
export function circleFromCenterEdge(center, edge) {
  const radius = Math.hypot(edge[0] - center[0], edge[1] - center[1]);
  return { center: [center[0], center[1]], radius };
}

// Map an editor draft to the wire shape: { points: [[x,y]...], radius }.
//
// state contracts by (category, shape):
//   - nogo "line"            -> { a:[x,y], b:[x,y] }          -> 2 points, r 0
//   - nogo "polygon"         -> { points: [[x,y]...] }        -> N points, r 0
//   - nogo "circle"          -> { center:[x,y], edge:[x,y] }  -> 1 point (center), r = radius
//   - ignore "polygon"       -> { points: [[x,y]...] }        -> N points, r 0
//   - mow "square"           -> { p0:[x,y], p1:[x,y] }        -> 4 corners (rectCorners), r 0
//   - mow other (circle/heart/triangle/teardrop/mushroom/cloud/rainbow)
//                            -> { p0:[x,y], p1:[x,y] }        -> 2-pt bbox (bboxCorners), r 0
//
// Coordinates are passed through frame-agnostic (caller supplies meters).
export function shapeToPoints(category, shape, state) {
  if (category === "nogo") {
    if (shape === "line") {
      return { points: [state.a, state.b], radius: 0 };
    }
    if (shape === "circle") {
      const { radius } = circleFromCenterEdge(state.center, state.edge);
      return { points: [state.center], radius };
    }
    if (shape === "polygon") {
      return { points: state.points.map((p) => [p[0], p[1]]), radius: 0 };
    }
  } else if (category === "ignore") {
    if (shape === "polygon") {
      return { points: state.points.map((p) => [p[0], p[1]]), radius: 0 };
    }
  } else if (category === "mow") {
    if (shape === "square") {
      return { points: rectCorners(state.p0, state.p1), radius: 0 };
    }
    // all other mow-shapes -> 2-point bbox
    return { points: bboxCorners(state.p0, state.p1), radius: 0 };
  }
  throw new Error(`shapeToPoints: unsupported (${category}, ${shape})`);
}
