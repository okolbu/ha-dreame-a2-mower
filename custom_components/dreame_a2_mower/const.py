"""Domain-level constants for the Dreame A2 Mower integration."""
from __future__ import annotations

import logging
from typing import Final

from homeassistant.const import CONF_PASSWORD as CONF_PASSWORD
from homeassistant.const import CONF_USERNAME as CONF_USERNAME

DOMAIN: Final = "dreame_a2_mower"
"""HA domain identifier — kept identical to legacy for config-flow continuity."""

PLATFORMS: Final = [
    "lawn_mower",
    "sensor",
    "binary_sensor",
    "device_tracker",
    "camera",
    "select",
    "number",
    "switch",
    "time",
    "button",
    "event",
    "calendar",
    "update",
]
"""HA platforms this integration sets up. F5 = session lifecycle surface added button."""

# Lifecycle event_types fired on event.dreame_a2_mower_lifecycle.
# See docs/events.md for payload schema.
EVENT_TYPE_MOWING_STARTED: Final = "mowing_started"
EVENT_TYPE_MOWING_PAUSED: Final = "mowing_paused"
EVENT_TYPE_MOWING_RESUMED: Final = "mowing_resumed"
EVENT_TYPE_MOWING_ENDED: Final = "mowing_ended"
EVENT_TYPE_DOCK_ARRIVED: Final = "dock_arrived"
EVENT_TYPE_DOCK_DEPARTED: Final = "dock_departed"
EVENT_TYPE_CHARGING_STARTED: Final = "charging_started"
EVENT_TYPE_CHARGING_COMPLETE: Final = "charging_complete"
EVENT_TYPE_RAIN_DELAY_STARTED: Final = "rain_delay_started"
EVENT_TYPE_FAULT_DETECTED: Final = "fault_detected"
EVENT_TYPE_FAULT_CLEARED: Final = "fault_cleared"
EVENT_TYPE_SELF_SHUTDOWN: Final = "self_shutdown"

LIFECYCLE_EVENT_TYPES: Final[tuple[str, ...]] = (
    EVENT_TYPE_MOWING_STARTED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
    EVENT_TYPE_CHARGING_STARTED,
    EVENT_TYPE_CHARGING_COMPLETE,
    EVENT_TYPE_RAIN_DELAY_STARTED,
    EVENT_TYPE_FAULT_DETECTED,
    EVENT_TYPE_FAULT_CLEARED,
    EVENT_TYPE_SELF_SHUTDOWN,
)

# Slug fired when an s2p2 notification code has no catalog-derived mapping
# (mower/error_codes.py:S2P2_UNKNOWN_EVENT_TYPE). This is a genuine
# foundation-layer constant (a bare string, not derived from the fault
# catalog), so it lives here and `mower/error_codes.py` imports it — the
# INVERSE of the former `const -> mower.error_codes -> mower.fault_catalog`
# back-edge (T2-5/R-30). The catalog-DERIVED slug tables themselves
# (S2P2_EVENT_TYPES, NOTIFICATION_EVENT_TYPES, triggerable_notification_slugs)
# stay in mower/error_codes.py — they need the fault catalog's data and
# cannot be foundation-layer constants. Consumers that need the derived
# tables (event.py, device_trigger.py) import them directly from
# `mower.error_codes`, not through const.
S2P2_UNKNOWN_EVENT_TYPE: Final = "unknown_s2p2"

LOGGER: Final = logging.getLogger(__package__)
"""Module-level logger. Per spec §3, every layer-3 file uses this."""

# Config flow keys
# CONF_USERNAME and CONF_PASSWORD are re-exported from homeassistant.const
# (see import block above). CONF_COUNTRY stays local — it's our cloud-region
# key, not an HA standard constant.
CONF_COUNTRY: Final = "country"

# F7.7.1: archive retention options.
CONF_LIDAR_ARCHIVE_KEEP: Final = "lidar_archive_keep"
CONF_LIDAR_ARCHIVE_MAX_MB: Final = "lidar_archive_max_mb"
CONF_PHOTO_ARCHIVE_KEEP: Final = "photo_archive_keep"
CONF_PHOTO_ARCHIVE_MAX_MB: Final = "photo_archive_max_mb"
CONF_VIDEO_ARCHIVE_KEEP: Final = "video_archive_keep"
CONF_VIDEO_ARCHIVE_MAX_MB: Final = "video_archive_max_mb"
CONF_SESSION_ARCHIVE_KEEP: Final = "session_archive_keep"
CONF_WIFI_ARCHIVE_KEEP: Final = "wifi_archive_keep"
CONF_MESSAGES_KEEP: Final = "messages_keep"

