"""File-bridge signing + client mixin for /file-bridge/user/getDeiviceFile.

All constants and the sign function are [UNVERIFIED] — reverse-engineered from
libdreame-lib.so (EncryptUtil::encryptMd5BySalt) + RequestParamsUtil.signParams
[apk:Dreamehome_2.5.6.4].  The hypothesis signer does NOT yet reproduce the
captured golden 952cdf8580ae1c162df56b9c24fe21c3.  See
FINDING-getdevicefile-signer-2026-06-20.md for full analysis.

`_FileBridgeMixin.get_device_file` is the client entrypoint.  It fails closed
(returns None) on any error — backend currently unreliable and the sign is
unverified.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any

from ._helpers import _LOGGER

# ---------------------------------------------------------------------------
# Constants (extracted from native lib .rodata) [apk:libdreame-lib.so]
# ---------------------------------------------------------------------------

#: Basic auth header value — base64(dreame_appv1:AP^dv@z@SQYVxN88)
#: [apk:libdreame-lib.so@0x48a3e]  [UNVERIFIED as complete formula]
FILE_BRIDGE_BASIC_AUTH: str = "Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg="

#: FileTypes enum serialized inside the fileinfo JSON field.
#: [apk:index.android.bundle@6544183]
FILE_BRIDGE_TYPES: dict[str, str] = {
    "Obstacle": "ai_obs",
    "Pet": "pet",
    "Cruise": "cruise",
    "List": "list",
    "Map": "map",
    "Delete": "delete",
}

#: Sign salt from native lib .rodata [apk:libdreame-lib.so@0x4889b]
_DEFAULT_SIGN_SALT: str = "RAylYC%fmSKp7%Tq"

#: AES/GCM key for dreame-rlc header [apk:libdreame-lib.so@0x48f6d]
FILE_BRIDGE_RLC_KEY: str = "RAylYC%XI5z*nHsI"


# ---------------------------------------------------------------------------
# Signer
# ---------------------------------------------------------------------------


def sign_file_bridge(
    params: dict,
    timestamp_ms: int,
    *,
    salt: str = _DEFAULT_SIGN_SALT,
) -> str:
    """[UNVERIFIED] Hypothesis signer for /file-bridge/user/getDeiviceFile.

    Reverse-engineered from libdreame-lib.so (EncryptUtil::encryptMd5BySalt) +
    RequestParamsUtil.signParams [apk:Dreamehome_2.5.6.4].  Does NOT yet reproduce
    the captured golden 952cdf8580ae1c162df56b9c24fe21c3 — a hidden signed input
    is missing.  Verify against a live 200 or a successful app capture before
    trusting.  See FINDING-getdevicefile-signer-2026-06-20.md.

    Formula (hypothesis):
      1. Sort body params alphabetically by key, excluding 'sign' and 'timestamp'.
      2. Build ``k=v&k=v`` string.
      3. Append ``str(timestamp_ms)`` (no separator).
      4. Append salt.
      5. Return lowercase MD5 hex of the UTF-8 encoded result.
    """
    pairs = sorted(
        (k, str(v)) for k, v in params.items() if k not in ("sign", "timestamp")
    )
    spliced = "&".join(f"{k}={v}" for k, v in pairs)
    to_sign = spliced + str(timestamp_ms) + salt
    return hashlib.md5(to_sign.encode()).hexdigest()


# ---------------------------------------------------------------------------
# File-bridge base URL
# ---------------------------------------------------------------------------

#: Base URL for the file-bridge service.
#: Captured host from app MITM: eu.iot.dreame.tech:13267
#: [capture:cloud/captures/mitm_session_20260619/miio-13267.jsonl]
#: TODO: the EU-region host is hardcoded here; other regions may differ.
#: The main cloud RPC uses self._country + strings[0]/[1] (see _rpc.get_api_url).
#: The file-bridge runs on a separate service at port 13267 with no country-prefix
#: equivalant in the strings table, so we keep it as a module constant.
_FILE_BRIDGE_BASE_URL: str = "https://eu.iot.dreame.tech:13267"


# ---------------------------------------------------------------------------
# Client mixin
# ---------------------------------------------------------------------------


class _FileBridgeMixin:
    """[UNVERIFIED signer] File-bridge download client for DreameA2CloudClient.

    Adds ``get_device_file`` — fetches an obstacle/pet/cruise photo from the
    file-bridge service at /file-bridge/user/getDeiviceFile.

    The request signing is UNVERIFIED (signer recovered from the native lib but
    does not reproduce the captured golden; see FINDING-getdevicefile-signer-
    2026-06-20.md).  The backend is also currently unreliable.  This mixin fails
    closed: every error path returns None with a DEBUG log.  Do NOT mark anything
    here verified until a live 200 is observed.
    """

    def _post_file_bridge(self, body: dict) -> Any:
        """POST the signed body to /file-bridge/user/getDeiviceFile.

        This is a seam for testing — tests override this method to return a
        fake response dict without hitting the network.  The real implementation
        uses ``self._session`` directly (no retry — the backend is flaky and we
        fail closed on any error).

        Returns the parsed JSON dict on a 200 response, or None on any error.
        """
        url = f"{_FILE_BRIDGE_BASE_URL}/file-bridge/user/getDeiviceFile"
        headers = {
            "Authorization": FILE_BRIDGE_BASIC_AUTH,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
        }
        try:
            response = self._session.post(
                url,
                data=json.dumps(body, separators=(",", ":")),
                headers=headers,
                timeout=15,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("[file-bridge] POST error: %s", exc)
            return None
        if response.status_code != 200:
            _LOGGER.debug(
                "[file-bridge] POST non-200: status=%d body=%r",
                response.status_code,
                response.text[:200],
            )
            return None
        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("[file-bridge] JSON parse error: %s", exc)
            return None

    def get_device_file(
        self, filename: str, file_type: str = "ai_obs"
    ) -> bytes | None:
        """[UNVERIFIED signer] Fetch one obstacle file via /file-bridge/user/getDeiviceFile.

        Fails closed (returns None) on any error — backend currently unreliable
        and the sign is unverified.  See FINDING-getdevicefile-signer-2026-06-20.md.

        Response shape is unknown (never captured a 200).  Two hypotheses are
        handled:
        - JSON with a base64 ``data`` field → decoded to raw bytes
          (``code64=true`` hint from the app bundle).
        - JSON with a URL in the ``data`` (or ``url``) field → fetched via
          ``self.get_file(url)`` (the OSS download path already in _OssMixin).
        - Raw JPEG bytes (starts with ``\\xff\\xd8``) returned directly.
        On ANY exception or unexpected shape → None.
        """
        try:
            fileinfo = json.dumps(
                {"filename": filename, "type": file_type}, separators=(",", ":")
            )
            did = str(self._did)
            timestamp_ms = int(time.time() * 1000)
            sign = sign_file_bridge(
                {"fileinfo": fileinfo, "did": did}, timestamp_ms
            )
            body = {
                "fileinfo": fileinfo,
                "did": did,
                "sign": sign,
                "timestamp": timestamp_ms,
            }
            resp = self._post_file_bridge(body)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("[file-bridge] get_device_file build/post error: %s", exc)
            return None

        if resp is None:
            return None

        # resp is the parsed JSON dict.  Extract the payload field.
        try:
            # Prefer "data"; fall back to "url" (hypothetical alternative key).
            payload = resp.get("data") or resp.get("url")
            if not payload:
                _LOGGER.debug(
                    "[file-bridge] get_device_file: no data/url in response: %r",
                    resp,
                )
                return None

            # Detect raw JPEG: starts with JPEG SOI marker \xff\xd8
            if isinstance(payload, (bytes, bytearray)) and payload[:2] == b"\xff\xd8":
                return bytes(payload)

            if isinstance(payload, str):
                # URL branch: data field is an http(s) URL.
                if payload.startswith("http"):
                    return self.get_file(payload)
                # Base64 branch: data field is base64-encoded bytes.
                return base64.b64decode(payload)

            _LOGGER.debug(
                "[file-bridge] get_device_file: unexpected payload type %s",
                type(payload).__name__,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("[file-bridge] get_device_file decode error: %s", exc)
            return None
