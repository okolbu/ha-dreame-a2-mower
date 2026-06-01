// Dreame A2 Mower — shared client-side map core
//
// Pure projection / icon-rotation math shared by the live-map card and the
// replay card. Loaded as an ES module by cards that import it, and also
// attached to window.DreameMapCore so non-module cards can reach the same
// functions.
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
// screen DOWN, matching the replay card's _projectPoint exactly. The byte
// heading H (deg, 0 = cloud +X axis) is the cloud-frame travel direction;
// for an up-pointing icon the CW-positive SVG rotation that aims it along
// travel is A = (270 - H) mod 360.

// Project a point given in METRES (cloud frame) to screen pixels.
// proj = { bx2_mm, by2_mm, pixel_size_mm, height_px }
// Matches dreame-mower-replay-card.js:_projectPoint exactly.
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

// Build the mower-icon SVG group. The <image> source art points UP; the
// caller rotates the <g> by iconRotation(...) about (0,0) and translates it to
// the projected screen position. Starts hidden until first positioned.
export function buildMowerIconSvg(iconUrl, sizePx) {
  const half = sizePx / 2;
  return (
    `<g id="mower" visibility="hidden">` +
    `<image href="${iconUrl}" width="${sizePx}" height="${sizePx}" ` +
    `x="${-half}" y="${-half}" />` +
    `</g>`
  );
}

if (typeof window !== "undefined") {
  window.DreameMapCore = { projectPoint, iconRotation, buildMowerIconSvg };
}
