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
            avg_abs=180.0,
            peak_abs=420,
            non_silent_ratio=0.06,
            source="mic",
        )

        self.assertEqual(status["audio"]["state"], "receiving")
        self.assertEqual(status["audio"]["strong_chunk_ratio"], 0.7)
        self.assertEqual(status["audio"]["avg_abs"], 180.0)
        self.assertEqual(status["audio"]["peak_abs"], 420)
        self.assertEqual(status["audio"]["non_silent_ratio"], 0.06)
        self.assertEqual(status["audio"]["max_avg_abs"], 180.0)
        self.assertEqual(status["audio"]["max_peak_abs"], 420)

    def test_video_heartbeat_records_transport(self):
        gateway = MediaGateway(events=InMemoryEventStore())

        status = gateway.record_video_heartbeat(
            session_id="sess_test",
            transport="h264_tcp",
            codec="h264",
            width=1280,
            height=720,
            fps=30,
            metadata={"orientation": "landscape", "profile": "rv101_live"},
        )

        self.assertEqual(status["video"]["transport"], "h264_tcp")
        self.assertEqual(status["video"]["codec"], "h264")
        self.assertEqual(status["video"]["width"], 1280)
        self.assertEqual(status["video"]["height"], 720)
        self.assertEqual(status["video"]["fps"], 30)
        self.assertEqual(status["video"]["metadata"]["orientation"], "landscape")
        self.assertEqual(status["video"]["metadata"]["profile"], "rv101_live")
        self.assertEqual(status["video"]["frame_count"], 0)
        self.assertIsNone(status["video"]["last_frame_age_ms"])

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
            avg_abs=180.0,
            peak_abs=420,
            non_silent_ratio=0.06,
            source="VOICE_RECOGNITION",
        )

        self.assertEqual(video["video"]["frame_count"], 1)
        self.assertEqual(video["video"]["keyframe_count"], 1)
        self.assertEqual(video["video"]["last_frame_age_ms"], 0)
        self.assertEqual(video["video"]["last_frame_at"], video["video"]["updated_at"])
        self.assertEqual(audio["audio"]["chunk_count"], 1)
        self.assertEqual(audio["audio"]["strong_chunk_ratio"], 1.0)
        self.assertEqual(audio["audio"]["avg_abs"], 180.0)
        self.assertEqual(audio["audio"]["peak_abs"], 420)
        self.assertEqual(audio["audio"]["non_silent_ratio"], 0.06)

    def test_audio_gate_decisions_update_counters(self):
        gateway = MediaGateway(events=InMemoryEventStore())

        opened = gateway.record_audio_gate_decision(
            session_id="sess_test",
            source="iphone_webrtc",
            state="open",
            transition="opened",
            strong=True,
            forwarded_chunks=3,
            buffered_chunks=0,
            avg_abs=220.0,
            peak_abs=600,
            non_silent_ratio=0.08,
        )
        closed = gateway.record_audio_gate_decision(
            session_id="sess_test",
            source="iphone_webrtc",
            state="idle",
            transition="closed",
            strong=False,
            forwarded_chunks=1,
            buffered_chunks=0,
            avg_abs=20.0,
            peak_abs=40,
            non_silent_ratio=0.0,
        )

        self.assertEqual(opened["audio"]["gate_open_count"], 1)
        self.assertEqual(closed["audio"]["gate_close_count"], 1)
        self.assertEqual(closed["audio"]["gate_forwarded_chunk_count"], 4)
        self.assertEqual(closed["audio"]["last_gate_transition"], "closed")
        self.assertEqual(closed["audio"]["max_avg_abs"], 220.0)
        self.assertEqual(closed["audio"]["max_peak_abs"], 600)

    def test_video_samples_estimate_fps_and_last_frame_age(self):
        now = 100.0

        def clock():
            return now

        gateway = MediaGateway(events=InMemoryEventStore(), clock=clock)

        first = gateway.record_video_sample(
            session_id="sess_test",
            transport="webrtc",
            codec="raw_video",
            payload_bytes=1024,
            width=640,
            height=480,
        )
        now = 100.5
        second = gateway.record_video_sample(
            session_id="sess_test",
            transport="webrtc",
            codec="raw_video",
            payload_bytes=1024,
            width=640,
            height=480,
        )
        now = 101.75
        status = gateway.status("sess_test")

        self.assertIsNone(first["video"]["estimated_fps"])
        self.assertEqual(second["video"]["estimated_fps"], 2.0)
        self.assertEqual(status["video"]["estimated_fps"], 2.0)
        self.assertEqual(status["video"]["last_frame_age_ms"], 1250)
        self.assertEqual(status["video"]["width"], 640)
        self.assertEqual(status["video"]["height"], 480)

    def test_stop_video_stream_marks_receiving_video_idle(self):
        events = InMemoryEventStore()
        gateway = MediaGateway(events=events)
        gateway.record_video_sample(
            session_id="sess_test",
            transport="rv101_tcp",
            codec="video/avc",
            payload_bytes=1024,
            width=640,
            height=360,
        )

        status = gateway.stop_video_stream(session_id="sess_test", reason="live_video_timeout")

        self.assertEqual(status["video"]["state"], "idle")
        self.assertEqual(status["video"]["transport"], "rv101_tcp")
        self.assertEqual(status["video"]["frame_count"], 1)
        self.assertTrue(
            any(event["module"] == "media" and event["event_type"] == "video_stream_stopped" for event in events.list())
        )

    def test_stop_audio_stream_marks_receiving_audio_closed(self):
        events = InMemoryEventStore()
        gateway = MediaGateway(events=events)
        gateway.record_audio_sample(
            session_id="sess_test",
            transport="rv101_tcp",
            sample_rate=24000,
            channels=1,
            payload_bytes=1920,
            strong=False,
            source="rv101",
        )

        status = gateway.stop_audio_stream(session_id="sess_test", reason="rv101_tcp_audio_disconnected")

        self.assertEqual(status["audio"]["state"], "closed")
        self.assertEqual(status["audio"]["transport"], "rv101_tcp")
        self.assertEqual(status["audio"]["chunk_count"], 1)
        self.assertTrue(
            any(event["module"] == "media" and event["event_type"] == "audio_stream_closed" for event in events.list())
        )

    def test_video_heartbeat_starts_fresh_window_after_live_stop(self):
        now = 100.0

        def clock():
            return now

        events = InMemoryEventStore()
        gateway = MediaGateway(events=events, clock=clock)
        gateway.record_video_heartbeat(
            session_id="sess_test",
            transport="rv101_tcp",
            codec="video/avc",
            width=1280,
            height=720,
            fps=30,
            metadata={"requested_fps": 30},
        )
        gateway.record_video_sample(
            session_id="sess_test",
            transport="rv101_tcp",
            codec="video/avc",
            payload_bytes=1000,
            is_keyframe=True,
            width=1280,
            height=720,
        )
        now = 100.5
        first_window = gateway.record_video_sample(
            session_id="sess_test",
            transport="rv101_tcp",
            codec="video/avc",
            payload_bytes=1000,
            width=1280,
            height=720,
        )
        self.assertEqual(first_window["video"]["frame_count"], 2)
        self.assertEqual(first_window["video"]["estimated_fps"], 2.0)

        gateway.stop_video_stream(session_id="sess_test", reason="live_video_timeout")
        now = 140.0
        gateway.record_video_heartbeat(
            session_id="sess_test",
            transport="rv101_tcp",
            codec="video/avc",
            width=1280,
            height=720,
            fps=30,
            metadata={"requested_fps": 30, "sent_fps_estimate": 29.8},
        )
        second_first = gateway.record_video_sample(
            session_id="sess_test",
            transport="rv101_tcp",
            codec="video/avc",
            payload_bytes=2000,
            is_keyframe=True,
            width=1280,
            height=720,
        )
        now = 140.0333333333
        second_second = gateway.record_video_sample(
            session_id="sess_test",
            transport="rv101_tcp",
            codec="video/avc",
            payload_bytes=2000,
            width=1280,
            height=720,
        )

        self.assertEqual(second_first["video"]["frame_count"], 1)
        self.assertIsNone(second_first["video"]["estimated_fps"])
        self.assertEqual(second_second["video"]["frame_count"], 2)
        self.assertEqual(second_second["video"]["byte_count"], 4000)
        self.assertAlmostEqual(second_second["video"]["estimated_fps"], 30.0, places=1)
        self.assertEqual(second_second["video"]["metadata"]["sent_fps_estimate"], 29.8)
        started = [event for event in events.list(limit=20) if event["event_type"] == "video_window_started"]
        self.assertGreaterEqual(len(started), 2)
