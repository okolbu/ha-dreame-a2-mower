import assert from "node:assert";
import { gapBreakIndices, trailPathD }
  from "../../custom_components/dreame_a2_mower/www/_dreame-map-core.js";

// Snapshot rows are [x_m, y_m, heading|null, t]. gapBreakIndices flags the
// index that STARTS a new subpath (pen-up before it) whenever the time step
// from the previous point exceeds the threshold.

// Continuous capture (~5s cadence) -> no breaks.
const cont = [
  [0, 0, null, 1000],
  [1, 0, null, 1005],
  [2, 0, null, 1010],
  [3, 0, null, 1015],
];
const b0 = gapBreakIndices(cont, 30);
assert.strictEqual(b0.size, 0, "continuous trail has no breaks");

// A downtime gap (HA restart: 1015 -> 1080) breaks the path at the rejoining point.
const gap = [
  [0, 0, null, 1000],
  [1, 0, null, 1005],
  [5, 0, null, 1080],   // 75s later -> break here
  [6, 0, null, 1085],
];
const b1 = gapBreakIndices(gap, 30);
assert.ok(b1.has(2), "gap flags the rejoining index");
assert.strictEqual(b1.size, 1, "exactly one break for one gap");

// Null timestamps never trigger a break (can't measure the step).
const nulls = [
  [0, 0, null, null],
  [1, 0, null, null],
];
assert.strictEqual(gapBreakIndices(nulls, 30).size, 0, "null t -> no break");

// trailPathD: one continuous subpath -> exactly one moveto.
const pts = [[10, 10], [20, 20], [30, 30]];
const dCont = trailPathD(pts, new Set());
assert.strictEqual((dCont.match(/M/g) || []).length, 1, "no breaks -> single subpath");
assert.strictEqual((dCont.match(/L/g) || []).length, 2, "no breaks -> two linetos");

// trailPathD: a break starts a second subpath (pen-up across the gap, no
// phantom line bridging it).
const dGap = trailPathD(pts, new Set([2]));
assert.strictEqual((dGap.match(/M/g) || []).length, 2, "break -> two subpaths");
assert.strictEqual((dGap.match(/L/g) || []).length, 1, "break -> one lineto");
// The point AT the break is the start of subpath 2 (a moveto), not a lineto.
assert.ok(/M 30.0 30.0/.test(dGap), "break point is a moveto");

console.log("OK");
