import asyncio
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.realtime_manager import RealtimeSessionManager, _compact_server_event
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
        self.assertEqual(status["error"]["code"], "missing_openai_api_key")
        self.assertEqual(events.list()[-1]["event_type"], "blocked")

    async def test_send_text_requires_connected_session(self):
        manager = RealtimeSessionManager(
            events=InMemoryEventStore(),
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
        )

        with self.assertRaises(RuntimeError):
            await manager.send_text(session_id="sess_missing", text="hello")

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
        self.assertEqual(response["type"], "response.create")

    async def test_voice_output_modalities_are_preserved_for_tool_response(self):
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
                output_modalities=["text", "audio"],
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

        self.assertEqual(response["response"]["output_modalities"], ["text", "audio"])

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
