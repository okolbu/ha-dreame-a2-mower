"""Probe for /file-bridge/user/getDeiviceFile — offline self-test + live replay.

Offline mode (default): calls sign_file_bridge against the captured golden inputs
and reports whether the hypothesis formula reproduces the golden signature.  It
will print MISMATCH — that is the honest current state.

Live mode (--live --filename <name>): POSTs to the real endpoint with the signed
body + required headers and prints the full response so the response shape can
be captured.  Backend is currently down ("Client disconnected"); the probe handles
that cleanly.

Usage:
  # Offline self-test (default — prints MISMATCH, not a bug):
  python tools/probes/getdevicefile_probe.py

  # Live replay:
  python tools/probes/getdevicefile_probe.py --live --filename 1781714586.078000_0.jpg [--did -112293549]

Credentials for --live: same as other probes — DREAME_USER/DREAME_PASS/DREAME_COUNTRY
env vars or /data/claude/homeassistant/secrets/server-credentials.txt.
Dev-box only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap — needed so we can import from the repo without a real HA install.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

TOOL_META = {
    "domain": "probes",
    "run_by": "owner",
    "when": (
        "When testing the [UNVERIFIED] file-bridge signer or capturing the live "
        "getDeiviceFile response shape. Offline mode needs no credentials."
    ),
    "summary": (
        "Offline: checks hypothesis sign formula against the captured golden "
        "(will print MISMATCH until the formula is corrected). "
        "Live (--live --filename): POST to file-bridge endpoint and print full response."
    ),
}

# Golden test inputs from FINDING-getdevicefile-signer-2026-06-20.md
# [cloud/captures/mitm_session_20260619/miio-13267.jsonl@2026-06-17_19:50:18]
_GOLDEN_FILEINFO = '{"filename":"1781714586.078000_0.jpg","type":"ai_obs"}'
_GOLDEN_DID = "-112293549"
_GOLDEN_TS = 1781718618184
_GOLDEN_SIGN = "952cdf8580ae1c162df56b9c24fe21c3"

_FILE_BRIDGE_URL = "https://eu.iot.dreame.tech:13267/file-bridge/user/getDeiviceFile"
_DEFAULT_CREDS = "/data/claude/homeassistant/secrets/server-credentials.txt"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Offline self-test
# ---------------------------------------------------------------------------

def _import_file_bridge():
    """Import _file_bridge without triggering the full integration __init__.

    _file_bridge.py only uses hashlib — no HA deps.  Load it directly via
    importlib to avoid the homeassistant stubs dance for a no-HA module.
    """
    import importlib.util
    fb_path = (
        _REPO_ROOT
        / "custom_components"
        / "dreame_a2_mower"
        / "cloud_client"
        / "_file_bridge.py"
    )
    spec = importlib.util.spec_from_file_location(
        "dreame_a2_mower.cloud_client._file_bridge", str(fb_path)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def offline_selftest() -> None:
    fb = _import_file_bridge()
    sign_file_bridge = fb.sign_file_bridge
    FILE_BRIDGE_BASIC_AUTH = fb.FILE_BRIDGE_BASIC_AUTH

    params = {"fileinfo": _GOLDEN_FILEINFO, "did": _GOLDEN_DID}
    got = sign_file_bridge(params, _GOLDEN_TS)

    print(f"[{_ts()}] === getDeiviceFile signer offline self-test ===")
    print(f"[{_ts()}] inputs  fileinfo={_GOLDEN_FILEINFO!r}  did={_GOLDEN_DID!r}  ts={_GOLDEN_TS}")
    print(f"[{_ts()}] golden  {_GOLDEN_SIGN}")
    print(f"[{_ts()}] got     {got}")

    if got == _GOLDEN_SIGN:
        # Should not happen until the formula is corrected — but do not suppress it
        # if it ever does match.
        print(f"[{_ts()}] MATCH  — signer reproduces golden (unexpected; verify this is correct)")
    else:
        print(
            f"[{_ts()}] MISMATCH — hypothesis formula does not yet reproduce the captured golden."
        )
        print(
            f"[{_ts()}]   This is the known [UNVERIFIED] state.  A hidden signed input is missing."
        )
        print(
            f"[{_ts()}]   See FINDING-getdevicefile-signer-2026-06-20.md for analysis."
        )

    print(f"[{_ts()}] Basic-auth header: {FILE_BRIDGE_BASIC_AUTH!r}")


# ---------------------------------------------------------------------------
# Live POST
# ---------------------------------------------------------------------------

def _load_credentials() -> dict[str, str]:
    user = os.environ.get("DREAME_USER")
    passwd = os.environ.get("DREAME_PASS")
    country = os.environ.get("DREAME_COUNTRY", "eu")
    if user and passwd:
        return {"username": user, "password": passwd, "country": country}
    path = Path(_DEFAULT_CREDS)
    if not path.is_file():
        raise SystemExit(
            f"Credentials file not found: {path}. "
            "Set DREAME_USER / DREAME_PASS env vars or update _DEFAULT_CREDS."
        )
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    if len(lines) < 2:
        raise SystemExit(f"{path}: need email on line 1, password on line 2")
    return {
        "username": lines[0],
        "password": lines[1],
        "country": lines[2] if len(lines) >= 3 else country,
    }


def live_probe(filename: str, did: str | None) -> None:
    """POST to the real file-bridge endpoint and print the full response."""
    import urllib.error
    import urllib.parse
    import urllib.request

    fb = _import_file_bridge()
    sign_file_bridge = fb.sign_file_bridge
    FILE_BRIDGE_BASIC_AUTH = fb.FILE_BRIDGE_BASIC_AUTH
    FILE_BRIDGE_TYPES = fb.FILE_BRIDGE_TYPES

    creds = _load_credentials()

    # Build body
    fileinfo = json.dumps({"filename": filename, "type": FILE_BRIDGE_TYPES["Obstacle"]})
    timestamp_ms = int(time.time() * 1000)

    # For the DID we need a logged-in client if none supplied
    if did is None:
        # Import bootstrap machinery from _probe_common
        sys.path.insert(0, str(_REPO_ROOT / "tools" / "probes"))
        from _probe_common import connect  # noqa: PLC0415
        print(f"[{_ts()}] Logging in to discover device DID …")
        cloud = connect()
        did = str(cloud._did)
        print(f"[{_ts()}] DID = {did}")

    params = {"fileinfo": fileinfo, "did": did}
    sign = sign_file_bridge(params, timestamp_ms)

    body_dict = {**params, "sign": sign, "timestamp": str(timestamp_ms)}
    body_bytes = urllib.parse.urlencode(body_dict).encode()

    print(f"[{_ts()}] === getDeiviceFile live probe ===")
    print(f"[{_ts()}] POST {_FILE_BRIDGE_URL}")
    print(f"[{_ts()}] body {body_dict}")
    print(
        f"[{_ts()}] NOTE: sign is [UNVERIFIED] — expect 401/403 until formula is corrected"
    )

    req = urllib.request.Request(
        _FILE_BRIDGE_URL,
        data=body_bytes,
        method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Authorization", FILE_BRIDGE_BASIC_AUTH)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            headers = dict(resp.headers)
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        print(f"[{_ts()}] HTTP {exc.code} {exc.reason}")
        try:
            raw = exc.read()
            print(f"[{_ts()}] response body: {raw.decode(errors='replace')}")
        except Exception:  # noqa: BLE001
            pass
        return
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"[{_ts()}] Network error: {exc}")
        print(f"[{_ts()}] Backend may be down (Client disconnected is expected).")
        return

    print(f"[{_ts()}] HTTP {status}")
    for k, v in headers.items():
        print(f"[{_ts()}]   {k}: {v}")
    body_str = raw.decode(errors="replace")
    try:
        parsed = json.loads(body_str)
        print(f"[{_ts()}] response body (JSON): {json.dumps(parsed, indent=2)}")
    except json.JSONDecodeError:
        print(f"[{_ts()}] response body (raw): {body_str[:2000]}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="POST to the real endpoint (requires credentials, --filename required)",
    )
    parser.add_argument(
        "--filename",
        default=None,
        help="Obstacle photo filename to request (e.g. 1781714586.078000_0.jpg)",
    )
    parser.add_argument(
        "--did",
        default=None,
        help="Device DID (optional; auto-discovered via login if omitted with --live)",
    )
    args = parser.parse_args()

    if args.live:
        if not args.filename:
            parser.error("--live requires --filename")
        live_probe(args.filename, args.did)
    else:
        offline_selftest()


if __name__ == "__main__":
    main()
