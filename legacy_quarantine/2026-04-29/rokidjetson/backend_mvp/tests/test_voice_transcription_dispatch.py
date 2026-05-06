import unittest

from app.voice_transcription_dispatch import (
    build_partial_transcription_plan,
    build_segment_transcription_plan,
)


class VoiceTranscriptionDispatchTests(unittest.TestCase):
    def test_segment_plan_for_hybrid_backend_preserves_local_first_fallback_order(self) -> None:
        plan = build_segment_transcription_plan(
            {
                "asrBackend": "hybrid_local_openai",
                "allowOpenAITranscriptionFallback": True,
            }
        )

        self.assertEqual(
            [(attempt.backend, attempt.result_source, attempt.partial_mode) for attempt in plan.attempts],
            [
                ("local_http", "local_http", False),
                ("local_command", "local_command", False),
                ("openai", "openai", False),
            ],
        )
        self.assertEqual(plan.terminal_source, "hybrid_local_openai")
        self.assertIsNone(plan.skip_reason)

    def test_segment_plan_for_hybrid_backend_can_disable_openai_fallback(self) -> None:
        plan = build_segment_transcription_plan(
            {
                "asrBackend": "hybrid_local_openai",
                "allowOpenAITranscriptionFallback": False,
            }
        )

        self.assertEqual(
            [attempt.backend for attempt in plan.attempts],
            ["local_http", "local_command"],
        )
        self.assertEqual(plan.terminal_source, "hybrid_local_openai")

    def test_segment_plan_reports_disabled_and_unknown_backends_explicitly(self) -> None:
        disabled = build_segment_transcription_plan({"asrBackend": "disabled"})
        unknown = build_segment_transcription_plan({"asrBackend": "openai_realtime_skills"})

        self.assertEqual(disabled.skip_reason, "backend_disabled")
        self.assertEqual(disabled.terminal_source, "disabled")
        self.assertEqual(unknown.skip_reason, "unknown_backend")
        self.assertEqual(unknown.skip_backend, "openai_realtime_skills")
        self.assertEqual(unknown.terminal_source, "openai_realtime_skills")

    def test_empty_segment_plan_defaults_to_realtime_skills_not_hybrid(self) -> None:
        plan = build_segment_transcription_plan({})

        self.assertEqual(plan.attempts, ())
        self.assertEqual(plan.terminal_source, "openai_realtime_skills")
        self.assertEqual(plan.skip_reason, "unknown_backend")

    def test_partial_plan_only_uses_local_backends(self) -> None:
        local_http = build_partial_transcription_plan({"asrBackend": "local_http"})
        hybrid = build_partial_transcription_plan({"asrBackend": "hybrid_local_openai"})
        realtime = build_partial_transcription_plan({"asrBackend": "openai_realtime_skills"})

        self.assertEqual(
            [(attempt.backend, attempt.result_source, attempt.partial_mode) for attempt in local_http.attempts],
            [("local_http", "local_http_partial", True)],
        )
        self.assertEqual(
            [(attempt.backend, attempt.result_source, attempt.partial_mode) for attempt in hybrid.attempts],
            [
                ("local_http", "local_http_partial", True),
                ("local_command", "local_command_partial", False),
            ],
        )
        self.assertEqual(realtime.attempts, ())
        self.assertEqual(realtime.terminal_source, "openai_realtime_skills")

    def test_empty_partial_plan_defaults_to_realtime_skills_not_local_http(self) -> None:
        plan = build_partial_transcription_plan({})

        self.assertEqual(plan.attempts, ())
        self.assertEqual(plan.terminal_source, "openai_realtime_skills")


if __name__ == "__main__":
    unittest.main()
