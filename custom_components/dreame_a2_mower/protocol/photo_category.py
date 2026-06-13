"""Categorize an archived photo/video from its OSS record + parsed JPEG COM.

Single source of truth for the gallery taxonomy. Derived from the 2026-06-12
live OSS probe: the server `category` field is always 0 (useless) and the COM
`o` is the *activity* during capture (107=patrol, 100-103=mow), NOT the photo
type. AI detection = a non-empty COM `detections` list; `cls` names the object.
Manual live-view snapshots have no COM.

Categories: video, ai_human, ai_animal, ai_object, patrol, obstacle, manual.

PROVISIONAL (refined once a live session produces these events):
  - ANIMAL_CLASSES is a best-guess set; any unknown `cls` falls through to
    ai_object with its raw label preserved on the item (no silent loss).
  - obstacle (o in mow modes + empty detections) vs manual (no COM) may overlap
    if normal-obstacle photos turn out to lack a COM.
"""
from __future__ import annotations

from typing import Any

HUMAN_CLASSES: frozenset[str] = frozenset({"person", "human"})

# Best-guess animal labels. Unknown labels -> ai_object (raw label kept).
ANIMAL_CLASSES: frozenset[str] = frozenset({
    "animal", "cat", "dog", "hedgehog", "bird", "rabbit", "fox", "squirrel",
    "mouse", "rat", "deer", "cow", "sheep", "horse", "goat", "pig", "chicken",
    "duck", "tortoise", "turtle", "frog", "snake", "lizard",
})

_MOW_MODES = frozenset({100, 101, 102, 103})


def primary_detection(detections: list[dict] | None) -> dict:
    """Return the highest-confidence detection (or {} if none)."""
    if not detections:
        return {}
    return max(detections, key=lambda d: (d or {}).get("conf") or 0.0)


def categorize(*, name: str | None, record: dict[str, Any], com: dict | None) -> str:
    """Return the gallery category for one media item.

    `name`   = OSS leaf filename (e.g. "1780952775_person.jpg").
    `record` = the userDidOssList record (`type`, `videoPath`, ...).
    `com`    = parsed JPEG COM (`{o, detections, s, sub}`) or None.
    """
    if (record or {}).get("type") == "thumb" or (record or {}).get("videoPath"):
        return "video"

    dets = (com or {}).get("detections") or []
    if dets:
        cls = primary_detection(dets).get("cls")
        if cls in HUMAN_CLASSES:
            return "ai_human"
        if cls in ANIMAL_CLASSES:
            return "ai_animal"
        return "ai_object"

    # No AI detection.
    if name and name.lower().endswith("_person.jpg"):
        return "ai_human"  # app-named human capture (COM detection may be absent)
    o = (com or {}).get("o")
    if o == 107:
        return "patrol"
    if o in _MOW_MODES:
        return "obstacle"
    if com is None:
        return "manual"
    return "obstacle"
