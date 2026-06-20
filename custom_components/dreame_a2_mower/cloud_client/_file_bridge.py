"""File-bridge signing + constants for /file-bridge/user/getDeiviceFile.

All constants and the sign function are [UNVERIFIED] — reverse-engineered from
libdreame-lib.so (EncryptUtil::encryptMd5BySalt) + RequestParamsUtil.signParams
[apk:Dreamehome_2.5.6.4].  The hypothesis signer does NOT yet reproduce the
captured golden 952cdf8580ae1c162df56b9c24fe21c3.  See
FINDING-getdevicefile-signer-2026-06-20.md for full analysis.

Task 11 will add a _FileBridgeMixin to this file.
"""
from __future__ import annotations

import hashlib

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
