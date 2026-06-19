"""refreshers mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import math
import time
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..archive.lidar import LidarArchive
from ..archive.session import ArchivedSession, SessionArchive
from ..wifi_archive_store import WifiArchiveEntry, WifiArchiveStore
from ..cloud_client import DreameA2CloudClient
from ..protocol import message_record as _msg
from ..const import (
    CONF_COUNTRY,
    CONF_LIDAR_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_MAX_MB,
    CONF_MESSAGES_KEEP,
    DEFAULT_MESSAGES_KEEP,
    CONF_PASSWORD,
    CONF_SESSION_ARCHIVE_KEEP,
    CONF_STATION_BEARING_DEG,
    CONF_USERNAME,
    DEFAULT_LIDAR_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_MAX_MB,
    DEFAULT_SESSION_ARCHIVE_KEEP,
    DOMAIN,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_STARTED,
    LOG_NOVEL_KEY_SESSION_SUMMARY,
    LOG_NOVEL_PROPERTY,
    LOG_NOVEL_VALUE,
    LOGGER,
)
from ..inventory.loader import load_inventory
from ..live_map.finalize import RETRY_INTERVAL_SECONDS, FinalizeAction
from ..live_map.finalize import decide as _finalize_decide
from ..live_map.state import LiveMapState
from ..mower.actions import ACTION_TABLE, MowerAction
from ..mower.property_mapping import PROPERTY_MAPPING, resolve_field
from ..mower.state import ChargingStatus, MowerState
from ..mower.state_machine import MowerStateMachine
from ..mqtt_client import DreameA2MqttClient
from ..observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck

from ._property_apply import (
    _BLOB_SLOTS,
    _INVENTORY,
    _SESSION_SUMMARY_CHECK,
    _SETTINGS_TRIPWIRE_SLOTS,
    _SUPPRESSED_SLOTS,
    S2P2_EVENT_TYPES,
    S2P2_UNKNOWN_EVENT_TYPE,
    _apply_consumables,
    _apply_s1p1_heartbeat,
    _apply_s1p4_telemetry,
    _apply_s2p51_settings,
    _coerce_blob,
    _project_north_east,
    apply_property_to_state,
)

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


def apply_mpos_result(state, res: dict, now_unix: int):
    """Merge a fetch_mpos() result into MowerState (pure, no side effects).

    On "ok": set mpos_x/y/yaw + mpos_updated_unix=now + mpos_last_result="ok".
    On "idle"/"error": keep the prior x/y/yaw + timestamp (no false "freshen"),
    only update mpos_last_result. RAW values — no transform.
    """
    if res.get("result") == "ok":
        return dataclasses.replace(
            state,
            mpos_x=res.get("x"), mpos_y=res.get("y"), mpos_yaw=res.get("yaw"),
            mpos_updated_unix=now_unix, mpos_last_result="ok",
        )
    return dataclasses.replace(state, mpos_last_result=res.get("result") or "error")


class _RefreshersMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    async def _refresh_mapl(self) -> None:
        """Re-poll MAPL only (no full CFG refresh)."""
        if not hasattr(self, "_cloud") or self._cloud is None:
            return
        try:
            mapl_resp = await self.hass.async_add_executor_job(
                self._cloud.fetch_mapl
            )
        except Exception as ex:
            LOGGER.debug("[map] _refresh_mapl raised: %s", ex)
            return
        if isinstance(mapl_resp, dict):
            inner = (mapl_resp.get("ok") or {}).get("d") or mapl_resp.get("ok") or mapl_resp
            self._apply_mapl(inner if isinstance(inner, list) else None)
        elif isinstance(mapl_resp, list):
            # fetch_mapl can return a bare list per Task 7 implementation.
            self._apply_mapl(mapl_resp)

    async def _refresh_dock(self) -> None:
        """Fetch CFG.DOCK → populate dock-position fields on MowerState.

        DOCK returns ``{dock: {connect_status, in_region, x, y, yaw,
        near_x, near_y, near_yaw, path_connect}}``. We pull the inner
        dict and map position fields (x/y/yaw/in_region) onto MowerState
        for the dock-position sensors. connect_status is not used here —
        location is owned solely by s2p1 (dock cluster {6,13,15,16}).
        """
        if not hasattr(self, "_cloud"):
            return
        dock_outer = await self.hass.async_add_executor_job(self._cloud.fetch_dock)
        if not isinstance(dock_outer, dict):
            return
        dock = dock_outer.get("dock") if isinstance(dock_outer.get("dock"), dict) else dock_outer
        if not isinstance(dock, dict):
            return

        def _i(name: str) -> int | None:
            v = dock.get(name)
            if v is None:
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        connect_status = dock.get("connect_status")
        in_region = dock.get("in_region")

        updates: dict[str, Any] = {}
        # Dock position fields flow to MowerState for the dock-position sensors.
        # Location is owned solely by s2p1 (not by this cloud poll).
        if in_region is not None:
            updates["dock_in_lawn_region"] = bool(in_region)
        for src, dst in (
            ("x", "dock_x_mm"),
            ("y", "dock_y_mm"),
            ("yaw", "dock_yaw"),
        ):
            v = _i(src)
            if v is not None:
                updates[dst] = v

        if not updates:
            return

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _refresh_net(self) -> None:
        """Fetch CFG.NET → populate wifi_ssid / wifi_ip / wifi_rssi_dbm.

        NET returns ``{current: ssid, list: [{ip, rssi, ssid}, …]}``.
        We pull the matching entry from `list` (where `ssid == current`)
        and populate the three fields. The s1p1 byte[17] live RSSI
        overrides this once heartbeats start flowing — but until then
        the sensor would otherwise sit Unknown for ~45 s after HA boot.
        """
        if not hasattr(self, "_cloud"):
            return
        net = await self.hass.async_add_executor_job(self._cloud.fetch_net)
        if not isinstance(net, dict):
            return

        current_ssid = net.get("current")
        ap_list = net.get("list") if isinstance(net.get("list"), list) else []
        match = next(
            (
                ap for ap in ap_list
                if isinstance(ap, dict) and ap.get("ssid") == current_ssid
            ),
            None,
        )

        updates: dict[str, Any] = {}
        if isinstance(current_ssid, str) and current_ssid:
            updates["wifi_ssid"] = current_ssid
        if match is not None:
            ip = match.get("ip")
            rssi = match.get("rssi")
            if isinstance(ip, str) and ip:
                updates["wifi_ip"] = ip
            if isinstance(rssi, int):
                # Only seed the RSSI if the heartbeat hasn't already
                # populated it — avoid overwriting a live value with a
                # potentially stale catalogue entry.
                if self.data.wifi_rssi_dbm is None:
                    updates["wifi_rssi_dbm"] = rssi

        if not updates:
            return

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _refresh_gps(self) -> None:
        """Absolute GPS via getRecords → position_lat/lon (+ attrs). None clears."""
        if not hasattr(self, "_cloud"):
            return
        gps = await self.hass.async_add_executor_job(self._cloud.fetch_gps)
        if gps is None:
            if (self.data.position_lat is not None or self.data.position_lon is not None
                    or self.data.gps_update_time is not None or self.data.gps_card4g is not None):
                self.async_set_updated_data(dataclasses.replace(
                    self.data, position_lat=None, position_lon=None,
                    gps_update_time=None, gps_card4g=None))
            return
        new = dataclasses.replace(
            self.data, position_lat=gps["lat"], position_lon=gps["lon"],
            gps_update_time=gps.get("update_time"), gps_card4g=gps.get("card4g"))
        if new != self.data:
            self.async_set_updated_data(new)

    async def _refresh_remote(self) -> None:
        """4G SIM status via REMOTE."""
        if not hasattr(self, "_cloud"):
            return
        r = await self.hass.async_add_executor_job(self._cloud.fetch_remote)
        if not r:
            return
        # sim_expired_time is fed from biz_4g_remain's ISO exp_time below (not
        # REMOTE's TZ-ambiguous expiredTime string) so the sensor can be a
        # proper timestamp; REMOTE still owns card_id/active_time/left_days.
        fields = dict(
            sim_active_time=r.get("active_time"), sim_card_id=r.get("card_id"),
            sim_left_days=r.get("left_days"))
        # Chain the SIM-provider quantitative poll, keyed by the ICCID we just
        # learned (REMOTE's card_id). Resilient to stub clouds lacking it.
        fetch_4g = getattr(self._cloud, "fetch_4g_remain", None)
        if fetch_4g is not None and r.get("card_id"):
            g4 = await self.hass.async_add_executor_job(fetch_4g, r.get("card_id"))
            if g4:
                fields["sim_data_remaining_mb"] = g4.get("data_remaining_mb")
                fields["sim_out_of_warranty"] = g4.get("out_of_warranty")
                if g4.get("expiry"):
                    fields["sim_expired_time"] = g4.get("expiry")
        new = dataclasses.replace(self.data, **fields)
        if new != self.data:
            self.async_set_updated_data(new)

    async def _refresh_mpos(self) -> None:
        """On-demand MPOS diagnostic fetch (button-triggered; not scheduled).

        Surfaces the RAW routed-get position for physical-match characterization.
        Never drives MowerState.position_* — diagnostic only.
        """
        if not hasattr(self, "_cloud"):
            return
        res = await self.hass.async_add_executor_job(self._cloud.fetch_mpos)
        new = apply_mpos_result(self.data, res, int(time.time()))
        if new != self.data:
            self.async_set_updated_data(new)
        LOGGER.info("mpos refresh: result=%s", (res or {}).get("result"))

    async def _refresh_messages(self) -> None:
        """Account message lists + unread counts via message-record/list v1,
        device-messages/v2, and share-messages. Trims each list to the cap."""
        if not hasattr(self, "_cloud"):
            return
        entry = getattr(self, "entry", None)
        cap = int(
            entry.options.get(CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP)
            if entry is not None else DEFAULT_MESSAGES_KEEP
        )
        # did is derived the same way as _notifications.py
        did = getattr(self._cloud, "device_id", None) or getattr(self._cloud, "_did", None)
        m = await self.hass.async_add_executor_job(self._cloud.fetch_message_record)
        dev_raw = await self.hass.async_add_executor_job(
            self._cloud.fetch_device_messages, did, 10
        )
        share_raw = await self.hass.async_add_executor_job(
            self._cloud.fetch_share_messages, cap
        )
        kw: dict = {}
        if m:
            kw["service_messages_unread"] = m.get("service_unread")
            kw["system_messages_unread"] = m.get("system_unread")
            kw["latest_service_message"] = m.get("latest")
            kw["service_messages"] = [
                msg.as_dict()
                for msg in _msg.normalize_service(m.get("service_records"))[:cap]
            ]
        if dev_raw is not None:
            fresh = [msg.as_dict() for msg in _msg.normalize_device(dev_raw)]
            kw["device_messages"] = self._merge_device_messages(fresh)
        if share_raw is not None:
            kw["shared_messages"] = [
                msg.as_dict() for msg in _msg.normalize_share(share_raw)[:cap]
            ]
        if not kw:
            return
        new = dataclasses.replace(self.data, **kw)
        if new != self.data:
            self.async_set_updated_data(new)

    async def _refresh_dev(self) -> None:
        """Fetch DEV {fw, mac, ota, sn} and update MowerState.

        DEV is the authoritative source for hardware_serial — the s1p5
        cloud `get_properties` path is unreliable on g2408 (mostly returns
        80001). Once DEV has populated `hardware_serial` we can drop s1p5
        from the slow-poll list. firmware_version source could also move
        here in a future change; today we leave the cloud-record path
        alone since DEV.fw matched it in the 2026-05-04 dump.

        DEV.ota's semantic is unconfirmed (user has Auto-update Firmware
        OFF in the app but DEV.ota = 1). Provisionally surfaced as
        `ota_capable_raw` while we figure out what it actually represents.
        """
        if not hasattr(self, "_cloud"):
            return
        dev = await self.hass.async_add_executor_job(self._cloud.fetch_dev)
        if not isinstance(dev, dict):
            return

        new_serial = dev.get("sn")
        new_fw = dev.get("fw")
        new_ota = dev.get("ota")

        updates: dict[str, Any] = {}
        if isinstance(new_serial, str) and new_serial:
            updates["hardware_serial"] = new_serial
        if isinstance(new_fw, str) and new_fw:
            updates["firmware_version"] = new_fw
        if new_ota is not None:
            try:
                updates["ota_capable_raw"] = int(new_ota)
            except (TypeError, ValueError):
                pass

        ov = await self.hass.async_add_executor_job(
            getattr(self._cloud, "fetch_ota_version", lambda: None)
        )
        if isinstance(ov, dict):
            latest = ov.get("newVersion")
            if isinstance(latest, str) and latest:
                updates["firmware_latest"] = latest
            avail = ov.get("hasNewFirmware")
            if isinstance(avail, bool):
                updates["firmware_update_available"] = avail
            notes = ov.get("description")
            if isinstance(notes, str) and notes:
                updates["firmware_release_notes"] = notes
            cur = ov.get("curVersion")
            if isinstance(cur, str) and cur and "firmware_version" not in updates:
                updates["firmware_version"] = cur

        if not updates:
            return

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)
            if "hardware_serial" in updates:
                self._update_device_registry_serial(updates["hardware_serial"])

    async def _refresh_aiobs(self) -> None:
        """Poll the live AIOBS obstacle markers — ONLY while a mow session is
        active. Mow-gated minutes cadence: the app polls AIOBS only while a human
        is viewing the live map (~281 reads across a multi-day capture); we have no
        "viewing" signal, so the safe analogue is session-gated, one read per timer
        tick. Do NOT poll at seconds cadence / 24-7.
        [cloud/captures/mitm_session_20260619/miio-13267.jsonl@2026-06-17]
        """
        from ..mower.state_snapshot import MowSession  # local import: avoid cycle

        snap = self.state_machine.snapshot()
        mow_session = getattr(snap, "mow_session", None)
        # Gate: only proceed when a mow session is active.
        # The real integration path has MowSession.IN_SESSION; the unit-test stub
        # passes the string "IN_SESSION" — handle both with the positive check
        # (enum value = "in_session", enum name = "IN_SESSION").
        is_active = (
            mow_session == MowSession.IN_SESSION
            or (isinstance(mow_session, str)
                and mow_session in (MowSession.IN_SESSION.name, MowSession.IN_SESSION.value))
        )
        if not is_active:
            return
        hass = getattr(self, "hass", None)
        markers = (
            await hass.async_add_executor_job(self._cloud.fetch_aiobs_markers)
            if hass is not None else self._cloud.fetch_aiobs_markers()
        )
        if markers is None:
            return
        self._obstacle_markers = markers
        for m in markers:
            self._obstacle_marker_log.note(m)

    # _poll_slow_properties REMOVED 2026-05-26.
    # It only fetched s6.3 ([cloud_connected, rssi_dbm]) and s1.5 (serial) via
    # the relay get_properties path, which 80001s when the device is asleep
    # (113 hourly :01 failures in production). Both targets are now redundant:
    #   • wifi_rssi_dbm comes from heartbeat byte[17] (~20 s cadence) directly.
    #   • cloud_connected is implied by MQTT being up (see coordinator
    #     `last_mqtt_unix` + binary_sensor.cloud_connected).
    #   • serial is provided by DEV (CFG.DEV.sn), which the integration's own
    #     comments flagged as authoritative.
    # See docs/research/app-api-surface-2026-05-25.md § 80001 for the full
    # write-up; nothing else called this method.

