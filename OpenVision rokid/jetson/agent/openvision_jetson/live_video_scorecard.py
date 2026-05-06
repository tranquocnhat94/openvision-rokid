"""Score live-video runtime stability without touching device/system services."""

from __future__ import annotations

from typing import Any


FINAL_MEDIA_STATUSES = {"ok", "timeout", "cancelled", "error"}
SUCCESSFUL_LIVE_STATUSES = {"ok", "timeout"}
FPS_BUDGET_OVERRUN_TOLERANCE = 1.0


def build_live_video_no_restart_scorecard(
    *,
    before_health: dict[str, Any] | None,
    after_health: dict[str, Any] | None,
    media: list[dict[str, Any]] | None = None,
    media_commands: dict[str, Any] | None = None,
    session_id: str | None = None,
    command_id: str | None = None,
    min_video_frames: int = 1,
) -> dict[str, Any]:
    """Build a small pass/fail scorecard for an RV101 live_video smoke window."""

    gates: dict[str, dict[str, Any]] = {}
    before_health = before_health if isinstance(before_health, dict) else None
    after_health = after_health if isinstance(after_health, dict) else None

    _set_gate(
        gates,
        "health_available",
        bool(before_health and after_health and before_health.get("ok") and after_health.get("ok")),
        "before/after health snapshots are available",
        "missing healthy before/after /api/health snapshot",
    )

    before_epoch = _runtime_epoch(before_health)
    after_epoch = _runtime_epoch(after_health)
    _set_gate(
        gates,
        "runtime_no_restart",
        bool(before_epoch and before_epoch == after_epoch),
        "Jetson runtime epoch stayed stable",
        "Jetson runtime epoch changed or is missing",
        observed={"before": before_epoch, "after": after_epoch},
    )

    active_live_count = _to_int((after_health or {}).get("active_live_count"))
    _set_gate(
        gates,
        "no_active_live_left",
        active_live_count == 0,
        "no active live_video command remains",
        "active live_video command remains after smoke window",
        observed={"active_live_count": active_live_count},
    )

    command_status = _find_command(media_commands, command_id) if command_id else None
    if command_id:
        event = command_status.get("event") if isinstance(command_status, dict) else None
        status = event.get("status") if isinstance(event, dict) else None
        _set_gate(
            gates,
            "live_command_final",
            status in FINAL_MEDIA_STATUSES,
            "live_video command reached a final MediaEvent",
            "live_video command did not reach a final MediaEvent",
            observed={"command_id": command_id, "status": status},
        )
        _set_gate(
            gates,
            "live_command_successful_final",
            status in SUCCESSFUL_LIVE_STATUSES,
            "live_video command ended without client error",
            "live_video command ended with error or cancellation",
            observed={"command_id": command_id, "status": status},
        )
        payload = event.get("payload") if isinstance(event, dict) else {}
        _set_gate(
            gates,
            "client_stop_reported",
            bool(isinstance(payload, dict) and payload.get("client_reported")),
            "client reported the final live_video event",
            "final live_video event was not reported by the client",
            observed={"command_id": command_id, "client_reported": bool(isinstance(payload, dict) and payload.get("client_reported"))},
            required=False,
        )

    video = _find_video(media, session_id) if session_id else None
    if session_id:
        frame_count = _to_int(video.get("frame_count")) if isinstance(video, dict) else None
        _set_gate(
            gates,
            "video_frames_received",
            frame_count is not None and frame_count >= max(0, min_video_frames),
            "Jetson recorded RV101 live_video frames",
            "Jetson did not record enough RV101 live_video frames",
            observed={"session_id": session_id, "frame_count": frame_count, "min_video_frames": min_video_frames},
        )
        _set_live_fps_budget_gate(gates, video=video, command_status=command_status, session_id=session_id)

    required_failures = [name for name, gate in gates.items() if gate["required"] and gate["status"] == "fail"]
    warnings = [name for name, gate in gates.items() if not gate["required"] and gate["status"] == "warn"]
    status = "fail" if required_failures else "warn" if warnings else "pass"
    return {
        "status": status,
        "gates": gates,
        "metrics": {
            "required_failure_count": len(required_failures),
            "warning_count": len(warnings),
            "before_runtime_epoch": before_epoch,
            "after_runtime_epoch": after_epoch,
            "max_video_actual_fps": _actual_fps(video),
            "max_video_budget_fps": _fps_budget(video=video, command_status=command_status),
        },
    }


