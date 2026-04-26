import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.perception_graph import PerceptionGraph, compute_bbox_zone


class PerceptionGraphZoneTest(unittest.TestCase):
    def test_compute_bbox_zone_from_normalized_bbox(self):
        self.assertEqual(compute_bbox_zone([0.05, 0.2, 0.25, 0.7]), "left_front")
        self.assertEqual(compute_bbox_zone([0.38, 0.2, 0.62, 0.7]), "front")
        self.assertEqual(compute_bbox_zone([0.75, 0.2, 0.95, 0.7]), "right_front")

    def test_compute_bbox_zone_from_size(self):
        self.assertEqual(compute_bbox_zone([0.15, 0.05, 0.85, 0.95]), "near")
        self.assertEqual(compute_bbox_zone([0.49, 0.4, 0.53, 0.54]), "far")

    def test_compute_bbox_zone_from_absolute_bbox(self):
        self.assertEqual(
            compute_bbox_zone([480, 120, 620, 430], frame_width=640, frame_height=480),
            "right_front",
        )

    def test_compute_bbox_zone_unknown_when_bbox_or_frame_is_unusable(self):
        self.assertEqual(compute_bbox_zone(None), "unknown")
        self.assertEqual(compute_bbox_zone([10, 20, 100, 200]), "unknown")
        self.assertEqual(compute_bbox_zone([0.5, 0.5, 0.5, 0.6]), "unknown")

    def test_graph_computes_missing_or_invalid_zones(self):
        graph = PerceptionGraph(events=InMemoryEventStore())
        payload = graph.update_snapshot(
            session_id="sess_test",
            source="unit",
            width=640,
            height=480,
            detections=[
                {"label": "person", "confidence": 0.9, "bbox": [20, 100, 160, 350]},
                {"label": "person", "confidence": 0.9, "bbox": [240, 80, 390, 360]},
                {"label": "person", "confidence": 0.9, "bbox": [500, 100, 620, 350]},
                {"label": "person", "confidence": 0.9, "bbox": [80, 20, 560, 460]},
                {"label": "person", "confidence": 0.9, "bbox": [310, 210, 335, 260]},
                {"label": "person", "confidence": 0.9, "zone": "somewhere"},
            ],
        )

        self.assertEqual(
            [obj["zone"] for obj in payload["objects"]],
            ["left_front", "front", "right_front", "near", "far", "unknown"],
        )

    def test_graph_preserves_valid_explicit_zone(self):
        graph = PerceptionGraph(events=InMemoryEventStore())
        payload = graph.update_snapshot(
            session_id="sess_test",
            source="unit",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.9,
                    "bbox": [20, 100, 160, 350],
                    "attributes": {"zone": "front"},
                }
            ],
        )

        self.assertEqual(payload["objects"][0]["zone"], "front")


class PerceptionGraphTemporalTest(unittest.TestCase):
    def test_object_persists_across_updates_by_track_id(self):
        times = iter(
            [
                "2026-04-25T00:00:00.000+00:00",
                "2026-04-25T00:00:02.500+00:00",
            ]
        )
        graph = PerceptionGraph(events=InMemoryEventStore(), now_provider=lambda: next(times))
        first = graph.update_snapshot(
            session_id="sess_test",
            source="unit",
            frame_id="frame_1",
            width=640,
            height=480,
            detections=[{"label": "person", "confidence": 0.9, "track_id": "p1", "bbox": [20, 100, 160, 350]}],
        )
        second = graph.update_snapshot(
            session_id="sess_test",
            source="unit",
            frame_id="frame_2",
            width=640,
            height=480,
            detections=[{"label": "person", "confidence": 0.8, "track_id": "p1", "bbox": [240, 80, 390, 360]}],
        )

        first_obj = first["objects"][0]
        second_obj = second["objects"][0]
        self.assertEqual(second_obj["object_id"], first_obj["object_id"])
        self.assertEqual(second_obj["first_seen_at"], first_obj["first_seen_at"])
        self.assertEqual(second_obj["last_seen_at"], "2026-04-25T00:00:02.500+00:00")
        self.assertEqual(second_obj["age_ms"], 2500)
        self.assertEqual(second_obj["zone"], "front")

    def test_object_persists_across_updates_by_object_id_without_track_id(self):
        times = iter(
            [
                "2026-04-25T00:00:00.000+00:00",
                "2026-04-25T00:00:01.000+00:00",
            ]
        )
        graph = PerceptionGraph(events=InMemoryEventStore(), now_provider=lambda: next(times))
        first = graph.update_snapshot(
            session_id="sess_test",
            source="unit",
            detections=[{"object_id": "obj_person_1", "label": "person", "confidence": 0.9}],
        )
        second = graph.update_snapshot(
            session_id="sess_test",
            source="unit",
            detections=[{"object_id": "obj_person_1", "label": "person", "confidence": 0.7}],
        )

        self.assertEqual(second["objects"][0]["object_id"], first["objects"][0]["object_id"])
        self.assertEqual(second["objects"][0]["first_seen_at"], first["objects"][0]["first_seen_at"])
        self.assertEqual(second["objects"][0]["age_ms"], 1000)

    def test_recent_snapshots_are_kept_per_session_and_capped(self):
        times = iter(
            [
                "2026-04-25T00:00:00.000+00:00",
                "2026-04-25T00:00:01.000+00:00",
                "2026-04-25T00:00:02.000+00:00",
                "2026-04-25T00:00:03.000+00:00",
            ]
        )
        graph = PerceptionGraph(events=InMemoryEventStore(), now_provider=lambda: next(times), history_limit=2)
        for frame_id in ("frame_1", "frame_2", "frame_3"):
            graph.update_snapshot(
                session_id="sess_a",
                source="unit",
                frame_id=frame_id,
                detections=[{"object_id": "obj_a", "label": "person", "confidence": 0.9}],
            )
        graph.update_snapshot(
            session_id="sess_b",
            source="unit",
            frame_id="frame_other",
            detections=[{"object_id": "obj_b", "label": "bag", "confidence": 0.9}],
        )

        self.assertEqual([item["frame_id"] for item in graph.recent_snapshots("sess_a", limit=10)], ["frame_2", "frame_3"])
        self.assertEqual([item["frame_id"] for item in graph.recent_snapshots("sess_b")], ["frame_other"])


if __name__ == "__main__":
    unittest.main()
