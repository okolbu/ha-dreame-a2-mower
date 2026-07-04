"""Settings-write service (layer 4) — refactor-v2 P3.9b.

The three settings-write transports, extracted VERBATIM from
``coordinator/_writes.py``:

  * SETTINGS.* cloud-record write (``write_settings`` — map-scoped RMW via the
    ``write_chunked_key`` KV transport, with the pre-write fresh-fetch).
  * CFG single-key / PRE array write (``write_setting`` → ``dispatch_cfg_write``
    → ``coord._cloud.set_cfg`` / ``.set_pre``), carrying the P2.6/P3.8
    optimistic-broadcast + per-field revert.
  * AI_HUMAN.0 toggle (``write_ai_human_enabled``).

Plus the per-map General-mode dual-writes (``write_map_general_setting`` /
``write_map_general_ai_bit``) and their scoped PRE helper (``write_pre_scoped``).

Each function takes the coordinator (``coord``) as its first argument; the
low-level device writers stay in transport (see ``service.py`` docstring) and
are reached via ``coord._cloud.set_cfg`` / ``.set_pre``. Cross-method calls stay
``coord.<method>`` so the public/test surface is preserved.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from ...const import LOGGER
from ...cloud_client import WriteResult

from .service import _chunked_kv_write_result


async def write_ai_human_enabled(coord, enabled: bool) -> WriteResult:
    """Toggle AI_HUMAN.0 (Capture Photos AI Obstacles) via write_chunked_key.

    Cloud value is a JSON-encoded boolean string (`"true"` / `"false"`).
    Privacy auth is gated app-side; here we trust that AI_HUMAN.0
    being writable means the user has accepted the policy in the app.

    Returns a :class:`WriteResult` (P2 Task 5 — was a bool); see
    ``_chunked_kv_write_result`` for the honest-signal caveat of the
    iotuserdata KV transport.
    """
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning("write_ai_human_enabled: cloud client not ready")
        return WriteResult.not_delivered("cloud client not ready")
    value = '"true"' if enabled else '"false"'
    LOGGER.info("[ai-human-write] AI_HUMAN.0 → %s", value)
    async with coord._chunked_write_lock:
        ok, response = await coord.hass.async_add_executor_job(
            coord._cloud.write_chunked_key, "AI_HUMAN", value,
        )
        if not ok:
            LOGGER.warning("[ai-human-write] rejected: %r", response)
    await coord._refresh_cloud_state()
    return _chunked_kv_write_result(ok, response)


def fetch_fresh_settings_blob(coord) -> list[dict[str, Any]] | None:
    """Pull SETTINGS chunks fresh from the cloud and return the
    decoded list. Returns None if the fetch fails or the response
    is malformed.

    Runs in the executor (called via async_add_executor_job from
    write_settings). Targets only the SETTINGS keys instead of the
    full empty-batch dump — one HTTP round-trip, ~1-2KB response.
    """
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        return None
    # Optimistic key list — we only need the chunks the cloud
    # actually has. We over-fetch up to .8 (8 chunks = 8KB total
    # blob) plus .info; missing keys come back as None and are
    # filtered by the chunk-walk below.
    keys = [f"SETTINGS.{i}" for i in range(8)] + ["SETTINGS.info"]
    try:
        response = coord._cloud.get_batch_device_datas(keys)
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


async def write_settings(
    coord, *, map_id: int, field: str, value: Any
) -> WriteResult:
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

    Returns a :class:`WriteResult` (P2 Task 5 — was a bool): accepted iff
    the cloud accepted the KV write (code=0; see
    ``_chunked_kv_write_result`` for the transport's honest-signal
    caveat). Local preconditions that abort before any wire attempt
    (no cloud client / no settings base / unknown field) return
    not-delivered. Triggers a cloud_state refresh so the local view
    reflects what landed.
    """
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning("write_settings: cloud client not ready")
        return WriteResult.not_delivered("cloud client not ready")
    from ...protocol.settings import parse_settings_batch, write_setting as _proto_write_setting

    async with coord._chunked_write_lock:
        # Always try a fresh fetch first so the RMW is on cloud-current data.
        fresh_raw = await coord.hass.async_add_executor_job(
            coord._fetch_fresh_settings_blob,
        )
        if fresh_raw is not None:
            settings_raw = fresh_raw
            # Mirror onto cloud_state so subsequent reads see fresh values.
            # Defensive: cloud_state may not exist yet if write happens
            # before the first periodic refresh.
            cs = coord.cloud_state
            if cs is not None:
                coord.cloud_state = dataclasses.replace(
                    cs, settings=parse_settings_batch(fresh_raw),
                )
        else:
            # Fresh fetch failed; fall back to the cached state and accept
            # the higher-stale-cache risk for this one write.
            cs = coord.cloud_state
            if cs is None:
                LOGGER.warning(
                    "write_settings: cloud_state empty and fresh fetch failed"
                )
                return WriteResult.not_delivered(
                    "no settings base (cloud_state empty, fresh fetch failed)"
                )
            settings_raw = cs.settings.raw
            LOGGER.warning(
                "[settings-write] fresh fetch failed; falling back to cached state"
            )
        try:
            new_raw = _proto_write_setting(
                settings_raw, map_id=map_id, field=field, value=value,
            )
        except KeyError as ex:
            LOGGER.warning("write_settings: KeyError %s", ex)
            return WriteResult.not_delivered(f"unknown settings field: {ex}")
        import json as _json
        json_value = _json.dumps(new_raw, separators=(",", ":"))
        LOGGER.info(
            "[settings-write] field=%s map=%d value=%r json_len=%d (fresh=%s)",
            field, map_id, value, len(json_value), fresh_raw is not None,
        )
        ok, response = await coord.hass.async_add_executor_job(
            coord._cloud.write_chunked_key, "SETTINGS", json_value,
        )
        if not ok:
            LOGGER.warning("[settings-write] rejected: %r", response)
    await coord._refresh_cloud_state()
    return _chunked_kv_write_result(ok, response)


