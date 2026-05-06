import unittest

from app.voice_session_state import VoiceSessionState


class VoiceSessionStateTests(unittest.TestCase):
    def test_snapshot_preserves_legacy_flat_contract(self) -> None:
        state = VoiceSessionState(session_id="session-1")
        state.audio.last_seen_ms = 1200
        state.audio.last_energy_ms = 1400
        state.segment.last_processed_offset = 3200
        state.segment.transcribe_inflight = True
        state.segment.inflight_start_offset = 3000
        state.segment.inflight_end_offset = 3600
        state.route.pending_transcript = "tim nguoi"
        state.route.pending_ms = 2000
        state.route.record_action(
            now_ms=2500,
            transcript="tim nguoi ao do",
            answer="Dang tim",
            intent="target_search",
            mode="search",
            target_query="ao do",
        )
        state.realtime.input_offset = 4096
        state.realtime.generation = 3
        state.caption.input_offset = 5120
        state.caption.commit_offset = 4800
        state.caption.generation = 4
        state.caption.last_voice_ms = 2600
        state.caption.last_commit_ms = 2550
        state.caption.committed_text = "xin chao"
        state.caption.partial_text = "xin"
        state.caption.last_text = "xin chao"
        state.caption.last_emit_ms = 2580
        state.caption.active = True
        state.partial.last_transcript = "xin chao"
        state.partial.last_ms = 2580
        state.partial.local_inflight = True
        state.partial.local_last_probe_ms = 2400
        state.partial.local_last_text = "xin chao"
        state.partial.local_last_emit_ms = 2580

        snapshot = state.snapshot()

        self.assertEqual(snapshot["session_id"], "session-1")
        self.assertEqual(snapshot["last_processed_offset"], 3200)
        self.assertTrue(snapshot["transcribe_inflight"])
        self.assertEqual(snapshot["last_transcript"], "tim nguoi ao do")
        self.assertEqual(snapshot["last_intent"], "target_search")
        self.assertEqual(snapshot["realtime_input_offset"], 4096)
        self.assertEqual(snapshot["live_caption_last_text"], "xin chao")
        self.assertEqual(snapshot["last_partial_transcript"], "xin chao")
        self.assertTrue(snapshot["local_partial_inflight"])
        self.assertEqual(snapshot["pending_route_transcript"], "")

    def test_reset_caption_feedback_clears_partial_and_caption_text_only(self) -> None:
        state = VoiceSessionState(session_id="session-1")
        state.partial.last_transcript = "xin chao"
        state.partial.last_ms = 1000
        state.partial.local_last_text = "xin chao"
        state.partial.local_last_emit_ms = 1100
        state.partial.local_inflight = True
        state.caption.committed_text = "xin chao"
        state.caption.partial_text = "xin"
        state.caption.last_text = "xin chao"
        state.caption.last_emit_ms = 1100
        state.caption.active = True
        state.caption.last_voice_ms = 900
        state.route.last_transcript = "bat den"

        state.reset_caption_feedback()

        self.assertEqual(state.partial.last_transcript, "")
        self.assertEqual(state.partial.last_ms, 0)
        self.assertEqual(state.partial.local_last_text, "")
        self.assertEqual(state.partial.local_last_emit_ms, 0)
        self.assertTrue(state.partial.local_inflight)
        self.assertEqual(state.caption.committed_text, "")
        self.assertEqual(state.caption.partial_text, "")
        self.assertEqual(state.caption.last_text, "")
        self.assertEqual(state.caption.last_emit_ms, 0)
        self.assertFalse(state.caption.active)
        self.assertEqual(state.caption.last_voice_ms, 900)
        self.assertEqual(state.route.last_transcript, "bat den")

    def test_record_action_updates_route_and_clears_pending(self) -> None:
        state = VoiceSessionState(session_id="session-1")
        state.route.pending_transcript = "tim nguoi"
        state.route.pending_ms = 1000

        state.route.record_action(
            now_ms=2000,
            transcript="tim nguoi ao do",
            answer="Dang tim",
            intent="target_search",
            mode="search",
            target_query="ao do",
        )

        self.assertEqual(state.route.pending_transcript, "")
        self.assertEqual(state.route.pending_ms, 0)
        self.assertEqual(state.route.last_transcript_ms, 2000)
        self.assertEqual(state.route.last_transcript, "tim nguoi ao do")
        self.assertEqual(state.route.last_answer, "Dang tim")
        self.assertEqual(state.route.last_intent, "target_search")
        self.assertEqual(state.route.last_mode, "search")
        self.assertEqual(state.route.last_target_query, "ao do")


if __name__ == "__main__":
    unittest.main()
