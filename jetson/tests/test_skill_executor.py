import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.perception_graph import PerceptionGraph
from openvision_jetson.skill_executor import SkillExecutor


class SkillExecutorTest(unittest.TestCase):
    def test_count_people_uses_latest_perception_snapshot(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="unit",
            detections=[
                {"label": "person", "confidence": 0.9, "bbox": [0, 0, 1, 1]},
                {"label": "person", "confidence": 0.8, "bbox": [1, 0, 2, 1]},
                {"label": "bag", "confidence": 0.7},
            ],
        )
        executor = SkillExecutor(perception=perception, events=events)

        result = executor.execute(
            name="count_people",
            args={"min_confidence": 0.25},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["count"], 2)
        self.assertEqual(result["result"]["hud"]["answer_strip"], "2 người")

    def test_count_people_returns_no_evidence_without_snapshot(self):
        executor = SkillExecutor(
            perception=PerceptionGraph(events=InMemoryEventStore()),
            events=InMemoryEventStore(),
        )

        result = executor.execute(name="count_people", args={}, session_id="sess_missing")

        self.assertEqual(result["status"], "no_evidence")

    def test_search_targets_marks_attribute_queries_as_needing_cloud(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="unit",
            detections=[
                {"label": "person", "confidence": 0.9, "bbox": [0, 0, 1, 1], "track_id": "p1"},
                {"label": "person", "confidence": 0.8, "bbox": [1, 0, 2, 1], "track_id": "p2"},
                {"label": "bag", "confidence": 0.7},
            ],
        )
        executor = SkillExecutor(perception=perception, events=events)

        result = executor.execute(
            name="search_targets",
            args={"query": "người mặc áo màu xanh"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "needs_cloud")
        self.assertEqual(result["result"]["candidate_count"], 2)
        self.assertEqual(result["result"]["confirmed_match_count"], 0)
        self.assertEqual(result["result"]["cloud_attribute_resolution"], "required")
        self.assertIn("chưa xác minh", result["result"]["user_message"])
        self.assertEqual(
            result["result"]["candidates"][0]["match_status"],
            "unverified_attribute_candidate",
        )
        self.assertIn("chưa xác minh", result["result"]["hud"]["answer_strip"])
        self.assertEqual(len(result["result"]["hud"]["thumbnails"]), 2)
        self.assertEqual(result["result"]["hud"]["thumbnails"][0]["target_id"], result["result"]["candidates"][0]["target_id"])
        self.assertEqual(result["result"]["hud"]["thumbnails"][0]["match_status"], "unverified_attribute_candidate")

    def test_search_targets_allows_label_only_candidates(self):
        events = InMemoryEventStore()
        perception = PerceptionGraph(events=events)
        perception.update_snapshot(
            session_id="sess_test",
            source="unit",
            detections=[
                {"label": "person", "confidence": 0.9, "track_id": "p1"},
                {"label": "bag", "confidence": 0.7, "track_id": "b1"},
            ],
        )
        executor = SkillExecutor(perception=perception, events=events)

        result = executor.execute(
            name="search_targets",
            args={"query": "người"},
            session_id="sess_test",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"]["candidate_semantics"], "label_matches")
        self.assertEqual(result["result"]["confirmed_match_count"], 1)
        self.assertEqual(len(result["result"]["hud"]["thumbnails"]), 1)


if __name__ == "__main__":
    unittest.main()
