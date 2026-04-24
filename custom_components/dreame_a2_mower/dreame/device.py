from __future__ import annotations
import logging
import time
import json
import re
import copy
import zlib
import base64
import traceback
from datetime import datetime
from random import randrange
from threading import Timer
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageDraw

from .types import (
    PIID,
    DIID,
    ACTION_AVAILABILITY,
    PROPERTY_AVAILABILITY,
    DreameMowerProperty,
    DreameMowerAutoSwitchProperty,
    DreameMowerStrAIProperty,
    DreameMowerAIProperty,
    DreameMowerPropertyMapping,
    DreameMowerAction,
    DreameMowerActionMapping,
    DreameMowerChargingStatus,
    DreameMowerTaskStatus,
    DreameMowerState,
    DreameMowerStatus,
    DreameMowerErrorCode,
    DreameMowerRelocationStatus,
    DreameMowerCleaningMode,
    DreameMowerStreamStatus,
    DreameMowerVoiceAssistantLanguage,
    DreameMowerWiderCornerCoverage,
    DreameMowerSecondCleaning,
    DreameMowerCleaningRoute,
    DreameMowerCleanGenius,
    DreameMowerTaskType,
    DreameMapRecoveryStatus,
    DreameMapBackupStatus,
    CleaningHistory,
    DreameMowerDeviceCapability,
    DirtyData,
    RobotType,
    MapData,
    MapImageDimensions,
    MapPixelType,
    Point,
    Segment,
    Area,
    Shortcut,
    ShortcutTask,
    ObstacleType,
    CleanupMethod,
    GoToZoneSettings,
    Path,
    PathType,
    Coordinate,
    ATTR_ACTIVE_AREAS,
    ATTR_ACTIVE_POINTS,
    ATTR_ACTIVE_SEGMENTS,
    ATTR_PREDEFINED_POINTS,
    ATTR_ACTIVE_CRUISE_POINTS,
)
from .const import (
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
    CLEANING_MODE_CODE_TO_NAME,
    CHARGING_STATUS_CODE_TO_NAME,
    RELOCATION_STATUS_CODE_TO_NAME,
    TASK_STATUS_CODE_TO_NAME,
    STATE_CODE_TO_STATE,
    ERROR_CODE_TO_ERROR_NAME,
    ERROR_CODE_TO_ERROR_DESCRIPTION,
    STATUS_CODE_TO_NAME,
    STREAM_STATUS_TO_NAME,
    WIDER_CORNER_COVERAGE_TO_NAME,
    SECOND_CLEANING_TO_NAME,
    CLEANING_ROUTE_TO_NAME,
    CLEANGENIUS_TO_NAME,
    FLOOR_MATERIAL_CODE_TO_NAME,
    FLOOR_MATERIAL_DIRECTION_CODE_TO_NAME,
    SEGMENT_VISIBILITY_CODE_TO_NAME,
    VOICE_ASSISTANT_LANGUAGE_TO_NAME,
    TASK_TYPE_TO_NAME,
    ERROR_CODE_TO_IMAGE_INDEX,
    CONSUMABLE_TO_LIFE_WARNING_DESCRIPTION,
    PROPERTY_TO_NAME,
    DEVICE_KEY,
    DREAME_MODEL_CAPABILITIES,
    ATTR_CHARGING,
    ATTR_MOWER_STATE,
    ATTR_DND,
    ATTR_SHORTCUTS,
    ATTR_CLEANING_SEQUENCE,
    ATTR_STARTED,
    ATTR_PAUSED,
    ATTR_RUNNING,
    ATTR_RETURNING_PAUSED,
    ATTR_RETURNING,
    ATTR_MAPPING,
    ATTR_MAPPING_AVAILABLE,
    ATTR_ZONES,
    ATTR_CURRENT_SEGMENT,
    ATTR_SELECTED_MAP,
    ATTR_ID,
    ATTR_NAME,
    ATTR_ICON,
    ATTR_ORDER,
    ATTR_STATUS,
    ATTR_DID,
    ATTR_CLEANING_MODE,
    ATTR_COMPLETED,
    ATTR_CLEANING_TIME,
    ATTR_TIMESTAMP,
    ATTR_CLEANED_AREA,
    ATTR_CLEANGENIUS,
    ATTR_CRUISING_TIME,
    ATTR_CRUISING_TYPE,
    ATTR_MAP_INDEX,
    ATTR_MAP_NAME,
    ATTR_NEGLECTED_SEGMENTS,
    ATTR_INTERRUPT_REASON,
    ATTR_CLEANUP_METHOD,
    ATTR_SEGMENT_CLEANING,
    ATTR_ZONE_CLEANING,
    ATTR_SPOT_CLEANING,
    ATTR_CRUSING,
    ATTR_HAS_SAVED_MAP,
    ATTR_HAS_TEMPORARY_MAP,
    ATTR_CAPABILITIES,
)
from .resources import ERROR_IMAGE
from .exceptions import (
    DeviceUpdateFailedException,
    InvalidActionException,
    InvalidValueException,
)
from .protocol import DreameMowerProtocol
from .map import DreameMapMowerMapManager, DreameMowerMapDecoder

_LOGGER = logging.getLogger(__name__)

# Slots that firmware pushes as value={} (session-boundary pings,
# per protocol §4.7). The watchdog's first-observation hook already
# logs these at DEBUG via `known_quiet`; this subset additionally
# suppresses the value-novelty warning for the documented `{}`
# payload, so HA reloads don't emit PROTOCOL_VALUE_NOVEL for an
# expected sentinel. Non-empty values for these slots would still
# be flagged.
_EMPTY_DICT_SENTINEL_SLOTS: frozenset[tuple[int, int]] = frozenset({
    (1, 50),  # "something changed" ping (session start, edits)
    (1, 51),  # "new session — subscribe to telemetry"
    (1, 52),  # "task ended — flush / commit"
    (2, 52),  # cloud-side session-completion ping
})

# ioBroker.dreame documents start/stop/pause on siid=2 (not the siid=5
# upstream MIoT vacuum spec). Used as a fallback when the primary
# siid=5 path returns 80001. Dock stays on siid=5 because both the
# upstream mapping and ioBroker agree. See B2 in TODO.md.
_ALT_ACTION_SIID_MAP: dict = {}  # populated after DreameMowerAction import
def _init_alt_action_siid_map() -> None:
    global _ALT_ACTION_SIID_MAP
    _ALT_ACTION_SIID_MAP = {
        DreameMowerAction.START_MOWING: (2, 1),
        DreameMowerAction.STOP: (2, 2),
        DreameMowerAction.PAUSE: (2, 4),
    }
_init_alt_action_siid_map()


