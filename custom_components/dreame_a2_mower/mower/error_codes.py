"""Mower error code → human description map.

Source: ``docs/research/g2408-protocol.md`` §2.1 row ``s2.2``.

The s2.2 push on g2408 carries an error code per the apk fault index
(originally reverse-engineered from the Dreame Smart Life app's
decompiled APK; cross-validated against live captures during P1+P2).

Some s2.2 values that arrive on g2408 are actually phase / mode codes
that the apk does not classify as faults (e.g., 56 = rain protection,
71 = standby-outside-station-too-long auto-return — NOT the apk's
"positioning failed", which is unconfirmed on g2408). These are routed
to dedicated binary_sensor entities in F2; describe_error covers all
codes by delegating to the authoritative bundled app catalog.

Codes absent from the catalog yield a fallback "Unknown error N"
description. The coordinator emits a [NOVEL/error_code] warning when
it sees a code not in the catalog.
"""
from __future__ import annotations

from . import fault_catalog


def describe_error(code: int, lang: str = "en") -> str:
    """Authoritative localized fault text for an s2p2 (iot) code, or a fallback.

    Sourced from the bundled app catalog (mower/fault_catalog.py,
    [apk:g2408-plugin-ext1423]). Returns "Unknown error N" for codes absent
    from the catalog (which also surface via the [PROTOCOL_NOVEL] /
    unknown_s2p2 paths). `lang` must be a resolved catalog language — callers
    resolve via fault_catalog.resolve_lang(hass.config.language); defaults to
    English.
    """
    return fault_catalog.fault_text(int(code), lang) or f"Unknown error {code}"


# ---------------------------------------------------------------------------
# s2p2 notification SLUG table — keyed off s2p2 value, value = HA event_type
# slug. DERIVED from the authoritative app catalog fault_name
# [apk:g2408-plugin-ext1423] via fault_catalog.event_slug (strips the
# FAULT_/ALERT_/INFO_ prefix, lowercases), plus _SLUG_SUPPLEMENT for wire codes
# the catalog omits. This is the pure, layer-2 module so external dev tools
# (mower_tail.py, probe_a2_mqtt.py) can import it WITHOUT pulling homeassistant.
# The user-visible text per fire comes from the catalog / cloud payload — slugs
# only here.
#
# NOTE: two FAULT/ALERT variant-pairs intentionally share a slug
# (11/42 -> battery_overheat, 43/59 -> battery_temp_low). The per-fire payload
# carries the distinguishing code + tier. Do NOT reverse-map slug->code.

# Codes observed on the g2408 wire that the app catalog does NOT classify, so
# event_slug() returns None for them and they need an explicit slug here.
_SLUG_SUPPLEMENT: dict[int, str] = {
    47: "task_cancelled",  # mova [MOWER] community-confirmed; absent from the catalog
}


def _derive_iot_slugs() -> dict[int, str]:
    out: dict[int, str] = {}
    for c in sorted(fault_catalog.known_codes("iot")):
        slug = fault_catalog.event_slug(c)
        if slug:
            out[c] = slug
    out.update(_SLUG_SUPPLEMENT)
    return out


S2P2_EVENT_TYPES: dict[int, str] = _derive_iot_slugs()

# Slug fired when s2p2 carries a value not in S2P2_EVENT_TYPES — the cloud still
# provides authoritative text in the payload; the slug is generic so HA can
# register the event_type up-front.
S2P2_UNKNOWN_EVENT_TYPE = "unknown_s2p2"

# The event_types advertised by event.dreame_a2_mower_notification: the unique
# derived slugs (sorted for stability) plus the unknown sentinel. Defined here
# (catalog-authoritative home) and re-exported by const.py.
NOTIFICATION_EVENT_TYPES: tuple[str, ...] = tuple(
    sorted(set(S2P2_EVENT_TYPES.values())) + [S2P2_UNKNOWN_EVENT_TYPE]
)

def is_fault(code: int | None) -> bool:
    """True if a code is the app's 'error' tier (FAULT + anomaly|malfunction):
    the mower can't continue without intervention. Drives the latched error
    state (lawn_mower ERROR + Error sensor + fault events). Sourced from the
    app catalog [apk:g2408-plugin-ext1423] via fault_tier — no hand-curated
    list. None / unknown codes -> False (surfaced via the notification event +
    [NOVEL] log, not latched)."""
    return code is not None and fault_catalog.fault_tier(int(code)) == "error"
