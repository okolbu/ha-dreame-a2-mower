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
# slug. Distinct from the app catalog: the catalog covers the full apk
# FaultIndex + community remaps, while this table maps s2p2 values to the
# stable HA event_type slugs fired by
# `event.dreame_a2_mower_notification`.
#
# This is the pure, layer-2 module so external dev tools (mower_tail.py,
# probe_a2_mqtt.py) can import it WITHOUT pulling homeassistant via the
# coordinator package's __init__. The user-visible text per fire comes from
# the catalog (see fault_catalog.fault_text) / cloud notification payload
# (coordinator/_notifications.py) — slugs only here.
#
# Source: docs/research/app-notification-history-2026-05-16.md § Empirical s2p2 mapping.
S2P2_EVENT_TYPES: dict[int, str] = {
    0:   "hanging",
    2:   "robot_trapped",                   # verified 2026-05-30 (stuck on hose; user-confirmed app text)
    4:   "left_wheel_error",                # verified 2026-05-30 (left wheel spinning on a ledge)
    5:   "right_wheel_error",               # verified 2026-06-01 (wire s2p2=5 + user-confirmed app text "Right drive wheel error")
    23:  "emergency_stop",
    27:  "human_detected",
    28:  "blades_worn",                     # cloud-verified 2026-05-26
    30:  "maintenance_reminder",            # cloud-verified 2026-05-26
    31:  "positioning_failed_stuck",
    33:  "positioning_failed_transient",
    36:  "failed_to_start_task",            # cloud-verified 2026-05-26
    43:  "battery_temp_low_charging_paused",
    47:  "task_cancelled",                  # mova [MOWER] community-confirmed
    48:  "mowing_complete",                 # cloud-verified 2026-05-26
    50:  "mowing_started",                  # cloud-verified 2026-05-26
    51:  "patrol_started",                  # verified 2026-05-30; was vacuum "Filter blocked" (g2408 has no filter)
    53:  "scheduled_mowing_started",
    54:  "low_battery_return",
    56:  "rain_protection",                 # cloud-verified 2026-05-26
    63:  "schedule_cancelled_busy",         # cloud-verified 2026-05-26
    70:  "continue_unfinished_task",        # cloud-verified 2026-05-26
    71:  "standby_outside_station_too_long",  # verified 2026-05-30 (was "positioning_failure"; apk label wrong on g2408)
    72:  "paused_too_long_returning",       # cloud-labelled 2026-06-17 ("Task paused for too long. Automatically returning to the station to wait."); was borrowed slug return_after_pause_timeout
    73:  "top_cover_open",
    74:  "patrol_ended",                    # verified 2026-05-30 (patrol cancelled → return to dock)
    75:  "arrived_at_maintenance_point",
    76:  "cannot_reach_maintenance_point",  # user-confirmed app text 2026-05-30
}

# Slug fired when s2p2 carries a value not in S2P2_EVENT_TYPES — the cloud
# still provides authoritative text in the event payload; the slug is generic
# so HA can register the event_type up-front.
S2P2_UNKNOWN_EVENT_TYPE = "unknown_s2p2"

# ---------------------------------------------------------------------------
# Fault partition — which s2p2 codes are genuine, user-actionable FAULTS.
#
# s2p2 is a single multiplexed slot: the same wire field carries "mowing
# started" (50), "rain protection" (56), and "right drive wheel error" (5).
# MowerState.error_code is just the last raw value, so it cannot represent
# "is there an active fault?". This set is the single source of truth.
#
# Membership = codes that are BOTH (a) wire/cloud-VERIFIED on g2408 (present
# in inventory.yaml § s2p2 verified Faults list) AND (b) require the user to
# intervene to get the mower going again. Intentionally a SMALL, high-
# confidence set.
#
# Deliberately EXCLUDED:
#   - 24 Battery low, 43 Battery temp low → lifecycle/environmental.
#   - 33 Positioning/relocate failed → surfaced via positioning_health=STUCK
#     + binary_sensor.positioning_failed (owned there); often auto-recovers.
#   - 76 Cannot reach maintenance point → mower auto-returns home (s2p1→5);
#     no intervention (contrast 31, which strands the mower mid-lawn).
#   - tilt(1)/lift(9)/bumper → live on the s1p1 HEARTBEAT (binary_sensors +
#     snapshot.pin_required), NOT s2p2. The terminal "can't continue" state
#     is s2p2=23 (PIN lockout), which IS included.
#   - 37/38/39/40/41/44/45/46/49/57/58/59/61/62/64/65/66/67/78/117 →
#     apk/vacuum-lineage codes; ZERO probe-corpus occurrences on g2408;
#     removed from ERROR_CODE_DESCRIPTIONS (2026-06-01). They fall back to
#     "Unknown error N". Latching the lawn_mower entity to ERROR on a guessed
#     vacuum semantic violates fact-discipline. Add here ONLY once confirmed.
FAULT_CODES: frozenset[int] = frozenset({
    2,    # Robot trapped (verified 2026-05-30)
    4,    # Left drive wheel error (verified 2026-05-30)
    5,    # Right drive wheel error (verified 2026-06-01)
    23,   # Lift lockout — PIN required on device (emergency stop terminal)
    31,   # Failed to return to station (stranded — user must recharge)
    36,   # Failed to start the task — retry (cloud-verified 2026-05-26)
})


def is_fault(code: int | None) -> bool:
    """True only for genuine, user-actionable s2p2 fault codes.

    None (no code) and unmapped/unknown codes return False — an unknown
    code is surfaced via the notification event + [NOVEL] log, not latched
    as a fault, until its semantics are confirmed and added to FAULT_CODES.
    """
    return code is not None and code in FAULT_CODES
