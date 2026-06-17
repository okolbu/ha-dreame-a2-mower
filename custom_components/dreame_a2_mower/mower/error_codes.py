"""Mower error code → human description map.

Source: ``docs/research/g2408-protocol.md`` §2.1 row ``s2.2``.

The s2.2 push on g2408 carries an error code per the apk fault index
(originally reverse-engineered from the Dreame Smart Life app's
decompiled APK; cross-validated against live captures during P1+P2).

Some s2.2 values that arrive on g2408 are actually phase / mode codes
that the apk does not classify as faults (e.g., 56 = rain protection,
71 = standby-outside-station-too-long auto-return — NOT the apk's
"positioning failed", which is unconfirmed on g2408). These are routed
to dedicated binary_sensor entities in F2; the error-code description
map here only covers genuine faults.

Codes documented but not in this map yield a fallback "Unknown error N"
description. The coordinator emits a [NOVEL/error_code] warning when
it sees a code not in this table.
"""
from __future__ import annotations

# Confirmed entries from docs/research/g2408-protocol.md §2.1 plus
# names lifted from legacy DreameMowerErrorCode enum (originally apk-
# decompiled). Some codes are status / phase indicators rather than
# faults — the integration still surfaces them via the "Error code"
# entity for visibility, but the description signals the non-fault
# nature where applicable.
ERROR_CODE_DESCRIPTIONS: dict[int, str] = {
    # 2026-04-30 19:37:13 controlled test: s2p2 1→0 co-fired with the HB bumper
    # bit — previously mislabelled "No error / OK" (apk vacuum-derived label
    # that doesn't apply to g2408). See inventory.yaml § state_codes s2p2_0.
    0: "Bumper / hanging (s2p2 echo of the s1p1 bumper bit)",
    # Confirmed 2026-04-30 against app notifications during a deliberate
    # tilt / lift / lift-lockout test (g2408-protocol §3.4 byte[1..3]).
    1: "Robot tilted (drop sensor)",
    # 2 / 4 user-confirmed app text 2026-05-30 during a stuck patrol (partial —
    # single observation each; apk had these unmapped/vacuum-derived). inventory § s2p2.
    2: "Robot trapped",
    4: "Left drive wheel error",
    # 5: first wire occurrence 2026-06-01 (probe_log_20260520) + user-confirmed
    # app text "Right drive wheel error" — the symmetric sibling of 4. inventory § s2p2.
    5: "Right drive wheel error",
    9: "Robot lifted",
    23: "Lift lockout — PIN required on device (event slug: emergency_stop)",
    24: "Battery low",
    27: "Human detected",
    # 28 = blade-wear notification (cloud-verified 2026-05-26 device-messages/v2
    # maps 28 → "Blades are severely worn. Replace them soon."; corpus-confirmed
    # 2026-05-30, inventory § s2p2). The cloud PUSHES it only when wear% justifies
    # (server-side gate); the integration relays the cloud push and never keys
    # blades-worn off a raw s2p2=28 transition. NB: the earlier "off-dock relocate
    # marker, fires 14/14 on every undock" reading was DEBUNKED by full-corpus
    # analysis — 28 only fired in the 2026-05-15..05-25 worn-blade window, and
    # 29/32 of all 28 events fire while docked (charging), not during an undock.
    28: "Blades severely worn — replace them soon (cloud wear%-gated push)",
    # 30: cloud-verified 2026-05-26 "Robot maintenance time reached. Maintain the
    # robot soon." Fires at task-start (same second as 50) when robot-maintenance%
    # is low; cloud gates the push on wear%.
    30: "Maintenance reminder — maintain robot soon (not an error)",
    # 2026-05-05: two distinct paths into 31 — 33→31 (documented "task
    # errored out, now idle" pair after positioning fail / task-start
    # fail) and 48→31 direct (post-edge-mow auto-dock planner could not
    # route home from a stuck pose). Both surface the Dreame app's
    # "Failed to return to station" notification. See g2408-protocol.md
    # §4.1 row 31 + §4.6.1 for the wheel-bind chain.
    31: "Failed to return to station",
    # 36: cloud-verified 2026-05-26 "Failed to start the task. Please retry."
    36: "Failed to start the task — retry",
    # 43: apk FaultIndex "RTC clock error" is vacuum-derived + unconfirmed on
    # g2408; the event table fires `battery_temp_low_charging_paused`. Neither
    # is cloud-pinned — resolve on next capture. inventory § s2p2.
    43: "RTC clock error? (unconfirmed; event slug: battery temp low, charging paused)",
    47: "Scheduled task cancelled (not an error)",
    48: "Mowing complete (not an error)",
    50: "Mowing task started (not an error)",  # cloud-verified 2026-05-26
    51: "Patrol started (not an error)",  # verified 2026-05-30; was vacuum "Filter blocked" (g2408 has no filter)
    53: "Session starting (scheduled — not an error)",
    54: "Low battery — returning to station",  # S2P2_EVENT_TYPES low_battery_return; was vacuum "Edge fault"
    56: "Bad weather (rain protection active)",
    63: "Scheduled task cancelled — robot working (not an error)",  # cloud-verified 2026-05-26; was vacuum "Blocked"
    # 70: cloud-verified 2026-05-26 "Robot will continue the unfinished task."
    70: "Robot will continue the unfinished task (not an error)",
    # 71: apk says "Positioning failed (SLAM relocation needed)" but that is
    # UNCONFIRMED on g2408 and contradicted by live data — corpus 5/5 occurrences
    # are return-to-dock, and the 2026-05-30 app text was "The robot is on standby
    # outside the station for too long. Automatically returning to the station."
    # (inventory § s2p2). NB binary_sensor.positioning_failed + S2P2_EVENT_TYPES[71]
    # still carry the old label — see TODO "Fix s2p2=71 mislabel".
    71: "Standby outside station too long — auto-returning (apk 'positioning failed' unconfirmed on g2408)",
    # 72: wire-confirmed 2026-06-17 — a PAUSED mower (~1h) auto-returns. inventory § s2p2.
    72: "Returning to dock after pause timeout",
    73: "Top cover open",
    # 74: observed 2026-05-30 when a patrol was user-cancelled → return to dock
    # (fired with s2p1→2). Partial — single observation. inventory § s2p2.
    74: "Patrol ended / cancelled",
    # 75: apk "Low battery turn-off" is vacuum-derived + unconfirmed; the event
    # table fires `arrived_at_maintenance_point`. Conflict unresolved — next
    # capture. inventory § s2p2.
    75: "Low battery turn-off? (unconfirmed; event slug: arrived at maintenance point)",
    # 76: user-confirmed app text 2026-05-30 "Cannot reach the maintenance point.
    # Task ended." Fires at give-up; followed by s2p1→5 (auto-return). inventory § s2p2.
    76: "Cannot reach the maintenance point — task ended",
}


def describe_error(code: int) -> str:
    """Return a human-readable description for the given error code.

    Returns a fallback string for unknown codes — the caller is
    responsible for emitting a [NOVEL/error_code] warning.
    """
    if code in ERROR_CODE_DESCRIPTIONS:
        return ERROR_CODE_DESCRIPTIONS[code]
    return f"Unknown error {code}"


# ---------------------------------------------------------------------------
# s2p2 notification SLUG table — keyed off s2p2 value, value = HA event_type
# slug. Distinct from ERROR_CODE_DESCRIPTIONS above: the description table is
# a fault catalogue (apk FaultIndex + community remaps), while this table maps
# s2p2 values to the stable HA event_type slugs fired by
# `event.dreame_a2_mower_notification`.
#
# This is the pure, layer-2 module so external dev tools (mower_tail.py,
# probe_a2_mqtt.py) can import it WITHOUT pulling homeassistant via the
# coordinator package's __init__. The user-visible text per fire comes from
# the cloud (see coordinator/_notifications.py) — slugs only here.
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
    72:  "return_after_pause_timeout",      # wire-confirmed 2026-06-17 (paused ~1h -> auto-return; from s2p1=3 or 4)
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
