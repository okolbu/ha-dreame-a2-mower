# Phase C — New read sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the mower's absolute GPS (via `location/getRecords` → device_tracker), 4G-SIM status (REMOTE → sensors), and the account message-list unread count (message-record/list v1 → sensor).

**Architecture:** Three new read-only cloud fetchers + their refreshers feed new `MowerState` fields read by a device_tracker (already exists) and new diagnostic sensors. The non-functional LOCN→`position_lat/lon` write is retired; getRecords becomes the device_tracker source. All read-only — no control_mode/writability.

**Tech Stack:** Python, vanilla pytest venv (`/data/claude/homeassistant/.venv-vanilla/bin/python`), inventory validators.

**Spec:** `docs/superpowers/specs/2026-06-10-phase-c-new-read-sources-design.md`

**Captured response shapes (2026-06-09):**
- getRecords: `{"success":true,"locationRecords":{"records":[{"did","card4G","gpsLat":"[REDACTED-LAT]","gpsLong":"[REDACTED-LON]","updateTime":"2026-06-09 16:04:03","reversed0..3":null}, …]}}` — gpsLat/gpsLong are decimal-degree STRINGS; `records` is history (take newest by `updateTime`).
- REMOTE (routed `m:g t:"REMOTE"` → `d`): `{"activeTime":"2025-11-20 15:45:29","cardId":"<ICCID>","expiredTime":"2028-11-20 15:45:29","leftDays":895}`.
- message-record/list v1: `{"code","success","data":{"serviceMsg":{"unread","msgRecord","categoryUnread"},"systemMsg":{"unread","msgRecord",…},"shareMsg":{"shareMessage","unread"},"deviceMsgs":[…]},"msg"}`.

**Already done (NOT in scope):** NET wifi (ssid/ip/rssi sensors + `_refresh_net`), MAP.* decoded cache (`fetch_map`), device fault/event messages (`fetch_device_messages` v2 + `event.py`), and the **`wifi_ip` sensor (already exists** in `sensor_device.py`).

**Patterns to mirror:**
- Routed GET (REMOTE): `from ..protocol.cfg_action import probe_get` → `probe_get(self.action, "REMOTE")` returns the `d` dict (see `fetch_net`).
- HTTP GET/POST (getRecords, message-record): mirror `cloud_client/_fetchers.py:fetch_device_messages` — `self._session`, `self.get_api_url()`, headers built from `self._ensure_strings()`/`strings`, `resp.json()`.
- Refresher registration: `coordinator/_core.py` ~L505-555 — each refresher has a `_periodic_X` wrapper + `async_track_time_interval(..., timedelta(...))` + an initial `await self._refresh_X()`.
- Sensor descriptor: `sensor_device.py` `DreameA2SensorEntityDescription(key=, name=, icon=, entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda s: s.<field>)`.

**Conventions:** Python = `/data/claude/homeassistant/.venv-vanilla/bin/python`. Stage by explicit path (never `git add -A`). Co-Authored-By trailer for Claude Opus 4.8. **Test fixtures use FAKE GPS lat/long + a FAKE ICCID** — the captured values are the user's real home/SIM. Branch is `phase-c-new-read-sources`.

---