# Debug-services gate (P2 sub-task 2.5). When False (the default), the two
# developer-only diagnostic services — dump_map_diagnostics + discover_cloud_api
# — are NOT registered, so they don't appear in the HA service registry. Flip
# the "Enable debug services" toggle in the integration's options to expose
# them (e.g. for a one-off cloud-API dump). They still ship in services.yaml so
# their descriptions are available when enabled.
CONF_DEBUG_SERVICES: Final = "debug_services"
DEFAULT_DEBUG_SERVICES: Final = False

# Experimental-features opt-in gate (P4 / R-52). ONE config-entry option that
# unifies the former debug_services toggle. When False (the default),
# experimental ENTITIES are not created and experimental SERVICES raise a clear
# ServiceValidationError. The former ``debug_services`` option is absorbed:
# ``_experimental.experimental_features_enabled`` still honours a legacy
# debug_services=True (graceful migration; see config_flow default mapping).
CONF_EXPERIMENTAL_FEATURES: Final = "experimental_features"
DEFAULT_EXPERIMENTAL_FEATURES: Final = False

# Experimental carveout tiers (spec §6 "Experimental gate"). A descriptor's
# ``experimental`` field (or a gated service's marker) carries exactly one of
# these; None = production surface. The tier only DOCUMENTS why a surface is
# gated + what evidence would promote it — the gate behaviour is identical
# across tiers (skip-when-off / disabled-when-on for entities; raise-when-off
# for services). No production surface is tiered yet (P4.4 populates them).
EXPERIMENTAL_T1_SPECULATIVE: Final = "speculative"  # frame/units/behaviour unverified (e.g. MPOS)
EXPERIMENTAL_T2_WIRE_UNEXERCISED: Final = "wire_unexercised"  # wire byte-verified, client-send unexercised (e.g. OTA install)
EXPERIMENTAL_T3_FAIL_CLOSED: Final = "fail_closed"  # fail-closed pending backend return (e.g. obstacle-photo signer)
EXPERIMENTAL_TIERS: Final = frozenset(
    {
        EXPERIMENTAL_T1_SPECULATIVE,
        EXPERIMENTAL_T2_WIRE_UNEXERCISED,
        EXPERIMENTAL_T3_FAIL_CLOSED,
    }
)

# Bearing (degrees clockwise from north) of the dock's local X axis.
# Used to project dock-frame (x_m, y_m) telemetry into global compass-frame
# (north_m, east_m) for position_north_m / position_east_m sensors.
#
# CFG.DOCK.yaw is unreliable (firmware reports values that drift even when
# the dock hasn't physically moved), so this is a user-set config option.
# When unset (None), N/E projection is skipped and those entities stay
# Unknown.
#
# Convention (verify on first use): X axis points along bearing direction;
# Y axis is 90 deg CCW from X (typical robotics convention). If the
# resulting N/E values are clearly wrong (e.g. signs flipped or 90 deg
# rotated), adjust the bearing value.
CONF_STATION_BEARING_DEG: Final = "station_bearing_deg"
DEFAULT_STATION_BEARING_DEG: Final = None  # type: ignore[assignment]  # optional; user sets if they want N/E projection

# Default values
DEFAULT_NAME: Final = "Dreame A2 Mower"
MANUFACTURER: Final = "Dreame"
DEFAULT_MODEL: Final = "dreame.mower.g2408"
DEFAULT_COUNTRY: Final = "eu"
DEFAULT_LIDAR_ARCHIVE_KEEP: Final = 20
DEFAULT_LIDAR_ARCHIVE_MAX_MB: Final = 200
DEFAULT_PHOTO_ARCHIVE_KEEP: Final = 200
DEFAULT_PHOTO_ARCHIVE_MAX_MB: Final = 50
DEFAULT_VIDEO_ARCHIVE_KEEP: Final = 10
DEFAULT_VIDEO_ARCHIVE_MAX_MB: Final = 100
# Per-category count cap for the photo archive (the 7-category photo_category.py
# scheme: video / ai_human / ai_animal / ai_object / patrol / obstacle / manual).
# 50 per category keeps storage bounded while retaining a reasonable history for
# each detection type.
DEFAULT_PHOTO_ARCHIVE_PER_CATEGORY: Final = 50
DEFAULT_SESSION_ARCHIVE_KEEP: Final = 50
# Per-map keep-newest-N for the WiFi heatmap archive. WiFi JSONs are tiny
# (a few KB) so a byte cap is pointless — count is the meaningful lever; the
# cap exists to bound the picker dropdown and unbounded accumulation. Per-map
# (see WifiArchiveStore.enforce_retention), so this is 20 *per map*, matching
# DEFAULT_LIDAR_ARCHIVE_KEEP.
DEFAULT_WIFI_ARCHIVE_KEEP: Final = 20
DEFAULT_MESSAGES_KEEP: Final = 200

