import asyncio
import json
import sys
import types
import unittest
from types import SimpleNamespace

try:
    from fastapi import WebSocketDisconnect
except Exception:  # pragma: no cover - local test env may not install FastAPI
    fastapi_stub = types.ModuleType("fastapi")

    class WebSocketDisconnect(Exception):
        def __init__(self, code: int = 1000) -> None:
            super().__init__(code)
            self.code = code

    class WebSocket:  # noqa: D401 - tiny stub for runtime import
        pass

    fastapi_stub.WebSocket = WebSocket
    fastapi_stub.WebSocketDisconnect = WebSocketDisconnect
    sys.modules.setdefault("fastapi", fastapi_stub)

from app.websocket_control_runtime import SessionControlRuntime


class _FakeWebSocket:
    def __init__(self, messages: list[str] | None = None) -> None:
        self._messages = list(messages or [])
        self.sent: list[dict[str, object]] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if not self._messages:
            raise WebSocketDisconnect(code=1000)
        return self._messages.pop(0)

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


class WebsocketControlRuntimeTest(unittest.TestCase):
    def _build_runtime(self, events: list[tuple[str, dict[str, object]]]) -> SessionControlRuntime:
        def append_log(session: SimpleNamespace, event: str, payload: dict[str, object]) -> None:
            events.append((event, dict(payload)))

        return SessionControlRuntime(
            session_accept_payload_provider=lambda session, media_transport: {
                "type": "session_accept",
                "sessionId": session.session_id,
                "media": {"transport": media_transport},
            },
            mode_state_provider=lambda mode: {"shellLabel": mode},
            make_hud_scene=lambda session, **kwargs: {"type": "hud_scene", "sessionId": session.session_id, **kwargs},
            make_speech_state=lambda session, **kwargs: {"type": "speech_state", "sessionId": session.session_id, **kwargs},
            make_result=lambda session: {"type": "vision_result", "sessionId": session.session_id},
            make_node_telemetry=lambda session: {"type": "node_telemetry", "sessionId": session.session_id},
            drain_control_events=lambda session_id: [],
            append_session_log=append_log,
            result_interval_provider=lambda mode: 10_000,
            now_ms_provider=lambda: 1234,
            activity_ts_provider=lambda: 55.0,
        )

    def test_handle_session_control_message_updates_mode_and_push_to_talk(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = self._build_runtime(events)
        websocket = _FakeWebSocket()
        session = SimpleNamespace(
            session_id="sess_demo",
            mode="standby",
            last_ping_at=0.0,
            latest_device_telemetry={},
            latest_audio_stats={},
            latest_encoder_stats={},
            control_connected=True,
        )

        async def scenario() -> None:
            handled_mode = await runtime.handle_session_control_message(
                session,
                websocket,
                "mode_change",
                {"mode": "visual_assistant"},
            )
            handled_ptt = await runtime.handle_session_control_message(
                session,
                websocket,
                "ptt_down",
                {},
            )
            handled_ping = await runtime.handle_session_control_message(
                session,
                websocket,
                "ping",
                {},
            )
            self.assertTrue(handled_mode)
            self.assertTrue(handled_ptt)
            self.assertTrue(handled_ping)

        asyncio.run(scenario())

        self.assertEqual(session.mode, "visual_assistant")
        self.assertEqual(session.last_ping_at, 55.0)
        self.assertEqual([payload["type"] for payload in websocket.sent], ["mode_state", "speech_state", "hud_scene", "pong"])
        self.assertEqual(events[0][0], "mode_change")
        self.assertEqual(events[1][0], "ptt_down")

    def test_run_endpoint_handles_client_hello_ping_and_unknown_ack(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = self._build_runtime(events)
        created: list[SimpleNamespace] = []
        disconnected: list[str] = []

        def create_session(payload: dict[str, object]) -> SimpleNamespace:
            session = SimpleNamespace(
                session_id="sess_browser",
                mode=str(payload.get("selectedMode") or "standby"),
                control_connected=False,
                last_message_at=0.0,
                last_ping_at=0.0,
                latest_device_telemetry={},
                latest_audio_stats={},
                latest_encoder_stats={},
            )
            created.append(session)
            return session

        async def on_disconnect(session: SimpleNamespace) -> None:
            disconnected.append(session.session_id)

        websocket = _FakeWebSocket(
            messages=[
                json.dumps({"type": "client_hello", "selectedMode": "scene_monitor"}),
                json.dumps({"type": "ping"}),
                json.dumps({"type": "unknown_event", "value": 1}),
            ]
        )

        async def scenario() -> None:
            await runtime.run_endpoint(
                websocket,
                create_session_from_hello=create_session,
                media_transport="browser_webrtc",
                unknown_event_name="browser_ack_unknown",
                disconnect_handler=on_disconnect,
            )

        asyncio.run(scenario())

        self.assertTrue(websocket.accepted)
        self.assertEqual(created[0].mode, "scene_monitor")
        self.assertEqual(disconnected, ["sess_browser"])
        self.assertEqual(
            [payload["type"] for payload in websocket.sent],
            ["session_accept", "mode_state", "hud_scene", "pong", "ack"],
        )
        self.assertEqual(events[-1][0], "browser_ack_unknown")


if __name__ == "__main__":
    unittest.main()
