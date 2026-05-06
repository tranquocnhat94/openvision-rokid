import asyncio
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.realtime_manager import (
    REALTIME_CONVERSATION_ITEM_KEEP,
    REALTIME_CONTEXT_REFRESH_RESPONSE_COUNT,
    REALTIME_TOOL_OUTPUT_MAX_CHARS,
    RealtimeSessionManager,
    _compact_server_event,
    _next_send_event,
    _server_event_severity,
)
from openvision_jetson.contracts import RealtimeStatus
from openvision_jetson.settings import RuntimeSettings
from openvision_jetson.skill_registry import SkillRegistry
from openvision_jetson.realtime_manager import _RealtimeConnection


def no_key_settings():
    return RuntimeSettings(
        environment="test",
        openai_api_key=None,
        realtime_model="gpt-realtime-1.5",
        realtime_voice="marin",
        realtime_url="wss://api.openai.com/v1/realtime",
    )


def keyed_settings():
    return RuntimeSettings(
        environment="test",
        openai_api_key="test-key",
        realtime_model="gpt-realtime-1.5",
        realtime_voice="marin",
        realtime_url="wss://api.openai.com/v1/realtime",
    )


class _FailingConnect:
    async def __aenter__(self):
        raise TimeoutError("timed out during opening handshake")

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _BlockingWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send(self, message):
        self.sent.append(message)

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(3600)
        raise StopAsyncIteration


class _FiniteWebSocket:
    def __init__(self, events):
        self.events = [json.dumps(event) for event in events]
        self.closed = False

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.events:
            raise StopAsyncIteration
        return self.events.pop(0)


class _SuccessfulConnect:
    def __init__(self, websocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb):
        return False


class RealtimeManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_blocks_without_api_key(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )

        status = await manager.start(session_id="sess_test")

        self.assertEqual(status["status"], "blocked")
        self.assertEqual(status["turn_policy"], "server_vad")
        self.assertEqual(status["error"]["code"], "missing_openai_api_key")
        self.assertEqual(events.list()[-1]["event_type"], "blocked")

    async def test_start_rejects_unknown_turn_policy(self):
        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )

        with self.assertRaises(ValueError):
            await manager.start(session_id="sess_test", turn_policy="local_gate")

    async def test_send_text_requires_connected_session(self):
        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )

        with self.assertRaises(RuntimeError):
            await manager.send_text(session_id="sess_missing", text="hello")

    async def test_start_retries_opening_handshake_timeout(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=keyed_settings,
        )
        websocket = _BlockingWebSocket()
        attempts = []

        def fake_connect(*_args, **_kwargs):
            attempts.append(_kwargs)
            if len(attempts) == 1:
                return _FailingConnect()
            return _SuccessfulConnect(websocket)

        with (
            patch("openvision_jetson.realtime_manager.websockets.connect", side_effect=fake_connect),
            patch("openvision_jetson.realtime_manager.REALTIME_CONNECT_RETRY_DELAY_S", 0.01),
        ):
            await manager.start(session_id="sess_retry")
            for _ in range(20):
                current = manager.status("sess_retry") or {}
                if current.get("status") == "connected":
                    break
                await asyncio.sleep(0.02)
            self.assertEqual((manager.status("sess_retry") or {})["status"], "connected")
            await manager.stop("sess_retry")

        self.assertEqual(len(attempts), 2)
        self.assertTrue(websocket.sent)
        sent_update = [
            event for event in events.list(session_id="sess_retry") if event["event_type"] == "session_update_sent"
        ][0]
        self.assertTrue(sent_update["payload"]["identity_marker"])
        self.assertGreaterEqual(sent_update["payload"]["tool_count"], 8)
        self.assertEqual(sent_update["payload"]["max_output_tokens"], 192)
        self.assertTrue(
            any(event["event_type"] == "connect_retry_scheduled" for event in events.list(session_id="sess_retry"))
        )

    async def test_output_text_done_notifies_handler(self):
        seen = []
        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
            response_text_handler=lambda session_id, text: seen.append((session_id, text)),
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
            )
        )

        manager._handle_output_text(connection, {"type": "response.output_text.delta", "item_id": "item_1", "delta": "Xin "})
        manager._handle_output_text(connection, {"type": "response.output_text.delta", "item_id": "item_1", "delta": "chào"})
        manager._handle_output_text(connection, {"type": "response.output_text.done", "item_id": "item_1"})

        self.assertEqual(seen, [("sess_test", "Xin chào")])

    async def test_session_expired_error_marks_connection_expired(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )
        websocket = _FiniteWebSocket(
            [
                {
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "code": "session_expired",
                        "message": "Your session hit the maximum duration of 60 minutes.",
                    },
                }
            ]
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="server_vad",
            ),
            websocket=websocket,
            response_active=True,
            response_create_pending=True,
            response_create_deferred=True,
        )

        await manager._receive_loop(connection)

        self.assertEqual(connection.status.status, "expired")
        self.assertEqual(connection.status.error["code"], "session_expired")
        self.assertFalse(connection.response_active)
        self.assertFalse(connection.response_create_pending)
        self.assertFalse(connection.response_create_deferred)
        self.assertTrue(websocket.closed)
        self.assertEqual((await connection.send_queue.get()), None)
        self.assertTrue(any(event["event_type"] == "expired" for event in events.list(session_id="sess_test")))

    async def test_insufficient_quota_error_notifies_hud_and_stops_connection(self):
        events = InMemoryEventStore()
        seen_text = []
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
            response_text_handler=lambda session_id, text: seen_text.append((session_id, text)),
        )
        websocket = _FiniteWebSocket(
            [
                {
                    "type": "error",
                    "error": {
                        "type": "insufficient_quota",
                        "code": "insufficient_quota",
                        "message": "You exceeded your current quota.",
                    },
                }
            ]
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="server_vad",
            ),
            websocket=websocket,
            response_active=True,
            response_create_pending=True,
            response_create_deferred=True,
        )

        await manager._receive_loop(connection)

        self.assertEqual(connection.status.status, "error")
        self.assertEqual(connection.status.error["code"], "insufficient_quota")
        self.assertFalse(connection.response_active)
        self.assertFalse(connection.response_create_pending)
        self.assertFalse(connection.response_create_deferred)
        self.assertTrue(websocket.closed)
        self.assertEqual((await connection.send_queue.get()), None)
        self.assertEqual(seen_text[0][0], "sess_test")
        self.assertIn("OpenAI Realtime hết quota", seen_text[0][1])
        self.assertTrue(any(event["event_type"] == "terminal_error" for event in events.list(session_id="sess_test")))

    async def test_repeated_failed_responses_schedule_reconnect(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=keyed_settings,
        )
        restart_calls = []

        async def fake_restart(**kwargs):
            restart_calls.append(kwargs)

        manager._restart_connection = fake_restart
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="server_vad",
                output_modalities=["audio"],
            )
        )
        failed = {
            "type": "response.done",
            "response": {
                "id": "resp_failed",
                "status": "failed",
                "status_details": {
                    "type": "failed",
                    "reason": None,
                    "error": {"code": "server_error", "message": "temporary failure"},
                },
                "output": [],
            },
        }

        await manager._handle_response_lifecycle(connection, failed)
        await manager._handle_response_lifecycle(connection, failed)
        await manager._handle_response_lifecycle(connection, failed)
        await asyncio.sleep(0)

        self.assertEqual(connection.status.status, "reconnecting")
        self.assertTrue(connection.reconnect_scheduled)
        self.assertFalse(connection.response_active)
        self.assertFalse(connection.response_create_pending)
        self.assertEqual(len(restart_calls), 1)
        self.assertEqual(restart_calls[0]["session_id"], "sess_test")
        event_types = [event["event_type"] for event in events.list(session_id="sess_test")]
        self.assertEqual(event_types.count("response_failed"), 3)
        self.assertIn("reconnect_scheduled", event_types)
        self.assertEqual(event_types.count("recovery_clear_audio_queued"), 2)

    async def test_rate_limit_failed_response_reconnects_immediately(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=keyed_settings,
        )
        restart_calls = []

        async def fake_restart(**kwargs):
            restart_calls.append(kwargs)

        manager._restart_connection = fake_restart
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="server_vad",
                output_modalities=["audio"],
            )
        )
        event = {
            "type": "response.done",
            "response": {
                "id": "resp_rate",
                "status": "failed",
                "status_details": {
                    "type": "failed",
                    "reason": None,
                    "error": {"code": "rate_limit_exceeded", "message": "TPM exceeded"},
                },
                "output": [],
            },
        }

        await manager._handle_response_lifecycle(connection, event)
        await asyncio.sleep(0)

        self.assertEqual(connection.status.status, "reconnecting")
        self.assertTrue(connection.reconnect_scheduled)
        self.assertEqual(connection.status.error["code"], "realtime_rate_limit_exceeded")
        self.assertEqual(len(restart_calls), 1)
        event_types = [item["event_type"] for item in events.list(session_id="sess_test")]
        self.assertIn("response_failed", event_types)
        self.assertIn("reconnect_scheduled", event_types)
        self.assertNotIn("recovery_clear_audio_queued", event_types)

    async def test_low_token_rate_limit_budget_warns_once_per_drop(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=keyed_settings,
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="server_vad",
            )
        )

        manager._handle_rate_limits(
            connection,
            {
                "type": "rate_limits.updated",
                "rate_limits": [
                    {"name": "requests", "limit": 100, "remaining": 99, "reset_seconds": 2},
                    {"name": "tokens", "limit": 20000, "remaining": 5900, "reset_seconds": 8},
                ],
            },
        )
        manager._handle_rate_limits(
            connection,
            {
                "type": "rate_limits.updated",
                "rate_limits": [
                    {"name": "tokens", "limit": 20000, "remaining": 5800, "reset_seconds": 7},
                ],
            },
        )
        manager._handle_rate_limits(
            connection,
            {
                "type": "rate_limits.updated",
                "rate_limits": [
                    {"name": "tokens", "limit": 20000, "remaining": 4800, "reset_seconds": 6},
                ],
            },
        )

        warnings = [event for event in events.list(session_id="sess_test") if event["event_type"] == "rate_limit_budget_low"]
        self.assertEqual(len(warnings), 2)
        self.assertEqual(warnings[0]["payload"]["remaining"], 5900)
        self.assertEqual(warnings[1]["payload"]["remaining"], 4800)

    async def test_completed_responses_refresh_context_before_budget_bloat(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=keyed_settings,
        )
        restart_calls = []

        async def fake_restart(**kwargs):
            restart_calls.append(kwargs)

        manager._restart_connection = fake_restart
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="server_vad",
                output_modalities=["audio"],
            ),
            response_done_count=REALTIME_CONTEXT_REFRESH_RESPONSE_COUNT - 1,
        )

        await manager._handle_response_lifecycle(
            connection,
            {"type": "response.done", "response": {"id": "resp_ok", "status": "completed", "output": []}},
        )
        await asyncio.sleep(0)

        self.assertEqual(connection.status.status, "reconnecting")
        self.assertEqual(connection.status.error["code"], "context_budget_refresh")
        self.assertTrue(connection.reconnect_scheduled)
        self.assertEqual(len(restart_calls), 1)
        event = next(event for event in events.list(session_id="sess_test") if event["event_type"] == "reconnect_scheduled")
        self.assertEqual(event["payload"]["reason"], "context_budget_refresh")

    async def test_output_audio_transcript_done_notifies_text_handler(self):
        seen = []
        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
            response_text_handler=lambda session_id, text: seen.append((session_id, text)),
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
            )
        )

        manager._handle_output_audio_transcript(
            connection,
            {"type": "response.output_audio_transcript.delta", "item_id": "item_1", "delta": "Có "},
        )
        manager._handle_output_audio_transcript(
            connection,
            {"type": "response.output_audio_transcript.delta", "item_id": "item_1", "delta": "3 người"},
        )
        manager._handle_output_audio_transcript(
            connection,
            {"type": "response.output_audio_transcript.done", "item_id": "item_1"},
        )

        self.assertEqual(seen, [("sess_test", "Có 3 người")])

    async def test_send_text_defers_response_create_while_response_is_active(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
                output_modalities=["audio"],
            ),
            response_active=True,
        )
        manager._connections["sess_test"] = connection

        await manager.send_text(session_id="sess_test", text="Nội bộ Jetson: kết quả sẵn sàng")

        item = await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)
        self.assertEqual(item["type"], "conversation.item.create")
        self.assertTrue(connection.response_create_deferred)
        self.assertTrue(
            any(event["event_type"] == "response_create_deferred" for event in events.list(session_id="sess_test"))
        )

        await manager._handle_response_lifecycle(connection, {"type": "response.done", "response": {"status": "completed"}})
        response = await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)

        self.assertEqual(response["type"], "response.create")
        self.assertFalse(connection.response_create_deferred)
        self.assertTrue(connection.response_create_pending)

    async def test_response_done_prunes_old_conversation_items(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="server_vad",
            )
        )
        for idx in range(REALTIME_CONVERSATION_ITEM_KEEP + 3):
            manager._track_conversation_item(
                connection,
                {"type": "conversation.item.added", "item": {"id": f"item_{idx}"}},
            )

        await manager._handle_response_lifecycle(
            connection,
            {"type": "response.done", "response": {"status": "completed"}},
        )

        deletes = [await asyncio.wait_for(connection.send_queue.get(), timeout=1.0) for _ in range(3)]
        self.assertEqual([event["type"] for event in deletes], ["conversation.item.delete"] * 3)
        self.assertEqual([event["item_id"] for event in deletes], ["item_0", "item_1", "item_2"])
        self.assertEqual(len(connection.conversation_item_ids), REALTIME_CONVERSATION_ITEM_KEEP)
        self.assertTrue(
            any(event["event_type"] == "conversation_prune_queued" for event in events.list(session_id="sess_test"))
        )

    async def test_commit_audio_is_ordered_after_queued_audio_appends(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="server_vad",
            )
        )
        manager._connections["sess_test"] = connection

        await manager.append_audio(session_id="sess_test", pcm_bytes=b"one")
        await manager.append_audio(session_id="sess_test", pcm_bytes=b"two")
        await manager.commit_audio(session_id="sess_test")

        ordered_types = [
            (await _next_send_event(connection))["type"],
            (await _next_send_event(connection))["type"],
            (await _next_send_event(connection))["type"],
            (await _next_send_event(connection))["type"],
        ]
        event_payloads = [event["payload"] for event in events.list(session_id="sess_test")]

        self.assertEqual(
            ordered_types,
            [
                "input_audio_buffer.append",
                "input_audio_buffer.append",
                "input_audio_buffer.commit",
                "response.create",
            ],
        )
        self.assertIn({"type": "input_audio_buffer.commit", "queue": "audio_ordered"}, event_payloads)
        self.assertIn({"source": "client", "queue": "audio_ordered"}, event_payloads)

    async def test_output_audio_transcript_done_prefers_final_transcript(self):
        seen = []
        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
            response_text_handler=lambda session_id, text: seen.append((session_id, text)),
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
            )
        )

        manager._handle_output_audio_transcript(
            connection,
            {"type": "response.output_audio_transcript.delta", "item_id": "item_1", "delta": "bản nháp"},
        )
        manager._handle_output_audio_transcript(
            connection,
            {
                "type": "response.output_audio_transcript.done",
                "item_id": "item_1",
                "transcript": "Bản cuối hiển thị lên HUD.",
            },
        )

        self.assertEqual(seen, [("sess_test", "Bản cuối hiển thị lên HUD.")])

    async def test_output_audio_transcript_done_compacts_preview(self):
        payload = _compact_server_event(
            {
                "type": "response.output_audio_transcript.done",
                "transcript": "Đã nhận lệnh và đang xử lý.",
            }
        )

        self.assertEqual(payload["type"], "response.output_audio_transcript.done")
        self.assertEqual(payload["chars"], len("Đã nhận lệnh và đang xử lý."))
        self.assertEqual(payload["preview"], "Đã nhận lệnh và đang xử lý.")

    async def test_failed_response_compacts_error_details_and_warns(self):
        event = {
            "type": "response.done",
            "response": {
                "id": "resp_failed",
                "status": "failed",
                "status_details": {
                    "type": "failed",
                    "reason": None,
                    "error": {
                        "type": "server_error",
                        "code": "internal_error",
                        "message": "temporary failure",
                    },
                },
                "output": [],
            },
        }

        payload = _compact_server_event(event)

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["status_details_type"], "failed")
        self.assertEqual(payload["status_details_error"]["code"], "internal_error")
        self.assertEqual(payload["status_details_error"]["message"], "temporary failure")
        self.assertEqual(_server_event_severity(event), "error")

    async def test_response_done_compacts_usage_for_cost_telemetry(self):
        event = {
            "type": "response.done",
            "response": {
                "id": "resp_usage",
                "status": "completed",
                "output": [],
                "usage": {
                    "total_tokens": 253,
                    "input_tokens": 132,
                    "output_tokens": 121,
                    "input_token_details": {
                        "text_tokens": 119,
                        "audio_tokens": 13,
                        "image_tokens": 0,
                        "cached_tokens": 64,
                        "cached_tokens_details": {
                            "text_tokens": 64,
                            "audio_tokens": 0,
                            "image_tokens": 0,
                        },
                    },
                    "output_token_details": {
                        "text_tokens": 30,
                        "audio_tokens": 91,
                    },
                },
            },
        }

        payload = _compact_server_event(event)

        self.assertEqual(payload["usage"]["total_tokens"], 253)
        self.assertEqual(payload["usage"]["input_token_details"]["audio_tokens"], 13)
        self.assertEqual(payload["usage"]["input_token_details"]["cached_tokens"], 64)
        self.assertEqual(payload["usage"]["output_token_details"]["audio_tokens"], 91)

    async def test_tool_calls_are_scheduled_off_receive_loop(self):
        def slow_skill_handler(name, args, session_id):
            time.sleep(0.2)
            return {"status": "ok", "result": {"name": name, "args": args, "session_id": session_id}}

        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
            skill_handler=slow_skill_handler,
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
            )
        )
        event = {
            "type": "response.done",
            "response": {
                "output": [
                    {
                        "type": "function_call",
                        "name": "count_people",
                        "call_id": "call_1",
                        "arguments": "{\"min_confidence\": 0.5}",
                    }
                ]
            },
        }

        started = time.monotonic()
        await manager._handle_tool_calls(connection, event)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.05)
        self.assertEqual(len(connection.tool_tasks), 1)
        output = await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)
        response = await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)
        self.assertEqual(output["item"]["type"], "function_call_output")
        payload = json.loads(output["item"]["output"])
        self.assertEqual(payload["schema_version"], "openvision.tool_result.v1")
        self.assertEqual(payload["tool_name"], "count_people")
        self.assertEqual(payload["result"]["result"]["session_id"], "sess_test")
        self.assertEqual(response["type"], "response.create")

    async def test_voice_output_uses_audio_only_for_tool_response(self):
        def skill_handler(name, args, session_id):
            return {"status": "ok", "result": {"name": name}}

        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
            skill_handler=skill_handler,
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
                output_modalities=["audio"],
            )
        )
        event = {
            "type": "response.done",
            "response": {
                "output": [
                    {
                        "type": "function_call",
                        "name": "count_people",
                        "call_id": "call_1",
                        "arguments": "{}",
                    }
                ]
            },
        }

        await manager._handle_tool_calls(connection, event)
        await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)
        response = await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)

        self.assertEqual(response["response"]["output_modalities"], ["audio"])

    async def test_interim_media_tool_output_skips_realtime_response_create(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
            )
        )
        output = {
            "schema_version": "openvision.tool_result.v1",
            "tool_call_id": "call_scene",
            "tool_name": "scene_describe",
            "session_id": "sess_test",
            "status": "no_evidence",
            "result": {
                "status": "no_evidence",
                "result": {
                    "user_message": "Đang bật camera để lấy ảnh.",
                    "media_command": {
                        "command_id": "cmd_1",
                        "mode": "snapshot",
                        "skill_id": "scene_describe",
                    },
                    "media_event": {
                        "event_id": "evt_1",
                        "command_id": "cmd_1",
                        "status": "queued",
                    },
                },
            },
        }

        await manager._queue_tool_result(
            connection,
            output=output,
            name="scene_describe",
            call_id="call_scene",
        )

        queued = await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)
        self.assertEqual(queued["item"]["type"], "function_call_output")
        self.assertTrue(connection.send_queue.empty())
        event = next(event for event in events.list(session_id="sess_test") if event["event_type"] == "tool_output_queued")
        self.assertFalse(event["payload"]["response_create_queued"])
        self.assertTrue(event["payload"]["interim_media_request"])

    async def test_tool_output_compacts_face_identity_payload_for_realtime(self):
        events = InMemoryEventStore()
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
            )
        )
        output = {
            "schema_version": "openvision.tool_result.v1",
            "tool_call_id": "call_face",
            "tool_name": "person_info",
            "session_id": "sess_test",
            "status": "ok",
            "duration_ms": 42,
            "result": {
                "status": "ok",
                "result": {
                    "answer": "Miu Thúi",
                    "user_message": "Miu Thúi",
                    "identity_provider": {
                        "status": "confirmed",
                        "candidate_count": 1,
                        "candidate_vector_count": 1,
                        "best_score": 0.64,
                        "best_match": {
                            "contact_id": "contact_miu",
                            "display_name": "Miu Thúi",
                            "confidence": 0.64,
                            "identity_vector": [0.1] * 256,
                        },
                        "matches": [
                            {
                                "contact_id": "contact_miu",
                                "display_name": "Miu Thúi",
                                "confidence": 0.64,
                                "identity_vector": [0.1] * 256,
                            }
                        ],
                    },
                    "candidates": [
                        {
                            "target_id": "person_1",
                            "label": "person",
                            "attributes": {
                                "detector_family": "face_identity",
                                "identity_vector": [0.2] * 512,
                            },
                        }
                    ],
                },
            },
        }

        await manager._queue_tool_result(
            connection,
            output=output,
            name="person_info",
            call_id="call_face",
        )

        queued = await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)
        payload_text = queued["item"]["output"]
        payload = json.loads(payload_text)
        self.assertLessEqual(len(payload_text), REALTIME_TOOL_OUTPUT_MAX_CHARS)
        self.assertNotIn("identity_vector", payload_text)
        self.assertEqual(payload["result"]["result"]["answer"], "Miu Thúi")
        self.assertEqual(
            payload["result"]["result"]["identity_provider"]["best_match"]["display_name"],
            "Miu Thúi",
        )
        compact_event = next(
            event for event in events.list(session_id="sess_test") if event["event_type"] == "tool_output_queued"
        )
        self.assertTrue(compact_event["payload"]["compacted"])
        self.assertLessEqual(compact_event["payload"]["output_chars"], REALTIME_TOOL_OUTPUT_MAX_CHARS)

    async def test_output_audio_delta_notifies_handler(self):
        seen = []
        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
            response_audio_handler=lambda session_id, audio, byte_count: seen.append((session_id, audio, byte_count)),
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
            )
        )

        manager._handle_output_audio(connection, {"type": "response.output_audio.delta", "delta": "AAE="})

        self.assertEqual(seen, [("sess_test", "AAE=", 2)])

    async def test_output_audio_done_notifies_handler(self):
        seen = []
        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
            response_audio_done_handler=lambda session_id: seen.append(session_id),
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
            )
        )

        manager._handle_output_audio(connection, {"type": "response.output_audio.done"})

        self.assertEqual(seen, ["sess_test"])

    async def test_realtime_send_queue_is_bounded(self):
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
            )
        )

        self.assertGreater(connection.send_queue.maxsize, 0)
        self.assertGreater(connection.audio_queue.maxsize, 0)

    async def test_audio_queue_does_not_block_tool_control_events(self):
        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )
        connection = _RealtimeConnection(
            status=RealtimeStatus(
                session_id="sess_test",
                status="connected",
                model="gpt-realtime-1.5",
                turn_policy="manual",
            )
        )

        for _ in range(connection.audio_queue.maxsize + 3):
            await manager._queue_event(
                connection,
                {"type": "input_audio_buffer.append", "audio": "AAE="},
                source="client",
            )
        await manager._queue_event(
            connection,
            {"type": "conversation.item.create"},
            source="tool",
        )

        self.assertEqual(connection.audio_queue.qsize(), connection.audio_queue.maxsize)
        self.assertEqual((await connection.send_queue.get())["type"], "conversation.item.create")


if __name__ == "__main__":
    unittest.main()
