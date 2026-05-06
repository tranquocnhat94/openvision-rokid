import unittest

from app.voice_realtime_transcription_client import (
    RealtimeTranscriptionSendQueue,
    build_realtime_session_update_event,
    build_realtime_ws_url,
)


class VoiceRealtimeTranscriptionClientTests(unittest.TestCase):
    def test_build_realtime_ws_url_uses_explicit_override(self) -> None:
        url = build_realtime_ws_url({"openaiRealtimeWsUrl": "wss://example.com/custom"})

        self.assertEqual(url, "wss://example.com/custom")

    def test_build_realtime_ws_url_converts_base_api_url(self) -> None:
        url = build_realtime_ws_url({"openaiBaseUrl": "https://api.openai.com/v1"})

        self.assertEqual(url, "wss://api.openai.com/v1/realtime?intent=transcription")

    def test_build_realtime_session_update_event_sets_server_vad_and_logprobs(self) -> None:
        event = build_realtime_session_update_event(
            config={
                "transcriptionModel": "gpt-realtime-mini",
                "languageHint": "vi",
                "openaiTranscriptionPrompt": "chi tra transcript",
                "realtimeVadThreshold": 0.42,
                "realtimeVadPrefixPaddingMs": 280,
                "realtimeVadSilenceDurationMs": 440,
                "realtimeNoiseReduction": "near_field",
                "realtimeIncludeLogprobs": True,
            },
            turn_detection_mode="server_vad",
            model_config_key="transcriptionModel",
            prompt_config_key="openaiTranscriptionPrompt",
        )

        session = event["session"]
        self.assertEqual(event["type"], "session.update")
        self.assertEqual(session["audio"]["input"]["transcription"]["model"], "gpt-realtime-mini")
        self.assertEqual(session["audio"]["input"]["transcription"]["prompt"], "chi tra transcript")
        self.assertEqual(session["audio"]["input"]["turn_detection"]["threshold"], 0.42)
        self.assertEqual(session["audio"]["input"]["noise_reduction"]["type"], "near_field")
        self.assertEqual(session["include"], ["item.input_audio_transcription.logprobs"])

    def test_build_realtime_session_update_event_disables_turn_detection_for_manual_mode(self) -> None:
        event = build_realtime_session_update_event(
            config={
                "liveCaptionModel": "gpt-caption",
                "openaiLiveCaptionPrompt": "caption live",
            },
            turn_detection_mode="manual",
            model_config_key="liveCaptionModel",
            prompt_config_key="openaiLiveCaptionPrompt",
        )

        session = event["session"]
        self.assertEqual(session["audio"]["input"]["transcription"]["model"], "gpt-caption")
        self.assertEqual(session["audio"]["input"]["transcription"]["prompt"], "caption live")
        self.assertIsNone(session["audio"]["input"]["turn_detection"])

    def test_transcription_send_queue_preserves_audio_then_commit_order(self) -> None:
        queue = RealtimeTranscriptionSendQueue(max_items=4)

        queue.enqueue("audio-1", phase="input_audio_buffer.append", is_audio=True, byte_count=10)
        queue.enqueue("commit", phase="input_audio_buffer.commit", is_audio=False)
        queue.enqueue("audio-2", phase="input_audio_buffer.append", is_audio=True, byte_count=10)

        events = queue.pop_many(10)

        self.assertEqual([event.payload for event in events], ["audio-1", "commit", "audio-2"])

    def test_transcription_send_queue_rejects_audio_when_control_boundary_is_queued(self) -> None:
        queue = RealtimeTranscriptionSendQueue(max_items=8)

        for index in range(7):
            queue.enqueue(
                f"audio-{index}",
                phase="input_audio_buffer.append",
                is_audio=True,
                byte_count=10,
            )
        queue.enqueue("commit", phase="input_audio_buffer.commit", is_audio=False)
        accepted, stats = queue.enqueue(
            "audio-extra",
            phase="input_audio_buffer.append",
            is_audio=True,
            byte_count=10,
        )

        events = queue.pop_many(10)

        self.assertFalse(accepted)
        self.assertEqual(stats["droppedAudio"], 1)
        self.assertEqual(
            [event.payload for event in events],
            [f"audio-{index}" for index in range(7)] + ["commit"],
        )


if __name__ == "__main__":
    unittest.main()
