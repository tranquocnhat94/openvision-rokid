import unittest

from app.voice_caption_text_runtime import (
    build_live_caption_prompt_markers,
    merge_incremental_transcript,
    merge_local_partial_text,
    sanitize_live_caption_transcript,
    should_emit_local_partial_text,
    strip_live_caption_prompt_echo,
    trim_live_caption_hint,
)


class VoiceCaptionTextRuntimeTests(unittest.TestCase):
    def test_merge_incremental_transcript_joins_overlap(self) -> None:
        merged = merge_incremental_transcript(
            "xin chao moi nguoi",
            "moi nguoi dang o day",
            cleaner=lambda value: " ".join(value.strip().split()),
            normalizer=lambda value: " ".join(value.strip().lower().split()),
        )

        self.assertEqual(merged, "xin chao moi nguoi dang o day")

    def test_merge_local_partial_text_prefers_longer_progressive_caption(self) -> None:
        merged = merge_local_partial_text(
            "tim nguoi",
            "tim nguoi ao do",
            cleaner=lambda value: " ".join(value.strip().split()),
            normalizer=lambda value: " ".join(value.strip().lower().split()),
        )

        self.assertEqual(merged, "tim nguoi ao do")

    def test_strip_live_caption_prompt_echo_keeps_prefix_before_marker(self) -> None:
        stripped = strip_live_caption_prompt_echo(
            "xin chao transcribe ongoing spoken vietnamese only",
            cleaner=lambda value: " ".join(value.strip().split()),
            prompt_markers=build_live_caption_prompt_markers(["Transcribe ongoing spoken Vietnamese only."]),
        )

        self.assertEqual(stripped, "xin chao")

    def test_sanitize_live_caption_transcript_rejects_short_prompt_echo(self) -> None:
        sanitized = sanitize_live_caption_transcript(
            "live stream stable",
            cleaner=lambda value: " ".join(value.strip().split()),
            normalizer=lambda value: " ".join(value.strip().lower().split()),
            has_vietnamese_markers=lambda value: False,
            prompt_markers=build_live_caption_prompt_markers(["Return only the spoken Vietnamese transcript."]),
        )

        self.assertEqual(sanitized, "")

    def test_should_emit_local_partial_text_follows_command_hints(self) -> None:
        self.assertTrue(
            should_emit_local_partial_text(
                "tim nguoi ao do",
                normalizer=lambda value: " ".join(value.strip().lower().split()),
                command_hints=("tim", "xe"),
            )
        )
        self.assertFalse(
            should_emit_local_partial_text(
                "xin chao moi nguoi",
                normalizer=lambda value: " ".join(value.strip().lower().split()),
                command_hints=("tim", "xe"),
            )
        )

    def test_trim_live_caption_hint_keeps_tail_when_too_long(self) -> None:
        hinted = trim_live_caption_hint(
            "mot hai ba bon nam sau bay tam chin muoi",
            cleaner=lambda value: " ".join(value.strip().split()),
            max_chars=12,
        )

        self.assertTrue(hinted.startswith("…"))
        self.assertEqual(len(hinted), 12)


if __name__ == "__main__":
    unittest.main()
