import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.yolo26_live_stabilizer import (
    Yolo26LiveStabilizer,
    Yolo26LiveStabilizerSettings,
)


class Yolo26LiveStabilizerTest(unittest.TestCase):
    def test_filters_noisy_boxes_and_emits_confident_track_immediately(self):
        events = InMemoryEventStore()
        stabilizer = Yolo26LiveStabilizer(
            events=events,
            settings_provider=lambda: Yolo26LiveStabilizerSettings(
                min_confidence=0.35,
                instant_confidence=0.70,
                min_hits=2,
                class_allowlist={"person"},
            ),
            clock=lambda: 10.0,
        )

        detections, metrics = stabilizer.stabilize(
            session_id="sess_1",
            source="yolo26_rokid_stream:openvision_rv101_yolo26",
            frame_id="f1",
            width=800,
            height=600,
            sequence=1,
            detections=[
                {"label": "person", "confidence": 0.91, "bbox": [10, 20, 110, 220], "track_id": "p1"},
                {"label": "person", "confidence": 0.89, "bbox": [14, 22, 112, 218], "track_id": "p2"},
                {"label": "object", "confidence": 0.99, "bbox": [300, 20, 360, 80]},
                {"label": "bottle", "confidence": 0.20, "bbox": [420, 200, 460, 310]},
            ],
        )

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0]["label"], "person")
        self.assertTrue(detections[0]["attributes"]["stabilized"])
        self.assertEqual(metrics["raw_count"], 4)
        self.assertEqual(metrics["after_nms_count"], 1)
        self.assertEqual(metrics["rejected_unclassified"], 1)
        self.assertEqual(metrics["rejected_low_confidence"], 1)

    def test_holds_recent_track_to_reduce_flicker_then_expires(self):
        now = {"value": 20.0}
        stabilizer = Yolo26LiveStabilizer(
            events=InMemoryEventStore(),
            settings_provider=lambda: Yolo26LiveStabilizerSettings(
                min_confidence=0.35,
                instant_confidence=0.70,
                min_hits=1,
                hold_ms=500,
                class_allowlist={"person"},
            ),
            clock=lambda: now["value"],
        )
        first, _ = stabilizer.stabilize(
            session_id="sess_1",
            source="yolo26_rokid_stream:openvision_rv101_yolo26",
            detections=[{"label": "person", "confidence": 0.9, "bbox": [10, 20, 110, 220], "track_id": "p1"}],
        )
        now["value"] = 20.2
        held, held_metrics = stabilizer.stabilize(
            session_id="sess_1",
            source="yolo26_rokid_stream:openvision_rv101_yolo26",
            detections=[],
        )
        now["value"] = 20.8
        expired, expired_metrics = stabilizer.stabilize(
            session_id="sess_1",
            source="yolo26_rokid_stream:openvision_rv101_yolo26",
            detections=[],
        )

        self.assertEqual(first[0]["attributes"]["stable_state"], "tracked")
        self.assertEqual(held[0]["attributes"]["stable_state"], "held")
        self.assertEqual(held_metrics["held_count"], 1)
        self.assertEqual(expired, [])
        self.assertEqual(expired_metrics["track_count"], 0)


if __name__ == "__main__":
    unittest.main()
