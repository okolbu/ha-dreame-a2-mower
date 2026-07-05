"""Periodic cloud-state family fetchers for DreameA2CloudClient (P3.5 split).

The CFG / DEV / MIHIS / DOCK / NET / MAP / MAPL routed-action reads plus the
``fetch_full_cloud_state`` orchestrator that assembles the empty-batch families
into the parts of a CloudState. The CloudState *composition* itself lives in
the state layer (``coordinator/_cloud_state.py``), not here — this transport
mixin only decodes and returns the parts.
"""
from __future__ import annotations

from typing import Any


from ._helpers import _LOGGER


class _StateFetchMixin:

    def fetch_cfg(self) -> dict[str, Any] | None:
        """Fetch CFG via the routed-action s2 aiid=50 {m:'g', t:'CFG'} path.

        Returns the parsed ``d`` field (a dict of CFG keys) on success,
        or None on failure. Logs warnings; does not raise.

        This uses the ``action`` cloud-RPC path (siid=2, aiid=50), which
        is the only cloud surface confirmed to work on g2408 — regular
        ``set_properties`` / ``action`` for other siids returns 80001.

        Source: docs/research/g2408-protocol.md §6.2; legacy
        dreame/device.py:refresh_cfg for request shape.
        """
        from ..protocol.cfg_action import CfgActionError, get_cfg  # type: ignore[import]

        try:
            cfg = get_cfg(self.action)
        except CfgActionError as ex:
            _LOGGER.debug("fetch_cfg: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_cfg: unexpected error: %s", ex)
            return None
        _LOGGER.info("[CFG] fetched %d keys", len(cfg))
        _LOGGER.debug("[CFG] payload: %r", cfg)
        return cfg

    # fetch_locn() deleted 2026-07-02 — LOCN-era endpoint fetcher with zero
    # integration callers (the only remaining caller was
    # tools/probes/inventory_probe.py). position_lat/position_lon are
    # written solely by _refresh_gps; LOCN's routed-action target still
    # exists on the wire (see inventory.yaml § LOCN) and can be re-added
    # trivially if a future dock-location entity needs it. See
    # docs/research/debunked-claims.md § D18.

    def fetch_dev(self) -> dict[str, Any] | None:
        """Fetch DEV via routed-action s2 aiid=50 {m:'g', t:'DEV'}.

        Returns ``{fw, mac, ota, sn}`` on success — the authoritative
        source for the mower's firmware version, MAC, OTA capability flag,
        and hardware serial. Cleaner than the legacy paths:

        - hardware_serial via s1p5 cloud `get_properties` (mostly returns
          80001 on g2408)
        - firmware_version via the cloud device record (`device.info.version`)
        - MAC from `get_devices()` (alt-source, this endpoint cross-checks)

        Returns None on failure (logs at WARNING). Confirmed working on
        g2408 from the 2026-05-04 cloud dump capture.
        """
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "DEV")
        except CfgActionError as ex:
            _LOGGER.debug("fetch_dev: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_dev: unexpected error: %s", ex)
            return None

        # Unwrap optional `d` envelope (some firmware revisions wrap the
        # response in `{d: {...}}`, others return the dict directly).
        if isinstance(payload, dict) and isinstance(payload.get("d"), dict):
            result = payload["d"]
        elif isinstance(payload, dict):
            result = payload
        else:
            _LOGGER.warning("fetch_dev: unexpected payload shape: %r", payload)
            return None

        _LOGGER.debug("[DEV] payload: %r", result)
        return result

    def fetch_mihis(self) -> dict[str, Any] | None:
        """Fetch MIHIS via routed-action s2 aiid=50 {m:'g', t:'MIHIS'}.

        Returns ``{area: m², count: sessions, start: unix_ts, time: minutes}``
        — the cloud-side authoritative lifetime mowing totals matching
        the app's Work Logs header. NOT included in the all-keys
        `getCFG t:'CFG'` dump; needs this dedicated call.

        Returns None on failure (logs at WARNING).
        """
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "MIHIS")
        except CfgActionError as ex:
            _LOGGER.debug("fetch_mihis: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_mihis: unexpected error: %s", ex)
            return None

        if isinstance(payload, dict) and isinstance(payload.get("d"), dict):
            result = payload["d"]
        elif isinstance(payload, dict):
            result = payload
        else:
            _LOGGER.warning("fetch_mihis: unexpected payload shape: %r", payload)
            return None

        _LOGGER.debug("[MIHIS] payload: %r", result)
        return result

    def fetch_dock(self) -> dict[str, Any] | None:
        """Fetch DOCK via routed-action s2 aiid=50 {m:'g', t:'DOCK'}.

        Returns ``{dock: {connect_status, in_region, near_x, near_y,
        near_yaw, path_connect, x, y, yaw}}`` — the dock's authoritative
        state and position in the map frame.

        Confirmed semantics (2026-05-04):
          - connect_status: 1 → mower currently in dock (more reliable
            than inferring from s2p1 == 6 CHARGING).
          - in_region: 1 if dock is inside the lawn polygon, 0 if outside.
          - yaw: dock orientation; matches compass bearing for the X-axis
            of the dock-relative coordinate frame on user's setup.
          - x, y: dock position in the map frame (NOT necessarily 0,0).
          - near_x, near_y, near_yaw, path_connect: semantics still TBD.

        Returns None on failure (logs at WARNING).
        """
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "DOCK")
        except CfgActionError as ex:
            _LOGGER.debug("fetch_dock: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_dock: unexpected error: %s", ex)
            return None

        if isinstance(payload, dict) and isinstance(payload.get("d"), dict):
            result = payload["d"]
        elif isinstance(payload, dict):
            result = payload
        else:
            _LOGGER.warning("fetch_dock: unexpected payload shape: %r", payload)
            return None

        _LOGGER.debug("[DOCK] payload: %r", result)
        return result

    def fetch_net(self) -> dict[str, Any] | None:
        """Fetch NET via routed-action s2 aiid=50 {m:'g', t:'NET'}.

        Returns ``{current: ssid, list: [{ip, rssi, ssid}, ...]}`` —
        the device's currently-associated AP plus the catalogue of
        remembered APs with their last-seen RSSI.

        Useful for populating WiFi RSSI / SSID / IP at startup before
        the first s1p1 heartbeat arrives (which can take ~45 s after
        HA restart). Once the heartbeat starts flowing, byte[17] becomes
        the live RSSI source.

        Returns None on failure (logs at WARNING).
        """
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "NET")
        except CfgActionError as ex:
            _LOGGER.debug("fetch_net: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_net: unexpected error: %s", ex)
            return None

        if isinstance(payload, dict) and isinstance(payload.get("d"), dict):
            result = payload["d"]
        elif isinstance(payload, dict):
            result = payload
        else:
            _LOGGER.warning("fetch_net: unexpected payload shape: %r", payload)
            return None

        _LOGGER.debug("[NET] payload: %r", result)
        return result

    def fetch_map(self) -> dict[int, dict[str, Any]] | None:
        """Fetch the cloud MAP.* batch and return per-map dicts keyed by map_id.

        Calls `get_batch_device_datas` with keys `MAP.0..MAP.127` plus
        `MAP.info`. Reassembles the non-empty chunks; uses `MAP.info` as a
        byte offset to split the joined string when multiple maps are present.
        Each segment is a JSON list `[{...}]` whose inner dict has a
        `mapIndex` field. Returns `{mapIndex: dict, ...}`.

        Range choice: 128 is wide enough for any plausible future expansion
        (the user's current setup uses ~46 chunks for 2 maps; 64 was chosen
        arbitrarily in a96 and proved fine up to a99). The cloud silently
        ignores keys it doesn't have and returns empty strings for them, so
        over-requesting is cheap — it costs nothing at the transport level.
        If g2408 firmware ever grows beyond 128 chunks, raise this to 256.
        (The original a96 value of 64 was confirmed adequate by the
        dump_map_diagnostics a98 run which observed MAP.0..MAP.45; 128 gives
        3× headroom without touching transport cost.)

        Returns None on any irrecoverable failure (network error, empty
        batch, every segment malformed). Partial results beat None when
        at least one map decodes.
        """
        try:
            map_keys = [f"MAP.{i}" for i in range(128)] + ["MAP.info"]
            batch = self.get_batch_device_datas(map_keys)
        except Exception as ex:
            _LOGGER.warning("fetch_map: get_batch_device_datas error: %s", ex)
            return None

        if not batch:
            _LOGGER.debug("fetch_map: empty cloud response")
            return None

        parts = [batch.get(f"MAP.{i}", "") or "" for i in range(128)]
        full = "".join(parts)
        if not full:
            _LOGGER.debug("fetch_map: all MAP.* keys empty")
            return None

        info_raw = batch.get("MAP.info", "") or ""
        try:
            split_pos = int(info_raw) if info_raw else 0
        except (TypeError, ValueError) as e:
            _LOGGER.debug("fetch_map: MAP.info parse failed %r: %s", info_raw, e)
            split_pos = 0

        if split_pos > 0 and split_pos < len(full):
            segments = [full[:split_pos], full[split_pos:]]
        else:
            segments = [full]

        result: dict[int, dict[str, Any]] = {}
        import json as _json
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            try:
                parsed = _json.loads(seg)
            except (ValueError, _json.JSONDecodeError) as e:
                _LOGGER.debug("fetch_map: skipping malformed segment: %s", e)
                continue
            # Cloud wraps each map as a 1-element list.
            entries = parsed if isinstance(parsed, list) else [parsed]
            for entry in entries:
                # Cloud sometimes returns a list-of-JSON-strings (each
                # string is a wrapped map dict). Decode if needed.
                if isinstance(entry, str):
                    try:
                        entry = _json.loads(entry)
                    except (ValueError, _json.JSONDecodeError) as e:
                        _LOGGER.debug("fetch_map: skipping malformed double-encoded entry: %s", e)
                        continue
                if not isinstance(entry, dict):
                    continue
                if "boundary" not in entry and "mowingAreas" not in entry:
                    continue
                idx = entry.get("mapIndex", 0)
                try:
                    idx_int = int(idx)
                except (TypeError, ValueError) as e:
                    _LOGGER.debug("fetch_map: mapIndex cast failed %r: %s", idx, e)
                    idx_int = 0
                result[idx_int] = entry

        if not result:
            _LOGGER.debug("fetch_map: no usable map segments")
            return None

        _LOGGER.debug("fetch_map: decoded %d map(s) by id", len(result))
        return result

    def fetch_full_cloud_state(
        self, include_device_probes: bool = True
    ) -> dict[str, Any] | None:
        """Fetch + decode the device's full cloud state in one orchestrated call.

        - Empty-list `get_batch_device_datas([])` returns all chunked
          data families (MAP, M_PATH, SETTINGS, SCHEDULE, AI_HUMAN,
          FBD_NTYPE, OTA_INFO, TASKID, prop.s_*).
        - `fetch_cfg()` returns the 24 CFG keys (not in the empty-batch).
        - Probes for MAPL, MIHIS (each a separate cfg_individual call that's
          already wired). DOCK is owned by the 60 s `_refresh_dock` timer and
          is deliberately NOT probed here.

        ``include_device_probes`` (default True): MAPL and MIHIS are
        routed-ACTION reads (s2 aiid=50) that go to the *device*, not the cloud
        cache — so when the mower is OFFLINE each blocks ~15 s on the cloud
        relay timeout. The empty-batch and CFG are cloud-cache reads and stay
        fast. Pass ``False`` on the setup-blocking first refresh to skip the two
        device probes (they are best-effort — mapl→None / mihis→{} — and the
        post-setup backfill + 2-min periodic refresh fill them in). This is the
        difference between a ~3 s and a ~35 s config-entry setup while offline.

        Returns the decoded **parts** — a dict whose keys are exactly the
        :class:`CloudState` fields — or ``None`` if the empty-batch call fails
        entirely (network error). Partial data — a missing family within a
        successful batch — produces the appropriate empty/None part rather than
        failing the whole fetch.

        Composition into the ``CloudState`` container happens in the STATE layer
        (``coordinator/_cloud_state.py:_refresh_cloud_state``) — this transport
        method never imports the container (R-31/T2-6: closes the
        transport→state back-edge; the CloudState import was previously
        function-local and thus invisible to the layer gate).
        """
        from ..protocol.batch_grouper import group_keys_by_prefix
        from ..protocol.cruise_config import parse_cruise_config

        try:
            batch = self.get_batch_device_datas([])
        except Exception as ex:
            _LOGGER.warning("fetch_full_cloud_state: empty-batch raised: %s", ex)
            return None
        if batch is None:
            return None
        if not isinstance(batch, dict):
            _LOGGER.warning(
                "fetch_full_cloud_state: empty-batch returned %s, not dict",
                type(batch).__name__,
            )
            batch = {}

        # CFG (separate call — not in the empty-batch).
        try:
            cfg = self.fetch_cfg() or {}
        except Exception as ex:
            _LOGGER.warning("fetch_full_cloud_state: fetch_cfg raised: %s", ex)
            cfg = {}

        # Group batch keys by family prefix, then decode each family via its
        # named helper (autopsy #2: the 235-LOC monolith split along its
        # internal per-family seams; each helper is a pure decode of one
        # family, behaviour-identical to the inline block it replaced).
        families = group_keys_by_prefix(batch)

        # Device-routed probes (MAPL, MIHIS — each a separate routed-action
        # call to the device). Errors here don't fail the whole fetch — the
        # field just stays None/empty. Skipped when include_device_probes is
        # False (the setup-blocking first refresh) so an offline mower's ~15 s
        # relay timeouts don't stall HA boot; the backfill + periodic refresh
        # fetch them shortly after.
        mapl = None
        mihis: dict[str, Any] = {}
        if include_device_probes:
            try:
                mapl = self.fetch_mapl()
            except Exception as e:
                _LOGGER.debug("fetch_full_cloud_state: fetch_mapl raised: %s", e)
                mapl = None
            try:
                mihis = self.fetch_mihis() or {}
            except Exception as e:
                _LOGGER.debug("fetch_full_cloud_state: fetch_mihis raised: %s", e)
                mihis = {}

        import time as _time
        return {
            "cfg": cfg,
            "maps_by_id": _decode_maps(families, batch),
            "mow_paths_by_map_id": _decode_mow_paths(families, batch),
            "settings": _decode_settings(families, batch),
            "schedule": _decode_schedule(self.action, families, batch),
            "ai_human_enabled": _decode_ai_human(families, batch),
            "forbidden_node_types_by_map": _decode_forbidden_node_types(families, batch),
            "ota_status": _decode_ota_status(families, batch),
            "task_id": _decode_task_id(families, batch),
            "props": _decode_props(families, batch),
            "mapl": mapl,
            "mihis": mihis,
            "fetched_at_unix": int(_time.time()),
            "cruise_config_by_map": parse_cruise_config(batch.get("CRUISE.0")),
        }

    def fetch_mapl(self) -> list | None:
        """Fetch MAPL via routed-action s2 aiid=50 {m:'g', t:'MAPL'}.

        MAPL is the multi-map active-map list. Each row is a list of the
        form ``[map_id, is_active, ?, ?, ?]`` where ``is_active == 1``
        marks the currently-selected map.

        Returns the raw list-of-rows on success, or None on failure.
        Logs at DEBUG; does not raise.
        """
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "MAPL")
        except CfgActionError as ex:
            _LOGGER.debug("fetch_mapl: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.debug("fetch_mapl: unexpected error: %s", ex)
            return None

        # MAPL may be returned as a bare list or wrapped in a `d` key.
        if isinstance(payload, list):
            _LOGGER.debug("[MAPL] payload (bare list): %r", payload)
            return payload
        if isinstance(payload, dict):
            inner = payload.get("d")
            if isinstance(inner, list):
                _LOGGER.debug("[MAPL] payload (d-wrapped): %r", inner)
                return inner
            _LOGGER.debug("fetch_mapl: unexpected dict shape: %r", payload)
            return None
        _LOGGER.debug("fetch_mapl: unexpected payload type: %r", type(payload).__name__)
        return None

    def get_pre(self, idx: int, region: int) -> list | None:
        """Scoped PRE read for map `idx`, zone `region`. None on failure."""
        from ..protocol import cfg_action  # type: ignore[import]
        try:
            return cfg_action.get_pre(self.action, idx=idx, region=region)
        except Exception as ex:  # pragma: no cover - defensive
            _LOGGER.warning("get_pre(idx=%s,region=%s) failed: %s", idx, region, ex)
            return None


# ---------------------------------------------------------------------------
# fetch_full_cloud_state per-family decoders (P3.5 / autopsy #2 decomposition).
#
# Each is a PURE decode of one empty-batch family into its protocol/state part
# — no ``self``, no network. ``fetch_full_cloud_state`` orchestrates them. They
# return protocol-layer types (MapData / MowPathData / SettingsRoot /
# ScheduleData) or primitives; NONE constructs the CloudState container (that
# is the state layer's job — R-31/T2-6). Behaviour is byte-identical to the
# inline blocks these replaced.
# ---------------------------------------------------------------------------


def _decode_maps(families: dict, batch: dict) -> dict[int, Any]:
    """MAP.* → ``{map_id: MapData}`` (empty when absent/unparsable).

    We already hold the empty-batch dict, so we parse the joined MAP chunks
    directly rather than re-calling ``fetch_map`` (which makes its own batch
    request). ``MAP.info`` is the byte offset that splits the joined string
    when two maps are concatenated.
    """
    if "MAP" not in families:
        return {}
    import json as _json

    from ..protocol.map import parse_cloud_maps
    from ..protocol.batch_grouper import join_family_chunks

    map_joined = join_family_chunks("MAP", batch)
    map_info_raw = batch.get("MAP.info") or ""
    try:
        split_pos = int(map_info_raw) if map_info_raw else 0
    except (TypeError, ValueError) as e:
        _LOGGER.debug("parse_full_cloud_state: MAP.info parse failed %r: %s", map_info_raw, e)
        split_pos = 0
    segments = (
        [map_joined[:split_pos], map_joined[split_pos:]]
        if 0 < split_pos < len(map_joined)
        else [map_joined]
    )
    raw_by_id: dict[int, dict] = {}
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        try:
            parsed = _json.loads(seg)
        except (ValueError, _json.JSONDecodeError):
            continue
        entries = parsed if isinstance(parsed, list) else [parsed]
        for entry in entries:
            if isinstance(entry, str):
                try:
                    entry = _json.loads(entry)
                except (ValueError, _json.JSONDecodeError) as e:
                    _LOGGER.debug("parse_full_cloud_state: MAP entry double-decode failed: %s", e)
                    continue
            if not isinstance(entry, dict):
                continue
            if "boundary" not in entry and "mowingAreas" not in entry:
                continue
            idx = entry.get("mapIndex", 0)
            try:
                idx_int = int(idx)
            except (TypeError, ValueError) as e:
                _LOGGER.debug("parse_full_cloud_state: mapIndex cast failed %r: %s", idx, e)
                idx_int = 0
            raw_by_id[idx_int] = entry
    return parse_cloud_maps(raw_by_id) if raw_by_id else {}


def _decode_mow_paths(families: dict, batch: dict) -> dict[int, Any]:
    """M_PATH.* → ``{map_id: MowPathData}`` (empty when absent)."""
    if "M_PATH" not in families:
        return {}
    from ..protocol.batch_grouper import join_family_chunks
    from ..protocol.m_path import parse_m_path_batch

    m_path_joined = join_family_chunks("M_PATH", batch)
    m_path_info = batch.get("M_PATH.info") or ""
    try:
        m_split = int(m_path_info) if str(m_path_info).isdigit() else 0
    except (TypeError, ValueError) as e:
        _LOGGER.debug("parse_full_cloud_state: M_PATH.info parse failed %r: %s", m_path_info, e)
        m_split = 0
    return parse_m_path_batch(m_path_joined, m_split)


def _decode_settings(families: dict, batch: dict):
    """SETTINGS.* → ``SettingsRoot`` (empty root when absent)."""
    from ..protocol.batch_grouper import join_family_chunks
    from ..protocol.settings import SettingsRoot, parse_settings_batch

    if "SETTINGS" not in families:
        return SettingsRoot(raw=[], by_map_id_canonical={})
    settings_joined = join_family_chunks("SETTINGS", batch)
    try:
        import json as _json
        settings_raw = _json.loads(settings_joined)
    except Exception as e:
        _LOGGER.debug("parse_full_cloud_state: SETTINGS JSON parse failed: %s", e, exc_info=True)
        settings_raw = []
    return parse_settings_batch(settings_raw)


def _decode_schedule(action, families: dict, batch: dict):
    """SCHEDULE → ``ScheduleData``.

    The SCHEDULE.* iotuserdata KV is a STALE cache that app schedule edits do
    NOT write back (verified 2026-06-17: KV held a 6-plan v=35477 for hours
    while the device's live schedule was a 3-plan v=58177). Prefer the
    authoritative device-plane read (SCHDIV3→SCHDDV3 chunked GET); fall back to
    the KV only when the live read is unavailable (device offline / firmware
    reject).
    """
    from ..protocol.batch_grouper import join_family_chunks
    from ..protocol.schedule import parse_schedule_batch
    from ..protocol.schedule_action import read_live_schedule
    from ..protocol.schedule_decode import ScheduleData

    live_sched = None
    try:
        live_sched = read_live_schedule(action)
    except Exception as ex:  # noqa: BLE001 — never fail the whole fetch
        _LOGGER.debug("fetch_full_cloud_state: live schedule read raised: %s", ex)
    if live_sched is not None:
        return parse_schedule_batch(live_sched)
    if "SCHEDULE" in families:
        sched_joined = join_family_chunks("SCHEDULE", batch)
        try:
            import json as _json
            sched_raw = _json.loads(sched_joined)
        except Exception as e:
            _LOGGER.debug("parse_full_cloud_state: SCHEDULE JSON parse failed: %s", e, exc_info=True)
            sched_raw = {}
        return parse_schedule_batch(sched_raw)
    return ScheduleData(version=0, slots=())


def _decode_ai_human(families: dict, batch: dict) -> bool | None:
    """AI_HUMAN → bool (single chunk, JSON-encoded boolean) or None."""
    if "AI_HUMAN" not in families:
        return None
    from ..protocol.batch_grouper import join_family_chunks

    ai_joined = join_family_chunks("AI_HUMAN", batch)
    try:
        import json as _json
        return bool(_json.loads(ai_joined))
    except Exception as e:
        _LOGGER.debug("parse_full_cloud_state: AI_HUMAN JSON parse failed: %s", e)
        return None


def _decode_forbidden_node_types(families: dict, batch: dict) -> dict[int, dict[str, Any]]:
    """FBD_NTYPE → ``{map_id: dict}`` (a list of per-map dicts on the wire)."""
    forbidden_node_types_by_map: dict[int, dict[str, Any]] = {}
    if "FBD_NTYPE" not in families:
        return forbidden_node_types_by_map
    from ..protocol.batch_grouper import join_family_chunks

    fbd_joined = join_family_chunks("FBD_NTYPE", batch)
    try:
        import json as _json
        fbd_list = _json.loads(fbd_joined)
        if isinstance(fbd_list, list):
            for i, entry in enumerate(fbd_list):
                if isinstance(entry, dict):
                    forbidden_node_types_by_map[i] = entry
    except Exception as e:
        _LOGGER.debug("parse_full_cloud_state: FBD_NTYPE JSON parse failed: %s", e, exc_info=True)
    return forbidden_node_types_by_map


def _decode_ota_status(families: dict, batch: dict) -> tuple[int, int] | None:
    """OTA_INFO → ``(status, percent)`` or None."""
    if "OTA_INFO" not in families:
        return None
    from ..protocol.batch_grouper import join_family_chunks

    ota_joined = join_family_chunks("OTA_INFO", batch)
    try:
        import json as _json
        ota_list = _json.loads(ota_joined)
        if isinstance(ota_list, list) and len(ota_list) >= 2:
            return (int(ota_list[0]), int(ota_list[1]))
    except Exception as e:
        _LOGGER.debug("parse_full_cloud_state: OTA_INFO JSON parse failed: %s", e)
    return None


def _decode_task_id(families: dict, batch: dict) -> int:
    """TASKID → int (0 when absent/unparsable)."""
    if "TASKID" not in families:
        return 0
    from ..protocol.batch_grouper import join_family_chunks

    tid_joined = join_family_chunks("TASKID", batch)
    try:
        import json as _json
        return int(_json.loads(tid_joined))
    except Exception as e:
        _LOGGER.debug("parse_full_cloud_state: TASKID JSON parse failed: %s", e)
        return 0


def _decode_props(families: dict, batch: dict) -> dict[str, str]:
    """prop.s_* → ``{key: value}`` standalone string props."""
    props: dict[str, str] = {}
    if "prop" not in families:
        return props
    for k in families["prop"]:
        v = batch.get(k)
        if isinstance(v, str):
            props[k] = v
    return props
