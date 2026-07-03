"""Decoded cloud-map geometry dataclasses for the Dreame g2408 mower.

The single output of :func:`.parse.parse_cloud_map` is :class:`MapData`. These
are pure data containers — no rotation / reflection / pixel math lives here
(that is the render-side ``map_render`` presentation step). See the module
docstrings and ``docs/research/cloud-map-geometry.md``.
"""

from __future__ import annotations

from dataclasses import dataclass


# Millimetres from mower-nose-at-dock to physical charger centre.
# Empirically tuned against the app rendering (2026-04-19).
CHARGER_OFFSET_MM: int = 800

# Cloud MAP grid resolution.
GRID_SIZE_MM: int = 50


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExclusionZone:
    """A single exclusion / forbidden area polygon in *post-rotation cloud* mm.

    ``points`` contains the polygon corners after rotating around the polygon
    centroid by ``-angle`` (angle negated to match app rendering handedness),
    in cloud-frame millimetres.  This is the SAME frame ``points_m`` is in
    (×1000).  The midline reflection that aligns these to the flipped pixel
    frame is applied at RENDER time by the ``map_render`` presentation step
    (``_zone_point_to_px``), not baked in here — so the decoder carries one
    cloud frame.  (P3a transform-move, 2026-06-14.)

    ``subtype`` is one of:

    - ``None`` — classic no-go / forbidden (red in app)
    - ``"ignore"`` — Designated Ignore Obstacle zone (green in app)

    Spots used to live here too (subtype="spot") but are now their own
    dataclass (`SpotZone`) so the user can target individual spots by
    cloud-provided id+name from the UI.
    """

    points: tuple[tuple[float, float], ...]
    subtype: str | None = None
    obj_id: int | None = None
    # Edit-frame polygon corners in METERS (un-reflected cloud frame:
    # rotate(path, -angle)/1000). These feed the map-editor card's
    # projectPoint directly. Post P3a transform-move ``points`` (above) is
    # in the SAME frame ×1000 — render applies the reflection. See
    # docs/research/wire-captures/map-edit-frame-verification-2026-06-12.md.
    points_m: tuple[tuple[float, float], ...] = ()
    # Cloud ``shapeType`` read-side enum (0=area, 1=line, 2=rotated-rect,
    # 3=circle, 5=point, 7=spot, 9=square, 12=circle, 13=heart, 14=triangle,
    # 15=teardrop, 16=mushroom, 17=cloud, 18=rainbow). For DECORATIVE types
    # (>=9, in map_render._shape_masks.DECORATIVE_SHAPE_TYPES) the 2 ``points``
    # are the raw axis-aligned bbox corners (UN-rotated) and ``angle`` carries
    # the raw cloud angle so the render can stamp a silhouette rotated by it.
    # For non-decorative types ``points`` are centroid-rotated as before and
    # ``angle`` is informational. See cloud-map-geometry.md §4.1.
    shape_type: int | None = None
    angle: float | None = None


@dataclass(frozen=True, slots=True)
class MowingZone:
    """Mowing area (lawn zone) as described by the cloud MAP.* JSON.

    ``path`` is the raw polygon in cloud-frame mm (not yet reflected).
    Pixel-mask painting applies the ``(bx2-x)/grid, (by2-y)/grid``
    formula; the renderer uses the reflected midline coords.

    ``area_m2`` is the cloud-supplied ``area`` value (already in
    square metres). May be 0.0 when the cloud omits it.
    """

    zone_id: int
    name: str
    path: tuple[tuple[float, float], ...]  # cloud-frame mm
    area_m2: float = 0.0


@dataclass(frozen=True, slots=True)
class SpotZone:
    """A single spot-mowing area with cloud id+name.

    ``points`` is in post-rotation cloud-frame mm (same frame as
    ExclusionZone.points; render applies the midline reflection). The
    ``spot_id`` is the integer key from the cloud's ``spotAreas[entry][0]``
    and is what the s2.50 op=103 spot-mow task expects in
    ``d.area: [spot_id, ...]``.
    """

    spot_id: int
    name: str
    points: tuple[tuple[float, float], ...]
    area_m2: float = 0.0
    # Edit-frame polygon corners in METERS (÷1000 of ``points``, un-reflected
    # cloud frame) — feeds the map-editor card's editable_objects directly,
    # exactly like ExclusionZone.points_m. The o=214 spot create/edit wire
    # takes these 4 corners back in metres.
    points_m: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class MaintenancePoint:
    """Maintenance / clean-point marker in raw cloud-frame mm.

    Coordinates are kept in the cloud frame so go-to services can pass
    them straight to ``device.go_to(x_mm, y_mm)`` without re-reflecting.
    """

    point_id: int
    x_mm: float
    y_mm: float


@dataclass(frozen=True, slots=True)
class PatrolPoint:
    """Cruise / patrol point in raw cloud-frame mm.

    From the MAP blob key ``cruisePoints`` (type=8) — distinct from
    maintenance ``cleanPoints`` (type=6). Coordinates kept in the cloud
    frame, mirroring MaintenancePoint.
    """

    point_id: int
    x_mm: float
    y_mm: float


