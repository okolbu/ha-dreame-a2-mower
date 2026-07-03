"""Decorative mow-shape silhouette masks (shapeType -> base64 PNG).

Extracted from the Dreame app's Shapes palette [screenshot:OLD/IMG_4615.PNG,
2026-06-12]. Each is an L-mode silhouette (white shape on black) used by
map_render.base_map to stamp a heart/cloud/etc. no-go region: the cloud stores
decorative forbiddenAreas as 2 bbox corners + angle + shapeType (the app
tessellates client-side), so the integration stamps the matching mask scaled to
the bbox and rotated by angle. shapeType 9=square, 12=circle, 13=heart,
14=triangle, 15=teardrop, 16=mushroom, 17=cloud, 18=rainbow.
"""

SHAPE_MASK_PNG_B64: dict[int, str] = {
    9: (  # square
        "iVBORw0KGgoAAAANSUhEUgAAAFgAAABYCAAAAABU/m/oAAAAPUlEQVR42u3MMQEAIAACMLB/Zy0h"
        "3xZgzc1Cu3mTE7FYLBaLxWKxWCwWi8VisVgsFovFYrFYLBb/j7t5+wA+hwKwoZ0DfgAAAABJRU5E"
        "rkJggg=="
    ),
    12: (  # circle
        "iVBORw0KGgoAAAANSUhEUgAAAFgAAABYCAAAAABU/m/oAAABF0lEQVR42u3ZSw6AIAwEUKb3v/O4"
        "VD5qgSkJCazpy6QWN0XyHqaUUoL3OrxibxkGVFclxtT/Yoyz3+WYYb8AzLHvBGbZN8QErnMgu9m2"
        "Yxq3LjONWxeayK1KTeWWxSZzi3LTuTlgQjcjTOk+EUtBx6SBH4xp3RuKbgV1IpckppLkgsTUmgxP"
        "TDXKJU86AKZe5Z6tYATLPafiwMEweFpx4ApG0LSdHh+4BYfMG/bsMSI6sem4IaATwa2APnD0x4M8"
        "cPi4QR04/oFAHPhODK274l8BaeBnYijdrBUQunmPoXOLjweZW04FVG41bhC59RxD4zYdzrPtlweB"
        "u3gl1EN3LrG89MDazUMPLgp/7JnV5rs9v4wtfff9CyUvNKCbA+lWAAAAAElFTkSuQmCC"
    ),
    13: (  # heart
        "iVBORw0KGgoAAAANSUhEUgAAAGMAAABVCAAAAAB4cwX5AAABhElEQVR42u2Xy5aEMAgFKf7/n5nF"
        "jHZrGwMJeEZPu3JxsQzvIM3HRARxPedSmjZd0ZHyUErfrI0x32/jswsp91K8dnutXxmw24oD0s27"
        "9ROIqFJEREOIP41fucOZrxRwK9dvaxAh5lauQg0iIspdPOKGgd/RQsTyXZXSx1aG1YK0GGH1vroi"
        "HiImouXRuMpXVu6sR8T8OQy75Bz2jce/YvD1lXfNek5e8YBzcFVecXtf8cvg5udgYXDrc/BiUIlY"
        "zkEhYvUVdYhXPChDvMWcKsR7XlGE2OQuNYhtfVCC2NUgFYh9nVOA+Ogl5CM++xXpiIOeSDbiqO+S"
        "jDjs7eQijucHqYjGjCIT0ZqDJCKas5Y8RHuek4Y42RnIQpztJSQhTncfchDn+xUpiM4ORwaityeS"
        "gOjuoswj+vsu0wjHTs30T+isKxzO1El/e+Klc3njyjudSk5fautMkTlLVCcq2dsF3PdBxruZ/87J"
        "cMMM3GsZbfyRuzODsyV0P2dsRkantg1Y/QAb+SnkA+HGDQAAAABJRU5ErkJggg=="
    ),
    14: (  # triangle
        "iVBORw0KGgoAAAANSUhEUgAAAFsAAABYCAAAAAC/ydTrAAABLElEQVR42s2YSQ6DMAwAY8T/vzy9"
        "oSJI6y2xOQXbjAZLWUCG4WIMMZSLBWx85DCjv0ZJbCbjBDY/7uI9cVyHQ1srXu6NIuJko4w16wmG"
        "aCNvjPEm3jgyDbxx5oq9CWQLvRmR1yrzZoyIeJW3Zo2mn7duw6Wbt/b0RC9v9YlyXnmE0fPagp5g"
        "gtDFGyOFHt6YMXTwxsGh3hsXiGpvnCRqvXGjqPQmwKLOmxCMKm+CNOZswqpU9IQEHvu9SQGy25sk"
        "Inu9SUOy05tEJvu8SYWyy5tkKnu8Sceyw5sFXNZ7swTMam8WkRmnpVxsDTwtYCNeMICN+5+GLc7v"
        "W/lXJObfD9eTpxes6P3pBSvws6RYF48XgrylxDXFHwx5JCSwgtwpcg9LdJ6/ckg7D16gDwxCaFtR"
        "/I03AAAAAElFTkSuQmCC"
    ),
    15: (  # teardrop
        "iVBORw0KGgoAAAANSUhEUgAAAE8AAABhCAAAAACy+aMcAAABOElEQVR42u2YSQ6DMBAE3f7/nyu3"
        "iEQss0Ii4GyXehkbwRi2B+M6OWCq4eFZPV1OyfPwxTidPZDj4S16uqeEZB++Z/qHmCiPwFmZkSNG"
        "hEfoNM/YBcDV/TJGSOCMXnd4eJbbk+vys13uWHnWdwU2HmZzXJEfjt0c83DJ4YiH0x/n5ocbwB6P"
        "gCLO80sIwRaPoCbO8UsYwhqPhCr6/ZLC0K2PJIdefaRBLHn0nN8CgS35USewQx+FCTboo7LiU79n"
        "QjwKafyB33vxxJNfiqfaOp55/jVeZcG6Yx8qjK/Fr+rk9fShMnlN86IqeV3zrCJ5b32qwfWdX5XI"
        "W+hTBW7pVwW4j/yUx332oTTuq19lcd/zoiRuBUCCtjbPyuDWdxOlbaohRttxR4S2nxbDv0mmvyD2"
        "HcY2sa58AbaETZNDHL3zAAAAAElFTkSuQmCC"
    ),
    16: (  # mushroom
        "iVBORw0KGgoAAAANSUhEUgAAAGQAAABeCAAAAADwaO5DAAABOklEQVR42u2X0RKCMAwEe/n/fz4f"
        "HKVAhZbkIjrlPbteEktBGXtYSikFY0UYo18rxlXBCAAuQycDXkMPBhGKMxBiFMcoC3McFCBKcURD"
        "pOMTD6GKD0ALdjSLLdjRLEewogk1gWMHMYFjhzGFYwsyiWODMo1jDbOS8JgoyApnKkcNNJmjQprO"
        "sUAzB08NnbWEqgxMbhd1fKYmoVLAxCTUGph/CuuimLpb33hpTUnHjZKzXbeTIGHucyZ3lMgnj/+a"
        "CdTdymsXxEGeSaB1ZG4XpEFeSaB0vNsFoWOZCXSOavCQOdZoShS730+BotUkBhtOJ8Hr4P6jHiGO"
        "eZGYkimZkmRJ5+GF2a6BfuEntgv+IHcZPPxZzd0NxKwwvOtnzhVF3J8RvmOnc7vgcQzc5am6+h14"
        "RgqHv0p4oegBP1I3rcA5w1gAAAAASUVORK5CYII="
    ),
    17: (  # cloud
        "iVBORw0KGgoAAAANSUhEUgAAAH8AAABVCAAAAABF4WSfAAABVklEQVR42u2ZyQ6DQAxD46j//8vu"
        "AXVha2eGJEaCOQLhxc5CpcJGDs3MYAEHA+AjLzgSziARQ6GMtLE7kNGF7ApjRiu1BzGpmdtCmDdN"
        "LRFMnWfzWHz38x77uli/mDnSbf6Pfhwi+CxIwOPxXZGegA/xnzUt4DmyeJRf436a/ub8XSs/TX+r"
        "Ak+Tf+RHS7D96LyVUX2I+Tsst7pDtuWUOXwQ6t/ywMt3D//w01cff9a/ZPNij1+197Htf9ln5w16"
        "KOjb/VeK54pfrJ4Lfrn5nPEVtf/iK/BU7P9t/Rr3+eJTrV90OPFpF9U/8akswDnmT8nnxfVfmk+5"
        "ft71Fx7I9eOu/82Xtf8J9OO6/uMU/Qeh/FPMH3Tyhfrx6X+o5w8q+TL/Md8/EOHf+qHBf/yHBP9V"
        "fyjwcyrL8QvVLKavXWcpfT3/qMVX/v+G5osJKaDzelwSvyv6BOueR35hvsCxAAAAAElFTkSuQmCC"
    ),
    18: (  # rainbow
        "iVBORw0KGgoAAAANSUhEUgAAAHoAAABACAAAAADw0zzzAAABOElEQVR42uWY2RKEIAwEmSn//5ez"
        "rx4cISQRa33VdDsCFgHFfkkppRRYy2E1rqPgo7Xg4KedRcLZO0FFgFjJRYhYRUaQWMFGmHhIR6B4"
        "wGesuYdgrLkHQay452C8uYVivLkFQ7y45WGOuYZkjrkGZZK5gmWW+QlmmvmBZp75Dmd57WJi6Bue"
        "meargKnmi4K55rPkxWkGW2gsrEk8GGLVWgGH3z4P1hZFFsXzlMMnsSU5J17XrYmTydT63lWmUoub"
        "Wd/H0TnzxMPUhYbXCjzFpn9mbQE1oQ3HTIofACMy64oYZFaUcfi9g04DZaNtoWPoYSmT9kWVL864"
        "0KPifccaa3T01bJnaqzi8cmxfk2NdT72TC1/OdbYMrXLW2HPxYXQ0B0Mm/fcJkGLz9Y9x+nX4KPa"
        "afpP+wr/B5C3QXoQYgk0AAAAAElFTkSuQmCC"
    ),
}

# DECORATIVE_SHAPE_TYPES is owned by the protocol leaf ``protocol/map/shapes.py``
# (wire knowledge — kills the protocol->render back-edge T2-3/R-10). Re-exported
# here so render-side importers (base_map) keep a local name. The PNG masks above
# are the presentation asset; the mask keys must stay a subset of the wire set.
from ..protocol.map.shapes import DECORATIVE_SHAPE_TYPES  # noqa: E402,F401

assert set(SHAPE_MASK_PNG_B64).issubset(DECORATIVE_SHAPE_TYPES), (
    "SHAPE_MASK_PNG_B64 has a shapeType not in protocol.map.shapes.DECORATIVE_SHAPE_TYPES"
)

