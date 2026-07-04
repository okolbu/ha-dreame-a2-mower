from __future__ import annotations

import pytest
from custom_components.dreame_a2_mower.map_render.background import (
    BackgroundMode, background_mode_for,
)
from custom_components.dreame_a2_mower.state.snapshot import (
    MowSession, CurrentActivity,
)
from custom_components.dreame_a2_mower.state import ActionMode

ACTIVE = [
    CurrentActivity.MOWING, CurrentActivity.PAUSED, CurrentActivity.REPOSITIONING,
    CurrentActivity.RETURNING, CurrentActivity.CHARGE_RESUME,
    CurrentActivity.CRUISING_TO_POINT, CurrentActivity.FAST_MAPPING,
    CurrentActivity.DRIVING_BLADES_UP,
    # Patrol is an active (blades-up, out-and-moving) session -> GREEN.
    CurrentActivity.PATROL_POINT, CurrentActivity.PATROL_EDGE,
]


def test_patrol_activities_render_green():
    # Regression (2026-06-04): a patrol settled into PATROL_POINT/EDGE flickered
    # back to the idle stripe preview because these weren't in _ACTIVE_ACTIVITIES.
    for activity in (CurrentActivity.PATROL_POINT, CurrentActivity.PATROL_EDGE):
        assert background_mode_for(
            mow_session=MowSession.BETWEEN_SESSIONS,
            current_activity=activity,
            action_mode=ActionMode.ALL_AREAS,
        ) is BackgroundMode.GREEN

@pytest.mark.parametrize("activity", ACTIVE)
def test_active_activities_render_green(activity):
    # The #1 fix: every non-idle activity -> GREEN, regardless of action_mode
    # or mow_session. REPOSITIONING is the reorientation window that used to
    # stay striped for ~41s.
    assert background_mode_for(
        mow_session=MowSession.BETWEEN_SESSIONS,
        current_activity=activity,
        action_mode=ActionMode.ALL_AREAS,
    ) is BackgroundMode.GREEN

def test_in_session_is_green_even_if_activity_idle():
    assert background_mode_for(
        mow_session=MowSession.IN_SESSION,
        current_activity=CurrentActivity.IDLE,
        action_mode=ActionMode.ALL_AREAS,
    ) is BackgroundMode.GREEN

@pytest.mark.parametrize("action,expected", [
    (ActionMode.ALL_AREAS, BackgroundMode.STRIPES),
    (ActionMode.ZONE, BackgroundMode.STRIPES),
    (ActionMode.EDGE, BackgroundMode.EDGE),
    (ActionMode.SPOT, BackgroundMode.SPOT),
])
def test_idle_dispatches_by_action_mode(action, expected):
    assert background_mode_for(
        mow_session=MowSession.BETWEEN_SESSIONS,
        current_activity=CurrentActivity.IDLE,
        action_mode=action,
    ) is expected

def test_idle_at_point_is_idle_preview_not_green():
    # AT_POINT (parked at maintenance point) is idle -> striped preview.
    assert background_mode_for(
        mow_session=MowSession.BETWEEN_SESSIONS,
        current_activity=CurrentActivity.AT_POINT,
        action_mode=ActionMode.ALL_AREAS,
    ) is BackgroundMode.STRIPES

def test_none_action_mode_defaults_to_stripes():
    assert background_mode_for(
        mow_session=MowSession.BETWEEN_SESSIONS,
        current_activity=CurrentActivity.IDLE,
        action_mode=None,
    ) is BackgroundMode.STRIPES
