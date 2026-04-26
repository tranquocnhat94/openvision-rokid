"""OpenAI Realtime session manager for the Jetson agent."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import websockets

from .contracts import RealtimeStatus, to_jsonable, utc_now
from .event_store import InMemoryEventStore
from .realtime_events import (
    append_audio_event,
    clear_audio_event,
    commit_audio_event,
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
ResponseTextHandler = Callable[[str, str], None]
ResponseAudioHandler = Callable[[str, str, int], None]
ResponseAudioDoneHandler = Callable[[str], None]
SEND_QUEUE_MAXSIZE = 256
AUDIO_QUEUE_MAXSIZE = 256
SEND_QUEUE_PUT_TIMEOUT_S = 0.25


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
    ) -> None:
        self._events = events
        self._skills = skills
        self._skill_handler = skill_handler
        self._response_text_handler = response_text_handler
        self._response_audio_handler = response_audio_handler
        self._response_audio_done_handler = response_audio_done_handler
        self._settings_provider = settings_provider
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
        turn_policy: str = "manual",
        output_modalities: list[str] | None = None,
        voice_output: bool | None = None,
    ) -> dict[str, Any]:
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
        await self._send(session_id, response_create_event(output_modalities=self._output_modalities_for(session_id)))
        return {"queued": True, "session_id": session_id}

    async def append_audio(self, *, session_id: str, pcm_bytes: bytes) -> dict[str, Any]:
        await self._send(session_id, append_audio_event(pcm_bytes))
        return {"queued": True, "session_id": session_id, "bytes": len(pcm_bytes)}

    async def commit_audio(self, *, session_id: str, create_response: bool = True) -> dict[str, Any]:
        await self._send(session_id, commit_audio_event())
        if create_response:
            await self._send(session_id, response_create_event(output_modalities=self._output_modalities_for(session_id)))
        return {"queued": True, "session_id": session_id}

    async def clear_audio(self, *, session_id: str) -> dict[str, Any]:
        await self._send(session_id, clear_audio_event())
        return {"queued": True, "session_id": session_id}

    async def _send(self, session_id: str, event: dict[str, Any]) -> None:
        connection = self._connections.get(session_id)
        if not connection or connection.status.status != "connected":
            raise RuntimeError(f"Realtime session is not connected: {session_id}")
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
            async with websockets.connect(url, additional_headers=headers) as websocket:
                connection.websocket = websocket
                status.status = "connected"
                status.connected_at = utc_now()
                status.updated_at = status.connected_at
                await websocket.send(
                    json.dumps(
                        session_update_event(
                            model=settings.realtime_model,
                            voice=settings.realtime_voice,
                            tools=self._skills.realtime_tools(),
                            turn_policy=status.turn_policy,
                            output_modalities=output_modalities,
                            max_output_tokens=settings.realtime_max_output_tokens,
                        ),
                        ensure_ascii=False,
                    )
                )
                self._events.add(
                    "realtime",
                    "connected",
                    {"model": settings.realtime_model},
                    session_id=status.session_id,
                )
                await asyncio.gather(
                    self._send_loop(connection),
                    self._receive_loop(connection),
                )
        except asyncio.CancelledError:
            status.status = "stopped"
            status.updated_at = utc_now()
            raise
        except Exception as exc:
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
            self._handle_output_text(connection, event)
            self._handle_output_audio_transcript(connection, event)
            self._handle_output_audio(connection, event)
            await self._handle_tool_calls(connection, event)

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
            if self._response_audio_handler:
                self._response_audio_handler(connection.status.session_id, delta, byte_count)
            return
        if event_type == "response.output_audio.done":
            self._events.add(
                "realtime",
                "output_audio_done",
                {},
                session_id=connection.status.session_id,
            )
            if self._response_audio_done_handler:
                self._response_audio_done_handler(connection.status.session_id)

    async def _handle_tool_calls(self, connection: _RealtimeConnection, event: dict[str, Any]) -> None:
        for call in parse_function_calls(event):
            name = call.get("name")
            call_id = call.get("call_id")
            if not name or not call_id:
                continue
            args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            task = asyncio.create_task(
                self._run_tool_call(
                    connection,
                    name=str(name),
                    call_id=str(call_id),
                    args=args,
                )
            )
            connection.tool_tasks.add(task)
            task.add_done_callback(connection.tool_tasks.discard)

    async def _run_tool_call(
        self,
        connection: _RealtimeConnection,
        *,
        name: str,
        call_id: str,
        args: dict[str, Any],
    ) -> None:
        try:
            if self._skill_handler:
                result = await asyncio.to_thread(self._skill_handler, name, args, connection.status.session_id)
            else:
                result = self._skills.dry_run(name, args, session_id=connection.status.session_id)
        except Exception as exc:
            result = {
                "status": "error",
                "error": {
                    "code": exc.__class__.__name__,
                    "message": str(exc),
                },
            }
        try:
            await self._queue_event(
                connection,
                function_call_output_event(
                    call_id=call_id,
                    output=result,
                ),
                source="tool",
            )
            await self._queue_event(
                connection,
                response_create_event(output_modalities=connection.status.output_modalities),
                source="tool",
            )
            self._events.add(
                "realtime",
                "tool_output_queued",
                {"name": name, "call_id": call_id, "status": result["status"]},
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


def _server_event_severity(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    if event_type == "error":
        return "error"
    if event_type == "response.done":
        response = event.get("response")
        if isinstance(response, dict) and response.get("status") == "cancelled":
            return "warning"
    return "info"


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
    if "text" not in normalized:
        normalized.insert(0, "text")
    if voice_output and "audio" not in normalized:
        normalized.append("audio")
    if not voice_output and "audio" in normalized:
        normalized.remove("audio")
    return normalized


def _base64_decoded_len(value: str) -> int:
    try:
        return len(base64.b64decode(value, validate=False))
    except (ValueError, binascii.Error):
        return 0
