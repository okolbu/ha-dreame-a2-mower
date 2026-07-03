"""Census ratchet: no NEW coordinator-construction bypasses (P3 Task 1, R-16).

T7-7: the real ``DreameA2MowerCoordinator.__init__`` never executed anywhere
in the suite — every coordinator-building test bypassed it (``object.__new__``
and friends), so the constructor owning ALL shared coordinator state had zero
coverage, and tests hand-seeded whichever attributes they remembered.

New tests MUST build coordinators via ``tests/factories.py:make_coordinator``
(real ``__init__``; transports mocked at the client boundary). The legacy
bypass sites migrate opportunistically as later P3 tasks touch their files;
this gate pins the census so the count can only ever DECREASE.

When you migrate a file, re-run this test: it fails with the new (lower)
count — update ``BYPASS_BASELINE`` downward to match. It must never go up.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent

# Every spelling of "construct the coordinator without running __init__"
# observed in the suite (grep census 2026-07-04). `cls.__new__(cls)` is NOT
# included as a pattern because it is used by non-coordinator helpers too;
# the two coordinator files that used it are pilot-migrated in this task.
#
# Constructing ANY of the coordinator's concern mixins via __new__ is the same
# bypass class (each mixin is a facet of the same object; a test that skips
# _WritesMixin.__init__ skips _CoreMixin.__init__ just as much). The mixin
# names are ENUMERATED, not matched with a generic `_\w+Mixin.__new__`, on
# purpose: cloud_client's `_FetchersMixin.__new__` (test_messages_refresh.py:16)
# is an unrelated non-coordinator helper and must NOT be swept in. Source of
# the roster: grep `class _*Mixin` in custom_components/.../coordinator/.
_COORD_MIXINS = (
    "_CloudStateMixin",
    "_CoreMixin",
    "_DeviceSyncMixin",
    "_LidarOssMixin",
    "_MqttHandlersMixin",
    "_NotificationsMixin",
    "_RefreshersMixin",
    "_RenderingMixin",
    "_SessionMixin",
    "_WifiArchiveMixin",
    "_WritesMixin",
)
_BYPASS_PATTERNS = (
    re.compile(r"object\.__new__\(\s*DreameA2MowerCoordinator\s*\)"),
    re.compile(r"DreameA2MowerCoordinator\.__new__"),
    re.compile(r"\b(?:" + "|".join(_COORD_MIXINS) + r")\.__new__"),
    re.compile(r"object\.__new__\(\s*coord_klass\s*\)"),
)

# Ratchet baseline — the total bypass-occurrence count across tests/.
# P3 Task 1 pin. ONLY update DOWNWARD.
BYPASS_BASELINE = 86


def _census() -> tuple[int, dict[str, int]]:
    per_file: dict[str, int] = {}
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        n = sum(len(pat.findall(text)) for pat in _BYPASS_PATTERNS)
        if n:
            per_file[str(path.relative_to(TESTS_DIR))] = n
    return sum(per_file.values()), per_file


def test_no_new_coordinator_bypass():
    total, per_file = _census()
    listing = "\n".join(f"  {f}: {n}" for f, n in sorted(per_file.items()))
    assert total <= BYPASS_BASELINE, (
        f"Coordinator-construction bypass census GREW: {total} > baseline "
        f"{BYPASS_BASELINE}.\nNew tests must use tests/factories.py:"
        f"make_coordinator (real __init__, client-boundary mocks) instead of "
        f"object.__new__(DreameA2MowerCoordinator).\nCurrent sites:\n{listing}"
    )
    assert total == BYPASS_BASELINE, (
        f"Bypass census DECREASED: {total} < recorded baseline "
        f"{BYPASS_BASELINE} — nice. Ratchet it: set BYPASS_BASELINE = {total} "
        f"in {__file__} so the gain is locked in."
    )
