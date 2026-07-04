"""refreshers mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import dataclasses
import hashlib
import time
from typing import TYPE_CHECKING, Any


from ..protocol import message_record as _msg
from ..const import (
    CONF_MESSAGES_KEEP,
    DEFAULT_MESSAGES_KEEP,
    LOGGER,
)
from ..domain import gps as _gps


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
        """Delegates to ``domain.gps.refresh_gps`` (P3.9d).

        Only the GPS refresh moved to the domain layer this task; the rest of
        the ``_refresh_*`` cycles stay here until 9e dissolves the poll body.
        """
        await _gps.refresh_gps(self)

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
            if self._obstacle_markers:
                self._obstacle_markers = []
                if getattr(self, "hass", None) is not None:
                    self._schedule_render_base()
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
        # Trigger a re-render so new markers paint on the live map immediately.
        if getattr(self, "hass", None) is not None:
            self._schedule_render_base()
        # Download photos for any pending markers (bounded: one pass per tick).
        try:
            await self._fetch_pending_obstacle_photos()
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("[aiobs] _fetch_pending_obstacle_photos raised: %s", exc)

    async def _fetch_pending_obstacle_photos(self) -> None:
        """Download photos for live-session AIOBS markers via the file-bridge client.

        Bounded: iterates self._obstacle_markers (the CURRENT live-session set),
        which is volatile and cleared at session end — so this naturally does NOT
        retry ancient cross-session failures.  Within the current mow we attempt
        every marker whose stored status is not yet ready/gone on each 2-min tick.
        This retries backend_unavailable markers mid-session so photos are captured
        as soon as the backend recovers.  One attempt per marker per tick — not a
        tight inner retry.

        On backend failure → mark backend_unavailable; on success → store bytes
        in PhotoArchive (category obstacle_ephemeral) and flip to ready.
        Per-marker failures are isolated so one bad marker doesn't abort the loop.
        [UNVERIFIED signer — backend currently down; loop marks all attempts
        backend_unavailable until the backend is verified and returns bytes]
        """
        log = self._obstacle_marker_log
        # Build a quick status-by-id map from the durable log so we can skip
        # markers that are already captured or confirmed gone.
        status_by_id = {r.id: r.image_status for r in log.all()}

        get_file = getattr(self._cloud, "get_device_file", None)
        hass = getattr(self, "hass", None)

        for marker in list(self._obstacle_markers):
            # Skip already-captured or gone markers; default to "pending" if the
            # marker hasn't been noted yet (note() is called earlier in _refresh_aiobs
            # so this is a defensive fallback only).
            if status_by_id.get(marker.id, "pending") in {"ready", "gone"}:
                continue
            try:
                fn = f"{marker.filename}.jpg"
                if get_file is None:
                    log.set_status(marker.id, "backend_unavailable")
                    continue
                data = (
                    await hass.async_add_executor_job(get_file, fn)
                    if hass is not None else get_file(fn)
                )
                if not data:
                    log.set_status(marker.id, "backend_unavailable")
                    continue
                md5 = hashlib.md5(data).hexdigest()
                self._photo_archive.archive(
                    name=fn,
                    unix_ts=int(marker.detection_epoch or 0),
                    data=data,
                    is_person=False,
                    category="obstacle_ephemeral",
                )
                log.set_status(marker.id, "ready", image_md5=md5)
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("[aiobs] photo fetch failed for %s: %s", marker.id, exc)

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

