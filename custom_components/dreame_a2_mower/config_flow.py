"""Config flow for Dremae Mower."""

from __future__ import annotations
from typing import Any, Final
import logging
import re

_LOGGER = logging.getLogger(__name__)
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from collections.abc import Mapping
from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.device_registry import format_mac
from homeassistant.components import persistent_notification
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)

from .dreame import DreameMowerProtocol, MAP_COLOR_SCHEME_LIST, MAP_ICON_SET_LIST

from .const import (
    DOMAIN,
    CONF_NOTIFY,
    CONF_COLOR_SCHEME,
    CONF_ICON_SET,
    CONF_COUNTRY,
    CONF_ACCOUNT_TYPE,
    CONF_MAC,
    CONF_DID,
    CONF_MAP_OBJECTS,
    CONF_PREFER_CLOUD,
    CONF_LOW_RESOLUTION,
    CONF_SQUARE,
    CONF_MQTT_ARCHIVE,
    CONF_MQTT_ARCHIVE_RETAIN_DAYS,
    DEFAULT_MQTT_ARCHIVE_RETAIN_DAYS,
    CONF_STATION_BEARING,
    CONF_SESSION_ARCHIVE_KEEP,
    DEFAULT_SESSION_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_KEEP,
    NOTIFICATION,
    MAP_OBJECTS,
    NOTIFICATION_ID_2FA_LOGIN,
    NOTIFICATION_2FA_LOGIN,
)

from .live_map import OPT_X_FACTOR, OPT_Y_FACTOR, DEFAULT_X_FACTOR, DEFAULT_Y_FACTOR

DREAME_MODELS = [
    "dreame.mower.",
    "mova.mower.",
]

model_map = {
    "dreame.mower.p2255": "A1",
    "dreame.mower.g2422": "A1 Pro",
    "dreame.mower.g2408": "A2",
    "dreame.mower.g2568a": "A2 1200",
    "dreame.mower.g3255": "A3",
}

DREAMEHOME: Final = "Dreamehome Account"
MOVAHOME: Final = "Mova Account"
LOCAL: Final = "Manual Connection (Without map)"