class DreameMowerDevice:
    """Support for Dreame Mower"""

    property_mapping: dict[DreameMowerProperty, dict[str, int]] = DreameMowerPropertyMapping
    action_mapping: dict[DreameMowerAction, dict[str, int]] = DreameMowerActionMapping

    def __init__(
        self,
        name: str,
        host: str,
        token: str,
        mac: str = None,
        username: str = None,
        password: str = None,
        country: str = None,
        prefer_cloud: bool = False,
        account_type: str = "mi",
        device_id: str = None,
    ) -> None:
        # Used for easy filtering the device from cloud device list and generating unique ids
        self.info = None
        self.mac: str = None
        self.token: str = None  # Local api token
        self.host: str = None  # IP address or host name of the device
        # Dictionary for storing the current property values
        self.data: dict[DreameMowerProperty, Any] = {}
        self.auto_switch_data: dict[DreameMowerAutoSwitchProperty, Any] = None
        self.ai_data: dict[DreameMowerStrAIProperty | DreameMowerAIProperty, Any] = None
        self.available: bool = False  # Last update is successful or not
        self.disconnected: bool = False

        self._update_running: bool = False  # Update is running
        self._previous_cleaning_mode: DreameMowerCleaningMode = None
        # Device do not request properties that returned -1 as result. This property used for overriding that behavior at first connection
        self._ready: bool = False
        # Last settings properties requested time
        self._last_settings_request: float = 0
        self._last_map_list_request: float = 0  # Last map list property requested time
        self._last_map_request: float = 0  # Last map request trigger time
        self._last_change: float = 0  # Last property change time
        self._last_update_failed: float = 0  # Last update failed time
        self._cleaning_history_update: float = 0  # Cleaning history update time
        self._update_fail_count: int = 0  # Update failed counter
        self._map_select_time: float = None
        # Map Manager object. Only available when cloud connection is present
        self._map_manager: DreameMapMowerMapManager = None
        self._update_callback = None  # External update callback for device
        self._error_callback = None  # External update failed callback
        # External update callbacks for specific device property
        self._property_update_callback = {}
        self._update_timer: Timer = None  # Update schedule timer
        # Used for requesting consumable properties after reset action otherwise they will only requested when cleaning completed
        self._consumable_change: bool = False
        self._remote_control: bool = False
        self._dirty_data: dict[DreameMowerProperty, DirtyData] = {}
        self._dirty_auto_switch_data: dict[DreameMowerAutoSwitchProperty, DirtyData] = {}
        self._dirty_ai_data: dict[DreameMowerStrAIProperty | DreameMowerAIProperty, Any] = None
        # Per-property monotonic timestamp of last MQTT event arrival, updated
        # even when value is unchanged (re-assertions). Used by sensors that
        # need to auto-clear after a timeout when the mower stops re-asserting
        # a latched boolean (e.g. s1p53 obstacle flag — no "all-clear" event).
        self._property_last_seen_at: dict[int, float] = {}
        # Latest decoded position (x_mm, y_mm) from either the 33-byte full
        # telemetry frame or the 8-byte idle beacon. Updated on every s1p4
        # arrival; independent of `mowing_telemetry` (which is only set for
        # full-shape frames so phase/area/distance sensors don't flicker).
        self._latest_position: tuple[int, int] | None = None
        # Monotonic time.time() of the last s1p4 arrival. Used to detect
        # Manual mode (state=MOWING but no telemetry — Manual is BT-only,
        # firmware doesn't broadcast position/phase on MQTT during a
        # Manual drive, confirmed 2026-04-20 run analysis).
        self._latest_position_ts: float | None = None
        # time.time() of the last s2p1 → MOWING transition. Used as a
        # reference point for Manual-mode detection: we only count
        # "no telemetry" against the mower once the MOWING state has
        # been held for longer than the telemetry timeout, to avoid a
        # brief false-Manual flash at the start of a normal session
        # before the first s1p4 arrives.
        self._mowing_state_entered_at: float | None = None
        # Latest SessionSummary (populated on event_occured → JSON fetch).
        # Holds lawn boundary + mow path + obstacles from the last completed
        # session. Exposed to consumers as `device.latest_session_summary`.
        self._latest_session_summary = None
        # Raw JSON dict of the same summary, retained so the coordinator can
        # archive the authentic wire payload instead of a lossy rebuild.
        self._latest_session_raw = None
        # CFG cache — populated by `refresh_cfg()` calls. Each key mirrors
        # what the firmware returns from `getCFG`: WRP, DND, BAT, CLS, VOL,
        # LIT, AOP, REC, STUN, ATA, PATH, WRF, PROT, CMS, PRE. Default empty
        # so consumers can rely on `device.cfg.get(...)` semantics.
        self._cfg: dict = {}
        # Dock-position cache from getDockPos. Populated by
        # `refresh_dock_pos()`; consumers read via `device.dock_pos`.
        # Schema (per apk): {x, y, yaw, connect_status, path_connect, in_region}.
        self._dock_pos: dict | None = None
        # Maintenance Points (cloud MAP.* `cleanPoints` key). User-placed
        # "go here" markers. Populated by `_build_map_from_cloud_data`.
        # List of `{"id": int, "x_mm": int, "y_mm": int}` in cloud frame
        # (same as charger/obstacles). Empty list when no points placed.
        # The app supports multiple; the user picks which one to visit
        # via the `point_id` param to `mower_go_to_maintenance_point`.
        self._maintenance_points: list[dict] = []
        # Cloud M_PATH.* userData cache — populated alongside MAP.*
        # by `_build_map_from_cloud_data`. Used by live_map's
        # boot-time restore as a fallback when in_progress.json
        # is missing. Per apk, M_PATH coords are ~10x smaller
        # than MAP coords (MAP = mm, M_PATH ~= cm).
        self._cloud_mpath: list | None = None
        # apk-documented SIID 2 piid values surfaced as sensors:
        self._voice_dl_progress: int | None = None
        self._self_check_result: dict | None = None
        # Wall-clock timestamp of the last successful CFG fetch. Entity
        # availability gates use this to avoid surfacing stale-config-only
        # data.
        self._cfg_fetched_at: float | None = None
        # Tri-state: None=untested, True=routed-action endpoint works on
        # this firmware, False=cloud returned 404 (siid:2 aiid:50 not
        # supported on g2408 — empirically confirmed alpha.78 / 2026-04-23).
        # Once False, refresh_cfg / refresh_dock_pos / call_action_opcode
        # short-circuit to avoid spamming the cloud with calls that will
        # never work, and dependent entities hide via exists_fn.
        self._routed_actions_supported: bool | None = None
        # Transient-failure backoff so one 80001 relay-timeout doesn't
        # permanently blind CFG-derived entities. Flips to False (hard
        # disable) only after _CFG_HARD_DISABLE_AFTER consecutive
        # failures — until then we just skip until _cfg_next_retry_at.
        self._cfg_next_retry_at: float = 0.0
        self._cfg_consecutive_failures: int = 0
        self._cfg_last_failure_reason: str | None = None
        self._cfg_last_failure_ts: float | None = None
        self._cfg_success_count: int = 0
        self._cfg_failure_count: int = 0
        # Per-CFG-key change log — populated on every successful
        # refresh_cfg when a value differs from the previous snapshot.
        # Keys never expire; the "recency" is derived at render time
        # from (now - changed_at). Powers the cfg_keys_raw `_recent_
        # changes` attribute used by toggle-correlation dashboards.
        self._cfg_recent_changes: dict[str, dict] = {}
        # The diff from the most recent refresh_cfg call, if any keys
        # moved on that call. Reset-aware view of "what just flipped".
        self._cfg_last_diff: dict[str, tuple] = {}
        self._cfg_last_diff_at: float | None = None
        # OSS object key of the most recently *announced* session-summary
        # (from the event_occured push) that we have NOT yet successfully
        # downloaded. Cleared on a successful fetch. Used so a transient
        # cloud-auth failure at session-end doesn't permanently lose the
        # summary — the coordinator retries on every update cycle until
        # the fetch succeeds. Set back to None to disable retry.
        self._pending_session_object_name: str | None = None
        # Latest LiDAR scan — (object_name, unix_ts, raw_bytes) tuple. Populated
        # by `_handle_lidar_object_name` on every s99p20 push. The coordinator
        # polls this and writes through to the on-disk LidarArchive, same
        # pattern as session-summary JSON.
        self._latest_lidar_scan: tuple[str, int, bytes] | None = None
        # g2408 session-status from s2p56. The upstream TASK_STATUS
        # property (s4p7) never arrives on this device, so these flags
        # are the only signal that a session is "active but paused"
        # (rain-paused, low-battery recharge mid-session, etc).
        # `_task_pending_resume` = True means `{"status": [[1, 4]]}`
        # was the last value — session is on hold pending resume.
        self._task_pending_resume: bool = False
        self._task_running_s2p56: bool = False
        # Flips True on first s2p56 arrival (startup probe or MQTT
        # push). Distinguishes "no session-task" (empty s2p56 seen)
        # from "we haven't heard yet"; consumers like the live-map
        # draft auto-close need that difference to avoid discarding
        # a just-loaded draft while waiting for the first push.
        self._session_status_known: bool = False
        # Dedupe novelty detector — reports unknown (siid, piid) pairs,
        # unfamiliar methods, and new event piids exactly once each so
        # future protocol changes don't get silently discarded.
        from ..protocol.unknown_watchdog import UnknownFieldWatchdog
        self._unknown_watchdog = UnknownFieldWatchdog()
        # Pre-seed with shapes that are fully documented in
        # docs/research/g2408-protocol.md — otherwise every HA
        # restart fires a fresh WARNING for normal operation. The
        # watchdog is in-memory only, so without this seeding the
        # session-completion event would log [PROTOCOL_NOVEL] on
        # every boot even though §7.4 catalogs every piid.
        # Update this list when the protocol doc adds a new
        # documented (siid, eiid, piids) combo.
        self._unknown_watchdog.saw_event(
            4, 1, {1, 2, 3, 7, 8, 9, 11, 13, 14, 15, 60}
        )
        # General novelty detector — records each distinct (shape-key)
        # once so novel protocol content surfaces exactly one WARNING
        # instead of flooding the log every time the same new shape
        # repeats. Holds arbitrary hashables: int values for s2p2 codes,
        # (siid, piid, len) tuples for short-frame lengths, etc.
        self._protocol_novelty: set[object] = set()
        # Latest-value caches for g2408 novel properties surfaced as
        # HA entities. Populated from `_message_callback`. See §4.1
        # (s2p2) and §4.8 (s2p65) in docs/research/g2408-protocol.md.
        # `_s2p2_last` is the most recent secondary state-code emitted
        # (None before first push). `_s2p65_last` is the most recent
        # SLAM task-type string. Neither property currently has a
        # dedicated mapping slot, so we store them here instead of in
        # `self.data[did]` (which is keyed by DreameMowerProperty).
        self._s2p2_last: int | None = None
        self._s2p65_last: str | None = None
        # Optional raw-MQTT archive, attached by coordinator when enabled.
        # Forwarded to the protocol layer where the on-wire payload is
        # still available before JSON-decode.
        self._mqtt_archive = None
        self._discard_timeout = 5
        self._restore_timeout = 15

        self._name = name
        self.mac = mac
        self.token = token
        self.host = host
        self.two_factor_url = None
        self.account_type = account_type
        self.status = DreameMowerDeviceStatus(self)
        self.capability = DreameMowerDeviceCapability(self)

        # Remove write only and response only properties from default list
        self._default_properties = list(
            set([prop for prop in DreameMowerProperty])
            - set(
                [
                    DreameMowerProperty.SCHEDULE_ID,
                    DreameMowerProperty.REMOTE_CONTROL,
                    DreameMowerProperty.VOICE_CHANGE,
                    DreameMowerProperty.VOICE_CHANGE_STATUS,
                    DreameMowerProperty.MAP_RECOVERY,
                    DreameMowerProperty.CLEANING_START_TIME,
                    DreameMowerProperty.CLEAN_LOG_FILE_NAME,
                    DreameMowerProperty.CLEANING_PROPERTIES,
                    DreameMowerProperty.CLEAN_LOG_STATUS,
                    DreameMowerProperty.MAP_INDEX,
                    DreameMowerProperty.MAP_NAME,
                    DreameMowerProperty.CRUISE_TYPE,
                    DreameMowerProperty.MAP_DATA,
                    DreameMowerProperty.FRAME_INFO,
                    DreameMowerProperty.OBJECT_NAME,
                    DreameMowerProperty.MAP_EXTEND_DATA,
                    DreameMowerProperty.ROBOT_TIME,
                    DreameMowerProperty.RESULT_CODE,
                    DreameMowerProperty.OLD_MAP_DATA,
                    DreameMowerProperty.FACTORY_TEST_STATUS,
                    DreameMowerProperty.FACTORY_TEST_RESULT,
                    DreameMowerProperty.SELF_TEST_STATUS,
                    DreameMowerProperty.LSD_TEST_STATUS,
                    DreameMowerProperty.DEBUG_SWITCH,
                    DreameMowerProperty.SERIAL,
                    DreameMowerProperty.CALIBRATION_STATUS,
                    DreameMowerProperty.VERSION,
                    DreameMowerProperty.PERFORMANCE_SWITCH,
                    DreameMowerProperty.AI_TEST_STATUS,
                    DreameMowerProperty.PUBLIC_KEY,
                    DreameMowerProperty.AUTO_PAIR,
                    DreameMowerProperty.MCU_VERSION,
                    DreameMowerProperty.PLATFORM_NETWORK,
                    DreameMowerProperty.TAKE_PHOTO,
                    DreameMowerProperty.STEAM_HUMAN_FOLLOW,
                    DreameMowerProperty.STREAM_KEEP_ALIVE,
                    DreameMowerProperty.STREAM_UPLOAD,
                    DreameMowerProperty.STREAM_AUDIO,
                    DreameMowerProperty.STREAM_RECORD,
                    DreameMowerProperty.STREAM_CODE,
                    DreameMowerProperty.STREAM_SET_CODE,
                    DreameMowerProperty.STREAM_VERIFY_CODE,
                    DreameMowerProperty.STREAM_RESET_CODE,
                    DreameMowerProperty.STREAM_CRUISE_POINT,
                    DreameMowerProperty.STREAM_FAULT,
                    DreameMowerProperty.STREAM_TASK,
                ]
            )
        )
        self._discarded_properties = [
            DreameMowerProperty.ERROR,
            DreameMowerProperty.STATE,
            DreameMowerProperty.STATUS,
            DreameMowerProperty.TASK_STATUS,
            DreameMowerProperty.ERROR,
            DreameMowerProperty.AUTO_SWITCH_SETTINGS,
            DreameMowerProperty.CAMERA_LIGHT_BRIGHTNESS,
            DreameMowerProperty.AI_DETECTION,
            DreameMowerProperty.SHORTCUTS,
            DreameMowerProperty.MAP_BACKUP_STATUS,
            DreameMowerProperty.MAP_RECOVERY_STATUS,
            DreameMowerProperty.OFF_PEAK_CHARGING,
        ]
        self._read_write_properties = [
            DreameMowerProperty.RESUME_CLEANING,
            DreameMowerProperty.OBSTACLE_AVOIDANCE,
            DreameMowerProperty.AI_DETECTION,
            DreameMowerProperty.CLEANING_MODE,
            DreameMowerProperty.INTELLIGENT_RECOGNITION,
            DreameMowerProperty.CUSTOMIZED_CLEANING,
            DreameMowerProperty.CHILD_LOCK,
            DreameMowerProperty.DND_TASK,
            DreameMowerProperty.MULTI_FLOOR_MAP,
            DreameMowerProperty.VOLUME,
            DreameMowerProperty.VOICE_PACKET_ID,
            DreameMowerProperty.TIMEZONE,
            DreameMowerProperty.MAP_SAVING,
            DreameMowerProperty.AUTO_SWITCH_SETTINGS,
            DreameMowerProperty.SHORTCUTS,
            DreameMowerProperty.VOICE_ASSISTANT,
            DreameMowerProperty.CRUISE_SCHEDULE,
            DreameMowerProperty.CAMERA_LIGHT_BRIGHTNESS,
            DreameMowerProperty.STREAM_PROPERTY,
            DreameMowerProperty.STREAM_SPACE,
            DreameMowerProperty.VOICE_ASSISTANT_LANGUAGE,
            DreameMowerProperty.OFF_PEAK_CHARGING,
        ]

        self.listen(self._task_status_changed, DreameMowerProperty.TASK_STATUS)
        self.listen(self._status_changed, DreameMowerProperty.STATUS)
        self.listen(self._charging_status_changed, DreameMowerProperty.CHARGING_STATUS)
        self.listen(self._cleaning_mode_changed, DreameMowerProperty.CLEANING_MODE)
        self.listen(self._ai_obstacle_detection_changed, DreameMowerProperty.AI_DETECTION)
        self.listen(
            self._auto_switch_settings_changed,
            DreameMowerProperty.AUTO_SWITCH_SETTINGS,
        )
        self.listen(self._dnd_task_changed, DreameMowerProperty.DND_TASK)
        self.listen(self._stream_status_changed, DreameMowerProperty.STREAM_STATUS)
        self.listen(self._shortcuts_changed, DreameMowerProperty.SHORTCUTS)
        self.listen(
            self._voice_assistant_language_changed,
            DreameMowerProperty.VOICE_ASSISTANT_LANGUAGE,
        )
        self.listen(self._off_peak_charging_changed, DreameMowerProperty.OFF_PEAK_CHARGING)
        self.listen(self._error_changed, DreameMowerProperty.ERROR)
        self.listen(
            self._map_recovery_status_changed,
            DreameMowerProperty.MAP_RECOVERY_STATUS,
        )

        self._protocol = DreameMowerProtocol(
            self.host,
            self.token,
            username,
            password,
            country,
            prefer_cloud,
            account_type,
            device_id,
        )
        if self._protocol.cloud:
            self._map_manager = DreameMapMowerMapManager(self._protocol)

            self.listen(self._map_list_changed, DreameMowerProperty.MAP_LIST)
            self.listen(self._recovery_map_list_changed, DreameMowerProperty.RECOVERY_MAP_LIST)
            self.listen(self._battery_level_changed, DreameMowerProperty.BATTERY_LEVEL)
            self.listen(self._map_property_changed, DreameMowerProperty.CUSTOMIZED_CLEANING)
            self.listen(self._map_property_changed, DreameMowerProperty.STATE)
            self.listen(self._state_transition_map_poll, DreameMowerProperty.STATE)
            self.listen(
                self._map_backup_status_changed,
                DreameMowerProperty.MAP_BACKUP_STATUS,
            )
            self._map_manager.listen(self._map_changed, self._property_changed)
            self._map_manager.listen_error(self._update_failed)

    def _connected_callback(self):
        if not self._ready:
            return
        _LOGGER.info("Requesting properties after connect")
        self.schedule_update(2, True)
        # Fetch CFG + dock pos now that the protocol is actually
        # connected. The coordinator's init-time schedule fires too
        # early (protocol not yet connected) and silently returns
        # False. Run on a background thread so the connect callback
        # isn't blocked by the cloud round-trip.
        import threading

        def _initial_routed_fetches():
            self.refresh_cfg()
            self.refresh_dock_pos()

        threading.Thread(target=_initial_routed_fetches, daemon=True).start()

    def _message_callback(self, message):
        if not self._ready:
            return

        _LOGGER.debug("Message Callback: %s", message)

        if "method" in message:
            self.available = True
            method = message["method"]
            if method == "properties_changed" and "params" in message:
                params = []
                map_params = []
                for param in message["params"]:
                    matched = False
                    properties = [prop for prop in DreameMowerProperty]
                    for prop in properties:
                        if prop in self.property_mapping:
                            mapping = self.property_mapping[prop]
                            _LOGGER.debug("Mapping: %s", mapping)
                            if (
                                "aiid" not in mapping
                                and param["siid"] == mapping["siid"]
                                and param["piid"] == mapping["piid"]
                            ):
                                matched = True
                                if prop in self._default_properties:
                                    param["did"] = str(prop.value)
                                    param["code"] = 0
                                    params.append(param)
                                else:
                                    if (
                                        prop is DreameMowerProperty.OBJECT_NAME
                                        or prop is DreameMowerProperty.MAP_DATA
                                        or prop is DreameMowerProperty.ROBOT_TIME
                                        or prop is DreameMowerProperty.OLD_MAP_DATA
                                    ):
                                        map_params.append(param)
                                break
                    if not matched and "siid" in param and "piid" in param:
                        # s99p20 = OSS object key for a LiDAR point-cloud upload.
                        # Fires when the user taps "Download LiDAR map" in the
                        # app and a fresh scan is produced. Treated as known
                        # (not unknown) so the watchdog doesn't log it.
                        if param["siid"] == 99 and param["piid"] == 20:
                            value = param.get("value")
                            if isinstance(value, str) and value:
                                self._handle_lidar_object_name(value)
                            continue
                        # s2p56 = session-task status on g2408. Shape:
                        #   `{"status": []}`         — no active task
                        #   `{"status": [[1, 0]]}`   — task running
                        #   `{"status": [[1, 4]]}`   — task paused, pending
                        #                              resume (dock-charging
                        #                              mid-session, rain-
                        #                              paused, etc.)
                        # The upstream TASK_STATUS property (s4p7) is never
                        # emitted on the g2408, so the "session active but
                        # not currently mowing" state (e.g. rain-pause) was
                        # invisible to HA. Track it here so the
                        # `mowing_session_active` binary sensor can reflect
                        # the app's "Continue / End" state correctly.
                        if param["siid"] == 2 and param["piid"] == 56:
                            self._handle_session_status(param.get("value"))
                            continue
                        # s2p50 on g2408 wraps multiple operation classes:
                        #   session-start (mowing):  flat fields {area_id, exe, o:100, region_id, time, t:'TASK'}
                        #   map edit (zone add/remove, exclusion-zone edit):
                        #     {d:{exe, o, status, ...}, t:'TASK'} with 204 (request) + 215 (confirm)
                        # A confirmed map edit (o=215) means the cloud's
                        # MAP.* dataset has changed server-side — our
                        # cached camera image is now stale. Re-fetch +
                        # rebuild so the Mower dashboard reflects the
                        # new zones without waiting for the next HA
                        # restart. See docs/research/g2408-protocol.md
                        # §4.6.
                        if param["siid"] == 2 and param["piid"] == 50:
                            value = param.get("value")
                            if (
                                isinstance(value, dict)
                                and value.get("t") == "TASK"
                                and isinstance(value.get("d"), dict)
                                and value["d"].get("o") == 215
                            ):
                                _LOGGER.info(
                                    "[MAP_EDIT] s2p50 confirmed map edit "
                                    "(ids=%s, id=%s); rebuilding camera "
                                    "map from cloud",
                                    value["d"].get("ids"),
                                    value["d"].get("id"),
                                )
                                try:
                                    self._build_map_from_cloud_data()
                                    # Fire the standard map-changed hook
                                    # so the camera entity picks up the
                                    # new `last_updated` and redraws on
                                    # the next coordinator tick.
                                    if self._map_manager:
                                        self._map_manager._map_data_changed()
                                    self._property_changed()
                                except Exception as ex:  # pragma: no cover
                                    _LOGGER.warning(
                                        "[MAP_EDIT] cloud-map rebuild failed: %s", ex
                                    )
                            continue
                        # s2p2 on g2408 is the "secondary phase code" channel
                        # (not the error enum other models use). Known codes
                        # observed so far: 27, 43 (battery-temp-low), 48
                        # (mowing complete), 50, 53 (scheduled-start,
                        # provisional), 54 (returning), 56 (rain-protection),
                        # 70 (mowing). Anything outside this set is
                        # firmware-novel — worth a one-shot WARNING so the
                        # user can report it back.
                        if param["siid"] == 2 and param["piid"] == 2:
                            value = param.get("value")
                            # Cache so HA sensors (positioning_failed,
                            # rain_protection_active, …) can read the
                            # most-recent code via
                            # `device.s2p2_last`.
                            if isinstance(value, int):
                                self._s2p2_last = value
                            known = {27, 31, 33, 43, 48, 50, 53, 54, 56, 70, 71, 75}
                            if (
                                value not in known
                                and value not in self._protocol_novelty
                            ):
                                self._protocol_novelty.add(value)
                                _LOGGER.warning(
                                    "[PROTOCOL_NOVEL] s2p2 carried unknown value=%r "
                                    "on g2408 (known: %s). Please report at "
                                    "https://github.com/okolbu/ha-dreame-a2-mower/issues",
                                    value,
                                    sorted(known),
                                )
                            # Session-start codes — 50 = manual start,
                            # 53 = scheduled start. Neither fires a map-
                            # ready MQTT signal (no s6p1=300, no
                            # event_occured until session-end), so
                            # anything edited since the last rebuild —
                            # exclusion zones, BUILDING-derived zone
                            # additions, app-side tweaks — would leave
                            # the HA camera showing a stale polygon
                            # during the whole run. Proactively poll
                            # the cloud MAP.* dataset here; the md5sum
                            # dedupe inside `_build_map_from_cloud_data`
                            # makes this a no-op if nothing actually
                            # changed. See docs/research/g2408-protocol.md
                            # §7.1 for the full list of map-refresh
                            # triggers the integration now handles.
                            if value in (50, 53):
                                self._schedule_cloud_map_poll(
                                    reason=f"session-start s2p2={value}"
                                )
                            continue
                        # s2p65 on g2408 is a string-valued SLAM task
                        # label — observed `'TASK_SLAM_RELOCATE'` during
                        # LiDAR relocalization (see §4.8). Cache the
                        # most recent value so HA sensors can surface
                        # it. Other label values likely exist for
                        # other SLAM modes; we store whatever string
                        # arrives.
                        if param["siid"] == 2 and param["piid"] == 65:
                            value = param.get("value")
                            if isinstance(value, str):
                                self._s2p65_last = value
                            continue
                        if self._unknown_watchdog.saw_property(
                            param["siid"], param["piid"]
                        ):
                            # Known-unmapped slots whose existence we've
                            # already characterised (see
                            # docs/research/g2408-protocol.md §2.1) — no
                            # point surfacing at WARNING every HA reload
                            # when the watchdog's in-memory dedup resets.
                            # Downgrade to DEBUG so genuine novelty
                            # (anything NOT in this set) still produces
                            # the one-shot WARNING.
                            known_quiet = {
                                (2, 54),    # LiDAR upload progress 0..100 (§7.3b)
                                (2, 65),    # SLAM-task-type string (§4.8)
                                (2, 66),    # pre-observed 2-element list
                                # Per apk decompilation:
                                (2, 53),    # Voice-pack download progress (%)
                                (2, 57),    # Robot shutdown trigger (5s delay then off)
                                (2, 58),    # Self-check result {d:{mode, id, result}}
                                (2, 61),    # Map-update trigger — loadMap re-fetch
                                (5, 104),   # SLAM relocate counter, unknown role
                                (5, 105),   # mid-session = 1, unknown role
                                (5, 106),   # small int, observed 1-9 and 11 (no 10), purpose unknown
                                (5, 107),   # dynamic, values catalogued
                                # Session-boundary empty-dict pings, all
                                # carry value={}. Per protocol §4.7:
                                (1, 50),    # "something changed" ping (session start, edits)
                                (1, 51),    # "new session — subscribe to telemetry"
                                (1, 52),    # "task ended — flush / commit"
                                (2, 52),    # cloud-side session-completion ping
                            }
                            key = (int(param["siid"]), int(param["piid"]))
                            if key in known_quiet:
                                _LOGGER.debug(
                                    "[PROTOCOL_OBSERVED] properties_changed "
                                    "siid=%s piid=%s value=%r (known-unmapped slot, "
                                    "see docs/research/g2408-protocol.md §2.1)",
                                    param["siid"],
                                    param["piid"],
                                    param.get("value"),
                                )
                            else:
                                # Genuine novelty — not yet catalogued.
                                _LOGGER.warning(
                                    "[PROTOCOL_NOVEL] properties_changed carried an "
                                    "unmapped siid=%s piid=%s value=%r — add to "
                                    "property mapping if this field turns out to be "
                                    "meaningful. Please report at "
                                    "https://github.com/okolbu/ha-dreame-a2-mower/issues",
                                    param["siid"],
                                    param["piid"],
                                    param.get("value"),
                                )
                        # Value-history capture: independent of the
                        # first-seen-property hook above, log each
                        # distinct value of an unmapped property at
                        # WARNING. Lets us derive semantics from the
                        # value pattern without manual probe analysis
                        # (e.g. s5p107 cycles a 10-value enum we want
                        # to catalogue; s2p2 state codes accumulate
                        # over time). Capped at MAX_VALUES_PER_PROP
                        # so high-entropy slots can't flood the log.
                        siid_int = int(param["siid"])
                        piid_int = int(param["piid"])
                        value = param.get("value")
                        # Empty-dict sentinel slots (protocol §4.7) always
                        # carry value={} by design. Their first-observation
                        # hook above already logs at DEBUG; skip the
                        # value-novelty warning for the documented sentinel
                        # payload so HA reloads don't emit noise. If one of
                        # these slots ever carries something non-empty,
                        # THAT is the novelty we want surfaced.
                        if (
                            (siid_int, piid_int) in _EMPTY_DICT_SENTINEL_SLOTS
                            and value == {}
                        ):
                            pass
                        elif self._unknown_watchdog.saw_value(
                            siid_int, piid_int, value
                        ):
                            _LOGGER.warning(
                                "[PROTOCOL_VALUE_NOVEL] siid=%d piid=%d "
                                "value=%r — first time seeing this value "
                                "for this property. Update §2.1 of the "
                                "protocol doc if a pattern emerges.",
                                siid_int, piid_int, value,
                            )
                        # Trigger a CFG re-fetch on settings/preference
                        # updates (s2p51 = MULTIPLEXED_CONFIG, s2p52 =
                        # mowing-prefs changed per apk decompilation).
                        # Runs synchronously on the MQTT callback thread,
                        # same pattern as _fetch_session_summary.
                        if (siid_int, piid_int) in ((2, 51), (2, 52)):
                            self.refresh_cfg()
                        # Trigger a dock-position re-fetch on s1p51
                        # (apk: dock-position-update trigger). Runs
                        # synchronously on the MQTT thread, same
                        # pattern as refresh_cfg above.
                        if (siid_int, piid_int) == (1, 51):
                            self.refresh_dock_pos()
                        # s2p53 (voice-pack download %) and s2p58 (self-
                        # check result) — cache for sensor consumers.
                        # Per apk decompilation.
                        if (siid_int, piid_int) == (2, 53):
                            value = param.get("value")
                            if isinstance(value, (int, float)):
                                self._voice_dl_progress = int(value)
                        elif (siid_int, piid_int) == (2, 58):
                            value = param.get("value")
                            if isinstance(value, dict):
                                self._self_check_result = value.get("d") if "d" in value else value
                if len(map_params) and self._map_manager:
                    self._map_manager.handle_properties(map_params)

                self._decode_blob_properties(params)
                self._handle_properties(params)
            elif method == "event_occured" and "params" in message:
                # Dreame A2 (g2408) fires this at session-complete with the
                # OSS object key for the session-summary JSON in piid=9.
                # Upstream never read this message class, so integrations
                # derived from the vacuum path silently ignored the only
                # signal that carries the map object name on this device.
                # See docs/research/g2408-protocol.md §"event_occured".
                self._handle_event_occured(message["params"])
            else:
                if self._unknown_watchdog.saw_method(method):
                    # Promoted from INFO to WARNING so novel methods surface
                    # at HA's default `logger.default: warning` level. One-
                    # shot per method via the watchdog.
                    _LOGGER.warning(
                        "[PROTOCOL_NOVEL] MQTT message with unfamiliar "
                        "method=%r arrived — payload sample: %s. Please "
                        "report at "
                        "https://github.com/okolbu/ha-dreame-a2-mower/issues",
                        method,
                        message,
                    )

    @property
    def session_end_detected_at(self) -> float | None:
        """Monotonic timestamp of the most recent `event_occured` that the
        cloud fired at session end (`siid=4 eiid=1` on g2408). None until
        the first end-of-session event arrives after HA boot. Cleared by
        `_fetch_session_summary` on a successful fetch, so the presence of
        a value here means "the cloud told us a session ended but we
        haven't yet ingested its summary" — live_map's fallback-finalize
        path reads this + `_pending_session_object_name` to decide when
        to promote the captured live_path to an "(incomplete)" archive
        entry instead of losing the run.
        """
        return getattr(self, "_session_end_detected_at", None)

    def _handle_event_occured(self, params) -> None:
        """Handle an `event_occured` MQTT message.

        Observed on g2408 exactly once per completed mowing session, carrying
        the OSS object key for that session's summary JSON in `piid=9`. The
        JSON contains the full mow path, lawn boundary polygon, obstacle
        polygons, area/time counters, and dock coordinates.

        Format (from 2026-04-18 captures):
        ```
        {
          "id": <corr-id>, "method": "event_occured",
          "params": {
            "did": "<did>", "siid": 4, "eiid": 1,
            "arguments": [
              {"piid": 1,  "value": <int>},
              {"piid": 2,  "value": <int>},           # end-reason-ish
              {"piid": 3,  "value": <area_centiares>},
              {"piid": 7,  "value": <int>},
              {"piid": 8,  "value": <unix_ts>},
              {"piid": 9,  "value": "ali_dreame/…json"},   # OSS object key
              {"piid": 11, "value": <int>},
              ...
            ]
          }
        }
        ```

        For now we just log the object key at INFO so users / future devs
        can see the trigger firing. A follow-up will wire an A2-specific
        JSON decoder and populate the camera entity from this file — the
        existing map-manager decoder expects an encrypted binary blob that
        g2408 does not emit.
        """
        try:
            args = params.get("arguments") if isinstance(params, dict) else None
            siid = params.get("siid") if isinstance(params, dict) else None
            eiid = params.get("eiid") if isinstance(params, dict) else None
            if not isinstance(args, list):
                return
            fields = {}
            for a in args:
                if isinstance(a, dict) and "piid" in a:
                    fields[a["piid"]] = a.get("value")
            object_name = fields.get(9)
            area_centiares = fields.get(3)
            total_lawn_m2 = fields.get(14)
            unix_ts = fields.get(8)
            # Surface any previously-unseen (siid, eiid) combo, or a known
            # combo that introduces a new piid, at WARNING level. One-shot
            # per novelty via the watchdog; known (siid=4, eiid=1) stays
            # silent for the stable piid set so normal operation doesn't
            # log at WARN.
            if (
                isinstance(siid, int)
                and isinstance(eiid, int)
                and self._unknown_watchdog.saw_event(siid, eiid, fields.keys())
            ):
                _LOGGER.warning(
                    "[PROTOCOL_NOVEL] event_occured siid=%s eiid=%s with "
                    "piids=%s — first time seen. Please report at "
                    "https://github.com/okolbu/ha-dreame-a2-mower/issues",
                    siid,
                    eiid,
                    sorted(fields.keys()),
                )
            _LOGGER.info(
                "[EVENT] event_occured siid=%s eiid=%s: object_name=%r "
                "area_mowed_m2=%s total_lawn_m2=%s unix_ts=%s (other fields: %s)",
                siid,
                eiid,
                object_name,
                None if area_centiares is None else area_centiares / 100.0,
                total_lawn_m2,
                unix_ts,
                {k: v for k, v in fields.items() if k not in (3, 8, 9, 14)},
            )
            # Stamp session-end so live_map can fall back to captured
            # telemetry if the OSS fetch never recovers (g2408 cloud
            # is flaky around session-end with "device may be in deep
            # sleep" errors). Only stamp for the documented end-of-
            # session shape so other event_occured variants don't
            # spuriously trigger fallback finalize.
            if siid == 4 and eiid == 1:
                import time as _time
                self._session_end_detected_at = _time.monotonic()
                _LOGGER.warning(
                    "[EVENT] session-end event_occured siid=4 eiid=1 received; "
                    "object_name=%r area=%s m² total_lawn=%s m² ts=%s "
                    "fields=%s",
                    object_name,
                    None if area_centiares is None else area_centiares / 100.0,
                    total_lawn_m2,
                    unix_ts,
                    {k: v for k, v in fields.items()},
                )
            if isinstance(object_name, str) and object_name:
                self._fetch_session_summary(object_name)
            elif siid == 4 and eiid == 1:
                _LOGGER.warning(
                    "[EVENT] session-end event_occured had no object_name "
                    "(piid=9 was %r) — OSS session-summary download cannot "
                    "be attempted; live_map fallback will save captured "
                    "telemetry as (incomplete) archive entry.",
                    object_name,
                )
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning("_handle_event_occured parse failed: %s", ex)

    def _fetch_session_summary(self, object_name: str) -> bool:
        """Download + parse the session-summary JSON referenced by `object_name`.

        Happens inline on the MQTT callback thread — the request is small
        (~60 KB) and the fetch typically completes in under a second. Any
        failure is logged and the object_name is stashed in
        `_pending_session_object_name` so the next coordinator update can
        retry (this matters because g2408 only emits the announcement once
        per session — dropping it on a transient cloud hiccup permanently
        loses that session's summary).

        Returns True on a successful fetch, False on any failure.
        """
        cloud = getattr(self._protocol, "cloud", None)
        if cloud is None or not getattr(cloud, "logged_in", False):
            _LOGGER.warning(
                "[EVENT] session-summary fetch deferred (no cloud login yet) "
                "for %s — will retry on next coordinator update",
                object_name,
            )
            self._pending_session_object_name = object_name
            return False
        try:
            url = cloud.get_interim_file_url(object_name)
            if not url:
                _LOGGER.warning(
                    "[EVENT] session-summary: getDownloadUrl returned None for %s "
                    "— will retry on next coordinator update",
                    object_name,
                )
                self._pending_session_object_name = object_name
                return False
            raw = cloud.get_file(url)
            if not raw:
                _LOGGER.warning(
                    "[EVENT] session-summary: download returned None for %s "
                    "— will retry on next coordinator update",
                    object_name,
                )
                self._pending_session_object_name = object_name
                return False
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            # Local import keeps the heavy protocol package out of the hot
            # property-dispatch path for non-g2408 devices.
            from ..protocol.session_summary import parse_session_summary

            summary = parse_session_summary(data)
            prev_md5 = getattr(
                getattr(self, "_latest_session_summary", None), "md5", None
            )
            self._latest_session_summary = summary
            self._latest_session_raw = data
            self._pending_session_object_name = None
            # OSS download succeeded — clear the session-end fallback
            # flag so live_map doesn't synthesize an "(incomplete)"
            # entry in addition to the cloud-authoritative one.
            self._session_end_detected_at = None
            md5_note = (
                "" if prev_md5 != summary.md5 else
                " (same md5 as previous; downstream dedupe will skip)"
            )
            _LOGGER.warning(
                "[EVENT] session-summary fetched: md5=%s %.1f/%d m² mowed in %d min; "
                "%d boundary pts, %d track segments, %d obstacles, %d exclusions%s",
                summary.md5[:8] if summary.md5 else "?",
                summary.area_mowed_m2,
                summary.map_area_m2,
                summary.duration_min,
                len(summary.lawn_polygon),
                len(summary.track_segments),
                len(summary.obstacles),
                len(summary.exclusions),
                md5_note,
            )
            return True
        except Exception as ex:
            _LOGGER.warning(
                "[EVENT] session-summary fetch failed for %s: %s "
                "— will retry on next coordinator update",
                object_name,
                ex,
            )
            self._pending_session_object_name = object_name
            return False

    def retry_pending_session_summary(self) -> bool:
        """Retry the most recently deferred session-summary fetch, if any.

        Called from the coordinator's periodic update. No-op when nothing
        is pending. Returns True only when this call actually completed
        the fetch (so the coordinator knows to re-archive).
        """
        object_name = self._pending_session_object_name
        if not object_name:
            return False
        return self._fetch_session_summary(object_name)

    def _handle_session_status(self, value) -> None:
        """React to an ``s2p56`` session-status arrival (g2408).

        The g2408 never emits the upstream TASK_STATUS property, so
        this is our only signal that a session is active. Flags we
        set from the payload shape:

        - ``{"status": []}``     → no active task (both False)
        - ``{"status": [[1, 0]]}``→ task running (`_task_running_s2p56`)
        - ``{"status": [[1, 4]]}``→ task paused, pending resume
                                    (`_task_pending_resume`)

        Used by ``device.status.started`` so the Mowing Session Active
        binary sensor correctly reports "session in progress" during
        rain-protection stops and low-battery recharge pauses even
        when the mower is physically docked.
        """
        running = False
        pending = False
        try:
            status = None
            if isinstance(value, dict):
                status = value.get("status")
            if isinstance(status, list) and status:
                first = status[0]
                if isinstance(first, list) and len(first) >= 2:
                    # Second element: 0 = running, 4 = paused-pending-resume.
                    code = int(first[1])
                    running = (code == 0)
                    pending = (code == 4)
        except (TypeError, ValueError):
            pass
        if running != self._task_running_s2p56 or pending != self._task_pending_resume:
            _LOGGER.info(
                "[SESSION] s2p56 update: running=%s pending_resume=%s (raw=%r)",
                running, pending, value,
            )
        self._task_running_s2p56 = running
        self._task_pending_resume = pending
        self._session_status_known = True

    def _handle_lidar_object_name(self, object_name: str) -> None:
        """React to an ``s99p20`` LiDAR-scan upload announcement.

        The mower uploads a point-cloud binary (standard PCL `.pcd`
        format) to OSS and then publishes the object key over MQTT. We
        fetch the blob via the same cloud client used for session
        summaries, stash raw bytes on the device, and let the
        coordinator write through to the on-disk archive.
        """
        if self._latest_lidar_scan and self._latest_lidar_scan[0] == object_name:
            return  # same OSS key — nothing new to do
        _LOGGER.info("[LIDAR] s99p20 announced object_name=%r", object_name)
        self._fetch_lidar_scan(object_name)

    def _fetch_lidar_scan(self, object_name: str) -> None:
        """Download the PCD binary for ``object_name`` inline. Failures
        are logged and swallowed — observability never breaks telemetry."""
        cloud = getattr(self._protocol, "cloud", None)
        if cloud is None or not getattr(cloud, "logged_in", False):
            _LOGGER.info(
                "[LIDAR] scan fetch skipped (no cloud login): %s", object_name
            )
            return
        try:
            url = cloud.get_interim_file_url(object_name)
            if not url:
                _LOGGER.warning(
                    "[LIDAR] getDownloadUrl returned None for %s", object_name
                )
                return
            raw = cloud.get_file(url)
            if not raw:
                _LOGGER.warning("[LIDAR] download returned empty for %s", object_name)
                return
            self._latest_lidar_scan = (object_name, int(time.time()), bytes(raw))
            _LOGGER.info(
                "[LIDAR] scan fetched: %s (%d bytes)",
                object_name,
                len(raw),
            )
        except Exception as ex:
            _LOGGER.warning("[LIDAR] fetch failed for %s: %s", object_name, ex)

    @property
    def latest_lidar_scan(self) -> tuple[str, int, bytes] | None:
        """Return the most recently fetched LiDAR scan, or None.

        Tuple shape: ``(object_name, unix_ts, raw_pcd_bytes)``. The
        coordinator polls this on each update tick and hands it to the
        on-disk archive.
        """
        return self._latest_lidar_scan

    def _handle_properties(self, properties) -> bool:
        # Timestamp every incoming property event (even re-assertions that
        # don't change the value) so auto-clearing sensors can detect when
        # the mower has stopped re-asserting a latched flag.
        _now_monotonic = time.monotonic()
        for _prop in properties:
            if isinstance(_prop, dict):
                try:
                    self._property_last_seen_at[int(_prop.get("did", 0))] = _now_monotonic
                except (TypeError, ValueError):
                    pass

        changed = False
        callbacks = []
        for prop in properties:
            if not isinstance(prop, dict):
                continue
            did = int(prop["did"])
            if prop["code"] == 0 and "value" in prop:
                value = prop["value"]
                if did in self._dirty_data:
                    if (
                        self._dirty_data[did].value != value
                        and time.time() - self._dirty_data[did].update_time < self._discard_timeout
                    ):
                        _LOGGER.info(
                            "Property %s Value Discarded: %s <- %s",
                            DreameMowerProperty(did).name,
                            self._dirty_data[did].value,
                            value,
                        )
                        del self._dirty_data[did]
                        continue
                    del self._dirty_data[did]

                current_value = self.data.get(did)

                if current_value != value:
                    # Do not call external listener when map and json properties changed
                    if not (
                        did == DreameMowerProperty.MAP_LIST.value
                        or did == DreameMowerProperty.RECOVERY_MAP_LIST.value
                        or did == DreameMowerProperty.MAP_DATA.value
                        or did == DreameMowerProperty.OBJECT_NAME.value
                        or did == DreameMowerProperty.AUTO_SWITCH_SETTINGS.value
                        or did == DreameMowerProperty.AI_DETECTION.value
                        # or did == DreameMowerProperty.SELF_TEST_STATUS.value
                    ):
                        changed = True
                    custom_property = (
                        did == DreameMowerProperty.AUTO_SWITCH_SETTINGS.value
                        or did == DreameMowerProperty.AI_DETECTION.value
                        or did == DreameMowerProperty.MAP_LIST.value
                        or did == DreameMowerProperty.SERIAL_NUMBER.value
                    )
                    if not custom_property:
                        if current_value is not None:
                            _LOGGER.info(
                                "Property %s Changed: %s -> %s",
                                DreameMowerProperty(did).name,
                                current_value,
                                value,
                            )
                        else:
                            _LOGGER.info(
                                "Property %s Added: %s",
                                DreameMowerProperty(did).name,
                                value,
                            )
                    self.data[did] = value
                    if did in self._property_update_callback:
                        _LOGGER.debug("Property %s Callbacks: %s", DreameMowerProperty(did).name, self._property_update_callback[did])
                        for callback in self._property_update_callback[did]:
                            if not self._ready and custom_property:
                                callback(current_value)
                            else:
                                callbacks.append([callback, current_value])
            else:
                _LOGGER.debug("Property %s Not Available", DreameMowerProperty(did).name)

        if not self._ready:
            self.capability.refresh(
                json.loads(zlib.decompress(base64.b64decode(DREAME_MODEL_CAPABILITIES), zlib.MAX_WBITS | 32))
            )

        for callback in callbacks:
            callback[0](callback[1])

        if changed:
            self._last_change = time.time()
            if self._ready:
                self._property_changed()

        if not self._ready:
            if self._protocol.dreame_cloud:
                self._discard_timeout = 5

            self.status.segment_cleaning_mode_list = self.status.cleaning_mode_list.copy()

            if self.capability.cleaning_route:
                if (
                    self.status.cleaning_mode == DreameMowerCleaningMode.MOWING
                ):
                    new_list = CLEANING_ROUTE_TO_NAME.copy()
                    new_list.pop(DreameMowerCleaningRoute.DEEP)
                    new_list.pop(DreameMowerCleaningRoute.INTENSIVE)
                    self.status.cleaning_route_list = {v: k for k, v in new_list.items()}
                    new_list = CLEANING_ROUTE_TO_NAME.copy()
                    if self.capability.segment_slow_clean_route:
                        new_list.pop(DreameMowerCleaningRoute.QUICK)
                    self.status.segment_cleaning_route_list = {v: k for k, v in new_list.items()}

            for p in dir(self.capability):
                if not p.startswith("__") and not callable(getattr(self.capability, p)):
                    val = getattr(self.capability, p)
                    if isinstance(val, bool) and val:
                        _LOGGER.info("Capability %s", p.upper())

        return changed

    def _decode_blob_properties(self, params: list[dict]) -> None:
        """Decode g2408 blob properties in-place into structured objects.

        Blob properties (s1p4 telemetry, s1p1 heartbeat, s2p51 config) arrive
        as raw lists of bytes or dicts. We replace param['value'] with the
        decoded dataclass/object so downstream entities can read structured
        fields instead of raw bytes. Malformed blobs are logged and dropped
        (the param's value is set to None) so they don't poison entity state.
        """
        from ..protocol.telemetry import (
            FRAME_LENGTH,
            FRAME_LENGTH_BEACON,
            FRAME_LENGTH_BUILDING,
            InvalidS1P4Frame,
            decode_s1p4,
            decode_s1p4_position,
        )
        from ..protocol.heartbeat import InvalidS1P1Frame, decode_s1p1
        from ..protocol.config_s2p51 import S2P51DecodeError, decode_s2p51

        telemetry_did = DreameMowerProperty.MOWING_TELEMETRY.value
        heartbeat_did = DreameMowerProperty.HEARTBEAT.value
        config_did = DreameMowerProperty.MULTIPLEXED_CONFIG.value

        for param in params:
            if not isinstance(param, dict):
                continue
            did = int(param.get("did", 0))
            value = param.get("value")
            try:
                if did == telemetry_did and isinstance(value, list):
                    raw = bytes(value)
                    # Always extract position — works on 8/10-byte variants too.
                    beacon = decode_s1p4_position(raw)
                    self._latest_position = (beacon.x_mm, beacon.y_mm)
                    self._latest_position_ts = time.time()
                    self._update_map_robot_position(beacon.x_mm, beacon.y_mm)
                    if len(raw) == FRAME_LENGTH:
                        param["value"] = decode_s1p4(raw)
                    else:
                        # 8-byte idle beacon or 10-byte BUILDING frame:
                        # position-only. Drop the value so _handle_properties
                        # doesn't overwrite the last good MowingTelemetry
                        # (keeps phase/area/distance sensors from flickering
                        # between real data and None when no full frame has
                        # arrived yet).
                        param["code"] = 1
                        # Log the raw bytes once per frame length so the
                        # un-decoded bytes (e.g. the 8-byte preamble's
                        # middle bytes varying 19/20/30 and 192/160/192 —
                        # see 2026-04-20 run analysis) stay recoverable
                        # for future RE instead of silently discarding.
                        # Key on (siid, piid, len) so each novel shape
                        # logs exactly once.
                        key = (1, 4, len(raw))
                        if key not in self._protocol_novelty:
                            self._protocol_novelty.add(key)
                            _LOGGER.warning(
                                "[PROTOCOL_NOVEL] s1p4 short frame len=%d "
                                "observed — position decoded, remaining "
                                "bytes not yet reverse-engineered. "
                                "Raw=%s. Please report at "
                                "https://github.com/okolbu/ha-dreame-a2-mower/issues",
                                len(raw),
                                list(raw),
                            )
                elif did == heartbeat_did and isinstance(value, list):
                    param["value"] = decode_s1p1(bytes(value))
                elif did == config_did and isinstance(value, dict):
                    param["value"] = decode_s2p51(value)
            except (InvalidS1P4Frame, InvalidS1P1Frame, S2P51DecodeError) as e:
                _LOGGER.warning(
                    "Discarding malformed g2408 blob (did=%d): %s", did, e
                )
                param["value"] = None

    def _request_properties(self, properties: list[DreameMowerProperty] = None) -> bool:
        """Request properties from the device."""
        if not properties:
            properties = self._default_properties

        property_list = []
        for prop in properties:
            if prop in self.property_mapping:
                mapping = self.property_mapping[prop]
                # Do not include properties that are not exists on the device
                if "aiid" not in mapping and (not self._ready or prop.value in self.data):
                    property_list.append({"did": str(prop.value), **mapping})

        props = property_list.copy()
        results = []
        while props:
            result = self._protocol.get_properties(props[:15])
            if result is not None:
                results.extend(result)
                props[:] = props[15:]
            else:
                break

        return self._handle_properties(results)

    def _update_status(self, task_status: DreameMowerTaskStatus, status: DreameMowerStatus) -> None:
        """Update status properties on memory for map renderer to update the image before action is sent to the device."""
        if task_status is not DreameMowerTaskStatus.COMPLETED:
            new_state = DreameMowerState.MOWING
            self._update_property(DreameMowerProperty.STATE, new_state.value)

        self._update_property(DreameMowerProperty.STATUS, status.value)
        self._update_property(DreameMowerProperty.TASK_STATUS, task_status.value)

    def _update_property(self, prop: DreameMowerProperty, value: Any) -> Any:
        """Update device property on memory and notify listeners."""
        if prop in self.property_mapping:
            # Legacy old-state remap (>18 → new enum via DreameMowerStateOld)
            # removed 2026-04-20. A2 always uses the new-state enum.
            current_value = self.get_property(prop)
            if current_value != value:
                did = prop.value
                self.data[did] = value
                if did in self._property_update_callback:
                    for callback in self._property_update_callback[did]:
                        callback(current_value)

                self._property_changed()
                return current_value if current_value is not None else value
        return None

    def _map_property_changed(self, previous_property: Any = None) -> None:
        """Update last update time of the map when a property associated with rendering map changed."""
        if self._map_manager and previous_property is not None:
            self._map_manager.editor.refresh_map()

    def _state_transition_map_poll(self, previous_value: Any = None) -> None:
        """Re-pull the cloud MAP.* dataset when the state transitions in a
        way that's likely to have left the cached map out of date.

        Triggers:
        - Previous was BUILDING(11), now anything else → zone boundary trace
          just completed and the firmware committed a new map polygon.
          Dreame does not emit `s2p50 o=215` for firmware-driven saves,
          so `_message_callback`'s map-edit branch doesn't catch this one.
        - Previous was CHARGING(6) and current is MOWING(1), IDLE(2) or
          BUILDING(11) → starting a new session. Catches the s2p2=50/53
          path already covered in `_message_callback` as a belt-and-braces
          fallback for manual-UI starts that emit `s2p1` transition first.

        The md5sum dedupe inside `_build_map_from_cloud_data` makes this a
        no-op if nothing actually changed upstream, so it's cheap to be
        liberal with triggers.
        """
        if previous_value is None:
            return  # Initial population, not a real transition
        current = self.get_property(DreameMowerProperty.STATE)
        if current is None:
            return
        try:
            prev_int = int(previous_value)
            cur_int = int(current)
        except (TypeError, ValueError):
            return
        BUILDING = 11
        CHARGING = 6
        # Trigger 1: BUILDING → anything else
        if prev_int == BUILDING and cur_int != BUILDING:
            self._schedule_cloud_map_poll(
                reason=f"building-complete s2p1: {prev_int} → {cur_int}"
            )
            return
        # Trigger 2: CHARGING → anything active (mow / build / idle-out-of-dock)
        if prev_int == CHARGING and cur_int != CHARGING:
            self._schedule_cloud_map_poll(
                reason=f"dock-departure s2p1: {prev_int} → {cur_int}"
            )
        # Trigger 3: reset mower icon on the map when (re)docked so the
        # icon sits at the station instead of wherever the last s1p4 put
        # it. The final in-flight telemetry frame typically lags the
        # state change by a few seconds, so we re-seed on transition.
        if cur_int == CHARGING and prev_int != CHARGING:
            self._seed_robot_at_charger()
        # Track MOWING-state entry time so Manual-mode detection can
        # wait out an initial telemetry grace period instead of
        # false-triggering at session start.
        if cur_int == DreameMowerState.MOWING.value and prev_int != DreameMowerState.MOWING.value:
            self._mowing_state_entered_at = time.time()
        # Trigger 4: state left MOWING → always clear any Manual-mode
        # overlay (either we arrived at dock with no telemetry, or the
        # session finished normally). The overlay itself is set by the
        # coordinator's periodic tick calling `manual_mode_tick`.
        if prev_int == DreameMowerState.MOWING.value and cur_int != DreameMowerState.MOWING.value:
            self._clear_manual_mode_overlay()
            self._mowing_state_entered_at = None

    def _update_map_robot_position(self, x_mm: int, y_mm: int) -> None:
        """Project s1p4 charger-relative position into the cloud-frame map.

        Transform (see docs/research/g2408-protocol.md §Coordinates):

            mower_cloud_x = charger_position.x - x_mm
            mower_cloud_y = charger_position.y - y_mm

        Both axes are in map-scale mm (matches cloud-frame units), so
        the projection is a straight subtraction. The cloud frame uses
        X+Y reflection through the midline that the A2 station sits on,
        so a positive charger-relative mower position becomes a
        *negative* delta in the cloud frame.

        Historical note: alphas prior to .98 had a 16× Y scaling bug in
        the pose decoder compensated by a `* 0.625` factor here. alpha.98
        fixed the decoder; both factors are now removed.

        Updates both the live `_map_data.robot_position` and the saved
        map copy that the camera renders from. No-op if the map hasn't
        been built yet. Also clears any Manual-mode overlay since we
        now have authoritative telemetry.
        """
        if not self._map_manager:
            return
        map_data = getattr(self._map_manager, "_map_data", None)
        if map_data is None or map_data.charger_position is None:
            return
        try:
            from .types import Point
            mower_x = map_data.charger_position.x - x_mm
            mower_y = map_data.charger_position.y - y_mm
            pt = Point(mower_x, mower_y, 0)
            map_data.robot_position = pt
            saved = getattr(self._map_manager, "_saved_map_data", None)
            if isinstance(saved, dict) and 1 in saved and saved[1] is not None:
                saved[1].robot_position = pt
                # Clear manual overlay on both copies — telemetry means
                # the mower is talking via MQTT, so not in BT-only Manual.
                saved[1].manual_mode_overlay = None
            map_data.manual_mode_overlay = None
        except Exception as ex:
            _LOGGER.debug("Failed to update map robot position: %s", ex)

    def _seed_robot_at_charger(self) -> None:
        """Reset robot_position to the charger (used on re-dock transitions)."""
        if not self._map_manager:
            return
        map_data = getattr(self._map_manager, "_map_data", None)
        if map_data is None or map_data.charger_position is None:
            return
        try:
            from .types import Point
            pt = Point(
                map_data.charger_position.x,
                map_data.charger_position.y,
                0,
            )
            map_data.robot_position = pt
            saved = getattr(self._map_manager, "_saved_map_data", None)
            if isinstance(saved, dict) and 1 in saved and saved[1] is not None:
                saved[1].robot_position = pt
        except Exception as ex:
            _LOGGER.debug("Failed to seed robot at charger: %s", ex)

    def is_manual_mode(self) -> bool:
        """Return True if the mower is in Manual drive (BT-only, no MQTT telemetry).

        Heuristic: state is MOWING but no s1p4 frame has arrived within
        MANUAL_MODE_TELEMETRY_TIMEOUT_S seconds. Manual mode is driven
        purely over Bluetooth from the phone; firmware does not broadcast
        s1p4 position/phase or s2p2 status codes during the drive. The
        only MQTT artefacts are the bookend s2p1 transitions (1 on start,
        2 on end). Confirmed in 2026-04-20 Manual-run log analysis.
        """
        MANUAL_MODE_TELEMETRY_TIMEOUT_S = 15.0
        try:
            state_val = self.get_property(DreameMowerProperty.STATE)
            if state_val is None or int(state_val) != DreameMowerState.MOWING.value:
                return False
        except (TypeError, ValueError):
            return False
        entered_at = self._mowing_state_entered_at
        if entered_at is None:
            # We don't know when MOWING started (e.g. integration came
            # up already in MOWING). Be conservative and don't flag
            # Manual — the next state transition will give us a
            # reference point.
            return False
        now = time.time()
        if now - entered_at < MANUAL_MODE_TELEMETRY_TIMEOUT_S:
            # Grace period: normal sessions may take several seconds
            # to emit the first s1p4 after s2p1=MOWING.
            return False
        if self._latest_position_ts is None:
            return True
        # Any s1p4 since state entered MOWING disqualifies Manual.
        return self._latest_position_ts < entered_at

    def manual_mode_tick(self) -> None:
        """Periodic check for Manual mode, called from the coordinator.

        If Manual is detected, clear the robot_position on the map
        (so the icon is hidden) and set `manual_mode_overlay` so the
        renderer can draw a 'MANUAL MODE' banner. If the mower leaves
        Manual (telemetry returns or state leaves MOWING), the overlay
        is cleared by `_update_map_robot_position` or the state-transition
        handler.
        """
        if not self._map_manager:
            return
        map_data = getattr(self._map_manager, "_map_data", None)
        if map_data is None:
            return
        if self.is_manual_mode():
            map_data.robot_position = None
            map_data.manual_mode_overlay = "MANUAL MODE"
            saved = getattr(self._map_manager, "_saved_map_data", None)
            if isinstance(saved, dict) and 1 in saved and saved[1] is not None:
                saved[1].robot_position = None
                saved[1].manual_mode_overlay = "MANUAL MODE"

    def _clear_manual_mode_overlay(self) -> None:
        """Remove any 'MANUAL MODE' overlay from the map data."""
        if not self._map_manager:
            return
        map_data = getattr(self._map_manager, "_map_data", None)
        if map_data is not None:
            map_data.manual_mode_overlay = None
        saved = getattr(self._map_manager, "_saved_map_data", None)
        if isinstance(saved, dict) and 1 in saved and saved[1] is not None:
            saved[1].manual_mode_overlay = None

    def _map_list_changed(self, previous_map_list: Any = None) -> None:
        """Update map list object name on map manager map list property when changed"""
        if self._map_manager:
            map_list = self.get_property(DreameMowerProperty.MAP_LIST)
            if map_list and map_list != "":
                try:
                    map_list = json.loads(map_list)
                    object_name = map_list.get("object_name")
                    if object_name is None:
                        object_name = map_list.get("obj_name")
                    if object_name and object_name != "":
                        _LOGGER.info("Property MAP_LIST Changed: %s", object_name)
                        self._map_manager.set_map_list_object_name(object_name, map_list.get("md5"))
                    else:
                        self._last_map_list_request = 0
                except:
                    pass

    def _recovery_map_list_changed(self, previous_recovery_map_list: Any = None) -> None:
        """Update recovery list object name on map manager recovery list property when changed"""
        if self._map_manager:
            map_list = self.get_property(DreameMowerProperty.RECOVERY_MAP_LIST)
            if map_list and map_list != "":
                try:
                    map_list = json.loads(map_list)
                    object_name = map_list.get("object_name")
                    if object_name is None:
                        object_name = map_list.get("obj_name")
                    if object_name and object_name != "":
                        self._map_manager.set_recovery_map_list_object_name(object_name)
                    else:
                        self._last_map_list_request = 0
                except:
                    pass

    def _map_recovery_status_changed(self, previous_map_recovery_status: Any = None) -> None:
        if previous_map_recovery_status and self.status.map_recovery_status:
            if self.status.map_recovery_status == DreameMapRecoveryStatus.SUCCESS.value:
                if not self._protocol.dreame_cloud:
                    self._last_map_list_request = 0
                self._map_manager.request_next_map()
                self._map_manager.request_next_recovery_map_list()

            if self.status.map_recovery_status != DreameMapRecoveryStatus.RUNNING.value:
                self._request_properties([DreameMowerProperty.MAP_RECOVERY_STATUS])

    def _map_backup_status_changed(self, previous_map_backup_status: Any = None) -> None:
        if previous_map_backup_status and self.status.map_backup_status:
            if self.status.map_backup_status == DreameMapBackupStatus.SUCCESS.value:
                if not self._protocol.dreame_cloud:
                    self._last_map_list_request = 0
                self._map_manager.request_next_recovery_map_list()
            if self.status.map_backup_status != DreameMapBackupStatus.RUNNING.value:
                self._request_properties([DreameMowerProperty.MAP_BACKUP_STATUS])

    def _cleaning_mode_changed(self, previous_cleaning_mode: Any = None) -> None:
        value = self.get_property(DreameMowerProperty.CLEANING_MODE)
        new_cleaning_mode = None

        if previous_cleaning_mode is not None and self.status.go_to_zone:
            self.status.go_to_zone.cleaning_mode = None

        if self.status.cleaning_mode != new_cleaning_mode:
            self.status.cleaning_mode = new_cleaning_mode

            if self._ready and self.capability.cleaning_route:
                new_list = CLEANING_ROUTE_TO_NAME.copy()
                if (
                    self.status.cleaning_mode == DreameMowerCleaningMode.MOWING
                ):
                    new_list.pop(DreameMowerCleaningRoute.DEEP)
                    new_list.pop(DreameMowerCleaningRoute.INTENSIVE)
                self.status.cleaning_route_list = {v: k for k, v in new_list.items()}

                if self.status.cleaning_route and self.status.cleaning_route not in self.status.cleaning_route_list:
                    self.set_auto_switch_property(
                        DreameMowerAutoSwitchProperty.CLEANING_ROUTE,
                        DreameMowerCleaningRoute.STANDARD.value,
                    )

    def _task_status_changed(self, previous_task_status: Any = None) -> None:
        """Task status is a very important property and must be listened to trigger necessary actions when a task started or ended"""
        if previous_task_status is not None:
            if previous_task_status in DreameMowerTaskStatus._value2member_map_:
                previous_task_status = DreameMowerTaskStatus(previous_task_status)

            task_status = self.get_property(DreameMowerProperty.TASK_STATUS)
            if task_status in DreameMowerTaskStatus._value2member_map_:
                task_status = DreameMowerTaskStatus(task_status)

            if previous_task_status is DreameMowerTaskStatus.COMPLETED:
                # as implemented on the app
                self._update_property(DreameMowerProperty.CLEANING_TIME, 0)
                self._update_property(DreameMowerProperty.CLEANED_AREA, 0)

            if self._map_manager is not None:
                # Update map data for renderer to update the map image according to the new task status
                if previous_task_status is DreameMowerTaskStatus.COMPLETED:
                    if (
                        task_status is DreameMowerTaskStatus.AUTO_CLEANING
                        or task_status is DreameMowerTaskStatus.ZONE_CLEANING
                        or task_status is DreameMowerTaskStatus.SEGMENT_CLEANING
                        or task_status is DreameMowerTaskStatus.SPOT_CLEANING
                        or task_status is DreameMowerTaskStatus.CRUISING_PATH
                        or task_status is DreameMowerTaskStatus.CRUISING_POINT
                    ):
                        # Clear path on current map on cleaning start as implemented on the app
                        self._map_manager.editor.clear_path()
                    elif task_status is DreameMowerTaskStatus.FAST_MAPPING:
                        # Clear current map on mapping start as implemented on the app
                        self._map_manager.editor.reset_map()
                    else:
                        self._map_manager.editor.refresh_map()
                else:
                    self._map_manager.editor.refresh_map()

            if task_status is DreameMowerTaskStatus.COMPLETED:
                if (
                    previous_task_status is DreameMowerTaskStatus.CRUISING_PATH
                    or previous_task_status is DreameMowerTaskStatus.CRUISING_POINT
                    or self.status.go_to_zone
                ):
                    if self._map_manager is not None:
                        # Get the new map list from cloud
                        self._map_manager.editor.set_cruise_points([])
                        self._map_manager.request_next_map_list()
                    self._cleaning_history_update = time.time()
                elif previous_task_status is DreameMowerTaskStatus.FAST_MAPPING:
                    # as implemented on the app
                    self._update_property(DreameMowerProperty.CLEANING_TIME, 0)
                    if self._map_manager is not None:
                        # Mapping is completed, get the new map list from cloud
                        self._map_manager.request_next_map_list()
                elif (
                    self.status.cleanup_started
                    and not self.status.cleanup_completed
                    and (self.status.status is DreameMowerStatus.BACK_HOME or not self.status.running)
                ):
                    self.status.cleanup_started = False
                    self.status.cleanup_completed = True
                    self._cleaning_history_update = time.time()
            else:
                self.status.cleanup_started = not (
                    self.status.fast_mapping
                    or self.status.cruising
                    or (
                        task_status is DreameMowerTaskStatus.DOCKING_PAUSED
                        and previous_task_status is DreameMowerTaskStatus.COMPLETED
                    )
                )
                self.status.cleanup_completed = False

            if self.status.go_to_zone is not None and not (
                task_status is DreameMowerTaskStatus.ZONE_CLEANING
                or task_status is DreameMowerTaskStatus.ZONE_CLEANING_PAUSED
                or task_status is DreameMowerTaskStatus.ZONE_DOCKING_PAUSED
                or task_status is DreameMowerTaskStatus.CRUISING_POINT
                or task_status is DreameMowerTaskStatus.CRUISING_POINT_PAUSED
            ):
                self._restore_go_to_zone()

            if self._map_manager:
                self._map_manager.editor.refresh_map()

            if (
                task_status is DreameMowerTaskStatus.COMPLETED
                or previous_task_status is DreameMowerTaskStatus.COMPLETED
            ):
                # Get properties that only changes when task status is changed
                properties = [
                    DreameMowerProperty.BLADES_TIME_LEFT,
                    DreameMowerProperty.BLADES_LEFT,
                    DreameMowerProperty.SIDE_BRUSH_TIME_LEFT,
                    DreameMowerProperty.SIDE_BRUSH_LEFT,
                    DreameMowerProperty.FILTER_LEFT,
                    DreameMowerProperty.FILTER_TIME_LEFT,
                    DreameMowerProperty.TANK_FILTER_LEFT,
                    DreameMowerProperty.TANK_FILTER_TIME_LEFT,
                    DreameMowerProperty.SILVER_ION_TIME_LEFT,
                    DreameMowerProperty.SILVER_ION_LEFT,
                    DreameMowerProperty.LENSBRUSH_TIME_LEFT,
                    DreameMowerProperty.LENSBRUSH_LEFT,
                    DreameMowerProperty.SQUEEGEE_TIME_LEFT,
                    DreameMowerProperty.SQUEEGEE_LEFT,
                    DreameMowerProperty.TOTAL_CLEANING_TIME,
                    DreameMowerProperty.CLEANING_COUNT,
                    DreameMowerProperty.TOTAL_CLEANED_AREA,
                    DreameMowerProperty.TOTAL_RUNTIME,
                    DreameMowerProperty.TOTAL_CRUISE_TIME,
                    DreameMowerProperty.FIRST_CLEANING_DATE,
                    DreameMowerProperty.SCHEDULE,
                    DreameMowerProperty.SCHEDULE_CANCEL_REASON,
                    DreameMowerProperty.CRUISE_SCHEDULE,
                ]

                if not self.capability.disable_sensor_cleaning:
                    properties.extend(
                        [
                            DreameMowerProperty.SENSOR_DIRTY_LEFT,
                            DreameMowerProperty.SENSOR_DIRTY_TIME_LEFT,
                        ]
                    )

                if self._map_manager is not None:
                    properties.extend(
                        [
                            DreameMowerProperty.MAP_LIST,
                            DreameMowerProperty.RECOVERY_MAP_LIST,
                        ]
                    )
                    self._last_map_list_request = time.time()

                try:
                    self._request_properties(properties)
                except Exception as ex:
                    pass

                if self._protocol.prefer_cloud and self._protocol.dreame_cloud:
                    self.schedule_update(1, True)

    def _status_changed(self, previous_status: Any = None) -> None:
        if previous_status is not None:
            if previous_status in DreameMowerStatus._value2member_map_:
                previous_status = DreameMowerStatus(previous_status)

            status = self.get_property(DreameMowerProperty.STATUS)
            if (
                self._remote_control
                and status != DreameMowerStatus.REMOTE_CONTROL.value
                and previous_status != DreameMowerStatus.REMOTE_CONTROL.value
            ):
                self._remote_control = False

            if (
                not self.capability.cruising
                and status == DreameMowerStatus.BACK_HOME
                and previous_status == DreameMowerStatus.ZONE_CLEANING
                and self.status.started
            ):
                self.status.cleanup_started = False
                self.status.cleanup_completed = False
                self.status.go_to_zone.stop = True
                self._restore_go_to_zone(True)
            elif (
                not self.status.started
                and self.status.cleanup_started
                and not self.status.cleanup_completed
                and (self.status.status is DreameMowerStatus.BACK_HOME or not self.status.running)
            ):
                self.status.cleanup_started = False
                self.status.cleanup_completed = True
                self._cleaning_history_update = time.time()

                did = DreameMowerProperty.TASK_STATUS.value
                if did in self._property_update_callback:
                    for callback in self._property_update_callback[did]:
                        callback(self.status.task_status.value)
                self._property_changed()
            elif status == DreameMowerStatus.CHARGING.value and previous_status == DreameMowerStatus.BACK_HOME.value:
                self._cleaning_history_update = time.time()

            if previous_status == DreameMowerStatus.OTA.value:
                self._ready = False
                self.connect_device()

            if self._map_manager:
                self._map_manager.editor.refresh_map()

    def _charging_status_changed(self, previous_charging_status: Any = None) -> None:
        self._remote_control = False
        if previous_charging_status is not None:
            if self._map_manager:
                self._map_manager.editor.refresh_map()

            if (
                self._protocol.dreame_cloud
                and self.status.charging_status != DreameMowerChargingStatus.CHARGING_COMPLETED
            ):
                self.schedule_update(2, True)

    def _ai_obstacle_detection_changed(self, previous_ai_obstacle_detection: Any = None) -> None:
        """AI Detection property returns multiple values as json or int this function parses and sets the sub properties to memory"""
        ai_value = self.get_property(DreameMowerProperty.AI_DETECTION)
        changed = False
        if isinstance(ai_value, str):
            settings = json.loads(ai_value)
            if settings and self.ai_data is None:
                self.ai_data = {}

            for prop in DreameMowerStrAIProperty:
                if prop.value in settings:
                    value = settings[prop.value]
                    if prop.value in self._dirty_ai_data:
                        if (
                            self._dirty_ai_data[prop.name].value != value
                            and time.time() - self._dirty_ai_data[prop.name].update_time < self._discard_timeout
                        ):
                            _LOGGER.info(
                                "AI Property %s Value Discarded: %s <- %s",
                                prop.name,
                                self._dirty_ai_data[prop.name].value,
                                value,
                            )
                            del self._dirty_ai_data[prop.name]
                            continue
                        del self._dirty_ai_data[prop.name]

                    current_value = self.ai_data.get(prop.name)
                    if current_value != value:
                        if current_value is not None:
                            _LOGGER.info(
                                "AI Property %s Changed: %s -> %s",
                                prop.name,
                                current_value,
                                value,
                            )
                        else:
                            _LOGGER.info("AI Property %s Added: %s", prop.name, value)
                        changed = True
                        self.ai_data[prop.name] = value
        elif isinstance(ai_value, int):
            if self.ai_data is None:
                self.ai_data = {}

            for prop in DreameMowerAIProperty:
                bit = int(prop.value)
                value = (ai_value & bit) == bit
                if prop.name in self._dirty_ai_data:
                    if (
                        self._dirty_ai_data[prop.name].value != value
                        and time.time() - self._dirty_ai_data[prop.name].update_time < self._discard_timeout
                    ):
                        _LOGGER.info(
                            "AI Property %s Value Discarded: %s <- %s",
                            prop.name,
                            self._dirty_ai_data[prop.name].value,
                            value,
                        )
                        del self._dirty_ai_data[prop.name]
                        continue
                    del self._dirty_ai_data[prop.name]

                current_value = self.ai_data.get(prop.name)
                if current_value != value:
                    if current_value is not None:
                        _LOGGER.info(
                            "AI Property %s Changed: %s -> %s",
                            prop.name,
                            current_value,
                            value,
                        )
                    else:
                        _LOGGER.info("AI Property %s Added: %s", prop.name, value)
                    changed = True
                    self.ai_data[prop.name] = value

        if changed:
            self._last_change = time.time()
            if self._ready:
                self._property_changed()

        self.status.ai_policy_accepted = bool(
            self.status.ai_policy_accepted or self.status.ai_obstacle_detection or self.status.ai_obstacle_picture
        )

    def _auto_switch_settings_changed(self, previous_auto_switch_settings: Any = None) -> None:
        value = self.get_property(DreameMowerProperty.AUTO_SWITCH_SETTINGS)
        if isinstance(value, str) and len(value) > 2:
            cleangenius_changed = False
            try:
                settings = json.loads(value)
                settings_dict = {}

                if isinstance(settings, list):
                    for setting in settings:
                        settings_dict[setting["k"]] = setting["v"]
                elif "k" in settings:
                    settings_dict[settings["k"]] = settings["v"]

                if settings_dict and self.auto_switch_data is None:
                    self.auto_switch_data = {}

                changed = False
                for prop in DreameMowerAutoSwitchProperty:
                    if prop.value in settings_dict:
                        value = settings_dict[prop.value]

                        if prop.name in self._dirty_auto_switch_data:
                            if (
                                self._dirty_auto_switch_data[prop.name].value != value
                                and time.time() - self._dirty_auto_switch_data[prop.name].update_time
                                < self._discard_timeout
                            ):
                                _LOGGER.info(
                                    "Property %s Value Discarded: %s <- %s",
                                    prop.name,
                                    self._dirty_auto_switch_data[prop.name].value,
                                    value,
                                )
                                del self._dirty_auto_switch_data[prop.name]
                                continue
                            del self._dirty_auto_switch_data[prop.name]

                        current_value = self.auto_switch_data.get(prop.name)
                        if current_value != value:
                            if prop == DreameMowerAutoSwitchProperty.CLEANGENIUS:
                                cleangenius_changed = True

                            if current_value is not None:
                                _LOGGER.info(
                                    "Property %s Changed: %s -> %s",
                                    prop.name,
                                    current_value,
                                    value,
                                )
                            else:
                                _LOGGER.info("Property %s Added: %s", prop.name, value)
                            changed = True
                            self.auto_switch_data[prop.name] = value

                if changed:
                    self._last_change = time.time()
                    if self._ready and previous_auto_switch_settings is not None:
                        self._property_changed()
            except Exception as ex:
                _LOGGER.error("Failed to parse auto switch settings: %s", ex)

            if cleangenius_changed and self._map_manager and self._ready and previous_auto_switch_settings is not None:
                self._map_manager.editor.refresh_map()

    def _dnd_task_changed(self, previous_dnd_task: Any = None) -> None:
        dnd_tasks = self.get_property(DreameMowerProperty.DND_TASK)
        if dnd_tasks and dnd_tasks != "":
            self.status.dnd_tasks = json.loads(dnd_tasks)

    def _stream_status_changed(self, previous_stream_status: Any = None) -> None:
        stream_status = self.get_property(DreameMowerProperty.STREAM_STATUS)
        if stream_status and stream_status != "" and stream_status != "null":
            stream_status = json.loads(stream_status)
            if stream_status and stream_status.get("result") == 0:
                self.status.stream_session = stream_status.get("session")
                operation_type = stream_status.get("operType")
                operation = stream_status.get("operation")
                if operation_type:
                    if operation_type == "end" or operation == "end":
                        self.status.stream_status = DreameMowerStreamStatus.IDLE
                    elif operation_type == "start" or operation == "start":
                        if operation:
                            if operation == "monitor" or operation_type == "monitor":
                                self.status.stream_status = DreameMowerStreamStatus.VIDEO
                            elif operation == "intercom" or operation_type == "intercom":
                                self.status.stream_status = DreameMowerStreamStatus.AUDIO
                            elif operation == "recordVideo" or operation_type == "recordVideo":
                                self.status.stream_status = DreameMowerStreamStatus.RECORDING

    def _shortcuts_changed(self, previous_shortcuts: Any = None) -> None:
        shortcuts = self.get_property(DreameMowerProperty.SHORTCUTS)
        if shortcuts and shortcuts != "":
            shortcuts = json.loads(shortcuts)
            if shortcuts:
                # response = self.call_shortcut_action("GET_COMMANDS")
                new_shortcuts = {}
                for shortcut in shortcuts:
                    id = shortcut["id"]
                    running = (
                        False
                        if "state" not in shortcut
                        else bool(shortcut["state"] == "0" or shortcut["state"] == "1")
                    )
                    name = base64.decodebytes(shortcut["name"].encode("utf8")).decode("utf-8")
                    tasks = None
                    # response = self.call_shortcut_action("GET_COMMAND_BY_ID", {"id": id})
                    # if response and "out" in response:
                    #    data = response["out"]
                    #    if data and len(data):
                    #        if "value" in data[0] and data[0]["value"] != "":
                    #            tasks = []
                    #            for task in json.loads(data[0]["value"]):
                    #                segments = []
                    #                for segment in task:
                    #                    segments.append(ShortcutTask(segment_id=segment[0], suction_level=segment[1], water_volume=segment[2], cleaning_times=segment[3], cleaning_mode=segment[4]))
                    #                tasks.append(segments)
                    new_shortcuts[id] = Shortcut(id=id, name=name, running=running, tasks=tasks)
                self.status.shortcuts = new_shortcuts

    def _voice_assistant_language_changed(self, previous_voice_assistant_language: Any = None) -> None:
        value = self.get_property(DreameMowerProperty.VOICE_ASSISTANT_LANGUAGE)
        language_list = self.status.voice_assistant_language_list
        if value and len(value):
            language_list = VOICE_ASSISTANT_LANGUAGE_TO_NAME.copy()
            language_list.pop(DreameMowerVoiceAssistantLanguage.DEFAULT)
            language_list = {v: k for k, v in language_list.items()}
        elif DreameMowerVoiceAssistantLanguage.DEFAULT.value not in language_list:
            language_list = {v: k for k, v in VOICE_ASSISTANT_LANGUAGE_TO_NAME.items()}
        self.status.voice_assistant_language_list = language_list

    def _off_peak_charging_changed(self, previous_off_peak_charging: Any = None) -> None:
        off_peak_charging = self.get_property(DreameMowerProperty.OFF_PEAK_CHARGING)
        if off_peak_charging and off_peak_charging != "":
            self.status.off_peak_charging_config = json.loads(off_peak_charging)

    def _error_changed(self, previous_error: Any = None) -> None:
        if previous_error is not None and self.status.go_to_zone and self.status.has_error:
            self._restore_go_to_zone(True)

        if self._map_manager and previous_error is not None:
            self._map_manager.editor.refresh_map()

    def _battery_level_changed(self, previous_battery_level: Any = None) -> None:
        if self._map_manager and previous_battery_level is not None and self.status.battery_level == 100:
            self._map_manager.editor.refresh_map()

    def _build_map_from_cloud_data(self) -> None:
        """Build map data from cloud MAP batch keys for A1 Pro (no MQTT map support).

        **See `docs/research/cloud-map-geometry.md`** for the complete
        reference on cloud-frame units, boundary semantics, the two
        coordinate transforms used below, the forbidden-zone angle
        rotation, the midline-reflection bridge, and the charger-offset
        calibration. Every overlay added to this pipeline (live mower
        position, maintenance-point markers, session replay, …) must
        follow the same geometry rules.
        """
        if not self.cloud_connected:
            return

        from ..protocol.cloud_map_geom import _rotate_path_around_centroid  # noqa: F401 — imported at top of try for clarity

        try:
            map_keys = [f"MAP.{i}" for i in range(28)]
            response = self._protocol.cloud.get_batch_device_datas(map_keys)
            if not response:
                _LOGGER.warning("No MAP data from cloud")
                return

            # M_PATH.* userData — separate from MAP.* per apk. Array
            # of [x, y] pairs or null (segment delimiters); sentinel
            # [32767, -32768] = path break. Coordinates ~10x smaller
            # than MAP coords.
            mpath_keys = [f"M_PATH.{i}" for i in range(28)]
            try:
                mpath_response = self._protocol.cloud.get_batch_device_datas(mpath_keys)
            except Exception as ex:
                _LOGGER.debug("M_PATH fetch failed (non-fatal): %s", ex)
                mpath_response = None
            if mpath_response:
                mpath_parts = [mpath_response.get(f"M_PATH.{i}", "") for i in range(28)]
                mpath_raw = "".join(p for p in mpath_parts if p)
                if mpath_raw:
                    try:
                        mpath = json.loads(mpath_raw)
                        if isinstance(mpath, list):
                            self._cloud_mpath = mpath
                            _LOGGER.info(
                                "[M_PATH] received %d entries from cloud", len(mpath)
                            )
                    except (ValueError, TypeError) as ex:
                        _LOGGER.debug("M_PATH parse failed: %s", ex)

            raw_parts = []
            for i in range(28):
                val = response.get(f"MAP.{i}")
                if val:
                    raw_parts.append(val)
            if not raw_parts:
                return

            raw_json = "".join(raw_parts)
            decoder = json.JSONDecoder()
            map_json, _ = decoder.raw_decode(raw_json)
            if isinstance(map_json, list):
                # MAP data is wrapped: [json_string, ...]
                for item in map_json:
                    if isinstance(item, str):
                        try:
                            parsed = json.loads(item)
                            if isinstance(parsed, dict) and ("boundary" in parsed or "mowingAreas" in parsed):
                                map_json = parsed
                                break
                        except (json.JSONDecodeError, ValueError):
                            continue
                    elif isinstance(item, dict) and ("boundary" in item or "mowingAreas" in item):
                        map_json = item
                        break

            # One-shot schema dump per HA process, WARNING-level so users
            # running at `logger.default: warning` see it without bumping
            # a logger override. Goal: catalogue every top-level key the
            # Dreame cloud puts in the map payload so we can decide which
            # ones (beyond boundary/mowingAreas/forbiddenAreas/contours
            # we already parse) carry useful information. Rerun a new
            # fetch after an HA restart if you want to compare payloads
            # across sessions. Key shape: `type:<count-or-sample>`.
            if isinstance(map_json, dict) and not getattr(self, "_map_schema_logged", False):
                self._map_schema_logged = True
                def _shape(v):
                    if isinstance(v, dict):
                        return f"dict(keys={list(v.keys())[:10]})"
                    if isinstance(v, list):
                        head = f" head={v[0]!r}"[:80] if v else ""
                        return f"list(len={len(v)}{head})"
                    if isinstance(v, str):
                        return f"str(len={len(v)})" if len(v) > 60 else f"str={v!r}"
                    return f"{type(v).__name__}={v!r}"
                schema = {k: _shape(v) for k, v in sorted(map_json.items())}
                _LOGGER.warning(
                    "[MAP_SCHEMA] cloud MAP payload has %d top-level keys "
                    "(one-shot dump per HA process): %s",
                    len(schema),
                    schema,
                )
                # Per-key deep dump for keys we don't yet consume in the
                # decoder. Truncate values >2k chars so we don't blow out
                # the log buffer.
                _CONSUMED = {"boundary", "mowingAreas", "forbiddenAreas",
                             "md5sum", "mapIndex", "name", "hasBack",
                             "merged", "totalArea",
                             # Added 2026-04-24:
                             "contours",      # drawn as WALL outline (below)
                             "cleanPoints"}   # maintenance-point marker
                # Single multi-line WARNING so the whole dump survives
                # HA's log-UI dedupe (otherwise the 8 [MAP_KEY] lines
                # collapse into one displayed entry).
                map_lines = []
                for k in sorted(map_json.keys()):
                    if k in _CONSUMED:
                        continue
                    v = map_json[k]
                    s = repr(v)
                    if len(s) > 1500:
                        s = s[:1500] + f"... (truncated, full len={len(repr(v))})"
                    map_lines.append(f"  {k:<16} = {s}")
                if map_lines:
                    _LOGGER.warning(
                        "[MAP_KEYS] %d unconsumed top-level keys:\n%s",
                        len(map_lines),
                        "\n".join(map_lines),
                    )
                if isinstance(map_json, list):
                    _LOGGER.warning("MAP JSON: no usable entry found in list")
                    return
            boundary = map_json.get("boundary", {})
            # Cloud JSON sometimes returns boundary coords as floats (e.g.
            # after a scale/rotation was applied server-side). Our grid
            # arithmetic below is integer-only — downstream PIL polygon /
            # Image.new calls reject floats with
            # "'float' object cannot be interpreted as an integer".
            bx1_raw = int(boundary.get("x1", 0))
            by1_raw = int(boundary.get("y1", 0))
            bx2_raw = int(boundary.get("x2", 0))
            by2_raw = int(boundary.get("y2", 0))

            # Pre-rotate forbidden paths so we can include their post-
            # rotation corners in the image bbox. Otherwise rotated
            # exclusion zones that extend past the boundary get clipped
            # (user saw this 2026-04-19).
            #
            # Angle sign note: the cloud JSON stores the angle in a
            # coordinate convention that's mirror-flipped relative to
            # how the app renders (the app effectively mirrors the Y
            # axis before rotating, so a positive-angle shape in the
            # cloud draws as a negative-angle shape on screen). After
            # we apply the X + Y midline reflections below, the
            # exclusion zone is in the right POSITION but its rotation
            # handedness remains from the cloud — producing a flipped-
            # along-X-axis rectangle. Negating the angle up front fixes
            # the tilt direction before reflection so final output
            # matches the app.
            forbidden_pre = map_json.get("forbiddenAreas", {}).get("value", [])
            rotated_forbidden: list[tuple[int, list[dict]]] = []
            for entry in forbidden_pre:
                if isinstance(entry, list) and len(entry) >= 2:
                    zid = entry[0]
                    zdata = entry[1]
                elif isinstance(entry, dict):
                    zid = entry.get("id", 0)
                    zdata = entry
                else:
                    continue
                path = zdata.get("path", [])
                if not path:
                    continue
                raw_angle = zdata.get("angle")
                rot_angle = -raw_angle if raw_angle is not None else None
                rp = _rotate_path_around_centroid(path, rot_angle)
                rotated_forbidden.append((zid, rp))

            # Expand the bbox to include every rotated exclusion corner.
            bx1 = bx1_raw
            by1 = by1_raw
            bx2 = bx2_raw
            by2 = by2_raw
            for _zid, rp in rotated_forbidden:
                for pt in rp:
                    x, y = int(pt["x"]), int(pt["y"])
                    if x < bx1:
                        bx1 = x
                    if x > bx2:
                        bx2 = x
                    if y < by1:
                        by1 = y
                    if y > by2:
                        by2 = y

            grid_size = 50
            width = int(max(1, (bx2 - bx1) // grid_size + 1))
            height = int(max(1, (by2 - by1) // grid_size + 1))

            pixel_type = np.full((width, height), MapPixelType.OUTSIDE.value, dtype=np.uint8)

            segments = {}
            mowing_areas = map_json.get("mowingAreas", {}).get("value", [])
            for entry in mowing_areas:
                if isinstance(entry, list) and len(entry) >= 2:
                    zone_id = entry[0]
                    zone_data = entry[1]
                elif isinstance(entry, dict):
                    zone_id = entry.get("id", 1)
                    zone_data = entry
                else:
                    continue

                path = zone_data.get("path", [])
                name = zone_data.get("name", f"Zone {zone_id}")

                if not path or zone_id < 1 or zone_id > 62:
                    continue

                poly_points = []
                for pt in path:
                    # Mirror cloud +X horizontally (user-confirmed 2026-04-19:
                    # the lawn polygon rendered mirrored vs the app unless we
                    # flip X). forbiddenAreas does NOT get this flip — its
                    # path is already in the correct visual orientation once
                    # the `angle` rotation is applied.
                    px = int((bx2 - int(pt["x"])) // grid_size)
                    py = int((by2 - int(pt["y"])) // grid_size)
                    poly_points.append((px, py))

                if len(poly_points) >= 3:
                    img = Image.new("L", (width, height), 0)
                    draw = ImageDraw.Draw(img)
                    draw.polygon(poly_points, fill=zone_id)
                    mask = np.array(img).T
                    pixel_type[mask > 0] = zone_id

                xs = [int(pt["x"]) for pt in path]
                ys = [int(pt["y"]) for pt in path]
                seg = Segment(
                    segment_id=zone_id,
                    x0=min(xs), y0=min(ys),
                    x1=max(xs), y1=max(ys),
                    x=sum(xs) // len(xs),
                    y=sum(ys) // len(ys),
                    custom_name=name,
                )
                seg.color_index = (zone_id - 1) % 4
                segments[zone_id] = seg

            # Use the pre-rotated forbidden paths (computed above for bbox).
            # The downstream renderer's `Area.to_img` uses un-flipped
            # cloud coords, which ended up placing the exclusion + dock
            # at the wrong Y (user reported "flip around X axis" 2026-04-19).
            # Reflect BOTH axes through the cloud-frame midlines so the
            # no-go rectangle lines up with the lawn's X+Y-flipped mask
            # and with the dock icon (same reflection applied there).
            # User reported 2026-04-19 after the Y-only reflection that
            # the exclusion was still too far to the right — X reflection
            # brings it back.
            x_reflect = bx1 + bx2
            y_reflect = by1 + by2
            no_go_areas = []
            for _zid, rotated_path in rotated_forbidden:
                if len(rotated_path) >= 4:
                    # Area objects drive the renderer's semi-transparent
                    # `no_go` colour (so the lawn zone below stays
                    # visible). We keep them un-painted in pixel_type
                    # because filling there would render as opaque grey.
                    no_go_areas.append(Area(
                        int(x_reflect - rotated_path[0]["x"]), int(y_reflect - rotated_path[0]["y"]),
                        int(x_reflect - rotated_path[1]["x"]), int(y_reflect - rotated_path[1]["y"]),
                        int(x_reflect - rotated_path[2]["x"]), int(y_reflect - rotated_path[2]["y"]),
                        int(x_reflect - rotated_path[3]["x"]), int(y_reflect - rotated_path[3]["y"]),
                    ))
                # However, the renderer also auto-crops the canvas to
                # the bbox of non-OUTSIDE pixels in pixel_type — so if we
                # only paint the lawn, the exclusion overlay gets clipped
                # when it extends past the lawn. Plant each rotated
                # corner as a single WALL pixel inside the pixel mask:
                # four pixels per corner is enough to stretch the crop
                # bbox to cover the exclusion, and they all land UNDER
                # the semi-transparent red overlay so they're invisible.
                for pt in rotated_path:
                    cx = int((bx2 - int(pt["x"])) // grid_size)
                    cy = int((by2 - int(pt["y"])) // grid_size)
                    if 0 <= cx < width and 0 <= cy < height:
                        pixel_type[cx, cy] = MapPixelType.WALL.value

            contours = map_json.get("contours", {}).get("value", [])
            for entry in contours:
                if isinstance(entry, list) and len(entry) >= 2:
                    zone_data = entry[1]
                elif isinstance(entry, dict):
                    zone_data = entry
                else:
                    continue

                path = zone_data.get("path", [])
                if len(path) < 2:
                    continue

                line_points = []
                for pt in path:
                    # Same X-mirror as mowingAreas (see note there).
                    px = int((bx2 - int(pt["x"])) // grid_size)
                    py = int((by2 - int(pt["y"])) // grid_size)
                    line_points.append((px, py))

                img = Image.new("L", (width, height), 0)
                draw = ImageDraw.Draw(img)
                for i in range(len(line_points)):
                    p1 = line_points[i]
                    p2 = line_points[(i + 1) % len(line_points)]
                    # 2 px wide so the real grass outline stays visible over
                    # top of the coarser mowingAreas zone fills. 1 px got
                    # swallowed by zone colour on steep contour segments.
                    draw.line([p1, p2], fill=255, width=2)
                mask = np.array(img).T
                pixel_type[mask > 0] = MapPixelType.WALL.value

            # cleanPoints: user-placed Maintenance Points. The app allows
            # multiple points and the user picks which one to visit when
            # dispatching a maintenance run — so we collect ALL of them.
            # Coords stay in raw cloud-frame mm so the go-to service can
            # feed them straight into `device.go_to(x, y)` without
            # re-reflecting.
            clean_points = map_json.get("cleanPoints", {}).get("value", [])
            mps: list[dict] = []
            for entry in clean_points:
                if isinstance(entry, list) and len(entry) >= 2:
                    point_id = entry[0]
                    point_data = entry[1]
                elif isinstance(entry, dict):
                    point_id = entry.get("id", 1)
                    point_data = entry
                else:
                    continue
                point_path = point_data.get("path") or []
                if not point_path:
                    continue
                try:
                    pt = point_path[0]
                    resolved_id = (
                        int(point_id)
                        if isinstance(point_id, (int, float))
                        else int(point_data.get("id", len(mps) + 1))
                    )
                    mps.append({
                        "id": resolved_id,
                        "x_mm": int(pt["x"]),
                        "y_mm": int(pt["y"]),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
            self._maintenance_points = mps

            dimensions = MapImageDimensions(
                top=by1,
                left=bx1,
                height=height,
                width=width,
                grid_size=grid_size,
            )

            map_data = MapData()
            map_data.map_id = 1
            map_data.frame_id = 1
            map_data.frame_type = 73
            map_data.dimensions = dimensions
            map_data.pixel_type = pixel_type
            map_data.segments = segments if segments else None
            map_data.no_go_areas = no_go_areas if no_go_areas else None
            map_data.empty_map = len(segments) == 0
            # Leave `saved_map` False so the downstream renderer's
            # `render_areas` path runs and paints the no-go zones with
            # the semi-transparent `no_go` colour scheme (opacity ~50/255
            # by default) rather than opaque grey WALL pixels. The map
            # IS persistent in a loose sense, but saved_map=True is the
            # renderer's "skip overlays" branch, which we don't want.
            map_data.saved_map = False
            map_data.saved_map_status = 2
            # Only bump `last_updated` when the cloud map's content
            # actually changed. Earlier code used the cloud-provided
            # `md5sum` top-level field, but 2026-04-20 evidence (11
            # camera state-changes over the 19:28-19:44 Positioning-
            # Failed episode, each aligned to an unrelated s2p1/s2p2
            # transition) proved the cloud's md5 is NOT stable across
            # fetches — it apparently includes volatile state (robot
            # position, active task, …) so every state-transition-
            # triggered poll ended up bumping `last_updated` and
            # flooding HA's logbook with "Current Map changed to …"
            # lines even when the polygons hadn't moved.
            #
            # Compute our own hash instead, over just the structurally
            # stable fields: zones, no-go areas, dimensions, and
            # charger position. Any real map edit changes one of
            # these; ephemeral state doesn't.
            import hashlib
            stable_repr = json.dumps({
                "zones": sorted(
                    [
                        (
                            getattr(seg, "segment_id", None),
                            round(getattr(seg, "x0", 0) or 0, 3),
                            round(getattr(seg, "y0", 0) or 0, 3),
                            round(getattr(seg, "x1", 0) or 0, 3),
                            round(getattr(seg, "y1", 0) or 0, 3),
                        )
                        for seg in (map_data.segments or {}).values()
                    ]
                ) if isinstance(map_data.segments, dict) else [],
                "no_go_areas": [
                    (getattr(a, "x0", 0), getattr(a, "y0", 0),
                     getattr(a, "x1", 0), getattr(a, "y1", 0),
                     getattr(a, "x2", 0), getattr(a, "y2", 0),
                     getattr(a, "x3", 0), getattr(a, "y3", 0))
                    for a in (map_data.no_go_areas or [])
                ],
                "dims": (
                    int(getattr(map_data.dimensions, "width", 0) or 0),
                    int(getattr(map_data.dimensions, "height", 0) or 0),
                    int(getattr(map_data.dimensions, "grid_size", 0) or 0),
                ),
                "charger": (
                    round(float(getattr(map_data, "charger_position", None) is not None
                                and getattr(map_data.charger_position, "x", 0)), 2)
                    if getattr(map_data, "charger_position", None) is not None else None,
                    round(float(getattr(map_data, "charger_position", None) is not None
                                and getattr(map_data.charger_position, "y", 0)), 2)
                    if getattr(map_data, "charger_position", None) is not None else None,
                ),
            }, sort_keys=True).encode()
            new_md5 = hashlib.md5(stable_repr).hexdigest()
            prior_md5 = getattr(self, "_last_cloud_map_md5", None)
            if prior_md5 == new_md5 and self._map_manager and getattr(
                self._map_manager._map_data, "last_updated", None
            ):
                # Content unchanged → preserve the prior timestamp so
                # HA doesn't log a spurious state change.
                map_data.last_updated = self._map_manager._map_data.last_updated
            else:
                map_data.last_updated = time.time()
                self._last_cloud_map_md5 = new_md5
            map_data.rotation = 0
            # Cloud-frame (0, 0) is where the mower's nose meets the
            # charging station as it enters the dock — NOT the physical
            # centre of the charger. The station body extends ~40 cm
            # further in +X (mower-frame), i.e. house-ward. User
            # observed 2026-04-19 (IMG_4422.PNG) that without the
            # offset the dock icon sits on the very edge of the mowing
            # boundary, whereas the app places the charger glyph a bit
            # outside the lawn where the physical unit sits. Shifting
            # the icon by half the known station length (400 mm) along
            # +X matches the app.
            #
            # Our lawn mask uses (bx2 - x)/grid for X and (by2 - y)/grid
            # for Y. The renderer's Point.to_img interprets raw cloud
            # coords via its own transform, so the input Point must be
            # reflected through (bx1+bx2, by1+by2) to land in the same
            # place. A +400 mm shift in cloud-X (house-ward) becomes
            # `- 400` on the reflected X axis.
            # User-tuned 2026-04-19: 400 mm landed the icon on the lawn
            # border (where the mower enters the dock). Another 400 mm
            # puts it at the physical station centre — user confirmed
            # "direction was fine, add the other 40 cm as well".
            CHARGER_OFFSET_MM = 800  # full Dreame A2 charging-station length
            map_data.charger_position = Point(
                bx1 + bx2 - CHARGER_OFFSET_MM,
                by1 + by2,
                0,
            )
            # Seed `robot_position` at the charger so the renderer's
            # robot-icon layer (map.py:4838 gating on `map_data.robot_position`)
            # has something to draw when the mower is docked. The cloud
            # MAP.* JSON doesn't include a robot position — the upstream
            # binary-blob decoder populated it from MQTT map pushes that
            # the A2 never emits. Without this seed the mower icon only
            # appears once s1p4 live telemetry has arrived, i.e. never
            # while docked. Live updates during mowing overwrite this
            # via the coordinator's position tracking; Manual mode
            # (no s1p4 broadcast) and dock-idle fall back to this
            # charger-relative value, which is factually correct for
            # those states (user 2026-04-20: "if state is Docked or
            # Charging we know it is in the charger location"). See
            # docs/research/g2408-protocol.md §Manual mode for the
            # no-telemetry caveat.
            map_data.robot_position = Point(
                map_data.charger_position.x,
                map_data.charger_position.y,
                0,
            )
            # Publish the cloud-frame midline reflections so overlay
            # consumers (the camera's TrailLayer) can align themselves
            # to the same X+Y-flipped frame the lawn mask is drawn in.
            # Calibration_points live in the un-flipped frame (per
            # DreameMowerMapRenderer._calculate_calibration_points),
            # so without this hint any trail drawn through calibration
            # lands on the opposite X of the lawn.
            map_data.cloud_frame_x_reflect_mm = float(bx1 + bx2)
            map_data.cloud_frame_y_reflect_mm = float(by1 + by2)

            if self._map_manager:
                self._map_manager._map_data = map_data
                self._map_manager._saved_map_data[1] = map_data
                self._map_manager._selected_map_id = 1
                self._map_manager._current_map_id = 1
                self._map_manager._ready = True
                _LOGGER.info(
                    "Map built from cloud data: %dx%d, %d zones, %d no-go areas",
                    width, height, len(segments), len(no_go_areas),
                )

        except Exception as ex:
            _LOGGER.warning("Failed to build map from cloud data: %s", ex)

    def _schedule_cloud_map_poll(self, reason: str) -> None:
        """Re-pull the cloud MAP.* dataset and rebuild the camera image.

        The g2408 only pushes an MQTT map-refresh signal on auto-recharge
        legs (`s6p1 = 300`). Session starts, manual BUILDING sessions, and
        app-driven zone/exclusion edits are silent on that channel, so
        without proactive polling the HA camera can drift out of sync
        with the mower's actual map for a whole run. This helper is
        called at those silent inflection points; the md5sum dedupe
        inside `_build_map_from_cloud_data` makes it a no-op if nothing
        changed upstream.

        Called from the MQTT paho worker thread, so the cloud HTTP call
        is fine to do inline. Errors are caught here so a transient
        cloud hiccup at session start doesn't spam the property pipeline.
        """
        if not self.cloud_connected:
            _LOGGER.debug(
                "[MAP_POLL] skipped (cloud not connected) — trigger=%s", reason
            )
            return
        _LOGGER.info("[MAP_POLL] rebuilding cloud map — trigger=%s", reason)
        try:
            self._build_map_from_cloud_data()
            if self._map_manager:
                self._map_manager._map_data_changed()
            self._property_changed()
        except Exception as ex:  # pragma: no cover — defensive
            _LOGGER.warning(
                "[MAP_POLL] rebuild failed (trigger=%s): %s", reason, ex
            )

    def _populate_stats_from_history(self) -> None:
        """Calculate cumulative stats from cloud event history when siid:12 properties are unavailable."""
        if self.get_property(DreameMowerProperty.CLEANING_COUNT) is not None:
            return

        if not self.cloud_connected:
            return

        try:
            diid = DIID(DreameMowerProperty.STATUS, self.property_mapping)
            result = self._protocol.cloud.get_device_event(diid, 200, 0)
            if not result:
                return

            total_time = 0
            total_area = 0
            count = 0
            first_date = None

            for data in result:
                raw = json.loads(data.get("history") or data.get("value", "[]"))
                props = {item["piid"]: item["value"] for item in raw if "piid" in item and "value" in item}

                duration = props.get(2, 0)
                area = props.get(3, 0)
                timestamp = props.get(8, 0)

                if props:
                    total_time += duration
                    total_area += area
                    count += 1
                    if timestamp and (first_date is None or timestamp < first_date):
                        first_date = timestamp

            if count > 0:
                self.data[DreameMowerProperty.CLEANING_COUNT.value] = count
                self.data[DreameMowerProperty.TOTAL_CLEANING_TIME.value] = total_time
                self.data[DreameMowerProperty.TOTAL_CLEANED_AREA.value] = total_area // 100
                if first_date:
                    self.data[DreameMowerProperty.FIRST_CLEANING_DATE.value] = first_date
                _LOGGER.info(
                    "Stats calculated from history: %d sessions, %d min, %d area, first=%s",
                    count, total_time, total_area, first_date,
                )
        except Exception as ex:
            _LOGGER.warning("Failed to populate stats from history: %s", ex)

    def _request_cleaning_history(self) -> None:
        """Get and parse the cleaning history from cloud event data and set it to memory"""
        if (
            self.cloud_connected
            and self._cleaning_history_update != 0
            and (
                self._cleaning_history_update == -1
                or self.status._cleaning_history is None
                or (
                    time.time() - self._cleaning_history_update >= 5
                    and self.status.task_status is DreameMowerTaskStatus.COMPLETED
                )
            )
        ):
            self._cleaning_history_update = 0

            _LOGGER.info("Get Cleaning History")
            try:
                # Limit the results
                max = 25
                total = self.get_property(DreameMowerProperty.CLEANING_COUNT)
                start = self.get_property(DreameMowerProperty.FIRST_CLEANING_DATE)

                if total is None:
                    total = 5
                if start is None:
                    start = int(time.time())
                limit = 40
                if total < max:
                    limit = total + max

                changed = False
                # Cleaning history is generated from events of status property that has been sent to cloud by the device when it changed
                result = self._protocol.cloud.get_device_event(
                    DIID(DreameMowerProperty.STATUS, self.property_mapping),
                    limit,
                    start,
                )
                if result:
                    cleaning_history = []
                    history_size = 0
                    for data in result:
                        history = CleaningHistory(
                            json.loads(data["history"] if "history" in data else data["value"]),
                            self.property_mapping,
                        )
                        if history_size > 0 and cleaning_history[-1].date == history.date:
                            continue

                        if history.cleanup_method == CleanupMethod.CUSTOMIZED_CLEANING and self.capability.cleangenius:
                            history.cleanup_method = CleanupMethod.DEFAULT_MODE

                        cleaning_history.append(history)
                        history_size = history_size + 1
                        if history_size >= max or history_size >= total:
                            break

                    if self.status._cleaning_history != cleaning_history:
                        _LOGGER.info("Cleaning History Changed")
                        self.status._cleaning_history = cleaning_history
                        self.status._cleaning_history_attrs = None
                        if cleaning_history:
                            self.status._last_cleaning_time = cleaning_history[0].date.replace(
                                tzinfo=datetime.now().astimezone().tzinfo
                            )
                        changed = True

                if changed:
                    if self._ready:
                        for k, v in copy.deepcopy(self.status._history_map_data).items():
                            found = False
                            if self.status._cleaning_history:
                                for item in self.status._cleaning_history:
                                    if k in item.file_name:
                                        found = True
                                        break

                            if found:
                                continue

                            if self.status._cruising_history:
                                for item in self.status._cruising_history:
                                    if k in item.file_name:
                                        found = True
                                        break

                            if found:
                                continue

                            del self.status._history_map_data[k]

                        if self._map_manager:
                            self._map_manager.editor.refresh_map()
                        self._property_changed()

            except Exception as ex:
                _LOGGER.warning("Get Cleaning History failed!: %s", ex)

    def _property_changed(self) -> None:
        """Call external listener when a property changed"""
        if self._update_callback:
            self._update_callback()

    def _map_changed(self) -> None:
        """Call external listener when a map changed"""
        map_data = self.status.current_map
        if self._map_select_time:
            self._map_select_time = None
        if map_data and self.status.started:
            if self.status.go_to_zone is None and not self.status._capability.cruising and self.status.zone_cleaning:
                if map_data.active_areas and len(map_data.active_areas) == 1:
                    area = map_data.active_areas[0]
                    size = map_data.dimensions.grid_size
                    if area.check_size(size):
                        new_cleaning_mode = DreameMowerCleaningMode.MOWING.value

                        size = int(map_data.dimensions.grid_size / 2)
                        self.status.go_to_zone = GoToZoneSettings(
                            x=area.x0 + size,
                            y=area.y0 + size,
                            stop=bool(not self._map_manager.ready),
                            size=size,
                            cleaning_mode=new_cleaning_mode,
                        )
                        self._map_manager.editor.set_active_areas([])
                    else:
                        self.status.go_to_zone = False
                else:
                    self.status.go_to_zone = False

            if self.status.go_to_zone:
                position = map_data.robot_position
                if position:
                    size = self.status.go_to_zone.size
                    x = self.status.go_to_zone.x
                    y = self.status.go_to_zone.y
                    if (
                        position.x >= x - size
                        and position.x <= x + size
                        and position.y >= y - size
                        and position.y <= y + size
                    ):
                        self._restore_go_to_zone(True)

            if self.status.docked != map_data.docked and self._protocol.prefer_cloud:
                self.schedule_update(self._update_interval, True)

        if self._map_manager.ready:
            self._property_changed()

    def _update_failed(self, ex) -> None:
        """Call external listener when update failed"""
        if self._error_callback:
            self._error_callback(ex)

    def _action_update_task(self) -> None:
        self._update_task(True)

    def _update_task(self, force_request_properties=False) -> None:
        """Timer task for updating properties periodically"""
        self._update_timer = None
        try:
            self.update(force_request_properties)
            if self._ready:
                self.available = True
            self._update_fail_count = 0
        except Exception as ex:
            self._update_fail_count = self._update_fail_count + 1
            if self.available:
                self._last_update_failed = time.time()
                if self._update_fail_count <= 3:
                    _LOGGER.debug(
                        "Update failed, retrying %s: %s",
                        self._update_fail_count,
                        str(ex),
                    )
                elif self._ready:
                    _LOGGER.warning("Update Failed: %s", str(ex))
                    self.available = False
                    self._update_failed(ex)

        if not self.disconnected:
            self.schedule_update(self._update_interval)

    def _set_go_to_zone(self, x, y, size):
        current_cleaning_mode = int(self.status.cleaning_mode.value)

        new_cleaning_mode = None

        cleaning_mode = DreameMowerCleaningMode.MOWING.value

        if current_cleaning_mode != cleaning_mode:
            new_cleaning_mode = cleaning_mode
            current_cleaning_mode = DreameMowerCleaningMode.MOWING.value

        self.status.go_to_zone = GoToZoneSettings(
            x=x,
            y=y,
            stop=True,
            cleaning_mode=current_cleaning_mode,
            size=size,
        )

    def _restore_go_to_zone(self, stop=False):
        if self.status.go_to_zone is not None:
            if self.status.go_to_zone:
                stop = stop and self.status.go_to_zone.stop
                cleaning_mode = self.status.go_to_zone.cleaning_mode
                self.status.go_to_zone = None
                if stop:
                    self.schedule_update(10, True)
                    try:
                        mapping = self.action_mapping[DreameMowerAction.STOP]
                        self._protocol.action(mapping["siid"], mapping["aiid"])
                    except:
                        pass

                try:
                    self._cleaning_history_update = time.time()
                    if cleaning_mode is not None and self.status.cleaning_mode.value != cleaning_mode:
                        self._update_cleaning_mode(cleaning_mode)

                    if stop and self.status.started:
                        self._update_status(DreameMowerTaskStatus.COMPLETED, DreameMowerStatus.STANDBY)
                except:
                    pass

                if self._protocol.dreame_cloud:
                    self.schedule_update(3, True)
            else:
                self.status.go_to_zone = None

    @staticmethod
    def split_group_value(value: int, mop_pad_lifting: bool = False) -> list[int]:
        if value is not None:
            value_list = []
            value_list.append((value & 3) if mop_pad_lifting else (value & 1))
            byte1 = value >> 8
            byte1 = byte1 & -769
            value_list.append(byte1)
            value_list.append(value >> 16)
            return value_list

    @staticmethod
    def combine_group_value(values: list[int]) -> int:
        if values and len(values) == 3:
            return ((((0 ^ values[2]) << 8) ^ values[1]) << 8) ^ values[0]

    def connect_device(self) -> None:
        """Connect to the device api."""
        _LOGGER.info("Connecting to device")
        info = self._protocol.connect(self._message_callback, self._connected_callback)
        if info:
            self.info = DreameMowerDeviceInfo(info)
            if self.mac is None:
                self.mac = self.info.mac_address

            # Apply model-specific property-mapping overlay. For g2408 this
            # corrects siid/piid divergences from upstream's A1-Pro-centric
            # mapping (most notably STATE<->ERROR swap at siid=2). For other
            # models the overlay is a no-op and the class-level default
            # remains in effect.
            from .types import property_mapping_for_model
            self.property_mapping = property_mapping_for_model(self.info.model)
            _LOGGER.info(
                "Connected to device: %s %s",
                self.info.model,
                self.info.firmware_version,
            )

            self._last_settings_request = time.time()
            self._last_map_list_request = self._last_settings_request
            self._dirty_data = {}
            self._dirty_auto_switch_data = {}
            self._dirty_ai_data = {}
            try:
                self._request_properties()
            except Exception as ex:
                _LOGGER.warning(
                    "Initial property request failed (MQTT will provide updates): %s", ex)
            # Proactively query s2p56 (g2408 session-task status) so
            # `device.status.started` is correct on startup. The
            # property is normally push-only on change, so after an
            # HA reboot mid-session the integration would otherwise
            # see `started=False` until the next mower-driven event
            # (often not until the resume-from-charging minutes
            # later). The Live Map's Latest view and the Session
            # Active binary sensor both depend on this, and without
            # it users rebooting mid-mow see yesterday's archive
            # replayed instead of the ongoing run.
            try:
                result = self._protocol.get_properties(
                    [{"did": "2.56", "siid": 2, "piid": 56}]
                )
                if isinstance(result, list) and result:
                    param = result[0]
                    if isinstance(param, dict) and param.get("code") == 0:
                        self._handle_session_status(param.get("value"))
            except Exception as ex:
                _LOGGER.debug("s2p56 startup probe failed: %s", ex)
            self._last_update_failed = None

            if self.device_connected and self._protocol.cloud is not None and (not self._ready or not self.available):
                if self._map_manager:
                    model = self.info.model.split(".")
                    if len(model) == 3:
                        for k, v in json.loads(
                            zlib.decompress(base64.b64decode(DEVICE_KEY), zlib.MAX_WBITS | 32)
                        ).items():
                            if model[2] in v:
                                self._map_manager.set_aes_iv(k)
                                break
                    self._map_manager.set_capability(self.capability)
                    self._map_manager.set_update_interval(self._map_update_interval)
                    self._map_manager.set_device_running(
                        self.status.running,
                        self.status.docked and not self.status.started,
                    )

                    if self.status.current_map is None:
                        self._map_manager.schedule_update(15)
                        try:
                            self._map_manager.update()
                            self._last_map_request = self._last_settings_request
                        except Exception as ex:
                            _LOGGER.error("Initial map update failed! %s", str(ex))
                        self._map_manager.schedule_update()
                    else:
                        self.update_map()

                    if self._map_manager._map_data is None or (
                        self._map_manager._map_data and
                        self._map_manager._map_data.pixel_type is None
                    ):
                        self._build_map_from_cloud_data()

                if self.cloud_connected:
                    self._populate_stats_from_history()
                    self._cleaning_history_update = -1
                    self._request_cleaning_history()
                    if (self.capability.ai_detection and not self.status.ai_policy_accepted) or True:
                        try:
                            prop = "prop.s_ai_config"
                            response = self._protocol.cloud.get_batch_device_datas([prop])
                            if response and prop in response and response[prop]:
                                value = json.loads(response[prop])
                                self.status.ai_policy_acepted = (
                                    value.get("privacyAuthed")
                                    if "privacyAuthed" in value
                                    else value.get("aiPrivacyAuthed")
                                )
                        except:
                            pass

            if not self.available:
                self.available = True

            if not self._ready:
                self._ready = True
            else:
                self._property_changed()

    def connect_cloud(self) -> None:
        """Connect to the cloud api."""
        if self._protocol.cloud and not self._protocol.cloud.logged_in:
            self._protocol.cloud.login()
            if self._protocol.cloud.logged_in is False:
                if self._protocol.cloud.two_factor_url:
                    self.two_factor_url = self._protocol.cloud.two_factor_url
                    self._property_changed()
                self._map_manager.schedule_update(-1)
            elif self._protocol.cloud.logged_in:
                if self.two_factor_url:
                    self.two_factor_url = None
                    self._property_changed()

                if self._protocol.connected:
                    self._map_manager.schedule_update(5)

                self.token, self.host = self._protocol.cloud.get_info(self.mac)
                if not self._protocol.dreame_cloud:
                    self._protocol.set_credentials(self.host, self.token, self.mac, self.account_type)

    def disconnect(self) -> None:
        """Disconnect from device and cancel timers"""
        _LOGGER.info("Disconnect")
        self.disconnected = True
        self.schedule_update(-1)
        self._protocol.disconnect()
        if self._map_manager:
            self._map_manager.disconnect()
        self._property_changed()

    def listen(self, callback, property: DreameMowerProperty = None) -> None:
        """Set callback functions for external listeners"""
        if callback is None:
            self._update_callback = None
            self._property_update_callback = {}
            return

        if property is None:
            self._update_callback = callback
        else:
            if property.value not in self._property_update_callback:
                self._property_update_callback[property.value] = []
            self._property_update_callback[property.value].append(callback)

    def listen_error(self, callback) -> None:
        """Set error callback function for external listeners"""
        self._error_callback = callback

    def attach_mqtt_archive(self, archive) -> None:
        """Opt in to raw-MQTT JSONL archival.

        The archive is held on the device so the protocol layer can be
        discovered at attach time (cloud vs local, which exposes the
        MQTT client). Any subsequent MQTT message handled by
        ``_on_client_message`` is mirrored into the archive before
        JSON-decoding so even undecodable payloads land on disk.
        """
        self._mqtt_archive = archive
        if self._protocol is not None:
            self._protocol.attach_mqtt_archive(archive)

    def schedule_update(self, wait: float = None, force_request_properties=False) -> None:
        """Schedule a device update for future"""
        if wait == None:
            wait = self._update_interval

        if self._update_timer is not None:
            self._update_timer.cancel()
            del self._update_timer
            self._update_timer = None

        if wait >= 0:
            self._update_timer = Timer(
                wait, self._action_update_task if force_request_properties else self._update_task
            )
            self._update_timer.start()

    def get_property(
        self,
        prop: (
            DreameMowerProperty | DreameMowerAutoSwitchProperty | DreameMowerStrAIProperty | DreameMowerAIProperty
        ),
    ) -> Any:
        """Get a device property from memory"""
        if isinstance(prop, DreameMowerAutoSwitchProperty):
            return self.get_auto_switch_property(prop)
        if isinstance(prop, DreameMowerStrAIProperty) or isinstance(prop, DreameMowerAIProperty):
            return self.get_ai_property(prop)
        if prop is not None and prop.value in self.data:
            return self.data[prop.value]
        return None

    def get_auto_switch_property(self, prop: DreameMowerAutoSwitchProperty) -> int:
        """Get a device auto switch property from memory"""
        if self.capability.auto_switch_settings and self.auto_switch_data:
            if prop is not None and prop.name in self.auto_switch_data:
                return int(self.auto_switch_data[prop.name])
        return None

    def get_ai_property(self, prop: DreameMowerStrAIProperty | DreameMowerAIProperty) -> bool:
        """Get a device AI property from memory"""
        if self.capability.ai_detection and self.ai_data:
            if prop is not None and prop.name in self.ai_data:
                return bool(self.ai_data[prop.name])
        return None

    def set_property_value(self, prop: str, value: Any):
        if prop is not None and value is not None:
            set_fn = "set_" + prop.lower()
            if hasattr(self, set_fn):
                set_fn = getattr(self, set_fn)
            else:
                set_fn = None

            prop = prop.upper()
            if prop in DreameMowerProperty.__members__:
                prop = DreameMowerProperty(DreameMowerProperty[prop])
                if prop not in self._read_write_properties:
                    raise InvalidActionException("Invalid property")
            elif prop in DreameMowerAutoSwitchProperty.__members__:
                prop = DreameMowerAutoSwitchProperty(DreameMowerAutoSwitchProperty[prop])
            elif prop in DreameMowerAIProperty.__members__:
                prop = DreameMowerAIProperty(DreameMowerAIProperty[prop])
            elif prop in DreameMowerStrAIProperty.__members__:
                prop = DreameMowerStrAIProperty(DreameMowerStrAIProperty[prop])
            elif set_fn is None:
                raise InvalidActionException("Invalid property")

            if set_fn is None and self.get_property(prop) is None:
                raise InvalidActionException("Invalid property")

            prop_name = prop.lower() if isinstance(prop, str) else prop.name

            if (
                (
                    self.status.started
                    or not (
                        prop is DreameMowerProperty.CLEANING_MODE
                        or prop is DreameMowerAutoSwitchProperty.CLEANING_ROUTE
                    )
                )
                and prop_name in PROPERTY_AVAILABILITY
                and not PROPERTY_AVAILABILITY[prop_name](self)
            ):
                raise InvalidActionException("Property unavailable")

            def get_int_value(enum, value, enum_list=None):
                if isinstance(value, str):
                    value = value.upper()
                    if value.isnumeric():
                        value = int(value)
                    elif value in enum.__members__:
                        value = enum[value].value
                        if enum_list is None:
                            return value

                if isinstance(value, int):
                    if enum_list is None:
                        if value in enum._value2member_map_:
                            return value
                    elif value in enum_list.values():
                        return value

            if prop is DreameMowerProperty.CLEANING_MODE:
                value = get_int_value(DreameMowerCleaningMode, value)
            elif prop is DreameMowerProperty.VOICE_ASSISTANT_LANGUAGE:
                value = get_int_value(
                    DreameMowerVoiceAssistantLanguage, value, self.status.voice_assistant_language_list
                )
            elif prop is DreameMowerAutoSwitchProperty.WIDER_CORNER_COVERAGE:
                value = get_int_value(DreameMowerWiderCornerCoverage, value)
            elif prop is DreameMowerAutoSwitchProperty.CLEANING_ROUTE:
                value = get_int_value(DreameMowerCleaningRoute, value, self.status.cleaning_route_list)
            elif prop is DreameMowerAutoSwitchProperty.CLEANGENIUS:
                value = get_int_value(DreameMowerCleanGenius, value)
            elif isinstance(value, bool):
                value = int(value)
            elif isinstance(value, str):
                value = value.upper()
                if value == "TRUE" or value == "1":
                    value = 1
                elif value == "FALSE" or value == "0":
                    value = 0
                elif value.isnumeric():
                    value = int(value)
                else:
                    value = None

            if value is None or not isinstance(value, int):
                raise InvalidActionException("Invalid value")

            if prop == DreameMowerProperty.VOLUME:
                if value < 0 or value > 100:
                    value = None
            elif prop == DreameMowerProperty.CAMERA_LIGHT_BRIGHTNESS:
                if value < 40 or value > 100:
                    value = None

            if value is None:
                raise InvalidActionException("Invalid value")

            if not self.device_connected:
                raise InvalidActionException("Device unavailable")

            if set_fn:
                return set_fn(value)

            if self.get_property(prop) == value or self.set_property(prop, value):
                return
            raise InvalidActionException("Property not updated")
        raise InvalidActionException("Invalid property or value")

    def call_action_value(self, action: str):
        if action is not None:
            if hasattr(self, action):
                action_fn = getattr(self, action)
            else:
                action_fn = None

            action = action.upper()
            if action in DreameMowerAction.__members__:
                action = DreameMowerAction(DreameMowerAction[action])
            elif action_fn is None:
                raise InvalidActionException("Invalid action")

            action_name = action.lower() if isinstance(action, str) else action.name

            if action_name in ACTION_AVAILABILITY and not ACTION_AVAILABILITY[action_name](self):
                raise InvalidActionException("Action unavailable")

            if not self.device_connected:
                raise InvalidActionException("Device unavailable")

            if action_fn:
                return action_fn()

            result = self.call_action(action)
            if result and result.get("code") == 0:
                return
            raise InvalidActionException("Unable to call action")
        raise InvalidActionException("Invalid action")

    def set_property(
        self,
        prop: (
            DreameMowerProperty | DreameMowerAutoSwitchProperty | DreameMowerStrAIProperty | DreameMowerAIProperty
        ),
        value: Any,
    ) -> bool:
        """Sets property value using the existing property mapping and notify listeners
        Property must be set on memory first and notify its listeners because device does not return new value immediately.
        """
        if value is None:
            return False

        if isinstance(prop, DreameMowerAutoSwitchProperty):
            return self.set_auto_switch_property(prop, value)
        if isinstance(prop, DreameMowerStrAIProperty) or isinstance(prop, DreameMowerAIProperty):
            return self.set_ai_property(prop, value)

        self.schedule_update(10)
        current_value = self._update_property(prop, value)
        if current_value is not None:
            if prop not in self._discarded_properties:
                self._dirty_data[prop.value] = DirtyData(value, current_value, time.time())

            self._last_change = time.time()
            self._last_settings_request = 0

            try:
                mapping = self.property_mapping[prop]
                result = self._protocol.set_property(mapping["siid"], mapping["piid"], value)

                if result is None or result[0]["code"] != 0:
                    _LOGGER.error(
                        "Property not updated: %s: %s -> %s",
                        prop.name,
                        current_value,
                        value,
                    )
                    self._update_property(prop, current_value)
                    if prop.value in self._dirty_data:
                        del self._dirty_data[prop.value]
                    self._property_changed()

                    self.schedule_update(2)
                    return False
                else:
                    _LOGGER.info("Update Property: %s: %s -> %s", prop.name, current_value, value)
                    if prop.value in self._dirty_data:
                        self._dirty_data[prop.value].update_time = time.time()

                    self.schedule_update(2)
                    return True
            except Exception as ex:
                self._update_property(prop, current_value)
                if prop.value in self._dirty_data:
                    del self._dirty_data[prop.value]
                self.schedule_update(1)
                raise DeviceUpdateFailedException("Set property failed %s: %s", prop.name, ex) from None

        self.schedule_update(1)
        return False

    def get_map_for_render(self, map_data: MapData) -> MapData | None:
        """Makes changes on map data for device related properties for renderer.
        Map manager does not need any device property for parsing and storing map data but map renderer does.
        """
        if map_data:
            if map_data.need_optimization:
                map_data = self._map_manager.optimizer.optimize(
                    map_data,
                    self._map_manager.selected_map if map_data.saved_map_status == 2 else None,
                )
                map_data.need_optimization = False

            render_map_data = copy.deepcopy(map_data)
            if (
                not self.capability.lidar_navigation
                and self.status.docked
                and not self.status.started
                and map_data.saved_map_status == 1
            ):
                saved_map_data = self._map_manager.selected_map
                render_map_data.segments = copy.deepcopy(saved_map_data.segments)
                render_map_data.data = copy.deepcopy(saved_map_data.data)
                render_map_data.pixel_type = copy.deepcopy(saved_map_data.pixel_type)
                render_map_data.dimensions = copy.deepcopy(saved_map_data.dimensions)
                render_map_data.charger_position = copy.deepcopy(saved_map_data.charger_position)
                render_map_data.no_go_areas = saved_map_data.no_go_areas
                render_map_data.virtual_walls = saved_map_data.virtual_walls
                render_map_data.robot_position = render_map_data.charger_position
                render_map_data.docked = True
                render_map_data.path = None
                render_map_data.need_optimization = False
                render_map_data.saved_map_status = 2
                render_map_data.optimized_pixel_type = None
                render_map_data.optimized_charger_position = None

            if render_map_data.optimized_pixel_type is not None:
                render_map_data.pixel_type = render_map_data.optimized_pixel_type
                render_map_data.dimensions = render_map_data.optimized_dimensions
                if render_map_data.optimized_charger_position is not None:
                    render_map_data.charger_position = render_map_data.optimized_charger_position

                # if not self.status.started and render_map_data.docked and render_map_data.robot_position and render_map_data.charger_position:
                #    render_map_data.charger_position = copy.deepcopy(render_map_data.robot_position)

            if render_map_data.combined_pixel_type is not None:
                render_map_data.pixel_type = render_map_data.combined_pixel_type
                render_map_data.dimensions = render_map_data.combined_dimensions

            offset = render_map_data.dimensions.grid_size / (1 if self.capability.map_object_offset else 2)
            render_map_data.dimensions.left = render_map_data.dimensions.left - offset
            render_map_data.dimensions.top = render_map_data.dimensions.top + offset

            if render_map_data.wifi_map:
                return render_map_data

            if render_map_data.furniture_version == 1 and self.capability.new_furnitures:
                render_map_data.furniture_version = 2

            if not render_map_data.history_map:
                if self.status.started and not (
                    self.status.zone_cleaning
                    or self.status.go_to_zone
                    or (
                        render_map_data.active_areas
                        and self.status.task_status is DreameMowerTaskStatus.DOCKING_PAUSED
                    )
                ):
                    # Map data always contains last active areas
                    render_map_data.active_areas = None

                if self.status.started and not self.status.spot_cleaning:
                    # Map data always contains last active points
                    render_map_data.active_points = None

                if not self.status.segment_cleaning:
                    # Map data always contains last active segments
                    render_map_data.active_segments = None

                if not self.status.cruising:
                    # Map data always contains last active path points
                    render_map_data.active_cruise_points = None

                if self.capability.camera_streaming and render_map_data.predefined_points is None:
                    render_map_data.predefined_points = []
            else:
                if not self.capability.camera_streaming:
                    if render_map_data.active_areas and len(render_map_data.active_areas) == 1:
                        area = render_map_data.active_areas[0]
                        size = render_map_data.dimensions.grid_size
                        if area.check_size(size):
                            x = area.x0 + int(size / 2)
                            y = area.y0 + int(size / 2)
                            render_map_data.task_cruise_points = {
                                1: Coordinate(
                                    x,
                                    y,
                                    False,
                                    0,
                                )
                            }

                            if render_map_data.completed == False:
                                if render_map_data.robot_position:
                                    render_map_data.completed = bool(
                                        render_map_data.robot_position.x >= x - size
                                        and render_map_data.robot_position.x <= x + size
                                        and render_map_data.robot_position.y >= y - size
                                        and render_map_data.robot_position.y <= y + size
                                    )
                                else:
                                    render_map_data.completed = True

                            render_map_data.active_areas = None

                if render_map_data.active_areas or render_map_data.active_points:
                    render_map_data.segments = None

                if render_map_data.customized_cleaning != 1:
                    render_map_data.cleanset = None

                if (
                    render_map_data.cleanup_method is None
                    or render_map_data.cleanup_method != CleanupMethod.CUSTOMIZED_CLEANING
                ):
                    render_map_data.cleanset = None

                if render_map_data.task_cruise_points:
                    render_map_data.active_cruise_points = render_map_data.task_cruise_points.copy()
                    render_map_data.task_cruise_points = True
                    render_map_data.active_areas = None
                    render_map_data.path = None
                    render_map_data.cleanset = None
                    if render_map_data.furnitures is not None:
                        render_map_data.furnitures = {}

                if render_map_data.segments:
                    if render_map_data.task_cruise_points or (
                        render_map_data.cleanup_method is not None
                        and render_map_data.cleanup_method == CleanupMethod.CLEANGENIUS
                    ):
                        for k, v in render_map_data.segments.items():
                            render_map_data.segments[k].order = None
                    elif render_map_data.active_segments:
                        order = 1
                        for segment_id in list(
                            sorted(
                                render_map_data.segments,
                                key=lambda segment_id: (
                                    render_map_data.segments[segment_id].order
                                    if render_map_data.segments[segment_id].order
                                    else 99
                                ),
                            )
                        ):
                            if (
                                len(render_map_data.active_segments) > 1
                                and render_map_data.segments[segment_id].order
                                and segment_id in render_map_data.active_segments
                            ):
                                render_map_data.segments[segment_id].order = order
                                order = order + 1
                            else:
                                render_map_data.segments[segment_id].order = None

                return render_map_data

            if not render_map_data.saved_map and not render_map_data.recovery_map:
                if not self.status._capability.cruising:
                    if self.status.go_to_zone:
                        render_map_data.active_cruise_points = {
                            1: Coordinate(
                                self.status.go_to_zone.x,
                                self.status.go_to_zone.y,
                                False,
                                0,
                            )
                        }
                        render_map_data.active_areas = None
                        render_map_data.path = None

                    if render_map_data.active_areas and len(render_map_data.active_areas) == 1:
                        area = render_map_data.active_areas[0]
                        if area.check_size(render_map_data.dimensions.grid_size):
                            if self.status.started and not self.status.go_to_zone and self.status.zone_cleaning:
                                render_map_data.active_cruise_points = {
                                    1: Coordinate(
                                        area.x0 + int(render_map_data.dimensions.grid_size / 2),
                                        area.y0 + int(render_map_data.dimensions.grid_size / 2),
                                        False,
                                        0,
                                    )
                                }
                            render_map_data.active_areas = None
                            render_map_data.path = None

                if not self.status.go_to_zone and (
                    (self.status.zone_cleaning and render_map_data.active_areas)
                    or (self.status.spot_cleaning and render_map_data.active_points)
                ):
                    # App does not render segments when zone or spot cleaning
                    render_map_data.segments = None

                # App does not render pet obstacles when pet detection turned off
                if render_map_data.obstacles and self.status.ai_pet_detection == 0:
                    obstacles = copy.deepcopy(render_map_data.obstacles)
                    for k, v in obstacles.items():
                        if v.type == ObstacleType.PET:
                            del render_map_data.obstacles[k]

                if render_map_data.furnitures and self.status.ai_furniture_detection == 0:
                    render_map_data.furnitures = {}

                # App adds robot position to paths as last line when map data is line to robot
                if render_map_data.line_to_robot and render_map_data.path and render_map_data.robot_position:
                    render_map_data.path.append(
                        Path(
                            render_map_data.robot_position.x,
                            render_map_data.robot_position.y,
                            PathType.LINE,
                        )
                    )

            if not self.status.customized_cleaning or self.status.cruising or self.status.cleangenius_cleaning:
                # App does not render customized cleaning settings on saved map list
                render_map_data.cleanset = None
            elif (
                not render_map_data.saved_map
                and not render_map_data.recovery_map
                and render_map_data.cleanset is None
                and self.status.customized_cleaning
            ):
                DreameMowerMapDecoder.set_segment_cleanset(render_map_data, {}, self.capability)
                render_map_data.cleanset = True

            if render_map_data.segments:
                if (
                    not self.status.custom_order
                    or self.status.cleangenius_cleaning
                    or render_map_data.saved_map
                    or render_map_data.recovery_map
                ):
                    for k, v in render_map_data.segments.items():
                        render_map_data.segments[k].order = None

            # Device currently may not be docked but map data can be old and still showing when robot is docked
            render_map_data.docked = bool(render_map_data.docked or self.status.docked)

            if (
                not self.capability.lidar_navigation
                and not render_map_data.saved_map
                and not render_map_data.recovery_map
                and render_map_data.saved_map_status == 1
                and render_map_data.docked
            ):
                # For correct scaling of vslam saved map
                render_map_data.saved_map_status = 2

            if (
                render_map_data.charger_position == None
                and render_map_data.docked
                and render_map_data.robot_position
                and not render_map_data.saved_map
                and not render_map_data.recovery_map
            ):
                render_map_data.charger_position = copy.deepcopy(render_map_data.robot_position)
                render_map_data.charger_position.a = render_map_data.robot_position.a + 180

            if render_map_data.saved_map or render_map_data.recovery_map:
                if not render_map_data.recovery_map:
                    render_map_data.virtual_walls = None
                    render_map_data.no_go_areas = None
                    render_map_data.pathways = None
                render_map_data.active_areas = None
                render_map_data.active_points = None
                render_map_data.active_segments = None
                render_map_data.active_cruise_points = None
                render_map_data.path = None
                render_map_data.cleanset = None
            elif render_map_data.charger_position and render_map_data.docked and not self.status.fast_mapping:
                if not render_map_data.robot_position:
                    render_map_data.robot_position = copy.deepcopy(render_map_data.charger_position)
            return render_map_data
        return map_data

    def get_map(self, map_index: int) -> MapData | None:
        """Get stored map data by index from map manager."""
        if self._map_manager:
            if self.status.multi_map:
                return self._map_manager.get_map(map_index)
            if map_index == 1:
                return self._map_manager.selected_map
            if map_index == 0:
                return self.status.current_map

    def update_map(self) -> None:
        """Trigger a map update.
        This function is used for requesting map data when a image request has been made to renderer
        """

        self._last_change = time.time()
        if self._map_manager:
            now = time.time()
            if now - self._last_map_request > 120:
                self._last_map_request = now
                self._map_manager.set_update_interval(self._map_update_interval)
                self._map_manager.schedule_update(0.01)

    def update(self, force_request_properties=False) -> None:
        """Get properties from the device."""
        _LOGGER.debug("Device update: %s", self._update_interval)

        if self._update_running:
            return

        if not self.cloud_connected:
            self.connect_cloud()

        if not self.device_connected:
            self.connect_device()

        if not self.device_connected:
            raise DeviceUpdateFailedException("Device cannot be reached") from None

        # self._update_running = True

        # Read-only properties
        properties = [
            DreameMowerProperty.STATE,
            DreameMowerProperty.ERROR,
            DreameMowerProperty.BATTERY_LEVEL,
            DreameMowerProperty.CHARGING_STATUS,
            DreameMowerProperty.STATUS,
            DreameMowerProperty.TASK_STATUS,
            DreameMowerProperty.WARN_STATUS,
            DreameMowerProperty.RELOCATION_STATUS,
            DreameMowerProperty.CLEANING_PAUSED,
            DreameMowerProperty.CLEANING_CANCEL,
            DreameMowerProperty.SCHEDULED_CLEAN,
            DreameMowerProperty.TASK_TYPE,
            DreameMowerProperty.MAP_RECOVERY_STATUS,
        ]

        if self.capability.backup_map:
            properties.append(DreameMowerProperty.MAP_BACKUP_STATUS)

        now = time.time()
        if self.status.active:
            # Only changed when robot is active
            properties.extend([DreameMowerProperty.CLEANED_AREA, DreameMowerProperty.CLEANING_TIME])

        if self._consumable_change:
            # Consumable properties
            properties.extend(
                [
                    DreameMowerProperty.BLADES_TIME_LEFT,
                    DreameMowerProperty.BLADES_LEFT,
                    DreameMowerProperty.SIDE_BRUSH_TIME_LEFT,
                    DreameMowerProperty.SIDE_BRUSH_LEFT,
                    DreameMowerProperty.FILTER_LEFT,
                    DreameMowerProperty.FILTER_TIME_LEFT,
                    DreameMowerProperty.LENSBRUSH_LEFT,
                    DreameMowerProperty.LENSBRUSH_TIME_LEFT,
                    DreameMowerProperty.SQUEEGEE_LEFT,
                    DreameMowerProperty.SQUEEGEE_TIME_LEFT,
                    DreameMowerProperty.SILVER_ION_LEFT,
                    DreameMowerProperty.SILVER_ION_TIME_LEFT,
                    DreameMowerProperty.TANK_FILTER_LEFT,
                    DreameMowerProperty.TANK_FILTER_TIME_LEFT,
                ]
            )

            if not self.capability.disable_sensor_cleaning:
                properties.extend(
                    [
                        DreameMowerProperty.SENSOR_DIRTY_LEFT,
                        DreameMowerProperty.SENSOR_DIRTY_TIME_LEFT,
                    ]
                )

        if now - self._last_settings_request > 9.5:
            self._last_settings_request = now

            if not self._consumable_change:
                properties.extend(
                    [
                        DreameMowerProperty.LENSBRUSH_LEFT,
                        DreameMowerProperty.LENSBRUSH_TIME_LEFT,
                        DreameMowerProperty.SQUEEGEE_LEFT,
                        DreameMowerProperty.SQUEEGEE_TIME_LEFT,
                    ]
                )

            properties.extend(self._read_write_properties)

            if not self.capability.dnd_task or not self.status.dnd_tasks:
                properties.extend(
                    [
                        DreameMowerProperty.DND,
                        DreameMowerProperty.DND_START,
                        DreameMowerProperty.DND_END,
                    ]
                )

        if self._map_manager and not self.status.running and now - self._last_map_list_request > 60:
            properties.extend([DreameMowerProperty.MAP_LIST, DreameMowerProperty.RECOVERY_MAP_LIST])
            self._last_map_list_request = time.time()

        try:
            if self._protocol.dreame_cloud and (not self.device_connected or not self.cloud_connected):
                force_request_properties = True

            if not self._protocol.dreame_cloud or force_request_properties:
                self._request_properties(properties)
            elif self.status.map_backup_status:
                self._request_properties([DreameMowerProperty.MAP_BACKUP_STATUS])
            elif self.status.map_recovery_status:
                self._request_properties([DreameMowerProperty.MAP_RECOVERY_STATUS])
        except Exception as ex:
            self._update_running = False
            raise DeviceUpdateFailedException(ex) from None

        if self._dirty_data:
            for k, v in copy.deepcopy(self._dirty_data).items():
                if time.time() - v.update_time >= self._restore_timeout:
                    if v.previous_value is not None:
                        value = self.data.get(k)
                        if value is None or v.value == value:
                            _LOGGER.info(
                                "Property %s Value Restored: %s <- %s",
                                DreameMowerProperty(k).name,
                                v.previous_value,
                                value,
                            )
                            self.data[k] = v.previous_value
                            if k in self._property_update_callback:
                                for callback in self._property_update_callback[k]:
                                    callback(v.previous_value)

                            self._property_changed()
                            self.schedule_update(1, True)
                    del self._dirty_data[k]

        if self._dirty_auto_switch_data:
            for k, v in copy.deepcopy(self._dirty_auto_switch_data).items():
                if time.time() - v.update_time >= self._restore_timeout:
                    if v.previous_value is not None:
                        value = self.auto_switch_data.get(k)
                        ## TODO
                        # if value is None or v.value == value:
                        #    _LOGGER.info(
                        #        "Property %s Value Restored: %s <- %s",
                        #        k,
                        #        v.previous_value,
                        #        value,
                        #    )
                        #    self.auto_switch_data[k] = v.previous_value
                        #    self._property_changed()
                        #    self.schedule_update(1, True)
                    del self._dirty_auto_switch_data[k]

        if self._dirty_ai_data:
            for k, v in copy.deepcopy(self._dirty_ai_data).items():
                if time.time() - v.update_time >= self._restore_timeout:
                    if v.previous_value is not None:
                        value = self.ai_data.get(k)
                        ## TODO
                        # if value is None or v.value == value:
                        #    _LOGGER.info(
                        #        "AI Property %s Value Restored: %s <- %s",
                        #        k,
                        #        v.previous_value,
                        #        value,
                        #    )
                        #    self.ai_data[k] = v.previous_value
                        #    self._property_changed()
                        #    self.schedule_update(1, True)
                    del self._dirty_ai_data[k]

        if self._consumable_change:
            self._consumable_change = False

        if self._map_manager:
            self._map_manager.set_update_interval(self._map_update_interval)
            self._map_manager.set_device_running(self.status.running, self.status.docked and not self.status.started)

        if self.cloud_connected:
            self._request_cleaning_history()

        self._update_running = False

    def call_stream_audio_action(self, property: DreameMowerProperty, parameters=None):
        return self.call_stream_action(DreameMowerAction.STREAM_AUDIO, property, parameters)

    def call_stream_video_action(self, property: DreameMowerProperty, parameters=None):
        return self.call_stream_action(DreameMowerAction.STREAM_VIDEO, property, parameters)

    def call_stream_property_action(self, property: DreameMowerProperty, parameters=None):
        return self.call_stream_action(DreameMowerAction.STREAM_PROPERTY, property, parameters)

    def call_stream_action(
        self,
        action: DreameMowerAction,
        property: DreameMowerProperty,
        parameters=None,
    ):
        params = {"session": self.status.stream_session}
        if parameters:
            params.update(parameters)
        return self.call_action(
            action,
            [
                {
                    "piid": PIID(property),
                    "value": str(json.dumps(params, separators=(",", ":"))).replace(" ", ""),
                }
            ],
        )

    def call_shortcut_action(self, command: str, parameters={}):
        return self.call_action(
            DreameMowerAction.SHORTCUTS,
            [
                {
                    "piid": PIID(DreameMowerProperty.CLEANING_PROPERTIES),
                    "value": str(
                        json.dumps(
                            {"cmd": command, "params": parameters},
                            separators=(",", ":"),
                        )
                    ).replace(" ", ""),
                }
            ],
        )

    def call_action(self, action: DreameMowerAction, parameters: dict[str, Any] = None) -> dict[str, Any] | None:
        """Call an action."""
        if action not in self.action_mapping:
            raise InvalidActionException(f"Unable to find {action} in the action mapping")

        mapping = self.action_mapping[action]
        if "siid" not in mapping or "aiid" not in mapping:
            raise InvalidActionException(f"{action} is not an action (missing siid or aiid)")

        map_action = bool(action is DreameMowerAction.REQUEST_MAP or action is DreameMowerAction.UPDATE_MAP_DATA)

        if not map_action:
            self.schedule_update(10, True)

        cleaning_action = bool(
            action
            in [
                DreameMowerAction.START_MOWING,
                DreameMowerAction.PAUSE,
                DreameMowerAction.DOCK,
                DreameMowerAction.STOP,
            ]
        )

        if not cleaning_action:
            available_fn = ACTION_AVAILABILITY.get(action.name)
            if available_fn and not available_fn(self):
                raise InvalidActionException("Action unavailable")
        elif self._map_select_time:
            elapsed = time.time() - self._map_select_time
            self._map_select_time = None
            if elapsed < 5:
                time.sleep(5 - elapsed)

        # Reset consumable on memory
        if action is DreameMowerAction.RESET_BLADES:
            self._consumable_change = True
            self._update_property(DreameMowerProperty.BLADES_LEFT, 100)
            self._update_property(DreameMowerProperty.BLADES_TIME_LEFT, 300)
        elif action is DreameMowerAction.RESET_SIDE_BRUSH:
            self._consumable_change = True
            self._update_property(DreameMowerProperty.SIDE_BRUSH_LEFT, 100)
            self._update_property(DreameMowerProperty.SIDE_BRUSH_TIME_LEFT, 200)
        elif action is DreameMowerAction.RESET_FILTER:
            self._consumable_change = True
            self._update_property(DreameMowerProperty.FILTER_LEFT, 100)
            self._update_property(DreameMowerProperty.FILTER_TIME_LEFT, 150)
        elif action is DreameMowerAction.RESET_SENSOR:
            self._consumable_change = True
            self._update_property(DreameMowerProperty.SENSOR_DIRTY_LEFT, 100)
            self._update_property(DreameMowerProperty.SENSOR_DIRTY_TIME_LEFT, 30)
        elif action is DreameMowerAction.RESET_TANK_FILTER:
            self._consumable_change = True
            self._update_property(DreameMowerProperty.TANK_FILTER_LEFT, 100)
            self._update_property(DreameMowerProperty.TANK_FILTER_TIME_LEFT, 30)
        elif action is DreameMowerAction.RESET_SILVER_ION:
            self._consumable_change = True
            self._update_property(DreameMowerProperty.SILVER_ION_LEFT, 100)
            self._update_property(DreameMowerProperty.SILVER_ION_TIME_LEFT, 365)
        elif action is DreameMowerAction.RESET_LENSBRUSH:
            parameters['in'] = {
                "CMS": {
                    "type": "set",
                    "value": [
                        1,
                        0,
                        1
                    ]
                }
            }
            self._consumable_change = True
            self._update_property(DreameMowerProperty.LENSBRUSH_LEFT, 100)
            self._update_property(DreameMowerProperty.LENSBRUSH_TIME_LEFT, 18)
        elif action is DreameMowerAction.RESET_SQUEEGEE:
            self._consumable_change = True
            self._update_property(DreameMowerProperty.SQUEEGEE_LEFT, 100)
            self._update_property(DreameMowerProperty.SQUEEGEE_TIME_LEFT, 100)
        elif action is DreameMowerAction.CLEAR_WARNING:
            self._update_property(DreameMowerProperty.ERROR, DreameMowerErrorCode.NO_ERROR.value)

        # Update listeners
        if cleaning_action or self._consumable_change:
            self._property_changed()

        try:
            result = self._protocol.action(mapping["siid"], mapping["aiid"], parameters)
        except Exception as ex:
            _LOGGER.error("Send action failed %s: %s", action.name, ex)
            self.schedule_update(1, True)
            return

        # Alternate-siid fallback for motion commands (alpha.105).
        # ioBroker.dreame documents start/stop/pause as siid=2 aiid=1/2/4
        # (rather than siid=5 that upstream MIoT vacuum spec defines). On
        # g2408 our siid=5 path has historically returned 80001 ("device
        # unreachable via cloud relay") — B1 test 2026-04-19 confirmed.
        # siid=2 aiid=50 (routed action) is known to work on this mower
        # thanks to the alpha.78-81 URL fix, suggesting siid=2 is the
        # live endpoint. Retry the motion commands on the alt siid when
        # the primary returns 80001, then cache which path worked.
        if (
            isinstance(result, dict)
            and result.get("code") == 80001
            and action in _ALT_ACTION_SIID_MAP
            and getattr(self, "_action_alt_path_preferred", {}).get(action) is not True
        ):
            alt_siid, alt_aiid = _ALT_ACTION_SIID_MAP[action]
            _LOGGER.info(
                "Send action %s primary path (siid=%d aiid=%d) returned "
                "80001; retrying via ioBroker-documented siid=%d aiid=%d",
                action.name, mapping["siid"], mapping["aiid"],
                alt_siid, alt_aiid,
            )
            try:
                alt_result = self._protocol.action(alt_siid, alt_aiid, parameters)
            except Exception as ex:
                _LOGGER.warning(
                    "Send action %s alternate path raised: %s",
                    action.name, ex,
                )
                alt_result = None
            if isinstance(alt_result, dict) and alt_result.get("code") == 0:
                _LOGGER.info(
                    "Send action %s succeeded via alternate siid=%d aiid=%d — "
                    "caching preference so future calls skip the failing primary",
                    action.name, alt_siid, alt_aiid,
                )
                if not hasattr(self, "_action_alt_path_preferred"):
                    self._action_alt_path_preferred = {}
                self._action_alt_path_preferred[action] = True
                result = alt_result
            else:
                _LOGGER.info(
                    "Send action %s alternate path also failed: %r",
                    action.name, alt_result,
                )

        # If this action previously succeeded via the alt path, prefer it
        # directly on subsequent calls (skip the failing primary).
        elif getattr(self, "_action_alt_path_preferred", {}).get(action) is True:
            alt_siid, alt_aiid = _ALT_ACTION_SIID_MAP[action]
            try:
                result = self._protocol.action(alt_siid, alt_aiid, parameters)
            except Exception as ex:
                _LOGGER.warning(
                    "Send action %s (cached-alt) raised: %s", action.name, ex
                )

        # Schedule update for retrieving new properties after action sent
        self.schedule_update(6, bool(not map_action and self._protocol.dreame_cloud))
        if result and result.get("code") == 0:
            _LOGGER.info("Send action %s %s", action.name, parameters)
            self._last_change = time.time()
            if not map_action:
                self._last_settings_request = 0
        else:
            _LOGGER.error("Send action failed %s (%s): %s", action.name, parameters, result)

        return result

    def send_command(self, command: str, parameters: dict[str, Any] = None) -> dict[str, Any] | None:
        """Send a raw command to the device. This is mostly useful when trying out
        commands which are not implemented by a given device instance. (Not likely)"""

        if command == "":
            raise InvalidActionException(f"Invalid Command: ({command}).")

        self.schedule_update(10, True)
        response = self._protocol.send(command, parameters, 3)
        if response:
            _LOGGER.info("Send command response: %s", response)
        self.schedule_update(2, True)

    def set_cleaning_mode(self, cleaning_mode: int) -> bool:
        """Set cleaning mode."""
        if self.status.cleaning_mode is None:
            raise InvalidActionException("Cleaning mode is not supported on this device")

        if self.status.cruising:
            raise InvalidActionException("Cannot set cleaning mode when cruising")

        if self.status.scheduled_clean or self.status.shortcut_task:
            raise InvalidActionException("Cannot set cleaning mode when scheduled cleaning or shortcut task")

        if (
            self.status.started
            and self.capability.custom_cleaning_mode
            and (self.status.customized_cleaning and not (self.status.zone_cleaning or self.status.spot_cleaning))
        ):
            raise InvalidActionException("Cannot set cleaning mode when customized cleaning is enabled")

        cleaning_mode = int(cleaning_mode)

        if self.status.started and not PROPERTY_AVAILABILITY[DreameMowerProperty.CLEANING_MODE.name](self):
            raise InvalidActionException("Cleaning mode unavailable")

        return self._update_cleaning_mode(cleaning_mode)


    def set_dnd_task(self, enabled: bool, dnd_start: str, dnd_end: str) -> bool:
        """Set do not disturb task"""
        if dnd_start is None or dnd_start == "":
            dnd_start = "22:00"

        if dnd_end is None or dnd_end == "":
            dnd_end = "08:00"

        time_pattern = re.compile("([0-1][0-9]|2[0-3]):[0-5][0-9]$")
        if not re.match(time_pattern, dnd_start):
            raise InvalidValueException("DnD start time is not valid: (%s).", dnd_start)
        if not re.match(time_pattern, dnd_end):
            raise InvalidValueException("DnD end time is not valid: (%s).", dnd_end)
        if dnd_start == dnd_end:
            raise InvalidValueException(
                "DnD Start time must be different from DnD end time: (%s == %s).",
                dnd_start,
                dnd_end,
            )

        if self.status.dnd_tasks is None:
            self.status.dnd_tasks = []

        if len(self.status.dnd_tasks) == 0:
            self.status.dnd_tasks.append(
                {
                    "id": 1,
                    "en": enabled,
                    "st": dnd_start,
                    "et": dnd_end,
                    "wk": 127,
                    "ss": 0,
                }
            )
        else:
            self.status.dnd_tasks[0]["en"] = enabled
            self.status.dnd_tasks[0]["st"] = dnd_start
            self.status.dnd_tasks[0]["et"] = dnd_end
        return self.set_property(
            DreameMowerProperty.DND_TASK,
            str(json.dumps(self.status.dnd_tasks, separators=(",", ":"))).replace(" ", ""),
        )

    def set_dnd(self, enabled: bool) -> bool:
        """Set do not disturb function"""
        if not self.capability.dnd_task:
            return self.set_property(DreameMowerProperty.DND, bool(enabled))
        # Try task-based DnD first, fallback to simple property if tasks are empty
        if self.status.dnd_tasks and len(self.status.dnd_tasks):
            return self.set_dnd_task(bool(enabled), self.status.dnd_start, self.status.dnd_end)
        return self.set_property(DreameMowerProperty.DND, bool(enabled))

    def set_dnd_start(self, dnd_start: str) -> bool:
        """Set do not disturb function"""
        return (
            self.set_property(DreameMowerProperty.DND_START, dnd_start)
            if not self.capability.dnd_task
            else self.set_dnd_task(self.status.dnd, str(dnd_start), self.status.dnd_end)
        )

    def set_dnd_end(self, dnd_end: str) -> bool:
        """Set do not disturb function"""
        if not self.capability.dnd_task:
            return self.set_property(DreameMowerProperty.DND_END, dnd_end)
        return self.set_dnd_task(self.status.dnd, self.status.dnd_start, str(dnd_end))

    def set_off_peak_charging_config(self, enabled: bool, start: str, end: str) -> bool:
        """Set of peak charging config"""
        if start is None or start == "":
            start = "22:00"

        if end is None or end == "":
            end = "08:00"

        time_pattern = re.compile("([0-1][0-9]|2[0-3]):[0-5][0-9]$")
        if not re.match(time_pattern, start):
            raise InvalidValueException("Start time is not valid: (%s).", start)
        if not re.match(time_pattern, end):
            raise InvalidValueException("End time is not valid: (%s).", end)
        if start == end:
            raise InvalidValueException("Start time must be different from end time: (%s == %s).", start, end)

        self.status.off_peak_charging_config = {
            "enable": enabled,
            "startTime": start,
            "endTime": end,
        }
        return self.set_property(
            DreameMowerProperty.OFF_PEAK_CHARGING,
            str(json.dumps(self.status.off_peak_charging_config, separators=(",", ":"))).replace(" ", ""),
        )

    def set_off_peak_charging(self, enabled: bool) -> bool:
        """Set off peak charging function"""
        return self.set_off_peak_charging_config(
            bool(enabled),
            self.status.off_peak_charging_start,
            self.status.off_peak_charging_end,
        )

    def set_off_peak_charging_start(self, off_peak_charging_start: str) -> bool:
        """Set off peak charging function"""
        return self.set_off_peak_charging_config(
            self.status.off_peak_charging,
            str(off_peak_charging_start),
            self.status.off_peak_charging_end,
        )

    def set_off_peak_charging_end(self, off_peak_charging_end: str) -> bool:
        """Set off peak charging function"""
        return self.set_off_peak_charging_config(
            self.status.off_peak_charging,
            self.status.off_peak_charging_start,
            str(off_peak_charging_end),
        )

    def set_voice_assistant_language(self, voice_assistant_language: str) -> bool:
        if (
            self.get_property(DreameMowerProperty.VOICE_ASSISTANT_LANGUAGE) is None
            or voice_assistant_language is None
            or len(voice_assistant_language) < 2
            or voice_assistant_language.upper() not in DreameMowerVoiceAssistantLanguage.__members__
        ):
            raise InvalidActionException(f"Voice assistant language ({voice_assistant_language}) is not supported")
        return self.set_property(
            DreameMowerProperty.VOICE_ASSISTANT_LANGUAGE,
            DreameMowerVoiceAssistantLanguage[voice_assistant_language.upper()],
        )

    def locate(self) -> dict[str, Any] | None:
        """Locate the mower cleaner."""
        return self.call_action(DreameMowerAction.LOCATE)

    def start_mowing(self) -> dict[str, Any] | None:
        """Start or resume the cleaning task."""
        if self.status.fast_mapping_paused:
            return self.start_custom(DreameMowerStatus.FAST_MAPPING.value)

        if self.status.returning_paused:
            return self.return_to_base()

        if self.capability.cruising:
            if self.status.cruising_paused:
                return self.start_custom(self.status.status.value)
        elif not self.status.paused:
            self._restore_go_to_zone()


        self.schedule_update(10, True)

        if not self.status.started:
            self._update_status(DreameMowerTaskStatus.AUTO_CLEANING, DreameMowerStatus.CLEANING)
        elif (
            self.status.paused
            and not self.status.cleaning_paused
            and not self.status.cruising
            and not self.status.scheduled_clean
        ):
            self._update_property(DreameMowerProperty.STATUS, DreameMowerStatus.CLEANING.value)
            if self.status.task_status is not DreameMowerTaskStatus.COMPLETED:
                new_state = DreameMowerState.MOWING
                self._update_property(DreameMowerProperty.STATE, new_state.value)

        if self._map_manager:
            if not self.status.started:
                self._map_manager.editor.clear_path()
            self._map_manager.editor.refresh_map()

        return self.call_action(DreameMowerAction.START_MOWING)

    def start(self) -> dict[str, Any] | None:
        """Start or resume the cleaning task."""
        if self.status.fast_mapping_paused:
            return self.start_custom(DreameMowerStatus.FAST_MAPPING.value)

        if self.status.returning_paused:
            return self.return_to_base()

        if self.capability.cruising:
            if self.status.cruising_paused:
                return self.start_custom(self.status.status.value)
        elif not self.status.paused:
            self._restore_go_to_zone()


        self.schedule_update(10, True)

        if not self.status.started:
            self._update_status(DreameMowerTaskStatus.AUTO_CLEANING, DreameMowerStatus.CLEANING)
        elif (
            self.status.paused
            and not self.status.cleaning_paused
            and not self.status.cruising
            and not self.status.scheduled_clean
        ):
            self._update_property(DreameMowerProperty.STATUS, DreameMowerStatus.CLEANING.value)
            if self.status.task_status is not DreameMowerTaskStatus.COMPLETED:
                new_state = DreameMowerState.MOWING
                self._update_property(DreameMowerProperty.STATE, new_state.value)

        if self._map_manager:
            if not self.status.started:
                self._map_manager.editor.clear_path()
            self._map_manager.editor.refresh_map()

        return self.call_action(DreameMowerAction.START_MOWING)

    def start_custom(self, status, parameters: dict[str, Any] = None) -> dict[str, Any] | None:
        """Start custom cleaning task."""
        if not self.capability.cruising and status != DreameMowerStatus.ZONE_CLEANING.value:
            self._restore_go_to_zone()

        if status is not DreameMowerStatus.FAST_MAPPING.value and self.status.fast_mapping:
            raise InvalidActionException("Cannot start cleaning while fast mapping")

        payload = [
            {
                "piid": PIID(DreameMowerProperty.STATUS, self.property_mapping),
                "value": status,
            }
        ]

        if parameters is not None:
            payload.append(
                {
                    "piid": PIID(DreameMowerProperty.CLEANING_PROPERTIES, self.property_mapping),
                    "value": parameters,
                }
            )

        return self.call_action(DreameMowerAction.START_CUSTOM, payload)

    def stop(self) -> dict[str, Any] | None:
        """Stop the mower cleaner."""
        if self.status.fast_mapping:
            return self.return_to_base()


        self.schedule_update(10, True)

        response = None
        if self.status.go_to_zone:
            response = self.call_action(DreameMowerAction.STOP)

        if self.status.started:
            self._update_status(DreameMowerTaskStatus.COMPLETED, DreameMowerStatus.STANDBY)

            # Clear active segments on current map data
            if self._map_manager:
                if self.status.go_to_zone:
                    self._map_manager.editor.set_active_areas([])
                self._map_manager.editor.set_cruise_points([])
                self._map_manager.editor.set_active_segments([])

        if response:
            return response

        return self.call_action(DreameMowerAction.STOP)

    def pause(self) -> dict[str, Any] | None:
        """Pause the cleaning task."""


        self.schedule_update(10, True)

        if not self.status.paused and self.status.started:
            if self.status.cruising and not self.capability.cruising:
                self._update_property(
                    DreameMowerProperty.STATE,
                    DreameMowerState.MONITORING_PAUSED.value,
                )
            else:
                self._update_property(DreameMowerProperty.STATE, DreameMowerState.PAUSED.value)
            self._update_property(DreameMowerProperty.STATUS, DreameMowerStatus.PAUSED.value)
            if self.status.go_to_zone:
                self._update_property(
                    DreameMowerProperty.TASK_STATUS,
                    DreameMowerTaskStatus.CRUISING_POINT_PAUSED.value,
                )

        return self.call_action(DreameMowerAction.PAUSE)

    def return_to_base(self) -> dict[str, Any] | None:
        """Set the mower cleaner to return to the dock."""
        if self._map_manager:
            self._map_manager.editor.set_cruise_points([])

        # if self.status.started:
        if not self.status.docked:
            self._update_property(DreameMowerProperty.STATUS, DreameMowerStatus.BACK_HOME.value)
            self._update_property(DreameMowerProperty.STATE, DreameMowerState.RETURNING.value)

        # Clear active segments on current map data
        # if self._map_manager:
        #    self._map_manager.editor.set_active_segments([])

        if not self.capability.cruising:
            self._restore_go_to_zone()
        return self.call_action(DreameMowerAction.DOCK)

    def dock(self) -> dict[str, Any] | None:
        """Set the mower cleaner to return to the dock."""
        if self._map_manager:
            self._map_manager.editor.set_cruise_points([])

        # if self.status.started:
        if not self.status.docked:
            self._update_property(DreameMowerProperty.STATUS, DreameMowerStatus.BACK_HOME.value)
            self._update_property(DreameMowerProperty.STATE, DreameMowerState.RETURNING.value)

        # Clear active segments on current map data
        # if self._map_manager:
        #    self._map_manager.editor.set_active_segments([])

        if not self.capability.cruising:
            self._restore_go_to_zone()
        return self.call_action(DreameMowerAction.DOCK)

    def start_pause(self) -> dict[str, Any] | None:
        """Start or resume the cleaning task."""
        if (
            not self.status.started
            or self.status.state is DreameMowerState.PAUSED
            or self.status.status is DreameMowerStatus.BACK_HOME
        ):
            return self.start()
        return self.pause()

    def clean_zone(
        self,
        zones: list[int] | list[list[int]],
        cleaning_times: int | list[int],
    ) -> dict[str, Any] | None:
        """Clean selected area."""

        if not isinstance(zones, list) or not zones:
            raise InvalidActionException(f"Invalid zone coordinates: %s", zones)

        if not isinstance(zones[0], list):
            zones = [zones]

        if cleaning_times is None or cleaning_times == "":
            cleaning_times = 1

        cleanlist = []
        index = 0
        for zone in zones:
            if not isinstance(zone, list) or len(zone) != 4:
                raise InvalidActionException(f"Invalid zone coordinates: %s", zone)

            if isinstance(cleaning_times, list):
                if index < len(cleaning_times):
                    repeat = cleaning_times[index]
                else:
                    repeat = 1
            else:
                repeat = cleaning_times

            index = index + 1

            x_coords = sorted([zone[0], zone[2]])
            y_coords = sorted([zone[1], zone[3]])

            grid_size = self.status.current_map.dimensions.grid_size if self.status.current_map else 50
            w = (x_coords[1] - x_coords[0]) / grid_size
            h = (y_coords[1] - y_coords[0]) / grid_size

            if h <= 1.0 or w <= 1.0:
                raise InvalidActionException(f"Zone {index} is smaller than minimum zone size ({h}, {w})")

            cleanlist.append(
                [
                    int(round(zone[0])),
                    int(round(zone[1])),
                    int(round(zone[2])),
                    int(round(zone[3])),
                    max(1, repeat),
                ]
            )

        self.schedule_update(10, True)
        if not self.capability.cruising:
            self._restore_go_to_zone()
        if not self.status.started or self.status.paused:
            self._update_status(DreameMowerTaskStatus.ZONE_CLEANING, DreameMowerStatus.ZONE_CLEANING)

            if self._map_manager:
                # Set active areas on current map data is implemented on the app
                if not self.status.started:
                    self._map_manager.editor.clear_path()
                self._map_manager.editor.set_active_areas(zones)

        return self.start_custom(
            DreameMowerStatus.ZONE_CLEANING.value,
            str(json.dumps({"areas": cleanlist}, separators=(",", ":"))).replace(" ", ""),
        )

    def clean_segment(
        self,
        selected_segments: int | list[int],
        cleaning_times: int | list[int] | None = None,
        timestamp: int | None = None,
    ) -> dict[str, Any] | None:
        """Clean selected segment using id."""

        if self.status.current_map and not self.status.has_saved_map:
            raise InvalidActionException("Cannot clean segments on current map")

        if not isinstance(selected_segments, list):
            selected_segments = [selected_segments]

        if cleaning_times is None or cleaning_times == "":
            cleaning_times = 1

        cleanlist = []
        index = 0
        segments = self.status.current_segments

        for segment_id in selected_segments:
            if isinstance(cleaning_times, list):
                if index < len(cleaning_times):
                    repeat = cleaning_times[index]
                else:
                    if segments and segment_id in segments and self.status.customized_cleaning:
                        repeat = segments[segment_id].cleaning_times
                    else:
                        repeat = 1
            else:
                repeat = cleaning_times


            index = index + 1
            cleanlist.append([segment_id, max(1, repeat), index])

        self.schedule_update(10, True)
        if not self.status.started or self.status.paused:
            self._update_status(
                DreameMowerTaskStatus.SEGMENT_CLEANING,
                DreameMowerStatus.SEGMENT_CLEANING,
            )

            if self._map_manager:
                if not self.status.started:
                    self._map_manager.editor.clear_path()

                # Set active segments on current map data is implemented on the app
                self._map_manager.editor.set_active_segments(selected_segments)

        data = {"selects": cleanlist}
        if timestamp is not None:
            data["timestamp"] = timestamp

        return self.start_custom(
            DreameMowerStatus.SEGMENT_CLEANING.value,
            str(json.dumps(data, separators=(",", ":"))).replace(" ", ""),
        )

    def clean_spot(
        self,
        points: list[int] | list[list[int]],
        cleaning_times: int | list[int] | None,
    ) -> dict[str, Any] | None:
        """Clean 1.5 square meters area of selected points."""

        if not isinstance(points, list) or not points:
            raise InvalidActionException(f"Invalid point coordinates: %s", points)

        if not isinstance(points[0], list):
            points = [points]

        if cleaning_times is None or cleaning_times == "":
            cleaning_times = 1

        cleanlist = []
        index = 0
        for point in points:
            if isinstance(cleaning_times, list):
                if index < len(cleaning_times):
                    repeat = cleaning_times[index]
                else:
                    repeat = 1
            else:
                repeat = cleaning_times


            index = index + 1

            if self.status.current_map and not self.status.current_map.check_point(point[0], point[1]):
                raise InvalidActionException(f"Coordinate ({point[0]}, {point[1]}) is not inside the map")

            cleanlist.append(
                [
                    int(round(point[0])),
                    int(round(point[1])),
                    repeat,
                ]
            )

        self.schedule_update(10, True)
        if not self.status.started or self.status.paused:
            self._update_status(DreameMowerTaskStatus.SPOT_CLEANING, DreameMowerStatus.SPOT_CLEANING)

            if self._map_manager:
                if not self.status.started:
                    self._map_manager.editor.clear_path()

                # Set active points on current map data is implemented on the app
                self._map_manager.editor.set_active_points(points)

        return self.start_custom(
            DreameMowerStatus.SPOT_CLEANING.value,
            str(json.dumps({"points": cleanlist}, separators=(",", ":"))).replace(" ", ""),
        )

    def go_to(self, x, y) -> dict[str, Any] | None:
        """Go to a point and take pictures around."""
        if self.status.current_map and not self.status.current_map.check_point(x, y):
            raise InvalidActionException("Coordinate is not inside the map")

        if self.status.battery_level < 15:
            raise InvalidActionException(
                "Low battery capacity. Please start the robot for working after it being fully charged."
            )

        if not self.capability.cruising:
            size = self.status.current_map.dimensions.grid_size if self.status.current_map else 50
            if self.status.current_map and self.status.current_map.robot_position:
                position = self.status.current_map.robot_position
                if abs(x - position.x) <= size and abs(y - position.y) <= size:
                    raise InvalidActionException(f"Robot is already on selected coordinate")
            self._set_go_to_zone(x, y, size)
            zone = [
                x - int(size / 2),
                y - int(size / 2),
                x + int(size / 2),
                y + int(size / 2),
            ]

        if not (self.status.started or self.status.paused):
            self._update_property(DreameMowerProperty.STATE, DreameMowerState.MONITORING.value)
            self._update_property(DreameMowerProperty.STATUS, DreameMowerStatus.CRUISING_POINT.value)
            self._update_property(
                DreameMowerProperty.TASK_STATUS,
                DreameMowerTaskStatus.CRUISING_POINT.value,
            )

            if self._map_manager:
                # Set active cruise points on current map data is implemented on the app
                self._map_manager.editor.set_cruise_points([[x, y, 0, 0]])

        if self.capability.cruising:
            return self.start_custom(
                DreameMowerStatus.CRUISING_POINT.value,
                str(
                    json.dumps(
                        {"tpoint": [[x, y, 0, 0]]},
                        separators=(",", ":"),
                    )
                ).replace(" ", ""),
            )
        else:
            cleanlist = [
                int(round(zone[0])),
                int(round(zone[1])),
                int(round(zone[2])),
                int(round(zone[3])),
                1,
                0,
                1,
            ]

            response = self.start_custom(
                DreameMowerStatus.ZONE_CLEANING.value,
                str(json.dumps({"areas": [cleanlist]}, separators=(",", ":"))).replace(" ", ""),
            )
            if not response:
                self._restore_go_to_zone()

            return response

    def follow_path(self, points: list[int] | list[list[int]]) -> dict[str, Any] | None:
        """Start a survaliance job."""
        if not self.capability.cruising:
            raise InvalidActionException("Follow path is supported on this device")

        if self.status.stream_status != DreameMowerStreamStatus.IDLE:
            raise InvalidActionException(f"Follow path only works with live camera streaming")

        if self.status.battery_level < 15:
            raise InvalidActionException(
                "Low battery capacity. Please start the robot for working after it being fully charged."
            )

        if not points:
            points = []

        if points and not isinstance(points[0], list):
            points = [points]

        if self.status.current_map:
            for point in points:
                if not self.status.current_map.check_point(point[0], point[1]):
                    raise InvalidActionException(f"Coordinate ({point[0]}, {point[1]}) is not inside the map")

        path = []
        for point in points:
            path.append([int(round(point[0])), int(round(point[1])), 0, 1])

        predefined_points = []
        if self.status.current_map and self.status.current_map.predefined_points:
            for point in self.status.current_map.predefined_points.values():
                predefined_points.append([int(round(point.x)), int(round(point.y)), 0, 1])

        if len(path) == 0:
            path.extend(predefined_points)

        if len(path) == 0:
            raise InvalidActionException("At least one valid or saved coordinate is required")

        if not self.status.started or self.status.paused:
            self._update_property(DreameMowerProperty.STATE, DreameMowerState.MONITORING.value)
            self._update_property(DreameMowerProperty.STATUS, DreameMowerStatus.CRUISING_PATH.value)
            self._update_property(
                DreameMowerProperty.TASK_STATUS,
                DreameMowerTaskStatus.CRUISING_PATH.value,
            )

            if self._map_manager:
                # Set active cruise points on current map data is implemented on the app
                self._map_manager.editor.set_cruise_points(path[:20])

        return self.start_custom(
            DreameMowerStatus.CRUISING_PATH.value,
            str(
                json.dumps(
                    {"tpoint": path[:20]},
                    separators=(",", ":"),
                )
            ).replace(" ", ""),
        )

    def start_shortcut(self, shortcut_id: int) -> dict[str, Any] | None:
        """Start shortcut job."""

        if not self.status.started:
            if self.status.status is DreameMowerStatus.STANDBY:
                self._update_property(DreameMowerProperty.STATE, DreameMowerState.IDLE.value)

            self._update_property(DreameMowerProperty.STATUS, DreameMowerStatus.SEGMENT_CLEANING.value)
            self._update_property(
                DreameMowerProperty.TASK_STATUS,
                DreameMowerTaskStatus.SEGMENT_CLEANING.value,
            )

        if self.status.shortcuts and shortcut_id in self.status.shortcuts:
            self.status.shortcuts[shortcut_id].running = True

        return self.start_custom(
            DreameMowerStatus.SHORTCUT.value,
            str(shortcut_id),
        )

    def start_fast_mapping(self) -> dict[str, Any] | None:
        """Fast map."""
        if self.status.fast_mapping:
            return

        if self.status.battery_level < 15:
            raise InvalidActionException(
                "Low battery capacity. Please start the robot for working after it being fully charged."
            )

        self.schedule_update(10, True)
        self._update_status(DreameMowerTaskStatus.FAST_MAPPING, DreameMowerStatus.FAST_MAPPING)

        if self._map_manager:
            self._map_manager.editor.refresh_map()

        return self.start_custom(DreameMowerStatus.FAST_MAPPING.value)

    def start_mapping(self) -> dict[str, Any] | None:
        """Create a new map by cleaning whole floor."""
        self.schedule_update(10, True)
        if self._map_manager:
            self._update_status(DreameMowerTaskStatus.AUTO_CLEANING, DreameMowerStatus.CLEANING)
            self._map_manager.editor.reset_map()

        return self.start_custom(DreameMowerStatus.CLEANING.value, "3")

    def clear_warning(self) -> dict[str, Any] | None:
        """Clear warning error code from the mower cleaner."""
        if self.status.has_warning:
            return self.call_action(
                DreameMowerAction.CLEAR_WARNING,
                [
                    {
                        "piid": PIID(
                            DreameMowerProperty.CLEANING_PROPERTIES,
                            self.property_mapping,
                        ),
                        "value": f"[{self.status.error.value}]",
                    }
                ],
            )

    def remote_control_move_step(
        self, rotation: int = 0, velocity: int = 0, prompt: bool | None = None
    ) -> dict[str, Any] | None:
        """Send remote control command to device."""
        if self.status.fast_mapping:
            raise InvalidActionException("Cannot remote control mower while fast mapping")

        payload = '{"spdv":%(velocity)d,"spdw":%(rotation)d,"audio":"%(audio)s","random":%(random)d}' % {
            "velocity": velocity,
            "rotation": rotation,
            "audio": (
                "true"
                if prompt == True
                else (
                    "false"
                    if prompt == False or self._remote_control or self.status.status is DreameMowerStatus.SLEEPING
                    else "true"
                )
            ),
            "random": randrange(65535),
        }
        self._remote_control = True
        mapping = self.property_mapping[DreameMowerProperty.REMOTE_CONTROL]
        return self._protocol.set_property(mapping["siid"], mapping["piid"], payload, 1)

    def install_voice_pack(self, lang_id: int, url: str, md5: str, size: int) -> dict[str, Any] | None:
        """install a custom language pack"""
        payload = '{"id":"%(lang_id)s","url":"%(url)s","md5":"%(md5)s","size":%(size)d}' % {
            "lang_id": lang_id,
            "url": url,
            "md5": md5,
            "size": size,
        }
        mapping = self.property_mapping[DreameMowerProperty.VOICE_CHANGE]
        return self._protocol.set_property(mapping["siid"], mapping["piid"], payload, 3)

    def obstacle_image(self, index):
        if self.capability.map:
            map_data = self.status.current_map
            if map_data:
                return self._map_manager.get_obstacle_image(map_data, index)
        return (None, None)

    def obstacle_history_image(self, index, history_index, cruising=False):
        if self.capability.map:
            map_data = self.history_map(history_index, cruising)
            if map_data:
                return self._map_manager.get_obstacle_image(map_data, index)
        return (None, None)

    def history_map(self, index, cruising=False):
        if self.capability.map and index and str(index).isnumeric():
            item = None
            if cruising:
                if self.status._cruising_history and len(self.status._cruising_history) > int(index) - 1:
                    item = self.status._cruising_history[int(index) - 1]
            else:
                if self.status._cleaning_history and len(self.status._cleaning_history) > int(index) - 1:
                    item = self.status._cleaning_history[int(index) - 1]
            if item and item.object_name:
                if item.object_name not in self.status._history_map_data:
                    map_data = self._map_manager.get_history_map(item.object_name, item.key)
                    if map_data is None:
                        return None
                    map_data.last_updated = item.date.timestamp()
                    map_data.completed = item.completed
                    map_data.neglected_segments = item.neglected_segments
                    map_data.second_cleaning = item.second_cleaning
                    map_data.cleaned_area = item.cleaned_area
                    map_data.cleaning_time = item.cleaning_time
                    if item.cleanup_method is not None:
                        map_data.cleanup_method = item.cleanup_method
                    if map_data.cleaning_map_data:
                        map_data.cleaning_map_data.last_updated = item.date.timestamp()
                        map_data.cleaning_map_data.completed = item.completed
                        map_data.cleaning_map_data.neglected_segments = item.neglected_segments
                        map_data.cleaning_map_data.second_cleaning = item.second_cleaning
                        map_data.cleaning_map_data.cleaned_area = item.cleaned_area
                        map_data.cleaning_map_data.cleaning_time = item.cleaning_time
                        map_data.cleaning_map_data.cleanup_method = map_data.cleanup_method
                    self.status._history_map_data[item.object_name] = map_data
                return self.status._history_map_data[item.object_name]

    def recovery_map(self, map_id, index):
        if self.capability.map and map_id and index and str(index).isnumeric():
            if (map_id is None or map_id == "") and self.status.selected_map:
                map_id = self.status.selected_map.map_id

            return self._map_manager.get_recovery_map(map_id, index)

    def recovery_map_file(self, map_id, index):
        if self.capability.map and map_id and index and str(index).isnumeric():
            if (map_id is None or map_id == "") and self.status.selected_map:
                map_id = self.status.selected_map.map_id

            return self._map_manager.get_recovery_map_file(map_id, index)

    def set_ai_detection(self, settings: dict[str, bool] | int) -> dict[str, Any] | None:
        """Send ai detection parameters to the device."""
        if self.capability.ai_detection:
            if (self.status.ai_obstacle_detection or self.status.ai_obstacle_image_upload) and (
                self._protocol.cloud and not self.status.ai_policy_accepted
            ):
                prop = "prop.s_ai_config"
                response = self._protocol.cloud.get_batch_device_datas([prop])
                if response and prop in response and response[prop]:
                    try:
                        self.status.ai_policy_accepted = json.loads(response[prop]).get("privacyAuthed")
                    except:
                        pass

                if not self.status.ai_policy_accepted:
                    if self.status.ai_obstacle_detection:
                        self.status.ai_obstacle_detection = False

                    if self.status.ai_obstacle_image_upload:
                        self.status.ai_obstacle_image_upload = False

                    self._property_changed()

                    raise InvalidActionException(
                        "You need to accept privacy policy from the App before enabling AI obstacle detection feature"
                    )
            mapping = self.property_mapping[DreameMowerProperty.AI_DETECTION]
            if isinstance(settings, int):
                return self._protocol.set_property(mapping["siid"], mapping["piid"], settings, 3)
            return self._protocol.set_property(
                mapping["siid"],
                mapping["piid"],
                str(json.dumps(settings, separators=(",", ":"))).replace(" ", ""),
                3,
            )

    def set_ai_property(
        self, prop: DreameMowerStrAIProperty | DreameMowerAIProperty, value: bool
    ) -> dict[str, Any] | None:
        if self.capability.ai_detection:
            if prop.name not in self.ai_data:
                raise InvalidActionException("Not supported")
            current_value = self.get_ai_property(prop)

            self._dirty_ai_data[prop.name] = DirtyData(value, current_value, time.time())
            self.ai_data[prop.name] = value
            ai_value = self.get_property(DreameMowerProperty.AI_DETECTION)
            self._property_changed()
            try:
                if isinstance(ai_value, int):
                    bit = DreameMowerAIProperty[prop.name].value
                    result = self.set_ai_detection((ai_value | bit) if value else (ai_value & -(bit + 1)))
                else:
                    result = self.set_ai_detection({DreameMowerStrAIProperty[prop.name].value: bool(value)})

                if result is None or result[0]["code"] != 0:
                    _LOGGER.error(
                        "AI Property not updated: %s: %s -> %s",
                        prop.name,
                        current_value,
                        value,
                    )
                    if prop.name in self._dirty_ai_data:
                        del self._dirty_ai_data[prop.name]
                    self.ai_data[prop.name] = current_value
                    self._property_changed()
            except:
                if prop.name in self._dirty_ai_data:
                    del self._dirty_ai_data[prop.name]
                self.ai_data[prop.name] = current_value
                self._property_changed()
            return result

    def set_auto_switch_settings(self, settings) -> dict[str, Any] | None:
        if self.capability.auto_switch_settings:
            mapping = self.property_mapping[DreameMowerProperty.AUTO_SWITCH_SETTINGS]
            return self._protocol.set_property(
                mapping["siid"],
                mapping["piid"],
                str(json.dumps(settings, separators=(",", ":"))).replace(" ", ""),
                1,
            )

    def set_auto_switch_property(self, prop: DreameMowerAutoSwitchProperty, value: int) -> dict[str, Any] | None:
        if self.capability.auto_switch_settings:
            if prop.name not in self.auto_switch_data:
                raise InvalidActionException("Not supported")
            current_value = self.get_auto_switch_property(prop)
            if current_value != value:
                self._dirty_auto_switch_data[prop.name] = DirtyData(value, current_value, time.time())
                self.auto_switch_data[prop.name] = value
                self._property_changed()
                try:
                    result = self.set_auto_switch_settings({"k": prop.value, "v": int(value)})
                    if result is None or result[0]["code"] != 0:
                        _LOGGER.error(
                            "Auto Switch Property not updated: %s: %s -> %s",
                            prop.name,
                            current_value,
                            value,
                        )
                        if prop.name in self._dirty_auto_switch_data:
                            del self._dirty_auto_switch_data[prop.name]
                        self.auto_switch_data[prop.name] = current_value
                        self._property_changed()
                    else:
                        _LOGGER.info("Update Property: %s: %s -> %s", prop.name, current_value, value)
                        if prop.name in self._dirty_auto_switch_data:
                            self._dirty_auto_switch_data[prop.name].update_time = time.time()
                except:
                    if prop.name in self._dirty_auto_switch_data:
                        del self._dirty_auto_switch_data[prop.name]
                    self.auto_switch_data[prop.name] = current_value
                    self._property_changed()
                return result

    def set_camera_light_brightness(self, brightness: int) -> dict[str, Any] | None:
        if self.capability.auto_switch_settings:
            if brightness < 40:
                brightness = 40
            current_value = self.status.camera_light_brightness
            self._update_property(DreameMowerProperty.CAMERA_LIGHT_BRIGHTNESS, str(brightness))
            result = self.call_stream_property_action(
                DreameMowerProperty.CAMERA_LIGHT_BRIGHTNESS, {"value": str(brightness)}
            )
            if result is None or result.get("code") != 0:
                self._update_property(DreameMowerProperty.CAMERA_LIGHT_BRIGHTNESS, str(current_value))
            return result

    def set_wider_corner_coverage(self, value: int) -> dict[str, Any] | None:
        if self.capability.auto_switch_settings:
            current_value = self.get_auto_switch_property(DreameMowerAutoSwitchProperty.WIDER_CORNER_COVERAGE)
            if current_value is not None and current_value > 0 and value <= 0:
                value = -current_value
            return self.set_auto_switch_property(DreameMowerAutoSwitchProperty.WIDER_CORNER_COVERAGE, value)

    def set_resume_cleaning(self, value: int) -> dict[str, Any] | None:
        if self.capability.auto_charging and bool(value):
            value = 2
        return self.set_property(DreameMowerProperty.RESUME_CLEANING, value)

    def set_multi_floor_map(self, enabled: bool) -> bool:
        if self.set_property(DreameMowerProperty.MULTI_FLOOR_MAP, int(enabled)):
            if (
                self.capability.auto_switch_settings
                and not enabled
                and self.get_property(DreameMowerProperty.INTELLIGENT_RECOGNITION) == 1
            ):
                self.set_property(DreameMowerProperty.INTELLIGENT_RECOGNITION, 0)
            return True
        return False

    def rename_shortcut(self, shortcut_id: int, shortcut_name: str = "") -> dict[str, Any] | None:
        """Rename a shortcut"""
        if self.status.started:
            raise InvalidActionException("Cannot rename a shortcut while mower is running")

        if not self.capability.shortcuts or not self.status.shortcuts:
            raise InvalidActionException("Shortcuts are not supported on this device")

        if shortcut_id not in self.status.shortcuts:
            raise InvalidActionException(f"Shortcut {shortcut_id} not found")

        if shortcut_name and len(shortcut_name) > 0:
            current_name = self.status.shortcuts[shortcut_id]
            if current_name != shortcut_name:
                counter = 1
                for id, shortcut in self.status.shortcuts.items():
                    if shortcut.name == shortcut_name and shortcut.id != shortcut_id:
                        counter = counter + 1

                if counter > 1:
                    shortcut_name = f"{shortcut_name}{counter}"

                self.status.shortcuts[shortcut_id].name = shortcut_name
                shortcut_name = base64.b64encode(shortcut_name.encode("utf-8")).decode("utf-8")
                shortcuts = self.get_property(DreameMowerProperty.SHORTCUTS)
                if shortcuts and shortcuts != "":
                    shortcuts = json.loads(shortcuts)
                    if shortcuts:
                        for shortcut in shortcuts:
                            if shortcut["id"] == shortcut_id:
                                shortcut["name"] = shortcut_name
                                break
                self._update_property(
                    DreameMowerProperty.SHORTCUTS,
                    str(json.dumps(shortcuts, separators=(",", ":"))).replace(" ", ""),
                )
                self._property_changed()

                success = False
                response = self.call_shortcut_action(
                    "EDIT_COMMAND",
                    {"id": shortcut_id, "name": shortcut_name, "type": 3},
                )
                if response and "out" in response:
                    data = response["out"]
                    if data and len(data):
                        if "value" in data[0] and data[0]["value"] != "":
                            success = data[0]["value"] == "0"
                if not success:
                    self.status.shortcuts[shortcut_id].name = current_name
                    self._property_changed()
                return response

    def set_obstacle_ignore(self, x, y, obstacle_ignored) -> dict[str, Any] | None:
        if not self.capability.ai_detection:
            raise InvalidActionException("Obstacle detection is not available on this device")

        if not self._map_manager:
            raise InvalidActionException("Obstacle ignore requires cloud connection")

        if self.status.started:
            raise InvalidActionException("Cannot set obstacle ignore status while mower is running")

        if not self.status.current_map and not self.status.current_map.obstacles:
            raise InvalidActionException("Obstacle not found")

        if self.status.current_map.obstacles is None or (
            len(self.status.current_map.obstacles)
            and next(iter(self.status.current_map.obstacles.values())).ignore_status is None
        ):
            raise InvalidActionException("Obstacle ignore is not supported on this device")

        found = False
        obstacle_type = 142
        for k, v in self.status.current_map.obstacles.items():
            if int(v.x) == int(x) and int(v.y) == int(y):
                if v.ignore_status.value == 2:
                    raise InvalidActionException("Cannot ignore a dynamically ignored obstacle")
                obstacle_type = v.type.value
                found = True
                break

        if not found:
            raise InvalidActionException("Obstacle not found")

        self._map_manager.editor.set_obstacle_ignore(x, y, obstacle_ignored)
        return self.update_map_data_async(
            {
                "obstacleignore": [
                    int(x),
                    int(y),
                    obstacle_type,
                    1 if bool(obstacle_ignored) else 0,
                ]
            }
        )

    def set_router_position(self, x, y):
        if not self.capability.wifi_map:
            raise InvalidActionException("WiFi map is not available on this device")

        if self.status.started:
            raise InvalidActionException("Cannot set router position while mower is running")

        if self._map_manager:
            self._map_manager.editor.set_router_position(x, y)
        return self.update_map_data_async({"wrp": [int(x), int(y)]})

    def request_map(self) -> dict[str, Any] | None:
        """Send map request action to the device.
        Device will upload a new map on cloud after this command if it has a saved map on memory.
        Otherwise this action will timeout when device is spot cleaning or a restored map exists on memory.
        """

        if self._map_manager:
            return self._map_manager.request_new_map()
        return self.call_action(
            DreameMowerAction.REQUEST_MAP,
            [
                {
                    "piid": PIID(DreameMowerProperty.FRAME_INFO, self.property_mapping),
                    "value": '{"frame_type":"I"}',
                }
            ],
        )

    def update_map_data_async(self, parameters: dict[str, Any]):
        """Send update map action to the device."""
        if self._map_manager:
            self._map_manager.schedule_update(10)
            self._property_changed()
            self._last_map_request = time.time()

        parameters = [
            {
                "piid": PIID(DreameMowerProperty.MAP_EXTEND_DATA, self.property_mapping),
                "value": str(json.dumps(parameters, separators=(",", ":"))).replace(" ", ""),
            }
        ]

        def callback(result):
            if result and result.get("code") == 0:
                _LOGGER.info("Send action UPDATE_MAP_DATA async %s", parameters)
                self._last_change = time.time()
            else:
                _LOGGER.error(
                    "Send action failed UPDATE_MAP_DATA async (%s): %s",
                    parameters,
                    result,
                )

            self.schedule_update(5)

            if self._map_manager:
                if self._protocol.dreame_cloud:
                    self._map_manager.schedule_update(3)
                else:
                    self._map_manager.request_next_map()
                    self._last_map_list_request = 0

        mapping = self.action_mapping[DreameMowerAction.UPDATE_MAP_DATA]
        self._protocol.action_async(callback, mapping["siid"], mapping["aiid"], parameters)

    def update_map_data(self, parameters: dict[str, Any]) -> dict[str, Any] | None:
        """Send update map action to the device."""
        if self._map_manager:
            self._map_manager.schedule_update(10)
            self._property_changed()
            self._last_map_request = time.time()

        response = self.call_action(
            DreameMowerAction.UPDATE_MAP_DATA,
            [
                {
                    "piid": PIID(DreameMowerProperty.MAP_EXTEND_DATA, self.property_mapping),
                    "value": str(json.dumps(parameters, separators=(",", ":"))).replace(" ", ""),
                }
            ],
        )

        self.schedule_update(5, True)

        if self._map_manager:
            if self._protocol.dreame_cloud:
                self._map_manager.schedule_update(3)
            else:
                self._map_manager.request_next_map()
                self._last_map_list_request = 0

        return response

    def rename_map(self, map_id: int, map_name: str = "") -> dict[str, Any] | None:
        """Set custom name for a map"""
        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot rename a map when temporary map is present")

        if map_name != "":
            map_name = map_name.replace(" ", "-")
            if self._map_manager:
                self._map_manager.editor.set_map_name(map_id, map_name)
            return self.update_map_data_async({"nrism": {map_id: {"name": map_name}}})

    def set_map_rotation(self, rotation: int, map_id: int = None) -> dict[str, Any] | None:
        """Set rotation of a map"""
        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot rotate a map when temporary map is present")

        if rotation is not None:
            rotation = int(rotation)
            if rotation > 270 or rotation < 0:
                rotation = 0

            if self._map_manager:
                if map_id is None:
                    map_id = self.status.selected_map.map_id
                self._map_manager.editor.set_rotation(map_id, rotation)

            if map_id is not None:
                return self.update_map_data_async({"smra": {map_id: {"ra": rotation}}})

    def set_restricted_zone(self, walls=[], zones=[], no_mops=[]) -> dict[str, Any] | None:
        """Set restricted zones on current saved map."""
        if walls == "":
            walls = []
        if zones == "":
            zones = []
        if no_mops == "":
            no_mops = []

        if self._map_manager:
            self._map_manager.editor.set_zones(walls, zones, no_mops)
        return self.update_map_data_async({"vw": {"line": walls, "rect": zones, "mop": no_mops}})

    def set_pathway(self, pathways=[]) -> dict[str, Any] | None:
        """Set pathways on current saved map."""
        if pathways == "":
            pathways = []

        if self._map_manager:
            if self.status.current_map and not (
                self.status.current_map.pathways is not None or self.capability.floor_material
            ):
                raise InvalidActionException("Pathways are not supported on this device")

            if self.status.current_map and not self.status.has_saved_map:
                raise InvalidActionException("Cannot edit pathways on current map")
            self._map_manager.editor.set_pathways(pathways)

        return self.update_map_data_async({"vws": {"vwsl": pathways}})

    def set_predefined_points(self, points=[]) -> dict[str, Any] | None:
        """Set predefined points on current saved map."""
        if points == "":
            points = []

        if not self.capability.cruising:
            raise InvalidActionException("Predefined points are not supported on this device")

        if self.status.started:
            raise InvalidActionException("Cannot set predefined points while mower is running")

        if self.status.current_map:
            for point in points:
                if not self.status.current_map.check_point(point[0], point[1]):
                    raise InvalidActionException(f"Coordinate ({point[0]}, {point[1]}) is not inside the map")

        predefined_points = []
        for point in points:
            predefined_points.append([point[0], point[1], 0, 1])

        if self._map_manager:
            if self.status.current_map and not self.status.has_saved_map:
                raise InvalidActionException("Cannot edit predefined points on current map")
            self._map_manager.editor.set_predefined_points(predefined_points[:20])

        return self.update_map_data_async({"spoint": predefined_points[:20], "tpoint": []})

    def set_selected_map(self, map_id: int) -> dict[str, Any] | None:
        """Change currently selected map when multi floor map is enabled."""
        if self.status.multi_map:
            self._map_select_time = time.time()
            if self._map_manager:
                self._map_manager.editor.set_selected_map(map_id)
            return self.update_map_data({"sm": {}, "mapid": map_id})

    def delete_map(self, map_id: int = None) -> dict[str, Any] | None:
        """Delete a map."""
        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot delete a map when temporary map is present")

        if self.status.started:
            raise InvalidActionException("Cannot delete a map while mower is running")

        if self._map_manager:
            if map_id == 0:
                map_id = None

            # Device do not deletes saved maps when you disable multi floor map feature
            # but it deletes all maps if you delete any map when multi floor map is disabled.
            if self.status.multi_map:
                if not map_id and self._map_manager.selected_map:
                    map_id = self._map_manager.selected_map.map_id
            else:
                if self._map_manager.selected_map and map_id == self._map_manager.selected_map.map_id:
                    self._map_manager.editor.delete_map()
                else:
                    self._map_manager.editor.delete_map(map_id)
        parameters = {"cm": {}}
        if map_id:
            parameters["mapid"] = map_id
        return self.update_map_data(parameters)

    def save_temporary_map(self) -> dict[str, Any] | None:
        """Replace new map with an old one when multi floor map is disabled."""
        if self.status.has_temporary_map:
            if self._map_manager:
                self._map_manager.editor.save_temporary_map()
            return self.update_map_data({"cw": 5})

    def discard_temporary_map(self) -> dict[str, Any] | None:
        """Discard new map when device have reached maximum number of maps it can store."""
        if self.status.has_temporary_map:
            if self._map_manager:
                self._map_manager.editor.discard_temporary_map()
            return self.update_map_data({"cw": 0})

    def replace_temporary_map(self, map_id: int = None) -> dict[str, Any] | None:
        """Replace new map with an old one when device have reached maximum number of maps it can store."""
        if self.status.has_temporary_map:
            if self.status.multi_map:
                raise InvalidActionException("Cannot replace a map when multi floor map is disabled")

            if self._map_manager:
                self._map_manager.editor.replace_temporary_map(map_id)
            parameters = {"cw": 1}
            if map_id:
                parameters["mapid"] = map_id
            return self.update_map_data(parameters)

    def restore_map_from_file(self, map_url: int, map_id: int = None) -> dict[str, Any] | None:
        map_recovery_status = self.status.map_recovery_status
        if map_recovery_status is None:
            raise InvalidActionException("Map recovery is not supported on this device")

        if map_recovery_status == DreameMapRecoveryStatus.RUNNING.value:
            raise InvalidActionException("Map recovery in progress")

        if map_id is None or map_id == "":
            if self.status.selected_map is None:
                raise InvalidActionException("Map ID is required")

            map_id = self.status.selected_map.map_id

        if self.status.map_data_list and not (map_id in self.status.map_data_list):
            raise InvalidActionException("Map not found")

        if self.status.started:
            raise InvalidActionException("Cannot set restore a map while mower is running")

        self.schedule_update(15)
        if self._map_manager:
            self._last_map_request = time.time()
            self._map_manager.schedule_update(15)

        self._update_property(
            DreameMowerProperty.MAP_RECOVERY_STATUS,
            DreameMapRecoveryStatus.RUNNING.value,
        )
        mapping = self.property_mapping[DreameMowerProperty.MAP_RECOVERY]
        response = self._protocol.set_property(
            mapping["siid"],
            mapping["piid"],
            str(json.dumps({"map_id": map_id, "map_url": map_url}, separators=(",", ":"))).replace(" ", ""),
        )
        if not response or response[0]["code"] != 0:
            self._update_property(DreameMowerProperty.MAP_RECOVERY_STATUS, map_recovery_status)
            raise InvalidActionException("Map recovery failed with error code %s", response[0]["code"])
        self._map_manager.schedule_update(5)
        self.schedule_update(1)
        return response

    def restore_map(self, recovery_map_index: int, map_id: int = None) -> dict[str, Any] | None:
        """Replace a map with previously saved version by device."""
        map_recovery_status = self.status.map_recovery_status
        if map_recovery_status is None:
            raise InvalidActionException("Map recovery is not supported on this device")

        if not self._map_manager:
            raise InvalidActionException("Map recovery requires cloud connection")

        if map_recovery_status == DreameMapRecoveryStatus.RUNNING.value:
            raise InvalidActionException("Map recovery in progress")

        if self.status.started:
            raise InvalidActionException("Cannot set restore a map while mower is running")

        if self.status.has_temporary_map:
            raise InvalidActionException("Restore a map when temporary map is present")

        if (map_id is None or map_id == "") and self.status.selected_map:
            map_id = self.status.selected_map.map_id

        if not map_id or map_id not in self.status.map_data_list:
            raise InvalidActionException("Map not found")

        if len(self.status.map_data_list[map_id].recovery_map_list) <= int(recovery_map_index) - 1:
            raise InvalidActionException("Invalid recovery map index")

        recovery_map_info = self.status.map_data_list[map_id].recovery_map_list[int(recovery_map_index) - 1]
        object_name = recovery_map_info.object_name
        if object_name and object_name != "":
            file, map_url, object_name = self.recovery_map_file(map_id, recovery_map_index)
            if map_url == None:
                raise InvalidActionException("Failed get recovery map file url: %s", object_name)

            if file == None:
                raise InvalidActionException("Failed to download recovery map file: %s", map_url)

            response = self.restore_map_from_file(map_url, map_id)
            if response and response[0]["code"] == 0:
                self._map_manager.editor.restore_map(recovery_map_info)
            return response
        raise InvalidActionException("Invalid recovery map object name")

    def backup_map(self, map_id: int = None) -> dict[str, Any] | None:
        """Save a map map to cloud for later use of restoring."""
        if not self.capability.backup_map:
            raise InvalidActionException("Map backup is not supported on this device")

        if self.status.map_backup_status == DreameMapBackupStatus.RUNNING.value:
            raise InvalidActionException("Map backup in progress")

        if map_id is None or map_id == "":
            if self.status.selected_map is None:
                raise InvalidActionException("Map ID is required")

            map_id = self.status.selected_map.map_id

        if self.status.map_data_list and not (map_id in self.status.map_data_list):
            raise InvalidActionException("Map not found")

        response = self.call_action(
            DreameMowerAction.BACKUP_MAP,
            [
                {
                    "piid": PIID(DreameMowerProperty.MAP_EXTEND_DATA, self.property_mapping),
                    "value": str(map_id),
                }
            ],
        )
        self.schedule_update(3, True)
        if response and response.get("code") == 0:
            self._update_property(
                DreameMowerProperty.MAP_BACKUP_STATUS,
                DreameMapBackupStatus.RUNNING.value,
            )
        return response

    def merge_segments(self, map_id: int, segments: list[int]) -> dict[str, Any] | None:
        """Merge segments on a map"""
        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot edit segments when temporary map is present")

        if segments:
            if map_id == "":
                map_id = None

            if self._map_manager:
                if not map_id:
                    if self.capability.lidar_navigation and self._map_manager.selected_map:
                        map_id = self._map_manager.selected_map.map_id
                    else:
                        map_id = 0
                self._map_manager.editor.merge_segments(map_id, segments)

            if not map_id and self.capability.lidar_navigation:
                raise InvalidActionException("Map ID is required")

            data = {"msr": [segments[0], segments[1]]}
            if map_id:
                data["mapid"] = map_id
            return self.update_map_data(data)

    def split_segments(self, map_id: int, segment: int, line: list[int]) -> dict[str, Any] | None:
        """Split segments on a map"""
        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot edit segments when temporary map is present")

        if segment and line is not None:
            if map_id == "":
                map_id = None

            if self._map_manager:
                if not map_id:
                    if self.capability.lidar_navigation and self._map_manager.selected_map:
                        map_id = self._map_manager.selected_map.map_id
                    else:
                        map_id = 0
                self._map_manager.editor.split_segments(map_id, segment, line)

            if not map_id and self.capability.lidar_navigation:
                raise InvalidActionException("Map ID is required")

            line.append(segment)
            data = {"dsrid": line}
            if map_id:
                data["mapid"] = map_id
            return self.update_map_data(data)

    def set_cleaning_sequence(self, cleaning_sequence: list[int]) -> dict[str, Any] | None:
        """Set cleaning sequence on current map.
        Device will use this order even you specify order in segment cleaning."""

        if not self.capability.customized_cleaning:
            raise InvalidActionException("Cleaning sequence is not supported on this device")

        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot edit segments when temporary map is present")

        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot edit segments when temporary map is present")

        if self.status.started:
            raise InvalidActionException("Cannot set cleaning sequence while mower is running")

        if cleaning_sequence == "" or not cleaning_sequence:
            cleaning_sequence = []

        if self._map_manager:
            if cleaning_sequence and self.status.segments:
                for k in cleaning_sequence:
                    if int(k) not in self.status.segments.keys():
                        raise InvalidValueException("Segment not found! (%s)", k)

            map_data = self.status.current_map
            if map_data and map_data.segments and not map_data.temporary_map:
                if not cleaning_sequence:
                    current = self._map_manager.cleaning_sequence
                    if current and len(current):
                        self.status._previous_cleaning_sequence[map_data.map_id] = current
                    elif map_data.map_id in self.status._previous_cleaning_sequence:
                        del self.status._previous_cleaning_sequence[map_data.map_id]

                cleaning_sequence = self._map_manager.editor.set_cleaning_sequence(cleaning_sequence)

        return self.update_map_data_async({"cleanOrder": cleaning_sequence})

    def set_cleanset(self, cleanset: dict[str, list[int]]) -> dict[str, Any] | None:
        """Set customized cleaning settings on current map.
        Device will use these settings even you pass another setting for custom segment cleaning.
        """

        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot edit segments when temporary map is present")

        if cleanset is not None:
            return self.update_map_data_async({"customeClean": cleanset})

    def set_custom_cleaning(
        self,
        segment_id: list[int],
        cleaning_times: list[int],
        cleaning_mode: list[int] = None,
    ) -> dict[str, Any] | None:
        """Set customized cleaning settings on current map.
        Device will use these settings even you pass another setting for custom segment cleaning.
        """

        if not self.capability.customized_cleaning:
            raise InvalidActionException("Customized cleaning is not supported on this device")

        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot edit customized cleaning parameters when temporary map is present")

        if self.status.started:
            raise InvalidActionException("Cannot edit customized cleaning parameters while mower is running")

        if cleaning_times:
            for v in cleaning_times:
                if int(v) < 1 or int(v) > 3:
                    raise InvalidActionException("Invalid cleaning times: %s", v)

        if cleaning_mode:
            for v in cleaning_mode:
                if int(v) < 0 or int(v) > 2:
                    raise InvalidActionException("Invalid cleaning mode: %s", v)

        if self.capability.map:
            if not self.status.has_saved_map:
                raise InvalidActionException("Cannot edit customized cleaning parameters on current map")

            current_map = self.status.current_map
            if current_map:
                segments = self.status.segments
                index = 0
                for k in segment_id:
                    id = int(k)
                    if not segments or id not in segments:
                        raise InvalidActionException("Invalid Segment ID: %s", id)
                    self._map_manager.editor.set_segment_cleaning_times(id, int(cleaning_times[index]), False)
                    if self.capability.custom_cleaning_mode:
                        self._map_manager.editor.set_segment_cleaning_mode(id, int(cleaning_mode[index]), False)
                    index = index + 1
                self._map_manager.editor.refresh_map()
                return self.set_cleanset(self._map_manager.editor.cleanset(current_map))

        custom_cleaning_mode = self.capability.custom_cleaning_mode
        has_cleaning_mode = cleaning_mode != "" and cleaning_mode is not None
        if (
            segment_id != ""
            and segment_id
            and cleaning_times != ""
            and cleaning_times is not None
        ):
            if has_cleaning_mode and not custom_cleaning_mode:
                raise InvalidActionException(
                    "Setting custom cleaning mode for segments is not supported by the device!"
                )
            elif not has_cleaning_mode and custom_cleaning_mode:
                raise InvalidActionException("Cleaning mode is required")

            if segments:
                count = len(segments.items())
                if (
                    len(segment_id) != count
                    or len(cleaning_times) != count
                    or (custom_cleaning_mode and len(cleaning_mode) != count)
                ):
                    raise InvalidActionException("Parameter count mismatch!")

            custom_cleaning = []
            index = 0

            for id in segment_id:
                values = [
                    id,
                    cleaning_times[index],
                ]
                if custom_cleaning_mode:
                    values.append(cleaning_mode[index])
                    if segments:
                        if id not in segments:
                            raise InvalidActionException("Invalid Segment ID: %s", id)

                custom_cleaning.append(values)
                index = index + 1

            return self.set_cleanset(custom_cleaning)

        raise InvalidActionException("Missing parameters!")

    def set_hidden_segments(self, invisible_segments: list[int]):
        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot edit segments when temporary map is present")

        if self.status.started:
            raise InvalidActionException("Cannot set zone visibility while mower is running")

        if invisible_segments == "" or not invisible_segments:
            invisible_segments = []

        if self._map_manager:
            if invisible_segments and self.status.segments:
                for k in invisible_segments:
                    if int(k) not in self.status.segments.keys():
                        raise InvalidValueException("Segment not found! (%s)", k)

            # invisible_segments = self._map_manager.editor.set_invisible_segments(invisible_segments)

        return self.update_map_data_async({"delsr": invisible_segments})

    def set_segment_name(self, segment_id: int, segment_type: int, custom_name: str = None) -> dict[str, Any] | None:
        """Update name of a segment on current map"""
        if self.status.has_temporary_map:
            raise InvalidActionException("Cannot edit segment when temporary map is present")

        if self._map_manager:
            segment_info = self._map_manager.editor.set_segment_name(segment_id, segment_type, custom_name)
            if segment_info:
                data = {"nsr": segment_info}
                if self.status.current_map:
                    data["mapid"] = self.status.current_map.map_id
                if self.capability.auto_rename_segment:
                    data["autonsr"] = True
                return self.update_map_data_async(data)

    def set_segment_order(self, segment_id: int, order: int) -> dict[str, Any] | None:
        """Update cleaning order of a segment on current map"""
        if self._map_manager and not self.status.has_temporary_map:
            if order is None or (isinstance(order, str) and not order.isnumeric()):
                order = 0

            cleaning_order = self._map_manager.editor.set_segment_order(segment_id, order)

            return self.update_map_data_async({"cleanOrder": cleaning_order})

    def set_segment_cleaning_mode(self, segment_id: int, cleaning_mode: int) -> dict[str, Any] | None:
        """Update mop pad humidity of a segment on current map"""
        if self._map_manager and not self.status.has_temporary_map:
            return self.set_cleanset(self._map_manager.editor.set_segment_cleaning_mode(segment_id, cleaning_mode))

    def set_segment_cleaning_route(self, segment_id: int, cleaning_route: int) -> dict[str, Any] | None:
        """Update cleaning route of a segment on current map"""
        if (
            self.capability.cleaning_route
            and self._map_manager
            and not self.status.has_temporary_map
        ):
            return self.set_cleanset(self._map_manager.editor.set_segment_cleaning_route(segment_id, cleaning_route))

    def set_segment_cleaning_times(self, segment_id: int, cleaning_times: int) -> dict[str, Any] | None:
        """Update cleaning times of a segment on current map."""
        if self.status.started:
            raise InvalidActionException("Cannot set zone cleaning times while mower is running")

        if self._map_manager and not self.status.has_temporary_map:
            return self.set_cleanset(self._map_manager.editor.set_segment_cleaning_times(segment_id, cleaning_times))

    def set_segment_floor_material(
        self, segment_id: int, floor_material: int, direction: int = None
    ) -> dict[str, Any] | None:
        """Update floor material of a segment on current map"""
        if self._map_manager and not self.status.has_temporary_map:
            if not self.capability.floor_direction_cleaning:
                direction = None
            else:
                if floor_material != 1:
                    direction = None
                elif direction is None:
                    segment = self.status.segments[segment_id]
                    direction = (
                        segment.floor_material_rotated_direction
                        if segment.floor_material_rotated_direction is not None
                        else (
                            0
                            if self.status.current_map.rotation == 0 or self.status.current_map.rotation == 90
                            else 90
                        )
                    )

            data = {"nsm": self._map_manager.editor.set_segment_floor_material(segment_id, floor_material, direction)}
            if self.status.selected_map:
                data["map_id"] = self.status.selected_map.map_id
            return self.update_map_data_async(data)

    def set_segment_floor_material_direction(
        self, segment_id: int, floor_material_direction: int
    ) -> dict[str, Any] | None:
        """Update floor material direction of a segment on current map"""
        if self.capability.floor_direction_cleaning and self._map_manager and not self.status.has_temporary_map:
            data = {
                "nsm": self._map_manager.editor.set_segment_floor_material(segment_id, 1, floor_material_direction)
            }
            if self.status.selected_map:
                data["map_id"] = self.status.selected_map.map_id
            return self.update_map_data_async(data)

    def set_segment_visibility(self, segment_id: int, visibility: int) -> dict[str, Any] | None:
        """Update visibility a segment on current map"""
        if self.capability.segment_visibility and self._map_manager and not self.status.has_temporary_map:
            data = {"delsr": self._map_manager.editor.set_segment_visibility(segment_id, int(visibility))}
            # if self.status.selected_map:
            #    data["map_id"] = self.status.selected_map.map_id
            return self.update_map_data_async(data)

    @property
    def _update_interval(self) -> float:
        """Dynamic update interval of the device for the timer."""
        now = time.time()
        if self.status.map_backup_status or self.status.map_recovery_status:
            return 2
        if self._last_update_failed:
            return 5 if now - self._last_update_failed <= 60 else 10 if now - self._last_update_failed <= 300 else 30
        if not -self._last_change <= 60:
            return 3 if self.status.active else 5
        if self.status.active or self.status.started:
            return 3 if self.status.running else 5
        if self._map_manager:
            return min(self._map_update_interval, 10)
        return 10

    @property
    def _map_update_interval(self) -> float:
        """Dynamic map update interval for the map manager."""
        if self._map_manager:
            if self._protocol.dreame_cloud:
                return 10 if self.status.active else 30
            now = time.time()
            if now - self._last_map_request <= 120 or now - self._last_change <= 60:
                return 2.5 if self.status.active or self.status.started else 5
            return 3 if self.status.running else 10 if self.status.active else 30
        return -1

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self._name

    @property
    def device_connected(self) -> bool:
        """Return connection status of the device."""
        return self._protocol.connected

    @property
    def cloud_connected(self) -> bool:
        """Return connection status of the device."""
        return (
            self._protocol.cloud
            and self._protocol.cloud.connected
            and (not self._protocol.prefer_cloud or self.device_connected)
        )

    @property
    def mowing_telemetry(self):
        """Return the most recently decoded s1p4 telemetry (MowingTelemetry or None)."""
        return self.data.get(DreameMowerProperty.MOWING_TELEMETRY.value)

    @property
    def latest_position(self) -> tuple[int, int] | None:
        """Return the most recently observed (x_cm, y_mm) position.

        Sourced from either a 33-byte s1p4 full telemetry frame (active mow) or
        the 8-byte s1p4 beacon (docked / remote-drive / idle). Independent of
        `mowing_telemetry` which stays at its last full-shape value so
        phase/area/distance sensors don't flicker when the mower drops back to
        beacon-only output.
        """
        return self._latest_position

    @property
    def latest_session_summary(self):
        """Return the most recently fetched SessionSummary, or None.

        Populated by `_fetch_session_summary` on every `event_occured` MQTT
        message (once per completed mowing session on g2408). Contains the
        lawn boundary polygon, full mow path (as segments), obstacle
        polygons, exclusion zones, dock coordinates, and timing — all in
        metres relative to the charger. See `protocol.session_summary`.
        """
        return self._latest_session_summary

    @property
    def latest_session_raw(self):
        """Return the raw JSON dict for the most recently fetched session.

        Kept alongside the parsed `latest_session_summary` so archivers can
        write the authentic wire payload to disk. `None` when no session
        has been fetched yet.
        """
        return self._latest_session_raw

    @property
    def cfg(self) -> dict:
        """Most recent settings dict from `getCFG`. Empty until first
        successful fetch (see `refresh_cfg`)."""
        return self._cfg

    @property
    def cfg_fetched_at(self) -> float | None:
        return self._cfg_fetched_at

    @property
    def routed_actions_supported(self) -> bool | None:
        """Tri-state probe of whether `siid:2 aiid:50` routed actions work
        on this firmware. None until first call attempt; True on success;
        False once the cloud returns a 404 (the apk's CFG/PRE/DOCK/action
        infrastructure is firmware-dependent — confirmed absent on g2408)."""
        return self._routed_actions_supported

    # Routed-action retry/backoff tuning. A single transient 80001 no
    # longer permanently disables CFG fetching — we exp-back-off and only
    # hard-disable after _CFG_HARD_DISABLE_AFTER consecutive failures.
    _CFG_HARD_DISABLE_AFTER = 10
    _CFG_BACKOFF_CAP_S = 600  # 10 min

    def _routed_action_in_backoff(self) -> bool:
        """True while the next routed-action attempt should be skipped."""
        return time.time() < self._cfg_next_retry_at

    def _routed_action_note_failure(self, reason: str, is_nonetype: bool) -> None:
        """Record a failure, schedule exp-backoff, and hard-disable the
        tri-state flag once a long run of consecutive failures suggests
        the firmware actually doesn't support the endpoint (vs. a cloud
        relay being flaky)."""
        now = time.time()
        self._cfg_consecutive_failures += 1
        self._cfg_failure_count += 1
        self._cfg_last_failure_reason = reason
        self._cfg_last_failure_ts = now
        delay = min(30 * (2 ** (self._cfg_consecutive_failures - 1)), self._CFG_BACKOFF_CAP_S)
        self._cfg_next_retry_at = now + delay
        if is_nonetype and self._cfg_consecutive_failures >= self._CFG_HARD_DISABLE_AFTER:
            self._routed_actions_supported = False
            _LOGGER.warning(
                "[routed-action] %d consecutive NoneType failures — "
                "hard-disabling for this HA process. Reload the config "
                "entry or restart HA to retry.",
                self._cfg_consecutive_failures,
            )

    def _routed_action_note_success(self) -> None:
        """Reset backoff/strike tracking after any successful call."""
        self._cfg_consecutive_failures = 0
        self._cfg_next_retry_at = 0.0
        self._cfg_success_count += 1

    def refresh_cfg(self) -> bool:
        """Fetch the full settings dict via the routed action. Stores the
        result in `self._cfg` and returns True on success. Logs + returns
        False on any error (cloud failure, malformed envelope, etc.) —
        the cache is preserved so transient errors don't blank existing
        entity state. Synchronous; call from an executor (e.g.
        `hass.async_add_executor_job`) to avoid blocking the event loop.
        """
        from ..protocol.cfg_action import get_cfg, CfgActionError

        if self._protocol is None:
            return False
        if self._routed_actions_supported is False:
            return False
        if self._routed_action_in_backoff():
            return False
        try:
            cfg = get_cfg(self._protocol.action)
        except CfgActionError as ex:
            is_nonetype = "NoneType" in str(ex)
            self._routed_action_note_failure(str(ex), is_nonetype)
            if is_nonetype:
                _LOGGER.warning(
                    "refresh_cfg: routed action returned no data "
                    "(80001 relay-timeout or 404). Retry #%d scheduled "
                    "in %ds.",
                    self._cfg_consecutive_failures,
                    int(self._cfg_next_retry_at - time.time()),
                )
            else:
                _LOGGER.warning("refresh_cfg: %s", ex)
            return False
        except Exception as ex:  # pragma: no cover — defensive
            self._routed_action_note_failure(repr(ex), False)
            _LOGGER.warning("refresh_cfg: unexpected error %s", ex)
            return False
        # Compute diff vs previous cfg — any key whose value changed
        # is logged at WARNING so app-side toggles immediately reveal
        # which CFG slot they drive. One-shot-per-toggle, quiet at
        # steady state. Also persists per-key change timestamps in
        # `_cfg_recent_changes` so the cfg_keys_raw sensor can expose
        # a "which keys just moved" view without needing log tailing.
        prev = self._cfg
        now = time.time()
        changed = {}
        if isinstance(prev, dict) and prev:
            for k in sorted(set(prev.keys()) | set(cfg.keys())):
                if prev.get(k) != cfg.get(k):
                    changed[k] = (prev.get(k), cfg.get(k))
        for k, (old, new) in changed.items():
            self._cfg_recent_changes[k] = {
                "old": old, "new": new, "changed_at": now
            }
        self._cfg_last_diff = dict(changed)
        self._cfg_last_diff_at = now if changed else self._cfg_last_diff_at
        self._cfg = cfg
        self._cfg_fetched_at = now
        self._routed_actions_supported = True
        self._routed_action_note_success()
        _LOGGER.info("[CFG] fetched %d settings keys", len(cfg))
        _LOGGER.debug("[CFG] payload: %r", cfg)
        if changed:
            _LOGGER.warning(
                "[CFG_DIFF] %d key(s) changed since last fetch:\n%s",
                len(changed),
                "\n".join(f"  {k}: {old!r} -> {new!r}" for k, (old, new) in changed.items()),
            )
        return True

    def write_pre(self, index: int, value: int) -> bool:
        """Read the current PRE array, replace one slot, and write the
        updated array back via setPRE. Returns True on success.

        `index` must be a valid PRE slot (0..9). Caller is responsible
        for value validation (range, enum membership).
        """
        from ..protocol.cfg_action import set_pre, CfgActionError

        if self._protocol is None or not getattr(self._protocol, "connected", False):
            _LOGGER.warning("write_pre: protocol not connected")
            return False
        # Always read the freshest PRE before modifying — the cache may
        # be seconds out of date if the user just toggled something via
        # the app.
        if not self.refresh_cfg():
            _LOGGER.warning("write_pre: refresh_cfg failed; aborting")
            return False
        pre = self._cfg.get("PRE")
        if not isinstance(pre, list) or len(pre) < 10:
            _LOGGER.warning("write_pre: no PRE array in cfg")
            return False
        if not 0 <= index < len(pre):
            _LOGGER.warning("write_pre: index %d out of range", index)
            return False
        new_pre = list(pre)
        new_pre[index] = value
        try:
            set_pre(self._protocol.action, new_pre)
        except (CfgActionError, ValueError) as ex:
            _LOGGER.warning("write_pre: set_pre failed: %s", ex)
            return False
        # Update local cache immediately so the entity reflects the
        # change without waiting for the next s2p52 push.
        self._cfg = dict(self._cfg)
        self._cfg["PRE"] = new_pre
        _LOGGER.info("write_pre: PRE[%d] = %r -> %r", index, pre[index], value)
        return True

    @property
    def dock_pos(self) -> dict | None:
        return self._dock_pos

    @property
    def maintenance_points(self) -> list[dict]:
        """All user-placed Maintenance Points, parsed from the cloud MAP
        `cleanPoints` key. List of `{id, x_mm, y_mm}` in cloud-frame mm
        (same frame as `device.go_to`). Empty list until the map has
        been fetched and the user has placed at least one point."""
        return list(self._maintenance_points)

    @property
    def maintenance_point(self) -> dict | None:
        """Convenience accessor for the first Maintenance Point, or None
        if no points exist. Used by `maintenance_point_x_mm` / `_y_mm`
        sensors to show the most likely target at a glance. See
        `maintenance_points` for the full list."""
        return self._maintenance_points[0] if self._maintenance_points else None

    def maintenance_point_by_id(self, point_id: int) -> dict | None:
        """Look up a Maintenance Point by its firmware-assigned id.
        Returns None if no point with that id exists."""
        for pt in self._maintenance_points:
            if pt.get("id") == point_id:
                return pt
        return None

    @property
    def cloud_mpath(self) -> list | None:
        """Most recent M_PATH from the cloud userdata fetch. Set by
        `_build_map_from_cloud_data`. Used by live_map's boot-time
        restore when in_progress.json is missing or empty."""
        return self._cloud_mpath

    @property
    def voice_dl_progress(self) -> int | None:
        """Voice-pack download progress 0..100 (%) from s2p53 per apk."""
        return self._voice_dl_progress

    @property
    def self_check_result(self) -> dict | None:
        """Self-check result dict {mode, id, result} from s2p58 per apk."""
        return self._self_check_result

    def refresh_dock_pos(self) -> bool:
        """Fetch dock position + lawn-connection via the routed getDockPos
        action. Stores the result in `self._dock_pos` and returns True on
        success. Synchronous; call from an executor."""
        from ..protocol.cfg_action import get_dock_pos, CfgActionError

        if self._protocol is None:
            return False
        if self._routed_actions_supported is False:
            return False
        if self._routed_action_in_backoff():
            return False
        try:
            self._dock_pos = get_dock_pos(self._protocol.action)
        except CfgActionError as ex:
            is_nonetype = "NoneType" in str(ex)
            self._routed_action_note_failure(str(ex), is_nonetype)
            if is_nonetype:
                _LOGGER.warning(
                    "refresh_dock_pos: routed action returned no data "
                    "(retry #%d in %ds).",
                    self._cfg_consecutive_failures,
                    int(self._cfg_next_retry_at - time.time()),
                )
            else:
                _LOGGER.warning("refresh_dock_pos: %s", ex)
            return False
        except Exception as ex:  # pragma: no cover — defensive
            self._routed_action_note_failure(repr(ex), False)
            _LOGGER.warning("refresh_dock_pos: unexpected error %s", ex)
            return False
        self._routed_action_note_success()
        _LOGGER.info("[DOCK] %s", self._dock_pos)
        return True

    def call_action_opcode(self, op: int, extra: dict | None = None) -> bool:
        """Invoke a routed action opcode via siid:2 aiid:50. See
        protocol/cfg_action.py and apk.md for the opcode catalog
        (9 findBot, 11 suppressFault, 12 lockBot, 100 globalMower,
        101 edgeMower, 102 zoneMower, 110 startLearningMap,
        401 takePic, 503 cutterBias, ...). Synchronous; call from
        an executor."""
        from ..protocol.cfg_action import call_action_op

        if self._protocol is None:
            _LOGGER.warning("call_action_opcode: no protocol")
            return False
        if self._routed_actions_supported is False:
            _LOGGER.warning(
                "call_action_opcode(%d): routed actions disabled (cloud "
                "returned 404 on prior probe — g2408 firmware doesn't "
                "support siid:2 aiid:50). Use the existing native action "
                "buttons instead.",
                op,
            )
            return False
        if self._routed_action_in_backoff():
            _LOGGER.warning(
                "call_action_opcode(%d): in backoff window after recent "
                "failure (retry in %ds)",
                op, int(self._cfg_next_retry_at - time.time()),
            )
            return False
        try:
            call_action_op(self._protocol.action, op, extra)
        except Exception as ex:
            is_nonetype = "NoneType" in str(ex) or "404" in str(ex)
            self._routed_action_note_failure(str(ex), is_nonetype)
            if is_nonetype:
                _LOGGER.warning(
                    "call_action_opcode(%d): cloud returned no data "
                    "(retry #%d in %ds)",
                    op, self._cfg_consecutive_failures,
                    int(self._cfg_next_retry_at - time.time()),
                )
            else:
                _LOGGER.warning("call_action_opcode(%d): %s", op, ex)
            return False
        self._routed_action_note_success()
        return True

    @property
    def heartbeat(self):
        """Return the most recently decoded s1p1 heartbeat (Heartbeat or None)."""
        return self.data.get(DreameMowerProperty.HEARTBEAT.value)

    @property
    def last_config_event(self):
        """Return the most recently decoded s2p51 config event (S2P51Event or None)."""
        return self.data.get(DreameMowerProperty.MULTIPLEXED_CONFIG.value)

    @property
    def obstacle_detected(self) -> bool | None:
        """Return the s1p53 obstacle flag, or None if never seen."""
        value = self.data.get(DreameMowerProperty.OBSTACLE_FLAG.value)
        return bool(value) if value is not None else None

    @property
    def battery_temp_low(self) -> bool | None:
        """Return the s1p1 HEARTBEAT byte[6]&0x08 low-temp charging-paused flag.

        Asserted by the mower while it refuses to charge because the battery
        is below its safe-charge threshold (the Dreame app surfaces this as
        "Battery temperature is low. Charging stopped."). Returns None if no
        heartbeat has been decoded yet. See docs/research/g2408-protocol.md
        §3.4 and §4.4 for the signal discovery and wire-level evidence.
        """
        hb = self.data.get(DreameMowerProperty.HEARTBEAT.value)
        if hb is None:
            return None
        return bool(getattr(hb, "battery_temp_low", False))

    @property
    def positioning_failed(self) -> bool | None:
        """True when the mower's most recent `s2p2` code is 71.

        `s2p2 = 71` is the g2408's *Positioning Failed* marker — the
        mower cannot locate itself on the saved map (e.g. parked outside
        the known area, loop-closure failed). Recovery requires driving
        the mower back into the known area so SLAM relocation
        (§4.8) can re-anchor. Returns None before any `s2p2` has been
        seen in the current process lifetime.
        """
        if self._s2p2_last is None:
            return None
        return self._s2p2_last == 71

    @property
    def rain_protection_active(self) -> bool | None:
        """True when the mower's most recent `s2p2` code is 56 —
        Dreame app's *"Water is detected on the LiDAR. Rain Protection
        is activated."* signal. Cleared when the next `s2p2` arrives.
        """
        if self._s2p2_last is None:
            return None
        return self._s2p2_last == 56

    @property
    def slam_activity(self) -> str | None:
        """Most recent SLAM task-type label from `s2p65` — e.g.
        `'TASK_SLAM_RELOCATE'` during LiDAR relocalization. None before
        the first `s2p65` arrives. Because the mower only fires s2p65
        when a SLAM task is actively dispatched, this doesn't
        auto-clear; consumers should treat a stale value as "last
        known SLAM activity" rather than "currently running".
        """
        return self._s2p65_last


class DreameMowerDeviceStatus:
    """Helper class for device status and int enum type properties.
    This class is used for determining various states of the device by its properties.
    Determined states are used by multiple validation and rendering condition checks.
    Almost of the rules are extracted from mobile app that has a similar class with same purpose.
    """

    def __init__(self, device):
        self._device: DreameMowerDevice = device
        self._cleaning_history = None
        self._cleaning_history_attrs = None
        self._last_cleaning_time = None
        self._cruising_history = None
        self._cruising_history_attrs = None
        self._last_cruising_time = None
        self._history_map_data: dict[str, MapData] = {}
        self._previous_cleaning_sequence: dict[int, list[int]] = {}

        self.cleaning_mode_list = {v: k for k, v in CLEANING_MODE_CODE_TO_NAME.items()}
        self.wider_corner_coverage_list = {v: k for k, v in WIDER_CORNER_COVERAGE_TO_NAME.items()}
        self.second_cleaning_list = {v: k for k, v in SECOND_CLEANING_TO_NAME.items()}
        self.cleaning_route_list = {v: k for k, v in CLEANING_ROUTE_TO_NAME.items()}
        self.cleangenius_list = {v: k for k, v in CLEANGENIUS_TO_NAME.items()}
        self.floor_material_list = {v: k for k, v in FLOOR_MATERIAL_CODE_TO_NAME.items()}
        self.floor_material_direction_list = {v: k for k, v in FLOOR_MATERIAL_DIRECTION_CODE_TO_NAME.items()}
        self.visibility_list = {v: k for k, v in SEGMENT_VISIBILITY_CODE_TO_NAME.items()}
        self.voice_assistant_language_list = {v: k for k, v in VOICE_ASSISTANT_LANGUAGE_TO_NAME.items()}
        self.segment_cleaning_mode_list = {}
        self.segment_cleaning_route_list = {}
        self.warning_codes = [
            DreameMowerErrorCode.TASK_CANCELLED,
            DreameMowerErrorCode.MOWING_COMPLETE,
            DreameMowerErrorCode.STATION_DISCONNECTED,
            DreameMowerErrorCode.SELF_TEST_FAILED,
            DreameMowerErrorCode.LOW_BATTERY_TURN_OFF,
            DreameMowerErrorCode.UNKNOWN_WARNING_2,
        ]

        self.cleaning_mode = None
        self.ai_policy_accepted = False
        self.go_to_zone: GoToZoneSettings = None
        self.cleanup_completed: bool = False
        self.cleanup_started: bool = False

        self.stream_status = None
        self.stream_session = None

        self.dnd_tasks = None
        self.off_peak_charging_config = None
        self.shortcuts = None

    def _get_property(self, prop: DreameMowerProperty) -> Any:
        """Helper function for accessing a property from device"""
        _LOGGER.debug("Getting property: %s", prop)
        result = self._device.get_property(prop)
        _LOGGER.debug("Result: %s", result)
        return result

    @property
    def _capability(self) -> DreameMowerDeviceCapability:
        """Helper property for accessing device capabilities"""
        return self._device.capability

    @property
    def _map_manager(self) -> DreameMapMowerMapManager | None:
        """Helper property for accessing map manager from device"""
        return self._device._map_manager

    @property
    def _device_connected(self) -> bool:
        """Helper property for accessing device connection status"""
        return self._device.device_connected

    @property
    def battery_level(self) -> int:
        """Return battery level of the device."""
        return self._get_property(DreameMowerProperty.BATTERY_LEVEL)

    @property
    def cleaning_mode_name(self) -> str:
        """Return cleaning mode as string for translation."""
        return CLEANING_MODE_CODE_TO_NAME.get(self.cleaning_mode, STATE_UNKNOWN)

    @property
    def status(self) -> DreameMowerStatus:
        """Return status of the device."""
        value = self._get_property(DreameMowerProperty.STATUS)
        if value is not None and value in DreameMowerStatus._value2member_map_:
            if self.go_to_zone and value == DreameMowerStatus.ZONE_CLEANING.value:
                return DreameMowerStatus.CRUISING_POINT
            if value == DreameMowerStatus.CHARGING.value and not self.charging:
                return DreameMowerStatus.IDLE
            return DreameMowerStatus(value)
        if value is not None:
            _LOGGER.debug("STATUS not supported: %s", value)
        return DreameMowerStatus.UNKNOWN

    @property
    def status_name(self) -> str:
        """Return status as string for translation."""
        return STATUS_CODE_TO_NAME.get(self.status, STATE_UNKNOWN)

    @property
    def task_status(self) -> DreameMowerTaskStatus:
        """Return task status of the device."""
        value = self._get_property(DreameMowerProperty.TASK_STATUS)
        if value is not None and value in DreameMowerTaskStatus._value2member_map_:
            if self.go_to_zone:
                if value == DreameMowerTaskStatus.ZONE_CLEANING.value:
                    return DreameMowerTaskStatus.CRUISING_POINT
                if value == DreameMowerTaskStatus.ZONE_CLEANING_PAUSED.value:
                    return DreameMowerTaskStatus.CRUISING_POINT_PAUSED
            return DreameMowerTaskStatus(value)
        if value is not None:
            _LOGGER.debug("TASK_STATUS not supported: %s", value)
        return DreameMowerTaskStatus.UNKNOWN

    @property
    def task_status_name(self) -> str:
        """Return task status as string for translation."""
        return TASK_STATUS_CODE_TO_NAME.get(self.task_status, STATE_UNKNOWN)

    @property
    def charging_status(self) -> DreameMowerChargingStatus:
        """Return charging status of the device."""
        value = self._get_property(DreameMowerProperty.CHARGING_STATUS)
        if value is not None and value in DreameMowerChargingStatus._value2member_map_:
            value = DreameMowerChargingStatus(value)
            # Charging status complete is not present on older firmwares
            if value is DreameMowerChargingStatus.CHARGING and self.battery_level == 100:
                return DreameMowerChargingStatus.CHARGING_COMPLETED
            return value
        if value is not None:
            _LOGGER.debug("CHARGING_STATUS not supported: %s", value)
        return DreameMowerChargingStatus.UNKNOWN

    @property
    def charging_status_name(self) -> str:
        """Return charging status as string for translation."""
        return CHARGING_STATUS_CODE_TO_NAME.get(self.charging_status, STATE_UNKNOWN)

    @property
    def relocation_status(self) -> DreameMowerRelocationStatus:
        """Return relocation status of the device."""
        value = self._get_property(DreameMowerProperty.RELOCATION_STATUS)
        if value is not None and value in DreameMowerRelocationStatus._value2member_map_:
            return DreameMowerRelocationStatus(value)
        if value is not None:
            _LOGGER.debug("RELOCATION_STATUS not supported: %s", value)
        return DreameMowerRelocationStatus.UNKNOWN

    @property
    def relocation_status_name(self) -> str:
        """Return relocation status as string for translation."""
        return RELOCATION_STATUS_CODE_TO_NAME.get(self.relocation_status, STATE_UNKNOWN)

    @property
    def state(self) -> DreameMowerState:
        """Return state of the device."""
        value = self._get_property(DreameMowerProperty.STATE)

        # g2408 emits state codes (27/48/50/54/70) that aren't in
        # DreameMowerState. Map them to the closest enum member before
        # the generic translation path so the lawn_mower entity and other
        # consumers show meaningful activity.
        if (
            value is not None
            and self._device.info is not None
            and self._device.info.model == "dreame.mower.g2408"
        ):
            _G2408_STATE_MAP = {
                27: DreameMowerState.IDLE,
                48: DreameMowerState.CHARGING_COMPLETED,
                50: DreameMowerState.MOWING,  # session start — treat as active mow
                54: DreameMowerState.RETURNING,
                70: DreameMowerState.MOWING,
            }
            mapped = _G2408_STATE_MAP.get(int(value))
            if mapped is not None:
                value = mapped.value

        # Legacy old-state enum remap removed 2026-04-20; A2 always uses
        # the new-state enum.
        if value is not None and value in DreameMowerState._value2member_map_:
            if self.go_to_zone and (
                value == DreameMowerState.IDLE
                or value == DreameMowerState.MOWING.value
            ):
                if self.paused:
                    return DreameMowerState.MONITORING_PAUSED
                return DreameMowerState.MONITORING
            mower_state = DreameMowerState(value)

            ## Determine state as implemented on the app
            if mower_state is DreameMowerState.IDLE:
                if self.started or self.cleaning_paused or self.fast_mapping_paused:
                    return DreameMowerState.PAUSED
                elif self.docked:
                    if self.charging:
                        return DreameMowerState.CHARGING
                    ## This is for compatibility with various lovelace mower cards
                    ## Device will report idle when charging is completed and mower card will display return to dock icon even when robot is docked
                    if self.charging_status is DreameMowerChargingStatus.CHARGING_COMPLETED:
                        return DreameMowerState.CHARGING_COMPLETED
            return mower_state
        if value is not None:
            _LOGGER.debug("STATE not supported: %s", value)
        return DreameMowerState.UNKNOWN

    @property
    def state_name(self) -> str:
        """Return state as string for translation."""
        # For g2408 the raw s2p2 codes (48/54/70/50/27) aren't in
        # DreameMowerState — translate via the protocol.properties_g2408
        # label table instead of falling through to "unknown".
        if (
            self._device.info is not None
            and self._device.info.model == "dreame.mower.g2408"
        ):
            raw = self._get_property(DreameMowerProperty.STATE)
            if raw is not None:
                from ..protocol.properties_g2408 import state_label
                label = state_label(int(raw))
                if not label.startswith("unknown_"):
                    return label
        return STATE_CODE_TO_STATE.get(self.state, STATE_UNKNOWN)

    @property
    def stream_status_name(self) -> str:
        """Return camera stream status as string for translation."""
        return STREAM_STATUS_TO_NAME.get(self.stream_status, STATE_UNKNOWN)

    @property
    def wider_corner_coverage(self) -> DreameMowerWiderCornerCoverage:
        value = self._device.get_auto_switch_property(DreameMowerAutoSwitchProperty.WIDER_CORNER_COVERAGE)
        if value is not None and value < 0:
            value = 0
        if value is not None and value in DreameMowerWiderCornerCoverage._value2member_map_:
            return DreameMowerWiderCornerCoverage(value)
        if value is not None:
            _LOGGER.debug("WIDER_CORNER_COVERAGE not supported: %s", value)
        return DreameMowerWiderCornerCoverage.UNKNOWN

    @property
    def wider_corner_coverage_name(self) -> str:
        """Return wider corner coverage as string for translation."""
        wider_corner_coverage = 0 if self.wider_corner_coverage < 0 else self.wider_corner_coverage
        if (
            wider_corner_coverage is not None
            and wider_corner_coverage in DreameMowerWiderCornerCoverage._value2member_map_
        ):
            return WIDER_CORNER_COVERAGE_TO_NAME.get(
                DreameMowerWiderCornerCoverage(wider_corner_coverage), STATE_UNKNOWN
            )
        return STATE_UNKNOWN

    @property
    def cleaning_route(self) -> DreameMowerCleaningRoute:
        if self._capability.cleaning_route:
            value = self._device.get_auto_switch_property(DreameMowerAutoSwitchProperty.CLEANING_ROUTE)
            if value is not None and value < 0:
                value = 0
            if value is not None and value in DreameMowerCleaningRoute._value2member_map_:
                return DreameMowerCleaningRoute(value)
            if value is not None:
                _LOGGER.debug("CLEANING_ROUTE not supported: %s", value)
            return DreameMowerCleaningRoute.UNKNOWN

    @property
    def cleaning_route_name(self) -> str:
        """Return cleaning route as string for translation."""
        cleaning_route = 0 if self.cleaning_route < 0 else self.cleaning_route
        if cleaning_route is not None and cleaning_route in DreameMowerCleaningRoute._value2member_map_:
            return CLEANING_ROUTE_TO_NAME.get(DreameMowerCleaningRoute(cleaning_route), STATE_UNKNOWN)
        return STATE_UNKNOWN

    @property
    def cleangenius(self) -> DreameMowerCleanGenius:
        if self._capability.cleangenius:
            value = self._device.get_auto_switch_property(DreameMowerAutoSwitchProperty.CLEANGENIUS)
            if value is not None and value < 0:
                value = 0
            if value is not None and value in DreameMowerCleanGenius._value2member_map_:
                return DreameMowerCleanGenius(value)
            if value is not None:
                _LOGGER.debug("CLEANGENIUS not supported: %s", value)
        return DreameMowerCleanGenius.UNKNOWN

    @property
    def cleangenius_name(self) -> str:
        """Return CleanGenius as string for translation."""
        cleangenius = 0 if not self.cleangenius or self.cleangenius < 0 else self.cleangenius
        if cleangenius is not None and cleangenius in DreameMowerCleanGenius._value2member_map_:
            return CLEANGENIUS_TO_NAME.get(DreameMowerCleanGenius(cleangenius), STATE_UNKNOWN)
        return STATE_UNKNOWN

    @property
    def voice_assistant_language(self) -> DreameMowerVoiceAssistantLanguage:
        """Return voice assistant language of the device."""
        value = self._get_property(DreameMowerProperty.VOICE_ASSISTANT_LANGUAGE)
        if value is not None and value in DreameMowerVoiceAssistantLanguage._value2member_map_:
            return DreameMowerVoiceAssistantLanguage(value)
        if value is not None:
            _LOGGER.debug("VOICE_ASSISTANT_LANGUAGE not supported: %s", value)
        return DreameMowerVoiceAssistantLanguage.DEFAULT

    @property
    def voice_assistant_language_name(self) -> str:
        """Return voice assistant language as string for translation."""
        return VOICE_ASSISTANT_LANGUAGE_TO_NAME.get(self.voice_assistant_language, STATE_UNKNOWN)

    @property
    def task_type(self) -> DreameMowerTaskType:
        """Return drainage status of the device."""
        value = self._get_property(DreameMowerProperty.TASK_TYPE)
        if value is not None and value in DreameMowerTaskType._value2member_map_:
            return DreameMowerTaskType(value)
        if value is not None:
            _LOGGER.debug("TASK_TYPE not supported: %s", value)
        return DreameMowerTaskType.UNKNOWN

    @property
    def task_type_name(self) -> str:
        """Return drainage status as string for translation."""
        return TASK_TYPE_TO_NAME.get(self.task_type, STATE_UNKNOWN)

    @property
    def faults(self) -> str:
        faults = self._get_property(DreameMowerProperty.FAULTS)
        return 0 if faults == "" or faults == " " else faults

    @property
    def error(self) -> DreameMowerErrorCode:
        """Return error of the device."""
        value = self._get_property(DreameMowerProperty.ERROR)
        if value is not None and value in DreameMowerErrorCode._value2member_map_:
            if value in (
                DreameMowerErrorCode.LOW_BATTERY_TURN_OFF.value,
                DreameMowerErrorCode.UNKNOWN_WARNING_2.value,
                DreameMowerErrorCode.MOWING_COMPLETE.value,
                DreameMowerErrorCode.TASK_CANCELLED.value,
            ):
                return DreameMowerErrorCode.NO_ERROR
            return DreameMowerErrorCode(value)
        if value is not None:
            _LOGGER.debug("ERROR_CODE not supported: %s", value)
        return DreameMowerErrorCode.UNKNOWN

    @property
    def error_name(self) -> str:
        """Return error as string for translation."""
        if not self.has_error and not self.has_warning:
            return ERROR_CODE_TO_ERROR_NAME.get(DreameMowerErrorCode.NO_ERROR)
        return ERROR_CODE_TO_ERROR_NAME.get(self.error, STATE_UNKNOWN)

    @property
    def error_description(self) -> str:
        """Return error description of the device."""
        return ERROR_CODE_TO_ERROR_DESCRIPTION.get(self.error, [STATE_UNKNOWN, ""])

    @property
    def error_image(self) -> str:
        """Return error image of the device as base64 string."""
        if not self.has_error:
            return None
        return ERROR_IMAGE.get(ERROR_CODE_TO_IMAGE_INDEX.get(self.error, 19))

    @property
    def robot_status(self) -> int:  # TODO: Convert to enum
        """Device status for robot icon rendering."""
        value = 0
        if self.running and not self.returning and not self.fast_mapping and not self.cruising:
            value = 1
        elif self.charging:
            value = 2
        elif self.sleeping:
            value = 3
        if self.has_error:
            value += 10
        return value

    @property
    def has_error(self) -> bool:
        """Returns true when an error is present."""
        error = self.error
        return bool(error.value > 0 and not self.has_warning and error is not DreameMowerErrorCode.BATTERY_LOW)

    @property
    def has_warning(self) -> bool:
        """Returns true when a warning is present and available for dismiss."""
        error = self.error
        return bool(error.value > 0 and error in self.warning_codes)

    @property
    def scheduled_clean(self) -> bool:
        if self.started:
            value = self._get_property(DreameMowerProperty.SCHEDULED_CLEAN)
            return bool(value == 1 or value == 2 or value == 4)
        return False

    @property
    def camera_light_brightness(self) -> int:
        if self._capability.camera_streaming:
            brightness = self._get_property(DreameMowerProperty.CAMERA_LIGHT_BRIGHTNESS)
            if brightness and str(brightness).isnumeric():
                return int(brightness)

    @property
    def dnd_remaining(self) -> bool:
        """Returns remaining seconds to DND period to end."""
        if self.dnd:
            dnd_start = self.dnd_start
            dnd_end = self.dnd_end
            if dnd_start and dnd_end:
                end_time = dnd_end.split(":")
                if len(end_time) == 2:
                    now = datetime.now()
                    hour = now.hour
                    minute = now.minute
                    if minute < 10:
                        minute = f"0{minute}"

                    time = int(f"{hour}{minute}")
                    start = int(dnd_start.replace(":", ""))
                    end = int(dnd_end.replace(":", ""))
                    current_seconds = hour * 3600 + int(minute) * 60
                    end_seconds = int(end_time[0]) * 3600 + int(end_time[1]) * 60

                    if (
                        start < end
                        and start < time
                        and time < end
                        or end < start
                        and (2400 > time and time > start or end > time and time > 0)
                        or time == start
                        or time == end
                    ):
                        return (
                            (end_seconds + 86400 - current_seconds)
                            if current_seconds > end_seconds
                            else (end_seconds - current_seconds)
                        )
                return 0
        return None

    @property
    def located(self) -> bool:
        """Returns true when robot knows its position on current map."""
        relocation_status = self.relocation_status
        return bool(
            relocation_status is DreameMowerRelocationStatus.LOCATED
            or relocation_status is DreameMowerRelocationStatus.UNKNOWN
            or self.fast_mapping
        )

    @property
    def sweeping(self) -> bool:
        """Returns true when cleaning mode is sweeping."""
        cleaning_mode = self.cleaning_mode
        return 1

    @property
    def zone_cleaning(self) -> bool:
        """Returns true when device is currently performing a zone cleaning task."""
        task_status = self.task_status
        return bool(
            self._device_connected
            and self.started
            and (
                task_status is DreameMowerTaskStatus.ZONE_CLEANING
                or task_status is DreameMowerTaskStatus.ZONE_CLEANING_PAUSED
                or task_status is DreameMowerTaskStatus.ZONE_DOCKING_PAUSED
            )
        )

    @property
    def spot_cleaning(self) -> bool:
        """Returns true when device is currently performing a spot cleaning task."""
        task_status = self.task_status
        return bool(
            self._device_connected
            and self.started
            and (
                task_status is DreameMowerTaskStatus.SPOT_CLEANING
                or task_status is DreameMowerTaskStatus.SPOT_CLEANING_PAUSED
                or self.status is DreameMowerStatus.SPOT_CLEANING
            )
        )

    @property
    def segment_cleaning(self) -> bool:
        """Returns true when device is currently performing a custom segment cleaning task."""
        task_status = self.task_status
        return bool(
            self._device_connected
            and self.started
            and (
                task_status is DreameMowerTaskStatus.SEGMENT_CLEANING
                or task_status is DreameMowerTaskStatus.SEGMENT_CLEANING_PAUSED
                or task_status is DreameMowerTaskStatus.SEGMENT_DOCKING_PAUSED
            )
        )

    @property
    def auto_cleaning(self) -> bool:
        """Returns true when device is currently performing a complete map cleaning task."""
        task_status = self.task_status
        return bool(
            self._device_connected
            and self.started
            and (
                task_status is DreameMowerTaskStatus.AUTO_CLEANING
                or task_status is DreameMowerTaskStatus.AUTO_CLEANING_PAUSED
                or task_status is DreameMowerTaskStatus.AUTO_DOCKING_PAUSED
            )
        )

    @property
    def fast_mapping(self) -> bool:
        """Returns true when device is creating a new map."""
        return bool(
            self._device_connected
            and (
                self.task_status is DreameMowerTaskStatus.FAST_MAPPING
                or self.status is DreameMowerStatus.FAST_MAPPING
                or self.fast_mapping_paused
            )
        )

    @property
    def fast_mapping_paused(self) -> bool:
        """Returns true when creating a new map paused by user.
        Used for resuming fast cleaning on start because standard start action can not be used for resuming fast mapping.
        """

        state = self._get_property(DreameMowerProperty.STATE)
        task_status = self.task_status
        return bool(
            (
                task_status is DreameMowerTaskStatus.FAST_MAPPING
                or task_status is DreameMowerTaskStatus.MAP_CLEANING_PAUSED
            )
            and (
                state == DreameMowerState.PAUSED.value
                or state == DreameMowerState.ERROR.value
                or state == DreameMowerState.IDLE.value
            )
        )

    @property
    def cruising(self) -> bool:
        """Returns true when device is cruising."""
        if self._capability.cruising:
            task_status = self.task_status
            status = self.status
            return bool(
                task_status is DreameMowerTaskStatus.CRUISING_PATH
                or task_status is DreameMowerTaskStatus.CRUISING_POINT
                or task_status is DreameMowerTaskStatus.CRUISING_PATH_PAUSED
                or task_status is DreameMowerTaskStatus.CRUISING_POINT_PAUSED
                or status is DreameMowerStatus.CRUISING_PATH
                or status is DreameMowerStatus.CRUISING_POINT
            )
        return bool(self.go_to_zone)

    @property
    def cruising_paused(self) -> bool:
        """Returns true when cruising paused."""
        if self._capability.cruising:
            task_status = self.task_status
            return bool(
                task_status is DreameMowerTaskStatus.CRUISING_PATH_PAUSED
                or task_status is DreameMowerTaskStatus.CRUISING_POINT_PAUSED
            )
        if self.go_to_zone:
            status = self.status
            if self.started and (
                status is DreameMowerStatus.PAUSED
                or status is DreameMowerStatus.SLEEPING
                or status is DreameMowerStatus.IDLE
                or status is DreameMowerStatus.STANDBY
            ):
                return True
        return False

    @property
    def resume_cleaning(self) -> bool:
        """Returns true when resume_cleaning is enabled."""
        return bool(
            self._get_property(DreameMowerProperty.RESUME_CLEANING) == (2 if self._capability.auto_charging else 1)
        )

    @property
    def cleaning_paused(self) -> bool:
        """Returns true when device battery is too low for resuming its task and needs to be charged before continuing."""
        return bool(self._get_property(DreameMowerProperty.CLEANING_PAUSED))

    @property
    def charging(self) -> bool:
        """Returns true when device is currently charging."""
        return bool(self.charging_status is DreameMowerChargingStatus.CHARGING)

    @property
    def docked(self) -> bool:
        """Returns true when device is docked."""
        return bool(
            (
                self.charging
                or self.charging_status is DreameMowerChargingStatus.CHARGING_COMPLETED
            )
            and not (self.running and not self.returning and not self.fast_mapping and not self.cruising)
        )

    @property
    def sleeping(self) -> bool:
        """Returns true when device is sleeping."""
        return bool(self.status is DreameMowerStatus.SLEEPING)

    @property
    def returning_paused(self) -> bool:
        """Returns true when returning to dock is paused."""
        task_status = self.task_status
        return bool(
            self._device_connected
            and task_status is DreameMowerTaskStatus.DOCKING_PAUSED
            or task_status is DreameMowerTaskStatus.AUTO_DOCKING_PAUSED
            or task_status is DreameMowerTaskStatus.SEGMENT_DOCKING_PAUSED
            or task_status is DreameMowerTaskStatus.ZONE_DOCKING_PAUSED
        )

    @property
    def returning(self) -> bool:
        """Returns true when returning to dock for charging."""
        return bool(self._device_connected and (self.status is DreameMowerStatus.BACK_HOME))

    @property
    def started(self) -> bool:
        """Returns true when device has an active task.
        Used for preventing updates on settings that relates to currently performing task.
        """
        status = self.status
        task_status = self.task_status
        # Devices that do not emit TASK_STATUS at all (e.g. dreame.mower.g2408,
        # where the property upstream expects at siid=4,piid=7 is never pushed)
        # make task_status permanently UNKNOWN. The original condition
        # `task_status is not COMPLETED and task_status is not DOCKING_PAUSED`
        # then latches True forever, leaving binary sensors like
        # `mowing_session_active` stuck on while the mower is docked and
        # charging after a completed run. Treat UNKNOWN the same as COMPLETED
        # for the purposes of this check — the `or` chain below still flips to
        # True when the device reports an actively-mowing status, so this only
        # affects the no-evidence case.
        task_active_by_status = (
            task_status is not DreameMowerTaskStatus.COMPLETED
            and task_status is not DreameMowerTaskStatus.DOCKING_PAUSED
            and task_status is not DreameMowerTaskStatus.UNKNOWN
        )
        # g2408 supplementary signal: session state from s2p56. Either
        # "running" or "pending resume" means a task is live from the
        # mower's perspective — the app still shows Continue/End, and
        # HA's Mowing Session Active should agree.
        task_active_by_s2p56 = bool(
            self._device._task_running_s2p56 or self._device._task_pending_resume
        )
        return bool(
            task_active_by_status
            or task_active_by_s2p56
            or self.cleaning_paused
            or status is DreameMowerStatus.CLEANING
            or status is DreameMowerStatus.SEGMENT_CLEANING
            or status is DreameMowerStatus.ZONE_CLEANING
            or status is DreameMowerStatus.SPOT_CLEANING
            or status is DreameMowerStatus.PART_CLEANING
            or status is DreameMowerStatus.FAST_MAPPING
            or status is DreameMowerStatus.CRUISING_PATH
            or status is DreameMowerStatus.CRUISING_POINT
            or status is DreameMowerStatus.SHORTCUT
        )

    @property
    def paused(self) -> bool:
        """Returns true when device has an active paused task."""
        status = self.status
        return bool(
            self.cleaning_paused
            or self.cruising_paused
            or (
                self.started
                and (
                    status is DreameMowerStatus.PAUSED
                    or status is DreameMowerStatus.SLEEPING
                    or status is DreameMowerStatus.IDLE
                    or status is DreameMowerStatus.STANDBY
                )
            )
        )

    @property
    def active(self) -> bool:
        """Returns true when device is moving or not sleeping."""
        return self.status is DreameMowerStatus.STANDBY or self.running

    @property
    def running(self) -> bool:
        """Returns true when device is moving."""
        status = self.status
        return bool(
            not (
                self.charging
                or self.charging_status is DreameMowerChargingStatus.CHARGING_COMPLETED
            )
            and (
                status is DreameMowerStatus.CLEANING
                or status is DreameMowerStatus.BACK_HOME
                or status is DreameMowerStatus.PART_CLEANING
                or status is DreameMowerStatus.FOLLOW_WALL
                or status is DreameMowerStatus.REMOTE_CONTROL
                or status is DreameMowerStatus.SEGMENT_CLEANING
                or status is DreameMowerStatus.ZONE_CLEANING
                or status is DreameMowerStatus.SPOT_CLEANING
                or status is DreameMowerStatus.PART_CLEANING
                or status is DreameMowerStatus.FAST_MAPPING
                or status is DreameMowerStatus.CRUISING_PATH
                or status is DreameMowerStatus.CRUISING_POINT
                or status is DreameMowerStatus.SUMMON_CLEAN
                or status is DreameMowerStatus.SHORTCUT
                or status is DreameMowerStatus.PERSON_FOLLOW
            )
        )

    @property
    def shortcut_task(self) -> bool:
        """Returns true when device has an active shortcut task."""
        if self.started and self.shortcuts:
            for k, v in self.shortcuts.items():
                if v.running:
                    return True
        return False

    @property
    def customized_cleaning(self) -> bool:
        """Returns true when customized cleaning feature is enabled."""
        return bool(
            self._get_property(DreameMowerProperty.CUSTOMIZED_CLEANING)
            and self.has_saved_map
            and not self.cleangenius_cleaning
        )

    @property
    def cleangenius_cleaning(self) -> bool:
        """Returns true when CleanGenius feature is enabled."""
        return bool(
            self._capability.cleangenius
            and self._get_property(DreameMowerAutoSwitchProperty.CLEANGENIUS)
            and not self.zone_cleaning
            and not self.spot_cleaning
        )

    @property
    def max_suction_power(self) -> bool:
        """Returns true when max suction power feature is enabled."""
        return bool(
            self._capability.max_suction_power and self._get_property(DreameMowerAutoSwitchProperty.MAX_SUCTION_POWER)
        )

    @property
    def multi_map(self) -> bool:
        """Returns true when multi floor map feature is enabled."""
        return bool(self._get_property(DreameMowerProperty.MULTI_FLOOR_MAP))

    @property
    def last_cleaning_time(self) -> datetime | None:
        if self._cleaning_history:
            return self._last_cleaning_time

    @property
    def last_cruising_time(self) -> datetime | None:
        if self._cruising_history:
            return self._last_cruising_time

    @property
    def cleaning_history(self) -> dict[str, Any] | None:
        """Returns the cleaning history list as dict."""
        if self._cleaning_history:
            if self._cleaning_history_attrs is None:
                list = {}
                for history in self._cleaning_history:
                    date = time.strftime("%m-%d %H:%M", time.localtime(history.date.timestamp()))
                    list[date] = {
                        ATTR_TIMESTAMP: history.date.timestamp(),
                        ATTR_CLEANING_TIME: f"{history.cleaning_time} min",
                        ATTR_CLEANED_AREA: f"{history.cleaned_area} m²",
                    }
                    if history.status is not None:
                        list[date][ATTR_STATUS] = (
                            STATUS_CODE_TO_NAME.get(history.status, STATE_UNKNOWN).replace("_", " ").capitalize()
                        )
                    if history.completed is not None:
                        list[date][ATTR_COMPLETED] = history.completed
                    if history.neglected_segments:
                        list[date][ATTR_NEGLECTED_SEGMENTS] = {
                            k: v.name.replace("_", " ").capitalize() for k, v in history.neglected_segments.items()
                        }
                    if history.cleanup_method is not None:
                        list[date][ATTR_CLEANUP_METHOD] = history.cleanup_method.name.replace("_", " ").capitalize()
                    if history.task_interrupt_reason is not None:
                        list[date][ATTR_INTERRUPT_REASON] = history.task_interrupt_reason.name.replace(
                            "_", " "
                        ).capitalize()
                self._cleaning_history_attrs = list
            return self._cleaning_history_attrs

    @property
    def cruising_history(self) -> dict[str, Any] | None:
        """Returns the cruising history list as dict."""
        if self._cruising_history:
            if self._cruising_history_attrs is None:
                list = {}
                for history in self._cruising_history:
                    date = time.strftime("%m-%d %H:%M", time.localtime(history.date.timestamp()))
                    list[date] = {
                        ATTR_CRUISING_TIME: f"{history.cleaning_time} min",
                    }
                    if history.status is not None:
                        list[date][ATTR_STATUS] = (
                            STATUS_CODE_TO_NAME.get(history.status, STATE_UNKNOWN).replace("_", " ").capitalize()
                        )
                    if history.cruise_type is not None:
                        list[date][ATTR_CRUISING_TYPE] = history.cruise_type
                    if history.map_index is not None:
                        list[date][ATTR_MAP_INDEX] = history.map_index
                    if history.map_name is not None and len(history.map_name) > 1:
                        list[date][ATTR_MAP_NAME] = history.map_name
                    if history.completed is not None:
                        list[date][ATTR_COMPLETED] = history.completed
                self._cruising_history_attrs = list
            return self._cruising_history_attrs

    @property
    def maximum_maps(self) -> int:
        return (
            1 if not self._capability.lidar_navigation or not self.multi_map else 4 if self._capability.wifi_map else 3
        )

    @property
    def mapping_available(self) -> bool:
        """Returns true when creating a new map is possible."""
        return bool(
            not self.started
            and not self.fast_mapping
            and (not self._device.capability.map or self.maximum_maps > len(self.map_list))
        )

    @property
    def second_cleaning_available(self) -> bool:
        if self._cleaning_history and self.current_map:
            history = self._cleaning_history[0]
            if history.object_name:
                map_data = self._history_map_data.get(history.object_name)
                return bool(
                    (map_data is not None and self.current_map.map_id == map_data.map_id)
                    and (
                        bool(history.neglected_segments)
                        or bool(
                            history.cleanup_method.value == 2
                            and map_data.cleaned_segments
                            and map_data.cleaning_map_data is not None
                            and map_data.cleaning_map_data.has_dirty_area
                        )
                    )
                )
        return False

    @property
    def blades_life(self) -> int:
        """Returns blade remaining life in percent."""
        return self._get_property(DreameMowerProperty.BLADES_LEFT)

    @property
    def side_brush_life(self) -> int:
        """Returns side brush remaining life in percent."""
        return self._get_property(DreameMowerProperty.SIDE_BRUSH_LEFT)

    @property
    def filter_life(self) -> int:
        """Returns filter remaining life in percent."""
        return self._get_property(DreameMowerProperty.FILTER_LEFT)

    @property
    def sensor_dirty_life(self) -> int:
        """Returns sensor clean remaining time in percent."""
        return self._get_property(DreameMowerProperty.SENSOR_DIRTY_LEFT)

    @property
    def tank_filter_life(self) -> int:
        """Returns tank filter remaining life in percent."""
        return self._get_property(DreameMowerProperty.TANK_FILTER_LEFT)

    @property
    def silver_ion_life(self) -> int:
        """Returns silver-ion life in percent."""
        return self._get_property(DreameMowerProperty.SILVER_ION_LEFT)

    @property
    def lensbrush_life(self) -> int:
        """Returns lensbrush life in percent."""
        return 30000 - self._get_property(DreameMowerProperty.LENSBRUSH_LEFT)['CMS'][0]

    @property
    def squeegee_life(self) -> int:
        """Returns squeegee life in percent."""
        return self._get_property(DreameMowerProperty.SQUEEGEE_LEFT)

    @property
    def dnd(self) -> bool | None:
        """Returns DND is enabled."""
        if self._capability.dnd:
            if not self._capability.dnd_task:
                return bool(self._get_property(DreameMowerProperty.DND))
            if self.dnd_tasks and len(self.dnd_tasks):
                return self.dnd_tasks[0].get("en")
            # Fallback: DND_TASK is empty, try simple DND property
            dnd_val = self._get_property(DreameMowerProperty.DND)
            if dnd_val is not None:
                return bool(dnd_val)
            return False

    @property
    def dnd_start(self) -> str | None:
        """Returns DND start time."""
        if self._capability.dnd:
            if not self._capability.dnd_task:
                return self._get_property(DreameMowerProperty.DND_START)
            if self.dnd_tasks and len(self.dnd_tasks):
                return self.dnd_tasks[0].get("st")
            # Fallback: try simple DND_START property
            val = self._get_property(DreameMowerProperty.DND_START)
            return val if val is not None else "22:00"

    @property
    def dnd_end(self) -> str | None:
        """Returns DND end time."""
        if self._capability.dnd:
            if not self._capability.dnd_task:
                return self._get_property(DreameMowerProperty.DND_END)
            if self.dnd_tasks and len(self.dnd_tasks):
                return self.dnd_tasks[0].get("et")
            # Fallback: try simple DND_END property
            val = self._get_property(DreameMowerProperty.DND_END)
            return val if val is not None else "08:00"

    @property
    def off_peak_charging(self) -> bool | None:
        """Returns Off-Peak charging is enabled."""
        if self._capability.off_peak_charging:
            return bool(
                self._capability.off_peak_charging
                and len(self.off_peak_charging_config)
                and self.off_peak_charging_config.get("enable")
            )

    @property
    def off_peak_charging_start(self) -> str | None:
        """Returns Off-Peak charging start time."""
        if self._capability.off_peak_charging:
            return (
                self.off_peak_charging_config.get("startTime")
                if self.off_peak_charging_config and len(self.off_peak_charging_config)
                else "22:00"
            )

    @property
    def off_peak_charging_end(self) -> str | None:
        """Returns Off-Peak charging end time."""
        if self._capability.off_peak_charging:
            return (
                self.off_peak_charging_config.get("endTime")
                if self.off_peak_charging_config and len(self.off_peak_charging_config)
                else "08:00"
            )

    @property
    def ai_obstacle_detection(self) -> bool:
        return self._device.get_ai_property(DreameMowerAIProperty.AI_OBSTACLE_DETECTION)

    @property
    def ai_obstacle_image_upload(self) -> bool:
        return self._device.get_ai_property(DreameMowerAIProperty.AI_OBSTACLE_IMAGE_UPLOAD)

    @property
    def ai_pet_detection(self) -> bool:
        return self._device.get_ai_property(DreameMowerAIProperty.AI_PET_DETECTION)

    @property
    def ai_furniture_detection(self) -> bool:
        return self._device.get_ai_property(DreameMowerAIProperty.AI_FURNITURE_DETECTION)

    @property
    def ai_fluid_detection(self) -> bool:
        return self._device.get_ai_property(DreameMowerAIProperty.AI_FLUID_DETECTION)

    @property
    def ai_obstacle_picture(self) -> bool:
        return self._device.get_ai_property(DreameMowerAIProperty.AI_OBSTACLE_PICTURE)

    @property
    def fill_light(self) -> bool:
        return self._device.get_auto_switch_property(DreameMowerAutoSwitchProperty.FILL_LIGHT)

    @property
    def stain_avoidance(self) -> bool:
        return bool(self._device.get_auto_switch_property(DreameMowerAutoSwitchProperty.STAIN_AVOIDANCE) == 2)

    @property
    def pet_focused_cleaning(self) -> bool:
        return self._device.get_auto_switch_property(DreameMowerAutoSwitchProperty.PET_FOCUSED_CLEANING)

    @property
    def map_backup_status(self) -> int | None:
        return self._get_property(DreameMowerProperty.MAP_BACKUP_STATUS)

    @property
    def map_recovery_status(self) -> int | None:
        return self._get_property(DreameMowerProperty.MAP_RECOVERY_STATUS)

    @property
    def custom_order(self) -> bool:
        """Returns true when custom cleaning sequence is set."""
        if self.cleangenius_cleaning:
            return False
        segments = self.current_segments
        if segments:
            for v in segments.values():
                if v.order:
                    return True
        return False

    @property
    def segment_order(self) -> list[int] | None:
        """Returns cleaning order list."""
        segments = self.current_segments
        if segments:
            return (
                list(
                    sorted(
                        segments,
                        key=lambda segment_id: segments[segment_id].order if segments[segment_id].order else 99,
                    )
                )
                if self.custom_order
                else None
            )
        return [] if self.custom_order else None

    @property
    def has_saved_map(self) -> bool:
        """Returns true when device has saved map and knowns its location on saved map."""
        if self._map_manager is None:
            return True

        current_map = self.current_map
        return bool(
            current_map is not None
            and current_map.saved_map_status == 2
            and not self.has_temporary_map
            and not self.has_new_map
            and not current_map.empty_map
        )

    @property
    def has_temporary_map(self) -> bool:
        """Returns true when device cannot store the newly created map and waits prompt for restoring or discarding it."""
        if self._map_manager is None:
            return False

        current_map = self.current_map
        return bool(current_map is not None and current_map.temporary_map and not current_map.empty_map)

    @property
    def has_new_map(self) -> bool:
        """Returns true when fast mapping from empty map."""
        if self._map_manager is None:
            return False

        current_map = self.current_map
        return bool(
            current_map is not None
            and not current_map.temporary_map
            and not current_map.empty_map
            and current_map.new_map
        )

    @property
    def selected_map(self) -> MapData | None:
        """Return the selected map data"""
        if self._map_manager and not self.has_temporary_map and not self.has_new_map:
            return self._map_manager.selected_map

    @property
    def current_map(self) -> MapData | None:
        """Return the current map data"""
        if self._map_manager:
            return self._map_manager.get_map()

    @property
    def map_list(self) -> list[int] | None:
        """Return the saved map id list if multi floor map is enabled"""
        if self._map_manager:
            if self.multi_map:
                return self._map_manager.map_list

            selected_map = self._map_manager.selected_map
            if selected_map:
                return [selected_map.map_id]
        return []

    @property
    def map_data_list(self) -> dict[int, MapData] | None:
        """Return the saved map data list if multi floor map is enabled"""
        if self._map_manager:
            if self.multi_map:
                return self._map_manager.map_data_list
            selected_map = self.selected_map
            if selected_map:
                return {selected_map.map_id: selected_map}
        return {}

    @property
    def current_segments(self) -> dict[int, Segment] | None:
        """Return the segments of current map"""
        current_map = self.current_map
        if current_map and current_map.segments and not current_map.empty_map:
            return current_map.segments
        return {}

    @property
    def segments(self) -> dict[int, Segment] | None:
        """Return the segments of selected map"""
        current_map = self.selected_map
        if current_map and current_map.segments and not current_map.empty_map:
            return current_map.segments
        return {}

    @property
    def current_zone(self) -> Segment | None:
        """Return the segment that device is currently on"""
        if self._capability.lidar_navigation:
            current_map = self.current_map
            if current_map and current_map.segments and current_map.robot_segment and not current_map.empty_map:
                return current_map.segments[current_map.robot_segment]

    @property
    def cleaning_sequence(self) -> list[int] | None:
        """Returns custom segment cleaning sequence list."""
        if self._map_manager:
            return self._map_manager.cleaning_sequence

    @property
    def previous_cleaning_sequence(self):
        if self.current_map and self.current_map.map_id in self._previous_cleaning_sequence:
            return self._previous_cleaning_sequence[self.current_map.map_id]

    @property
    def active_segments(self) -> list[int] | None:
        map_data = self.current_map
        if map_data and self.started and not self.fast_mapping:
            if self.segment_cleaning:
                if map_data.active_segments:
                    return map_data.active_segments
            elif (
                not self.zone_cleaning
                and not self.spot_cleaning
                and map_data.segments
                and not self.docked
                and not self.returning
                and not self.returning_paused
            ):
                return list(map_data.segments.keys())
            return []

    @property
    def job(self) -> dict[str, Any] | None:
        attributes = {
            ATTR_STATUS: self.status.name,
        }
        if self._device._protocol.cloud:
            attributes[ATTR_DID] = self._device._protocol.cloud.device_id
        if self._capability.custom_cleaning_mode:
            attributes[ATTR_CLEANING_MODE] = self.cleaning_mode.name

        if self.cleanup_completed:
            attributes.update(
                {
                    ATTR_CLEANED_AREA: self._get_property(DreameMowerProperty.CLEANED_AREA),
                    ATTR_CLEANING_TIME: self._get_property(DreameMowerProperty.CLEANING_TIME),
                    ATTR_COMPLETED: True,
                }
            )
        else:
            attributes[ATTR_COMPLETED] = False

        map_data = self.current_map
        if map_data:
            if map_data.active_segments:
                attributes[ATTR_ACTIVE_SEGMENTS] = map_data.active_segments
            elif map_data.active_areas is not None:
                if self.go_to_zone:
                    attributes[ATTR_ACTIVE_CRUISE_POINTS] = {
                        1: Coordinate(self.go_to_zone.x, self.go_to_zone.y, False, 0)
                    }
                else:
                    attributes[ATTR_ACTIVE_AREAS] = map_data.active_areas
            elif map_data.active_points is not None:
                attributes[ATTR_ACTIVE_POINTS] = map_data.active_points
            elif map_data.predefined_points is not None:
                attributes[ATTR_PREDEFINED_POINTS] = map_data.predefined_points
            elif map_data.active_cruise_points is not None:
                attributes[ATTR_ACTIVE_CRUISE_POINTS] = map_data.active_cruise_points
        return attributes

    @property
    def attributes(self) -> dict[str, Any] | None:
        """Return the attributes of the device."""
        properties = [
            DreameMowerProperty.STATUS,
            DreameMowerProperty.CLEANING_MODE,
            DreameMowerProperty.ERROR,
            DreameMowerProperty.CLEANING_TIME,
            DreameMowerProperty.CLEANED_AREA,
            DreameMowerProperty.VOICE_PACKET_ID,
            DreameMowerProperty.TIMEZONE,
            DreameMowerProperty.BLADES_TIME_LEFT,
            DreameMowerProperty.BLADES_LEFT,
            DreameMowerProperty.SIDE_BRUSH_TIME_LEFT,
            DreameMowerProperty.SIDE_BRUSH_LEFT,
            DreameMowerProperty.FILTER_LEFT,
            DreameMowerProperty.FILTER_TIME_LEFT,
            DreameMowerProperty.TANK_FILTER_LEFT,
            DreameMowerProperty.TANK_FILTER_TIME_LEFT,
            DreameMowerProperty.SILVER_ION_LEFT,
            DreameMowerProperty.SILVER_ION_TIME_LEFT,
            DreameMowerProperty.LENSBRUSH_LEFT,
            DreameMowerProperty.LENSBRUSH_TIME_LEFT,
            DreameMowerProperty.SQUEEGEE_LEFT,
            DreameMowerProperty.SQUEEGEE_TIME_LEFT,
            DreameMowerProperty.TOTAL_CLEANED_AREA,
            DreameMowerProperty.TOTAL_CLEANING_TIME,
            DreameMowerProperty.CLEANING_COUNT,
            DreameMowerProperty.CUSTOMIZED_CLEANING,
            DreameMowerProperty.SERIAL_NUMBER,
            DreameMowerProperty.NATION_MATCHED,
            DreameMowerProperty.TOTAL_RUNTIME,
            DreameMowerProperty.TOTAL_CRUISE_TIME,
            DreameMowerProperty.CLEANING_PROGRESS,
            DreameMowerProperty.INTELLIGENT_RECOGNITION,
            DreameMowerProperty.MULTI_FLOOR_MAP,
            DreameMowerProperty.SCHEDULED_CLEAN,
            DreameMowerProperty.VOICE_ASSISTANT_LANGUAGE,
        ]

        if not self._capability.disable_sensor_cleaning:
            properties.extend(
                [
                    DreameMowerProperty.SENSOR_DIRTY_LEFT,
                    DreameMowerProperty.SENSOR_DIRTY_TIME_LEFT,
                ]
            )

        if not self._capability.dnd_task:
            properties.extend(
                [
                    DreameMowerProperty.DND_START,
                    DreameMowerProperty.DND_END,
                ]
            )

        attributes = {}

        for prop in properties:
            value = self._get_property(prop)
            if value is not None:
                prop_name = PROPERTY_TO_NAME.get(prop.name)
                if prop_name:
                    prop_name = prop_name[0]
                else:
                    prop_name = prop.name.lower()

                if prop is DreameMowerProperty.ERROR:
                    value = self.error_name.replace("_", " ").capitalize()
                elif prop is DreameMowerProperty.STATUS:
                    value = self.status_name.replace("_", " ").capitalize()
                elif prop is DreameMowerProperty.CLEANING_MODE:
                    value = self.cleaning_mode_name.replace("_", " ").capitalize()
                    attributes[f"{prop_name}_list"] = (
                        [v.replace("_", " ").capitalize() for v in self.cleaning_mode_list.keys()]
                        if PROPERTY_AVAILABILITY[prop.name](self._device)
                        else []
                    )
                elif prop is DreameMowerProperty.VOICE_ASSISTANT_LANGUAGE:
                    if not self._capability.voice_assistant:
                        continue
                    value = self.voice_assistant_language_name.replace("_", " ").capitalize()
                    attributes[f"{prop_name}_list"] = [
                        v.replace("_", " ").capitalize() for v in self.voice_assistant_language_list.keys()
                    ]
                elif prop is DreameMowerAutoSwitchProperty.CLEANING_ROUTE:
                    value = self.cleaning_route_name.replace("_", " ").capitalize()
                    attributes[f"{prop_name}_list"] = (
                        [v.replace("_", " ").capitalize() for v in self.cleaning_route_list.keys()]
                        if PROPERTY_AVAILABILITY[prop.name](self._device)
                        else []
                    )
                elif prop is DreameMowerAutoSwitchProperty.CLEANGENIUS:
                    value = self.cleangenius_name.replace("_", " ").capitalize()
                    attributes[f"{prop_name}_list"] = (
                        [v.replace("_", " ").capitalize() for v in self.cleangenius_list.keys()]
                        if PROPERTY_AVAILABILITY[prop.name](self._device)
                        else []
                    )
                elif prop is DreameMowerProperty.CUSTOMIZED_CLEANING:
                    value = value and not self.zone_cleaning and not self.spot_cleaning
                elif prop is DreameMowerProperty.SCHEDULED_CLEAN:
                    value = bool(value == 1 or value == 2 or value == 4)
                elif (
                    prop is DreameMowerProperty.MULTI_FLOOR_MAP
                    or prop is DreameMowerProperty.INTELLIGENT_RECOGNITION
                ):
                    value = bool(value > 0)
                attributes[prop_name] = value

        if self._capability.dnd_task and self.dnd_tasks is not None:
            attributes[ATTR_DND] = {}
            for dnd_task in self.dnd_tasks:
                attributes[ATTR_DND][dnd_task["id"]] = {
                    "enabled": dnd_task.get("en"),
                    "start": dnd_task.get("st"),
                    "end": dnd_task.get("et"),
                }
        if self._capability.shortcuts and self.shortcuts is not None:
            attributes[ATTR_SHORTCUTS] = {}
            for id, shortcut in self.shortcuts.items():
                attributes[ATTR_SHORTCUTS][id] = {
                    "name": shortcut.name,
                    "running": shortcut.running,
                    "tasks": shortcut.tasks,
                }

        attributes[ATTR_CLEANING_SEQUENCE] = self.segment_order
        attributes[ATTR_CHARGING] = self.docked
        attributes[ATTR_STARTED] = self.started
        attributes[ATTR_PAUSED] = self.paused
        attributes[ATTR_RUNNING] = self.running
        attributes[ATTR_RETURNING_PAUSED] = self.returning_paused
        attributes[ATTR_RETURNING] = self.returning
        attributes[ATTR_SEGMENT_CLEANING] = self.segment_cleaning
        attributes[ATTR_ZONE_CLEANING] = self.zone_cleaning
        attributes[ATTR_SPOT_CLEANING] = self.spot_cleaning
        attributes[ATTR_CRUSING] = self.cruising
        attributes[ATTR_MOWER_STATE] = self.state_name.lower()
        attributes[ATTR_HAS_SAVED_MAP] = self._map_manager is not None and self.has_saved_map
        attributes[ATTR_HAS_TEMPORARY_MAP] = self.has_temporary_map

        if self._capability.lidar_navigation:
            attributes[ATTR_MAPPING] = self.fast_mapping
            attributes[ATTR_MAPPING_AVAILABLE] = self.mapping_available

        if self._capability.cleangenius:
            attributes[ATTR_CLEANGENIUS] = bool(self.cleangenius_cleaning)

        if self.map_list:
            attributes[ATTR_ACTIVE_SEGMENTS] = self.active_segments
            if self._capability.lidar_navigation:
                attributes[ATTR_CURRENT_SEGMENT] = self.current_zone.segment_id if self.current_zone else 0
            attributes[ATTR_SELECTED_MAP] = self.selected_map.map_name if self.selected_map else None
            attributes[ATTR_ZONES] = {}
            for k, v in self.map_data_list.items():
                attributes[ATTR_ZONES][v.map_name] = [
                    {ATTR_ID: j, ATTR_NAME: s.name, ATTR_ICON: s.icon} for (j, s) in sorted(v.segments.items())
                ]
        attributes[ATTR_CAPABILITIES] = self._capability.list
        return attributes

    def consumable_life_warning_description(self, consumable_property) -> str:
        description = CONSUMABLE_TO_LIFE_WARNING_DESCRIPTION.get(consumable_property)
        if description:
            value = self._get_property(consumable_property)
            if value is not None and value >= 0 and value <= 5:
                if value != 0 and len(description) > 1:
                    return description[1]
                return description[0]

    def segment_order_list(self, segment) -> list[int] | None:
        order = []
        if self.current_segments:
            order = [
                v.order
                for k, v in sorted(
                    self.current_segments.items(),
                    key=lambda s: s[1].order if s[1].order != None else 0,
                )
                if v.order
            ]
            if not segment.order and len(order):
                order = order + [max(order) + 1]
        return list(map(str, order))


class DreameMowerDeviceInfo:
    """Container of device information."""

    def __init__(self, data):
        self.data = data
        self.version = 0
        firmware_version = self.firmware_version
        if firmware_version is not None:
            firmware_version = firmware_version.split("_")
            if len(firmware_version) == 2:
                self.version = int(firmware_version[1])

    def __repr__(self):
        return "%s v%s (%s) @ %s - token: %s" % (
            self.model,
            self.version,
            self.mac,
            self.network_interface["localIp"] if self.network_interface else "",
        )

    @property
    def network_interface(self) -> str:
        """Information about network configuration."""
        if "netif" in self.data:
            return self.data["netif"]
        return None

    @property
    def model(self) -> Optional[str]:
        """Model string if available."""
        if "model" in self.data:
            return self.data["model"]
        return None

    @property
    def firmware_version(self) -> Optional[str]:
        """Firmware version if available."""
        if "fw_ver" in self.data and self.data["fw_ver"] is not None:
            return self.data["fw_ver"]
        if "ver" in self.data and self.data["ver"] is not None:
            return self.data["ver"]
        return None

    @property
    def hardware_version(self) -> Optional[str]:
        """Hardware version if available."""
        if "hw_ver" in self.data:
            return self.data["hw_ver"]
        return "Linux"

    @property
    def mac_address(self) -> Optional[str]:
        """MAC address if available."""
        if "mac" in self.data:
            return self.data["mac"]
        return None

    @property
    def manufacturer(self) -> str:
        """Manufacturer name."""
        return "Dreametech™"

    @property
    def raw(self) -> dict[str, Any]:
        """Raw data as returned by the device."""
        return self.data
