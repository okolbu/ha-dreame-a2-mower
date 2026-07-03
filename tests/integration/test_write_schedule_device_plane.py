"""Task 5: write_schedule must use the SCHD*V3 device plane, not the KV path."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin
from custom_components.dreame_a2_mower.cloud_state import (
    ScheduleData,
    SchedulePlan,
    ScheduleSlot,
)


def _make_coord(rows, version=0):
    """Build a bare _WritesMixin instance wired with capture hooks.

    Returns (coord, captured, write_row, read_live). The test monkeypatches
    the module-level write_schedule_row / read_live_schedule with these.
    read_live returns the live-read shape {"d": rows, "v": version} — the
    write path now derives base_version from the live read's `v`, not from
    cloud_state (the KV/cloud_state version is a stale cache).
    """
    c = _WritesMixin()
    captured = {"row_writes": [], "kv_writes": []}

    def _write_row(send_action, **kw):
        captured["row_writes"].append(kw)

    def _read_live(send_action):
        return {"d": rows, "v": version}

    c._cloud = SimpleNamespace(
        action=lambda *a, **k: None,
        write_chunked_key=MagicMock(
            side_effect=lambda key, val: captured["kv_writes"].append(key) or (True, "")
        ),
    )
    c._chunked_write_lock = asyncio.Lock()
    c._refresh_cloud_state = AsyncMock()

    async def _exec(fn, *a, **k):
        return fn(*a, **k)

    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    return c, captured, _write_row, _read_live


@pytest.mark.asyncio
async def test_write_schedule_writes_only_changed_slot_via_device_plane(monkeypatch):
    import custom_components.dreame_a2_mower.coordinator._writes as W

    rows = [[0, 1, "Spr", "OLD"], [1, 0, "Aut", ""]]
    new_plan = SchedulePlan(
        time_min=780, weekday_mask=0b100, action_type=0, zone_id=None, extra_bytes=b""
    )
    new_slots = [
        ScheduleSlot(slot_id=0, name="Spr", raw_blob_b64="", plans=(new_plan,), mode=1)
    ]
    c, captured, write_row, read_live = _make_coord(rows, version=5)
    monkeypatch.setattr(W, "write_schedule_row", write_row, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", read_live, raising=False)
    c.cloud_state = SimpleNamespace(schedule=ScheduleData(version=99, slots=()))

    ok = await c.write_schedule(new_slots)

    assert ok.accepted is True
    assert captured["kv_writes"] == []  # KV path retired
    assert len(captured["row_writes"]) == 1  # only the changed slot 0
    w = captured["row_writes"][0]
    assert w["slot"] == 0
    assert w["enabled_array"] == [1, 0]  # slot0=1 (preserved), slot1=0 (preserved)
    assert w["version"] == 6  # base 5 + 1
    assert w["name"] == "Spr"
    assert isinstance(w["txn_id"], int) and w["txn_id"] > 0
    c._refresh_cloud_state.assert_awaited()


@pytest.mark.asyncio
async def test_write_schedule_escapes_ampersand_name(monkeypatch):
    """`&`-names round-trip via the wire `&amp;` convention.

    The device row carries `Spr &amp; Sum`; decode html.unescapes it to
    `Spr & Sum`. The write must re-escape so an unchanged slot is skipped
    (no perpetual rewrite / double-escape drift), and a real write sends the
    escaped form.
    """
    import custom_components.dreame_a2_mower.coordinator._writes as W
    from custom_components.dreame_a2_mower.protocol.schedule_encode import (
        encode_schedule_blob,
    )

    plan = SchedulePlan(
        time_min=780, weekday_mask=0b100, action_type=0, zone_id=None, extra_bytes=b""
    )
    blob = encode_schedule_blob((plan,))
    # Authoritative device row: name escaped, blob matches → must be skipped.
    rows = [[0, 1, "Spr &amp; Sum", blob]]
    # Slot carries the decoded (unescaped) name, as cloud_state would.
    slots = [
        ScheduleSlot(
            slot_id=0, name="Spr & Sum", raw_blob_b64="", plans=(plan,), mode=1
        )
    ]
    c, captured, write_row, read_live = _make_coord(rows, version=3)
    monkeypatch.setattr(W, "write_schedule_row", write_row, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", read_live, raising=False)
    c.cloud_state = SimpleNamespace(schedule=ScheduleData(version=3, slots=()))

    ok = await c.write_schedule(slots)
    assert ok.accepted is True
    assert captured["row_writes"] == []  # escaped-name compare → skipped

    # Now change the plan so it DOES write — name must go out escaped.
    plan2 = SchedulePlan(
        time_min=781, weekday_mask=0b100, action_type=0, zone_id=None, extra_bytes=b""
    )
    slots2 = [
        ScheduleSlot(
            slot_id=0, name="Spr & Sum", raw_blob_b64="", plans=(plan2,), mode=1
        )
    ]
    c2, captured2, write_row2, read_live2 = _make_coord(rows, version=3)
    monkeypatch.setattr(W, "write_schedule_row", write_row2, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", read_live2, raising=False)
    c2.cloud_state = SimpleNamespace(schedule=ScheduleData(version=3, slots=()))

    ok2 = await c2.write_schedule(slots2)
    assert ok2.accepted is True
    assert len(captured2["row_writes"]) == 1
    assert captured2["row_writes"][0]["name"] == "Spr &amp; Sum"


@pytest.mark.asyncio
async def test_write_schedule_skips_unchanged_slot(monkeypatch):
    """A slot whose re-encoded blob AND name match the authoritative row is skipped."""
    import custom_components.dreame_a2_mower.coordinator._writes as W
    from custom_components.dreame_a2_mower.protocol.schedule_encode import (
        encode_schedule_blob,
    )

    plan = SchedulePlan(
        time_min=780, weekday_mask=0b100, action_type=0, zone_id=None, extra_bytes=b""
    )
    same_blob = encode_schedule_blob((plan,))
    rows = [[0, 1, "Spr", same_blob]]
    slots = [
        ScheduleSlot(slot_id=0, name="Spr", raw_blob_b64="", plans=(plan,), mode=1)
    ]
    c, captured, write_row, read_live = _make_coord(rows, version=2)
    monkeypatch.setattr(W, "write_schedule_row", write_row, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", read_live, raising=False)
    c.cloud_state = SimpleNamespace(schedule=ScheduleData(version=2, slots=()))

    ok = await c.write_schedule(slots)

    assert ok.accepted is True
    assert captured["row_writes"] == []  # unchanged — no write, no version churn
    c._refresh_cloud_state.assert_awaited()


@pytest.mark.asyncio
async def test_write_schedule_preserves_other_season_enabled(monkeypatch):
    """Editing slot 1's plans while slot 1 is the active season must NOT flip
    the active season: SCHDSV3 s must be [slot0_enabled, slot1_enabled], not
    [thisslot_enabled, 0]."""
    import custom_components.dreame_a2_mower.coordinator._writes as W
    from custom_components.dreame_a2_mower.protocol.schedule_encode import (
        encode_schedule_blob,
    )

    # Live rows: slot0 OFF, slot1 ON.
    rows = [[0, 0, "Spr", "OLDSPR"], [1, 1, "Win", "OLDWIN"]]
    new_plan = SchedulePlan(
        time_min=600, weekday_mask=0b1, action_type=0, zone_id=None, extra_bytes=b""
    )
    new_slots = [
        ScheduleSlot(slot_id=1, name="Win", raw_blob_b64="", plans=(new_plan,), mode=1)
    ]
    c, captured, write_row, read_live = _make_coord(rows, version=7)
    monkeypatch.setattr(W, "write_schedule_row", write_row, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", read_live, raising=False)
    c.cloud_state = SimpleNamespace(schedule=ScheduleData(version=7, slots=()))

    ok = await c.write_schedule(new_slots)

    assert ok.accepted is True
    assert len(captured["row_writes"]) == 1
    assert captured["row_writes"][0]["slot"] == 1
    assert captured["row_writes"][0]["enabled_array"] == [0, 1]  # both seasons preserved


def _make_toggle_coord(rows, version):
    """Bare _WritesMixin with a captured SCHDSV3-only send path."""
    from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin
    c = _WritesMixin()
    captured = {"enabled_writes": []}

    def _write_enabled(send_action, *, version, enabled_array):
        captured["enabled_writes"].append({"version": version, "enabled": enabled_array})

    def _read_live(send_action):
        return {"d": rows, "v": version}

    c._cloud = SimpleNamespace(action=lambda *a, **k: None)
    c._chunked_write_lock = asyncio.Lock()
    c._refresh_cloud_state = AsyncMock()

    async def _exec(fn, *a, **k):
        return fn(*a, **k)

    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))
    return c, captured, _write_enabled, _read_live


@pytest.mark.asyncio
async def test_write_schedule_enabled_enable_makes_sole_active(monkeypatch):
    import custom_components.dreame_a2_mower.coordinator._writes as W
    rows = [[0, 1, "Spr", "B"], [1, 0, "Win", "B"]]  # Spr on
    c, captured, write_enabled, read_live = _make_toggle_coord(rows, version=99)
    monkeypatch.setattr(W, "write_schedule_enabled_state", write_enabled, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", read_live, raising=False)

    ok = await c.write_schedule_enabled(slot_id=1, enabled=True)

    assert ok.accepted is True
    assert captured["enabled_writes"] == [{"version": 99, "enabled": [0, 1]}]  # Win on, Spr off
    c._refresh_cloud_state.assert_awaited()


@pytest.mark.asyncio
async def test_write_schedule_enabled_disable_zeroes_slot(monkeypatch):
    import custom_components.dreame_a2_mower.coordinator._writes as W
    rows = [[0, 0, "Spr", "B"], [1, 1, "Win", "B"]]  # Win on
    c, captured, write_enabled, read_live = _make_toggle_coord(rows, version=42)
    monkeypatch.setattr(W, "write_schedule_enabled_state", write_enabled, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", read_live, raising=False)

    ok = await c.write_schedule_enabled(slot_id=1, enabled=False)

    assert ok.accepted is True
    assert captured["enabled_writes"] == [{"version": 42, "enabled": [0, 0]}]  # both off


@pytest.mark.asyncio
async def test_write_schedule_enabled_falls_back_to_cloud_state_when_live_none(monkeypatch):
    """When the live read is unavailable, the toggle uses cloud_state.schedule
    (version + per-slot mode). Disabling slot 0 while slot 1 is on must preserve
    slot 1 (proves the fallback reads each slot's mode, not [0,0])."""
    import custom_components.dreame_a2_mower.coordinator._writes as W
    from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin

    captured = {"enabled_writes": []}

    def _write_enabled(send_action, *, version, enabled_array):
        captured["enabled_writes"].append({"version": version, "enabled": enabled_array})

    monkeypatch.setattr(W, "write_schedule_enabled_state", _write_enabled, raising=False)
    monkeypatch.setattr(W, "read_live_schedule", lambda send_action: None, raising=False)

    c = _WritesMixin()
    c._cloud = SimpleNamespace(action=lambda *a, **k: None)
    c._chunked_write_lock = asyncio.Lock()
    c._refresh_cloud_state = AsyncMock()
    c.cloud_state = SimpleNamespace(
        schedule=ScheduleData(
            version=31,
            slots=(
                ScheduleSlot(slot_id=0, name="Spr", raw_blob_b64="", plans=(), mode=0),
                ScheduleSlot(slot_id=1, name="Win", raw_blob_b64="", plans=(), mode=1),
            ),
        )
    )

    async def _exec(fn, *a, **k):
        return fn(*a, **k)
    c.hass = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=_exec))

    ok = await c.write_schedule_enabled(slot_id=0, enabled=False)

    assert ok.accepted is True
    # slot1 stays on (mode=1 read from cloud_state), slot0 forced off.
    assert captured["enabled_writes"] == [{"version": 31, "enabled": [0, 1]}]
