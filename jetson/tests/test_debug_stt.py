import sys
import unittest
import wave
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.debug_stt import DebugSttRuntime, DebugSttSettings, pcm16_to_wav_16k_mono
from openvision_jetson.event_store import InMemoryEventStore


class DebugSttTest(unittest.IsolatedAsyncioTestCase):
    def test_pcm_is_packaged_as_16k_mono_wav(self):
        pcm_24k = (300).to_bytes(2, "little", signed=True) * 24_000

        wav_bytes = pcm16_to_wav_16k_mono(pcm_24k, sample_rate=24_000, channels=1)

        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 16_000)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertGreater(wav_file.getnframes(), 15_000)

    async def test_closed_turn_posts_to_worker_and_stores_transcript(self):
        async def fake_post(settings, wav_bytes, session_id):
            self.assertEqual(settings.language, "vi")
            self.assertEqual(session_id, "sess_test")
            self.assertGreater(len(wav_bytes), 44)
            return {"text": "đếm người đi", "backend": "phowhisper_http", "transcribeMs": 123, "language": "vi"}

        runtime = DebugSttRuntime(
            events=InMemoryEventStore(),
            settings_provider=lambda: DebugSttSettings(enabled=True, min_audio_ms=0),
            http_post=fake_post,
        )
        voice = (300).to_bytes(2, "little", signed=True) * 24_000
        silence = (0).to_bytes(2, "little", signed=True) * 2_400

        runtime.accept_gate_decision(
            session_id="sess_test",
            chunks=[voice],
            transition="opened",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        runtime.accept_gate_decision(
            session_id="sess_test",
            chunks=[silence],
            transition="closed",
            sample_rate=24_000,
            channels=1,
            source="unit",
        )
        await runtime.wait_for_idle()

        rows = runtime.transcripts(session_id="sess_test")
        self.assertEqual(rows[0]["text"], "đếm người đi")
        self.assertEqual(rows[0]["backend"], "phowhisper_http")


if __name__ == "__main__":
    unittest.main()
