"""Live per-device telemetry fetchers for DreameA2CloudClient (P3.5 split).

GPS / 4G-SIM status / live position / live AIOBS obstacle markers — the
fast-cadence, view-gated device reads (distinct from the periodic full
cloud-state families in ``_state_fetch.py``).
"""
from __future__ import annotations

import time

from ._helpers import _LOGGER


class _DeviceFetchMixin:

    def fetch_aiobs_markers(self):
        """Fetch + parse the live AIOBS obstacle markers, or None on error."""
        from ..protocol.cfg_action import CfgActionError, get_aiobs_markers  # type: ignore[import]
        from ..protocol.obstacle_markers import parse_aiobs_markers  # type: ignore[import]

        try:
            d = get_aiobs_markers(self.action)
        except CfgActionError as ex:
            _LOGGER.debug("fetch_aiobs_markers: routed-action error: %s", ex)
            return None
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("fetch_aiobs_markers: unexpected error: %s", ex)
            return None
        markers = parse_aiobs_markers(d)
        _LOGGER.info("[AIOBS] fetched %d marker(s)", len(markers))
        return markers

    def fetch_gps(self) -> dict | None:
        """Absolute GPS via dreame-mower-service-app/location/getRecords.

        Returns the newest record as ``{lat, lon, update_time, card4g}``
        (float lat/lon, string timestamps).

        ``None`` = the fetch itself failed (HTTP error, timeout, transport
        exception, or an unparsable record) — a transient failure that the
        caller should NOT treat as "no GPS data" (T3-10: conflating the two
        made a single flaky poll flip the tracker to unknown).

        ``{}`` (empty dict) = the endpoint answered but returned zero
        records — the genuine "no data" shape. ``gpsLat``/``gpsLong`` are
        decimal-degree strings in the wire payload.

        Note: the endpoint is ATA[2]-gated — it returns an empty records
        list when Real-Time Location is disabled in the app. That is the
        one case that should legitimately clear a previously-known fix.
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
        if not isinstance(recs, list):
            # Malformed response (records present but not a list) — a
            # failure, NOT genuine no-data: corrupt cloud data must not
            # clear the tracker (review of the T3-10 fix).
            _LOGGER.warning("fetch_gps: malformed records shape: %s", type(recs).__name__)
            return None
        if not recs:
            return {}
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
