import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.audio_signal import AudioForwardGate, is_voice_like, pcm16_metrics


class AudioSignalTest(unittest.TestCase):
    def test_pcm16_metrics_detects_silence_and_voice(self):
        silence = (0).to_bytes(2, "little", signed=True) * 20
        voice = (300).to_bytes(2, "little", signed=True) * 20

        self.assertFalse(is_voice_like(pcm16_metrics(silence)))
        self.assertTrue(is_voice_like(pcm16_metrics(voice)))

    def test_forward_gate_buffers_prefix_then_opens_on_sustained_voice(self):
        gate = AudioForwardGate(prefix_chunks=3, start_strong_chunks=2, hangover_chunks=2)
        silence = (0).to_bytes(2, "little", signed=True) * 20
        voice = (300).to_bytes(2, "little", signed=True) * 20

        self.assertEqual(gate.accept(silence, pcm16_metrics(silence)).chunks, [])
        self.assertEqual(gate.accept(silence, pcm16_metrics(silence)).chunks, [])
        first_voice = gate.accept(voice, pcm16_metrics(voice))
        self.assertEqual(first_voice.chunks, [])
        opened = gate.accept(voice, pcm16_metrics(voice))

        self.assertEqual(opened.transition, "opened")
        self.assertEqual(len(opened.chunks), 3)
        self.assertEqual(opened.chunks[-1], voice)

    def test_forward_gate_keeps_short_trailing_silence_then_closes(self):
        gate = AudioForwardGate(prefix_chunks=1, start_strong_chunks=1, hangover_chunks=2)
        silence = (0).to_bytes(2, "little", signed=True) * 20
        voice = (300).to_bytes(2, "little", signed=True) * 20

        opened = gate.accept(voice, pcm16_metrics(voice))
        self.assertEqual(opened.transition, "opened")
        self.assertEqual(gate.accept(silence, pcm16_metrics(silence)).state, "open")
        closed = gate.accept(silence, pcm16_metrics(silence))

        self.assertEqual(closed.transition, "closed")
        self.assertEqual(closed.state, "idle")


if __name__ == "__main__":
    unittest.main()
