"""rendering mixin — thin delegators (refactor-v2 P3.9e).

The live-map render orchestration LOGIC moved VERBATIM to the ``domain/`` layer
(``domain/render.py``). Each domain function takes the coordinator (``coord``)
as its first argument; this mixin keeps thin delegating methods so the
public/test surface (``coord._render_base`` / ``coord._render_active_map_base``
/ ``coord._current_mower_position`` / ``coord._compute_background_mode`` /
``coord._schedule_render_base`` / ``coord._live_obstacle_polygons`` /
``coord._begin_live_stream`` / ``coord._publish_live_point`` /
``coord.live_track_snapshot`` / ``coord._load_last_session_obstacles``, the
unbound ``_RenderingMixin._X`` methods bound by ``test_live_stream_publish`` /
``test_base_render_on_activity`` / ``test_obstacle_live_render``, and the
``LIVE_TRACK_SNAPSHOT_MAX`` re-export) is unchanged.

See docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md and
the refactor-v2 P3 plan.
"""
from __future__ import annotations

from ..domain import render as _render

# Back-compat re-export — tests import this constant from its old
# ``coordinator._rendering`` home (test_live_stream_publish).
LIVE_TRACK_SNAPSHOT_MAX = _render.LIVE_TRACK_SNAPSHOT_MAX
_decimate = _render._decimate


class _RenderingMixin:
    """Thin delegators to ``domain.render`` (P3.9e) — see module docstring."""

    def _current_mower_position(self) -> tuple[float, float] | None:
        """Delegates to ``domain.render.current_mower_position`` (P3.9e)."""
        return _render.current_mower_position(self)

    def _compute_background_mode(self):
        """Delegates to ``domain.render.compute_background_mode`` (P3.9e)."""
        return _render.compute_background_mode(self)

    def _schedule_render_base(self) -> None:
        """Delegates to ``domain.render.schedule_render_base`` (P3.9e)."""
        _render.schedule_render_base(self)

    def _live_obstacle_polygons(self) -> "list[list[tuple[float, float]]]":
        """Delegates to ``domain.render.live_obstacle_polygons`` (P3.9e)."""
        return _render.live_obstacle_polygons(self)

    async def _render_base(self) -> None:
        """Delegates to ``domain.render.render_base`` (P3.9e)."""
        await _render.render_base(self)

    async def _render_active_map_base(self) -> None:
        """Delegates to ``domain.render.render_active_map_base`` (P3.9e)."""
        await _render.render_active_map_base(self)

    def _begin_live_stream(self) -> None:
        """Delegates to ``domain.render.begin_live_stream`` (P3.9e)."""
        _render.begin_live_stream(self)

    def _publish_live_point(
        self, *, x_m: float, y_m: float, heading_deg: float | None, t: float
    ) -> None:
        """Delegates to ``domain.render.publish_live_point`` (P3.9e)."""
        _render.publish_live_point(
            self, x_m=x_m, y_m=y_m, heading_deg=heading_deg, t=t
        )

    def live_track_snapshot(self) -> list[list]:
        """Delegates to ``domain.render.live_track_snapshot`` (P3.9e)."""
        return _render.live_track_snapshot(self)

    async def _load_last_session_obstacles(
        self, map_id: int
    ) -> list[list[tuple[float, float]]] | None:
        """Delegates to ``domain.render.load_last_session_obstacles`` (P3.9e)."""
        return await _render.load_last_session_obstacles(self, map_id)
