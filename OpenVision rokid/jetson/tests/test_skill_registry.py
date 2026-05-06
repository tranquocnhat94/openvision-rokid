import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.skill_registry import SkillRegistry


class SkillRegistryTest(unittest.TestCase):
    def test_default_registry_loads_manifests(self):
        registry = SkillRegistry()

        definitions = registry.list_definitions()
        names = {item["name"] for item in definitions}

        self.assertIn("scene_describe", names)
        self.assertIn("count_people", names)
        self.assertIn("object_counter", names)
        self.assertIn("text_reader", names)
        self.assertIn("target_finder", names)
        self.assertIn("person_info", names)
        self.assertIn("remember_person", names)
        count_people = next(item for item in definitions if item["name"] == "count_people")
        self.assertEqual(count_people["manifest_id"], "openvision.skill.count_people")
        self.assertEqual(count_people["tool_name"], "count_people")
        self.assertEqual(count_people["latency_class"], "live")
        self.assertEqual(count_people["cloud_behavior"], "local_only")
        self.assertEqual(count_people["media_requirements"]["default_mode"], "none")
        self.assertIn("text_hud", count_people["display_capabilities"])
        self.assertIn("đếm người", count_people["activation_phrases_vi"])

    def test_realtime_tool_descriptions_include_vietnamese_routing_hints(self):
        registry = SkillRegistry()

        tools = {item["name"]: item for item in registry.realtime_tools()}

        self.assertIn("Route by semantic intent", tools["scene_describe"]["description"])
        self.assertIn("not exact command text", tools["person_info"]["description"])
        self.assertIn("noisy ASR/paraphrases", tools["target_finder"]["description"])
        self.assertIn("đang có gì trước mặt tôi", tools["scene_describe"]["description"])
        self.assertIn("trước mặt tôi có gì", tools["scene_describe"]["description"])
        self.assertIn("tôi đang nhìn thấy gì", tools["scene_describe"]["description"])
        self.assertIn("nhìn hộ tôi xem có gì", tools["scene_describe"]["description"])
        self.assertIn("choose scene_describe", tools["scene_describe"]["description"])
        self.assertIn("specific visual follow-up", tools["query_scene"]["description"])
        self.assertIn("use text_reader", tools["query_scene"]["description"])
        self.assertIn("OCR/text-reading", tools["text_reader"]["description"])
        self.assertIn("biển này ghi gì", tools["text_reader"]["description"])
        self.assertIn("đọc giúp tôi dòng này", tools["text_reader"]["description"])
        self.assertIn("exact visible text", tools["text_reader"]["description"])
        self.assertIn("use scene_describe instead", tools["count_people"]["description"])
        self.assertIn("mấy người", tools["count_people"]["description"])
        self.assertIn("tìm Trâm", tools["count_people"]["description"])
        self.assertIn("use target_finder", tools["count_people"]["description"])
        self.assertIn("non-person objects", tools["object_counter"]["description"])
        self.assertIn("bao nhiêu hạt", tools["object_counter"]["description"])
        self.assertIn("đếm giúp tôi cái này", tools["object_counter"]["description"])
        self.assertIn("live target-finding", tools["target_finder"]["description"])
        self.assertIn("tìm Trâm", tools["target_finder"]["description"])
        self.assertIn('target_type="person"', tools["target_finder"]["description"])
        self.assertIn("include target_name", tools["target_finder"]["description"])
        self.assertIn("identity_query=true", tools["target_finder"]["description"])
        self.assertIn('Do not simplify "tìm Trâm"', tools["target_finder"]["description"])
        self.assertIn("nhắc tên Trâm", tools["target_finder"]["description"])
        self.assertIn("skill is not enabled", tools["target_finder"]["description"])
        self.assertIn("tìm người trong đám đông", tools["target_finder"]["description"])
        self.assertIn("local OpenVision contact identity DB", tools["target_finder"]["description"])
        self.assertIn("có ai quen không", tools["person_info"]["description"])
        self.assertIn("người này là ai", tools["person_info"]["description"])
        self.assertIn("đây là ai", tools["person_info"]["description"])
        self.assertIn("nhắc tên người này", tools["person_info"]["description"])
        self.assertIn("nhắc tên Trâm", tools["person_info"]["description"])
        self.assertIn('scan_mode="snapshot"', tools["person_info"]["description"])
        self.assertIn('scan_mode="name_reminder"', tools["person_info"]["description"])
        self.assertIn("People Registry", tools["person_info"]["description"])
        self.assertIn("use target_finder instead", tools["person_info"]["description"])
        self.assertIn("remember/save the visible person", tools["remember_person"]["description"])
        self.assertIn("ghi nhớ người này", tools["remember_person"]["description"])
        self.assertIn("uploads it to Immich", tools["remember_person"]["description"])

    def test_live_video_skill_tools_allow_rv101_30fps_budget(self):
        registry = SkillRegistry()

        tools = {item["name"]: item for item in registry.realtime_tools()}

        self.assertEqual(tools["target_finder"]["parameters"]["properties"]["fps"]["maximum"], 30)
        self.assertEqual(tools["person_info"]["parameters"]["properties"]["fps"]["maximum"], 30)

    def test_custom_manifest_directory_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = Path(tmp)
            (manifest_dir / "demo.json").write_text(
                json.dumps(
                    {
                        "id": "openvision.skill.demo",
                        "name": "demo_skill",
                        "description": "Demo skill.",
                        "tool_name": "demo_skill",
                        "input_schema": {"type": "object", "properties": {}, "required": []},
                        "result_schema": {"type": "object", "properties": {}, "required": []},
                        "latency_class": "interactive",
                        "local_first": True,
                        "local_resources": [],
                        "media_requirements": {
                            "default_mode": "none",
                            "allowed_modes": ["none"],
                            "requires_camera": False,
                            "requires_mic": False,
                            "live_video_allowed": False,
                        },
                        "display_capabilities": ["text_hud"],
                        "memory_allowed": False,
                        "cloud_allowed": False,
                        "cloud_behavior": "local_only",
                        "privacy_level": "low",
                        "hud_policy": "answer_strip",
                        "timeout_ms": 1000,
                        "activation_phrases_vi": ["demo"],
                        "acceptance_tests": ["loads manifest"],
                        "failure_modes": ["none"],
                    }
                ),
                encoding="utf-8",
            )

            registry = SkillRegistry(manifest_dir=manifest_dir)

        self.assertEqual(registry.get("demo_skill").manifest_id, "openvision.skill.demo")

    def test_manifest_schema_rejects_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _demo_manifest()
            manifest.pop("media_requirements")
            (Path(tmp) / "demo.json").write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manifest.media_requirements is required"):
                SkillRegistry(manifest_dir=Path(tmp))

    def test_manifest_schema_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _demo_manifest()
            manifest["legacy_endpoint"] = "/detect"
            (Path(tmp) / "demo.json").write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "manifest.legacy_endpoint is not allowed"):
                SkillRegistry(manifest_dir=Path(tmp))

    def test_manifest_policy_rejects_inconsistent_media_and_cloud_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _demo_manifest()
            manifest["media_requirements"]["default_mode"] = "snapshot"
            manifest["media_requirements"]["allowed_modes"] = ["none"]
            manifest["cloud_allowed"] = False
            manifest["cloud_behavior"] = "gateway_optional"
            (Path(tmp) / "demo.json").write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "default_mode must be present in allowed_modes"):
                SkillRegistry(manifest_dir=Path(tmp))

    def test_empty_manifest_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                SkillRegistry(manifest_dir=Path(tmp))


def _demo_manifest() -> dict[str, object]:
    return {
        "id": "openvision.skill.demo",
        "name": "demo_skill",
        "description": "Demo skill.",
        "tool_name": "demo_skill",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "result_schema": {"type": "object", "properties": {}, "required": []},
        "latency_class": "interactive",
        "local_first": True,
        "local_resources": [],
        "media_requirements": {
            "default_mode": "none",
            "allowed_modes": ["none"],
            "requires_camera": False,
            "requires_mic": False,
            "live_video_allowed": False,
        },
        "display_capabilities": ["text_hud"],
        "memory_allowed": False,
        "cloud_allowed": False,
        "cloud_behavior": "local_only",
        "privacy_level": "low",
        "hud_policy": "answer_strip",
        "timeout_ms": 1000,
        "activation_phrases_vi": ["demo"],
        "acceptance_tests": ["loads manifest"],
        "failure_modes": ["none"],
    }


if __name__ == "__main__":
    unittest.main()
