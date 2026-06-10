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


def _fake_send_action(calls, *, fail_on=None):
    """Return a send_action that records every call and returns a success
    envelope ({"result":{"out":[{"m":"s","r":0}]}}), or an r!=0 error envelope
    when the call's `t` matches fail_on."""
    def send(siid, aiid, params):
        payload = params[0]
        calls.append((siid, aiid, payload))
        r = 7 if (fail_on and payload.get("t") == fail_on) else 0
        return {"result": {"out": [{"m": "r", "r": r}]}}
    return send


def test_write_schedule_row_envelope():
    calls = []
    row = "[0,1,\"Spr\",\"qghRIBIAAu0=\"]"  # arbitrary but realistic
    sa.write_schedule_row(
        _fake_send_action(calls),
        slot=0, enabled=1, name="Spr", blob_b64="qghRIBIAAu0=",
        version=5, flag=0, txn_id=1781118711306,
    )
    # All on siid:2 aiid:50.
    assert all(c[0] == 2 and c[1] == 50 for c in calls)
    kinds = [c[2]["t"] for c in calls]
    assert kinds[0] == "SCHDIV3"
    assert kinds[-1] == "SCHDSV3"
    assert set(kinds[1:-1]) == {"SCHDDV3"}
    header = calls[0][2]["d"]
    expected_row = '[0,1,"Spr","qghRIBIAAu0="]'
    assert header == {"i": 0, "l": len(expected_row.encode()), "v": 1781118711306}
    # chunks share txn id, contiguous offsets, reassemble to the row JSON.
    chunks = [c[2]["d"] for c in calls[1:-1]]
    assert all(ch["v"] == 1781118711306 for ch in chunks)
    assert [ch["s"] for ch in chunks] == list(range(0, len(expected_row), 50))
    assert "".join(ch["d"] for ch in chunks) == expected_row
    assert all(ch["l"] == len(ch["d"].encode()) for ch in chunks)
    state = calls[-1][2]["d"]
    assert state == {"i": 0, "v": 5, "s": [1, 0]}


def test_write_schedule_row_raises_on_error():
    import pytest
    with pytest.raises(sa.CfgActionError):
        sa.write_schedule_row(
            _fake_send_action([], fail_on="SCHDSV3"),
            slot=0, enabled=1, name="Spr", blob_b64="qghRIBIAAu0=",
            version=5, flag=0, txn_id=1,
        )


def test_read_schedule_rows_from_probe_rows():
    # SCHDTV3 probe returns the full table in d.rows -> return as-is.
    def send(siid, aiid, params):
        t = params[0]["t"]
        if t == "SCHDTV3":
            return {"result": {"out": [{"m": "r", "r": 0, "d": {
                "rows": [[0, 1, "Spr", "qghRIBIAAu0="], [1, 0, "Aut", ""]],
            }}]}}
        raise AssertionError(f"unexpected t={t}")
    rows = sa.read_schedule_rows(send)
    assert rows == [[0, 1, "Spr", "qghRIBIAAu0="], [1, 0, "Aut", ""]]


def test_read_schedule_rows_malformed_returns_empty():
    def send(siid, aiid, params):
        return {"result": {"out": [{"m": "r", "r": 0, "d": {}}]}}
    assert sa.read_schedule_rows(send) == []
