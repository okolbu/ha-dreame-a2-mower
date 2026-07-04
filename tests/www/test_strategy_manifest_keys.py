"""Durable gate: every entity KEY the dashboard strategy references must be a
real ``unique_id`` suffix defined by some entity class in the integration.

The strategy (`www/dreame-a2-strategy.js`) resolves entities from the registry by
``unique_id`` suffix. A key with no matching entity class silently drops its card
(no crash, no dead ref — but a MISSING card the P5.5 eyeball could miss). This
test turns "silently dropped card" into a CI error: it extracts every key the
strategy uses (MANIFEST ``key:`` entries + bespoke ``resolve()`` /
``resolveMap()`` literals) and asserts each is a real key suffix mined from the
entity classes' ``unique_id`` construction sites.

This gate would have caught the review's four dead-key findings
(``obstacle_detected`` → relabelled ``bluetooth_connected``; the non-existent
per-map ``total_area_mowed`` / ``total_mowing_time`` / ``mowing_sessions``), plus
two more it surfaced during the fix (``location`` → ``mower_location``;
``sessions`` → ``session_calendar``; event ``alert`` → ``notification``).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
PKG = ROOT / "custom_components" / "dreame_a2_mower"
STRATEGY = PKG / "www" / "dreame-a2-strategy.js"

# Keys whose unique_id suffix is built dynamically (f-string / computed) so they
# cannot be mined by the literal patterns below. Each MUST be justified.
DYNAMIC_KEY_ALLOWLIST = {
    # entities/switch/global_.py:750  leaf = f"wifi_heatmap_flip_{self._AXIS}"
    "wifi_heatmap_flip_x",
    "wifi_heatmap_flip_y",
}

# Patterns that mine real unique_id suffixes from the entity classes. Covers
# description tables (`key="…"`), class `_KEY` / `_MOWER_KEY`, the
# `*_unique_id(...)` helper call sites, and the base-class first-positional-arg
# convention used by button / select / event bases
# (`super().__init__(coordinator, "<suffix>", …)`).
_REAL_PATTERNS = [
    re.compile(r'\bkey\s*=\s*"([a-z0-9_]+)"'),
    re.compile(r'\b_KEY\s*=\s*"([a-z0-9_]+)"'),
    re.compile(r'\b_MOWER_KEY\s*=\s*"([a-z0-9_]+)"'),
    re.compile(r'mower_unique_id\(\s*coordinator\s*,\s*"([a-z0-9_]+)"'),
    re.compile(r'map_unique_id\(\s*coordinator\s*,\s*map_id\s*,\s*"([a-z0-9_]+)"'),
    re.compile(r'unique_suffix\s*=\s*"([a-z0-9_]+)"'),
    re.compile(r'__init__\(\s*coordinator,\s*"([a-z0-9_]+)"'),
]


def _real_keys() -> set[str]:
    real: set[str] = set()
    for f in PKG.rglob("*.py"):
        text = f.read_text(encoding="utf-8", errors="replace")
        for pat in _REAL_PATTERNS:
            real |= set(pat.findall(text))
    return real


def _strategy_keys() -> set[str]:
    js = STRATEGY.read_text(encoding="utf-8", errors="replace")
    keys: set[str] = set()
    keys |= set(re.findall(r'\bkey:\s*"([a-z0-9_]+)"', js))
    keys |= set(re.findall(r'resolve\(\s*"([a-z0-9_]+)"\s*\)', js))
    keys |= set(re.findall(r'resolveMap\([^,]+,\s*"([a-z0-9_]+)"\s*\)', js))
    return keys


def test_every_strategy_key_is_a_real_entity_suffix():
    real = _real_keys()
    assert len(real) > 100, f"real-key extraction looks broken (only {len(real)})"
    used = _strategy_keys()
    assert used, "no strategy keys extracted — pattern drift"

    dead = sorted(k for k in used if k not in real and k not in DYNAMIC_KEY_ALLOWLIST)
    assert not dead, (
        "dashboard strategy references keys with no matching entity unique_id "
        f"suffix (each silently drops a card): {dead}"
    )


def test_allowlisted_dynamic_keys_are_still_used():
    """Guard against the allowlist rotting: every entry must still be referenced
    by the strategy (else it should be deleted, not carried forever)."""
    used = _strategy_keys()
    stale = sorted(k for k in DYNAMIC_KEY_ALLOWLIST if k not in used)
    assert not stale, f"DYNAMIC_KEY_ALLOWLIST entries no longer used by the strategy: {stale}"
