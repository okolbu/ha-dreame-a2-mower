# Messages "Info" dashboard tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the Dreame message center's Device / Service / Sharing message lists as three read-only HA sensors and render them on a new dashboard "Info" tab as markdown cards, with a configurable per-list cap.

**Architecture:** A pure `protocol/message_record.py` normalizes each upstream source into a common `Message` shape. The existing 1 h `_refresh_messages` cycle calls three fetchers (extend `fetch_message_record`, reuse `fetch_device_messages`, add `fetch_share_messages`), normalizes + trims to `CONF_MESSAGES_KEEP`, and writes three new `MowerState` list fields. Three `DreameA2Sensor`-style sensors expose `state = unread count` + an `items` attribute (recorder-excluded), mirroring the existing `patrol_points` / photo-gallery pattern. A new YAML dashboard view renders one markdown card per list.

**Tech Stack:** Python 3.13, Home Assistant custom component, `dataclasses`, `voluptuous` (options flow), `pytest` (stubbed-HA vanilla venv), Jinja2 markdown Lovelace cards.

**Test command (local):** run from repo root `/data/claude/homeassistant/ha-dreame-a2-mower` using the vanilla venv:
`/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest <path> -v`

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `custom_components/dreame_a2_mower/protocol/message_record.py` | Pure normalizers: upstream record → `Message` | Create |
| `custom_components/dreame_a2_mower/const.py` | `CONF_MESSAGES_KEEP` + `DEFAULT_MESSAGES_KEEP` | Modify |
| `custom_components/dreame_a2_mower/config_flow.py` | Options-flow cap field | Modify |
| `custom_components/dreame_a2_mower/cloud_client/_fetchers.py` | Return service list; add `fetch_share_messages` | Modify |
| `custom_components/dreame_a2_mower/mower/state.py` | 3 new `MowerState` list fields | Modify |
| `custom_components/dreame_a2_mower/coordinator/_refreshers.py` | Wire fetch→normalize→trim→state in `_refresh_messages` | Modify |
| `custom_components/dreame_a2_mower/entities/sensor/device.py` | 3 read-only message-list sensors | Modify |
| `custom_components/dreame_a2_mower/sensor.py` | Register the 3 sensors | Modify (if needed) |
| `custom_components/dreame_a2_mower/entity-inventory.yaml` | Rows for the 3 sensors | Modify |
| `custom_components/dreame_a2_mower/inventory.yaml` | Verification on message_record_and_messaging_endpoints | Modify |
| `tools/state_machine/state_machine_audit_expectations.yaml` | Audit rows for the 3 sensors | Modify |
| `tests/protocol/test_message_record.py` | Normalizer unit tests | Create |
| `tests/integration/test_messages_refresh.py` | Refresher trim/wire test | Create |
| `tests/integration/test_messages_sensors.py` | Sensor state/items test | Create |
| `tests/config/test_options_flow_messages_keep.py` | Options-flow cap test | Create |
| docs (TODO→DONE) | Move the resolved TODO | Modify |
| `/config/dashboards/mower/dashboard.yaml` (HA host) | New "Info" view (deploy artifact) | Deploy (SCP) |

---

## Task 1: Config cap (`CONF_MESSAGES_KEEP`)

**Files:**
- Modify: `custom_components/dreame_a2_mower/const.py`
- Modify: `custom_components/dreame_a2_mower/config_flow.py`
- Test: `tests/config/test_options_flow_messages_keep.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/config/test_options_flow_messages_keep.py
from custom_components.dreame_a2_mower.const import (
    CONF_MESSAGES_KEEP,
    DEFAULT_MESSAGES_KEEP,
)
from custom_components.dreame_a2_mower.config_flow import DreameA2MowerOptionsFlow


class _FakeEntry:
    options: dict = {}


def _flow():
    flow = DreameA2MowerOptionsFlow()
    flow.config_entry = _FakeEntry()  # type: ignore[attr-defined]
    return flow


def test_default_messages_keep_is_100():
    assert DEFAULT_MESSAGES_KEEP == 100


def test_schema_includes_messages_keep_with_default():
    schema = _flow()._build_schema()
    # voluptuous Schema: find the CONF_MESSAGES_KEEP marker + its default
    markers = {str(k): k for k in schema.schema}
    assert CONF_MESSAGES_KEEP in markers
    assert markers[CONF_MESSAGES_KEEP].default() == DEFAULT_MESSAGES_KEEP
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/config/test_options_flow_messages_keep.py -v`
Expected: FAIL — `ImportError: cannot import name 'CONF_MESSAGES_KEEP'`.