class DreameMowerOptionsFlowHandler(OptionsFlow):
    """Handle Dreame Mower options."""

    # config_entry is auto-set by HA's OptionsFlowHandler base class after
    # async_get_options_flow constructs us; don't assign it here.

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage Dreame/Mova Mower options."""
        errors = {}
        data = self.config_entry.data
        options = self.config_entry.options

        if user_input is not None:
            return self.async_create_entry(title="", data={**options, **user_input})

        notify = options.get(CONF_NOTIFY, list(NOTIFICATION.keys()))
        if isinstance(notify, bool):
            if notify is True:
                notify = list(NOTIFICATION.keys())
            else:
                notify = []

        data_schema = vol.Schema(
            {vol.Required(CONF_NOTIFY, default=notify): cv.multi_select(NOTIFICATION)}
        )
        if data.get(CONF_USERNAME):
            stored_scheme = options.get(CONF_COLOR_SCHEME, next(iter(MAP_COLOR_SCHEME_LIST)))
            if stored_scheme not in MAP_COLOR_SCHEME_LIST:
                stored_scheme = next(iter(MAP_COLOR_SCHEME_LIST))
            data_schema = data_schema.extend(
                {
                    vol.Required(
                        CONF_COLOR_SCHEME, default=stored_scheme
                    ): vol.In(list(MAP_COLOR_SCHEME_LIST.keys())),
                    vol.Required(
                        CONF_MAP_OBJECTS,
                        default=options.get(CONF_MAP_OBJECTS, list(MAP_OBJECTS.keys())),
                    ): cv.multi_select(MAP_OBJECTS),
                }
            )
            # CONF_PREFER_CLOUD toggle removed in Phase 5: cloud is
            # now the only transport. Existing options values will be
            # ignored.

            # Calibration factors for the live map.
            data_schema = data_schema.extend(
                {
                    vol.Optional(
                        OPT_X_FACTOR,
                        default=options.get(OPT_X_FACTOR, DEFAULT_X_FACTOR),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0)),
                    vol.Optional(
                        OPT_Y_FACTOR,
                        default=options.get(OPT_Y_FACTOR, DEFAULT_Y_FACTOR),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10.0)),
                    vol.Optional(
                        CONF_MQTT_ARCHIVE,
                        default=options.get(CONF_MQTT_ARCHIVE, False),
                    ): bool,
                    vol.Optional(
                        CONF_MQTT_ARCHIVE_RETAIN_DAYS,
                        default=options.get(
                            CONF_MQTT_ARCHIVE_RETAIN_DAYS,
                            DEFAULT_MQTT_ARCHIVE_RETAIN_DAYS,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=90)),
                    vol.Optional(
                        CONF_STATION_BEARING,
                        default=options.get(CONF_STATION_BEARING, 0.0),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=360.0)),
                    vol.Optional(
                        CONF_SESSION_ARCHIVE_KEEP,
                        default=options.get(
                            CONF_SESSION_ARCHIVE_KEEP,
                            DEFAULT_SESSION_ARCHIVE_KEEP,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
                    vol.Optional(
                        CONF_LIDAR_ARCHIVE_KEEP,
                        default=options.get(
                            CONF_LIDAR_ARCHIVE_KEEP,
                            DEFAULT_LIDAR_ARCHIVE_KEEP,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=200)),
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )


class DreameMowerFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle config flow for an Dreame Mower device."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self.entry: ConfigEntry | None = None
        self.mac: str | None = None
        self.model = None
        self.host: str | None = None
        self.token: str | None = None
        self.name: str | None = None
        self.username: str | None = None
        self.password: str | None = None
        self.country: str = "cn"
        self.account_type: str = "local"
        self.device_id: int | None = None
        self.prefer_cloud: bool = False
        self.low_resolution: bool = False
        self.square: bool = False
        self.devices: dict[str, dict[str, Any]] = {}
        self.protocol: DreameMowerProtocol | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> DreameMowerOptionsFlowHandler:
        """Get the options flow for this handler."""
        return DreameMowerOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user.

        Phase 2 cleanup: Mi/Xiaomi and Mova account types + the
        local-LAN miIO path are gone. The A2 only speaks Dreame cloud,
        so the user-facing chooser is redundant — jump straight to the
        Dreame cloud credentials step.
        """
        return await self.async_step_dreame()

    async def async_step_reauth(self, user_input: Mapping[str, Any]) -> FlowResult:
        """Perform reauth upon an authentication error or missing cloud credentials."""
        self.name = user_input.get(CONF_NAME)
        self.host = user_input.get(CONF_HOST)
        self.token = user_input.get(CONF_TOKEN)
        self.username = user_input.get(CONF_USERNAME)
        self.password = user_input.get(CONF_PASSWORD)
        self.country = user_input.get(CONF_COUNTRY, "cn")
        self.prefer_cloud = user_input.get(CONF_PREFER_CLOUD, False)
        self.account_type = user_input.get(CONF_ACCOUNT_TYPE, DREAMEHOME)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Dialog that informs the user that reauth is required."""
        if user_input is not None:
            return await self.async_step_cloud()
        return self.async_show_form(step_id="reauth_confirm")

    async def async_step_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Connect to a Dreame/Mova Mower device."""
        errors: dict[str, str] = {}
        if self.prefer_cloud or (self.token and len(self.token) == 32):
            try:
                if self.protocol is None:
                    self.protocol = DreameMowerProtocol(
                        self.host,
                        self.token,
                        self.username,
                        self.password,
                        self.country,
                        self.prefer_cloud,
                        self.account_type,
                    )
                else:
                    self.protocol.set_credentials(
                        self.host, self.token, account_type=self.account_type
                    )

                if self.protocol.device_cloud:
                    self.protocol.device_cloud._did = self.device_id

                if (
                    (self.account_type != "dreame" and self.account_type != "mova")
                    or self.mac is None
                    or self.model is None
                ):
                    info = await self.hass.async_add_executor_job(
                        self.protocol.connect, 5
                    )
                    if info:
                        self.mac = info["mac"]
                        self.model = info["model"]
            except Exception as ex:
                _LOGGER.error("Connection failed: %s", ex)
                errors["base"] = "cannot_connect"
            else:
                if self.mac:
                    await self.async_set_unique_id(format_mac(self.mac))
                    self._abort_if_unique_id_configured(
                        updates={
                            CONF_HOST: self.host,
                            CONF_TOKEN: self.token,
                            CONF_MAC: self.mac,
                            CONF_DID: self.device_id,
                        }
                    )

                if any(self.model.startswith(prefix) for prefix in DREAME_MODELS):
                    if self.name is None:
                        self.name = self.model
                    return await self.async_step_options()
                else:
                    errors["base"] = "unsupported"

            if self.username and self.password:
                return await self.async_step_dreame(errors=errors)
        else:
            errors["base"] = "wrong_token"
        # Fall through to the Dreame step for re-auth — the local step
        # was removed in Phase 2 cleanup.
        return await self.async_step_dreame(errors=errors)

    # step_local removed 2026-04-20 (Cleanup Phase 2): A2 only uses Dreame cloud.

    # step_mi removed 2026-04-20 (Cleanup Phase 2): A2 only uses Dreame cloud.

    async def async_step_dreame(
        self,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, Any] | None = {},
    ) -> FlowResult:
        """Configure a dreame mower device through the Miio Cloud."""
        placeholders = {}
        if user_input is not None:
            self.account_type = "dreame"
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)
            country = user_input.get(CONF_COUNTRY)

            if username and password and country:
                self.username = username
                self.password = password
                self.country = country
                self.prefer_cloud = True

                self.protocol = DreameMowerProtocol(
                    username=self.username,
                    password=self.password,
                    country=self.country,
                    prefer_cloud=self.prefer_cloud,
                    account_type="dreame",
                )
                await self.hass.async_add_executor_job(self.protocol.cloud.login)

                if self.protocol.cloud.logged_in is False:
                    errors["base"] = "login_error"
                elif self.protocol.cloud.logged_in:
                    persistent_notification.dismiss(
                        self.hass, f"{DOMAIN}_{NOTIFICATION_ID_2FA_LOGIN}"
                    )

                    devices = await self.hass.async_add_executor_job(
                        self.protocol.cloud.get_devices
                    )
                    if devices:
                        found = list(
                            filter(
                                lambda d: any(
                                    str(d["model"]).startswith(prefix)
                                    for prefix in DREAME_MODELS
                                ),
                                devices["page"]["records"],
                            )
                        )

                        self.devices = {}
                        for device in found:
                            name = (
                                device["customName"]
                                if device["customName"]
                                and len(device["customName"]) > 0
                                else device["deviceInfo"]["displayName"]
                            )
                            modelId = device["model"]
                            model = model_map.get(modelId, modelId)
                            list_name = f"{name} - {model} ({modelId})"
                            self.devices[list_name] = device

                        if self.devices:
                            if len(self.devices) == 1:
                                self.extract_info(list(self.devices.values())[0])
                                return await self.async_step_connect()
                            return await self.async_step_devices()

                    errors["base"] = "no_devices"
            else:
                errors["base"] = "credentials_incomplete"

        return self.async_show_form(
            step_id="dreame",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=self.username): str,
                    vol.Required(CONF_PASSWORD, default=self.password): str,
                    vol.Required(CONF_COUNTRY, default=self.country): vol.In(
                        ["cn", "eu", "us", "ru", "sg"]
                    ),
                }
            ),
            description_placeholders=placeholders,
            errors=errors,
        )

    # step_mova removed 2026-04-20 (Cleanup Phase 2): A2 only uses Dreame cloud.

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle multiple Dreame/Mova Mower devices found."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self.extract_info(self.devices[user_input["devices"]])
            return await self.async_step_connect()

        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {vol.Required("devices"): vol.In(list(self.devices))}
            ),
            errors=errors,
        )

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Dreame/Mova Mower options step."""
        errors = {}

        if user_input is not None:
            self.name = user_input[CONF_NAME]

            return self.async_create_entry(
                title=self.name,
                data={
                    CONF_NAME: self.name,
                    CONF_HOST: self.host,
                    CONF_TOKEN: self.token,
                    CONF_USERNAME: self.username,
                    CONF_PASSWORD: self.password,
                    CONF_COUNTRY: self.country,
                    CONF_MAC: self.mac,
                    CONF_DID: self.device_id,
                    CONF_ACCOUNT_TYPE: self.account_type,
                },
                options={
                    CONF_NOTIFY: user_input[CONF_NOTIFY],
                    CONF_COLOR_SCHEME: user_input.get(CONF_COLOR_SCHEME),
                    CONF_ICON_SET: user_input.get(CONF_ICON_SET),
                    CONF_MAP_OBJECTS: user_input.get(CONF_MAP_OBJECTS),
                    CONF_SQUARE: user_input.get(CONF_SQUARE),
                    CONF_LOW_RESOLUTION: user_input.get(CONF_LOW_RESOLUTION),
                    CONF_PREFER_CLOUD: self.prefer_cloud,
                },
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=self.name): str,
                vol.Required(
                    CONF_NOTIFY, default=list(NOTIFICATION.keys())
                ): cv.multi_select(NOTIFICATION),
            }
        )

        default_objects = list(MAP_OBJECTS.keys())
        default_color_scheme = "Dreame Light"
        default_icon_set = "Dreame"
        model = re.sub(r"[^0-9]", "", self.model)
        if not (model.isnumeric() and int(model) >= 2215):
            default_objects.pop(3)  # Room Name Background
            default_objects.pop(2)  # Room Names

        if self.account_type != "local":
            data_schema = data_schema.extend(
                {
                    vol.Required(
                        CONF_COLOR_SCHEME, default=default_color_scheme
                    ): vol.In(list(MAP_COLOR_SCHEME_LIST.keys())),
                    vol.Required(CONF_ICON_SET, default=default_icon_set): vol.In(
                        list(MAP_ICON_SET_LIST.keys())
                    ),
                    vol.Required(
                        CONF_MAP_OBJECTS, default=default_objects
                    ): cv.multi_select(MAP_OBJECTS),
                    vol.Required(CONF_SQUARE, default=False): bool,
                    vol.Required(CONF_LOW_RESOLUTION, default=False): bool,
                }
            )

        return self.async_show_form(
            step_id="options", data_schema=data_schema, errors=errors
        )

    def extract_info(self, device_info: dict[str, Any]) -> None:
        """Extract the device info from the Dreame cloud /listV2 payload.

        The Mi-cloud branch was removed in Phase 2; only the Dreame-cloud
        field layout remains.
        """
        if self.token is None:
            self.token = " "  # placeholder — cloud-only, never used
        if self.host is None:
            self.host = device_info["bindDomain"]
        if self.mac is None:
            self.mac = device_info["mac"]
        if self.model is None:
            self.model = device_info["model"]
        if self.name is None:
            self.name = (
                device_info["customName"]
                if device_info["customName"] and len(device_info["customName"]) > 0
                else device_info["deviceInfo"]["displayName"]
            )
            self.device_id = device_info["did"]
