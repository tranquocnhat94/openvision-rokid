from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BackendLifecycleSnapshot:
    uses_any_realtime_backend: bool
    uses_local_backend: bool
    has_active_sessions: bool
    has_api_key: bool
    backend_state: str
    auto_wake_on_session: bool
    last_activity_ms: int
    now_ms: int
    idle_unload_ms: int
    local_backend_running: bool
    local_process_alive: bool


@dataclass(frozen=True, slots=True)
class BackendLifecycleDecision:
    next_state: str | None = None
    touch_activity: bool = False
    warm_local_backend: bool = False
    stop_local_backend: bool = False
    stop_reason: str | None = None


def evaluate_backend_lifecycle(snapshot: BackendLifecycleSnapshot) -> BackendLifecycleDecision:
    if snapshot.uses_any_realtime_backend:
        if snapshot.has_active_sessions and snapshot.has_api_key:
            return BackendLifecycleDecision(
                next_state="active",
                touch_activity=True,
            )
        if snapshot.backend_state != "sleeping":
            return BackendLifecycleDecision(next_state="sleeping")
        return BackendLifecycleDecision()

    if snapshot.has_active_sessions and not snapshot.uses_local_backend:
        if snapshot.backend_state != "sleeping":
            return BackendLifecycleDecision(
                next_state="sleeping",
                touch_activity=True,
            )
        return BackendLifecycleDecision(touch_activity=True)

    if snapshot.has_active_sessions:
        if (
            snapshot.local_backend_running
            and snapshot.last_activity_ms
            and snapshot.now_ms - snapshot.last_activity_ms >= snapshot.idle_unload_ms
        ):
            return BackendLifecycleDecision(
                touch_activity=True,
                stop_local_backend=True,
                stop_reason="idle_unload",
            )
        if snapshot.auto_wake_on_session:
            return BackendLifecycleDecision(
                next_state="warm",
                touch_activity=True,
                warm_local_backend=snapshot.backend_state != "active",
            )
        return BackendLifecycleDecision(touch_activity=True)

    if not snapshot.uses_local_backend:
        if snapshot.backend_state != "sleeping":
            return BackendLifecycleDecision(next_state="sleeping")
        return BackendLifecycleDecision()

    if (
        snapshot.local_process_alive
        and snapshot.last_activity_ms
        and snapshot.now_ms - snapshot.last_activity_ms >= snapshot.idle_unload_ms
    ):
        return BackendLifecycleDecision(
            stop_local_backend=True,
            stop_reason="idle_unload",
        )
    if snapshot.backend_state != "sleeping":
        return BackendLifecycleDecision(next_state="sleeping")
    return BackendLifecycleDecision()
