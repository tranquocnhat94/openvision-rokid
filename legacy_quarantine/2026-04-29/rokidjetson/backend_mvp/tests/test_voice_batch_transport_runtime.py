import io
import tempfile
import unittest
import wave
from pathlib import Path

from app.voice_batch_transport_runtime import (
    deep_get_path,
    extract_local_response_text,
    extract_openai_route_choice,
    parse_json_object_fragment,
    pcm_to_wav_bytes,
    run_local_command_transcription,
)


class VoiceBatchTransportRuntimeTests(unittest.TestCase):
    def test_deep_get_path_reads_nested_dict_values(self) -> None:
        payload = {"result": {"text": "xin chao"}}

        self.assertEqual(deep_get_path(payload, "result.text"), "xin chao")
        self.assertIsNone(deep_get_path(payload, "result.missing"))

    def test_extract_local_response_text_supports_json_and_plain_text(self) -> None:
        json_text = extract_local_response_text(
            b'{"result":{"text":"xin chao"}}',
            "application/json",
            "result.text",
        )
        plain_text = extract_local_response_text(
            " xin chao \n".encode("utf-8"),
            "text/plain",
            "text",
        )

        self.assertEqual(json_text, "xin chao")
        self.assertEqual(plain_text, "xin chao")

    def test_parse_json_object_fragment_reads_embedded_json(self) -> None:
        parsed = parse_json_object_fragment("router output: {\"intent\":\"scene_query\"}")

        self.assertEqual(parsed["intent"], "scene_query")

    def test_extract_openai_route_choice_parses_first_message_json(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "```json\n{\"intent\":\"target_search\",\"confidence\":0.9}\n```"
                    }
                }
            ]
        }

        route = extract_openai_route_choice(payload)

        self.assertIsNotNone(route)
        self.assertEqual(route["intent"], "target_search")
        self.assertEqual(route["confidence"], 0.9)

    def test_pcm_to_wav_bytes_writes_16khz_mono_wave(self) -> None:
        wav_bytes = pcm_to_wav_bytes(b"\x01\x00\x02\x00\x03\x00\x04\x00")

        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getframerate(), 16000)
            self.assertEqual(wav_file.readframes(4), b"\x01\x00\x02\x00\x03\x00\x04\x00")

    def test_run_local_command_transcription_extracts_json_text_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript = run_local_command_transcription(
                config={
                    "localCommandTemplate": "printf '{\"text\":\"xin chao\"}'",
                    "localResponseTextPath": "text",
                },
                session_id="session-1",
                wav_bytes=b"\x00\x00",
                segment_dir=Path(tmpdir),
                now_ms=lambda: 1234,
            )

        self.assertEqual(transcript, "xin chao")


if __name__ == "__main__":
    unittest.main()
