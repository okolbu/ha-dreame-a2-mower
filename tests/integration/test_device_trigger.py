"""Tests for the device_trigger platform (sub-task 2.3).

Test-env note
-------------
This repo's tests run against a VANILLA STUBBED Home Assistant
(`tests/conftest.py`), not real HA. The full
`homeassistant.components.device_automation` / `homeassistant.helpers.trigger`
machinery is NOT importable under the stub, so this module installs the few
extra `homeassistant.*` symbols `device_trigger.py` references at import time
— mirroring real HA's signatures faithfully — and then tests OUR logic, not
HA's trigger framework:

1. `async_get_triggers` returns one trigger dict per supported event type for
   a mower device (and `[]` for a foreign device).
2. The attach-time filtering: `async_attach_trigger` builds an event-trigger
   config that pins the bus event to THIS device's source `event.*` entity
   plus the configured `event_type`. We supply a faithful stand-in for the
   core event trigger that implements HA's event_data subset-match semantics,
   then prove the action fires for a matching `{entity_id, event_type}` event
   and does NOT fire for a mismatched device-entity or a mismatched type.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import voluptuous as vol

DOMAIN = "dreame_a2_mower"


# ---------------------------------------------------------------------------
# Extra homeassistant stubs that device_trigger.py needs at import time but
# the shared conftest doesn't provide. Installed once at module import.
# ---------------------------------------------------------------------------
def _install_device_trigger_stubs() -> None:
    # homeassistant.const additions
    const_mod = sys.modules["homeassistant.const"]
    for name, value in (
        ("CONF_DEVICE_ID", "device_id"),
        ("CONF_DOMAIN", "domain"),
        ("CONF_ENTITY_ID", "entity_id"),
        ("CONF_PLATFORM", "platform"),
        ("CONF_TYPE", "type"),
    ):
        if not hasattr(const_mod, name):
            setattr(const_mod, name, value)

    # homeassistant.core.CALLBACK_TYPE
    core_mod = sys.modules["homeassistant.core"]
    if not hasattr(core_mod, "CALLBACK_TYPE"):
        core_mod.CALLBACK_TYPE = object  # type: ignore[attr-defined]

    # homeassistant.components.device_automation.DEVICE_TRIGGER_BASE_SCHEMA
    if "homeassistant.components" not in sys.modules:
        sys.modules["homeassistant.components"] = types.ModuleType(
            "homeassistant.components"
        )
    da_mod = types.ModuleType("homeassistant.components.device_automation")
    # Real DEVICE_TRIGGER_BASE_SCHEMA requires platform/domain/device_id and
    # allows extra keys. Mirror the shape closely enough to .extend().
    da_mod.DEVICE_TRIGGER_BASE_SCHEMA = vol.Schema(  # type: ignore[attr-defined]
        {
            vol.Required("platform"): "device",
            vol.Required("domain"): str,
            vol.Required("device_id"): str,
        },
        extra=vol.ALLOW_EXTRA,
    )
    sys.modules["homeassistant.components.device_automation"] = da_mod

    # homeassistant.components.homeassistant.triggers.event — faithful stand-in
    ha_comp = types.ModuleType("homeassistant.components.homeassistant")
    triggers_pkg = types.ModuleType("homeassistant.components.homeassistant.triggers")
    event_mod = types.ModuleType(
        "homeassistant.components.homeassistant.triggers.event"
    )
    event_mod.CONF_PLATFORM = "platform"  # type: ignore[attr-defined]
    event_mod.CONF_EVENT_TYPE = "event_type"  # type: ignore[attr-defined]
    event_mod.CONF_EVENT_DATA = "event_data"  # type: ignore[attr-defined]
    # The real TRIGGER_SCHEMA validates+normalises the event-trigger config;
    # here it just passes the dict through (we assert on its contents).
    event_mod.TRIGGER_SCHEMA = lambda cfg: cfg  # type: ignore[attr-defined]

    async def _async_attach_trigger(hass, config, action, trigger_info, *, platform_type):  # noqa: D401
        """Faithful subset-match stand-in for the core event trigger.

        Subscribes to config[event_type] on the fake bus and invokes `action`
        only when every key/value in config[event_data] is present-and-equal
        in the fired event's data — exactly HA's event-trigger semantics.
        """
        want_event = config[event_mod.CONF_EVENT_TYPE]
        want_data = config.get(event_mod.CONF_EVENT_DATA) or {}

        @hass.bus._callback
        def _listener(event):
            if event.event_type != want_event:
                return
            data = event.data or {}
            if all(data.get(k) == v for k, v in want_data.items()):
                action({"trigger": {"event": event}})

        return hass.bus.async_listen(want_event, _listener)

    event_mod.async_attach_trigger = _async_attach_trigger  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.homeassistant"] = ha_comp
    sys.modules["homeassistant.components.homeassistant.triggers"] = triggers_pkg
    sys.modules[
        "homeassistant.components.homeassistant.triggers.event"
    ] = event_mod

    # homeassistant.helpers.trigger — TriggerActionType / TriggerInfo
    trig_mod = types.ModuleType("homeassistant.helpers.trigger")
    trig_mod.TriggerActionType = object  # type: ignore[attr-defined]
    trig_mod.TriggerInfo = dict  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.trigger"] = trig_mod

    # homeassistant.helpers.typing — ConfigType
    typing_mod = types.ModuleType("homeassistant.helpers.typing")
    typing_mod.ConfigType = dict  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.typing"] = typing_mod

    # entity_registry needs async_entries_for_device + DeviceEntry on
    # device_registry. Add to the existing stub modules.
    er_mod = sys.modules["homeassistant.helpers.entity_registry"]
    if not hasattr(er_mod, "async_entries_for_device"):
        er_mod.async_entries_for_device = (  # type: ignore[attr-defined]
            lambda registry, device_id, include_disabled_entities=False: registry.async_entries_for_device(
                device_id, include_disabled_entities
            )
        )
    dr_mod = sys.modules["homeassistant.helpers.device_registry"]
    if not hasattr(dr_mod, "DeviceEntry"):
        dr_mod.DeviceEntry = object  # type: ignore[attr-defined]


_install_device_trigger_stubs()

from custom_components.dreame_a2_mower import device_trigger  # noqa: E402
from custom_components.dreame_a2_mower.const import (  # noqa: E402
    LIFECYCLE_EVENT_TYPES,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeDevice:
    def __init__(self, identifiers: set[tuple[str, str]]) -> None:
        self.identifiers = identifiers


class _FakeEntry:
    def __init__(self, entity_id: str, domain: str, platform: str, unique_id: str) -> None:
        self.entity_id = entity_id
        self.domain = domain
        self.platform = platform
        self.unique_id = unique_id


class _FakeDeviceRegistry:
    def __init__(self, devices: dict[str, _FakeDevice]) -> None:
        self._devices = devices

    def async_get(self, device_id: str) -> _FakeDevice | None:
        return self._devices.get(device_id)


class _FakeEntityRegistry:
    def __init__(self, entries_by_device: dict[str, list[_FakeEntry]]) -> None:
        self._entries_by_device = entries_by_device

    def async_entries_for_device(self, device_id, include_disabled_entities=False):
        return self._entries_by_device.get(device_id, [])


class _FakeEvent:
    def __init__(self, event_type: str, data: dict[str, Any]) -> None:
        self.event_type = event_type
        self.data = data


class _FakeBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list] = {}

    def _callback(self, fn):
        return fn

    def async_listen(self, event_type, listener):
        self._listeners.setdefault(event_type, []).append(listener)
        return lambda: self._listeners[event_type].remove(listener)

    def async_fire(self, event_type, data):
        for listener in list(self._listeners.get(event_type, ())):
            listener(_FakeEvent(event_type, data))


class _FakeHass:
    def __init__(self, dev_reg, ent_reg) -> None:
        self.bus = _FakeBus()
        self._dev_reg = dev_reg
        self._ent_reg = ent_reg


@pytest.fixture
def hass_with_mower(monkeypatch):
    """A fake hass whose registries hold one mower device with both event entities."""
    device_id = "mower-device-1"
    foreign_id = "other-device-9"
    dev_reg = _FakeDeviceRegistry(
        {
            device_id: _FakeDevice({(DOMAIN, "ABC123")}),
            foreign_id: _FakeDevice({("some_other_domain", "x")}),
        }
    )
    ent_reg = _FakeEntityRegistry(
        {
            device_id: [
                _FakeEntry(
                    "event.dreame_a2_mower_lifecycle",
                    "event",
                    DOMAIN,
                    "ABC123_lifecycle",
                ),
                _FakeEntry(
                    "event.dreame_a2_mower_notification",
                    "event",
                    DOMAIN,
                    "ABC123_notification",
                ),
                # a foreign-platform event entity on the same device should
                # be ignored by the resolver
                _FakeEntry("event.foo", "event", "other", "foo"),
            ],
        }
    )
    hass = _FakeHass(dev_reg, ent_reg)

    monkeypatch.setattr(device_trigger.dr, "async_get", lambda h: dev_reg)
    monkeypatch.setattr(device_trigger.er, "async_get", lambda h: ent_reg)

    return hass, device_id, foreign_id


# ---------------------------------------------------------------------------
# async_get_triggers
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_triggers_returns_one_per_supported_type(hass_with_mower):
    hass, device_id, _ = hass_with_mower
    triggers = await device_trigger.async_get_triggers(hass, device_id)

    types_returned = [t["type"] for t in triggers]
    assert types_returned == list(device_trigger.TRIGGER_TYPES)

    # Every trigger carries the platform/domain/device_id contract.
    for t in triggers:
        assert t["platform"] == "device"
        assert t["domain"] == DOMAIN
        assert t["device_id"] == device_id

    # All 11 lifecycle types are exposed.
    for et in LIFECYCLE_EVENT_TYPES:
        assert et in types_returned

    # High-value notification types are exposed; pure-noise ones are not.
    assert "human_detected" in types_returned
    assert "trapped" in types_returned          # was robot_trapped (code 2)
    assert "emergency_stop" in types_returned
    assert "blade_loss" in types_returned       # was blades_worn (code 28)
    assert "fault_detected" in types_returned  # lifecycle fault
    assert "unknown_s2p2" not in types_returned
    assert "maintenance_reminder" not in types_returned
    # notification mowing_started would collide with the lifecycle one
    assert types_returned.count("mowing_started") == 1


@pytest.mark.asyncio
async def test_get_triggers_empty_for_foreign_device(hass_with_mower):
    hass, _, foreign_id = hass_with_mower
    assert await device_trigger.async_get_triggers(hass, foreign_id) == []


@pytest.mark.asyncio
async def test_get_triggers_empty_for_unknown_device(hass_with_mower):
    hass, _, _ = hass_with_mower
    assert await device_trigger.async_get_triggers(hass, "no-such-device") == []


# ---------------------------------------------------------------------------
# async_attach_trigger filtering
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attach_lifecycle_fires_only_on_matching_event(hass_with_mower):
    hass, device_id, _ = hass_with_mower
    fired: list[Any] = []

    config = {
        "platform": "device",
        "domain": DOMAIN,
        "device_id": device_id,
        "type": "mowing_started",
    }
    await device_trigger.async_attach_trigger(
        hass, config, lambda data: fired.append(data), {}
    )

    bus_event = f"{DOMAIN}_event"

    # Matching: correct source entity + correct event_type -> fires.
    hass.bus.async_fire(
        bus_event,
        {
            "entity_id": "event.dreame_a2_mower_lifecycle",
            "event_type": "mowing_started",
            "data": {"at_unix": 1},
        },
    )
    assert len(fired) == 1

    # Wrong event_type on the same entity -> does NOT fire.
    hass.bus.async_fire(
        bus_event,
        {
            "entity_id": "event.dreame_a2_mower_lifecycle",
            "event_type": "mowing_ended",
            "data": {},
        },
    )
    assert len(fired) == 1

    # Right event_type but a DIFFERENT device's entity -> does NOT fire.
    hass.bus.async_fire(
        bus_event,
        {
            "entity_id": "event.some_other_mower_lifecycle",
            "event_type": "mowing_started",
            "data": {},
        },
    )
    assert len(fired) == 1


@pytest.mark.asyncio
async def test_attach_notification_pins_notification_entity(hass_with_mower):
    hass, device_id, _ = hass_with_mower
    fired: list[Any] = []

    config = {
        "platform": "device",
        "domain": DOMAIN,
        "device_id": device_id,
        "type": "human_detected",
    }
    await device_trigger.async_attach_trigger(
        hass, config, lambda data: fired.append(data), {}
    )

    bus_event = f"{DOMAIN}_event"

    # Notification trigger must pin the NOTIFICATION entity, not lifecycle.
    hass.bus.async_fire(
        bus_event,
        {
            "entity_id": "event.dreame_a2_mower_notification",
            "event_type": "human_detected",
            "data": {"text": "Person detected"},
        },
    )
    assert len(fired) == 1

    # Same type but arriving (impossibly) from the lifecycle entity -> no fire,
    # proving the resolver pinned the notification entity specifically.
    hass.bus.async_fire(
        bus_event,
        {
            "entity_id": "event.dreame_a2_mower_lifecycle",
            "event_type": "human_detected",
            "data": {},
        },
    )
    assert len(fired) == 1


def test_source_entity_resolution_picks_right_entity(hass_with_mower):
    hass, device_id, _ = hass_with_mower
    # lifecycle type -> lifecycle entity
    assert (
        device_trigger._source_entity_id_for_type(hass, device_id, "mowing_started")
        == "event.dreame_a2_mower_lifecycle"
    )
    # notification type -> notification entity
    assert (
        device_trigger._source_entity_id_for_type(hass, device_id, "human_detected")
        == "event.dreame_a2_mower_notification"
    )


def test_exposed_triggers_use_corrected_catalog_slugs():
    from custom_components.dreame_a2_mower.device_trigger import (
        _EXPOSED_NOTIFICATION_EVENT_TYPES as EXP, TRIGGER_TYPES,
    )
    from custom_components.dreame_a2_mower.mower.error_codes import S2P2_EVENT_TYPES
    assert "back_charge_failed" in EXP            # was positioning_failed_stuck (31)
    assert "go_to_cleanpoint_success" in EXP       # was arrived_at_maintenance_point (75)
    assert "trapped" in EXP                        # was robot_trapped (2)
    for stale in ("positioning_failed_stuck", "robot_trapped", "arrived_at_maintenance_point"):
        assert stale not in EXP
    valid = set(S2P2_EVENT_TYPES.values())
    for slug in EXP:
        assert slug in valid, f"exposed trigger {slug!r} not a derived slug"
    assert set(EXP) <= set(TRIGGER_TYPES)


def _trigger_labels(rel: str) -> dict:
    root = Path(__file__).resolve().parents[2] / "custom_components" / "dreame_a2_mower"
    data = json.loads((root / rel).read_text(encoding="utf-8"))
    return data["device_automation"]["trigger_type"]


def test_every_trigger_type_has_a_label_in_both_files():
    for rel in ("strings.json", "translations/en.json"):
        labels = _trigger_labels(rel)
        missing = [t for t in device_trigger.TRIGGER_TYPES if t not in labels]
        assert not missing, f"{rel} trigger_type missing labels for: {missing}"


def test_no_stale_old_trigger_slugs_remain():
    stale = {
        "robot_trapped", "blades_worn", "left_wheel_error", "right_wheel_error",
        "positioning_failed_stuck", "positioning_failed_transient",
        "failed_to_start_task", "battery_temp_low_charging_paused",
        "low_battery_return", "rain_protection",
        "standby_outside_station_too_long", "paused_too_long_returning",
        "arrived_at_maintenance_point", "cannot_reach_maintenance_point",
    }
    for rel in ("strings.json", "translations/en.json"):
        labels = set(_trigger_labels(rel))
        leftover = stale & labels
        assert not leftover, f"{rel} still has stale trigger_type keys: {leftover}"
