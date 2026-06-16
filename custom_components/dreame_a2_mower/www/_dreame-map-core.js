// Dreame A2 Mower — shared client-side map core
//
// Pure projection / icon-rotation math used by both the live-map card and the
// replay card. This file is an ES module (`export function`), so it can only be
// loaded with type="module"; a plain <script src> would throw a SyntaxError. It
// is ALSO attached to window.DreameMapCore so other ES module cards that load it
// as a side-effect import can reach the same functions without a named import.
// Both cards now import `projectPoint` directly from here — there is no longer a
// duplicate projection implementation anywhere.
//
// THE ICON-ROTATION CONVENTION IS CORPUS-VALIDATED.
// The byte-heading rotation formula below is character-equivalent to the
// Python reference in tests/protocol/test_icon_direction_corpus.py
// (_icon_rotation). That test pins the convention against ~43k straight-line
// real frames: median 1.35°, p90 7.23° error vs screen-space travel direction.
// DO NOT change the sign/offset of iconRotation's byte branch without
// re-running that corpus test — it is the authoritative gate for bug #3
// (the icon facing the wrong way).
//
// Geometry: the served base PNG is FLIP_TOP_BOTTOM'd. projectPoint maps
// cloud-mm -> screen-px so that cloud +X -> screen LEFT and cloud +Y ->
// screen DOWN. Both the live-map and replay cards call this single function.
// The byte heading H (deg, 0 = cloud +X axis) is the cloud-frame travel
// direction;
// for an up-pointing icon the CW-positive SVG rotation that aims it along
// travel is A = (270 - H) mod 360.

// Project a point given in METRES (cloud frame) to screen pixels.
// proj = { bx2_mm, by2_mm, pixel_size_mm, height_px }
// The SOLE projection implementation — both bundled cards import it.
// The Python server render uses the matching formula (map_render._geometry
// _cloud_to_px + the height_px flip); tests/www/test_projection_parity.py
// pins JS↔Python agreement within 1e-6 px.
export function projectPoint(x_m, y_m, proj) {
  const px = (proj.bx2_mm - x_m * 1000) / proj.pixel_size_mm;
  const py =
    proj.height_px - (proj.by2_mm - y_m * 1000) / proj.pixel_size_mm;
  return [px, py];
}

// Icon rotation (degrees, CW-positive in y-down screen space) for an icon
// whose source art points UP (screen -y).
//
//  - If headingDeg is a number (byte heading available): return the
//    corpus-validated (270 - H) mod 360. (Character-equivalent to the Python
//    _icon_rotation; see module header.)
//  - Else if prev+cur screen points are given and the move is > ~1px: derive
//    the rotation from the screen displacement vector (vector fallback). For a
//    straight move this returns the same rotation as the byte branch — proven
//    in test_vector_fallback_agrees_with_byte_branch.
//  - Else: return null (caller keeps the last angle).
export function iconRotation(headingDeg, prevScreenXY, curScreenXY) {
  if (headingDeg !== null && headingDeg !== undefined && !Number.isNaN(headingDeg)) {
    // VALIDATED byte branch — keep character-equivalent to the Python mirror.
    return ((270 - headingDeg) % 360 + 360) % 360;
  }
  if (prevScreenXY && curScreenXY) {
    const dpx = curScreenXY[0] - prevScreenXY[0];
    const dpy = curScreenXY[1] - prevScreenXY[1];
    if (Math.hypot(dpx, dpy) > 1) {
      // Vector fallback: atan2(dpy, dpx) is the screen travel angle
      // (CW-positive, y-down); +90 maps it to the up-art SVG rotation.
      const deg = (Math.atan2(dpy, dpx) * 180) / Math.PI + 90;
      return ((deg % 360) + 360) % 360;
    }
  }
  return null;
}

// WiFi heatmap colour gradient — character-equivalent mirror of
// wifi_map_render.py:_rssi_to_rgb. Returns { r, g, b } for a data cell or
// null for the no-data sentinel (rssi === 1). The card supplies translucency
// via the overlay layer's config opacity, so alpha is NOT mirrored here.
// THE GRADIENT CONTRACT IS PINNED by tests/protocol/test_wifi_gradient_contract.py
// — do not change the channel math without re-running it.
export const WIFI_STRONGEST = -50; // dBm -> full green
export const WIFI_WEAKEST = -99;   // dBm -> full red
export function rssiToRgb(rssi) {
  if (rssi === 1) return null; // no-data sentinel
  let n = (rssi - WIFI_WEAKEST) / (WIFI_STRONGEST - WIFI_WEAKEST);
  n = Math.max(0, Math.min(1, n));
  let r;
  let g;
  if (n < 0.5) {
    r = 255;
    g = Math.round(n * 2 * 255);
  } else {
    r = Math.round((1 - n) * 2 * 255);
    g = 255;
  }
  return { r, g, b: 0 };
}

