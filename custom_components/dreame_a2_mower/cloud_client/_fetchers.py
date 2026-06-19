"""Cloud-state fetchers + CFG writers mixin for DreameA2CloudClient (B1d split from cloud_client.py)."""
from __future__ import annotations

import time
from typing import Any

from ._helpers import _LOGGER


class _FetchersMixin:

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

    def fetch_locn(self) -> dict[str, Any] | None:
        """Fetch LOCN via the routed-action s2 aiid=50 {m:'g', t:'LOCN'} path.

        Returns a dict containing a ``pos`` key (e.g. ``{"pos": [lon, lat]}``)
        on success, or None on failure. Logs warnings; does not raise.

        The sentinel value ``pos: [-1, -1]`` means the dock GPS origin has
        not been configured — callers should treat this as "no position".

        Source: docs/research/g2408-protocol.md §2.1 LOCN; legacy
        dreame/device.py:refresh_locn for request shape and response handling.
        """
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "LOCN")
        except CfgActionError as ex:
            _LOGGER.debug("fetch_locn: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_locn: unexpected error: %s", ex)
            return None

        # Unwrap optional `d` envelope — some firmware revisions wrap the
        # location dict in a `d` key; others return it directly.
        if isinstance(payload, dict) and isinstance(payload.get("d"), dict):
            result = payload["d"]
        elif isinstance(payload, dict):
            result = payload
        else:
            _LOGGER.warning("fetch_locn: unexpected payload shape: %r", payload)
            return None

        _LOGGER.debug("[LOCN] payload: %r", result)
        return result

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

    def fetch_full_cloud_state(self) -> CloudState | None:
        """Fetch the device's full cloud state in one orchestrated call.

        - Empty-list `get_batch_device_datas([])` returns all chunked
          data families (MAP, M_PATH, SETTINGS, SCHEDULE, AI_HUMAN,
          FBD_NTYPE, OTA_INFO, TASKID, prop.s_*).
        - `fetch_cfg()` returns the 24 CFG keys (not in the empty-batch).
        - Probes for LOCN, DOCK, MAPL, MIHIS (each a separate cfg_individual
          call that's already wired).

        Returns None if the empty-batch call fails entirely (network
        error). Partial data — a missing family within a successful
        batch — produces the appropriate empty/None field on
        CloudState rather than failing the whole fetch.
        """
        from ..cloud_state import CloudState, ScheduleData, SettingsRoot
        from ..protocol.cruise_config import parse_cruise_config
        from ..map_decoder import parse_cloud_maps
        from ..protocol.batch_grouper import group_keys_by_prefix, join_family_chunks
        from ..protocol.m_path import parse_m_path_batch
        from ..protocol.schedule import parse_schedule_batch
        from ..protocol.settings import parse_settings_batch

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

        # Group batch keys by family prefix.
        families = group_keys_by_prefix(batch)

        # MAP.* — reuse existing fetch_map logic via an inline parse.
        # The existing fetch_map() makes its own get_batch_device_datas
        # call; we already have the batch, so parse directly.
        maps_by_id: dict[int, Any] = {}
        if "MAP" in families:
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
            import json as _json
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
            maps_by_id = parse_cloud_maps(raw_by_id) if raw_by_id else {}

        # M_PATH.*
        mow_paths_by_map_id: dict[int, Any] = {}
        if "M_PATH" in families:
            m_path_joined = join_family_chunks("M_PATH", batch)
            m_path_info = batch.get("M_PATH.info") or ""
            try:
                m_split = int(m_path_info) if str(m_path_info).isdigit() else 0
            except (TypeError, ValueError) as e:
                _LOGGER.debug("parse_full_cloud_state: M_PATH.info parse failed %r: %s", m_path_info, e)
                m_split = 0
            mow_paths_by_map_id = parse_m_path_batch(m_path_joined, m_split)

        # SETTINGS.*
        settings_root: SettingsRoot
        if "SETTINGS" in families:
            settings_joined = join_family_chunks("SETTINGS", batch)
            try:
                import json as _json
                settings_raw = _json.loads(settings_joined)
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: SETTINGS JSON parse failed: %s", e, exc_info=True)
                settings_raw = []
            settings_root = parse_settings_batch(settings_raw)
        else:
            settings_root = SettingsRoot(raw=[], by_map_id_canonical={})

        # SCHEDULE — the SCHEDULE.* iotuserdata KV is a STALE cache that app
        # schedule edits do NOT write back (verified 2026-06-17: KV held a
        # 6-plan v=35477 for hours while the device's live schedule was a 3-plan
        # v=58177). Prefer the authoritative device-plane read (SCHDIV3->SCHDDV3
        # chunked GET); fall back to the KV only when the live read is
        # unavailable (e.g. device offline / firmware reject).
        from ..protocol.schedule_action import read_live_schedule
        schedule = ScheduleData(version=0, slots=())
        live_sched = None
        try:
            live_sched = read_live_schedule(self.action)
        except Exception as ex:  # noqa: BLE001 — never fail the whole fetch
            _LOGGER.debug("fetch_full_cloud_state: live schedule read raised: %s", ex)
        if live_sched is not None:
            schedule = parse_schedule_batch(live_sched)
        elif "SCHEDULE" in families:
            sched_joined = join_family_chunks("SCHEDULE", batch)
            try:
                import json as _json
                sched_raw = _json.loads(sched_joined)
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: SCHEDULE JSON parse failed: %s", e, exc_info=True)
                sched_raw = {}
            schedule = parse_schedule_batch(sched_raw)

        # AI_HUMAN — single chunk, JSON-encoded boolean.
        ai_human_enabled: bool | None = None
        if "AI_HUMAN" in families:
            ai_joined = join_family_chunks("AI_HUMAN", batch)
            try:
                import json as _json
                ai_human_enabled = bool(_json.loads(ai_joined))
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: AI_HUMAN JSON parse failed: %s", e)
                ai_human_enabled = None

        # FBD_NTYPE — list of per-map dicts: [{<map0_dict>}, {<map1_dict>}].
        forbidden_node_types_by_map: dict[int, dict[str, Any]] = {}
        if "FBD_NTYPE" in families:
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
                pass

        # OTA_INFO — `[status, percent]`.
        ota_status: tuple[int, int] | None = None
        if "OTA_INFO" in families:
            ota_joined = join_family_chunks("OTA_INFO", batch)
            try:
                import json as _json
                ota_list = _json.loads(ota_joined)
                if isinstance(ota_list, list) and len(ota_list) >= 2:
                    ota_status = (int(ota_list[0]), int(ota_list[1]))
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: OTA_INFO JSON parse failed: %s", e)
                pass

        # TASKID — int.
        task_id = 0
        if "TASKID" in families:
            tid_joined = join_family_chunks("TASKID", batch)
            try:
                import json as _json
                task_id = int(_json.loads(tid_joined))
            except Exception as e:
                _LOGGER.debug("parse_full_cloud_state: TASKID JSON parse failed: %s", e)
                pass

        # prop.s_* — standalone keys.
        props: dict[str, str] = {}
        if "prop" in families:
            for k in families["prop"]:
                v = batch.get(k)
                if isinstance(v, str):
                    props[k] = v

        # Fast-cadence probes (each a separate cloud call).
        # DOCK is owned by the 60-second _refresh_dock timer; do NOT probe
        # it here to avoid double-fetching.
        # Errors here don't fail the whole fetch — fields just stay None/empty.
        try:
            mapl = self.fetch_mapl()
        except Exception as e:
            _LOGGER.debug("parse_full_cloud_state: fetch_mapl raised: %s", e)
            mapl = None
        try:
            mihis = self.fetch_mihis() or {}
        except Exception as e:
            _LOGGER.debug("parse_full_cloud_state: fetch_mihis raised: %s", e)
            mihis = {}

        import time as _time
        return CloudState(
            cfg=cfg,
            maps_by_id=maps_by_id,
            mow_paths_by_map_id=mow_paths_by_map_id,
            settings=settings_root,
            schedule=schedule,
            ai_human_enabled=ai_human_enabled,
            forbidden_node_types_by_map=forbidden_node_types_by_map,
            ota_status=ota_status,
            task_id=task_id,
            props=props,
            mapl=mapl,
            mihis=mihis,
            fetched_at_unix=int(_time.time()),
            cruise_config_by_map=parse_cruise_config(batch.get("CRUISE.0")),
        )

    def fetch_device_messages(
        self, did: str | int, page_size: int = 10,
    ) -> list[dict[str, Any]] | None:
        """Fetch the per-device cloud notification store (the app's A2 tab).

        GET ``/dreame-messaging/user/device-messages/v2?did=<did>&pageNum=1&pageSize=N``.
        Server caps `page_size` at 10 and ignores pagination (pageNum 2+ returns
        the same latest-10) [probe@2026-06-18] — this is a
        moving window of the latest N pushes for `did`. Each record carries
        `source={siid,piid,value,eiid,aiid}` (values as STRING), multilingual
        `localizationContents`, `sendTime` (str "YYYY-MM-DD HH:MM:SS"),
        `readTime`, and `messageId` (the dedup key).

        Returns the parsed `data.content` list on success, or `None` on
        any failure (no token, HTTP error, JSON parse error, non-zero code).
        Logs at warning level.

        See docs/research/app-api-surface-2026-05-25.md § device-messages/v2.
        """
        strings = self._ensure_strings()
        if self._key_expire and time.time() > self._key_expire:
            self.login()
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            strings[47]: strings[3],
            strings[49]: strings[5],
            strings[50]: self._ti if self._ti else strings[6],
            strings[51]: strings[52],
            strings[46]: self._key,
        }
        if self._country == "cn":
            headers[strings[48]] = strings[4]
        url = f"{self.get_api_url()}/dreame-messaging/user/device-messages/v2"
        try:
            resp = self._session.get(
                url,
                headers=headers,
                params={"did": str(did), "pageNum": 1, "pageSize": page_size},
                timeout=15,
            )
        except Exception as ex:  # noqa: BLE001 — defensive
            _LOGGER.warning("fetch_device_messages: request failed: %s", ex)
            return None
        if resp.status_code != 200:
            _LOGGER.warning(
                "fetch_device_messages: HTTP %d (body: %s)",
                resp.status_code, resp.text[:200],
            )
            return None
        try:
            body = resp.json()
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning("fetch_device_messages: JSON parse failed: %s", ex)
            return None
        if not isinstance(body, dict) or body.get("code") not in (0, 200):
            _LOGGER.debug(
                "fetch_device_messages: non-zero response code: %r msg=%r",
                body.get("code"), body.get("msg"),
            )
            return None
        records = (body.get("data") or {}).get("content")
        return records if isinstance(records, list) else None

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

    def set_cfg(self, key: str, value: Any) -> bool:
        """Write a single CFG key via routed-action s2 aiid=50.

        Wire format: ``{m: 's', t: key, d: <d_payload>}`` sent as
        ``in[0]`` of the siid=2 aiid=50 action call.

        ``value`` accepts two shapes:

        - **dict** — sent as ``d`` directly (named-key payload). Use
          this for complex CFG keys that take more than one slot:
          e.g. ``WRP {"value":1,"time":8,"sen":0}``,
          ``DND {"value":1,"time":[1200,480]}``,
          ``LIT {"value":1,"time":[480,1200],"light":[1,1,1,1],"fill":0}``.
          Source for the named-key catalog: ioBroker.dreame v0.3.7
          (see docs/research/wire-captures/iobroker-write-catalog-2026-05-09.md).
        - **anything else** — wrapped as ``{"value": value}``. This is
          the path for simple keys that take a single int / bool /
          all-bool list (CLS, VOL, FDP, STUN, AOP, PROT, ATA,
          MSG_ALERT, VOICE).

        The value MUST always end up wrapped under a ``value`` key —
        without it the device returns ``r=-3`` (not supported)
        inside the routed-action response and the cloud silently
        retains the old value (smoking-gun probe 2026-05-09 against
        all 16 known-writable CFG keys).

        Returns True only when the device's routed-action response has
        ``out[0].r == 0`` — i.e. the device actually accepted the
        write. Pre-fix code only checked the top-level HTTP code which
        is always 0 even when the device rejected the action.

        Wire-format coverage on g2408 (confirmed live 2026-05-09):

        Working with the wrapped {value: X} format (primitive callers):
        - Single int / bool: CLS, VOL, FDP, STUN, AOP, PROT
        - All-bool list[3]: ATA
        - All-bool list[4]: MSG_ALERT, VOICE

        Hypothesised to work with the named-key dict format (post-2026-05-09;
        verify per-key before relying on it):
        - WRP, DND, LOW, LIT — see ioBroker catalog above
        - CMS reset, PRE — full-array writes (separate set_pre helper)

        Still unknown wire format (no app-side reference):
        - BAT (list[6] mixed), REC (list[9] mixed), LANG (list[2] mixed)

        For unsupported shapes the device returns r=-3 and set_cfg
        returns False — the entity-layer caller's optimistic update
        is reverted.

        Source: probe `/tmp/probe_cfg_writes.py` 2026-05-09; full
        evidence in docs/research/wire-captures/cfg-write-regression-2026-05-09.md
        and the ioBroker catalog at iobroker-write-catalog-2026-05-09.md.
        """
        if isinstance(value, dict):
            d_payload: Any = value
        else:
            d_payload = {"value": value}
        payload = {"m": "s", "t": key, "d": d_payload}
        try:
            result = self.action(siid=2, aiid=50, parameters=[payload])
            if result is None:
                _LOGGER.warning(
                    "set_cfg %s=%r: cloud returned None (80001?)", key, value
                )
                return False
            if not isinstance(result, dict):
                _LOGGER.warning(
                    "set_cfg %s=%r: unexpected response shape: %r",
                    key, value, result,
                )
                return False
            # HTTP-layer code = always 0 on a reachable cloud; the actual
            # action result is in `out[0].r`.
            top_code = result.get("code")
            if top_code is not None and top_code != 0:
                _LOGGER.warning(
                    "set_cfg %s=%r: cloud HTTP error code %s", key, value, top_code,
                )
                return False
            outs = result.get("out") or []
            if not outs or not isinstance(outs[0], dict):
                _LOGGER.warning(
                    "set_cfg %s=%r: missing or malformed `out` in response: %r",
                    key, value, result,
                )
                return False
            r = outs[0].get("r")
            if r != 0:
                msg = outs[0].get("msg") or outs[0].get("e") or ""
                _LOGGER.warning(
                    "set_cfg %s=%r: device rejected (out[0].r=%r msg=%r). "
                    "Wire format may be wrong for this CFG key — see "
                    "docs/research/wire-captures/cfg-write-regression-2026-05-09.md",
                    key, value, r, msg,
                )
                return False
            return True
        except Exception as ex:
            _LOGGER.warning("set_cfg %s=%r failed: %s", key, value, ex)
            return False

    def set_pre(self, pre_array: list) -> bool:
        """Write the full PRE preferences array.

        Delegates to ``protocol.cfg_action.set_pre`` which constructs the
        routed-action envelope ``{m:'s', t:'PRE', d:<bare array>}``.
        The ``d`` field is the array itself — NOT wrapped under ``value``.

        The caller is responsible for read-modify-write semantics: read the
        current PRE array via fetch_cfg(), mutate the target element, and
        pass the full updated array here.

        Returns True only when the device's routed-action response has
        ``out[0].r == 0``. The HTTP-layer ``code`` is always 0 on a
        reachable cloud even when the device rejects the action, so a
        shallow ``result is not None`` check reports false success — the
        same bug class as the pre-v1.0.2a9 ``set_cfg``. We parse
        ``out[0].r`` here just like ``set_cfg`` does.

        Prior r=-3 verdict debunked (2026-06-09 app MITM capture): the
        original code wrapped the array as ``d:{"value": pre_array}``, and
        the device returned ``r=-3`` on every write.  The app sends the bare
        array ``d:[...]`` and the device accepts it (r=0).  The r=-3 was a
        wrong-envelope artifact, not evidence that g2408 has no PRE setter.
        See docs/research/wire-captures/pre-write-r3-2026-06-03.md (the
        old -3 evidence) and the 2026-06-09 app-capture findings.

        Source: protocol/cfg_action.py set_pre(); docs/research/g2408-protocol.md §6.2.
        """
        from ..protocol import cfg_action  # type: ignore[import]

        try:
            result = cfg_action.set_pre(self.action, pre_array)
            if result is None:
                _LOGGER.warning("set_pre: cloud returned None (80001?)")
                return False
            if not isinstance(result, dict):
                _LOGGER.warning(
                    "set_pre: unexpected response shape: %r", result
                )
                return False
            top_code = result.get("code")
            if top_code is not None and top_code != 0:
                _LOGGER.warning("set_pre: cloud HTTP error code %s", top_code)
                return False
            outs = result.get("out") or []
            if not outs or not isinstance(outs[0], dict):
                _LOGGER.warning(
                    "set_pre: missing or malformed `out` in response: %r", result
                )
                return False
            r = outs[0].get("r")
            if r != 0:
                msg = outs[0].get("msg") or outs[0].get("e") or ""
                _LOGGER.warning(
                    "set_pre: device rejected (out[0].r=%r msg=%r) — envelope is "
                    "the app's bare array; non-zero r is a genuine device rejection",
                    r, msg,
                )
                return False
            return True
        except ValueError as ex:
            _LOGGER.warning("set_pre: invalid array: %s", ex)
            return False
        except Exception as ex:
            _LOGGER.warning("set_pre failed: %s", ex)
            return False

    def get_pre(self, idx: int, region: int) -> list | None:
        """Scoped PRE read for map `idx`, zone `region`. None on failure."""
        from ..protocol import cfg_action  # type: ignore[import]
        try:
            return cfg_action.get_pre(self.action, idx=idx, region=region)
        except Exception as ex:  # pragma: no cover - defensive
            _LOGGER.warning("get_pre(idx=%s,region=%s) failed: %s", idx, region, ex)
            return None

    def fetch_gps(self) -> dict | None:
        """Absolute GPS via dreame-mower-service-app/location/getRecords.

        Returns the newest record as ``{lat, lon, update_time, card4g}``
        (float lat/lon, string timestamps), or ``None`` on any failure.
        ``gpsLat``/``gpsLong`` are decimal-degree strings in the wire
        payload.

        Note: the endpoint is ATA[2]-gated — it returns an empty records
        list when Real-Time Location is disabled in the app.
        """
        self._ensure_strings()
        if getattr(self, "_key_expire", None) and time.time() > self._key_expire:
            self.login()
        strings = getattr(self, "_strings", None) or self.strings
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            strings[47]: strings[3],
            strings[49]: strings[5],
            strings[50]: getattr(self, "_ti", None) or strings[6],
            strings[51]: strings[52],
            strings[46]: getattr(self, "_key", ""),
        }
        if getattr(self, "_country", None) == "cn":
            headers[strings[48]] = strings[4]
        try:
            url = f"{self.get_api_url()}/dreame-mower-service-app/location/getRecords"
            resp = self._session.post(
                url,
                headers=headers,
                json={"did": str(self._did)},
                timeout=10,
            )
            if resp.status_code != 200:
                _LOGGER.warning("fetch_gps: HTTP %d (body: %s)", resp.status_code, resp.text[:200])
                return None
            body = resp.json()
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_gps: %s", ex)
            return None
        recs = (((body or {}).get("locationRecords") or {}).get("records")) or []
        if not isinstance(recs, list) or not recs:
            return None
        newest = max(recs, key=lambda r: r.get("updateTime") or "")
        try:
            return {
                "lat": float(newest["gpsLat"]),
                "lon": float(newest["gpsLong"]),
                "update_time": newest.get("updateTime"),
                "card4g": newest.get("card4G"),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def fetch_remote(self) -> dict | None:
        """4G SIM status via routed m:g t:REMOTE.

        Returns ``{active_time, card_id, expired_time, left_days}`` or
        ``None`` on failure (device not present, firmware-gated, or
        transport error).
        """
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]

        try:
            payload = probe_get(self.action, "REMOTE")
        except CfgActionError as ex:
            _LOGGER.debug("fetch_remote: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_remote: %s", ex)
            return None
        # probe_get returns out[0] — the {m, t, d, ...} envelope.
        # Extract the inner data dict from the 'd' key.
        d = payload.get("d") if isinstance(payload, dict) and isinstance(payload.get("d"), dict) else (
            payload if isinstance(payload, dict) else None
        )
        if not isinstance(d, dict) or "cardId" not in d:
            _LOGGER.debug("fetch_remote: unexpected payload shape: %r", payload)
            return None
        return {
            "active_time": d.get("activeTime"),
            "card_id": d.get("cardId"),
            "expired_time": d.get("expiredTime"),
            "left_days": d.get("leftDays"),
        }

    def fetch_4g_remain(self, iccid: str | None = None) -> dict | None:
        """Quantitative 4G-SIM data via the SIM provider's public endpoint.

        ``GET https://api-4g.tsingting.tech/api/v1/biz_4g_remain/{did}`` with
        query params ``sn``, ``iccid``, ``region``, ``isProd``. This is the
        third-party Tsingting (SIM MVNO) host the app polls for its SIM page —
        NOT the Dreame IoT host, and it is **unauthenticated** (no Dreame-Auth /
        key header; keyed by did+sn+iccid).
        ``[api-calls.jsonl@2026-06-08 (mitm_session_20260616)]``

        Returns ``{data_remaining_mb, out_of_warranty, expiry}``. The first two
        are unique to this endpoint; ``expiry`` is the ISO-8601 UTC ``exp_time``
        — preferred over REMOTE's ``expiredTime`` (a TZ-ambiguous space-format
        string) so the integration can surface a proper timestamp sensor.
        ``rem_time``/``iccid`` overlap with REMOTE's leftDays/cardId and are
        surfaced from there. Returns ``None`` when the ICCID is unknown (REMOTE
        not yet polled), on a non-200, or on a transport/parse error. Never raises.
        """
        if not iccid:
            return None
        did = getattr(self, "_did", None)
        url = f"https://api-4g.tsingting.tech/api/v1/biz_4g_remain/{did}"
        params = {
            "sn": getattr(self, "_sn", None) or "",
            "iccid": iccid,
            "region": getattr(self, "_country", None) or "",
            "isProd": "true",
        }
        try:
            resp = self._session.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                _LOGGER.warning("fetch_4g_remain: HTTP %d (body: %s)", resp.status_code, resp.text[:200])
                return None
            data = (resp.json() or {}).get("data") or {}
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_4g_remain: %s", ex)
            return None
        out: dict = {}
        flow = data.get("rem_flow")
        if flow is not None:
            try:
                out["data_remaining_mb"] = float(flow)
            except (TypeError, ValueError):
                pass
        if "out_of_warranty" in data:
            out["out_of_warranty"] = bool(data["out_of_warranty"])
        exp = data.get("exp_time")
        if exp:
            out["expiry"] = exp
        return out or None

    def fetch_mpos(self) -> dict:
        """Live mower position via routed-get m:g t:MPOS (DIAGNOSTIC, RAW).

        Returns one of:
          {"result": "ok", "x": int, "y": int, "yaw": int}  — r:0 with data
          {"result": "idle"}   — r:-1/-3 (mower idle / no data, like MISTA)
          {"result": "error"}  — transport failure or malformed payload

        [tools/probes/read_key_probe.py@2026-06-09] observed r:0
        d={"x":95,"y":-4,"yaw":0} at dock-idle. The values are RAW cloud frame —
        units/frame UNVERIFIED; never transform or treat as the integration's
        position. Never raises.
        """
        try:
            resp = self.action(
                siid=2, aiid=50,
                parameters=[{"m": "g", "t": "MPOS", "d": None}],
            )
        except Exception as ex:  # noqa: BLE001 — diagnostic read never breaks callers
            _LOGGER.warning("fetch_mpos: %s", ex)
            return {"result": "error"}
        if not isinstance(resp, dict):
            return {"result": "error"}
        out = resp.get("out") or []
        if not out or not isinstance(out[0], dict):
            return {"result": "error"}
        env = out[0]
        if env.get("r") != 0:
            return {"result": "idle"}
        d = env.get("d")
        if not isinstance(d, dict) or not all(k in d for k in ("x", "y", "yaw")):
            return {"result": "error"}
        return {"result": "ok", "x": d["x"], "y": d["y"], "yaw": d["yaw"]}

    def fetch_message_record(self) -> dict | None:
        """System + service messages via /dreame-message-push/v1/message-record/list.

        Returns ``{service_unread, system_unread, latest}`` where ``latest``
        is the ``en.name`` of the first serviceMsg record (or ``None``).
        Returns ``None`` on any failure.
        """
        self._ensure_strings()
        if getattr(self, "_key_expire", None) and time.time() > self._key_expire:
            self.login()
        strings = getattr(self, "_strings", None) or self.strings
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            strings[47]: strings[3],
            strings[49]: strings[5],
            strings[50]: getattr(self, "_ti", None) or strings[6],
            strings[51]: strings[52],
            strings[46]: getattr(self, "_key", ""),
        }
        if getattr(self, "_country", None) == "cn":
            headers[strings[48]] = strings[4]
        try:
            url = f"{self.get_api_url()}/dreame-message-push/v1/message-record/list"
            resp = self._session.get(
                url,
                headers=headers,
                params={"version": "v1"},
                timeout=10,
            )
            if resp.status_code != 200:
                _LOGGER.warning("fetch_message_record: HTTP %d (body: %s)", resp.status_code, resp.text[:200])
                return None
            body = resp.json()
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_message_record: %s", ex)
            return None
        data = (body or {}).get("data") or {}
        svc = data.get("serviceMsg") or {}
        sysm = data.get("systemMsg") or {}
        latest = None
        recs = svc.get("msgRecord") or []
        if recs and isinstance(recs[0], dict):
            import json as _json
            try:
                disp = _json.loads(recs[0].get("multiLangDisplay") or "{}")
                en = disp.get("en") or next(iter(disp.values()), {})
                latest = (en or {}).get("name")
            except (ValueError, TypeError):
                latest = None
        return {
            "service_unread": svc.get("unread"),
            "system_unread": sysm.get("unread"),
            "latest": latest,
            "service_records": recs,
        }

    def fetch_share_messages(self, limit: int = 100, offset: int = 0) -> list | None:
        """Sharing-tab messages via /dreame-messaging/user/share-messages.

        GET …/share-messages?version=v1&limit=<limit>&offset=<offset>.
        Returns the raw record list (data.content), or None on failure.
        Logs at WARNING; does not raise.
        """
        self._ensure_strings()
        if getattr(self, "_key_expire", None) and time.time() > self._key_expire:
            self.login()
        strings = getattr(self, "_strings", None) or self.strings
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            strings[47]: strings[3],
            strings[49]: strings[5],
            strings[50]: getattr(self, "_ti", None) or strings[6],
            strings[51]: strings[52],
            strings[46]: getattr(self, "_key", ""),
        }
        if getattr(self, "_country", None) == "cn":
            headers[strings[48]] = strings[4]
        try:
            url = f"{self.get_api_url()}/dreame-messaging/user/share-messages"
            resp = self._session.get(
                url,
                headers=headers,
                params={"version": "v1", "limit": limit, "offset": offset},
                timeout=10,
            )
            if resp.status_code != 200:
                _LOGGER.warning(
                    "fetch_share_messages: HTTP %d (body: %s)",
                    resp.status_code, resp.text[:200],
                )
                return None
            body = resp.json()
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_share_messages: %s", ex)
            return None
        if not isinstance(body, dict) or body.get("code") not in (0, 200):
            _LOGGER.debug(
                "fetch_share_messages: non-zero response code: %r msg=%r",
                (body or {}).get("code") if isinstance(body, dict) else None,
                (body or {}).get("msg") if isinstance(body, dict) else None,
            )
            return None
        records = body.get("data") or {}
        recs = records.get("content") if isinstance(records, dict) else None
        return recs if isinstance(recs, list) else None

    def list_oss_media(self, media_type: str, *, size: int = 12, max_pages: int = 20) -> list | None:
        """List OSS media via iotoss/userDidOssList. media_type 'jpg' (photos) or
        'thumb' (videos). Paged; returns all records or None. Records carry
        server-signed `filepath` (+ `videoPath` for thumb)."""
        import time
        self._ensure_strings()
        if getattr(self, "_key_expire", None) and time.time() > self._key_expire:
            self.login()
        strings = getattr(self, "_strings", None) or self.strings
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            strings[47]: strings[3],
            strings[49]: strings[5],
            strings[50]: getattr(self, "_ti", None) or strings[6],
            strings[51]: strings[52],
            strings[46]: getattr(self, "_key", ""),
        }
        if getattr(self, "_country", None) == "cn":
            headers[strings[48]] = strings[4]
        out: list = []
        for page in range(1, max_pages + 1):
            try:
                url = f"{self.get_api_url()}/dreame-user-iot/iotoss/userDidOssList?current={page}&size={size}"
                resp = self._session.post(url, headers=headers,
                                          json={"did": str(self._did), "type": media_type}, timeout=10)
                if resp.status_code != 200:
                    return out or None
                body = resp.json()
            except Exception as ex:  # pragma: no cover
                _LOGGER.warning("list_oss_media(%s): %s", media_type, ex)
                return out or None
            recs = ((body or {}).get("data") or {}).get("records")
            if recs is None:
                recs = (body or {}).get("records")
            if not recs:
                break
            out.extend(recs)
            if len(recs) < size:
                break
        return out or None

    def fetch_ota_version(self) -> dict[str, Any] | None:
        """OTA availability check — POST iotuserbind/checkDeviceVersion.

        Returns ``{curVersion, newVersion, hasNewFirmware, description}`` or
        ``None``.

        Auth: Dreame-Auth bearer (via ``request()``), no ``sign``. B1 spike
        found the app's ``sign`` field has an opaque per-request input and is
        not reproducible (two identical calls 17 ms apart produced different
        signs); the iotuserbind endpoint family accepts token-auth with a
        ``timestamp`` and no sign (matches the ioBroker.dreame reference
        adapter). ``timestamp`` is the current epoch in MILLISECONDS.

        Source: app-mitm 2026-06-16; inventory.yaml § ota.checkDeviceVersion.
        """
        url = f"{self.get_api_url()}/dreame-user-iot/iotuserbind/checkDeviceVersion"
        body = {"did": str(self._did), "timestamp": int(time.time() * 1000)}
        try:
            import json as _json
            resp = self.request(
                url, _json.dumps(body), content_type="application/json"
            )
        except Exception as ex:  # noqa: BLE001 — defensive
            _LOGGER.warning("fetch_ota_version: %s", ex)
            return None
        if not isinstance(resp, dict):
            return None
        data = resp.get("data")
        if isinstance(data, dict):
            src = data
        else:
            src = resp
        keys = ("curVersion", "newVersion", "hasNewFirmware", "description")
        if not any(k in src for k in keys):
            return None
        return {k: src.get(k) for k in keys}

    def trigger_firmware_update(self) -> bool:
        """"Update now" trigger — POST iotuserbind/manualFirmwareUpdate.

        Returns the INNER ``data.success`` — the device's own verdict. The
        outer ``success`` only means the API received the call; ``False`` here
        means the device refused (weak WiFi / not charging — gated
        device-side). Returns ``False`` on None / non-dict / missing-field /
        transport error.

        Auth: Dreame-Auth bearer (via ``request()``), no ``sign`` (see
        ``fetch_ota_version``). Body carries ``did``, ``uid``, and a
        millisecond ``timestamp``.

        Source: app-mitm 2026-06-16; inventory.yaml § ota.manualFirmwareUpdate.
        """
        url = f"{self.get_api_url()}/dreame-user-iot/iotuserbind/manualFirmwareUpdate"
        body = {
            "did": str(self._did),
            "uid": str(self._uid),
            "timestamp": int(time.time() * 1000),
        }
        try:
            import json as _json
            resp = self.request(
                url, _json.dumps(body), content_type="application/json"
            )
        except Exception as ex:  # noqa: BLE001 — defensive
            _LOGGER.warning("trigger_firmware_update: %s", ex)
            return False
        if not isinstance(resp, dict):
            return False
        data = resp.get("data")
        if not isinstance(data, dict):
            return False
        return bool(data.get("success"))

    def fetch_oss_quota(self) -> dict | None:
        """OSS storage quota via iotoss/checkDevOssStorage → {total, used} bytes."""
        import time
        self._ensure_strings()
        if getattr(self, "_key_expire", None) and time.time() > self._key_expire:
            self.login()
        strings = getattr(self, "_strings", None) or self.strings
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            strings[47]: strings[3],
            strings[49]: strings[5],
            strings[50]: getattr(self, "_ti", None) or strings[6],
            strings[51]: strings[52],
            strings[46]: getattr(self, "_key", ""),
        }
        if getattr(self, "_country", None) == "cn":
            headers[strings[48]] = strings[4]
        try:
            url = f"{self.get_api_url()}/dreame-user-iot/iotoss/checkDevOssStorage"
            resp = self._session.post(url, headers=headers,
                                      json={"did": str(self._did)}, timeout=10)
            if resp.status_code != 200:
                return None
            data = (resp.json() or {}).get("data") or {}
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_oss_quota: %s", ex)
            return None
        try:
            return {"total": int(data["total"]), "used": int(data["used"])}
        except (KeyError, TypeError, ValueError):
            return None
