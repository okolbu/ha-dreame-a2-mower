"""DataUpdateCoordinator for Dreame Mower."""

from __future__ import annotations

import math
import time
import traceback
from datetime import timedelta
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    CONF_HOST,
    CONF_TOKEN,
    CONF_PASSWORD,
    CONF_USERNAME,
    ATTR_ENTITY_ID,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .dreame import DreameMowerDevice, DreameMowerProperty
from .dreame.types import DreameMowerState
from .dreame.resources import (
    CONSUMABLE_IMAGE,
)
from .const import (
    DOMAIN,
    LOGGER,
    CONF_NOTIFY,
    CONF_COUNTRY,
    CONF_MAC,
    CONF_DID,
    CONF_ACCOUNT_TYPE,
    CONF_PREFER_CLOUD,
    CONTENT_TYPE,
    NOTIFICATION_CLEANUP_COMPLETED,
    NOTIFICATION_RESUME_CLEANING,
    NOTIFICATION_RESUME_CLEANING_NOT_PERFORMED,
    NOTIFICATION_REPLACE_MULTI_MAP,
    NOTIFICATION_REPLACE_MAP,
    NOTIFICATION_2FA_LOGIN,
    NOTIFICATION_ID_CLEANING_PAUSED,
    NOTIFICATION_ID_REPLACE_BLADES,
    NOTIFICATION_ID_REPLACE_SIDE_BRUSH,
    NOTIFICATION_ID_REPLACE_FILTER,
    NOTIFICATION_ID_REPLACE_TANK_FILTER,
    NOTIFICATION_ID_CLEAN_SENSOR,
    NOTIFICATION_ID_SILVER_ION,
    NOTIFICATION_ID_REPLACE_LENSBRUSH,
    NOTIFICATION_ID_REPLACE_SQUEEGEE,
    NOTIFICATION_ID_CLEANUP_COMPLETED,
    NOTIFICATION_ID_WARNING,
    NOTIFICATION_ID_ERROR,
    NOTIFICATION_ID_INFORMATION,
    NOTIFICATION_ID_CONSUMABLE,
    NOTIFICATION_ID_REPLACE_TEMPORARY_MAP,
    NOTIFICATION_ID_2FA_LOGIN,
    NOTIFICATION_ID_BATTERY_TEMP_LOW,
    NOTIFICATION_BATTERY_TEMP_LOW,
    EVENT_TASK_STATUS,
    EVENT_CONSUMABLE,
    EVENT_WARNING,
    EVENT_ERROR,
    EVENT_INFORMATION,
    EVENT_2FA_LOGIN,
    CONSUMABLE_BLADES,
    CONSUMABLE_SIDE_BRUSH,
    CONSUMABLE_FILTER,
    CONSUMABLE_TANK_FILTER,
    CONSUMABLE_SENSOR,
    CONSUMABLE_SILVER_ION,
    CONSUMABLE_LENSBRUSH,
    CONSUMABLE_SQUEEGEE,
)


