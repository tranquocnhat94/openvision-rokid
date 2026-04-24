import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.realtime_events import (
    append_audio_event,
    function_call_output_event,
    parse_function_calls,
    session_update_event,
    turn_detection_for,
)


class RealtimeEventsTest(unittest.TestCase):
    def test_manual_turn_policy_disables_vad(self):
        self.assertIsNone(turn_detection_for("manual"))

    def test_semantic_vad_uses_low_eagerness(self):
        policy = turn_detection_for("semantic_vad")
        self.assertEqual(policy["type"], "semantic_vad")
        self.assertEqual(policy["eagerness"], "low")
        self.assertFalse(policy["interrupt_response"])

    def test_server_vad_does_not_interrupt_active_response(self):
        policy = turn_detection_for("server_vad")
        self.assertEqual(policy["type"], "server_vad")
        self.assertTrue(policy["create_response"])
        self.assertFalse(policy["interrupt_response"])

    def test_session_update_registers_tools(self):
        event = session_update_event(
            model="gpt-realtime-1.5",
            voice="marin",
            tools=[{"type": "function", "name": "count_people", "parameters": {"type": "object"}}],
            turn_policy="manual",
            output_modalities=["text"],
        )

        self.assertEqual(event["type"], "session.update")
        self.assertEqual(event["session"]["model"], "gpt-realtime-1.5")
        self.assertEqual(event["session"]["tools"][0]["name"], "count_people")
        self.assertIsNone(event["session"]["audio"]["input"]["turn_detection"])
        self.assertEqual(event["session"]["audio"]["input"]["format"]["rate"], 24000)
        self.assertEqual(event["session"]["audio"]["output"]["format"]["rate"], 24000)
        self.assertNotIn("transcription", event["session"]["audio"]["input"])
        self.assertIn("needs_cloud", event["session"]["instructions"])
        self.assertIn("candidate", event["session"]["instructions"])

    def test_audio_append_base64_encodes_pcm(self):
        event = append_audio_event(b"\x00\x01")

        self.assertEqual(event["type"], "input_audio_buffer.append")
        self.assertEqual(event["audio"], "AAE=")

    def test_function_call_output_is_json_string(self):
        event = function_call_output_event(call_id="call_1", output={"count": 2})

        self.assertEqual(event["item"]["type"], "function_call_output")
        self.assertEqual(event["item"]["call_id"], "call_1")
        self.assertIn('"count": 2', event["item"]["output"])

    def test_parse_function_calls_from_response_done(self):
        calls = parse_function_calls(
            {
                "type": "response.done",
                "response": {
                    "output": [
                        {
                            "type": "function_call",
                            "name": "count_people",
                            "call_id": "call_1",
                            "arguments": "{\"frame_window_ms\": 1000}",
                        }
                    ]
                },
            }
        )

        self.assertEqual(calls[0]["name"], "count_people")
        self.assertEqual(calls[0]["arguments"]["frame_window_ms"], 1000)


if __name__ == "__main__":
    unittest.main()
