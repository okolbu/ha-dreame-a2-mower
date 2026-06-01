# Live-map Display Rehaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the live map and session-replay onto one client-side SVG-animation model — server renders only the base (with a lifecycle-driven stripes/green background), the client animates a directional mower icon and trail from a published position stream.

**Architecture:** `background_mode` becomes a pure projection of the state machine's `current_activity` (fixes the 41 s stripe lag). The server stops compositing the live PNG entirely and instead publishes a position/heading stream as camera attributes. A shared client SVG card interpolates the icon between ~5 s position messages (fixes stutter) and rotates it by the trusted byte heading via one flip convention (fixes wrong-facing). Three PIL compositors, the `_StateProxy` hack, and ~6 scattered render triggers collapse to one publisher + one base renderer.

**Tech Stack:** Python 3.13 (Home Assistant custom component, PIL/Pillow for the base PNG), vanilla-JS Lovelace custom cards (SVG + `requestAnimationFrame`), pytest (vanilla stubbed-HA venv), node for JS pure-function tests.

**Spec:** `docs/superpowers/specs/2026-05-31-live-map-display-rehaul-design.md`

**Test runner:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest` (system `python3`=3.14 is broken — always use this venv; baseline 1591 passed / 4 skipped — see `reference_test_env_setup`).

**Conventions to honor:** per-map naming (CLAUDE.md), rendering package is acyclic `_geometry ← base_map ← {main_view, work_log}` (CLAUDE.md "Rendering structure"), fact-discipline inventory updates (CLAUDE.md), single-user — no migration/back-compat shims (`feedback_no_migration_overengineering`), commit per task but **do not push/tag** unless the user asks.

---

## File Structure

**Server (Python)**
- `custom_components/dreame_a2_mower/map_render/background.py` — **new.** `BackgroundMode` enum + `background_mode_for(...)` pure projection.
- `custom_components/dreame_a2_mower/map_render/main_view.py` — **trim** to `render_base(map_data, background_mode, ...)` (base + background dispatch). Delete the trail branch + `_composite_mower_icon`.
- `custom_components/dreame_a2_mower/map_render/trail.py` — **delete.**
- `custom_components/dreame_a2_mower/map_render/__init__.py` — drop `render_main_view`/`render_with_trail` re-exports; add `render_base`, `BackgroundMode`, `background_mode_for`.
- `custom_components/dreame_a2_mower/coordinator/_rendering.py` — replace `_render_main_view` family with `_compute_background_mode`, `_render_base`, `_publish_live_stream`. Delete `_maybe_rerender_between_session_icon`, `_rerender_live_trail`, `_StateProxy`, `_current_mower_heading`, throttle constants.
- `custom_components/dreame_a2_mower/coordinator/_core.py` — replace render-cache attrs with `_base_png`, `_base_png_mode`, `_base_png_md5`, `_live_point_seq`, `_latest_point`, `_track_snapshot`.
- `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py`, `_cloud_state.py` — rewire trigger sites to the new methods.
- `custom_components/dreame_a2_mower/_camera_map.py` — publish stream attributes; `entity_picture` serves the base PNG; recorder-exclude.

**Client (JS, `custom_components/dreame_a2_mower/www/`)**
- `_dreame-map-core.js` — **new shared.** `projectPoint`, `iconRotation`, `buildMowerIcon`, trail-append helpers. Exposed both as ES exports (for node tests) and attached to a global for the cards.
- `dreame-mower-map-card.js` — **new.** Live incremental animation card.
- `dreame-mower-replay-card.js` — swap the round `#head` circle for the shared directional icon.
- `dreame-mower-live-image-card.js` — **delete** (superseded for the live map).

**Tests**
- `tests/map_render/test_background_mode.py`, `tests/map_render/test_render_base.py`
- `tests/coordinator/test_live_stream_publish.py`
- `tests/integration/test_map_camera_attributes.py`
- `tests/protocol/test_icon_direction_corpus.py` — corpus-backed regression guard.
- `tests/js/icon_math.test.mjs` — node test for `projectPoint`/`iconRotation`.

**Docs / SoT**
- `custom_components/dreame_a2_mower/entity-inventory.yaml`, `inventory.yaml` — per fact-discipline.
- `dashboards/mower/dashboard.yaml` — swap live-map card.

---

## Task 1: `BackgroundMode` enum + state-machine projection

**Files:**
- Create: `custom_components/dreame_a2_mower/map_render/background.py`
- Create test: `tests/map_render/test_background_mode.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/map_render/test_background_mode.py
import pytest
from custom_components.dreame_a2_mower.map_render.background import (
    BackgroundMode, background_mode_for,
)
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    MowSession, CurrentActivity,
)
from custom_components.dreame_a2_mower.mower.state import ActionMode

ACTIVE = [
    CurrentActivity.MOWING, CurrentActivity.PAUSED, CurrentActivity.REPOSITIONING,
    CurrentActivity.RETURNING, CurrentActivity.CHARGE_RESUME,
    CurrentActivity.CRUISING_TO_POINT, CurrentActivity.FAST_MAPPING,
    CurrentActivity.DRIVING_BLADES_UP,
]

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/map_render/test_background_mode.py -v`
Expected: FAIL — `ModuleNotFoundError: ...map_render.background`.

- [ ] **Step 3: Write minimal implementation**

```python
# custom_components/dreame_a2_mower/map_render/background.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/map_render/test_background_mode.py -v`
Expected: PASS (all params).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render/background.py tests/map_render/test_background_mode.py
git commit -m "feat(live-map): BackgroundMode projection from state-machine activity"
```

---

## Task 2: `render_base` — base PNG by background mode

Replaces `render_main_view`'s idle-preview dispatch with a mode-keyed base renderer that draws **no trail and no icon**. Reuses the existing `_render_pre_start_*` builders and `render_base_map`.

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render/main_view.py`
- Create test: `tests/map_render/test_render_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/map_render/test_render_base.py
import io
from PIL import Image
from custom_components.dreame_a2_mower.map_render.main_view import render_base
from custom_components.dreame_a2_mower.map_render.background import BackgroundMode
from tests.map_render.conftest import make_map_data  # existing fixture helper

def _png_size(b):
    return Image.open(io.BytesIO(b)).size

def test_render_base_returns_png_for_each_mode():
    md = make_map_data()  # a small synthetic MapData with one mowing zone
    for mode in BackgroundMode:
        png = render_base(md, background_mode=mode)
        assert isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n"
        assert _png_size(png) == (md.width_px, md.height_px)

def test_green_and_stripes_differ():
    md = make_map_data()
    assert render_base(md, background_mode=BackgroundMode.GREEN) != \
           render_base(md, background_mode=BackgroundMode.STRIPES)
```

