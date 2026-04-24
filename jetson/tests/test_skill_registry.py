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

        self.assertIn("count_people", names)
        count_people = next(item for item in definitions if item["name"] == "count_people")
        self.assertEqual(count_people["manifest_id"], "openvision.skill.count_people")
        self.assertEqual(count_people["latency_class"], "live")
        self.assertIn("đếm người", count_people["activation_phrases_vi"])

    def test_custom_manifest_directory_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = Path(tmp)
            (manifest_dir / "demo.json").write_text(
                json.dumps(
                    {
                        "id": "openvision.skill.demo",
                        "name": "demo_skill",
                        "description": "Demo skill.",
                        "input_schema": {"type": "object", "properties": {}, "required": []},
                        "result_schema": {"type": "object", "properties": {}, "required": []},
                        "local_resources": [],
                        "cloud_allowed": False,
                        "hud_policy": "answer_strip",
                    }
                ),
                encoding="utf-8",
            )

            registry = SkillRegistry(manifest_dir=manifest_dir)

        self.assertEqual(registry.get("demo_skill").manifest_id, "openvision.skill.demo")

    def test_empty_manifest_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                SkillRegistry(manifest_dir=Path(tmp))


if __name__ == "__main__":
    unittest.main()
