"""Shared bootstrap for standalone probes in tools/probes/.

Provides:
  connect(creds_path=DEFAULT_CREDS_PATH) -> DreameA2CloudClient
    Returns a logged-in client selected onto the g2408.

Module-level side effects (run on first import):
  1. Stubs all ``homeassistant.*`` and ``voluptuous`` modules so the cloud_client
     package can be imported without a real HA install.
  2. Adds the repo root to sys.path so ``from custom_components.…`` bare-module
     imports resolve (e.g. ``photo_keys.py``, which has no HA deps).
  3. Loads ``dreame_a2_mower.cloud_client`` (and its transitive deps) via
     ``importlib.util.spec_from_file_location`` — mirrors probe_pre_write.py.

Credentials (same as probe_pre_write.py / probe_cruise_to_point.py):
  DREAME_USER / DREAME_PASS / DREAME_COUNTRY env vars   — highest priority
  server-credentials.txt (email line1, password line2, country line3 opt.)  — fallback
  --credentials <path> argument                          — override via connect()
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Step 1 — stub homeassistant so cloud_client relative imports don't break
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Step 2 — add repo root to sys.path so `from custom_components.…` resolves
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INTEG_ROOT = str(_REPO_ROOT / "custom_components" / "dreame_a2_mower")

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Step 3 — load the cloud_client package via spec_from_file_location
#           (mirrors probe_pre_write.py exactly)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Credentials helper (mirrors probe_pre_write.py / probe_cruise_to_point.py)
# ---------------------------------------------------------------------------

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
    lines = [ln.strip() for ln in creds_file.read_text().splitlines() if ln.strip()]
    if len(lines) < 2:
        raise SystemExit(f"{creds_file}: need email on line 1, password on line 2")
    return {
        "username": lines[0],
        "password": lines[1],
        "country": lines[2] if len(lines) >= 3 else country,
    }


def connect(creds_path: str = DEFAULT_CREDS_PATH) -> DreameA2CloudClient:
    """Return a logged-in DreameA2CloudClient selected onto the g2408.

    Raises SystemExit on credential-load or login failure (safe for probe scripts).
    """
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
