"""writes mixin — thin delegators (refactor-v2 P3.9b).

The write orchestration LOGIC moved VERBATIM to the ``domain/writes/`` package
(autopsy #9): ``service`` (shared WriteResult plumbing + OTA trigger),
``schedule``, ``settings``, ``tasks``, ``map_edit``. Each domain function takes
the coordinator (``coord``) as its first argument; this mixin keeps thin
delegating methods so the public/test surface (``coord.write_settings``,
``coord.dispatch_action``, ``coord.edit_map``, the unbound ``_WritesMixin._X``
methods, the ``import coordinator._writes as W`` module handle) is unchanged.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md
(original decomposition) + the refactor-v2 P3 plan.
"""
from __future__ import annotations

from typing import Any

from ..cloud_client import WriteResult
from ..mower.actions import MowerAction
from ..domain.writes import (
    map_edit as _map_edit,
    schedule as _schedule,
    service as _service,
    settings as _settings,
    tasks as _tasks,
)

# Back-compat re-exports: the module-level WriteResult helpers kept their old
# ``coordinator._writes`` home for any importer, and the schedule-write tests
# monkeypatch the SCHD*V3 protocol functions at their NEW module home
# (``domain.writes.schedule``) — see that module.
_accepted = _service._accepted
_chunked_kv_write_result = _service._chunked_kv_write_result
_write_result_from_schedule_exc = _service._write_result_from_schedule_exc


