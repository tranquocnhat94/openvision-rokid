import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.hud_authority import HudAuthority


class HudAuthorityTest(unittest.TestCase):
    def test_skill_result_updates_answer_strip_scene(self):
        authority = HudAuthority(events=InMemoryEventStore())

        scene = authority.update_from_skill_result(
            {
                "session_id": "sess_test",
                "result": {"hud": {"answer_strip": "2 người", "edge_chips": ["count_people"]}},
            }
        )

        self.assertEqual(scene["answer_strip"], "2 người")
        self.assertEqual(scene["edge_chips"], ["count_people"])
        self.assertEqual(authority.latest("sess_test")["scene_id"], scene["scene_id"])

    def test_direct_answer_updates_hud_scene(self):
        authority = HudAuthority(events=InMemoryEventStore())

        scene = authority.update_answer(
            session_id="sess_test",
            answer_strip="Sẵn sàng",
            edge_chips=["realtime"],
        )

        self.assertEqual(scene["answer_strip"], "Sẵn sàng")
        self.assertEqual(scene["edge_chips"], ["realtime"])

    def test_skill_result_preserves_thumbnail_strip(self):
        authority = HudAuthority(events=InMemoryEventStore())

        scene = authority.update_from_skill_result(
            {
                "session_id": "sess_test",
                "result": {
                    "hud": {
                        "answer_strip": "2 ứng viên",
                        "thumbnails": [
                            {"target_id": "obj_1", "caption": "1. person p1"},
                            {"target_id": "obj_2", "caption": "2. person p2"},
                        ],
                    }
                },
            }
        )

        self.assertEqual(len(scene["thumbnails"]), 2)
        self.assertEqual(scene["thumbnails"][0]["target_id"], "obj_1")
