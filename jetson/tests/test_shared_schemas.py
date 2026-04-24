import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.perception_graph import PerceptionGraph
from openvision_jetson.session_replay import build_session_replay, build_session_scorecard


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "shared" / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def assert_required_fields(testcase: unittest.TestCase, schema: dict, payload: dict) -> None:
    for key in schema.get("required", []):
        testcase.assertIn(key, payload, f"missing required field {key}")
    properties = schema.get("properties", {})
    for key, subschema in properties.items():
        if key not in payload:
            continue
        value = payload[key]
        allowed_types = subschema.get("type")
        if isinstance(allowed_types, str):
            allowed_types = [allowed_types]
        if isinstance(allowed_types, list):
            testcase.assertTrue(
                any(_matches_json_type(value, expected) for expected in allowed_types),
                f"{key} has unexpected type: {type(value).__name__}",
            )
        if isinstance(value, dict) and isinstance(subschema.get("properties"), dict):
            assert_required_fields(testcase, subschema, value)
        if isinstance(value, list) and isinstance(subschema.get("items"), dict):
            item_schema = subschema["items"]
            for item in value:
                if isinstance(item, dict):
                    assert_required_fields(testcase, item_schema, item)


def _matches_json_type(value, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


class SharedSchemasTest(unittest.TestCase):
    def test_all_shared_schema_files_are_json_objects(self):
        schema_files = sorted(SCHEMA_DIR.glob("*.schema.json"))
        self.assertGreaterEqual(len(schema_files), 10)
        for path in schema_files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertIn("title", payload)
            self.assertEqual(payload["type"], "object")

    def test_perception_graph_runtime_payload_matches_schema_surface(self):
        graph = PerceptionGraph(events=InMemoryEventStore())
        payload = graph.update_snapshot(
            session_id="sess_test",
            source="unit",
            frame_id="frame_1",
            width=640,
            height=480,
            detections=[
                {
                    "label": "person",
                    "confidence": 0.9,
                    "bbox": [10, 20, 100, 200],
                    "track_id": "track_1",
                    "attributes": {"zone": "front"},
                }
            ],
        )

        self.assertEqual(payload["schema_version"], "perception_snapshot.v1")
        assert_required_fields(self, load_schema("perception_graph.schema.json"), payload)

    def test_replay_and_scorecard_payloads_match_schema_surface(self):
        replay = build_session_replay(
            session_id="sess_test",
            sessions=[{"session_id": "sess_test"}],
            events=[],
            media=[],
            perception=[],
            hud_scenes=[],
            realtime=[],
            debug_stt=[],
        )
        scorecard = build_session_scorecard(replay)

        assert_required_fields(self, load_schema("session_replay.schema.json"), replay)
        assert_required_fields(self, load_schema("session_scorecard.schema.json"), scorecard)

    def test_cloud_and_memory_contract_examples_match_required_fields(self):
        evidence = {
            "schema_version": "cloud_evidence_bundle.v1",
            "bundle_id": "bundle_test",
            "session_id": "sess_test",
            "skill_id": "target_finder",
            "user_query": "find person in blue shirt",
            "created_at": "2026-04-25T00:00:00.000+00:00",
            "local_summary": {"candidate_count": 2},
            "frame_refs": [],
            "crop_refs": [],
            "candidates": [],
            "requested_output": {"format": "json", "max_answer_chars": 60, "hud_allowed": True},
            "privacy": {
                "contains_face": True,
                "allow_cloud": True,
                "store_result": False,
                "privacy_level": "medium",
            },
        }
        cloud_result = {
            "schema_version": "cloud_result.v1",
            "status": "ok",
            "answer_short": "left front",
            "answer_long": None,
            "confidence": 0.82,
            "selected_candidate_id": "track_1",
            "hud_scene": None,
            "safety_flags": [],
            "memory_event": None,
            "error": None,
        }
        memory_event = {
            "schema_version": "memory_event.v1",
            "event_id": "mem_test",
            "session_id": "sess_test",
            "created_at": "2026-04-25T00:00:00.000+00:00",
            "type": "object_location",
            "summary": "Keys seen on desk",
            "evidence_ref": None,
            "retention": "user_saved",
            "cloud_synced": False,
            "delete_allowed": True,
        }

        assert_required_fields(self, load_schema("cloud_evidence_bundle.schema.json"), evidence)
        assert_required_fields(self, load_schema("cloud_result.schema.json"), cloud_result)
        assert_required_fields(self, load_schema("memory_event.schema.json"), memory_event)


if __name__ == "__main__":
    unittest.main()
