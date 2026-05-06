from collections import deque
import unittest

from app.openai_realtime_skills import (
    RealtimeSkillSendQueue,
    remember_handled_call_id,
    should_surface_realtime_skill_message,
)


class OpenAIRealtimeSkillsTests(unittest.TestCase):
    def test_remember_handled_call_id_is_bounded_and_evicts_oldest(self) -> None:
        handled_ids: set[str] = set()
        handled_order: deque[str] = deque()

        self.assertTrue(remember_handled_call_id(handled_ids, handled_order, "call-1", max_size=3))
        self.assertTrue(remember_handled_call_id(handled_ids, handled_order, "call-2", max_size=3))
        self.assertTrue(remember_handled_call_id(handled_ids, handled_order, "call-3", max_size=3))
        self.assertTrue(remember_handled_call_id(handled_ids, handled_order, "call-4", max_size=3))

        self.assertEqual(list(handled_order), ["call-2", "call-3", "call-4"])
        self.assertEqual(handled_ids, {"call-2", "call-3", "call-4"})
        self.assertFalse(remember_handled_call_id(handled_ids, handled_order, "call-4", max_size=3))

    def test_should_surface_message_rejects_chatter_and_tool_followups(self) -> None:
        self.assertFalse(should_surface_realtime_skill_message("0.19", had_tool_call=False))
        self.assertFalse(should_surface_realtime_skill_message("VMLINUX", had_tool_call=False))
        self.assertFalse(
            should_surface_realtime_skill_message(
                "Please clarify your request.",
                had_tool_call=False,
            )
        )
        self.assertFalse(
            should_surface_realtime_skill_message(
                "Đang tìm người đeo kính.",
                had_tool_call=True,
            )
        )

    def test_should_surface_message_allows_short_vietnamese_status_without_tool(self) -> None:
        self.assertTrue(
            should_surface_realtime_skill_message(
                "Đang nhìn phía trước.",
                had_tool_call=False,
            )
        )

    def test_send_queue_prioritizes_control_events_over_audio(self) -> None:
        queue = RealtimeSkillSendQueue(max_items=4)

        queue.enqueue("audio-1", phase="input_audio_buffer.append", is_audio=True)
        queue.enqueue("audio-2", phase="input_audio_buffer.append", is_audio=True)
        queue.enqueue("control-1", phase="response.create:speech_stopped", is_audio=False)
        queue.enqueue("audio-3", phase="input_audio_buffer.append", is_audio=True)

        self.assertEqual(
            [item.payload for item in queue.pop_many(4)],
            ["control-1", "audio-1", "audio-2", "audio-3"],
        )

    def test_send_queue_drops_stale_audio_before_control(self) -> None:
        queue = RealtimeSkillSendQueue(max_items=8)

        for index in range(1, 9):
            queue.enqueue(f"audio-{index}", phase="input_audio_buffer.append", is_audio=True)
        queued, stats = queue.enqueue(
            "control-1",
            phase="conversation.item.create:function_call_output",
            is_audio=False,
        )

        self.assertTrue(queued)
        self.assertEqual(stats["droppedAudio"], 1)
        self.assertEqual(
            [item.payload for item in queue.pop_many(8)],
            ["control-1", "audio-2", "audio-3", "audio-4", "audio-5", "audio-6", "audio-7", "audio-8"],
        )

    def test_send_queue_preserves_audio_byte_count_for_telemetry(self) -> None:
        queue = RealtimeSkillSendQueue(max_items=4)

        queue.enqueue(
            "audio-1",
            phase="input_audio_buffer.append",
            is_audio=True,
            byte_count=3840,
        )

        [item] = queue.pop_many(1)
        self.assertTrue(item.is_audio)
        self.assertEqual(item.byte_count, 3840)


if __name__ == "__main__":
    unittest.main()