### Task 1: Cloud fetchers — fetch_gps, fetch_remote, fetch_message_record

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py`
- Test: `tests/integration/test_phase_c_fetchers.py` (create)

- [ ] **Step 1: Read** `fetch_net` (routed-get pattern, ~L186) and `fetch_device_messages` (HTTP pattern, ~L539) to copy their exact session/header/error-handling style.

- [ ] **Step 2: Write the failing test** (`tests/integration/test_phase_c_fetchers.py`) — uses FAKE coords/ICCID and stubs the transport:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from custom_components.dreame_a2_mower.cloud_client import _fetchers


def _client_with_session(json_body):
    """Build a bare _FetchersMixin instance with a stubbed _session + get_api_url."""
    c = _fetchers._FetchersMixin()
    resp = SimpleNamespace(status_code=200, json=lambda: json_body, text="")
    c._session = SimpleNamespace(get=MagicMock(return_value=resp), post=MagicMock(return_value=resp))
    c.get_api_url = lambda: "https://eu.iot.dreame.tech"
    c._ensure_strings = lambda: None
    c.strings = ["" for _ in range(60)]
    c.did = 123
    return c


def test_fetch_gps_takes_newest_record():
    body = {"success": True, "locationRecords": {"records": [
        {"gpsLat": "1.0", "gpsLong": "2.0", "updateTime": "2026-06-09 08:00:00", "card4G": "FAKEICCID"},
        {"gpsLat": "3.5", "gpsLong": "4.5", "updateTime": "2026-06-09 16:00:00", "card4G": "FAKEICCID"},
    ]}}
    c = _client_with_session(body)
    out = c.fetch_gps()
    assert out == {"lat": 3.5, "lon": 4.5, "update_time": "2026-06-09 16:00:00", "card4g": "FAKEICCID"}


def test_fetch_gps_empty_records_returns_none():
    c = _client_with_session({"success": True, "locationRecords": {"records": []}})
    assert c.fetch_gps() is None


def test_fetch_message_record_unread():
    body = {"code": 0, "success": True, "data": {
        "serviceMsg": {"unread": 2, "msgRecord": [{"multiLangDisplay": "{\"en\":{\"name\":\"Sale\",\"link\":\"http://x\"}}"}]},
        "systemMsg": {"unread": 1, "msgRecord": []},
    }}
    c = _client_with_session(body)
    out = c.fetch_message_record()
    assert out["service_unread"] == 2
    assert out["system_unread"] == 1
    assert "Sale" in (out["latest"] or "")
```
(REMOTE is tested via a routed-action stub — add this in the same file:)
```python
def test_fetch_remote_parses_sim():
    c = _fetchers._FetchersMixin()
    # probe_get calls self.action(...); stub the routed-get to return the d dict
    c.action = MagicMock(return_value={"out": [{"m": "g", "t": "REMOTE",
        "d": {"activeTime": "2025-11-20 15:45:29", "cardId": "FAKEICCID",
              "expiredTime": "2028-11-20 15:45:29", "leftDays": 895}}]})
    out = c.fetch_remote()
    assert out == {"active_time": "2025-11-20 15:45:29", "card_id": "FAKEICCID",
                   "expired_time": "2028-11-20 15:45:29", "left_days": 895}
```

- [ ] **Step 3: Run, expect fail**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_phase_c_fetchers.py -q`
Expected: FAIL — methods missing.

- [ ] **Step 4: Implement the three fetchers** in `_fetchers.py` (`_FetchersMixin`). Mirror `fetch_device_messages` for the HTTP ones (real header/auth setup from the strings/session — the test stubs them, but production must build the same headers `fetch_device_messages` uses; copy that header block). Reference shapes:

```python
    def fetch_gps(self) -> dict | None:
        """Absolute GPS via dreame-mower-service-app/location/getRecords.
        Returns the NEWEST record {lat, lon, update_time, card4g} or None.
        gpsLat/gpsLong are decimal-degree strings. ATA[2]-gated: empty when
        Real-Time Location is off."""
        try:
            url = f"{self.get_api_url()}/dreame-mower-service-app/location/getRecords"
            # build headers exactly as fetch_device_messages does (auth/dreame-auth/etc.)
            resp = self._session.post(url, headers=<same headers as fetch_device_messages>,
                                      json={"did": str(self.did)}, timeout=10)
            if resp.status_code != 200:
                return None
            body = resp.json()
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_gps: %s", ex)
            return None
        recs = (((body or {}).get("locationRecords") or {}).get("records")) or []
        if not isinstance(recs, list) or not recs:
            return None
        newest = max(recs, key=lambda r: r.get("updateTime") or "")
        try:
            return {"lat": float(newest["gpsLat"]), "lon": float(newest["gpsLong"]),
                    "update_time": newest.get("updateTime"), "card4g": newest.get("card4G")}
        except (KeyError, TypeError, ValueError):
            return None

    def fetch_remote(self) -> dict | None:
        """4G SIM status via routed m:g t:REMOTE → {active_time, card_id, expired_time, left_days}."""
        from ..protocol.cfg_action import CfgActionError, probe_get  # type: ignore[import]
        try:
            payload = probe_get(self.action, "REMOTE")
        except CfgActionError as ex:
            _LOGGER.debug("fetch_remote: %s", ex); return None
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_remote: %s", ex); return None
        d = payload.get("d") if isinstance(payload, dict) and isinstance(payload.get("d"), dict) else (payload if isinstance(payload, dict) else None)
        if not isinstance(d, dict) or "cardId" not in d:
            return None
        return {"active_time": d.get("activeTime"), "card_id": d.get("cardId"),
                "expired_time": d.get("expiredTime"), "left_days": d.get("leftDays")}

    def fetch_message_record(self) -> dict | None:
        """System+Service+Activity messages via /dreame-message-push/v1/message-record/list?version=v1.
        Returns {service_unread, system_unread, latest} or None."""
        try:
            url = f"{self.get_api_url()}/dreame-message-push/v1/message-record/list"
            resp = self._session.get(url, headers=<same headers as fetch_device_messages>,
                                     params={"version": "v1"}, timeout=10)
            if resp.status_code != 200:
                return None
            body = resp.json()
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_message_record: %s", ex); return None
        data = (body or {}).get("data") or {}
        svc = data.get("serviceMsg") or {}
        sysm = data.get("systemMsg") or {}
        latest = None
        recs = svc.get("msgRecord") or []
        if recs and isinstance(recs[0], dict):
            import json as _json
            try:
                disp = _json.loads(recs[0].get("multiLangDisplay") or "{}")
                en = disp.get("en") or next(iter(disp.values()), {})
                latest = (en or {}).get("name")
            except (ValueError, TypeError):
                latest = None
        return {"service_unread": svc.get("unread"), "system_unread": sysm.get("unread"), "latest": latest}
