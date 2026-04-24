"""OpenAI Realtime session manager for the Jetson agent."""

from __future__ import annotations

import asyncio
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


@dataclass(slots=True)
class _RealtimeConnection:
    status: RealtimeStatus
    task: asyncio.Task[None] | None = None
    websocket: Any | None = None
    send_queue: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)
    output_text_parts: dict[str, list[str]] = field(default_factory=dict)


class RealtimeSessionManager:
    def __init__(
        self,
        *,
        events: InMemoryEventStore,
        skills: SkillRegistry,
        settings_provider: SettingsProvider = load_runtime_settings,
        skill_handler: SkillHandler | None = None,
        response_text_handler: ResponseTextHandler | None = None,
    ) -> None:
        self._events = events
        self._skills = skills
        self._skill_handler = skill_handler
        self._response_text_handler = response_text_handler
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
    ) -> dict[str, Any]:
        settings = self._settings_provider()
        output = output_modalities or ["text"]
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
            await connection.send_queue.put(None)
            if connection.task:
                connection.task.cancel()
            if connection.websocket:
                await connection.websocket.close()
            connection.status.status = "stopped"
            connection.status.updated_at = utc_now()
            self._events.add("realtime", "stopped", {}, session_id=session_id)
            return to_jsonable(connection.status)

    async def send_text(self, *, session_id: str, text: str) -> dict[str, Any]:
        await self._send(session_id, text_item_event(text))
        await self._send(session_id, response_create_event(output_modalities=["text"]))
        return {"queued": True, "session_id": session_id}

    async def append_audio(self, *, session_id: str, pcm_bytes: bytes) -> dict[str, Any]:
        await self._send(session_id, append_audio_event(pcm_bytes))
        return {"queued": True, "session_id": session_id, "bytes": len(pcm_bytes)}

    async def commit_audio(self, *, session_id: str, create_response: bool = True) -> dict[str, Any]:
        await self._send(session_id, commit_audio_event())
        if create_response:
            await self._send(session_id, response_create_event(output_modalities=["text"]))
        return {"queued": True, "session_id": session_id}

    async def clear_audio(self, *, session_id: str) -> dict[str, Any]:
        await self._send(session_id, clear_audio_event())
        return {"queued": True, "session_id": session_id}

    async def _send(self, session_id: str, event: dict[str, Any]) -> None:
        connection = self._connections.get(session_id)
        if not connection or connection.status.status != "connected":
            raise RuntimeError(f"Realtime session is not connected: {session_id}")
        await connection.send_queue.put(event)
        self._events.add(
            "realtime",
            "client_event_queued",
            {"type": event.get("type")},
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
            connection.websocket = None

    async def _send_loop(self, connection: _RealtimeConnection) -> None:
        while True:
            event = await connection.send_queue.get()
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
                severity="error" if event_type == "error" else "info",
            )
            self._handle_output_text(connection, event)
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

    async def _handle_tool_calls(self, connection: _RealtimeConnection, event: dict[str, Any]) -> None:
        for call in parse_function_calls(event):
            name = call.get("name")
            call_id = call.get("call_id")
            if not name or not call_id:
                continue
            args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            if self._skill_handler:
                result = self._skill_handler(str(name), args, connection.status.session_id)
            else:
                result = self._skills.dry_run(str(name), args, session_id=connection.status.session_id)
            await connection.send_queue.put(
                function_call_output_event(
                    call_id=str(call_id),
                    output=result,
                )
            )
            await connection.send_queue.put(response_create_event(output_modalities=["text"]))
            self._events.add(
                "realtime",
                "tool_output_queued",
                {"name": name, "call_id": call_id, "status": result["status"]},
                session_id=connection.status.session_id,
            )


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
    return payload


def _text_output_key(event: dict[str, Any]) -> str:
    return str(
        event.get("item_id")
        or f"{event.get('response_id')}:{event.get('output_index')}:{event.get('content_index')}"
    )
