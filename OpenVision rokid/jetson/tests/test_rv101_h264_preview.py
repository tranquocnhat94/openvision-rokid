import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.preview_store import PreviewStore
from openvision_jetson.rv101_h264_preview import (
    Rv101H264PreviewDecoder,
    Rv101H264PreviewSettings,
    load_rv101_h264_preview_settings,
)


class FakeImage:
    def __init__(self, width=8, height=4, mode="RGB") -> None:
        self.width = width
        self.height = height
        self.mode = mode

    def resize(self, size, *_args):
        return FakeImage(width=size[0], height=size[1], mode=self.mode)

    def rotate(self, angle, *, expand=False):
        normalized = int(angle) % 360
        if expand and normalized in {90, 270}:
            return FakeImage(width=self.height, height=self.width, mode=self.mode)
        return FakeImage(width=self.width, height=self.height, mode=self.mode)

    def convert(self, mode):
        return FakeImage(width=self.width, height=self.height, mode=mode)

    def save(self, buffer, *, format, quality):
        buffer.write(b"\xff\xd8fake-jpeg")


class FakeH264Decoder:
    def __init__(self) -> None:
        self.closed = False

    def decode(self, payload: bytes):
        if payload != b"frame":
            return []
        return [FakeImage()]

    def close(self) -> None:
        self.closed = True


