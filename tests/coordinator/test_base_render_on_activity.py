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
    coord = types.SimpleNamespace()
    coord.state_machine = MowerStateMachine()
    coord._active_map_id = 1
    coord.data = types.SimpleNamespace(action_mode=action_mode)
    coord.cloud_state = types.SimpleNamespace(
        maps_by_id={1: types.SimpleNamespace(md5=md5)}
    )
    coord.hass = _FakeHass()
    coord._base_png = None
    coord._base_png_mode = None
    coord._base_png_md5 = None

    for name in ("_render_base", "_compute_background_mode"):
        setattr(coord, name, types.MethodType(getattr(_RenderingMixin, name), coord))

    # _render_base only loads obstacles for non-GREEN modes; stub to "none".
    async def _no_obstacles(map_id):
        return None

    coord._load_last_session_obstacles = _no_obstacles
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
    assert len(coord.hass.calls) == 1


@pytest.mark.asyncio
async def test_render_base_noop_on_unchanged_mode_and_md5():
    coord = _make_coord()
    _set_activity(
        coord, activity=CurrentActivity.IDLE, mow_session=MowSession.BETWEEN_SESSIONS
    )
    await coord._render_base()
    assert len(coord.hass.calls) == 1
    # Second call, nothing changed: dedup short-circuits before the executor.
    await coord._render_base()
    assert len(coord.hass.calls) == 1
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
    assert len(coord.hass.calls) == 1

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
    assert len(coord.hass.calls) == 2


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
