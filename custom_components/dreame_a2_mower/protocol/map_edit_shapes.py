"""Pure shape→type maps + point validation for the map-edit create ops.

Wire facts: dreame-app-capture-2026-06-09 (o=215/o=234) + the full o=215
shape-type map wire-confirmed [app-mitm:2026-06-17] (Square..Carrot, 14 shapes).
No HA / cloud imports — keeps the coordinator wrappers thin and fast to test.
"""
from __future__ import annotations

from typing import Any

NOGO_TYPE = {"line": 1, "polygon": 2, "circle": 3}
# Full o=215 shape-type map, wire-confirmed across the board [app-mitm:2026-06-17].
# circle is 11 (NOT 12 — the old 12 was an [UNVERIFIED] Shapes-screen-ordering
# guess that drew a no-render type); type ids 10 & 12 are firmware-UNUSED.
MOW_SHAPE_TYPE = {
    "square": 9, "circle": 11, "heart": 13, "triangle": 14,
    "teardrop": 15, "mushroom": 16, "cloud": 17, "rainbow": 18,
    "moon": 19, "star": 20, "butterfly": 21, "blob": 22,
    "tree": 23, "carrot": 24,
}


def as_pairs(points: Any) -> list[list[float]]:
    """Coerce an iterable of [x, y] into a list of [float, float]. Raises
    ValueError on a non-iterable, an empty list, or a non-2-element pair."""
    if isinstance(points, (str, bytes)) or not hasattr(points, "__iter__"):
        raise ValueError(f"points must be a list of [x, y] pairs, got {points!r}")
    out: list[list[float]] = []
    for p in points:
        if isinstance(p, (str, bytes)) or not hasattr(p, "__iter__"):
            raise ValueError(f"point must be [x, y], got {p!r}")
        pair = list(p)
        if len(pair) != 2:
            raise ValueError(f"point must have exactly 2 coords, got {pair!r}")
        out.append([float(pair[0]), float(pair[1])])
    if not out:
        raise ValueError("points is empty")
    return out


def pair(p: Any) -> list[float]:
    """Coerce a single [x, y] into [float, float]."""
    return as_pairs([p])[0]


def nogo_type(shape: str) -> int:
    try:
        return NOGO_TYPE[shape]
    except KeyError:
        raise ValueError(f"unknown no-go shape {shape!r}; expected one of {sorted(NOGO_TYPE)}")


def mow_shape_type(shape: str) -> int:
    try:
        return MOW_SHAPE_TYPE[shape]
    except KeyError:
        raise ValueError(f"unknown mow-shape {shape!r}; expected one of {sorted(MOW_SHAPE_TYPE)}")


def validate_nogo(shape: str, points: list[list[float]], *, radius: float) -> None:
    n = len(points)
    if shape == "line" and n != 2:
        raise ValueError(f"line no-go needs exactly 2 points, got {n}")
    if shape == "polygon" and n < 3:
        raise ValueError(f"polygon no-go needs >=3 points, got {n}")
    if shape == "circle":
        if n != 1:
            raise ValueError(f"circle no-go needs exactly 1 point, got {n}")
        if not radius > 0:
            raise ValueError(f"circle no-go needs radius > 0, got {radius}")


def validate_mow_shape(shape: str, points: list[list[float]]) -> None:
    n = len(points)
    if shape == "square" and n != 4:
        raise ValueError(f"square mow-shape needs exactly 4 points, got {n}")
    if shape != "square" and n != 2:
        raise ValueError(f"{shape} mow-shape needs exactly 2 points (bbox), got {n}")
