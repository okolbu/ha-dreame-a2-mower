"""Tests for _RenderingMixin._render_base — the single server-side live-map
render, keyed on (background_mode, map md5), fired on activity transitions.

Built with the lightweight bound-mixin harness used elsewhere in
tests/coordinator (see test_inject_live_map_meta.py): a SimpleNamespace
carrying just the attrs _render_base touches, with the mixin methods bound via
types.MethodType. hass.async_add_executor_job is stubbed to record calls and
return PNG-ish bytes without invoking PIL.
"""
from __future__ import annotations

import dataclasses
import types

import pytest

from custom_components.dreame_a2_mower.coordinator._rendering import _RenderingMixin
from custom_components.dreame_a2_mower.map_render import BackgroundMode
from custom_components.dreame_a2_mower.mower.state import ActionMode
from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    CurrentActivity,
    MowSession,
)


_FAKE_PNG = b"\x89PNG\r\n\x1a\nFAKE"


class _FakeHass:
    """Records executor-job calls and returns canned PNG bytes."""

    def __init__(self):
        self.calls = []

    async def async_add_executor_job(self, func, *args):
        # func is functools.partial(render_base, ...) — we DON'T run it (no PIL).
        self.calls.append(func)
        return _FAKE_PNG


def _set_activity(coord, *, activity, mow_session):
    sm = coord.state_machine
    sm._snapshot = dataclasses.replace(
        sm._snapshot, current_activity=activity, mow_session=mow_session
    )


def _make_coord(*, action_mode=ActionMode.ALL_AREAS, md5="md5-aaa"):
    from tests.map_render.conftest import make_map_data

    coord = types.SimpleNamespace()
    coord.state_machine = MowerStateMachine()
    coord._active_map_id = 1
    coord.data = types.SimpleNamespace(action_mode=action_mode)
    # Real MapData (dataclass) — _render_base does dataclasses.replace() on it to
    # render the clean (no-exclusions) editor base, which a SimpleNamespace can't.
    map_data = dataclasses.replace(make_map_data(), md5=md5)
    coord.cloud_state = types.SimpleNamespace(maps_by_id={1: map_data})
    coord.hass = _FakeHass()
    coord._base_png = None
    coord._base_png_mode = None
    coord._base_png_md5 = None
    coord._editor_base_png = None
    coord._active_map_base_png = None
    coord._active_map_base_md5 = None

    for name in ("_render_base", "_compute_background_mode"):
        setattr(coord, name, types.MethodType(getattr(_RenderingMixin, name), coord))

    # _render_base only loads obstacles for non-GREEN modes; stub to "none".
    async def _no_obstacles(map_id):
        return None

    coord._load_last_session_obstacles = _no_obstacles

    # _render_base tail-calls _render_active_map_base (the Work Log clean-base
    # render). Stub it to a no-op here so the executor-call counts below reflect
    # only the live BASE render; the clean-base render is covered separately.
    async def _no_clean_base():
        return None

    coord._render_active_map_base = _no_clean_base
    return coord


@pytest.mark.asyncio
async def test_render_base_renders_and_caches_when_mode_changes():
    coord = _make_coord()
    # Idle ALL_AREAS -> STRIPES.
    _set_activity(
        coord, activity=CurrentActivity.IDLE, mow_session=MowSession.BETWEEN_SESSIONS
    )
    await coord._render_base()
    assert coord._base_png == _FAKE_PNG
    assert coord._base_png_mode == BackgroundMode.STRIPES
    assert coord._base_png_md5 == "md5-aaa"
    assert coord._editor_base_png == _FAKE_PNG
    # Two executor renders per pass: the live BASE + the clean (no-exclusions)
    # editor base.
    assert len(coord.hass.calls) == 2


@pytest.mark.asyncio
async def test_render_base_noop_on_unchanged_mode_and_md5():
    coord = _make_coord()
    _set_activity(
        coord, activity=CurrentActivity.IDLE, mow_session=MowSession.BETWEEN_SESSIONS
    )
    await coord._render_base()
    assert len(coord.hass.calls) == 2  # live base + clean editor base
    # Second call, nothing changed: dedup short-circuits before the executor.
    await coord._render_base()
    assert len(coord.hass.calls) == 2
    assert coord._base_png_mode == BackgroundMode.STRIPES


