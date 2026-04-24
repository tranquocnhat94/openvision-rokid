import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.contracts import HudScene, new_id, to_jsonable


class ContractsTest(unittest.TestCase):
    def test_ids_are_prefixed(self):
        self.assertTrue(new_id("hud").startswith("hud_"))

    def test_hud_scene_is_jsonable(self):
        scene = HudScene(
            scene_id="hud_test",
            answer_strip="100 người",
            edge_chips=["count_people"],
        )
        payload = to_jsonable(scene)

        self.assertEqual(payload["scene_id"], "hud_test")
        self.assertEqual(payload["answer_strip"], "100 người")
        self.assertEqual(payload["edge_chips"], ["count_people"])


if __name__ == "__main__":
    unittest.main()