// Cache-bust identity for the live-map WiFi overlay <g>. The card only
// re-renders the overlay rects when this key changes, so it MUST capture
// everything that affects what/where they draw:
//   - map identity (mapId): two maps whose heatmaps share grid geometry would
//     otherwise collide on a geometry-only key, so switching maps left the prior
//     map's rects on the canvas ("showing map2 blocks after switching to map1").
//   - projection (proj): the rects are positioned via projectPoint(...,proj);
//     a projection change must force a re-render or the overlay draws at the old
//     map's scale ("overlay scaled to map1 on a map2 background").
//   - overlay geometry/length: catches same-map heatmap regeneration.
// Returns null for an absent / no-data overlay so the caller can clear the <g>
// and reset its stored key.
export function wifiOverlayKey(overlay, mapId, proj) {
  if (!overlay || !Array.isArray(overlay.data)) return null;
  const p = proj
    ? `${proj.bx2_mm}/${proj.by2_mm}/${proj.pixel_size_mm}/${proj.height_px}`
    : "noproj";
  const m = mapId == null ? "?" : mapId;
  return (
    `m${m}|${overlay.width}x${overlay.height}` +
    `@${overlay.start_x_m},${overlay.start_y_m}:${overlay.data.length}|${p}`
  );
}

// Trail gap-splitting for the cold-start backfill. A snapshot row is
// [x_m, y_m, heading|null, t]; the mower keeps moving while the integration is
// down (HA restart / disabled), so two consecutive captured points can straddle
// a real gap. Drawing one continuous polyline would bridge that gap with a
// phantom mow-line. gapBreakIndices returns the set of indices that START a new
// subpath (pen-up before them) — any step whose elapsed time exceeds
// gapSeconds. A stationary pause (deduped, same position either side) also trips
// this, but the resulting break is zero-length, so it's harmless. Null
// timestamps can't be measured and never break.
export function gapBreakIndices(snap, gapSeconds) {
  const breaks = new Set();
  let prevT = null;
  for (let i = 0; i < snap.length; i += 1) {
    const t = snap[i][3];
    if (prevT != null && t != null && t - prevT > gapSeconds) breaks.add(i);
    prevT = t;
  }
  return breaks;
}

// Build an SVG path `d` from projected [x,y] points, starting a fresh subpath
// (moveto) at index 0 and at every index in `breaks` (a Set). Everything else
// is a lineto. With an empty `breaks` this is a single continuous polyline.
export function trailPathD(points, breaks) {
  let d = "";
  for (let i = 0; i < points.length; i += 1) {
    const q = points[i];
    const cmd = i === 0 || (breaks && breaks.has(i)) ? "M" : "L";
    d += `${i ? " " : ""}${cmd} ${q[0].toFixed(1)} ${q[1].toFixed(1)}`;
  }
  return d;
}

// Build the mower-icon SVG group. The caller rotates the <g> by
// iconRotation(...) about (0,0) and translates it to the projected screen
// position. Starts hidden until first positioned.
//
// ART-ORIENTATION COMPENSATION (ICON_ART_FORWARD_DEG):
// iconRotation assumes the art's FORWARD points screen-UP (-y). The shipped
// mower-icon.png is authored with its forward pointing LEFT (-x) — front
// (lidar) at screen-left, red lid-lift at screen-right. Measured render error
// was a constant 90deg anticlockwise on every replay (and live). We correct it
// HERE, at the art layer, by pre-rotating the <image> +90deg (clockwise) about
// the icon centre so its forward becomes screen-UP — keeping iconRotation the
// pure, corpus-validated heading->angle function (test unchanged). If a future
// icon asset is re-authored pointing up, set this to 0.
export const ICON_ART_FORWARD_DEG = 90;
export function buildMowerIconSvg(iconUrl, sizePx) {
  const half = sizePx / 2;
  // Escape double-quotes in the URL so it can't break out of the href="" attr
  // (this string is inserted via innerHTML by the cards). In practice iconUrl
  // is a hass static path, but the util shouldn't assume that.
  const safeUrl = String(iconUrl).replace(/"/g, "&quot;");
  return (
    `<g id="mower" visibility="hidden">` +
    `<image href="${safeUrl}" width="${sizePx}" height="${sizePx}" ` +
    `x="${-half}" y="${-half}" transform="rotate(${ICON_ART_FORWARD_DEG})" />` +
    `</g>`
  );
}

if (typeof window !== "undefined") {
  window.DreameMapCore = {
    projectPoint,
    iconRotation,
    gapBreakIndices,
    trailPathD,
    buildMowerIconSvg,
    ICON_ART_FORWARD_DEG,
    rssiToRgb,
    WIFI_STRONGEST,
    WIFI_WEAKEST,
  };
}
