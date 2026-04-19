"""Dedupe novelty detector for unknown MQTT fields.

Background
----------
The g2408 emits telemetry at 5 s intervals during mowing. If an unmapped
`(siid, piid)` pair or an unfamiliar `method` were logged on every arrival,
the log would be swamped within minutes. This helper records the first
observation of each distinct key and reports novelty only on that first
call — any subsequent observation returns ``False`` so the caller can
skip logging.

The watchdog holds no state beyond per-process in-memory sets; a HA
restart resets it, which is exactly what we want — a restart may bring a
new integration version with different mappings, so re-flagging is
useful.

Thread-safety: the integration's MQTT callback is invoked on the paho
network thread, so every mutation happens on one thread. No locking.
"""

from __future__ import annotations

from typing import Iterable


class UnknownFieldWatchdog:
    """Track first-observations of unexpected MQTT fields.

    Each ``saw_*`` method returns ``True`` the first time its argument
    tuple is observed and ``False`` thereafter — callers use the bool to
    gate an ``_LOGGER.info(...)`` call so novelty is reported at most
    once per key.
    """

    def __init__(self) -> None:
        self._seen_properties: set[tuple[int, int]] = set()
        self._seen_methods: set[str] = set()
        self._seen_event_piids: dict[tuple[int, int], set[int]] = {}

    def saw_property(self, siid: int, piid: int) -> bool:
        key = (int(siid), int(piid))
        if key in self._seen_properties:
            return False
        self._seen_properties.add(key)
        return True

    def saw_method(self, method: str) -> bool:
        key = method if method is not None else ""
        if key in self._seen_methods:
            return False
        self._seen_methods.add(key)
        return True

    def saw_event(self, siid: int, eiid: int, piids: Iterable[int]) -> bool:
        """Return True if any piid in ``piids`` is new for this (siid, eiid).

        The first call for any (siid, eiid) marks every supplied piid as
        seen and returns True. Later calls only return True when they
        introduce a piid not previously recorded for that (siid, eiid).
        """
        key = (int(siid), int(eiid))
        piid_set = {int(p) for p in piids}
        known = self._seen_event_piids.get(key)
        if known is None:
            self._seen_event_piids[key] = piid_set
            return True
        new_piids = piid_set - known
        if not new_piids:
            return False
        known.update(new_piids)
        return True
