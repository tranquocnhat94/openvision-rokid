import unittest

from app.voice_route_runtime import resolve_final_route


class VoiceRouteRuntimeTests(unittest.TestCase):
    def test_resolve_final_route_skips_recent_duplicate(self) -> None:
        resolution = resolve_final_route(
            transcript="tim nguoi ao do",
            source="openai",
            now_ms=5000,
            last_transcript="tim nguoi ao do",
            last_transcript_ms=1000,
            pending_text="",
            pending_ms=0,
            build_action=lambda transcript, source: {"intent": "target_search", "targetQuery": transcript},
            merge_transcript=lambda previous, current: f"{previous} {current}".strip(),
            is_action_more_specific=lambda candidate, baseline: False,
            is_incomplete_command_prefix=lambda transcript, action: False,
        )

        self.assertTrue(resolution.duplicate)

    def test_resolve_final_route_uses_more_specific_merged_action(self) -> None:
        resolution = resolve_final_route(
            transcript="ao do",
            source="openai",
            now_ms=5000,
            last_transcript="",
            last_transcript_ms=0,
            pending_text="tim nguoi",
            pending_ms=3000,
            build_action=lambda transcript, source: {
                "intent": "target_search",
                "targetQuery": transcript,
                "specificity": 2 if transcript == "tim nguoi ao do" else 1,
            },
            merge_transcript=lambda previous, current: f"{previous} {current}".strip(),
            is_action_more_specific=lambda candidate, baseline: candidate.get("specificity", 0) > baseline.get("specificity", 0),
            is_incomplete_command_prefix=lambda transcript, action: False,
        )

        self.assertFalse(resolution.duplicate)
        self.assertEqual(resolution.effective_transcript, "tim nguoi ao do")
        self.assertEqual(resolution.effective_action["specificity"], 2)

    def test_resolve_final_route_holds_incomplete_followup(self) -> None:
        resolution = resolve_final_route(
            transcript="ao do",
            source="openai",
            now_ms=5000,
            last_transcript="",
            last_transcript_ms=0,
            pending_text="tim nguoi",
            pending_ms=3000,
            build_action=lambda transcript, source: {"intent": "target_search", "targetQuery": transcript},
            merge_transcript=lambda previous, current: f"{previous} {current}".strip(),
            is_action_more_specific=lambda candidate, baseline: False,
            is_incomplete_command_prefix=lambda transcript, action: transcript == "tim nguoi ao do",
        )

        self.assertEqual(resolution.hold_transcript, "tim nguoi ao do")
        self.assertEqual(resolution.hold_reason, "await_followup")

    def test_resolve_final_route_clears_stale_pending_after_timeout(self) -> None:
        resolution = resolve_final_route(
            transcript="bat canh bao",
            source="openai",
            now_ms=9000,
            last_transcript="",
            last_transcript_ms=0,
            pending_text="tim nguoi",
            pending_ms=1000,
            build_action=lambda transcript, source: {"intent": "alert_burst"},
            merge_transcript=lambda previous, current: f"{previous} {current}".strip(),
            is_action_more_specific=lambda candidate, baseline: False,
            is_incomplete_command_prefix=lambda transcript, action: False,
        )

        self.assertTrue(resolution.clear_pending)
        self.assertEqual(resolution.effective_transcript, "bat canh bao")


if __name__ == "__main__":
    unittest.main()
