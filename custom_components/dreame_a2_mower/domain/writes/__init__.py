"""Writes-domain services (layer 4) — refactor-v2 P3.9b.

The device/cloud WRITE orchestration extracted VERBATIM from
``coordinator/_writes.py``. Each module owns one write family and takes the
coordinator (``coord``) as its first argument; the coordinator keeps thin
``_WritesMixin`` delegators for its public + test surface.

- ``service.py``   — shared WriteResult plumbing (``_accepted`` /
                     ``_chunked_kv_write_result`` / ``_write_result_from_schedule_exc``)
                     + the OTA-trigger orchestration (``async_trigger_firmware_update``).
                     Documents the set_cfg/set_pre/OTA-trigger transport-home decision.
- ``schedule.py``  — SCHD*V3 schedule writes (txn-id, ``write_schedule``,
                     ``write_schedule_enabled``).
- ``settings.py``  — SETTINGS.* / CFG / PRE / AI_HUMAN writes + the per-map
                     General-mode dual-writes; carries the P2.6/P3.8
                     optimistic-broadcast + per-field revert VERBATIM.
- ``tasks.py``     — ``dispatch_action`` + the ``start_*`` mowing-mode launchers
                     + ``ensure_active_map``.
- ``map_edit.py``  — the ``edit_map`` transaction driver + the map-object CRUD
                     ops + ``write_patrol_point_config`` (o=111 + CRUISED).

The low-level device writers (``set_cfg`` / ``set_pre`` /
``trigger_firmware_update``) STAY in transport at ``cloud_client/_writers.py``;
these services orchestrate them via ``coord._cloud.<writer>`` (a legal
domain(4)→transport(2) downward call).
"""
