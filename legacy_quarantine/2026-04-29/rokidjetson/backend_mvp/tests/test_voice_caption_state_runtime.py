import unittest

from app.voice_caption_state_runtime import (
    next_live_final_text,
    next_live_partial_text,
    next_local_partial_text,
    next_route_partial_text,
)


class VoiceCaptionStateRuntimeTests(unittest.TestCase):
    def test_next_local_partial_text_skips_unchanged_result(self) -> None:
        result = next_local_partial_text(
            "tim nguoi",
            "tim nguoi",
            merge_local_partial_text=lambda previous, current: current,
        )

        self.assertIsNone(result)

    def test_next_route_partial_text_skips_duplicate_partial(self) -> None:
        self.assertIsNone(next_route_partial_text("xin chao", "xin chao"))
        self.assertEqual(next_route_partial_text("xin chao", "xin chao moi nguoi"), "xin chao moi nguoi")

    def test_next_live_partial_text_skips_duplicate_merged_caption(self) -> None:
        result = next_live_partial_text(
            "xin chao",
            "xin chao moi nguoi",
            "moi nguoi",
            merge_incremental_transcript=lambda committed, cleaned: "xin chao moi nguoi",
        )

        self.assertIsNone(result)

    def test_next_live_final_text_requires_new_committed_content(self) -> None:
        self.assertIsNone(
            next_live_final_text(
                "xin chao moi nguoi",
                "xin chao moi nguoi",
                "moi nguoi",
                merge_incremental_transcript=lambda committed, cleaned: "xin chao moi nguoi",
            )
        )
        self.assertEqual(
            next_live_final_text(
                "xin chao",
                "xin chao moi nguoi",
                "moi nguoi dang o day",
                merge_incremental_transcript=lambda committed, cleaned: "xin chao moi nguoi dang o day",
            ),
            "xin chao moi nguoi dang o day",
        )


if __name__ == "__main__":
    unittest.main()