- [ ] **Step 3: Add the constants**

In `const.py`, after the `CONF_WIFI_ARCHIVE_KEEP` line (~118) add:

```python
CONF_MESSAGES_KEEP: Final = "messages_keep"
```

After the `DEFAULT_*_ARCHIVE_KEEP` block (~161) add:

```python
DEFAULT_MESSAGES_KEEP: Final = 100
```

- [ ] **Step 4: Add the options-flow field**

In `config_flow.py`, add to the imports from `.const` (the existing `CONF_*` block ~20-28): `CONF_MESSAGES_KEEP,` and `DEFAULT_MESSAGES_KEEP,`.

In `DreameA2MowerOptionsFlow._build_schema`, inside the returned `vol.Schema({...})`, after the `CONF_WIFI_ARCHIVE_KEEP` entry add:

```python
                # Message center retention: keep newest-N per list
                # (device / service / sharing). Records are tiny; default
                # generous. Applied identically to all three lists.
                vol.Optional(
                    CONF_MESSAGES_KEEP,
                    default=opts.get(
                        CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP
                    ),
                ): vol.All(int, vol.Range(min=1, max=500)),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/config/test_options_flow_messages_keep.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/const.py custom_components/dreame_a2_mower/config_flow.py tests/config/test_options_flow_messages_keep.py
git commit -m "feat(messages): add CONF_MESSAGES_KEEP options cap (default 100)"
```

---

## Task 2: Pure normalizer (`protocol/message_record.py`)

