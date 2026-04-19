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

    # Register frontend
    # frontend_js = f"/{DOMAIN}/frontend.js"
    # if DATA_EXTRA_MODULE_URL not in hass.data:
    #    hass.data[DATA_EXTRA_MODULE_URL] = set()
    # if frontend_js not in (
    #    hass.data[DATA_EXTRA_MODULE_URL].urls
    #    if hasattr(hass.data[DATA_EXTRA_MODULE_URL], "urls")
    #    else hass.data[DATA_EXTRA_MODULE_URL]
    # ):
    #    hass.data[DATA_EXTRA_MODULE_URL].add(frontend_js)
    #    hass.http.register_static_path(frontend_js, str(Path(Path(__file__).parent / "frontend.js")), True)

    # Set up all platforms for this device/entry.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Options-update listener re-broadcasts current state with new calibration.
    async def _options_updated(hass_arg, entry_arg):
        coord = hass_arg.data[DOMAIN].get(entry_arg.entry_id)
        if coord and hasattr(coord, "live_map"):
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
    # the historical run. Accepts an explicit file or "latest".
    async def _handle_replay(call):
        coord = next(iter(hass.data[DOMAIN].values()), None)
        if coord is None:
            raise ValueError("No Dreame A2 coordinator loaded")
        file = call.data.get("file")
        if not file or file == "latest":
            return coord.live_map.replay_latest_session()
        return coord.live_map.replay_session(file)

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


