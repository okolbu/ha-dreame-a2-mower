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


def _fake_schedule_read(rows_json, *, version=58177, device_chunk_cap=76):
    """send_action that serves rows_json via the live SCHDIV3->SCHDDV3 chunked
    GET. Simulates a device that caps each data chunk at `device_chunk_cap`
    bytes regardless of the requested length (mirrors the 2026-06-17 capture:
    a 119-byte schedule came back as 76 + 43)."""
    raw = rows_json.encode("utf-8")
    total = len(raw)

    def send(siid, aiid, params):
        assert (siid, aiid) == (2, 50)
        p = params[0]
        assert p["m"] == "g", f"read must use m:'g', got {p['m']!r}"
        t = p["t"]
        if t == "SCHDIV3":
            assert p["d"] == {"i": 0}
            return {"result": {"out": [{"m": "r", "r": 0,
                    "d": {"i": 0, "l": total, "v": version}}]}}
        if t == "SCHDDV3":
            d = p["d"]
            assert d["v"] == version
            s = d["s"]
            seg = raw[s:s + min(d["l"], device_chunk_cap)]
            return {"result": {"out": [{"m": "r", "r": 0, "d": {
                "d": seg.decode("utf-8"), "l": len(seg), "s": s, "v": version,
            }}]}}
        raise AssertionError(f"unexpected t={t}")

    return send


def test_read_live_schedule_chunked_get():
    # The exact reassembled payload from the 2026-06-17 capture (v=58177, l=119).
    rows_json = (
        '{"d":[[0,1,"Spr & Sum Schedule",'
        '"qgcQ3gEA7aoHMN4BAO2qBzDAAwDtqgdQ4AEA7Q=="],'
        '[1,0,"","qgcQHAIA7aoHQBwCAO0="]],"v":58177}'
    )
    obj = sa.read_live_schedule(_fake_schedule_read(rows_json))
    assert obj is not None
    assert obj["v"] == 58177
    assert obj["d"][0][:3] == [0, 1, "Spr & Sum Schedule"]
    assert obj["d"][1][:2] == [1, 0]


def test_read_schedule_rows_chunked_get():
    rows_json = '{"d":[[0,1,"Spr","qghRIBIAAu0="],[1,0,"",""]],"v":42}'
    rows = sa.read_schedule_rows(_fake_schedule_read(rows_json, version=42))
    assert rows == [[0, 1, "Spr", "qghRIBIAAu0="], [1, 0, "", ""]]


def test_read_schedule_rows_uses_m_g_not_m_r():
    # m:'r' returns no payload on the wire; the read must send m:'g'.
    captured = []

    def send(siid, aiid, params):
        captured.append(params[0]["m"])
        return None  # device gives nothing back

    assert sa.read_schedule_rows(send) == []
    assert sa.read_live_schedule(send) is None
    assert captured and all(m == "g" for m in captured)


def test_read_live_schedule_device_error_returns_none():
    def send(siid, aiid, params):
        return {"result": {"out": [{"m": "r", "r": 7}]}}  # firmware rejects
    assert sa.read_live_schedule(send) is None
    assert sa.read_schedule_rows(send) == []


def test_read_live_schedule_bad_json_returns_none():
    def send(siid, aiid, params):
        t = params[0]["t"]
        if t == "SCHDIV3":
            return {"result": {"out": [{"m": "r", "r": 0,
                    "d": {"i": 0, "l": 5, "v": 1}}]}}
        return {"result": {"out": [{"m": "r", "r": 0,
                "d": {"d": "xxxxx", "l": 5, "s": 0, "v": 1}}]}}
    assert sa.read_live_schedule(send) is None