Normalizes each upstream record into a common shape. Service + device shapes are known; share is parsed defensively (its field names are confirmed in Task 7's capture).

**Files:**
- Create: `custom_components/dreame_a2_mower/protocol/message_record.py`
- Test: `tests/protocol/test_message_record.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/protocol/test_message_record.py
import json

from custom_components.dreame_a2_mower.protocol.message_record import (
    Message,
    normalize_service,
    normalize_device,
    normalize_share,
    unread_count,
)


def _svc_rec(name, content, link, read, mid="1", ts=1780000000):
    return {
        "id": mid,
        "readStatus": read,        # 1 = read, 0 = unread
        "createTime": ts,
        "multiLangDisplay": json.dumps(
            {"en": {"name": name, "content": content, "link": link}}
        ),
    }


def test_normalize_service_maps_fields_and_unread():
    recs = [_svc_rec("Summer sale", "30% off", "https://x", 0, "9", 1780000900)]
    out = normalize_service(recs)
    assert out == [
        Message(
            id="9",
            title="Summer sale",
            date="2026-05-28T07:08:20+00:00",  # 1780000900 UTC
            body="30% off",
            link="https://x",
            unread=True,
        )
    ]


def test_normalize_service_orders_newest_first():
    recs = [_svc_rec("old", "", None, 1, "1", 1000), _svc_rec("new", "", None, 1, "2", 2000)]
    out = normalize_service(recs)
    assert [m.id for m in out] == ["2", "1"]


def test_normalize_service_tolerates_missing_keys():
    assert normalize_service([{"id": "x"}]) == [
        Message(id="x", title="", date=None, body=None, link=None, unread=True)
    ]


def test_normalize_device_has_no_read_flag_so_all_unread():
    recs = [
        {
            "messageId": "m1",
            "sendTime": 1780000000,
            "multiLangDisplay": json.dumps({"en": {"name": "Right drive wheel error"}}),
        }
    ]
    out = normalize_device(recs)
    assert out[0].id == "m1"
    assert out[0].title == "Right drive wheel error"
    assert out[0].unread is True  # device has no reliable read flag → treated unread


def test_normalize_share_defensive_returns_messages():
    # Provisional shape (refined post-capture in Task 7). Defensive parse must
    # not raise and must produce a Message per record.
    out = normalize_share([{"id": "s1", "title": "Home shared with you"}])
    assert len(out) == 1 and out[0].id == "s1"


def test_unread_count_counts_unread():
    msgs = [
        Message("1", "a", None, None, None, True),
        Message("2", "b", None, None, None, False),
    ]
    assert unread_count(msgs) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_message_record.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '...protocol.message_record'`.

- [ ] **Step 3: Write the module**

```python
# custom_components/dreame_a2_mower/protocol/message_record.py
"""Normalize Dreame message-center records into one shape.

Pure module (no I/O). Three upstream sources feed the dashboard "Info" tab:

  - service  — v1 message-record/list serviceMsg.msgRecord
               (multiLangDisplay JSON, readStatus, createTime)  [verified]
  - device   — device-messages/v2 content[] (messageId, sendTime,
               multiLang text; no reliable read flag)            [verified]
  - share    — /dreame-messaging/user/share-messages             [field names
               confirmed by live capture — see the plan's Task 7]

Each becomes a ``Message``; ``date`` is ISO-8601 UTC. Newest first.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Message:
    id: str
    title: str
    date: str | None
    body: str | None
    link: str | None
    unread: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "date": self.date,
            "body": self.body,
            "link": self.link,
            "unread": self.unread,
        }


def _iso(ts: Any) -> str | None:
    """Epoch seconds (or ms) → ISO-8601 UTC string, or None."""
    if ts is None:
        return None
    try:
        v = float(ts)
    except (TypeError, ValueError):
        return None
    if v > 1e11:  # milliseconds
        v /= 1000.0
    try:
        return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _en_display(rec: dict) -> dict:
    """Decode multiLangDisplay JSON → the en (or first) lang dict."""
    raw = rec.get("multiLangDisplay")
    if not raw:
        return {}
    try:
        disp = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return {}
    if not isinstance(disp, dict):
        return {}
    return disp.get("en") or next((v for v in disp.values() if isinstance(v, dict)), {})


def _sorted_newest_first(items: list[tuple[Any, Message]]) -> list[Message]:
    """Sort (sort_key, Message) by key desc; None keys sort last."""
    return [
        m
        for _, m in sorted(
            items, key=lambda t: (t[0] is not None, t[0] or 0), reverse=True
        )
    ]


def normalize_service(records: list[dict] | None) -> list[Message]:
    out: list[tuple[Any, Message]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        en = _en_display(rec)
        ts = rec.get("createTime") or rec.get("sendTime")
        out.append(
            (
                ts,
                Message(
                    id=str(rec.get("id") or rec.get("messageId") or ""),
                    title=str(en.get("name") or ""),
                    date=_iso(ts),
                    body=en.get("content") or None,
                    link=en.get("link") or None,
                    # readStatus: 1 = read, 0/absent = unread
                    unread=not bool(rec.get("readStatus")),
                ),
            )
        )
    return _sorted_newest_first(out)


def normalize_device(records: list[dict] | None) -> list[Message]:
    out: list[tuple[Any, Message]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        en = _en_display(rec)
        ts = rec.get("sendTime") or rec.get("createTime")
        out.append(
            (
                ts,
                Message(
                    id=str(rec.get("messageId") or rec.get("id") or ""),
                    title=str(en.get("name") or en.get("content") or ""),
                    date=_iso(ts),
                    body=en.get("content") or None,
                    link=en.get("link") or None,
                    # device-messages/v2 carries no reliable read flag → treat
                    # all as unread so the sensor state falls back to total.
                    unread=True,
                ),
            )
        )
    return _sorted_newest_first(out)


def normalize_share(records: list[dict] | None) -> list[Message]:
    # Defensive: confirm exact field names via the Task 7 live capture, then
    # tighten. Must never raise on an unexpected shape.
    out: list[tuple[Any, Message]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        en = _en_display(rec)
        ts = rec.get("createTime") or rec.get("sendTime") or rec.get("time")
        title = (
            en.get("name")
            or rec.get("title")
            or rec.get("content")
            or rec.get("message")
            or ""
        )
        out.append(
            (
                ts,
                Message(
                    id=str(rec.get("id") or rec.get("messageId") or ""),
                    title=str(title),
                    date=_iso(ts),
                    body=(en.get("content") or rec.get("content") or None),
                    link=(en.get("link") or rec.get("link") or None),
                    unread=not bool(rec.get("readStatus") or rec.get("read")),
                ),
            )
        )
    return _sorted_newest_first(out)


def unread_count(messages: list[Message]) -> int:
    return sum(1 for m in messages if m.unread)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_message_record.py -v`
Expected: PASS (all 6 tests). If the `date` assertion fails on tz formatting, copy the exact ISO string the test prints into the expected value (UTC offset rendering is deterministic).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/message_record.py tests/protocol/test_message_record.py
git commit -m "feat(messages): pure message_record normalizer (service/device/share)"
```

---

## Task 3: Fetchers (service list + share-messages)

**Files:**
- Modify: `custom_components/dreame_a2_mower/cloud_client/_fetchers.py`
- Test: `tests/integration/test_messages_refresh.py` (fetcher portion)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_messages_refresh.py
from unittest.mock import MagicMock
from custom_components.dreame_a2_mower.cloud_client._fetchers import _FetchersMixin


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.text = "x"

    def json(self):
        return self._p


def _client(resp):
    c = _FetchersMixin.__new__(_FetchersMixin)
    c._ensure_strings = lambda: None
    c._key_expire = None
    c._strings = [""] * 60
    c.strings = [""] * 60
    c._session = MagicMock()
    c._session.get.return_value = resp
    c.get_api_url = lambda: "https://api"
    c.login = lambda: None
    return c


def test_fetch_message_record_returns_service_records():
    payload = {"data": {"serviceMsg": {"unread": 2, "msgRecord": [{"id": "1"}]},
                        "systemMsg": {"unread": 0}}}
    c = _client(_Resp(200, payload))
    out = c.fetch_message_record()
    assert out["service_unread"] == 2
    assert out["service_records"] == [{"id": "1"}]


def test_fetch_share_messages_returns_list():
    payload = {"code": 0, "data": {"content": [{"id": "s1"}]}}
    c = _client(_Resp(200, payload))
    out = c.fetch_share_messages(limit=50)
    assert out == [{"id": "s1"}]


def test_fetch_share_messages_none_on_http_error():
    c = _client(_Resp(500, {}))
    assert c.fetch_share_messages(limit=50) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_messages_refresh.py -v`
Expected: FAIL — `KeyError: 'service_records'` and `AttributeError: ... 'fetch_share_messages'`.

- [ ] **Step 3a: Add `service_records` to `fetch_message_record`**

In `cloud_client/_fetchers.py`, in `fetch_message_record`, change the final `return` dict to also carry the raw service list:

```python
        return {
            "service_unread": svc.get("unread"),
            "system_unread": sysm.get("unread"),
            "latest": latest,
            "service_records": recs,   # raw serviceMsg.msgRecord (was discarded)
        }
```

(`recs` is already computed above as `svc.get("msgRecord") or []`.)

- [ ] **Step 3b: Add `fetch_share_messages`**

Add this method to `_FetchersMixin` (next to `fetch_message_record`), reusing the same header pattern:

```python
    def fetch_share_messages(self, limit: int = 100, offset: int = 0) -> list | None:
        """Sharing-tab messages via /dreame-messaging/user/share-messages.

        GET …/share-messages?version=v1&limit=<limit>&offset=<offset>.
        Returns the raw record list (data.content), or None on failure.
        Logs at WARNING; does not raise.
        """
        self._ensure_strings()
        if getattr(self, "_key_expire", None) and time.time() > self._key_expire:
            self.login()
        strings = getattr(self, "_strings", None) or self.strings
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            strings[47]: strings[3],
            strings[49]: strings[5],
            strings[50]: getattr(self, "_ti", None) or strings[6],
            strings[51]: strings[52],
            strings[46]: getattr(self, "_key", ""),
        }
        if getattr(self, "_country", None) == "cn":
            headers[strings[48]] = strings[4]
        try:
            url = f"{self.get_api_url()}/dreame-messaging/user/share-messages"
            resp = self._session.get(
                url,
                headers=headers,
                params={"version": "v1", "limit": limit, "offset": offset},
                timeout=10,
            )
            if resp.status_code != 200:
                _LOGGER.warning(
                    "fetch_share_messages: HTTP %d (body: %s)",
                    resp.status_code, resp.text[:200],
                )
                return None
            body = resp.json()
        except Exception as ex:  # pragma: no cover
            _LOGGER.warning("fetch_share_messages: %s", ex)
            return None
        records = (body or {}).get("data") or {}
        recs = records.get("content") if isinstance(records, dict) else None
        return recs if isinstance(recs, list) else None
```

(`time` and `_LOGGER` are already imported at the top of `_fetchers.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_messages_refresh.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/cloud_client/_fetchers.py tests/integration/test_messages_refresh.py
git commit -m "feat(messages): fetch service list + add fetch_share_messages"
```

---

## Task 4: MowerState fields

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py`

- [ ] **Step 1: Locate the existing message fields**

Run: `grep -n "service_messages_unread\|system_messages_unread\|latest_service_message" custom_components/dreame_a2_mower/mower/state.py`
Expected: shows the three existing message-count fields on `MowerState`.

- [ ] **Step 2: Add three list fields**

Immediately after the `latest_service_message` field on `MowerState`, add:

```python
    device_messages: list = field(default_factory=list)
    service_messages: list = field(default_factory=list)
    shared_messages: list = field(default_factory=list)
```

(`field` is already imported from `dataclasses` in this module; if a `list` default needs `default_factory`, use the form shown.)

- [ ] **Step 3: Run the state test to verify nothing broke**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/mower/test_state.py -v`
Expected: PASS (existing tests unaffected; new fields default to empty lists).

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/state.py
git commit -m "feat(messages): MowerState device/service/shared_messages list fields"
```

---

## Task 5: Refresher wiring

Wire fetch → normalize → trim to cap → write state inside the existing `_refresh_messages`.

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_refreshers.py`
- Test: `tests/integration/test_messages_refresh.py` (refresher portion)

- [ ] **Step 1: Add the failing test (append to the existing test file)**

```python
# append to tests/integration/test_messages_refresh.py
import dataclasses
from custom_components.dreame_a2_mower.coordinator._refreshers import _RefreshersMixin
from custom_components.dreame_a2_mower.mower.state import MowerState


def test_refresh_messages_normalizes_and_trims(monkeypatch):
    coord = _RefreshersMixin.__new__(_RefreshersMixin)
    coord.data = MowerState()
    coord._entry = type("E", (), {"options": {"messages_keep": 2}})()

    svc = [{"id": str(i), "createTime": i,
            "multiLangDisplay": '{"en":{"name":"m%d"}}' % i} for i in range(5)]
    cloud = type("C", (), {})()
    cloud.fetch_message_record = lambda: {
        "service_unread": 1, "system_unread": 0, "latest": "x", "service_records": svc}
    cloud.fetch_device_messages = lambda did, n: []
    cloud.fetch_share_messages = lambda limit, offset=0: []
    coord._cloud = cloud
    coord._did = "did123"

    captured = {}
    coord.async_set_updated_data = lambda new: captured.update(new=new)

    async def _run():
        await _RefreshersMixin._refresh_messages(coord)
    import asyncio
    # executor jobs run inline in this stub:
    coord.hass = type("H", (), {})()
    coord.hass.async_add_executor_job = lambda fn, *a: _Immediate(fn(*a))
    asyncio.get_event_loop().run_until_complete(_run())

    new = captured["new"]
    assert len(new.service_messages) == 2          # trimmed to cap
    assert new.service_messages[0]["title"] == "m4"  # newest first


class _Immediate:
    """Await-able that returns a precomputed value (stub executor job)."""
    def __init__(self, value):
        self._v = value
    def __await__(self):
        if False:
            yield
        return self._v
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_messages_refresh.py::test_refresh_messages_normalizes_and_trims -v`
Expected: FAIL — `_refresh_messages` doesn't populate `service_messages`.

- [ ] **Step 3: Update `_refresh_messages`**

In `coordinator/_refreshers.py`, add near the top of the file (with the other imports):

```python
from ..protocol import message_record as _msg
from ..const import CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP
```

Replace the body of `_refresh_messages` with:

```python
    async def _refresh_messages(self) -> None:
        """Account message lists + unread counts via message-record/list v1,
        device-messages/v2, and share-messages. Trims each list to the cap."""
        if not hasattr(self, "_cloud"):
            return
        cap = int(
            getattr(self, "_entry", None).options.get(
                CONF_MESSAGES_KEEP, DEFAULT_MESSAGES_KEEP
            )
            if getattr(self, "_entry", None) is not None
            else DEFAULT_MESSAGES_KEEP
        )

        m = await self.hass.async_add_executor_job(self._cloud.fetch_message_record)
        dev_raw = await self.hass.async_add_executor_job(
            self._cloud.fetch_device_messages, self._did, 10
        )
        share_raw = await self.hass.async_add_executor_job(
            self._cloud.fetch_share_messages, cap
        )

        kw: dict = {}
        if m:
            kw["service_messages_unread"] = m.get("service_unread")
            kw["system_messages_unread"] = m.get("system_unread")
            kw["latest_service_message"] = m.get("latest")
            kw["service_messages"] = [
                msg.as_dict()
                for msg in _msg.normalize_service(m.get("service_records"))[:cap]
            ]
        if dev_raw is not None:
            kw["device_messages"] = [
                msg.as_dict() for msg in _msg.normalize_device(dev_raw)[:cap]
            ]
        if share_raw is not None:
            kw["shared_messages"] = [
                msg.as_dict() for msg in _msg.normalize_share(share_raw)[:cap]
            ]
        if not kw:
            return
        new = dataclasses.replace(self.data, **kw)
        if new != self.data:
            self.async_set_updated_data(new)
```

Note: verify the coordinator's config-entry attribute name — run
`grep -n "self\._entry\b\|self\.config_entry\|self\._did\b" custom_components/dreame_a2_mower/coordinator/_core.py | head`. If the entry is `self.config_entry`, replace `self._entry` accordingly; if the device id is not `self._did`, use the actual attribute the existing notifications code uses (`grep -n "fetch_device_messages" coordinator/_notifications.py` shows how `did` is obtained).

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_messages_refresh.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_refreshers.py tests/integration/test_messages_refresh.py
git commit -m "feat(messages): wire fetch+normalize+trim into _refresh_messages"
```

---

## Task 6: Sensors

Three read-only sensors mirroring the photo-gallery `items` pattern. Place them in `entities/sensor/device.py` next to the existing message-count sensor.

**Files:**
- Modify: `custom_components/dreame_a2_mower/entities/sensor/device.py`
- Modify: `custom_components/dreame_a2_mower/sensor.py` (register, if it uses an explicit list)
- Test: `tests/integration/test_messages_sensors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_messages_sensors.py
from custom_components.dreame_a2_mower.entities.sensor.device import (
    DreameA2DeviceMessagesSensor,
    DreameA2ServiceMessagesSensor,
    DreameA2SharedMessagesSensor,
)
from custom_components.dreame_a2_mower.mower.state import MowerState


class _Coord:
    def __init__(self, data):
        self.data = data
        self.last_update_success = True


def _sensor(cls, data):
    s = cls.__new__(cls)
    s.coordinator = _Coord(data)
    return s


def test_service_messages_sensor_state_is_unread_count():
    data = MowerState()
    data = data.__class__(**{**data.__dict__, "service_messages": [
        {"id": "1", "title": "a", "unread": True},
        {"id": "2", "title": "b", "unread": False},
    ]})
    s = _sensor(DreameA2ServiceMessagesSensor, data)
    assert s.native_value == 1
    assert s.extra_state_attributes["items"][0]["id"] == "1"


def test_message_sensors_exclude_recorder():
    assert DreameA2DeviceMessagesSensor._unrecorded_attributes == frozenset({"*"})
    assert DreameA2SharedMessagesSensor._unrecorded_attributes == frozenset({"*"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_messages_sensors.py -v`
Expected: FAIL — `ImportError` (classes don't exist).

- [ ] **Step 3: Add the sensor classes**

In `entities/sensor/device.py`, add (near the photo-gallery sensor that already uses `_unrecorded_attributes = frozenset({"*"})`):

```python
class _DreameA2MessageListSensor(DreameA2Entity, SensorEntity):
    """Base: state = unread count, items attr = the normalized list."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unrecorded_attributes = frozenset({"*"})
    _FIELD = ""  # MowerState list attribute name
    _attr_has_entity_name = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_{self._FIELD}"

    def _items(self) -> list:
        return list(getattr(self.coordinator.data, self._FIELD, None) or [])

    @property
    def native_value(self) -> int:
        return sum(1 for it in self._items() if it.get("unread"))

    @property
    def extra_state_attributes(self) -> dict:
        return {"items": self._items()}


class DreameA2DeviceMessagesSensor(_DreameA2MessageListSensor):
    _attr_name = "Device messages"
    _attr_icon = "mdi:robot"
    _FIELD = "device_messages"


class DreameA2ServiceMessagesSensor(_DreameA2MessageListSensor):
    _attr_name = "Service messages"
    _attr_icon = "mdi:email-newsletter"
    _FIELD = "service_messages"


class DreameA2SharedMessagesSensor(_DreameA2MessageListSensor):
    _attr_name = "Shared messages"
    _attr_icon = "mdi:account-multiple"
    _FIELD = "shared_messages"
```

Verify the base class + imports match this file: run `grep -n "class DreameA2Entity\|from .base import\|EntityCategory\|SensorStateClass\|SensorEntity\|entry_id" custom_components/dreame_a2_mower/entities/sensor/device.py | head`. Adjust the base class name / import line and the `unique_id` source (`coordinator.entry_id` vs `coordinator.config_entry.entry_id`) to match the existing sensors in this file. Use the SAME parent-device wiring the existing `service_messages_unread` sensor uses.

- [ ] **Step 4: Register the sensors**

Run `grep -n "service_messages_unread\|async_add_entities\|entities.append\|SENSORS\b" custom_components/dreame_a2_mower/sensor.py | head` to find how parent sensors are added. Add the three new classes to that list/append exactly as the existing message-count sensor is added.

- [ ] **Step 5: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_messages_sensors.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/entities/sensor/device.py custom_components/dreame_a2_mower/sensor.py tests/integration/test_messages_sensors.py
git commit -m "feat(messages): device/service/shared message-list sensors"
```

---

## Task 7: Confirm the share-messages wire shape (live capture) + finalize parser

The one `[UNKNOWN — to capture]` from the spec. Do this on the dev box with cloud access.

**Files:**
- Create: `tests/protocol/data/share_messages_sample.json` (captured fixture)
- Modify: `custom_components/dreame_a2_mower/protocol/message_record.py` (tighten `normalize_share` if fields differ)
- Modify: `custom_components/dreame_a2_mower/inventory.yaml` (verification)
- Test: `tests/protocol/test_message_record.py` (add a fixture-driven share test)

- [ ] **Step 1: Capture the live response**

Use the existing probe machinery to GET `/dreame-messaging/user/share-messages?version=v1&limit=50&offset=0` with the integration token (mirror `tools/probes/probe_a2_endpoints.py`). Save the raw `data.content[0]` record to `tests/protocol/data/share_messages_sample.json`. If the endpoint returns 0 records (no shares on this account), record that fact in the inventory verification and keep `normalize_share` defensive (the `test_normalize_share_defensive_returns_messages` test already covers the empty/unknown path).

- [ ] **Step 2: Add a fixture-driven test (only if records were captured)**

```python
# add to tests/protocol/test_message_record.py
import json as _json, pathlib

def test_normalize_share_against_captured_fixture():
    p = pathlib.Path(__file__).parent / "data" / "share_messages_sample.json"
    if not p.exists():
        import pytest; pytest.skip("no share-messages capture on this account")
    rec = _json.loads(p.read_text())
    out = normalize_share([rec])
    assert out and out[0].id  # id present
    assert out[0].title       # title resolved from the real fields
```

- [ ] **Step 3: Tighten `normalize_share` to the captured field names** (only if they differ from the defensive guesses). Keep the defensive `.get` fallbacks.

- [ ] **Step 4: Run tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_message_record.py -v`
Expected: PASS (skips the fixture test if no capture).

- [ ] **Step 5: Record the inventory verification**

In `inventory.yaml` § `message_record_and_messaging_endpoints`, append a `verifications:` entry dated today: status `verified` if records captured (with the field map + `[probe:<file>]` evidence) or `partial` if the account had 0 shares (note the parser stays defensive). Update `status.last_seen`.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/protocol/message_record.py custom_components/dreame_a2_mower/inventory.yaml tests/protocol/test_message_record.py tests/protocol/data/share_messages_sample.json
git commit -m "feat(messages): confirm share-messages shape + finalize normalize_share"
```

---

## Task 8: Inventory + audit bookkeeping (CI gates)

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify: `tools/state_machine/state_machine_audit_expectations.yaml`

- [ ] **Step 1: Add entity-inventory rows**

For each of the three sensors, add a row modeled on the existing
`sensor.dreame_a2_mower_service_messages_unread` entry (id, platform: sensor,
class, class_file, device: parent, source.wire = the endpoint, source.state_path
= `MowerState.<field>`, write_path: read-only, a `verifications` entry dated
today). Use ids:
`sensor.dreame_a2_mower_device_messages`, `_service_messages`, `_shared_messages`.

- [ ] **Step 2: Add audit-expectation rows**

For each new sensor add the matching rows to
`tools/state_machine/state_machine_audit_expectations.yaml` (two yellows each —
idle + reboot — as the existing diagnostic sensors do; copy the shape of an
existing sensor's rows). This prevents `tests/audit` from going red.

- [ ] **Step 3: Run the gates**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory/entity_inventory_audit.py`
Expected: OK (every entity class inventoried).
Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/audit -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml tools/state_machine/state_machine_audit_expectations.yaml
git commit -m "chore(messages): entity-inventory + audit rows for message sensors"
```

---

## Task 9: Dashboard "Info" view (deploy artifact)

The live dashboard is YAML-mode on the HA host (`/config/dashboards/mower/dashboard.yaml`) and is NOT in this repo — deploy via the standard SCP procedure (backup first, browser-reload, no restart).

- [ ] **Step 1: Author the view YAML**

Append this view to `dashboard.yaml`:

```yaml
  - title: Info
    path: info
    icon: mdi:message-text
    cards:
      - type: markdown
        title: Device messages
        content: >
          {% set items = state_attr('sensor.dreame_a2_mower_device_messages','items') or [] %}
          {% if items %}{% for m in items %}
          {{ '●' if m.unread else '○' }} **{{ m.title }}**
          {{ m.date }}{% if m.body %} · {{ m.body }}{% endif %}{% if m.link %} · [open]({{ m.link }}){% endif %}
          {% endfor %}{% else %}_No messages_{% endif %}
      - type: markdown
        title: Service messages
        content: >
          {% set items = state_attr('sensor.dreame_a2_mower_service_messages','items') or [] %}
          {% if items %}{% for m in items %}
          {{ '●' if m.unread else '○' }} **{{ m.title }}**
          {{ m.date }}{% if m.body %} · {{ m.body }}{% endif %}{% if m.link %} · [open]({{ m.link }}){% endif %}
          {% endfor %}{% else %}_No messages_{% endif %}
      - type: markdown
        title: Shared messages
        content: >
          {% set items = state_attr('sensor.dreame_a2_mower_shared_messages','items') or [] %}
          {% if items %}{% for m in items %}
          {{ '●' if m.unread else '○' }} **{{ m.title }}**
          {{ m.date }}{% if m.body %} · {{ m.body }}{% endif %}{% if m.link %} · [open]({{ m.link }}){% endif %}
          {% endfor %}{% else %}_No messages_{% endif %}
```

- [ ] **Step 2: Deploy + verify**

Back up the current dashboard, SCP the updated file to `/config/dashboards/mower/`, hard-refresh the browser, and confirm the Info tab shows the three cards (entity_ids must match what HA assigned — verify via Developer Tools → States that `sensor.dreame_a2_mower_device_messages` etc. exist; adjust slugs if HA appended `_2`).

---

## Task 10: Full verification + release + close the TODO

- [ ] **Step 1: Full suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/ -q`
Expected: all pass (no new failures).

- [ ] **Step 2: Move the resolved TODO to DONE.md**

Remove the "Probe `message-record/list` for the System/Sharing/Service/Activity tabs" item from `docs/TODO.md` and add a DONE.md entry at `/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/DONE.md` summarizing: endpoint mapped (v1, all tabs), Device/Service/Sharing lists now surfaced as sensors + an Info dashboard tab, System/marketing tab intentionally skipped.

- [ ] **Step 3: Commit + release**

```bash
git add docs/TODO.md
git commit -m "docs(todo): close message-record probe — Info messages tab shipped"
git push origin main
tools/release/release.sh
```

Expected: release script bumps the version, runs tests + `node --check`, tags, creates the GitHub Release (`--latest`, no prerelease), and refreshes HACS.

---

## Self-review notes

- **Spec coverage:** §1 fetchers → Task 3; §2 normalizer → Task 2; §3 sensors → Task 6; §4 state → Task 4; §5 sensors/recorder → Task 6; §6 cap → Task 1; §7 dashboard → Task 9; error handling → built into Tasks 3/5 (None-tolerant); testing → Tasks 2/3/5/6; share-capture open question → Task 7; done-when #7 (TODO→DONE) → Task 10. All covered.
- **Type consistency:** `Message`/`as_dict()`/`normalize_service|device|share`/`unread_count` defined in Task 2 and used identically in Tasks 5/6; `service_records` key added in Task 3 and read in Task 5; `_FIELD` names (`device_messages`/`service_messages`/`shared_messages`) match the MowerState fields (Task 4) and the sensor classes (Task 6).
- **Known adjustment points (verify against code, not guesses):** the coordinator's config-entry attribute (`self._entry` vs `self.config_entry`) and device-id attribute (`self._did`) in Task 5; the sensor base class + `unique_id`/registration wiring in Task 6. Each step says how to confirm before writing.
- **Placeholders:** none — all code blocks are concrete; the only deferred item is the share-messages field confirmation, which is an explicit capture task (Task 7), not a placeholder.
