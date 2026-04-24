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


if __name__ == "__main__":
    unittest.main()
