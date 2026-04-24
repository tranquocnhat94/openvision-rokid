import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.media_gateway import MediaGateway


class MediaGatewayTest(unittest.TestCase):
    def test_audio_metrics_accumulate_strong_ratio(self):
        gateway = MediaGateway(events=InMemoryEventStore())

        status = gateway.record_audio_metrics(
            session_id="sess_test",
            transport="pcm_tcp",
            sample_rate=24000,
            channels=1,
            chunk_count=10,
            strong_chunk_count=7,
            rms=0.12,
            source="mic",
        )

        self.assertEqual(status["audio"]["state"], "receiving")
        self.assertEqual(status["audio"]["strong_chunk_ratio"], 0.7)

    def test_video_heartbeat_records_transport(self):
        gateway = MediaGateway(events=InMemoryEventStore())

        status = gateway.record_video_heartbeat(
            session_id="sess_test",
            transport="h264_tcp",
            codec="h264",
            width=1280,
            height=720,
            fps=30,
        )

        self.assertEqual(status["video"]["transport"], "h264_tcp")
        self.assertEqual(status["video"]["codec"], "h264")

    def test_rv101_samples_update_media_counters(self):
        gateway = MediaGateway(events=InMemoryEventStore())

        video = gateway.record_video_sample(
            session_id="sess_test",
            transport="rv101_tcp",
            codec="video/avc",
            payload_bytes=4096,
            is_keyframe=True,
            width=1280,
            height=720,
        )
        audio = gateway.record_audio_sample(
            session_id="sess_test",
            transport="rv101_tcp",
            sample_rate=24000,
            channels=1,
            payload_bytes=960,
            strong=True,
            rms=180.0,
            source="VOICE_RECOGNITION",
        )

        self.assertEqual(video["video"]["frame_count"], 1)
        self.assertEqual(video["video"]["keyframe_count"], 1)
        self.assertEqual(audio["audio"]["chunk_count"], 1)
        self.assertEqual(audio["audio"]["strong_chunk_ratio"], 1.0)
