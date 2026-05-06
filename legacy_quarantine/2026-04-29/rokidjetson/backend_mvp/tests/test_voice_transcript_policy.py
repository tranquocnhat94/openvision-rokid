import unittest

from app.voice_transcript_policy import evaluate_transcript_candidate


class VoiceTranscriptPolicyTests(unittest.TestCase):
    def test_evaluate_transcript_candidate_accepts_clean_text(self) -> None:
        decision = evaluate_transcript_candidate(
            "  xin chao  ",
            cleaner=lambda value: value.strip(),
            is_spurious=lambda value: False,
            is_language_script_mismatch=lambda value: False,
        )

        self.assertEqual(decision.cleaned_text, "xin chao")
        self.assertEqual(decision.accepted_text, "xin chao")
        self.assertIsNone(decision.discard_reason)

    def test_evaluate_transcript_candidate_rejects_spurious_before_language_checks(self) -> None:
        decision = evaluate_transcript_candidate(
            "hello",
            cleaner=lambda value: value.strip(),
            is_spurious=lambda value: value == "hello",
            is_language_script_mismatch=lambda value: True,
        )

        self.assertEqual(decision.cleaned_text, "hello")
        self.assertEqual(decision.accepted_text, "")
        self.assertEqual(decision.discard_reason, "spurious")

    def test_evaluate_transcript_candidate_rejects_language_script_mismatch(self) -> None:
        decision = evaluate_transcript_candidate(
            "annyeong",
            cleaner=lambda value: value.strip(),
            is_spurious=lambda value: False,
            is_language_script_mismatch=lambda value: True,
        )

        self.assertEqual(decision.cleaned_text, "annyeong")
        self.assertEqual(decision.accepted_text, "")
        self.assertEqual(decision.discard_reason, "language_script_mismatch")

    def test_evaluate_transcript_candidate_handles_empty_clean_result(self) -> None:
        decision = evaluate_transcript_candidate(
            "   ",
            cleaner=lambda value: "",
            is_spurious=lambda value: False,
            is_language_script_mismatch=lambda value: False,
        )

        self.assertEqual(decision.cleaned_text, "")
        self.assertEqual(decision.accepted_text, "")
        self.assertIsNone(decision.discard_reason)


if __name__ == "__main__":
    unittest.main()
