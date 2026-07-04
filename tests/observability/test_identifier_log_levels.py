"""Guard: identifier-bearing log lines stay at DEBUG, not INFO.

Task 5 (P6.2b, refactor-v2/p6-release): any log line that prints a device
identifier (did/serial/mac), an MQTT topic, an OSS object_name (which embeds
the device uid/did — see inventory.yaml § s99p20 / getDeiviceFile), an SSID,
or a raw cloud-auth response was demoted from INFO to DEBUG so a user's
pasted HA log doesn't leak it. This is a narrow, precise fixed-list check
(NOT a broad "any log line with X" gate — that would false-positive on the
many safe count-only INFO logs elsewhere in the tree, e.g. "[CFG] fetched
%d keys"). Each row names one exact call site by its file and a unique
substring of its format string, and asserts a ``.debug(`` call (not
``.info(``) begins within a few lines above that substring.

If a future refactor moves one of these log lines, update its row here —
do not delete the row; the "already fixed" outcome for a moved line is
finding the same substring's call still logs at .debug(.
"""

from __future__ import annotations

import re
from pathlib import Path

CC = Path(__file__).resolve().parents[2] / "custom_components" / "dreame_a2_mower"

# (relative file path, unique substring of the log format string)
IDENTIFIER_LOG_SITES = [
    ("mqtt_client.py", "Connecting to MQTT broker %s:%s"),
    ("mqtt_client.py", "MQTT subscribing to %s"),
    ("mqtt_client.py", "MQTT subscribe(%r) cached"),
    ("mqtt_client.py", "MQTT subscribing to %s (from on_connect)"),
    ("coordinator/_core.py", "Cloud auth ok; device %s model=%s host=%s"),
    ("coordinator/_core.py", "Subscribed to %s"),
    ("cloud_client/_discovery.py", "cloud _handle_device_info: did=%r model=%r mac=%r _host=%r"),
    ("cloud_client/_discovery.py", "Get Device OTC Info empty, trying fallback"),
    ("domain/device_sync.py", "device serial_number updated to %s"),
    ("domain/ingress.py", "event_occured: OSS object_name=%r"),
    ("domain/lidar/service.py", "s99p20 announced object_name=%r"),
    ("cloud_client/_oss.py", "list_wifi_candidates: positional fallback"),
    ("domain/wifi/service.py", "[wifi-match] tagged %s"),
]

# Count-only / no-identifier INFO logs that must stay INFO — a regression
# guard in the other direction (catches an over-eager future demotion of a
# genuinely safe log alongside an identifier-bearing one).
SAFE_INFO_SITES = [
    ("cloud_client/_state_fetch.py", "[CFG] fetched %d keys"),
    ("cloud_client/_device_fetch.py", "[AIOBS] fetched %d marker(s)"),
]

_LOG_CALL_RE = re.compile(r"_?LOGGER\.(debug|info|warning|error)\(")


def _level_for_substring(file_rel: str, substring: str) -> str:
    """Return the LOGGER method name whose call contains ``substring``.

    Scans backward from the substring's line for the nearest
    ``_LOGGER.<level>(`` / ``LOGGER.<level>(`` opener — this tolerates the
    multi-line ``LOGGER.info(\\n    "msg %s",\\n    arg,\\n)`` call shape
    used throughout this codebase.
    """
    path = CC / file_rel
    text = path.read_text()
    idx = text.find(substring)
    assert idx != -1, f"substring {substring!r} not found in {file_rel} (log line moved/reworded?)"
    head = text[:idx]
    matches = list(_LOG_CALL_RE.finditer(head))
    assert matches, f"no LOGGER.<level>( call found before {substring!r} in {file_rel}"
    return matches[-1].group(1)


def test_identifier_bearing_logs_are_debug_not_info():
    for file_rel, substring in IDENTIFIER_LOG_SITES:
        level = _level_for_substring(file_rel, substring)
        assert level == "debug", (
            f"{file_rel}: {substring!r} logs at .{level}( — identifier-bearing "
            "log lines (did/serial/mac/topic/object_name/ssid) must be .debug( "
            "so they don't land in a user's pasted INFO-level HA log "
            "(task-5-brief.md, P6.2b)"
        )


def test_safe_count_only_logs_stay_info():
    for file_rel, substring in SAFE_INFO_SITES:
        level = _level_for_substring(file_rel, substring)
        assert level == "info", (
            f"{file_rel}: {substring!r} logs at .{level}( — this is a count-only "
            "log with no identifier and should stay at .info( (regression guard "
            "against over-eager future demotion)"
        )
