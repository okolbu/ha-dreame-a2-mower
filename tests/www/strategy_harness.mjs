// Node harness for the registered dashboard strategy (P5.3) — THE strategy's
// proof (no browser). Imports the pure `generateDashboard` from
// `dreame-a2-strategy.js`, runs it against synthesized `hass` fixtures, and
// asserts the load-bearing guarantees:
//
//   (a) valid Lovelace config — `views[]`, each view `cards[]`.
//   (b) NO dead refs — every structural entity_id in the output exists in the
//       fixture registry/states (R-14). Proven even when the entity_id carries
//       the recurring `floor_0_outside_` rename prefix (unique_id keying).
//   (c) NO `attribute:` conditionals anywhere in the output (R-13).
//   (d) per-map views scale with the number of registered map devices — tested
//       with a 1-map AND a 3-map fixture (R-48).
//   (e) plotly degrade — absent → native fallback, present → plotly card (OQ-4).
//   (f) experimental/dev entities self-omit when absent from the registry (R-55).
//   (g) no phantom service refs (download_diagnostics / set_zone_setting /
//       clear_zone_setting) and every emitted service is in the known allowlist.
//
// Run: `node tests/www/strategy_harness.mjs` → prints OK / exits 0 on success.

import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STRAT = path.resolve(HERE, "../../custom_components/dreame_a2_mower/www/dreame-a2-strategy.js");
const mod = await import(STRAT);
const { generateDashboard, MANIFEST, DOMAIN } = mod;

const STABLE = "G2408TEST";

function assert(cond, msg) {
  if (!cond) throw new Error("ASSERT FAILED: " + msg);
}

// ---- collect the key set the strategy might reference ----------------------

function parentKeys() {
  const keys = new Set();
  const push = (arr) => (arr || []).forEach((r) => r && r.key && keys.add(r.key));
  push(MANIFEST.overviewState);
  push(MANIFEST.scheduleTimes);
  MANIFEST.settings.forEach((g) => push(g.keys));
  push(MANIFEST.diagIdentity);
  push(MANIFEST.diagConnectivity);
  push(MANIFEST.firmware);
  push(MANIFEST.toolsManual);
  push(MANIFEST.toolsRecovery);
  push(MANIFEST.sessionLatest);
  push(MANIFEST.sessionLive);
  push(MANIFEST.deviceTotals);
  push(MANIFEST.photoGlance);
  push(MANIFEST.photoCameras);
  push(MANIFEST.messages);
  // bespoke parent keys referenced by the view builders directly.
  [
    "map", "work_log", "picked_session", "schedule_count", "sessions",
    "lidar_archive", "lidar_archive_count", "wifi_selected", "wifi_archive",
    "wifi_heatmap_flip_x", "wifi_heatmap_flip_y", "photo_gallery",
    "active_map", "action_mode", "emergency_stop", "current_activity",
    "charging_status", "mower_in_dock", "mowing_session_active",
    "positioning_health", "mqtt_connectivity",
    "rain_protection_active", "active_selection", "area_mowed_m2",
    "trail_render_width", "battery_level", "mower_location", "lifecycle", "notification",
    "gps", "start_mowing", "stop_mowing", "pause_mowing", "resume_mowing",
    "recharge", "cancel_dock_return", "find_bot", "update_station_location",
    "refresh_cloud_state", "refresh_wifi_heatmaps", "finalize_session",
    "wifi_rssi_dbm", "integration_version", "api_endpoint",
    "device_messages", "service_messages_unread", "shared_messages",
    "session_calendar",
  ].forEach((k) => keys.add(k));
  return keys;
}

function perMapKeys() {
  const keys = new Set(["map", "maintenance_point", "head_to_point"]);
  (MANIFEST.perMapGeneral || []).forEach((r) => keys.add(r.key));
  (MANIFEST.perMapCounts || []).forEach((r) => keys.add(r.key));
  Object.values(MANIFEST.perMapTargets).forEach((r) => keys.add(r.key));
  (MANIFEST.perMapPatrol || []).forEach((r) => keys.add(r.key));
  return keys;
}

// Some entity ids deliberately carry the recurring rename prefix, to prove the
// generator resolves off unique_id, not the (unstable) entity_id (T6-1/R-14).
const PREFIXED = new Set(["obstacle_photo", "photos_obstacle"]);

function slug(key, mapId) {
  const base = mapId == null ? `dreame_a2_mower_${key}` : `dreame_a2_mower_map_${mapId + 1}_${key}`;
  return PREFIXED.has(key) ? `floor_0_outside_${base}` : base;
}

