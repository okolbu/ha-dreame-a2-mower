"""Decoded cloud-map geometry dataclasses for the Dreame g2408 mower.

The single output of :func:`.parse.parse_cloud_map` is :class:`MapData`. These
are pure data containers in ONE frame: **raw cloud-frame millimetres**, exactly
as the cloud supplied them, plus ``angle`` / ``shape_type`` verbatim. No
rotation, reflection, or pixel math is baked into any coordinate here — that is
the render-side ``map_render`` presentation step (``map_render/_geometry.py``:
``build_projection`` + ``_zone_point_to_px``). See
``docs/research/cloud-map-geometry.md`` and CLAUDE.md
§ "Decode->render zone frame contract".

Coordinate conventions
----------------------
- Cloud units: millimetres. Origin ``(0, 0)`` = mower nose at dock entry.
- ``+X`` = toward the house (docking direction).
- Rendering flips both axes: ``px = (bx2 - x)/grid``, ``py = (by2 - y)/grid``.
- Zone / dock overlay points are aligned to that flipped pixel frame by the
  render's midline reflection ``(bx1+bx2 - x, by1+by2 - y)``; the decoder never
  applies it. See §3.3 of the geometry doc.
"""

from __future__ import annotations

from dataclasses import dataclass


# Millimetres from mower-nose-at-dock to physical charger centre.
# Empirically tuned against the app rendering (2026-04-19).
CHARGER_OFFSET_MM: int = 800

# Cloud MAP grid resolution.
GRID_SIZE_MM: int = 50


# ---------------------------------------------------------------------------
# Unified polygonal zone (exclusion / spot) — T2-17 "one Zone(kind=…)".
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Zone:
    """A single polygonal map object (no-go / ignore / spot) in RAW cloud mm.

    Collapses the old ``ExclusionZone`` + ``SpotZone`` pair (T2-17). ``kind``
    distinguishes them; per-``kind`` fields default to their empty value.

    ``points`` are the polygon corners **exactly as the cloud supplied them**
    (raw cloud-frame millimetres) — the per-centroid rotation the app applies
    (``-angle``) and the midline reflection are BOTH deferred to the render
    presentation step. This is the single-frame contract (the ``points`` /
    ``points_m`` stored twin is GONE: the metre-frame edit polygon is derived
    at the ``editable_objects`` boundary as ``rotate(points, -angle)/1000``).

    ``kind`` values:

    - ``"exclusion"`` — forbidden / ignore area. ``subtype`` is ``None`` (classic
      red no-go) or ``"ignore"`` (designated ignore-obstacle, green). ``obj_id``
      is the cloud object id; ``shape_type`` is the read-side ``shapeType`` enum
      (see ``protocol/map/shapes.py`` + ``inventory.yaml`` § shapeType). For a
      DECORATIVE ``shape_type`` (in ``DECORATIVE_SHAPE_TYPES``) the 2 ``points``
      are the raw axis-aligned bbox corners and ``angle`` is the raw cloud angle
      the render stamps the silhouette by.
    - ``"spot"`` — spot-mow area. ``obj_id`` is the spot id (the s2.50 op=103
      ``d.area`` key); ``name`` / ``area_m2`` carry the cloud label + size.
    """

    points: tuple[tuple[float, float], ...]
    # ``kind`` defaults to ``"exclusion"`` (the dominant case) so the legacy
    # ``ExclusionZone(points=…)`` construction path keeps working via the alias;
    # spot zones pass ``kind="spot"`` explicitly.
    kind: str = "exclusion"
    subtype: str | None = None
    obj_id: int | None = None
    shape_type: int | None = None
    angle: float | None = None
    name: str | None = None
    area_m2: float = 0.0

    @property
    def spot_id(self) -> int | None:
        """Back-compat accessor — spot zones key on ``obj_id``."""
        return self.obj_id


# Backward-compatible names for the ~29 deep-import sites + isinstance checks
# (their import rewrite is P3.10). Both resolve to the unified ``Zone`` — an
# ``isinstance(z, ExclusionZone)`` on any zone is now ``isinstance(z, Zone)``.
# New construction uses ``Zone(kind=…)``.
ExclusionZone = Zone
SpotZone = Zone


@dataclass(frozen=True, slots=True)
class MowingZone:
    """Mowing area (lawn zone) from the cloud MAP.* JSON, in RAW cloud mm.

    NOT folded into :class:`Zone` (T2-17): mowing zones render in the plain
    cloud->pixel frame (``_cloud_to_px``, no midline reflection), carry a
    firmware-validated ``zone_id`` (1–62) rather than an ``obj_id``, and have no
    ``angle`` / ``shape_type`` — a different render path and identity space, so
    unifying would only push a ``kind`` branch into every consumer.

    ``area_m2`` is the cloud-supplied ``area`` (square metres; may be 0.0).
    """

    zone_id: int
    name: str
    path: tuple[tuple[float, float], ...]  # cloud-frame mm
    area_m2: float = 0.0


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

    Single output of :func:`.parse.parse_cloud_map`. Carries the geometry the
    F2.8.2 renderer + overlays need — no pixel array (that is renderer work).

    All polygon / point coordinates are RAW cloud-frame millimetres (see the
    module docstring). The canvas extents (``bx1``..``by2``, ``width_px`` /
    ``height_px``, ``cloud_x_reflect`` / ``cloud_y_reflect``, ``dock_xy``,
    ``boundary_polygon``) are the lawn bbox EXPANDED to cover every zone corner
    after the app's per-centroid rotation — a pure cloud-frame geometry
    derivation (``protocol/map/geom.py``: ``derive_canvas``); the render's
    ``build_projection`` recomputes the identical values from these raw fields.
    ``md5`` is a stable content hash for render dedup (not the volatile cloud
    ``md5sum``).
    """

    # --- deduplication ---
    md5: str

    # --- canvas dimensions ---
    width_px: int
    height_px: int
    pixel_size_mm: float  # always GRID_SIZE_MM (50) for g2408

    # --- bounding box (cloud-frame mm; expanded over rotated zone corners) ---
    bx1: float
    by1: float
    bx2: float
    by2: float

    # --- midline reflections (bx1+bx2, by1+by2) ---
    cloud_x_reflect: float
    cloud_y_reflect: float

    # --- map rotation (always 0 for g2408 cloud maps) ---
    rotation_deg: float

    # --- geometry (all RAW cloud-frame mm) ---
    boundary_polygon: tuple[tuple[float, float], ...]
    mowing_zones: tuple[MowingZone, ...]
    exclusion_zones: tuple[Zone, ...]
    spot_zones: tuple[Zone, ...]
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

    # --- charger (raw cloud-frame mm, +X offset; render reflects) ---
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
