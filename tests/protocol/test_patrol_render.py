"""Patrol points render as a green 'P' marker on the base map."""
from custom_components.dreame_a2_mower.map_render import render_base_map
from custom_components.dreame_a2_mower.protocol.map import PatrolPoint


class _FakeMap:
    """Minimal MapData stand-in for the renderer (only the fields it reads)."""
    md5 = "x"; width_px = 40; height_px = 40; pixel_size_mm = 50.0
    bx1 = 0.0; by1 = 0.0; bx2 = 2000.0; by2 = 2000.0
    cloud_x_reflect = 2000.0; cloud_y_reflect = 2000.0; rotation_deg = 0.0
    boundary_polygon = ((0.0, 0.0), (2000.0, 0.0), (2000.0, 2000.0), (0.0, 2000.0))
    mowing_zones = (); exclusion_zones = (); spot_zones = ()
    contour_paths = (); available_contour_ids = ()
    maintenance_points = ()
    patrol_points = (PatrolPoint(point_id=3, x_mm=1000.0, y_mm=1000.0),)
    dock_xy = None; total_area_m2 = 0.0; nav_paths = (); map_id = 0; name = ""


def _to_img(result):
    # render_base_map may return a PIL Image or PNG bytes; normalise.
    import io
    from PIL import Image
    if isinstance(result, (bytes, bytearray)):
        return Image.open(io.BytesIO(result))
    return result


def _has_greenish_pixel(img):
    for px in img.convert("RGBA").getdata():
        r, g, b, a = px
        if a > 0 and g > 120 and g > r + 30 and g > b + 30:
            return True
    return False


def test_patrol_point_draws_green_marker():
    img = _to_img(render_base_map(_FakeMap()))
    assert _has_greenish_pixel(img), "expected a green patrol-point marker pixel"


def test_no_patrol_points_no_crash():
    m = _FakeMap(); m.patrol_points = ()
    render_base_map(m)  # must not raise
