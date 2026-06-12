# MPOS diagnostic entity + refresh button — design

**Date:** 2026-06-12
**Status:** Design — pending review
**Topic:** Surface the routed-get `MPOS` reading (live mower position as the
cloud reports it) as a **read-only diagnostic** entity plus an on-demand
**refresh button**, with **no coordinate transform and no position-driving**, so
its frame/units can be characterized against the physical mower before deciding
whether it should ever drive or co-drive the integration's position.

---

## 1. Why this exists

`MPOS` was decoded 2026-06-09 by `tools/probes/read_key_probe.py`: the routed-get
`action(siid:2, aiid:50, [{"m":"g","t":"MPOS","d":None}])` returns `r:0` with
`d={"x":<int>,"y":<int>,"yaw":<int>}` (observed `{x:95,y:-4,yaw:0}` at dock-idle)
[tools/probes/read_key_probe.py@2026-06-09; inventory.yaml § MPOS, status partial].

The integration's live position today comes from **s1p4 MQTT telemetry**
(`position_x_m/y_m/heading_deg`, dock-relative metres). `MPOS` is a *cloud*
read of position — a potential MQTT-down/startup fallback or cross-check — but
its **frame and units are unverified**: the single dock-idle sample can't reveal
whether it's mm vs cm, or the same dock-relative frame s1p4 uses. Calibrating
that needs the mower mid-lawn (large coordinates) where the two can be compared,
which can't be forced from a desk.

So this feature is deliberately scoped to **observation only**: surface the raw
values and let the user press refresh while standing at the mower, record what
`MPOS` says vs where the mower physically is, and from that data decide later
whether `MPOS` should drive/co-drive `position_*`. Driving position is
**explicitly out of scope** here.

---

## 2. Architecture / data flow

```
button "Refresh MPOS"  ──>  coordinator.async_refresh_mpos()
                                  │  (hass.async_add_executor_job)
                                  ▼
                       cloud_client.fetch_mpos()  ── routed-get m:g t:MPOS
                                  │  returns {"x","y","yaw"} | None
                                  ▼
                       MowerState.mpos_{x,y,yaw,updated_unix}  (RAW, untransformed)
                                  │
                                  ▼
                       sensor "MPOS" (diagnostic) reflects fields
```

No transform, no reflection, no map/icon interaction. The values written are
exactly what the wire returns.

---

## 3. Components

| Unit | File | Responsibility |
|---|---|---|
| `fetch_mpos()` | `cloud_client/_fetchers.py` | Issue the routed-get, return `{"x","y","yaw"}` on `r:0`, else `None` |
| `MowerState` fields | `mower/state.py` | `mpos_x`, `mpos_y`, `mpos_yaw` (`int | None`), `mpos_updated_unix` (`int | None`), `mpos_last_result` (`str | None`) |
| `async_refresh_mpos()` | coordinator (new method on a `_refreshers`-style mixin) | Executor-fetch + write fields via `async_set_updated_data`; never raises |
| MPOS sensor | `sensor*.py` (parent-device, diagnostic) | One entity; state + x/y/yaw/last-updated attributes |
| Refresh button | `button.py` (parent-device, diagnostic) | Calls `async_refresh_mpos()` |
| inventory entries | `entity-inventory.yaml` | sensor + button rows; read source = MPOS routed-get |

### 3.1 `fetch_mpos()`
```
def fetch_mpos(self) -> dict | None:
    resp = self.action(siid=2, aiid=50, parameters=[{"m": "g", "t": "MPOS", "d": None}])
    # resp["out"][0]: {"m":"r","r":0,"d":{"x","y","yaw"}}  (r:-1/-3 = idle/no-data)
    # return d on r==0 with a dict d; else None. Never raise (log + None).
```
Mirrors the defensive shape of the existing routed-get helpers
(`list_3dmap_objects`, `fetch_wifi_map`): tolerate non-dict resp, missing `out`,
non-zero `r`. `d=None` is sent verbatim (the app sends no args for the bare get).

