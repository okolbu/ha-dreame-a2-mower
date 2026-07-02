"""OSS / WiFi-map mixin for DreameA2CloudClient (B1d split from cloud_client.py)."""
from __future__ import annotations

from typing import Any

import requests

from ._helpers import _LOGGER, _http_retry


class _OssMixin:

    def get_interim_file_url(self, object_name: str = "") -> str | None:
        """Fetch a time-limited signed OSS URL for an object.

        This is the only reliable mechanism to download session-summary JSONs
        and LiDAR PCDs on g2408.  ``object_name`` is the MQTT-pushed object
        key from the ``event_occured`` message.

        Source: legacy ``dreame/protocol.py`` ``get_interim_file_url()``.
        See also: docs/research/g2408-protocol.md §1.2 (OSS download).
        """
        if not object_name:
            # An empty object_name is never a valid OSS key; the cloud replies
            # with error 40020 ("数据错误"). Skip the round-trip + the WARNING.
            _LOGGER.debug("[OSS] get_interim_file_url: empty object_name — skipping")
            return None
        strings = self._ensure_strings()
        api_response = self._api_call(
            f"{strings[23]}/{strings[39]}/{strings[55]}",
            {
                "did": str(self._did),
                strings[35]: self._model,
                strings[40]: object_name,
                strings[21]: self._country,
            },
        )
        if api_response is None:
            _LOGGER.warning(
                "[OSS] get_interim_file_url: API call returned None for "
                "object_name=%r — cloud transport failure",
                object_name,
            )
            return None
        if "data" not in api_response:
            _LOGGER.warning(
                "[OSS] get_interim_file_url: response had no `data` field "
                "for object_name=%r. Full response: %r",
                object_name,
                api_response,
            )
            return None
        return api_response["data"]

    def get_file_url(self, object_name: str = "") -> Any:
        """Fetch an OSS URL via the alternative (non-interim) endpoint."""
        strings = self._ensure_strings()
        api_response = self._api_call(
            f"{strings[23]}/{strings[39]}/{strings[56]}",
            {
                "did": str(self._did),
                "uid": str(self._uid),
                strings[35]: self._model,
                "filename": object_name[1:],
                strings[21]: self._country,
            },
        )
        if api_response is None or "data" not in api_response:
            return None
        return api_response["data"]

    def list_3dmap_objects(self) -> list[str] | None:
        """List the LiDAR PCD OSS object keys via the OBJ routed action.

        `s2.50 m='g' t='OBJ' d={type:'3dmap'}` → {out:[{d:{name:[<obj>,...]}}]},
        newest-first. These are the SAME `.0550.bin` PCD objects that s99.20
        announces over MQTT (see inventory.yaml § s99p20). Used by the startup
        LiDAR backfill so fresh installs don't wait for a live "View LiDAR Map"
        push.

        Returns the list of non-empty object-name strings (possibly empty `[]`
        when the cloud holds no 3dmap objects), or ``None`` when the routed
        action failed (e.g. the g2408 relay 80001'd) so the caller can retry.
        """
        try:
            resp = self.action(
                siid=2, aiid=50,
                parameters=[{"m": "g", "t": "OBJ", "d": {"type": "3dmap"}}],
            )
        except Exception as ex:  # noqa: BLE001 — observability never breaks refresh
            _LOGGER.warning("list_3dmap_objects: OBJ probe error: %s", ex)
            return None
        if not isinstance(resp, dict):
            return None
        outs = resp.get("out") or []
        if not outs or not isinstance(outs[0], dict):
            return None
        names = (outs[0].get("d") or {}).get("name")
        if names is None:
            return None
        if isinstance(names, dict):
            names = list(names.values())
        if not isinstance(names, list):
            return None
        return [n for n in names if isinstance(n, str) and n]

    # fetch_wifi_map() + its sole helper _download_wifi_object() deleted
    # 2026-07-02 — dead code from the single-map / entity-validation-matrix
    # era (zero production callers; the live multi-map path is
    # list_wifi_candidates(), the sole caller of which is
    # coordinator/_wifi_archive.py). See
    # docs/research/debunked-claims.md § single-map era.

    def list_wifi_candidates(
        self,
        map_extents: "dict[int, tuple[float, float, float, float]] | None" = None,
    ) -> "list[dict]":
        """Return metadata for every wifimap object in the cloud, sorted newest-first.

        Calls the same OBJ probe as ``fetch_wifi_map`` but returns ALL objects
        (one per map, typically), not just the one that matches a given map_id.
        Each returned dict has:
            {
                "object_name": str,
                "unix_ts": int,       # parsed from filename; 0 if not parseable
                "map_id": int | None, # geometry-matched against map_extents
                "startX": float, "startY": float,
                "width": int, "height": int, "resolution": int,
            }

        map_extents: dict mapping map_id → (x1, y1, x2, y2) in cm (cloud frame).
        If empty or None, map_id is left as None for all candidates.
        """
        import re as _re
        import json as _json_lc
        try:
            obj_resp = self.action(
                siid=2, aiid=50,
                parameters=[{"m": "g", "t": "OBJ", "d": {"type": "wifimap"}}],
            )
        except Exception as ex:
            _LOGGER.warning("list_wifi_candidates: OBJ probe error: %s", ex)
            return []
        if not isinstance(obj_resp, dict):
            return []
        outs = obj_resp.get("out") or []
        if not outs or not isinstance(outs[0], dict):
            return []
        names = (outs[0].get("d") or {}).get("name")
        if not names:
            return []
        candidates: "list[str]" = []
        if isinstance(names, list):
            candidates = [n for n in names if isinstance(n, str)]
        elif isinstance(names, dict):
            candidates = [v for v in names.values() if isinstance(v, str)]
        if not candidates:
            return []

        def _decode_candidate(obj_name: str) -> "dict[str, Any] | None":
            cache = getattr(self, "_wifi_map_cache", None)
            if cache is not None:
                for (mid, cached_name), cached_dec in cache.items():
                    if cached_name == obj_name:
                        return cached_dec
            url = self.get_interim_file_url(obj_name)
            if not url:
                return None
            body = self.get_file(url)
            if not body:
                return None
            try:
                dec = _json_lc.loads(body)
            except Exception as e:
                _LOGGER.debug("_decode_candidate(%s): JSON/LZ4 decode failed: %s", obj_name, e)
                return None
            if isinstance(dec, dict) and "data" in dec:
                dec["_object_name"] = obj_name
                return dec
            return None

        def _parse_unix_ts(obj_name: str) -> int:
            """Extract a unix timestamp from the object's filename component."""
            # Typical pattern: something/wifimap_<digits>.json or _<digits>_...
            m = _re.search(r"_(\d{9,11})(?:[._]|$)", obj_name)
            if m:
                return int(m.group(1))
            # Fallback: any 10-digit run.
            m = _re.search(r"\b(\d{10})\b", obj_name)
            if m:
                return int(m.group(1))
            return 0

        results: "list[dict]" = []
        extents = map_extents or {}
        for obj_name in candidates:
            dec = _decode_candidate(obj_name)
            if dec is None:
                continue
            # Cloud body schema (wifimap OBJ candidate):
            #   startX, startY     — bbox origin in cm (cloud frame)
            #   width, height      — cell counts
            #   resolution         — cell size in METRES per cell on g2408
            try:
                start_x_cm = float(dec.get("startX", 0))
                start_y_cm = float(dec.get("startY", 0))
                cells_w = int(dec.get("width", 0))
                cells_h = int(dec.get("height", 0))
                cell_size_m = int(dec.get("resolution", 1)) or 1
            except (TypeError, ValueError) as e:
                _LOGGER.debug("_decode_candidate(%s): malformed cell geometry, using fallback zeros: %s", obj_name, e)
                start_x_cm = start_y_cm = 0.0
                cells_w = cells_h = 0
                cell_size_m = 1

            # Geometry-match: find which map's extent contains this heatmap's centre.
            matched_map_id: "int | None" = None
            if extents:
                cell_size_cm = cell_size_m * 100
                bbox_w_cm = cells_w * cell_size_cm
                bbox_h_cm = cells_h * cell_size_cm
                centre_x_cm = start_x_cm + bbox_w_cm / 2.0
                centre_y_cm = start_y_cm + bbox_h_cm / 2.0
                for mid, (ex_x1, ex_y1, ex_x2, ex_y2) in extents.items():
                    x1, x2 = sorted((ex_x1, ex_x2))
                    y1, y2 = sorted((ex_y1, ex_y2))
                    if x1 <= centre_x_cm <= x2 and y1 <= centre_y_cm <= y2:
                        matched_map_id = mid
                        break

            results.append({
                "object_name": obj_name,
                "unix_ts": _parse_unix_ts(obj_name),
                "map_id": matched_map_id,
                "_assigned_by": "geometry" if matched_map_id is not None else None,
                "startX": start_x_cm,
                "startY": start_y_cm,
                "width": cells_w,
                "height": cells_h,
                "resolution": cell_size_m,
            })

        # Tier-2 positional fallback: when geometry matching leaves
        # ambiguity (e.g., overlapping or co-located map extents),
        # assign by array position iff the count of unmatched
        # candidates equals the count of unmatched maps. The cloud's
        # OBJ array order is "newest-first" globally, but when there
        # is exactly one heatmap per map this collapses to a stable
        # 1:1 mapping. Sorted map_ids ensure determinism.
        if extents and results:
            unmatched_map_ids = sorted(
                mid for mid in extents.keys()
                if not any(r.get("map_id") == mid for r in results)
            )
            unmatched_results = [r for r in results if r.get("map_id") is None]
            if (
                unmatched_map_ids
                and len(unmatched_map_ids) == len(unmatched_results)
            ):
                for r, mid in zip(unmatched_results, unmatched_map_ids):
                    r["map_id"] = mid
                    r["_assigned_by"] = "positional"
                    _LOGGER.info(
                        "list_wifi_candidates: positional fallback "
                        "assigned %s → map_id=%d",
                        r["object_name"], mid,
                    )

        results.sort(key=lambda r: r["unix_ts"], reverse=True)
        return results

    def get_file(self, url: str, retry_count: int = 4) -> Any:
        """Download raw bytes from a signed OSS URL.

        Source: legacy ``dreame/protocol.py`` ``get_file()``.
        """
        if not retry_count or retry_count < 0:
            retry_count = 0

        class _NonOKStatus(Exception):
            """Raised inside the action lambda when HTTP status != 200."""

        def _do_get() -> bytes:
            response = self._session.get(url, timeout=15)
            if response.status_code != 200:
                raise _NonOKStatus(response.status_code)
            return response.content

        def _log_and_retry(exc: BaseException) -> bool:
            if isinstance(exc, _NonOKStatus):
                _LOGGER.warning(
                    "Unable to get file at %s: HTTP %s", url, exc.args[0]
                )
            else:
                _LOGGER.warning("Unable to get file at %s: %s", url, exc)
            return True

        try:
            return _http_retry(
                _do_get,
                max_attempts=retry_count + 1,
                should_retry=_log_and_retry,
            )
        except (_NonOKStatus, requests.exceptions.RequestException):
            # HTTP non-200 / transport failure already logged by
            # _log_and_retry; a code bug in _do_get would propagate.
            return None
