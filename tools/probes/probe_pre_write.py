#!/usr/bin/env python3
"""Probe whether CFG.PRE (Mowing Efficiency = PRE[1]) is device-writable on g2408.

Why
---
EdgeMaster (s6p2[2]) and Mowing Efficiency (s6p2[1]) were long carried as
"no working device-write surface" — but tracing the evidence (see the
2026-06-03 analysis) shows that conclusion was *extrapolated*, never tested:

  * The cloud-cache-only proof (settings-surface-cloud-only-2026-05-09.md)
    was on a SETTINGS chunked-batch field (obstacleAvoidanceAi), NOT on PRE.
  * Mowing height's "writable" entity also rides that same cloud-cache-only
    SETTINGS batch — so height is NOT a working example to generalise from.
  * Mowing Efficiency's real home is CFG.PRE[1], whose write path
    (cfg_action.set_pre → routed-action {m:'s', t:'PRE', d:{value:…}}) is the
    SAME transport tier proven to DRIVE the device for 9 simple CFG keys
    (CLS/FDP/STUN/AOP/PROT/VOL/ATA/MSG_ALERT/VOICE — cfg-write-regression-2026-05-09.md).
  * PRE was NEVER in that 16-key probe. Genuinely untested.

So this is the one promising, untested lead. This script reads CFG.PRE, fires
a flipped value through the real routed-action transport, and reports the
device's `out[0].r`:

  r == 0   + CFG.VER bumps  → PRE IS device-writable; the "no write surface"
                              framing collapses (then confirm behaviourally).
  r == -3                   → no setter registered for PRE on this firmware
                              — a REAL disproof for efficiency, at last.
  None / 80001              → relay asleep (docked-idle device). INCONCLUSIVE —
                              re-run while the mower is actively connected.
                              The --relay-check / findBot control disambiguates.

g2408 CFG.PRE is the 2-element shape ``[zone_id, mode]`` (NOT the apk's 10).
The integration's set_pre() currently *raises* on len<10 and inflates short
arrays (open PRE bug, TODO:974) — this probe deliberately bypasses set_pre and
builds the wire envelope directly so we can test the correct 2-element shape
(and compare against the bare / 10-element / named variants).

Usage
-----
::

    # Just read current PRE + VER (no write)
    python3 tools/probes/probe_pre_write.py --read

    # Is the cloud relay awake right now? (harmless findBot beep)
    python3 tools/probes/probe_pre_write.py --relay-check

    # Probe writability: flip mode, read out[0].r, then RESTORE original
    # (non-destructive). Uses the highest-confidence shape by default.
    python3 tools/probes/probe_pre_write.py --probe

    # Try every candidate shape until one returns r=0 (each auto-restored)
    python3 tools/probes/probe_pre_write.py --probe --auto

    # Intentionally SET efficiency and LEAVE it (for the behavioural test:
    # then check the Dreame app / mowing behaviour reflects it). 0=Standard 1=Efficient.
    python3 tools/probes/probe_pre_write.py --set 1

Confirming firmware-side acceptance: cloud ``r:0`` + a ``CFG.VER`` bump is the
strong cloud signal, but the decisive proof the *device* applied it is the
behavioural / app-side check (CLS was confirmed this way). In a second
terminal, ``probe_a2_mqtt.py`` will also show the device's ``s6p2`` echo if the
firmware re-publishes the frame.

Credentials: ``DREAME_USER`` / ``DREAME_PASS`` env vars or
``/data/claude/homeassistant/secrets/server-credentials.txt`` (email line 1, password
line 2, country optional line 3, default ``eu``). ``--credentials <path>`` overrides.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


# --- Stub `homeassistant` so we can import the cloud_client package standalone
# Mirrors tools/probes/probe_cruise_to_point.py.
for _mod in (
    "homeassistant",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.helpers",
    "homeassistant.helpers.event",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.device_registry",
    "homeassistant.components",
    "homeassistant.components.persistent_notification",
    "homeassistant.components.http",
    "homeassistant.components.button",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.camera",
    "homeassistant.components.lawn_mower",
    "homeassistant.components.number",
    "homeassistant.components.select",
    "homeassistant.components.sensor",
    "homeassistant.components.switch",
    "homeassistant.components.time",
    "homeassistant.exceptions",
    "homeassistant.util",
    "voluptuous",
):
    sys.modules.setdefault(_mod, MagicMock())

import importlib.util  # noqa: E402
import types  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INTEG_ROOT = str(_REPO_ROOT / "custom_components" / "dreame_a2_mower")

TOOL_META = {"domain": "probes", "run_by": "owner",
    "when": "When testing whether CFG.PRE (mowing efficiency) is device-writable. WRITES to the live device.",
    "summary": "Probe whether CFG.PRE is writable on the g2408 vs cloud-cache-only."}

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from tools._toolmeta import add_to_parser  # noqa: E402


def _load_module(modname: str, filepath: str, package: str | None = None):
    spec = importlib.util.spec_from_file_location(modname, filepath)
    mod = importlib.util.module_from_spec(spec)
    if package is not None:
        mod.__package__ = package
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_package(modname: str, pkgdir: str):
    spec = importlib.util.spec_from_file_location(
        modname,
        f"{pkgdir}/__init__.py",
        submodule_search_locations=[pkgdir],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_pkg = types.ModuleType("dreame_a2_mower")
_pkg.__path__ = [_INTEG_ROOT]
sys.modules["dreame_a2_mower"] = _pkg

_proto_pkg = types.ModuleType("dreame_a2_mower.protocol")
_proto_pkg.__path__ = [f"{_INTEG_ROOT}/protocol"]
sys.modules["dreame_a2_mower.protocol"] = _proto_pkg

_load_module("dreame_a2_mower.const", f"{_INTEG_ROOT}/const.py", package="dreame_a2_mower")
_load_module(
    "dreame_a2_mower.protocol.cfg_action",
    f"{_INTEG_ROOT}/protocol/cfg_action.py",
    package="dreame_a2_mower.protocol",
)
_cloud_mod = _load_package(
    "dreame_a2_mower.cloud_client",
    f"{_INTEG_ROOT}/cloud_client",
)
DreameA2CloudClient = _cloud_mod.DreameA2CloudClient


# --- Candidate `d`-payload shapes for {m:'s', t:'PRE', d:<here>} -------------
#
# Each builder takes the full PRE array and returns the `d` field. Ordered by
# confidence. The PROVEN-good envelope for simple CFG keys (CLS et al.) is the
# wrapped form ``d={"value": <payload>}`` — so wrapped_2 is the prime candidate.

def shape_wrapped(pre_array: list) -> Any:
    """d={"value": [...]} — the format proven to drive the device for the 9
    simple CFG keys (cfg-write-regression-2026-05-09.md §"the fix")."""
    return {"value": list(pre_array)}


def shape_bare(pre_array: list) -> Any:
    """d=[...] — the pre-v1.0.2a9 bare format (r=-3 for the 16 keys tested,
    but PRE was never among them)."""
    return list(pre_array)


def shape_named(pre_array: list) -> Any:
    """d={"zone_id":…, "mode":…} — named-key variant (mirrors the DND
    named-key attempt). Only meaningful for the 2-element shape."""
    d: dict[str, int] = {}
    if len(pre_array) >= 1:
        d["zone_id"] = int(pre_array[0])
    if len(pre_array) >= 2:
        d["mode"] = int(pre_array[1])
    return d


SHAPES: dict[str, Any] = {
    "wrapped": shape_wrapped,
    "bare": shape_bare,
    "named": shape_named,
}

# Probe order under --auto: wrapped first (proven transport), then bare, then named.
AUTO_ORDER = ["wrapped", "bare", "named"]


# --- Credentials + client setup (mirrors probe_cruise_to_point.py) -----------

DEFAULT_CREDS_PATH = "/data/claude/homeassistant/secrets/server-credentials.txt"


def _load_credentials(path: str) -> dict[str, str]:
    user = os.environ.get("DREAME_USER")
    passwd = os.environ.get("DREAME_PASS")
    country = os.environ.get("DREAME_COUNTRY", "eu")
    if user and passwd:
        return {"username": user, "password": passwd, "country": country}
    creds_file = Path(path)
    if not creds_file.is_file():
        raise SystemExit(
            f"Credentials file not found: {creds_file}. "
            "Set DREAME_USER / DREAME_PASS env vars or pass --credentials."
        )
    lines = [l.strip() for l in creds_file.read_text().splitlines() if l.strip()]
    if len(lines) < 2:
        raise SystemExit(f"{creds_file}: need email on line 1, password on line 2")
    return {
        "username": lines[0],
        "password": lines[1],
        "country": lines[2] if len(lines) >= 3 else country,
    }


def _build_cloud_client(creds_path: str):
    creds = _load_credentials(creds_path)
    client = DreameA2CloudClient(
        username=creds["username"],
        password=creds["password"],
        country=creds["country"],
    )
    if not client.login():
        raise SystemExit("login failed — check credentials")
    client.select_first_g2408()
    client.get_device_info()
    return client


# --- CFG read helpers --------------------------------------------------------

def read_cfg(client) -> dict[str, Any]:
    cfg = client.fetch_cfg()
    if not isinstance(cfg, dict):
        raise SystemExit("fetch_cfg returned nothing (relay asleep? not logged in?)")
    return cfg


def show_pre(cfg: dict[str, Any], label: str = "PRE") -> tuple[list | None, Any]:
    pre = cfg.get("PRE")
    ver = cfg.get("VER")
    if isinstance(pre, list) and len(pre) >= 2:
        mode = pre[1]
        mode_name = {0: "Standard", 1: "Efficient"}.get(mode, "?")
        print(f"  {label}: {pre}  (zone_id={pre[0]}, mode={mode}={mode_name})  CFG.VER={ver}")
    else:
        print(f"  {label}: {pre!r}  CFG.VER={ver}  (unexpected shape)")
    return (pre if isinstance(pre, list) else None), ver


# --- Send one PRE write ------------------------------------------------------

def send_pre(client, shape_name: str, pre_array: list) -> tuple[Any, int | None, int | None]:
    """Fire {m:'s', t:'PRE', d:<shape>} via the routed-action s2.50 path.

    Returns (raw_reply, out0_r, last_send_error_code).
    Bypasses cfg_action.set_pre (which raises on len<10) by hand-building the
    envelope — exactly the wire the integration would emit, minus the length guard.
    """
    d_field = SHAPES[shape_name](pre_array)
    envelope = {"m": "s", "t": "PRE", "d": d_field}
    print(
        f"→ shape={shape_name!r}  payload={pre_array}"
        f"\n  wire: action(siid=2, aiid=50, [{json.dumps(envelope, separators=(',', ':'))}])"
    )
    client._last_send_error_code = None
    try:
        reply = client.action(siid=2, aiid=50, parameters=[envelope])
    except Exception as ex:  # noqa: BLE001
        print(f"  ERROR: {ex!r}")
        return None, None, getattr(client, "_last_send_error_code", None)
    err = getattr(client, "_last_send_error_code", None)
    out0_r = _extract_out_r(reply)
    print(
        f"  ← reply: {json.dumps(reply, ensure_ascii=False)[:400]}"
        f"\n  out[0].r={out0_r}  (last_send_error_code={err})"
    )
    return reply, out0_r, err


def _extract_out_r(reply: Any) -> int | None:
    if not isinstance(reply, dict):
        return None
    out = reply.get("out")
    if isinstance(out, list) and out and isinstance(out[0], dict):
        r = out[0].get("r")
        return int(r) if isinstance(r, int) else None
    return None


def interpret(out0_r: int | None, err: int | None) -> str:
    if out0_r == 0:
        return (
            "✓ r=0 — device ACCEPTED the write. Re-read CFG below: if CFG.VER "
            "bumped and PRE reflects the new mode, PRE IS device-writable. "
            "Confirm behaviourally (app / mowing) — cloud r=0 alone isn't device-apply."
        )
    if out0_r == -3:
        return (
            "✗ r=-3 — NO setter registered for t='PRE' on this firmware. This is a "
            "REAL disproof: Mowing Efficiency is not writable via the routed-action "
            "CFG surface (same class as DND/LOW/BAT/… int-list keys). Needs the "
            "app's actual write RPC (HTTPS sniff)."
        )
    if out0_r is not None:
        return f"? r={out0_r} — unexpected non-zero result. Record verbatim; not a clean accept or the known -3 reject."
    if err == 80001 or err is not None:
        return (
            "⚠ 80001 / send-timeout (relay asleep on idle-docked device). INCONCLUSIVE. "
            "Run --relay-check; if findBot also 80001s, re-probe while the mower is "
            "actively connected (e.g. just after an app command, or mid-mow)."
        )
    return "⚠ no result and no error code — inconclusive; re-run --relay-check."


# --- Relay control (findBot op=9) — same disambiguation as probe_cruise ------

def relay_check(client) -> bool:
    print("--- relay control: routed_action op=9 (findBot, harmless beep) ---")
    client._last_send_error_code = None
    reply = client.routed_action(9)
    err = getattr(client, "_last_send_error_code", None)
    alive = reply is not None
    print(f"  ← result: {json.dumps(reply, ensure_ascii=False)[:200]}  (last_send_error_code={err})")
    print(
        "  relay ALIVE — a PRE r=-3/r=0 below is a genuine device verdict."
        if alive else
        "  relay ASLEEP/UNREACHABLE (findBot 80001'd too) — any PRE 80001 below is "
        "INCONCLUSIVE. Re-probe while the mower is actively connected."
    )
    return alive


# --- Probe / set drivers -----------------------------------------------------

def _flip_mode(pre: list) -> int:
    cur = int(pre[1]) if len(pre) >= 2 else 0
    return 0 if cur == 1 else 1


def probe_writability(client, shapes: list[str], pause_s: float, restore: bool) -> None:
    """For each shape: read PRE, send a flipped 2-element value, read back,
    then (optionally) restore the original. Stops at first r=0."""
    alive = relay_check(client)
    print()
    cfg = read_cfg(client)
    orig_pre, orig_ver = show_pre(cfg, "PRE (before)")
    if orig_pre is None or len(orig_pre) < 2:
        raise SystemExit("CFG.PRE is missing or shorter than 2 elements — cannot probe.")

    zone_id = int(orig_pre[0])
    new_mode = _flip_mode(orig_pre)
    new_pre = [zone_id, new_mode]  # correct g2408 2-element shape
    print(f"\nWill flip mode {orig_pre[1]} → {new_mode} (2-element shape [{zone_id}, {new_mode}]).\n")

    accepted_shape: str | None = None
    for shape_name in shapes:
        print("=" * 68)
        reply, out0_r, err = send_pre(client, shape_name, new_pre)
        print("  " + interpret(out0_r, err))
        if out0_r == 0:
            time.sleep(1.5)
            after = read_cfg(client)
            after_pre, after_ver = show_pre(after, "PRE (after write)")
            ver_bumped = (
                isinstance(orig_ver, int) and isinstance(after_ver, int) and after_ver > orig_ver
            )
            pre_changed = after_pre is not None and len(after_pre) >= 2 and int(after_pre[1]) == new_mode
            print(
                f"  CFG.VER {orig_ver} → {after_ver}  ({'BUMPED' if ver_bumped else 'unchanged'});"
                f"  PRE[1] now {'reflects' if pre_changed else 'does NOT reflect'} the new mode."
            )
            if ver_bumped and pre_changed:
                print(
                    "\n  ★ STRONG cloud-accept signal: r=0 + VER bump + PRE reflects the write. "
                    "Now do the BEHAVIOURAL check (Dreame app / mowing) to confirm device-apply."
                )
            accepted_shape = shape_name
            break
        if pause_s > 0:
            time.sleep(pause_s)

    if accepted_shape is None:
        print("\n" + "=" * 68)
        verdict = "no shape accepted"
        if not alive:
            print(
                "✗ No PRE shape accepted — BUT findBot 80001'd too, so the relay was "
                "asleep. INCONCLUSIVE. Re-run while the mower is actively connected."
            )
        else:
            print(
                "✗ No PRE shape accepted and the relay was ALIVE — strong evidence "
                "PRE has no routed-action setter on this firmware (r=-3 class). "
                "Record as the real disproof; next lead is the app HTTPS sniff."
            )
        _ = verdict
        return

    # Restore (non-destructive probe). Only needed if we actually changed it.
    if restore:
        print("\n--- restoring original PRE ---")
        reply, out0_r, err = send_pre(client, accepted_shape, list(orig_pre))
        if out0_r == 0:
            print(f"  ✓ restored PRE to {orig_pre}.")
        else:
            print(
                f"  ⚠ restore returned out[0].r={out0_r}. PRE may be left at mode "
                f"{new_mode}. Re-run with --set {orig_pre[1]} to force it back."
            )
    else:
        print(
            f"\n--restore not requested: PRE left at mode {new_mode}. This is the "
            "behavioural-test state — check the app/mowing now. Re-run "
            f"--set {orig_pre[1]} to revert."
        )


def set_mode(client, mode: int, shape_name: str) -> None:
    """Intentionally set efficiency to `mode` and LEAVE it (behavioural test)."""
    if mode not in (0, 1):
        raise SystemExit("--set takes 0 (Standard) or 1 (Efficient).")
    relay_check(client)
    print()
    cfg = read_cfg(client)
    orig_pre, orig_ver = show_pre(cfg, "PRE (before)")
    if orig_pre is None or len(orig_pre) < 2:
        raise SystemExit("CFG.PRE missing/short — cannot set.")
    new_pre = [int(orig_pre[0]), mode]
    print(f"\nSetting mode → {mode} ({'Efficient' if mode else 'Standard'}) via shape={shape_name!r}.\n")
    print("=" * 68)
    reply, out0_r, err = send_pre(client, shape_name, new_pre)
    print("  " + interpret(out0_r, err))
    if out0_r == 0:
        time.sleep(1.5)
        after = read_cfg(client)
        _after_pre, after_ver = show_pre(after, "PRE (after)")
        print(f"  CFG.VER {orig_ver} → {after_ver}.")
        print(
            "\nLeft at the new value. CONFIRM device-apply behaviourally: open the "
            "Dreame app (cold-start a fresh instance for the strongest test) and check "
            "Mowing Efficiency reflects it; or watch mowing behaviour. That is the "
            "decisive proof — cloud r=0 only means the cloud accepted it."
        )


# --- Main --------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--read", action="store_true",
                   help="Read and print current CFG.PRE + CFG.VER, then exit.")
    p.add_argument("--relay-check", action="store_true",
                   help="Fire findBot (op=9, harmless beep) to report whether the "
                        "cloud relay is awake. Exits.")
    p.add_argument("--probe", action="store_true",
                   help="Flip mode via the routed-action PRE write, read out[0].r, "
                        "then restore the original (non-destructive writability test).")
    p.add_argument("--auto", action="store_true",
                   help="With --probe: try every shape (wrapped, bare, named) until "
                        "one returns r=0. Default tries 'wrapped' only.")
    p.add_argument("--shape", choices=sorted(SHAPES), default="wrapped",
                   help="Shape for --probe (single) / --set. Default: wrapped "
                        "(the proven-good CFG envelope d={value:…}).")
    p.add_argument("--set", type=int, metavar="MODE", default=None,
                   help="Set efficiency to MODE (0=Standard, 1=Efficient) and LEAVE "
                        "it for the behavioural test. Mutually exclusive with --probe.")
    p.add_argument("--no-restore", action="store_true",
                   help="With --probe: do NOT restore the original PRE (leave flipped "
                        "for behavioural inspection).")
    p.add_argument("--pause-between-shapes", type=float, default=2.0,
                   help="Seconds between shapes in --probe --auto mode (default 2).")
    p.add_argument("--credentials", default=DEFAULT_CREDS_PATH,
                   help=f"Credentials file (email/pass/country, one per line). "
                        f"Default: {DEFAULT_CREDS_PATH}")
    add_to_parser(p, TOOL_META)
    args = p.parse_args()

    client = _build_cloud_client(args.credentials)

    if args.read:
        show_pre(read_cfg(client), "PRE")
        return 0

    if args.relay_check:
        relay_check(client)
        return 0

    if args.set is not None:
        if args.probe:
            p.error("--set and --probe are mutually exclusive")
        set_mode(client, args.set, args.shape)
        return 0

    if args.probe:
        shapes = AUTO_ORDER if args.auto else [args.shape]
        probe_writability(client, shapes, args.pause_between_shapes,
                           restore=not args.no_restore)
        return 0

    p.error("must specify one of --read, --relay-check, --probe, or --set MODE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
