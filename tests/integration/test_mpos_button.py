"""Tests for the Refresh MPOS diagnostic button."""
import asyncio
from custom_components.dreame_a2_mower.button import DreameA2RefreshMposButton


class _Coord:
    def __init__(self):
        self.calls = 0
        self.last_update_success = True

    async def _refresh_mpos(self):
        self.calls += 1


def _make(coord):
    # Bypass CoordinatorEntity.__init__ (needs HA runtime) like sibling
    # button/camera tests do; set the coordinator attr directly.
    btn = DreameA2RefreshMposButton.__new__(DreameA2RefreshMposButton)
    btn.coordinator = coord
    return btn


def test_press_calls_refresh_mpos():
    coord = _Coord()
    btn = _make(coord)
    asyncio.run(btn.async_press())
    assert coord.calls == 1