@dataclass(frozen=True, slots=True)
class NavPath:
    """A connecting "navigation path" rendered as a gray polyline in the
    Dreame app. Connects two map regions (e.g. dock area to a remote
    mowing zone). Decoded from the cloud `paths` key.

    `path_type` semantics undecoded (observed `0` in 2026-05-07 capture).
    """

    path_id: int
    path: tuple[tuple[float, float], ...]  # cloud-frame mm
    path_type: int = 0


@dataclass(frozen=True, slots=True)
class MapData:
    """Decoded base-map geometry from the Dreame cloud ``MAP.*`` keys.

    This dataclass is the single output of :func:`parse_cloud_map`.  It
    carries all geometric fields required by the F2.8.2 renderer and
    future overlay work.  It does **not** contain a pixel array —
    computing the pixel mask is renderer work.

    Field notes
    -----------
    ``md5`` — stable content hash (not the cloud's ``md5sum`` field,
    which is volatile).  Used for deduplication: if ``md5`` matches the
    previously decoded map the coordinator can skip a re-render.

    ``dock_xy`` — charger position in post-rotation cloud-frame mm
    (``CHARGER_OFFSET_MM`` along the +X axis; ``(800, 0)``).  Render applies
    the midline reflection (same as exclusion/spot points).
    ``None`` when the boundary is zero-sized (empty/error response).

    ``boundary_polygon`` — axis-aligned bounding box of the lawn
    expressed as four ``(x, y)`` corners in cloud-frame mm:
    ``(bx1,by1), (bx2,by1), (bx2,by2), (bx1,by2)``.  Primarily
    informational; the renderer sizes its canvas from ``width_px`` /
    ``height_px``.

    ``exclusion_zones`` — polygons in post-rotation cloud-frame mm; the
    renderer applies the midline reflection (presentation step) before
    painting.

    ``mowing_zones`` — raw cloud-frame polygons; the renderer's pixel
    mask logic applies its own ``(bx2-x)/grid`` flip when painting.

    ``contour_paths`` — closed contour polylines in cloud-frame mm.
    Rendered as ``WALL`` outlines on the pixel mask.

    ``maintenance_points`` — user-placed go-to markers; raw cloud-frame
    mm so go-to services need no extra transform.

    ``cloud_x_reflect``, ``cloud_y_reflect`` — midline values
    ``bx1+bx2`` and ``by1+by2`` (mm).  Trail / overlay consumers use
    these to convert raw cloud coords to renderer coords without knowing
    the bbox.

    ``total_area_m2`` — lawn area reported by the cloud (may be 0.0 if
    absent from the payload).
    """

    # --- deduplication ---
    md5: str

    # --- canvas dimensions ---
    width_px: int
    height_px: int
    pixel_size_mm: float  # always GRID_SIZE_MM (50) for g2408

    # --- bounding box (cloud-frame mm) ---
    bx1: float
    by1: float
    bx2: float
    by2: float

    # --- midline reflections (bx1+bx2, by1+by2) ---
    cloud_x_reflect: float
    cloud_y_reflect: float

    # --- map rotation (always 0 for g2408 cloud maps) ---
    rotation_deg: float

    # --- geometry ---
    boundary_polygon: tuple[tuple[float, float], ...]
    mowing_zones: tuple[MowingZone, ...]
    exclusion_zones: tuple[ExclusionZone, ...]
    spot_zones: tuple[SpotZone, ...]
    contour_paths: tuple[tuple[tuple[float, float], ...], ...]
    # Contour IDs in cloud-key order, parallel to ``contour_paths``.
    # Each entry is the 2-int composite identifier from the cloud's
    # ``contours.value`` map keying — e.g. ``(1, 0)`` for "the outer
    # perimeter of zone-region 1", ``(1, 1)`` for an inner-seam contour,
    # ``(2, 0)`` for "outer perimeter of region 2" on multi-zone lawns.
    # Used by the edge-mow action dispatcher to default to "all outer
    # perimeters" (entries with second-int = 0) when no explicit
    # contour selection is given. See docs/research/g2408-protocol.md
    # §4.6 for the wire-format finding (2026-05-05 live runs).
    available_contour_ids: tuple[tuple[int, int], ...]
    maintenance_points: tuple[MaintenancePoint, ...]

    # --- charger (post-rotation cloud-frame mm, +X offset; render reflects) ---
    dock_xy: tuple[float, float] | None

    # --- metadata ---
    total_area_m2: float = 0.0
    nav_paths: tuple[NavPath, ...] = ()

    # --- multi-map identity ---
    # Present in cloud responses that carry ``mapIndex`` (multi-map
    # accounts).  Single-map fixtures and older responses leave these at
    # their defaults (0 / None) so existing MapData() call-sites need no
    # changes.
    map_id: int = 0
    name: str | None = None
    # Patrol/cruise points (cloud key cruisePoints, type=8). Defaulted so
    # existing MapData() call-sites need no changes.
    patrol_points: tuple[PatrolPoint, ...] = ()
