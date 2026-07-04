"""Config flow for the Dreame A2 Mower integration.

F1: minimal user-step flow. Just collects cloud credentials + country.
F4 (settings) extends this with options-flow for archive retention and
station bearing.

Per spec §5.9 credential discipline: credentials are stored in HA's
encrypted-at-rest config-entry secrets via the standard
``CONF_USERNAME`` / ``CONF_PASSWORD`` constants.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .cloud_client import DreameA2CloudClient
from .const import (
    CONF_COUNTRY,
    CONF_DEBUG_SERVICES,
    CONF_EXPERIMENTAL_FEATURES,
    CONF_LIDAR_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_MAX_MB,
    CONF_MESSAGES_KEEP,
    CONF_PASSWORD,
    CONF_SESSION_ARCHIVE_KEEP,
    CONF_STATION_BEARING_DEG,
    CONF_USERNAME,
    CONF_WIFI_ARCHIVE_KEEP,
    DEFAULT_COUNTRY,
    DEFAULT_EXPERIMENTAL_FEATURES,
    DEFAULT_LIDAR_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_MAX_MB,
    DEFAULT_MESSAGES_KEEP,
    DEFAULT_MODEL,
    DEFAULT_NAME,
    DEFAULT_SESSION_ARCHIVE_KEEP,
    DEFAULT_WIFI_ARCHIVE_KEEP,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class CannotConnect(Exception):
    """Raised when the cloud login attempt fails at the transport level."""


class InvalidAuth(Exception):
    """Raised when the cloud login attempt reports bad credentials."""


async def _validate_login(hass: Any, data: dict[str, Any]) -> DreameA2CloudClient:
    """Attempt a real cloud login with the submitted credentials.

    ``client.login()`` is blocking (uses ``requests``), so it's run via
    ``hass.async_add_executor_job`` rather than called directly in the
    event loop. It returns a bool (``True``/``False``); Task 2 (P6.1b)
    added ``client.last_login_failure`` so a ``False`` return can now be
    disambiguated: ``"transport"`` (network/timeout/malformed-response —
    login couldn't reach a clear verdict) maps to ``CannotConnect``,
    anything else (``"auth"``, or an absent attribute on a test double)
    maps to ``InvalidAuth``. Any exception that escapes the executor job
    (e.g. a genuine programming error) is treated as a transport/unknown
    failure here.

    On success, returns the now-authenticated ``client`` (Task 3 / P6.1c)
    so ``async_step_user`` can reuse it for device discovery without a
    second login round-trip. ``async_step_reauth_confirm`` only needs
    "didn't raise" and ignores the return value.
    """
    client = DreameA2CloudClient(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        country=data[CONF_COUNTRY],
    )
    try:
        ok = await hass.async_add_executor_job(client.login)
    except Exception as err:  # noqa: BLE001 - mapped to a flow error below
        raise CannotConnect from err
    if not ok:
        if getattr(client, "last_login_failure", None) == "transport":
            raise CannotConnect
        raise InvalidAuth
    return client


def _discover_mower_records(client: DreameA2CloudClient) -> list[dict[str, Any]]:
    """Return the account's ``dreame.mower.*`` device records.

    ``client.get_devices()`` is blocking — callers run it via
    ``hass.async_add_executor_job``. Guards against ``None``/malformed
    responses (no ``data``/``page``/``records`` keys) by returning an
    empty list rather than raising.
    """
    data = client.get_devices()
    if not data:
        return []
    records = data.get("page", {}).get("records", [])
    return [
        d for d in records if str(d.get("model", "")).startswith("dreame.mower.")
    ]


class DreameA2MowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup conversation."""

    VERSION = 2

    @staticmethod
    def async_get_options_flow(
        entry: config_entries.ConfigEntry,  # noqa: ARG004 - HA calls with positional arg
    ) -> DreameA2MowerOptionsFlow:
        """Return the options flow handler for this entry.

        The base ``OptionsFlow`` class exposes ``config_entry`` as a
        read-only property (resolved via ``self.handler``) in HA 2024.11+,
        so we must NOT pass ``entry`` into the subclass and stash it
        ourselves — doing so raises ``AttributeError: property
        'config_entry' has no setter`` in HA 2026.5+, which surfaces as a
        500 from the options-flow handler endpoint.
        """
        return DreameA2MowerOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: collect cloud credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            try:
                client = await _validate_login(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - last-resort form error
                errors["base"] = "unknown"
            else:
                mowers = await self.hass.async_add_executor_job(
                    _discover_mower_records, client
                )
                if not mowers:
                    return self.async_abort(reason="no_supported_device")

                g2408s = [d for d in mowers if d.get("model") == DEFAULT_MODEL]
                others = [d for d in mowers if d.get("model") != DEFAULT_MODEL]
                chosen = g2408s[0] if g2408s else others[0]

                if len(g2408s) > 1:
                    _LOGGER.warning(
                        "Multiple dreame.mower.g2408 devices found on this "
                        "account (%d); pinning the first (did=%s) — this "
                        "integration supports a single device.",
                        len(g2408s),
                        chosen.get("did"),
                    )
                if not g2408s:
                    _LOGGER.warning(
                        "No verified dreame.mower.g2408 device found; "
                        "proceeding best-effort with model=%r (did=%s). "
                        "This model has not been wire-verified (R-44).",
                        chosen.get("model"),
                        chosen.get("did"),
                    )

                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={
                        **user_input,
                        "did": chosen.get("did"),
                        "sn": chosen.get("sn"),
                        "model": chosen.get("model"),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_COUNTRY, default=DEFAULT_COUNTRY): vol.In(
                        ["eu", "us", "cn", "ru", "i2", "sg", "de"]
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Entry point when HA starts a reauth flow (Task 2 / P6.1b).

        Triggered either by ``coordinator/_core.py:_init_cloud`` raising
        ``ConfigEntryAuthFailed`` during setup, or by
        ``domain/mqtt_lifecycle.py`` calling
        ``entry.async_start_reauth`` after a runtime rc=5 relogin finds the
        cloud has genuinely rejected the credentials. Stashes the entry
        being reauthenticated (looked up via the standard
        ``self.context["entry_id"]``) and forwards straight to the
        password-only confirm step.
        """
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Password-only reauth form; validates via the shared ``_validate_login``."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**self._reauth_entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            try:
                await _validate_login(self.hass, data)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - last-resort form error
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    self._reauth_entry, data=data
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )


class DreameA2MowerOptionsFlow(config_entries.OptionsFlow):
    """Options flow — archive retention caps (spec §5.8).

    No custom ``__init__``: the base class supplies ``config_entry`` as a
    read-only property that resolves via ``self.handler`` (the entry id).
    Assigning ``self.config_entry`` in ``__init__`` raises AttributeError
    in HA 2024.11+, which manifests as a 500 in HA 2026.5+ when the
    Configure cog is clicked.
    """

    def _build_schema(self) -> vol.Schema:
        """Voluptuous schema for the options form.

        Extracted as a plain helper so the bounds can be unit-tested
        without a running HA instance.
        """
        opts = self.config_entry.options
        return vol.Schema(
            {
                vol.Optional(
                    CONF_LIDAR_ARCHIVE_KEEP,
                    default=opts.get(
                        CONF_LIDAR_ARCHIVE_KEEP, DEFAULT_LIDAR_ARCHIVE_KEEP
                    ),
                ): vol.All(int, vol.Range(min=1, max=50)),
                vol.Optional(
                    CONF_LIDAR_ARCHIVE_MAX_MB,
                    default=opts.get(
                        CONF_LIDAR_ARCHIVE_MAX_MB, DEFAULT_LIDAR_ARCHIVE_MAX_MB
                    ),
                ): vol.All(int, vol.Range(min=50, max=2000)),
                vol.Optional(
                    CONF_SESSION_ARCHIVE_KEEP,
                    default=opts.get(
                        CONF_SESSION_ARCHIVE_KEEP, DEFAULT_SESSION_ARCHIVE_KEEP
                    ),
                ): vol.All(int, vol.Range(min=1, max=200)),
                # WiFi heatmap archive: keep newest-N per map (enforced after
                # fingerprint tagging). Bounds the picker + disk growth.
                vol.Optional(
                    CONF_WIFI_ARCHIVE_KEEP,
                    default=opts.get(
                        CONF_WIFI_ARCHIVE_KEEP, DEFAULT_WIFI_ARCHIVE_KEEP
                    ),
                ): vol.All(int, vol.Range(min=1, max=200)),
                # Message center retention: keep newest-N per list
                # (device / service / sharing). Records are tiny; default
                # generous. Applied identically to all three lists.
                vol.Optional(
                    CONF_MESSAGES_KEEP,
                    default=opts.get(
                        CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP
                    ),
                ): vol.All(int, vol.Range(min=1, max=500)),
                # Position-fix P2: dock compass bearing used to project
                # dock-frame (x_m, y_m) into compass-frame (north_m, east_m).
                # 0-359 deg clockwise from north. Default 0; user can change.
                # CFG.DOCK.yaw is unreliable on this firmware so we expose
                # this as a user-set option instead of reading it from CFG.
                vol.Optional(
                    CONF_STATION_BEARING_DEG,
                    default=opts.get(CONF_STATION_BEARING_DEG, 0),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=359)),
                # P4 / R-52: the UNIFIED experimental-features opt-in gate.
                # OFF by default. When on, experimental entities are created
                # (disabled-by-default) and experimental services stop raising;
                # it also exposes the two developer-only diagnostic services
                # (dump_map_diagnostics + discover_cloud_api), which are not
                # registered in the service registry when off. Absorbs the former
                # ``debug_services`` toggle — a pre-P4 entry that still carries
                # debug_services=True pre-populates this toggle as on.
                vol.Optional(
                    CONF_EXPERIMENTAL_FEATURES,
                    default=opts.get(
                        CONF_EXPERIMENTAL_FEATURES,
                        opts.get(CONF_DEBUG_SERVICES, DEFAULT_EXPERIMENTAL_FEATURES),
                    ),
                ): bool,
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Single-step options form."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self._build_schema(),
        )