function makeHass(nMaps, opts = {}) {
  const { experimental = false, disabledKeys = [], plotly = false, extraParentIdents = [] } = opts;
  const entReg = [];
  const states = {};
  const add = (key, uid, mapId, extra = {}) => {
    const eid = `x.${slug(key, mapId)}`;
    entReg.push({ entity_id: eid, unique_id: uid, platform: DOMAIN, disabled_by: null, hidden_by: null, ...extra });
    if (!extra.disabled_by) states[eid] = { entity_id: eid, state: "0", attributes: {} };
    return eid;
  };

  const disabledSet = new Set(disabledKeys);
  for (const k of parentKeys()) if (!disabledSet.has(k)) add(k, `${STABLE}_${k}`, null);
  for (let m = 0; m < nMaps; m++) for (const k of perMapKeys()) add(k, `${STABLE}_map_${m}_${k}`, m);

  // Experimental / developer entities — only present when experimental on.
  if (experimental) for (const r of MANIFEST.diagExperimental) add(r.key, `${STABLE}_${r.key}`, null);

  // Disabled-by-default entities (e.g. ota_state) — present in registry with a
  // disabled_by, NO state. Must never be referenced (T6-2).
  for (const k of disabledKeys) add(k, `${STABLE}_${k}`, null, { disabled_by: "integration" });

  // A foreign (other-integration) entity that must be ignored.
  entReg.push({ entity_id: "sensor.someone_else", unique_id: "OTHER_x", platform: "other", disabled_by: null });
  states["sensor.someone_else"] = { state: "1", attributes: {} };

  // The live parent device can carry MORE THAN ONE domain identifier (e.g. the
  // config-entry ULID listed BEFORE the hardware SN). extraParentIdents injects
  // those ahead of STABLE so the harness exercises the real registry shape.
  const parentIdents = [...extraParentIdents.map((x) => [DOMAIN, x]), [DOMAIN, STABLE]];
  const devReg = [{ id: "devP", identifiers: parentIdents, name: "Dreame A2 Mower", name_by_user: null }];
  for (let m = 0; m < nMaps; m++)
    devReg.push({ id: `devM${m}`, identifiers: [[DOMAIN, `${STABLE}_map_${m}`]], name: `Dreame A2 Mower Map ${m + 1}`, name_by_user: null });

  if (plotly) globalThis.window = { customCards: [{ type: "custom:plotly-graph" }] };
  else delete globalThis.window;

  return {
    states,
    async callWS(msg) {
      if (msg.type === "config/entity_registry/list") return entReg;
      if (msg.type === "config/device_registry/list") return devReg;
      throw new Error("unexpected WS " + msg.type);
    },
  };
}

// ---- deep walkers ----------------------------------------------------------

function walk(node, fn, keyName) {
  fn(node, keyName);
  if (Array.isArray(node)) node.forEach((n) => walk(n, fn));
  else if (node && typeof node === "object") for (const [k, v] of Object.entries(node)) walk(v, fn, k);
}

function collectEntityRefs(config) {
  const refs = [];
  walk(config, (node, key) => {
    if (typeof node === "string" && (key === "entity" || key === "picker_entity" || key === "sensor")) refs.push(node);
    if (key === "entities" && Array.isArray(node))
      node.forEach((it) => {
        if (typeof it === "string") refs.push(it);
        else if (it && typeof it === "object" && typeof it.entity === "string") refs.push(it.entity);
      });
    if (key === "entity_id") {
      if (typeof node === "string") refs.push(node);
      else if (Array.isArray(node)) node.forEach((s) => typeof s === "string" && refs.push(s));
    }
  });
  return refs;
}

function collectKeys(config) {
  const found = new Set();
  walk(config, (_node, key) => key && found.add(key));
  return found;
}

function collectServices(config) {
  const svc = [];
  walk(config, (node, key) => {
    if (key === "service" && typeof node === "string") svc.push(node);
  });
  return svc;
}

function validateNoDeadRefs(config, hass, label) {
  const refs = collectEntityRefs(config);
  assert(refs.length > 0, `${label}: expected some entity refs`);
  for (const eid of refs) assert(Object.prototype.hasOwnProperty.call(hass.states, eid), `${label}: dead ref ${eid}`);
}

