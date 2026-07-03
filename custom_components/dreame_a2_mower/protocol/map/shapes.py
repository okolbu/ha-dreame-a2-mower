"""Decorative mow-shape ``shapeType`` codes (wire knowledge).

The Dreame cloud stores decorative ``forbiddenAreas`` (heart / cloud / …) as
2 bbox corners + ``angle`` + ``shapeType``; the app tessellates the silhouette
client-side. This module owns the read-side set of decorative ``shapeType``
codes so the protocol map decoder can branch on decorative-vs-normal WITHOUT
importing the presentation layer — killing the protocol->render back-edge
(track-2 T2-3 / R-10). The matching PNG silhouette masks stay in
``map_render/_shape_masks.py`` (a presentation asset).

See ``inventory.yaml`` § shapeType for the decoded ``shapeType`` enum
(0=area, 1=line, 2=rotated-rect, 3=circle, 5=point, 7=spot, 9=square,
12=circle, 13=heart, 14=triangle, 15=teardrop, 16=mushroom, 17=cloud,
18=rainbow). Decorative = the client-tessellated palette (>=9).
"""

from __future__ import annotations

#: ``shapeType`` values the cloud stores as bbox-corners+angle for a
#: client-tessellated decorative silhouette (see module docstring + inventory
#: § shapeType). The render stamps a scaled+rotated PNG mask for these; the
#: decoder keeps their 2 bbox corners UN-rotated.
DECORATIVE_SHAPE_TYPES: frozenset[int] = frozenset({9, 12, 13, 14, 15, 16, 17, 18})
