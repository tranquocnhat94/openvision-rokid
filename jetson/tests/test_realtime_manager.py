import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.realtime_manager import RealtimeSessionManager
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


if __name__ == "__main__":
    unittest.main()