> If `tests/map_render/conftest.py::make_map_data` does not exist, create it by
> reusing the MapData construction already used in
> `tests/test_render_pre_start_edge_spot.py` (copy its fixture, factored into the
> conftest). Check that file first.

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/map_render/test_render_base.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_base'`.

- [ ] **Step 3: Write minimal implementation**

Add to `map_render/main_view.py` (keep the existing `_render_pre_start_with_stripes`, `_render_pre_start_edge`, `_render_pre_start_spot`, `STRIPE_WIDTH_MM`; they are reused):

```python
def render_base(
    map_data: "MapData",
    *,
    background_mode,                      # BackgroundMode
    state: object | None = None,
    map_id: int = 0,
    palette: dict | None = None,
    obstacle_polygons_m: "list[list[tuple[float, float]]] | None" = None,
) -> bytes:
    """Render the live map's BASE PNG for the given background mode.

    No trail, no mower icon — those are drawn client-side by the map card.
    GREEN  -> dark-green active lawn (+ optional idle obstacle overlay).
    STRIPES-> dark lawn + next-mow stripe overlay (needs ``state`` + ``map_id``).
    EDGE   -> light lawn + dotted boundary.
    SPOT   -> light lawn + dotted spot rectangles.
    """
    from ..mower.state import ActionMode
    from .._render_direction import next_direction
    from .._render_stripes import compute_stripe_overlay
    from .background import BackgroundMode

    if background_mode == BackgroundMode.STRIPES and state is not None:
        return _render_pre_start_with_stripes(
            map_data, state=state, map_id=int(map_id), palette=palette,
            next_direction_fn=next_direction,
            compute_stripe_overlay_fn=compute_stripe_overlay,
        )
    if background_mode == BackgroundMode.EDGE:
        return _render_pre_start_edge(map_data, palette=palette)
    if background_mode == BackgroundMode.SPOT:
        return _render_pre_start_spot(map_data, palette=palette)
    # GREEN (active) or STRIPES-without-state fallback: plain dark lawn,
    # optionally with the between-session obstacle overlay.
    return render_base_map(
        map_data, palette=palette, lawn_mode="dark",
        obstacles=obstacle_polygons_m,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/map_render/test_render_base.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render/main_view.py tests/map_render/test_render_base.py tests/map_render/conftest.py
git commit -m "feat(live-map): render_base draws base+background only (no trail/icon)"
```

---

## Task 3: Coordinator — base render on activity transition

Replace the live-PNG render path with: compute `background_mode`, and re-render the base **only when the mode or map md5 changes**. This is the #1 fix at the coordinator level.

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_core.py` (cache attrs)
- Modify: `custom_components/dreame_a2_mower/coordinator/_rendering.py`
- Create test: `tests/coordinator/test_base_render_on_activity.py`

- [ ] **Step 1: Add cache attrs to `_core.py.__init__`**

Replace the render-cache block (around `_core.py:229`, the `_main_view_png` / `_active_map_base_png` group) with:

```python
        # Live-map base PNG cache (rehaul 2026-05-31). The composited live PNG
        # is gone: the server renders only the base, keyed on background mode +
        # map md5. The trail + mower icon are drawn client-side from the
        # published stream (see _publish_live_stream).
        self._base_png: bytes | None = None
        self._base_png_mode: object | None = None    # BackgroundMode of _base_png
        self._base_png_md5: str | None = None         # MapData.md5 of _base_png
        # Live position stream published on the map camera entity.
        self._live_point_seq: int = 0
        self._latest_point: list | None = None        # [x_m, y_m, heading|None, t]
        self._track_snapshot: list | None = None       # full session-so-far, set on begin
```

Delete these now-unused attrs from `_core.py`: `_main_view_png`, `_active_map_base_png`, `_active_map_base_md5`, `_live_trail_dirty`, `_last_live_render_unix`, `_last_between_session_render_x`, `_last_between_session_render_y`. (Grep for each and remove its assignment + comments.)

- [ ] **Step 2: Write the failing test**

```python
# tests/coordinator/test_base_render_on_activity.py
import pytest
from custom_components.dreame_a2_mower.map_render.background import BackgroundMode
from tests.coordinator.conftest import make_coordinator  # existing helper

@pytest.mark.asyncio
async def test_base_rerenders_when_mode_changes(monkeypatch):
    coord = make_coordinator()  # with one active map in cloud_state
    renders = []
    async def fake_executor(fn, *a, **k):
        renders.append(getattr(fn, "func", fn))
        return b"\x89PNG\r\n\x1a\n" + bytes(8)
    monkeypatch.setattr(coord.hass, "async_add_executor_job", fake_executor)

    # First render at idle -> STRIPES
    coord._set_activity(IDLE_SNAPSHOT)        # helper sets state_machine snapshot
    await coord._render_base()
    assert coord._base_png_mode is BackgroundMode.STRIPES
    n_after_first = len(renders)

    # Same mode again -> no new render (md5 + mode unchanged)
    await coord._render_base()
    assert len(renders) == n_after_first

    # Activity flips to REPOSITIONING -> GREEN -> re-render
    coord._set_activity(REPOSITIONING_SNAPSHOT)
    await coord._render_base()
    assert coord._base_png_mode is BackgroundMode.GREEN
    assert len(renders) == n_after_first + 1
