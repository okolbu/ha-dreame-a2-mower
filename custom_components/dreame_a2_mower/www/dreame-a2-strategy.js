// Dreame A2 Mower — registered Lovelace dashboard STRATEGY (P5.3).
//
// ONE resource that (a) registers the `custom:dreame-a2-mower` dashboard
// strategy and (b) side-effect-imports every bundled card so a fresh install
// needs a single Lovelace resource entry instead of seven. The strategy
// GENERATES its views from the live entity/device registry — it never hardcodes
// an entity_id — which structurally kills the dead-reference bug class:
//
//   * R-13 — no `attribute: current_map_id` conditionals are ever emitted; the
//     generator uses STATE-compare conditionals (`state: "Map 1"`) and, better,
//     one generated view per registered map device so most conditionals vanish.
//   * R-14 — every entity_id in the output is resolved FROM the registry, so a
//     phantom service / disabled-by-default sensor / renamed entity can never be
//     referenced (an unresolved key simply drops its row).
//   * R-48 — per-map views/cards are generated per registered map sub-device, so
//     a 1-map or 3-map mower is handled with no code change (no hardcoded 2-map
//     assumption).
//   * R-55 — developer-only / experimental content is generated only when its
//     backing entity exists in the registry: gated entities are absent when
//     `experimental_features` is off, so they self-omit (no special-casing).
//
// Grouping source of truth: the MANIFEST below (baked-in machine-readable data
// structure). It references entities by their **unique_id suffix (key)** — the
// stable token that survives entity_id renames — NOT by entity_id. The keys were
// reconciled against the integration's entity classes (`*_unique_id(...)` call
// sites), because the name-derived entity_id slug frequently differs from the
// key (e.g. switch key `dnd` → entity_id `…_do_not_disturb`; per-map select key
// `zone_target` → entity_id `…_map_1_zone`).
//
// The pure generator (`generateDashboard`) is exported and DOM-free so the node
// harness (`tests/www/strategy_harness.mjs`) can exercise it headless. The
// browser-only registration block at the bottom is what ships.

export const DOMAIN = "dreame_a2_mower";
export const STRATEGY_TYPE = "dreame-a2-mower";
const CARD_VERSION = "2.0.1";

// ---------------------------------------------------------------------------
// MANIFEST — the card grouping. Keys are unique_id suffixes.
// ---------------------------------------------------------------------------

