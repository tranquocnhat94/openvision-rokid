import asyncio
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.contracts import RealtimeStatus
from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.realtime_manager import RealtimeSessionManager, _RealtimeConnection
from openvision_jetson.settings import RuntimeSettings
from openvision_jetson.skill_registry import SkillRegistry


def no_key_settings():
    return RuntimeSettings(
        environment="test",
        openai_api_key=None,
        realtime_model="gpt-realtime-1.5",
        realtime_voice="marin",
        realtime_url="wss://api.openai.com/v1/realtime",
    )


class RealtimeVietnameseRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_vietnamese_greeting_route_stays_conversational(self):
        events = InMemoryEventStore()
        seen_text = []
        skill_calls = []
        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
            skill_handler=lambda name, args, session_id: skill_calls.append((name, args, session_id)) or {"status": "ok"},
            response_text_handler=lambda session_id, text: seen_text.append((session_id, text)),
        )
        connection = _connected()

        manager._handle_output_audio_transcript(
            connection,
            {
                "type": "response.output_audio_transcript.done",
                "item_id": "item_greeting",
                "transcript": "Chào bạn, mình nghe đây.",
            },
        )
        await manager._handle_tool_calls(
            connection,
            {
                "type": "response.done",
                "response": {
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Chào bạn, mình nghe đây."}],
                        }
                    ]
                },
            },
        )

        self.assertEqual(seen_text, [("sess_vi", "Chào bạn, mình nghe đây.")])
        self.assertEqual(skill_calls, [])
        self.assertEqual(len(connection.tool_tasks), 0)
        self.assertFalse(any(event["module"] == "realtime_tool" for event in events.list(session_id="sess_vi")))

    async def test_vietnamese_scene_question_routes_through_typed_tool(self):
        events = InMemoryEventStore()
        skill_calls = []

        def skill_handler(name, args, session_id):
            skill_calls.append((name, args, session_id))
            return {
                "skill_call_id": "skill_vi_scene",
                "name": name,
                "args": args,
                "session_id": session_id,
                "status": "no_evidence",
                "result": {
                    "user_message": "Đang bật camera để lấy ảnh.",
                    "media_command": {
                        "command_id": "media_cmd_test",
                        "mode": "snapshot",
                        "session_id": session_id,
                        "skill_id": name,
                    },
                },
            }

        manager = RealtimeSessionManager(
            events=events,
            skills=SkillRegistry(),
            settings_provider=no_key_settings,
            skill_handler=skill_handler,
        )
        connection = _connected()

        await manager._handle_tool_calls(
            connection,
            {
                "type": "response.done",
                "response": {
                    "output": [
                        {
                            "type": "function_call",
                            "name": "scene_describe",
                            "call_id": "call_vi_scene",
                            "arguments": json.dumps({"focus": "đang có gì trước mặt"}, ensure_ascii=False),
                        }
                    ]
                },
            },
        )

        function_output = await asyncio.wait_for(connection.send_queue.get(), timeout=1.0)
        tool_payload = json.loads(function_output["item"]["output"])

        self.assertEqual(skill_calls, [("scene_describe", {"focus": "đang có gì trước mặt"}, "sess_vi")])
        self.assertEqual(function_output["item"]["type"], "function_call_output")
        self.assertEqual(function_output["item"]["call_id"], "call_vi_scene")
        self.assertEqual(tool_payload["schema_version"], "openvision.tool_result.v1")
        self.assertEqual(tool_payload["tool_name"], "scene_describe")
        self.assertEqual(tool_payload["status"], "no_evidence")
        self.assertEqual(tool_payload["result"]["result"]["media_command"]["mode"], "snapshot")
        self.assertTrue(connection.send_queue.empty())
        self.assertTrue(
            any(
                event["module"] == "realtime_tool"
                and event["event_type"] == "call_completed"
                and event["payload"]["tool_name"] == "scene_describe"
                for event in events.list(session_id="sess_vi")
            )
        )


def _connected() -> _RealtimeConnection:
    return _RealtimeConnection(
        status=RealtimeStatus(
            session_id="sess_vi",
            status="connected",
            model="gpt-realtime-1.5",
            turn_policy="server_vad",
            output_modalities=["audio"],
        )
    )


if __name__ == "__main__":
    unittest.main()