class DreameMowerDataUpdateCoordinator(DataUpdateCoordinator[DreameMowerDevice]):
    """Class to manage fetching Dreame Mower data from single endpoint."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry: ConfigEntry,
    ) -> None:
        """Initialize global Dreame Mower data updater."""
        self._device: DreameMowerDevice = None
        self._token = entry.data[CONF_TOKEN]
        self._host = entry.data[CONF_HOST]
        self._notify = entry.options.get(CONF_NOTIFY, True)
        self._entry = entry
        self._ready = False
        self._available = False
        self._has_warning = False
        self._was_battery_temp_low = False
        self._was_error = False
        self._has_temporary_map = None
        self._two_factor_url = None
        self._properties_logged = False

        LOGGER.info("Integration loading: %s", entry.data[CONF_NAME])
        self._device = DreameMowerDevice(
            entry.data[CONF_NAME],
            self._host,
            self._token,
            entry.data.get(CONF_MAC),
            entry.data.get(CONF_USERNAME),
            entry.data.get(CONF_PASSWORD),
            entry.data.get(CONF_COUNTRY),
            entry.options.get(CONF_PREFER_CLOUD, False),
            entry.data.get(CONF_ACCOUNT_TYPE, "mi"),
            entry.data.get(CONF_DID),
        )

        # Station-bearing option (compass degrees, 0=N 90=E 180=S 270=W).
        # Makes the mower's +X axis map onto a real-world direction so
        # the N/E position sensors can project mower-frame (x, y) onto
        # world (north, east) coords. Zero = "station faces north"
        # (identity projection: north = x, east = y).
        from .const import CONF_STATION_BEARING
        self._device.station_bearing_deg = float(
            entry.options.get(CONF_STATION_BEARING, 0.0) or 0.0
        )

        self._device.listen(self._error_changed, DreameMowerProperty.ERROR)
        self._device.listen(self._state_changed, DreameMowerProperty.STATE)
        self._device.listen(self._task_status_changed, DreameMowerProperty.TASK_STATUS)
        self._device.listen(self._cleaning_paused_changed, DreameMowerProperty.CLEANING_PAUSED)
        self._device.listen(self._heartbeat_changed, DreameMowerProperty.HEARTBEAT)
        self._device.listen(self.set_updated_data)
        self._device.listen_error(self.set_update_error)

        super().__init__(hass, LOGGER, name=DOMAIN)

        # Persistent archive of every session-summary JSON the mower uploads.
        # Lives alongside HA's config dir under `dreame_a2_mower/sessions/`.
        # The coordinator polls `device.latest_session_summary` on every
        # update tick and writes new (unseen md5) summaries through.
        #
        # Created BEFORE live_map because live_map's _restore_in_progress
        # (called from DreameA2LiveMap.__init__) reads session_archive off
        # this coordinator to hydrate the in_progress.json on boot. If
        # the order is swapped, `getattr(coordinator, "session_archive",
        # None)` returns None inside _restore_in_progress and the
        # restore silently no-ops, losing the saved path data.
        from pathlib import Path
        from .session_archive import SessionArchive

        archive_root = Path(hass.config.path(DOMAIN, "sessions"))
        from .const import CONF_SESSION_ARCHIVE_KEEP, DEFAULT_SESSION_ARCHIVE_KEEP
        session_keep = int(entry.options.get(
            CONF_SESSION_ARCHIVE_KEEP, DEFAULT_SESSION_ARCHIVE_KEEP
        ))
        try:
            self.session_archive = SessionArchive(archive_root, retention=session_keep)
        except OSError as ex:
            LOGGER.warning(
                "SessionArchive: could not initialise at %s: %s — archival disabled",
                archive_root,
                ex,
            )
            self.session_archive = None
        self._last_archived_md5: str | None = (
            self.session_archive.latest().md5 if self.session_archive and self.session_archive.latest() else None
        )

        from .live_map import DreameA2LiveMap
        self.live_map = DreameA2LiveMap(hass, entry, self)
        self.live_map.async_setup()

        # LiDAR scan archive. Lives next to the session archive under
        # `<ha_config>/dreame_a2_mower/lidar/`. Each downloaded PCD blob
        # is content-addressed by md5 so re-downloading the same OSS key
        # is a no-op.
        from .lidar_archive import LidarArchive as _LidarArchive
        from .const import CONF_LIDAR_ARCHIVE_KEEP, DEFAULT_LIDAR_ARCHIVE_KEEP

        lidar_root = Path(hass.config.path(DOMAIN, "lidar"))
        lidar_keep = int(entry.options.get(
            CONF_LIDAR_ARCHIVE_KEEP, DEFAULT_LIDAR_ARCHIVE_KEEP
        ))
        try:
            self.lidar_archive = _LidarArchive(lidar_root, retention=lidar_keep)
        except OSError as ex:
            LOGGER.warning(
                "LidarArchive: could not initialise at %s: %s — archival disabled",
                lidar_root,
                ex,
            )
            self.lidar_archive = None
        self._last_archived_lidar_md5: str | None = (
            self.lidar_archive.latest().md5
            if self.lidar_archive and self.lidar_archive.latest()
            else None
        )
        # Throttle for the deferred-session-summary retry so repeated
        # failures during a cloud outage don't spam the executor pool.
        # Minimum seconds between retry attempts.
        self._session_retry_min_interval = 60.0
        self._session_retry_last_at: float = 0.0

        # Optional raw-MQTT archive — off by default. When enabled, every
        # MQTT message the device client receives gets appended to a
        # daily-rotating JSONL file under
        # `<ha_config>/dreame_a2_mower/mqtt_archive/YYYY-MM-DD.jsonl`, with
        # pruning at `retain_days`. Gives an in-HA equivalent of the
        # external probe's capture for users who need a full record of
        # unknown/novel fields without running a separate Python script.
        from .const import (
            CONF_MQTT_ARCHIVE,
            CONF_MQTT_ARCHIVE_RETAIN_DAYS,
            DEFAULT_MQTT_ARCHIVE_RETAIN_DAYS,
        )
        if entry.options.get(CONF_MQTT_ARCHIVE, False):
            from .protocol.mqtt_archive import MqttArchive
            mqtt_archive_dir = Path(hass.config.path(DOMAIN, "mqtt_archive"))
            retain = int(entry.options.get(
                CONF_MQTT_ARCHIVE_RETAIN_DAYS,
                DEFAULT_MQTT_ARCHIVE_RETAIN_DAYS,
            ))
            try:
                self._device.attach_mqtt_archive(
                    MqttArchive(mqtt_archive_dir, retain_days=retain)
                )
                LOGGER.info(
                    "MQTT archive enabled at %s (retain %d days)",
                    mqtt_archive_dir,
                    retain,
                )
            except OSError as ex:
                LOGGER.warning(
                    "MQTT archive: could not initialise at %s: %s — disabled",
                    mqtt_archive_dir,
                    ex,
                )

        async_dispatcher_connect(
            hass,
            persistent_notification.SIGNAL_PERSISTENT_NOTIFICATIONS_UPDATED,
            self._notification_dismiss_listener,
        )

        # Periodic cloud-map freshness poll. The mower only broadcasts a
        # map-ready signal on auto-recharge legs (`s6p1 = 300`); zone /
        # exclusion edits made from another device (or from this phone
        # before HA comes online) are otherwise invisible until the next
        # mowing session. If HA has been up for days without a session,
        # the camera's polygons drift out of sync. Re-pull the MAP.*
        # cloud keys every 6 hours to close that gap — the md5sum
        # dedupe inside `_build_map_from_cloud_data` turns a no-change
        # poll into a zero-cost no-op, and one HTTP round-trip per
        # 6-hour tick is negligible next to the mower's own MQTT
        # traffic. No lightweight probe is possible: the md5sum is
        # embedded inside the compressed payload so the full fetch IS
        # the cheapest check the Dreame cloud offers. The user-LiDAR
        # archive has no analogous poll — `s99p20` is only emitted when
        # the user opens the app's LiDAR view, there's no
        # integration-side way to know whether the on-mower scan has
        # changed.
        async def _periodic_map_refresh(_now):
            dev = self._device
            if dev is None:
                return
            await self.hass.async_add_executor_job(
                dev._schedule_cloud_map_poll, "periodic-6h"
            )

        entry.async_on_unload(
            async_track_time_interval(
                hass,
                _periodic_map_refresh,
                timedelta(hours=6),
            )
        )

    def _heartbeat_changed(self, previous_value=None) -> None:
        """Rising-edge notifier for the s1p1 battery-temperature-low flag.

        The Dreame app raises "Battery temperature is low. Charging stopped."
        every time the mower (re-)enters the low-temp charging-pause state.
        We mirror that semantics: fire EVENT_WARNING + create/refresh a
        persistent notification on the False→True transition, and dismiss
        the notification on True→False. See docs/research/g2408-protocol.md
        §4.4 for the wire-level evidence.
        """
        flag = self._device.battery_temp_low
        if flag is None:
            return
        is_low = bool(flag)
        if is_low and not self._was_battery_temp_low:
            self._fire_event(
                EVENT_WARNING,
                {EVENT_WARNING: NOTIFICATION_ID_BATTERY_TEMP_LOW},
            )
            self._create_persistent_notification(
                NOTIFICATION_BATTERY_TEMP_LOW,
                NOTIFICATION_ID_BATTERY_TEMP_LOW,
            )
        elif not is_low and self._was_battery_temp_low:
            self._remove_persistent_notification(NOTIFICATION_ID_BATTERY_TEMP_LOW)
        self._was_battery_temp_low = is_low

    def _cleaning_paused_changed(self, previous_value=None) -> None:
        if self._device.status.cleaning_paused:
            notification = NOTIFICATION_RESUME_CLEANING
            if self._device.status.battery_level >= 80:
                dnd_remaining = self._device.status.dnd_remaining
                if dnd_remaining:
                    hour = math.floor(dnd_remaining / 3600)
                    minute = math.floor((dnd_remaining - hour * 3600) / 60)
                    notification = f"{NOTIFICATION_RESUME_CLEANING_NOT_PERFORMED}\n## Cleaning will start in {hour} hour(s) and {minute} minutes(s)"
                self._fire_event(
                    EVENT_INFORMATION,
                    {EVENT_INFORMATION: NOTIFICATION_ID_CLEANING_PAUSED},
                )
            else:
                self._fire_event(
                    EVENT_INFORMATION,
                    {EVENT_INFORMATION: NOTIFICATION_ID_CLEANING_PAUSED},
                )

            self._create_persistent_notification(notification, NOTIFICATION_ID_CLEANING_PAUSED)
        else:
            self._remove_persistent_notification(NOTIFICATION_ID_CLEANING_PAUSED)

    def _task_status_changed(self, previous_value=None) -> None:
        if previous_value is not None:
            if self._device.status.cleanup_completed:
                self._fire_event(EVENT_TASK_STATUS, self._device.status.job)
                self._create_persistent_notification(NOTIFICATION_CLEANUP_COMPLETED, NOTIFICATION_ID_CLEANUP_COMPLETED)
                self._check_consumables()

            elif previous_value == 0 and not self._device.status.fast_mapping and not self._device.status.cruising:
                self._fire_event(EVENT_TASK_STATUS, self._device.status.job)
        else:
            self._check_consumables()

    def _error_changed(self, previous_value=None) -> None:
        has_warning = self._device.status.has_warning
        description = self._device.status.error_description
        if has_warning:
            content = description[0]
            self._fire_event(
                EVENT_WARNING,
                {EVENT_WARNING: content, "code": self._device.status.error.value},
            )

            if len(description[1]) > 2:
                content = f"### {content}\n{description[1]}"

            image = self._device.status.error_image
            if image:
                content = f"{content}![image](data:{CONTENT_TYPE};base64,{image})"
            self._create_persistent_notification(content, NOTIFICATION_ID_WARNING)
        elif self._has_warning:
            self._remove_persistent_notification(NOTIFICATION_ID_WARNING)

        if self._device.status.has_error:
            self._fire_event(
                EVENT_ERROR,
                {EVENT_ERROR: description[0], "code": self._device.status.error.value},
            )

            content = f"### {description[0]}\n{description[1]}"
            image = self._device.status.error_image
            if image:
                content = f"{content}![image](data:{CONTENT_TYPE};base64,{image})"
            self._create_persistent_notification(content, f"{NOTIFICATION_ID_ERROR}_{self._device.status.error.value}")

        self._has_warning = has_warning

    def _state_changed(self, previous_value=None) -> None:
        is_error = self._device.status.state == DreameMowerState.ERROR
        if is_error and not self._was_error:
            error_detail = self._try_fetch_error_code()
            lang = self.hass.config.language
            if error_detail:
                content = f"### {error_detail[0]}\n{error_detail[1]}"
            elif lang == "fr":
                content = "La tondeuse a signalé une erreur. Veuillez la vérifier."
            else:
                content = "The mower reported an error. Please check the mower."
            # Always notify on error regardless of notification settings
            if not self.device.disconnected and self.device.device_connected:
                persistent_notification.create(
                    hass=self.hass,
                    message=content,
                    title=self._device.name,
                    notification_id=f"{DOMAIN}_{self._device.mac}_{NOTIFICATION_ID_ERROR}_state",
                )
            self._fire_event(
                EVENT_ERROR,
                {EVENT_ERROR: content},
            )
        elif not is_error and self._was_error:
            persistent_notification.dismiss(
                self.hass,
                f"{DOMAIN}_{self._device.mac}_{NOTIFICATION_ID_ERROR}_state",
            )
        self._was_error = is_error

    def _try_fetch_error_code(self) -> tuple[str, str] | None:
        """Try to fetch detailed error code via cloud API."""
        try:
            from .dreame.types import DreameMowerErrorCode
            from .dreame.const import (
                ERROR_CODE_TO_ERROR_DESCRIPTION,
                ERROR_CODE_TO_ERROR_DESCRIPTION_FR,
            )
            mapping = self._device.property_mapping.get(DreameMowerProperty.ERROR)
            if not mapping:
                return None
            result = self._device._protocol.get_properties(
                [{"did": str(DreameMowerProperty.ERROR.value), **mapping}]
            )
            if result:
                for prop in result:
                    if prop.get("code") == 0:
                        value = prop.get("value")
                        if value is not None and value > 0 and value in DreameMowerErrorCode._value2member_map_:
                            error_code = DreameMowerErrorCode(value)
                            lang = self.hass.config.language
                            desc = None
                            if lang == "fr":
                                desc = ERROR_CODE_TO_ERROR_DESCRIPTION_FR.get(error_code)
                            if not desc:
                                desc = ERROR_CODE_TO_ERROR_DESCRIPTION.get(
                                    error_code, ["Unknown error", ""]
                                )
                            return (desc[0], desc[1])
        except Exception:
            LOGGER.debug("Failed to fetch error code from cloud")
        return None

    def _has_temporary_map_changed(self, previous_value=None) -> None:
        if self._device.status.has_temporary_map:
            self._fire_event(EVENT_WARNING, {EVENT_WARNING: NOTIFICATION_REPLACE_MULTI_MAP})

            self._create_persistent_notification(
                NOTIFICATION_REPLACE_MULTI_MAP if self._device.status.multi_map else NOTIFICATION_REPLACE_MAP,
                NOTIFICATION_ID_REPLACE_TEMPORARY_MAP,
            )
        else:
            self._fire_event(EVENT_WARNING, {EVENT_WARNING: NOTIFICATION_ID_REPLACE_TEMPORARY_MAP})

            self._remove_persistent_notification(NOTIFICATION_ID_REPLACE_TEMPORARY_MAP)

    def _check_consumable(self, consumable, notification_id, property):
        description = self._device.status.consumable_life_warning_description(property)
        if description:
            image = CONSUMABLE_IMAGE.get(consumable)
            notification = f"### {description[0]}\n{description[1]}"
            if image:
                notification = f"{notification}\n![image](data:{CONTENT_TYPE};base64,{image})"
            self._create_persistent_notification(
                notification,
                notification_id,
            )

            self._fire_event(
                EVENT_CONSUMABLE,
                {
                    EVENT_CONSUMABLE: consumable,
                    "life_left": self._device.get_property(property),
                },
            )

    def _check_consumables(self):
        self._check_consumable(
            CONSUMABLE_BLADES,
            NOTIFICATION_ID_REPLACE_BLADES,
            DreameMowerProperty.BLADES_LEFT,
        )
        self._check_consumable(
            CONSUMABLE_SIDE_BRUSH,
            NOTIFICATION_ID_REPLACE_SIDE_BRUSH,
            DreameMowerProperty.SIDE_BRUSH_LEFT,
        )
        self._check_consumable(
            CONSUMABLE_FILTER,
            NOTIFICATION_ID_REPLACE_FILTER,
            DreameMowerProperty.FILTER_LEFT,
        )
        self._check_consumable(
            CONSUMABLE_TANK_FILTER,
            NOTIFICATION_ID_REPLACE_TANK_FILTER,
            DreameMowerProperty.TANK_FILTER_LEFT,
        )
        if not self.device.capability.disable_sensor_cleaning:
            self._check_consumable(
                CONSUMABLE_SENSOR,
                NOTIFICATION_ID_CLEAN_SENSOR,
                DreameMowerProperty.SENSOR_DIRTY_LEFT,
            )
        self._check_consumable(
            CONSUMABLE_SQUEEGEE,
            NOTIFICATION_ID_REPLACE_SQUEEGEE,
            DreameMowerProperty.SQUEEGEE_LEFT,
        )
        self._check_consumable(
            CONSUMABLE_LENSBRUSH,
            NOTIFICATION_ID_REPLACE_LENSBRUSH,
            DreameMowerProperty.LENSBRUSH_LEFT,
        )

    def _create_persistent_notification(self, content, notification_id) -> None:
        if (
            not self.device.disconnected
            and self.device.device_connected
            and (self._notify or notification_id == NOTIFICATION_ID_2FA_LOGIN)
        ):
            if isinstance(self._notify, list) and notification_id != NOTIFICATION_ID_2FA_LOGIN:
                if notification_id == NOTIFICATION_ID_CLEANUP_COMPLETED:
                    if NOTIFICATION_ID_CLEANUP_COMPLETED not in self._notify:
                        return
                    notification_id = f"{notification_id}_{int(time.time())}"
                elif NOTIFICATION_ID_WARNING in notification_id:
                    if NOTIFICATION_ID_WARNING not in self._notify:
                        return
                elif NOTIFICATION_ID_ERROR in notification_id:
                    if NOTIFICATION_ID_ERROR not in self._notify:
                        return
                elif (
                    notification_id == NOTIFICATION_ID_CLEANING_PAUSED
                ):
                    if NOTIFICATION_ID_INFORMATION not in self._notify:
                        return
                elif (
                    notification_id != NOTIFICATION_ID_REPLACE_TEMPORARY_MAP
                ):
                    if NOTIFICATION_ID_CONSUMABLE not in self._notify:
                        return

            persistent_notification.create(
                hass=self.hass,
                message=content,
                title=self._device.name,
                notification_id=f"{DOMAIN}_{self._device.mac}_{notification_id}",
            )

    def _remove_persistent_notification(self, notification_id) -> None:
        persistent_notification.dismiss(self.hass, f"{DOMAIN}_{self._device.mac}_{notification_id}")

    def _notification_dismiss_listener(self, type, data) -> None:
        if type == persistent_notification.UpdateType.REMOVED and self._device:
            notifications = self.hass.data.get(persistent_notification.DOMAIN)
            if self._has_warning:
                if f"{DOMAIN}_{self._device.mac}_{NOTIFICATION_ID_WARNING}" not in notifications:
                    if NOTIFICATION_ID_WARNING in self._notify:
                        self._device.clear_warning()
                    self._has_warning = self._device.status.has_warning

            if self._two_factor_url:
                if f"{DOMAIN}_{self._device.mac}_{NOTIFICATION_ID_2FA_LOGIN}" not in notifications:
                    self._two_factor_url = None

    def _fire_event(self, event_id, data) -> None:
        event_data = {ATTR_ENTITY_ID: generate_entity_id("mower.{}", self._device.name, hass=self.hass)}
        if data:
            event_data.update(data)
        self.hass.bus.fire(f"{DOMAIN}_{event_id}", event_data)

    async def _async_update_data(self) -> DreameMowerDevice:
        """Handle device update. This function is only called once when the integration is added to Home Assistant."""
        try:
            LOGGER.info("Integration starting...")
            await self.hass.async_add_executor_job(self._device.update)
            if self._device and not self._device.disconnected:
                self._device.schedule_update()
                self.async_set_updated_data()
                return self._device
        except Exception as ex:
            LOGGER.warning("Integration start failed: %s", traceback.format_exc())
            if self._device is not None:
                self._device.listen(None)
                self._device.disconnect()
                del self._device
                self._device = None
            raise UpdateFailed(ex) from ex

    @property
    def device(self) -> DreameMowerDevice:
        return self._device

    def set_update_error(self, ex=None) -> None:
        self.hass.loop.call_soon_threadsafe(self.async_set_update_error, ex)

    def set_updated_data(self, device=None) -> None:
        self.hass.loop.call_soon_threadsafe(self.async_set_updated_data, device)

    @callback
    def async_set_updated_data(self, device=None) -> None:
        # If an earlier event_occured push announced a session-summary OSS
        # key but the download was deferred (no cloud login, HTTP error),
        # retry it on a worker thread. The mower only announces the key
        # once per session, so missing it here permanently loses that
        # session — worth the cheap retry on every update tick, throttled
        # to at most once per `_session_retry_min_interval` seconds so a
        # persistent cloud outage doesn't flood the executor.
        # Manual drive is BT-only on the A2 — when the mower enters
        # state=MOWING but no s1p4 telemetry arrives within 15s, we
        # hide the icon and draw a "MANUAL MODE" banner. Checked here
        # every tick so the banner appears/disappears within one
        # update cycle of telemetry going silent or resuming.
        if self._device is not None:
            try:
                self._device.manual_mode_tick()
            except Exception as ex:
                LOGGER.debug("manual_mode_tick failed: %s", ex)

        if self._device is not None and getattr(
            self._device, "_pending_session_object_name", None
        ):
            import time as _time
            now = _time.monotonic()
            if now - self._session_retry_last_at >= self._session_retry_min_interval:
                self._session_retry_last_at = now
                self.hass.async_add_executor_job(
                    self._device.retry_pending_session_summary
                )

        # Archive any newly-fetched session summary. Cheap check:
        # compare md5 against the last archived one.
        if self.session_archive is not None:
            summary = getattr(self._device, "latest_session_summary", None)
            if summary is not None:
                md5 = getattr(summary, "md5", None)
                if md5 and md5 != self._last_archived_md5:
                    raw = getattr(self._device, "latest_session_raw", None)
                    entry = self.session_archive.archive(summary, raw_json=raw)
                    if entry is not None:
                        self._last_archived_md5 = md5
                        LOGGER.info(
                            "SessionArchive: stored %s (%.1f m² in %d min), total=%d",
                            entry.filename,
                            entry.area_mowed_m2,
                            entry.duration_min,
                            self.session_archive.count,
                        )

        # Same pattern for LiDAR scans — md5 dedupe so re-downloading the
        # same OSS key (e.g. after HA restart) is idempotent.
        if self.lidar_archive is not None:
            latest = getattr(self._device, "latest_lidar_scan", None)
            if latest is not None:
                object_name, unix_ts, raw_bytes = latest
                import hashlib as _hashlib

                md5 = _hashlib.md5(raw_bytes).hexdigest()
                if md5 != self._last_archived_lidar_md5:
                    entry = self.lidar_archive.archive(object_name, unix_ts, raw_bytes)
                    if entry is not None:
                        self._last_archived_lidar_md5 = md5
                        LOGGER.info(
                            "LidarArchive: stored %s (%d bytes), total=%d",
                            entry.filename,
                            entry.size_bytes,
                            self.lidar_archive.count,
                        )

        if self._has_temporary_map != self._device.status.has_temporary_map:
            self._has_temporary_map_changed(self._has_temporary_map)
            self._has_temporary_map = self._device.status.has_temporary_map

        if not self._ready:
            self._ready = True
            if (self._device.token and self._device.token != self._token) or (
                self._device.host and self._device.host != self._host
            ):
                data = self._entry.data.copy()
                self._host = self._device.host
                self._token = self._device.token
                data[CONF_HOST] = self._host
                data[CONF_TOKEN] = self._token
                LOGGER.info("Update Host Config: %s", self._host)
                self.hass.config_entries.async_update_entry(self._entry, data=data)

        if not self._properties_logged and self._ready and hasattr(self._device, 'data') and self._device.data:
            self._properties_logged = True
            LOGGER.debug(
                "Device properties available (%d): %s",
                len(self._device.data),
                sorted(self._device.data.keys()),
            )

        if self._device.two_factor_url:
            self._create_persistent_notification(
                f"{NOTIFICATION_2FA_LOGIN}[Click for 2FA Login]({self._device.two_factor_url})",
                NOTIFICATION_ID_2FA_LOGIN,
            )
            if self._two_factor_url != self._device.two_factor_url:
                self._fire_event(EVENT_2FA_LOGIN, {"url": self._device.two_factor_url})
        else:
            self._remove_persistent_notification(NOTIFICATION_ID_2FA_LOGIN)

        self._two_factor_url = self._device.two_factor_url

        self._available = self._device and self._device.available
        super().async_set_updated_data(self._device)

    @callback
    def async_set_update_error(self, ex) -> None:
        if self._available:
            self._available = self._device and self._device.available
            super().async_set_update_error(ex)
