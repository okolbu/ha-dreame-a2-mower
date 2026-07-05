"""Coordinator test factory — construct the REAL coordinator in tests.

P3 Task 1 (R-16, T7-7): before this factory, every coordinator-constructing
test bypassed ``__init__`` via ``object.__new__`` — the constructor that owns
ALL shared coordinator state (`_CoreMixin.__init__`, the sole ``self._foo``
owner per CLAUDE.md) had zero test coverage. ``make_coordinator`` runs the
real ``DreameA2MowerCoordinator.__init__`` against a faithful fake hass/entry;
transports are mocked at the CLIENT boundary only (pass ``cloud=`` / ``mqtt=``
instances, or monkeypatch ``DreameA2CloudClient`` / ``DreameA2MqttClient`` in
``coordinator._core``) — never by skipping construction.

The census ratchet in ``tests/audit/test_no_new_coordinator_bypass.py`` pins
the remaining legacy bypass sites; new tests MUST use this factory.

Notes for factory users
-----------------------
- ``__init__`` needs: ``hass.config.path(...)`` (real writable dirs — the
  LiDAR archive root is mkdir'd inside ``__init__``), ``entry.data`` with
  username/password/country, ``entry.options`` (a dict), ``entry.entry_id``.
  It does NOT construct the cloud/MQTT clients — those are deferred to
  ``_async_update_data``'s first-boot block (``_init_cloud`` / ``_init_mqtt``),
  so pure-construction tests need no client mocks at all.
- Every ``make_coordinator`` call gets its own temp config dir (pass
  ``base_dir=tmp_path`` to use pytest's fixture instead).
- ``hass.async_add_executor_job`` is an ``AsyncMock`` with an inline-executing
  ``side_effect`` so barrier-executor tests can swap ``.side_effect`` (the
  established pattern in tests/coordinator/test_finalize_interleavings.py).
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.dreame_a2_mower.const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator


class FakeConfigEntry:
    """Faithful-minimal ConfigEntry double.

    Mirrors the real-HA surface the integration touches: ``data`` /
    ``options`` / ``entry_id``, ``add_update_listener`` (returns a working
    remove callback), and ``async_on_unload`` registration. ``run_on_unload``
    mirrors HA's ``_async_process_on_unload`` (invoked by the config-entry
    manager after a successful unload — LIFO, like real HA pops from the end).
    """

    def __init__(
        self,
        *,
        entry_id: str = "test-entry",
        data: dict | None = None,
        options: dict | None = None,
    ) -> None:
        self.entry_id = entry_id
        self.data = {
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "hunter2",
            CONF_COUNTRY: "eu",
            **(data or {}),
        }
        self.options: dict = dict(options or {})
        self._on_unload: list = []
        self.update_listeners: list = []
        self._background_tasks: set = set()

    def async_on_unload(self, func) -> None:
        """Register a callback to run when the entry is unloaded.

        Returns None — matching real HA's ConfigEntry.async_on_unload (it
        registers the callback and returns nothing; callers must not rely on
        a passthrough return value).
        """
        self._on_unload.append(func)

    def add_update_listener(self, listener):
        """Register an options-update listener; returns its remover."""
        self.update_listeners.append(listener)

        def _remove() -> None:
            if listener in self.update_listeners:
                self.update_listeners.remove(listener)

        return _remove

    def async_create_background_task(self, hass, target, name, eager_start=True):
        """Mirror ConfigEntry.async_create_background_task: schedule *target*
        on the loop, track it, and auto-discard on completion. HA cancels
        these on unload — ``run_on_unload`` does the same below."""
        task = hass.async_create_task(target)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def run_on_unload(self) -> None:
        """Run + clear the on-unload callbacks (real HA: after unload OK) and
        cancel any still-pending background tasks (real HA cancels these)."""
        for task in list(self._background_tasks):
            task.cancel()
        self._background_tasks.clear()
        while self._on_unload:
            self._on_unload.pop()()


class FakeServiceRegistry:
    """Dict-backed hass.services with real register/remove semantics, so a
    setup → unload → re-setup cycle exercises the actual idempotency branch
    in ``async_setup_entry`` (``has_service`` gate)."""

    def __init__(self) -> None:
        self._services: dict[tuple[str, str], object] = {}
        self.async_call = AsyncMock()

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self._services

    def async_register(self, domain, service, handler, schema=None) -> None:
        self._services[(domain, service)] = handler

    def async_remove(self, domain, service) -> None:
        self._services.pop((domain, service), None)


class FakeConfigEntries:
    """Platform-forward fake (T7-20): records forwards/unloads, returns True.

    Deliberately does NOT import or run the platform modules — the three
    lifecycle tests it exists for (per-timer cancel identity, reload
    idempotency, no-thread-leak-on-reload) assert on coordinator/transport/
    timer wiring, not on entity construction.
    """

    def __init__(self) -> None:
        self.forward_calls: list[tuple] = []
        self.unload_calls: list[tuple] = []
        self.unload_result: bool = True

    async def async_forward_entry_setups(self, entry, platforms) -> None:
        self.forward_calls.append((entry, tuple(platforms)))

    async def async_unload_platforms(self, entry, platforms) -> bool:
        self.unload_calls.append((entry, tuple(platforms)))
        return self.unload_result


def make_hass(base_dir: str | Path | None = None):
    """Fake HomeAssistant good enough for coordinator __init__ + lifecycle.

    ``config.path(*parts)`` maps into a per-call temp dir (real, writable —
    the coordinator mkdirs archive roots during __init__).
    """
    base = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="dreame-hass-"))
    base.mkdir(parents=True, exist_ok=True)

    hass = SimpleNamespace()
    hass.data = {}
    hass.config = SimpleNamespace(path=lambda *parts: str(base.joinpath(*parts)))

    async def _inline_executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=_inline_executor)
    hass.async_create_task = MagicMock(
        side_effect=lambda coro, *a, **k: asyncio.ensure_future(coro)
    )
    # Paho/MQTT callbacks hop to the loop via call_soon_threadsafe — run inline.
    hass.loop = SimpleNamespace(call_soon_threadsafe=lambda fn, *a: fn(*a))
    hass.bus = MagicMock()
    hass.http = MagicMock()
    hass.services = FakeServiceRegistry()
    hass.config_entries = FakeConfigEntries()
    return hass


def make_entry(**kwargs) -> FakeConfigEntry:
    """Shorthand for FakeConfigEntry(...)."""
    return FakeConfigEntry(**kwargs)


def make_coordinator(
    *,
    cls: type = DreameA2MowerCoordinator,
    hass=None,
    entry: FakeConfigEntry | None = None,
    base_dir: str | Path | None = None,
    wifi_index: list | None = None,
    cloud=None,
    mqtt=None,
    data=None,
    **overrides,
):
    """Build a coordinator through the REAL ``__init__`` (never __new__).

    - ``cls`` may be a test subclass of DreameA2MowerCoordinator (e.g. a
      spy subclass) — it still constructs through the real MRO.
    - ``cloud`` / ``mqtt``: client-boundary doubles attached as ``_cloud`` /
      ``_mqtt`` AFTER construction (production attaches them the same way,
      from ``_init_cloud`` / ``_init_mqtt``).
    - ``data``: replaces the freshly-seeded empty MowerState.
    - ``**overrides``: setattr'd last, for per-test knobs on REAL attributes
      seeded by __init__ (e.g. ``_active_map_id=0``). Prefer overriding an
      attribute __init__ created over inventing new ones.
    """
    if hass is None:
        hass = make_hass(base_dir)
    if entry is None:
        entry = make_entry()
    coord = cls(hass, entry, wifi_index=wifi_index if wifi_index is not None else [])
    if cloud is not None:
        coord._cloud = cloud
    if mqtt is not None:
        coord._mqtt = mqtt
    if data is not None:
        coord.data = data
    for key, value in overrides.items():
        setattr(coord, key, value)
    return coord
