import assert from "node:assert";
import { pixelToMeters, rectCorners, rotatePointsAroundCentroid, circleFromCenterEdge, shapeToPoints, pointerAngleAboutCentroid, resizeUniform,
  resizeRectCorner, orientedEdgeBox, edgeBoxCenter, resizeOrientedEdge, rotateEdgeAboutCenter }
  from "../../custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js";

function rightAngle(a, b, c) {
  // angle at b between b->a and b->c, returns dot (0 == right angle)
  const u = [a[0] - b[0], a[1] - b[1]];
  const v = [c[0] - b[0], c[1] - b[1]];
  return u[0] * v[0] + u[1] * v[1];
}

const proj = { bx2_mm: 10000, by2_mm: 6000, pixel_size_mm: 50, width_px: 400, height_px: 240 };

// round-trip: meters -> pixel (projectPoint formula) -> meters
const x_m = 2.5, y_m = -1.0;
const px = (proj.bx2_mm - x_m * 1000) / proj.pixel_size_mm;
const py = proj.height_px - (proj.by2_mm - y_m * 1000) / proj.pixel_size_mm;
const [rx, ry] = pixelToMeters(px, py, proj);
assert.ok(Math.abs(rx - x_m) < 1e-6 && Math.abs(ry - y_m) < 1e-6, "round-trip");

// rectCorners: 2 drag points -> 4 corners
const rc = rectCorners([1, 1], [3, 4]);
assert.strictEqual(rc.length, 4);

// rotate a 3m axis-aligned square by ~26.565deg reproduces a skewed square (edge len preserved)
const sq = [[-1.5, -1.5], [1.5, -1.5], [1.5, 1.5], [-1.5, 1.5]];
const rot = rotatePointsAroundCentroid(sq, 26.565);
const edge = Math.hypot(rot[1][0] - rot[0][0], rot[1][1] - rot[0][1]);
assert.ok(Math.abs(edge - 3.0) < 1e-3, "rotation preserves edge length");

// circleFromCenterEdge
const c = circleFromCenterEdge([0, 0], [3, 4]);
assert.ok(Math.abs(c.radius - 5) < 1e-9, "circle radius");

// shapeToPoints: circle -> 1 point + radius; line -> 2; square -> 4
assert.strictEqual(shapeToPoints("nogo", "circle", { center: [0, 0], edge: [3, 4] }).points.length, 1);
assert.strictEqual(shapeToPoints("nogo", "line", { a: [0, 0], b: [1, 1] }).points.length, 2);
// mow square -> 4 corners; curved mow shape -> 2-pt bbox
assert.strictEqual(shapeToPoints("mow", "square", { p0: [0, 0], p1: [3, 3] }).points.length, 4);
assert.strictEqual(shapeToPoints("mow", "heart", { p0: [0, 0], p1: [3, 3] }).points.length, 2);

// resizeUniform: dragging a unit-square corner to double its centroid-distance
// scales every corner 2x about the centroid (uniform, aspect preserved).
const usq = [[-1, -1], [1, -1], [1, 1], [-1, 1]]; // centroid (0,0), corner dist sqrt2
const grown = resizeUniform(usq, 2, [2, 2]); // corner 2 from (1,1) -> (2,2): 2x
assert.ok(Math.abs(grown[2][0] - 2) < 1e-9 && Math.abs(grown[2][1] - 2) < 1e-9, "resizeUniform 2x corner");
assert.ok(Math.abs(grown[0][0] - -2) < 1e-9 && Math.abs(grown[0][1] - -2) < 1e-9, "resizeUniform 2x opposite");

// pointerAngleAboutCentroid: degrees about centroid; a 90deg pointer sweep
// applied as a rotation delta turns a +x edge into a +y edge.
const sq2 = [[-1, -1], [1, -1], [1, 1], [-1, 1]]; // centroid (0,0)
assert.ok(Math.abs(pointerAngleAboutCentroid(sq2, [1, 0]) - 0) < 1e-9, "angle 0 on +x");
assert.ok(Math.abs(pointerAngleAboutCentroid(sq2, [0, 1]) - 90) < 1e-9, "angle 90 on +y");
const a0 = pointerAngleAboutCentroid(sq2, [2, 0]);
const a1 = pointerAngleAboutCentroid(sq2, [0, 2]);
const swept = rotatePointsAroundCentroid(sq2, a1 - a0);
assert.ok(Math.abs(swept[0][0] - 1) < 1e-9 && Math.abs(swept[0][1] - -1) < 1e-9, "90deg sweep rotates corner");