def _runtime_epoch(health: dict[str, Any] | None) -> dict[str, Any] | None:
    if not health:
        return None
    epoch = health.get("runtime_epoch")
    process_id = health.get("process_id")
    started_at = health.get("runtime_started_at")
    boot_id = health.get("runtime_boot_id")
    if epoch:
        return {
            "runtime_epoch": epoch,
            "process_id": process_id,
            "runtime_started_at": started_at,
            "runtime_boot_id": boot_id,
        }
    if process_id and started_at:
        return {
            "runtime_epoch": f"{process_id}:{started_at}",
            "process_id": process_id,
            "runtime_started_at": started_at,
            "runtime_boot_id": boot_id,
        }
    return None


def _find_command(media_commands: dict[str, Any] | None, command_id: str | None) -> dict[str, Any] | None:
    if not command_id or not isinstance(media_commands, dict):
        return None
    for item in media_commands.get("commands") or []:
        command = item.get("command") if isinstance(item, dict) else None
        if isinstance(command, dict) and command.get("command_id") == command_id:
            return item
    return None


def _find_video(media: list[dict[str, Any]] | None, session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    for item in media or []:
        if item.get("session_id") == session_id and isinstance(item.get("video"), dict):
            return item["video"]
    return None


def _set_live_fps_budget_gate(
    gates: dict[str, dict[str, Any]],
    *,
    video: dict[str, Any] | None,
    command_status: dict[str, Any] | None,
    session_id: str,
) -> None:
    budget_fps = _fps_budget(video=video, command_status=command_status)
    if budget_fps is None:
        return
    actual_fps = _actual_fps(video)
    observed = {
        "session_id": session_id,
        "actual_fps": actual_fps,
        "budget_fps": budget_fps,
        "estimated_fps": _to_float((video or {}).get("estimated_fps")),
        "sent_fps_estimate": _metadata_float(video, "sent_fps_estimate"),
        "dropped_frames": _metadata_int(video, "dropped_frames"),
        "camera_id": _metadata_str(video, "camera_id"),
    }
    if actual_fps is None:
        _set_gate(
            gates,
            "live_fps_budget",
            False,
            "live_video fps stayed within requested budget",
            "live_video fps budget exists but no actual fps estimate was recorded",
            observed=observed,
            required=False,
        )
        return
    _set_gate(
        gates,
        "live_fps_budget",
        actual_fps <= budget_fps + FPS_BUDGET_OVERRUN_TOLERANCE,
        "live_video actual fps stayed within requested budget",
        "live_video actual fps exceeded requested budget",
        observed=observed,
        required=False,
    )


def _actual_fps(video: dict[str, Any] | None) -> float | None:
    values = [
        _to_float((video or {}).get("estimated_fps")),
        _metadata_float(video, "sent_fps_estimate"),
    ]
    values = [value for value in values if value is not None]
    return round(max(values), 4) if values else None


def _fps_budget(*, video: dict[str, Any] | None, command_status: dict[str, Any] | None) -> float | None:
    command = command_status.get("command") if isinstance(command_status, dict) else None
    command_fps = _to_float(command.get("fps")) if isinstance(command, dict) else None
    if command_fps is not None:
        return command_fps
    return _metadata_float(video, "capture_fps_max") or _metadata_float(video, "requested_fps")


def _metadata_float(video: dict[str, Any] | None, key: str) -> float | None:
    metadata = video.get("metadata") if isinstance(video, dict) else None
    if not isinstance(metadata, dict):
        return None
    return _to_float(metadata.get(key))


def _metadata_int(video: dict[str, Any] | None, key: str) -> int | None:
    metadata = video.get("metadata") if isinstance(video, dict) else None
    if not isinstance(metadata, dict):
        return None
    return _to_int(metadata.get(key))


def _metadata_str(video: dict[str, Any] | None, key: str) -> str | None:
    metadata = video.get("metadata") if isinstance(video, dict) else None
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _set_gate(
    gates: dict[str, dict[str, Any]],
    name: str,
    passed: bool,
    pass_message: str,
    fail_message: str,
    *,
    observed: dict[str, Any] | None = None,
    required: bool = True,
) -> None:
    status = "pass" if passed else "fail" if required else "warn"
    gates[name] = {
        "status": status,
        "required": required,
        "message": pass_message if passed else fail_message,
        "observed": observed or {},
    }


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
