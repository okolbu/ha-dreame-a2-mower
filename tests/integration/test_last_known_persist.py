"""Task 12a — offline last-known persistence: Store restore/seed + save wiring.

Covers the coordinator-layer wiring around ``state.last_known.LastKnown``:
  - ``_CoreMixin._restore_last_known`` seeds MowerState fields + ``_active_map_id``
  - a restored ``active_map_id`` lets ``render_base`` proceed past its None guard
  - ``_CoreMixin._save_last_known`` builds a blob from ``data`` + ``_active_map_id``
    and schedules a debounced Store save
  - a FAILED specialist refresh does NOT persist (no overwrite of good last-known)
"""
from __future__ import annotations

import asyncio
import dataclasses
import types
from types import SimpleNamespace

import pytest

from custom_components.dreame_a2_mower.coordinator._core import _CoreMixin
from custom_components.dreame_a2_mower.domain import device_info
from custom_components.dreame_a2_mower.state import MowerState
from custom_components.dreame_a2_mower.state.last_known import LastKnown


class _AsyncLoadStore:
    def __init__(self, data):
        self._data = data

    async def async_load(self):
        return self._data


class _DelaySaveStore:
    def __init__(self):
        self.saved = []

    def async_delay_save(self, data_func, delay):
        self.saved.append((data_func(), delay))


def _restore_coord(store):
    # Lightweight bound-mixin harness (no __init__ bypass — see
    # tests/audit/test_no_new_coordinator_bypass.py): bind just the _CoreMixin
    # method under test onto a SimpleNamespace carrying the attrs it touches.
    c = SimpleNamespace()
    c.data = MowerState()
    c._active_map_id = None
    c._last_known_store = store
    c.entry = SimpleNamespace(entry_id="e1")
    c.hass = SimpleNamespace()
    c._restore_last_known = types.MethodType(_CoreMixin._restore_last_known, c)
    return c


# --- restore + seed ---------------------------------------------------------

def test_restore_seeds_mower_state_and_active_map_id():
    blob = LastKnown(
        blades_life_pct=88.0,
        dock_x_mm=1500,
        wifi_ssid="MyLawnNet",
        firmware_version="4.3.6_0625",
        rain_protection_enabled=True,
        active_map_id=7,
        saved_unix=123.0,
    )
    c = _restore_coord(_AsyncLoadStore(blob.to_dict()))
    asyncio.run(c._restore_last_known())
    assert c.data.blades_life_pct == 88.0
    assert c.data.dock_x_mm == 1500
    assert c.data.wifi_ssid == "MyLawnNet"
    assert c.data.firmware_version == "4.3.6_0625"
    assert c.data.rain_protection_enabled is True
    assert c._active_map_id == 7


def test_restore_missing_store_data_is_noop():
    c = _restore_coord(_AsyncLoadStore(None))
    asyncio.run(c._restore_last_known())
    assert c.data == MowerState()
    assert c._active_map_id is None


def test_restore_none_active_map_id_left_alone():
    # A blob with values but no active_map_id must not clobber a live one.
    c = _restore_coord(_AsyncLoadStore({"blades_life_pct": 10.0}))
    c._active_map_id = 3
    asyncio.run(c._restore_last_known())
    assert c.data.blades_life_pct == 10.0
    assert c._active_map_id == 3  # untouched


def test_restore_tolerates_corrupt_store():
    class _BadStore:
        async def async_load(self):
            raise RuntimeError("corrupt")

    c = _restore_coord(_BadStore())
    asyncio.run(c._restore_last_known())  # must not raise
    assert c.data == MowerState()


# --- restored active_map_id unblocks render_base ----------------------------