async def write_setting(
    coord,
    cfg_key: str,
    new_full_value: Any,
    field_updates: dict[str, Any] | None = None,
) -> WriteResult:
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

    Returns a :class:`WriteResult` (P2 Task 5 — was a bool): the honest
    device verdict from ``set_cfg``/``set_pre`` (accepted / rejected with
    the device's ``out[0].r`` code / not-delivered), or not-delivered for
    the local preconditions (no cloud client / unknown cfg_key) that
    abort before any wire attempt.
    """
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning("write_setting %s: cloud client not ready", cfg_key)
        return WriteResult.not_delivered("cloud client not ready")

    if cfg_key not in coord._CFG_SINGLE_KEYS and cfg_key != "PRE":
        LOGGER.warning("write_setting: unknown cfg_key %r", cfg_key)
        return WriteResult.not_delivered(f"unknown cfg_key {cfg_key!r}")

    # Optimistic update — capture the PRIOR VALUE of each field this write
    # touches (per-field, NOT a whole-state snapshot) and apply field_updates
    # now. Per-field capture is what makes the revert safe against a
    # concurrent update (an MQTT push landing between the optimistic apply
    # and a cloud rejection): reverting the whole snapshot would clobber that
    # concurrent change to OTHER fields (P2 final-review inherit).
    applied_updates: dict[str, Any] = {}
    prior_values: dict[str, Any] = {}
    if field_updates:
        try:
            prior_values = {k: getattr(coord.data, k) for k in field_updates}
            coord.async_set_updated_data(
                dataclasses.replace(coord.data, **field_updates)
            )
            applied_updates = dict(field_updates)
        except (TypeError, AttributeError) as ex:
            LOGGER.warning(
                "write_setting %s: invalid field_updates %r — %s; skipping optimistic update",
                cfg_key, field_updates, ex,
            )
            # Don't revert — no update was applied; just proceed with the write.
            applied_updates = {}

    # Dispatch to the right cloud_client method.
    result = await coord._dispatch_cfg_write(cfg_key, new_full_value)

    if not result.accepted:
        LOGGER.warning(
            "write_setting %s=%r: cloud write failed (%s); "
            "reverting optimistic update",
            cfg_key, new_full_value, result.msg or result.code,
        )
        if applied_updates:
            # Per-field revert: restore ONLY the fields this write set, and
            # only where they still hold our optimistic value (a concurrent
            # writer may have overwritten one — leave that alone). Fields we
            # never touched are preserved verbatim from current state.
            current = coord.data
            revert = {
                k: prior_values[k]
                for k, opt_v in applied_updates.items()
                if getattr(current, k, prior_values[k]) == opt_v
                and getattr(current, k, prior_values[k]) != prior_values[k]
            }
            if revert:
                coord.async_set_updated_data(
                    dataclasses.replace(current, **revert)
                )

    return result


async def dispatch_cfg_write(coord, cfg_key: str, value: Any) -> WriteResult:
    """Route a CFG write to the appropriate cloud_client method.

    All CFG single-key writes use ``cloud_client.set_cfg``.
    ``PRE`` uses ``cloud_client.set_pre`` (full-array write).
    Both return an honest :class:`WriteResult` — propagated verbatim.

    Runs the blocking I/O in the executor per spec §3.
    """
    if cfg_key == "PRE":
        if not isinstance(value, list):
            LOGGER.warning(
                "_dispatch_cfg_write PRE: expected list, got %r",
                type(value).__name__,
            )
            return WriteResult.not_delivered(
                f"PRE expects a list, got {type(value).__name__}"
            )
        return await coord.hass.async_add_executor_job(
            coord._cloud.set_pre, value
        )

    # All other CFG keys — single-key set via set_cfg().
    return await coord.hass.async_add_executor_job(
        coord._cloud.set_cfg, cfg_key, value
    )


async def write_pre_scoped(coord, map_id: int, apply_fn) -> WriteResult:
    """Scoped PRE read for (map_id, region 0) → apply_fn(array) → set_pre.
    apply_fn returns the full write array or None (no base). Returns the
    honest ``set_pre`` :class:`WriteResult` — accepted only on device
    accept (out[0].r==0); the no-base/not-ready aborts (nothing sent)
    return not-delivered."""
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning("_write_pre_scoped: cloud client not ready")
        return WriteResult.not_delivered("cloud client not ready")
    raw = await coord.hass.async_add_executor_job(coord._cloud.get_pre, map_id, 0)
    new_array = apply_fn(raw)
    if new_array is None:
        LOGGER.warning("_write_pre_scoped: no PRE base for map %s — aborted", map_id)
        return WriteResult.not_delivered(
            f"no PRE base for map {map_id} — nothing sent"
        )
    return await coord.hass.async_add_executor_job(coord._cloud.set_pre, new_array)


async def write_map_general_setting(
    coord, *, map_id: int, pre_index: int, pre_value,
    settings_field: str | None = None, settings_value=None,
) -> WriteResult:
    """Dual-write a per-map General-Mode setting: PRE (device) first, then
    SETTINGS (cloud record) if settings_field given. Returns the PRE-write
    :class:`WriteResult` — the DEVICE write is the authoritative half. A
    SETTINGS (cloud-record) failure after an accepted PRE write is logged
    but deliberately does NOT flip the verdict: the device applied the
    change and the cloud record self-heals on reconcile."""
    from ...protocol import cfg_payloads
    result = await coord._write_pre_scoped(
        map_id,
        lambda raw: cfg_payloads.apply_pre(raw, map_idx=map_id, index=pre_index, value=pre_value),
    )
    if not result.accepted:
        return result
    if settings_field is not None:
        s_result = await coord.write_settings(
            map_id=map_id, field=settings_field, value=settings_value
        )
        if not s_result.accepted:
            LOGGER.warning(
                "write_map_general_setting: PRE ok but SETTINGS %s failed "
                "(device changed; cloud record stale until reconcile)", settings_field,
            )
    return result


async def write_map_general_ai_bit(
    coord, *, map_id: int, bit: int, on: bool, settings_value: int,
) -> WriteResult:
    """Dual-write one AI-recognition bit: PRE[15] bit + SETTINGS.obstacleAvoidanceAi.

    Same verdict semantics as ``write_map_general_setting``: the PRE
    (device) write's :class:`WriteResult` is returned; a SETTINGS
    cloud-record failure is log-only."""
    from ...protocol import cfg_payloads
    result = await coord._write_pre_scoped(
        map_id,
        lambda raw: cfg_payloads.apply_pre_ai_bit(raw, map_idx=map_id, bit=bit, on=on),
    )
    if not result.accepted:
        return result
    s_result = await coord.write_settings(
        map_id=map_id, field="obstacleAvoidanceAi", value=settings_value,
    )
    if not s_result.accepted:
        LOGGER.warning("write_map_general_ai_bit: PRE ok but SETTINGS failed (stale until reconcile)")
    return result
