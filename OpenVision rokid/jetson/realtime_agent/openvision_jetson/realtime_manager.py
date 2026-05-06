"""OpenAI Realtime session manager for the Jetson agent."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import websockets

from .contracts import RealtimeStatus, RealtimeToolCall, ToolError, to_jsonable, utc_now
from .event_store import InMemoryEventStore
from .jetson_tool_server import JetsonToolServer
from .realtime_events import (
    SYSTEM_INSTRUCTIONS,
    append_audio_event,
    clear_audio_event,
    commit_audio_event,
    conversation_item_delete_event,
    function_call_output_event,
    parse_function_calls,
    response_create_event,
    session_update_event,
    text_item_event,
)
from .settings import RuntimeSettings, load_runtime_settings
from .skill_registry import SkillRegistry


SettingsProvider = Callable[[], RuntimeSettings]
SkillHandler = Callable[[str, dict[str, Any], str | None], dict[str, Any]]
SessionValidator = Callable[[str], bool]
ResponseTextHandler = Callable[[str, str], None]
ResponseAudioHandler = Callable[[str, str, int], None]
ResponseAudioDoneHandler = Callable[[str], None]
SEND_QUEUE_MAXSIZE = 256
AUDIO_QUEUE_MAXSIZE = 256
SEND_QUEUE_PUT_TIMEOUT_S = 0.25
REALTIME_CONNECT_ATTEMPTS = 3
REALTIME_CONNECT_OPEN_TIMEOUT_S = 20.0
REALTIME_CONNECT_RETRY_DELAY_S = 0.75
REALTIME_FAILED_RESPONSE_RECONNECT_THRESHOLD = 3
REALTIME_RECOVERY_RESTART_DELAY_S = 0.25
REALTIME_TOOL_OUTPUT_MAX_CHARS = 1200
REALTIME_CONVERSATION_ITEM_KEEP = 6
REALTIME_CONTEXT_REFRESH_RESPONSE_COUNT = 12
REALTIME_RATE_LIMIT_TOKEN_WARN_REMAINING = 6_000
DEFAULT_REALTIME_TURN_POLICY = "server_vad"
SUPPORTED_REALTIME_TURN_POLICIES = {"manual", "server_vad", "semantic_vad"}


@dataclass(slots=True)
class _RealtimeConnection:
    status: RealtimeStatus
    task: asyncio.Task[None] | None = None
    websocket: Any | None = None
    send_queue: asyncio.Queue[dict[str, Any] | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=SEND_QUEUE_MAXSIZE)
    )
    audio_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)
    )
    output_text_parts: dict[str, list[str]] = field(default_factory=dict)
    output_audio_transcript_parts: dict[str, list[str]] = field(default_factory=dict)
    tool_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    audio_append_count: int = 0
    response_active: bool = False
    response_create_pending: bool = False
    response_create_deferred: bool = False
    consecutive_failed_responses: int = 0
    reconnect_scheduled: bool = False
    conversation_item_ids: deque[str] = field(default_factory=deque)
    conversation_item_seen: set[str] = field(default_factory=set)
    response_done_count: int = 0
    last_rate_limit_token_warning_remaining: int | None = None


class RealtimeSessionManager:
    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        skills: SkillRegistry,
        settings_provider: SettingsProvider = load_runtime_settings,
        skill_handler: SkillHandler | None = None,
        response_text_handler: ResponseTextHandler | None = None,
        response_audio_handler: ResponseAudioHandler | None = None,
        response_audio_done_handler: ResponseAudioDoneHandler | None = None,
        tool_server: JetsonToolServer | None = None,
        session_validator: SessionValidator | None = None,
    ) -> None:
        self._events = events
        self._skills = skills
        self._skill_handler = skill_handler
        self._tool_server = tool_server or JetsonToolServer(
            events=events,
            skills=skills,
            skill_handler=skill_handler,
            session_validator=session_validator,
        )
        self._response_text_handler = response_text_handler
        self._response_audio_handler = response_audio_handler
        self._response_audio_done_handler = response_audio_done_handler
        self._settings_provider = settings_provider
        self._session_validator = session_validator
        self._connections: dict[str, _RealtimeConnection] = {}
        self._lock = asyncio.Lock()

    def statuses(self) -> list[dict[str, Any]]:
        return [to_jsonable(connection.status) for connection in self._connections.values()]

    def status(self, session_id: str) -> dict[str, Any] | None:
        connection = self._connections.get(session_id)
        return to_jsonable(connection.status) if connection else None

    async def start(
        self,
        *,
        session_id: str,
        turn_policy: str = DEFAULT_REALTIME_TURN_POLICY,
        output_modalities: list[str] | None = None,
        voice_output: bool | None = None,
    ) -> dict[str, Any]:
        turn_policy = _normalize_turn_policy(turn_policy)
        settings = self._settings_provider()
        output = _normalize_output_modalities(
            output_modalities,
            voice_output=settings.realtime_voice_output_enabled if voice_output is None else voice_output,
        )
        async with self._lock:
            existing = self._connections.get(session_id)
            if existing and existing.status.status in {"connecting", "connected"}:
                return to_jsonable(existing.status)

            status = RealtimeStatus(
                session_id=session_id,
                status="blocked" if not settings.openai_api_key else "connecting",
                model=settings.realtime_model,
                turn_policy=turn_policy,
                output_modalities=output,
            )
            if not settings.openai_api_key:
                status.error = {
                    "code": "missing_openai_api_key",
                    "message": "Set OPENAI_API_KEY or OPENAI_API_KEY_FILE in the Jetson service environment.",
                }
                self._events.add(
                    "realtime",
                    "blocked",
                    {"reason": "missing_openai_api_key", "model": settings.realtime_model},
                    session_id=session_id,
                    severity="warning",
                )
                connection = _RealtimeConnection(status=status)
                self._connections[session_id] = connection
                return to_jsonable(status)

            connection = _RealtimeConnection(status=status)
            connection.task = asyncio.create_task(
                self._run_connection(
                    connection,
                    settings=settings,
                    output_modalities=output,
                )
            )
            self._connections[session_id] = connection
            self._events.add(
                "realtime",
                "connecting",
                {"model": settings.realtime_model, "turn_policy": turn_policy},
                session_id=session_id,
            )
            return to_jsonable(status)

    async def stop(self, session_id: str) -> dict[str, Any]:
        async with self._lock:
            connection = self._connections.get(session_id)
            if not connection:
                return {"session_id": session_id, "status": "not_found"}
            _queue_stop(connection)
            if connection.task:
                connection.task.cancel()
            for task in list(connection.tool_tasks):
                task.cancel()
            if connection.websocket:
                await connection.websocket.close()
            connection.status.status = "stopped"
            connection.status.updated_at = utc_now()
            self._events.add("realtime", "stopped", {}, session_id=session_id)
            return to_jsonable(connection.status)

    async def send_text(self, *, session_id: str, text: str) -> dict[str, Any]:
        await self._send(session_id, text_item_event(text))
        connection = self._require_connected(session_id)
        await self._queue_response_create(connection, source="client")
        return {"queued": True, "session_id": session_id}

    async def append_audio(self, *, session_id: str, pcm_bytes: bytes) -> dict[str, Any]:
        await self._send(session_id, append_audio_event(pcm_bytes))
        return {"queued": True, "session_id": session_id, "bytes": len(pcm_bytes)}

    async def commit_audio(self, *, session_id: str, create_response: bool = True) -> dict[str, Any]:
        connection = self._require_connected(session_id)
        await self._queue_ordered_audio_event(connection, commit_audio_event(), source="client")
        self._events.add(
            "realtime",
            "client_event_queued",
            {"type": "input_audio_buffer.commit", "queue": "audio_ordered"},
            session_id=session_id,
        )
        if create_response:
            await self._queue_response_create(connection, source="client", after_audio=True)
        return {"queued": True, "session_id": session_id}

    async def clear_audio(self, *, session_id: str) -> dict[str, Any]:
        await self._send(session_id, clear_audio_event())
        return {"queued": True, "session_id": session_id}

    async def _send(self, session_id: str, event: dict[str, Any]) -> None:
        connection = self._require_connected(session_id)
        await self._queue_event(connection, event, source="client")
        event_type = str(event.get("type") or "unknown")
        if event_type == "input_audio_buffer.append":
            connection.audio_append_count += 1
            if connection.audio_append_count % 50 == 0:
                self._events.add(
                    "realtime",
                    "client_audio_append_summary",
                    {
                        "append_count": connection.audio_append_count,
                        "control_queue_size": connection.send_queue.qsize(),
                        "audio_queue_size": connection.audio_queue.qsize(),
                    },
                    session_id=session_id,
                )
            return
        self._events.add(
            "realtime",
            "client_event_queued",
            {"type": event_type},
            session_id=session_id,
        )

    async def _run_connection(
        self,
        connection: _RealtimeConnection,
        *,
        settings: RuntimeSettings,
        output_modalities: list[str],
    ) -> None:
        status = connection.status
        url = f"{settings.realtime_url}?{urlencode({'model': settings.realtime_model})}"
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        try:
            for attempt in range(1, REALTIME_CONNECT_ATTEMPTS + 1):
                try:
                    async with websockets.connect(
                        url,
                        additional_headers=headers,
                        open_timeout=REALTIME_CONNECT_OPEN_TIMEOUT_S,
                    ) as websocket:
                        connection.websocket = websocket
                        tools = self._skills.realtime_tools()
                        await websocket.send(
                            json.dumps(
                                session_update_event(
                                    model=settings.realtime_model,
                                    voice=settings.realtime_voice,
                                    tools=tools,
                                    turn_policy=status.turn_policy,
                                    output_modalities=output_modalities,
                                    max_output_tokens=settings.realtime_max_output_tokens,
                                ),
                                ensure_ascii=False,
                            )
                        )
                        self._events.add(
                            "realtime",
                            "session_update_sent",
                            {
                                "model": settings.realtime_model,
                                "turn_policy": status.turn_policy,
                                "output_modalities": output_modalities,
                                "tool_count": len(tools),
                                "tool_names": [str(tool.get("name") or "") for tool in tools[:12]],
                                "instructions_chars": len(SYSTEM_INSTRUCTIONS),
                                "identity_marker": "OpenVision Rokid V2" in SYSTEM_INSTRUCTIONS,
                                "max_output_tokens": settings.realtime_max_output_tokens,
                            },
                            session_id=status.session_id,
                        )
                        status.status = "connected"
                        status.error = None
                        status.connected_at = utc_now()
                        status.updated_at = status.connected_at
                        self._events.add(
                            "realtime",
                            "connected",
                            {"model": settings.realtime_model, "attempt": attempt},
                            session_id=status.session_id,
                        )
                        await asyncio.gather(
                            self._send_loop(connection),
                            self._receive_loop(connection),
                        )
                        return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    connection.websocket = None
                    if status.status == "connected" or attempt >= REALTIME_CONNECT_ATTEMPTS:
                        status.status = "error"
                        status.error = {"code": exc.__class__.__name__, "message": str(exc)}
                        status.updated_at = utc_now()
                        self._events.add(
                            "realtime",
                            "error",
                            status.error,
                            session_id=status.session_id,
                            severity="error",
                        )
                        return
                    status.status = "connecting"
                    status.error = {
                        "code": exc.__class__.__name__,
                        "message": str(exc),
                        "attempt": attempt,
                    }
                    status.updated_at = utc_now()
                    self._events.add(
                        "realtime",
                        "connect_retry_scheduled",
                        {
                            "attempt": attempt,
                            "max_attempts": REALTIME_CONNECT_ATTEMPTS,
                            "retry_delay_s": REALTIME_CONNECT_RETRY_DELAY_S,
                            "error": status.error,
                        },
                        session_id=status.session_id,
                        severity="warning",
                    )
                    await asyncio.sleep(REALTIME_CONNECT_RETRY_DELAY_S)
        except asyncio.CancelledError:
            status.status = "stopped"
            status.updated_at = utc_now()
            raise
        finally:
            for task in list(connection.tool_tasks):
                task.cancel()
            connection.websocket = None

    async def _send_loop(self, connection: _RealtimeConnection) -> None:
        while True:
            event = await _next_send_event(connection)
            if event is None:
                return
            if not connection.websocket:
                continue
            await connection.websocket.send(json.dumps(event, ensure_ascii=False))

    async def _receive_loop(self, connection: _RealtimeConnection) -> None:
        websocket = connection.websocket
        if websocket is None:
            return
        async for raw in websocket:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                event = {"type": "invalid_json", "raw": str(raw)[:200]}
            event_type = str(event.get("type") or "unknown")
            connection.status.last_event_type = event_type
            connection.status.event_count += 1
            connection.status.updated_at = utc_now()
            self._events.add(
                "realtime",
                "server_event",
                _compact_server_event(event),
                session_id=connection.status.session_id,
                severity=_server_event_severity(event),
            )
            self._track_conversation_item(connection, event)
            self._handle_rate_limits(connection, event)
            if await self._handle_terminal_error(connection, event):
                return
            self._handle_output_text(connection, event)
            self._handle_output_audio_transcript(connection, event)
            self._handle_output_audio(connection, event)
            await self._handle_tool_calls(connection, event)
            await self._handle_response_lifecycle(connection, event)

    async def _handle_terminal_error(self, connection: _RealtimeConnection, event: dict[str, Any]) -> bool:
        if event.get("type") != "error":
            return False
        error = event.get("error") if isinstance(event.get("error"), dict) else {}
        error_code = str(error.get("code") or "").strip()
        if error_code != "session_expired":
            user_message = _fatal_realtime_error_message(error)
            if not user_message:
                return False
            accepts_output = self._session_accepts_output(connection)
            connection.status.status = "error"
            connection.status.error = {
                "code": error_code or "realtime_error",
                "message": str(error.get("message") or "Realtime session failed."),
            }
            connection.status.updated_at = utc_now()
            connection.response_active = False
            connection.response_create_pending = False
            connection.response_create_deferred = False
            if self._response_text_handler and accepts_output:
                self._response_text_handler(connection.status.session_id, user_message)
            _queue_stop(connection)
            if connection.websocket:
                await connection.websocket.close()
            self._events.add(
                "realtime",
                "terminal_error",
                {
                    "code": connection.status.error["code"],
                    "message": connection.status.error["message"],
                    "hud_notified": bool(self._response_text_handler),
                },
                session_id=connection.status.session_id,
                severity="error",
            )
            return True
        connection.status.status = "expired"
        connection.status.error = {
            "code": "session_expired",
            "message": str(error.get("message") or "Realtime session expired."),
        }
        connection.status.updated_at = utc_now()
        connection.response_active = False
        connection.response_create_pending = False
        connection.response_create_deferred = False
        _queue_stop(connection)
        if connection.websocket:
            await connection.websocket.close()
        self._events.add(
            "realtime",
            "expired",
            connection.status.error,
            session_id=connection.status.session_id,
            severity="warning",
        )
        return True

    def _handle_rate_limits(self, connection: _RealtimeConnection, event: dict[str, Any]) -> None:
        if event.get("type") != "rate_limits.updated":
            return
        rate_limits = event.get("rate_limits")
        if not isinstance(rate_limits, list):
            return
        token_budget = _lowest_rate_limit(rate_limits, name_contains="token")
        if not token_budget:
            return
        remaining = token_budget.get("remaining")
        if not isinstance(remaining, int):
            return
        if remaining > REALTIME_RATE_LIMIT_TOKEN_WARN_REMAINING:
            connection.last_rate_limit_token_warning_remaining = None
            return
        previous = connection.last_rate_limit_token_warning_remaining
        if previous is not None and remaining > max(0, previous - 1_000):
            return
        connection.last_rate_limit_token_warning_remaining = remaining
        self._events.add(
            "realtime",
            "rate_limit_budget_low",
            {
                "name": token_budget.get("name"),
                "limit": token_budget.get("limit"),
                "remaining": remaining,
                "reset_seconds": token_budget.get("reset_seconds"),
                "threshold": REALTIME_RATE_LIMIT_TOKEN_WARN_REMAINING,
                "mitigation": "compact_outputs_prune_context_refresh_after_turn",
            },
            session_id=connection.status.session_id,
            severity="warning",
        )

    def _handle_output_text(self, connection: _RealtimeConnection, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type not in {"response.output_text.delta", "response.output_text.done"}:
            return
        key = _text_output_key(event)
        if event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                connection.output_text_parts.setdefault(key, []).append(delta)
            return
        text = event.get("text")
        if not isinstance(text, str):
            text = "".join(connection.output_text_parts.pop(key, []))
        else:
            connection.output_text_parts.pop(key, None)
        text = text.strip()
        if not text:
            return
        if not self._session_accepts_output(connection):
            self._events.add(
                "realtime",
                "output_text_ignored",
                {"reason": "inactive_session", "chars": len(text)},
                session_id=connection.status.session_id,
                severity="warning",
            )
            return
        self._events.add(
            "realtime",
            "output_text_done",
            {"chars": len(text), "preview": text[:120]},
            session_id=connection.status.session_id,
        )
        if self._response_text_handler:
            self._response_text_handler(connection.status.session_id, text)

    def _handle_output_audio_transcript(self, connection: _RealtimeConnection, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type not in {"response.output_audio_transcript.delta", "response.output_audio_transcript.done"}:
            return
        key = _text_output_key(event)
        if event_type == "response.output_audio_transcript.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                connection.output_audio_transcript_parts.setdefault(key, []).append(delta)
            return
        transcript = event.get("transcript")
        if not isinstance(transcript, str):
            transcript = "".join(connection.output_audio_transcript_parts.pop(key, []))
        else:
            connection.output_audio_transcript_parts.pop(key, None)
        transcript = transcript.strip()
        if not transcript:
            return
        if not self._session_accepts_output(connection):
            self._events.add(
                "realtime",
                "output_audio_transcript_ignored",
                {"reason": "inactive_session", "chars": len(transcript)},
                session_id=connection.status.session_id,
                severity="warning",
            )
            return
        self._events.add(
            "realtime",
            "output_audio_transcript_done",
            {"chars": len(transcript), "preview": transcript[:120]},
            session_id=connection.status.session_id,
        )
        if self._response_text_handler:
            self._response_text_handler(connection.status.session_id, transcript)

    def _handle_output_audio(self, connection: _RealtimeConnection, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type == "response.output_audio.delta":
            delta = event.get("delta")
            if not isinstance(delta, str) or not delta:
                return
            byte_count = _base64_decoded_len(delta)
            self._events.add(
                "realtime",
                "output_audio_delta",
                {"bytes": byte_count},
                session_id=connection.status.session_id,
            )
            if self._response_audio_handler and self._session_accepts_output(connection):
                self._response_audio_handler(connection.status.session_id, delta, byte_count)
            return
        if event_type == "response.output_audio.done":
            self._events.add(
                "realtime",
                "output_audio_done",
                {},
                session_id=connection.status.session_id,
            )
            if self._response_audio_done_handler and self._session_accepts_output(connection):
                self._response_audio_done_handler(connection.status.session_id)

    def _session_accepts_output(self, connection: _RealtimeConnection) -> bool:
        if connection.status.status not in {"connecting", "connected"}:
            return False
        if self._session_validator and not self._session_validator(connection.status.session_id):
            return False
        return True

    async def _handle_tool_calls(self, connection: _RealtimeConnection, event: dict[str, Any]) -> None:
        for call in parse_function_calls(event):
            tool_call = self._tool_server.build_tool_call(call, session_id=connection.status.session_id)
            if isinstance(tool_call, ToolError):
                if tool_call.tool_call_id == "missing_call_id":
                    self._events.add(
                        "realtime_tool",
                        "call_dropped",
                        {
                            "schema_version": tool_call.schema_version,
                            "tool_name": tool_call.tool_name,
                            "error_code": tool_call.error["code"],
                        },
                        session_id=connection.status.session_id,
                        severity="error",
                    )
                    continue
                await self._queue_tool_result(
                    connection,
                    output=to_jsonable(tool_call),
                    name=tool_call.tool_name,
                    call_id=tool_call.tool_call_id,
                )
                continue
            task = asyncio.create_task(
                self._run_tool_call(
                    connection,
                    tool_call=tool_call,
                )
            )
            connection.tool_tasks.add(task)
            task.add_done_callback(connection.tool_tasks.discard)

    async def _run_tool_call(
        self,
        connection: _RealtimeConnection,
        *,
        tool_call: RealtimeToolCall,
    ) -> None:
        result = await asyncio.to_thread(self._tool_server.execute, tool_call)
        await self._queue_tool_result(
            connection,
            output=result,
            name=tool_call.name,
            call_id=tool_call.call_id,
        )

    async def _queue_tool_result(
        self,
        connection: _RealtimeConnection,
        *,
        output: dict[str, Any],
        name: str,
        call_id: str,
    ) -> None:
        realtime_output = _compact_tool_output_for_realtime(output)
        skip_response_create = _tool_output_is_interim_media_request(realtime_output)
        try:
            await self._queue_event(
                connection,
                function_call_output_event(
                    call_id=call_id,
                    output=realtime_output,
                ),
                source="tool",
            )
            if not skip_response_create:
                await self._queue_response_create(connection, source="tool")
            self._events.add(
                "realtime",
                "tool_output_queued",
                {
                    "name": name,
                    "call_id": call_id,
                    "status": output.get("status"),
                    "output_chars": len(json.dumps(realtime_output, ensure_ascii=False)),
                    "compacted": realtime_output is not output,
                    "response_create_queued": not skip_response_create,
                    "interim_media_request": skip_response_create,
                },
                session_id=connection.status.session_id,
            )
        except RuntimeError as exc:
            self._events.add(
                "realtime",
                "tool_output_dropped",
                {"name": name, "call_id": call_id, "error": str(exc)},
                session_id=connection.status.session_id,
                severity="error",
            )

    def _require_connected(self, session_id: str) -> _RealtimeConnection:
        connection = self._connections.get(session_id)
        if not connection or connection.status.status != "connected":
            raise RuntimeError(f"Realtime session is not connected: {session_id}")
        return connection

    async def _queue_response_create(
        self,
        connection: _RealtimeConnection,
        *,
        source: str,
        after_audio: bool = False,
    ) -> None:
        if connection.response_active or connection.response_create_pending:
            connection.response_create_deferred = True
            self._events.add(
                "realtime",
                "response_create_deferred",
                {
                    "source": source,
                    "response_active": connection.response_active,
                    "response_create_pending": connection.response_create_pending,
                },
                session_id=connection.status.session_id,
                severity="warning",
            )
            return
        event = response_create_event(output_modalities=connection.status.output_modalities)
        if after_audio:
            await self._queue_ordered_audio_event(connection, event, source=source)
        else:
            await self._queue_event(connection, event, source=source)
        connection.response_create_pending = True
        self._events.add(
            "realtime",
            "response_create_queued",
            {"source": source, "queue": "audio_ordered" if after_audio else "control"},
            session_id=connection.status.session_id,
        )

    async def _handle_response_lifecycle(self, connection: _RealtimeConnection, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type == "response.created":
            connection.response_create_pending = False
            connection.response_active = True
            return
        if event_type == "error":
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            if error.get("code") == "conversation_already_has_active_response":
                connection.response_create_pending = False
                connection.response_active = True
                connection.response_create_deferred = True
            return
        if event_type != "response.done":
            return
        connection.response_create_pending = False
        connection.response_active = False
        if self._handle_failed_response(connection, event):
            return
        connection.consecutive_failed_responses = 0
        connection.response_done_count += 1
        await self._prune_conversation_context(connection)
        if not connection.response_create_deferred:
            if self._should_refresh_context(connection):
                self._schedule_reconnect(
                    connection,
                    reason="context_budget_refresh",
                    details={
                        "completed_responses": connection.response_done_count,
                        "threshold": REALTIME_CONTEXT_REFRESH_RESPONSE_COUNT,
                        "conversation_items": len(connection.conversation_item_ids),
                    },
                )
            return
        connection.response_create_deferred = False
        await self._queue_response_create(connection, source="deferred")

    def _should_refresh_context(self, connection: _RealtimeConnection) -> bool:
        if connection.response_done_count < REALTIME_CONTEXT_REFRESH_RESPONSE_COUNT:
            return False
        if connection.reconnect_scheduled or connection.tool_tasks:
            return False
        return (
            connection.status.status == "connected"
            and not connection.response_active
            and not connection.response_create_pending
            and not connection.response_create_deferred
        )

    def _handle_failed_response(self, connection: _RealtimeConnection, event: dict[str, Any]) -> bool:
        response = event.get("response")
        if not isinstance(response, dict) or response.get("status") != "failed":
            return False
        connection.consecutive_failed_responses += 1
        details = _response_failure_details(event)
        payload = {
            **details,
            "consecutive_failed_responses": connection.consecutive_failed_responses,
            "threshold": REALTIME_FAILED_RESPONSE_RECONNECT_THRESHOLD,
        }
        self._events.add(
            "realtime",
            "response_failed",
            payload,
            session_id=connection.status.session_id,
            severity="error"
            if connection.consecutive_failed_responses >= REALTIME_FAILED_RESPONSE_RECONNECT_THRESHOLD
            else "warning",
        )
        if _is_rate_limit_failure(details):
            self._schedule_reconnect(
                connection,
                reason="realtime_rate_limit_exceeded",
                details=payload,
            )
            return True
        if connection.consecutive_failed_responses < REALTIME_FAILED_RESPONSE_RECONNECT_THRESHOLD:
            self._queue_recovery_clear_audio(connection, reason="response_failed")
            return True
        self._schedule_reconnect(
            connection,
            reason="consecutive_response_failures",
            details=payload,
        )
        return True

    def _queue_recovery_clear_audio(self, connection: _RealtimeConnection, *, reason: str) -> None:
        try:
            connection.send_queue.put_nowait(clear_audio_event())
        except asyncio.QueueFull:
            self._events.add(
                "realtime",
                "recovery_clear_audio_dropped",
                {
                    "reason": reason,
                    "queued": connection.send_queue.qsize(),
                    "maxsize": connection.send_queue.maxsize,
                },
                session_id=connection.status.session_id,
                severity="warning",
            )
            return
        self._events.add(
            "realtime",
            "recovery_clear_audio_queued",
            {"reason": reason},
            session_id=connection.status.session_id,
        )

    def _schedule_reconnect(
        self,
        connection: _RealtimeConnection,
        *,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if connection.reconnect_scheduled:
            return
        connection.reconnect_scheduled = True
        connection.response_active = False
        connection.response_create_pending = False
        connection.response_create_deferred = False
        connection.status.status = "reconnecting"
        message = (
            "Realtime session is refreshing its context budget."
            if reason == "context_budget_refresh"
            else "Realtime response stream failed repeatedly; reconnecting."
        )
        connection.status.error = {
            "code": reason,
            "message": message,
            "details": details or {},
        }
        connection.status.updated_at = utc_now()
        self._events.add(
            "realtime",
            "reconnect_scheduled",
            {
                "reason": reason,
                "delay_s": REALTIME_RECOVERY_RESTART_DELAY_S,
                "details": details or {},
            },
            session_id=connection.status.session_id,
            severity="warning",
        )
        asyncio.create_task(
            self._restart_connection(
                session_id=connection.status.session_id,
                old_connection=connection,
                delay_s=REALTIME_RECOVERY_RESTART_DELAY_S,
            )
        )

    async def _restart_connection(
        self,
        *,
        session_id: str,
        old_connection: _RealtimeConnection,
        delay_s: float,
    ) -> None:
        await asyncio.sleep(delay_s)
        async with self._lock:
            if self._connections.get(session_id) is not old_connection:
                return
            if old_connection.websocket:
                await old_connection.websocket.close()
            if old_connection.task:
                old_connection.task.cancel()
            for task in list(old_connection.tool_tasks):
                task.cancel()

            settings = self._settings_provider()
            output_modalities = list(old_connection.status.output_modalities)
            status = RealtimeStatus(
                session_id=session_id,
                status="blocked" if not settings.openai_api_key else "connecting",
                model=settings.realtime_model,
                turn_policy=old_connection.status.turn_policy,
                output_modalities=output_modalities,
            )
            if not settings.openai_api_key:
                status.error = {
                    "code": "missing_openai_api_key",
                    "message": "Cannot reconnect Realtime without an OpenAI API key.",
                }
                self._connections[session_id] = _RealtimeConnection(status=status)
                self._events.add(
                    "realtime",
                    "reconnect_blocked",
                    {"reason": "missing_openai_api_key"},
                    session_id=session_id,
                    severity="error",
                )
                return

            connection = _RealtimeConnection(status=status)
            connection.task = asyncio.create_task(
                self._run_connection(
                    connection,
                    settings=settings,
                    output_modalities=output_modalities,
                )
            )
            self._connections[session_id] = connection
            self._events.add(
                "realtime",
                "reconnecting",
                {"model": settings.realtime_model, "turn_policy": status.turn_policy},
                session_id=session_id,
                severity="warning",
            )

    def _track_conversation_item(self, connection: _RealtimeConnection, event: dict[str, Any]) -> None:
        item_id = _conversation_item_id(event)
        if not item_id or item_id in connection.conversation_item_seen:
            return
        connection.conversation_item_seen.add(item_id)
        connection.conversation_item_ids.append(item_id)

    async def _prune_conversation_context(self, connection: _RealtimeConnection) -> None:
        if len(connection.conversation_item_ids) <= REALTIME_CONVERSATION_ITEM_KEEP:
            return
        deleted = 0
        while len(connection.conversation_item_ids) > REALTIME_CONVERSATION_ITEM_KEEP:
            item_id = connection.conversation_item_ids.popleft()
            connection.conversation_item_seen.discard(item_id)
            try:
                await self._queue_event(
                    connection,
                    conversation_item_delete_event(item_id),
                    source="context_prune",
                )
            except RuntimeError:
                break
            deleted += 1
        if not deleted:
            return
        self._events.add(
            "realtime",
            "conversation_prune_queued",
            {
                "deleted_count": deleted,
                "keep_count": REALTIME_CONVERSATION_ITEM_KEEP,
                "remaining_count": len(connection.conversation_item_ids),
            },
            session_id=connection.status.session_id,
        )

    async def _queue_event(self, connection: _RealtimeConnection, event: dict[str, Any], *, source: str) -> None:
        if event.get("type") == "input_audio_buffer.append":
            self._queue_audio_event(connection, event, source=source)
            return
        try:
            await asyncio.wait_for(connection.send_queue.put(event), timeout=SEND_QUEUE_PUT_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            self._events.add(
                "realtime",
                "send_queue_full",
                {
                    "source": source,
                    "maxsize": connection.send_queue.maxsize,
                    "queued": connection.send_queue.qsize(),
                    "event_type": event.get("type"),
                },
                session_id=connection.status.session_id,
                severity="error",
            )
            raise RuntimeError("Realtime send queue is full") from exc

    def _queue_audio_event(self, connection: _RealtimeConnection, event: dict[str, Any], *, source: str) -> None:
        try:
            connection.audio_queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            try:
                connection.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            connection.audio_queue.put_nowait(event)
            self._events.add(
                "realtime",
                "audio_append_dropped_for_backpressure",
                {
                    "source": source,
                    "maxsize": connection.audio_queue.maxsize,
                    "queued": connection.audio_queue.qsize(),
                },
                session_id=connection.status.session_id,
                severity="warning",
            )
        except asyncio.QueueFull:
            self._events.add(
                "realtime",
                "audio_queue_full",
                {
                    "source": source,
                    "maxsize": connection.audio_queue.maxsize,
                    "queued": connection.audio_queue.qsize(),
                },
                session_id=connection.status.session_id,
                severity="warning",
            )

    async def _queue_ordered_audio_event(
        self,
        connection: _RealtimeConnection,
        event: dict[str, Any],
        *,
        source: str,
    ) -> None:
        try:
            await asyncio.wait_for(connection.audio_queue.put(event), timeout=SEND_QUEUE_PUT_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            self._events.add(
                "realtime",
                "audio_queue_full",
                {
                    "source": source,
                    "maxsize": connection.audio_queue.maxsize,
                    "queued": connection.audio_queue.qsize(),
                    "event_type": event.get("type"),
                },
                session_id=connection.status.session_id,
                severity="error",
            )
            raise RuntimeError("Realtime audio queue is full") from exc

    def _output_modalities_for(self, session_id: str) -> list[str]:
        connection = self._connections.get(session_id)
        if not connection:
            return ["text"]
        return list(connection.status.output_modalities)


def _queue_stop(connection: _RealtimeConnection) -> None:
    try:
        connection.send_queue.put_nowait(None)
    except asyncio.QueueFull:
        try:
            connection.send_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        connection.send_queue.put_nowait(None)


async def _next_send_event(connection: _RealtimeConnection) -> dict[str, Any] | None:
    try:
        return connection.send_queue.get_nowait()
    except asyncio.QueueEmpty:
        pass
    try:
        return connection.audio_queue.get_nowait()
    except asyncio.QueueEmpty:
        pass

    control_task = asyncio.create_task(connection.send_queue.get())
    audio_task = asyncio.create_task(connection.audio_queue.get())
    done, pending = await asyncio.wait(
        {control_task, audio_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    if control_task in done:
        return control_task.result()
    return audio_task.result()


def _compact_server_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = event.get("type")
    payload: dict[str, Any] = {"type": event_type}
    if event_type == "response.done":
        response = event.get("response") or {}
        if isinstance(response, dict):
            payload["response_id"] = response.get("id")
            payload["status"] = response.get("status")
            payload["output_types"] = [
                item.get("type")
                for item in response.get("output", [])
                if isinstance(item, dict)
            ]
            status_details = response.get("status_details")
            if isinstance(status_details, dict):
                payload["status_details_type"] = status_details.get("type")
                payload["status_details_reason"] = status_details.get("reason")
                error = status_details.get("error")
                if isinstance(error, dict):
                    payload["status_details_error"] = {
                        key: error.get(key)
                        for key in ("type", "code", "message", "param")
                        if key in error
                    }
            usage = response.get("usage")
            if isinstance(usage, dict):
                payload["usage"] = _compact_realtime_usage(usage)
    elif event_type == "error":
        payload["error"] = event.get("error", event)
    elif event_type in {"session.created", "session.updated"}:
        session = event.get("session") or {}
        if isinstance(session, dict):
            payload["model"] = session.get("model")
            payload["output_modalities"] = session.get("output_modalities")
    elif event_type == "response.output_text.done":
        text = event.get("text")
        if isinstance(text, str):
            payload["chars"] = len(text)
            payload["preview"] = text[:120]
    elif event_type == "response.output_audio_transcript.done":
        transcript = event.get("transcript")
        if isinstance(transcript, str):
            payload["chars"] = len(transcript)
            payload["preview"] = transcript[:120]
    elif event_type == "response.output_audio.delta":
        delta = event.get("delta")
        if isinstance(delta, str):
            payload["bytes"] = _base64_decoded_len(delta)
    return payload


def _compact_realtime_usage(usage: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: usage.get(key)
        for key in ("total_tokens", "input_tokens", "output_tokens")
        if key in usage
    }
    input_details = usage.get("input_token_details")
    if isinstance(input_details, dict):
        compact["input_token_details"] = {
            key: input_details.get(key)
            for key in ("text_tokens", "audio_tokens", "image_tokens", "cached_tokens")
            if key in input_details
        }
        cached_details = input_details.get("cached_tokens_details")
        if isinstance(cached_details, dict):
            compact["input_token_details"]["cached_tokens_details"] = {
                key: cached_details.get(key)
                for key in ("text_tokens", "audio_tokens", "image_tokens")
                if key in cached_details
            }
    output_details = usage.get("output_token_details")
    if isinstance(output_details, dict):
        compact["output_token_details"] = {
            key: output_details.get(key)
            for key in ("text_tokens", "audio_tokens")
            if key in output_details
        }
    return compact


def _server_event_severity(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    if event_type == "error":
        return "error"
    if event_type == "response.done":
        response = event.get("response")
        if isinstance(response, dict) and response.get("status") == "cancelled":
            return "warning"
        if isinstance(response, dict) and response.get("status") == "failed":
            return "error"
    return "info"


def _fatal_realtime_error_message(error: dict[str, Any]) -> str | None:
    code = str(error.get("code") or "").strip().lower()
    if code == "insufficient_quota":
        return "OpenAI Realtime hết quota/billing. Jetson vẫn nghe được mic nhưng cloud chưa thể trả lời."
    if code in {"invalid_api_key", "missing_api_key"}:
        return "OpenAI Realtime lỗi API key. Jetson vẫn chạy, nhưng cloud voice chưa sẵn sàng."
    return None


def _response_failure_details(event: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_server_event(event)
    return {
        key: value
        for key, value in compact.items()
        if key
        in {
            "response_id",
            "status",
            "output_types",
            "status_details_type",
            "status_details_reason",
            "status_details_error",
        }
    }


def _is_rate_limit_failure(details: dict[str, Any]) -> bool:
    error = details.get("status_details_error")
    if not isinstance(error, dict):
        return False
    return str(error.get("code") or "").strip().lower() == "rate_limit_exceeded"


def _lowest_rate_limit(rate_limits: list[Any], *, name_contains: str) -> dict[str, Any] | None:
    needle = name_contains.strip().lower()
    best: dict[str, Any] | None = None
    for item in rate_limits:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("type") or "").strip().lower()
        if needle and needle not in name:
            continue
        remaining = _coerce_int(item.get("remaining"))
        if remaining is None:
            continue
        candidate = {
            "name": item.get("name") or item.get("type"),
            "limit": _coerce_int(item.get("limit")),
            "remaining": remaining,
            "reset_seconds": item.get("reset_seconds"),
        }
        if best is None or remaining < int(best["remaining"]):
            best = candidate
    return best


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _conversation_item_id(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "")
    if not event_type.startswith("conversation.item.") or event_type == "conversation.item.deleted":
        return None
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    value = item.get("id") or event.get("item_id")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _compact_tool_output_for_realtime(output: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_tool_value(output)
    if isinstance(compact, dict) and _json_chars(compact) <= REALTIME_TOOL_OUTPUT_MAX_CHARS:
        return compact
    summary = _tool_output_summary(output)
    if _json_chars(summary) <= REALTIME_TOOL_OUTPUT_MAX_CHARS:
        return summary
    return _minimal_tool_output_summary(output)


def _tool_output_is_interim_media_request(output: dict[str, Any]) -> bool:
    skill_payload = output.get("result") if isinstance(output.get("result"), dict) else {}
    result = skill_payload.get("result") if isinstance(skill_payload.get("result"), dict) else {}
    if not result.get("media_command"):
        return False
    status = str(output.get("status") or skill_payload.get("status") or "").strip().lower()
    if status != "no_evidence":
        return False
    media_event = result.get("media_event") if isinstance(result.get("media_event"), dict) else {}
    media_status = str(media_event.get("status") or "").strip().lower()
    return media_status in {"", "queued", "pending", "running"}


def _compact_tool_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 8:
        return {"_truncated": True}
    if isinstance(value, dict):
        if key == "identity_provider":
            return _compact_identity_provider(value)
        if key == "identity_match" or key == "best_match":
            return _compact_identity_match(value)
        if key == "profile":
            return _compact_profile(value)
        if key == "detector_status":
            return _compact_detector_status(value)
        if key == "preview":
            return _compact_preview(value)
        if key == "media_command":
            return _compact_media_command(value)
        if key == "media_event":
            return _compact_media_event(value)
        if key == "hud":
            return _compact_hud(value)
        output: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            child_key = str(raw_key)
            if child_key in {
                "identity_vector",
                "vector",
                "embedding",
                "embeddings",
                "cloud_evidence_bundle",
                "image_bytes",
                "frame_jpeg",
                "jpeg",
                "audio",
                "raw_frame",
                "image_url",
                "thumbnail_url",
                "thumb_url",
            }:
                continue
            if child_key in {"candidates", "objects", "known_people"} and isinstance(raw_value, list):
                output[child_key] = [
                    _compact_candidate(item) if isinstance(item, dict) else _compact_tool_value(item, key=child_key, depth=depth + 1)
                    for item in raw_value[:3]
                ]
                if len(raw_value) > 3:
                    output[f"{child_key}_truncated_count"] = len(raw_value) - 3
                continue
            output[child_key] = _compact_tool_value(raw_value, key=child_key, depth=depth + 1)
        return output
    if isinstance(value, list):
        compact_items = [_compact_tool_value(item, key=key, depth=depth + 1) for item in value[:4]]
        if len(value) > 4:
            compact_items.append({"_truncated_count": len(value) - 4})
        return compact_items
    if isinstance(value, str) and len(value) > 220:
        return f"{value[:220]}..."
    return value


def _tool_output_summary(output: dict[str, Any]) -> dict[str, Any]:
    skill_payload = output.get("result") if isinstance(output.get("result"), dict) else {}
    result = skill_payload.get("result") if isinstance(skill_payload.get("result"), dict) else {}
    summary_result = {
        key: _compact_tool_value(result.get(key), key=key)
        for key in (
            "answer",
            "user_message",
            "query",
            "info_focus",
            "scan_mode",
            "known_person",
            "known_people",
            "identity_provider",
            "identity_match",
            "identity_policy",
            "identity_uncertain",
            "count",
            "target",
            "media_command",
            "hud",
        )
        if key in result
    }
    return {
        "schema_version": output.get("schema_version"),
        "tool_call_id": output.get("tool_call_id"),
        "tool_name": output.get("tool_name"),
        "session_id": output.get("session_id"),
        "status": output.get("status"),
        "duration_ms": output.get("duration_ms"),
        "result": {
            "status": skill_payload.get("status"),
            "result": summary_result,
            "_compacted_for_realtime": True,
        },
    }


def _minimal_tool_output_summary(output: dict[str, Any]) -> dict[str, Any]:
    skill_payload = output.get("result") if isinstance(output.get("result"), dict) else {}
    result = skill_payload.get("result") if isinstance(skill_payload.get("result"), dict) else {}
    summary_result = {
        key: _compact_tool_value(result.get(key), key=key)
        for key in (
            "answer",
            "user_message",
            "known_person",
            "identity_provider",
            "identity_policy",
            "count",
            "media_command",
        )
        if key in result
    }
    return {
        "schema_version": output.get("schema_version"),
        "tool_call_id": output.get("tool_call_id"),
        "tool_name": output.get("tool_name"),
        "status": output.get("status"),
        "duration_ms": output.get("duration_ms"),
        "result": {
            "status": skill_payload.get("status"),
            "result": summary_result,
            "_compacted_for_realtime": True,
            "_minimal": True,
        },
    }


def _compact_identity_provider(value: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: _compact_tool_value(value.get(key), key=key)
        for key in (
            "status",
            "provider",
            "candidate_count",
            "candidate_vector_count",
            "low_quality_candidate_count",
            "quality_reasons",
            "best_score",
            "best_match",
            "requested_contact_count",
            "match_count",
            "message",
        )
        if key in value
    }
    matches = value.get("matches")
    if isinstance(matches, list):
        compact["matches"] = [_compact_identity_match(item) for item in matches[:2] if isinstance(item, dict)]
        if len(matches) > 2:
            compact["matches_truncated_count"] = len(matches) - 2
    return compact


def _compact_identity_match(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "target_id",
            "track_id",
            "anonymous_id",
            "contact_id",
            "display_name",
            "confidence",
            "identity_match",
            "match_status",
        )
        if key in value
    }


def _compact_candidate(value: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: _compact_tool_value(value.get(key), key=key)
        for key in (
            "target_id",
            "track_id",
            "anonymous_id",
            "label",
            "confidence",
            "bbox",
            "zone",
            "display_name",
            "identity_match",
            "match_status",
            "aim",
        )
        if key in value
    }
    attributes = value.get("attributes") if isinstance(value.get("attributes"), dict) else {}
    compact_attributes = {
        key: attributes.get(key)
        for key in (
            "detector_family",
            "identity_quality",
            "identity_quality_reasons",
            "face_min_side_px",
            "brightness",
            "contrast",
            "sharpness",
        )
        if key in attributes
    }
    if compact_attributes:
        compact["attributes"] = compact_attributes
    return compact


def _compact_profile(value: dict[str, Any]) -> dict[str, Any]:
    person = value.get("person") if isinstance(value.get("person"), dict) else {}
    if not person:
        return {}
    return {
        "person": {
            key: _compact_tool_value(person.get(key), key=key)
            for key in (
                "display_name",
                "age",
                "birthday",
                "where_lives",
                "relationship",
                "why_known",
                "first_met",
                "phone",
                "address",
                "links",
                "notes",
                "facts",
            )
            if key in person
        }
    }


def _compact_detector_status(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _compact_tool_value(value.get(key), key=key)
        for key in ("status", "source", "ready_for_person_info", "face_identity_status", "message")
        if key in value
    }


def _compact_preview(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in ("session_id", "source", "width", "height", "frame_count", "has_frame")
        if key in value
    }


def _compact_media_command(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _compact_tool_value(value.get(key), key=key)
        for key in ("command_id", "mode", "skill_id", "reason", "timeout_ms", "fps", "resolution", "auto_stop")
        if key in value
    }


def _compact_media_event(value: dict[str, Any]) -> dict[str, Any]:
    payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
    compact = {
        key: value.get(key)
        for key in ("event_id", "command_id", "mode", "session_id", "status", "duration_ms")
        if key in value
    }
    if payload:
        compact["payload"] = {
            key: _compact_tool_value(payload.get(key), key=key)
            for key in ("adapter_status", "client_reported", "duration_ms", "preview", "client_timing_ms")
            if key in payload
        }
    return compact


def _compact_hud(value: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    answer_strip = value.get("answer_strip")
    if isinstance(answer_strip, str) and answer_strip.strip():
        compact["answer_strip"] = _compact_tool_value(answer_strip, key="answer_strip")
    chips = value.get("edge_chips")
    if isinstance(chips, list):
        compact["edge_chips"] = [str(item)[:40] for item in chips[:3]]
        if len(chips) > 3:
            compact["edge_chips_truncated_count"] = len(chips) - 3
    target_hint = value.get("target_hint")
    if isinstance(target_hint, dict):
        compact["target_hint"] = {
            key: _compact_tool_value(target_hint.get(key), key=key)
            for key in ("direction", "distance_label", "target_id", "track_id", "display_name")
            if key in target_hint
        }
    thumbnails = value.get("thumbnails")
    if isinstance(thumbnails, list):
        compact["thumbnails"] = [
            {
                key: _compact_tool_value(item.get(key), key=key)
                for key in ("target_id", "track_id", "label", "display_name", "confidence")
                if isinstance(item, dict) and key in item
            }
            for item in thumbnails[:2]
            if isinstance(item, dict)
        ]
        if len(thumbnails) > 2:
            compact["thumbnails_truncated_count"] = len(thumbnails) - 2
    ttl_ms = value.get("ttl_ms")
    if isinstance(ttl_ms, int):
        compact["ttl_ms"] = ttl_ms
    return compact


def _json_chars(value: dict[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def _text_output_key(event: dict[str, Any]) -> str:
    return str(
        event.get("item_id")
        or f"{event.get('response_id')}:{event.get('output_index')}:{event.get('content_index')}"
    )


def _normalize_output_modalities(
    output_modalities: list[str] | None,
    *,
    voice_output: bool,
) -> list[str]:
    normalized: list[str] = []
    for modality in output_modalities or ["text"]:
        value = str(modality).strip().lower()
        if value in {"text", "audio"} and value not in normalized:
            normalized.append(value)
    # The current OpenAI Realtime session accepts either text or audio output,
    # not both in the same output_modalities array. Audio mode still emits
    # output_audio_transcript events, which we use to keep the HUD text updated.
    if voice_output or "audio" in normalized:
        return ["audio"]
    return ["text"]


def _normalize_turn_policy(value: str | None) -> str:
    policy = str(value or DEFAULT_REALTIME_TURN_POLICY).strip().lower()
    if policy in SUPPORTED_REALTIME_TURN_POLICIES:
        return policy
    raise ValueError(
        "Unsupported turn_policy. Expected one of: "
        + ", ".join(sorted(SUPPORTED_REALTIME_TURN_POLICIES))
    )


def _base64_decoded_len(value: str) -> int:
    try:
        return len(base64.b64decode(value, validate=False))
    except (ValueError, binascii.Error):
        return 0
