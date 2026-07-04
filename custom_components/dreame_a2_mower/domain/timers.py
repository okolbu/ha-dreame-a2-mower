"""Self-cleaning delayed-timer registry (P2-inherit, refactor-v2 P3.8; relocated
from ``coordinator/_managed_timers.py`` to the domain layer in P3.9d — its only
callers are now domain services, so a domain home removes the domain→coordinator
import edge).

``async_call_later`` returns a canceller. Routing that canceller straight
through ``entry.async_on_unload`` (the old T3-8 pattern) never REMOVES it after
the timer fires, so a hot path that schedules timers on every call —
``domain/writes/map_edit.py:edit_map`` (3 staggered re-fetches per map-edit) and
the post-session OSS gallery refresh in ``domain/media/gallery.py`` (one per
finalize) — grows the config-entry's unload-listener list without bound over the
entry's lifetime. The P2.8 final review flagged this as a new listener-growth
class.

``schedule_self_cleaning`` fixes it with a bounded per-owner registry:

* the timer removes ITSELF from the registry when it fires, so the set only
  ever holds not-yet-fired timers;
* exactly ONE ``entry.async_on_unload`` hook is registered per owner (the first
  time), and it cancels every outstanding timer at unload — so the unload list
  gains a single entry regardless of how many timers are scheduled.

The caller passes its own module-local ``async_call_later`` reference as
``scheduler`` so existing test monkeypatches (which patch the name in the
caller's module) keep intercepting.
"""
from __future__ import annotations

from typing import Any, Callable


def schedule_self_cleaning(
    owner: Any,
    scheduler: Callable[[Any, float, Callable], Callable[[], None]],
    delay: float,
    action: Callable[[Any], Any],
) -> Callable[[], None]:
    """Schedule ``action`` after ``delay`` with a self-cleaning canceller.

    ``scheduler`` is ``async_call_later`` (passed by the caller so a monkeypatch
    of the name in the caller's module still applies). ``action(now)`` is the
    work to run; its return value is propagated (tests fire the wrapped callback
    and await the returned coroutine). Returns the underlying canceller.
    """
    registry: set = owner.__dict__.setdefault("_managed_cancellers", set())
    box: dict[str, Callable[[], None]] = {}

    def _fire(now: Any) -> Any:
        # Self-clean: drop this (now-fired) timer from the live registry so it
        # can't accumulate over repeated scheduling.
        registry.discard(box.get("cancel"))
        return action(now)

    cancel = scheduler(owner.hass, delay, _fire)
    box["cancel"] = cancel
    registry.add(cancel)

    entry = getattr(owner, "entry", None)
    if entry is not None and not owner.__dict__.get("_managed_unload_registered"):
        def _cancel_all() -> None:
            for canceller in list(registry):
                canceller()
            registry.clear()

        entry.async_on_unload(_cancel_all)
        owner.__dict__["_managed_unload_registered"] = True

    return cancel
