"""When mowing (GREEN background), live AIOBS markers must be the obstacle
source fed to render_base — today the code forces obstacles=None in GREEN."""
import types

from custom_components.dreame_a2_mower.coordinator._rendering import _RenderingMixin
from custom_components.dreame_a2_mower.protocol.obstacle_markers import ObstacleMarker


def test_live_markers_supply_render_obstacles(monkeypatch):
    captured = {}

    def fake_render_base(map_data, **kw):
        captured["obstacles"] = kw.get("obstacle_polygons_m")
        return b"PNG"

    # _live_obstacle_polygons is the new pure selector under test.
    class _C(_RenderingMixin):
        _obstacle_markers = [
            ObstacleMarker("a", "a", ((-6.6, 4.1), (-6.7, 4.1), (-6.7, 4.0)),
                           78, 5, 0, 1781714586.078),
        ]

    polys = _C()._live_obstacle_polygons()
    assert polys == [[(-6.6, 4.1), (-6.7, 4.1), (-6.7, 4.0)]]


def test_short_polygons_dropped():
    class _C(_RenderingMixin):
        _obstacle_markers = [ObstacleMarker("a", "a", ((1.0, 2.0),), 50, 5, 0, 1.0)]

    assert _C()._live_obstacle_polygons() == []   # <3 points dropped
