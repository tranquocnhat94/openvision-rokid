from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from typing import Any, Awaitable, Callable

from fastapi import WebSocket, WebSocketDisconnect

from .control_protocol_runtime import (
    build_ack_payload,
    build_error_payload,
    build_mode_state_payload,
    build_pong_payload,
)


async def send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        raise
    except Exception as error:
        # Disconnect races are normal when the glasses pause or tear down sockets.
        raise WebSocketDisconnect(code=1006) from error


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
        return await value
    return value


class SessionControlRuntime:
    def __init__(
        self,
        *,
        session_accept_payload_provider: Callable[..., dict[str, Any]],
        mode_state_provider: Callable[[str], dict[str, Any]],
        make_hud_scene: Callable[..., dict[str, Any]],
        make_speech_state: Callable[..., dict[str, Any]],
        make_result: Callable[[Any], dict[str, Any]],
        make_node_telemetry: Callable[[Any], dict[str, Any]],
        drain_control_events: Callable[[str], list[dict[str, Any]]],
        append_session_log: Callable[[Any, str, dict[str, Any]], None],
        result_interval_provider: Callable[[str], int],
        now_ms_provider: Callable[[], int],
        activity_ts_provider: Callable[[], float] | None = None,
    ) -> None:
        self._session_accept_payload_provider = session_accept_payload_provider
        self._mode_state_provider = mode_state_provider
        self._make_hud_scene = make_hud_scene
        self._make_speech_state = make_speech_state
        self._make_result = make_result
        self._make_node_telemetry = make_node_telemetry
        self._drain_control_events = drain_control_events
        self._append_session_log = append_session_log
        self._result_interval_provider = result_interval_provider
        self._now_ms_provider = now_ms_provider
        self._activity_ts_provider = activity_ts_provider or time.time

    async def result_loop(self, websocket: WebSocket, session: Any) -> None:
        while bool(getattr(session, "control_connected", False)):
            await asyncio.sleep(self._result_interval_provider(str(getattr(session, "mode", ""))) / 1000.0)
            for payload in self._drain_control_events(str(getattr(session, "session_id", ""))):
                await send_json(websocket, payload)
            await send_json(websocket, self._make_result(session))
            await send_json(websocket, self._make_node_telemetry(session))
            for payload in self._drain_control_events(str(getattr(session, "session_id", ""))):
                await send_json(websocket, payload)

    async def handle_session_control_message(
        self,
        session: Any,
        websocket: WebSocket,
        message_type: str,
        payload: dict[str, Any],
    ) -> bool:
        if message_type == "mode_change":
            session.mode = payload.get("mode", getattr(session, "mode", "standby"))
            self._append_session_log(session, "mode_change", {"mode": session.mode})
            await send_json(
                websocket,
                build_mode_state_payload(
                    session_id=str(getattr(session, "session_id", "")),
                    mode=str(getattr(session, "mode", "")),
                    mode_state=self._mode_state_provider(str(getattr(session, "mode", ""))),
                ),
            )
            return True
        if message_type == "ping":
            session.last_ping_at = self._activity_ts_provider()
            await send_json(
                websocket,
                build_pong_payload(
                    session_id=str(getattr(session, "session_id", "")),
                    timestamp_ms=self._now_ms_provider(),
                ),
            )
            return True
        if message_type == "device_telemetry":
            session.latest_device_telemetry = payload
            self._append_session_log(session, "device_telemetry", payload)
            return True
        if message_type == "audio_hello":
            self._append_session_log(session, "audio_hello_control", payload)
            await send_json(websocket, self._make_hud_scene(session))
            return True
        if message_type == "audio_stats":
            session.latest_audio_stats = payload
            self._append_session_log(session, "audio_stats", payload)
            return True
        if message_type == "encoder_stats":
            session.latest_encoder_stats = payload
            self._append_session_log(session, "encoder_stats", payload)
            return True
        if message_type == "ptt_down":
            self._append_session_log(session, "ptt_down", payload)
            await send_json(
                websocket,
                self._make_speech_state(
                    session,
                    listening=True,
                    state_label="listening",
                    task_label="voice capture",
                    transcript_hint="Jetson is listening",
                ),
            )
            await send_json(
                websocket,
                self._make_hud_scene(
                    session,
                    task_chip="voice capture",
                    mic_chip="listening",
                    answer_text="Speak your request now.",
                    status_text="Jetson keeps the dedicated voice socket open while listening.",
                ),
            )
            return True
        if message_type == "ptt_up":
            transcript_hint = payload.get("transcriptHint")
            self._append_session_log(session, "ptt_up", payload)
            await send_json(
                websocket,
                self._make_speech_state(
                    session,
                    listening=False,
                    state_label="processing",
                    task_label="voice request",
                    transcript_hint=str(transcript_hint) if transcript_hint else "Voice captured on Jetson",
                ),
            )
            await send_json(
                websocket,
                self._make_hud_scene(
                    session,
                    task_chip="voice request",
                    mic_chip="processing",
                    answer_text="Voice captured on Jetson. ASR and task routing come next.",
                    status_text="This is the first voice-first bridge layer.",
                ),
            )
            return True
        if message_type == "stream_log":
            self._append_session_log(session, "stream_log", payload)
            return True
        return False

    async def run_endpoint(
        self,
        websocket: WebSocket,
        *,
        create_session_from_hello: Callable[[dict[str, Any]], Any],
        media_transport: str,
        unknown_event_name: str,
        disconnect_handler: Callable[[Any], Any] | None = None,
        client_hello_handler: Callable[[Any, dict[str, Any]], Any] | None = None,
        extra_message_handler: Callable[[Any, WebSocket, str, dict[str, Any]], Any] | None = None,
    ) -> None:
        await websocket.accept()
        session: Any | None = None
        loop_task: asyncio.Task[Any] | None = None
        try:
            while True:
                raw = await websocket.receive_text()
                payload = json.loads(raw)
                message_type = payload.get("type")

                if message_type == "client_hello":
                    session = create_session_from_hello(payload)
                    session.control_connected = True
                    if client_hello_handler is not None:
                        await _maybe_await(client_hello_handler(session, payload))
                    await send_json(
                        websocket,
                        self._session_accept_payload_provider(session, media_transport=media_transport),
                    )
                    await send_json(
                        websocket,
                        build_mode_state_payload(
                            session_id=str(getattr(session, "session_id", "")),
                            mode=str(getattr(session, "mode", "")),
                            mode_state=self._mode_state_provider(str(getattr(session, "mode", ""))),
                        ),
                    )
                    await send_json(websocket, self._make_hud_scene(session))
                    if loop_task is None:
                        loop_task = asyncio.create_task(self.result_loop(websocket, session))
                    continue

                if session is None:
                    await send_json(websocket, build_error_payload(message="client_hello required before other messages"))
                    continue

                session.last_message_at = self._activity_ts_provider()

                if await self.handle_session_control_message(session, websocket, str(message_type), payload):
                    continue
                if extra_message_handler is not None:
                    handled = await _maybe_await(extra_message_handler(session, websocket, str(message_type), payload))
                    if handled:
                        continue

                self._append_session_log(session, unknown_event_name, payload)
                await send_json(
                    websocket,
                    build_ack_payload(
                        session_id=str(getattr(session, "session_id", "")),
                        message_type=str(message_type),
                    ),
                )
        except WebSocketDisconnect:
            pass
        finally:
            if session is not None:
                session.last_message_at = self._activity_ts_provider()
                session.control_connected = False
                if disconnect_handler is not None:
                    await _maybe_await(disconnect_handler(session))
            if loop_task is not None:
                loop_task.cancel()
                with suppress(asyncio.CancelledError):
                    await loop_task
