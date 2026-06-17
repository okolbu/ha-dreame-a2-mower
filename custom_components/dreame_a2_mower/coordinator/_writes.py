"""writes mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..archive.lidar import LidarArchive
from ..archive.session import ArchivedSession, SessionArchive
from ..wifi_archive_store import WifiArchiveEntry, WifiArchiveStore
from ..cloud_client import DreameA2CloudClient, WriteResult
from ..const import (
    CONF_COUNTRY,
    CONF_LIDAR_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_MAX_MB,
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
from ..protocol.schedule_action import (
    read_live_schedule,
    write_schedule_enabled_state,
    write_schedule_row,
)
from ..protocol.schedule_encode import encode_schedule_blob
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
    _consumable_pct_remaining,
    _project_north_east,
    apply_property_to_state,
)

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


class _WritesMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    def _next_schedule_txn_id(self) -> int:
        """Monotonic ms-epoch txn id (shared across a write's header+chunks)."""
        import time as _time

        txn = int(_time.time() * 1000)
        last = getattr(self, "_last_schedule_txn_id", 0)
        if txn <= last:
            txn = last + 1
        self._last_schedule_txn_id = txn
        return txn

    async def write_schedule(
        self,
        new_slots: tuple[Any, ...] | list[Any],
    ) -> bool:
        """Push changed schedule slots to the device via the SCHD*V3 transport.

        new_slots is a sequence of ScheduleSlot dataclasses (.plans is the
        source of truth; .raw_blob_b64 is ignored — re-encoded). Reads the
        authoritative rows, writes only slots whose re-encoded blob or name
        changed, preserving each slot's enabled state, bumping the schedule
        version. The SCHEDULE.* KV is intentionally NOT written (the device
        ignores it; see dreame-app-schedule-write-2026-06-10.md).
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_schedule: cloud client not ready")
            return False

        # Read the authoritative LIVE schedule once (rows for the skip-gate +
        # the live version to bump). The SCHEDULE.* KV / cloud_state.version is
        # a stale cache, so deriving the base version from it could emit a
        # new_version BELOW the device's current and get the write rejected
        # (verified 2026-06-17: KV v=35477 vs live v=58177).
        live = await self.hass.async_add_executor_job(
            read_live_schedule, self._cloud.action
        )
        if live is not None:
            rows = live.get("d") or []
            base_version = int(live.get("v") or 0)
        else:
            rows = []
            cs = self.cloud_state
            base_version = cs.schedule.version if cs is not None else 0
        new_version = base_version + 1

        by_slot = {
            r[0]: r for r in rows if isinstance(r, list) and len(r) == 4
        }
        # SCHDSV3 `s` is the FULL per-slot enabled array; build it once from the
        # live rows so editing one season's plans preserves the OTHER season's
        # on/off (sending [thisslot, 0] would flip the active season).
        # Absent slot → 0 (disabled): a never-configured slot is off on the
        # device, and defaulting to 1 would wrongly enable it.
        enabled_array = [
            int(by_slot[i][1]) if i in by_slot else 0 for i in (0, 1)
        ]

        ok = True
        async with self._chunked_write_lock:
            for slot in new_slots:
                blob_b64 = encode_schedule_blob(tuple(slot.plans))
                # Name is HTML-escaped on the wire — only `&` (the device read
                # row carries `Spr &amp; Sum`); `<`/`>`/`"` appear unescaped.
                # decode does html.unescape, so compare AND write the escaped
                # form, else `&`-names never match the skip gate and drift via
                # double-escape on each save.
                wire_name = (slot.name or "").replace("&", "&amp;")
                prev = by_slot.get(slot.slot_id)
                prev_blob = prev[3] if prev else None
                prev_name = prev[2] if prev else None
                if (
                    prev is not None
                    and blob_b64 == prev_blob
                    and wire_name == prev_name
                ):
                    continue  # unchanged — skip (idempotent, no version churn)
                txn_id = self._next_schedule_txn_id()
                try:
                    await self.hass.async_add_executor_job(
                        lambda s=slot, b=blob_b64, t=txn_id, n=wire_name, ea=enabled_array: write_schedule_row(
                            self._cloud.action,
                            slot=s.slot_id,
                            enabled_array=ea,
                            name=n,
                            blob_b64=b,
                            version=new_version,
                            txn_id=t,
                        )
                    )
                    LOGGER.info(
                        "[schedule-write] slot %d, %d plan(s), v→%d, blob_len=%d",
                        slot.slot_id, len(slot.plans), new_version, len(blob_b64),
                    )
                except Exception as exc:  # noqa: BLE001 — surface, keep going
                    ok = False
                    LOGGER.warning(
                        "[schedule-write] slot %d rejected: %r", slot.slot_id, exc
                    )

        await self._refresh_cloud_state()
        return ok

    async def write_schedule_enabled(self, slot_id: int, enabled: bool) -> bool:
        """Enable or disable one schedule season via a standalone SCHDSV3 write.

        Seasons are mutually exclusive (device-enforced): enabling a slot makes
        it the sole active one; disabling a slot sets it off (and, since only one
        is ever on, leaves no schedule running). Reads the live schedule for the
        fresh version + current enabled states, then writes the full array.

        Does NOT guard against an active task — the service layer does (it owns
        the user-facing ServiceValidationError).
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_schedule_enabled: cloud client not ready")
            return False

        live = await self.hass.async_add_executor_job(
            read_live_schedule, self._cloud.action
        )
        if live is not None:
            rows = live.get("d") or []
            version = int(live.get("v") or 0)
            by_slot = {r[0]: r for r in rows if isinstance(r, list) and len(r) == 4}
            current = [int(by_slot[i][1]) if i in by_slot else 0 for i in (0, 1)]
        else:
            cs = self.cloud_state
            version = cs.schedule.version if cs is not None else 0
            current = [0, 0]
            if cs is not None:
                for s in cs.schedule.slots:
                    if s.slot_id in (0, 1):
                        # s.mode / wire element[1] is the per-slot enabled flag (confirmed app-mitm 2026-06-17).
                        current[s.slot_id] = int(s.mode)

        if enabled:
            new_array = [1 if i == slot_id else 0 for i in (0, 1)]  # sole active
        else:
            new_array = list(current)
            if slot_id in (0, 1):
                new_array[slot_id] = 0

        ok = True
        async with self._chunked_write_lock:
            try:
                await self.hass.async_add_executor_job(
                    lambda v=version, a=new_array: write_schedule_enabled_state(
                        self._cloud.action, version=v, enabled_array=a
                    )
                )
                LOGGER.info(
                    "[schedule-enable] slot %d → %s, s=%s, v=%d",
                    slot_id, "on" if enabled else "off", new_array, version,
                )
            except Exception as exc:  # noqa: BLE001 — surface, keep going
                ok = False
                LOGGER.warning("[schedule-enable] slot %d rejected: %r", slot_id, exc)

        await self._refresh_cloud_state()
        return ok

    async def write_ai_human_enabled(self, enabled: bool) -> bool:
        """Toggle AI_HUMAN.0 (Capture Photos AI Obstacles) via write_chunked_key.

        Cloud value is a JSON-encoded boolean string (`"true"` / `"false"`).
        Privacy auth is gated app-side; here we trust that AI_HUMAN.0
        being writable means the user has accepted the policy in the app.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_ai_human_enabled: cloud client not ready")
            return False
        value = '"true"' if enabled else '"false"'
        LOGGER.info("[ai-human-write] AI_HUMAN.0 → %s", value)
        async with self._chunked_write_lock:
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "AI_HUMAN", value,
            )
            if not ok:
                LOGGER.warning("[ai-human-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok

    def _fetch_fresh_settings_blob(self) -> list[dict[str, Any]] | None:
        """Pull SETTINGS chunks fresh from the cloud and return the
        decoded list. Returns None if the fetch fails or the response
        is malformed.

        Runs in the executor (called via async_add_executor_job from
        write_settings). Targets only the SETTINGS keys instead of the
        full empty-batch dump — one HTTP round-trip, ~1-2KB response.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return None
        # Optimistic key list — we only need the chunks the cloud
        # actually has. We over-fetch up to .8 (8 chunks = 8KB total
        # blob) plus .info; missing keys come back as None and are
        # filtered by the chunk-walk below.
        keys = [f"SETTINGS.{i}" for i in range(8)] + ["SETTINGS.info"]
        try:
            response = self._cloud.get_batch_device_datas(keys)
        except Exception as ex:  # pragma: no cover — defensive
            LOGGER.debug("[settings-write] fresh fetch raised: %s", ex)
            return None
        if not isinstance(response, dict):
            return None
        info = response.get("SETTINGS.info")
        if info is None:
            return None
        try:
            total = int(info)
        except (TypeError, ValueError):
            return None
        chunks: list[str] = []
        i = 0
        while True:
            chunk = response.get(f"SETTINGS.{i}")
            if chunk is None:
                break
            chunks.append(str(chunk))
            i += 1
        if not chunks:
            return None
        full = "".join(chunks)[:total]
        import json as _json
        try:
            parsed = _json.loads(full)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, list) else None

    async def write_settings(self, *, map_id: int, field: str, value: Any) -> bool:
        """Push one SETTINGS field change to the cloud.

        Pre-write fresh-fetch: pulls the current SETTINGS blob from the
        cloud right before the write so the resulting blob carries
        whatever values the app (or another HA instance) most recently
        saved. Without this step, HA's read-modify-write would be based
        on the last 2-min poll's snapshot — every other field on every
        map would be stamped back to its stale value, clobbering anything
        the app changed in the meantime.

        Read-modify-write mutates the target field on every entry that
        carries the target map_id; other fields and other maps are left
        untouched. Serializes against _chunked_write_lock so concurrent
        writes can't race against the same fresh fetch.

        Returns True iff cloud accepted (code=0). Triggers a cloud_state
        refresh on success so the local view reflects what landed.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_settings: cloud client not ready")
            return False
        from ..protocol.settings import parse_settings_batch, write_setting

        async with self._chunked_write_lock:
            # Always try a fresh fetch first so the RMW is on cloud-current data.
            fresh_raw = await self.hass.async_add_executor_job(
                self._fetch_fresh_settings_blob,
            )
            if fresh_raw is not None:
                settings_raw = fresh_raw
                # Mirror onto cloud_state so subsequent reads see fresh values.
                # Defensive: cloud_state may not exist yet if write happens
                # before the first periodic refresh.
                cs = self.cloud_state
                if cs is not None:
                    self.cloud_state = dataclasses.replace(
                        cs, settings=parse_settings_batch(fresh_raw),
                    )
            else:
                # Fresh fetch failed; fall back to the cached state and accept
                # the higher-stale-cache risk for this one write.
                cs = self.cloud_state
                if cs is None:
                    LOGGER.warning(
                        "write_settings: cloud_state empty and fresh fetch failed"
                    )
                    return False
                settings_raw = cs.settings.raw
                LOGGER.warning(
                    "[settings-write] fresh fetch failed; falling back to cached state"
                )
            try:
                new_raw = write_setting(
                    settings_raw, map_id=map_id, field=field, value=value,
                )
            except KeyError as ex:
                LOGGER.warning("write_settings: KeyError %s", ex)
                return False
            import json as _json
            json_value = _json.dumps(new_raw, separators=(",", ":"))
            LOGGER.info(
                "[settings-write] field=%s map=%d value=%r json_len=%d (fresh=%s)",
                field, map_id, value, len(json_value), fresh_raw is not None,
            )
            ok, response = await self.hass.async_add_executor_job(
                self._cloud.write_chunked_key, "SETTINGS", json_value,
            )
            if not ok:
                LOGGER.warning("[settings-write] rejected: %r", response)
        await self._refresh_cloud_state()
        return ok

    async def write_setting(
        self,
        cfg_key: str,
        new_full_value: Any,
        field_updates: dict[str, Any] | None = None,
    ) -> bool:
        """Write a settings value to the mower via the CFG write path.

        The entity layer (F4.6.x) is responsible for constructing the full
        wire-level value (e.g. the complete DND list ``[enabled, start_min,
        end_min]``) and passing it as ``new_full_value``.  This method relays
        it to the right ``cloud_client`` method without interpreting the value.

        ``cfg_key`` must be one of the known CFG key strings (``CLS``, ``VOL``,
        ``LANG``, ``DND``, ``WRP``, ``LOW``, ``BAT``, ``LIT``, ``ATA``,
        ``REC``) or the special key ``PRE`` (full-array write via
        ``cloud_client.set_pre``).

        Optimistic state update (optional):
          If ``field_updates`` is provided it must be a ``{field_name: value}``
          dict whose keys are valid ``MowerState`` field names.  The state is
          updated optimistically before the cloud call and reverted if the cloud
          call fails.  When ``field_updates`` is ``None`` (the default) no
          optimistic update is applied — the entity layer handles its own
          optimistic state.

        Returns ``True`` on cloud success, ``False`` on failure.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("write_setting %s: cloud client not ready", cfg_key)
            return False

        if cfg_key not in self._CFG_SINGLE_KEYS and cfg_key != "PRE":
            LOGGER.warning("write_setting: unknown cfg_key %r", cfg_key)
            return False

        # Optimistic update — snapshot state and apply field_updates now.
        prior_state = self.data
        if field_updates:
            try:
                self.async_set_updated_data(
                    dataclasses.replace(self.data, **field_updates)
                )
            except TypeError as ex:
                LOGGER.warning(
                    "write_setting %s: invalid field_updates %r — %s; skipping optimistic update",
                    cfg_key, field_updates, ex,
                )
                # Don't revert — no update was applied; just proceed with the write.

        # Dispatch to the right cloud_client method.
        success = await self._dispatch_cfg_write(cfg_key, new_full_value)

        if not success:
            LOGGER.warning(
                "write_setting %s=%r: cloud write failed; reverting optimistic update",
                cfg_key, new_full_value,
            )
            if field_updates and self.data != prior_state:
                self.async_set_updated_data(prior_state)

        return success

    async def _dispatch_cfg_write(self, cfg_key: str, value: Any) -> bool:
        """Route a CFG write to the appropriate cloud_client method.

        All CFG single-key writes use ``cloud_client.set_cfg``.
        ``PRE`` uses ``cloud_client.set_pre`` (full-array write).

        Runs the blocking I/O in the executor per spec §3.
        """
        if cfg_key == "PRE":
            if not isinstance(value, list):
                LOGGER.warning(
                    "_dispatch_cfg_write PRE: expected list, got %r",
                    type(value).__name__,
                )
                return False
            return await self.hass.async_add_executor_job(
                self._cloud.set_pre, value
            )

        # All other CFG keys — single-key set via set_cfg().
        return await self.hass.async_add_executor_job(
            self._cloud.set_cfg, cfg_key, value
        )

    async def dispatch_action(
        self, action: MowerAction, parameters: dict[str, Any] | None = None
    ) -> WriteResult:
        """Dispatch a typed mower action.

        Looks up the action in ACTION_TABLE. local_only actions are handled
        internally (currently only FINALIZE_SESSION — its actual
        implementation lands in F5). Cloud actions go via the routed path
        (s2 aiid=50) since the direct (siid, aiid) call returns 80001 on
        g2408.

        For actions that have a ``routed_o`` opcode, uses
        ``cloud_client.routed_action(op, extra)`` — the working path on g2408.
        For actions that have only ``siid``/``aiid`` (no opcode), falls back
        to a direct ``cloud_client.action(siid, aiid)`` call.

        Returns a :class:`WriteResult` carrying the honest device verdict for
        the cloud path, or a synthetic one for the local-only / cfg-toggle /
        not-ready / unknown-action / error branches. **Non-raising** — errors
        and timeouts are logged and folded into a not-accepted WriteResult so
        the integration keeps going and existing callers (which ignore the
        return value in Task A) are unaffected. Surfacing rejections to the
        user is Task B's job.
        """
        parameters = parameters or {}
        entry = ACTION_TABLE.get(action)
        if entry is None:
            LOGGER.warning("dispatch_action: unknown action %r", action)
            return WriteResult.not_delivered(f"unknown action {action!r}")

        if entry.get("local_only"):
            # FINALIZE_SESSION — integration-internal action; routes to the
            # finalize-incomplete path (F5.10.1).  Forces an "(incomplete)"
            # archive of whatever the live_map currently holds, clears
            # pending_session_* state, and calls live_map.end_session().
            # Safe to call even when no session is active (no-ops cleanly).
            if action == MowerAction.FINALIZE_SESSION:
                import time as _time
                LOGGER.info(
                    "dispatch_action: FINALIZE_SESSION — running finalize-incomplete path"
                )
                await self._run_finalize_incomplete(int(_time.time()))
            else:
                LOGGER.info(
                    "dispatch_action: local-only %s — no implementation yet", action.name
                )
            # Local-only actions have no device round-trip; they always "succeed".
            return WriteResult.local_ok()

        # cfg_toggle_field path — reads the named MowerState field, computes
        # the toggled (boolean NOT) value, and calls write_setting.
        # Used for LOCK_BOT_TOGGLE → CFG key CLS.  This branch runs before
        # the cloud-client path; write_setting itself handles executor dispatch.
        cfg_toggle_field = entry.get("cfg_toggle_field")
        if cfg_toggle_field is not None:
            cfg_key = entry.get("cfg_key")
            if not cfg_key:
                LOGGER.warning(
                    "dispatch_action %s: cfg_toggle_field set but cfg_key missing — skipped",
                    action.name,
                )
                return WriteResult.not_delivered(
                    "cfg_toggle_field set but cfg_key missing"
                )
            current = getattr(self.data, cfg_toggle_field, None)
            toggled = not bool(current)
            LOGGER.info(
                "dispatch_action: %s toggle %s=%r → %r via write_setting(%r)",
                action.name, cfg_toggle_field, current, toggled, cfg_key,
            )
            ok = await self.write_setting(
                cfg_key,
                int(toggled),  # CLS wire value is int {0, 1}
                field_updates={cfg_toggle_field: toggled},
            )
            # write_setting returns only a bool — it never surfaces a device
            # `-3`, so a rejection carries code=None like every other synthetic
            # not-accepted result (NOT a fabricated wire code).
            if ok:
                return WriteResult.local_ok()
            return WriteResult(
                delivered=True, accepted=False, code=None,
                msg="setting write rejected",
            )

        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("dispatch_action: cloud client not ready; %s deferred", action.name)
            return WriteResult.not_delivered("cloud not ready")

        routed_o = entry.get("routed_o")
        payload_fn = entry.get("payload_fn")

        # START_EDGE_MOW default-contour resolution. When the caller doesn't
        # specify ``contour_ids``, we want to edge every zone's outer
        # perimeter (entries in the cached map's contour table whose
        # second-int = 0). This matches the Dreame app's behaviour and
        # avoids the firmware's "edge every contour including merged
        # sub-zone seams" mode that drains the edge-mode budget on
        # invisible internal segments and triggers FTRTS.
        # See docs/research/g2408-protocol.md §4.6 (2026-05-05 finding).
        if action == MowerAction.START_EDGE_MOW and not parameters.get("contour_ids"):
            map_data = self.cloud_state.maps_by_id.get(self._active_map_id)
            avail = getattr(map_data, "available_contour_ids", ()) if map_data else ()
            outer = [list(cid) for cid in avail if len(cid) == 2 and cid[1] == 0]
            if outer:
                parameters = {**parameters, "contour_ids": outer}
                LOGGER.info(
                    "dispatch_action: START_EDGE_MOW defaulting contour_ids to "
                    "all outer perimeters %s (from %d cached contours)",
                    outer, len(avail),
                )
            # else: fall through to _edge_mow_payload's [[1, 0]] last-resort
            # fallback (map data not loaded yet on this start).

        try:
            extra = payload_fn(parameters) if payload_fn else None
        except ValueError as ex:
            LOGGER.warning("dispatch_action %s: payload error: %s", action.name, ex)
            return WriteResult.not_delivered(f"payload error: {ex}")

        LOGGER.info(
            "dispatch_action: %s via routed op=%s extra=%s",
            action.name, routed_o, extra,
        )

        try:
            if routed_o is not None:
                # Action opcode path — works on g2408 (cfg_action.call_action_op).
                # routed_action already returns an honest WriteResult; propagate.
                return await self.hass.async_add_executor_job(
                    self._cloud.routed_action, routed_o, extra
                )
            # Direct siid/aiid path — returns 80001 on g2408 for most actions,
            # but included for completeness (PAUSE/DOCK/STOP/etc. may succeed
            # via this path on some firmware or cloud configurations).
            siid = entry.get("siid")
            aiid = entry.get("aiid")
            if siid is None or aiid is None:
                LOGGER.warning(
                    "dispatch_action: %s has no routed_o and no siid/aiid — skipped",
                    action.name,
                )
                return WriteResult.not_delivered("no routed_o and no siid/aiid")
            # The direct action() returns the raw device dict or None — wrap it
            # into a WriteResult. We can't read out[0].r here (action() doesn't
            # carry the routed envelope), so a non-None result is treated as
            # delivered+accepted (mirrors routed_action's no-`out` branch).
            result = await self.hass.async_add_executor_job(
                self._cloud.action, siid, aiid
            )
            if result is None:
                return WriteResult.not_delivered("direct action not delivered")
            return WriteResult(delivered=True, accepted=True, code=None)
        except Exception as ex:
            LOGGER.warning("dispatch_action %s failed: %s", action.name, ex)
            return WriteResult.not_delivered(str(ex))

    # ------------------------------------------------------------------
    # Unified mowing-mode wrappers (used by DreameA2MowingModeSelect)
    # ------------------------------------------------------------------

    async def _ensure_active_map(self, map_id: int) -> WriteResult:
        """Switch to map_id via SET_ACTIVE_MAP (op=200) if it isn't already active.

        No-op when the requested map is already active or when
        _active_map_id is None (not yet polled — single-map devices never
        set it, so we fall through and let the firmware pick).  Logs a
        warning and continues on failure so the subsequent mow command
        still fires against whatever map is currently active.

        Returns the SET_ACTIVE_MAP dispatch result so a failed switch is
        visible to the caller; the no-op cases return an accepted result.
        """
        current = self._active_map_id
        if current is None or current == map_id:
            return WriteResult.local_ok()
        try:
            return await self.dispatch_action(
                MowerAction.SET_ACTIVE_MAP, {"map_id": map_id}
            )
        except Exception as ex:
            LOGGER.warning(
                "start_mowing: SET_ACTIVE_MAP(map_id=%d) failed: %s — "
                "proceeding with current active map %s",
                map_id,
                ex,
                current,
            )
            return WriteResult.not_delivered(str(ex))

    async def start_mowing_all_areas(self, *, map_id: int) -> WriteResult:
        """Start all-areas mow on the given map (op=100).

        Switches the active map first if needed.  The all-areas TASK
        envelope doesn't carry a map_id itself; op=200 SET_ACTIVE_MAP
        must be sent first when the requested map isn't already active.
        Returns the START dispatch's result.
        """
        await self._ensure_active_map(map_id)
        return await self.dispatch_action(MowerAction.START_MOWING, {})

    async def start_mowing_edge(self, *, map_id: int) -> WriteResult:
        """Start edge mow on the given map (op=101)."""
        await self._ensure_active_map(map_id)
        return await self.dispatch_action(MowerAction.START_EDGE_MOW, {})

    async def start_mowing_zone(self, *, map_id: int, zone_id: int) -> WriteResult:
        """Start zone mow for a specific zone on the given map (op=102)."""
        await self._ensure_active_map(map_id)
        return await self.dispatch_action(
            MowerAction.START_ZONE_MOW, {"zones": [zone_id]}
        )

    async def start_mowing_spot(self, *, map_id: int, spot_id: int) -> WriteResult:
        """Start spot mow for a specific spot on the given map (op=103)."""
        await self._ensure_active_map(map_id)
        return await self.dispatch_action(
            MowerAction.START_SPOT_MOW, {"spots": [spot_id]}
        )

    async def start_go_to_point(self, *, map_id: int, point_id: int) -> WriteResult:
        """Send the mower to a maintenance/clean point on the given map (op=109).

        Confirmed 2026-05-31: ``routed_action(109, {"point":[id]})``. ``point_id``
        is a per-map cleanPoint id, so the map must be active first.
        """
        await self._ensure_active_map(map_id)
        return await self.dispatch_action(
            MowerAction.GO_TO_POINT, {"point_id": point_id}
        )

    async def start_point_patrol(self, *, map_id: int, point_ids: list[int]) -> WriteResult:
        """Launch a POINT patrol (op=107) over the given cruise points on map_id.

        point_ids are per-map cruisePoint ids, so the map must be active first.
        SEND shape is [UNVERIFIED] — see actions._point_patrol_payload / o107.
        """
        await self._ensure_active_map(map_id)
        return await self.dispatch_action(
            MowerAction.START_POINT_PATROL, {"point_ids": [int(i) for i in point_ids]}
        )

    async def start_edge_patrol(self, *, map_id: int, contour_ids: list[list[int]]) -> WriteResult:
        """Launch an EDGE patrol (op=108) over the given contour pairs on map_id.

        contour_ids are [m, c] pairs (outer perimeters). SEND shape is
        [UNVERIFIED] — see actions._edge_patrol_payload / o108.
        """
        await self._ensure_active_map(map_id)
        return await self.dispatch_action(
            MowerAction.START_EDGE_PATROL, {"contour_ids": [list(c) for c in contour_ids]}
        )

    # ------------------------------------------------------------------
    # PRE dual-write helpers (Phase A2 — per-map General settings)
    # ------------------------------------------------------------------

    async def _write_pre_scoped(self, map_id: int, apply_fn) -> bool:
        """Scoped PRE read for (map_id, region 0) → apply_fn(array) → set_pre.
        apply_fn returns the full write array or None (no base). True only on
        device accept (set_pre out[0].r==0)."""
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("_write_pre_scoped: cloud client not ready")
            return False
        raw = await self.hass.async_add_executor_job(self._cloud.get_pre, map_id, 0)
        new_array = apply_fn(raw)
        if new_array is None:
            LOGGER.warning("_write_pre_scoped: no PRE base for map %s — aborted", map_id)
            return False
        return await self.hass.async_add_executor_job(self._cloud.set_pre, new_array)

    async def write_map_general_setting(
        self, *, map_id: int, pre_index: int, pre_value,
        settings_field: str | None = None, settings_value=None,
    ) -> bool:
        """Dual-write a per-map General-Mode setting: PRE (device) first, then
        SETTINGS (cloud record) if settings_field given. A SETTINGS failure is
        logged but does NOT revert the device. Returns the PRE-write result."""
        from ..protocol import cfg_payloads
        ok = await self._write_pre_scoped(
            map_id,
            lambda raw: cfg_payloads.apply_pre(raw, map_idx=map_id, index=pre_index, value=pre_value),
        )
        if not ok:
            return False
        if settings_field is not None:
            s_ok = await self.write_settings(map_id=map_id, field=settings_field, value=settings_value)
            if not s_ok:
                LOGGER.warning(
                    "write_map_general_setting: PRE ok but SETTINGS %s failed "
                    "(device changed; cloud record stale until reconcile)", settings_field,
                )
        return True

    async def write_map_general_ai_bit(
        self, *, map_id: int, bit: int, on: bool, settings_value: int,
    ) -> bool:
        """Dual-write one AI-recognition bit: PRE[15] bit + SETTINGS.obstacleAvoidanceAi."""
        from ..protocol import cfg_payloads
        ok = await self._write_pre_scoped(
            map_id,
            lambda raw: cfg_payloads.apply_pre_ai_bit(raw, map_idx=map_id, bit=bit, on=on),
        )
        if not ok:
            return False
        s_ok = await self.write_settings(
            map_id=map_id, field="obstacleAvoidanceAi", value=settings_value,
        )
        if not s_ok:
            LOGGER.warning("write_map_general_ai_bit: PRE ok but SETTINGS failed (stale until reconcile)")
        return True

    async def edit_map(
        self, map_id: int, mutations: list[tuple[int, dict | None]]
    ) -> bool:
        """Run a map-edit transaction on `map_id`, then refresh state.

        Sequence: o=200{idx:map_id} -> o=204(p:0) begin -> each mutation(p:0)
        -> o=201(p:1) commit. The target map becomes (and stays) active. Each
        leg is sent via routed_action; the commit (o=201) is ALWAYS sent so the
        device never stays in edit mode even if an earlier leg failed.

        Returns True only when EVERY leg was *accepted* by the device. Each
        ``routed_action`` now returns a :class:`WriteResult` whose ``__bool__``
        is its ``accepted`` flag, so ``ok = ok and bool(leg)`` means "every leg
        accepted" — a delivered-but-rejected leg (e.g. bad region/id, r!=0) now
        correctly drives the return to False, where the old code only caught
        transport-level (None) failures.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning("edit_map: cloud client not ready")
            return False

        async def _send(op, extra=None, *, p=0):
            return await self.hass.async_add_executor_job(
                lambda: self._cloud.routed_action(op, extra, p=p)
            )

        ok = True
        async with self._chunked_write_lock:
            ok = bool(await _send(200, {"idx": int(map_id)})) and ok
            ok = bool(await _send(204)) and ok
            for op, payload in mutations:
                ok = bool(await _send(op, payload)) and ok
            # Commit is always sent (even on prior failure) to exit edit mode.
            ok = bool(await _send(201, p=1)) and ok
        LOGGER.info(
            "[map-edit] map %d, %d mutation(s), ok=%s", map_id, len(mutations), ok
        )
        # Immediate refresh often grabs STALE cloud data — the mower→cloud
        # propagation of a map edit takes seconds-to-a-minute and the next
        # regular refresh is up to ~2 min away, so the edited/deleted shape
        # would linger. Run the immediate refresh anyway, then schedule a few
        # staggered DELAYED re-fetches so the integration picks up the
        # propagated change in seconds. Scheduled unconditionally — a delete
        # that "hasn't applied yet" still benefits — and outside the write
        # lock (async_call_later fires later on the event loop).
        await self._refresh_cloud_state()
        for delay in (8, 20, 40):
            async_call_later(
                self.hass,
                delay,
                lambda _now: self.hass.async_create_task(
                    self._refresh_cloud_state()
                ),
            )
        return ok

    async def rename_zone(self, map_id: int, region: int, name: str) -> bool:
        """Rename mowing zone `region` on `map_id` (o=219)."""
        return await self.edit_map(
            int(map_id), [(219, {"region": int(region), "name": str(name)})]
        )

    async def delete_map_object(
        self, map_id: int, object_id: int, category: int
    ) -> bool:
        """Delete a map object by id+category on `map_id` (o=218).

        category: 0 = zone/no-go/mow-shape, 1 = spot, 2 = patrol/cruise point,
        3 = maintenance point, 4 = ignore-obstacle (all confirmed values;
        app-mitm 2026-06-12 + 2026-06-15 patrol).
        """
        return await self.edit_map(
            int(map_id), [(218, {"id": int(object_id), "type": int(category)})]
        )

    async def create_no_go(self, map_id, shape, points, radius=0.0, object_id=-1) -> bool:
        """Create a no-go area (o=215): shape line(2pt)/polygon(>=3pt)/circle(1pt+radius>0).

        points are [x, y] meter pairs in the map edit-frame.
        object_id: -1 creates a new object; an existing id edits it in place.
        """
        from ..protocol import map_edit_shapes as _mes
        t = _mes.nogo_type(shape)
        pts = _mes.as_pairs(points)
        _mes.validate_nogo(shape, pts, radius=float(radius))
        return await self.edit_map(int(map_id), [(215, {
            "id": int(object_id), "type": t, "points": pts, "radius": float(radius),
        })])

    async def create_ignore_obstacle(self, map_id, points, object_id=-1) -> bool:
        """Create an ignore-obstacle area (o=234, polygon >=3 pt, no radius).

        object_id: -1 creates a new object; an existing id edits it in place.
        """
        from ..protocol import map_edit_shapes as _mes
        pts = _mes.as_pairs(points)
        if len(pts) < 3:
            raise ValueError(f"ignore-obstacle needs >=3 points, got {len(pts)}")
        return await self.edit_map(int(map_id), [(234, {
            "id": int(object_id), "type": 0, "points": pts,
        })])

    async def create_mow_shape(self, map_id, shape, points, object_id=-1) -> bool:
        """Create a decorative mow-shape (o=215 type 9/12-18). square=4pt, others=2pt bbox.

        object_id: -1 creates a new object; an existing id edits it in place.
        """
        from ..protocol import map_edit_shapes as _mes
        t = _mes.mow_shape_type(shape)
        pts = _mes.as_pairs(points)
        _mes.validate_mow_shape(shape, pts)
        return await self.edit_map(int(map_id), [(215, {
            "id": int(object_id), "type": t, "points": pts, "radius": 0,
        })])

    async def create_spot(self, map_id, points, object_id=-1) -> bool:
        """Create (or edit-in-place) a spot area (o=214).

        Spots are 4 axis-aligned corners — same geometry as a no-go rect, but
        their own opcode with NO type/radius/name on the wire. `points` are
        exactly four [x, y] meter pairs in the map edit-frame.
        object_id: -1 creates a new spot; an existing id edits it in place.
        Delete reuses ``delete_map_object`` with category 1.
        """
        from ..protocol import map_edit_shapes as _mes
        pts = _mes.as_pairs(points)
        if len(pts) != 4:
            raise ValueError(f"spot needs exactly 4 points, got {len(pts)}")
        return await self.edit_map(int(map_id), [(214, {
            "id": int(object_id), "points": pts,
        })])

    async def create_maintenance_point(
        self, map_id, x, y, heading=0.0, object_id=-1
    ) -> bool:
        """Create (or move) a maintenance / clean point (o=224).

        Wire payload is a FLAT 3-element array ``[x, y, heading]`` (NOT a
        list-of-pairs). `x`/`y` are meters in the map edit-frame; `heading` is
        in radians and defaults 0.0 (the read map carries no heading, so a MOVE
        — edit-in-place via a real object_id — resets heading to 0).
        object_id: -1 creates a new point; an existing id moves it.
        Delete reuses ``delete_map_object`` with category 3.
        """
        return await self.edit_map(int(map_id), [(224, {
            "id": int(object_id),
            "points": [float(x), float(y), float(heading)],
        })])

    async def create_patrol_point(
        self, map_id, x, y, heading=0.0, object_id=-1
    ) -> bool:
        """Create (or move) a patrol / cruise point (o=223).

        DISTINCT opcode from the maintenance point (o=224), though both are
        oriented points with the same FLAT 3-element wire array
        ``[x, y, heading]``. `x`/`y` are meters in the map edit-frame;
        `heading` is in radians and defaults 0.0 (the read map carries no
        heading, so a MOVE — edit-in-place via a real object_id — resets
        heading to 0). object_id: -1 creates a new point; an existing id moves
        it. Delete reuses ``delete_map_object`` with category 2.
        (wire-confirmed app-mitm 2026-06-15.)
        """
        return await self.edit_map(int(map_id), [(223, {
            "id": int(object_id),
            "points": [float(x), float(y), float(heading)],
        })])

    async def write_patrol_point_config(
        self, *, map_id: int, point_id: int, cycles: int, auto_capture: bool
    ) -> bool:
        """Set a patrol point's per-point cycles + auto-capture.

        DUAL-WRITE — the app sends BOTH of these for every patrol-config change,
        and CRUISED alone does NOT stick (it only updates the cloud CRUISE.0
        record; cycles never reach the device). Order matches the wire
        [app-mitm:2026-06-16 (miio-13267.jsonl, 12:26-12:31 window)]:

          1. routed_action(111, {"point":[point_id, cycles]}) -> {m:'a',p:0,
             o:111,d:{point:[id,cycles]}} — the DEVICE-APPLIED cycles write.
          2. set_cfg("CRUISED", {idx, value:[-1, point_id, auto, cycles]}) —
             the cloud-record half, read back via the CRUISE.0 device-data key
             (no m:g getter on t:CRUISED).

        o=111 carries ONLY [point_id, cycles]; auto_capture lives solely in
        CRUISED (config the device reads at patrol-run time). idx = the 0-based
        map index (== map_id, same convention as PRE). value[0]=-1 is a constant
        sentinel. See inventory.yaml § CRUISED. Returns True only when BOTH legs
        are accepted (out[0].r==0).

        THE WRITE WORKS — it just reads back with lag. Confirmed 2026-06-17: a
        write through this path IS applied (an independent app client reflected
        x1 after an integration write), but CRUISE.0 (the cloud device-data the
        read path uses) propagates slowly, so a poll right after the write
        returns the STALE value. We do NOT need to activate the map (the
        earlier _ensure_active_map was a red herring — writes propagated on the
        build without it; it also had the side-effect of switching the active
        map on a config save). Instead we record an OPTIMISTIC pending write so
        the stale poll cannot revert the user's change — see
        _pending_cruise_writes + _apply_pending_cruise_overlay.
        """
        if int(cycles) not in (1, 2, 3):
            raise ValueError(f"cycles must be 1, 2 or 3, got {cycles!r}")
        # Leg 1: o=111 applies the cycles to the device.
        cycles_ok = await self.hass.async_add_executor_job(
            lambda: self._cloud.routed_action(
                111, {"point": [int(point_id), int(cycles)]}
            )
        )
        # Leg 2: CRUISED records cycles + auto_capture (cloud CRUISE.0).
        value = [-1, int(point_id), 1 if auto_capture else 0, int(cycles)]
        cruised_ok = await self.hass.async_add_executor_job(
            self._cloud.set_cfg, "CRUISED", {"idx": int(map_id), "value": value}
        )
        ok = bool(cycles_ok) and bool(cruised_ok)
        if ok:
            # Optimistic: hold the just-written value over the laggy CRUISE.0
            # cache until a poll confirms it (or the TTL expires).
            import time as _time
            self._pending_cruise_writes[(int(map_id), int(point_id))] = {
                "cycles": int(cycles),
                "auto_capture": bool(auto_capture),
                "ts": _time.time(),
            }
            # Reflect it immediately on the live cloud_state so the UI updates
            # now (the next refresh re-applies the overlay).
            try:
                cfg = self.cloud_state.cruise_config_by_map.setdefault(int(map_id), {})
                cfg[int(point_id)] = {
                    "cycles": int(cycles),
                    "auto_capture": bool(auto_capture),
                }
            except Exception:  # noqa: BLE001 — cloud_state may be unset early
                pass
            # Push to the frontend NOW. Entities (patrol-points sensor + map
            # camera editable_objects) read cloud_state lazily on coordinator
            # update, so without this notify the optimistic value would not
            # surface until the next ~2-min poll — the exact symptom: the app
            # reflects the edit instantly while HA lags minutes.
            notify = getattr(self, "async_update_listeners", None)
            if callable(notify):
                notify()
        return ok

    async def split_zone(self, map_id, zone_id, line_start, line_end) -> bool:
        """Split a zone by a line (o=220). DESTRUCTIVE: clears that zone's schedule/prefs."""
        from ..protocol import map_edit_shapes as _mes
        return await self.edit_map(int(map_id), [(220, {
            "id": int(zone_id),
            "line_start": _mes.pair(line_start),
            "line_end": _mes.pair(line_end),
        })])

    async def merge_zones(self, map_id, ids) -> bool:
        """Merge zones by id list (o=221). DESTRUCTIVE: resets merged prefs."""
        zone_ids = [int(i) for i in ids]
        if len(zone_ids) < 2:
            raise ValueError(f"merge needs >=2 zone ids, got {zone_ids}")
        return await self.edit_map(int(map_id), [(221, {"ids": zone_ids})])

    async def async_trigger_firmware_update(self) -> bool:
        """Fire the OTA "update now" trigger. Returns the device decision
        (False = refused: weak WiFi / charge -- gated device-side)."""
        if not hasattr(self, "_cloud"):
            return False
        return bool(
            await self.hass.async_add_executor_job(
                self._cloud.trigger_firmware_update
            )
        )

