"""Coordinator replay_session tests (domain/session/replay).

Split out of the test_coordinator.py monolith (P3.11); tests moved verbatim.
"""
from __future__ import annotations


from tests.integration._coordinator_helpers import (
    _REPLAY_SUMMARY_JSON,
    _REPLAY_SUMMARY_WITH_OBSTACLES_JSON,
    _make_coordinator_for_replay_tests,
)


def test_replay_session_unknown_md5_returns_early():
    """replay_session with an unknown md5 logs a warning and returns without rendering."""
    import asyncio
    from unittest.mock import patch

    coord = _make_coordinator_for_replay_tests(sessions=[])

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_work_log",
    ) as mock_trail:
        asyncio.run(coord.replay_session("does-not-exist"))
        mock_trail.assert_not_called()

    assert coord._work_log_png is None


def test_replay_session_load_failure_returns_early():
    """replay_session aborts when archive.load() returns None."""
    import asyncio
    from unittest.mock import patch

    from custom_components.dreame_a2_mower.archive.session import ArchivedSession

    entry = ArchivedSession(
        filename="session_abc.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="abc123",
    )
    coord = _make_coordinator_for_replay_tests(sessions=[entry], load_return=None)

    with patch("custom_components.dreame_a2_mower.map_render.render_work_log") as mock_trail:
        asyncio.run(coord.replay_session("abc123"))
        mock_trail.assert_not_called()

    assert coord._work_log_png is None


def test_replay_session_renders_archived_trail():
    """Happy-path replay_session fetches the archived path and renders it.

    Verifies:
    - render_work_log is called once with map_data and the parsed legs.
    - _work_log_png is populated with the returned PNG bytes.
    """
    import asyncio
    import copy
    from unittest.mock import patch

    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    from tests.integration.test_map_decoder import _MINIMAL_MAP

    entry = ArchivedSession(
        filename="session_replay.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="replay-md5",
    )
    coord = _make_coordinator_for_replay_tests(
        sessions=[entry],
        load_return=copy.deepcopy(_REPLAY_SUMMARY_JSON),
        fetch_map_return=copy.deepcopy(_MINIMAL_MAP),
        last_map_md5="old-md5",
    )

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

    # Inject a top-level "track" into the raw_dict so the new path has data.
    # 7-element rows: [t, x_m, y_m, area_m2, heading_deg, task_state, role].
    # Three mowing points → derive_render_legs produces one mowing leg.
    import copy
    raw_with_track = copy.deepcopy(_REPLAY_SUMMARY_JSON)
    raw_with_track["track"] = [
        [1_700_000_010, 1.0, 0.5, 0.5, 90.0, 0, "mowing"],
        [1_700_000_020, 2.0, 0.5, 1.0, 90.0, 0, "mowing"],
        [1_700_000_030, 3.0, 0.5, 1.5, 90.0, 0, "mowing"],
    ]
    coord.session_archive.load.return_value = raw_with_track

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_work_log",
        return_value=fake_png,
    ) as mock_render:
        asyncio.run(coord.replay_session("replay-md5"))

        mock_render.assert_called_once()
        # Task 13: render_work_log is now called with legs_timeline= derived
        # from the top-level "track" field (7-element rows).
        # Three mowing points → one legs_timeline entry with role="mowing".
        timeline = mock_render.call_args.kwargs.get("legs_timeline")
        assert isinstance(timeline, list), (
            f"expected legs_timeline kwarg, got: {mock_render.call_args.kwargs!r}"
        )
        assert len(timeline) == 1
        assert timeline[0]["role"] == "mowing"
        assert len(timeline[0]["pts"]) == 3

    assert coord._work_log_png == fake_png


def test_replay_session_no_cloud_returns_early():
    """replay_session aborts gracefully when _cloud is not set (pre-init)."""
    import asyncio
    import copy

    from custom_components.dreame_a2_mower.archive.session import ArchivedSession

    entry = ArchivedSession(
        filename="session_replay.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="replay-md5",
    )
    coord = _make_coordinator_for_replay_tests(
        sessions=[entry],
        load_return=copy.deepcopy(_REPLAY_SUMMARY_JSON),
    )
    # Remove _cloud to simulate pre-init state.
    del coord._cloud

    from unittest.mock import patch
    with patch("custom_components.dreame_a2_mower.map_render.render_work_log") as mock_trail:
        asyncio.run(coord.replay_session("replay-md5"))
        mock_trail.assert_not_called()

    assert coord._work_log_png is None


def test_replay_session_passes_obstacles_to_renderer():
    """replay_session should extract Obstacle.polygon tuples and pass
    them to render_with_trail under the obstacle_polygons_m kwarg."""
    import asyncio
    import copy
    from unittest.mock import patch

    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    from tests.integration.test_map_decoder import _MINIMAL_MAP

    entry = ArchivedSession(
        filename="session_obs.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="obs-md5",
    )
    coord = _make_coordinator_for_replay_tests(
        sessions=[entry],
        load_return=copy.deepcopy(_REPLAY_SUMMARY_WITH_OBSTACLES_JSON),
        fetch_map_return=copy.deepcopy(_MINIMAL_MAP),
        last_map_md5="old-md5",
    )

    captured: dict = {}

    def fake_render(map_data, *args, **kwargs):
        captured["kwargs"] = kwargs
        return b"PNGFAKE"

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_work_log",
        side_effect=fake_render,
    ):
        asyncio.run(coord.replay_session("obs-md5"))

    polys = captured.get("kwargs", {}).get("obstacle_polygons_m")
    assert polys is not None, "render_work_log_session must pass obstacle_polygons_m"
    assert len(polys) == 7, f"fixture has 7 obstacle polygons, got {len(polys)}"
    # Each polygon is a list/tuple of (x_m, y_m) pairs in metres.
    for poly in polys:
        assert len(poly) >= 3, "each polygon must have >= 3 points"
        for x, y in poly:
            assert isinstance(x, float), f"x must be float, got {type(x)}"
            assert isinstance(y, float), f"y must be float, got {type(y)}"
    # Spot-check: first obstacle first point is [-110cm, 1163cm] => [-1.1m, 11.63m].
    assert abs(polys[0][0][0] - (-1.1)) < 1e-9
    assert abs(polys[0][0][1] - 11.63) < 1e-9


def test_replay_session_with_no_obstacles_passes_empty_list():
    """A session with zero obstacles still passes an empty list (not
    None) to the renderer so the overlay branch is consistent."""
    import asyncio
    import copy
    from unittest.mock import patch

    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    from tests.integration.test_map_decoder import _MINIMAL_MAP

    entry = ArchivedSession(
        filename="session_replay.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="replay-md5",
    )
    coord = _make_coordinator_for_replay_tests(
        sessions=[entry],
        load_return=copy.deepcopy(_REPLAY_SUMMARY_JSON),  # obstacle: []
        fetch_map_return=copy.deepcopy(_MINIMAL_MAP),
        last_map_md5="old-md5",
    )

    captured: dict = {}

    def fake_render(map_data, *args, **kwargs):
        captured["kwargs"] = kwargs
        return b"PNGFAKE"

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_work_log",
        side_effect=fake_render,
    ):
        asyncio.run(coord.replay_session("replay-md5"))

    polys = captured.get("kwargs", {}).get("obstacle_polygons_m")
    assert polys == [], f"expected empty list for no obstacles, got {polys!r}"
