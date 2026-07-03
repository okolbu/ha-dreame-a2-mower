"""Cloud-JSON map decoder for the Dreame g2408 mower.

Parses the cloud ``MAP.0`` … ``MAP.27`` batch (joined + JSON-decoded) into a
typed :class:`.types.MapData`. Extracts geometry only — no pixel array (that is
:mod:`map_render`). Cloud units are millimetres; origin ``(0,0)`` = mower nose
at dock entry.

Lifted from legacy ``dreame/device.py::_build_map_from_cloud_data``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from typing import Any

from .geom import derive_canvas, rotate_zone_points
from .types import (
    GRID_SIZE_MM,
    MaintenancePoint,
    MapData,
    MowingZone,
    NavPath,
    PatrolPoint,
    Zone,
)

_LOGGER = logging.getLogger(__name__)


def _warn_shape_mismatch(
    field_name: str,
    expected: str,
    actual: Any,
    context: str = "",
) -> None:
    """Log a structured warning when a cloud JSON field has an unexpected
    shape. Helps debug 'silent zero' decode bugs (a92's `paths` empty
    decode was hidden behind silent isinstance falls).

    Always WARN-level — these are signals the firmware sent something
    we didn't expect, and we want them visible in `system_log/list`
    rather than buried at DEBUG.

    The same helper should be adopted by boundaries, mowing-zones, and
    contour decoders in follow-up PRs to guard against the same class of
    silent-empty bugs.
    """
    actual_type = type(actual).__name__
    actual_preview = repr(actual)[:200]
    suffix = f" ({context})" if context else ""
    _LOGGER.warning(
        "[shape-mismatch] %s: expected %s, got %s — %s%s",
        field_name, expected, actual_type, actual_preview, suffix,
    )


# ---------------------------------------------------------------------------
# Section helpers (called by parse_cloud_map)
# ---------------------------------------------------------------------------


def _collect_exclusion_entries(
    entries_wrapper: Any,
    subtype: str | None,
) -> list[
    tuple[
        int | None,
        tuple[tuple[float, float], ...],
        str | None,
        int | None,
        float | None,
    ]
]:
    """Parse one exclusion-zone wrapper dict into RAW-frame entries.

    Returns a list of ``(obj_id, raw_points, subtype, shape_type, raw_angle)``
    5-tuples, where ``raw_points`` are the polygon corners exactly as the cloud
    supplied them (raw cloud-frame mm ``(x, y)`` tuples) — NO rotation baked in
    (single-frame contract; the app's ``-angle`` per-centroid rotation is a
    render-time transform, ``geom.rotate_zone_points``).  ``obj_id`` is the
    cloud object id from ``entry[0]`` (or ``None`` for the id-less dict form).

    ``shape_type`` is the cloud ``shapeType`` value (or ``None``); ``raw_angle``
    the raw cloud angle.  For DECORATIVE shapeTypes the 2 points are the raw
    bbox corners the render stamps a silhouette on (see ``protocol/map/shapes``).
    """
    result: list[
        tuple[
            int | None,
            tuple[tuple[float, float], ...],
            str | None,
            int | None,
            float | None,
        ]
    ] = []
    entries = entries_wrapper.get("value", []) if isinstance(entries_wrapper, dict) else []
    for entry in entries:
        obj_id: int | None = None
        if isinstance(entry, list) and len(entry) >= 2:
            try:
                # -1 is the create-payload sentinel (server assigns the real
                # id); never surface it as a deletable target.
                obj_id = v if (v := int(entry[0])) >= 0 else None
            except (TypeError, ValueError):
                obj_id = None
            zdata = entry[1]
        elif isinstance(entry, dict):
            zdata = entry
        else:
            continue
        path = zdata.get("path", [])
        if not path:
            continue
        raw_angle = zdata.get("angle")
        shape_type: int | None
        try:
            shape_type = int(st) if (st := zdata.get("shapeType")) is not None else None
        except (TypeError, ValueError):
            shape_type = None
        raw_points = tuple(
            (float(pt["x"]), float(pt["y"]))
            for pt in path
            if isinstance(pt, dict) and "x" in pt and "y" in pt
        )
        if not raw_points:
            continue
        result.append((obj_id, raw_points, subtype, shape_type, raw_angle))
    return result


def _collect_spot_entries(
    entries_wrapper: Any,
) -> list[tuple[int, str, tuple[tuple[float, float], ...], float, float | None]]:
    """Parse the ``spotAreas`` wrapper dict into RAW-frame spot entries.

    Returns ``(spot_id, name, raw_points, area_m2, raw_angle)`` 5-tuples — the
    polygon corners are the cloud's raw cloud-frame mm (no rotation baked in;
    the render applies ``-angle`` like an exclusion polygon).
    """
    result: list[tuple[int, str, tuple[tuple[float, float], ...], float, float | None]] = []
    entries = entries_wrapper.get("value", []) if isinstance(entries_wrapper, dict) else []
    for entry in entries:
        if isinstance(entry, list) and len(entry) >= 2:
            spot_id_raw = entry[0]
            zdata = entry[1]
        elif isinstance(entry, dict):
            spot_id_raw = entry.get("id", 0)
            zdata = entry
        else:
            continue
        path = zdata.get("path", [])
        if not path:
            continue
        try:
            spot_id = int(spot_id_raw)
        except (TypeError, ValueError):
            continue
        name = str(zdata.get("name", "") or f"Spot {spot_id}")
        try:
            area_m2 = float(zdata.get("area", 0.0) or 0.0)
        except (TypeError, ValueError):
            area_m2 = 0.0
        raw_angle = zdata.get("angle")
        raw_points = tuple(
            (float(pt["x"]), float(pt["y"]))
            for pt in path
            if isinstance(pt, dict) and "x" in pt and "y" in pt
        )
        if not raw_points:
            continue
        result.append((spot_id, name, raw_points, area_m2, raw_angle))
    return result


def _parse_mowing_zones(cloud_response: dict[str, Any]) -> list[MowingZone]:
    """Parse ``mowingAreas`` from *cloud_response* into :class:`MowingZone` objects.

    Coordinates are kept in cloud-frame mm; the renderer applies its own
    ``(bx2-x)/grid`` flip when painting the pixel mask.
    Valid zone_ids are 1–62 (firmware-imposed range).
    """
    mowing_out: list[MowingZone] = []
    mowing_areas = cloud_response.get("mowingAreas", {})
    entries = mowing_areas.get("value", []) if isinstance(mowing_areas, dict) else []
    for entry in entries:
        if isinstance(entry, list) and len(entry) >= 2:
            zone_id = entry[0]
            zdata = entry[1]
        elif isinstance(entry, dict):
            zone_id = entry.get("id", 1)
            zdata = entry
        else:
            continue
        path = zdata.get("path", [])
        name = zdata.get("name", f"Zone {zone_id}")
        if not path:
            continue
        try:
            zone_id_int = int(zone_id)
        except (TypeError, ValueError):
            continue
        if zone_id_int < 1 or zone_id_int > 62:
            continue
        try:
            area_m2 = float(zdata.get("area", 0.0) or 0.0)
        except (TypeError, ValueError):
            area_m2 = 0.0
        pts = tuple((float(pt["x"]), float(pt["y"])) for pt in path if "x" in pt and "y" in pt)
        if len(pts) >= 3:
            mowing_out.append(
                MowingZone(zone_id=zone_id_int, name=name, path=pts, area_m2=area_m2)
            )
    return mowing_out


def _parse_contours(
    cloud_response: dict[str, Any],
) -> tuple[list[tuple[tuple[float, float], ...]], list[tuple[int, int]]]:
    """Parse ``contours`` from *cloud_response*.

    Returns a parallel pair of lists:
    - ``contour_paths``: closed polylines in cloud-frame mm.
    - ``contour_ids``: 2-int composite IDs ``(m, c)`` aligned with the paths.

    Each cloud entry is keyed by a 2-int composite ID (e.g. ``[1, 0]``,
    ``[1, 1]``, ``[2, 0]``) which the edge-mow wire format passes directly
    in ``d.edge: [[m, c], ...]``.  Both list/tuple and ``"m,c"`` string
    key forms are handled.  Missing or unparseable keys are synthesised as
    ``(1, index)`` so the parallel arrays stay aligned.
    """
    contour_out: list[tuple[tuple[float, float], ...]] = []
    contour_ids_out: list[tuple[int, int]] = []
    contours_raw = cloud_response.get("contours", {})
    c_entries = contours_raw.get("value", []) if isinstance(contours_raw, dict) else []
    for entry in c_entries:
        cid: tuple[int, int] | None = None
        if isinstance(entry, list) and len(entry) >= 2:
            raw_key = entry[0]
            zdata = entry[1]
            # Cloud key is typically a 2-element list/tuple [m, c]; some
            # firmware variants emit it as a "m,c" string. Both forms
            # collapse to a (m, c) int tuple here.
            if isinstance(raw_key, (list, tuple)) and len(raw_key) == 2:
                try:
                    cid = (int(raw_key[0]), int(raw_key[1]))
                except (TypeError, ValueError):
                    cid = None
            elif isinstance(raw_key, str):
                parts = [p.strip() for p in raw_key.split(",")]
                if len(parts) == 2:
                    try:
                        cid = (int(parts[0]), int(parts[1]))
                    except ValueError:
                        cid = None
        elif isinstance(entry, dict):
            zdata = entry
        else:
            continue
        path = zdata.get("path", [])
        pts = tuple((float(pt["x"]), float(pt["y"])) for pt in path if "x" in pt and "y" in pt)
        if len(pts) >= 2:
            contour_out.append(pts)
            # If the cloud entry didn't carry a parseable composite key
            # (e.g. dict-shaped entries from older firmware), synthesise
            # one from the entry's positional index — keeps the parallel
            # arrays aligned and lets dispatcher logic fall back to
            # "everything" rather than crashing.
            contour_ids_out.append(cid if cid is not None else (1, len(contour_ids_out)))
    return contour_out, contour_ids_out


def _parse_maintenance_points(cloud_response: dict[str, Any]) -> list[MaintenancePoint]:
    """Parse ``cleanPoints`` from *cloud_response* into :class:`MaintenancePoint` objects.

    Coordinates are kept in raw cloud-frame mm so go-to services can pass
    them straight to ``device.go_to(x_mm, y_mm)`` without re-reflecting.
    """
    mp_out: list[MaintenancePoint] = []
    clean_raw = cloud_response.get("cleanPoints", {})
    cp_entries = clean_raw.get("value", []) if isinstance(clean_raw, dict) else []
    for entry in cp_entries:
        if isinstance(entry, list) and len(entry) >= 2:
            point_id = entry[0]
            pdata = entry[1]
        elif isinstance(entry, dict):
            point_id = entry.get("id", 1)
            pdata = entry
        else:
            continue
        point_path = pdata.get("path") or []
        if not point_path:
            continue
        try:
            pt = point_path[0]
            pid = int(point_id) if isinstance(point_id, (int, float)) else int(pdata.get("id", len(mp_out) + 1))
            mp_out.append(MaintenancePoint(point_id=pid, x_mm=float(pt["x"]), y_mm=float(pt["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    return mp_out


def _parse_cruise_points(cloud_response: dict[str, Any]) -> list[PatrolPoint]:
    """Parse ``cruisePoints`` (patrol points, type=8) into PatrolPoint objects.

    Same wrapper shape as ``cleanPoints``:
    ``{dataType, value: [[id, {path:[{x,y}], type, ...}], ...]}``.
    Coordinates kept in raw cloud-frame mm.
    """
    pp_out: list[PatrolPoint] = []
    cruise_raw = cloud_response.get("cruisePoints", {})
    cp_entries = cruise_raw.get("value", []) if isinstance(cruise_raw, dict) else []
    for entry in cp_entries:
        if isinstance(entry, list) and len(entry) >= 2:
            point_id = entry[0]
            pdata = entry[1]
        elif isinstance(entry, dict):
            point_id = entry.get("id", 1)
            pdata = entry
        else:
            continue
        point_path = pdata.get("path") or []
        if not point_path:
            continue
        try:
            pt = point_path[0]
            pid = int(point_id) if isinstance(point_id, (int, float)) else int(pdata.get("id", len(pp_out) + 1))
            pp_out.append(PatrolPoint(point_id=pid, x_mm=float(pt["x"]), y_mm=float(pt["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    return pp_out


def _parse_nav_paths(cloud_response: dict[str, Any]) -> list[NavPath]:
    """Parse ``paths`` (gray nav-path polylines) from *cloud_response*.

    Coordinates are kept in cloud-frame mm (no reflection needed — purely
    informational for rendering).

    Cloud shape (verified 2026-05-08 against user's g2408 fw 4.3.6_0550):
      paths = {"dataType": "Map", "value": [[id_int, {id, type, shapeType, path: [{x, y}, ...]}]]}
    The OUTER dict has dataType + value; ``value`` is a list of
    ``[id, dict]`` pairs (same wrapper shape as mowingAreas, forbiddenAreas,
    etc.).  Earlier (a92) decoder iterated the outer dict directly and
    always returned () because dataType / value aren't valid path_ids.
    """
    nav_paths_raw = cloud_response.get("paths", {})
    nav_paths_out: list[NavPath] = []
    if nav_paths_raw is not None and nav_paths_raw != {} and nav_paths_raw != []:
        if isinstance(nav_paths_raw, dict):
            # Unwrap the dataType/value layer if present.
            # Expected shape: {"dataType": "Map", "value": [[id, {...}], ...]}
            nav_value = nav_paths_raw.get("value", nav_paths_raw)
        elif isinstance(nav_paths_raw, list):
            nav_value = nav_paths_raw
        else:
            _warn_shape_mismatch(
                "paths",
                "dict{dataType,value} or list",
                nav_paths_raw,
                context="outer paths field",
            )
            nav_value = None

        if nav_value is not None and nav_value != [] and not isinstance(nav_value, list):
            _warn_shape_mismatch(
                "paths.value",
                "list of [id, dict] pairs",
                nav_value,
                context="after unwrapping dataType/value envelope",
            )
            nav_value = None

        if isinstance(nav_value, list):
            # Two cases: list of [id, dict] pairs (real cloud shape) or
            # list of dicts directly (defensive for hypothetical alt shape).
            for entry in nav_value:
                pdata = None
                path_id_int: int | None = None
                if isinstance(entry, list) and len(entry) == 2:
                    # [id, dict] pair form (the real shape)
                    try:
                        path_id_int = int(entry[0])
                    except (TypeError, ValueError):
                        continue
                    if isinstance(entry[1], dict):
                        pdata = entry[1]
                    else:
                        _warn_shape_mismatch(
                            "paths entry[1]",
                            "dict",
                            entry[1],
                            context=f"path_id={entry[0]}",
                        )
                        continue
                elif isinstance(entry, dict):
                    # Bare dict form (alt shape; id pulled from entry["id"])
                    try:
                        path_id_int = int(entry.get("id", 0))
                    except (TypeError, ValueError):
                        continue
                    pdata = entry
                elif entry is not None:
                    # Non-None, not a list or dict — unexpected entry type
                    _warn_shape_mismatch(
                        "paths list entry",
                        "list[id, dict] or dict",
                        entry,
                        context="paths.value element",
                    )
                    continue
                if pdata is None:
                    continue
                raw_pts = pdata.get("path", [])
                if not isinstance(raw_pts, list):
                    _warn_shape_mismatch(
                        "paths entry path",
                        "list of {x, y} dicts",
                        raw_pts,
                        context=f"path_id={path_id_int}",
                    )
                    continue
                pts = tuple(
                    (float(p["x"]), float(p["y"]))
                    for p in raw_pts
                    if isinstance(p, dict) and "x" in p and "y" in p
                )
                if pts:
                    nav_paths_out.append(
                        NavPath(
                            path_id=path_id_int,
                            path=pts,
                            path_type=int(pdata.get("type", 0) or 0),
                        )
                    )
    return nav_paths_out


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------


def parse_cloud_map(cloud_response: dict[str, Any]) -> MapData | None:
    """Parse the cloud's ``MAP.*`` batch response into a :class:`MapData`.

    ``cloud_response`` should be the already-joined-and-JSON-decoded
    top-level map dict (the dict that contains ``"boundary"``,
    ``"mowingAreas"``, etc. — see §1 of cloud-map-geometry.md).

    Returns ``None`` when the input is empty, malformed, or carries an
    unusable boundary (e.g. all-zero after a failed cloud fetch).  The
    caller should log and skip re-render in that case.
    """
    if not isinstance(cloud_response, dict):
        _LOGGER.debug("parse_cloud_map: not a dict (%r)", type(cloud_response))
        return None

    boundary = cloud_response.get("boundary")
    if not isinstance(boundary, dict):
        _LOGGER.debug("parse_cloud_map: missing 'boundary' key")
        return None

    # Cloud sometimes returns float boundary coords.
    try:
        bx1 = float(boundary.get("x1", 0))
        by1 = float(boundary.get("y1", 0))
        bx2 = float(boundary.get("x2", 0))
        by2 = float(boundary.get("y2", 0))
    except (TypeError, ValueError) as exc:
        _LOGGER.debug("parse_cloud_map: bad boundary values: %s", exc)
        return None

    # An all-zero boundary almost always means an empty/error response.
    if bx1 == 0 and by1 == 0 and bx2 == 0 and by2 == 0:
        _LOGGER.debug("parse_cloud_map: zero boundary — skipping")
        return None

    # -----------------------------------------------------------------------
    # Forbidden/exclusion + spot zones — stored as RAW cloud-frame corners
    # (single-frame contract). The app's per-centroid rotation (``-angle``) is
    # a RENDER transform (``geom.rotate_zone_points``); we rotate here ONLY to
    # (a) expand the canvas bbox to cover the on-screen corners and (b) feed the
    # stable dedup hash. The STORED ``Zone.points`` stay raw. See §4.1 of the
    # geometry doc + CLAUDE.md § "Decode->render zone frame contract".
    # -----------------------------------------------------------------------
    forbidden_raw = cloud_response.get("forbiddenAreas", {})
    ignore_raw = cloud_response.get("notObsAreas", {})
    spot_raw = cloud_response.get("spotAreas", {})

    excl_entries = [
        *_collect_exclusion_entries(forbidden_raw, None),     # red
        *_collect_exclusion_entries(ignore_raw, "ignore"),    # green
    ]
    spot_entries = _collect_spot_entries(spot_raw)   # grey, id+name preserved

    excl_out: list[Zone] = []
    excl_rotated: list[tuple[tuple[float, float], ...]] = []
    for (obj_id, raw_pts, subtype, shape_type, raw_angle) in excl_entries:
        angle = float(raw_angle) if raw_angle is not None else None
        excl_out.append(
            Zone(
                kind="exclusion",
                points=raw_pts,
                subtype=subtype,
                obj_id=obj_id,
                shape_type=shape_type,
                angle=angle,
            )
        )
        excl_rotated.append(rotate_zone_points(raw_pts, angle, shape_type))

    spot_out: list[Zone] = []
    spot_rotated: list[tuple[tuple[float, float], ...]] = []
    for (spot_id, name, raw_pts, area_m2, raw_angle) in spot_entries:
        angle = float(raw_angle) if raw_angle is not None else None
        spot_out.append(
            Zone(
                kind="spot",
                points=raw_pts,
                obj_id=spot_id,
                name=name,
                area_m2=area_m2,
                angle=angle,
            )
        )
        spot_rotated.append(rotate_zone_points(raw_pts, angle, None))

    # Canvas params — bbox expanded over the ROTATED zone corners, derived by
    # the pure ``geom.derive_canvas`` helper (the render's ``build_projection``
    # recomputes the identical values from the raw MapData).
    canvas = derive_canvas(
        bx1, by1, bx2, by2,
        (*excl_rotated, *spot_rotated),
        grid_size_mm=GRID_SIZE_MM,
    )
    bx1_exp = canvas["bx1"]
    by1_exp = canvas["by1"]
    bx2_exp = canvas["bx2"]
    by2_exp = canvas["by2"]
    width_px = canvas["width_px"]
    height_px = canvas["height_px"]
    x_reflect = canvas["cloud_x_reflect"]
    y_reflect = canvas["cloud_y_reflect"]
    dock_xy = canvas["dock_xy"]
    boundary_polygon = canvas["boundary_polygon"]

    # -----------------------------------------------------------------------
    # Mowing zones — keep in cloud-frame mm (renderer applies its own flip).
    # -----------------------------------------------------------------------
    mowing_out = _parse_mowing_zones(cloud_response)

    # -----------------------------------------------------------------------
    # Contour paths — closed outlines, cloud-frame mm.
    # Each cloud entry is keyed by a 2-int composite ID (e.g. [1, 0],
    # [1, 1], [2, 0]) which the edge-mow wire format passes directly
    # in ``d.edge: [[m, c], ...]``. We preserve those keys parallel
    # to the path tuples for the dispatcher's default-selection logic.
    # -----------------------------------------------------------------------
    contour_out, contour_ids_out = _parse_contours(cloud_response)

    # -----------------------------------------------------------------------
    # Maintenance / clean points — raw cloud-frame mm.
    # -----------------------------------------------------------------------
    mp_out = _parse_maintenance_points(cloud_response)

    # -----------------------------------------------------------------------
    # Cruise / patrol points — raw cloud-frame mm.
    # -----------------------------------------------------------------------
    pp_out = _parse_cruise_points(cloud_response)

    # -----------------------------------------------------------------------
    # Nav paths — gray connecting polylines between map regions.
    # Decoded from the cloud `paths` key. Coordinates kept in cloud-frame
    # mm (no reflection needed — purely informational for rendering).
    # Legacy upstream parses these as `MowerPath`; we use `NavPath`.
    # -----------------------------------------------------------------------
    nav_paths_out = _parse_nav_paths(cloud_response)

    # -----------------------------------------------------------------------
    # Stable content hash (NOT the cloud's md5sum which is volatile). Uses the
    # ROTATED (on-screen) exclusion corners so the dedup key is invariant to
    # the decode->render frame move (unchanged from pre-P3).
    # -----------------------------------------------------------------------
    stable = json.dumps(
        {
            "zones": sorted(
                (z.zone_id, round(z.path[0][0], 3), round(z.path[0][1], 3))
                for z in mowing_out
            ),
            "excl": [
                (round(p[0], 2), round(p[1], 2))
                for rp in excl_rotated
                for p in rp[:4]
            ],
            "dims": (width_px, height_px),
            "charger": dock_xy,
        },
        sort_keys=True,
    ).encode()
    md5 = hashlib.md5(stable).hexdigest()

    total_area_m2 = float(cloud_response.get("totalArea", 0.0) or 0.0)

    # Multi-map metadata: present in cloud responses with mapIndex; absent
    # in older single-map fixtures (default to 0 / None).
    map_index = cloud_response.get("mapIndex")
    if map_index is None:
        map_index = 0
    map_name = cloud_response.get("name")
    if map_name is not None:
        map_name = str(map_name)

    return MapData(
        md5=md5,
        width_px=width_px,
        height_px=height_px,
        pixel_size_mm=float(GRID_SIZE_MM),
        bx1=bx1_exp,
        by1=by1_exp,
        bx2=bx2_exp,
        by2=by2_exp,
        cloud_x_reflect=float(x_reflect),
        cloud_y_reflect=float(y_reflect),
        rotation_deg=0.0,
        boundary_polygon=boundary_polygon,
        mowing_zones=tuple(mowing_out),
        exclusion_zones=tuple(excl_out),
        spot_zones=tuple(spot_out),
        contour_paths=tuple(contour_out),
        available_contour_ids=tuple(contour_ids_out),
        maintenance_points=tuple(mp_out),
        patrol_points=tuple(pp_out),
        dock_xy=dock_xy,
        total_area_m2=total_area_m2,
        nav_paths=tuple(nav_paths_out),
        map_id=int(map_index),
        name=map_name,
    )


def apply_session_geometry(
    map_data: MapData,
    *,
    exclusion_polys_m: Sequence[Sequence[tuple[float, float]]],
    spot_polys_m: Sequence[Sequence[tuple[float, float]]],
) -> MapData:
    """Return a copy of ``map_data`` with its exclusion_zones / spot_zones
    replaced by SESSION-TIME geometry from a session-summary archive.

    The lawn boundary box is stable for a given map, so the canvas
    (bx1..by2, width/height, pixel grid) and therefore trail alignment are
    unchanged — only the user-editable no-go zones / spot areas differ between
    session time and now. The session polygons are already axis-aligned (no
    cloud ``angle``), so the stored RAW ``Zone.points`` (metres ×1000, angle
    ``None``) render identically once the presentation step applies its midline
    reflection; no coordinate math is re-derived here.

    ``exclusion_polys_m`` / ``spot_polys_m`` are polygons in charger-relative
    METRES (the frame SessionSummary.exclusions[].points /
    SessionSummary.spots[].corners are already in — the same frame as the
    s1p4 trail). Polygons with fewer than 3 points are dropped.
    """
    import dataclasses

    def _to_cloud_mm(poly: Sequence[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
        # metres → raw cloud-frame mm (×1000). Render rotates (angle None →
        # identity) then reflects.
        return tuple((x * 1000.0, y * 1000.0) for (x, y) in poly)

    excl = tuple(
        Zone(kind="exclusion", points=_to_cloud_mm(p), subtype=None)
        for p in exclusion_polys_m
        if len(p) >= 3
    )
    spots = tuple(
        Zone(kind="spot", points=_to_cloud_mm(p), obj_id=i, name=None, area_m2=0.0)
        for i, p in enumerate(spot_polys_m)
        if len(p) >= 3
    )
    return dataclasses.replace(map_data, exclusion_zones=excl, spot_zones=spots)
