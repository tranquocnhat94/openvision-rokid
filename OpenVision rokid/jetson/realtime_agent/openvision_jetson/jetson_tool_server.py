"""Typed Jetson tool server for cloud realtime calls."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from time import perf_counter
from threading import BoundedSemaphore, RLock
from typing import Any, Callable

from .cloud_gateway import CloudGateway
from .contracts import RealtimeToolCall, SkillDefinition, ToolError, ToolResult, to_jsonable
from .event_store import InMemoryEventStore
from .skill_registry import SkillRegistry


SkillHandler = Callable[[str, dict[str, Any], str | None], dict[str, Any]]
SessionValidator = Callable[[str], bool]
RESULT_STATUSES = {"ok", "needs_cloud", "no_evidence", "not_implemented", "cancelled"}
PRIVACY_LEVELS = {"low": 0, "medium": 1, "high": 2, "sensitive": 3}


@dataclass(frozen=True, slots=True)
class ToolServerPolicy:
    """Runtime gates applied before a cloud-selected tool reaches Jetson code."""

    require_session: bool = True
    allow_cloud_tools: bool = True
    max_privacy_level: str = "high"
    max_tool_calls_per_session: int = 60
    max_cloud_calls_per_session: int = 12
    default_timeout_ms: int = 2500
    max_timeout_ms: int = 12000
    max_concurrent_tool_workers: int = 4


class ToolExecutionTimeout(RuntimeError):
    def __init__(self, *, tool_name: str, timeout_ms: int) -> None:
        super().__init__(f"Tool {tool_name} exceeded timeout budget of {timeout_ms}ms.")
        self.timeout_ms = timeout_ms


class ToolServerBusy(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Jetson tool worker pool is full.")


class JetsonToolServer:
    """Validates cloud realtime tool calls before executing Jetson-owned skills."""

    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        skills: SkillRegistry,
        skill_handler: SkillHandler | None = None,
        policy: ToolServerPolicy | None = None,
        session_validator: SessionValidator | None = None,
        cloud_gateway: CloudGateway | None = None,
    ) -> None:
        self._events = events
        self._skills = skills
        self._skill_handler = skill_handler
        self._policy = policy or ToolServerPolicy()
        self._session_validator = session_validator
        self._cloud_gateway = cloud_gateway or CloudGateway(events=events)
        self._lock = RLock()
        self._tool_counts_by_session: dict[str, int] = {}
        self._cloud_counts_by_session: dict[str, int] = {}
        max_workers = max(1, int(self._policy.max_concurrent_tool_workers or 1))
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="jetson-tool")
        self._tool_slots = BoundedSemaphore(max_workers)

    def build_tool_call(self, raw_call: dict[str, Any], *, session_id: str | None) -> RealtimeToolCall | ToolError:
        call_id = str(raw_call.get("call_id") or "").strip()
        name = str(raw_call.get("name") or "").strip()
        args = raw_call.get("arguments") if isinstance(raw_call.get("arguments"), dict) else {}
        if not call_id or not name:
            return ToolError(
                tool_call_id=call_id or "missing_call_id",
                tool_name=name or "missing_tool_name",
                session_id=session_id,
                error={
                    "code": "invalid_realtime_tool_call",
                    "message": "Realtime function call is missing call_id or name.",
                },
            )
        return RealtimeToolCall(
            call_id=call_id,
            name=name,
            arguments=args,
            session_id=session_id,
        )

    def execute(self, tool_call: RealtimeToolCall) -> dict[str, Any]:
        started = perf_counter()
        self._events.add(
            "realtime_tool",
            "call_received",
            {
                "schema_version": tool_call.schema_version,
                "tool_name": tool_call.name,
                "call_id": tool_call.call_id,
                "arguments": _tool_argument_summary(tool_call.arguments),
            },
            session_id=tool_call.session_id,
        )
        definition = self._skills.get(tool_call.name)
        validation_error = self._validate(tool_call, definition=definition)
        if validation_error:
            return self._error(tool_call, error=validation_error, started=started)

        try:
            skill_payload = self._execute_with_timeout(
                tool_call,
                timeout_ms=self._timeout_ms(definition),
            )
        except ToolExecutionTimeout as exc:
            return self._error(
                tool_call,
                error={
                    "code": "tool_timeout",
                    "message": str(exc),
                    "details": {"timeout_ms": exc.timeout_ms},
                },
                started=started,
            )
        except ToolServerBusy:
            return self._error(
                tool_call,
                error={
                    "code": "tool_server_busy",
                    "message": "Jetson tool worker pool is busy; retry shortly.",
                    "details": {"max_concurrent_tool_workers": self._policy.max_concurrent_tool_workers},
                },
                started=started,
            )
        except Exception as exc:
            return self._error(
                tool_call,
                error={
                    "code": exc.__class__.__name__,
                    "message": str(exc),
                },
                started=started,
            )

        status = str(skill_payload.get("status") or "ok")
        if status == "error":
            return self._error(
                tool_call,
                error=skill_payload.get("error")
                if isinstance(skill_payload.get("error"), dict)
                else {
                    "code": "tool_execution_error",
                    "message": f"Tool {tool_call.name} returned error status.",
                },
                started=started,
            )
        cloud_errors = self._cloud_gateway.validate_needs_cloud_payload(skill_payload)
        if cloud_errors:
            return self._error(
                tool_call,
                error={
                    "code": "invalid_cloud_escalation",
                    "message": "Tool returned needs_cloud without a valid cloud evidence/result contract.",
                    "details": cloud_errors,
                },
                started=started,
            )
        duration_ms = _duration_ms(started)
        result = ToolResult(
            tool_call_id=tool_call.call_id,
            tool_name=tool_call.name,
            session_id=tool_call.session_id,
            status=status if status in RESULT_STATUSES else "ok",
            result=skill_payload,
            display_command=_display_command_from_skill_payload(skill_payload),
            duration_ms=duration_ms,
        )
        payload = to_jsonable(result)
        self._events.add(
            "realtime_tool",
            "call_completed",
            {
                "schema_version": payload["schema_version"],
                "tool_name": tool_call.name,
                "call_id": tool_call.call_id,
                "status": payload["status"],
                "duration_ms": duration_ms,
            },
            session_id=tool_call.session_id,
        )
        return payload

    def _validate(
        self,
        tool_call: RealtimeToolCall,
        *,
        definition: SkillDefinition | None,
    ) -> dict[str, Any] | None:
        if definition is None:
            return {
                "code": "unknown_tool",
                "message": f"Unknown Jetson tool: {tool_call.name}",
            }
        errors = self._skills.validate_args(tool_call.name, tool_call.arguments)
        if errors:
            return {
                "code": "invalid_tool_args",
                "message": "Tool arguments do not match the skill manifest.",
                "details": errors,
            }
        policy_error = self._validate_policy(tool_call, definition=definition)
        if policy_error:
            return policy_error
        budget_error = self._reserve_budget(tool_call, definition=definition)
        if budget_error:
            return budget_error
        return None

    def _validate_policy(
        self,
        tool_call: RealtimeToolCall,
        *,
        definition: SkillDefinition,
    ) -> dict[str, Any] | None:
        session_id = str(tool_call.session_id or "").strip()
        if self._policy.require_session and not session_id:
            return {
                "code": "missing_session",
                "message": "Realtime tool calls must be attached to a Jetson session.",
            }
        if session_id and self._session_validator and not self._session_validator(session_id):
            return {
                "code": "unknown_session",
                "message": f"Realtime tool call references an unknown session: {session_id}",
            }
        if _is_cloud_capable(definition) and not self._policy.allow_cloud_tools:
            return {
                "code": "cloud_tool_blocked",
                "message": f"Tool {tool_call.name} requires cloud permission, but cloud tools are disabled.",
            }
        if _privacy_rank(definition.privacy_level) > _privacy_rank(self._policy.max_privacy_level):
            return {
                "code": "privacy_level_blocked",
                "message": (
                    f"Tool {tool_call.name} has privacy level {definition.privacy_level}, "
                    f"above policy max {self._policy.max_privacy_level}."
                ),
            }
        return None

    def _reserve_budget(
        self,
        tool_call: RealtimeToolCall,
        *,
        definition: SkillDefinition,
    ) -> dict[str, Any] | None:
        session_key = str(tool_call.session_id or "global")
        with self._lock:
            tool_count = self._tool_counts_by_session.get(session_key, 0)
            if tool_count >= self._policy.max_tool_calls_per_session:
                return {
                    "code": "tool_budget_exceeded",
                    "message": "Realtime tool-call budget exceeded for this session.",
                    "details": {"max_tool_calls_per_session": self._policy.max_tool_calls_per_session},
                }
            if _is_cloud_capable(definition):
                cloud_count = self._cloud_counts_by_session.get(session_key, 0)
                if cloud_count >= self._policy.max_cloud_calls_per_session:
                    return {
                        "code": "cloud_budget_exceeded",
                        "message": "Realtime cloud-capable tool budget exceeded for this session.",
                        "details": {"max_cloud_calls_per_session": self._policy.max_cloud_calls_per_session},
                    }
                self._cloud_counts_by_session[session_key] = cloud_count + 1
            self._tool_counts_by_session[session_key] = tool_count + 1
        return None

    def _execute_with_timeout(self, tool_call: RealtimeToolCall, *, timeout_ms: int) -> dict[str, Any]:
        if not self._tool_slots.acquire(blocking=False):
            raise ToolServerBusy()
        future = self._executor.submit(self._execute_skill_payload, tool_call)
        future.add_done_callback(lambda _future: self._release_tool_slot())
        try:
            payload = future.result(timeout=timeout_ms / 1000)
        except FutureTimeoutError as exc:
            future.cancel()
            raise ToolExecutionTimeout(tool_name=tool_call.name, timeout_ms=timeout_ms) from exc
        return payload

    def _release_tool_slot(self) -> None:
        try:
            self._tool_slots.release()
        except ValueError:
            pass

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _execute_skill_payload(self, tool_call: RealtimeToolCall) -> dict[str, Any]:
        if self._skill_handler:
            return self._skill_handler(tool_call.name, tool_call.arguments, tool_call.session_id)
        return self._skills.dry_run(
            tool_call.name,
            tool_call.arguments,
            session_id=tool_call.session_id,
        )

    def _timeout_ms(self, definition: SkillDefinition | None) -> int:
        timeout_ms = definition.timeout_ms if definition else self._policy.default_timeout_ms
        timeout_ms = timeout_ms or self._policy.default_timeout_ms
        return max(1, min(int(timeout_ms), int(self._policy.max_timeout_ms)))

    def _error(self, tool_call: RealtimeToolCall, *, error: dict[str, Any], started: float) -> dict[str, Any]:
        duration_ms = _duration_ms(started)
        payload = to_jsonable(
            ToolError(
                tool_call_id=tool_call.call_id,
                tool_name=tool_call.name,
                session_id=tool_call.session_id,
                error=_normalize_error(error),
                duration_ms=duration_ms,
            )
        )
        self._events.add(
            "realtime_tool",
            "call_failed",
            {
                "schema_version": payload["schema_version"],
                "tool_name": tool_call.name,
                "call_id": tool_call.call_id,
                "status": "error",
                "duration_ms": duration_ms,
                "error_code": payload["error"]["code"],
            },
            session_id=tool_call.session_id,
            severity="error",
        )
        return payload


def _normalize_error(error: dict[str, Any]) -> dict[str, Any]:
    code = str(error.get("code") or "tool_error")
    message = str(error.get("message") or code)
    normalized = {"code": code, "message": message}
    if "details" in error:
        normalized["details"] = error["details"]
    return normalized


def _duration_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def _tool_argument_summary(args: dict[str, Any]) -> dict[str, Any]:
    safe_keys = {
        "query",
        "question",
        "focus",
        "target",
        "target_type",
        "target_name",
        "identity_query",
        "max_candidates",
        "desired_zone",
        "zoom_if_far",
        "display_name",
        "enroll_identity",
    }
    summary: dict[str, Any] = {}
    for key in safe_keys:
        if key not in args:
            continue
        value = args.get(key)
        if isinstance(value, str):
            summary[key] = value[:160]
        elif isinstance(value, (int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, list):
            summary[key] = f"list[{len(value)}]"
        elif isinstance(value, dict):
            summary[key] = f"object[{len(value)}]"
    extra_count = len([key for key in args if key not in safe_keys])
    if extra_count:
        summary["_extra_arg_count"] = extra_count
    return summary


def _privacy_rank(level: str) -> int:
    return PRIVACY_LEVELS.get(str(level or "").strip().lower(), PRIVACY_LEVELS["sensitive"])


def _is_cloud_capable(definition: SkillDefinition) -> bool:
    return definition.cloud_allowed or definition.cloud_behavior != "local_only"


def _display_command_from_skill_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return None
    command = result.get("display_command")
    return command if isinstance(command, dict) else None
