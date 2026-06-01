"""Coordinator live-map PNG-slot + base-render-method shape.

The composited ``render_main_view`` renderer was removed in the live-map
rehaul — the server renders only the base PNG (``render_base``, covered by
``tests/coordinator/test_base_render_on_activity.py``) and the map card draws
the trail + mower icon client-side. This file now pins the coordinator's PNG
cache slots and the ``_render_base`` method shape, plus the live-map camera
serving ``_base_png``.
"""
from __future__ import annotations


def test_coordinator_has_base_and_work_log_png_slots():
    """Coordinator exposes the live-map cache slots."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._base_png = None
    coord._work_log_png = None
    coord._base_png = b"\x89PNG"
    coord._work_log_png = b"\x89PNG"
    assert coord._base_png == b"\x89PNG"
    assert coord._work_log_png == b"\x89PNG"


def test_coordinator_init_sets_png_slots_to_none():
    """A freshly-constructed coordinator declares the live-map base slots None."""
    import re
    from pathlib import Path
    # Refactor 2026-05-15: see test_coordinator_writes.py for context.
    src = Path("custom_components/dreame_a2_mower/coordinator/_core.py").read_text()
    assert re.search(r"self\._base_png\s*:\s*bytes\s*\|\s*None\s*=\s*None", src), (
        "coordinator.__init__ should declare self._base_png: bytes | None = None"
    )
    assert re.search(
        r"self\._active_map_base_png\s*:\s*bytes\s*\|\s*None\s*=\s*None", src
    ), (
        "coordinator.__init__ should declare self._active_map_base_png: bytes | None = None"
    )
    assert re.search(r"self\._work_log_png\s*:\s*bytes\s*\|\s*None\s*=\s*None", src), (
        "coordinator.__init__ should declare self._work_log_png: bytes | None = None"
    )


def test_coordinator_render_base_method_exists():
    """Coordinator exposes _render_base as an awaitable that writes
    self._base_png."""
    import inspect
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    method = getattr(DreameA2MowerCoordinator, "_render_base", None)
    assert method is not None, "_render_base should be defined"
    assert inspect.iscoroutinefunction(method), "_render_base should be async"


def test_map_camera_reads_base_png():
    """DreameA2MapCamera.async_camera_image returns _base_png."""
    import asyncio
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.camera import DreameA2MapCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._base_png = b"\x89PNGbase"
    coord._work_log_png = None
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MagicMock()
    coord.data.hardware_serial = None

    cam = DreameA2MapCamera(coord)
    result = asyncio.run(cam.async_camera_image())
    assert result == b"\x89PNGbase"
