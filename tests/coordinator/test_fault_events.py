"""Tests for _DeviceSyncMixin._fire_fault_delta — fires fault_detected /
fault_cleared lifecycle events when snapshot.errors changes.

Uses the same lightweight bound-mixin harness as test_base_render_on_activity
and test_inject_live_map_meta: a SimpleNamespace carrying only the attrs the
method needs, with the mixin methods bound via types.MethodType.
"""
from __future__ import annotations

import types

from custom_components.dreame_a2_mower.coordinator._device_sync import _DeviceSyncMixin
from custom_components.dreame_a2_mower.const import (
    EVENT_TYPE_FAULT_DETECTED,
    EVENT_TYPE_FAULT_CLEARED,
)
from custom_components.dreame_a2_mower.mower import fault_catalog as fc


class _RecordingLifecycle:
    """Minimal stand-in for the lifecycle EventEntity.

    Records every trigger(event_type, data) call so tests can assert on
    which events were fired and with what payloads.
    """

    def __init__(self):
        self.fired: list[tuple[str, dict]] = []

    def trigger(self, event_type: str, data: dict | None = None) -> None:
        self.fired.append((event_type, data or {}))


def _make_coord() -> types.SimpleNamespace:
    """Build the minimal namespace that _fire_fault_delta needs.

    Required by _fire_lifecycle:
      - self._lifecycle_event  (set by register_event_entities)
    _fire_fault_delta also calls _post_fault_notice / _dismiss_fault_notice;
    these are bound here so they no-op gracefully when hass/entry are absent.
    """
    coord = types.SimpleNamespace()
    coord._lifecycle_event = None  # pre-set so _fire_lifecycle guard works
    coord._notification_event = None
    coord.hass = None
    coord.entry = None

    # Bind the methods from the mixin.
    for name in (
        "_fire_lifecycle",
        "_fire_fault_delta",
        "_fire_local_novel_s2p2",
        "_fault_notification_id",
        "_post_fault_notice",
        "_dismiss_fault_notice",
        "register_event_entities",
    ):
        setattr(
            coord,
            name,
            types.MethodType(getattr(_DeviceSyncMixin, name), coord),
        )
    return coord


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fault_delta_fires_detected_and_cleared():
    """New fault → fault_detected; fault gone → fault_cleared."""
    coord = _make_coord()
    lc = _RecordingLifecycle()
    coord.register_event_entities(lifecycle=lc, notification=None)

    # Fault code 5 appears.
    coord._fire_fault_delta(frozenset(), frozenset({5}), now_unix=1000)
    # Fault code 5 is cleared.
    coord._fire_fault_delta(frozenset({5}), frozenset(), now_unix=1100)

    types_fired = [t for t, _ in lc.fired]
    assert EVENT_TYPE_FAULT_DETECTED in types_fired
    assert EVENT_TYPE_FAULT_CLEARED in types_fired

    detected = next(d for t, d in lc.fired if t == EVENT_TYPE_FAULT_DETECTED)
    assert detected["code"] == 5
    assert detected["description"] == fc.fault_text(5, "en")
    assert detected["at_unix"] == 1000

    cleared = next(d for t, d in lc.fired if t == EVENT_TYPE_FAULT_CLEARED)
    assert cleared["code"] == 5
    assert cleared["at_unix"] == 1100


def test_fault_delta_noop_when_unchanged():
    """No event is fired when prev == new."""
    coord = _make_coord()
    lc = _RecordingLifecycle()
    coord.register_event_entities(lifecycle=lc, notification=None)

    coord._fire_fault_delta(frozenset({5}), frozenset({5}), now_unix=1000)
    assert lc.fired == []


def test_fault_delta_noop_when_entity_unregistered():
    """When lifecycle entity is None, _fire_lifecycle no-ops gracefully."""
    coord = _make_coord()
    # _lifecycle_event stays None — no register_event_entities call.

    # Should not raise.
    coord._fire_fault_delta(frozenset(), frozenset({5}), now_unix=1000)


def test_fault_delta_fires_multiple_codes_sorted():
    """Multiple new faults fire in sorted code order."""
    coord = _make_coord()
    lc = _RecordingLifecycle()
    coord.register_event_entities(lifecycle=lc, notification=None)

    coord._fire_fault_delta(frozenset(), frozenset({10, 5, 3}), now_unix=2000)

    assert len(lc.fired) == 3
    codes = [d["code"] for _, d in lc.fired]
    assert codes == sorted(codes)