class Rv101H264PreviewTest(unittest.TestCase):
    def test_default_preview_settings_are_smooth_enough_for_ops_console(self):
        with patch.dict(
            "os.environ",
            {
                "OPENVISION_RV101_H264_PREVIEW": "1",
            },
            clear=True,
        ):
            settings = load_rv101_h264_preview_settings()

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.every_n_frames, 1)
        self.assertEqual(settings.min_interval_ms, 66)
        self.assertEqual(settings.max_width, 720)
        self.assertEqual(settings.jpeg_quality, 82)
        self.assertEqual(settings.queue_size, 4)
        self.assertTrue(settings.decode_every_sample)

    def test_disabled_decoder_ignores_samples(self):
        events = InMemoryEventStore()
        preview = PreviewStore(events=events)
        decoder = Rv101H264PreviewDecoder(
            preview=preview,
            events=events,
            settings_provider=lambda: Rv101H264PreviewSettings(enabled=False),
            decoder_factory=FakeH264Decoder,
        )

        decoder.handle_sample(
            session_id="sess_test",
            header={
                "sequence": 1,
                "isKeyframe": True,
                "sensorOrientationDegrees": 0,
                "requestedWidth": 1280,
                "requestedHeight": 720,
                "sentFpsEstimate": 14.7,
                "droppedFrames": 3,
                "cameraId": "0",
            },
            payload=b"frame",
            media_status={"video": {"frame_count": 1, "metadata": {"capture_fps_max": 15}}},
        )

        self.assertIsNone(preview.status("sess_test"))
        self.assertEqual(decoder.status()["status"], "disabled")

    def test_enabled_decoder_records_jpeg_preview(self):
        events = InMemoryEventStore()
        preview = PreviewStore(events=events)
        recorded = []
        decoder = Rv101H264PreviewDecoder(
            preview=preview,
            events=events,
            settings_provider=lambda: Rv101H264PreviewSettings(
                enabled=True,
                every_n_frames=1,
                min_interval_ms=0,
                max_width=4,
                jpeg_quality=70,
            ),
            decoder_factory=FakeH264Decoder,
            preview_frame_recorder=lambda **kwargs: recorded.append(kwargs),
        )

        decoder.handle_sample(
            session_id="sess_test",
            header={
                "sequence": 1,
                "isKeyframe": True,
                "sensorOrientationDegrees": 0,
                "requestedWidth": 1280,
                "requestedHeight": 720,
                "sentFpsEstimate": 14.7,
                "droppedFrames": 3,
                "cameraId": "0",
            },
            payload=b"frame",
            media_status={"video": {"frame_count": 1, "metadata": {"capture_fps_max": 15}}},
        )

        status = preview.status("sess_test")
        image = preview.latest_image("sess_test")
        self.assertIsNotNone(status)
        self.assertIsNotNone(image)
        self.assertEqual(status["source"], "rv101_live_h264")
        self.assertEqual(status["width"], 4)
        self.assertEqual(status["height"], 2)
        self.assertEqual(status["metadata"]["profile"], "rv101_live_h264")
        self.assertEqual(status["metadata"]["preview_profile"], "downscaled")
        self.assertTrue(status["metadata"]["preview_downscaled"])
        self.assertEqual(status["metadata"]["sensor_orientation_degrees"], 0)
        self.assertEqual(status["metadata"]["requested_width"], 1280)
        self.assertEqual(status["metadata"]["requested_height"], 720)
        self.assertEqual(status["metadata"]["capture_fps_max"], 15)
        self.assertEqual(status["metadata"]["sent_fps_estimate"], 14.7)
        self.assertEqual(status["metadata"]["dropped_frames"], 3)
        self.assertEqual(status["metadata"]["camera_id"], "0")
        self.assertEqual(status["metadata"]["source"], "rv101_live_h264")
        self.assertEqual(status["metadata"]["source_width"], 8)
        self.assertEqual(status["metadata"]["source_height"], 4)
        self.assertEqual(status["metadata"]["sourceWidth"], 8)
        self.assertEqual(status["metadata"]["sourceHeight"], 4)
        self.assertEqual(status["metadata"]["oriented_width"], 8)
        self.assertEqual(status["metadata"]["oriented_height"], 4)
        self.assertFalse(status["metadata"]["rotation_applied"])
        self.assertEqual(status["metadata"]["rotation_applied_degrees"], 0)
        self.assertEqual(status["metadata"]["downscaled_from"], "8x4")
        self.assertEqual(status["metadata"]["downscaled_to"], "4x2")
        self.assertEqual(status["frame_count"], 1)
        self.assertEqual(status["image_url"], "/api/preview/sess_test/frame.jpg")
        self.assertEqual(image[1], "image/jpeg")
        self.assertTrue(image[0].startswith(b"\xff\xd8"))
        self.assertEqual(decoder.status()["decoded_frame_count"], 1)
        self.assertEqual(decoder.status()["preview_frame_count"], 1)
        self.assertIsNone(decoder.status()["max_publish_fps"])
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["session_id"], "sess_test")
        self.assertEqual(recorded[0]["width"], 4)
        self.assertEqual(recorded[0]["height"], 2)
        self.assertEqual(recorded[0]["frame_count"], 1)

    def test_enqueue_uses_bounded_queue_and_drops_when_full(self):
        events = InMemoryEventStore()
        preview = PreviewStore(events=events)
        decoder = Rv101H264PreviewDecoder(
            preview=preview,
            events=events,
            settings_provider=lambda: Rv101H264PreviewSettings(
                enabled=True,
                every_n_frames=1,
                min_interval_ms=0,
                queue_size=1,
            ),
            decoder_factory=FakeH264Decoder,
            start_workers=False,
        )

        first = decoder.enqueue_sample(
            session_id="sess_test",
            header={"sequence": 1, "isKeyframe": True},
            payload=b"frame",
            media_status={"video": {"frame_count": 1}},
        )
        second = decoder.enqueue_sample(
            session_id="sess_test",
            header={"sequence": 2},
            payload=b"frame",
            media_status={"video": {"frame_count": 2}},
        )

        status = decoder.status()
        self.assertTrue(first["queued"])
        self.assertFalse(second["queued"])
        self.assertEqual(second["reason"], "backpressure_delta_drop")
        self.assertEqual(status["queued_sample_count"], 1)
        self.assertEqual(status["processed_sample_count"], 0)
        self.assertEqual(status["pending_sample_count"], 1)
        self.assertEqual(status["queue_drop_count"], 1)
        self.assertIsNone(preview.status("sess_test"))

    def test_enqueue_drops_non_key_samples_until_decoder_config_arrives(self):
        events = InMemoryEventStore()
        preview = PreviewStore(events=events)
        decoder = Rv101H264PreviewDecoder(
            preview=preview,
            events=events,
            settings_provider=lambda: Rv101H264PreviewSettings(
                enabled=True,
                every_n_frames=1,
                min_interval_ms=0,
                queue_size=2,
            ),
            decoder_factory=FakeH264Decoder,
            start_workers=False,
        )

        first = decoder.enqueue_sample(
            session_id="sess_test",
            header={"sequence": 1, "isKeyframe": False},
            payload=b"frame",
            media_status={"video": {"frame_count": 1}},
        )
        second = decoder.enqueue_sample(
            session_id="sess_test",
            header={"sequence": 2, "isKeyframe": True},
            payload=b"frame",
            media_status={"video": {"frame_count": 2}},
        )

        status = decoder.status()
        self.assertFalse(first["queued"])
        self.assertEqual(first["reason"], "throttled")
        self.assertTrue(second["queued"])
        self.assertEqual(status["queued_sample_count"], 1)
        self.assertEqual(status["throttled_sample_count"], 1)

    def test_enqueue_keyframe_replaces_old_sample_when_queue_is_full(self):
        decoder = Rv101H264PreviewDecoder(
            preview=PreviewStore(events=InMemoryEventStore()),
            events=InMemoryEventStore(),
            settings_provider=lambda: Rv101H264PreviewSettings(
                enabled=True,
                every_n_frames=1,
                min_interval_ms=0,
                queue_size=1,
            ),
            decoder_factory=FakeH264Decoder,
            start_workers=False,
        )

        first = decoder.enqueue_sample(
            session_id="sess_test",
            header={"sequence": 1, "isKeyframe": True},
            payload=b"frame",
            media_status={"video": {"frame_count": 1}},
        )
        replacement = decoder.enqueue_sample(
            session_id="sess_test",
            header={"sequence": 2, "isKeyframe": True},
            payload=b"frame",
            media_status={"video": {"frame_count": 2}},
        )

        self.assertTrue(first["queued"])
        self.assertTrue(replacement["queued"])
        self.assertEqual(replacement["reason"], "queued_keyframe_resynced")
        self.assertEqual(decoder.status()["queued_sample_count"], 2)
        self.assertEqual(decoder.status()["pending_sample_count"], 1)
        self.assertEqual(decoder.status()["queue_drop_count"], 0)
        self.assertEqual(decoder.status()["queue_resync_count"], 1)

    def test_rv101_rotation_degrees_270_is_applied_before_preview_resize(self):
        events = InMemoryEventStore()
        preview = PreviewStore(events=events)
        decoder = Rv101H264PreviewDecoder(
            preview=preview,
            events=events,
            settings_provider=lambda: Rv101H264PreviewSettings(
                enabled=True,
                every_n_frames=1,
                min_interval_ms=0,
                max_width=4,
                jpeg_quality=70,
            ),
            decoder_factory=FakeH264Decoder,
        )

        decoder.handle_sample(
            session_id="sess_rv101",
            header={
                "sequence": 1,
                "isKeyframe": True,
                "width": 1280,
                "height": 720,
                "orientation": "landscape",
                "profile": "rv101_live_h264_landscape",
                "sensorOrientationDegrees": 270,
                "rotationDegrees": 270,
                "requestedWidth": 1280,
                "requestedHeight": 720,
            },
            payload=b"frame",
            media_status={"video": {"frame_count": 1}},
        )

        status = preview.status("sess_rv101")
        self.assertIsNotNone(status)
        self.assertEqual(status["source"], "rv101_live_h264")
        self.assertEqual(status["width"], 4)
        self.assertEqual(status["height"], 8)
        self.assertEqual(status["metadata"]["profile"], "rv101_live_h264_landscape")
        self.assertEqual(status["metadata"]["orientation"], "landscape")
        self.assertEqual(status["metadata"]["requested_width"], 1280)
        self.assertEqual(status["metadata"]["requested_height"], 720)
        self.assertEqual(status["metadata"]["sensor_orientation_degrees"], 270)
        self.assertEqual(status["metadata"]["rotation_degrees"], 270)
        self.assertTrue(status["metadata"]["rotation_applied"])
        self.assertEqual(status["metadata"]["rotation_applied_degrees"], 270)
        self.assertEqual(status["metadata"]["rotation_metadata_source"], "rotation_degrees")
        self.assertEqual(status["metadata"]["source_width"], 8)
        self.assertEqual(status["metadata"]["source_height"], 4)
        self.assertEqual(status["metadata"]["sourceWidth"], 8)
        self.assertEqual(status["metadata"]["sourceHeight"], 4)
        self.assertEqual(status["metadata"]["oriented_width"], 4)
        self.assertEqual(status["metadata"]["oriented_height"], 8)
        self.assertEqual(status["metadata"]["preview_width"], 4)
        self.assertEqual(status["metadata"]["preview_height"], 8)
        self.assertEqual(status["metadata"]["downscaled_from"], None)
        self.assertEqual(status["metadata"]["downscaled_to"], "4x8")

    def test_decoder_decodes_every_sample_but_throttles_preview_publish(self):
        events = InMemoryEventStore()
        preview = PreviewStore(events=events)
        now = [100.0]
        decoder = Rv101H264PreviewDecoder(
            preview=preview,
            events=events,
            settings_provider=lambda: Rv101H264PreviewSettings(
                enabled=True,
                every_n_frames=3,
                min_interval_ms=1000,
            ),
            decoder_factory=FakeH264Decoder,
            clock=lambda: now[0],
        )

        for frame_count in [1, 2, 3]:
            decoder.handle_sample(
                session_id="sess_test",
                header={"sequence": frame_count, "isKeyframe": frame_count == 1},
                payload=b"frame",
                media_status={"video": {"frame_count": frame_count}},
            )

        self.assertEqual(preview.status("sess_test")["frame_count"], 1)
        now[0] += 1.1
        decoder.handle_sample(
            session_id="sess_test",
            header={"sequence": 4, "isKeyframe": False},
            payload=b"frame",
            media_status={"video": {"frame_count": 4}},
        )

        self.assertEqual(preview.status("sess_test")["frame_count"], 4)
        self.assertEqual(decoder.status()["decoded_frame_count"], 4)
        self.assertEqual(decoder.status()["preview_frame_count"], 2)
        self.assertEqual(decoder.status()["throttled_sample_count"], 0)


if __name__ == "__main__":
    unittest.main()
