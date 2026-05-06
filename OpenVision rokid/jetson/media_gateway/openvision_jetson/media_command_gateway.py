"""Typed media-command gateway for camera activation policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from time import perf_counter
import time
from typing import Any

from .contracts import MediaCommand, MediaEvent, new_id, to_jsonable
from .event_store import InMemoryEventStore


SessionValidator = Callable[[str], bool]
PreviewStatusProvider = Callable[[str], dict[str, Any] | None]

VISUAL_MODES = {"snapshot", "burst_clip", "live_video"}
MEDIA_MODES = {"none", *VISUAL_MODES}
MEDIA_EVENT_STATUSES = {"queued", "running", "ok", "timeout", "cancelled", "error"}
FINAL_MEDIA_EVENT_STATUSES = {"ok", "timeout", "cancelled", "error"}
QUALITY_GATE_SNAPSHOT_TIMEOUT_MS = 5000


@dataclass(frozen=True, slots=True)
class _ModeBudget:
    default_timeout_ms: int | None
    max_timeout_ms: int | None
    default_fps: float | None
    max_fps: float | None
    default_resolution: dict[str, int] | None
    max_width: int | None
    max_height: int | None


@dataclass(slots=True)
class _ActiveLiveVideo:
    command: MediaCommand
    started_s: float
    expires_s: float


class MediaCommandValidationError(RuntimeError):
    def __init__(self, *, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        payload = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class MediaCommandGateway:
    """Validate and record media activation commands before clients see them."""

    _BUDGETS = {
        "snapshot": _ModeBudget(
            default_timeout_ms=3000,
            max_timeout_ms=3000,
            default_fps=None,
            max_fps=None,
            default_resolution={"width": 1280, "height": 720},
            max_width=1280,
            max_height=720,
        ),
        "burst_clip": _ModeBudget(
            default_timeout_ms=3000,
            max_timeout_ms=5000,
            default_fps=5.0,
            max_fps=10.0,
            default_resolution={"width": 640, "height": 360},
            max_width=1280,
            max_height=720,
        ),
        "live_video": _ModeBudget(
            default_timeout_ms=None,
            max_timeout_ms=60000,
            default_fps=None,
            max_fps=30.0,
            default_resolution=None,
            max_width=1280,
            max_height=720,
        ),
    }

    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        session_validator: SessionValidator | None = None,
        preview_status_provider: PreviewStatusProvider | None = None,
        clock: Callable[[], float] | None = None,
        max_commands: int = 250,
    ) -> None:
        self._events = events
        self._session_validator = session_validator
        self._preview_status_provider = preview_status_provider
        self._clock = clock or time.monotonic
        self._max_commands = max(25, max_commands)
        self._lock = RLock()
        self._commands: dict[str, MediaCommand] = {}
        self._latest_events: dict[str, MediaEvent] = {}
        self._latest_client_payloads: dict[str, dict[str, Any]] = {}
        self._active_live_by_session: dict[str, _ActiveLiveVideo] = {}

    def request_command(
        self,
        *,
        mode: str,
        session_id: str,
        command_id: str | None = None,
        skill_id: str | None = None,
        reason: str | None = None,
        timeout_ms: int | None = None,
        fps: float | None = None,
        resolution: dict[str, Any] | None = None,
        auto_stop: bool = True,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = perf_counter()
        params = dict(params or {})
        try:
            with self._lock:
                self._expire_active_live_videos()
                normalized_mode = self._normalize_mode(mode)
                normalized_session_id = self._validate_session_id(session_id)
                action = self._normalize_action(normalized_mode, params)
                command = self._build_command(
                    mode=normalized_mode,
                    session_id=normalized_session_id,
                    command_id=command_id,
                    skill_id=skill_id,
                    reason=reason,
                    timeout_ms=timeout_ms,
                    fps=fps,
                    resolution=resolution,
                    auto_stop=auto_stop,
                    params={**params, "action": action},
                )
                event = self._handle_command(command, action=action, started=started)
                return self._response(command=command, event=event)
        except MediaCommandValidationError as exc:
            duration_ms = _duration_ms(started)
            error = exc.to_payload()
            self._events.add(
                "media_command",
                "command_failed",
                {
                    "mode": mode,
                    "status": "error",
                    "duration_ms": duration_ms,
                    "error": error,
                },
                session_id=session_id or None,
                severity="error",
            )
            return {
                "status": "error",
                "error": error,
                "duration_ms": duration_ms,
            }

    def statuses(self) -> list[dict[str, Any]]:
        with self._lock:
            self._expire_active_live_videos()
            active_ids = {active.command.command_id for active in self._active_live_by_session.values()}
            return [
                {
                    "command": to_jsonable(command),
                    "event": to_jsonable(self._latest_events.get(command_id)),
                    "active": command_id in active_ids,
                }
                for command_id, command in self._commands.items()
            ]

    def client_event(
        self,
        *,
        command_id: str,
        session_id: str,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = perf_counter()
        try:
            with self._lock:
                self._expire_active_live_videos()
                normalized_command_id = self._validate_known_command_id(command_id)
                command = self._commands[normalized_command_id]
                normalized_session_id = self._validate_session_id(session_id)
                if command.session_id != normalized_session_id:
                    raise MediaCommandValidationError(
                        code="media_command_session_mismatch",
                        message="Client media event session does not match the command session.",
                        details={
                            "command_id": normalized_command_id,
                            "command_session_id": command.session_id,
                            "event_session_id": normalized_session_id,
                        },
                    )
                normalized_status = self._normalize_client_status(status)
                normalized_payload = self._normalize_client_payload(payload)
                self._latest_client_payloads[normalized_command_id] = dict(normalized_payload)
                latest = self._latest_events.get(normalized_command_id)
                if latest and latest.status in FINAL_MEDIA_EVENT_STATUSES:
                    if self._can_merge_late_auto_stop_event(
                        command=command,
                        latest=latest,
                        status=normalized_status,
                    ):
                        event = self._record_event(
                            command,
                            status=latest.status,
                            payload=_merge_late_auto_stop_payload(
                                latest=latest,
                                client_status=normalized_status,
                                client_payload=normalized_payload,
                            ),
                            started=started,
                        )
                        return {
                            **self._response(command=command, event=event),
                            "merged": True,
                            "merge_reason": "late_client_final_after_auto_stop",
                        }
                    self._events.add(
                        "media_command",
                        "client_event_ignored",
                        {
                            "command_id": normalized_command_id,
                            "mode": command.mode,
                            "status": normalized_status,
                            "existing_status": latest.status,
                            "reason": "final_event_already_recorded",
                        },
                        session_id=command.session_id,
                    )
                    return {
                        **self._response(command=command, event=latest),
                        "ignored": True,
                        "ignore_reason": "final_event_already_recorded",
                    }
                if self._should_clear_active_live(command, normalized_status):
                    active = self._active_live_by_session.get(command.session_id)
                    if active and active.command.command_id == command.command_id:
                        self._active_live_by_session.pop(command.session_id, None)
                event = self._record_event(
                    command,
                    status=normalized_status,
                    payload={
                        "adapter_status": normalized_payload.pop("adapter_status", "client_reported"),
                        "client_reported": True,
                        **normalized_payload,
                    },
                    started=started,
                )
                return self._response(command=command, event=event)
        except MediaCommandValidationError as exc:
            duration_ms = _duration_ms(started)
            error = exc.to_payload()
            self._events.add(
                "media_command",
                "command_failed",
                {
                    "command_id": command_id or None,
                    "status": "error",
                    "duration_ms": duration_ms,
                    "error": error,
                },
                session_id=session_id or None,
                severity="error",
            )
            return {
                "status": "error",
                "error": error,
                "duration_ms": duration_ms,
            }

    def active_live_statuses(self) -> list[dict[str, Any]]:
        with self._lock:
            self._expire_active_live_videos()
            now = self._clock()
            return [
                {
                    "session_id": session_id,
                    "command_id": active.command.command_id,
                    "skill_id": active.command.skill_id,
                    "reason": active.command.reason,
                    "timeout_ms": active.command.timeout_ms,
                    "fps": active.command.fps,
                    "resolution": active.command.resolution,
                    "params": to_jsonable(active.command.params),
                    "preview_route": to_jsonable(active.command.params.get("preview_route")),
                    "perception_branches": to_jsonable(active.command.params.get("perception_branches") or []),
                    "primary_perception_branch": active.command.params.get("primary_perception_branch"),
                    "remaining_ms": max(0, int((active.expires_s - now) * 1000)),
                    "auto_stop": active.command.auto_stop,
                }
                for session_id, active in self._active_live_by_session.items()
            ]

    def close_session(self, session_id: str, *, reason: str = "session_closed") -> dict[str, Any] | None:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return None
        started = perf_counter()
        with self._lock:
            self._expire_active_live_videos()
            active = self._active_live_by_session.pop(normalized_session_id, None)
            if not active:
                return None
            event = self._record_event(
                active.command,
                status="cancelled",
                payload={
                    "action": "session_close",
                    "adapter_status": "session_closed",
                    "active_live_video": False,
                    "reason": reason,
                    "budget": self._budget_payload(active.command),
                },
                started=started,
            )
            return {
                **self._response(command=active.command, event=event),
                "closed_session": normalized_session_id,
            }

    def _build_command(
        self,
        *,
        mode: str,
        session_id: str,
        command_id: str | None,
        skill_id: str | None,
        reason: str | None,
        timeout_ms: int | None,
        fps: float | None,
        resolution: dict[str, Any] | None,
        auto_stop: bool,
        params: dict[str, Any],
    ) -> MediaCommand:
        action = str(params.get("action") or "")
        if mode == "live_video" and action == "stop":
            normalized_reason = self._required_text(reason, "reason")
            return MediaCommand(
                command_id=self._normalize_command_id(command_id),
                mode=mode,
                session_id=session_id,
                skill_id=self._optional_text(skill_id),
                reason=normalized_reason,
                auto_stop=True,
                params=params,
            )
        if mode == "none":
            return MediaCommand(
                command_id=self._normalize_command_id(command_id),
                mode=mode,
                session_id=session_id,
                skill_id=self._optional_text(skill_id),
                reason=self._optional_text(reason),
                auto_stop=True,
                params=params,
            )
        if mode in VISUAL_MODES:
            normalized_skill_id = self._required_text(skill_id, "skill_id")
            normalized_reason = self._required_text(reason, "reason")
            if not auto_stop:
                raise MediaCommandValidationError(
                    code="auto_stop_required",
                    message="Visual media commands must include auto_stop=true.",
                )
            normalized_timeout_ms = self._normalize_timeout(mode, timeout_ms, params=params)
            normalized_fps = self._normalize_fps(mode, fps)
            normalized_resolution = self._normalize_resolution(mode, resolution)
            return MediaCommand(
                command_id=self._normalize_command_id(command_id),
                mode=mode,
                session_id=session_id,
                skill_id=normalized_skill_id,
                reason=normalized_reason,
                timeout_ms=normalized_timeout_ms,
                fps=normalized_fps,
                resolution=normalized_resolution,
                auto_stop=True,
                params=params,
            )
        raise MediaCommandValidationError(
            code="invalid_media_mode",
            message=f"Unsupported media mode: {mode}",
        )

    def _handle_command(self, command: MediaCommand, *, action: str, started: float) -> MediaEvent:
        if command.mode == "none":
            stopped = self._active_live_by_session.pop(command.session_id, None)
            return self._record_event(
                command,
                status="ok",
                payload={
                    "action": "off",
                    "camera_state": "off",
                    "stopped_live_video": stopped is not None,
                    "stopped_command_id": stopped.command.command_id if stopped else None,
                },
                started=started,
            )
        if command.mode == "snapshot":
            preview = self._preview_status_provider(command.session_id) if self._preview_status_provider else None
            active_live = self._active_live_by_session.get(command.session_id)
            if preview and active_live:
                return self._record_event(
                    command,
                    status="ok",
                    payload={
                        "adapter_status": "using_active_live_preview",
                        "budget": self._budget_payload(command),
                        "preview": preview,
                        "active_live_command_id": active_live.command.command_id,
                    },
                    started=started,
                )
            return self._record_event(
                command,
                status="queued",
                payload={
                    "adapter_status": "awaiting_media_client",
                    "budget": self._budget_payload(command),
                    "latest_preview": preview,
                    "message": "Snapshot requires a fresh client media capture.",
                },
                started=started,
            )
        if command.mode == "burst_clip":
            return self._record_event(
                command,
                status="running",
                payload={
                    "adapter_status": "awaiting_media_client",
                    "budget": self._budget_payload(command),
                },
                started=started,
            )
        if command.mode == "live_video" and action == "stop":
            stopped = self._active_live_by_session.pop(command.session_id, None)
            return self._record_event(
                command,
                status="cancelled" if stopped else "ok",
                payload={
                    "action": "stop",
                    "active_live_video": False,
                    "stopped_command_id": stopped.command.command_id if stopped else None,
                },
                started=started,
            )
        if command.mode == "live_video":
            replaced = self._active_live_by_session.get(command.session_id)
            now = self._clock()
            timeout_ms = int(command.timeout_ms or 0)
            self._active_live_by_session[command.session_id] = _ActiveLiveVideo(
                command=command,
                started_s=now,
                expires_s=now + (timeout_ms / 1000.0),
            )
            return self._record_event(
                command,
                status="running",
                payload={
                    "action": "start",
                    "adapter_status": "awaiting_media_client",
                    "active_live_video": True,
                    "replaced_command_id": replaced.command.command_id if replaced else None,
                    "budget": self._budget_payload(command),
                },
                started=started,
            )
        raise MediaCommandValidationError(
            code="invalid_media_action",
            message=f"Unsupported media command action: {command.mode}/{action}",
        )

    def _record_event(
        self,
        command: MediaCommand,
        *,
        status: str,
        payload: dict[str, Any],
        started: float,
    ) -> MediaEvent:
        duration_ms = _duration_ms(started)
        event = MediaEvent(
            event_id=new_id("media_evt"),
            command_id=command.command_id,
            mode=command.mode,
            session_id=command.session_id,
            status=status,
            payload={
                **payload,
                "duration_ms": duration_ms,
            },
        )
        self._commands[command.command_id] = command
        self._latest_events[command.command_id] = event
        self._prune_command_history()
        event_type = "command_failed" if status == "error" else "command_completed"
        severity = _media_event_severity(command=command, status=status)
        self._events.add(
            "media_command",
            event_type,
            _media_event_log_payload(command=command, status=status, payload=event.payload, duration_ms=duration_ms),
            session_id=command.session_id,
            severity=severity,
        )
        return event

    def _expire_active_live_videos(self) -> None:
        now = self._clock()
        for session_id, active in list(self._active_live_by_session.items()):
            if not active.command.auto_stop or active.expires_s > now:
                continue
            self._active_live_by_session.pop(session_id, None)
            event = MediaEvent(
                event_id=new_id("media_evt"),
                command_id=active.command.command_id,
                mode="live_video",
                session_id=session_id,
                status="timeout",
                payload={
                    "action": "auto_stop",
                    "adapter_status": "backend_auto_stop",
                    "active_live_video": False,
                    **_live_video_stats_from_payload(self._latest_client_payloads.get(active.command.command_id)),
                    "budget": self._budget_payload(active.command),
                    "duration_ms": int(active.command.timeout_ms or 0),
                },
            )
            self._latest_events[active.command.command_id] = event
            self._prune_command_history()
            self._events.add(
                "media_command",
                "command_completed",
                _media_event_log_payload(
                    command=active.command,
                    status="timeout",
                    payload=event.payload,
                    duration_ms=int(active.command.timeout_ms or 0),
                ),
                session_id=session_id,
                severity="info",
            )

    def _response(self, *, command: MediaCommand, event: MediaEvent) -> dict[str, Any]:
        return {
            "status": event.status,
            "command": to_jsonable(command),
            "event": to_jsonable(event),
            "active_live_video": command.session_id in self._active_live_by_session,
        }

    def _prune_command_history(self) -> None:
        overflow = len(self._commands) - self._max_commands
        if overflow <= 0:
            return
        active_ids = {active.command.command_id for active in self._active_live_by_session.values()}
        for command_id in list(self._commands):
            if overflow <= 0:
                break
            if command_id in active_ids:
                continue
            self._commands.pop(command_id, None)
            self._latest_events.pop(command_id, None)
            self._latest_client_payloads.pop(command_id, None)
            overflow -= 1

    def _budget_payload(self, command: MediaCommand) -> dict[str, Any]:
        return {
            "timeout_ms": command.timeout_ms,
            "fps": command.fps,
            "resolution": command.resolution,
            "auto_stop": command.auto_stop,
            "media_profile": command.params.get("media_profile"),
            "camera_profile": command.params.get("camera_profile"),
            "profile_authority": command.params.get("profile_authority"),
            "camera_contract_version": command.params.get("camera_contract_version"),
        }

    def _normalize_mode(self, mode: str) -> str:
        normalized = str(mode or "").strip()
        if normalized not in MEDIA_MODES:
            raise MediaCommandValidationError(
                code="invalid_media_mode",
                message=f"Media mode must be one of: {', '.join(sorted(MEDIA_MODES))}.",
                details={"mode": mode},
            )
        return normalized

    def _validate_session_id(self, session_id: str) -> str:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise MediaCommandValidationError(
                code="missing_session",
                message="Media commands must be attached to a Jetson session.",
            )
        if self._session_validator and not self._session_validator(normalized):
            raise MediaCommandValidationError(
                code="unknown_session",
                message=f"Media command references an unknown session: {normalized}",
            )
        return normalized

    def _normalize_action(self, mode: str, params: dict[str, Any]) -> str:
        if mode == "none":
            return "off"
        if mode == "live_video":
            action = str(params.get("action") or "start").strip().lower()
            if action not in {"start", "stop"}:
                raise MediaCommandValidationError(
                    code="invalid_media_action",
                    message="live_video media commands support params.action=start or params.action=stop.",
                    details={"action": action},
                )
            return action
        action = str(params.get("action") or "capture").strip().lower()
        if action != "capture":
            raise MediaCommandValidationError(
                code="invalid_media_action",
                message=f"{mode} media commands only support params.action=capture.",
                details={"action": action},
            )
        return action

    def _normalize_timeout(self, mode: str, value: int | None, *, params: dict[str, Any]) -> int:
        budget = self._BUDGETS[mode]
        default_timeout_ms = budget.default_timeout_ms
        max_timeout_ms = budget.max_timeout_ms
        if mode == "snapshot" and isinstance(params.get("quality_gate"), dict):
            default_timeout_ms = QUALITY_GATE_SNAPSHOT_TIMEOUT_MS
            max_timeout_ms = QUALITY_GATE_SNAPSHOT_TIMEOUT_MS
        if value is None:
            if default_timeout_ms is None:
                raise MediaCommandValidationError(
                    code="missing_media_budget",
                    message=f"{mode} requires explicit timeout_ms.",
                    details={"field": "timeout_ms"},
                )
            return default_timeout_ms
        timeout_ms = _positive_int(value, "timeout_ms")
        if max_timeout_ms is not None:
            timeout_ms = min(timeout_ms, max_timeout_ms)
        return timeout_ms

    def _normalize_fps(self, mode: str, value: float | None) -> float | None:
        if mode == "snapshot":
            return None
        budget = self._BUDGETS[mode]
        if value is None:
            if budget.default_fps is None:
                raise MediaCommandValidationError(
                    code="missing_media_budget",
                    message=f"{mode} requires explicit fps.",
                    details={"field": "fps"},
                )
            return budget.default_fps
        fps = _positive_float(value, "fps")
        if budget.max_fps is not None:
            fps = min(fps, budget.max_fps)
        return round(fps, 2)

    def _normalize_resolution(self, mode: str, value: dict[str, Any] | None) -> dict[str, int]:
        budget = self._BUDGETS[mode]
        if value is None:
            if budget.default_resolution is None:
                raise MediaCommandValidationError(
                    code="missing_media_budget",
                    message=f"{mode} requires explicit resolution.",
                    details={"field": "resolution"},
                )
            return dict(budget.default_resolution)
        if not isinstance(value, dict):
            raise MediaCommandValidationError(
                code="invalid_media_budget",
                message="resolution must be an object with width and height.",
                details={"field": "resolution"},
            )
        width = _positive_int(value.get("width"), "resolution.width")
        height = _positive_int(value.get("height"), "resolution.height")
        if budget.max_width is not None:
            width = min(width, budget.max_width)
        if budget.max_height is not None:
            height = min(height, budget.max_height)
        return {"width": width, "height": height}

    def _normalize_command_id(self, command_id: str | None) -> str:
        normalized = str(command_id or "").strip()
        return normalized or new_id("media_cmd")

    def _validate_known_command_id(self, command_id: str) -> str:
        normalized = str(command_id or "").strip()
        if not normalized:
            raise MediaCommandValidationError(
                code="missing_media_command",
                message="Client media events must include a command_id.",
            )
        if normalized not in self._commands:
            raise MediaCommandValidationError(
                code="unknown_media_command",
                message=f"Unknown media command: {normalized}",
                details={"command_id": normalized},
            )
        return normalized

    def _normalize_client_status(self, status: str) -> str:
        normalized = str(status or "").strip().lower()
        if normalized not in MEDIA_EVENT_STATUSES:
            raise MediaCommandValidationError(
                code="invalid_media_event_status",
                message=f"Media event status must be one of: {', '.join(sorted(MEDIA_EVENT_STATUSES))}.",
                details={"status": status},
            )
        return normalized

    def _normalize_client_payload(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise MediaCommandValidationError(
                code="invalid_media_event_payload",
                message="Media event payload must be an object.",
            )
        return dict(payload)

    def _should_clear_active_live(self, command: MediaCommand, status: str) -> bool:
        action = str(command.params.get("action") or "").strip().lower()
        if command.mode == "none":
            return True
        if command.mode == "live_video" and action == "stop":
            return True
        return command.mode == "live_video" and status in {"timeout", "cancelled", "error"}

    def _can_merge_late_auto_stop_event(
        self,
        *,
        command: MediaCommand,
        latest: MediaEvent,
        status: str,
    ) -> bool:
        if command.mode != "live_video":
            return False
        if latest.status != "timeout":
            return False
        if latest.payload.get("action") != "auto_stop":
            return False
        return status in FINAL_MEDIA_EVENT_STATUSES

    def _required_text(self, value: str | None, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise MediaCommandValidationError(
                code="missing_media_command_field",
                message=f"{field} is required for this media command.",
                details={"field": field},
            )
        return normalized

    def _optional_text(self, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise MediaCommandValidationError(
            code="invalid_media_budget",
            message=f"{field} must be a positive integer.",
            details={"field": field},
        )
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise MediaCommandValidationError(
            code="invalid_media_budget",
            message=f"{field} must be a positive integer.",
            details={"field": field},
        ) from exc
    if number <= 0:
        raise MediaCommandValidationError(
            code="invalid_media_budget",
            message=f"{field} must be greater than 0.",
            details={"field": field},
        )
    return number


def _positive_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise MediaCommandValidationError(
            code="invalid_media_budget",
            message=f"{field} must be a positive number.",
            details={"field": field},
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MediaCommandValidationError(
            code="invalid_media_budget",
            message=f"{field} must be a positive number.",
            details={"field": field},
        ) from exc
    if number <= 0:
        raise MediaCommandValidationError(
            code="invalid_media_budget",
            message=f"{field} must be greater than 0.",
            details={"field": field},
        )
    return number


def _duration_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def _media_event_severity(*, command: MediaCommand, status: str) -> str:
    if status == "error":
        return "error"
    if command.mode == "live_video" and status in {"timeout", "cancelled"}:
        return "info"
    if status == "timeout":
        return "warning"
    return "info"


def _media_event_log_payload(
    *,
    command: MediaCommand,
    status: str,
    payload: dict[str, Any],
    duration_ms: int,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "command_id": command.command_id,
        "mode": command.mode,
        "status": status,
        "skill_id": command.skill_id,
        "duration_ms": duration_ms,
    }
    for key in ("adapter_status", "action", "active_live_video"):
        if key in payload:
            output[key] = payload.get(key)
    for key in (
        "width",
        "height",
        "requested_width",
        "requested_height",
        "target_fps",
        "requested_fps",
        "capture_fps_min",
        "capture_fps_max",
        "sent_fps_estimate",
        "sent_frames",
        "sent_bytes",
        "keyframe_count",
        "dropped_frames",
        "camera_id",
        "sensor_orientation_degrees",
        "rotation_degrees",
        "orientation",
        "profile",
        "camera_profile",
        "source_width",
        "source_height",
        "selected_width",
        "selected_height",
    ):
        if key in payload and payload.get(key) is not None:
            output[key] = payload.get(key)
    budget = payload.get("budget")
    if isinstance(budget, dict):
        output["budget"] = {
            key: budget.get(key)
            for key in ("timeout_ms", "fps", "resolution", "auto_stop")
            if key in budget
        }
    preview = payload.get("preview")
    if isinstance(preview, dict):
        output["preview"] = _compact_preview(preview)
    client_video = payload.get("client_video")
    if isinstance(client_video, dict):
        output["client_video"] = _compact_client_video(client_video)
        warning = _video_quality_warning(command=command, client_video=client_video, preview=preview)
        if warning:
            output["quality_warning"] = warning
    return output


def _merge_late_auto_stop_payload(
    *,
    latest: MediaEvent,
    client_status: str,
    client_payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(client_payload)
    adapter_status = normalized.pop("adapter_status", "client_reported_after_auto_stop")
    merged = {
        **latest.payload,
        "adapter_status": adapter_status,
        "client_reported": True,
        "client_status": client_status,
        "late_after_auto_stop": True,
        **normalized,
    }
    merged["action"] = "auto_stop"
    merged["active_live_video"] = False
    if "budget" not in merged and "budget" in latest.payload:
        merged["budget"] = latest.payload["budget"]
    return merged


def _live_video_stats_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    keys = (
        "width",
        "height",
        "requested_width",
        "requested_height",
        "target_fps",
        "requested_fps",
        "capture_fps_min",
        "capture_fps_max",
        "sent_fps_estimate",
        "sent_frames",
        "sent_bytes",
        "keyframe_count",
        "dropped_frames",
        "camera_id",
        "sensor_orientation_degrees",
        "rotation_degrees",
        "orientation",
        "profile",
        "camera_profile",
        "source_width",
        "source_height",
        "selected_width",
        "selected_height",
    )
    output = {key: payload.get(key) for key in keys if key in payload and payload.get(key) is not None}
    if payload.get("adapter_status"):
        output["client_adapter_status"] = payload.get("adapter_status")
    return output


def _compact_preview(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        key: preview.get(key)
        for key in ("source", "width", "height", "frame_count", "has_frame")
        if key in preview
    }


def _compact_client_video(client_video: dict[str, Any]) -> dict[str, Any]:
    tracks = client_video.get("video_tracks") if isinstance(client_video.get("video_tracks"), list) else []
    compact_tracks: list[dict[str, Any]] = []
    for track in tracks[:2]:
        if not isinstance(track, dict):
            continue
        settings = track.get("settings") if isinstance(track.get("settings"), dict) else {}
        compact_tracks.append(
            {
                "ready_state": track.get("ready_state"),
                "enabled": track.get("enabled"),
                "settings": {
                    key: settings.get(key)
                    for key in ("width", "height", "frameRate", "facingMode", "aspectRatio")
                    if key in settings
                },
            }
        )
    return {
        "requested": client_video.get("requested") if isinstance(client_video.get("requested"), dict) else None,
        "preview_width": client_video.get("preview_width"),
        "preview_height": client_video.get("preview_height"),
        "video_track_count": client_video.get("video_track_count"),
        "video_tracks": compact_tracks,
    }


def _video_quality_warning(
    *,
    command: MediaCommand,
    client_video: dict[str, Any],
    preview: Any,
) -> dict[str, Any] | None:
    if command.mode != "live_video" or not isinstance(command.resolution, dict):
        return None
    target_width = _safe_int(command.resolution.get("width"))
    target_height = _safe_int(command.resolution.get("height"))
    if not target_width or not target_height:
        return None
    widths: list[int] = []
    heights: list[int] = []
    if isinstance(preview, dict):
        widths.append(_safe_int(preview.get("width")) or 0)
        heights.append(_safe_int(preview.get("height")) or 0)
    widths.append(_safe_int(client_video.get("preview_width")) or 0)
    heights.append(_safe_int(client_video.get("preview_height")) or 0)
    tracks = client_video.get("video_tracks") if isinstance(client_video.get("video_tracks"), list) else []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        settings = track.get("settings") if isinstance(track.get("settings"), dict) else {}
        widths.append(_safe_int(settings.get("width")) or 0)
        heights.append(_safe_int(settings.get("height")) or 0)
    actual_width = max(widths or [0])
    actual_height = max(heights or [0])
    if actual_width >= max(1, int(target_width * 0.5)) and actual_height >= max(1, int(target_height * 0.5)):
        return None
    return {
        "code": "client_video_below_requested_budget",
        "requested": {"width": target_width, "height": target_height},
        "observed": {"width": actual_width or None, "height": actual_height or None},
    }


def _safe_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
