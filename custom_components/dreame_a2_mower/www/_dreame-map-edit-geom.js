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

// Angle (DEGREES) of `pos` about the centroid of `points`. Drives a rotate
// drag: the card feeds the per-move delta (this angle minus the previous one)
// straight into rotatePointsAroundCentroid, so the centroid + atan2 convention
// stay in this tested module rather than the card. 0 deg = +x axis.
export function pointerAngleAboutCentroid(points, pos) {
  const n = points.length;
  if (n === 0) return 0;
  let cx = 0;
  let cy = 0;
  for (const [x, y] of points) {
    cx += x;
    cy += y;
  }
  cx /= n;
  cy /= n;
  return (Math.atan2(pos[1] - cy, pos[0] - cx) * 180) / Math.PI;
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

// ----- corner-rectangle free resize (rect / square mow) -------------------
// Resize a (possibly rotated) 4-corner rectangle by dragging corner `handleIdx`
// to `newPos`, keeping the diagonally-opposite corner anchored and preserving
// the rectangle's orientation + right angles (free aspect — width and height
// change independently, along the rect's OWN local axes). Returns 4 new corners
// in the same winding as the input.
export function resizeRectCorner(corners, handleIdx, newPos) {
  const anchorIdx = (handleIdx + 2) % 4;
  const a1Idx = (anchorIdx + 1) % 4; // neighbour of anchor (also adj to dragged)
  const a2Idx = (anchorIdx + 3) % 4;
  const anchor = corners[anchorIdx];
  let u = [corners[a1Idx][0] - anchor[0], corners[a1Idx][1] - anchor[1]];
  let v = [corners[a2Idx][0] - anchor[0], corners[a2Idx][1] - anchor[1]];
  const ul = Math.hypot(u[0], u[1]) || 1;
  const vl = Math.hypot(v[0], v[1]) || 1;
  u = [u[0] / ul, u[1] / ul];
  v = [v[0] / vl, v[1] / vl];
  const rel = [newPos[0] - anchor[0], newPos[1] - anchor[1]];
  const d1 = rel[0] * u[0] + rel[1] * u[1]; // projection onto local axis 1
  const d2 = rel[0] * v[0] + rel[1] * v[1];
  const out = new Array(4);
  out[anchorIdx] = [anchor[0], anchor[1]];
  out[a1Idx] = [anchor[0] + u[0] * d1, anchor[1] + u[1] * d1];
  out[a2Idx] = [anchor[0] + v[0] * d2, anchor[1] + v[1] * d2];
  out[handleIdx] = [anchor[0] + u[0] * d1 + v[0] * d2, anchor[1] + u[1] * d1 + v[1] * d2];
  return out;
}

// ----- oriented-edge model (curved mow-shapes) ----------------------------
// Curved mow-shapes are a 2-point WIRE form `[p0, p1]` where the segment is ONE
// EDGE of the shape's oriented bounding box: the edge direction is the box
// orientation (axis-aligned edge => unrotated; off-axis edge => rotated), and
// the box is square (perpendicular extent = edge length). The 2 points carry
// BOTH size and rotation — there is no separate angle field. (Wire-confirmed by
// the app: rotated curved shapes have non-axis-aligned 2-point values.)

// Left-perpendicular of the edge vector, SAME length as the edge (=> square box).
function _edgePerp(p0, p1) {
  return [-(p1[1] - p0[1]), p1[0] - p0[0]];
}

// 4 corners of the oriented box whose bottom edge is p0->p1, extending
// perpendicular-left by |p0->p1|. Order: [p0, p1, p1+n, p0+n].
export function orientedEdgeBox(p0, p1) {
  const n = _edgePerp(p0, p1);
  return [
    [p0[0], p0[1]],
    [p1[0], p1[1]],
    [p1[0] + n[0], p1[1] + n[1]],
    [p0[0] + n[0], p0[1] + n[1]],
  ];
}

// Centre of the oriented edge box = midpoint(p0,p1) + n/2.
export function edgeBoxCenter(p0, p1) {
  const n = _edgePerp(p0, p1);
  return [(p0[0] + p1[0]) / 2 + n[0] / 2, (p0[1] + p1[1]) / 2 + n[1] / 2];
}

// Uniformly scale the edge about the box centre by the ratio of the dragged
// corner's new vs old distance from the centre (handleIdx indexes the 4
// orientedEdgeBox corners). Preserves orientation + square aspect. -> [p0, p1].
export function resizeOrientedEdge(p0, p1, handleIdx, newPos) {
  const c = edgeBoxCenter(p0, p1);
  const box = orientedEdgeBox(p0, p1);
  const h = box[handleIdx];
  const oldR = Math.hypot(h[0] - c[0], h[1] - c[1]);
  if (oldR === 0) return [[p0[0], p0[1]], [p1[0], p1[1]]];
  const newR = Math.hypot(newPos[0] - c[0], newPos[1] - c[1]);
  const s = newR / oldR;
  return [
    [c[0] + (p0[0] - c[0]) * s, c[1] + (p0[1] - c[1]) * s],
    [c[0] + (p1[0] - c[0]) * s, c[1] + (p1[1] - c[1]) * s],
  ];
}

// Rotate the edge (both points) about the box centre by `deg`. -> [p0, p1].
export function rotateEdgeAboutCenter(p0, p1, deg) {
  const c = edgeBoxCenter(p0, p1);
  const rad = (deg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  const rot = ([x, y]) => {
    const dx = x - c[0];
    const dy = y - c[1];
    return [c[0] + dx * cos - dy * sin, c[1] + dx * sin + dy * cos];
  };
  return [rot(p0), rot(p1)];
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