def test_fault_delta_partial_change():
    """One fault added, one retained, one cleared."""
    coord = _make_coord()
    lc = _RecordingLifecycle()
    coord.register_event_entities(lifecycle=lc, notification=None)

    # prev={5, 10}, new={10, 20} → detected=20, cleared=5
    coord._fire_fault_delta(frozenset({5, 10}), frozenset({10, 20}), now_unix=3000)

    types_fired = [t for t, _ in lc.fired]
    assert types_fired.count(EVENT_TYPE_FAULT_DETECTED) == 1
    assert types_fired.count(EVENT_TYPE_FAULT_CLEARED) == 1

    detected = next(d for t, d in lc.fired if t == EVENT_TYPE_FAULT_DETECTED)
    assert detected["code"] == 20

    cleared = next(d for t, d in lc.fired if t == EVENT_TYPE_FAULT_CLEARED)
    assert cleared["code"] == 5


# ---------------------------------------------------------------------------
# Task 8: _fire_local_novel_s2p2 tests
# ---------------------------------------------------------------------------


class _RecordingNotification:
    """Minimal stand-in for the notification EventEntity.

    Records every trigger(event_type, data) call so tests can assert on
    which notification events were fired and with what payloads.
    """

    def __init__(self):
        self.fired: list[tuple[str, dict]] = []

    def trigger(self, event_type: str, data: dict | None = None) -> None:
        self.fired.append((event_type, data or {}))


def _make_coord_with_notification() -> tuple[types.SimpleNamespace, _RecordingNotification]:
    """Build the minimal namespace that _fire_local_novel_s2p2 needs,
    wired with both a lifecycle and notification recording entity.

    Returns (coord, notification_recorder).
    """
    coord = types.SimpleNamespace()
    coord._lifecycle_event = None
    coord._notification_event = None

    # Bind the methods from the mixin that are needed.
    for name in (
        "_fire_lifecycle",
        "_fire_fault_delta",
        "_fire_local_novel_s2p2",
        "register_event_entities",
    ):
        setattr(
            coord,
            name,
            types.MethodType(getattr(_DeviceSyncMixin, name), coord),
        )

    lc = _RecordingLifecycle()
    notif = _RecordingNotification()
    coord.register_event_entities(lifecycle=lc, notification=notif)
    return coord, notif


def test_unknown_s2p2_fires_local_notification():
    """An unknown s2p2 code (200, not in S2P2_EVENT_TYPES) fires
    a local 'unknown_s2p2' notification with code and source='local'."""
    coord, notif = _make_coord_with_notification()

    # 200 is not in S2P2_EVENT_TYPES
    coord._fire_local_novel_s2p2(code=200, now_unix=1000)

    assert any(t == "unknown_s2p2" for t, _ in notif.fired), (
        f"expected 'unknown_s2p2' in fired events, got: {[t for t, _ in notif.fired]}"
    )
    _, data = next((t, d) for t, d in notif.fired if t == "unknown_s2p2")
    assert data["code"] == 200
    assert data["source"] == "local"


def test_unknown_s2p2_noop_when_entity_unregistered():
    """When notification entity is None, _fire_local_novel_s2p2 no-ops gracefully."""
    coord = _make_coord()
    # _notification_event stays None — no notification recorder registered.
    # Should not raise.
    coord._fire_local_novel_s2p2(code=200, now_unix=1000)


def test_unknown_s2p2_includes_text_and_siid_piid():
    """The fired payload includes a human-readable text, siid=2, piid=2."""
    coord, notif = _make_coord_with_notification()

    coord._fire_local_novel_s2p2(code=42, now_unix=2000)

    assert len(notif.fired) == 1
    _, data = notif.fired[0]
    assert "text" in data
    assert data["siid"] == 2
    assert data["piid"] == 2


def test_unknown_s2p2_fired_at_matches_now_unix():
    """fired_at in the payload equals the now_unix passed in."""
    coord, notif = _make_coord_with_notification()

    coord._fire_local_novel_s2p2(code=200, now_unix=1000)

    assert len(notif.fired) == 1
    _, data = notif.fired[0]
    assert data["fired_at"] == 1000


def test_s2p2_event_types_gate_semantics():
    from custom_components.dreame_a2_mower.mower.error_codes import S2P2_EVENT_TYPES
    known = next(iter(S2P2_EVENT_TYPES))
    assert S2P2_EVENT_TYPES.get(known) is not None  # known code → gate does NOT fire local entry
    assert S2P2_EVENT_TYPES.get(9999) is None       # unknown code → gate fires local entry


# ---------------------------------------------------------------------------
# Task 4 (P3a): _fire_notification carries tier/category/severity
# ---------------------------------------------------------------------------