```

> Use the coordinator test helpers already in `tests/coordinator/` (see
> `tests/coordinator/test_inject_live_map_meta.py` for how a coordinator is
> built with a stub hass + cloud_state). `_set_activity`,
> `IDLE_SNAPSHOT`/`REPOSITIONING_SNAPSHOT` are thin local fixtures that set
> `coord.state_machine._snapshot` via `dataclasses.replace`.

- [ ] **Step 3: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_base_render_on_activity.py -v`
Expected: FAIL — `_render_base` / `_compute_background_mode` not defined.

- [ ] **Step 4: Implement in `_rendering.py`**

Replace `_render_main_view`, `_render_active_map_base`, `_rerender_live_trail`, `_current_mower_heading`, `_maybe_rerender_between_session_icon`, `_StateProxy`, and the throttle constants with:

```python
    def _compute_background_mode(self):
        """BackgroundMode for the current state-machine snapshot."""
        from ..map_render.background import background_mode_for
        snap = self.state_machine.snapshot()
        return background_mode_for(
            mow_session=snap.mow_session,
            current_activity=snap.current_activity,
            action_mode=getattr(self.data, "action_mode", None),
        )

    async def _render_base(self) -> None:
        """Render the active map's base PNG, keyed on (background_mode, md5).

        No-ops when neither the mode nor the map md5 changed since the last
        render. This is the ONLY server-side live-map render; the trail + icon
        are client-side. Fires on every activity transition (cheap because of
        the dedup) so the stripes->green flip lands within one tick of the
        state machine entering an active activity — ~41s before the first move.
        """
        active_id = self._active_map_id
        if active_id is None:
            return
        map_data = self.cloud_state.maps_by_id.get(active_id)
        if map_data is None:
            return
        mode = self._compute_background_mode()
        md5 = getattr(map_data, "md5", None)
        if (
            self._base_png is not None
            and self._base_png_mode == mode
            and self._base_png_md5 == md5
        ):
            return  # fresh render already cached

        from ..map_render.background import BackgroundMode
        obstacles = (
            None if mode == BackgroundMode.GREEN
            else await self._load_last_session_obstacles(active_id)
        )
        from functools import partial
        from ..map_render import render_base
        png = await self.hass.async_add_executor_job(
            partial(
                render_base, map_data,
                background_mode=mode, state=self.data,
                map_id=active_id, obstacle_polygons_m=obstacles,
            )
        )
        if png:
            self._base_png = png
            self._base_png_mode = mode
            self._base_png_md5 = md5
            LOGGER.debug(
                "[MAP] base render: bg=%s map=%s md5=%s",
                mode.value, active_id, md5,
            )
```

Keep `_load_last_session_obstacles` and `_current_mower_position` (the latter may still be referenced by the stream publisher — Task 4).

- [ ] **Step 5: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_base_render_on_activity.py -v`
Expected: PASS.

- [ ] **Step 6: Rewire trigger sites** (replace `_render_main_view()` / `_render_active_map_base()` calls with `_render_base()`):

- `_cloud_state.py:162` and `:165` → single `await self._render_base()`.
- `_mqtt_handlers.py:158` (MAPL/active-map change) → `hass.async_create_task(self._render_base())`.
- `_mqtt_handlers.py:269` (s2p1 REPOSITIONING trigger) → `self.hass.async_create_task(self._render_base())`. **Keep this trigger** — it's now the primary #1 fix path (activity transition → base re-render).
- `_mqtt_handlers.py:600` (dock arrival) → `self._render_base()`.
- `_mqtt_handlers.py:1056` (post-undock) → `self._render_base()`.
- `_rendering.py` internal calls — removed with the deleted methods.

Add a render on **every** activity transition: in the state-machine glue in `_mqtt_handlers.handle_property_push` after `handle_mqtt_property`, when `snapshot().current_activity` changed, `hass.async_create_task(self._render_base())`. (Search for where the snapshot is read after `handle_mqtt_property`; add a `prev_activity != new_activity` guard so we don't spawn a render per push.)

- [ ] **Step 7: Run the coordinator + mqtt test suites**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator tests/state_machine -q`
Expected: PASS (fix any test still referencing `_render_main_view`/`_main_view_png` — those move to Task 5/6).

- [ ] **Step 8: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_core.py custom_components/dreame_a2_mower/coordinator/_rendering.py custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py custom_components/dreame_a2_mower/coordinator/_cloud_state.py tests/coordinator/test_base_render_on_activity.py
git commit -m "feat(live-map): base render keyed on background mode; trigger on activity transition (fixes #1 stripe lag)"
```

---

## Task 4: Coordinator — publish the live position stream

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_rendering.py` (add `_publish_live_stream`)
- Modify: `custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py` (call it on s1p4 append; seed snapshot on session begin)
- Create test: `tests/coordinator/test_live_stream_publish.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/coordinator/test_live_stream_publish.py
import pytest
from tests.coordinator.conftest import make_coordinator

def test_publish_increments_seq_and_uses_byte_heading():
    coord = make_coordinator()
    coord._publish_live_point(x_m=1.0, y_m=2.0, heading_deg=88.0, t=100.0)
    coord._publish_live_point(x_m=1.5, y_m=2.2, heading_deg=90.0, t=105.0)
    assert coord._live_point_seq == 2
    assert coord._latest_point == [1.5, 2.2, 90.0, 105.0]

def test_publish_null_heading_for_beacon():
    coord = make_coordinator()
    coord._publish_live_point(x_m=1.0, y_m=2.0, heading_deg=None, t=100.0)
    assert coord._latest_point == [1.0, 2.0, None, 100.0]

def test_begin_session_resets_snapshot_and_seq():
    coord = make_coordinator()
    coord._publish_live_point(x_m=1.0, y_m=2.0, heading_deg=88.0, t=100.0)
    coord._begin_live_stream(t=200.0)
    assert coord._live_point_seq == 0
    assert coord._track_snapshot == []
    assert coord._latest_point is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_live_stream_publish.py -v`
Expected: FAIL — methods undefined.

