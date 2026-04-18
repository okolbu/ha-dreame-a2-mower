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
