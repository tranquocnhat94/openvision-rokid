import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from openvision_jetson.face_identity_worker import (
    FaceIdentityWorker,
    FaceIdentityWorkerSettings,
    JsonStatusWriter,
    SimpleFaceTracker,
    _absolute_url,
    _face_quality_metrics,
    _map_bbox_to_original,
    _scale_bbox,
    build_face_backend,
    load_face_identity_worker_settings,
)


class FakeImage:
    width = 640
    height = 480

    def crop(self, box):
        self.box = box
        return self

    def save(self, path, **kwargs):
        _ = kwargs
        Path(path).write_bytes(b"fake-jpeg")


class FakeApi:
    def __init__(self):
        self.posts = []
        self.image = FakeImage()
        self.active_live = [{"session_id": "sess_test", "skill_id": "target_finder"}]
        self.previews = [
            {
                "session_id": "sess_test",
                "has_frame": True,
                "image_url": "/api/preview/sess_test/frame.jpg",
                "frame_count": 7,
                "frame_id": "frame_7",
                "metadata": {"orientation": "landscape", "profile": "rv101_live_h264"},
            }
        ]
        self.preview_call_count = 0

    def list_active_live(self):
        return self.active_live

    def list_preview(self):
        self.preview_call_count += 1
        return self.previews

    def fetch_image(self, image_url):
        self.fetched = image_url
        return self.image

    def post_face_detections(self, *, session_id, payload):
        self.posts.append((session_id, payload))
        return {"status": "accepted", "perception": {"session_id": session_id}}


class FakeBackend:
    def status(self):
        return {"status": "ready", "backend": "fake_face"}

    def detect_and_embed(self, image):
        return [
            {
                "label": "person",
                "confidence": 0.91,
                "bbox": [220, 80, 320, 230],
                "attributes": {"identity_vector": [1.0, 0.0], "face_confidence": 0.91},
            }
        ]


class FakeGray:
    def __init__(self, *, mean_value: float, std_value: float) -> None:
        self._mean_value = mean_value
        self._std_value = std_value

    def mean(self):
        return self._mean_value

    def std(self):
        return self._std_value


class FakeLaplacian:
    def __init__(self, *, var_value: float) -> None:
        self._var_value = var_value

    def var(self):
        return self._var_value


class FakeCv2:
    COLOR_BGR2GRAY = 1
    CV_64F = 2

    def __init__(self, *, mean_value: float, std_value: float, var_value: float) -> None:
        self._gray = FakeGray(mean_value=mean_value, std_value=std_value)
        self._laplacian = FakeLaplacian(var_value=var_value)

    def cvtColor(self, bgr, mode):
        _ = bgr, mode
        return self._gray

    def Laplacian(self, gray, depth):
        _ = gray, depth
        return self._laplacian


