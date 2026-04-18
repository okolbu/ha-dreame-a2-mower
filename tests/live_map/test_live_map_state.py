"""Tests for custom_components.dreame_a2_mower.live_map — pure state machine."""

from __future__ import annotations

import pytest

from live_map import LiveMapState


def test_new_state_has_empty_path_and_obstacles():
    s = LiveMapState()
    assert s.path == []
    assert s.obstacles == []


def test_append_point_stores_tuple_in_path():
    s = LiveMapState()
    s.append_point(1.5, 2.5)
    assert s.path == [[1.5, 2.5]]


def test_append_point_dedupes_near_last():
    s = LiveMapState()
    s.append_point(0.0, 0.0)
    # Less than 0.2 m away — skip.
    s.append_point(0.1, 0.1)
    assert s.path == [[0.0, 0.0]]


def test_append_point_accepts_when_far_enough():
    s = LiveMapState()
    s.append_point(0.0, 0.0)
    # Exactly at 0.2 m — accept.
    s.append_point(0.2, 0.0)
    s.append_point(0.4, 0.0)
    assert s.path == [[0.0, 0.0], [0.2, 0.0], [0.4, 0.0]]


def test_append_point_rounds_to_3_decimals():
    s = LiveMapState()
    s.append_point(1.2345678, 2.9876543)
    assert s.path == [[1.235, 2.988]]


def test_append_obstacle_stores_tuple():
    s = LiveMapState()
    s.append_obstacle(1.0, 2.0)
    assert s.obstacles == [[1.0, 2.0]]


def test_append_obstacle_dedupes_by_proximity():
    s = LiveMapState()
    s.append_obstacle(0.0, 0.0)
    # Within 0.5 m of existing — skip.
    s.append_obstacle(0.3, 0.3)
    # Exactly at 0.5 m — boundary is skip.
    s.append_obstacle(0.5, 0.0)
    # Beyond 0.5 m — accept.
    s.append_obstacle(0.6, 0.0)
    assert s.obstacles == [[0.0, 0.0], [0.6, 0.0]]


def test_append_obstacle_rounds_to_3_decimals():
    s = LiveMapState()
    s.append_obstacle(1.2345678, 2.9876543)
    assert s.obstacles == [[1.235, 2.988]]


def test_append_obstacle_checks_all_existing_not_just_last():
    """Dedupe considers ALL existing obstacles, not just the last one."""
    s = LiveMapState()
    s.append_obstacle(0.0, 0.0)
    s.append_obstacle(5.0, 5.0)
    # Close to first obstacle (not last) — should still dedupe.
    s.append_obstacle(0.1, 0.0)
    assert s.obstacles == [[0.0, 0.0], [5.0, 5.0]]


def test_start_session_resets_path_and_obstacles_increments_id():
    s = LiveMapState()
    s.append_point(1.0, 2.0)
    s.append_obstacle(3.0, 4.0)
    assert s.path != []
    assert s.obstacles != []
    assert s.session_id == 0

    s.start_session("2026-04-18T12:00:00")

    assert s.path == []
    assert s.obstacles == []
    assert s.session_id == 1
    assert s.session_start == "2026-04-18T12:00:00"


def test_start_session_increments_id_on_each_call():
    s = LiveMapState()
    s.start_session("t1")
    s.start_session("t2")
    s.start_session("t3")
    assert s.session_id == 3
    assert s.session_start == "t3"
