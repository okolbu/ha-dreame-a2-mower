import assert from "node:assert";
import { pixelToMeters, rectCorners, rotatePointsAroundCentroid, circleFromCenterEdge, shapeToPoints }
  from "../../custom_components/dreame_a2_mower/www/_dreame-map-edit-geom.js";

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

console.log("OK");