### 3.2 State fields
`mpos_x/y/yaw` are raw ints as received — **no unit conversion**.
`mpos_updated_unix` is stamped by the coordinator at write time (so the sensor
can show staleness). `mpos_last_result` records `ok|idle|error` for the most
recent press. All default `None` until the first refresh.

### 3.3 Sensor (one entity)
- `entity_id`: `sensor.dreame_a2_mower_mpos`, name `"MPOS"`, parent device
  (`mower_device_info`), `entity_category = diagnostic`, no `device_class`.
- **State:** a compact string `"<x>, <y>, <yaw>"` when all present, else
  `None`/unknown. (Single human-readable "is it there + what does it say" value,
  matching the user's "surface the array" intent.)
- **Attributes:** `x`, `y`, `yaw` (raw ints), `last_updated` (ISO from
  `mpos_updated_unix`), `last_result` (`ok`|`idle`|`error` — outcome of the most
  recent refresh, so an idle/no-data press is visible), and a short `note`
  stating the values are raw/cloud-frame and untransformed, for dashboard honesty.
- Read-only; no `RestoreEntity` (a stale restored MPOS would mislead the
  matching exercise — blank-until-refreshed is more honest). Updates on
  coordinator state change like other coordinator-backed sensors.

### 3.4 Button
- `entity_id`: `button.dreame_a2_mower_refresh_mpos`, name `"Refresh MPOS"`,
  parent device, `entity_category = diagnostic`.
- `async_press` → `await coordinator.async_refresh_mpos()`.
- No auto-poll anywhere (button-only, per decision). A periodic piggyback on the
  2-min cloud refresh is a trivial future add but deliberately omitted now.

---

## 4. Error handling

- `fetch_mpos()` returns `None` on `r:-1/-3` (idle/no-data), transport failure,
  or malformed response — all logged at DEBUG/WARNING, never raised.
- `async_refresh_mpos()` on `None`: leaves prior `mpos_x/y/yaw/updated_unix`
  intact (no false "freshen"), sets `mpos_last_result = "idle"` (r:-1/-3) or
  `"error"` (transport/malformed), and logs the outcome. On success it sets the
  four value fields, `mpos_updated_unix = now`, and `mpos_last_result = "ok"`.
  (`mpos_last_result` is a fifth `MowerState` field, `str | None`.)
- Button press while the cloud client is unavailable: `async_refresh_mpos()`
  no-ops with a logged warning; the button never errors the UI.

---

## 5. Honesty / fact-discipline

- The MPOS protocol fact is already `partial` in `inventory.yaml § MPOS`. This
  feature adds **entity** rows in `entity-inventory.yaml` (the sensor + button),
  status `presumed` (code-wired, not yet physically validated), read source =
  MPOS routed-get. No new `verified` protocol claim is made — frame/units stay
  `[UNKNOWN — to capture: physical-match]`.
- The sensor's `note` attribute and the spec both state the values are raw and
  must not be treated as the integration's position.

---

## 6. Testing

- `fetch_mpos()` — unit test with a fake client: `r:0`→dict, `r:-3`→None,
  malformed/missing `out`→None, exception→None.
- `async_refresh_mpos()` — fake cloud returning a dict writes the four fields +
  timestamp; returning `None` leaves prior values and doesn't bump freshness.
- Sensor — state string + attributes from fields (incl. the all-None blank case),
  diagnostic category, parent-device naming (`sensor.dreame_a2_mower_mpos`).
- Button — press calls `async_refresh_mpos()` once.
- Gates: `entity-inventory` audit (two new entities) + per-map-naming regression
  (these are parent-device, name = entity-only) + full suite green.

---

## 7. Out of scope (explicit)

- **Driving/co-driving `position_*`** — deferred until the physical-match data
  says MPOS is trustworthy and its transform is known.
- Any coordinate transform / midline reflection / frame conversion.
- Auto-polling MPOS (button-only for now).
- Decoding `MPOS` args (the `r:-3` keys like PRE/AIOBS need an arg form; MPOS's
  bare get already returns `r:0`, so no arg work here).