def _render_coord():
    """Minimal bound-mixin render harness (mirrors test_base_render_on_activity)."""
    from tests.map_render.conftest import make_map_data
    from custom_components.dreame_a2_mower.coordinator._rendering import (
        _RenderingMixin,
    )
    from custom_components.dreame_a2_mower.state.machine import MowerStateMachine

    _FAKE_PNG = b"\x89PNG\r\n\x1a\nFAKE"

    class _FakeHass:
        def __init__(self):
            self.calls = []

        async def async_add_executor_job(self, func, *args):
            self.calls.append(func)
            return _FAKE_PNG

    coord = types.SimpleNamespace()
    coord.state_machine = MowerStateMachine()
    coord._active_map_id = None  # offline: not yet known
    coord.data = MowerState()
    coord.cloud_state = types.SimpleNamespace(
        maps_by_id={1: dataclasses.replace(make_map_data(), md5="md5-aaa")}
    )
    coord.hass = _FakeHass()
    coord._base_png = None
    coord._base_png_mode = None
    coord._base_png_md5 = None
    coord._base_png_marker_fp = None
    coord._base_png_direction = None
    coord._obstacle_markers = []
    coord._editor_base_png = None
    coord._active_map_base_png = None
    coord._active_map_base_md5 = None
    for name in ("_render_base", "_compute_background_mode", "_live_obstacle_polygons"):
        setattr(coord, name, types.MethodType(getattr(_RenderingMixin, name), coord))

    async def _no_obstacles(map_id):
        return None

    coord._load_last_session_obstacles = _no_obstacles

    async def _no_clean_base():
        return None

    coord._render_active_map_base = _no_clean_base
    # bind the restore/seed method under test
    coord._last_known_store = _AsyncLoadStore({"active_map_id": 1})
    coord.entry = SimpleNamespace(entry_id="e1")
    coord._restore_last_known = types.MethodType(
        _CoreMixin._restore_last_known, coord
    )
    return coord


def test_restored_active_map_id_unblocks_render_base():
    coord = _render_coord()
    # Before restore: _active_map_id is None -> render_base early-returns.
    asyncio.run(coord._render_base())
    assert coord.hass.calls == []
    # After restore: _active_map_id seeded from the blob -> render proceeds.
    asyncio.run(coord._restore_last_known())
    assert coord._active_map_id == 1
    asyncio.run(coord._render_base())
    assert coord.hass.calls, "render_base should proceed past the None guard"


# --- save builds blob + schedules debounced persist -------------------------

def _save_coord(store):
    c = SimpleNamespace()
    c.data = MowerState(blades_life_pct=55.0, wifi_ssid="Net")
    c._active_map_id = 4
    c._last_known_store = store
    c._save_last_known = types.MethodType(_CoreMixin._save_last_known, c)
    return c


def test_save_last_known_schedules_debounced_persist():
    store = _DelaySaveStore()
    c = _save_coord(store)
    c._save_last_known()
    assert len(store.saved) == 1
    saved, delay = store.saved[0]
    assert isinstance(delay, int) and delay > 0
    blob = LastKnown.from_dict(saved)
    assert blob.blades_life_pct == 55.0
    assert blob.wifi_ssid == "Net"
    assert blob.active_map_id == 4
    assert blob.saved_unix is not None


def test_save_last_known_noop_without_store():
    c = _save_coord(None)
    c._save_last_known()  # must not raise


# --- persist-on-success only ------------------------------------------------

def _refresh_coord(dock_return):
    c = SimpleNamespace()
    c._cloud = SimpleNamespace(fetch_dock=lambda: dock_return)
    c.data = MowerState()
    c._active_map_id = 1

    async def _exec(fn, *a):
        return fn(*a)

    c.hass = SimpleNamespace(async_add_executor_job=_exec)
    c.async_set_updated_data = lambda s: setattr(c, "data", s)
    c.saves = 0

    def _save():
        c.saves += 1

    c._save_last_known = _save
    return c


def test_failed_dock_refresh_does_not_persist():
    # fetch_dock returns a non-dict (transient failure) -> refresh_dock bails
    # before touching MowerState; last-known must NOT be overwritten.
    c = _refresh_coord(None)
    asyncio.run(device_info.refresh_dock(c))
    assert c.saves == 0


def test_successful_dock_refresh_persists():
    c = _refresh_coord({"dock": {"x": 100, "y": 200, "yaw": 90, "in_region": 1}})
    asyncio.run(device_info.refresh_dock(c))
    assert c.data.dock_x_mm == 100
    assert c.saves == 1