const MANIFEST = {
  // Overview "State" summary card (parent-device keys).
  overviewState: [
    { key: "current_activity" },
    { key: "mower_location", name: "Location" },
    { key: "mowing_session_active", name: "Mowing session active" },
    { key: "battery_level", name: "Battery" },
    { key: "charging_status" },
    { key: "mower_in_dock", name: "In dock" },
    { key: "positioning_health" },
    { key: "mqtt_connectivity" },
    { key: "rain_protection_active" },
    { key: "active_selection" },
    { key: "area_mowed_m2", name: "Session area mowed (m²)" },
    { key: "trail_render_width", name: "Trail width (px)" },
  ],

  // Per-map "General Mode" settings (map-device keys, in the app's order).
  perMapGeneral: [
    { key: "mowing_efficiency" },
    { key: "mowing_mode" },
    { key: "settings_mowing_height", name: "Mowing height" },
    { key: "settings_mowing_direction", name: "Direction" },
    { key: "settings_mowing_direction_mode", name: "Pattern" },
    { key: "settings_turning_method", name: "Turning method" },
    { key: "settings_edge_mowing_walk_mode", name: "Edge walk mode" },
    { key: "settings_edge_mowing_auto", name: "Automatic edge mowing" },
    { key: "settings_edge_mowing_safe", name: "Safe edge mowing" },
    { key: "settings_edgemaster", name: "EdgeMaster" },
    { key: "settings_edge_mowing_obstacle_avoidance", name: "Obstacle avoidance on edges" },
    { key: "settings_obstacle_avoidance_enabled", name: "Obstacle avoidance" },
    { key: "settings_obstacle_avoidance_height", name: "Obstacle avoidance height" },
    { key: "ai_recognition_humans", name: "AI recognition — humans" },
    { key: "ai_recognition_animals", name: "AI recognition — animals" },
    { key: "ai_recognition_objects", name: "AI recognition — objects" },
    { key: "settings_obstacle_avoidance_distance", name: "Obstacle avoidance distance" },
  ],

  // Per-map zone/spot/edge target selects (used both on Overview and per-map view).
  perMapTargets: {
    zone: { key: "zone_target", name: "Zone" },
    spot: { key: "spot_target", name: "Spot" },
    edge: { key: "edge_target", name: "Edge" },
  },

  // Per-map zone-count sensors.
  perMapCounts: [
    { key: "exclusion_zones", name: "No-go zones" },
    { key: "ignore_obstacle_zones", name: "Ignore-obstacle zones" },
    { key: "maintenance_points", name: "Maintenance points" },
    { key: "spots", name: "Spots" },
  ],

  // Per-map patrol multi-select cards. `service` is a real integration service.
  perMapPatrol: [
    { key: "patrol_points", title: "Point Patrol", service: "start_point_patrol", id_param: "point_ids" },
    { key: "patrol_edges", title: "Edge Patrol", service: "start_edge_patrol", id_param: "contour_ids" },
  ],

  // Schedule tab device-wide time windows (parent time.* keys).
  scheduleTimes: [
    { key: "dnd_start_time", name: "DnD start" },
    { key: "dnd_end_time", name: "DnD end" },
    { key: "low_speed_at_night_start_time", name: "Low-speed start" },
    { key: "low_speed_at_night_end_time", name: "Low-speed end" },
    { key: "charging_start_time", name: "Charging start" },
    { key: "charging_end_time", name: "Charging end" },
  ],

  // Settings tab — device-wide controls, grouped exactly as the reference dash.
  settings: [
    {
      title: "Consumables & Maintenance",
      keys: [
        { key: "blades_life_pct", name: "Blades" },
        { key: "cleaning_brush_life_pct", name: "Cleaning brush" },
        { key: "robot_maintenance_life_pct", name: "Robot maintenance" },
      ],
    },
    { title: "Work Management", keys: [{ key: "ai_obstacle_photos", name: "Capture photos of AI obstacles" }] },
    {
      title: "Rain Protection",
      keys: [
        { key: "rain_protection", name: "Enabled" },
        { key: "rain_protection_resume_hours", name: "Resume after" },
        { key: "rain_protection_active", name: "Currently delayed" },
      ],
    },
    { title: "Frost Protection", keys: [{ key: "frost_protection", name: "Enabled" }] },
    {
      title: "Do Not Disturb / Nighttime",
      keys: [
        { key: "dnd", name: "Do not disturb" },
        { key: "low_speed_at_night", name: "Low speed at night" },
      ],
    },
    { title: "Navigation Path", keys: [{ key: "navigation_path", name: "Path mode" }] },
    {
      title: "Charging",
      keys: [
        { key: "auto_recharge_standby", name: "Auto-recharge after standby" },
        { key: "auto_recharge_battery_pct", name: "Auto-recharge threshold (%)" },
        { key: "resume_battery_pct", name: "Resume-after-charge threshold (%)" },
        { key: "custom_charging_period", name: "Custom charging period" },
      ],
    },
    {
      title: "LED Light",
      keys: [
        { key: "led_in_standby", name: "In standby" },
        { key: "led_in_error", name: "On error" },
        { key: "led_in_charging", name: "While charging" },
        { key: "led_in_working", name: "While working" },
        { key: "led_period", name: "Period (timed)" },
      ],
    },
    {
      title: "Anti-theft",
      keys: [
        { key: "anti_theft_lift_alarm", name: "Lift alarm" },
        { key: "anti_theft_offmap_alarm", name: "Off-map alarm" },
        { key: "anti_theft_realtime_location", name: "Realtime location" },
      ],
    },
    {
      title: "Human Presence",
      keys: [
        { key: "human_presence_alert", name: "Alert enabled" },
        { key: "human_presence_alert_sensitivity", name: "Sensitivity (0=Low / 1=Medium / 2=High)" },
        { key: "human_presence_scenario_standby", name: "Scenario — standby" },
        { key: "human_presence_scenario_mowing", name: "Scenario — mowing" },
        { key: "human_presence_scenario_recharge", name: "Scenario — recharge" },
        { key: "human_presence_scenario_patrol", name: "Scenario — patrol" },
        { key: "human_presence_alert_voice", name: "Voice + push alert" },
        { key: "human_presence_push_interval_min", name: "Push interval (3 / 10 / 20 min)" },
      ],
    },
    { title: "Child Lock", keys: [{ key: "child_lock", name: "Enabled" }] },
    {
      title: "General — Language & Voice",
      keys: [
        { key: "voice_language", name: "Voice" },
        { key: "lcd_language", name: "LCD language" },
        { key: "volume", name: "Volume" },
        { key: "voice_regular_notification", name: "Regular notification prompt" },
        { key: "voice_work_status", name: "Work status prompt" },
        { key: "voice_special_status", name: "Special status prompt" },
        { key: "voice_error_status", name: "Error status prompt" },
      ],
    },
    {
      title: "Notification messages",
      keys: [
        { key: "msg_alert_anomaly", name: "Anomaly messages" },
        { key: "msg_alert_error", name: "Error messages" },
        { key: "msg_alert_task", name: "Task messages" },
        { key: "msg_alert_consumables", name: "Consumables messages" },
      ],
    },
  ],

  // Diagnostics tab — read-only device identity + connectivity.
  diagIdentity: [
    { key: "firmware_version_dev", name: "Firmware version" },
    { key: "cloud_device_id", name: "Cloud device id" },
    { key: "api_endpoint", name: "API endpoint" },
    { key: "integration_version", name: "Integration version" },
  ],
  diagConnectivity: [
    { key: "wifi_rssi_dbm", name: "WiFi RSSI (dBm)" },
    { key: "wifi_ssid", name: "WiFi SSID" },
    { key: "wifi_ip", name: "WiFi IP" },
    { key: "mqtt_connectivity", name: "MQTT connectivity" },
  ],
  // Experimental / developer diagnostic keys — self-omit when gated off.
  diagExperimental: [
    { key: "mpos", name: "MPOS (x / y / yaw)" },
    { key: "refresh_mpos", name: "Refresh MPOS" },
    { key: "novel_observations", name: "Novel observations" },
    { key: "api_endpoints_supported", name: "Endpoints probed" },
  ],

  // Tools tab. lock_robot + generate_3d_map are deliberately EXCLUDED
  // (D9 accepted-but-no-effect on g2408 / T6-16).
  toolsManual: [
    { key: "refresh_cloud_state", name: "Refresh cloud state" },
    { key: "refresh_wifi_heatmaps", name: "Refresh WiFi heatmaps" },
    { key: "finalize_session", name: "Finalize pending session" },
  ],
  toolsRecovery: [
    { key: "find_bot", name: "Find robot" },
    { key: "update_station_location", name: "Update station location" },
  ],

  // Firmware / OTA — the update entity is the honest surface; ota_state/progress
  // are disabled-by-default so they self-omit from the registry (T6-2 dies).
  firmware: [
    { key: "firmware", name: "Firmware update" },
    { key: "ota_state", name: "OTA state" },
    { key: "ota_progress", name: "OTA progress" },
  ],

  // Sessions tab widgets.
  sessionLatest: [
    { key: "latest_session_duration_min", name: "Latest duration" },
    { key: "latest_session_area_m2", name: "Latest area mowed (m²)" },
    { key: "latest_session_unix_ts", name: "Latest started at" },
    { key: "archived_session_count", name: "Archived count" },
  ],
  sessionLive: [
    { key: "session_distance_m", name: "Distance (m)" },
    { key: "session_track_point_count", name: "Track points" },
  ],
  // All-time device-wide totals (the mower publishes NO per-map totals — the
  // reference dashboard's per-map rows were dead; these are the real keys from
  // entities/sensor/device.py).
  deviceTotals: [
    { key: "total_lawn_area_m2", name: "Total lawn area" },
    { key: "total_mowed_area_m2", name: "Total area mowed" },
    { key: "total_mowing_time_min", name: "Total mowing time" },
  ],

  // Photos tab glance.
  photoGlance: [
    { key: "photos_obstacle", name: "Obstacle" },
    { key: "photos_patrol", name: "Patrol" },
    { key: "photos_person", name: "Person" },
    { key: "videos", name: "Videos" },
    { key: "oss_storage_pct", name: "Storage %" },
  ],
  photoCameras: [
    { key: "album_photo", name: "Latest photo" },
    { key: "person_photo", name: "Latest person detection" },
    { key: "latest_video_thumb", name: "Latest video (thumbnail)" },
  ],

  // Messages tab — device / service / shared message sensors.
  messages: [
    { key: "device_messages", title: "🤖 Device messages" },
    { key: "service_messages_unread", title: "📨 Service messages" },
    { key: "shared_messages", title: "👥 Shared messages" },
  ],
};

