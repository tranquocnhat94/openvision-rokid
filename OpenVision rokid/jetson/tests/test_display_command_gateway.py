import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from openvision_jetson.display_command_gateway import DisplayCommandGateway
from openvision_jetson.event_store import InMemoryEventStore
from openvision_jetson.hud_authority import HudAuthority, validate_hud_scene


class DisplayCommandGatewayTest(unittest.TestCase):
    def test_text_hud_updates_hud_scene_and_logs_scorecard_event(self):
        events = InMemoryEventStore()
        hud = HudAuthority(events=events)
        gateway = DisplayCommandGateway(
            events=events,
            hud=hud,
            session_validator=lambda session_id: session_id == "sess_test",
        )

        result = gateway.request_command(
            kind="text_hud",
            session_id="sess_test",
            payload={"text": "Ben trai co mot nguoi", "edge_chips": ["answer"]},
            skill_id="scene_describe",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["command"]["schema_version"], "openvision.display_command.v1")
        self.assertEqual(result["hud_scene"]["answer_strip"], "Ben trai co mot nguoi")
        self.assertEqual(result["hud_scene"]["edge_chips"], ["answer"])
        self.assertEqual(validate_hud_scene(result["hud_scene"]), [])
        self.assertEqual(hud.latest("sess_test")["scene_id"], result["hud_scene"]["scene_id"])
        trace = events.list(session_id="sess_test")
        self.assertEqual(trace[-1]["module"], "display_command")
        self.assertEqual(trace[-1]["event_type"], "command_completed")

    def test_object_card_maps_to_thumbnail_and_target_hint(self):
        gateway = DisplayCommandGateway(
            events=InMemoryEventStore(),
            hud=HudAuthority(events=InMemoryEventStore()),
            session_validator=lambda session_id: session_id == "sess_test",
        )

        result = gateway.request_command(
            kind="object_card",
            session_id="sess_test",
            payload={
                "target_id": "obj_person_1",
                "title": "Possible match",
                "subtitle": "yellow shirt",
                "thumbnail_uri": "session://sess_test/crops/person.jpg",
                "zone": "left_front",
            },
            priority="critical",
            ttl_ms=20000,
        )

        scene = result["hud_scene"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["command"]["priority"], "critical")
        self.assertEqual(result["command"]["ttl_ms"], 5000)
        self.assertEqual(scene["priority"], "urgent")
        self.assertEqual(scene["thumbnails"][0]["target_id"], "obj_person_1")
        self.assertEqual(scene["target_hint"]["target_id"], "obj_person_1")
        self.assertEqual(scene["target_hint"]["anchor"], "left_front")

    def test_clear_command_publishes_empty_hud_scene(self):
        hud = HudAuthority(events=InMemoryEventStore())
        gateway = DisplayCommandGateway(
            events=InMemoryEventStore(),
            hud=hud,
            session_validator=lambda session_id: session_id == "sess_test",
        )
        gateway.request_command(
            kind="text_hud",
            session_id="sess_test",
            payload={"text": "temporary"},
        )

        result = gateway.request_command(kind="clear", session_id="sess_test")

        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["hud_scene"]["answer_strip"])
        self.assertEqual(result["hud_scene"]["thumbnails"], [])
        self.assertIsNone(result["hud_scene"]["target_hint"])
        self.assertEqual(result["hud_scene"]["ttl_ms"], 0)

    def test_full_image_requires_image_uri(self):
        gateway = DisplayCommandGateway(
            events=InMemoryEventStore(),
            hud=HudAuthority(events=InMemoryEventStore()),
            session_validator=lambda session_id: session_id == "sess_test",
        )

        result = gateway.request_command(
            kind="full_image",
            session_id="sess_test",
            payload={"title": "Document"},
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "missing_display_payload_field")

    def test_debug_overlay_can_be_disabled_by_policy(self):
        events = InMemoryEventStore()
        gateway = DisplayCommandGateway(
            events=events,
            hud=HudAuthority(events=events),
            session_validator=lambda session_id: session_id == "sess_test",
            debug_overlay_allowed=False,
        )

        result = gateway.request_command(
            kind="debug_overlay",
            session_id="sess_test",
            payload={"fps": 24},
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "debug_overlay_disabled")
        self.assertEqual(events.list(session_id="sess_test")[-1]["event_type"], "command_failed")

    def test_unknown_session_is_rejected(self):
        gateway = DisplayCommandGateway(
            events=InMemoryEventStore(),
            hud=HudAuthority(events=InMemoryEventStore()),
            session_validator=lambda session_id: False,
        )

        result = gateway.request_command(
            kind="text_hud",
            session_id="sess_missing",
            payload={"text": "hello"},
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "unknown_session")


if __name__ == "__main__":
    unittest.main()