```
Replace `<same headers as fetch_device_messages>` with the actual header dict that function builds (copy it verbatim). Ensure `_LOGGER` is imported (it is, from `._helpers`).

- [ ] **Step 5: Run, expect pass**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_phase_c_fetchers.py -q`
Expected: PASS. If the test's bare-`_FetchersMixin()` construction fails (mixin needs attrs), set them in the test helper (the production methods only use `self._session`, `self.get_api_url`, `self.did`, `self.action`, headers).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client/_fetchers.py tests/integration/test_phase_c_fetchers.py
git commit -m "feat(c): fetch_gps / fetch_remote / fetch_message_record cloud fetchers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: MowerState fields + refreshers (retire LOCN position write)

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py`
- Modify: `custom_components/dreame_a2_mower/coordinator/_refreshers.py`
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py`
- Test: `tests/integration/test_phase_c_refreshers.py` (create)

- [ ] **Step 1: Add MowerState fields** (`mower/state.py`, near `position_lat`):
```python
    gps_update_time: str | None = None
    gps_card4g: str | None = None
    sim_active_time: str | None = None
    sim_card_id: str | None = None
    sim_expired_time: str | None = None
    sim_left_days: int | None = None
    service_messages_unread: int | None = None
    system_messages_unread: int | None = None
    latest_service_message: str | None = None
```

- [ ] **Step 2: Write the failing test** (`tests/integration/test_phase_c_refreshers.py`):
```python
import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.dreame_a2_mower.coordinator._refreshers import _RefreshersMixin
from custom_components.dreame_a2_mower.mower.state import MowerState


def _coord(gps=None, remote=None, msg=None):
    c = _RefreshersMixin()
    c._cloud = SimpleNamespace(
        fetch_gps=MagicMock(return_value=gps),
        fetch_remote=MagicMock(return_value=remote),
        fetch_message_record=MagicMock(return_value=msg),
    )
    c.data = MowerState()
    async def _exec(fn, *a): return fn(*a)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    c.async_set_updated_data = lambda s: setattr(c, "data", s)
    return c


@pytest.mark.asyncio
async def test_refresh_gps_sets_position():
    c = _coord(gps={"lat": 3.5, "lon": 4.5, "update_time": "t", "card4g": "FAKE"})
    await c._refresh_gps()
    assert c.data.position_lat == 3.5 and c.data.position_lon == 4.5
    assert c.data.gps_update_time == "t" and c.data.gps_card4g == "FAKE"


@pytest.mark.asyncio
async def test_refresh_gps_none_clears():
    c = _coord(gps=None)
    c.data = dataclasses.replace(c.data, position_lat=9.9, position_lon=9.9)
    await c._refresh_gps()
    assert c.data.position_lat is None and c.data.position_lon is None


@pytest.mark.asyncio
async def test_refresh_remote_sets_sim():
    c = _coord(remote={"active_time": "a", "card_id": "FAKE", "expired_time": "e", "left_days": 895})
    await c._refresh_remote()
    assert c.data.sim_left_days == 895 and c.data.sim_card_id == "FAKE"


@pytest.mark.asyncio
async def test_refresh_messages_sets_unread():
    c = _coord(msg={"service_unread": 2, "system_unread": 1, "latest": "Sale"})
    await c._refresh_messages()
    assert c.data.service_messages_unread == 2 and c.data.system_messages_unread == 1
    assert c.data.latest_service_message == "Sale"
```

