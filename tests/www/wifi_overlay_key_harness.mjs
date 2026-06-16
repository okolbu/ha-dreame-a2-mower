import assert from "node:assert";
import { wifiOverlayKey }
  from "../../custom_components/dreame_a2_mower/www/_dreame-map-core.js";

// wifiOverlayKey decides whether the live-map card re-renders the WiFi overlay
// <g>. The bug it guards against: two different active maps whose heatmaps share
// grid geometry (width/height/start/length) produced the SAME key, so switching
// maps skipped the re-render and left the prior map's RSSI rects on the canvas
// (drawn with the prior map's projection -> "showing map2 blocks" / "scaled to
// map1"). The key MUST therefore vary with map identity AND projection, not just
// overlay geometry.

const overlayA = {
  width: 10, height: 12, start_x_m: 1.0, start_y_m: 2.0,
  resolution_m: 0.5, data: new Array(120).fill(-55),
};
// Same grid geometry as A (the realistic collision case) but a DIFFERENT map.
const overlayB = {
  width: 10, height: 12, start_x_m: 1.0, start_y_m: 2.0,
  resolution_m: 0.5, data: new Array(120).fill(-70),
};

const projMap1 = { bx2_mm: 20000, by2_mm: 21000, pixel_size_mm: 50, height_px: 420 };
const projMap2 = { bx2_mm: 35000, by2_mm: 18000, pixel_size_mm: 40, height_px: 450 };

// (1) Identical geometry, DIFFERENT map_id -> keys MUST differ (obs1: ON, map2->map1
//     left map2's blocks because the geometry-only key collided).
assert.notStrictEqual(
  wifiOverlayKey(overlayA, 1, projMap1),
  wifiOverlayKey(overlayB, 2, projMap2),
  "different maps must yield different keys (geometry collision must not hide the switch)",
);

// (2) Same overlay + same map_id but DIFFERENT projection -> keys MUST differ
//     (obs2: overlay drawn with a stale projection -> wrong scale).
assert.notStrictEqual(
  wifiOverlayKey(overlayA, 1, projMap1),
  wifiOverlayKey(overlayA, 1, projMap2),
  "a projection change must force a re-render so the overlay isn't drawn at the old scale",
);

// (3) Identical map_id + overlay + projection -> SAME key (no needless re-render).
assert.strictEqual(
  wifiOverlayKey(overlayA, 1, projMap1),
  wifiOverlayKey(overlayA, 1, projMap1),
  "stable inputs must yield a stable key",
);

// (4) Absent / no-data overlay -> null (caller clears the <g> and resets the key).
assert.strictEqual(wifiOverlayKey(null, 1, projMap1), null, "null overlay -> null key");
assert.strictEqual(
  wifiOverlayKey({ width: 2, height: 2 }, 1, projMap1), null,
  "overlay without a data array -> null key",
);

console.log("OK");