// Real integration service names (services.yaml) that the generated cards call.
// A card that would call a service NOT in this allowlist is never emitted — this
// is the service half of the R-14 "no phantom refs" guarantee (kills the
// documented download_diagnostics / set_zone_setting / clear_zone_setting refs).
const KNOWN_SERVICES = new Set([
  "start_point_patrol",
  "start_edge_patrol",
]);

export { MANIFEST, KNOWN_SERVICES };

// ---------------------------------------------------------------------------
// Registry resolution — build a context of key → entity_id lookups.
// ---------------------------------------------------------------------------

function _reEscape(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Strip the DEFAULT_NAME prefix off a map device name to get its short suffix
// ("Dreame A2 Mower Map 1" → "Map 1"; "Dreame A2 Mower Front Yard" → "Front
// Yard"). The active-map select's STATE is exactly this suffix, so it doubles as
// the STATE-compare value for any Overview conditional (R-13).
function _mapSuffix(name, mapId) {
  const s = String(name || "").replace(/^Dreame A2 Mower\s*/i, "").trim();
  return s || `Map ${mapId + 1}`;
}

// Determine the stable id prefix (hardware SN / mac:… / entry:…) shared by every
// integration unique_id. The parent device can carry MORE THAN ONE domain
// identifier (e.g. the config-entry ULID AND the hardware SN), and only the one
// that actually prefixes the entity unique_ids is the right stable — so prefer a
// candidate that prefixes a uid, then fall back to a `_map_` split, then to the
// longest common uid prefix. (Trusting the first identifier blindly produced
// empty views live: the ULID identifier is listed before the SN, but every
// unique_id is SN-prefixed — see tests/www/strategy_harness.mjs.)
function _deriveStable(parentDevCands, uids) {
  const cands = Array.isArray(parentDevCands)
    ? parentDevCands
    : parentDevCands
      ? [parentDevCands]
      : [];
  for (const cand of cands) {
    if (cand && uids.some((u) => u.startsWith(cand + "_"))) return cand;
  }
  for (const u of uids) {
    const i = u.indexOf("_map_");
    if (i > 0) return u.slice(0, i);
  }
  if (!uids.length) return "";
  let p = uids[0];
  for (const u of uids.slice(1)) {
    let k = 0;
    while (k < p.length && k < u.length && p[k] === u[k]) k++;
    p = p.slice(0, k);
  }
  return p.replace(/_[^_]*$/, "");
}

export async function buildContext(hass) {
  const entReg = (await hass.callWS({ type: "config/entity_registry/list" })) || [];
  let devReg = [];
  try {
    devReg = (await hass.callWS({ type: "config/device_registry/list" })) || [];
  } catch (_e) {
    devReg = [];
  }
  const states = hass.states || {};

  // Integration devices. The parent device may carry several domain identifiers
  // (config-entry ULID, hardware SN, …); collect them ALL and let _deriveStable
  // pick the one that actually prefixes the entity unique_ids.
  const parentDevCands = [];
  const mapDevs = [];
  for (const d of devReg) {
    for (const ident of d.identifiers || []) {
      if (ident[0] !== DOMAIN) continue;
      const id = ident[1];
      const m = /_map_(\d+)$/.exec(id);
      if (m) {
        mapDevs.push({ id: parseInt(m[1], 10), rawId: id, deviceId: d.id, name: d.name_by_user || d.name });
      } else {
        parentDevCands.push(id);
      }
    }
  }

  // Filter to this integration's live, enabled, non-hidden entities.
  const mine = entReg.filter(
    (e) =>
      e.platform === DOMAIN &&
      !e.disabled_by &&
      !e.hidden_by &&
      e.entity_id &&
      Object.prototype.hasOwnProperty.call(states, e.entity_id),
  );
  const stable = _deriveStable(parentDevCands, mine.map((e) => e.unique_id || ""));
  const mapKeyRe = new RegExp("^" + _reEscape(stable) + "_map_(\\d+)_(.+)$");
  const parentRe = new RegExp("^" + _reEscape(stable) + "_(.+)$");

  const parentByKey = {};
  const mapByIdKey = {}; // {mapId: {key: entity_id}}
  const mapIds = new Set(mapDevs.map((m) => m.id));

  for (const e of mine) {
    const uid = e.unique_id || "";
    const mm = mapKeyRe.exec(uid);
    if (mm) {
      const mid = parseInt(mm[1], 10);
      (mapByIdKey[mid] = mapByIdKey[mid] || {})[mm[2]] = e.entity_id;
      mapIds.add(mid);
      continue;
    }
    const pm = parentRe.exec(uid);
    if (pm) parentByKey[pm[1]] = e.entity_id;
  }

  // Assemble the map list (device-registry order, else discovered ids), each
  // carrying its short suffix for view titles + STATE-compare values.
  const nameById = {};
  for (const md of mapDevs) nameById[md.id] = md.name;
  const maps = [...mapIds]
    .sort((a, b) => a - b)
    .map((id) => ({ id, suffix: _mapSuffix(nameById[id], id), byKey: mapByIdKey[id] || {} }));

  return {
    stable,
    parentByKey,
    maps,
    states,
    resolve(key) {
      return parentByKey[key] || null;
    },
    resolveMap(mapId, key) {
      return (mapByIdKey[mapId] || {})[key] || null;
    },
    activeMap: parentByKey["active_map"] || null,
  };
}

// ---------------------------------------------------------------------------
// Card builders — every builder resolves entities from the registry and returns
// `null` when nothing resolves, so the output NEVER carries a dead reference.
// ---------------------------------------------------------------------------

function entitiesCard(ctx, title, rows, extra = {}) {
  const entities = [];
  for (const r of rows) {
    const eid = ctx.resolve(r.key);
    if (!eid) continue;
    entities.push(r.name ? { entity: eid, name: r.name } : { entity: eid });
  }
  if (!entities.length) return null;
  return { type: "entities", title, show_header_toggle: false, entities, ...extra };
}

function mapEntitiesCard(ctx, mapId, title, rows) {
  const entities = [];
  for (const r of rows) {
    const eid = ctx.resolveMap(mapId, r.key);
    if (!eid) continue;
    entities.push(r.name ? { entity: eid, name: r.name } : { entity: eid });
  }
  if (!entities.length) return null;
  return { type: "entities", title, show_header_toggle: false, entities };
}

function glanceCard(ctx, rows, cols) {
  const entities = [];
  for (const r of rows) {
    const eid = ctx.resolve(r.key);
    if (eid) entities.push({ entity: eid, name: r.name });
  }
  if (!entities.length) return null;
  return { type: "glance", show_name: true, show_state: true, columns: cols || entities.length, entities };
}

function markdown(content, title) {
  const card = { type: "markdown", content };
  if (title) card.title = title;
  return card;
}

function headerCard(emoji, title, note) {
  const noteSpan = note
    ? ` &nbsp;<span style="font-size:0.75em;color:var(--secondary-text-color)">${note}</span>`
    : "";
  return markdown(
    `<hr style="border:0;border-top:3px solid var(--primary-color);margin:12px 0 0 0;"/>\n\n## ${emoji} ${title}${noteSpan}`,
  );
}

// A conditional card that is only built when its condition entities resolve —
// so the wrapper can never point at a missing entity. Conditions are STATE
// compares ONLY (never `attribute:`) — R-13.
function stateConditional(conditions, card) {
  if (!card) return null;
  for (const c of conditions) if (!c.entity) return null;
  return { type: "conditional", conditions, card };
}

function buttonRow(ctx, buttons) {
  const cards = [];
  for (const b of buttons) {
    const eid = ctx.resolve(b.key);
    if (eid) cards.push({ type: "button", entity: eid, icon: b.icon, name: b.name, show_state: false });
  }
  if (!cards.length) return null;
  return { type: "horizontal-stack", cards };
}

// ---------------------------------------------------------------------------
// View builders.
// ---------------------------------------------------------------------------

function overviewView(ctx) {
  const cards = [];
  cards.push(headerCard("🤖", "Mower", "live state, map & controls"));

  const estop = ctx.resolve("emergency_stop");
  if (estop) {
    cards.push(
      stateConditional(
        [{ entity: estop, state: "on" }],
        markdown("## ⚠️ Emergency stop activated\nEnter the PIN code on the robot to unlock it."),
      ),
    );
  }

  const stateCard = entitiesCard(ctx, "State", MANIFEST.overviewState);
  const mapCam = ctx.resolve("map");
  const row1 = [];
  if (stateCard) row1.push(stateCard);
  if (mapCam) row1.push({ type: "custom:dreame-mower-map-card", entity: mapCam });
  if (row1.length) cards.push({ type: "grid", columns: row1.length, square: false, cards: row1 });

  // Mowing target: action_mode + per-map target selects (STATE-compare on the
  // active-map name — never an `attribute:` conditional).
  const actionMode = ctx.resolve("action_mode");
  if (actionMode) {
    cards.push({ type: "entities", title: "Mowing target", entities: [{ entity: actionMode, name: "Mode" }] });
    for (const m of ctx.maps) {
      for (const [mode, spec] of Object.entries(MANIFEST.perMapTargets)) {
        const tgt = ctx.resolveMap(m.id, spec.key);
        if (!tgt || !ctx.activeMap) continue;
        cards.push(
          stateConditional(
            [
              { entity: actionMode, state: mode },
              { entity: ctx.activeMap, state: m.suffix },
            ],
            { type: "entities", entities: [{ entity: tgt, name: spec.name }] },
          ),
        );
      }
    }
  }

  // State-aware action rows.
  const sess = ctx.resolve("mowing_session_active");
  const charge = ctx.resolve("charging_status");
  const inDock = ctx.resolve("mower_in_dock");
  const activity = ctx.resolve("current_activity");
  const B = {
    start: { key: "start_mowing", icon: "mdi:play", name: "Start" },
    cont: { key: "start_mowing", icon: "mdi:play", name: "Continue" },
    pause: { key: "pause_mowing", icon: "mdi:pause", name: "Pause" },
    stop: { key: "stop_mowing", icon: "mdi:stop", name: "End" },
    resume: { key: "resume_mowing", icon: "mdi:play-circle", name: "Resume" },
    recharge: { key: "recharge", icon: "mdi:battery-charging", name: "Recharge" },
    cancel: { key: "cancel_dock_return", icon: "mdi:keyboard-return", name: "Cancel dock return" },
  };
  if (sess && charge)
    cards.push(
      stateConditional(
        [{ entity: sess, state: "on" }, { entity: charge, state: "charging" }],
        buttonRow(ctx, [B.cont, B.stop]),
      ),
    );
  if (sess && charge)
    cards.push(
      stateConditional(
        [{ entity: sess, state: "off" }, { entity: charge, state: "charging" }],
        buttonRow(ctx, [B.start]),
      ),
    );
  if (inDock && charge && sess)
    cards.push(
      stateConditional(
        [{ entity: inDock, state: "on" }, { entity: charge, state: "not_charging" }, { entity: sess, state: "off" }],
        buttonRow(ctx, [B.start, B.recharge]),
      ),
    );
  if (activity)
    cards.push(
      stateConditional(
        [{ entity: activity, state: ["mowing", "cruising_to_point", "fast_mapping", "repositioning"] }],
        buttonRow(ctx, [B.pause, B.stop, B.recharge]),
      ),
    );
  if (activity)
    cards.push(
      stateConditional([{ entity: activity, state: "returning" }], buttonRow(ctx, [B.pause, B.cancel, B.stop])),
    );
  if (activity)
    cards.push(
      stateConditional([{ entity: activity, state: "paused" }], buttonRow(ctx, [B.resume, B.cont, B.stop, B.recharge])),
    );
  if (activity && inDock && sess)
    cards.push(
      stateConditional(
        [{ entity: activity, state: ["idle", "at_point"] }, { entity: inDock, state: "off" }, { entity: sess, state: "off" }],
        buttonRow(ctx, [B.start, B.recharge]),
      ),
    );

  // Activity logbook + GPS + head-to-point (per-map).
  const bottom = [];
  const lifecycle = ctx.resolve("lifecycle");
  const alert = ctx.resolve("notification"); // event entity key is "notification" (entity_id …_alert)
  const logEnts = [lifecycle, alert].filter(Boolean);
  if (logEnts.length) bottom.push({ type: "logbook", title: "Mower activity", hours_to_show: 48, entities: logEnts });
  const gps = ctx.resolve("gps");
  if (gps)
    bottom.push({ type: "map", title: "GPS Location", default_zoom: 17, hours_to_show: 0, entities: [{ entity: gps }] });
  for (const m of ctx.maps) {
    const pt = ctx.resolveMap(m.id, "maintenance_point");
    const btn = ctx.resolveMap(m.id, "head_to_point");
    if ((pt || btn) && ctx.activeMap) {
      const ents = [];
      if (pt) ents.push({ entity: pt, name: "Point" });
      if (btn) ents.push({ entity: btn, name: "Head to point", icon: "mdi:map-marker-right" });
      bottom.push(
        stateConditional(
          [{ entity: ctx.activeMap, state: m.suffix }],
          { type: "entities", title: "Head to Maintenance Point", show_header_toggle: false, entities: ents },
        ),
      );
    }
  }
  const bottomClean = bottom.filter(Boolean);
  if (bottomClean.length)
    cards.push({ type: "grid", columns: Math.min(3, bottomClean.length), square: false, cards: bottomClean });

  return { title: "Overview", path: "overview", type: "panel", icon: "mdi:robot-mower-outline", cards: [{ type: "vertical-stack", cards: cards.filter(Boolean) }] };
}

function mapView(ctx, m, opts) {
  const cards = [];
  cards.push(headerCard("🗺️", m.suffix, "per-map settings, zones, patrol & editor"));

  const base = ctx.resolveMap(m.id, "map"); // per-map base camera (unique_id key "map")
  if (base)
    cards.push({ type: "picture-entity", entity: base, camera_view: "auto", show_state: false, tap_action: { action: "more-info" } });

  const col1 = [];
  const zoneEditor = mapEntitiesCard(ctx, m.id, "Zone / spot / edge targets", [
    { key: "zone_target", name: "Zone target" },
    { key: "spot_target", name: "Spot target" },
    { key: "edge_target", name: "Edge target" },
  ]);
  if (zoneEditor) col1.push(zoneEditor);
  const counts = mapEntitiesCard(ctx, m.id, "Zone counts", MANIFEST.perMapCounts);
  if (counts) col1.push(counts);
  for (const p of MANIFEST.perMapPatrol) {
    const eid = ctx.resolveMap(m.id, p.key);
    if (eid && KNOWN_SERVICES.has(p.service)) {
      col1.push({
        type: "custom:dreame-multi-select-card",
        title: `${p.title} — ${m.suffix}`,
        entity: eid,
        service: `${DOMAIN}.${p.service}`,
        id_param: p.id_param,
        map_id: m.id,
        action_label: `Start ${p.title.toLowerCase()}`,
      });
    }
  }
  const general = mapEntitiesCard(ctx, m.id, "General Mode", MANIFEST.perMapGeneral);

  const grid = [];
  if (col1.length) grid.push({ type: "vertical-stack", cards: col1 });
  if (general) grid.push(general);
  if (grid.length) cards.push({ type: "grid", columns: grid.length, square: false, cards: grid });

  // Interactive editor card (uses the parent active-map camera).
  const editorCam = ctx.resolve("map");
  if (editorCam) {
    cards.push(headerCard("✏️", "Map Editor", "draw / edit no-go, ignore & mow shapes — writes to the device"));
    cards.push({ type: "custom:dreame-map-editor-card", entity: editorCam });
  }

  return {
    title: m.suffix,
    path: `map_${m.id}`,
    type: "panel",
    icon: "mdi:map-marker-multiple",
    cards: [{ type: "vertical-stack", cards: cards.filter(Boolean) }],
  };
}

function scheduleView(ctx) {
  const cards = [headerCard("📅", "Schedule", "edit slots below — writes to the device")];
  const schedSensor = ctx.resolve("schedule_count");
  const col = [];
  if (schedSensor) col.push({ type: "custom:dreame-a2-schedule-card", sensor: schedSensor });
  const times = entitiesCard(ctx, "Device-wide time windows", MANIFEST.scheduleTimes);
  if (times) col.push(times);
  if (col.length) cards.push(col.length > 1 ? { type: "grid", columns: 2, square: false, cards: col } : col[0]);
  return { title: "Schedule", path: "schedule", type: "panel", icon: "mdi:calendar-clock", cards: [{ type: "vertical-stack", cards }] };
}

// Session-replay metadata summary. Reads sensor.picked_session attributes
// (built by domain/session/replay.py:build_picked_session_summary). Type-aware:
// mow-stat attributes are null for non-mow sessions, so those rows are guarded.
function replayMetaCard(picked) {
  const e = `'${picked}'`;
  const content =
    `### {{ state_attr(${e}, 'label') or 'Session details' }}\n\n` +
    `| | |\n|---|---|\n` +
    `| **Type** | {{ state_attr(${e}, 'session_type') }} |\n` +
    `| **Outcome** | {{ state_attr(${e}, 'result_label') or state_attr(${e}, 'outcome') or '—' }} |\n` +
    `| **Started** | {{ state_attr(${e}, 'started_at') }} |\n` +
    `| **Duration** | {{ state_attr(${e}, 'duration_min') }} min mowing · {{ state_attr(${e}, 'elapsed_min') }} min elapsed |\n` +
    `{% set area = state_attr(${e}, 'area_mowed_m2') %}` +
    `{% if area is not none %}| **Area mowed** | {{ '%.1f'|format(area) }} m²` +
    `{% set cov = state_attr(${e}, 'coverage_pct') %}{% if cov is not none %} ({{ '%.0f'|format(cov) }}%){% endif %} |\n` +
    `{% set rate = state_attr(${e}, 'm2_per_min') %}{% if rate is not none %}| **Rate** | {{ '%.1f'|format(rate) }} m²/min |\n{% endif %}` +
    `{% endif %}` +
    `{% set used = state_attr(${e}, 'charge_used_pct') %}{% if used is not none %}| **Battery used** | {{ used }}% |\n{% endif %}` +
    `{% set rc = state_attr(${e}, 'recharge_count') %}{% if rc %}| **Recharges** | {{ rc }} |\n{% endif %}`;
  return markdown(content, "Session details");
}

function sessionsView(ctx, opts) {
  const cards = [headerCard("📊", "Sessions", "calendar plus per-session breakdown")];

  const left = [];
  const cal = ctx.resolve("session_calendar");
  if (cal) left.push({ type: "calendar", title: "Mowing sessions", entities: [cal] }); // native calendar (OQ-4)
  const workLog = ctx.resolve("work_log");
  const replayEnts = [];
  if (workLog) replayEnts.push({ entity: workLog, name: "Session" });
  const trailW = ctx.resolve("trail_render_width");
  if (trailW) replayEnts.push({ entity: trailW, name: "Trail width (px)" });
  if (replayEnts.length) left.push({ type: "entities", title: "Replay picker", entities: replayEnts });
  const latest = entitiesCard(ctx, "Latest archived", MANIFEST.sessionLatest);
  if (latest) left.push(latest);
  const liveCard = entitiesCard(ctx, "Live session", MANIFEST.sessionLive);
  const sess = ctx.resolve("mowing_session_active");
  if (liveCard && sess) left.push(stateConditional([{ entity: sess, state: "on" }], liveCard));
  // All-time device-wide totals (the mower publishes no per-map totals).
  const totalsCard = entitiesCard(ctx, "Totals (all-time)", MANIFEST.deviceTotals);
  if (totalsCard) left.push(totalsCard);

  const picked = ctx.resolve("picked_session");
  // Right column: the replay/map card keeps the full 2-column (half) width;
  // the metadata card sits BELOW it (stacked), not beside — so the map isn't
  // squeezed into a third column.
  const right = [];
  if (picked) {
    right.push({ type: "custom:dreame-mower-replay-card", entity: picked });
    right.push(replayMetaCard(picked));
  }

  const top = [];
  if (left.filter(Boolean).length) top.push({ type: "vertical-stack", cards: left.filter(Boolean) });
  if (right.length) top.push({ type: "vertical-stack", cards: right });
  if (top.length) cards.push({ type: "horizontal-stack", cards: top });

  // Per-session detail + charts (only when picked_session exists).
  if (picked) {
    cards.push(sessionChartsRow(ctx, picked, opts));
  }

  return { title: "Sessions & History", path: "sessions", type: "panel", icon: "mdi:history", cards: [{ type: "vertical-stack", cards: cards.filter(Boolean) }] };
}

function coverageView(ctx) {
  const cards = [];

  // LiDAR archive.
  const lidarSel = ctx.resolve("lidar_archive");
  const lidarCount = ctx.resolve("lidar_archive_count");
  if (lidarSel || lidarCount) {
    cards.push(headerCard("📡", "LiDAR", "archived 3-D point clouds"));
    const lrow = [];
    const arch = entitiesCard(ctx, "Archive", [
      { key: "lidar_archive_count", name: "Total scans" },
      { key: "lidar_archive", name: "Selected scan" },
    ]);
    if (arch) lrow.push(arch);
    if (lidarSel)
      lrow.push({ type: "custom:dreame-a2-lidar-card", url: `/api/${DOMAIN}/lidar/selected.pcd`, picker_entity: lidarSel });
    if (lrow.length) cards.push({ type: "horizontal-stack", cards: lrow });
  }

  // WiFi coverage.
  const wifiCam = ctx.resolve("wifi_selected");
  const wifiSel = ctx.resolve("wifi_archive");
  if (wifiCam || wifiSel) {
    cards.push(headerCard("📶", "WiFi Coverage", "signal strength measured during mowing"));
    const wrow = [];
    const wctrl = entitiesCard(ctx, "Viewer controls", [
      { key: "wifi_archive", name: "Heatmap" },
      { key: "wifi_heatmap_flip_x", name: "Flip X" },
      { key: "wifi_heatmap_flip_y", name: "Flip Y" },
    ]);
    if (wctrl) wrow.push(wctrl);
    if (wifiCam)
      wrow.push({ type: "picture-entity", entity: wifiCam, name: "WiFi heatmap", camera_view: "auto", show_state: false });
    if (wrow.length) cards.push({ type: "horizontal-stack", cards: wrow });
  }

  if (!cards.length) return null; // self-hide when no archives exist
  return { title: "Coverage & Signal", path: "coverage", type: "panel", icon: "mdi:radar", cards: [{ type: "vertical-stack", cards: cards.filter(Boolean) }] };
}

// Battery/WiFi session charts. Degrade path (OQ-4): plotly only when installed,
// else a native history-graph of the live battery/RSSI sensors + a hint.
function sessionChartsRow(ctx, picked, opts) {
  if (opts && opts.plotly) {
    const mkPlot = (title, samplesAttr, tsIdx, valIdx, yrange) => ({
      type: "custom:plotly-graph",
      // The data comes from the picked-session attributes (below), NOT recorder
      // history, so the x-axis must be pinned to the SESSION's own time span —
      // an archived session is days/weeks in the past and plotly-graph-card's
      // default window is recent-relative, which pushed every point off-screen
      // (the charts read as "blank"). visible_range fits the window to the
      // samples; do NOT set hours_to_show (it overrides visible_range — see the
      // reference_plotly_graph_card_v3 quirk). Falls back to undefined (card's
      // own autorange) when no session is picked.
      title,
      visible_range: `$fn ({ hass }) => { const s = (hass.states['${picked}'] && hass.states['${picked}'].attributes && hass.states['${picked}'].attributes.${samplesAttr}) || []; if (!s.length) return undefined; const t = s.map(a => a[${tsIdx}] * 1000); const lo = Math.min(...t), hi = Math.max(...t); const pad = Math.max((hi - lo) * 0.02, 1000); return [lo - pad, hi + pad]; }`,
      entities: [
        {
          entity: picked,
          name: title,
          show_value: false,
          x: `$fn ({ hass }) => (hass.states['${picked}']?.attributes?.${samplesAttr}||[]).map(a => new Date(a[${tsIdx}]*1000))`,
          y: `$fn ({ hass }) => (hass.states['${picked}']?.attributes?.${samplesAttr}||[]).map(a => a[${valIdx}])`,
        },
      ],
      layout: { height: 280, margin: { l: 50, r: 30, t: 20, b: 50 }, ...(yrange ? { yaxis: { range: yrange } } : {}) },
    });
    return {
      type: "horizontal-stack",
      cards: [mkPlot("Battery % over session", "battery_samples", 0, 1, [0, 100]), mkPlot("WiFi RSSI over session", "wifi_samples", 3, 2, null)],
    };
  }
  // Fallback: live sensors' recorder history (coarse) + a note.
  const bat = ctx.resolve("battery_level");
  const rssi = ctx.resolve("wifi_rssi_dbm");
  const ents = [bat, rssi].filter(Boolean);
  if (ents.length)
    return {
      type: "vertical-stack",
      cards: [
        markdown("_Per-session battery/WiFi charts need the optional `custom:plotly-graph-card` resource. Showing live-sensor history instead._"),
        { type: "history-graph", hours_to_show: 24, entities: ents },
      ],
    };
  return markdown("_Per-session charts need the optional `custom:plotly-graph-card` resource._");
}

function settingsView(ctx) {
  const cards = [headerCard("⚙️", "Settings", "device-wide settings (per-map settings live on each map view)")];
  const grid = [];
  for (const group of MANIFEST.settings) {
    const c = entitiesCard(ctx, group.title, group.keys);
    if (c) grid.push(c);
  }
  if (grid.length) cards.push({ type: "grid", columns: 3, square: false, cards: grid });
  return { title: "Settings", path: "settings", type: "panel", icon: "mdi:cog", cards: [{ type: "vertical-stack", cards }] };
}

function diagnosticsView(ctx, opts) {
  const cards = [headerCard("🩺", "Diagnostics & Tools", "health checks, firmware & manual ops")];
  const grid = [];

  const idRows = [...MANIFEST.diagIdentity];
  const idCard = entitiesCard(ctx, "Device identity", idRows);
  // Firmware / OTA rows fold into the identity column when present.
  const fwCard = entitiesCard(ctx, "Firmware & OTA", MANIFEST.firmware);
  if (idCard) grid.push(idCard);
  if (fwCard) grid.push(fwCard);
  const connCard = entitiesCard(ctx, "Connectivity", MANIFEST.diagConnectivity);
  if (connCard) grid.push(connCard);

  // Experimental / developer diagnostics — self-omit when gated off (their
  // entities are simply absent from the registry). Only surface when present.
  const expCard = entitiesCard(ctx, "Diagnostics (experimental)", MANIFEST.diagExperimental);
  if (expCard) grid.push(expCard);

  if (grid.length) cards.push({ type: "grid", columns: 3, square: false, cards: grid });

  // Tools.
  const toolsGrid = [];
  const manual = entitiesCard(ctx, "Manual refresh", MANIFEST.toolsManual);
  if (manual) toolsGrid.push(manual);
  const recovery = entitiesCard(ctx, "Recovery actions", MANIFEST.toolsRecovery);
  if (recovery) toolsGrid.push(recovery);
  if (toolsGrid.length) {
    cards.push(headerCard("🔧", "Tools", "manual refreshes & recovery actions"));
    cards.push({ type: "grid", columns: Math.min(3, toolsGrid.length), square: false, cards: toolsGrid });
  }

  return { title: "Diagnostics & Tools", path: "diagnostics", type: "panel", icon: "mdi:wrench", cards: [{ type: "vertical-stack", cards }] };
}

function photosView(ctx) {
  const cards = [headerCard("🖼️", "Photos", "archived obstacle / patrol / person photos + videos")];
  const glance = glanceCard(ctx, MANIFEST.photoGlance, 5);
  if (glance) cards.push(glance);
  const camRow = [];
  for (const c of MANIFEST.photoCameras) {
    const eid = ctx.resolve(c.key);
    if (eid) camRow.push({ type: "picture-entity", entity: eid, name: c.name, show_state: false, camera_view: "auto" });
  }
  if (camRow.length) cards.push({ type: "horizontal-stack", cards: camRow });
  const gallery = ctx.resolve("photo_gallery");
  if (gallery) cards.push({ type: "custom:dreame-a2-photo-gallery-card", entity: gallery });
  return { title: "Photos", path: "photos", type: "panel", icon: "mdi:image-multiple", cards: [{ type: "vertical-stack", cards }] };
}

function messagesView(ctx) {
  const cards = [headerCard("📨", "Messages", "device, service & sharing messages")];
  let any = false;
  for (const m of MANIFEST.messages) {
    const eid = ctx.resolve(m.key);
    if (!eid) continue;
    any = true;
    cards.push(
      markdown(
        `{% set items = state_attr('${eid}','items') or [] %}\n**{{ items | count }} messages**\n{% for msg in items %}\n- {{ '🔵' if msg.unread else '⚪' }} **{{ msg.title }}**{% if msg.date %} <span style="font-size:0.8em;color:var(--secondary-text-color)">{{ (as_timestamp(msg.date, 0) | timestamp_custom('%Y-%m-%d %H:%M', true)) if as_timestamp(msg.date, 0) else msg.date }}</span>{% endif %}{% if msg.body %}<br>{{ msg.body }}{% endif %}\n{% endfor %}\n{% if not items %}_No messages_{% endif %}`,
        m.title,
      ),
    );
  }
  if (!any) return null;
  return { title: "Messages", path: "messages", type: "panel", icon: "mdi:message-text", cards: [{ type: "vertical-stack", cards }] };
}

// ---------------------------------------------------------------------------
// The generator — pure, DOM-free, node-testable.
// ---------------------------------------------------------------------------

export async function generateDashboard(config, hass) {
  const opts = {
    plotly: config && typeof config.plotly === "boolean" ? config.plotly : plotlyInstalled(),
  };
  const ctx = await buildContext(hass);

  const views = [];
  views.push(overviewView(ctx));
  for (const m of ctx.maps) views.push(mapView(ctx, m, opts));
  views.push(scheduleView(ctx));
  views.push(sessionsView(ctx, opts));
  const cov = coverageView(ctx);
  if (cov) views.push(cov);
  views.push(settingsView(ctx));
  views.push(diagnosticsView(ctx, opts));
  views.push(photosView(ctx));
  const msgs = messagesView(ctx);
  if (msgs) views.push(msgs);

  return { title: "Dreame A2 Mower", views: views.filter(Boolean) };
}

// Registry probe: is the optional plotly-graph card installed? (OQ-4 degrade.)
function plotlyInstalled() {
  try {
    const w = typeof window !== "undefined" ? window : globalThis;
    const cards = w && w.customCards;
    if (Array.isArray(cards))
      return cards.some((c) => String((c && c.type) || "").replace(/^custom:/, "") === "plotly-graph");
  } catch (_e) {
    /* ignore */
  }
  return false;
}

export { plotlyInstalled };

// ---------------------------------------------------------------------------
// Browser-only registration. Kept behind a guard so the node harness can import
// the pure generator without a DOM. This block (a) registers the dashboard
// strategy element and (b) dynamically imports every bundled card so ONE
// Lovelace resource entry replaces the previous seven.
// ---------------------------------------------------------------------------

if (typeof customElements !== "undefined" && typeof HTMLElement !== "undefined") {
  const STRATEGY_TAG = `ll-strategy-dashboard-${STRATEGY_TYPE}`;
  if (!customElements.get(STRATEGY_TAG)) {
    class DreameA2DashboardStrategy extends HTMLElement {
      static async generate(config, hass) {
        return generateDashboard(config || {}, hass);
      }
    }
    customElements.define(STRATEGY_TAG, DreameA2DashboardStrategy);
    // eslint-disable-next-line no-console
    console.info(
      `%c ${STRATEGY_TAG} v${CARD_VERSION} `,
      "color:#fff;background:#2b8a3e;border-radius:3px;padding:1px 4px",
    );
    // Pull in every bundled card (self-registers via defineCard). One resource
    // now carries the whole product.
    const CARDS = [
      "./dreame-mower-map-card.js",
      "./dreame-mower-replay-card.js",
      "./dreame-map-editor-card.js",
      "./dreame-a2-lidar-card.js",
      "./dreame-a2-schedule-card.js",
      "./dreame-a2-photo-gallery-card.js",
      "./dreame-multi-select-card.js",
    ];
    for (const url of CARDS) import(url).catch(() => {});
  }
}