- [ ] **Step 3: Implement the three refreshers** in `coordinator/_refreshers.py` (mirror `_refresh_net`'s structure — guard `_cloud`, executor-job the fetch, `dataclasses.replace` + `async_set_updated_data` on change):
```python
    async def _refresh_gps(self) -> None:
        """Absolute GPS via getRecords → position_lat/lon (+ attrs). None clears."""
        if not hasattr(self, "_cloud"):
            return
        gps = await self.hass.async_add_executor_job(self._cloud.fetch_gps)
        if gps is None:
            if self.data.position_lat is not None or self.data.position_lon is not None:
                self.async_set_updated_data(dataclasses.replace(
                    self.data, position_lat=None, position_lon=None))
            return
        new = dataclasses.replace(
            self.data, position_lat=gps["lat"], position_lon=gps["lon"],
            gps_update_time=gps.get("update_time"), gps_card4g=gps.get("card4g"))
        if new != self.data:
            self.async_set_updated_data(new)

    async def _refresh_remote(self) -> None:
        """4G SIM status via REMOTE."""
        if not hasattr(self, "_cloud"):
            return
        r = await self.hass.async_add_executor_job(self._cloud.fetch_remote)
        if not r:
            return
        new = dataclasses.replace(
            self.data, sim_active_time=r.get("active_time"), sim_card_id=r.get("card_id"),
            sim_expired_time=r.get("expired_time"), sim_left_days=r.get("left_days"))
        if new != self.data:
            self.async_set_updated_data(new)

    async def _refresh_messages(self) -> None:
        """Account message-list unread counts via message-record/list v1."""
        if not hasattr(self, "_cloud"):
            return
        m = await self.hass.async_add_executor_job(self._cloud.fetch_message_record)
        if not m:
            return
        new = dataclasses.replace(
            self.data, service_messages_unread=m.get("service_unread"),
            system_messages_unread=m.get("system_unread"),
            latest_service_message=m.get("latest"))
        if new != self.data:
            self.async_set_updated_data(new)
```
Confirm `dataclasses` is imported in `_refreshers.py` (it is — `_refresh_locn` uses it).

- [ ] **Step 4: Retire `_refresh_locn` + register the new refreshers in `_core.py`.** In the `~L505-515` block, REMOVE the `_periodic_locn` registration + its initial `await self._refresh_locn()` (the LOCN→position write is superseded). Add, following the same `_periodic_X` pattern:
  - `_refresh_gps` on a 60s interval (replaces the locn slot).
  - `_refresh_remote` on a 6h interval.
  - `_refresh_messages` on a 1h interval.
Mirror the exact `_periodic_X` closure + `async_track_time_interval(self.hass, _periodic_X, timedelta(...))` + initial `await self._refresh_X()` shape used by the existing blocks. Do NOT delete `_refresh_locn` the method or `fetch_locn` (kept for a future dock-location entity) — only remove its scheduling.

- [ ] **Step 5: Run tests + check _core wiring**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_phase_c_refreshers.py -q`
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -c "import ast; ast.parse(open('custom_components/dreame_a2_mower/coordinator/_core.py').read()); print('ok')"`
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -k "locn or refresh or coordinator" -q`
Expected: new tests pass; any test asserting `_refresh_locn` is scheduled / runs at startup is updated to reflect its retirement (note which you changed).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/state.py custom_components/dreame_a2_mower/coordinator/_refreshers.py custom_components/dreame_a2_mower/coordinator/_core.py tests/integration/test_phase_c_refreshers.py tests/
git commit -m "feat(c): GPS/REMOTE/messages refreshers + state fields; retire LOCN position write

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Sensors + device_tracker + entity-inventory

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor_device.py`
- Modify: `custom_components/dreame_a2_mower/device_tracker.py`
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Test: `tests/integration/test_phase_c_sensors.py` (create)

- [ ] **Step 1: Add 5 sensor descriptors** in `sensor_device.py` (mirror the `wifi_ssid` descriptor; all `EntityCategory.DIAGNOSTIC`):
```python
    DreameA2SensorEntityDescription(
        key="sim_card_id", name="SIM ICCID", icon="mdi:sim",
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda s: s.sim_card_id),
    DreameA2SensorEntityDescription(
        key="sim_left_days", name="SIM days remaining", icon="mdi:sim-alert",
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda s: s.sim_left_days),
    DreameA2SensorEntityDescription(
        key="sim_active_time", name="SIM activated", icon="mdi:sim",
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda s: s.sim_active_time),
    DreameA2SensorEntityDescription(
        key="sim_expired_time", name="SIM expires", icon="mdi:sim-off",
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda s: s.sim_expired_time),
    DreameA2SensorEntityDescription(
        key="service_messages_unread", name="Unread messages", icon="mdi:email-alert",
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda s: s.service_messages_unread),
```
(If `DreameA2SensorEntityDescription` supports an extra-attributes hook, add `latest_service_message` / `system_messages_unread` as attributes on the unread sensor; otherwise leave them as plain state fields — check the descriptor's capabilities and do the minimal correct thing.)

- [ ] **Step 2: Update `device_tracker.py`** — change the docstring source from "LOCN routed action" to "location/getRecords (absolute WGS84, ~4m, via 4G SIM)"; add `extra_state_attributes` exposing `gps_update_time` and `gps_card4g` (mirror how other entities expose attributes). No change to `latitude`/`longitude` (still read `position_lat`/`position_lon`, now getRecords-fed).

- [ ] **Step 3: Write the test** (`tests/integration/test_phase_c_sensors.py`):
```python
from custom_components.dreame_a2_mower import sensor_device
from custom_components.dreame_a2_mower.mower.state import MowerState


def _desc(key):
    return next(d for d in sensor_device.SENSOR_DESCRIPTIONS if d.key == key)
    # adapt SENSOR_DESCRIPTIONS to the real module-level list name


def test_sim_sensors_read_state():
    s = MowerState(sim_left_days=895, sim_card_id="FAKE", sim_active_time="a", sim_expired_time="e")
    assert _desc("sim_left_days").value_fn(s) == 895
    assert _desc("sim_card_id").value_fn(s) == "FAKE"
    assert _desc("sim_active_time").value_fn(s) == "a"
    assert _desc("sim_expired_time").value_fn(s) == "e"


def test_unread_sensor_reads_state():
    s = MowerState(service_messages_unread=2)
    assert _desc("service_messages_unread").value_fn(s) == 2
```
(Find the real descriptor-list name via `grep -nE "SENSOR_DESCRIPTIONS|_DESCRIPTIONS|: tuple|= \(" sensor_device.py` and adapt `_desc`.)

- [ ] **Step 4: Add entity-inventory entries** for the 5 new sensors (mirror the `wifi_ssid`/`wifi_ip` sensor entries' schema: source = the relevant cloud read (REMOTE / message-record-v1), `last_verified: "2026-06-10"`, a verification citing `app-mitm:2026-06-09-settings-sweep`). Sensors have no control_mode. Also **update the device_tracker entity-inventory entry's source from LOCN → getRecords** (if a stale "reads LOCN" claim exists, correct it; retract verbatim if literally false).

- [ ] **Step 5: Run tests + entity audit**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_phase_c_sensors.py -q`
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py`
Expected: sensor tests pass; entity audit `missing from inventory: 0` (the 5 new sensors are inventoried).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor_device.py custom_components/dreame_a2_mower/device_tracker.py custom_components/dreame_a2_mower/entity-inventory.yaml tests/integration/test_phase_c_sensors.py
git commit -m "feat(c): SIM + unread-messages sensors; device_tracker fed by getRecords

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Inventory fact-discipline + full verification

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`
- (verification)

- [ ] **Step 1: inventory.yaml** — getRecords / REMOTE / message-record-v1 are already `verified` (Phase 0). Append a `status: verified` verification (date 2026-06-10) to each recording they're now **wired + surfaced** in the integration (getRecords→device_tracker; REMOTE→4 SIM sensors; message-record-v1→unread sensor). Note the `_refresh_locn` position-write retirement on the LOCN entry. Evidence `app-mitm:2026-06-09-settings-sweep`. Bump `last_seen: "2026-06-10"`. (Retraction only if a prior claim is literally false — e.g. an entry asserting getRecords isn't reachable; quote verbatim if so.)

- [ ] **Step 2: Validate inventory**

Run:
```
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_gen.py --validate-only
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py
/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/audit_outstanding_retractions.py
```
Expected: validator ok; entity audit 0 missing; retraction audit clean.

- [ ] **Step 3: Commit inventory**

```bash
git add custom_components/dreame_a2_mower/inventory.yaml
git commit -m "inventory(c): record GPS/REMOTE/message-record now wired+surfaced; LOCN position retired

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Full suite + final report**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: 0 failures; 4 skipped; passed count ≥ prior baseline + new C tests.

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/inventory_audit.py --consistency`
Expected: clean.

- [ ] **Step 5: Report** the new sensors/tracker, that getRecords feeds the device_tracker (LOCN position-write retired, `fetch_locn` kept), pass/skip counts, and confirm no `.py` outside cloud_client/coordinator/sensor_device/device_tracker/mower-state changed.
