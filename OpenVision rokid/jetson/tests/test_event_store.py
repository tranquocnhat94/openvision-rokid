import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore


class EventStoreTest(unittest.TestCase):
    def test_key_events_survive_rolling_cap_and_session_limit(self):
        events = InMemoryEventStore(max_events=3, max_key_events=20)

        events.add(
            "rv101_control",
            "session_accept",
            {"voice_mode": "conversation_realtime", "turn_policy": "server_vad"},
            session_id="sess_long",
        )
        events.add(
            "realtime_tool",
            "call_completed",
            {"tool_name": "target_finder", "status": "ok", "duration_ms": 42},
            session_id="sess_long",
        )
        for index in range(20):
            events.add("hud", "scene_updated", {"index": index}, session_id="sess_long")

        replay_events = events.list(session_id="sess_long", limit=3)
        event_types = [event["event_type"] for event in replay_events]

        self.assertLessEqual(len(replay_events), 3)
        self.assertIn("session_accept", event_types)
        self.assertIn("call_completed", event_types)
        self.assertEqual(event_types[-1], "scene_updated")

    def test_limit_is_strict_even_when_key_events_exceed_limit(self):
        events = InMemoryEventStore(max_events=1, max_key_events=20)
        for index in range(8):
            events.add(
                "realtime_tool",
                "call_completed",
                {"tool_name": "target_finder", "index": index},
                session_id="sess_long",
            )

        replay_events = events.list(session_id="sess_long", limit=3)

        self.assertEqual(len(replay_events), 3)
        self.assertEqual([event["payload"]["index"] for event in replay_events], [5, 6, 7])


if __name__ == "__main__":
    unittest.main()