- [ ] **Step 3: Implement in `_rendering.py`**

```python
    def _begin_live_stream(self, *, t: float) -> None:
        """Reset the published live stream at session begin / cold-start."""
        self._live_point_seq = 0
        self._latest_point = None
        self._track_snapshot = []

    def _publish_live_point(
        self, *, x_m: float, y_m: float, heading_deg: float | None, t: float
    ) -> None:
        """Append one position to the published live stream.

        Heading is the byte heading (present on 99.2% of frames) or None for
        the 0.8% beacons — the client derives a fallback from the screen vector.
        Only the latest point + seq cross the wire each push; the client
        accumulates the trail. ``_track_snapshot`` is the catch-up payload for a
        freshly-loaded card.
        """
        pt = [float(x_m), float(y_m),
              None if heading_deg is None else float(heading_deg), float(t)]
        self._live_point_seq += 1
        self._latest_point = pt
        if self._track_snapshot is not None:
            self._track_snapshot.append(pt)
        LOGGER.debug(
            "[MAP] publish: seq=%d pt=(%.2f,%.2f) hdg=%s",
            self._live_point_seq, x_m, y_m,
            f"{heading_deg:.1f}(byte)" if heading_deg is not None else "none(vector)",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator/test_live_stream_publish.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into the s1p4 append path** in `_mqtt_handlers.py`

In `_on_state_update`, inside the `if self.live_map.total_points() > before_pts:` block (around `:498`), **replace** the throttled `_rerender_live_trail` task with:

```python
                self._live_map_dirty = True
                self._publish_live_point(
                    x_m=float(new_state.position_x_m),
                    y_m=float(new_state.position_y_m),
                    heading_deg=(
                        float(new_state.position_heading_deg)
                        if new_state.position_heading_deg is not None else None
                    ),
                    t=float(now_unix),
                )
                # Push entity state so the camera attributes update on the frontend.
                self.async_update_listeners()
```

In `begin_session` handling (around `_mqtt_handlers.py:393`), call `self._begin_live_stream(t=float(now_unix))` right after `self.live_map.begin_session(now_unix)`.

Delete the now-dead `_BETWEEN_SESSION_*` constants and the `_maybe_rerender_between_session_icon` import/call (`_mqtt_handlers.py:1075`).

- [ ] **Step 6: Run the mqtt handler tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/coordinator -q`
Expected: PASS (fix references to removed throttle symbols).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_rendering.py custom_components/dreame_a2_mower/coordinator/_mqtt_handlers.py tests/coordinator/test_live_stream_publish.py
git commit -m "feat(live-map): publish position/heading stream instead of compositing per frame"
```

---

## Task 5: Camera entity — publish projection + stream; recorder-exclude

**Files:**
- Modify: `custom_components/dreame_a2_mower/_camera_map.py`
- Modify: `custom_components/dreame_a2_mower/__init__.py` (recorder exclusion, if applicable) — or document a recorder `exclude` glob.
- Create test: `tests/integration/test_map_camera_attributes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_map_camera_attributes.py
from custom_components.dreame_a2_mower._camera_map import DreameA2MapCamera
from tests.coordinator.conftest import make_coordinator

def test_camera_exposes_projection_and_stream():
    coord = make_coordinator()  # active map id=1 with bx2/by2/grid/height set
    coord._active_map_id = 1
    coord._live_point_seq = 7
    coord._latest_point = [3.21, -1.04, 88.2, 1000.0]
    coord._track_snapshot = [[3.0, -1.0, 80.0, 995.0], [3.21, -1.04, 88.2, 1000.0]]
    from custom_components.dreame_a2_mower.map_render.background import BackgroundMode
    coord._base_png_mode = BackgroundMode.GREEN
    cam = DreameA2MapCamera.__new__(DreameA2MapCamera)
    cam.coordinator = coord
    attrs = cam.extra_state_attributes
    proj = attrs["map_projection"]
    assert set(proj) >= {"bx2_mm", "by2_mm", "pixel_size_mm", "width_px", "height_px"}
    assert attrs["point_seq"] == 7
    assert attrs["latest_point"] == [3.21, -1.04, 88.2, 1000.0]
    assert attrs["background_mode"] == "green"
    assert "calibration_points" not in attrs  # removed in the rehaul
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_camera_attributes.py -v`
Expected: FAIL — `map_projection`/`point_seq` absent; `calibration_points` present.

- [ ] **Step 3: Rewrite `DreameA2MapCamera`** in `_camera_map.py`

`async_camera_image` and `entity_picture` now serve `coordinator._base_png` (the base, not a composited view):

```python
    async def async_camera_image(self, width=None, height=None):
        return self.coordinator._base_png

    @property
    def entity_picture(self):
        png = self.coordinator._base_png
        if not png:
            return None
        import hashlib
        v = hashlib.sha1(png).hexdigest()[:12]
        return f"/api/dreame_a2_mower/map.png?v={v}"
```

Replace the `calibration_points` block in `extra_state_attributes` with the
`map_projection` dict and the live stream:

```python
        md = self.coordinator.cloud_state.maps_by_id.get(self.coordinator._active_map_id)
        if md is not None:
            try:
                attrs["map_projection"] = {
                    "bx1_mm": float(md.bx1), "by1_mm": float(md.by1),
                    "bx2_mm": float(md.bx2), "by2_mm": float(md.by2),
                    "pixel_size_mm": float(md.pixel_size_mm),
                    "width_px": int(md.width_px), "height_px": int(md.height_px),
                }
            except (TypeError, ValueError, AttributeError):
                pass
        attrs["point_seq"] = self.coordinator._live_point_seq
        attrs["latest_point"] = self.coordinator._latest_point
        attrs["track_snapshot"] = self.coordinator._track_snapshot
        mode = getattr(self.coordinator, "_base_png_mode", None)
        attrs["background_mode"] = getattr(mode, "value", None)
```

Update `_handle_coordinator_update` to rotate the token when `_base_png` changes (rename `_main_view_png` → `_base_png`). Keep `image_version` = sha1 of `_base_png`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration/test_map_camera_attributes.py -v`
Expected: PASS.