class FaceIdentityWorkerTests(TestCase):
    def test_disabled_worker_writes_disabled_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = FaceIdentityWorkerSettings(enabled=False, runtime_dir=Path(tmp))
            worker = FaceIdentityWorker(settings=settings, api=FakeApi(), backend=FakeBackend())

            status = worker.run_once()

            self.assertEqual(status["status"], "disabled")
            self.assertFalse(status["enabled"])

    def test_blocked_backend_reports_status_without_posting(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = FaceIdentityWorkerSettings(enabled=True, runtime_dir=Path(tmp))
            backend = build_face_backend(settings)
            api = FakeApi()
            worker = FaceIdentityWorker(settings=settings, api=api, backend=backend)

            status = worker.run_once()

            self.assertEqual(status["status"], "blocked")
            self.assertEqual(api.posts, [])

    def test_worker_posts_face_embeddings_and_crops_for_active_target_finder(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            settings = FaceIdentityWorkerSettings(
                enabled=True,
                runtime_dir=runtime_dir,
                source="openvision_rokid_face_identity",
                max_fps=10,
            )
            api = FakeApi()
            worker = FaceIdentityWorker(settings=settings, api=api, backend=FakeBackend(), clock=lambda: 1.0)

            status = worker.run_once()

            self.assertEqual(status["status"], "running")
            self.assertEqual(status["posted_frame_count"], 1)
            self.assertEqual(status["total_posted_frame_count"], 1)
            self.assertEqual(status["last_posted_frame"]["session_id"], "sess_test")
            self.assertEqual(status["last_posted_frame"]["frame_id"], "frame_7")
            self.assertEqual(status["last_posted_frame"]["detection_count"], 1)
            self.assertEqual(len(api.posts), 1)
            session_id, payload = api.posts[0]
            self.assertEqual(session_id, "sess_test")
            self.assertEqual(payload["source"], "openvision_rokid_face_identity")
            self.assertEqual(payload["frame_id"], "frame_7")
            self.assertEqual(payload["metadata"]["orientation"], "landscape")
            self.assertEqual(payload["metadata"]["profile"], "rv101_live_h264")
            self.assertEqual(api.fetched, "/api/preview/sess_test/frame.jpg?frame_count=7")
            self.assertEqual(payload["detections"][0]["track_id"], "f1")
            self.assertEqual(payload["detections"][0]["attributes"]["identity_vector"], [1.0, 0.0])
            self.assertEqual(payload["detections"][0]["crop_ref"], "/api/crops/sess_test/face_f1_latest.jpg")
            self.assertTrue((runtime_dir / "crops" / "sess_test" / "face_f1_latest.jpg").is_file())

    def test_worker_posts_for_active_person_info_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = FaceIdentityWorkerSettings(
                enabled=True,
                runtime_dir=Path(tmp),
                source="openvision_rokid_face_identity",
                max_fps=10,
            )
            api = FakeApi()
            api.active_live = [{"session_id": "sess_test", "skill_id": "person_info"}]
            worker = FaceIdentityWorker(settings=settings, api=api, backend=FakeBackend(), clock=lambda: 1.0)

            status = worker.run_once()

            self.assertEqual(status["status"], "running")
            self.assertEqual(status["target_skill_ids"], ["person_info", "target_finder"])
            self.assertEqual(len(api.posts), 1)
            self.assertEqual(api.posts[0][0], "sess_test")

    def test_worker_skips_duplicate_preview_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = FaceIdentityWorkerSettings(enabled=True, runtime_dir=Path(tmp), max_fps=10)
            api = FakeApi()
            worker = FaceIdentityWorker(settings=settings, api=api, backend=FakeBackend(), clock=lambda: 1.0)

            first = worker.run_once()
            second = worker.run_once()

            self.assertEqual(first["posted_frame_count"], 1)
            self.assertEqual(second["posted_frame_count"], 0)
            self.assertEqual(second["skipped_frame_count"], 1)
            self.assertEqual(second["total_posted_frame_count"], 1)
            self.assertGreaterEqual(second["total_skipped_frame_count"], 1)

    def test_worker_prunes_session_state_when_live_session_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = FaceIdentityWorkerSettings(enabled=True, runtime_dir=Path(tmp), max_fps=10)
            api = FakeApi()
            tracker = SimpleFaceTracker()
            worker = FaceIdentityWorker(
                settings=settings,
                api=api,
                backend=FakeBackend(),
                tracker=tracker,
                clock=lambda: 1.0,
            )

            first = worker.run_once()
            api.active_live = []
            second = worker.run_once()

            self.assertEqual(first["posted_frame_count"], 1)
            self.assertEqual(second["active_live_count"], 0)
            self.assertEqual(second["posted_frame_count"], 0)
            self.assertEqual(worker._last_frame_count, {})
            self.assertEqual(worker._last_post_s, {})
            self.assertEqual(tracker._tracks, {})
            self.assertEqual(api.preview_call_count, 1)

    def test_worker_uses_slower_polling_when_idle(self):
        settings = FaceIdentityWorkerSettings(
            enabled=True,
            poll_interval_s=0.25,
            idle_poll_interval_s=2.5,
        )
        worker = FaceIdentityWorker(settings=settings, api=FakeApi(), backend=FakeBackend())

        self.assertEqual(worker._sleep_interval_s({"active_live_count": 0}), 2.5)
        self.assertEqual(worker._sleep_interval_s({"active_live_count": 1}), 0.25)

    def test_settings_sanitize_ring_source(self):
        with patch.dict("os.environ", {"OPENVISION_FACE_WORKER_SOURCE": "ring_security_face"}):
            settings = load_face_identity_worker_settings()

        self.assertEqual(settings.source, "openvision_rokid_face_identity")

    def test_settings_default_to_high_resolution_identity_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"OPENVISION_RUNTIME_DIR": tmp}, clear=True):
                settings = load_face_identity_worker_settings()

        self.assertEqual(settings.detection_target_size, 1280)
        self.assertEqual(settings.min_identity_face_side_px, 56)

    def test_preview_absolute_url_must_stay_on_jetson_origin(self):
        base = "http://127.0.0.1:8765"

        self.assertEqual(_absolute_url(base, "/api/preview/sess/frame.jpg"), "http://127.0.0.1:8765/api/preview/sess/frame.jpg")
        self.assertEqual(
            _absolute_url(base, "http://127.0.0.1:8765/api/preview/sess/frame.jpg"),
            "http://127.0.0.1:8765/api/preview/sess/frame.jpg",
        )
        with self.assertRaises(ValueError):
            _absolute_url(base, "http://example.invalid/frame.jpg")

    def test_face_bbox_mapping_handles_orientation_fallbacks(self):
        self.assertEqual(_scale_bbox([20, 40, 120, 240], 0.5), [10.0, 20.0, 60.0, 120.0])
        self.assertEqual(
            _map_bbox_to_original([180, 10, 220, 110], orientation=90, original_width=100, original_height=240),
            [10.0, 20.0, 100.0, 60.0],
        )
        self.assertEqual(
            _map_bbox_to_original([20, 10, 60, 90], orientation=-90, original_width=100, original_height=240),
            [10.0, 20.0, 90.0, 60.0],
        )
        self.assertEqual(
            _map_bbox_to_original([10, 20, 40, 60], orientation=180, original_width=100, original_height=240),
            [60.0, 180.0, 90.0, 220.0],
        )

    def test_face_quality_metrics_flag_low_light_faces(self):
        metrics = _face_quality_metrics(FakeCv2(mean_value=18.0, std_value=6.0, var_value=1.0), object())

        self.assertEqual(metrics["face_quality_status"], "low_quality")
        self.assertEqual(metrics["face_brightness"], 18.0)
        self.assertIn("too_dark_for_identity", metrics["identity_quality_reasons"])
        self.assertIn("low_contrast_for_identity", metrics["identity_quality_reasons"])
        self.assertIn("too_soft_for_identity", metrics["identity_quality_reasons"])
