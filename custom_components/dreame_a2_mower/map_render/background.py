"""Background-mode projection: pure function of the state-machine snapshot.

This is the single authority for "is the live map showing an active (green)
view or an idle pre-start preview". It replaces the scattered
`live_map.is_active() OR current_activity == REPOSITIONING` checks that left the
~41s reorientation window striped (the #1 bug). Every non-idle activity reads as
GREEN, so stripes clear the instant the state machine enters REPOSITIONING /
CRUISING_TO_POINT on the s2p1 echo — ~41s before the first position message.
"""
from __future__ import annotations

from enum import Enum

from ..mower.state import ActionMode
from ..mower.state_snapshot import CurrentActivity, MowSession


class BackgroundMode(str, Enum):
    GREEN = "green"      # active session view (dark-green lawn, trail drawn client-side)
    STRIPES = "stripes"  # idle ALL_AREAS/ZONE pre-start preview
    EDGE = "edge"        # idle EDGE pre-start preview
    SPOT = "spot"        # idle SPOT pre-start preview


# Every activity that means "a task is underway / mower is out and moving".
# DRIVING_BLADES_UP and FAST_MAPPING are GREEN by design (spec §4.1 / §11.4):
# the mower is active, so the idle stripe preview would reproduce the #1 bug.
_ACTIVE_ACTIVITIES = frozenset({
    CurrentActivity.MOWING,
    CurrentActivity.PAUSED,
    CurrentActivity.REPOSITIONING,
    CurrentActivity.RETURNING,
    CurrentActivity.CHARGE_RESUME,
    CurrentActivity.CRUISING_TO_POINT,
    CurrentActivity.FAST_MAPPING,
    CurrentActivity.DRIVING_BLADES_UP,
})

_IDLE_PREVIEW_BY_ACTION = {
    ActionMode.ALL_AREAS: BackgroundMode.STRIPES,
    ActionMode.ZONE: BackgroundMode.STRIPES,
    ActionMode.EDGE: BackgroundMode.EDGE,
    ActionMode.SPOT: BackgroundMode.SPOT,
}


def background_mode_for(
    *,
    mow_session: MowSession,
    current_activity: CurrentActivity,
    action_mode: ActionMode | None,
) -> BackgroundMode:
    """Project the state-machine dimensions to a live-map background mode."""
    if mow_session == MowSession.IN_SESSION or current_activity in _ACTIVE_ACTIVITIES:
        return BackgroundMode.GREEN
    return _IDLE_PREVIEW_BY_ACTION.get(action_mode, BackgroundMode.STRIPES)