function validateShape(config, label) {
  assert(config && Array.isArray(config.views) && config.views.length, `${label}: no views`);
  assert(typeof config.title === "string", `${label}: no title`);
  for (const v of config.views) {
    assert(typeof v.title === "string", `${label}: view without title`);
    assert(Array.isArray(v.cards) && v.cards.length, `${label}: view '${v.title}' has no cards`);
  }
}

function jsonHas(config, substr) {
  return JSON.stringify(config).includes(substr);
}

// ---- the assertions --------------------------------------------------------

async function run() {
  // (d) 1-map fixture.
  const hass1 = makeHass(1, { disabledKeys: ["ota_state", "ota_progress"] });
  const cfg1 = await generateDashboard({}, hass1);
  validateShape(cfg1, "1-map");
  validateNoDeadRefs(cfg1, hass1, "1-map");

  // (a) valid config already checked. (b) no dead refs checked.
  // (c) no `attribute:` conditionals anywhere (R-13).
  assert(!collectKeys(cfg1).has("attribute"), "1-map: output contains an `attribute:` conditional (R-13)");

  // (d) exactly one per-map view for 1 map.
  const mapViews1 = cfg1.views.filter((v) => String(v.path || "").startsWith("map_"));
  assert(mapViews1.length === 1, `1-map: expected 1 map view, got ${mapViews1.length}`);

  // (g) no phantom services / entities anywhere.
  for (const bad of ["download_diagnostics", "set_zone_setting", "clear_zone_setting", "custom_mode_overrides"])
    assert(!jsonHas(cfg1, bad), `1-map: phantom ref '${bad}' present`);
  // lock_robot / generate_3d_map deliberately excluded (D9).
  for (const bad of ["lock_robot", "generate_3d_map"]) assert(!jsonHas(cfg1, bad), `1-map: D9 op '${bad}' surfaced`);
  // every emitted service is real.
  for (const svc of collectServices(cfg1))
    assert(svc.startsWith(`${DOMAIN}.start_point_patrol`) || svc.startsWith(`${DOMAIN}.start_edge_patrol`),
      `1-map: unexpected service ${svc}`);

  // (b') disabled-by-default entities never referenced (T6-2).
  const refs1 = new Set(collectEntityRefs(cfg1));
  for (const eid of refs1) assert(!/ota_state|ota_progress/.test(eid), `1-map: referenced disabled entity ${eid}`);

  // rename-prefixed entity still referenced correctly (T6-1): the photos glance
  // must carry the floor_0_outside_ obstacle-photos sensor, resolved by key.
  assert(jsonHas(cfg1, "floor_0_outside_dreame_a2_mower_photos_obstacle"),
    "1-map: rename-prefixed entity not resolved via unique_id");

  // (f) experimental omitted when off.
  assert(!jsonHas(cfg1, "Diagnostics (experimental)"), "1-map: experimental card present when gated off");
  assert(!jsonHas(cfg1, "_mpos"), "1-map: mpos surfaced when gated off");

  // (e) plotly degrade — off → no plotly, native fallback present.
  assert(!jsonHas(cfg1, '"custom:plotly-graph"'), "1-map: plotly card present without the resource");
  assert(jsonHas(cfg1, "history-graph") || jsonHas(cfg1, "plotly-graph-card"),
    "1-map: no native chart fallback / hint");
  // calendar uses the native card (OQ-4), not atomic-calendar-revive.
  assert(!jsonHas(cfg1, "atomic-calendar"), "1-map: atomic-calendar-revive leaked into output");
  assert(jsonHas(cfg1, '"type":"calendar"'), "1-map: native calendar card missing");

  // --- Part 1: LiDAR + WiFi live on their own Coverage tab, not Sessions. ---
  const covView1 = cfg1.views.find((v) => v.path === "coverage");
  assert(covView1, "coverage: no 'Coverage & Signal' view");
  assert(covView1.title === "Coverage & Signal", "coverage: wrong view title");
  assert(jsonHas(covView1, "custom:dreame-a2-lidar-card"), "coverage: LiDAR card missing from Coverage view");
  assert(jsonHas(covView1, "WiFi Coverage"), "coverage: WiFi block missing from Coverage view");
  const sessView1 = cfg1.views.find((v) => v.path === "sessions");
  assert(sessView1, "sessions: view missing");
  assert(!jsonHas(sessView1, "custom:dreame-a2-lidar-card"), "sessions: LiDAR card still present after move");
  assert(!jsonHas(sessView1, "WiFi Coverage"), "sessions: WiFi block still present after move");

  // --- Part 2: session-replay metadata card appears beside the replay card. ---
  assert(jsonHas(sessView1, "area_mowed_m2"), "sessions: replay metadata card missing (no area_mowed_m2 template)");
  assert(jsonHas(sessView1, "Session details"), "sessions: metadata card title missing");
  // Absent when no session is picked.
  const hassNoPick = makeHass(1, { disabledKeys: ["ota_state", "ota_progress", "picked_session"] });
  const cfgNoPick = await generateDashboard({}, hassNoPick);
  const sessNoPick = cfgNoPick.views.find((v) => v.path === "sessions");
  assert(!jsonHas(sessNoPick, "area_mowed_m2"), "sessions: metadata card present without a picked session");

  // (d) 3-map fixture — per-map views scale.
  const hass3 = makeHass(3);
  const cfg3 = await generateDashboard({}, hass3);
  validateShape(cfg3, "3-map");
  validateNoDeadRefs(cfg3, hass3, "3-map");
  assert(!collectKeys(cfg3).has("attribute"), "3-map: `attribute:` conditional present (R-13)");
  const mapViews3 = cfg3.views.filter((v) => String(v.path || "").startsWith("map_"));
  assert(mapViews3.length === 3, `3-map: expected 3 map views, got ${mapViews3.length}`);
  // each map view references its own map_N entities.
  for (let m = 0; m < 3; m++) {
    const v = cfg3.views.find((vv) => vv.path === `map_${m}`);
    assert(v, `3-map: missing map_${m} view`);
    assert(jsonHas(v, `dreame_a2_mower_map_${m + 1}_`), `3-map: map view ${m} lacks its own entities`);
  }

  // (e) plotly present → plotly cards emitted, no history-graph fallback.
  const hassP = makeHass(2, { plotly: true, experimental: true });
  const cfgP = await generateDashboard({}, hassP);
  validateShape(cfgP, "plotly");
  validateNoDeadRefs(cfgP, hassP, "plotly");
  assert(jsonHas(cfgP, '"custom:plotly-graph"'), "plotly: plotly card missing when resource present");

  // (f) experimental present → the experimental diagnostics card appears.
  assert(jsonHas(cfgP, "Diagnostics (experimental)"), "plotly/exp: experimental card missing when entities present");

  // explicit config.plotly override wins over the global probe.
  const cfgForceOff = await generateDashboard({ plotly: false }, hassP);
  assert(!jsonHas(cfgForceOff, '"custom:plotly-graph"'), "config.plotly=false did not suppress plotly");

  // (h) multi-identifier parent device (LIVE-caught, P5.5): the parent carries a
  // config-entry ULID BEFORE the hardware SN, but every unique_id is SN-prefixed.
  // The stable prefix must be derived from evidence (the id that prefixes the
  // uids), not the first identifier — otherwise resolve() returns null for every
  // key and every view collapses to just its header markdown.
  const hassMI = makeHass(2, { extraParentIdents: ["01KQENTRYULID0000000000000"] });
  const cfgMI = await generateDashboard({}, hassMI);
  validateShape(cfgMI, "multi-ident");
  validateNoDeadRefs(cfgMI, hassMI, "multi-ident");
  // Non-degenerate: the Overview view must carry real control/state cards, not
  // only the section-header markdown. Assert a known parent entity resolved.
  assert(jsonHas(cfgMI, "dreame_a2_mower_battery_level") || jsonHas(cfgMI, "x.dreame_a2_mower_battery_level"),
    "multi-ident: parent entities did not resolve (stable prefix mis-derived from the ULID identifier)");
  const overviewMI = cfgMI.views.find((v) => v.path === "overview");
  assert(overviewMI, "multi-ident: no overview view");
  assert(collectEntityRefs(overviewMI).length > 0, "multi-ident: overview collapsed to header-only (no entity refs)");
  // The per-map views must also resolve their map entities.
  assert(jsonHas(cfgMI, "dreame_a2_mower_map_1_"), "multi-ident: map view lacks its own entities");

  // 0-map fixture — still a valid dashboard, no map views, no crash.
  const hass0 = makeHass(0);
  const cfg0 = await generateDashboard({}, hass0);
  validateShape(cfg0, "0-map");
  validateNoDeadRefs(cfg0, hass0, "0-map");
  assert(cfg0.views.filter((v) => String(v.path || "").startsWith("map_")).length === 0, "0-map: unexpected map view");

  console.log(`OK — strategy harness: ${cfg1.views.length} views (1-map), ${cfg3.views.length} (3-map), all refs live`);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
