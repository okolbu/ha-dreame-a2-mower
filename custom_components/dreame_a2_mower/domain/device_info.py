"""Device-info / connectivity refresh service (layer 4) — refactor-v2 P3.9e.

Moved VERBATIM from ``coordinator/_refreshers.py`` (the DOCK / NET / REMOTE /
DEV / MPOS cloud-poll slices + the pure ``apply_mpos_result`` helper). Each
function takes the coordinator (``coord``) as its first argument; the
coordinator keeps thin ``_RefreshersMixin`` delegators so the public/test
surface (``coord._refresh_dock`` / ``coord._refresh_net`` /
``coord._refresh_remote`` / ``coord._refresh_dev`` / ``coord._refresh_mpos``
and the ``coordinator._refreshers.apply_mpos_result`` re-export, pinned by
``test_phase_c_refreshers`` / ``test_apply_mpos_result``) is unchanged.

See the "Refresher cadence" section of CLAUDE.md for the timer intervals; the
poll ORCHESTRATION (which cadence fires which slice) stays in
``domain/boot.py`` (the composition root's poll orchestrator).
"""
from __future__ import annotations

import dataclasses
import time
from typing import Any

from ..const import LOGGER


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


async def refresh_dock(coord) -> None:
    """Fetch CFG.DOCK → populate dock-position fields on MowerState.

    DOCK returns ``{dock: {connect_status, in_region, x, y, yaw,
    near_x, near_y, near_yaw, path_connect}}``. We pull the inner
    dict and map position fields (x/y/yaw/in_region) onto MowerState
    for the dock-position sensors. connect_status is not used here —
    location is owned solely by s2p1 (dock cluster {6,13,15,16}).
    """
    if not hasattr(coord, "_cloud"):
        return
    dock_outer = await coord.hass.async_add_executor_job(coord._cloud.fetch_dock)
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

    new_state = dataclasses.replace(coord.data, **updates)
    if new_state != coord.data:
        coord.async_set_updated_data(new_state)


async def refresh_net(coord) -> None:
    """Fetch CFG.NET → populate wifi_ssid / wifi_ip / wifi_rssi_dbm.

    NET returns ``{current: ssid, list: [{ip, rssi, ssid}, …]}``.
    We pull the matching entry from `list` (where `ssid == current`)
    and populate the three fields. The s1p1 byte[17] live RSSI
    overrides this once heartbeats start flowing — but until then
    the sensor would otherwise sit Unknown for ~45 s after HA boot.
    """
    if not hasattr(coord, "_cloud"):
        return
    net = await coord.hass.async_add_executor_job(coord._cloud.fetch_net)
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
            if coord.data.wifi_rssi_dbm is None:
                updates["wifi_rssi_dbm"] = rssi

    if not updates:
        return

    new_state = dataclasses.replace(coord.data, **updates)
    if new_state != coord.data:
        coord.async_set_updated_data(new_state)


async def refresh_remote(coord) -> None:
    """4G SIM status via REMOTE."""
    if not hasattr(coord, "_cloud"):
        return
    r = await coord.hass.async_add_executor_job(coord._cloud.fetch_remote)
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
    fetch_4g = getattr(coord._cloud, "fetch_4g_remain", None)
    if fetch_4g is not None and r.get("card_id"):
        g4 = await coord.hass.async_add_executor_job(fetch_4g, r.get("card_id"))
        if g4:
            fields["sim_data_remaining_mb"] = g4.get("data_remaining_mb")
            fields["sim_out_of_warranty"] = g4.get("out_of_warranty")
            if g4.get("expiry"):
                fields["sim_expired_time"] = g4.get("expiry")
    new = dataclasses.replace(coord.data, **fields)
    if new != coord.data:
        coord.async_set_updated_data(new)


async def refresh_mpos(coord) -> None:
    """On-demand MPOS diagnostic fetch (button-triggered; not scheduled).

    Surfaces the RAW routed-get position for physical-match characterization.
    Never drives MowerState.position_* — diagnostic only.
    """
    if not hasattr(coord, "_cloud"):
        return
    res = await coord.hass.async_add_executor_job(coord._cloud.fetch_mpos)
    new = apply_mpos_result(coord.data, res, int(time.time()))
    if new != coord.data:
        coord.async_set_updated_data(new)
    LOGGER.info("mpos refresh: result=%s", (res or {}).get("result"))


async def refresh_dev(coord) -> None:
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
    if not hasattr(coord, "_cloud"):
        return
    dev = await coord.hass.async_add_executor_job(coord._cloud.fetch_dev)
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

    ov = await coord.hass.async_add_executor_job(
        getattr(coord._cloud, "fetch_ota_version", lambda: None)
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

    new_state = dataclasses.replace(coord.data, **updates)
    if new_state != coord.data:
        coord.async_set_updated_data(new_state)
        if "hardware_serial" in updates:
            coord._update_device_registry_serial(updates["hardware_serial"])
