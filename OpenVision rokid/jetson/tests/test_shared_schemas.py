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
        obj = payload["objects"][0]
        self.assertEqual(obj["zone"], "front")
        self.assertEqual(obj["first_seen_at"], payload["created_at"])
        self.assertEqual(obj["last_seen_at"], payload["created_at"])
        self.assertEqual(obj["age_ms"], 0)
        self.assertEqual(obj["frame_width"], 640)
        self.assertEqual(obj["frame_height"], 480)
        assert_required_fields(self, load_schema("perception_graph.schema.json"), payload)

    def test_perception_graph_optional_object_fields_are_schema_safe(self):
        graph = PerceptionGraph(events=InMemoryEventStore())
        payload = graph.update_snapshot(
            session_id="sess_test",
            source="unit",
            detections=[{"name": "Phone", "score": 1.5, "bbox": [1, 2, 3]}],
        )

        obj = payload["objects"][0]
        self.assertEqual(obj["label"], "phone")
        self.assertEqual(obj["confidence"], 1.0)
        self.assertIsNone(obj["bbox"])
        self.assertIsNone(obj["track_id"])
        self.assertEqual(obj["zone"], "unknown")
        self.assertIsNone(obj["frame_width"])
        self.assertIsNone(obj["frame_height"])
        self.assertEqual(obj["age_ms"], 0)
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

    def test_realtime_media_and_display_contract_examples_match_required_fields(self):
        realtime_tool_call = {
            "schema_version": "openvision.realtime_tool_call.v1",
            "call_id": "call_test",
            "name": "count_people",
            "arguments": {"min_confidence": 0.5},
            "session_id": "sess_test",
            "source": "openai_realtime",
            "received_at": "2026-04-25T00:00:00.000+00:00",
        }
        tool_result = {
            "schema_version": "openvision.tool_result.v1",
            "tool_call_id": "call_test",
            "tool_name": "count_people",
            "session_id": "sess_test",
            "status": "ok",
            "result": {"count": 2},
            "display_command": None,
            "duration_ms": 18,
            "created_at": "2026-04-25T00:00:00.000+00:00",
        }
        tool_error = {
            "schema_version": "openvision.tool_error.v1",
            "tool_call_id": "call_bad",
            "tool_name": "count_people",
            "session_id": "sess_test",
            "status": "error",
            "error": {"code": "invalid_tool_args", "message": "Bad args"},
            "duration_ms": 1,
            "created_at": "2026-04-25T00:00:00.000+00:00",
        }
        media_command = {
            "schema_version": "openvision.media_command.v1",
            "command_id": "media_test",
            "mode": "snapshot",
            "session_id": "sess_test",
            "skill_id": "scene_describe",
            "reason": "single visual question",
            "timeout_ms": 2000,
            "fps": None,
            "resolution": {"width": 1280, "height": 720},
            "auto_stop": True,
            "params": {},
            "created_at": "2026-04-25T00:00:00.000+00:00",
        }
        media_event = {
            "schema_version": "openvision.media_event.v1",
            "event_id": "media_evt_test",
            "command_id": "media_test",
            "mode": "snapshot",
            "session_id": "sess_test",
            "status": "ok",
            "payload": {"frame_ref": "frame_1"},
            "created_at": "2026-04-25T00:00:00.000+00:00",
        }
        display_command = {
            "schema_version": "openvision.display_command.v1",
            "command_id": "display_test",
            "kind": "text_hud",
            "session_id": "sess_test",
            "skill_id": "count_people",
            "payload": {"answer_strip": "2 người"},
            "priority": "normal",
            "ttl_ms": 2500,
            "created_at": "2026-04-25T00:00:00.000+00:00",
        }

        assert_required_fields(self, load_schema("realtime_tool_call.schema.json"), realtime_tool_call)
        assert_required_fields(self, load_schema("tool_result.schema.json"), tool_result)
        assert_required_fields(self, load_schema("tool_error.schema.json"), tool_error)
        assert_required_fields(self, load_schema("media_command.schema.json"), media_command)
        assert_required_fields(self, load_schema("media_event.schema.json"), media_event)
        assert_required_fields(self, load_schema("display_command.schema.json"), display_command)


if __name__ == "__main__":
    unittest.main()
