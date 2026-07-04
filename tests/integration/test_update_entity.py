import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from homeassistant.exceptions import HomeAssistantError
from custom_components.dreame_a2_mower.const import CONF_EXPERIMENTAL_FEATURES
from custom_components.dreame_a2_mower.update import DreameA2FirmwareUpdateEntity


def _entity(coord):
    e = DreameA2FirmwareUpdateEntity.__new__(DreameA2FirmwareUpdateEntity)
    e.coordinator = coord
    return e


def _coord(experimental=True, **f):
    # P4.4 (R-52): the install ACTION is gated experimental. Default the fake
    # coordinator's entry to gate-ON so the version/refusal tests exercise the
    # real install path; the gate-OFF raise has its own test below.
    data = SimpleNamespace(
        firmware_version=f.get("installed"),
        firmware_latest=f.get("latest"),
        firmware_update_available=f.get("available"),
        firmware_release_notes=f.get("notes"),
        ota_state=f.get("ota_state"),
        ota_progress=f.get("ota_progress"),
    )
    entry = SimpleNamespace(options={CONF_EXPERIMENTAL_FEATURES: experimental})
    return SimpleNamespace(data=data, cloud_state=None, entry=entry)


def test_installed_and_latest_version():
    e = _entity(_coord(installed="4.3.6_0550", latest="4.3.6_0625", available=True))
    assert e.installed_version == "4.3.6_0550"
    assert e.latest_version == "4.3.6_0625"


def test_latest_falls_back_to_installed_when_not_available():
    e = _entity(_coord(installed="4.3.6_0625", latest=None, available=False))
    assert e.latest_version == "4.3.6_0625"


def test_in_progress_and_percentage():
    e = _entity(_coord(installed="x", ota_state=2, ota_progress=47))
    assert e.in_progress is True
    assert e.update_percentage == 47
    e2 = _entity(_coord(installed="x", ota_state=1, ota_progress=0))
    assert e2.in_progress is False


@pytest.mark.asyncio
async def test_install_raises_on_device_refusal():
    coord = _coord(installed="x")
    coord.async_trigger_firmware_update = AsyncMock(return_value=False)
    e = _entity(coord)
    with pytest.raises(HomeAssistantError):
        await e.async_install(version=None, backup=False)


@pytest.mark.asyncio
async def test_install_ok_on_accept():
    coord = _coord(installed="x")
    coord.async_trigger_firmware_update = AsyncMock(return_value=True)
    e = _entity(coord)
    await e.async_install(version=None, backup=False)


@pytest.mark.asyncio
async def test_install_raises_when_experimental_off():
    """P4.4 (R-52, track-5 T5-9): the install action is gated — it raises
    before touching the wire when experimental_features is off, and does NOT
    call async_trigger_firmware_update."""
    coord = _coord(experimental=False, installed="x")
    coord.async_trigger_firmware_update = AsyncMock(return_value=True)
    e = _entity(coord)
    with pytest.raises(HomeAssistantError):
        await e.async_install(version=None, backup=False)
    coord.async_trigger_firmware_update.assert_not_called()
