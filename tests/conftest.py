"""Pytest configuration shared by protocol/ + mower/ + integration/ tests.

Per spec §3, the protocol/ + mower/ test suites must run in a vanilla
pytest venv (no Home Assistant required). The integration/ test suite
adds pytest-homeassistant-custom-component fixtures separately.
"""
from __future__ import annotations

import dataclasses
import enum
import sys
import types
from pathlib import Path
from typing import Any

import pytest

# Make the top-level protocol/ package importable in tests
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Stub the ``homeassistant`` package so that the custom_components package
# __init__.py can be imported without a full HA install.  Only the names
# that the integration's layer-3 glue code references at import time are
# needed here; the integration/ tests that need real HA fixtures use
# pytest-homeassistant-custom-component instead.
# ---------------------------------------------------------------------------
def _make_ha_stub() -> None:
    """Inject minimal homeassistant stubs into sys.modules.

    Clears any broken/partial homeassistant install first so that the
    stub takes precedence even if a system package is partially installed.
    """
    # Remove any pre-existing (possibly broken) homeassistant modules
    for key in list(sys.modules):
        if key == "homeassistant" or key.startswith("homeassistant."):
            del sys.modules[key]

    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    # homeassistant.core
    core_mod = types.ModuleType("homeassistant.core")
    core_mod.HomeAssistant = object  # type: ignore[attr-defined]
    core_mod.callback = lambda f: f  # type: ignore[attr-defined]

    class _ServiceCallStub:  # noqa: D101
        """Stub for homeassistant.core.ServiceCall used by services.py."""

        def __init__(self, hass=None, domain="", service="", data=None):
            self.hass = hass
            self.domain = domain
            self.service = service
            self.data = data or {}

    core_mod.ServiceCall = _ServiceCallStub  # type: ignore[attr-defined]
    sys.modules["homeassistant.core"] = core_mod

    # homeassistant.config_entries
    ce_mod = types.ModuleType("homeassistant.config_entries")
    ce_mod.ConfigEntry = object  # type: ignore[attr-defined]

    # F7.7.1: ConfigFlow stub that accepts domain= keyword in __init_subclass__.
    class _ConfigFlowStub:  # noqa: D101
        """Stub ConfigFlow — accepts domain= keyword so config_flow.py parses."""

        def __init_subclass__(cls, domain=None, **kwargs):  # noqa: D105
            super().__init_subclass__(**kwargs)

    ce_mod.ConfigFlow = _ConfigFlowStub  # type: ignore[attr-defined]

    # F7.7.1: OptionsFlow base class stub
    class _OptionsFlowStub:  # noqa: D101
        config_entry = None

        def async_create_entry(self, title="", data=None):  # noqa: D102
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(self, **kwargs):  # noqa: D102
            return {"type": "form", **kwargs}

    ce_mod.OptionsFlow = _OptionsFlowStub  # type: ignore[attr-defined]
    sys.modules["homeassistant.config_entries"] = ce_mod

    # homeassistant.data_entry_flow — FlowResult used by config_flow.py
    def_mod = types.ModuleType("homeassistant.data_entry_flow")
    def_mod.FlowResult = dict  # type: ignore[attr-defined]
    sys.modules["homeassistant.data_entry_flow"] = def_mod

    # homeassistant.helpers.update_coordinator
    helpers_mod = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers_mod
    uc_mod = types.ModuleType("homeassistant.helpers.update_coordinator")

    class _DataUpdateCoordinatorStub:  # noqa: D101
        """Faithful-minimal stub of homeassistant DataUpdateCoordinator.

        P3 Task 1 (T7-7/T7-8, R-16): upgraded from a bare no-__init__ shell so
        the REAL ``DreameA2MowerCoordinator.__init__`` can run in tests (via
        ``tests/factories.py:make_coordinator``). Mirrors the real HA wheel's
        semantics for exactly the surface the integration uses (the
        async_set_updated_data core was verified against the real
        homeassistant wheel source in the P2.6 review):

        - ``__init__`` stores hass/logger/name/update_interval, seeds
          ``data=None`` and ``last_update_success=True``, and creates the
          listener registry.
        - ``async_set_updated_data(data)`` does ``self.data = data``, sets
          ``last_update_success = True``, then ``async_update_listeners()``
          — exactly the real method's observable core (the real method also
          cancels/reschedules the poll timer; this integration is push-based
          with ``update_interval=None`` so there is nothing to cancel).
        - ``async_add_listener`` returns a WORKING unsubscribe. (Real HA
          2025.12 keys ``_listeners`` by an incrementing int id and pops
          without a default on remove, so a double-unsub raises KeyError;
          this stub keys by the remove-callback but likewise pops WITHOUT a
          default, so a double-unsub bug surfaces in tests instead of being
          silently tolerated.)

        NOTE: ``_listeners`` is accessed via ``__dict__.setdefault`` so
        legacy ``object.__new__``-built coordinators (census-gated ratchet,
        tests/audit/test_no_new_coordinator_bypass.py) don't AttributeError
        when production code broadcasts through the class method.
        """

        def __init__(
            self,
            hass,
            logger,
            *,
            name,
            update_interval=None,
            **kwargs,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None
            self.last_update_success = True
            self._listeners: dict = {}

        def __class_getitem__(cls, item):  # type: ignore[override]
            return cls

        def async_add_listener(self, update_callback, context=None):
            """Mirror real HA: register a listener, return its unsubscribe."""
            listeners = self.__dict__.setdefault("_listeners", {})

            def remove_listener() -> None:
                # No default: real HA raises KeyError on double-remove, so a
                # double-unsub bug surfaces here rather than being swallowed.
                del listeners[remove_listener]

            listeners[remove_listener] = (update_callback, context)
            return remove_listener

        def async_update_listeners(self) -> None:
            """Mirror real HA: invoke every registered listener callback."""
            for update_callback, _ctx in list(
                self.__dict__.setdefault("_listeners", {}).values()
            ):
                update_callback()

        def async_set_updated_data(self, data) -> None:
            """Manually update data + notify listeners (real-HA semantics)."""
            self.data = data
            self.last_update_success = True
            self.async_update_listeners()

        async def async_config_entry_first_refresh(self) -> None:
            """Minimal first-refresh: run _async_update_data, keep the result.

            The real method wraps ``_async_refresh`` with setup-retry
            plumbing; the observable contract the integration relies on is:
            run the first update, store the returned data, and let
            ``ConfigEntryNotReady`` propagate to ``async_setup_entry``.
            """
            self.data = await self._async_update_data()
            self.last_update_success = True

    class _CoordinatorEntityStub:  # noqa: D101
        """Minimal stub — supports CoordinatorEntity[T] subscript and init."""

        # Real CoordinatorEntity.available reflects
        # coordinator.last_update_success (True for a healthy push-based
        # coordinator). The stub mirrors that as a constant True so that
        # entity ``available`` overrides ending in ``super().available``
        # (and the Phase-1.1 _FreshnessAvailableMixin) resolve in tests
        # exactly as they do in production.
        available = True

        def __class_getitem__(cls, item):  # type: ignore[override]
            return cls

        def __init__(self, coordinator: object) -> None:
            self.coordinator = coordinator

        def _handle_coordinator_update(self) -> None:
            """No-op stub — subclasses call super() safely in tests."""
            if hasattr(self, "async_write_ha_state"):
                self.async_write_ha_state()

        async def async_added_to_hass(self) -> None:
            """No-op stub — subclasses that restore from last_state
            call super().async_added_to_hass() at the top of their
            override; this keeps that path working in tests."""
            return None

    uc_mod.DataUpdateCoordinator = _DataUpdateCoordinatorStub  # type: ignore[attr-defined]
    uc_mod.CoordinatorEntity = _CoordinatorEntityStub  # type: ignore[attr-defined]
    uc_mod.UpdateFailed = Exception  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.update_coordinator"] = uc_mod

    # homeassistant.helpers.entity
    he_mod = types.ModuleType("homeassistant.helpers.entity")
    he_mod.Entity = object  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.entity"] = he_mod

    # homeassistant.helpers.entity_platform
    hep_mod = types.ModuleType("homeassistant.helpers.entity_platform")
    hep_mod.AddEntitiesCallback = object  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.entity_platform"] = hep_mod

    # homeassistant.helpers.event
    he_mod = types.ModuleType("homeassistant.helpers.event")
    he_mod.async_track_time_interval = lambda hass, action, interval: (lambda: None)  # type: ignore[attr-defined]
    he_mod.async_call_later = lambda hass, delay, action: (lambda: None)  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.event"] = he_mod

    # homeassistant.helpers.config_validation — used by services.py
    cv_mod = types.ModuleType("homeassistant.helpers.config_validation")

    def _ensure_list(value):
        """Stub for cv.ensure_list."""
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    cv_mod.ensure_list = _ensure_list  # type: ignore[attr-defined]

    def _boolean(value) -> bool:
        """Stub for cv.boolean — mirrors HA's string-bool parsing."""
        import voluptuous as _vol
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        if isinstance(value, str):
            lower = value.lower()
            if lower in ("true", "yes", "on", "1", "enable", "enabled"):
                return True
            if lower in ("false", "no", "off", "0", "disable", "disabled"):
                return False
        raise _vol.Invalid(f"invalid boolean value {value!r}")

    cv_mod.boolean = _boolean  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.config_validation"] = cv_mod

    # homeassistant.components.sensor
    sensor_mod = types.ModuleType("homeassistant.components.sensor")

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class _SensorEntityDescription:  # noqa: D101
        key: str = ""
        name: str = ""
        translation_key: str | None = None
        icon: str | None = None
        device_class: object = None
        state_class: object = None
        native_unit_of_measurement: str | None = None
        suggested_display_precision: int | None = None
        options: list | None = None
        entity_category: object = None
        entity_registry_enabled_default: bool = True

    class _SensorDeviceClass:  # noqa: D101
        """Stub enum-like for SensorDeviceClass — provides common attributes."""
        AREA = "area"
        BATTERY = "battery"
        DATE = "date"
        DISTANCE = "distance"
        DURATION = "duration"
        ENUM = "enum"
        SIGNAL_STRENGTH = "signal_strength"
        TIMESTAMP = "timestamp"

    class _SensorStateClass:  # noqa: D101
        """Stub enum-like for SensorStateClass."""
        MEASUREMENT = "measurement"
        TOTAL_INCREASING = "total_increasing"

    sensor_mod.SensorEntity = object  # type: ignore[attr-defined]
    sensor_mod.SensorEntityDescription = _SensorEntityDescription  # type: ignore[attr-defined]
    sensor_mod.SensorDeviceClass = _SensorDeviceClass  # type: ignore[attr-defined]
    sensor_mod.SensorStateClass = _SensorStateClass  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.sensor"] = sensor_mod

    # homeassistant.components.binary_sensor
    bs_mod = types.ModuleType("homeassistant.components.binary_sensor")

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class _BinarySensorEntityDescription:  # noqa: D101
        key: str = ""
        name: str = ""
        translation_key: str | None = None
        device_class: object = None
        entity_category: object = None

    class _BinarySensorDeviceClass:  # noqa: D101
        """Stub enum-like for BinarySensorDeviceClass."""
        CONNECTIVITY = "connectivity"
        MOISTURE = "moisture"
        MOTION = "motion"
        OCCUPANCY = "occupancy"
        OPENING = "opening"
        PROBLEM = "problem"
        RUNNING = "running"
        SAFETY = "safety"

    bs_mod.BinarySensorEntity = object  # type: ignore[attr-defined]
    bs_mod.BinarySensorEntityDescription = _BinarySensorEntityDescription  # type: ignore[attr-defined]
    bs_mod.BinarySensorDeviceClass = _BinarySensorDeviceClass  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.binary_sensor"] = bs_mod

    # homeassistant.components.lawn_mower
    lm_mod = types.ModuleType("homeassistant.components.lawn_mower")

    class _LawnMowerEntity:  # noqa: D101
        """Stub LawnMowerEntity — proper class (not bare `object`) so that
        class DreameA2LawnMower(CoordinatorEntity, LawnMowerEntity, RestoreEntity)
        can resolve a valid MRO without the 'object' conflict."""

    class _LawnMowerActivity(str):  # noqa: D101
        """Stub LawnMowerActivity that behaves like an enum (raises on unknown)."""
        MOWING = "mowing"
        DOCKED = "docked"
        PAUSED = "paused"
        RETURNING = "returning"
        ERROR = "error"

        def __new__(cls, value):  # noqa: D107
            known = {"mowing", "docked", "paused", "returning", "error"}
            if value not in known:
                raise ValueError(f"Unknown LawnMowerActivity: {value!r}")
            return str.__new__(cls, value)

    class _LawnMowerEntityFeature:  # noqa: D101
        START_MOWING = 1
        PAUSE = 2
        DOCK = 4

    lm_mod.LawnMowerEntity = _LawnMowerEntity  # type: ignore[attr-defined]
    lm_mod.LawnMowerActivity = _LawnMowerActivity  # type: ignore[attr-defined]
    lm_mod.LawnMowerEntityFeature = _LawnMowerEntityFeature  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.lawn_mower"] = lm_mod

    # homeassistant.components.number — used by number.py entity builders
    num_mod = types.ModuleType("homeassistant.components.number")

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class _NumberEntityDescription:  # noqa: D101
        key: str = ""
        name: str = ""
        native_min_value: float = 0
        native_max_value: float = 100
        native_step: float = 1
        native_unit_of_measurement: str = ""
        mode: object = None
        entity_category: object = None

    class _NumberMode:  # noqa: D101
        SLIDER = "slider"
        BOX = "box"

    num_mod.NumberEntity = object  # type: ignore[attr-defined]
    num_mod.NumberEntityDescription = _NumberEntityDescription  # type: ignore[attr-defined]
    num_mod.NumberMode = _NumberMode  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.number"] = num_mod

    # homeassistant.components.switch — used by switch.py entity builders
    sw_mod = types.ModuleType("homeassistant.components.switch")

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class _SwitchEntityDescription:  # noqa: D101
        key: str = ""
        name: str = ""
        icon: str = ""
        entity_category: object = None

    sw_mod.SwitchEntity = object  # type: ignore[attr-defined]
    sw_mod.SwitchEntityDescription = _SwitchEntityDescription  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.switch"] = sw_mod

    # homeassistant.components.button — used by button.py entity
    btn_mod = types.ModuleType("homeassistant.components.button")
    btn_mod.ButtonEntity = object  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.button"] = btn_mod

    # homeassistant.components.update — used by update.py firmware entity
    upd_mod = types.ModuleType("homeassistant.components.update")

    class _UpdateEntity:  # noqa: D101
        """Minimal stub mirroring homeassistant.components.update.UpdateEntity."""

    class _UpdateEntityFeature(enum.IntFlag):  # noqa: D101
        INSTALL = 1
        SPECIFIC_VERSION = 2
        PROGRESS = 4
        BACKUP = 8
        RELEASE_NOTES = 16

    upd_mod.UpdateEntity = _UpdateEntity  # type: ignore[attr-defined]
    upd_mod.UpdateEntityFeature = _UpdateEntityFeature  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.update"] = upd_mod

    # homeassistant.components.device_tracker — used by device_tracker.py entity
    dt_mod = types.ModuleType("homeassistant.components.device_tracker")

    class _SourceType:  # noqa: D101
        GPS = "gps"

    class _TrackerEntity:  # noqa: D101
        """Minimal stub — a distinct class (not bare object) so subclasses
        that also inherit RestoreEntity get a consistent MRO."""

    dt_mod.SourceType = _SourceType  # type: ignore[attr-defined]
    dt_mod.TrackerEntity = _TrackerEntity  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.device_tracker"] = dt_mod

    # homeassistant.components.calendar — used by calendar.py entity
    cal_mod = types.ModuleType("homeassistant.components.calendar")

    class _CalendarEntityStub:  # noqa: D101
        pass

    @dataclasses.dataclass
    class _CalendarEventStub:  # noqa: D101
        start: Any
        end: Any
        summary: str = ""
        description: str = ""
        uid: str = ""

    cal_mod.CalendarEntity = _CalendarEntityStub  # type: ignore[attr-defined]
    cal_mod.CalendarEvent = _CalendarEventStub  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.calendar"] = cal_mod

    # homeassistant.components.camera — used by camera.py entity
    cam_mod = types.ModuleType("homeassistant.components.camera")

    class _CameraStub:  # noqa: D101
        """Minimal stub for Camera base class."""

        def __init__(self) -> None:
            pass

    cam_mod.Camera = _CameraStub  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.camera"] = cam_mod

    # homeassistant.components.http — used by camera.py LidarPcdDownloadView
    http_mod = types.ModuleType("homeassistant.components.http")

    class _HomeAssistantViewStub:  # noqa: D101
        """Minimal stub for HomeAssistantView base class."""

        url = ""
        name = ""
        requires_auth = False

        async def get(self, request):  # noqa: D102
            raise NotImplementedError

    http_mod.HomeAssistantView = _HomeAssistantViewStub  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.http"] = http_mod

    # homeassistant.components.time — used by time.py entity builders
    time_mod = types.ModuleType("homeassistant.components.time")

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class _TimeEntityDescription:  # noqa: D101
        key: str = ""
        name: str = ""
        icon: str = ""
        entity_category: object = None

    time_mod.TimeEntity = object  # type: ignore[attr-defined]
    time_mod.TimeEntityDescription = _TimeEntityDescription  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.time"] = time_mod

    # homeassistant.components.select — used by select.py entity builders
    sel_mod = types.ModuleType("homeassistant.components.select")

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class _SelectEntityDescription:  # noqa: D101
        key: str = ""
        name: str = ""
        translation_key: str = ""
        icon: str = ""
        options: tuple = ()
        entity_category: object = None

    class _SelectEntity:  # noqa: D101
        pass

    sel_mod.SelectEntity = _SelectEntity  # type: ignore[attr-defined]
    sel_mod.SelectEntityDescription = _SelectEntityDescription  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.select"] = sel_mod

    # homeassistant.helpers.device_registry — DeviceInfo used by all entity classes
    dr_mod = types.ModuleType("homeassistant.helpers.device_registry")

    class _DeviceInfo(dict):  # noqa: D101
        pass

    class _DeviceRegistry:  # noqa: D101
        """Minimal stub for device_registry returned by async_get."""

        def __init__(self):
            self.devices = {}

        def async_get_device(self, identifiers=None, connections=None):  # noqa: D102
            return None

        def async_get_or_create(self, **kwargs):  # noqa: D102
            return None

        def async_update_device(self, device_id, **kwargs):  # noqa: D102
            pass

        def async_remove_device(self, device_id):  # noqa: D102
            pass

    dr_mod.DeviceInfo = _DeviceInfo  # type: ignore[attr-defined]
    dr_mod.CONNECTION_NETWORK_MAC = "mac"  # type: ignore[attr-defined]
    dr_mod.async_get = lambda hass: _DeviceRegistry()  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.device_registry"] = dr_mod

    # homeassistant.helpers.entity_registry — used by entity platform tests
    er_mod = types.ModuleType("homeassistant.helpers.entity_registry")

    class _RegistryEntry:  # noqa: D101
        entity_id: str = ""
        unique_id: str = ""
        config_entry_id: str | None = None

    class _EntityRegistry:  # noqa: D101
        entities: dict = {}

        def async_update_entity(self, entity_id, **kwargs):  # noqa: D102
            pass

    er_mod.RegistryEntry = _RegistryEntry  # type: ignore[attr-defined]
    er_mod.EntityRegistry = _EntityRegistry  # type: ignore[attr-defined]
    er_mod.async_get = lambda hass: _EntityRegistry()  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.entity_registry"] = er_mod

    # homeassistant.helpers.entity — EntityCategory used by all entity files
    he_mod2 = types.ModuleType("homeassistant.helpers.entity")

    class _EntityCategory:  # noqa: D101
        DIAGNOSTIC = "diagnostic"
        CONFIG = "config"

    he_mod2.Entity = object  # type: ignore[attr-defined]
    he_mod2.EntityCategory = _EntityCategory  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.entity"] = he_mod2

    # homeassistant.helpers.restore_state — RestoreEntity used by selects to
    # persist user picks (action_mode, zone, spot) across HA restarts.
    rs_mod = types.ModuleType("homeassistant.helpers.restore_state")

    class _RestoreEntity:  # noqa: D101
        async def async_added_to_hass(self) -> None:  # noqa: D102
            """No-op stub — subclasses call super() safely in tests."""

        async def async_get_last_state(self):  # noqa: D401
            return None

    rs_mod.RestoreEntity = _RestoreEntity  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.restore_state"] = rs_mod

    # homeassistant.helpers.storage — Store stub for coordinator state persistence.
    stor_mod = types.ModuleType("homeassistant.helpers.storage")

    class _Store:  # noqa: D101
        """Minimal stub for homeassistant.helpers.storage.Store."""

        def __init__(self, hass, version, key):  # noqa: D107
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):  # noqa: D102
            return None

        async def async_save(self, data):  # noqa: D102
            pass

    stor_mod.Store = _Store  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.storage"] = stor_mod

    # homeassistant.const — expose common CONF_* and other constants
    const_mod = types.ModuleType("homeassistant.const")
    const_mod.CONF_USERNAME = "username"  # type: ignore[attr-defined]
    const_mod.CONF_PASSWORD = "password"  # type: ignore[attr-defined]
    const_mod.CONF_HOST = "host"  # type: ignore[attr-defined]
    const_mod.CONF_PORT = "port"  # type: ignore[attr-defined]
    const_mod.CONF_NAME = "name"  # type: ignore[attr-defined]
    const_mod.CONF_TOKEN = "token"  # type: ignore[attr-defined]
    const_mod.UnitOfLength = object  # type: ignore[attr-defined]
    const_mod.UnitOfArea = object  # type: ignore[attr-defined]
    const_mod.UnitOfTime = object  # type: ignore[attr-defined]
    const_mod.PERCENTAGE = "%"  # type: ignore[attr-defined]
    sys.modules["homeassistant.const"] = const_mod

    # homeassistant.exceptions
    exc_mod = types.ModuleType("homeassistant.exceptions")

    class _HomeAssistantError(Exception):
        """Stub mirroring homeassistant.exceptions.HomeAssistantError."""

    class _ServiceValidationError(_HomeAssistantError):
        """Stub mirroring homeassistant.exceptions.ServiceValidationError.

        In real HA, ServiceValidationError subclasses HomeAssistantError; keep
        that relationship so `except HomeAssistantError` catches both.
        """

    class _ConfigEntryNotReady(_HomeAssistantError):
        """Stub mirroring homeassistant.exceptions.ConfigEntryNotReady.

        Real HA: raising this from `async_setup_entry` (or from a coordinator's
        first `_async_update_data` via `async_config_entry_first_refresh`)
        tells the config-entry setup manager to retry with backoff instead of
        marking the entry failed. Kept as a DISTINCT subclass (not aliased to
        bare `Exception`) so `pytest.raises(ConfigEntryNotReady)` can't be
        satisfied by an unrelated bug like `AttributeError` — see
        tests/integration/test_setup_cloud_blip.py (P2 Task 2 / T3-2 / R-5).
        """

    class _ConfigEntryAuthFailed(_HomeAssistantError):
        """Stub mirroring homeassistant.exceptions.ConfigEntryAuthFailed.

        Real HA: raising this from a config-entry setup path (or from a
        coordinator's first refresh) marks the entry as needing
        reauthentication and starts the reauth flow. Task 2 (P6.1b) — kept
        as a DISTINCT subclass (not aliased to ``ConfigEntryNotReady`` or a
        bare ``Exception``) so ``pytest.raises(ConfigEntryAuthFailed)``
        can't be satisfied by an unrelated ``ConfigEntryNotReady``/bug, and
        so a test can assert the two are NOT confused with each other.
        """

    exc_mod.HomeAssistantError = _HomeAssistantError  # type: ignore[attr-defined]
    exc_mod.ServiceValidationError = _ServiceValidationError  # type: ignore[attr-defined]
    exc_mod.ConfigEntryNotReady = _ConfigEntryNotReady  # type: ignore[attr-defined]
    exc_mod.ConfigEntryAuthFailed = _ConfigEntryAuthFailed  # type: ignore[attr-defined]
    sys.modules["homeassistant.exceptions"] = exc_mod


_make_ha_stub()

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the tests/fixtures directory."""
    return FIXTURES
