"""Pure access API for the bundled g2408 fault/notification catalog.

Loads mower/data/fault_catalog.json once and exposes per-code lookups by
channel ("iot" = s2p2, "heartbeat" = s1p1) and language. No HA imports.
Source: the app plugin extract [apk:g2408-plugin-ext1423]; see
tools/inventory/gen_fault_catalog.py.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "fault_catalog.json"

SUPPORTED_LANGS: frozenset[str] = frozenset({
    "zh", "en", "de", "fr", "it", "es", "pt", "nl", "da", "sv", "fi",
    "pl", "nb", "ru", "tr", "lt", "cs", "lv", "sk", "hu", "ro",
})

_DISPLAY_FIELDS = ("alert", "popup", "resident")


@lru_cache(maxsize=1)
def _catalog() -> dict:
    try:
        return json.loads(_DATA.read_text(encoding="utf-8"))
    except Exception:
        return {"iot": {}, "heartbeat": {}}


def _entry(code: int, channel: str) -> dict | None:
    try:
        return (_catalog().get(channel) or {}).get(str(int(code)))
    except (TypeError, ValueError):
        return None


def resolve_lang(ha_lang: str | None) -> str:
    """Map a HA language to a catalog lang (region-stripped), else 'en'."""
    if not ha_lang:
        return "en"
    lg = str(ha_lang).lower()
    if lg in SUPPORTED_LANGS:
        return lg
    base = lg.split("-")[0]
    return base if base in SUPPORTED_LANGS else "en"


def _field(code: int, lang: str, channel: str, key: str) -> str | None:
    e = _entry(code, channel)
    if e is None:
        return None
    langs = e.get("lang") or {}
    for src in (lang, "en"):
        val = (langs.get(src) or {}).get(key)
        if val:
            return val
    return None


def fault_text(code: int, lang: str = "en", channel: str = "iot") -> str | None:
    """The display string: first-non-empty(alert, popup, resident), lang then en."""
    e = _entry(code, channel)
    if e is None:
        return None
    langs = e.get("lang") or {}
    for src in (lang, "en"):
        f = langs.get(src) or {}
        for k in _DISPLAY_FIELDS:
            if f.get(k):
                return f[k]
    return None


def fault_detail(code: int, lang: str = "en", channel: str = "iot") -> str | None:
    return _field(code, lang, channel, "detail")


def fault_detail_title(code: int, lang: str = "en", channel: str = "iot") -> str | None:
    return _field(code, lang, channel, "detail_title")


def fault_name(code: int, channel: str = "iot") -> str | None:
    e = _entry(code, channel)
    return e.get("fault_name") if e else None


def fault_category(code: int, channel: str = "iot") -> str | None:
    e = _entry(code, channel)
    return e.get("category") if e else None


def fault_severity(code: int, channel: str = "iot") -> str | None:
    e = _entry(code, channel)
    return e.get("severity") if e else None


def can_suppress(code: int, channel: str = "iot") -> bool:
    e = _entry(code, channel)
    return bool(e.get("can_suppress")) if e else False


def known_codes(channel: str = "iot") -> frozenset[int]:
    out: set[int] = set()
    for k in (_catalog().get(channel) or {}):
        try:
            out.add(int(k))
        except (TypeError, ValueError):
            continue
    return frozenset(out)


def fault_tier(code: int, channel: str = "iot") -> str | None:
    """App-derived surfacing tier for a code, or None if unknown. Tier names
    track the app vocabulary (alert/info = category words; error/attention =
    the FAULT category split by severity).

      error     = FAULT + (anomaly|malfunction)     — mower can't continue / needs help
      attention = FAULT + (work_message|consumable) — attention, not broken
      alert     = ALERT (any severity)              — recoverable operation failure
      info      = INFO  (any severity)              — lifecycle/status
    """
    cat = fault_category(code, channel)
    if cat is None:
        return None
    sev = fault_severity(code, channel)
    if cat == "FAULT":
        return "error" if sev in ("anomaly", "malfunction") else "attention"
    if cat == "ALERT":
        return "alert"
    if cat == "INFO":
        return "info"
    return None


def error_tier_codes(channel: str = "iot") -> frozenset[int]:
    """The codes whose tier is 'error' (the HA error-latch set)."""
    return frozenset(
        c for c in known_codes(channel) if fault_tier(c, channel) == "error"
    )