class _WritesMixin:
    """Thin delegators to ``domain.writes`` (P3.9b) — see module docstring."""

    # ------------------------------------------------------------------
    # schedule.py
    # ------------------------------------------------------------------

    def _next_schedule_txn_id(self) -> int:
        """Monotonic ms-epoch txn id (shared across a write's header+chunks).

        Kept on the mixin (not delegated) because it reads/writes the
        coordinator-private lazy ``_last_schedule_txn_id`` via ``getattr``
        default — a domain-module ``getattr(coord, "_priv")`` would trip
        ``test_no_coordinator_private_getattr``, and the bare ``_WritesMixin()``
        test double has no ``_core`` init to seed the attr. ``domain.writes.
        schedule.write_schedule`` calls ``coord._next_schedule_txn_id()``.
        """
        import time as _time

        txn = int(_time.time() * 1000)
        last = getattr(self, "_last_schedule_txn_id", 0)
        if txn <= last:
            txn = last + 1
        self._last_schedule_txn_id = txn
        return txn

    async def write_schedule(
        self, new_slots: tuple[Any, ...] | list[Any]
    ) -> WriteResult:
        """Delegates to ``domain.writes.schedule.write_schedule`` (P3.9b)."""
        return await _schedule.write_schedule(self, new_slots)

    async def write_schedule_enabled(
        self, slot_id: int, enabled: bool
    ) -> WriteResult:
        """Delegates to ``domain.writes.schedule.write_schedule_enabled`` (P3.9b)."""
        return await _schedule.write_schedule_enabled(self, slot_id, enabled)

    # ------------------------------------------------------------------
    # settings.py
    # ------------------------------------------------------------------

    async def write_ai_human_enabled(self, enabled: bool) -> WriteResult:
        """Delegates to ``domain.writes.settings.write_ai_human_enabled`` (P3.9b)."""
        return await _settings.write_ai_human_enabled(self, enabled)

    def _fetch_fresh_settings_blob(self) -> list[dict[str, Any]] | None:
        """Delegates to ``domain.writes.settings.fetch_fresh_settings_blob`` (P3.9b)."""
        return _settings.fetch_fresh_settings_blob(self)

    async def write_settings(
        self, *, map_id: int, field: str, value: Any
    ) -> WriteResult:
        """Delegates to ``domain.writes.settings.write_settings`` (P3.9b)."""
        return await _settings.write_settings(
            self, map_id=map_id, field=field, value=value
        )

    async def write_setting(
        self,
        cfg_key: str,
        new_full_value: Any,
        field_updates: dict[str, Any] | None = None,
    ) -> WriteResult:
        """Delegates to ``domain.writes.settings.write_setting`` (P3.9b)."""
        return await _settings.write_setting(
            self, cfg_key, new_full_value, field_updates
        )

    async def _dispatch_cfg_write(self, cfg_key: str, value: Any) -> WriteResult:
        """Delegates to ``domain.writes.settings.dispatch_cfg_write`` (P3.9b)."""
        return await _settings.dispatch_cfg_write(self, cfg_key, value)

    async def _write_pre_scoped(self, map_id: int, apply_fn) -> WriteResult:
        """Delegates to ``domain.writes.settings.write_pre_scoped`` (P3.9b)."""
        return await _settings.write_pre_scoped(self, map_id, apply_fn)

    async def write_map_general_setting(
        self, *, map_id: int, pre_index: int, pre_value,
        settings_field: str | None = None, settings_value=None,
    ) -> WriteResult:
        """Delegates to ``domain.writes.settings.write_map_general_setting`` (P3.9b)."""
        return await _settings.write_map_general_setting(
            self, map_id=map_id, pre_index=pre_index, pre_value=pre_value,
            settings_field=settings_field, settings_value=settings_value,
        )

    async def write_map_general_ai_bit(
        self, *, map_id: int, bit: int, on: bool, settings_value: int,
    ) -> WriteResult:
        """Delegates to ``domain.writes.settings.write_map_general_ai_bit`` (P3.9b)."""
        return await _settings.write_map_general_ai_bit(
            self, map_id=map_id, bit=bit, on=on, settings_value=settings_value,
        )

    # ------------------------------------------------------------------
    # tasks.py
    # ------------------------------------------------------------------

    async def dispatch_action(
        self, action: MowerAction, parameters: dict[str, Any] | None = None
    ) -> WriteResult:
        """Delegates to ``domain.writes.tasks.dispatch_action`` (P3.9b)."""
        return await _tasks.dispatch_action(self, action, parameters)

    async def _ensure_active_map(self, map_id: int) -> WriteResult:
        """Delegates to ``domain.writes.tasks.ensure_active_map`` (P3.9b)."""
        return await _tasks.ensure_active_map(self, map_id)

    async def start_mowing_all_areas(self, *, map_id: int) -> WriteResult:
        """Delegates to ``domain.writes.tasks.start_mowing_all_areas`` (P3.9b)."""
        return await _tasks.start_mowing_all_areas(self, map_id=map_id)

    async def start_mowing_edge(self, *, map_id: int) -> WriteResult:
        """Delegates to ``domain.writes.tasks.start_mowing_edge`` (P3.9b)."""
        return await _tasks.start_mowing_edge(self, map_id=map_id)

    async def start_mowing_zone(self, *, map_id: int, zone_id: int) -> WriteResult:
        """Delegates to ``domain.writes.tasks.start_mowing_zone`` (P3.9b)."""
        return await _tasks.start_mowing_zone(self, map_id=map_id, zone_id=zone_id)

    async def start_mowing_spot(self, *, map_id: int, spot_id: int) -> WriteResult:
        """Delegates to ``domain.writes.tasks.start_mowing_spot`` (P3.9b)."""
        return await _tasks.start_mowing_spot(self, map_id=map_id, spot_id=spot_id)

    async def start_go_to_point(self, *, map_id: int, point_id: int) -> WriteResult:
        """Delegates to ``domain.writes.tasks.start_go_to_point`` (P3.9b)."""
        return await _tasks.start_go_to_point(self, map_id=map_id, point_id=point_id)

    async def start_point_patrol(self, *, map_id: int, point_ids: list[int]) -> WriteResult:
        """Delegates to ``domain.writes.tasks.start_point_patrol`` (P3.9b)."""
        return await _tasks.start_point_patrol(self, map_id=map_id, point_ids=point_ids)

    async def start_edge_patrol(self, *, map_id: int, contour_ids: list[list[int]]) -> WriteResult:
        """Delegates to ``domain.writes.tasks.start_edge_patrol`` (P3.9b)."""
        return await _tasks.start_edge_patrol(self, map_id=map_id, contour_ids=contour_ids)

    # ------------------------------------------------------------------
    # map_edit.py
    # ------------------------------------------------------------------

    async def edit_map(
        self, map_id: int, mutations: list[tuple[int, dict | None]]
    ) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.edit_map`` (P3.9b)."""
        return await _map_edit.edit_map(self, map_id, mutations)

    async def rename_zone(self, map_id: int, region: int, name: str) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.rename_zone`` (P3.9b)."""
        return await _map_edit.rename_zone(self, map_id, region, name)

    async def delete_map_object(
        self, map_id: int, object_id: int, category: int
    ) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.delete_map_object`` (P3.9b)."""
        return await _map_edit.delete_map_object(self, map_id, object_id, category)

    async def create_no_go(self, map_id, shape, points, radius=0.0, object_id=-1) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.create_no_go`` (P3.9b)."""
        return await _map_edit.create_no_go(self, map_id, shape, points, radius, object_id)

    async def create_ignore_obstacle(self, map_id, points, object_id=-1) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.create_ignore_obstacle`` (P3.9b)."""
        return await _map_edit.create_ignore_obstacle(self, map_id, points, object_id)

    async def create_mow_shape(self, map_id, shape, points, object_id=-1) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.create_mow_shape`` (P3.9b)."""
        return await _map_edit.create_mow_shape(self, map_id, shape, points, object_id)

    async def create_spot(self, map_id, points, object_id=-1) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.create_spot`` (P3.9b)."""
        return await _map_edit.create_spot(self, map_id, points, object_id)

    async def create_maintenance_point(
        self, map_id, x, y, heading=0.0, object_id=-1
    ) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.create_maintenance_point`` (P3.9b)."""
        return await _map_edit.create_maintenance_point(
            self, map_id, x, y, heading, object_id
        )

    async def create_patrol_point(
        self, map_id, x, y, heading=0.0, object_id=-1
    ) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.create_patrol_point`` (P3.9b)."""
        return await _map_edit.create_patrol_point(
            self, map_id, x, y, heading, object_id
        )

    async def write_patrol_point_config(
        self, *, map_id: int, point_id: int, cycles: int, auto_capture: bool
    ) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.write_patrol_point_config`` (P3.9b)."""
        return await _map_edit.write_patrol_point_config(
            self, map_id=map_id, point_id=point_id,
            cycles=cycles, auto_capture=auto_capture,
        )

    async def split_zone(self, map_id, zone_id, line_start, line_end) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.split_zone`` (P3.9b)."""
        return await _map_edit.split_zone(self, map_id, zone_id, line_start, line_end)

    async def merge_zones(self, map_id, ids) -> WriteResult:
        """Delegates to ``domain.writes.map_edit.merge_zones`` (P3.9b)."""
        return await _map_edit.merge_zones(self, map_id, ids)

    # ------------------------------------------------------------------
    # service.py
    # ------------------------------------------------------------------

    async def async_trigger_firmware_update(self) -> bool:
        """Delegates to ``domain.writes.service.async_trigger_firmware_update`` (P3.9b)."""
        return await _service.async_trigger_firmware_update(self)
