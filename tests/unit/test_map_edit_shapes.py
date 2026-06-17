import pytest
from custom_components.dreame_a2_mower.protocol import map_edit_shapes as mes


def test_as_pairs_coerces_and_validates():
    assert mes.as_pairs([[1, 2], (3.5, 4)]) == [[1.0, 2.0], [3.5, 4.0]]
    with pytest.raises(ValueError):
        mes.as_pairs([[1, 2, 3]])      # not a 2-tuple
    with pytest.raises(ValueError):
        mes.as_pairs([])               # empty
    with pytest.raises(ValueError):
        mes.as_pairs("nope")


def test_nogo_type_and_validation():
    assert mes.nogo_type("line") == 1
    assert mes.nogo_type("polygon") == 2
    assert mes.nogo_type("circle") == 3
    with pytest.raises(ValueError):
        mes.nogo_type("blob")
    # point-count validation
    mes.validate_nogo("line", [[0, 0], [1, 1]], radius=0)        # ok
    mes.validate_nogo("polygon", [[0, 0], [1, 0], [1, 1]], radius=0)  # ok
    mes.validate_nogo("circle", [[0, 0]], radius=1.5)            # ok
    with pytest.raises(ValueError):
        mes.validate_nogo("line", [[0, 0]], radius=0)           # need 2
    with pytest.raises(ValueError):
        mes.validate_nogo("polygon", [[0, 0], [1, 1]], radius=0)  # need >=3
    with pytest.raises(ValueError):
        mes.validate_nogo("circle", [[0, 0]], radius=0)         # radius must be >0


def test_mow_shape_type_and_validation():
    assert mes.mow_shape_type("square") == 9
    assert mes.mow_shape_type("heart") == 13
    assert mes.mow_shape_type("rainbow") == 18
    with pytest.raises(ValueError):
        mes.mow_shape_type("hexagon")
    mes.validate_mow_shape("square", [[0, 0], [1, 0], [1, 1], [0, 1]])   # 4 ok
    mes.validate_mow_shape("heart", [[0, 0], [1, 1]])                    # 2 ok
    with pytest.raises(ValueError):
        mes.validate_mow_shape("square", [[0, 0], [1, 1]])              # need 4
    with pytest.raises(ValueError):
        mes.validate_mow_shape("cloud", [[0, 0], [1, 1], [2, 2]])       # need 2


def test_mow_shape_type_full_wire_confirmed_map():
    """Wire-confirmed 2026-06-17 [app-mitm:2026-06-17]: circle is 11 (not 12),
    and moon/star/butterfly/blob/tree/carrot (19-24) exist. 10 & 12 unused."""
    expected = {
        "square": 9, "circle": 11, "heart": 13, "triangle": 14,
        "teardrop": 15, "mushroom": 16, "cloud": 17, "rainbow": 18,
        "moon": 19, "star": 20, "butterfly": 21, "blob": 22,
        "tree": 23, "carrot": 24,
    }
    for name, type_id in expected.items():
        assert mes.mow_shape_type(name) == type_id, name
    # the full map is exactly this set
    assert mes.MOW_SHAPE_TYPE == expected
    # 10 and 12 are firmware-UNUSED — must not be reachable type ids
    assert 10 not in mes.MOW_SHAPE_TYPE.values()
    assert 12 not in mes.MOW_SHAPE_TYPE.values()
    # unknown name still raises ValueError
    with pytest.raises(ValueError):
        mes.mow_shape_type("octagon")
