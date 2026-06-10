from custom_components.dreame_a2_mower.protocol import schedule_action as sa


def test_chunk_row_json_offsets_and_reassembly():
    s = "x" * 123  # 123 bytes -> 50 + 50 + 23
    chunks = sa.chunk_row_json(s)
    assert [off for off, _ in chunks] == [0, 50, 100]
    assert [len(c.encode("utf-8")) for _, c in chunks] == [50, 50, 23]
    assert "".join(c for _, c in chunks) == s


def test_chunk_row_json_short_string_single_chunk():
    s = "[0,1,\"n\",\"AA==\"]"
    chunks = sa.chunk_row_json(s)
    assert len(chunks) == 1
    assert chunks[0] == (0, s)


def test_chunk_row_json_empty():
    assert sa.chunk_row_json("") == []