- [ ] **Step 5: Recorder exclusion**

The streamed attributes must not bloat the recorder DB. In `__init__.py` (or wherever the integration documents recorder behavior), the live-map camera should be excluded from history. Since HA recorder config is user-owned, add a **note in the bundled dashboard README / config docs** and set `_attr_entity_registry_enabled_default` unaffected — preferred: mark the streamed attributes non-recorded by keeping them only on the entity that the user excludes. Document the recommended `recorder: exclude: entity_globs: ["camera.dreame_a2_mower_map"]` in `docs/observability` (or the dashboard deploy doc). (Code-only enforcement isn't available for attribute size; documentation + the single-point `latest_point` stream is the mitigation per spec §10.)

- [ ] **Step 6: Run integration tests**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/integration -q`
Expected: PASS (fix any test asserting `calibration_points`).

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/_camera_map.py tests/integration/test_map_camera_attributes.py docs/
git commit -m "feat(live-map): camera publishes map_projection + live point stream; serves base PNG"
```

---

## Task 6: Delete dead PIL render code

**Files:**
- Delete: `custom_components/dreame_a2_mower/map_render/trail.py`
- Modify: `custom_components/dreame_a2_mower/map_render/main_view.py` (remove trail branch + `_composite_mower_icon`), `map_render/__init__.py`, `map_render/base_map.py` (keep `_mower_icon` only if still used by work-log; else remove).

- [ ] **Step 1: Find all consumers**

Run:
```bash
cd custom_components/dreame_a2_mower
grep -rn "render_with_trail\|render_main_view\|_composite_mower_icon\|map_render.trail" . ../../tests
```
Expected: only `work_log.py` (archived render) may use `render_with_trail`.

- [ ] **Step 2: Repoint work-log if needed**

If `map_render/work_log.py` imports `render_with_trail`, that path renders **archived** sessions server-side. The rehaul keeps archived server rendering as-is for the work-log camera (the replay *card* is separate). So **keep** a minimal trail renderer for work-log only: move the legs_timeline branch of `render_with_trail` into `work_log.py` as a private `_render_archived_trail`, dropping the live-icon kwargs. If work-log does not use it, skip.

- [ ] **Step 3: Delete `trail.py` and the live composited path**

```bash
git rm custom_components/dreame_a2_mower/map_render/trail.py
```
In `main_view.py` delete `render_main_view` (the old composited entry) and `_composite_mower_icon`. In `__init__.py` remove `render_main_view`, `render_with_trail` from `__all__`/imports; add `render_base`, and re-export `BackgroundMode`, `background_mode_for` from `.background`.

- [ ] **Step 4: Run the full suite**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: PASS at the 1591-baseline (minus deleted tests, plus new ones). Fix any import error from removed symbols.

- [ ] **Step 5: Commit**

```bash
git add -A custom_components/dreame_a2_mower/map_render tests
git commit -m "refactor(live-map): delete trail.py + composited live PNG path (3 compositors -> 0)"
```

---

## Task 7: Shared client icon math + node test

Extract the pure geometry so it is unit-testable and shared by both cards. This is where the #3 flip convention is pinned.

**Files:**
- Create: `custom_components/dreame_a2_mower/www/_dreame-map-core.js`
- Create: `tests/js/icon_math.test.mjs`

- [ ] **Step 1: Write the failing node test**

```javascript
// tests/js/icon_math.test.mjs
import assert from "node:assert/strict";
import { projectPoint, iconRotation } from
  "../../custom_components/dreame_a2_mower/www/_dreame-map-core.js";

const proj = { bx2_mm: 5000, by2_mm: 5000, pixel_size_mm: 50, width_px: 100, height_px: 100 };

// Cloud +X moves the icon LEFT on screen; cloud +Y moves it DOWN.
const a = projectPoint(0, 0, proj);     // (100,0) preflip py=100 -> py=0
const b = projectPoint(1, 0, proj);     // x_m=1 -> 1000mm -> px=(5000-1000)/50=80
assert.ok(b[0] < a[0], "cloud +X -> screen left");

// iconRotation: byte heading 0deg (cloud +X) must point the icon to SCREEN LEFT.
// For an up-pointing source icon, screen-left = rotate 270 (CW). Formula: (270 - H) % 360.
assert.equal(iconRotation(0, null, null), 270);
assert.equal(iconRotation(90, null, null), 180);   // cloud +Y -> screen down -> 180
assert.equal(iconRotation(180, null, null), 90);
assert.equal(iconRotation(270, null, null), 0);

// Vector fallback when heading is null: derive from screen-space delta.
// prev->cur moving cloud +X (screen left): expect 270.
const prev = projectPoint(0, 0, proj);
const cur = projectPoint(1, 0, proj);
assert.equal(Math.round(iconRotation(null, prev, cur)), 270);

console.log("icon_math: all assertions passed");
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/js/icon_math.test.mjs`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `_dreame-map-core.js`**

```javascript
// Shared geometry for the Dreame map cards (live + replay).
// ES exports for node tests; also attached to window for the browser cards.

export function projectPoint(x_m, y_m, proj) {
  const px = (proj.bx2_mm - x_m * 1000) / proj.pixel_size_mm;
  const py_pre = (proj.by2_mm - y_m * 1000) / proj.pixel_size_mm;
  const py = proj.height_px - py_pre;        // base PNG is FLIP_TOP_BOTTOM'd
  return [px, py];
}

// Screen travel angle (SVG y-down) for a cloud-frame heading H (deg, 0=+X):
//   cloud (cosH, sinH) -> screen (-cosH, +sinH) -> theta = atan2(sinH, -cosH) = 180 - H
// For an up-pointing source icon, SVG rotate(A) (CW-positive) with A = theta + 90:
//   A = (270 - H) mod 360.
// Verified against the corpus in tests/protocol/test_icon_direction_corpus.py.
export function iconRotation(headingDeg, prevScreenXY, curScreenXY) {
  let H = headingDeg;
  if (H == null) {
    if (!prevScreenXY || !curScreenXY) return 0;
    const dpx = curScreenXY[0] - prevScreenXY[0];
    const dpy = curScreenXY[1] - prevScreenXY[1];
    if (Math.hypot(dpx, dpy) < 1) return null;   // <~1px: keep last angle (caller decides)
    // screen theta -> equivalent A directly (no cloud round-trip needed):
    const theta = Math.atan2(dpy, dpx) * 180 / Math.PI;
    return ((theta + 90) % 360 + 360) % 360;
  }
  return ((270 - H) % 360 + 360) % 360;
}

// Build the directional mower icon as an SVG <g> using the bundled raster
// mower icon (exact top-down copy of the mower -> front/back unambiguous).
// iconUrl points at the same asset the server used for _mower_icon.
export function buildMowerIconSvg(iconUrl, sizePx) {
  return `<g id="mower" visibility="hidden">
    <image href="${iconUrl}" width="${sizePx}" height="${sizePx}"
           x="${-sizePx / 2}" y="${-sizePx / 2}" />
  </g>`;
}

if (typeof window !== "undefined") {
  window.DreameMapCore = { projectPoint, iconRotation, buildMowerIconSvg };
}
```

> The raster icon asset: locate the file `base_map.py:_mower_icon` opens
> (around `base_map.py:49`) and copy/expose it under `www/` as a static asset
> served by the integration, or inline it as a data-URI in the card. Record the
> resolved path/URL in the card's config docstring.

- [ ] **Step 4: Run test to verify it passes**

Run: `node tests/js/icon_math.test.mjs`
Expected: prints `icon_math: all assertions passed`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/www/_dreame-map-core.js tests/js/icon_math.test.mjs
git commit -m "feat(live-map): shared client icon math (projection + single rotation convention)"
```

---

## Task 8: Corpus-backed icon-direction regression test

The guard that was missing — proves the §5 convention holds across all 71k real frames.

**Files:**
- Create: `tests/protocol/test_icon_direction_corpus.py`

- [ ] **Step 1: Write the test** (it runs the convention, not new code)

```python
# tests/protocol/test_icon_direction_corpus.py
"""Assert the icon rotation derived from the byte heading points along the
on-screen motion direction, across the probe-log corpus. Pins the §5 flip
convention; fails loudly if a renderer regresses it."""
import glob, json, math, os
import pytest

CORPUS = sorted(glob.glob("/data/claude/homeassistant/probe_log_*.jsonl"))
PROJ = {"bx2_mm": 0.0, "pixel_size_mm": 50.0, "height_px": 1000}  # affine cancels in angle

def _pose(v):
    b0,b1,b2,b3,b4 = v[1],v[2],v[3],v[4],v[5]
    x = ((b2 & 0x0F) << 16) | (b1 << 8) | b0
    if x & 0x80000: x -= 0x100000
    y = (b4 << 12) | (b3 << 4) | ((b2 & 0xF0) >> 4)
    if y & 0x80000: y -= 0x100000
    return x*10, y*10

def _icon_rotation(H):  # mirror of _dreame-map-core.iconRotation byte branch
    return (270 - H) % 360

def _screen_xy(x_mm, y_mm):
    px = (PROJ["bx2_mm"] - x_mm) / PROJ["pixel_size_mm"]
    py = PROJ["height_px"] - (0.0 - y_mm) / PROJ["pixel_size_mm"]
    return px, py

@pytest.mark.skipif(not CORPUS, reason="probe corpus not present")
def test_icon_points_along_screen_motion():
    errs = []
    for fn in CORPUS:
        prev = None
        with open(fn) as f:
            for line in f:
                if '"properties_changed"' not in line: continue
                try: o = json.loads(line)
                except Exception: continue
                for p in (o.get("params") or []):
                    if p.get("siid")==1 and p.get("piid")==4 and isinstance(p.get("value"),list) and len(p["value"])==33:
                        v = p["value"]; x,y = _pose(v); H = v[6]/255.0*360.0
                        sx, sy = _screen_xy(x, y)
                        if prev is not None:
                            dpx, dpy = sx-prev[0], sy-prev[1]
                            if math.hypot(dpx, dpy) > 0.1:  # >5cm at grid=50
                                motion = math.degrees(math.atan2(dpy, dpx))
                                # icon points at (rotation - 90) screen-deg (up-source)
                                icon_dir = _icon_rotation(H) - 90
                                e = abs((icon_dir - motion + 180) % 360 - 180)
                                errs.append(e)
                        prev = (sx, sy)
    assert errs, "no qualifying frames"
    errs.sort()
    median = errs[len(errs)//2]
    p90 = errs[int(len(errs)*0.9)]
    assert median < 10, f"median icon-vs-motion error {median:.1f} (flip regressed?)"
    assert p90 < 45, f"p90 {p90:.1f}"
```

- [ ] **Step 2: Run it**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/protocol/test_icon_direction_corpus.py -v`
Expected: PASS (median ~2.5°). **If it fails, the §5 formula sign is wrong — fix `iconRotation` AND this mirror together until it passes, then update the spec §5 formula to match.**

- [ ] **Step 3: Commit**

```bash
git add tests/protocol/test_icon_direction_corpus.py
git commit -m "test(live-map): corpus-backed icon-direction regression guard"
```

---

## Task 9: Live map card (incremental animation)

**Files:**
- Create: `custom_components/dreame_a2_mower/www/dreame-mower-map-card.js`

- [ ] **Step 1: Implement the card**

```javascript
// Live map card: SVG base <image> + client-accumulated trail + directional
// mower icon, animated between ~5s position messages. Reads the published
// stream (map_projection, point_seq, latest_point, track_snapshot,
// background_mode) from the camera entity. Replaces dreame-mower-live-image-card
// for the live map.
import { projectPoint, iconRotation, buildMowerIconSvg } from "./_dreame-map-core.js";

const ICON_PX = 32;
const MIN_MS = 1000, MAX_MS = 7000;   // glide duration clamp (cadence ~5s)

class DreameMowerMapCard extends HTMLElement {
  setConfig(cfg) {
    if (!cfg || !cfg.entity) throw new Error("entity is required");
    this._cfg = cfg; this._seq = -1; this._trail = [];
    this._iconAt = null; this._iconAngle = 0; this._anim = null;
  }
  set hass(hass) {
    this._hass = hass;
    const ent = hass.states[this._cfg.entity];
    if (!ent || !ent.attributes) return;
    const a = ent.attributes;
    if (!a.map_projection || !a.entity_picture) return;
    this._ensureSvg(a);
    // Background image (base) — swap if URL changed (background flip / map md5).
    const img = this.shadowRoot.getElementById("base");
    if (img && img.getAttribute("href") !== a.entity_picture) {
      img.setAttribute("href", a.entity_picture);
    }
    // Cold start / gap -> seed from snapshot.
    if (a.point_seq != null && (this._seq < 0 || a.point_seq < this._seq
        || a.point_seq - this._seq > 1)) {
      this._seedFromSnapshot(a);
    }
    // New point -> animate.
    if (a.latest_point && a.point_seq > this._seq) {
      this._seq = a.point_seq;
      this._onNewPoint(a.latest_point, a.map_projection);
    }
  }
  _ensureSvg(a) {
    if (this.shadowRoot && this.shadowRoot.getElementById("svg")) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const p = a.map_projection;
    const iconUrl = this._cfg.icon_url || "/dreame_a2_mower_static/mower-icon.png";
    this.shadowRoot.innerHTML = `
      <style>:host{display:block} svg{width:100%;height:auto}
        .trail{fill:none;stroke:rgb(178,223,138);stroke-width:3;
               stroke-linejoin:round;stroke-linecap:round}</style>
      <svg id="svg" viewBox="0 0 ${p.width_px} ${p.height_px}">
        <image id="base" href="${a.entity_picture}" x="0" y="0"
               width="${p.width_px}" height="${p.height_px}"/>
        <path id="trail" class="trail" d=""/>
        ${buildMowerIconSvg(iconUrl, ICON_PX)}
      </svg>`;
  }
  _seedFromSnapshot(a) {
    const snap = a.track_snapshot || [];
    this._trail = snap.map(pt => projectPoint(pt[0], pt[1], a.map_projection));
    this._redrawTrail();
    if (this._trail.length) {
      this._iconAt = this._trail[this._trail.length - 1];
      const last = snap[snap.length - 1];
      this._iconAngle = iconRotation(last[2],
        this._trail[this._trail.length - 2] || null, this._iconAt) ?? this._iconAngle;
      this._placeIcon();
    }
    this._seq = a.point_seq;
  }
  _onNewPoint(pt, proj) {
    const target = projectPoint(pt[0], pt[1], proj);
    const from = this._iconAt || target;
    const targetAngle = iconRotation(pt[2], this._iconAt, target);
    this._trail.push(target);
    this._redrawTrail();
    this._animateIcon(from, target,
      targetAngle == null ? this._iconAngle : targetAngle);
  }
  _redrawTrail() {
    const path = this.shadowRoot.getElementById("trail");
    if (!path) return;
    path.setAttribute("d", this._trail.map((q, i) =>
      `${i ? "L" : "M"} ${q[0].toFixed(1)} ${q[1].toFixed(1)}`).join(" "));
  }
  _animateIcon(from, to, toAngle) {
    if (this._anim) cancelAnimationFrame(this._anim);
    const dur = MAX_MS; // glide over the expected cadence; next point cancels
    const fromAngle = this._iconAngle;
    // shortest-arc rotation
    let dA = ((toAngle - fromAngle + 540) % 360) - 180;
    const start = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - start) / dur);
      const x = from[0] + (to[0] - from[0]) * k;
      const y = from[1] + (to[1] - from[1]) * k;
      this._iconAt = [x, y];
      this._iconAngle = fromAngle + dA * k;
      this._placeIcon();
      if (k < 1) this._anim = requestAnimationFrame(step);
    };
    this._anim = requestAnimationFrame(step);
  }
  _placeIcon() {
    const g = this.shadowRoot.getElementById("mower");
    if (!g || !this._iconAt) return;
    g.setAttribute("visibility", "visible");
    g.setAttribute("transform",
      `translate(${this._iconAt[0].toFixed(1)},${this._iconAt[1].toFixed(1)}) `
      + `rotate(${this._iconAngle.toFixed(1)})`);
  }
  getCardSize() { return 6; }
  static getStubConfig() { return { entity: "camera.dreame_a2_mower_map" }; }
}
if (!customElements.get("dreame-mower-map-card")) {
  customElements.define("dreame-mower-map-card", DreameMowerMapCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "dreame-mower-map-card",
    name: "Dreame Mower Live Map",
    description: "Animated live map: base + trail + directional mower icon." });
}
```

- [ ] **Step 2: Syntax check**

Run: `node --check custom_components/dreame_a2_mower/www/dreame-mower-map-card.js`
Expected: no output (valid). (ES `import` of a sibling resolves in the browser via the Lovelace resource; `--check` only validates syntax.)

- [ ] **Step 3: Serve the icon asset**

Register a static path for the mower icon so `icon_url` resolves. In `__init__.py` `async_setup_entry`, add (if not already serving `www/`):
```python
from homeassistant.components.http import StaticPathConfig
await hass.http.async_register_static_paths([
    StaticPathConfig("/dreame_a2_mower_static",
                     hass.config.path(f"custom_components/{DOMAIN}/www"), True),
])
```
Copy the `_mower_icon` source asset to `www/mower-icon.png`.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-map-card.js custom_components/dreame_a2_mower/www/mower-icon.png custom_components/dreame_a2_mower/__init__.py
git commit -m "feat(live-map): client SVG map card with interpolated directional icon"
```

---

## Task 10: Replay card — directional icon

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

- [ ] **Step 1: Swap the round marker for the shared icon**

At the SVG build (`replay-card.js:185`), replace the `<circle id="head">` with `buildMowerIconSvg(iconUrl, ICON_PX)` (import from `_dreame-map-core.js`). At the marker-position update (`:498-537`), replace the `cx/cy` set with a `transform="translate(x,y) rotate(A)"` where `A = iconRotation(headingAtPoint, prevScreenXY, curScreenXY)`. The archived track stores `heading_deg` per point (`live_map/state.py:283`), exposed in the leg `pts`/point records — read it; fall back to the screen vector when null.

- [ ] **Step 2: Syntax check**

Run: `node --check custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`
Expected: valid.

- [ ] **Step 3: Manual sanity** (note for executor)

Load a saved session in the replay card; confirm the icon now shows orientation along the path and matches the live card's icon.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "feat(replay): directional mower icon (shared core) replacing round marker"
```

---

## Task 11: Dashboard swap + remove obsolete card

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`
- Delete: `custom_components/dreame_a2_mower/www/dreame-mower-live-image-card.js`

- [ ] **Step 1: Find the live-map card in the live dashboard**

Run: `grep -n "camera.dreame_a2_mower_map\b\|live-image-card\|picture-entity" dashboards/mower/dashboard.yaml`
(The live dashboard is the `dashboards/mower/dashboard.yaml` directory file — see `reference_ha_dashboard_path`.)

- [ ] **Step 2: Replace the live-map card** with:

```yaml
- type: custom:dreame-mower-map-card
  entity: camera.dreame_a2_mower_map
```

- [ ] **Step 3: Register the card resource**

Ensure `_dreame-map-core.js`, `dreame-mower-map-card.js`, and the updated replay card are registered as Lovelace resources (module type). Do NOT rely on `add_extra_js_url` (it never registered at render time on YAML-mode dashboards — `project_live_image_card_render_bug`). Add explicit `lovelace.resources` entries or document the manual resource add.

- [ ] **Step 4: Delete the obsolete card**

```bash
git rm custom_components/dreame_a2_mower/www/dreame-mower-live-image-card.js
```

- [ ] **Step 5: Deploy + browser-reload** (executor, live box)

Per `reference_ha_dashboard_deploy`: backup, SCP `dashboards/mower/` + `www/*.js` to the live box, browser hard-reload (no HA restart). Verify the map renders (watch for `createErrorCardElement` in the browser console, NOT the HA server log — `reference_lovelace_card_errors`).

- [ ] **Step 6: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "feat(live-map): swap dashboard to animated map card; drop live-image-card"
```

---

## Task 12: Inventory + observability close-out

**Files:**
- Modify: `custom_components/dreame_a2_mower/entity-inventory.yaml`
- Modify: `custom_components/dreame_a2_mower/inventory.yaml`

- [ ] **Step 1: Update entity-inventory** for `camera.dreame_a2_mower_map`

Append a `verifications:` record (today's date) noting the entity now serves the base PNG and publishes `map_projection` + `point_seq` + `latest_point` + `track_snapshot` + `background_mode`; `calibration_points` removed. Status `presumed` (code-read) unless live-verified.

- [ ] **Step 2: Update inventory** for the s1p4 heading byte

Append a `verifications:` record to the `s1p4` heading-byte entry: corpus-validated byte-heading vs motion-vector median **2.5°** error (refines the prior 13°-median note), `status: verified`, `evidence: "analyze_move_corpus.py over probe_log_*.jsonl (9 logs, 69,639 pairs)"`. Update `status.last_seen` to today.

- [ ] **Step 3: Run the inventory audit**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/inventory_audit.py`
Expected: PASS (CI `inventory-touch-gate`).

- [ ] **Step 4: Full suite + commit**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest -q`
Expected: green.

```bash
git add custom_components/dreame_a2_mower/entity-inventory.yaml custom_components/dreame_a2_mower/inventory.yaml
git commit -m "docs(inventory): record live-map camera attrs + corpus-validated s1p4 heading (2.5deg)"
```

---

## Self-Review

**Spec coverage:**
- §4.1 background_mode projection → Task 1. ✓
- §4.2 base-only render → Tasks 2, 3, 6. ✓
- §4.3 publish stream + projection attrs + recorder exclusion → Tasks 4, 5. ✓
- §4.4 shared client card (live + replay) → Tasks 7, 9, 10. ✓
- §5 single icon/heading convention → Tasks 7, 8. ✓
- §6 trigger consolidation → Task 3 step 6, Task 4 step 5. ✓
- §8 corpus test → Task 8. ✓
- §9 observability log lines → Tasks 3, 4 (LOGGER.debug lines). ✓
- §10 rollout/recorder/card-registration → Tasks 5, 11. ✓
- §11 resolved decisions (full trail, raster icon, base-only, FAST_MAPPING/DRIVING_BLADES_UP green) → Tasks 1, 7, 9. ✓
- Fact discipline → Task 12. ✓

**Placeholder scan:** No "TBD/handle edge cases" steps; the two "locate the existing fixture/asset" notes (Task 2 conftest, Task 7 icon asset) point at exact source files. The recorder-exclusion (Task 5 step 5) is documentation-only by necessity (attribute size isn't code-enforceable) — stated explicitly, not deferred.

**Type consistency:** `BackgroundMode`, `background_mode_for(mow_session=, current_activity=, action_mode=)`, `_render_base()`, `_compute_background_mode()`, `_publish_live_point(x_m=,y_m=,heading_deg=,t=)`, `_begin_live_stream(t=)`, `_base_png`/`_base_png_mode`/`_base_png_md5`, `_live_point_seq`/`_latest_point`/`_track_snapshot` are used identically across server tasks. `projectPoint`/`iconRotation`/`buildMowerIconSvg` identical across JS tasks; the Python corpus test mirrors `iconRotation`'s byte branch as `_icon_rotation` and is reconciled in Task 8 step 2.

**Known coupling:** Task 8 (corpus test) and Task 7 (`iconRotation`) must agree on the sign; Task 8 step 2 makes fixing them together explicit. If the sign flips, the spec §5 formula is updated to match (the test is authoritative).
