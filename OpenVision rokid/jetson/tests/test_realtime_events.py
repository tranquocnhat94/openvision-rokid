import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.realtime_events import (
    append_audio_event,
    conversation_item_delete_event,
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

    def test_server_vad_waits_longer_and_does_not_cancel_replies(self):
        policy = turn_detection_for("server_vad")
        self.assertEqual(policy["type"], "server_vad")
        self.assertTrue(policy["create_response"])
        self.assertFalse(policy["interrupt_response"])
        self.assertEqual(policy["threshold"], 0.45)
        self.assertEqual(policy["prefix_padding_ms"], 500)
        self.assertEqual(policy["silence_duration_ms"], 900)

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
        self.assertEqual(event["session"]["max_output_tokens"], 192)
        self.assertIsNone(event["session"]["audio"]["input"]["turn_detection"])
        self.assertEqual(event["session"]["audio"]["input"]["format"]["rate"], 24000)
        self.assertEqual(event["session"]["audio"]["output"]["format"]["rate"], 24000)
        self.assertNotIn("transcription", event["session"]["audio"]["input"])
        self.assertIn("needs_cloud", event["session"]["instructions"])
        self.assertIn("candidate", event["session"]["instructions"])
        self.assertIn("trả lời trực tiếp", event["session"]["instructions"])
        self.assertIn("không gọi tool", event["session"]["instructions"])
        self.assertIn("không theo câu lệnh cố định", event["session"]["instructions"])
        self.assertIn("Đừng đợi người", event["session"]["instructions"])
        self.assertIn("theo ý định", event["session"]["instructions"])
        self.assertIn("nói tắt", event["session"]["instructions"])
        self.assertIn("có thể làm X không", event["session"]["instructions"])
        self.assertIn("đang có gì trước mặt tôi", event["session"]["instructions"])
        self.assertIn("scene_describe", event["session"]["instructions"])
        self.assertIn("tôi đang nhìn thấy gì", event["session"]["instructions"])
        self.assertIn("nhìn hộ tôi xem có gì", event["session"]["instructions"])
        self.assertIn("Nếu phân vân với scene_describe", event["session"]["instructions"])
        self.assertIn("count_people", event["session"]["instructions"])
        self.assertIn("object_counter", event["session"]["instructions"])
        self.assertIn("text_reader", event["session"]["instructions"])
        self.assertIn("biển này ghi gì", event["session"]["instructions"])
        self.assertIn("giúp tôi dòng này", event["session"]["instructions"])
        self.assertIn("target_finder", event["session"]["instructions"])
        self.assertIn('"tìm Trâm"', event["session"]["instructions"])
        self.assertIn("target_name", event["session"]["instructions"])
        self.assertIn("identity_query=true", event["session"]["instructions"])
        self.assertIn("Không rút gọn", event["session"]["instructions"])
        self.assertIn('target_type="person"', event["session"]["instructions"])
        self.assertIn("không trả lời rằng skill chưa bật", event["session"]["instructions"])
        self.assertIn("person_info", event["session"]["instructions"])
        self.assertIn("có ai quen không", event["session"]["instructions"])
        self.assertIn("đây là ai", event["session"]["instructions"])
        self.assertIn("nhắc tên người này", event["session"]["instructions"])
        self.assertIn("nhắc tên Trâm", event["session"]["instructions"])
        self.assertIn("không dùng search_targets", event["session"]["instructions"])
        self.assertIn('scan_mode="snapshot"', event["session"]["instructions"])
        self.assertIn('scan_mode="name_reminder"', event["session"]["instructions"])
        self.assertIn("info_focus", event["session"]["instructions"])
        self.assertIn("remember_person", event["session"]["instructions"])
        self.assertIn("ghi nhớ người này", event["session"]["instructions"])
        self.assertIn("person_info.known_person=true", event["session"]["instructions"])
        self.assertIn("contact_match_confirmed", event["session"]["instructions"])
        self.assertIn("no_match", event["session"]["instructions"])
        self.assertIn("Nội bộ Jetson: kết quả skill sau khi chụp ảnh", event["session"]["instructions"])
        self.assertIn("Không suy diễn thành nội dung", event["session"]["instructions"])
        self.assertIn("OpenVision Rokid V2", event["session"]["instructions"])
        self.assertIn("agent của AI Skill OS", event["session"]["instructions"])
        self.assertIn("bạn có skill gì", event["session"]["instructions"])
        self.assertIn("nhìn/mô tả cảnh", event["session"]["instructions"])
        self.assertIn("đọc chữ/OCR", event["session"]["instructions"])
        self.assertIn("nhận diện người quen từ", event["session"]["instructions"])
        self.assertIn("Không tự giới thiệu như assistant chung", event["session"]["instructions"])

    def test_session_update_can_omit_output_token_cap(self):
        event = session_update_event(
            model="gpt-realtime-1.5",
            voice="marin",
            tools=[],
            turn_policy="manual",
            output_modalities=["text"],
            max_output_tokens=None,
        )

        self.assertNotIn("max_output_tokens", event["session"])

    def test_audio_append_base64_encodes_pcm(self):
        event = append_audio_event(b"\x00\x01")

        self.assertEqual(event["type"], "input_audio_buffer.append")
        self.assertEqual(event["audio"], "AAE=")

    def test_conversation_item_delete_event_targets_item_id(self):
        event = conversation_item_delete_event("item_old")

        self.assertEqual(event["type"], "conversation.item.delete")
        self.assertEqual(event["item_id"], "item_old")
        self.assertIn("event_id", event)

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
