"""P4.4: experimental-gate POPULATION (R-52, track-5 T5-9).

P4.1 built the mechanism; P4.4 tiers the 13 real surfaces. With the
``experimental_features`` option OFF (the default), the 11 gated ENTITIES must
NOT be created and the 2 gated ACTIONS/SERVICES must raise; with it ON, every
gated entity IS created but forced disabled-by-default.

The 13 gated surfaces (track-5 T5-9):
  * T1 speculative — sensor.mpos, button.refresh_mpos, sensor.s5p104_raw /
    s5p105_raw / s5p106_raw / s5p107_raw / s6p1_raw, sensor.api_endpoints_supported,
    sensor.novel_observations, service create_patrol_point.
  * T2 wire_unexercised — update.firmware INSTALL action (entity kept),
    select.active_map.
  * T3 fail_closed — camera.obstacle_photo.

→ 11 entities vanish when off (create_patrol_point is a service; the firmware
  entity stays — only its install raises), 2 actions raise.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.dreame_a2_mower import button as button_platform
from custom_components.dreame_a2_mower import sensor as sensor_platform
from custom_components.dreame_a2_mower import select as select_platform
from custom_components.dreame_a2_mower import update as update_platform
from custom_components.dreame_a2_mower.camera import async_setup_entry as camera_setup
from custom_components.dreame_a2_mower.const import (
    CONF_EXPERIMENTAL_FEATURES,
    DOMAIN,
    EXPERIMENTAL_T1_SPECULATIVE,
    EXPERIMENTAL_T2_WIRE_UNEXERCISED,
    EXPERIMENTAL_T3_FAIL_CLOSED,
)

from tests.factories import make_coordinator, make_entry, make_hass


# The 11 gated ENTITY keys (suffix of unique_id / descriptor key) that must
# vanish when the gate is off.
_GATED_SENSOR_KEYS = {
    "mpos",
    "s5p104_raw",
    "s5p105_raw",
    "s5p106_raw",
    "s5p107_raw",
    "s6p1_raw",
    "api_endpoints_supported",
    "novel_observations",
}
_N_GATED_ENTITIES = 11  # 8 sensors + refresh_mpos button + active_map select + obstacle_photo camera


def _make(hass, options):
    entry = make_entry(options=options)
    coord = make_coordinator(hass=hass, entry=entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    return entry, coord


def _capture(setup_callable, hass, entry):
    """Run a platform ``async_setup_entry`` and return the created entities."""
    captured: list = []

    def _add(entities, *a, **k):
        captured.extend(list(entities))

    import asyncio

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(setup_callable(hass, entry, _add))
    finally:
        loop.close()
    return captured


def _sensor_key(e) -> str | None:
    desc = getattr(e, "entity_description", None)
    return getattr(desc, "key", None)


def _has_uid_suffix(ents, suffix) -> bool:
    return any(
        (getattr(e, "_attr_unique_id", "") or "").endswith("_" + suffix)
        for e in ents
    )


def _find_by_uid_suffix(ents, suffix):
    return next(
        e
        for e in ents
        if (getattr(e, "_attr_unique_id", "") or "").endswith("_" + suffix)
    )


# ---------------------------------------------------------------------------
# sensor platform
# ---------------------------------------------------------------------------
def test_sensor_gated_absent_when_off():
    hass = make_hass()
    entry, _ = _make(hass, {CONF_EXPERIMENTAL_FEATURES: False})
    ents = _capture(sensor_platform.async_setup_entry, hass, entry)
    keys = {_sensor_key(e) for e in ents}
    assert _GATED_SENSOR_KEYS.isdisjoint(keys), (
        f"gated sensors leaked when off: {_GATED_SENSOR_KEYS & keys}"
    )


def test_sensor_gated_present_disabled_when_on():
    hass = make_hass()
    entry, _ = _make(hass, {CONF_EXPERIMENTAL_FEATURES: True})
    ents = _capture(sensor_platform.async_setup_entry, hass, entry)
    by_key = {_sensor_key(e): e for e in ents}
    for k in _GATED_SENSOR_KEYS:
        assert k in by_key, f"gated sensor {k} missing when gate on"
        assert by_key[k]._attr_entity_registry_enabled_default is False
        assert by_key[k].entity_description.experimental == EXPERIMENTAL_T1_SPECULATIVE


def test_sensor_count_delta_is_eight():
    hass_off = make_hass()
    e_off, _ = _make(hass_off, {CONF_EXPERIMENTAL_FEATURES: False})
    hass_on = make_hass()
    e_on, _ = _make(hass_on, {CONF_EXPERIMENTAL_FEATURES: True})
    off = _capture(sensor_platform.async_setup_entry, hass_off, e_off)
    on = _capture(sensor_platform.async_setup_entry, hass_on, e_on)
    assert len(on) - len(off) == len(_GATED_SENSOR_KEYS) == 8


# ---------------------------------------------------------------------------
# button platform — refresh_mpos (descriptorless, class-attr tier)
# ---------------------------------------------------------------------------
def test_button_refresh_mpos_gated():
    hass_off = make_hass()
    e_off, _ = _make(hass_off, {CONF_EXPERIMENTAL_FEATURES: False})
    hass_on = make_hass()
    e_on, _ = _make(hass_on, {CONF_EXPERIMENTAL_FEATURES: True})
    off = _capture(button_platform.async_setup_entry, hass_off, e_off)
    on = _capture(button_platform.async_setup_entry, hass_on, e_on)
    off_keys = {getattr(e, "_MOWER_KEY", None) for e in off}
    on_keys = {getattr(e, "_MOWER_KEY", None) for e in on}
    assert "refresh_mpos" not in off_keys
    assert "refresh_mpos" in on_keys
    assert len(on) - len(off) == 1
    refresh = next(e for e in on if getattr(e, "_MOWER_KEY", None) == "refresh_mpos")
    assert refresh._experimental_tier == EXPERIMENTAL_T1_SPECULATIVE
    assert refresh._attr_entity_registry_enabled_default is False


# ---------------------------------------------------------------------------
# select platform — active_map (descriptorless, class-attr tier)
# ---------------------------------------------------------------------------
def test_select_active_map_gated():
    hass_off = make_hass()
    e_off, _ = _make(hass_off, {CONF_EXPERIMENTAL_FEATURES: False})
    hass_on = make_hass()
    e_on, _ = _make(hass_on, {CONF_EXPERIMENTAL_FEATURES: True})
    off = _capture(select_platform.async_setup_entry, hass_off, e_off)
    on = _capture(select_platform.async_setup_entry, hass_on, e_on)
    assert not _has_uid_suffix(off, "active_map")
    assert _has_uid_suffix(on, "active_map")
    assert len(on) - len(off) == 1
    active = _find_by_uid_suffix(on, "active_map")
    assert active._experimental_tier == EXPERIMENTAL_T2_WIRE_UNEXERCISED
    assert active._attr_entity_registry_enabled_default is False


# ---------------------------------------------------------------------------
# camera platform — obstacle_photo (descriptorless, class-attr tier)
# ---------------------------------------------------------------------------
def test_camera_obstacle_photo_gated():
    hass_off = make_hass()
    e_off, _ = _make(hass_off, {CONF_EXPERIMENTAL_FEATURES: False})
    hass_on = make_hass()
    e_on, _ = _make(hass_on, {CONF_EXPERIMENTAL_FEATURES: True})
    off = _capture(camera_setup, hass_off, e_off)
    on = _capture(camera_setup, hass_on, e_on)
    assert not _has_uid_suffix(off, "obstacle_photo")
    assert _has_uid_suffix(on, "obstacle_photo")
    assert len(on) - len(off) == 1
    cam = _find_by_uid_suffix(on, "obstacle_photo")
    assert cam._experimental_tier == EXPERIMENTAL_T3_FAIL_CLOSED
    assert cam._attr_entity_registry_enabled_default is False


# ---------------------------------------------------------------------------
# update platform — firmware ENTITY stays; only the INSTALL action is gated
# ---------------------------------------------------------------------------
def test_update_firmware_entity_stays_when_off():
    """The firmware entity is NOT filtered out (version display is useful)."""
    hass = make_hass()
    entry, _ = _make(hass, {CONF_EXPERIMENTAL_FEATURES: False})
    ents = _capture(update_platform.async_setup_entry, hass, entry)
    assert len(ents) == 1
    assert not getattr(ents[0], "_experimental_tier", None)  # entity not gated


async def test_update_firmware_install_raises_when_off():
    from homeassistant.exceptions import HomeAssistantError

    hass = make_hass()
    entry, coord = _make(hass, {CONF_EXPERIMENTAL_FEATURES: False})
    ent = update_platform.DreameA2FirmwareUpdateEntity(coord)
    with pytest.raises(HomeAssistantError):
        await ent.async_install(None, False)


async def test_update_firmware_install_runs_when_on(monkeypatch):
    hass = make_hass()
    entry, coord = _make(hass, {CONF_EXPERIMENTAL_FEATURES: True})
    ent = update_platform.DreameA2FirmwareUpdateEntity(coord)

    called = {}

    async def _trigger():
        called["yes"] = True
        return True

    monkeypatch.setattr(coord, "async_trigger_firmware_update", _trigger, raising=False)
    await ent.async_install(None, False)  # must NOT raise the experimental guard
    assert called.get("yes") is True


# ---------------------------------------------------------------------------
# service create_patrol_point — raises when off (wired via experimental_service)
# ---------------------------------------------------------------------------
async def test_create_patrol_point_raises_when_off(monkeypatch):
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.dreame_a2_mower import services

    coord = SimpleNamespace(
        entry=SimpleNamespace(options={CONF_EXPERIMENTAL_FEATURES: False})
    )
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    call = SimpleNamespace(hass=SimpleNamespace(), data={"x": 1.0, "y": 2.0})
    with pytest.raises(ServiceValidationError):
        await services._handle_create_patrol_point(call)


async def test_create_patrol_point_runs_when_on(monkeypatch):
    from custom_components.dreame_a2_mower import services

    ran = {}

    async def _create_patrol_point(*a, **k):
        ran["yes"] = True
        return SimpleNamespace(ok=True)

    async def _run_map_edit(coro, *a, **k):
        await coro

    coord = SimpleNamespace(
        entry=SimpleNamespace(options={CONF_EXPERIMENTAL_FEATURES: True}),
        active_map_id=0,
        create_patrol_point=_create_patrol_point,
    )
    monkeypatch.setattr(services, "_coordinator_from_call", lambda hass, call: coord)
    monkeypatch.setattr(services, "_run_map_edit", _run_map_edit)
    call = SimpleNamespace(
        hass=SimpleNamespace(), data={"x": 1.0, "y": 2.0}
    )
    await services._handle_create_patrol_point(call)
    assert ran.get("yes") is True


# ---------------------------------------------------------------------------
# Aggregate: exactly 11 entities vanish across the four entity platforms
# ---------------------------------------------------------------------------
def test_total_gated_entity_delta_is_eleven():
    setups = [
        sensor_platform.async_setup_entry,
        button_platform.async_setup_entry,
        select_platform.async_setup_entry,
        camera_setup,
    ]
    delta = 0
    for setup in setups:
        hass_off = make_hass()
        e_off, _ = _make(hass_off, {CONF_EXPERIMENTAL_FEATURES: False})
        hass_on = make_hass()
        e_on, _ = _make(hass_on, {CONF_EXPERIMENTAL_FEATURES: True})
        off = _capture(setup, hass_off, e_off)
        on = _capture(setup, hass_on, e_on)
        delta += len(on) - len(off)
    assert delta == _N_GATED_ENTITIES == 11
