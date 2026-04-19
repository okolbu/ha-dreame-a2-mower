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
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dreame Mower from a config entry."""
    coordinator = DreameMowerDataUpdateCoordinator(hass, entry=entry)
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
            await hass.http.async_register_static_paths(
                [{"url_path": f"/{DOMAIN}", "path": str(_www), "cache_headers": False}]
            )
        except AttributeError:
            # Older HA (pre-2024): sync API.
            hass.http.register_static_path(f"/{DOMAIN}", str(_www), cache_headers=False)
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

    # Session-replay service (A3). Freezes an archived session's
    # overlay into the live-map camera so a Lovelace map card redraws
    # the historical run. Accepts an explicit file or "latest". The
    # underlying method does blocking disk + JSON-parse work — run on
    # the executor to keep the event loop free.
    async def _handle_replay(call):
        coord = next(iter(hass.data[DOMAIN].values()), None)
        if coord is None:
            raise ValueError("No Dreame A2 coordinator loaded")
        file = call.data.get("file")
        if not file or file == "latest":
            return await hass.async_add_executor_job(coord.live_map.replay_latest_session)
        return await hass.async_add_executor_job(coord.live_map.replay_session, file)

    if not hass.services.has_service(DOMAIN, "replay_session"):
        hass.services.async_register(DOMAIN, "replay_session", _handle_replay)

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


