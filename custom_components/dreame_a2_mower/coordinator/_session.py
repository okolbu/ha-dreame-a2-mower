"""session mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ..live_map.finalize import FinalizeAction
from ..domain.session import finalize as _finalize
from ..domain.session import persistence as _persistence
from ..domain.session import replay as _replay

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


class _SessionMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    async def replay_session(self, session_md5: str) -> None:
        """Delegates to ``domain.session.replay.replay_session`` (P3.9a).

        Backwards-compat alias for the Work Log render method — kept so the
        public dreame_a2_mower.replay_session service (and any user automations
        referencing it) keep working after the rename.
        """
        await _replay.replay_session(self, session_md5)

    async def render_work_log_session(self, session_md5: str) -> None:
        """Delegates to ``domain.session.replay.render_work_log_session`` (P3.9a).

        Renders an archived session's path into _work_log_png + builds the
        picked-session summary. The T2-13 session_card.py derivation moved into
        that module (session_card.py is DELETED).
        """
        await _replay.render_work_log_session(self, session_md5)

    def _resolve_finalize_map_id(self) -> int:
        """Delegates to ``domain.session.finalize.resolve_finalize_map_id`` (P3.9a)."""
        return _finalize.resolve_finalize_map_id(self)

    async def _periodic_session_retry(self) -> None:
        """Delegates to ``domain.session.finalize.periodic_session_retry`` (P3.9a)."""
        await _finalize.periodic_session_retry(self)

    async def _wait_for_dock_return(self, *, timeout_s: int = 300) -> str:
        """Delegates to ``domain.session.finalize.wait_for_dock_return`` (P3.9a).

        Preserves the P2.7 single-flight guard + the P2.8
        ``_pending_finalize_task`` cancellation VERBATIM in the domain module.
        """
        return await _finalize.wait_for_dock_return(self, timeout_s=timeout_s)

    async def _finalize_prior_for_new_command(self, now_unix: int) -> None:
        """Delegates to ``domain.session.finalize.finalize_prior_for_new_command`` (P3.9a)."""
        await _finalize.finalize_prior_for_new_command(self, now_unix)

    async def _finalize_non_mow_immediate(self, now_unix: int, trigger: str) -> None:
        """Delegates to ``domain.session.finalize.finalize_non_mow_immediate`` (P3.9a)."""
        await _finalize.finalize_non_mow_immediate(self, now_unix, trigger)

    def _provisional_session_type(self) -> str:
        """Delegates to ``domain.session.finalize.provisional_session_type`` (P3.9a)."""
        return _finalize.provisional_session_type(self)

    def _provisional_session_is_mow(self) -> bool:
        """Delegates to ``domain.session.finalize.provisional_session_is_mow`` (P3.9a)."""
        return _finalize.provisional_session_is_mow(self)

    def _provisional_session_is_cloud_finalized(self) -> bool:
        """Delegates to ``domain.session.finalize.provisional_session_is_cloud_finalized`` (P3.9a)."""
        return _finalize.provisional_session_is_cloud_finalized(self)

    async def _route_finalize(
        self, now_unix: int, *, dock_wait: bool, trigger: str
    ) -> None:
        """Delegates to ``domain.session.finalize.route_finalize`` (P3.9a)."""
        await _finalize.route_finalize(
            self, now_unix, dock_wait=dock_wait, trigger=trigger
        )

    async def _dispatch_finalize_action(
        self, action: FinalizeAction, now_unix: int
    ) -> None:
        """Delegates to ``domain.session.finalize.dispatch_finalize_action`` (P3.9a)."""
        await _finalize.dispatch_finalize_action(self, action, now_unix)

    async def _finalize_with_latch(
        self, body: Callable[[], Awaitable[None]], *, label: str
    ) -> None:
        """Delegates to ``domain.session.finalize.finalize_with_latch`` (P3.9a)."""
        await _finalize.finalize_with_latch(self, body, label=label)

    async def _merge_recorder_into_payload(
        self, payload: dict[str, Any], *, label: str
    ) -> None:
        """Delegates to ``domain.session.finalize.merge_recorder_into_payload`` (P3.9a)."""
        await _finalize.merge_recorder_into_payload(self, payload, label=label)

    async def _post_archive_reset(
        self,
        *,
        now_unix: int,
        area_mowed_m2: float | None,
        duration_min: int | None,
        completed: bool,
        extra_updates: dict | None = None,
        delete_log_tag: str = "_do_finalize_incomplete",
    ) -> None:
        """Delegates to ``domain.session.finalize.post_archive_reset`` (P3.9a)."""
        await _finalize.post_archive_reset(
            self,
            now_unix=now_unix,
            area_mowed_m2=area_mowed_m2,
            duration_min=duration_min,
            completed=completed,
            extra_updates=extra_updates,
            delete_log_tag=delete_log_tag,
        )

    async def _run_finalize_incomplete(self, now_unix: int) -> None:
        """Delegates to ``domain.session.finalize.run_finalize_incomplete`` (P3.9a).

        The single finalize latch (P3e.4) is preserved VERBATIM in the domain
        module; concurrent same-session entries de-dupe there.
        """
        await _finalize.run_finalize_incomplete(self, now_unix)

    async def _do_run_finalize_incomplete(self, now_unix: int) -> None:
        """Delegates to ``domain.session.finalize.do_run_finalize_incomplete`` (P3.9a).

        Always invoked through _finalize_with_latch (never call directly).
        """
        await _finalize.do_run_finalize_incomplete(self, now_unix)

    def _load_pending_op_from_sidecar(self) -> None:
        """Delegates to ``domain.session.persistence.load_pending_op_from_sidecar`` (P3.9a)."""
        _persistence.load_pending_op_from_sidecar(self)

    def _clear_pending_op(self) -> None:
        """Delegates to ``domain.session.persistence.clear_pending_op`` (P3.9a)."""
        _persistence.clear_pending_op(self)

    async def _restore_in_progress(self) -> None:
        """Delegates to ``domain.session.persistence.restore_in_progress`` (P3.9a).

        The P2.7 restore×finalize discard guard is preserved VERBATIM there.
        """
        await _persistence.restore_in_progress(self)

    async def _persist_in_progress(self, _now: Any = None) -> None:
        """Delegates to ``domain.session.persistence.persist_in_progress`` (P3.9a).

        The T3-12 TOCTOU ``_finalize_lock`` hold is preserved VERBATIM there.
        """
        await _persistence.persist_in_progress(self, _now)
