"""Boot backfill deferral (#1 startup-latency fix).

The specialist refreshers used to fire INLINE inside
``async_config_entry_first_refresh`` — up to ~8 cloud round-trips (the
``_refresh_oss_gallery(max_pages=400)`` full backfill dominating), which with
an offline mower stretched HA boot past a minute. They now split into:

- ``_schedule_specialist_refreshers`` — SYNC, registers the periodic timers
  only (no immediate fire), so setup stays cheap;
- ``_run_boot_backfill`` — the one immediate boot kick for each specialist,
  run as an entry background task AFTER setup returns.

These tests pin that split so a future edit can't silently move a heavy fetch
back onto the setup-blocking path.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dreame_a2_mower.domain import boot as _boot
from custom_components.dreame_a2_mower.state import MowerState


def _stub_coord() -> SimpleNamespace:
    """Minimal coord surface for the two boot seam functions under test."""
    coord = SimpleNamespace()
    coord.hass = MagicMock()
    coord.entry = SimpleNamespace(async_on_unload=MagicMock())
    coord.data = MowerState()
    coord.async_set_updated_data = MagicMock()
    # Every specialist as an AsyncMock so we can assert awaited-or-not.
    for name in (
        "_refresh_cloud_state",
        "_refresh_gps", "_refresh_aiobs", "_refresh_remote", "_refresh_messages",
        "_refresh_oss_gallery", "_refresh_dev", "_refresh_net", "_refresh_dock",
        "_periodic_archive_refresh", "_establish_notification_baseline",
        "refresh_wifi_archive",
    ):
        setattr(coord, name, AsyncMock())
    return coord


def test_specialist_refreshers_registers_timers_without_firing(monkeypatch):
    """The (now synchronous) timer registration must NOT await any refresher —
    that would re-block setup. Pre-fix this function awaited ~8 of them."""
    recorded: list = []
    monkeypatch.setattr(
        _boot, "async_track_time_interval",
        lambda hass, action, interval: recorded.append((action, interval)) or (lambda: None),
    )
    coord = _stub_coord()

    _boot._schedule_specialist_refreshers(coord)

    # A real population of periodic timers was registered...
    assert len(recorded) >= 8
    # ...but NOTHING was fetched inline.
    coord._refresh_gps.assert_not_called()
    coord._refresh_oss_gallery.assert_not_called()
    coord._refresh_dev.assert_not_called()
    coord._refresh_messages.assert_not_called()
    coord.refresh_wifi_archive.assert_not_called()


@pytest.mark.asyncio
async def test_boot_backfill_fires_every_specialist_once():
    """The deferred backfill gives each specialist exactly one immediate boot
    kick, with the OSS gallery using the full max_pages=400 backfill cap."""
    coord = _stub_coord()

    await _boot._run_boot_backfill(coord)

    # Full cloud-state refresh (with the device probes the fast setup gate
    # skipped) runs off the boot path.
    coord._refresh_cloud_state.assert_awaited_once()
    coord._establish_notification_baseline.assert_awaited_once()
    coord._refresh_gps.assert_awaited_once()
    coord._refresh_remote.assert_awaited_once()
    coord._refresh_messages.assert_awaited_once()
    coord._refresh_oss_gallery.assert_awaited_once_with(max_pages=400)
    coord._refresh_dev.assert_awaited_once()
    coord._refresh_net.assert_awaited_once()
    coord._refresh_dock.assert_awaited_once()
    coord.refresh_wifi_archive.assert_awaited_once()
    # Seeds are pushed to entities once at the end.
    coord.async_set_updated_data.assert_called()


@pytest.mark.asyncio
async def test_boot_backfill_isolates_a_failing_step():
    """One failing fetch must not strand the rest (offline resilience) — the
    step wrapper swallows to debug and continues."""
    coord = _stub_coord()
    coord._refresh_gps.side_effect = RuntimeError("cloud offline")

    # Must not raise despite the GPS failure.
    await _boot._run_boot_backfill(coord)

    # Steps after the failing one still ran.
    coord._refresh_dock.assert_awaited_once()
    coord._refresh_oss_gallery.assert_awaited_once_with(max_pages=400)
