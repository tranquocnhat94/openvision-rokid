import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.rv101_stream_recorder import Rv101StreamRecorder, Rv101StreamRecorderSettings


def _jpeg_bytes() -> bytes:
    return b"synthetic-preview-bytes"


class Rv101StreamRecorderTest(unittest.TestCase):
    def test_records_raw_media_and_annotated_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Rv101StreamRecorderSettings(enabled=True, root_dir=Path(temp_dir), max_queue_items=32)
            recorder = Rv101StreamRecorder(
                events=InMemoryEventStore(),
                settings_provider=lambda: settings,
            )

            recorder.record_video_frame(
                session_id="sess_record",
                message_type=1,
                header={"sessionId": "sess_record", "width": 800, "height": 600, "targetFps": 15},
                payload=b"",
            )
            recorder.record_video_frame(
                session_id="sess_record",
                message_type=2,
                header={"sessionId": "sess_record", "isKeyframe": True, "sequence": 1, "width": 800, "height": 600},
                payload=b"\x00\x00\x00\x01h264",
            )
            recorder.record_audio_frame(
                session_id="sess_record",
                message_type=3,
                header={"sessionId": "sess_record", "sampleRateHz": 24000, "channels": 1},
                payload=b"",
            )
            recorder.record_audio_frame(
                session_id="sess_record",
                message_type=4,
                header={"sessionId": "sess_record", "sampleRateHz": 24000, "channels": 1},
                payload=b"\x00\x00\x01\x00",
            )
            recorder.record_processed_preview(
                session_id="sess_record",
                image_bytes=_jpeg_bytes(),
                frame_count=7,
                width=320,
                height=180,
                perception={
                    "snapshot_id": "perception_test",
                    "source": "yolo26_rokid_stream",
                    "frame_id": "preview_7",
                    "width": 320,
                    "height": 180,
                    "metadata": {
                        "perception_frame_count": 5,
                        "perception_frame_delta": 2,
                        "perception_bbox_stale": False,
                    },
                    "objects": [
                        {
                            "label": "person",
                            "confidence": 0.91,
                            "bbox": [20, 15, 120, 160],
                            "track_id": "p1",
                        }
                    ],
                },
            )
            recorder.close_session("sess_record", reason="unit_test")
            recorder.close_all()

            recordings = recorder.list_recordings()
            self.assertEqual(len(recordings), 1)
            row = recordings[0]
            self.assertTrue(Path(row["raw_video_path"]).is_file())
            self.assertTrue(Path(row["raw_audio_path"]).is_file())
            self.assertTrue(Path(row["processed_preview_path"]).is_file())
            self.assertTrue(Path(row["latest_annotated_preview_path"]).is_file())
            self.assertGreater(Path(row["raw_video_path"]).stat().st_size, 0)
            self.assertGreater(Path(row["raw_audio_path"]).stat().st_size, 0)
            self.assertGreater(Path(row["processed_preview_path"]).stat().st_size, 0)
            self.assertEqual(row["summary"]["raw_video_frame_count"], 1)
            self.assertEqual(row["summary"]["raw_video_width"], 800)
            self.assertEqual(row["summary"]["raw_video_height"], 600)
            self.assertEqual(row["summary"]["processed_frame_count"], 1)
            self.assertEqual(row["summary"]["processed_preview_width"], 320)
            self.assertEqual(row["summary"]["processed_preview_height"], 180)
            self.assertIsNotNone(row["summary"]["raw_audio_duration_s"])
            manifest = Path(row["manifest_path"]).read_text(encoding="utf-8")
            self.assertIn("recording_started", manifest)
            self.assertIn("recording_closed", manifest)
            processed_events = Path(row["artifacts"]["processed_events"]["path"]).read_text(encoding="utf-8")
            self.assertIn('"perception_frame_count":5', processed_events)
            self.assertIn('"perception_frame_delta":2', processed_events)

    def test_active_processed_preview_status_exposes_latest_frame(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Rv101StreamRecorderSettings(enabled=True, root_dir=Path(temp_dir), max_queue_items=32)
            recorder = Rv101StreamRecorder(
                events=InMemoryEventStore(),
                settings_provider=lambda: settings,
            )

            recorder.record_processed_preview(
                session_id="sess_live",
                image_bytes=_jpeg_bytes(),
                frame_count=1,
                width=320,
                height=180,
                perception={"source": "unit", "objects": []},
            )
            recorder._queue.join()

            status = recorder.active_processed_preview("sess_live")

            self.assertIsNotNone(status)
            self.assertEqual(status["session_id"], "sess_live")
            self.assertTrue(Path(status["latest_annotated_preview"]["path"]).is_file())
            self.assertEqual(status["latest_annotated_preview"]["size_bytes"], len(_jpeg_bytes()))

    def test_post_close_audio_tail_does_not_create_second_recording(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            events = InMemoryEventStore()
            settings = Rv101StreamRecorderSettings(enabled=True, root_dir=Path(temp_dir), max_queue_items=32)
            recorder = Rv101StreamRecorder(
                events=events,
                settings_provider=lambda: settings,
            )

            recorder.record_video_frame(
                session_id="sess_tail",
                message_type=2,
                header={"sessionId": "sess_tail", "isKeyframe": True, "sequence": 1, "width": 800, "height": 600},
                payload=b"\x00\x00\x00\x01h264",
            )
            recorder.record_audio_frame(
                session_id="sess_tail",
                message_type=4,
                header={"sessionId": "sess_tail", "sampleRateHz": 24000, "channels": 1},
                payload=b"\x00\x00\x01\x00",
            )
            recorder.close_session("sess_tail", reason="live_video_cancelled")
            recorder.record_audio_frame(
                session_id="sess_tail",
                message_type=4,
                header={"sessionId": "sess_tail", "sampleRateHz": 24000, "channels": 1},
                payload=b"\x00\x00\x01\x00",
            )
            recorder.close_session("sess_tail", reason="live_video_cancelled")
            recorder.close_all()

            recordings = recorder.list_recordings()
            self.assertEqual(len(recordings), 1)
            self.assertEqual(recordings[0]["session_id"], "sess_tail")
            ignored = [
                event
                for event in events.list(session_id="sess_tail")
                if event["event_type"] == "post_close_media_ignored"
            ]
            self.assertEqual(len(ignored), 1)


if __name__ == "__main__":
    unittest.main()