def _make_coord_with_fire_notification() -> tuple[types.SimpleNamespace, _RecordingNotification]:
    """Build the minimal namespace that _fire_notification needs.

    Extends _make_coord_with_notification() by also binding _fire_notification
    (which is the method under test in Task 4).  Returns (coord, notif_recorder).
    """
    coord = types.SimpleNamespace()
    coord._lifecycle_event = None
    coord._notification_event = None
    # _last_notification is set by _fire_notification; pre-seed to None.
    coord._last_notification = None

    for name in (
        "_fire_lifecycle",
        "_fire_fault_delta",
        "_fire_local_novel_s2p2",
        "_fire_notification",
        "register_event_entities",
    ):
        setattr(
            coord,
            name,
            types.MethodType(getattr(_DeviceSyncMixin, name), coord),
        )

    lc = _RecordingLifecycle()
    notif = _RecordingNotification()
    coord.register_event_entities(lifecycle=lc, notification=notif)
    return coord, notif


def test_fire_notification_payload_carries_tier_category_severity_for_known_code():
    """code=27 → tier/category/severity populated in fired payload.

    NOTE: _RecordingNotification.trigger does NOT strip None-valued keys —
    it stores data as-is.  So for a known code (27 → tier="attention") we
    assert the values are the catalog-derived strings, not absent.
    """
    coord, notif = _make_coord_with_fire_notification()

    coord._fire_notification(
        event_type="human_detected",
        text="A person was detected",
        code=27,
        siid=2,
        piid=2,
        send_time=None,
        message_id="m1",
        now_unix=0,
    )

    assert len(notif.fired) == 1
    event_type_fired, payload = notif.fired[0]
    assert event_type_fired == "human_detected"
    assert payload["tier"] == "attention"
    assert payload["category"] == "FAULT"
    assert payload["severity"] == "work_message"


def test_fire_notification_payload_tier_is_none_for_unknown_code():
    """code=9999 → catalog returns None for tier/category/severity.

    NOTE: _RecordingNotification.trigger does NOT strip None-valued keys —
    it stores data as-is (unlike the real EventEntity which drops None keys).
    So we assert payload.get("tier") is None rather than "tier" not in payload.
    """
    coord, notif = _make_coord_with_fire_notification()

    coord._fire_notification(
        event_type="unknown_s2p2",
        text="x",
        code=9999,
        siid=2,
        piid=2,
        send_time=None,
        message_id=None,
        now_unix=0,
    )

    assert len(notif.fired) == 1
    _, payload = notif.fired[0]
    # The recording entity does NOT strip None keys; assert None not absent.
    assert payload.get("tier") is None
    assert payload.get("category") is None
    assert payload.get("severity") is None


# ---------------------------------------------------------------------------
# P3b Task 1: persistent_notification for error-tier faults
# ---------------------------------------------------------------------------

import sys


class _FakePN:
    """Records persistent_notification.async_create/async_dismiss calls."""
    def __init__(self):
        self.created: list[dict] = []
        self.dismissed: list[str] = []

    def async_create(self, hass, *, message, title, notification_id):
        self.created.append(
            {"message": message, "title": title, "notification_id": notification_id}
        )

    def async_dismiss(self, hass, *, notification_id):
        self.dismissed.append(notification_id)


def _install_fake_pn(monkeypatch) -> _FakePN:
    fake = _FakePN()
    ha = sys.modules.get("homeassistant") or types.ModuleType("homeassistant")
    comp = sys.modules.get("homeassistant.components") or types.ModuleType(
        "homeassistant.components"
    )
    monkeypatch.setitem(sys.modules, "homeassistant", ha)
    monkeypatch.setitem(sys.modules, "homeassistant.components", comp)
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.persistent_notification", fake
    )
    monkeypatch.setattr(comp, "persistent_notification", fake, raising=False)
    return fake


def _make_coord_with_notice() -> types.SimpleNamespace:
    coord = _make_coord()
    coord.entry = types.SimpleNamespace(entry_id="e1")
    coord.hass = types.SimpleNamespace(config=types.SimpleNamespace(language="en"))
    # The notice helpers read self._EMERGENCY_STOP_CODE (a class attr on the real
    # coordinator); the SimpleNamespace stub must carry it explicitly.
    coord._EMERGENCY_STOP_CODE = _DeviceSyncMixin._EMERGENCY_STOP_CODE
    for name in ("_fault_notification_id", "_post_fault_notice", "_dismiss_fault_notice"):
        setattr(coord, name, types.MethodType(getattr(_DeviceSyncMixin, name), coord))
    return coord