# UI strings
WORK_LOG_PLACEHOLDER: Final = "(pick a session)"

# Log prefixes — single source per spec §3 cross-cutting commitment.
LOG_NOVEL_PROPERTY: Final = "[NOVEL/property]"
LOG_NOVEL_VALUE: Final = "[NOVEL/value]"
LOG_NOVEL_KEY: Final = "[NOVEL_KEY]"
# Forward-compat slot: LOG_NOVEL_KEY is kept in the log_buffer prefix tuple
# so it captures any future namespaced NOVEL_KEY variants (e.g. when CFG
# schema validation lands and emits "[NOVEL_KEY/cfg]" messages).
LOG_NOVEL_KEY_SESSION_SUMMARY: Final = "[NOVEL_KEY/session_summary]"
LOG_EVENT: Final = "[EVENT]"
LOG_SESSION: Final = "[SESSION]"
LOG_MAP: Final = "[MAP]"

# Session-type taxonomy. A session is a "mow" (blades-down work) unless its
# session_type is one of these non-mow move types (blades-up: patrol cruise,
# head-to-maintenance-point, manual drive). Untyped (None) legacy entries
# pre-date session typing and were always mows, so they count as mow.
NON_MOW_SESSION_TYPES: Final = frozenset({"patrol", "maintenance_run", "manual_drive"})

# Dreame cloud obfuscated-strings blob.
# gzip-compressed, base64-encoded JSON array of API endpoint fragments,
# header names, and field keys.  Decoded at runtime by DreameA2CloudClient.
# Source: legacy dreame/const.py DREAME_STRINGS.
DREAME_STRINGS: Final = (
    "H4sICAAAAAAEAGNsb3VkX3N0cmluZ3MuanNvbgBdUltv2jAU/iuoUtEmjZCEljBVPDAQgu0hK5eudJrQ"
    "wXaIV18y24yyX79jm45tebDPd67f+ZyvVwnXLqGGgWSJY6S+eneV9fJ+gfdidBKb8XUll5+a4nr1A12T"
    "kLhdSjCu1pJ1s+Q2uX3fesM/11qxuxYvl62sn6R3rSUBwbq9JE3f+p5kkO56xaDY5Xm/XxT9HaHkZpBV"
    "vYIOKrjJd5Cl0EuhGmTQp1Unw6IPYDlpPc0+is2XTDzm0yOZbV7K5+n9o1zk97NmtM6mTw+qLsvJfogF"
    "afjQsA7cwaIhwTpm1pyiveOKTrQErhA0RjfMuBOaqMCcepcAV2kjh/Ny2bYE40MQor03oNzWnRBikmGVY"
    "bbeOv3MVPsf5MMNWHvUhrYPlhkFMtS0X70BhE5AiD4oh7gbxe/AwdVdHc7QDUOYxKyNzS+j/2D20nB0b"
    "HkM7rn2hmPK8w0bn1t7Lh3cMu7qkZcioqjUJULBga9kPzlhaAhu3UPu46rSMVCuxvMItCPeCnsbkPacH"
    "/DeV0tNmQjsCK5vL5RwWodo6Z+KKTrWUsIro4oLX+ovL+D5rXytVw6vGkdo419uz9wkEJ1E1vY/PInDR"
    "igqorWXYbRnyl1CC0EQ+ARt+C9wUcNV0LAT/oqxVo4hWMXh0DSCk5DY/W5DdrPFY3umo49KaKBrI6Kjt"
    "Dajf3u//QbhJuZXdAMAAA=="
)
