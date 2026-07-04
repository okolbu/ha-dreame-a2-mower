"""OTA version-check fetcher for DreameA2CloudClient (P3.5 transport split).

The OTA *trigger* (``trigger_firmware_update``) is a write and lives in
``_writers.py``; this module carries only the read-side availability check.
"""
from __future__ import annotations

import time
from typing import Any

from ._helpers import _LOGGER


class _OtaMixin:

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