def test_error_fault_posts_persistent_notice_on_detect(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_notice()
    coord._fire_fault_delta(frozenset(), frozenset({7}), now_unix=1000)  # 7 = cutter (error)
    assert len(fake.created) == 1
    n = fake.created[0]
    assert n["notification_id"] == "dreame_a2_mower_fault_7_e1"
    assert fc.fault_text(7, "en") in n["title"]
    assert n["message"] == (fc.fault_detail(7, "en") or fc.fault_text(7, "en"))
    assert fake.dismissed == []


def test_error_fault_dismisses_persistent_notice_on_clear(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_notice()
    coord._fire_fault_delta(frozenset({7}), frozenset(), now_unix=1100)
    assert fake.dismissed == ["dreame_a2_mower_fault_7_e1"]
    assert fake.created == []


def test_emergency_stop_code_excluded_from_fault_notice(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_notice()
    coord._fire_fault_delta(frozenset(), frozenset({23}), now_unix=1000)
    coord._fire_fault_delta(frozenset({23}), frozenset(), now_unix=1100)
    assert fake.created == [] and fake.dismissed == []  # PIN handler owns code 23


def test_fault_notice_body_non_empty_for_every_error_code(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_notice()
    for code in sorted(fc.error_tier_codes("iot")):
        if code == 23:
            continue
        fake.created.clear()
        coord._fire_fault_delta(frozenset(), frozenset({code}), now_unix=1)
        assert fake.created, f"no notice for error code {code}"
        assert fake.created[0]["message"], f"empty notice body for code {code}"


def test_fault_notice_localized(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_notice()
    coord.hass.config.language = "nb"
    code = 7  # nb != en for code 7 (verified via fault_catalog)
    coord._fire_fault_delta(frozenset(), frozenset({code}), now_unix=1)
    assert fc.fault_text(code, "nb") in fake.created[0]["title"]
    assert fc.fault_text(code, "nb") != fc.fault_text(code, "en")  # guards meaningfulness


def test_fault_notice_failure_does_not_break_delta(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    def _boom(*a, **k):
        raise RuntimeError("pn down")
    fake.async_create = _boom
    coord = _make_coord_with_notice()
    lc = _RecordingLifecycle()
    coord._lifecycle_event = lc  # harness pre-sets this; assign our recorder
    coord._fire_fault_delta(frozenset(), frozenset({7}), now_unix=1)
    assert any(et == EVENT_TYPE_FAULT_DETECTED for et, _ in lc.fired)


def test_only_error_tier_latches_so_only_error_tier_persists():
    """Persistent notices ride snapshot.errors, which latches ONLY error-tier
    codes (is_fault ⟺ fault_tier=='error'). This pins the invariant so a future
    change that latches attention/alert codes can't silently start persisting them."""
    from custom_components.dreame_a2_mower.mower.error_codes import is_fault
    for code in fc.known_codes("iot"):
        tier = fc.fault_tier(code)
        assert is_fault(code) == (tier == "error"), (
            f"code {code} tier={tier} but is_fault={is_fault(code)}"
        )
    # attention exemplars are NOT error-tier (so never latched/persisted):
    for attn in (28, 30):  # blade_loss, maintain_loss
        if attn in fc.known_codes("iot"):
            assert fc.fault_tier(attn) == "attention"
            assert not is_fault(attn)


# ---------------------------------------------------------------------------
# P3b restart re-post: _repost_active_fault_notices
# ---------------------------------------------------------------------------


def _make_coord_with_repost(errors) -> types.SimpleNamespace:
    coord = _make_coord_with_notice()  # has hass, entry, _EMERGENCY_STOP_CODE, notice methods
    coord.state_machine = types.SimpleNamespace(
        snapshot=lambda: types.SimpleNamespace(errors=frozenset(errors))
    )
    coord._repost_active_fault_notices = types.MethodType(
        _DeviceSyncMixin._repost_active_fault_notices, coord
    )
    return coord


def test_repost_active_fault_notices_reposts_each_error(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_repost({7, 9})
    lc = _RecordingLifecycle()
    coord._lifecycle_event = lc
    coord._repost_active_fault_notices()
    ids = {n["notification_id"] for n in fake.created}
    assert ids == {"dreame_a2_mower_fault_7_e1", "dreame_a2_mower_fault_9_e1"}
    # NO spurious fault_detected lifecycle events
    assert lc.fired == []


def test_repost_skips_emergency_stop_code_23(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_repost({23, 7})
    coord._repost_active_fault_notices()
    ids = {n["notification_id"] for n in fake.created}
    assert ids == {"dreame_a2_mower_fault_7_e1"}  # 23 skipped by _post_fault_notice


def test_repost_empty_errors_is_noop(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_repost(set())
    coord._repost_active_fault_notices()
    assert fake.created == []


def test_repost_noop_without_hass_or_entry(monkeypatch):
    fake = _install_fake_pn(monkeypatch)
    coord = _make_coord_with_repost({7})
    coord.hass = None  # missing hass → no-op, no crash
    coord._repost_active_fault_notices()
    assert fake.created == []
