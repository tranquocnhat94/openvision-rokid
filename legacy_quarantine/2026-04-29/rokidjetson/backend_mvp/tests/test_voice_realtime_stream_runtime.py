import unittest

from app.voice_realtime_stream_runtime import (
    decide_live_caption_commit,
    plan_generation_replay,
    pump_pcm_chunks,
    resolve_buffer_window,
)


class VoiceRealtimeStreamRuntimeTests(unittest.TestCase):
    def test_plan_generation_replay_rewinds_offset_on_new_generation(self) -> None:
        decision = plan_generation_replay(
            current_input_offset=4000,
            current_generation=1,
            ready_generation=2,
            window_start=3200,
            replay_bytes=600,
        )

        self.assertEqual(decision.next_input_offset, 3400)
        self.assertEqual(decision.next_generation, 2)
        self.assertEqual(decision.replay_from, 3400)
        self.assertEqual(decision.replay_to, 4000)

    def test_plan_generation_replay_skips_rewind_when_generation_is_unchanged(self) -> None:
        decision = plan_generation_replay(
            current_input_offset=4000,
            current_generation=2,
            ready_generation=2,
            window_start=3200,
            replay_bytes=600,
        )

        self.assertEqual(decision.next_input_offset, 4000)
        self.assertEqual(decision.next_generation, 2)
        self.assertIsNone(decision.replay_from)

    def test_resolve_buffer_window_reports_overrun_once_per_interval(self) -> None:
        decision = resolve_buffer_window(
            requested_offset=1000,
            window_start=1400,
            window_end=2200,
            now_ms=5000,
            last_overrun_log_ms=3000,
        )

        self.assertTrue(decision.has_audio)
        self.assertEqual(decision.start_offset, 1400)
        self.assertEqual(decision.next_input_offset, 1400)
        self.assertTrue(decision.log_overrun)
        self.assertEqual(decision.next_overrun_log_ms, 5000)
        self.assertEqual(decision.buffered_bytes, 800)

    def test_pump_pcm_chunks_tracks_voice_and_stops_on_failed_append(self) -> None:
        appended: list[bytes] = []

        def append_pcm(chunk: bytes) -> bool:
            appended.append(chunk)
            return len(appended) < 3

        result = pump_pcm_chunks(
            payload_start=100,
            payload=b"abcdefghij",
            chunk_bytes=4,
            append_pcm=append_pcm,
            chunk_has_voice=lambda chunk: chunk == b"efgh",
        )

        self.assertEqual(appended, [b"abcd", b"efgh", b"ij"])
        self.assertEqual(result.next_offset, 108)
        self.assertEqual(result.appended_chunks, 2)
        self.assertTrue(result.saw_voice)
        self.assertEqual(result.voiced_bytes, 4)

    def test_decide_live_caption_commit_uses_tail_commit_after_silence(self) -> None:
        decision = decide_live_caption_commit(
            active=True,
            now_ms=5000,
            last_voice_ms=4500,
            input_offset=6400,
            commit_offset=5600,
            rolling_commit_bytes=1200,
            min_commit_bytes=600,
            silence_commit_ms=180,
        )

        self.assertTrue(decision.should_commit)
        self.assertEqual(decision.reason, "tail")
        self.assertEqual(decision.next_state_label, "transcribing")
        self.assertTrue(decision.deactivate_after_commit)

    def test_decide_live_caption_commit_uses_rolling_commit_while_active(self) -> None:
        decision = decide_live_caption_commit(
            active=True,
            now_ms=5000,
            last_voice_ms=4920,
            input_offset=7200,
            commit_offset=6000,
            rolling_commit_bytes=1200,
            min_commit_bytes=600,
            silence_commit_ms=180,
        )

        self.assertTrue(decision.should_commit)
        self.assertEqual(decision.reason, "rolling")
        self.assertEqual(decision.next_state_label, "captioning")
        self.assertFalse(decision.deactivate_after_commit)


if __name__ == "__main__":
    unittest.main()
