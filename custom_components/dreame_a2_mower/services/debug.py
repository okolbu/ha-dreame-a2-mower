"""Debug / discovery service tooling (refactor-v2 P3.8, autopsy #5/T2-11).

The dev-only diagnostic services — ``dump_map_diagnostics`` and
``discover_cloud_api`` — plus their pure summariser helpers, isolated out of the
production ``services`` module. These are gated behind the ``debug_services``
config option (``services/__init__.py`` only registers them when
``_debug_services_enabled`` is true); this module is the natural experimental-gate
seam. The GATE mechanism itself is P4 — here the tooling is merely SEPARATED so
the production service surface no longer carries ~250 LOC of dev machinery.

The handler bodies are plain ``async def _(coordinator, call)`` functions (the
``@service_handler`` coordinator-resolution wrapper is applied in
``services/__init__.py`` where ``service_handler`` lives), so this module has no
import edge back into the package ``__init__`` — no circular import.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import ServiceCall

    from ..coordinator import DreameA2MowerCoordinator


async def dump_map_diagnostics(
    coordinator: "DreameA2MowerCoordinator", call: "ServiceCall"
) -> None:
    """One-off diagnostic: dump raw cloud map-batch responses to the
    HA log so we can see what data the cloud is actually returning.
    Triggered by `service: dreame_a2_mower.dump_map_diagnostics`.
    """
    hass = call.hass
    if not hasattr(coordinator, "_cloud") or coordinator._cloud is None:
        LOGGER.warning("dump_map_diagnostics: no coordinator/cloud client ready")
        return
    cloud = coordinator._cloud

    # 1. MAP.* + MAP.info batch (the live fetch_map endpoint)
    try:
        batch = await hass.async_add_executor_job(
            cloud.get_batch_device_datas,
            [f"MAP.{i}" for i in range(28)] + ["MAP.info"],
        )
    except Exception as ex:
        LOGGER.warning("dump_map_diagnostics: MAP.* batch raised: %s", ex)
        batch = None
    LOGGER.warning(
        "dump_map_diagnostics: MAP.* batch keys=%s, MAP.info=%r, "
        "non-empty MAP.x slots=%d",
        sorted((batch or {}).keys()),
        (batch or {}).get("MAP.info"),
        sum(1 for k, v in (batch or {}).items() if k.startswith("MAP.") and k != "MAP.info" and v),
    )

    # 2. Re-parse and dump per-map top-level keys
    try:
        parsed = await hass.async_add_executor_job(cloud.fetch_map)
    except Exception as ex:
        LOGGER.warning("dump_map_diagnostics: fetch_map raised: %s", ex)
        parsed = None
    if parsed is None:
        LOGGER.warning("dump_map_diagnostics: fetch_map returned None")
    else:
        for map_id, raw in sorted(parsed.items()):
            keys = sorted(raw.keys())
            paths_val = raw.get("paths")
            LOGGER.warning(
                "dump_map_diagnostics: map_id=%s keys=%s, paths=%r",
                map_id, keys,
                paths_val if isinstance(paths_val, dict) else type(paths_val).__name__,
            )

    # 3. Try a list of plausible alternative batch names
    for prefix in ("M_PATH", "PATH", "NAV", "LINK", "MPATH"):
        try:
            other = await hass.async_add_executor_job(
                cloud.get_batch_device_datas,
                [f"{prefix}.{i}" for i in range(28)] + [f"{prefix}.info"],
            )
        except Exception as ex:
            LOGGER.warning("dump_map_diagnostics: %s.* batch raised: %s", prefix, ex)
            continue
        non_empty = sum(1 for k, v in (other or {}).items() if v)
        LOGGER.warning(
            "dump_map_diagnostics: %s.* batch — keys returned=%d, non-empty=%d, sample=%r",
            prefix, len(other or {}), non_empty,
            next(((k, str(v)[:200]) for k, v in (other or {}).items() if v), None),
        )

    LOGGER.warning("dump_map_diagnostics: done")


# ---------------------------------------------------------------------------
# discover_cloud_api — helpers
# ---------------------------------------------------------------------------

def _group_keys_by_prefix(batch: dict[str, Any]) -> dict[str, list[str]]:
    """Group keys by their dot-prefix.

    'MAP.0' / 'MAP.1' / 'MAP.info' -> {'MAP': ['MAP.0', 'MAP.1', 'MAP.info']}
    'prop.s_auth_config' -> {'prop': ['prop.s_auth_config']}
    'standalone_key' -> {'standalone_key': ['standalone_key']}
    """
    out: dict[str, list[str]] = {}
    for k in sorted(batch.keys()):
        prefix = k.split(".", 1)[0]
        out.setdefault(prefix, []).append(k)
    return out


def _summarise_value(value: Any, depth: int = 2) -> Any:
    """Recursively summarise a JSON value: types + keys + lengths +
    sample. Capped at `depth` levels to keep output bounded."""
    if depth <= 0:
        return {"type": type(value).__name__, "_truncated": True}
    if isinstance(value, dict):
        return {
            "type": "dict",
            "key_count": len(value),
            "keys": sorted(value.keys()) if all(isinstance(k, str) for k in value) else list(value.keys())[:20],
            "by_key": {
                k: _summarise_value(v, depth - 1)
                for k, v in list(value.items())[:20]
            },
        }
    if isinstance(value, list):
        return {
            "type": "list",
            "length": len(value),
            "first_element": _summarise_value(value[0], depth - 1) if value else None,
        }
    if isinstance(value, (str, int, float, bool, type(None))):
        return {"type": type(value).__name__, "value_preview": repr(value)[:200]}
    return {"type": type(value).__name__, "value_preview": repr(value)[:200]}


def _summarise_family(
    prefix: str,
    keys: list[str],
    batch: dict[str, Any],
) -> dict[str, Any]:
    """Summarise one prefix family. If chunked (PREFIX.0..N + PREFIX.info),
    reassemble and JSON-decode; otherwise return per-key types."""
    import json as _json

    out: dict[str, Any] = {"key_count": len(keys), "keys": keys}
    chunked_keys = sorted(
        [k for k in keys if k.startswith(f"{prefix}.") and k != f"{prefix}.info"
         and k.split(".", 1)[1].isdigit()],
        key=lambda k: int(k.split(".", 1)[1]),
    )
    info_key = f"{prefix}.info"
    if not chunked_keys:
        # Standalone keys (no chunking) — record raw types per key.
        per_key: dict[str, Any] = {}
        for k in keys:
            v = batch.get(k)
            per_key[k] = {"type": type(v).__name__, "value_preview": repr(v)[:200]}
        out["per_key"] = per_key
        return out

    parts = [batch.get(k, "") or "" for k in chunked_keys]
    joined = "".join(parts)
    out["joined_length"] = len(joined)
    out["info"] = batch.get(info_key)

    # Try to JSON-decode (with optional split via .info)
    segments = [joined]
    info_raw = batch.get(info_key)
    if isinstance(info_raw, str) and info_raw.isdigit():
        split_pos = int(info_raw)
        if 0 < split_pos < len(joined):
            segments = [joined[:split_pos], joined[split_pos:]]
    parsed_segments: list[Any] = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        try:
            parsed_segments.append(_json.loads(seg))
        except Exception:
            # Save first 200 chars as preview if JSON fails
            parsed_segments.append({"_decode_failed": seg[:200]})
    # If single segment, unwrap; if multiple, keep as list.
    structure = parsed_segments[0] if len(parsed_segments) == 1 else parsed_segments
    out["structure"] = _summarise_value(structure, depth=3)
    return out


async def discover_cloud_api(
    coord: "DreameA2MowerCoordinator", call: "ServiceCall"
) -> None:
    """Recursively dump the device's cloud API surface to
    <config>/dreame_a2_mower/api_discovery.json. Triggered via the
    service `dreame_a2_mower.discover_cloud_api`. No parameters.

    Discovers chunked-data families (PREFIX.0..N + PREFIX.info) by
    grouping keys returned from get_batch_device_datas([]).  Probes
    cfg_individual endpoints from the integration's catalog. Walks
    the resulting JSON to record types/keys at every path. Output
    is structured for human inspection rather than raw dump.
    """
    import json as _json
    import os

    hass = call.hass
    if not hasattr(coord, "_cloud") or coord._cloud is None:
        LOGGER.warning("discover_cloud_api: no coordinator/cloud client ready")
        return
    cloud = coord._cloud

    report: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "device": {
            "fw": getattr(cloud, "_firmware_version", None),
            "model": getattr(cloud, "_model", None),
            "did": getattr(cloud, "_did", None),
        },
        "batch_keys": {},
        "cfg_individual": {},
    }

    # 1. Empty-list batch fetch — returns the cloud's full key set.
    try:
        batch = await hass.async_add_executor_job(cloud.get_batch_device_datas, [])
    except Exception as ex:
        LOGGER.warning("discover_cloud_api: empty-list batch raised: %s", ex)
        batch = {}

    # 2. Group keys by prefix.
    families = _group_keys_by_prefix(batch or {})
    LOGGER.info(
        "discover_cloud_api: discovered %d families: %s",
        len(families), sorted(families.keys()),
    )

    # 3. For each family, attempt chunk reassembly + JSON decode + walk.
    for prefix, keys in families.items():
        report["batch_keys"][prefix] = _summarise_family(prefix, keys, batch)

    # 4. Probe cfg_individual catalog.
    try:
        from ..protocol.cfg_action import _GET_ENDPOINT_CATALOGUE
    except Exception:
        _GET_ENDPOINT_CATALOGUE = []
    for key in _GET_ENDPOINT_CATALOGUE:
        try:
            from ..protocol.cfg_action import probe_get
            raw = await hass.async_add_executor_job(probe_get, cloud.action, key)
        except Exception as ex:
            report["cfg_individual"][key] = {"_error": str(ex)[:200]}
            continue
        report["cfg_individual"][key] = _summarise_value(raw, depth=2)

    # 5. Write report.
    config_dir = hass.config.path(DOMAIN)
    try:
        os.makedirs(config_dir, exist_ok=True)
    except Exception:
        pass
    out_path = hass.config.path(DOMAIN, "api_discovery.json")
    try:
        await hass.async_add_executor_job(
            lambda: open(out_path, "w").write(_json.dumps(report, indent=2, default=str))
        )
    except Exception as ex:
        LOGGER.warning("discover_cloud_api: write to %s failed: %s", out_path, ex)
        return
    LOGGER.warning(
        "discover_cloud_api: wrote %s — %d batch families, %d cfg keys probed",
        out_path, len(report["batch_keys"]), len(report["cfg_individual"]),
    )