@pytest.mark.asyncio
async def test_render_base_rerenders_when_activity_flips_to_repositioning():
    coord = _make_coord()
    # Start idle -> STRIPES.
    _set_activity(
        coord, activity=CurrentActivity.IDLE, mow_session=MowSession.BETWEEN_SESSIONS
    )
    await coord._render_base()
    assert coord._base_png_mode == BackgroundMode.STRIPES
    assert len(coord.hass.calls) == 2  # live base + clean editor base

    # Flip to REPOSITIONING (off-dock, reorienting) -> GREEN. This is the
    # stripe-lag fix: the mode flips on the activity transition, ~41s before
    # the first move.
    _set_activity(
        coord,
        activity=CurrentActivity.REPOSITIONING,
        mow_session=MowSession.BETWEEN_SESSIONS,
    )
    await coord._render_base()
    assert coord._base_png_mode == BackgroundMode.GREEN
    assert len(coord.hass.calls) == 4  # +2 for the re-render (live + clean)


@pytest.mark.asyncio
async def test_editor_base_keeps_decorative_drops_standard_exclusions():
    """The editor-base render strips EDITABLE exclusions (line/rect/circle/
    ignore — drawn as card overlays) but KEEPS DECORATIVE shapes (heart/cloud/
    etc., shape_type in DECORATIVE_SHAPE_TYPES) so they render in the editor
    background pixel-identically to the live map. Pins the clean_md filter."""
    from custom_components.dreame_a2_mower.map_decoder import ExclusionZone

    heart = ExclusionZone(
        points=((5000.0, 5000.0), (9000.0, 8000.0)),
        subtype=None, obj_id=101,
        points_m=((5.0, 5.0), (9.0, 8.0)),
        shape_type=13,  # decorative -> KEEP in editor base
    )
    line = ExclusionZone(
        points=((2000.0, 2000.0), (4000.0, 6000.0)),
        subtype=None, obj_id=102,
        points_m=((2.0, 2.0), (4.0, 6.0)),
        shape_type=1,  # standard no-go line -> STRIP (card draws it)
    )
    coord = _make_coord()
    base = coord.cloud_state.maps_by_id[1]
    coord.cloud_state.maps_by_id[1] = dataclasses.replace(
        base, exclusion_zones=(heart, line)
    )

    _set_activity(
        coord, activity=CurrentActivity.IDLE, mow_session=MowSession.BETWEEN_SESSIONS
    )
    await coord._render_base()

    # Two executor renders: [0] = live base (all zones), [1] = editor base (clean_md).
    assert len(coord.hass.calls) == 2
    editor_partial = coord.hass.calls[1]
    clean_md = editor_partial.args[0]
    kept = clean_md.exclusion_zones
    assert [z.shape_type for z in kept] == [13], (
        "editor base must keep the decorative heart and drop the standard line"
    )


@pytest.mark.asyncio
async def test_render_base_noop_when_no_active_map():
    coord = _make_coord()
    coord._active_map_id = None
    await coord._render_base()
    assert coord._base_png is None
    assert len(coord.hass.calls) == 0


@pytest.mark.asyncio
async def test_compute_background_mode_in_session_is_green():
    coord = _make_coord()
    _set_activity(
        coord, activity=CurrentActivity.MOWING, mow_session=MowSession.IN_SESSION
    )
    assert coord._compute_background_mode() == BackgroundMode.GREEN


@pytest.mark.asyncio
async def test_green_skips_obstacle_load_idle_loads_it():
    """GREEN (active) must NOT load last-session obstacles; an idle preview
    mode MUST. Pins the `None if GREEN else _load_last_session_obstacles`
    branch in _render_base (otherwise both paths look identical when the load
    returns None)."""
    coord = _make_coord()
    loads = []

    async def _recording_load(map_id):
        loads.append(map_id)
        return None

    coord._load_last_session_obstacles = _recording_load

    # Idle ALL_AREAS -> STRIPES: obstacle load IS invoked.
    _set_activity(
        coord, activity=CurrentActivity.IDLE, mow_session=MowSession.BETWEEN_SESSIONS
    )
    await coord._render_base()
    assert loads == [1]

    # Flip to GREEN (active): obstacle load must NOT be invoked again.
    _set_activity(
        coord, activity=CurrentActivity.MOWING, mow_session=MowSession.IN_SESSION
    )
    await coord._render_base()
    assert loads == [1]  # unchanged — GREEN skipped the load


@pytest.mark.asyncio
async def test_render_active_map_base_writes_clean_base_and_dedups():
    """_render_active_map_base renders the Work Log clean base once per map
    version (md5-deduped) into _active_map_base_png."""
    coord = _make_coord()
    # Bind the real method (the harness stubs it to a no-op by default).
    coord._render_active_map_base = types.MethodType(
        _RenderingMixin._render_active_map_base, coord
    )

    await coord._render_active_map_base()
    assert coord._active_map_base_png == _FAKE_PNG
    assert coord._active_map_base_md5 == "md5-aaa"
    assert len(coord.hass.calls) == 1

    # Same md5 -> dedup short-circuits, no new executor call.
    await coord._render_active_map_base()
    assert len(coord.hass.calls) == 1
