import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

import av
from av.audio.resampler import AudioResampler

from openvision_jetson.audio_signal import pcm16_metrics
from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.simulator_bridge import (
    SimulatorBridge,
    SimulatorPeerStatus,
    audio_frame_to_pcm24_mono,
)


class SimulatorBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def test_close_unknown_peer_is_safe(self):
        bridge = SimulatorBridge(events=InMemoryEventStore())

        result = await bridge.close("sess_missing")

        self.assertEqual(result["session_id"], "sess_missing")
        self.assertFalse(result["closed"])

    async def test_invalid_offer_type_is_rejected(self):
        bridge = SimulatorBridge(events=InMemoryEventStore())

        with self.assertRaises(ValueError):
            await bridge.handle_offer(session_id="sess_test", sdp="bad", offer_type="answer")

    async def test_close_notifies_lifecycle_once_for_known_session(self):
        closed = []
        bridge = SimulatorBridge(events=InMemoryEventStore(), on_close=closed.append)
        bridge._statuses["sess_test"] = SimulatorPeerStatus(session_id="sess_test")

        await bridge.close("sess_test")
        await bridge.close("sess_test")

        self.assertEqual(closed, ["sess_test"])

    async def test_audio_frame_resamples_to_exact_pcm24_mono(self):
        frame = av.AudioFrame(format="s16", layout="mono", samples=480)
        frame.sample_rate = 48000
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        chunks = audio_frame_to_pcm24_mono(
            frame,
            AudioResampler(format="s16", layout="mono", rate=24000),
        )

        self.assertTrue(chunks)
        self.assertEqual(len(chunks[0]) % 2, 0)
        self.assertLess(len(chunks[0]), len(bytes(frame.planes[0])))

    async def test_pcm16_metrics_detects_strong_audio(self):
        pcm = (200).to_bytes(2, "little", signed=True) * 10

        metrics = pcm16_metrics(pcm)

        self.assertEqual(metrics["sample_count"], 10)
        self.assertEqual(metrics["peak_abs"], 200)
        self.assertEqual(metrics["non_silent_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
