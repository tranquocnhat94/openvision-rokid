import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.yolo26_rokid_adapter import Yolo26RokidAdapter


class Yolo26RokidAdapterTest(unittest.TestCase):
    def test_default_status_is_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            adapter = Yolo26RokidAdapter(events=InMemoryEventStore())
            status = adapter.status()

        self.assertEqual(status["name"], "yolo26_rokid")
        self.assertEqual(status["mode"], "disabled")
        self.assertEqual(status["status"], "disabled")
        self.assertEqual(status["isolation"], "rokid_specific_runtime_only")

    def test_external_snapshot_mode_is_ready_without_ring_runtime(self):
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_snapshot"}, clear=True):
            adapter = Yolo26RokidAdapter(events=InMemoryEventStore())
            status = adapter.status()

        self.assertEqual(status["status"], "ready")
        self.assertFalse(status["engine_exists"])
        self.assertFalse(status["labels_exists"])

    def test_disabled_adapter_rejects_snapshot_ingress(self):
        events = InMemoryEventStore()
        with patch.dict(os.environ, {}, clear=True):
            adapter = Yolo26RokidAdapter(events=events)
            result = adapter.validate_external_snapshot(source="unit")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "adapter_disabled")
        self.assertEqual(events.list()[-1]["event_type"], "snapshot_rejected")

    def test_external_snapshot_accepts_rokid_runtime_source(self):
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_snapshot"}, clear=True):
            adapter = Yolo26RokidAdapter(events=InMemoryEventStore())
            result = adapter.validate_external_snapshot(source="rokid_yolo26_unit")

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["source"], "yolo26_rokid:rokid_yolo26_unit")

    def test_external_snapshot_rejects_generic_or_ring_sources(self):
        events = InMemoryEventStore()
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "external_snapshot"}, clear=True):
            adapter = Yolo26RokidAdapter(events=events)
            generic = adapter.validate_external_snapshot(source="unit")
            ring = adapter.validate_external_snapshot(source="ring_security_yolo26")

        self.assertEqual(generic["status"], "error")
        self.assertEqual(generic["error"]["code"], "invalid_snapshot_source")
        self.assertEqual(ring["status"], "error")
        self.assertEqual(ring["error"]["code"], "forbidden_snapshot_source")
        self.assertEqual(
            [event["payload"]["reason"] for event in events.list()],
            ["invalid_snapshot_source", "forbidden_snapshot_source"],
        )

    def test_inline_runtime_mode_is_invalid(self):
        with patch.dict(os.environ, {"OPENVISION_YOLO26_MODE": "inline_trt"}, clear=True):
            adapter = Yolo26RokidAdapter(events=InMemoryEventStore())
            status = adapter.status()

        self.assertEqual(status["status"], "invalid")

    def test_filter_detections_applies_min_confidence(self):
        adapter = Yolo26RokidAdapter(events=InMemoryEventStore())
        detections = adapter.filter_detections(
            [
                {"label": "person", "confidence": 0.9},
                {"label": "bag", "score": 0.2},
                {"label": "phone"},
            ],
            min_confidence=0.25,
        )

        self.assertEqual([item["label"] for item in detections], ["person"])


if __name__ == "__main__":
    unittest.main()