// resizeRectCorner: free-aspect resize of an axis-aligned rect, anchored opposite.
// Corners [(-2,-1),(2,-1),(2,1),(-2,1)] (w4 h2). Drag corner 2 (2,1) -> (4,3):
// anchor corner 0 (-2,-1) stays; dragged -> (4,3); stays axis-aligned rect.
const rr = resizeRectCorner([[-2, -1], [2, -1], [2, 1], [-2, 1]], 2, [4, 3]);
assert.ok(Math.abs(rr[0][0] - -2) < 1e-9 && Math.abs(rr[0][1] - -1) < 1e-9, "rectCorner anchor fixed");
assert.ok(Math.abs(rr[2][0] - 4) < 1e-9 && Math.abs(rr[2][1] - 3) < 1e-9, "rectCorner dragged = newPos");
assert.ok(Math.abs(rr[1][0] - 4) < 1e-9 && Math.abs(rr[1][1] - -1) < 1e-9, "rectCorner adj1 follows");
assert.ok(Math.abs(rr[3][0] - -2) < 1e-9 && Math.abs(rr[3][1] - 3) < 1e-9, "rectCorner adj2 follows");
// right angles preserved on a ROTATED rect (45deg)
const rotRect = rotatePointsAroundCentroid([[-2, -1], [2, -1], [2, 1], [-2, 1]], 45);
const rr2 = resizeRectCorner(rotRect, 1, [rotRect[1][0] + 0.5, rotRect[1][1] + 0.5]);
assert.ok(Math.abs(rightAngle(rr2[0], rr2[1], rr2[2])) < 1e-6, "rotated rectCorner keeps right angle");

// orientedEdgeBox: axis-aligned edge -> axis-aligned square box.
const box0 = orientedEdgeBox([0, 0], [2, 0]); // edge along +x, len 2
// perp = (-(0), 2) = (0,2): corners [(0,0),(2,0),(2,2),(0,2)] -> a 2x2 square
assert.ok(Math.abs(box0[2][0] - 2) < 1e-9 && Math.abs(box0[2][1] - 2) < 1e-9, "edgeBox axis-aligned");
assert.strictEqual(box0.length, 4);
// edge sides equal (square): |edge| == |perp side|
const eLen = Math.hypot(box0[1][0] - box0[0][0], box0[1][1] - box0[0][1]);
const pLen = Math.hypot(box0[3][0] - box0[0][0], box0[3][1] - box0[0][1]);
assert.ok(Math.abs(eLen - pLen) < 1e-9, "edgeBox is square");
// off-axis edge -> rotated box (a corner is not axis-aligned w.r.t. p0)
const box1 = orientedEdgeBox([0, 0], [2, 1]);
assert.ok(box1[2][0] !== box1[0][0] && box1[2][1] !== box1[0][1], "off-axis edge -> rotated box");

// edgeBoxCenter is the square's centre
const ec = edgeBoxCenter([0, 0], [2, 0]); // box (0,0)-(2,2) -> centre (1,1)
assert.ok(Math.abs(ec[0] - 1) < 1e-9 && Math.abs(ec[1] - 1) < 1e-9, "edgeBoxCenter");

// resizeOrientedEdge: doubling the dragged-corner distance doubles the edge (uniform).
const [np0, np1] = resizeOrientedEdge([0, 0], [2, 0], 1, [3, -1]); // drag corner1 (2,0) outward
const newELen = Math.hypot(np1[0] - np0[0], np1[1] - np0[1]);
assert.ok(newELen > 2, "resizeOrientedEdge grows edge");
// aspect stays square after resize
const nbox = orientedEdgeBox(np0, np1);
const ne = Math.hypot(nbox[1][0] - nbox[0][0], nbox[1][1] - nbox[0][1]);
const npp = Math.hypot(nbox[3][0] - nbox[0][0], nbox[3][1] - nbox[0][1]);
assert.ok(Math.abs(ne - npp) < 1e-9, "resizeOrientedEdge stays square");

// rotateEdgeAboutCenter: 90deg keeps edge length, rotates about box centre.
const [rp0, rp1] = rotateEdgeAboutCenter([0, 0], [2, 0], 90);
const rELen = Math.hypot(rp1[0] - rp0[0], rp1[1] - rp0[1]);
assert.ok(Math.abs(rELen - 2) < 1e-9, "rotateEdgeAboutCenter keeps edge length");
const rc2 = edgeBoxCenter(rp0, rp1);
assert.ok(Math.abs(rc2[0] - 1) < 1e-9 && Math.abs(rc2[1] - 1) < 1e-9, "rotateEdgeAboutCenter keeps centre");

console.log("OK");
