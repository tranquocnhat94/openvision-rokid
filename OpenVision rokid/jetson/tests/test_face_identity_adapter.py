import os
from unittest import TestCase
from unittest.mock import patch

from openvision_jetson.face_identity_adapter import FaceIdentityAdapter


class FaceIdentityAdapterTests(TestCase):
    def test_status_ready_for_external_stream_by_default(self):
        adapter = FaceIdentityAdapter()

        status = adapter.status()

        self.assertEqual(status["name"], "face_identity")
        self.assertEqual(status["status"], "ready")
        self.assertTrue(status["stream_ingest_enabled"])
        self.assertEqual(status["isolation"], "separate_openvision_runtime_only")

    def test_rejects_ring_source(self):
        adapter = FaceIdentityAdapter()

        result = adapter.validate_external_stream(source="ring_security_face_id")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "forbidden_stream_source")

    def test_rejects_untrusted_source(self):
        adapter = FaceIdentityAdapter()

        result = adapter.validate_external_stream(source="random_worker")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "untrusted_stream_source")

    def test_filter_detections_keeps_identity_vector_attributes(self):
        adapter = FaceIdentityAdapter()

        filtered = adapter.filter_detections(
            [
                {"label": "person", "confidence": 0.9, "attributes": {"identity_vector": [1.0, 0.0]}},
                {"label": "person", "confidence": 0.2},
            ],
            min_confidence=0.75,
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["attributes"]["identity_vector"], [1.0, 0.0])
        self.assertEqual(filtered[0]["attributes"]["detector_family"], "face_identity")

    def test_disabled_mode_blocks_stream(self):
        adapter = FaceIdentityAdapter()
        with patch.dict(os.environ, {"OPENVISION_FACE_IDENTITY_MODE": "disabled"}):
            result = adapter.validate_external_stream(source="openvision_iphone_face_identity")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "adapter_mode_mismatch")
