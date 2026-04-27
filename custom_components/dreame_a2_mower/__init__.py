"""The Dreame Mower component."""

from __future__ import annotations
import traceback
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from pathlib import Path
from .const import DOMAIN
from .coordinator import DreameMowerDataUpdateCoordinator

PLATFORMS = (
    Platform.LAWN_MOWER,
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.TIME,
    Platform.DEVICE_TRACKER,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dreame Mower from a config entry."""
    coordinator = DreameMowerDataUpdateCoordinator(hass, entry=entry)
    # Load archive indices off the event loop before the first refresh —
    # `SessionArchive.__init__` and `LidarArchive.__init__` deliberately
    # defer their `index.json` reads so this step can run on an executor.
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Register the bundled WebGL LiDAR card at `/dreame_a2_mower/<file>`.
    # Users then add a Lovelace resource entry pointing at
    # `/dreame_a2_mower/dreame-a2-lidar-card.js` (type: module) to make
    # the `custom:dreame-a2-lidar-card` card type available in the UI.
    # Done once per HA process; guarded so reloads don't fail.
    from pathlib import Path as _Path
    _www = _Path(__file__).parent / "www"
    if not getattr(hass, "_dreame_a2_static_registered", False) and _www.is_dir():
        try:
            # Modern HA: async_register_static_paths takes a list of
            # StaticPathConfig dataclasses, not plain dicts.
            from homeassistant.components.http import StaticPathConfig
            await hass.http.async_register_static_paths(
                [StaticPathConfig(f"/{DOMAIN}", str(_www), False)]
            )
        except ImportError:
            # Fallback for HA versions predating StaticPathConfig.
            # `async_register_static_paths` on these accepts tuples.
            try:
                await hass.http.async_register_static_paths(
                    [(f"/{DOMAIN}", str(_www), False)]
                )
            except Exception:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "Static-path registration for LiDAR card skipped "
                    "(unsupported HA version). The card JS at %s won't "
                    "be served; copy it into /config/www/ manually to use it.",
                    _www,
                )
        hass._dreame_a2_static_registered = True

    # Set up all platforms for this device/entry.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Options-update listener re-broadcasts current state with new calibration.
    async def _options_updated(hass_arg, entry_arg):
        coord = hass_arg.data[DOMAIN].get(entry_arg.entry_id)
        if coord is None:
            return
        # Pick up station-bearing option for the compass position sensors.
        from .const import CONF_STATION_BEARING
        if hasattr(coord, "_device"):
            coord._device.station_bearing_deg = float(
                entry_arg.options.get(CONF_STATION_BEARING, 0.0) or 0.0
            )
        if hasattr(coord, "live_map"):
            coord.live_map.handle_options_update()

    entry.async_on_unload(entry.add_update_listener(_options_updated))

    # Import-from-probe-log service (dev tool).
    async def _handle_import(call):
        coord = next(iter(hass.data[DOMAIN].values()), None)
        if coord is None:
            raise ValueError("No Dreame A2 coordinator loaded")
        path = call.data.get("file")
        session_index = int(call.data.get("session_index", -1))
        if not path:
            raise ValueError("file is required")
        return coord.live_map.import_from_probe_log(path, session_index)

    if not hass.services.has_service(DOMAIN, "import_path_from_probe_log"):
        hass.services.async_register(DOMAIN, "import_path_from_probe_log", _handle_import)

    # Session-replay service (A3). Dispatches to live_map.set_mode:
    #   file missing / "latest" → LATEST (auto-track newest run)
    #   file == "blank"         → BLANK (empty canvas)
    #   file == <archive path>  → SESSION pinned to that entry
    # Runs on the executor because set_mode does blocking JSON parsing.
    async def _handle_replay(call):
        coord = next(iter(hass.data[DOMAIN].values()), None)
        if coord is None:
            raise ValueError("No Dreame A2 coordinator loaded")
        file = call.data.get("file")
        from .live_map import MapMode

        if not file or file == "latest":
            return await hass.async_add_executor_job(
                coord.live_map.set_mode, MapMode.LATEST
            )
        if file == "blank":
            return await hass.async_add_executor_job(
                coord.live_map.set_mode, MapMode.BLANK
            )

        # Resolve the file path to an archive entry by basename.
        archive = getattr(coord, "session_archive", None)
        if archive is None:
            raise ValueError("session archive not available")
        from pathlib import Path as _Path
        basename = _Path(file).name
        entry = next(
            (e for e in archive.list_sessions() if e.filename == basename),
            None,
        )
        if entry is None:
            raise ValueError(f"No archived session matches {basename}")
        return await hass.async_add_executor_job(
            coord.live_map.set_mode, MapMode.SESSION, entry
        )

    if not hass.services.has_service(DOMAIN, "replay_session"):
        hass.services.async_register(DOMAIN, "replay_session", _handle_replay)

    # Session-summary recovery service. Lets the user hand an OSS object
    # key to the integration when the auto-archival missed a session —
    # typically because the Dreame cloud auth was momentarily unhealthy
    # at the instant `event_occured` fired, and the pre-v2.0.0-alpha.6
    # handler silently dropped the key instead of stashing it for retry.
    # The key is usually recoverable from a probe log or the user's
    # Dreame app traffic. Setting the pending slot on the device lets
    # the coordinator's next tick perform the normal retry path —
    # including the `session_archive.archive(...)` call at the end on
    # success.
    async def _handle_recover_session(call):
        coord = next(iter(hass.data[DOMAIN].values()), None)
        if coord is None:
            raise ValueError("No Dreame A2 coordinator loaded")
        object_name = call.data.get("object_name")
        if not object_name or not isinstance(object_name, str):
            raise ValueError("object_name is required (e.g. ali_dreame/YYYY/MM/DD/…/…_*.json)")
        if coord._device is None:
            raise ValueError("Device not initialised yet")
        coord._device._pending_session_object_name = object_name
        # Bypass the coordinator's 60 s retry throttle — the user invoked
        # the service explicitly, so they want it now.
        coord._session_retry_last_at = 0.0
        # Fire the retry on the executor so the blocking HTTP round-trip
        # doesn't stall the event loop. We don't await the result — the
        # coordinator's normal archive path will pick it up on the next
        # updated-data tick, same as the auto-retry.
        hass.async_add_executor_job(coord._device.retry_pending_session_summary)
        return True

    if not hass.services.has_service(DOMAIN, "recover_session_summary"):
        hass.services.async_register(DOMAIN, "recover_session_summary", _handle_recover_session)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Dreame Mower config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: DreameMowerDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator._device.listen(None)
        coordinator._device.disconnect()
        del coordinator._device
        coordinator._device = None
        del hass.data[DOMAIN][entry.entry_id]

    return unload_ok


