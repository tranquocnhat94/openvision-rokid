import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.hud_authority import HudAuthority, validate_hud_scene


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
        events = InMemoryEventStore()
        authority = HudAuthority(events=events)

        scene = authority.update_answer(
            session_id="sess_test",
            answer_strip="Sẵn sàng",
            edge_chips=["realtime"],
        )

        self.assertEqual(scene["answer_strip"], "Sẵn sàng")
        self.assertEqual(scene["edge_chips"], ["realtime"])
        self.assertEqual(validate_hud_scene(scene), [])
        self.assertTrue(events.list()[-1]["payload"]["schema_valid"])

    def test_duplicate_hud_scene_content_updates_latest_without_spamming_events(self):
        events = InMemoryEventStore()
        authority = HudAuthority(events=events)

        first = authority.update_answer(session_id="sess_test", answer_strip="Đang tìm", edge_chips=["target_finder"])
        second = authority.update_answer(session_id="sess_test", answer_strip="Đang tìm", edge_chips=["target_finder"])

        self.assertNotEqual(first["scene_id"], second["scene_id"])
        self.assertEqual(authority.latest("sess_test")["scene_id"], second["scene_id"])
        hud_events = [event for event in events.list(session_id="sess_test") if event["module"] == "hud"]
        self.assertEqual(len(hud_events), 1)

    def test_test_scene_updates_hud_for_debug_baseline(self):
        authority = HudAuthority(events=InMemoryEventStore())

        scene = authority.update_test_scene(session_id="sess_test")

        self.assertEqual(scene["answer_strip"], "HUD test OK")
        self.assertEqual(scene["edge_chips"], ["hud", "test"])
        self.assertEqual(validate_hud_scene(scene), [])
        self.assertEqual(authority.latest("sess_test")["scene_id"], scene["scene_id"])

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

    def test_realtime_text_preserves_latest_rich_scene_elements(self):
        authority = HudAuthority(events=InMemoryEventStore())
        authority.update_from_skill_result(
            {
                "session_id": "sess_test",
                "result": {
                    "hud": {
                        "answer_strip": "2 ứng viên",
                        "edge_chips": ["needs_cloud"],
                        "target_hint": {"target_id": "obj_1"},
                        "thumbnails": [{"target_id": "obj_1", "caption": "1. person"}],
                    }
                },
            }
        )

        scene = authority.update_realtime_text(
            session_id="sess_test",
            text="Cần xác minh thêm.",
            edge_chips=["realtime"],
        )

        self.assertEqual(scene["answer_strip"], "Cần xác minh thêm.")
        self.assertEqual(scene["thumbnails"][0]["target_id"], "obj_1")
        self.assertEqual(scene["target_hint"]["target_id"], "obj_1")
        self.assertEqual(scene["edge_chips"], ["needs_cloud", "realtime"])

    def test_validation_rejects_missing_required_fields(self):
        errors = validate_hud_scene({"session_id": "sess_test", "answer_strip": "bad"})

        self.assertTrue(any("missing required fields" in error for error in errors))
